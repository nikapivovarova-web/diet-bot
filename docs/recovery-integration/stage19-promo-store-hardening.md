# Stage 19.2B-19.2E Promo Postgres Store Hardening

## Scope Completed

Stage 19.2B added the Postgres promo schema/store foundation and tests. Stage 19.2C wires the user monthly-access promo activation path to the Postgres promo store when `DIET_BOT_STORAGE_BACKEND=postgres`. Stage 19.2D wires the existing `/330366` admin promo menu create/list/disable actions to the Postgres promo store for the postgres storage path. Stage 19.2E adds the production preflight promo schema gate, restore-drill promo table coverage, and production runbook procedures for promo migration/import/backup/restore.

Sales follow-up, `FOOD20`, payment order discount wiring, payment/subscription semantics, PDF/recipe data, deploy, bot startup, git publishing, and archive/recovered-bot files were not touched.

## Schema Added

New promo migration module:

- `src/diet_bot/postgres_promo_migrations.py`

Tables:

- `promo_codes`
  - normalized `code` primary key;
  - `kind`, `discount_type`, `discount_percent`, `discount_amount_minor`;
  - `duration_days`, `monthly_duration_months`;
  - `max_uses`, `per_user_limit`;
  - `expires_at`, `active`, audit timestamps, `created_by`, disable audit fields;
  - `campaign_key`, `metadata_json`;
  - check constraints for non-empty codes, supported kinds, discount shape, limits, and duration.
- `promo_code_redemptions`
  - `redemption_id` primary key;
  - `code` FK to `promo_codes`;
  - `chat_id`, `user_id`, redemption lifecycle timestamps and status;
  - nullable payment/order/grant/campaign metadata fields;
  - `idempotency_key`, `entitlement_charge_id`, source, metadata JSON;
  - unique idempotency key, unique nullable payment order and entitlement charge indexes, and a non-unique `(code, chat_id, status, created_at)` lookup index. Duplicate-chat protection is enforced transactionally from `per_user_limit`, not by a hard one-row uniqueness constraint.
- `promo_import_runs`
  - import audit table for JSON-state migration/import runs.

Schema validation is defined in `PROMO_SCHEMA_EXPECTATION` in `src/diet_bot/postgres_promo_store.py`, covering tables, columns, indexes, constraints, and promo migration versions `202605300001` and `202605310002`.

## Store API Added

New store module:

- `src/diet_bot/postgres_promo_store.py`

Store methods:

- `initialize()`
- `validate_schema()`
- `create_or_update_promo_code()`
- `update_promo_code()`
- `get_promo_code()`
- `list_active_promo_codes()`
- `disable_promo_code()`
- `redeem_promo_code()`
- `reserve_promo_code()`
- `finalize_promo_redemption()`
- `release_promo_redemption()`
- `get_redemption_status()`
- `import_json_state()`

Redemption/reservation locks the promo row with `FOR UPDATE`, checks kind/active/expiry/max-use state inside the transaction, returns an idempotent existing redemption for the same idempotency key, enforces `per_user_limit` per `(code, chat_id)` across active `reserved`/`redeemed` rows, and prevents total active redemptions from exceeding `max_uses`.

JSON import preserves existing JSON model fields through `PromoCodeRecord`, including active/disabled state, expiry, discount fields, monthly duration, and `used_by_chat_id`/`used_at` as `promo_code_redemptions.status='redeemed'` with `source='json_import'`.

## Activation Wiring

Telegram `_activate_promo_code_for_chat()` now branches on runtime storage backend:

- JSON/local path remains unchanged and still uses `activate_promo_code()` plus the existing best-effort JSON rollback.
- Postgres path lazy-loads `PostgresPromoStore`, so JSON startup/import paths do not import psycopg/Postgres modules.
- Postgres path reserves a `monthly_access` promo with stable idempotency key `promo:{CODE}:chat:{CHAT_ID}:activation` and entitlement charge id `promo:{CODE}`.
- Store rejection statuses map back to existing user-facing activation statuses: `not_found`, `disabled`, `expired`, `not_access_code`, and `already_used`.
- Same-chat duplicate active redemption returns `already_used` and does not call entitlement grant again.
- Successful reservation grants the existing monthly subscription entitlement through `EntitlementService.apply_subscription_payment()` with the same promo charge id, then finalizes the promo redemption as `redeemed`.
- If entitlement grant fails after reservation, Telegram attempts to release the reserved redemption with failure reason `entitlement_grant_failed`, then raises the existing entitlement storage error so the user can retry.

