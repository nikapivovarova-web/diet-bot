# Final Audit Worker Liveness Re-Audit

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Verdict

RE-AUDIT PASSED for the scoped `HIGH-4` and `HIGH-5` worker
liveness/supervision findings.

`HIGH-4` is closed locally. Claimed one-day and weekly PDF worker jobs now have
a hard per-job timeout around the actual processing body, and heartbeat tasks
are stopped in the timeout/failure cleanup path.

`HIGH-5` is closed locally. `run_bot()` now supervises polling and durable
worker tasks together; if a worker stops while polling is active, polling is
cancelled and startup exits fail-closed instead of silently continuing durable
admission.

Updated final-audit count after this re-audit remains:

- `0` blocker
- `3` high
- `4` medium
- `6` low

Production launch is still not approved by this scoped re-audit.

## Validation Rubric

- [x] Per-job timeout wraps the actual claimed-job prepare/send work.
- [x] Timeout stops heartbeat/lease extension and routes through existing
  retry/failure/manual-review finalization.
- [x] Later jobs continue where expected after a timed-out job is finalized.
- [x] Worker death during polling cancels polling and exits fail-closed.
- [x] Normal startup/worker/polling paths and sensitive-error redaction are not
  regressed by the fix.

## Static Evidence

Original findings:

- `HIGH-4` identified no hard per-job deadline and lease extension during hung
  prepare/send work in `final-pre-release-audit.md:260-285`.
- `HIGH-5` identified worker task death being logged while polling continued in
  `final-pre-release-audit.md:287-309`.

One-day worker:

- `OneDayGenerationWorkerSettings.job_timeout_seconds` is present and loaded
  from config at `src/diet_bot/one_day_generation_job_runtime.py:184` and
  `src/diet_bot/one_day_generation_job_runtime.py:206-208`.
- `_process_claimed_job()` starts heartbeat, defines the full processing body,
  and wraps that body in `asyncio.wait_for(...)` at
  `src/diet_bot/one_day_generation_job_runtime.py:281-328`.
- On timeout, it logs only redacted job id and timeout metadata, then calls the
  existing processing-failure path at
  `src/diet_bot/one_day_generation_job_runtime.py:329-341`.
- The `finally` block stops and cancels heartbeat at
  `src/diet_bot/one_day_generation_job_runtime.py:349-353`.
- The failure path sends post-send or partial-delivery cases to the existing
  unknown-delivery/manual-review boundary, and pre-send cases to retry or final
  failure/refund handling at
  `src/diet_bot/one_day_generation_job_runtime.py:403-428`.

Weekly PDF worker:

- `WeeklyPdfWorkerSettings.job_timeout_seconds` is present and loaded from
  config at `src/diet_bot/weekly_pdf_job_runtime.py:163` and
  `src/diet_bot/weekly_pdf_job_runtime.py:188-190`.
- `_process_claimed_job()` starts heartbeat, defines the full prepare/send
  processing body, and wraps it in `asyncio.wait_for(...)` at
  `src/diet_bot/weekly_pdf_job_runtime.py:263-307`.
- On timeout, it logs only redacted job id and timeout metadata, then calls the
  existing processing-failure path at
  `src/diet_bot/weekly_pdf_job_runtime.py:308-315`.
- The `finally` block stops and cancels heartbeat at
  `src/diet_bot/weekly_pdf_job_runtime.py:318-322`.
- The failure path sends post-send or delivered cases to the existing
  unknown-delivery/manual-review boundary, and pre-send cases to retry or final
  failure/refund handling at `src/diet_bot/weekly_pdf_job_runtime.py:372-397`.

`run_bot()` supervision:

- `run_bot()` starts polling as a task and passes polling plus worker tasks into
  `_run_polling_with_worker_supervision(...)` at
  `src/diet_bot/telegram_app.py:1959-1968`.
- `_run_polling_with_worker_supervision(...)` waits for the first completed
  task. If a worker completes before polling, it cancels polling and raises a
  sanitized worker-stopped error at `src/diet_bot/telegram_app.py:1978-1994`.
- `_raise_worker_task_stopped(...)` consumes the original task exception but
  raises only `"{label} stopped unexpectedly"` at
  `src/diet_bot/telegram_app.py:1998-2003`.
- `_cancel_background_task(...)` suppresses cancellation and worker/polling
  shutdown exceptions at `src/diet_bot/telegram_app.py:2015-2025`.
- `_observe_worker_task(...)` logs only label, task name, and exception type,
  not raw exception text, at `src/diet_bot/telegram_app.py:2056-2071`.

## Runtime Evidence

Focused liveness selectors:

- Command:
  `pytest tests/test_one_day_generation_job_runtime.py::test_worker_times_out_hung_one_day_send_and_continues_next_job tests/test_weekly_pdf_job_runtime.py::test_worker_times_out_hung_weekly_pdf_prepare_and_continues_next_job tests/test_telegram_app_photos.py::test_run_bot_fails_closed_when_one_day_worker_dies_during_polling tests/test_telegram_app_photos.py::test_run_bot_starts_configured_one_day_worker_without_real_polling tests/test_telegram_app_photos.py::test_run_bot_starts_configured_weekly_pdf_worker_without_real_polling tests/test_telegram_app_photos.py::test_one_day_worker_task_exception_is_observed_without_secret_leak -q`
- Result: `6 passed in 4.77s`.
- Artifact:
  `tmp/final-audit-worker-liveness-reaudit/pytest-focused-liveness-selectors.txt`.

One-day and weekly worker runtime suites:

- Command:
  `pytest tests/test_one_day_generation_job_runtime.py tests/test_weekly_pdf_job_runtime.py -q`
- Result: `43 passed in 5.38s`.
- Artifact:
  `tmp/final-audit-worker-liveness-reaudit/pytest-one-day-weekly-runtime.txt`.

Telegram app photo/runtime suite:

- Command:
  `pytest tests/test_telegram_app_photos.py -q`
- Result: `151 passed in 17.70s`.
- Artifact:
  `tmp/final-audit-worker-liveness-reaudit/pytest-telegram-app-photos.txt`.

Weekly PDF Postgres wiring:

- Command:
  `pytest tests/test_weekly_pdf_postgres_wiring.py -q`
- Result: `25 passed in 4.59s`.
- Artifact:
  `tmp/final-audit-worker-liveness-reaudit/pytest-weekly-pdf-postgres-wiring.txt`.

Safe-discovered one-day/worker/queue tests:

- Discovery found:
  - `tests/test_one_day_generation_job_runtime.py`
  - `tests/test_one_day_manual_review_report.py`
- Command:
  `pytest tests/test_one_day_generation_job_runtime.py tests/test_one_day_manual_review_report.py -q`
- Result: `31 passed in 5.37s`.
- Artifacts:
  - `tmp/final-audit-worker-liveness-reaudit/safe-discovered-one-day-worker-queue-tests.txt`
  - `tmp/final-audit-worker-liveness-reaudit/pytest-safe-discovered-one-day-worker-queue.txt`

Additional temporary weekly post-send timeout harness:

- Command:
  `pytest tmp/final-audit-worker-liveness-reaudit/test_weekly_hung_send_timeout.py -q`
- Result: `1 passed in 3.96s`.
- What it proves:
  - a weekly PDF send that hangs after `mark_send_started()` reaches the
    per-job timeout;
  - the existing post-send unknown-delivery/manual-review path is used via
    `finish_failure_and_refund_once`;
  - `delivery_status` is `unknown`;
  - `requires_manual_review` is `True`;
  - no heartbeat lease extension remains active for the hung job.
- Artifacts:
  - `tmp/final-audit-worker-liveness-reaudit/test_weekly_hung_send_timeout.py`
  - `tmp/final-audit-worker-liveness-reaudit/pytest-weekly-hung-send-timeout-harness.txt`

Final diff hygiene:

- Command: `git diff --check`
- Result: exit code `0`; output contained LF-to-CRLF working-copy warnings only.
- Artifact:
  `tmp/final-audit-worker-liveness-reaudit/git-diff-check.txt`.

## DSN / External-Service Boundary

No DSN-backed Postgres job-store run was required for this scoped re-audit.
The fix changes worker runtime timeouts and `run_bot()` supervision, not SQL,
schema, migrations, Postgres claim predicates, or production DB state. The
weekly PDF Postgres wiring suite passed locally, and the timeout behavior was
validated through in-memory worker runtime tests plus a temporary harness under
`tmp`.

No production DB, real bot, Telegram API, `getUpdates`, webhook, provider,
payment, refund, deploy, push, commit, tag, or PR was used.

## Changed Files In This Re-Audit

- `docs/recovery-integration/final-audit-worker-liveness-reaudit.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/final-audit-worker-liveness-reaudit/**`

No application code, data, config, env file, secret, payment logic, recipe data,
Telegram UX text, archive, `New project 2 CLEAN`, or recovered bot file was
changed.

## Remaining Findings

The scoped worker liveness findings are closed, but final pre-release audit
still has:

- `0` blocker
- `3` high
- `4` medium
- `6` low

Next recommended prompt:

```text
FoodBalance: fix only the next explicit final pre-release audit high finding.

Use:
- docs/recovery-integration/final-pre-release-audit.md
- docs/recovery-integration/recovery-status.md

Stay inside the selected finding scope. Do not run the real bot, touch
Telegram API/getUpdates, use production DB, perform payment/refund/provider
actions, deploy, push, commit, tag, PR, or touch archive, New project 2 CLEAN,
or recovered bot.
```
