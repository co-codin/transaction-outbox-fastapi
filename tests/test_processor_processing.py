from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.models.payment import PaymentStatus
from app.schemas.messages import PaymentEvent
from app.services.processor import _process_or_load_payment, _send_webhook_once

PAYMENT_ID = UUID("a1163e5d-8f5e-432b-96dd-48ff68204948")


class FakeSession:
    def __init__(self, payment: SimpleNamespace) -> None:
        self._payment = payment
        self.get_calls: list[dict] = []
        self.commits = 0

    async def get(self, model, pk, **kwargs):
        self.get_calls.append({"pk": pk, **kwargs})
        return self._payment if pk == self._payment.id else None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:  # noqa: ARG002
        pass


def _payment(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=PAYMENT_ID,
        amount=Decimal("10.00"),
        status=status,
        processed_at=None,
        webhook_sent_at=None,
        webhook_last_error=None,
    )


async def _noop_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_pending_payment_is_locked_and_processed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Make processing deterministic and instant.
    monkeypatch.setattr("app.services.processor.asyncio.sleep", _noop_sleep)
    monkeypatch.setattr("app.services.processor.random.uniform", lambda a, b: 0.0)
    monkeypatch.setattr("app.services.processor.random.random", lambda: 0.0)  # < success_rate

    payment = _payment(PaymentStatus.PENDING.value)
    session = FakeSession(payment)

    result = await _process_or_load_payment(session, PaymentEvent(payment_id=PAYMENT_ID))

    # The row must be loaded under a FOR UPDATE lock (M1 regression guard).
    assert session.get_calls == [{"pk": PAYMENT_ID, "with_for_update": True}]
    assert result.status == PaymentStatus.SUCCEEDED.value
    assert isinstance(result.processed_at, datetime)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_already_terminal_payment_is_not_reprocessed() -> None:
    payment = _payment(PaymentStatus.SUCCEEDED.value)
    payment.processed_at = datetime(2026, 6, 10, tzinfo=UTC)
    session = FakeSession(payment)

    result = await _process_or_load_payment(session, PaymentEvent(payment_id=PAYMENT_ID))

    # Still locked, but no second processing / commit happens.
    assert session.get_calls == [{"pk": PAYMENT_ID, "with_for_update": True}]
    assert result.status == PaymentStatus.SUCCEEDED.value
    assert session.commits == 0


class FakeWebhookSession:
    def __init__(self, payment: SimpleNamespace) -> None:
        self._payment = payment
        self.get_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def begin(self):
        return self

    async def get(self, model, pk, **kwargs):
        self.get_calls.append({"pk": pk, **kwargs})
        return self._payment if pk == self._payment.id else None


@pytest.mark.asyncio
async def test_webhook_delivery_is_skipped_when_already_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment(PaymentStatus.SUCCEEDED.value)
    payment.webhook_sent_at = datetime(2026, 6, 10, tzinfo=UTC)
    session = FakeWebhookSession(payment)
    calls = 0

    async def fake_send_payment_webhook(payment):  # noqa: ARG001
        nonlocal calls
        calls += 1

    monkeypatch.setattr("app.services.processor.async_session_maker", lambda: session)
    monkeypatch.setattr("app.services.processor.send_payment_webhook", fake_send_payment_webhook)

    await _send_webhook_once(PAYMENT_ID)

    assert session.get_calls == [{"pk": PAYMENT_ID, "with_for_update": True}]
    assert calls == 0


@pytest.mark.asyncio
async def test_webhook_delivery_success_records_sent_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment(PaymentStatus.SUCCEEDED.value)
    payment.webhook_last_error = "previous failure"
    session = FakeWebhookSession(payment)

    async def fake_send_payment_webhook(payment):  # noqa: ARG001
        return None

    monkeypatch.setattr("app.services.processor.async_session_maker", lambda: session)
    monkeypatch.setattr("app.services.processor.send_payment_webhook", fake_send_payment_webhook)

    await _send_webhook_once(PAYMENT_ID)

    assert isinstance(payment.webhook_sent_at, datetime)
    assert payment.webhook_last_error is None


@pytest.mark.asyncio
async def test_webhook_delivery_failure_records_error_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment(PaymentStatus.SUCCEEDED.value)
    session = FakeWebhookSession(payment)

    async def fake_send_payment_webhook(payment):  # noqa: ARG001
        raise RuntimeError("receiver down")

    monkeypatch.setattr("app.services.processor.async_session_maker", lambda: session)
    monkeypatch.setattr("app.services.processor.send_payment_webhook", fake_send_payment_webhook)

    with pytest.raises(RuntimeError, match="Webhook delivery failed"):
        await _send_webhook_once(PAYMENT_ID)

    assert payment.webhook_sent_at is None
    assert payment.webhook_last_error == "receiver down"