Consistency behavior for 19.2C is fail-safe rather than fully atomic across stores. Promo reservation/finalization and entitlement grant are still separate store transactions. If the process crashes after reservation but before grant/release, the active reserved redemption prevents double use and may require operator repair before retry. If entitlement grant succeeds but redemption finalization fails, the entitlement remains granted and the active reserved redemption prevents a second grant on retry. A fully shared Postgres transaction across promo and entitlement stores remains deferred.

Corrupt or missing JSON promo state is ignored on the Postgres activation path and does not wipe or rewrite runtime Postgres promo state.

## Admin Menu Wiring

The existing `/330366` admin promo panel now branches on runtime storage backend:

- JSON/local path remains the fallback and keeps the existing JSON admin create/list/disable behavior.
- Postgres path lazy-loads `PostgresPromoStore`, just like user activation, and does not call JSON `load_promo_codes()` or `save_promo_codes()`.
- Admin monthly access creation inserts a `monthly_access` promo with `max_redemptions=1`, `per_user_limit=1`, `monthly_duration_months=1`, `created_by=<admin user id>`, and admin-menu metadata.
- Admin-created monthly access codes are redeemable through the Stage 19.2C Postgres activation path.
- Existing discount create/update maps the supported `CODE PERCENT` UI to a Postgres `discount` promo, preserving existing discount row limits/expiry when updating.
- Existing discount list reads active, unexpired discount promos from Postgres.
- Existing discount disable checks that the code is a discount promo, then disables it through Postgres with `disabled_by=<admin user id>`.
- Bare `/330366` no longer falls through to the old status path for non-admins; non-admins receive the existing admin-only rejection.

## Preflight, Runbook, And Restore Drill

Production preflight now includes a `promo schema` check after the durable job schema checks and before payment ledger validation. The check lazy-loads `PostgresPromoStore` and runs `validate_schema()`, so production Postgres preflight fails closed if `promo_codes`, `promo_code_redemptions`, `promo_import_runs`, promo migration versions `202605300001` and `202605310002`, or critical promo indexes/constraints are missing. Controlled QA preflight runs the same promo schema validator against its isolated Postgres database.

The explicit restore-drill required table list now includes:

- `promo_codes`
- `promo_code_redemptions`
- `promo_import_runs`

The production runbook now documents:

- production promo runtime must be Postgres-backed when production storage is Postgres;
- `.diet_bot_state/promo_codes.json` is a pre-cutover backup source, import seed, or local fallback only, not production source of truth;
- promo store migrations run through `PostgresPromoStore("<postgres-dsn>").initialize()`;
- reviewed JSON import must preserve used state as `promo_code_redemptions.status='redeemed'`, record `promo_import_runs`, check source fingerprint/counts, and fail closed on corrupt JSON;
- backup/restore drill evidence must include promo tables and row-count comparison when source comparison is enabled;
- `FOOD20` must not be seeded or enabled until later campaign approval.

## Tests

Stage 19.2E RED before implementation:

- `pytest tests/test_production_preflight.py::test_production_preflight_success_reports_pass_and_uses_existing_validators tests/test_production_preflight.py::test_production_preflight_reports_missing_promo_schema_without_printing_dsn tests/test_production_preflight.py::test_restore_drill_required_tables_include_promo_tables tests/test_production_preflight.py::test_runbook_documents_promo_store_migration_import_and_restore -q`
  - `4 failed`
  - failures showed production preflight had no promo schema validator, restore-drill required tables omitted promo tables, and the runbook lacked promo migration/import/restore instructions.

GREEN after Stage 19.2E implementation:

- `pytest tests/test_production_preflight.py tests/test_postgres_migration_versions.py -q`
  - `24 passed`
- `pytest tests/test_healthcheck.py -q`
  - `12 passed`
