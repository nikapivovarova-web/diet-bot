# Final Audit MEDIUM-4 Entitlement Lock Fix

## Verdict

MEDIUM-4 is closed locally.

The finding was a real release-risk bug in the durable one-day and weekly PDF
job stores: one-chat admission/start/refund paths used the same global
entitlement advisory lock as whole-map entitlement save/import flows. A slow
transaction holding that global lock could block unrelated chats even when the
other chat's entitlement row was independent.

## Root Cause

- `PostgresEntitlementStore.transact_chat_entitlement()` already bounded normal
  one-chat entitlement mutations with the chat row lock.
- `PostgresOneDayGenerationJobStore` and `PostgresWeeklyPdfJobStore` still took
  `ENTITLEMENT_MAP_LOCK_ID` before durable one-chat consume/refund work.
- That global lock serialized all durable generation admission/start/refund
  paths across users.

## Fix

- Added a deterministic per-chat advisory lock helper in
  `postgres_entitlement_store.py`.
- Updated one-day and weekly PDF durable job store admission/start/refund paths
  to use the per-chat lock for the affected `chat_id`.
- Kept `ENTITLEMENT_MAP_LOCK_ID` only in `PostgresEntitlementStore` whole-map
  `save_all()`, `transact()`, and JSON import flows.
- Added DSN-backed two-chat contention regressions for one-day and weekly PDF
  durable admission while the old global lock is held.

## Verification

- RED:
  `pytest tests/test_postgres_one_day_generation_job_store.py::test_durable_admission_does_not_wait_on_global_entitlement_lock_for_other_chat tests/test_postgres_weekly_pdf_job_store.py::test_durable_admission_does_not_wait_on_global_entitlement_lock_for_other_chat -q`
  with disposable local Postgres: `2 failed`, both blocked by the global
  entitlement advisory lock.
- GREEN:
  same command with disposable local Postgres: `2 passed`.
- Affected Postgres stores:
  `pytest tests/test_postgres_entitlement_store.py tests/test_postgres_one_day_generation_job_store.py tests/test_postgres_weekly_pdf_job_store.py -q`
  with disposable local Postgres: `122 passed`.
- Nearby entitlement layer:
  `pytest tests/test_entitlement_storage.py tests/test_entitlement_service.py -q`
  -> `21 passed`.
- Working-tree whitespace:
  `git diff --check` -> exit code `0`; output contained only existing
  LF-to-CRLF working-copy warnings.

## Scope Boundaries

- No bot process was started.
- No Telegram API, `getUpdates`, production database, provider API, deploy,
  push, commit, tag, PR, archive, `New project 2 CLEAN`, or recovered-bot work
  was done.
- MEDIUM-2 root-level legacy scripts/hard-coded external paths remains open.
- MEDIUM-3 core import cycles remains open.
- Payments/provider/refunds and sales follow-up were not changed.

## Count

Updated local final pre-release audit count: `0 high / 2 medium / 6 low`.
