# FoodBalance Recovery Integration Status

## Current Stage

Stage 20F final full verification rerun completed. The full pytest suite passed
with disposable local Postgres coverage, final targeted smoke commands passed,
and the integration state is ready for an explicitly approved manual-smoke bot
restart. Bot, deploy, push, commit, tag, PR, payment/refund/chargeback,
secrets/env-file, archive, `New project 2 CLEAN`, and recovered-bot work remain
untouched.

## Completed Items

- Stage 1: diff map completed.
- Stage 2: product data/assets transferred.
- Stage 3: PDF renderer/branding transferred.
- Stage 4: Telegram UI/product copy/buttons/onboarding/paywall appearance transferred.
- Stage 5: payments/promo/subscriptions transferred onto hardened master payment runtime.
- Stage 6: builder/selection flexible-slot avoidance and deterministic variety edge case fixed.
- Stage 7: hardening preservation audit completed.
- Stage 8: full safe local verification completed.
- Stage 9: final readiness report completed.
- Round 2 QA2-005: privacy consent flow fixed and verified without PDF, recipe, payment, runtime, deploy, or bot-process work.
- Round 2 QA2-002: PDF photo/layout consistency fixed and verified without privacy, recipe-data, payment, runtime, deploy, or bot-process work.
- Round 2 QA2-001/QA2-003/QA2-004: recipe-content audit completed and documented without recipe-data, PDF, Telegram, payment, runtime, deploy, or bot-process work.
- Round 2 QA2-003/QA2-004: high-suspicion recipe batch fixed and verified without PDF, Telegram/privacy/questionnaire, payment, runtime, storage, deploy, or bot-process work.
- Round 2 QA2-001: approximate-measures batch fixed confident common gram-only rows and verified without PDF, Telegram/privacy/questionnaire, payment, runtime, storage, deploy, or bot-process work.
- Round 2 stale Telegram photo/menu tests: stale promo/privacy/support keyboard and command expectations fixed and verified without production code, recipe/data, PDF, payment, runtime, storage, deploy, or bot-process work.
- Stage 16 Telegram UX quick fixes completed: duplicate weekly PDF generation notice removed, calculation copy added, per-meal KBJU displayed from `Meal.nutrients`, and free-ration offer copy updated.
- Stage 17 PDF layout v2 completed: day labels restored on recipe and shopping pages, recipe photos now use one fixed right-column layout, centered photo fallback removed, and long recipes continue below the photo block or on later pages.
- Stage 18A sales follow-up chain design completed without production code, payment, promo, runtime, storage, Telegram/PDF/recipe, bot, deploy, git, or archive work.
- Stage 19.1 B-1 worker guard completed: production Postgres startup/preflight fixtures now include both durable worker flags where the tests expect valid production config, while missing-flag guard assertions remain fail-closed.
- Stage 19.2A promo-store hardening design completed without production code, tests, promo JSON/data, payments/runtime/storage, bot, deploy, git, or archive work.
- Stage 19.2B promo Postgres schema + store foundation completed without Telegram activation/admin menu, payment/subscription semantics, sales follow-up, `FOOD20`, bot, deploy, push, commit, tag, PR, archive, or recovered-bot work.
- Stage 19.2C user promo activation wiring completed for the Postgres runtime path without admin menu wiring, sales follow-up, `FOOD20`, payment/subscription semantics beyond promo activation source, PDF/recipe data, bot, deploy, push, commit, tag, PR, archive, or recovered-bot work.
- Stage 19.2D admin promo menu wiring completed for the Postgres runtime path without sales follow-up, `FOOD20`, payment/subscription semantics, PDF/recipe data, bot, deploy, push, commit, tag, PR, archive, or recovered-bot work.
- Stage 19.2E promo production preflight, runbook, and restore-drill gates completed without sales follow-up, `FOOD20`, Telegram activation/admin behavior changes, payment/subscription semantics, PDF/recipe data, bot, deploy, push, commit, tag, PR, archive, or recovered-bot work.
- Stage 19.2F DSN-backed promo verification completed with a disposable local `diet_bot_test` Postgres database. A real restore-drill fixture gap was fixed so the live source initializes and seeds required promo tables; no production DB, bot, deploy, push, commit, tag, PR, archive, recovered-bot, `FOOD20`, sales/payment/PDF/recipe behavior, or secrets/env-file work was done.
- Stage 19.3 M-1 one-day worker `to_thread` completed: queued one-day delivery now offloads the CPU-bound daily planner with `asyncio.to_thread`, with no promo, PDF, recipe-data, payment/subscription, sales follow-up, bot, deploy, git, archive, `New project 2 CLEAN`, or recovered-bot work.
- Stage 19.4 env example / deploy config hygiene completed: `.env.example`
  now covers production Postgres, worker flags, payment placeholders,
  Postgres promo-store requirement, privacy/support, monitoring/ops, and
  local/dev-only vars without real secrets; no runtime behavior, Telegram UX,
  payments, promo logic, PDF, recipe data, sales follow-up, bot, deploy, git,
  archive, `New project 2 CLEAN`, or recovered-bot work was done.
- Stage 20A verification blocker fixed: the production startup guard test now
  stubs and asserts worker start hooks instead of constructing real durable
  worker runtimes from `postgresql://user:secret@example/db`; no production
  code, bot, deploy, payment, PDF, recipe data, secrets/env-file, archive,
  `New project 2 CLEAN`, or recovered-bot work was done.
