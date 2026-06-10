from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from app.services.webhooks import build_webhook_payload


def test_build_webhook_payload_serializes_payment() -> None:
    payment = SimpleNamespace(
        id=UUID("a1163e5d-8f5e-432b-96dd-48ff68204948"),
        amount=Decimal("1500.00"),
        currency="RUB",
        description="Order smoke test",
        metadata_={"order_id": "smoke-1"},
        status="succeeded",
        created_at=datetime(2026, 6, 10, 14, 53, 49, tzinfo=UTC),
        processed_at=datetime(2026, 6, 10, 14, 53, 54, tzinfo=UTC),
    )

    assert build_webhook_payload(payment) == {
        "event": "payment.processed",
        "payment_id": "a1163e5d-8f5e-432b-96dd-48ff68204948",
        "status": "succeeded",
        "amount": "1500.00",
        "currency": "RUB",
        "description": "Order smoke test",
        "metadata": {"order_id": "smoke-1"},
        "created_at": "2026-06-10T14:53:49+00:00",
        "processed_at": "2026-06-10T14:53:54+00:00",
    }
