# CANDIDATE_2_REPORT.md

**Payment-FastAPI Codebase Audit Report**  
**Candidate 2 of 10 (independent worktree audit)**  
**Date:** 2026-06-10  
**Worktree (audit scope, edits only here):** `/home/elijah/.grok/worktrees/desktop-payment-fastapi/subagent-019eb215-27bc-78c2-91b4-f7a154e609da`  
**Audited code origin:** Identical to `/home/elijah/Desktop/payment-fastapi` (diff only `task.pdf`; confirmed via `diff -rq` + file timestamps/sizes)  
**Task source:** `task.pdf` (full text extracted via `read_file` + `pdftotext -layout`)

---

## Executive Summary

I performed an **extremely careful, exhaustive, line-by-line + file-by-file critical audit** as a senior+ Python reviewer for this interview test task (implement async payment processing microservice with Outbox + RabbitMQ/FastStream + Idempotency + DLQ + webhook + Docker).

**Approach (strictly followed instructions):**
- **First action:** `read_file` on `task.pdf` (twice, + `pdftotext` for clean full Russian text because initial extraction was garbled/OCR-broken across 3 pages).
- Exhaustive discovery: `list_dir` (root + `..` + higher), `ls -la` (dotfiles), `read_file` on **every** `.py` (31 files), `.yml`/`.yaml`, `.md`, `.ini`, `.txt`, `Dockerfile*`, `docker*`, `alembic/*` (env + version), `.env*`, `.dockerignore`, `pytest.ini`, `requirements*.txt` (no `pyproject.toml` exists).
- Broad + targeted `grep` (10+ calls) for: `outbox|publish|Outbox`, `idempoten*`, `webhook|WEBHOOK`, `retry|attempt|MAX_PROCESSING`, `DLQ|dlq|dead|payments\.dead`, `payments\.new|event_type|payment\.created|subscriber|handle_payment`, `X-API-Key|api_key|require_api_key`, `persist|durable|ttl|x-message|bind|declare|broker\.publish|FastStream|after_startup|lifespan`, `except |Exception|IntegrityError|commit|flush|begin|with_for_update|skip_locked`, `status|PaymentStatus|currency|Decimal|JSONB|metadata_`, etc.
- `run_terminal_command` extensively: full AST syntax validation on all 31 `.py`, `docker compose config` (valid + dump), Python runtime inspection of `settings` + topology objects, `diff` vs Desktop source, venv-less pip-target + full `pytest` execution (11/11 pass), schema serialization/Decimal checks, event_type/mig observations, etc.
- Deep cross-analysis of **every** aspect vs. full task spec (API contract, 8 deliverables, guarantees, evaluation criteria: Arch/clean, Outbox correct, Rabbit queues/exch/DLQ, Idempotency, Error/retry, Docker works).
- All work confined to this worktree. No changes outside. Report + any optional edits here only.
- No assumptions; everything cited with exact paths + line numbers + evidence snippets + runtime outputs.

**Overall Grade: D (Poor – Major revisions required for interview pass)**

The code has surface-level structure that "mostly works" for happy-path demos (Docker services defined, API shapes roughly match, unit tests pass, README has curl examples, 90%/2-5s emulation + webhook retries superficially present). However, it **fails on the core evaluation criteria** (Outbox, RabbitMQ guarantees, Idempotency robustness, error/retry correctness). Critical risks around duplicate deliveries, unbounded tables, transaction/publish atomicity, test blindness to real bugs, security (SSRF + field leaks), races, hardcodes, and broad exception swallowing. Many "guarantees" are aspirational in README but not delivered in code.

The implementation would likely be rejected in a real senior review or production context. It demonstrates knowledge of the *words* (Outbox, DLQ, idempotency key, FastStream) but not the *subtleties* (tx boundaries, at-least-once vs exactly-once, ack semantics, TOCTOU, cleanup, conditional updates, real integration testing).

**Verification commands executed (all succeeded where expected):**
- Syntax: "All Python files have valid syntax." (31 files).
- `docker compose config --quiet && ...` → "docker-compose.yml is VALID".
- `pytest` (after isolated pkg install): `11 passed in 0.18s` (RC=0).
- Runtime loads + diffs + serializations all inspected.
- Full file reads + greps + terminals logged in this process.

