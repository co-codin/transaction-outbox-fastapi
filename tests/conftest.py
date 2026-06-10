from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import routes
from app.api.routes import router
from app.core.config import settings
from app.db.session import get_session
from app.models.payment import PaymentStatus


PAYMENT_ID = UUID("a1163e5d-8f5e-432b-96dd-48ff68204948")
CREATED_AT = datetime(2026, 6, 10, 14, 53, 49, tzinfo=UTC)


@pytest.fixture
def payment() -> SimpleNamespace:
    return SimpleNamespace(
        id=PAYMENT_ID,
        amount=Decimal("1500.00"),
        currency="RUB",
        description="Order smoke test",
        metadata_={"order_id": "smoke-1"},
        status=PaymentStatus.PENDING.value,
        idempotency_key="smoke-1",
        webhook_url="https://example.com/webhook",
        created_at=CREATED_AT,
        processed_at=None,
    )


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch, payment: SimpleNamespace) -> AsyncIterator[AsyncClient]:
    async def fake_session():
        yield object()

    async def fake_create_payment(session, payload, idempotency_key):
        payment.idempotency_key = idempotency_key
        payment.amount = payload.amount
        payment.currency = payload.currency.value
        payment.description = payload.description
        payment.metadata_ = payload.metadata
        payment.webhook_url = str(payload.webhook_url)
        return payment

    async def fake_get_payment(session, payment_id):
        if payment_id == payment.id:
            return payment
        return None

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_session] = fake_session
    monkeypatch.setattr(routes, "create_payment", fake_create_payment)
    monkeypatch.setattr(routes, "get_payment", fake_get_payment)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": settings.api_key}
