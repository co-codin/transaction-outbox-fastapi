import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E"),
    reason="requires the running docker compose stack; enable with E2E=1",
)

API_URL = os.environ.get("E2E_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("E2E_API_KEY", "dev-api-key")
WEBHOOK_PORT = int(os.environ.get("E2E_WEBHOOK_PORT", "9700"))
PROCESSING_TIMEOUT_SECONDS = 60


class _WebhookHandler(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        type(self).received.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def webhook_receiver() -> Iterator[list[dict]]:
    _WebhookHandler.received = []
    server = ThreadingHTTPServer(("0.0.0.0", WEBHOOK_PORT), _WebhookHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield _WebhookHandler.received
    server.shutdown()
    thread.join(timeout=5)


def test_payment_lifecycle(webhook_receiver: list[dict]) -> None:
    idempotency_key = f"e2e-{uuid.uuid4()}"
    body = {
        "amount": "42.00",
        "currency": "USD",
        "description": "e2e lifecycle payment",
        "metadata": {"suite": "e2e"},
        "webhook_url": f"http://host.docker.internal:{WEBHOOK_PORT}/webhook",
    }
    headers = {"X-API-Key": API_KEY, "Idempotency-Key": idempotency_key}

    created = httpx.post(f"{API_URL}/api/v1/payments", json=body, headers=headers)
    assert created.status_code == 202
    payment_id = created.json()["payment_id"]
    assert created.json()["status"] == "pending"

    replay = httpx.post(f"{API_URL}/api/v1/payments", json=body, headers=headers)
    assert replay.status_code == 202
    assert replay.json()["payment_id"] == payment_id

    conflict = httpx.post(
        f"{API_URL}/api/v1/payments",
        json={**body, "amount": "43.00"},
        headers=headers,
    )
    assert conflict.status_code == 409

    unauthorized = httpx.get(f"{API_URL}/api/v1/payments/{payment_id}")
    assert unauthorized.status_code == 401

    status = "pending"
    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        detail = httpx.get(
            f"{API_URL}/api/v1/payments/{payment_id}",
            headers={"X-API-Key": API_KEY},
        )
        assert detail.status_code == 200
        status = detail.json()["status"]
        if status != "pending":
            break
        time.sleep(1)
    assert status in {"succeeded", "failed"}
    assert detail.json()["processed_at"] is not None

    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while time.monotonic() < deadline and not webhook_receiver:
        time.sleep(0.5)
    assert webhook_receiver, "webhook was never delivered"
    webhook = webhook_receiver[0]
    assert webhook["event"] == "payment.processed"
    assert webhook["payment_id"] == payment_id
    assert webhook["status"] == status
    assert webhook["amount"] == "42.00"
