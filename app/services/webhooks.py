import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from faststream.rabbit import RabbitBroker

from app.core.config import settings
from app.db.session import async_session_maker
from app.messaging.topology import (
    WEBHOOKS_DEAD_EXCHANGE,
    WEBHOOKS_DLQ_ROUTING_KEY,
    WEBHOOKS_RETRY_QUEUES,
)
from app.models.payment import Payment
from app.schemas.messages import WebhookDeliveryEvent, WebhookPayload

logger = logging.getLogger(__name__)
MAX_WEBHOOK_ATTEMPTS = 3
WEBHOOK_DELIVERY_LEASE_SECONDS = 60


def build_webhook_payload(payment: Payment) -> dict[str, Any]:
    return WebhookPayload.model_validate(payment).model_dump(mode="json")


async def send_payment_webhook(payment: Payment) -> None:
    payload = build_webhook_payload(payment)

    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        response = await client.post(payment.webhook_url, json=payload)
        response.raise_for_status()


async def process_webhook_event(event: WebhookDeliveryEvent, broker: RabbitBroker) -> None:
    try:
        payment = await _claim_webhook_delivery(event.payment_id)
        if payment is None:
            return

        try:
            await send_payment_webhook(payment)
        except Exception as exc:
            await _mark_webhook_failed(event.payment_id, exc)
            await _retry_or_dead_letter_webhook(event, broker, exc)
            return

        await _mark_webhook_sent(event.payment_id)
    except Exception as exc:
        logger.warning(
            "Webhook event %s failed on attempt %s: %s",
            event.payment_id,
            event.attempt,
            exc,
        )
        await _retry_or_dead_letter_webhook(event, broker, exc)


async def _claim_webhook_delivery(payment_id: uuid.UUID) -> Payment | None:
    now = datetime.now(UTC)
    locked_until = now + timedelta(seconds=WEBHOOK_DELIVERY_LEASE_SECONDS)

    async with async_session_maker() as session:
        async with session.begin():
            payment = await session.get(Payment, payment_id, with_for_update=True)
            if payment is None:
                raise RuntimeError(f"Payment {payment_id} not found")
            if payment.webhook_sent_at is not None:
                return None
            if payment.webhook_locked_until is not None and payment.webhook_locked_until > now:
                logger.info("Webhook delivery for payment %s is already claimed", payment_id)
                return None

            payment.webhook_locked_until = locked_until
            return payment


async def _mark_webhook_sent(payment_id: uuid.UUID) -> None:
    async with async_session_maker() as session:
        async with session.begin():
            payment = await session.get(Payment, payment_id, with_for_update=True)
            if payment is None:
                raise RuntimeError(f"Payment {payment_id} not found")
            payment.webhook_sent_at = datetime.now(UTC)
            payment.webhook_last_error = None
            payment.webhook_locked_until = None


async def _mark_webhook_failed(payment_id: uuid.UUID, exc: Exception) -> None:
    async with async_session_maker() as session:
        async with session.begin():
            payment = await session.get(Payment, payment_id, with_for_update=True)
            if payment is None:
                raise RuntimeError(f"Payment {payment_id} not found")
            payment.webhook_last_error = str(exc)[:2000]
            payment.webhook_locked_until = None


async def _retry_or_dead_letter_webhook(
    event: WebhookDeliveryEvent,
    broker: RabbitBroker,
    exc: Exception,
) -> None:
    current_attempt = max(event.attempt, 1)
    headers = {
        "x-error": str(exc)[:500],
        "x-attempt": str(current_attempt),
    }

    if current_attempt < MAX_WEBHOOK_ATTEMPTS:
        retry_event = WebhookDeliveryEvent(
            payment_id=event.payment_id,
            attempt=current_attempt + 1,
        )
        try:
            await broker.publish(
                retry_event.model_dump(mode="json"),
                queue=WEBHOOKS_RETRY_QUEUES[current_attempt - 1],
                persist=True,
                headers=headers,
                message_type="webhook.retry",
            )
        except Exception:
            logger.exception(
                "Failed to schedule webhook retry for payment %s; dead-lettering",
                event.payment_id,
            )
        else:
            return

    dead_event = WebhookDeliveryEvent(payment_id=event.payment_id, attempt=current_attempt)
    await broker.publish(
        dead_event.model_dump(mode="json"),
        exchange=WEBHOOKS_DEAD_EXCHANGE,
        routing_key=WEBHOOKS_DLQ_ROUTING_KEY,
        persist=True,
        headers=headers,
        message_type="webhook.dead",
    )
