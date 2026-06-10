import asyncio
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.models.payment import Payment


def _json_decimal(value: Decimal) -> str:
    return format(value, "f")


def build_webhook_payload(payment: Payment) -> dict[str, Any]:
    return {
        "event": "payment.processed",
        "payment_id": str(payment.id),
        "status": payment.status,
        "amount": _json_decimal(payment.amount),
        "currency": payment.currency,
        "description": payment.description,
        "metadata": payment.metadata_,
        "created_at": payment.created_at.isoformat(),
        "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
    }


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
