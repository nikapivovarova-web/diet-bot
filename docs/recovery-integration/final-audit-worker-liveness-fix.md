# Final Audit Worker Liveness Fix

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Scope

Fixed the final pre-release audit worker liveness/supervision findings as one
minimal worker-supervision change:

- `HIGH-4`: Worker jobs have no hard per-job deadline.
- `HIGH-5`: Worker task death is logged but polling continues.

The two findings share the same durable worker boundary, so one scoped fix was
enough. No queue architecture rewrite was needed.

Forbidden areas remained untouched: recipes/data/PDF layout, payment/reversal
provider logic, Telegram UX text, bot process launch, Telegram API/getUpdates,
production DB, real payments/refunds, deploy, push, commit, tag, PR,
secrets/env files, archive, `New project 2 CLEAN`, and recovered bot.

## Root Cause

Durable one-day and weekly PDF workers claimed jobs, started a heartbeat task,
and then awaited the full prepare/send path without a hard job deadline. If
prepare or send hung, the heartbeat kept extending the lease, so the claimed job
could hold a worker slot indefinitely and low-concurrency queues could stop
making progress.

`run_bot()` started durable worker tasks, but unexpected task death was only
observed by a done-callback logger. Polling continued after a worker crash, so
the bot could keep admitting durable jobs while no worker drained them.

## Fix

- `OneDayGenerationWorkerSettings` now has `job_timeout_seconds` with a default
  hard deadline of `900` seconds.
- `WeeklyPdfWorkerSettings` now has `job_timeout_seconds` with a default hard
  deadline of `900` seconds.
- Both workers wrap the full claimed-job prepare/send processing body in
  `asyncio.wait_for(...)`.
- On timeout, the heartbeat is stopped and the existing failure boundary is
  used:
  - before send starts, the job follows existing retry/failure/refund handling;
  - after send starts or partial delivery exists, the job is finalized through
    the existing unknown-delivery/manual-review path.
- `run_bot()` now supervises the polling task and durable worker tasks together.
  If a worker stops unexpectedly while polling is active, polling is cancelled
  and `run_bot()` raises a sanitized fail-fast error instead of continuing to
  admit jobs silently.

## Behavior Before / After

Before:

- A hung one-day or weekly PDF prepare/send could keep extending its lease
  forever.
- With concurrency `1`, the next queued job could wait indefinitely behind the
  hung job.
- A crashed worker task was logged, but polling continued.

After:

- A hung job reaches a hard per-job timeout.
- The heartbeat stops on timeout, and the job is retried, failed/refunded, or
  marked unknown/manual-review according to the existing send state.
- The worker continues to later queued jobs after the timed-out job is handled.
- If a worker dies during polling, `run_bot()` cancels polling and exits
  fail-closed with a sanitized worker-stopped error.
- Normal worker paths still claim and complete jobs.

## Changed Files

- `src/diet_bot/one_day_generation_job_runtime.py`
- `src/diet_bot/weekly_pdf_job_runtime.py`
- `src/diet_bot/telegram_app.py`
  - scoped edit around `run_bot()` worker supervision only; this file already
    contained unrelated dirty working-tree changes before this fix.
- `tests/test_one_day_generation_job_runtime.py`
- `tests/test_weekly_pdf_job_runtime.py`
- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/final-audit-worker-liveness-fix.md`
- `docs/recovery-integration/recovery-status.md`

## Tests

RED before the production fix:

- Command:
  `pytest tests/test_one_day_generation_job_runtime.py::test_worker_times_out_hung_one_day_send_and_continues_next_job tests/test_weekly_pdf_job_runtime.py::test_worker_times_out_hung_weekly_pdf_prepare_and_continues_next_job tests/test_telegram_app_photos.py::test_run_bot_fails_closed_when_one_day_worker_dies_during_polling -q`
- Result:
  `3 failed`.
- Evidence:
  - one-day and weekly worker settings had no `job_timeout_seconds`;
  - `run_bot()` surfaced the original worker exception during shutdown instead
    of the expected sanitized fail-closed supervision error.

GREEN after the fix:

- Same focused command:
  `3 passed in 4.44s`.

Focused worker runtime suites:

- Command:
  `pytest tests/test_one_day_generation_job_runtime.py tests/test_weekly_pdf_job_runtime.py -q`
- Result:
  `43 passed in 5.39s`.

Focused `run_bot` worker supervision and startup paths:

- Command:
  `pytest tests/test_telegram_app_photos.py::test_run_bot_starts_configured_one_day_worker_without_real_polling tests/test_telegram_app_photos.py::test_run_bot_starts_configured_weekly_pdf_worker_without_real_polling tests/test_telegram_app_photos.py::test_one_day_worker_task_exception_is_observed_without_secret_leak tests/test_telegram_app_photos.py::test_run_bot_fails_closed_when_one_day_worker_dies_during_polling tests/test_telegram_app_runtime.py::test_run_bot_postgres_startup_acquires_guard_even_outside_production tests/test_telegram_app_runtime.py::test_run_bot_payment_enabled_validates_payment_runtime_before_bot tests/test_telegram_app_runtime.py::test_run_bot_production_postgres_acquires_guard_before_bot_and_releases -q`
- Result:
  `7 passed in 4.62s`.

Requested broader weekly PDF Postgres wiring:

- Command:
  `pytest tests/test_weekly_pdf_postgres_wiring.py -q`
- Result:
  `25 passed in 4.31s`.

Safe-discovered broader one-day / worker / queue pattern:

- Discovery command:
  `Get-ChildItem -Path tests -File -Filter test_one_day*.py`,
  `Get-ChildItem -Path tests -File -Filter test_*worker*.py`, and
  `Get-ChildItem -Path tests -File -Filter test_*queue*.py`, sorted unique.
- Existing files found:
  - `tests/test_one_day_generation_job_runtime.py`
  - `tests/test_one_day_manual_review_report.py`
- Command:
  `pytest tests/test_one_day_generation_job_runtime.py tests/test_one_day_manual_review_report.py -q`
- Result:
  `31 passed in 4.87s`.

## Proof Gaps / Skips

- No production DB was used.
- No live bot, Telegram API, `getUpdates`, payment provider, real payment, or
  refund action was used.
- DSN-backed Postgres job-store tests were not required for this scoped fix
  because no SQL, schema, migration, or Postgres store code changed. Existing
  Postgres claim SQL already supports reclaiming expired pre-send running jobs;
  this fix prevents the worker heartbeat from extending a hung job forever and
  routes timeout through existing runtime finalization.
- Full `pytest -q` was not run in this scoped prompt.

## Not Done

- Did not fix remaining final-audit high/medium/low findings.
- Did not change recipes/data/PDF layout.
- Did not change payment, reversal, provider, entitlement, subscription, or
  reconciliation logic.
- Did not change Telegram UX text.
- Did not deploy, push, commit, tag, create a PR, edit secrets/env files, touch
  archive, `New project 2 CLEAN`, or recovered bot.

## Verdict

READY FOR RE-AUDIT for `HIGH-4` and `HIGH-5`.