- Stage 20C payment-store blocker fixed: stale `400 XTR` subscription
  expectations in Postgres payment-store tests were aligned to the current
  `450 XTR` product price via `expected_payment_price(...)`; no production
  payment code, PDF, recipe/data, Telegram UI, promo, runtime/preflight worker,
  weekly PDF, bot, deploy, secrets/env-file, archive, `New project 2 CLEAN`, or
  recovered-bot work was done.
- Stage 20D runtime-preflight worker-flags blocker fixed: stale valid
  production/Postgres fixture in the Postgres runtime-preflight integration test
  now includes `DIET_BOT_ONE_DAY_WORKER_ENABLED=1` and
  `DIET_BOT_WEEKLY_PDF_WORKER_ENABLED=1`; B-1 production worker guard remains
  fail-closed.
- Stage 20E weekly PDF accepted-text blocker fixed: stale durable Postgres
  admission-only expectation no longer requires the separate accepted-text
  message removed in Stage 16; the old duplicate weekly PDF text remains absent.
- Stage 20F final full verification rerun completed with full DSN-backed pytest
  coverage, final recipe/PDF/runtime/preflight smoke checks, and
  `git diff --check`; no blocker was found.

## Changed Files

Stage 2 data/assets:

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/foodbalance_pdf_logo.png`
- `src/diet_bot/data/foodbalance_pdf_qr.png`
- `src/diet_bot/data/recipe_photos/r401.jpg` through `r610.jpg`
- `tests/test_curated_recipe_data.py`
- `tests/test_recipe_traits.py`

Stage 3 PDF:

- `src/diet_bot/pdf_renderer.py`
- `tests/test_pdf_renderer.py`
- `scripts/dev/pdf_renderer_recovery_smoke.py`

Stage 4 Telegram UI:

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/presentation.py`
- `src/diet_bot/questionnaire.py`
- `tests/test_questionnaire_and_presentation.py`
- `tests/test_telegram_user_journeys_smoke.py`
- `tests/test_telegram_callback_owner_smoke.py`

Round 2 QA2-005 privacy-only:

- `src/diet_bot/telegram_app.py` (privacy consent flow present in current dirty state)
- `tests/test_telegram_user_journeys_smoke.py`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 QA2-002 PDF-only:

- `src/diet_bot/pdf_renderer.py`
- `tests/test_pdf_renderer.py`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 QA2-001/QA2-003/QA2-004 recipe-audit-only:

- `scripts/dev/recipe_content_audit.py`
- `docs/recovery-integration/recipe-content-audit-round2.md`
- `docs/recovery-integration/recipe-content-audit-round2-findings.csv`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 QA2-003/QA2-004 high-suspicion recipe fixes:

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_recipes.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/recipe-content-audit-round2.md`
- `docs/recovery-integration/recipe-content-audit-round2-findings.csv`
- `docs/recovery-integration/recipe-fixes-round2.md`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 QA2-001 approximate-measures batch:

- `src/diet_bot/data/curated_recipe_ingredients.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/approximate-measures-round2.md`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 stale Telegram photo/menu tests:

- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/recovery-status.md`

Stage 16 Telegram UX quick fixes:

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/presentation.py`
- `tests/test_questionnaire_and_presentation.py`
- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/stage16-telegram-ux-fixes.md`
- `docs/recovery-integration/recovery-status.md`

Stage 17 PDF layout v2:

- `src/diet_bot/pdf_renderer.py`
- `tests/test_pdf_renderer.py`
- `docs/recovery-integration/stage17-pdf-layout-v2.md`
- `docs/recovery-integration/recovery-status.md`

Stage 18A sales follow-up chain design:

- `docs/recovery-integration/stage18-sales-followup-design.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.1 B-1 worker guard:

- `tests/test_runtime_config.py`
- `tests/test_production_preflight.py`
- `docs/recovery-integration/stage19-worker-guard.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2A promo-store hardening design:

- `docs/recovery-integration/stage19-promo-store-hardening-design.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2B promo Postgres schema + store:

- `src/diet_bot/postgres_promo_migrations.py`
- `src/diet_bot/postgres_promo_store.py`
- `tests/test_postgres_promo_store.py`
- `tests/test_postgres_migration_versions.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2C user promo activation wiring:

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/postgres_promo_store.py`
- `tests/test_telegram_app_runtime.py`
- `tests/test_postgres_promo_store.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2D admin promo menu wiring:

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `tests/test_telegram_user_journeys_smoke.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2E promo preflight/runbook/restore-drill:

- `src/diet_bot/production_preflight.py`
- `scripts/ops/postgres_restore_drill.py`
- `docs/production-runbook.md`
- `tests/test_production_preflight.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2F DSN-backed promo verification:

- `tests/test_postgres_restore_drill_ops.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.3 one-day worker `to_thread`:

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/stage19-one-day-to-thread.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.4 env example / deploy config hygiene:

- `.env.example`
- `docs/production-runbook.md`
- `tests/test_production_deploy_files.py`
- `docs/recovery-integration/stage19-env-example.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20A verification blocker:

- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/stage20-verification-blocker.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20C payment-store blocker:

- `tests/test_postgres_payment_store.py`
- `docs/recovery-integration/stage20-payment-store-blocker.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20D runtime-preflight worker-flags blocker:

- `tests/test_postgres_runtime_preflight.py`
- `docs/recovery-integration/stage20-runtime-preflight-blocker.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20E weekly PDF accepted-text blocker:

- `tests/test_weekly_pdf_postgres_wiring.py`
- `docs/recovery-integration/stage20-weekly-pdf-accepted-text-blocker.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20F final full verification:

- `docs/recovery-integration/stage20-full-verification.md`
- `docs/recovery-integration/recovery-status.md`
- `docs/recovery-integration/recipe-content-audit-round2.md`
- `docs/recovery-integration/recipe-content-audit-round2-findings.csv`

Stage 5 payments/promo/subscriptions:

- `src/diet_bot/payments.py`
- `src/diet_bot/subscriptions.py`
- `src/diet_bot/promo_codes.py`
- `src/diet_bot/telegram_app.py`
- `src/diet_bot/entitlement_service.py`
- `src/diet_bot/runtime_config.py`
- `src/diet_bot/postgres_entitlement_migrations.py`
- `src/diet_bot/postgres_entitlement_store.py`
- `src/diet_bot/postgres_payment_store.py`
- `src/diet_bot/postgres_one_day_generation_job_store.py`
- `src/diet_bot/postgres_weekly_pdf_job_store.py`
- `tests/test_payments.py`
- `tests/test_payment_service.py`
- `tests/test_promo_codes.py`
- `tests/test_subscriptions.py`
- `tests/test_runtime_config.py`
- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/payments-transfer.md`

Stage 6 builder/selection:

- `src/diet_bot/builder.py`
- `tests/test_builder_recipe_cache.py`
- `docs/recovery-integration/builder-selection-fix.md`

Stage 7 hardening audit:

- `tests/test_postgres_payment_store.py`
- `docs/recovery-integration/hardening-preservation-audit.md`

Stage 8 verification cleanup:

- `tests/test_payment_scale_rehearsal.py`
- `tests/test_payment_recovery_replay.py`
- `tests/test_payment_recovery_spool.py`
- `tests/test_postgres_payment_store.py`
- `tests/test_vectors_and_shopping.py`

Docs/status:

- `docs/recovery-integration/diff-map.md`
- `docs/recovery-integration/data-assets-transfer.md`
- `docs/recovery-integration/pdf-renderer-transfer.md`
- `docs/recovery-integration/telegram-ui-transfer.md`
- `docs/recovery-integration/recovery-status.md`
- `docs/recovery-integration/final-readiness-report.md`

## Tests Run

Latest Stage 20F final full verification rerun:

- Initial snapshot:
  - branch: `codex/recover-product-ui-on-hardened-master`
  - HEAD: `aa8336a250d0357e819904e0786abfbf1c0ea108`
  - `git status --short`: dirty integration worktree with 48 modified tracked
    entries and 222 untracked entries/directories reported by porcelain status.
- `DIET_BOT_TEST_DATABASE_URL` was not pre-set, so the full suite used a
  disposable local Docker Postgres database named `diet_bot_test`, bound to
  `127.0.0.1` on an ephemeral port. The DSN stayed in process environment only
  and was not printed or written to secrets/env files. Temporary PostgreSQL
  client-tool shims for restore-drill coverage were removed after the run.
- Full suite:
  `pytest -q`
  - `1067 passed, 1 skipped in 1333.36s (0:22:13)`
- Skip attribution:
  `pytest tests/test_pdf_renderer.py tests/test_weekly_selector_scoring.py -q -rs`
  - `30 passed, 1 skipped in 35.84s`
  - skip reason: `tests/test_weekly_selector_scoring.py:848: local live QA state test is opt-in`.
- Recipe content audit:
  `python scripts/dev/recipe_content_audit.py`
  - `recipes_checked=665`
  - `ingredients_checked=6130`
  - `foods_checked=359`
  - `nutrition_rows_checked=665`
  - `blocking_findings=0`
  - `warning_findings=1221`
- PDF renderer recovery smoke:
  `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
  - output dir: `tmp/pdf-renderer-recovery-smoke`
- Local runtime healthcheck:
  `python -m diet_bot.healthcheck`
  - safe local dummy token/JSON-storage/payments-disabled environment
  - `issues: none`
- Controlled-QA production preflight:
  `python -m scripts.ops.production_preflight --mode controlled-qa`
  - fresh disposable local Docker Postgres with required schemas initialized
  - `result: PASS`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Timeouts: none observed.
- Bot was not launched.
- No deploy, push, commit, tag, PR, real payment/refund/chargeback action,
  secrets/env-file work, archive work, `New project 2 CLEAN`, or recovered-bot
  work was done.

Latest Stage 20E weekly PDF accepted-text blocker:

- Initial focused run:
  `pytest tests/test_weekly_pdf_postgres_wiring.py::test_postgres_admission_returns_accepted_without_entering_local_queue_or_starting -q`
  - RED: `1 failed`; actual `message.texts == []` while the stale test expected `WEEK_PDF_ACCEPTED_TEXT`.
- Focused weekly PDF Postgres wiring suite:
  `pytest tests/test_weekly_pdf_postgres_wiring.py -q`
  - `24 passed`
- Runtime and user-journey smoke subset:
  `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `36 passed`
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings only.

Latest Stage 20D runtime-preflight worker-flags blocker:

- Initial focused run:
  `pytest tests/test_postgres_runtime_preflight.py::test_startup_preflight_validators_pass_against_fully_migrated_postgres -q`
  - `1 skipped` because `DIET_BOT_TEST_DATABASE_URL` is not set locally.
- Skip reason confirmation:
  `pytest tests/test_postgres_runtime_preflight.py::test_startup_preflight_validators_pass_against_fully_migrated_postgres -q -rs`
  - `1 skipped`; reason: `set DIET_BOT_TEST_DATABASE_URL to run Postgres runtime preflight integration tests`.
- Focused runtime preflight suite:
  `pytest tests/test_postgres_runtime_preflight.py -q`
  - `4 skipped` because `DIET_BOT_TEST_DATABASE_URL` is not set locally.