- `pytest tests/test_promo_codes.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `46 passed`
- `pytest tests/test_postgres_restore_drill_ops.py -q`
  - `16 passed, 1 skipped`
  - skipped case requires `DIET_BOT_TEST_DATABASE_URL`.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

Stage 19.2D RED before implementation:

- `pytest tests/test_telegram_app_runtime.py::test_postgres_admin_monthly_code_uses_store_and_can_be_redeemed tests/test_telegram_app_runtime.py::test_postgres_admin_discount_create_list_and_disable_use_store_not_json tests/test_telegram_app_runtime.py::test_json_admin_discount_flow_remains_fallback tests/test_telegram_user_journeys_smoke.py::test_non_admin_330366_does_not_open_admin_promo_panel -q`
  - `4 failed`
  - failures showed admin helpers still had no admin audit argument/Postgres branch and bare non-admin `/330366` still fell through to status.

Stage 19.2C RED before implementation:

- `pytest tests/test_telegram_app_runtime.py::test_postgres_promo_activation_uses_store_without_json_save tests/test_telegram_app_runtime.py::test_postgres_promo_activation_maps_store_rejections tests/test_telegram_app_runtime.py::test_postgres_promo_duplicate_activation_does_not_grant_twice tests/test_telegram_app_runtime.py::test_postgres_promo_activation_ignores_corrupt_json_state tests/test_postgres_promo_store.py::test_store_api_surface_is_ready_for_future_wiring -q`
  - `9 failed, 1 passed`
  - failures showed activation still using JSON and `PostgresPromoStore` missing finalize/release methods.

Stage 19.2B RED before implementation:

- `pytest tests/test_postgres_promo_store.py -q`
  - failed at collection with `ModuleNotFoundError: No module named 'diet_bot.postgres_promo_migrations'`, as expected because the store/migration module did not exist yet.

GREEN after Stage 19.2C implementation:

- Targeted 19.2C regression:
  `pytest tests/test_telegram_app_runtime.py::test_postgres_promo_activation_uses_store_without_json_save tests/test_telegram_app_runtime.py::test_postgres_promo_activation_maps_store_rejections tests/test_telegram_app_runtime.py::test_postgres_promo_duplicate_activation_does_not_grant_twice tests/test_telegram_app_runtime.py::test_postgres_promo_activation_ignores_corrupt_json_state tests/test_postgres_promo_store.py::test_store_api_surface_is_ready_for_future_wiring -q`
  - `10 passed`

- `pytest tests/test_promo_codes.py -q`
  - `11 passed`
- `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `31 passed`
- `pytest tests/test_postgres_promo_store.py -q`
  - `2 passed, 7 skipped`
  - skipped cases require `DIET_BOT_TEST_DATABASE_URL`.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

GREEN after Stage 19.2D implementation:

- Targeted 19.2D regression:
  `pytest tests/test_telegram_app_runtime.py::test_postgres_admin_monthly_code_uses_store_and_can_be_redeemed tests/test_telegram_app_runtime.py::test_postgres_admin_discount_create_list_and_disable_use_store_not_json tests/test_telegram_app_runtime.py::test_json_admin_discount_flow_remains_fallback tests/test_telegram_user_journeys_smoke.py::test_non_admin_330366_does_not_open_admin_promo_panel -q`
  - `4 passed`
- `pytest tests/test_promo_codes.py -q`
  - `11 passed`
- `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `35 passed`
- `pytest tests/test_postgres_promo_store.py -q`
  - `2 passed, 7 skipped`
  - skipped cases require `DIET_BOT_TEST_DATABASE_URL`.

Stage 19.2F DSN-backed verification:

- `DIET_BOT_TEST_DATABASE_URL` was not pre-set in the shell.
- Used a disposable local Docker Postgres database named `diet_bot_test`, bound to `127.0.0.1` on an ephemeral port. The DSN lived only in the test process environment and was not written to any secrets or env files.
- Initial DSN restore-drill run exposed a real integration fixture gap: the live restore source fixture initialized the required entitlement/chat/job/payment schemas but not the newly required promo schema, so restore verification reported missing `promo_codes`, `promo_code_redemptions`, and `promo_import_runs`.
- Fixed the fixture in `tests/test_postgres_restore_drill_ops.py` by initializing `PostgresPromoStore` and seeding one row in each required promo table for source/restore row-count comparison.
- Final DSN-backed rerun:
  - `pytest tests/test_postgres_promo_store.py -q`
    - `9 passed`
  - `pytest tests/test_production_preflight.py -q`
    - `23 passed`
  - `pytest tests/test_postgres_restore_drill_ops.py -q`
    - `17 passed`
  - `git diff --check`
    - exit code `0`
    - output contained existing LF-to-CRLF working-copy warnings only.
- Disposable database/container and temporary client-tool wrappers were removed after the run.

## Not Wired

Still not wired by design:

- payment order discount reservation or payment-success discount redemption finalization;
- `FOOD20` seed/enablement;
- strict operator script for JSON-file-to-Postgres migration.
- sales follow-up promo campaign behavior.

The existing JSON promo flow remains in place for local/dev fallback and admin JSON menu paths. It was not removed. Production/postgres preflight and restore-drill table expectations are wired and have now passed DSN-backed verification against a disposable test database.

## Remaining Stages

- Stage 19.3: proceed to one-day `to_thread` hardening or a separately approved discount payment-flow/campaign stage.
- `FOOD20` remains disabled until explicit later approval after DSN-backed verification and discount payment-flow approval.

## DSN Verification Status

Stage 19.2F closed the DSN caveat for promo store hardening, production preflight coverage, and restore-drill promo table comparison. The verification used only a disposable local test database with an explicit test name. It did not use production DB, launch the bot, deploy, push, commit, tag, open a PR, seed/enable `FOOD20`, or change sales/payment/PDF/recipe behavior.
