# Async Payment Processor

A FastAPI microservice that processes payments asynchronously. It accepts a
payment request, persists it together with an outbox event in a single
transaction, publishes the event to RabbitMQ, processes it in a background
consumer (FastStream), and notifies the client of the final status via webhook.

It is built around the **transactional outbox** pattern for guaranteed event
publication, with idempotent intake, TTL-based retries, and a dead-letter queue.

## Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quick Start (Docker)](#quick-start-docker)
- [API Reference](#api-reference)
- [Usage Examples](#usage-examples)
- [Local Development](#local-development)
- [Configuration](#configuration)
- [Delivery Guarantees](#delivery-guarantees)

## Architecture

```
client ──POST /payments──▶  API  ──┐  (one DB transaction)
                                   ├─▶ payments table  (status=pending)
                                   └─▶ outbox  table   (status=pending)
                                            │
                       outbox publisher ────┘  polls pending rows,
                       (in API process)        SELECT … FOR UPDATE SKIP LOCKED
                                            │
                                            ▼
                              RabbitMQ  payments exchange
                                            │ routing key: payments.new
                                            ▼
                                    [ payments.new ] ──▶ consumer
                                            ▲                │
                       dead-letter (TTL)    │                │ 1. lock payment row
              [ payments.retry.1 (2s) ] ────┤                │ 2. emulate gateway (2–5s, 90% ok)
              [ payments.retry.2 (4s) ] ────┘                │ 3. update status + processed_at
                                            │                │ 4. POST webhook (once, guarded
                                            │                │    by webhook_sent_at)
                                            ┌────────────────┤
                                            ▼  after 3 attempts
                                    [ payments.dlq ]
```

**Flow:**

1. The API validates the request, then inserts the `payment` and an `outbox`
   event in the **same transaction**, and returns `202 Accepted`.
2. An outbox publisher loop running inside the API process claims pending outbox
   rows (`FOR UPDATE SKIP LOCKED`) and publishes them to the `payments` exchange.
3. A single consumer reads `payments.new` and does everything: it locks the
   payment row, emulates the gateway (2–5 s; 90% `succeeded` / 10% `failed`),
   persists the result, then sends the webhook and records `webhook_sent_at` or
   `webhook_last_error`.
4. If any step fails — processing or webhook delivery — the event is routed
   through TTL retry queues (2 s, then 4 s) that dead-letter back to
   `payments.new`. Already-completed steps are skipped on redelivery: a terminal
   status skips reprocessing, and `webhook_sent_at` skips resending.
5. After 3 total attempts the event lands in `payments.dlq` for manual
   inspection.

## Tech Stack

FastAPI · gRPC · Pydantic v2 · SQLAlchemy 2.0 (async) · PostgreSQL · RabbitMQ
via FastStream · Alembic · Docker Compose.

## Quick Start (Docker)

```bash
cp .env.example .env
API_KEY=dev-api-key docker compose up --build
```

The API container runs Alembic migrations before Uvicorn starts. The consumer
waits for the API healthcheck, so the two services never race on the migration
table.

| Service                | URL / Address                               |
| ---------------------- | ------------------------------------------- |
| API                    | http://localhost:8000                       |
| gRPC                   | localhost:50051                             |
| RabbitMQ management UI | http://localhost:15672 (`guest` / `guest`)  |
| PostgreSQL             | `localhost:5433` (override `POSTGRES_PORT`) |

## API Reference

All endpoints require the `X-API-Key` header.

| Method | Path                    | Required headers               | Success        |
| ------ | ----------------------- | ------------------------------ | -------------- |
| `POST` | `/api/v1/payments`      | `X-API-Key`, `Idempotency-Key` | `202 Accepted` |
| `GET`  | `/api/v1/payments/{id}` | `X-API-Key`                    | `200 OK`       |

The generated OpenAPI schema is committed at `openapi.json`. Regenerate it
after API/schema changes with:

```bash
PYTHONPATH=. python -c "import json; from pathlib import Path; from app.main import app; Path('openapi.json').write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + '\n')"
```

**Request body** (`POST /api/v1/payments`):

| Field         | Type           | Notes                                |
| ------------- | -------------- | ------------------------------------ |
| `amount`      | decimal string | `> 0`, up to 2 decimal places        |
| `currency`    | string         | `RUB`, `USD`, or `EUR`               |
| `description` | string         | 1–1000 chars                         |
| `metadata`    | object         | optional, arbitrary JSON             |
| `webhook_url` | URL            | called with the final payment status |

The `Idempotency-Key` header is required, trimmed of surrounding whitespace, and
limited to 255 characters. Replaying the same key returns the original payment
instead of creating a duplicate.

### gRPC

The gRPC service exposes the same create-payment workflow as
`POST /api/v1/payments`:

| Service method       | Metadata                          | Success |
| -------------------- | --------------------------------- | ------- |
| `grpc.payments/POST` | `x-api-key`, `idempotency-key`    | accepted response |

The protobuf contract lives at `app/grpc/payment.proto`. Request fields mirror
the HTTP POST body: `amount`, `currency`, `description`, `metadata`, and
`webhook_url`. The response contains `payment_id`, `status`, and `created_at`.
Conflicting idempotency keys are returned as gRPC `ALREADY_EXISTS`.

## Usage Examples

Optionally run a local webhook receiver in another terminal to inspect callbacks:

```bash
python -m http.server 9000
```

Create a payment:

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key" \
  -H "Idempotency-Key: order-1001" \
  -d '{
    "amount": "1500.00",
    "currency": "RUB",
    "description": "Order 1001",
    "metadata": {"order_id": "1001"},
    "webhook_url": "http://host.docker.internal:9000/webhook"
  }'
```

Response — `202 Accepted`:

```json
{
  "payment_id": "2bb1c9a9-04c9-48f9-99f5-3d6a7f2dcd29",
  "status": "pending",
  "created_at": "2026-06-10T12:00:00Z"
}
```

Fetch payment details:

```bash
curl -s http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: dev-api-key"
```

Repeating the `POST` with the same `Idempotency-Key` returns the original payment
rather than creating a new one.

Create a payment through gRPC with `grpcurl`:

```bash
grpcurl -plaintext \
  -import-path . \
  -proto app/grpc/payment.proto \
  -H "x-api-key: dev-api-key" \
  -H "idempotency-key: order-1002" \
  -d '{
    "amount": "1500.00",
    "currency": "RUB",
    "description": "Order 1002",
    "metadata": {"order_id": "1002"},
    "webhook_url": "http://host.docker.internal:9000/webhook"
  }' \
  localhost:50051 grpc.payments/POST
```

## Local Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
alembic upgrade head
uvicorn app.main:app --reload
```

Run the consumer in a separate terminal:

```bash
faststream run app.worker:app --reload
```

Run the gRPC server in another terminal:

```bash
python -m app.grpc.server
```

Regenerate gRPC stubs after editing `app/grpc/payment.proto`:

```bash
make grpc-generate
```

Run the tests:

```bash
pytest
```

Run lint and the local check bundle:

```bash
ruff check .
pre-commit run --all-files
make check
```

With the Docker stack running, run the end-to-end suite (creates a real payment,
verifies idempotent replay, the 409 conflict on body mismatch, processing, and
webhook delivery to a local receiver):

```bash
E2E=1 pytest tests/test_e2e.py
```

Run the broker outage recovery test against the Docker stack:

```bash
E2E_BROKER_OUTAGE=1 pytest tests/test_broker_outage.py
```

## Configuration

All settings are read from the environment; see `.env.example` for the full list
and defaults. The most relevant:

| Variable                         | Description                                    |
| -------------------------------- | ---------------------------------------------- |
| `API_KEY`                        | Static key required in `X-API-Key`             |
| `DATABASE_URL`                   | Async PostgreSQL DSN (`postgresql+asyncpg://`) |
| `RABBITMQ_URL`                   | RabbitMQ connection URL                        |
| `GRPC_PORT`                      | gRPC server listen port (default `50051`)      |
| `PAYMENT_PROCESSING_MIN_SECONDS` | Lower bound of the emulated gateway delay      |
| `PAYMENT_PROCESSING_MAX_SECONDS` | Upper bound of the emulated gateway delay      |
| `PAYMENT_SUCCESS_RATE`           | Probability of `succeeded` (default `0.9`)     |

## Delivery Guarantees

- **Transactional outbox.** The payment and its outbox event are committed in one
  transaction. If RabbitMQ is unavailable, the outbox row stays `pending` and the
  publisher keeps retrying — no event is lost.
- **Idempotent intake.** A unique constraint on `idempotency_key`, plus an
  `IntegrityError` fallback, ensures concurrent duplicate requests resolve to the
  same payment.
- **Idempotent processing.** The payment consumer locks the payment row
  (`FOR UPDATE`) and skips any payment already in a terminal state, so duplicate
  deliveries never reprocess the gateway result.
- **Idempotent webhook delivery.** The webhook is sent under the same row lock
  with a `webhook_sent_at` check-and-set, so duplicate deliveries and retries
  never resend a webhook that already went out.
- **Retries.** Any failure — processing or webhook delivery — routes the event
  through TTL retry queues with exponential delays of 2 s and 4 s; completed
  steps are skipped on redelivery.
- **Dead-letter queue.** After 3 failed attempts the event goes to
  `payments.dlq` for manual inspection.