- Runtime/preflight/healthcheck regression:
  `pytest tests/test_healthcheck.py tests/test_runtime_config.py tests/test_production_preflight.py -q`
  - `73 passed`
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings.
- Bot was not launched.
- No payment/store tests, PDF, recipe/data, Telegram UI, promo behavior, weekly
  PDF accepted-text test, deploy, push, commit, tag, PR, secrets/env-file,
  archive, `New project 2 CLEAN`, or recovered-bot work was done.

Latest Stage 20C payment-store blocker:

- Initial focused run without `DIET_BOT_TEST_DATABASE_URL`:
  `pytest tests/test_postgres_payment_store.py -q`
  - `20 passed, 15 skipped`
- Focused DSN-backed reproduction with disposable local Postgres and redacted
  DSN:
  `pytest tests/test_postgres_payment_store.py -q`
  - before fix: `4 failed, 31 passed`
  - failures were stale `400 XTR` successful subscription requests now rejected
    as `amount_mismatch` against current `450 XTR` orders.
- Focused DSN-backed rerun after the fix:
  `pytest tests/test_postgres_payment_store.py -q`
  - `35 passed`
- Payment/promo/subscription regression:
  `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
  - `47 passed`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No PDF, recipe/data, Telegram UI copy, promo store/admin, runtime/preflight
  worker flags, weekly PDF tests, deploy, push, commit, tag, PR, real
  payment/refund/chargeback action, secrets/env-file, archive, `New project 2
  CLEAN`, or recovered-bot work was done.

Latest Stage 20A verification blocker:

- First blocker node id as provided:
  `pytest tests/test_telegram_app_runtime.py::test_one_day_plan_double_callback_same_chat_consumes_once -q`
  - `no tests ran`; in this checkout the test is in `tests/test_telegram_app_photos.py`.
- Focused five one-day tests individually from `tests/test_telegram_app_photos.py`
  - each passed in isolation.
- Original blocker suite before the fix:
  `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_photos.py -q`
  - `5 failed, 210 passed`
- Minimal leak repro before the fix:
  `pytest tests/test_telegram_app_runtime.py::test_run_bot_production_postgres_acquires_guard_before_bot_and_releases tests/test_telegram_app_photos.py::test_one_day_plan_double_callback_same_chat_consumes_once -q`
  - `1 failed, 1 passed`
- Minimal leak repro after the fix:
  same command
  - `2 passed`
- Focused five after the fix:
  `pytest tests/test_telegram_app_photos.py::test_one_day_plan_double_callback_same_chat_consumes_once tests/test_telegram_app_photos.py::test_concurrent_one_day_requests_same_chat_consume_once tests/test_telegram_app_photos.py::test_one_day_failure_releases_guard_and_allows_retry tests/test_telegram_app_photos.py::test_one_day_generation_different_chats_do_not_block_each_other tests/test_telegram_app_photos.py::test_trial_questionnaire_completion_sends_one_day_plan_and_subscription_cta -q`
  - `5 passed`
- Requested blocker suite after the fix:
  `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_photos.py -q`
  - `215 passed`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No production code, deploy, push, commit, tag, PR, payment behavior, PDF,
  recipe data, secrets/env files, archive, `New project 2 CLEAN`, or
  recovered-bot work was done.

Latest Stage 19.4 env example / deploy config hygiene:

- RED before `.env.example` creation:
  `pytest tests/test_production_deploy_files.py -q`
  - `5 failed`
  - failures confirmed `.env.example` was missing and required deploy-file
    coverage could catch the gap.
- GREEN deploy-file coverage:
  `pytest tests/test_production_deploy_files.py -q`
  - `5 passed`
- Runtime config and healthcheck regression:
  `pytest tests/test_runtime_config.py tests/test_healthcheck.py -q`
  - `50 passed`
- Final hygiene check:
  `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No runtime behavior, Telegram UX, payments, promo logic, PDF, recipe data,
  sales follow-up, deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`,
  recovered-bot, or real secret/env-file work was done.

Latest Stage 19.3 one-day worker `to_thread`:

- RED before implementation:
  `pytest tests/test_telegram_app_runtime.py::test_one_day_generation_delivery_offloads_plan_build_to_thread -q`
  - `1 failed`
  - failure confirmed `_prepare_one_day_generation_delivery` called `build_one_day_plan(...)` synchronously instead of through the patched `asyncio.to_thread` wrapper.
- GREEN targeted regression:
  `pytest tests/test_telegram_app_runtime.py::test_one_day_generation_delivery_offloads_plan_build_to_thread -q`
  - `1 passed`
- Requested Telegram runtime suite:
  `pytest tests/test_telegram_app_runtime.py -q`
  - `24 passed`
- Relevant one-day job/runtime suite:
  `pytest tests/test_one_day_generation_job_runtime.py -q`
  - `20 passed`
- Additional one-day job store suite:
  `pytest tests/test_postgres_one_day_generation_job_store.py -q`
  - `3 passed, 32 skipped`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No promo store, PDF/recipe data, sales follow-up, payment/subscription semantics, deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or recovered-bot work was done.

Latest Stage 19.2F DSN-backed promo verification:

- `DIET_BOT_TEST_DATABASE_URL` was not pre-set, so the run used a disposable local Docker Postgres database named `diet_bot_test`, bound to `127.0.0.1` on an ephemeral port. The DSN stayed in process environment only and was not written to secrets or env files.
- Initial DSN restore-drill run exposed a real fixture gap: the live restore source did not initialize/seed promo tables even though restore-drill now requires `promo_codes`, `promo_code_redemptions`, and `promo_import_runs`.
- Fixture fix:
  `tests/test_postgres_restore_drill_ops.py`
  - initialized `PostgresPromoStore`;
  - seeded one source row in each required promo table for source/restore row-count comparison.
- Final DSN-backed rerun:
  `pytest tests/test_postgres_promo_store.py -q`
  - `9 passed`
- `pytest tests/test_production_preflight.py -q`
  - `23 passed`
- `pytest tests/test_postgres_restore_drill_ops.py -q`
  - `17 passed`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Disposable database/container and temporary client-tool wrappers were removed after the run.
- Bot was not launched.
- No production DB, deploy, push, commit, tag, PR, archive, recovered-bot, `FOOD20`, sales/payment/PDF/recipe behavior, or secrets/env-file work was done.

Latest Stage 19.2E promo preflight/runbook/restore-drill gates:

- RED before implementation:
  `pytest tests/test_production_preflight.py::test_production_preflight_success_reports_pass_and_uses_existing_validators tests/test_production_preflight.py::test_production_preflight_reports_missing_promo_schema_without_printing_dsn tests/test_production_preflight.py::test_restore_drill_required_tables_include_promo_tables tests/test_production_preflight.py::test_runbook_documents_promo_store_migration_import_and_restore -q`
  - `4 failed`
  - failures showed production preflight had no promo schema validator, restore-drill required tables omitted promo tables, and the runbook lacked promo migration/import/restore instructions.
- GREEN targeted Stage 19.2E preflight/runbook/restore checks:
  `pytest tests/test_production_preflight.py tests/test_postgres_migration_versions.py -q`
  - `24 passed`
- Healthcheck regression:
  `pytest tests/test_healthcheck.py -q`
  - `12 passed`
- Promo/Telegram runtime regression:
  `pytest tests/test_promo_codes.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `46 passed`
