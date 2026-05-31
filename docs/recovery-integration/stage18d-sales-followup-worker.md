# Stage 18D Sales Follow-Up Worker Runtime

## Scope

Stage 18D adds the runtime and durable store transitions for processing due
`sales_followup_jobs` with an injectable sender. It does not add real Telegram
rendering, Telegram API calls, callback handlers, opt-out callbacks, `FOOD20`
activation, payment metadata changes, recipe/data/PDF changes, bot startup,
deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or recovered-bot
work.

Implemented:

- `SalesFollowupWorker` and `SalesFollowupJobRuntime` in
  `sales_followup_runtime.py`.
- Dedicated disabled-by-default worker flag:
  `DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED=0`.
- Atomic Postgres claim/lease/heartbeat/send-start/sent/retry/failed/unknown
  and skip/cancel/suppress transitions.
- Reclaim of expired running leases only when no send has started.
- Store-level first-unfinished-step claim ordering, preventing multiple due
  jobs from the same chain from being sent in one batch.
- Mock/injectable sender contract with explicit transient, permanent, and
  unknown outcome classes.

## Worker Behavior

The worker claims only due jobs whose chain is still active. A fresh queued job
must have `scheduled_at <= now` and `next_attempt_at <= now`; an expired running
job can be reclaimed only before `send_started_at` and `sent_at`.

Claiming sets:

- `status='running'`;
- `worker_id`;
- `leased_until`;
- `heartbeat_at`.

The heartbeat loop extends the lease while the job is running. Before calling
the injected sender, the worker rechecks eligibility and then persists
`send_started_at`. On mocked success it marks the job `sent`, records `sent_at`,
`finished_at`, and `telegram_message_id`.

## Eligibility Recheck

The runtime blocks sending and cancels future jobs in the chain when any guard
fails:

- campaign disabled;
- user opted out;
- active paid access, via injected eligibility checker;
- weekly PDF access, via injected eligibility checker;
- non-private chat, via injected eligibility checker.

Campaign and opt-out checks use the sales follow-up store directly. Paid access,
weekly PDF access, and chat-type checks are intentionally injectable in this
stage so the worker can be tested without Telegram API or production storage
side effects.

## Failure Handling

Transient send failure:

- safe retry only through explicit `SalesFollowupTransientSendError`;
- job returns to `queued`;
- `next_attempt_at` is bounded by worker retry settings;
- `attempt_count` increments;
- no blind retry for generic post-send errors.

Permanent send failure:

- current job is marked `skipped`;
- future queued/running jobs in the chain are marked `cancelled`;
- chain status becomes `suppressed`.

Unknown send outcome:

- current job becomes `unknown`;
- `finished_at` and `last_error` are recorded for manual review;
- job is not blindly retried.

Max attempts:

- known retryable failures requeue only while attempts remain;
- exhausted jobs become `failed`.

## Mocked-Only Proof

- `SalesFollowupWorker` accepts a `SalesFollowupSender` protocol.
- No `telegram_app.py` send path was added or changed.
- No `message.answer`, bot startup hook, `getUpdates`, callback handler, or
  Telegram button rendering was added.
- Tests use fake senders only.

## Verification

RED before implementation:

- `PYTHONPATH=src pytest tests/test_sales_followup.py tests/test_postgres_sales_followup_store.py tests/test_sales_followup_runtime.py -q`
  - Result: `3 errors` during collection because
    `diet_bot.sales_followup_runtime` did not exist.

GREEN after implementation without DSN:

- `PYTHONPATH=src pytest tests/test_sales_followup.py tests/test_postgres_sales_followup_store.py tests/test_sales_followup_runtime.py -q`
  - Result: `26 passed, 8 skipped`.

DSN-backed local Postgres proof:

- Disposable Docker Postgres: `postgres:16-alpine`, database `diet_bot_test`,
  random localhost port.
- `PYTHONPATH=src DIET_BOT_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:<port>/diet_bot_test pytest tests/test_postgres_sales_followup_store.py -q`
  - Result: `10 passed`.
- `PYTHONPATH=src DIET_BOT_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:<port>/diet_bot_test pytest tests/test_sales_followup.py tests/test_postgres_sales_followup_store.py tests/test_sales_followup_runtime.py -q`
  - Result: `34 passed`.
- Container removed after verification.

Runtime config proof:

- `PYTHONPATH=src pytest tests/test_sales_followup.py tests/test_runtime_config.py -q`
  - Result: `49 passed`.

Diff check:

- `git diff --check`
  - Exit code: `0`.
  - Output contained only existing LF-to-CRLF working-copy warnings.

## Stage 18E Remaining Work

- Add real Telegram rendering and inline buttons for the already-persisted
  message/button payload contract.
- Add opt-out callback handling.
- Wire an approved sender into bot startup only after explicit approval.
- Connect live eligibility sources for paid access, weekly PDF access, and
  chat type in the production worker wiring stage.
- Keep `FOOD20` activation/redemption/payment discount work blocked until its
  dedicated promo/payment stage.

## Verdict

READY FOR NEXT SALES FOLLOW-UP STAGE