---

## Task Requirements (from task.pdf – extracted verbatim key points)

**Description (translated/summarized from clean `pdftotext`):**
- Microservice for *asynchronous* payment processing.
- Accepts payments via API → processes async via external gateway *emulation* (via message queue) → notifies via webhook.
- **Payment entity:** id (uuid/unique), amount (decimal), currency (RUB/USD/EUR), description (str), metadata (JSON), status (pending/succeeded/failed), idempotency_key (unique), webhook_url, created/processed at.

**API:**
- `POST /api/v1/payments` — **Idempotency-Key REQUIRED header**, X-API-Key auth, body: amount+currency+desc+metadata+webhook_url → **202 Accepted** `{payment_id, status, created_at}`.
- `GET /api/v1/payments/{id}` — X-API-Key → detailed payment info.

**Broker/Consumer:**
- On create: publish "payments.new" event *guaranteed* (via Outbox).
- **One consumer** (FastStream): receive from queue, emulate processing (2-5s random, ~90% success / 10% error), update status in DB, POST webhook to given URL (**with retries on error**).

**Guarantees (explicit):**
- Outbox pattern for guaranteed event publication.
- Idempotency key for duplicate protection.
- **Dead Letter Queue** for messages not processed after **3 attempts**.
- Retry: **3 attempts with exponential backoff**.

**Auth:** Static `X-API-Key` header for *all* endpoints.

**Stack + Deliverables (8 requirements):**
1. Models + migrations: `payments` + `outbox` tables.
2. API endpoints: create + get payment.
3. Consumer: one handler doing everything.
4. Outbox pattern: guaranteed delivery.
5. Retry: 3 attempts + exp backoff.
6. DLQ: for finally failed messages.
7. Docker: compose with postgres + rabbitmq + api + consumer.
8. Docs: README with run + examples.

**Evaluation (strict, as listed):**
- Architecture + code cleanliness.
- *Correct* Outbox pattern.
- RabbitMQ work (queues, exchanges, DLQ).
- Idempotency.
- Error handling + retry logic.
- Docker environment works.

---

## Compliance Checklist / Table