- Restore-drill ops regression:
  `pytest tests/test_postgres_restore_drill_ops.py -q`
  - `16 passed, 1 skipped`
  - skipped case requires `DIET_BOT_TEST_DATABASE_URL`.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No sales follow-up, `FOOD20`, Telegram activation/admin behavior, payment/subscription semantics, PDF/recipe data, deploy, push, commit, tag, PR, archive, or recovered-bot files were touched.

Latest Stage 19.2D admin promo menu wiring:

- RED before implementation:
  `pytest tests/test_telegram_app_runtime.py::test_postgres_admin_monthly_code_uses_store_and_can_be_redeemed tests/test_telegram_app_runtime.py::test_postgres_admin_discount_create_list_and_disable_use_store_not_json tests/test_telegram_app_runtime.py::test_json_admin_discount_flow_remains_fallback tests/test_telegram_user_journeys_smoke.py::test_non_admin_330366_does_not_open_admin_promo_panel -q`
  - `4 failed`
  - failures showed admin helpers still lacked admin audit/Postgres wiring and bare non-admin `/330366` still returned the old status path.
- GREEN targeted Stage 19.2D regression:
  same command
  - `4 passed`
- Existing promo model/JSON tests:
  `pytest tests/test_promo_codes.py -q`
  - `11 passed`
- Telegram runtime/user journey smoke:
  `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `35 passed`
- Promo Postgres store suite:
  `pytest tests/test_postgres_promo_store.py -q`
  - `2 passed, 7 skipped`
  - skipped cases require `DIET_BOT_TEST_DATABASE_URL`.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No sales follow-up, `FOOD20`, payment/subscription semantics, PDF/recipe data, deploy, push, commit, tag, PR, archive, or recovered-bot files were touched.

Latest Stage 19.2C user promo activation wiring:

- RED before implementation:
  `pytest tests/test_telegram_app_runtime.py::test_postgres_promo_activation_uses_store_without_json_save tests/test_telegram_app_runtime.py::test_postgres_promo_activation_maps_store_rejections tests/test_telegram_app_runtime.py::test_postgres_promo_duplicate_activation_does_not_grant_twice tests/test_telegram_app_runtime.py::test_postgres_promo_activation_ignores_corrupt_json_state tests/test_postgres_promo_store.py::test_store_api_surface_is_ready_for_future_wiring -q`
  - `9 failed, 1 passed`
  - failures showed activation still using JSON and the store API missing finalize/release hooks.
- GREEN targeted Stage 19.2C regression:
  same command
  - `10 passed`
- Existing promo model/JSON tests:
  `pytest tests/test_promo_codes.py -q`
  - `11 passed`
- Telegram runtime/user journey smoke:
  `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `31 passed`
- Promo Postgres store suite:
  `pytest tests/test_postgres_promo_store.py -q`
  - `2 passed, 7 skipped`
  - skipped cases require `DIET_BOT_TEST_DATABASE_URL`.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No admin menu wiring, sales follow-up, `FOOD20`, payment/subscription semantics beyond promo activation source, PDF/recipe data, deploy, push, commit, tag, PR, archive, or recovered-bot files were touched.

Latest Stage 19.2B promo Postgres schema + store:

- RED before implementation:
  `pytest tests/test_postgres_promo_store.py -q`
  - failed at collection with `ModuleNotFoundError: No module named 'diet_bot.postgres_promo_migrations'`, because the promo migration/store modules did not exist yet.
- Existing promo model/JSON tests:
  `pytest tests/test_promo_codes.py -q`
  - `11 passed`
- New promo Postgres tests:
  `pytest tests/test_postgres_promo_store.py -q`
  - `2 passed, 7 skipped`
  - skipped cases require `DIET_BOT_TEST_DATABASE_URL`.
- Migration version registry:
  `pytest tests/test_postgres_migration_versions.py -q`
  - `1 passed`
