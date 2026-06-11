from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import grpc
import pytest
from google.protobuf.struct_pb2 import Struct

from app.core.config import settings
from app.grpc import payment_pb2
from app.grpc import server as grpc_server
from app.models.payment import Currency, PaymentStatus
from app.services.payments import IdempotencyKeyConflictError

pytestmark = pytest.mark.asyncio

PAYMENT_ID = UUID("a1163e5d-8f5e-432b-96dd-48ff68204948")
CREATED_AT = datetime(2026, 6, 10, 14, 53, 49, tzinfo=UTC)


class GrpcAbort(Exception):
    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        self.code = code
        self.details = details


class FakeContext:
    def __init__(self, metadata: tuple[tuple[str, str], ...]) -> None:
        self._metadata = metadata

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._metadata

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        raise GrpcAbort(code, details)


class FakeSessionFactory:
    session = object()

    def __call__(self) -> "FakeSessionFactory":
        return self

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def create_request(**overrides) -> payment_pb2.CreatePaymentRequest:
    metadata = Struct()
    metadata.update({"order_id": "smoke-1"})
    fields = {
        "amount": "1500.00",
        "currency": "RUB",
        "description": "Order smoke test",
        "metadata": metadata,
        "webhook_url": "https://example.com/webhook",
    }
    fields.update(overrides)
    return payment_pb2.CreatePaymentRequest(**fields)


def auth_context(idempotency_key: str = "grpc-smoke-1") -> FakeContext:
    return FakeContext(
        (
            ("x-api-key", settings.api_key),
            ("idempotency-key", idempotency_key),
        ),
    )


async def test_create_payment_returns_accepted_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {}

    async def fake_create_payment(session, payload, idempotency_key):
        observed["session"] = session
        observed["payload"] = payload
        observed["idempotency_key"] = idempotency_key
        return SimpleNamespace(
            id=PAYMENT_ID,
            status=PaymentStatus.PENDING,
            created_at=CREATED_AT,
        )

    session_factory = FakeSessionFactory()
    monkeypatch.setattr(grpc_server, "create_payment", fake_create_payment)

    response = await grpc_server.Payments(session_factory).CreatePayment(
        create_request(),
        auth_context("  grpc-smoke-1  "),
    )

    assert response.payment_id == str(PAYMENT_ID)
    assert response.status == PaymentStatus.PENDING.value
    assert response.created_at == "2026-06-10T14:53:49Z"
    assert observed["session"] is session_factory.session
    assert observed["idempotency_key"] == "grpc-smoke-1"
    assert observed["payload"].amount == Decimal("1500.00")
    assert observed["payload"].currency == Currency.RUB
    assert observed["payload"].metadata == {"order_id": "smoke-1"}


async def test_create_payment_requires_api_key() -> None:
    with pytest.raises(GrpcAbort) as exc_info:
        await grpc_server.Payments(FakeSessionFactory()).CreatePayment(
            create_request(),
            FakeContext((("idempotency-key", "grpc-smoke-1"),)),
        )

    assert exc_info.value.code == grpc.StatusCode.UNAUTHENTICATED
    assert exc_info.value.details == "Invalid or missing API key"


async def test_create_payment_requires_idempotency_key() -> None:
    with pytest.raises(GrpcAbort) as exc_info:
        await grpc_server.Payments(FakeSessionFactory()).CreatePayment(
            create_request(),
            FakeContext((("x-api-key", settings.api_key),)),
        )

    assert exc_info.value.code == grpc.StatusCode.INVALID_ARGUMENT
    assert exc_info.value.details == "Idempotency-Key header is required"


async def test_create_payment_rejects_invalid_payload() -> None:
    with pytest.raises(GrpcAbort) as exc_info:
        await grpc_server.Payments(FakeSessionFactory()).CreatePayment(
            create_request(amount="-1.00"),
            auth_context(),
        )

    assert exc_info.value.code == grpc.StatusCode.INVALID_ARGUMENT
    assert "amount: Input should be greater than 0" in exc_info.value.details


async def test_create_payment_conflicting_idempotency_key_returns_already_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def conflicting_create_payment(session, payload, idempotency_key):
        raise IdempotencyKeyConflictError(idempotency_key)

    monkeypatch.setattr(grpc_server, "create_payment", conflicting_create_payment)

    with pytest.raises(GrpcAbort) as exc_info:
        await grpc_server.Payments(FakeSessionFactory()).CreatePayment(
            create_request(),
            auth_context(),
        )

    assert exc_info.value.code == grpc.StatusCode.ALREADY_EXISTS
    assert exc_info.value.details == (
        "Idempotency-Key already used with a different request body"
    )