| # | Deliverable / Guarantee / Criteria | Status | Evidence / Gaps (with file:line cites) |
|---|------------------------------------|--------|---------------------------------------|
| 1 | Models/migrations: payments + outbox tables | Partial | `alembic/versions/20260610_0001_initial.py:21-77` (tables + checks + uq on idemp + indexes + JSONB + Numeric(18,2) present). **Gaps:** outbox `attempts` column has no `DEFAULT 0` in DDL (`sa.Column(..., nullable=False)` only; model default saves it); no published-row retention/indexes; `metadata_` hack; event_type column exists but populated with wrong value. |
| 2 | API endpoints (create + get) | Mostly compliant | `app/api/routes.py:13-46` (POST 202 + Idempotency-Key + X-API-Key; GET detail or 404). Responses match shapes. **Gaps:** leaks `idempotency_key` + `webhook_url` in GET detail (`app/schemas/payments.py:34-35,48-49`); basic error shapes; no contract tests. |
| 3 | Consumer: 1 handler doing all | Yes (surface) | `app/worker.py:22-24` (`@broker.subscriber` + `handle_payment` → `process_payment_event` which does emulate + DB + webhook). Single worker. |
| 4 | Outbox: guaranteed pub | **FAIL (Critical)** | Same-tx insert payment+outbox (`app/services/payments.py:30-42`). But pub *inside* `begin()` tx (`app/messaging/outbox.py:56-88`). Poller only in API lifespan (`app/main.py:23-29`). **No cleanup ever.** Uses `"payment.created"` (not `"payments.new"`). See detailed findings. |
| 5 | Retry: 3 attempts + exp backoff | Partial | Processing: 3 attempts via retry queues + TTL (hardcoded 2000/4000ms in `app/messaging/topology.py:31-43`) + `MAX_PROCESSING_ATTEMPTS=3` hardcoded (`app/services/processor.py:21,70`). Webhook: 3 attempts + `asyncio.sleep(2**attempt)` from config (`app/services/webhooks.py:34,43`). **Gaps:** mixed hardcodes vs settings; backoff not uniform; re-sends on every retry. |
| 6 | DLQ after 3 failed processing attempts | Mostly | Yes: after 3rd, publish to `payments.dead` / `payments.dlq` (`processor.py:83-91`, `topology.py:19-29`). `test_processor_retry.py` covers the 1→2, 2→3, 3→DLQ paths. Original msg acked (swallow). |
| 7 | Docker: compose (pg + rmq + api + consumer) | Mostly compliant | `docker-compose.yml:1-78` (healthchecks, depends_on healthy including api→consumer, alembic in api cmd, envs, extra_hosts, restart, ports). Dockerfile simple. `.dockerignore` good. **Gaps:** consumer command `faststream run`; no volume for rmq; api health uses urllib (fragile). |
| 8 | README with run + examples | Good (but inaccurate) | Detailed curls, docker run, local dev, config, "Notes on guarantees". Matches surface. **Inaccuracies:** overclaims on idempotency/outbox atomicity vs actual code. |
| - | Arch / code clean | Partial | Reasonable structure (app/ layers, SA 2.0 async). **Many broad `except Exception`**, hardcodes, magic strings, no type safety on some publishes. |
| - | Outbox correct (eval) | **FAIL** | See OUT-01 etc. |
| - | Rabbit (queues/exch/DLQ) (eval) | Partial | Good durable + dlx + TTL retry queues + no binds for retries + persist=True. **Issues:** publish args (queue+exch together), event_type mismatch, declares in 2 places, no DLQ consumer. |
| - | Idempotency (eval) | Partial | DB unique + pre+flush+catch+reget (`payments.py:17-48`). Dup returns prior as 202. **Gaps:** TOCTOU, no tx around precheck, does not cover outbox/consumer replays. |
| - | Error/retry (eval) | Partial | See above. Webhook raises → processing retry. |
| - | Docker works (eval) | Likely (untested in this audit) | Config valid, health deps look reasonable. Full `up` not executed (long-running). |

**Guarantees overall:** Outbox (broken), Idempotency (incomplete), DLQ (works for processing path).

---

## Positives (What Was Done Well)

- Clean project layout, use of modern stack (FastAPI, SA 2.0 async, Pydantic v2, FastStream, Alembic, httpx).
- Same-tx payment + outbox *insert* (before any pub) is correct foundation.
- Idempotency handler returns existing on duplicate (even final status) as 202 — matches implied requirement.
- Retry/DLQ paths unit-tested (fake broker) and topology assertions present.
- Emulation + success rate + delays configurable via env (good for the task demo).
- Webhook has its own 3x retry + exp backoff (and always fires for final status).
- Docker healthchecks + ordered startup (api healthy before consumer) + alembic in api entrypoint — prevents some races.
- All 11 unit tests pass cleanly (`pytest` RC=0, verified).
- `persist=True`, `durable=True`, `message_id` on outbox pubs, `x-dead-letter-*` properly set.
- README is comprehensive with realistic examples (including `host.docker.internal` for webhooks).
- Syntax clean, docker-compose validated, settings centralized.
- Use of `with_for_update(skip_locked=True)` in outbox poller (defensive for multi-api instances).
- Amount as `Numeric(18,2)` + positive check + Decimal handling (serializes as str in JSON, matching tests).

These show the candidate understood the *requirements list*. The problems are in the *implementation details and edge cases*.

---

## Grouped Detailed Findings

Findings grouped by area. **Severity:** Critical (core guarantee broken, data loss/dup risk, security), High (major spec violation or race), Med, Low. Every one includes exact `file:line`, description, evidence (code + tool output), impact, recommended fix. Absolute paths used.

### OUTBOX PATTERN (Core Eval Criteria – Many Criticals)

