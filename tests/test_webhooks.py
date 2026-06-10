from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app.core.config import settings
from app.services.webhooks import build_webhook_payload
from app.services.webhooks import send_payment_webhook


def _payment() -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID("a1163e5d-8f5e-432b-96dd-48ff68204948"),
        amount=Decimal("1500.00"),
        currency="RUB",
        description="Order smoke test",
        metadata_={"order_id": "smoke-1"},
        status="succeeded",
        webhook_url="https://example.com/webhook",
        created_at=datetime(2026, 6, 10, 14, 53, 49, tzinfo=UTC),
        processed_at=datetime(2026, 6, 10, 14, 53, 54, tzinfo=UTC),
    )


def test_build_webhook_payload_serializes_payment() -> None:
    payment = _payment()

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


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.request = httpx.Request("POST", "https://example.com/webhook")
        self.response = httpx.Response(status_code, request=self.request)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("webhook failed", request=self.request, response=self.response)


class FakeAsyncClient:
    responses: list[int] = []
    posts: list[dict] = []

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, json: dict):
        self.posts.append({"url": url, "json": json, "timeout": self.timeout})
        return FakeResponse(self.responses.pop(0))


async def _record_sleep(seconds: float) -> None:
    _record_sleep.calls.append(seconds)


_record_sleep.calls = []


@pytest.mark.asyncio
async def test_send_payment_webhook_retries_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAsyncClient.responses = [500, 200]
    FakeAsyncClient.posts = []
    _record_sleep.calls = []
    monkeypatch.setattr("app.services.webhooks.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("app.services.webhooks.asyncio.sleep", _record_sleep)

    await send_payment_webhook(_payment())

    assert len(FakeAsyncClient.posts) == 2
    assert FakeAsyncClient.posts[0]["timeout"] == settings.webhook_timeout_seconds
    assert _record_sleep.calls == [1]


@pytest.mark.asyncio
async def test_send_payment_webhook_raises_after_configured_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.responses = [500, 500, 500]
    FakeAsyncClient.posts = []
    _record_sleep.calls = []
    monkeypatch.setattr("app.services.webhooks.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("app.services.webhooks.asyncio.sleep", _record_sleep)

    with pytest.raises(RuntimeError, match="Webhook delivery failed"):
        await send_payment_webhook(_payment())

    assert len(FakeAsyncClient.posts) == settings.webhook_retry_attempts
    assert _record_sleep.calls == [1, 2]
