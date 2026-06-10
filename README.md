# Async Payment Processor

FastAPI microservice for asynchronous payment processing. It accepts payment requests, stores them with an idempotency key, publishes payment events through an outbox table, processes events with RabbitMQ/FastStream, and sends final status webhooks.

## What Is Implemented

- `POST /api/v1/payments` with required `X-API-Key` and `Idempotency-Key` headers.
- `GET /api/v1/payments/{payment_id}` with required `X-API-Key`.
- PostgreSQL tables: `payments` and `outbox`.
- Outbox publisher loop in the API process.
- RabbitMQ queues:
  - `payments.new`
  - `payments.retry.1`, `payments.retry.2`
  - `payments.dlq`
- Consumer processing:
  - waits 2-5 seconds by default;
  - produces `succeeded` with 90% probability, otherwise `failed`;
  - updates the payment in PostgreSQL;
  - sends a webhook with 3 exponential-backoff attempts;
  - retries failed event processing through RabbitMQ retry queues;
  - sends events to DLQ after 3 total processing attempts.

## Run With Docker

```bash
cp .env.example .env
API_KEY=dev-api-key docker compose up --build
```

The API container runs Alembic migrations before Uvicorn starts. The consumer waits for the API healthcheck, so both services do not race on the migration table.

Services:

- API: `http://localhost:8000`
- RabbitMQ management UI: `http://localhost:15672` (`guest` / `guest`)
- PostgreSQL: `localhost:5433` by default, configurable with `POSTGRES_PORT`

## Create A Payment

Run a local webhook receiver in another terminal if you want to inspect webhook calls:

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

The response is `202 Accepted`:

```json
{
  "payment_id": "2bb1c9a9-04c9-48f9-99f5-3d6a7f2dcd29",
  "status": "pending",
  "created_at": "2026-06-10T12:00:00Z"
}
```

Get payment details:

```bash
curl -s http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: dev-api-key"
```

Repeat the same `POST` with the same `Idempotency-Key`; it returns the original payment instead of creating a duplicate.

## Local Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Run the consumer separately:

```bash
faststream run app.worker:app --reload
```

Run tests:

```bash
pytest
```

## Configuration

Environment variables are listed in `.env.example`. The most important ones:

- `API_KEY`
- `DATABASE_URL`
- `RABBITMQ_URL`
- `PAYMENT_PROCESSING_MIN_SECONDS`
- `PAYMENT_PROCESSING_MAX_SECONDS`
- `PAYMENT_SUCCESS_RATE`
- `WEBHOOK_RETRY_ATTEMPTS`

## Notes On Delivery Guarantees

Payment creation and outbox insertion happen in the same database transaction. If RabbitMQ is unavailable, the outbox row remains `pending` and the API process keeps retrying publication. The consumer is idempotent for payment status updates: already-final payments are not processed by the gateway emulator again.

RabbitMQ retry uses TTL retry queues with exponential delays of 2 and 4 seconds. After the third processing attempt fails, the event is published to `payments.dlq` for manual inspection.