- Generic Postgres store suite:
  `tests/test_postgres_store.py`
  - file is absent in this checkout, so no generic suite was run.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings.
- Bot was not launched.
- No Telegram activation/admin menu, payment/subscription semantics, sales follow-up, `FOOD20`, PDF/recipe data, deploy, push, commit, tag, PR, archive, or recovered-bot files were changed.

Latest Stage 19.2A promo-store hardening design:

- Read-only inspection of:
  - `src/diet_bot/promo_codes.py`
  - promo usage in `src/diet_bot/telegram_app.py`
  - entitlement/payment grant transaction patterns
  - Postgres migration, schema validation, preflight, backup, and restore-drill patterns
  - promo, payment, subscription, and Telegram promo tests
- No tests were run, because this stage was documentation-only and explicitly prohibited implementation/runtime work.
- Bot was not launched.
- No production code, tests, promo JSON/data, payments/runtime/storage, deploy, push, commit, tag, PR, archive, or recovered-bot files were changed.

Latest Stage 19.1 B-1 worker guard:

- Initial targeted runtime/preflight reproduction:
  `pytest tests/test_healthcheck.py tests/test_runtime_config.py tests/test_telegram_app_runtime.py -q`
  - `2 failed, 59 passed`; failures were stale valid production fixtures missing `DIET_BOT_ONE_DAY_WORKER_ENABLED=1` and `DIET_BOT_WEEKLY_PDF_WORKER_ENABLED=1`.
- Initial preflight reproduction:
  `pytest tests/test_production_preflight.py -q`
  - `5 failed, 15 passed`; failures were downstream checks blocked by the same stale valid production fixture.
- Final targeted suite:
  `pytest tests/test_healthcheck.py tests/test_runtime_config.py tests/test_telegram_app_runtime.py -q`
  - `61 passed`
- Final production preflight suite:
  `pytest tests/test_production_preflight.py -q`
  - `20 passed`
- `tests/test_production_deploy_files.py`
  - file is absent in this checkout, so no deploy-file suite was run.
- Local healthcheck module entrypoint:
  `PYTHONPATH=src python -m diet_bot.healthcheck` with a dummy local JSON env
  - `issues: none`
- `git diff --check`
  - exit code `0`; output contained only existing LF-to-CRLF working-copy warnings.

Latest Stage 18A sales follow-up design:

- Design-only/read-only inspection of Telegram trial flow, payments/entitlements, durable job runtime patterns, and promo durability risk.
- No tests were run, because this stage was documentation-only and explicitly prohibited implementation/runtime work.
- Bot was not launched.

Latest Stage 17 PDF layout v2:

- RED before implementation:
  `pytest tests/test_pdf_renderer.py::test_recipe_with_photo_uses_right_photo_two_column_body tests/test_pdf_renderer.py::test_long_recipe_steps_continue_below_photo_block tests/test_pdf_renderer.py::test_recipe_photo_has_no_centered_photo_fallback tests/test_pdf_renderer.py::test_day_label_is_visible_on_recipe_continuation_pages -q`
  - `4 failed`
- GREEN after implementation:
  same command
  - `4 passed`
- Full PDF renderer suite:
  `pytest tests/test_pdf_renderer.py -q`
  - `14 passed`
- Recovery PDF smoke:
  `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
  - output dir: `tmp/pdf-renderer-recovery-smoke`
- PyMuPDF visual preview output:
  - `tmp/pdf-qa-stage17-preview/p03-day1-normal-right-photo.png`
  - `tmp/pdf-qa-stage17-preview/p05-long-recipe-continuation.png`
  - `tmp/pdf-qa-stage17-preview/p20-day5-label-right-photo.png`
  - `tmp/pdf-qa-stage17-preview/p27-cod-liver-previous-example.png`
  - `tmp/pdf-qa-stage17-preview/p33-shopping-list.png`
  - `tmp/pdf-qa-stage17-preview/p34-shopping-list-continued.png`
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF warnings for dirty files.

Latest Stage 16 checks:

- RED before implementation:
  `pytest tests/test_questionnaire_and_presentation.py::test_calculation_summary_adds_stage16_intro_and_follow_up tests/test_questionnaire_and_presentation.py::test_plan_response_includes_per_meal_kbju_lines_from_real_nutrients tests/test_questionnaire_and_presentation.py::test_meal_card_includes_kbju_line_from_meal_nutrients tests/test_telegram_app_photos.py::test_trial_subscription_keyboard_has_cta_button tests/test_telegram_app_photos.py::test_postgres_weekly_pdf_admission_does_not_send_duplicate_generation_message -q`
  - `5 failed`
- GREEN after implementation:
  same command
  - `5 passed`
- Regression check for long meal cards:
  `pytest tests/test_questionnaire_and_presentation.py::test_plan_response_includes_per_meal_kbju_lines_from_real_nutrients tests/test_questionnaire_and_presentation.py::test_meal_card_includes_kbju_line_from_meal_nutrients tests/test_telegram_app_photos.py::test_long_meal_card_sends_photo_without_duplicate_title -q`
  - `3 passed`
- Requested targeted suite:
  `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_photos.py -q`
  - `201 passed`
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF warnings for dirty files.

Latest Stage 5 checks:

- `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
  - `47 passed`
- `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py -q`
  - `17 passed`
- `pytest tests/test_questionnaire_and_presentation.py -q`
  - `21 passed`
- `pytest tests/test_runtime_config.py tests/test_production_preflight.py tests/test_healthcheck.py tests/test_payment_runtime.py tests/test_telegram_app_runtime.py -q`
  - `85 passed`