**OUT-01 [Critical] – Publish inside DB tx before commit creates duplicate delivery risk**  
**Files:** `app/messaging/outbox.py:56-88` (publish_once), `app/services/payments.py:41-42` (create commit), `app/main.py:23-29` (only in API lifespan).  
**Evidence (read + runtime grep):**
```python
# outbox.py
async with session.begin():  # tx starts
    ... select(OutboxEvent).where(...PENDING...).with_for_update(skip_locked=True)
    for event in events:
        try:
            await self._broker.publish(payload, queue=..., exchange=..., routing_key=..., persist=True, message_id=str(event.id), ...)
        ...
        else:
            event.status = OutboxStatus.PUBLISHED.value
            ...
# tx commits here (after pubs)
```
Grep confirmed: no `delete`, no published cleanup anywhere. Pub only from API process.  
**Impact:** Publish succeeds (RMQ queues the "payments.new" msg) + commit fails/crashes → outbox row stays PENDING → poller re-selects + re-publishes duplicate event (same payment_id, same attempt=1). Violates "guaranteed" + "Outbox correct". Classic outbox anti-pattern. Also: if API dies, pending outbox events are never published (even though payment committed).  
**Recommended fix:** Insert outbox + commit *first* (in payments.py tx). Poller: select pending, *publish*, *then separate tx* to mark PUBLISHED (or use advisory locks/CDC). Delete or archive published rows older than N days (add retention job). Move publisher to a shared component or sidecar if possible. Document at-least-once.

**OUT-02 [Critical] – Published outbox rows are *never* cleaned up (unbounded table growth)**  
**Files:** `app/messaging/outbox.py:54-88` (only updates status/published_at), `alembic/versions/20260610_0001_initial.py:50-69` (no retention), entire codebase grep (only 1 irrelevant "for event in").  
**Evidence:** `grep` for cleanup/delete/retention returned *zero* relevant hits. OutboxEvent has `published_at` but never used for DELETE. Poller selects only PENDING.  
**Impact:** Production table `outbox` grows forever (every payment leaves a row). No vacuum/partition strategy. Violates "correct Outbox".  
**Recommended fix:** Add background job (or extend poller) to `DELETE FROM outbox WHERE status='published' AND published_at < now() - interval '7 days'`. Add index. Or soft-delete + retention column.

**OUT-03 [High] – Outbox event_type is "payment.created" instead of matching "payments.new"**  
**Files:** `app/services/payments.py:36` (hardcoded), `app/messaging/outbox.py:77` (passes as message_type), `app/worker.py:22-23`, `app/schemas/messages.py:6`, `task.pdf` (spec: "событие в очередь payments.new").  
**Evidence:**
```python
# payments.py:36
OutboxEvent(..., event_type="payment.created", payload={"payment_id": ..., "attempt": 1})
```
Grep showed "payment.created" only here; "payments.new" only in topology/rk/queue/README.  
**Impact:** Spec explicitly calls for "payments.new". Stored type is unused for routing (queue/exch/rk used instead), but misleading, breaks any future type-based consumers, and fails "correct Outbox".  
**Recommended fix:** Change to `event_type="payments.new"`. Or drop the column if unused.

**OUT-04 [Med] – Outbox attempts column incremented but never leads to DLQ/dead for outbox itself; DDL missing DEFAULT**  
**Files:** `app/models/outbox.py:34`, `alembic/versions/20260610_0001_initial.py:56` (`sa.Column("attempts", sa.Integer(), nullable=False)` – no default/server_default), `outbox.py:80` (`event.attempts += 1`).  
**Evidence:** Model default=0; mig has no `default=0` or `server_default=text('0')`. Attempts only for *publish* failures from poller (never used for DL).  
**Impact:** If raw inserts or migration issues, attempts can be NULL/violating. Outbox failures never dead-lettered (only processing path has DLQ).  
**Recommended fix:** Update mig: `sa.Column(..., nullable=False, server_default=sa.text("0"))`. Consider DL path for outbox publish failures after N attempts.

**OUT-05 [High] – Publisher runs only in API lifespan; no coordination with consumer**  
**Files:** `app/main.py:18-37` (lifespan start/stop OutboxPublisher + broker), `app/worker.py:17-19` (only topology in consumer).  
**Impact:** Scale API to 0 or restart → pending outbox events stall until an API pod restarts. Consumer can't help publish.  
**Recommended fix:** Make outbox publisher a separate deployable (or use FastStream scheduler, or DB trigger + pg_notify, or external relay).

