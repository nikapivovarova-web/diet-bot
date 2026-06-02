# Final Audit Low Privacy Consent Durability

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Verdict

Closed locally with a narrow fix.

Updated local final pre-release audit count: `0 high / 0 medium / 1 low`.

## Classification

The low finding was real. Round 2 intentionally kept consent acceptance in
process memory, which was acceptable for the UX-only consent gate but did not
provide durable acceptance evidence across restart.

Docs-only closure was not used because there is no fresh release-owner
acceptance of consent evidence as an RC limitation. A narrow fix was safe
because the existing chat-state abstraction already persists per-chat profile
and recipe-history state in both JSON and Postgres backends.

## Root Cause

Consent acceptance was stored only in `PRIVACY_CONSENT_CHAT_IDS`. The
questionnaire checked that process-local set before collecting answers, but no
acceptance record was written through `JsonChatStateStore` or
`PostgresChatStateStore`.

## Fix

- Chat-state normalization now preserves a `privacy_consent` record with:
  `accepted`, `accepted_at`, `text_sha256`, optional `policy_url`, and
  `schema_version`.
- JSON chat-state writes persist that record in the existing state file.
- Postgres chat-state storage now has one minimal table:
  `chat_privacy_consents`.
- Accepting consent writes the durable record before starting the questionnaire.
- If consent persistence fails, the bot fails closed and does not start
  questionnaire collection.
- After restart, the bot can load durable consent from chat state and skip the
  consent screen for that chat.

## Tests

RED before the fix:

- `PYTHONPATH=src python -m pytest tests/test_chat_state_storage.py::test_valid_state_roundtrips_profile_and_history tests/test_telegram_user_journeys_smoke.py::test_privacy_consent_acceptance_continues_to_first_question tests/test_telegram_user_journeys_smoke.py::test_privacy_consent_acceptance_is_loaded_from_chat_state_after_restart tests/test_telegram_user_journeys_smoke.py::test_privacy_consent_save_failure_does_not_start_questionnaire -q`
  - `4 failed`

GREEN after the fix:

- Same focused command:
  - `4 passed`
- `PYTHONPATH=src python -m pytest tests/test_chat_state_storage.py -q`
  - `10 passed`
- `PYTHONPATH=src python -m pytest tests/test_telegram_user_journeys_smoke.py -q`
  - `14 passed`
- `PYTHONPATH=src python -m pytest tests/test_telegram_app_photos.py::test_private_callback_start_shows_privacy_consent_before_questionnaire tests/test_telegram_app_photos.py::test_repeated_start_clears_active_trial_questionnaire_state tests/test_telegram_app_photos.py::test_support_callback_starts_request_mode -q`
  - `3 passed`
- `PYTHONPATH=src python -m pytest tests/test_telegram_app_runtime.py -k "chat_state or privacy" -q`
  - `3 passed, 41 deselected`
- `PYTHONPATH=src python -m pytest tests/test_postgres_chat_state_store.py -q`
  - `16 skipped` because `DIET_BOT_TEST_DATABASE_URL` is not set in this shell.
- `PYTHONPATH=src python -m pytest tests/test_postgres_weekly_pdf_job_store.py::test_weekly_then_chat_state_migrations_create_both_schemas -q`
  - `1 skipped` because `DIET_BOT_TEST_DATABASE_URL` is not set in this shell.
- `PYTHONPATH=src python -m pytest tests/test_postgres_restore_drill_ops.py::test_verify_restored_database_output_shape_includes_required_and_payment_counts tests/test_postgres_restore_drill_ops.py::test_required_restore_tables_include_one_day_payment_and_schema_migrations -q`
  - `2 passed`
- `PYTHONPATH=src python -m pytest tests/test_production_preflight.py::test_production_preflight_reports_missing_schema_without_printing_dsn -q`
  - `1 passed`
- `PYTHONPATH=src python -m compileall -q src/diet_bot/chat_state_storage.py src/diet_bot/postgres_chat_state_migrations.py src/diet_bot/postgres_chat_state_store.py src/diet_bot/telegram_app.py scripts/ops/postgres_restore_drill.py`
  - exit code `0`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

## Scope Boundaries

- No promo `per_user_limit` change.
- No payment/provider/refund behavior change.
- No sales follow-up behavior change.
- No recipe data, import, or photo change.
- No bot process, Telegram API, `getUpdates`, production database,
  provider/live payment smoke, deploy, push, commit, tag, PR, archive,
  `New project 2 CLEAN`, or recovered-bot path was used.

## Remaining Low Finding

- Promo `per_user_limit` semantics before enabling multi-use discount
  campaigns such as `FOOD20`.

## Next Recommended Prompt

FoodBalance: resolve only the promo `per_user_limit` low finding. Do not touch
privacy consent, payments/provider/refunds, sales follow-up, recipe data/import
or photos, bot startup, Telegram API/getUpdates, production DB, live payment
smoke, deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or the
recovered bot.
