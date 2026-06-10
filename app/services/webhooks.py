import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.models.payment import Payment
from app.schemas.messages import WebhookPayload


def build_webhook_payload(payment: Payment) -> dict[str, Any]:
    return WebhookPayload.model_validate(payment).model_dump(mode="json")


async def send_payment_webhook(payment: Payment) -> None:
    payload = build_webhook_payload(payment)
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        for attempt in range(settings.webhook_retry_attempts):
            try:
                response = await client.post(payment.webhook_url, json=payload)
                response.raise_for_status()
                return
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt + 1 >= settings.webhook_retry_attempts:
                    break
                await asyncio.sleep(2**attempt)

    raise RuntimeError(f"Webhook delivery failed: {last_error}") from last_error
