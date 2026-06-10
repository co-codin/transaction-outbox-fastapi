# Repository Guidance

This repository implements an async payment processing service for the task in
`task.pdf`: FastAPI intake, PostgreSQL persistence, transactional outbox,
RabbitMQ/FastStream processing, webhook delivery, retries, and DLQ routing.

## Architecture

- Keep API code under `app/api`, business operations under `app/services`,
  RabbitMQ/outbox code under `app/messaging`, database models under
  `app/models`, and Pydantic schemas under `app/schemas`.
- `POST /api/v1/payments` must create the `payments` row and corresponding
  `outbox` row in one database transaction.
- The outbox publisher is owned by the API lifespan in `app/main.py`; the
  consumer entrypoint is `app/worker.py`.
- The consumer must remain one handler for `payments.new`: process the payment,
  persist the terminal status, send the webhook, and route failed attempts to
  retry queues or `payments.dlq`.
- Preserve idempotency at both boundaries: `Idempotency-Key` for payment intake
  and `webhook_sent_at` for webhook delivery.

## Code Rules

- Use async SQLAlchemy 2.0 patterns with `AsyncSession`.
- Keep Pydantic v2 models in schema modules; avoid returning ORM models directly
  from API routes.
- Do not add dependencies unless the task clearly requires one.
- When model fields change, update the Alembic migration and tests in the same
  pass.
- Keep queue names and routing keys centralized in `app/messaging/topology.py`.
- Do not expose internal delivery bookkeeping fields such as
  `webhook_sent_at`, `webhook_last_error`, or outbox internals through the
  public payment API unless explicitly requested.

## Verification

Use the smallest check that proves the change, then broaden when shared behavior
is touched.

- API/schema changes: `PYTHONPATH=. pytest -q tests/test_api_payments.py`
- Processor/retry/webhook changes:
  `PYTHONPATH=. pytest -q tests/test_processor_processing.py tests/test_processor_retry.py tests/test_webhooks.py`
- Outbox/topology changes:
  `PYTHONPATH=. pytest -q tests/test_outbox.py tests/test_topology.py`
- General verification: `PYTHONPATH=. pytest -q`
- Lint: `ruff check .`
- Docker config check: `docker compose config >/dev/null`

The local shell may not expose `python`; use `python3` for direct Python
commands. If plain `pytest` cannot import `app`, rerun with `PYTHONPATH=.`
before treating it as a code failure.

## Delivery Notes

- Keep diffs small and behavior-preserving unless the user asks for a feature.
- Report skipped end-to-end tests explicitly; `tests/test_e2e.py` and
  `tests/test_broker_outage.py` require opt-in environment variables and a
  running Docker stack.
- Leave unrelated untracked or user-owned files alone.