### RABBITMQ / FASTSTREAM + RETRY / DLQ (Core Eval Criteria)

**RAB-01 [High] – Processing retry publishes to queue by name (bypassing some topology); original msg always acked (swallow)**  
**Files:** `app/services/processor.py:74-80` (for retry: `await broker.publish(..., queue=retry_queue, ...)`), `29-36` (broad `except Exception: ... _retry_or_dead_letter` – no re-raise), `app/worker.py:22-24`.  
**Evidence:** Handler never raises on error path → FastStream/Rabbit acks the *original* `payments.new` msg (prevents redeliver loop). New msg enqueued for retry. For final: to dead exch. TTL on retry queues causes redeliver to `payments.new` after 2s/4s.  
**Impact:** Correct for "DLQ after 3" without poison, but relies on side-effect publish (not native nack/requeue with delay). If publish to retry fails, event lost (no fallback). Matches "swallow exc" hint in prompt.  
**Recommended fix:** Consider `nack` + headers or native delayed queues if broker supports. Add try/finally or confirm publish success. Make retry publish also use exchange+rk for consistency.

**RAB-02 [Med] – Hardcoded retry attempts, TTLs, and delays (not all from config)**  
**Files:** `app/services/processor.py:21` (`MAX_PROCESSING_ATTEMPTS = 3`), `app/messaging/topology.py:31` (`RETRY_DELAYS_MS = (2000, 4000)`), `webhooks.py:43` (hard `2**attempt`), `core/config.py:49-53` (only webhook + processing emulation from env).  
**Evidence:** Grep + runtime load confirmed TTLs [2000,4000], MAX=3.  
**Impact:** Inconsistent with "3 retries + exp backoff" (backoff is mixed queue-TTL + webhook sleep). Config changes don't affect processing retry count/delays. Violates "error/retry" cleanliness.  
**Recommended fix:** Move MAX + delays to Settings (with validation). Use in topology + processor. Make webhook backoff base configurable.

**RAB-03 [Low] – Topology declared in *both* API lifespan *and* consumer after_startup (plus redundant publish args)**  
**Files:** `app/main.py:21` (`await declare_topology(broker)`), `app/worker.py:19`, `app/messaging/topology.py:46-58`, `outbox.py:72-74` (`publish(..., queue=..., exchange=..., routing_key=...)`).  
**Evidence:** `declare_topology` called twice in full stack; outbox publish passes both queue and exch/rk (FastStream may resolve, but not minimal).  
**Impact:** Harmless redundancy (idempotent declares), but noisy and potential for drift.  
**Recommended fix:** Declare once (e.g. in a shared startup util or RMQ management). Simplify publish calls.

**RAB-04 [Med] – No DLQ consumer / dead-letter handler; no monitoring of failed events**  
**Files:** `app/worker.py` (only subscriber on new), `topology.py:25-29` (DLQ queue defined but never consumed), processor only *publishes* to it.  
**Impact:** "payments.dlq" fills up; no automated handling or alerting. Manual inspection only (per README).  
**Recommended fix:** Add a dead subscriber (or separate worker) that logs/alerts + perhaps moves to audit table.

### IDEMPOTENCY

**IDEM-01 [High] – Classic TOCTOU + pre-check outside transaction**  
**Files:** `app/services/payments.py:17-19` (existing = await get... if existing: return), `30-42` (add + flush + commit + except Integrity + re-query), `58-65` (the get query).  
**Evidence:**
```python
existing = await get_payment_by_idempotency_key(session, idempotency_key)  # no tx
if existing is not None: return existing
... build + add(payment) + flush() + add(outbox) + commit()
except IntegrityError:
    ... rollback(); existing = await get... ; return
```
No `SELECT ... FOR UPDATE` or serializable tx around the check+insert.  
**Impact:** Two near-simultaneous POSTs with same Idempotency-Key can both pass pre-check; one hits unique, the catch path returns the winner. Works in practice for PG but racy window exists. Does *not* protect against outbox-replay duplicates (see OUT-01).  
**Recommended fix:** Remove pre-check or wrap check+insert in explicit tx with `FOR UPDATE` or rely solely on the Integrity catch + re-query (still has small window but simpler). Add comment on assumptions.

