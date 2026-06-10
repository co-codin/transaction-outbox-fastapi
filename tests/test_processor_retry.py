from uuid import UUID

import pytest

from app.messaging.topology import (
    PAYMENTS_DEAD_EXCHANGE,
    PAYMENTS_DLQ_ROUTING_KEY,
    PAYMENTS_RETRY_QUEUES,
)
from app.schemas.messages import PaymentEvent
from app.services.processor import _retry_or_dead_letter


class FakeBroker:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, message, **kwargs) -> None:
        self.published.append({"message": message, **kwargs})


@pytest.mark.asyncio
async def test_retry_or_dead_letter_publishes_to_next_retry_queue() -> None:
    broker = FakeBroker()
    event = PaymentEvent(
        payment_id=UUID("a1163e5d-8f5e-432b-96dd-48ff68204948"),
        attempt=1,
    )

    await _retry_or_dead_letter(event, broker, RuntimeError("webhook failed"))

    assert broker.published == [
        {
            "message": {
                "payment_id": "a1163e5d-8f5e-432b-96dd-48ff68204948",
                "attempt": 2,
            },
            "queue": PAYMENTS_RETRY_QUEUES[0],
            "persist": True,
            "headers": {"x-error": "webhook failed", "x-attempt": "1"},
            "message_type": "payment.retry",
        },
    ]


@pytest.mark.asyncio
async def test_retry_or_dead_letter_publishes_second_retry_before_final_attempt() -> None:
    broker = FakeBroker()
    event = PaymentEvent(
        payment_id=UUID("a1163e5d-8f5e-432b-96dd-48ff68204948"),
        attempt=2,
    )

    await _retry_or_dead_letter(event, broker, RuntimeError("webhook failed again"))

    assert broker.published == [
        {
            "message": {
                "payment_id": "a1163e5d-8f5e-432b-96dd-48ff68204948",
                "attempt": 3,
            },
            "queue": PAYMENTS_RETRY_QUEUES[1],
            "persist": True,
            "headers": {"x-error": "webhook failed again", "x-attempt": "2"},
            "message_type": "payment.retry",
        },
    ]


@pytest.mark.asyncio
async def test_retry_or_dead_letter_publishes_to_dlq_after_three_attempts() -> None:
    broker = FakeBroker()
    event = PaymentEvent(
        payment_id=UUID("a1163e5d-8f5e-432b-96dd-48ff68204948"),
        attempt=3,
    )

    await _retry_or_dead_letter(event, broker, RuntimeError("still failing"))

    assert broker.published == [
        {
            "message": {
                "payment_id": "a1163e5d-8f5e-432b-96dd-48ff68204948",
                "attempt": 3,
            },
            "exchange": PAYMENTS_DEAD_EXCHANGE,
            "routing_key": PAYMENTS_DLQ_ROUTING_KEY,
            "persist": True,
            "headers": {"x-error": "still failing", "x-attempt": "3"},
            "message_type": "payment.dead",
        },
    ]
