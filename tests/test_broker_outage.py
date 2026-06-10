import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E_BROKER_OUTAGE"),
    reason="stops and restarts Docker Compose services; enable with E2E_BROKER_OUTAGE=1",
)

ROOT = Path(__file__).resolve().parents[1]
API_URL = os.environ.get("E2E_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("E2E_API_KEY", "dev-api-key")
WEBHOOK_PORT = int(os.environ.get("E2E_BROKER_WEBHOOK_PORT", "9800"))
PROCESSING_TIMEOUT_SECONDS = 90


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


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def _query_db(sql: str) -> str:
    result = _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "payments",
        "-d",
        "payments",
        "-tAc",
        sql,
    )
    return result.stdout.strip()


def _wait_for_api() -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{API_URL}/health", timeout=2)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError("API did not become healthy")


def _wait_for_rabbitmq() -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "rabbitmq", "rabbitmq-diagnostics", "-q", "ping"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise AssertionError("RabbitMQ did not become healthy")


def test_outbox_recovers_payment_created_during_broker_outage(
    webhook_receiver: list[dict],
) -> None:
    _wait_for_api()
    _compose("stop", "consumer", "rabbitmq")

    payment_id = None
    try:
        idempotency_key = f"outage-{uuid.uuid4()}"
        body = {
            "amount": "77.00",
            "currency": "USD",
            "description": "broker outage recovery payment",
            "metadata": {"suite": "broker-outage"},
            "webhook_url": f"http://host.docker.internal:{WEBHOOK_PORT}/webhook",
        }
        headers = {"X-API-Key": API_KEY, "Idempotency-Key": idempotency_key}

        created = httpx.post(f"{API_URL}/api/v1/payments", json=body, headers=headers, timeout=10)
        assert created.status_code == 202
        payment_id = created.json()["payment_id"]

        status = _query_db(
            "select status from outbox "
            f"where aggregate_id = '{payment_id}' and event_type = 'payments.new' "
            "order by created_at desc limit 1",
        )
        assert status == "pending"
    finally:
        _compose("up", "-d", "rabbitmq")
        _wait_for_rabbitmq()
        _compose("restart", "api")
        _wait_for_api()
        _compose("up", "-d", "consumer")

    assert payment_id is not None

    status = "pending"
    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        detail = httpx.get(
            f"{API_URL}/api/v1/payments/{payment_id}",
            headers={"X-API-Key": API_KEY},
            timeout=5,
        )
        assert detail.status_code == 200
        status = detail.json()["status"]
        if status != "pending":
            break
        time.sleep(1)
    assert status in {"succeeded", "failed"}

    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while time.monotonic() < deadline and not webhook_receiver:
        time.sleep(0.5)
    assert webhook_receiver, "webhook was never delivered after RabbitMQ recovery"

    outbox_status = _query_db(
        "select status from outbox "
        f"where aggregate_id = '{payment_id}' and event_type = 'payments.new' "
        "order by created_at desc limit 1",
    )
    assert outbox_status == "published"
