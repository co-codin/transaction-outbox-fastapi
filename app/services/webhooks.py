from typing import Any

import httpx

from app.core.config import settings
from app.models.payment import Payment
from app.schemas.messages import WebhookPayload


def build_webhook_payload(payment: Payment) -> dict[str, Any]:
    return WebhookPayload.model_validate(payment).model_dump(mode="json")


async def send_payment_webhook(payment: Payment) -> None:
    payload = build_webhook_payload(payment)

    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        response = await client.post(payment.webhook_url, json=payload)
        response.raise_for_status()
