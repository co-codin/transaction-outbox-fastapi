from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app.core.config import settings
from app.messaging.topology import (
    WEBHOOKS_DEAD_EXCHANGE,
    WEBHOOKS_DLQ_ROUTING_KEY,
    WEBHOOKS_RETRY_QUEUES,
)
from app.schemas.messages import WebhookDeliveryEvent
from app.services.webhooks import build_webhook_payload, process_webhook_event, send_payment_webhook

PAYMENT_ID = UUID("a1163e5d-8f5e-432b-96dd-48ff68204948")


def _payment() -> SimpleNamespace:
    return SimpleNamespace(
        id=PAYMENT_ID,
        amount=Decimal("1500.00"),
        currency="RUB",
        description="Order smoke test",
        metadata_={"order_id": "smoke-1"},
        status="succeeded",
        webhook_url="https://example.com/webhook",
        webhook_sent_at=None,
        webhook_last_error=None,
        webhook_locked_until=None,
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
            raise httpx.HTTPStatusError(
                "webhook failed",
                request=self.request,
                response=self.response,
            )


class FakeAsyncClient:
    responses: list[int] = []
    posts: list[dict] = []

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    async def post(self, url: str, json: dict):
        self.posts.append({"url": url, "json": json, "timeout": self.timeout})
        return FakeResponse(self.responses.pop(0))


@pytest.mark.asyncio
async def test_send_payment_webhook_posts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAsyncClient.responses = [200]
    FakeAsyncClient.posts = []
    monkeypatch.setattr("app.services.webhooks.httpx.AsyncClient", FakeAsyncClient)

    await send_payment_webhook(_payment())

    assert len(FakeAsyncClient.posts) == 1
    assert FakeAsyncClient.posts[0]["url"] == "https://example.com/webhook"
    assert FakeAsyncClient.posts[0]["timeout"] == settings.webhook_timeout_seconds


@pytest.mark.asyncio
async def test_send_payment_webhook_raises_for_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.responses = [500]
    FakeAsyncClient.posts = []
    monkeypatch.setattr("app.services.webhooks.httpx.AsyncClient", FakeAsyncClient)

    with pytest.raises(httpx.HTTPStatusError):
        await send_payment_webhook(_payment())

    assert len(FakeAsyncClient.posts) == 1


class FakeTransaction:
    def __init__(self, session: "FakeWebhookSession") -> None:
        self._session = session

    async def __aenter__(self):
        self._session.in_transaction = True
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self._session.in_transaction = False


class FakeWebhookSession:
    instances: list["FakeWebhookSession"] = []

    def __init__(self, payment: SimpleNamespace) -> None:
        self._payment = payment
        self.get_calls: list[dict] = []
        self.in_transaction = False
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def get(self, model, pk, **kwargs):  # noqa: ARG002
        self.get_calls.append({"pk": pk, **kwargs})
        return self._payment if pk == self._payment.id else None


class RecordingBroker:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, message, **kwargs) -> None:
        self.published.append({"message": message, **kwargs})


def _install_session_factory(monkeypatch: pytest.MonkeyPatch, payment: SimpleNamespace) -> None:
    FakeWebhookSession.instances = []
    monkeypatch.setattr("app.services.webhooks.async_session_maker", lambda: FakeWebhookSession(payment))


@pytest.mark.asyncio
async def test_webhook_event_sends_outside_db_lock_and_marks_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment()
    broker = RecordingBroker()
    send_calls = 0
    _install_session_factory(monkeypatch, payment)

    async def fake_send_payment_webhook(payment):  # noqa: ARG001
        nonlocal send_calls
        send_calls += 1
        assert not any(session.in_transaction for session in FakeWebhookSession.instances)

    monkeypatch.setattr("app.services.webhooks.send_payment_webhook", fake_send_payment_webhook)

    await process_webhook_event(WebhookDeliveryEvent(payment_id=PAYMENT_ID), broker)

    assert send_calls == 1
    assert isinstance(payment.webhook_sent_at, datetime)
    assert payment.webhook_locked_until is None
    assert payment.webhook_last_error is None
    assert broker.published == []


@pytest.mark.asyncio
async def test_webhook_event_skips_already_sent_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment()
    payment.webhook_sent_at = datetime(2026, 6, 10, tzinfo=UTC)
    broker = RecordingBroker()
    send_calls = 0
    _install_session_factory(monkeypatch, payment)

    async def fake_send_payment_webhook(payment):  # noqa: ARG001
        nonlocal send_calls
        send_calls += 1

    monkeypatch.setattr("app.services.webhooks.send_payment_webhook", fake_send_payment_webhook)

    await process_webhook_event(WebhookDeliveryEvent(payment_id=PAYMENT_ID), broker)

    assert send_calls == 0
    assert broker.published == []


@pytest.mark.asyncio
async def test_webhook_event_skips_active_delivery_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment()
    payment.webhook_locked_until = datetime.now(UTC) + timedelta(seconds=30)
    broker = RecordingBroker()
    send_calls = 0
    _install_session_factory(monkeypatch, payment)

    async def fake_send_payment_webhook(payment):  # noqa: ARG001
        nonlocal send_calls
        send_calls += 1

    monkeypatch.setattr("app.services.webhooks.send_payment_webhook", fake_send_payment_webhook)

    await process_webhook_event(WebhookDeliveryEvent(payment_id=PAYMENT_ID), broker)

    assert send_calls == 0
    assert broker.published == []


@pytest.mark.asyncio
async def test_webhook_event_retries_failed_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment()
    broker = RecordingBroker()
    _install_session_factory(monkeypatch, payment)

    async def fake_send_payment_webhook(payment):  # noqa: ARG001
        raise RuntimeError("receiver down")

    monkeypatch.setattr("app.services.webhooks.send_payment_webhook", fake_send_payment_webhook)

    await process_webhook_event(WebhookDeliveryEvent(payment_id=PAYMENT_ID, attempt=1), broker)

    assert payment.webhook_sent_at is None
    assert payment.webhook_locked_until is None
    assert payment.webhook_last_error == "receiver down"
    assert broker.published == [
        {
            "message": {
                "payment_id": "a1163e5d-8f5e-432b-96dd-48ff68204948",
                "attempt": 2,
            },
            "queue": WEBHOOKS_RETRY_QUEUES[0],
            "persist": True,
            "headers": {"x-error": "receiver down", "x-attempt": "1"},
            "message_type": "webhook.retry",
        },
    ]


@pytest.mark.asyncio
async def test_webhook_event_dead_letters_after_three_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment()
    broker = RecordingBroker()
    _install_session_factory(monkeypatch, payment)

    async def fake_send_payment_webhook(payment):  # noqa: ARG001
        raise RuntimeError("receiver still down")

    monkeypatch.setattr("app.services.webhooks.send_payment_webhook", fake_send_payment_webhook)

    await process_webhook_event(WebhookDeliveryEvent(payment_id=PAYMENT_ID, attempt=3), broker)

    assert payment.webhook_sent_at is None
    assert payment.webhook_locked_until is None
    assert payment.webhook_last_error == "receiver still down"
    assert broker.published == [
        {
            "message": {
                "payment_id": "a1163e5d-8f5e-432b-96dd-48ff68204948",
                "attempt": 3,
            },
            "exchange": WEBHOOKS_DEAD_EXCHANGE,
            "routing_key": WEBHOOKS_DLQ_ROUTING_KEY,
            "persist": True,
            "headers": {"x-error": "receiver still down", "x-attempt": "3"},
            "message_type": "webhook.dead",
        },
    ]