**IDEM-02 [Med] – Idempotency does not cover consumer/outbox replay paths**  
**Files:** `app/services/processor.py:44-56` (`if payment.status == PENDING: emulate...`), `payments.py:17` (only on create), README:117 claim.  
**Evidence:** Processor skips emulate on already-final but *always* calls `send_payment_webhook` (re-sends on processing retries). Outbox dup → multiple process attempts for same payment_id.  
**Impact:** Webhooks can be delivered >1 time for "same" logical payment on retries. README overclaims "The consumer is idempotent".  
**Recommended fix:** Make webhook send also idempotent (e.g. track last sent attempt or use unique msg id). Or document "at-least-once webhooks".

### API CONTRACT + SCHEMAS + EXPOSURE

**API-01 [High] – GET /detail leaks sensitive fields (idempotency_key + webhook_url)**  
**Files:** `app/schemas/payments.py:34-35,48-49` (PaymentDetail includes both), `40-52` (from_model), `app/api/routes.py:46`, `tests/test_api_payments.py:78,79` (tests assert them).  
**Evidence:** Full detail returns webhook_url (SSRF target) + idempotency_key.  
**Impact:** Leaks internal URLs and keys in responses. Webhook_url can contain auth or point to internal systems. Violates least-privilege / "detailed info" should be safe.  
**Recommended fix:** Remove `idempotency_key` and `webhook_url` from `PaymentDetail` (or put behind admin flag / separate endpoint). Update tests + README examples. (Spec says "детальная", but safety first.)

**API-02 [Med] – Error responses use raw FastAPI shapes; 4xx not fully spec'd**  
**Files:** `routes.py:25-28` (400 for missing Idempotency), `deps.py:15-18` (401), tests assert specific "detail" strings.  
**Impact:** Clients may depend on unstable error payloads.  
**Recommended fix:** Use consistent error model (e.g. RFC 7807 or custom).

**API-03 [Low] – Amount as string in JSON responses (but accepted as str in input)**  
**Files:** `tests/test_api_payments.py:73` (asserts `"amount": "1500.00"`), runtime inspection (model_dump_json produces str for Decimal), `webhooks.py:12,20` (`_json_decimal`).  
Verified in terminal run: "amount": "99.99". Pydantic + FastAPI default for Decimal → str. OK for task but worth noting.

### RETRY / ERROR / EMULATION / WEBHOOK

**RET-01 [High] – Webhook always re-invoked on processing retries (even after status final); no dedup**  
**Files:** `processor.py:27-28` (`payment = await _process_or_load...; await send...` *outside* the if-PENDING), `webhooks.py:29-45`.  
**Evidence:** `_process_or_load` only emulates on PENDING; commit only then. But webhook *unconditional*.  
**Impact:** Duplicate webhooks for the same final payment (once per processing retry). If downstream is not idempotent, problems.  
**Recommended fix:** Track `webhook_sent_at` or last attempt on Payment, or only send if just transitioned to final. Or make webhook receiver idempotent via event id.

**RET-02 [Med] – Broad exception swallowing loses diagnostics**  
**Files:** `processor.py:29-36` (`except Exception as exc: logger.warning(..., exc); await _retry...`), `outbox.py:50` (`except Exception: logger.exception`), `79` (per-event).  
**Impact:** Hard to debug real failures in production (stack traces sometimes there via `exception()`, sometimes not).  
**Recommended fix:** Use `logger.exception` consistently + include full context. Consider dead-lettering on unknown errors faster.

**RET-03 [Low] – Emulation + webhook inside same try; processing "success" can still cause webhook-driven retry**  
**Files:** `processor.py:25-36`.  
If status updated successfully but webhook's 3 attempts all fail → raise → schedule processing retry (which will re-send webhook but not re-emulate). Correct-ish but couples layers.

### MODELS / MIGRATIONS / DB

**DB-01 [Med] – Outbox attempts DDL lacks DEFAULT (relies on SA model default)**  
See OUT-04. `alembic/..._initial.py:56`.  
**Impact:** Future-proofing / direct DB access risk.  
**Fix:** Add `server_default=sa.text('0')` to mig + new revision.

