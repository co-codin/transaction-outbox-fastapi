import asyncio
import logging
import random
import uuid
from datetime import UTC, datetime

from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_maker
from app.messaging.topology import (
    PAYMENTS_DEAD_EXCHANGE,
    PAYMENTS_DLQ_ROUTING_KEY,
    PAYMENTS_RETRY_QUEUES,
)
from app.models.payment import Payment, PaymentStatus
from app.schemas.messages import PaymentEvent
from app.services.webhooks import send_payment_webhook

logger = logging.getLogger(__name__)
MAX_PROCESSING_ATTEMPTS = 3


async def process_payment_event(event: PaymentEvent, broker: RabbitBroker) -> None:
    try:
        async with async_session_maker() as session:
            payment = await _process_or_load_payment(session, event)
        await _send_webhook_once(payment.id)
    except Exception as exc:
        logger.warning(
            "Payment event %s failed on attempt %s: %s",
            event.payment_id,
            event.attempt,
            exc,
        )
        await _retry_or_dead_letter(event, broker, exc)


async def _process_or_load_payment(session: AsyncSession, event: PaymentEvent) -> Payment:
    # Lock the payment row so concurrent/duplicate deliveries of the same event
    # serialize: a second handler blocks here until the first commits, then re-reads
    # the now-terminal status below and skips reprocessing. The lock is held across
    # the simulated processing delay, but it is per-row and only contends with
    # duplicates of the *same* payment, not with other payments.
    payment = await session.get(Payment, event.payment_id, with_for_update=True)
    if payment is None:
        raise RuntimeError(f"Payment {event.payment_id} not found")

    if payment.status == PaymentStatus.PENDING:
        delay_low, delay_high = settings.payment_processing_delay_range
        await asyncio.sleep(random.uniform(delay_low, delay_high))
        payment.status = (
            PaymentStatus.SUCCEEDED
            if random.random() < settings.payment_success_rate
            else PaymentStatus.FAILED
        )
        payment.processed_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(payment)

    return payment


async def _send_webhook_once(payment_id: uuid.UUID) -> None:
    webhook_error: Exception | None = None

    async with async_session_maker() as session:
        async with session.begin():
            payment = await session.get(Payment, payment_id, with_for_update=True)
            if payment is None:
                raise RuntimeError(f"Payment {payment_id} not found")

            if payment.webhook_sent_at is not None:
                return

            try:
                await send_payment_webhook(payment)
            except Exception as exc:
                payment.webhook_last_error = str(exc)[:2000]
                webhook_error = exc
            else:
                payment.webhook_sent_at = datetime.now(UTC)
                payment.webhook_last_error = None

    if webhook_error is not None:
        raise RuntimeError(f"Webhook delivery failed for payment {payment_id}: {webhook_error}") from webhook_error


async def _retry_or_dead_letter(
    event: PaymentEvent,
    broker: RabbitBroker,
    exc: Exception,
) -> None:
    current_attempt = max(event.attempt, 1)
    headers = {
        "x-error": str(exc)[:500],
        "x-attempt": str(current_attempt),
    }

    if current_attempt < MAX_PROCESSING_ATTEMPTS:
        queue_index = current_attempt - 1
        next_event = PaymentEvent(payment_id=event.payment_id, attempt=current_attempt + 1)
        try:
            await broker.publish(
                next_event.model_dump(mode="json"),
                queue=PAYMENTS_RETRY_QUEUES[queue_index],
                persist=True,
                headers=headers,
                message_type="payment.retry",
            )
        except Exception:
            logger.exception(
                "Failed to schedule retry for payment %s; dead-lettering",
                event.payment_id,
            )
        else:
            return

    dead_event = PaymentEvent(payment_id=event.payment_id, attempt=current_attempt)
    await broker.publish(
        dead_event.model_dump(mode="json"),
        exchange=PAYMENTS_DEAD_EXCHANGE,
        routing_key=PAYMENTS_DLQ_ROUTING_KEY,
        persist=True,
        headers=headers,
        message_type="payment.dead",
    )
