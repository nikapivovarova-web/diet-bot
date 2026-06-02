# Stage 7 - Hardening Preservation Audit

## Verdict

Master hardening remains preserved after the product data, PDF, Telegram UI, payments, and builder transfers. The product changes did not replace the hardened runtime foundation, and the Stage 5 payment metadata changes were additive.

## Audit Checklist

- PostgreSQL storage remains the production path.
  - `runtime_config` still defaults production storage to `postgres`.
  - production startup still rejects JSON storage.
  - chat state, entitlement, payment, one-day job, and weekly PDF job Postgres modules are present.
- JSON storage is not the default publish path.
  - JSON remains local/development fallback only.
  - production tests still assert JSON rejection.
- Runtime safety remains enforced.
  - startup validation still checks bot token, Postgres database URL, support chat ID, privacy URL, worker/storage compatibility, payment recovery spool, public payment flag dependency, and test-price flag production rejection.
- Healthcheck remains available.
  - `python -m diet_bot.healthcheck` ran successfully with a dummy local token and reported `issues: none`.
- Durable queues/recovery remain present and wired.
  - one-day generation and weekly PDF Postgres job stores are present.
  - payment recovery spool and replay modules are present and importable.
- Monitoring/preflight remains present.
  - `production_preflight`, `postgres_schema_validation`, and runtime preflight tests remain in place.
- Telegram private-chat/callback/media hardening remains present.
  - private chat guard text and callback owner/session token smoke tests pass.
  - local Telegram media validation module is present and tested.
- Payment durability/idempotency is not bypassed.
  - `PaymentService`, `PostgresPaymentStore`, payment recovery spool/replay, reconciliation, and idempotent grant tests pass.
  - Stage 5 managed Stars metadata is persisted through Postgres entitlement, payment, one-day job, and weekly PDF job store paths.

## Inspected Changes

`git diff --name-status origin/master` was inspected for the integration working tree. Hardening-related touched files are limited to additive runtime/payment metadata support and Telegram UI/payment wiring:

- `src/diet_bot/runtime_config.py`
- `src/diet_bot/postgres_entitlement_migrations.py`
- `src/diet_bot/postgres_entitlement_store.py`
- `src/diet_bot/postgres_payment_store.py`
- `src/diet_bot/postgres_one_day_generation_job_store.py`
- `src/diet_bot/postgres_weekly_pdf_job_store.py`
- `src/diet_bot/telegram_app.py`

No hardening modules were deleted or replaced.

## Safe Checks Run

- `pytest tests/test_runtime_config.py tests/test_production_preflight.py tests/test_healthcheck.py tests/test_postgres_schema_validation.py tests/test_postgres_migration_versions.py tests/test_payment_runtime.py tests/test_payment_recovery_spool.py tests/test_payment_recovery_replay.py tests/test_payment_reconciliation_report.py tests/test_payment_service.py tests/test_telegram_app_runtime.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_media_validation.py -q`
  - `187 passed`
- `pytest tests/test_postgres_payment_store.py tests/test_postgres_entitlement_store.py tests/test_postgres_one_day_generation_job_store.py tests/test_postgres_weekly_pdf_job_store.py tests/test_postgres_runtime_preflight.py tests/test_postgres_single_poller_guard.py tests/test_postgres_connection.py tests/test_weekly_pdf_postgres_wiring.py -q`
  - first pass found two test-double failures from missing Stage 5 entitlement metadata columns
  - after updating the fake cursor schema: `100 passed, 98 skipped`
- `python -m diet_bot.healthcheck`
  - ran with a dummy local `DIET_BOT_TOKEN`
  - reported `issues: none`
- hardening module import check
  - imported 14 runtime/storage/recovery/preflight/media modules successfully
- hardening module existence check
  - confirmed expected runtime, healthcheck, preflight, recovery, payment, Postgres, and media validation modules exist

## Skipped / Not Run

- Real Postgres integration tests were skipped where they require `DIET_BOT_TEST_DATABASE_URL`.
- No live Telegram polling/webhook was started.
- No real payment API, capture, refund, chargeback, or reconciliation against live credentials was run.
- No deploy, push, PR, tag, or commit was performed.

## Open Risks

- A disposable test Postgres database is still needed for full Postgres integration coverage.
- Live Telegram and payment sandbox smoke remain manual approval gates before publish.
