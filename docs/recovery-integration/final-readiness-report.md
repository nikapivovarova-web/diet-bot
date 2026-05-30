# Final Readiness Report

## Summary

The recovery integration branch now restores product UI/data/PDF/payment semantics on top of the hardened master foundation. No deploy, push, PR, tag, commit, live Telegram polling/webhook, real payment API action, or secret/env change was performed.

Verdict: ready for manual Telegram/payment smoke.

## Changed Files By Stage

Stage 2 - data/assets:

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/foodbalance_pdf_logo.png`
- `src/diet_bot/data/foodbalance_pdf_qr.png`
- `src/diet_bot/data/recipe_photos/r401.jpg` through `src/diet_bot/data/recipe_photos/r610.jpg`
- `tests/test_curated_recipe_data.py`
- `tests/test_recipe_traits.py`

Stage 3 - PDF/branding:

- `src/diet_bot/pdf_renderer.py`
- `tests/test_pdf_renderer.py`
- `scripts/dev/pdf_renderer_recovery_smoke.py`

Stage 4 - Telegram UI/product copy:

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/presentation.py`
- `src/diet_bot/questionnaire.py`
- `tests/test_questionnaire_and_presentation.py`
- `tests/test_telegram_user_journeys_smoke.py`
- `tests/test_telegram_callback_owner_smoke.py`
- `tests/test_telegram_app_photos.py`
- `tests/test_vectors_and_shopping.py`

Stage 5 - payments/promo/subscriptions:

- `src/diet_bot/payments.py`
- `src/diet_bot/subscriptions.py`
- `src/diet_bot/promo_codes.py`
- `src/diet_bot/entitlement_service.py`
- `src/diet_bot/runtime_config.py`
- `src/diet_bot/postgres_entitlement_migrations.py`
- `src/diet_bot/postgres_entitlement_store.py`
- `src/diet_bot/postgres_payment_store.py`
- `src/diet_bot/postgres_one_day_generation_job_store.py`
- `src/diet_bot/postgres_weekly_pdf_job_store.py`
- `tests/test_payments.py`
- `tests/test_payment_service.py`
- `tests/test_payment_runtime.py`
- `tests/test_payment_recovery_spool.py`
- `tests/test_payment_recovery_replay.py`
- `tests/test_payment_recovery_spool_status.py`
- `tests/test_payment_reconciliation_report.py`
- `tests/test_payment_scale_rehearsal.py`
- `tests/test_postgres_payment_store.py`
- `tests/test_promo_codes.py`
- `tests/test_runtime_config.py`
- `tests/test_subscriptions.py`
- `docs/recovery-integration/payments-transfer.md`

Stage 6 - builder/selection:

- `src/diet_bot/builder.py`
- `tests/test_builder_recipe_cache.py`
- `docs/recovery-integration/builder-selection-fix.md`

Stage 7-9 docs/status:

- `docs/recovery-integration/hardening-preservation-audit.md`
- `docs/recovery-integration/recovery-status.md`
- `docs/recovery-integration/final-readiness-report.md`

## Product Features Restored

- Product recipe/catalog data and local recipe photos for `r401` through `r610`.
- PDF branding with FoodBalance logo, QR, local recipe photos, and recovery smoke renderer.
- Product Telegram copy, buttons, onboarding, paywall/payment appearance, private-chat text, and shopping-list wording.
- Product payment prices:
  - subscription RUB: `799`
  - subscription Stars: `450`
  - extra one day Stars: `29`
  - weekly PDF Stars: `141`
  - extra one day RUB: `50`
  - weekly PDF RUB: `250`
- Stars managed subscription metadata and autorenewal source/status fields.
- YooKassa one-time 30-day access wording and ledger validation.
- Discount/monthly promo model and promo grant flow hooks.
- Pre-checkout/order/payload validation, successful payment application, idempotent grants, recovery spool/replay compatibility, refunds/chargeback/reconciliation test coverage.
- Builder flexible-slot recipe avoidance and deterministic variety behavior for product recipe data.