- `pytest tests/test_payments.py tests/test_payment_service.py tests/test_promo_codes.py tests/test_subscriptions.py tests/test_entitlement_service.py tests/test_entitlement_storage.py tests/test_entitlement_json_migration.py tests/test_postgres_migration_versions.py -q`
  - `96 passed`
- `pytest tests/test_payment_service.py tests/test_payment_runtime.py tests/test_payment_recovery_spool.py tests/test_payment_recovery_replay.py tests/test_payment_reconciliation_report.py tests/test_payment_recovery_spool_status.py tests/test_telegram_app_photos.py -q`
  - `244 passed`
- `python -m compileall -q` on changed Stage 5 modules
  - exit code `0`
- `git diff --check`
  - exit code `0`
  - only CRLF warnings.

Latest Stage 6 checks:

- `pytest tests/test_safety_and_builder.py::test_five_repeat_generations_keep_key_meals_unique tests/test_safety_and_builder.py::test_repeat_generations_can_avoid_recent_recipe_families -q`
  - RED before fix: `2 failed`
  - GREEN after fix: `2 passed`
- `pytest tests/test_builder_recipe_cache.py::test_rank_recipes_filters_avoided_recipe_keys_by_requested_slot -q`
  - `1 passed`
- `pytest tests/test_safety_and_builder.py tests/test_builder_recipe_cache.py tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q`
  - first pass found one carbohydrate-range regression after the initial rotation change
  - final pass after tightening rotation: `131 passed`

Latest Stage 7 checks:

- `pytest tests/test_runtime_config.py tests/test_production_preflight.py tests/test_healthcheck.py tests/test_postgres_schema_validation.py tests/test_postgres_migration_versions.py tests/test_payment_runtime.py tests/test_payment_recovery_spool.py tests/test_payment_recovery_replay.py tests/test_payment_reconciliation_report.py tests/test_payment_service.py tests/test_telegram_app_runtime.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_media_validation.py -q`
  - `187 passed`
- `pytest tests/test_postgres_payment_store.py tests/test_postgres_entitlement_store.py tests/test_postgres_one_day_generation_job_store.py tests/test_postgres_weekly_pdf_job_store.py tests/test_postgres_runtime_preflight.py tests/test_postgres_single_poller_guard.py tests/test_postgres_connection.py tests/test_weekly_pdf_postgres_wiring.py -q`
  - first pass found two test-double failures from missing Stage 5 entitlement metadata columns
  - final pass after updating the fake cursor schema: `100 passed, 98 skipped`
- `python -m diet_bot.healthcheck`
  - ran with dummy local `DIET_BOT_TOKEN`
  - `issues: none`
- hardening module import/existence checks
  - 14 modules imported successfully
  - expected runtime/storage/recovery/preflight/payment/media modules present

Latest Stage 8 checks:

- `pytest tests/test_pdf_renderer.py -q`
  - `6 passed`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `238 passed`
- `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_questionnaire_and_presentation.py -q`
  - `38 passed`
- `pytest tests/test_payments.py tests/test_payment_service.py tests/test_payment_runtime.py tests/test_payment_recovery_spool.py tests/test_payment_recovery_replay.py tests/test_payment_reconciliation_report.py tests/test_payment_recovery_spool_status.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
  - `142 passed`
- `pytest tests/test_runtime_config.py tests/test_production_preflight.py tests/test_healthcheck.py tests/test_postgres_schema_validation.py tests/test_postgres_migration_versions.py tests/test_postgres_payment_store.py tests/test_postgres_entitlement_store.py tests/test_postgres_one_day_generation_job_store.py tests/test_postgres_weekly_pdf_job_store.py tests/test_postgres_runtime_preflight.py tests/test_postgres_single_poller_guard.py tests/test_postgres_connection.py tests/test_weekly_pdf_postgres_wiring.py -q`
  - `172 passed, 98 skipped`
- `python -m diet_bot.healthcheck`
  - ran with dummy local `DIET_BOT_TOKEN`
  - `issues: none`
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
- `pytest -q`
  - first full pass found two stale expectations:
    - old YooKassa subscription amount in `tests/test_payment_scale_rehearsal.py`
    - old shopping-list heading in `tests/test_vectors_and_shopping.py`
  - after aligning product expectations and related payment test fixtures: `890 passed, 115 skipped`

Latest Stage 9:

- `docs/recovery-integration/final-readiness-report.md`
  - created with changed files by stage, restored product features, preserved master hardening, test results, known risks, manual Telegram/payment smoke checklists, and approval gates before publish.
- `git diff --check`
  - exit code `0`
  - only CRLF checkout warnings.

Latest Round 2 QA2-005 privacy-only:

- `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py -q`
  - first pass after adding a new assertion failed because the assertion targeted the text-only age question, which has no inline keyboard.
  - final pass after correcting the test target to a normal option question: `48 passed`

Latest Round 2 QA2-002 PDF-only:

- `pytest tests/test_pdf_renderer.py::test_recipe_media_always_uses_single_stacked_photo_layout tests/test_pdf_renderer.py::test_renderer_keeps_no_side_by_side_recipe_photo_layout_helpers tests/test_pdf_renderer.py::test_meal_photo_source_is_rendered_to_fixed_box_aspect -q`
  - RED before fix: `2 failed, 1 passed`
  - GREEN after fix: `3 passed`
- `pytest tests/test_pdf_renderer.py -q`
  - `12 passed`
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
- `git diff --check`
  - exit code `0`
  - only existing CRLF checkout warnings.
- PyMuPDF preview render:
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p02-photo-after-ingredients.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p03-long-recipe-start.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p04-long-recipe-image-steps-next-page.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p28-cod-liver-salad-previous-example.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p30-shopping-list.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p31-shopping-list-continued.png`

