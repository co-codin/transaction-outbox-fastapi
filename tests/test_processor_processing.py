from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.models.payment import PaymentStatus
from app.schemas.messages import PaymentEvent
from app.services.processor import _process_or_load_payment

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
    )


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


async def _noop_sleep(_seconds: float) -> None:
    return None