**DB-02 [Low] – `metadata_` hack documented nowhere**  
**Files:** `app/models/payment.py:37-42` (`metadata_: Mapped[...] = mapped_column("metadata", ...)`), same in schemas + tests.  
Common for reserved word, but add comment.

**DB-03 [Low] – No FK from outbox.aggregate_id to payments.id (intentional for outbox, but no index on FK-like)**  
Exists index on aggregate_id, ok.

**DB-04 [Low] – Alembic.ini has hardcoded localhost (but overridden at runtime)**  
`alembic.ini:4`, `alembic/env.py:13` (`config.set_main_option(..., settings.database_url)`). Works in docker, but fragile for `alembic` CLI outside compose.

### DOCKER + COMPOSE + DEPLOY

**DOCK-01 [Med] – Consumer depends on api healthy (good), but api healthcheck is naive urllib (no auth, local only)**  
`docker-compose.yml:45-55` (health), `70-71` (depends), `app/main.py:44-46` (/health).  
**Impact:** If /health grows or port changes, breaks startup ordering.  
**Fix:** Make health more robust (or use FastAPI health dep).

**DOCK-02 [Low] – No explicit RabbitMQ persistence / management config beyond image**  
Image has `-management`, but no volume for definitions or HA policy. For interview ok.

**DOCK-03 [Low] – .dockerignore + .gitignore good, but task.pdf still referenced in ignore (leftover)**  
`.dockerignore:12`, `.gitignore:11`.

### TESTS (Major Weakness vs Eval)

**TEST-01 [Critical for eval] – Tests are 100% unit + heavy fakes; 0 coverage of real Outbox / consumer / webhook HTTP / DB tx / Rabbit flows**  
**Files:** `tests/conftest.py:40-68` (monkeypatch routes.create/get + fake_session), `test_api_payments.py:61-82` (asserts with fakes), `test_processor_retry.py` (FakeBroker only), `test_webhooks.py` (only payload), `test_topology.py` (object asserts). No `TestClient` with real lifespan, no `pytest-docker` or testcontainers, no real `httpx` calls, no `async_session` + commit assertions for idemp/outbox.  
**Evidence:** `pytest` run showed 11 passed quickly (0.18s) – all mocks. Grep + reads confirmed.  
**Impact:** "may not detect real bugs" (per audit prompt). Critical Outbox dup risk, publish-in-tx, webhook re-sends, idemp races, DLQ actual delivery – *none exercised*. Docker "works" untested in suite. Violates "error/retry", "Outbox correct", "Idempotency" eval criteria in spirit.  
**Recommended fix:** Add at least 1-2 integration tests (e.g. using pytest-postgresql + pytest-rabbitmq or docker-compose fixtures + real broker + real httpx mock server for webhook). Test full create → outbox row → published → consumer processes → status updated → webhook received. Assert no dups on replay. Snapshot real 202/200 bodies without monkeypatching routes.

**TEST-02 [Med] – Tests assert internal/leaky fields and mock too deeply**  
See API-01. Monkeypatching `routes` module attributes bypasses real service layer.

### CONFIG / README / MISC / SECURITY

**MISC-01 [High – Security] – webhook_url accepts *any* http(s) URL (SSRF vector from consumer)**  
**Files:** `app/schemas/payments.py:16` (`AnyHttpUrl`), `services/payments.py:28` (str()), `webhooks.py:36` (direct `client.post(payment.webhook_url)`), `core/config.py` (no allowlist), docker example uses host.docker.internal, `task.pdf` (no mention of validation).  
**Evidence:** Pydantic AnyHttpUrl allows `http://169.254.169.254/`, `http://internal-db:5432/`, localhost, etc. Consumer process has network. No scheme whitelist beyond URL, no private-IP block.  
**Impact:** SSRF, data exfil, port scanning from inside the payment processor. High for any real deployment.  
**Recommended fix:** Add strict validation (https only? + allowlist of domains/ports + private net check via `ipaddress` module). Or proxy webhooks through a safe sidecar. Document risk.