Latest Round 2 QA2-001/QA2-003/QA2-004 recipe-audit-only:

- `python scripts/dev/recipe_content_audit.py`
  - `recipes_checked=665`
  - `ingredients_checked=6130`
  - `blocking_findings=4`
  - `warning_findings=1634`
  - report: `docs/recovery-integration/recipe-content-audit-round2.md`
  - CSV: `docs/recovery-integration/recipe-content-audit-round2-findings.csv`
- `git diff --check`
  - exit code `0`
  - only existing CRLF checkout warnings.

Latest Round 2 QA2-003/QA2-004 high-suspicion recipe fixes:

- `python scripts/dev/recipe_content_audit.py`
  - `recipes_checked=665`
  - `ingredients_checked=6130`
  - `foods_checked=359`
  - `blocking_findings=0`
  - `warning_findings=1494`
  - `title_ingredient_mismatch.warnings=0`
  - `steps_mention_missing_ingredient.warnings=0`
  - `non_cis_unclear_ingredients.warnings=0`
  - `tiny_gram_anomalies.warnings=0`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q`
  - `92 passed`
- `git diff --check`
  - exit code `0`
  - Git printed only existing CRLF checkout warnings.

Latest Round 2 QA2-001 approximate-measures batch:

- `python scripts/dev/recipe_content_audit.py`
  - before this batch: `recipes_checked=665`, `ingredients_checked=6130`, `blocking_findings=0`, `warning_findings=1494`, `missing_approximate_measures.warnings=406`
  - after this batch: `recipes_checked=665`, `ingredients_checked=6130`, `blocking_findings=0`, `warning_findings=1221`, `missing_approximate_measures.warnings=133`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q`
  - RED on new guard before data changes: `2 failed, 1 passed`
  - first full narrow pass found one stale raw-text expectation for `r306`
  - final pass after updating that expectation: `95 passed`
- `git diff --check`
  - exit code `0`
  - Git printed only existing CRLF checkout warnings.

Latest Round 2 stale Telegram photo/menu tests:

- `pytest tests/test_telegram_app_photos.py -q`
  - RED before fix: `16 failed, 133 passed`
  - GREEN after aligning stale menu expectations: `149 passed`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `244 passed`

Earlier Stage 2-4 checks are documented in their stage reports.

## Failures / Open Risks

- Payment test-price flag is production-gated but does not switch invoice amounts in this stage.
- Admin payment-event reconciliation commands remain deferred.
- Builder tests are slow because they exercise the full curated recipe pool.
- QA2-005 consent acceptance is intentionally in-memory via `PRIVACY_CONSENT_CHAT_IDS`; no risky database migration was added.
- QA2-002 visual overlap cannot be fully proven by unit tests; rendered PNG previews and smoke PDFs were inspected for this PDF-only pass.
- Stage 17 visual overlap cannot be fully proven by unit tests; the PyMuPDF previews listed above were rendered and inspected for this PDF-only pass.
- Stage 18A identified `FOOD20` as blocked for launch until promo storage is hardened: current promo persistence is JSON-backed/direct-write, discount codes are not safely redeemable by users, and payment order metadata does not yet carry discount details.
- Stage 19.2F closes the H-1 DSN-backed verification caveat for promo Postgres store, production preflight coverage, and restore-drill promo table comparison. Discount payment-path wiring and campaign approval remain later-stage blockers before any `FOOD20` launch.
- Stage 19.3 closes external audit M-1 for the queued one-day generation worker delivery path. Legacy non-worker one-day generation still has its existing synchronous path and was intentionally left unchanged for this scoped fix.
- Stage 19.4 closes the missing `.env.example` / deploy-config hygiene gap.
  Full verification/manual smoke is still a separate stage and was not run here.
- Stage 20A closes the placeholder-DSN verification blocker for the requested
  Telegram/questionnaire subset. Full Stage 20 verification was intentionally
  not continued after this blocker fix.
- Stage 20C closes the Postgres payment-store blocker as stale test
  expectations after product price restoration. Full Stage 20 verification was
  intentionally not continued after this blocker fix.
- Stage 20D closes the runtime-preflight worker-flags blocker as a stale
  valid production/Postgres fixture after B-1. Full Stage 20 verification was
  intentionally not continued after this blocker fix.
- Stage 20E closes the weekly PDF accepted-text blocker as a stale
  durable-admission test expectation after the Stage 16 duplicate-message
  removal. Full Stage 20 verification was intentionally not continued after
  this blocker fix.
- Stage 20F closes the full-verification rerun: full DSN-backed pytest and all
  final targeted smoke commands passed. The only skip is the opt-in local live
  QA state test.
- Stage 18A recommends a PostgreSQL-backed `sales_followup_*` durable queue and explicitly rejects in-memory timers for follow-up scheduling.
- QA2-001 approximate measures are fixed for confident common gram-only rows. Current recipe audit reports 0 blockers and 1221 warnings, including 133 remaining missing-approximate-measure warnings intentionally left for ambiguous categories.
- Stale Telegram photo/menu unit-test blocker is resolved; live
  Telegram/YooKassa/Stars smoke remains pending explicit user approval,
  sandbox-safe credentials/config, and a manual bot restart.

## Next Stage

Ready for explicitly approved manual-smoke bot restart. Keep sales follow-up
launch and `FOOD20` blocked until their separately approved stages. Do not
deploy, push, PR, tag, commit, launch live polling/webhook, or run real payment
actions until approved.