## Master Hardening Preserved

- PostgreSQL remains production storage; JSON remains local/development fallback and is still rejected in production.
- Runtime config still enforces production DB, support chat ID, privacy URL, storage, payment recovery spool, and payment test-price safety.
- Healthcheck remains available and passes locally with a dummy token.
- Durable one-day and weekly PDF job stores remain present and tested.
- Payment ledger, idempotency, recovery spool, replay, reconciliation, and Postgres payment store paths remain present and tested.
- Preflight, schema validation, single poller guard, private-chat/callback-owner smoke, and Telegram media validation remain present and tested.
- Stage 5 schema change is additive; entitlement metadata columns are preserved through payment and durable job store paths.

## Test Results

- `pytest tests/test_pdf_renderer.py -q`: `6 passed`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`: `238 passed`
- `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_questionnaire_and_presentation.py -q`: `38 passed`
- `pytest tests/test_payments.py tests/test_payment_service.py tests/test_payment_runtime.py tests/test_payment_recovery_spool.py tests/test_payment_recovery_replay.py tests/test_payment_reconciliation_report.py tests/test_payment_recovery_spool_status.py tests/test_promo_codes.py tests/test_subscriptions.py -q`: `142 passed`
- `pytest tests/test_runtime_config.py ... tests/test_weekly_pdf_postgres_wiring.py -q`: `172 passed, 98 skipped`
- `pytest tests/test_safety_and_builder.py tests/test_builder_recipe_cache.py tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q`: `131 passed`
- `python -m diet_bot.healthcheck`: `issues: none` with dummy local `DIET_BOT_TOKEN`
- `python scripts/dev/pdf_renderer_recovery_smoke.py`: `rendered_pdfs=8`, `recipes_checked=210`
- `pytest -q`: `890 passed, 115 skipped`

## Known Risks

- Full DB-backed Postgres integration coverage still needs a disposable `DIET_BOT_TEST_DATABASE_URL`; local run skipped those tests.
- Live Telegram and payment sandbox smoke were intentionally not run.
- Admin discount promo UI and admin payment-event reconciliation commands are still deferred.
- Payment test-price runtime flag is production-gated but does not switch invoice amounts.

## Manual Telegram Smoke Checklist

- Confirm production-like env uses Postgres backend and passes healthcheck/preflight.
- Start bot only in approved sandbox/manual environment, not from this recovery run.
- `/start` in private chat: product intro, buttons, and onboarding flow render correctly.
- Non-private message/callback: private-chat guard blocks before state mutation.
- Questionnaire completion: profile state, product result copy, paywall, and retry paths work.
- One-day plan and weekly PDF generation: durable job acceptance, completion, local photos, PDF logo/QR, and shopping list look correct.
- Duplicate callbacks/messages: idempotency prevents duplicate generation/consumption.

## Manual Payment Smoke Checklist

- Use sandbox/test payment credentials only.
- Verify public payment visibility flags and disabled-payment behavior.
- Stars subscription: invoice amount `450`, order payload checksum, pre-checkout validation, successful grant, managed metadata, duplicate successful payment idempotency.
- YooKassa subscription: invoice amount `799 RUB`, title `FoodBalance: доступ на 30 дней`, receipt metadata, pre-checkout validation, 30-day one-time grant.
- Extras: Stars one-day `29`, Stars weekly PDF `141`, RUB one-day `50`, RUB weekly PDF `250`.
- Promo grant: monthly promo creates access without bypassing entitlement idempotency.
- Recovery: simulate ledger failure to spool, dry-run replay, apply once, repeat apply reports already recovered.
- Refund/chargeback/cancellation/reconciliation: use mocked/sandbox-only flows; no real captures/refunds/chargebacks.

## Approval Gates Before Publish

- Live Telegram token/env approval.
- Payment credentials and test mode approval.
- Production DB and migration window approval.
- Deploy target approval.
- Final manual Telegram smoke approval.
- Final manual payment smoke approval.
- PR/tag/release approval.