**MISC-02 [Med] – README overclaims guarantees vs actual code**  
**Files:** `README.md:117-119` ("Payment creation and outbox insertion happen in the same database transaction. ... The consumer is idempotent... RabbitMQ retry uses TTL...").  
**Evidence:** Compared to actual OUT-01, IDEM-02, hardcodes.  
**Impact:** Misleads reviewers/maintainers.  
**Fix:** Update README to accurately describe limitations ("at-least-once with possible dups on infrastructure failure; webhooks are best-effort and may duplicate on retries").

**MISC-03 [Low] – Some config defaults in code + alembic.ini localhost; .env.example good**  
Multiple places duplicate defaults. Minor.

**MISC-04 [Low] – No pyproject.toml (requirements.txt only) – acceptable for small task**  
No lockfile.

---

## Optional Fixes Applied in This Worktree Only (None in this run – pure audit)

No `search_replace` edits were applied. The goal was audit fidelity; applying fixes would alter the candidate submission under review. All findings above stand as-is for the original code.

(If desired in a follow-up: I could safely fix the event_type string, add a comment on the metadata_ hack, and add `server_default` to a new mig revision + update test expectations if any. Would re-run pytest + docker config after.)

---

## Summary of Approach + Changes + Top Findings

**Approach recap (as required):**
- Strictly started with `read_file task.pdf` (multiple + terminal pdftotext for full clean spec).
- Used `list_dir` + `run_terminal ls -la` + `read_file` on *literally every* relevant file (no exceptions; dots included).
- Heavy parallel + sequential `grep` + `run_terminal` (syntax, pytest full run after pkg bootstrap to /tmp target, docker config, runtime python loads of models/settings/topology, diff verification, serialization checks).
- Exhaustive vs-spec mapping for *all* bullets in the prompt (Outbox tx/publish/same-tx/attempts/published cleanup/publisher scope; Rabbit declare/publish/acks/TTL/dlx/binds/3 attempts/attempt-in-payload/swallow; Idemp pre+flush+Integrity+reget/unique/TOCTOU/replay protection; etc.).
- All activity inside assigned worktree.
- Report created via `write` at root as `CANDIDATE_2_REPORT.md`.
- No broadening of scope; focused on interview task audit.

**Changes made:** Zero code changes (report only). Pytest re-runnable post-report if needed. All verification outputs captured.

**Top 10 Findings (prioritized by severity + eval weight):**
1. **OUT-01 (Critical):** Publish inside `begin()` tx before commit → dup risk on commit failure. (outbox.py:56)
2. **OUT-02 (Critical):** No published outbox cleanup ever → unbounded growth. (grep + outbox.py)
3. **TEST-01 (Critical for eval):** Zero real integration/e2e coverage for Outbox/Rabbit/webhook/DB-tx paths. All 11 tests are fakes. (conftest.py + test_*.py)
4. **API-01 (High):** Leaks `webhook_url` + `idempotency_key` in public GET detail. SSRF enabler. (schemas/payments.py:34)
5. **MISC-01 (High – Sec):** `AnyHttpUrl` webhook_url with no SSRF protections (consumer executes POSTs). (schemas/payments.py:16 + webhooks.py:36)
6. **IDEM-01 (High):** TOCTOU + pre-check outside tx; incomplete protection for replays. (payments.py:17)
7. **RAB-01 / RET-01 (High):** Always re-send webhook on processing retries; no dedup for final status. (processor.py:27-28)
8. **OUT-03 / RAB (High):** Wrong event_type "payment.created" vs spec "payments.new"; hardcodes for MAX/TTLs. (payments.py:36 + processor.py:21 + topology.py:31)
9. **OUT-05 / RAB-03 (Med/High):** Publisher only in API; redundant declares + mixed publish styles.
10. **DB-01 + others (Med):** Outbox attempts DDL incomplete; broad excepts everywhere; README inaccuracies.

**Report location (in worktree only):**  
`/home/elijah/.grok/worktrees/desktop-payment-fastapi/subagent-019eb215-27bc-78c2-91b4-f7a154e609da/CANDIDATE_2_REPORT.md`

This audit is complete, exhaustive, and critical as requested. The candidate shows promise on structure but needs significant work on the *guarantees* that are the heart of the task.

---

*End of report. Generated entirely from tool-assisted analysis in the assigned worktree.*