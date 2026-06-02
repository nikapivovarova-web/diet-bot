# Manual Smoke Runbook

Audit date: 2026-05-29

## Current Branch And HEAD

- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD short: `aa8336a250d0`
- HEAD full: `aa8336a250d0357e819904e0786abfbf1c0ea108`
- `git diff --name-status origin/master...HEAD`: empty at audit time.
- `git diff --stat origin/master...HEAD`: empty at audit time.
- Smoke scope note: integration changes are currently in the working tree as modified/untracked files, not committed on top of `origin/master`.

## Changed Files Grouped

### Data, Assets, Photos

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/foodbalance_pdf_logo.png`
- `src/diet_bot/data/foodbalance_pdf_qr.png`
- `src/diet_bot/data/recipe_photos/r401.jpg` through `src/diet_bot/data/recipe_photos/r610.jpg` (`210` photos)

### PDF

- `src/diet_bot/pdf_renderer.py`
- `scripts/dev/pdf_renderer_recovery_smoke.py`

### Telegram UI

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/presentation.py`
- `src/diet_bot/questionnaire.py`

### Payments, Promo, Subscriptions

- `src/diet_bot/entitlement_service.py`
- `src/diet_bot/payments.py`
- `src/diet_bot/postgres_entitlement_migrations.py`
- `src/diet_bot/postgres_entitlement_store.py`
- `src/diet_bot/postgres_one_day_generation_job_store.py`
- `src/diet_bot/postgres_payment_store.py`
- `src/diet_bot/postgres_weekly_pdf_job_store.py`
- `src/diet_bot/promo_codes.py`
- `src/diet_bot/subscriptions.py`

### Builder, Runtime

- `src/diet_bot/builder.py`
- `src/diet_bot/runtime_config.py`

### Tests, Docs

- `docs/recovery-integration/builder-selection-fix.md`
- `docs/recovery-integration/data-assets-transfer.md`
- `docs/recovery-integration/diff-map.md`
- `docs/recovery-integration/final-readiness-report.md`
- `docs/recovery-integration/hardening-preservation-audit.md`
- `docs/recovery-integration/manual-smoke-runbook.md`
- `docs/recovery-integration/payments-transfer.md`
- `docs/recovery-integration/pdf-renderer-transfer.md`
- `docs/recovery-integration/recovery-status.md`
- `docs/recovery-integration/telegram-ui-transfer.md`
- `tests/test_builder_recipe_cache.py`
- `tests/test_curated_recipe_data.py`
- `tests/test_payment_recovery_replay.py`
- `tests/test_payment_recovery_spool.py`
- `tests/test_payment_scale_rehearsal.py`
- `tests/test_payment_service.py`
- `tests/test_payments.py`
- `tests/test_pdf_renderer.py`
- `tests/test_postgres_payment_store.py`
- `tests/test_promo_codes.py`
- `tests/test_questionnaire_and_presentation.py`
- `tests/test_recipe_traits.py`
- `tests/test_runtime_config.py`
- `tests/test_subscriptions.py`
- `tests/test_telegram_app_photos.py`
- `tests/test_telegram_callback_owner_smoke.py`
- `tests/test_telegram_user_journeys_smoke.py`
- `tests/test_vectors_and_shopping.py`

## Last Verified Test Results

Last recorded in `docs/recovery-integration/final-readiness-report.md`:

- Full pytest: `pytest -q` -> `890 passed, 115 skipped`
- Healthcheck: `python -m diet_bot.healthcheck` -> `issues: none` with dummy local `DIET_BOT_TOKEN`
- PDF smoke: `python scripts/dev/pdf_renderer_recovery_smoke.py` -> `rendered_pdfs=8`, `recipes_checked=210`

## Manual Telegram Smoke Checklist

- Confirm the manual environment is sandbox/approved and uses the intended Telegram bot token. Do not start from this audit run.
- Start/menu: `/start` opens the product intro, menu buttons, paywall entry points, and private-chat copy.
- Onboarding/questionnaire: complete the questionnaire, verify profile state, result copy, validation errors, and retry paths.
- Recipe/photos: generate a one-day plan, verify recipe titles, shopping-list wording, local recipe photos, and repeated generation variety.
- Weekly PDF flow: request weekly PDF, verify durable job acceptance, completion message, PDF attachment, logo, QR, recipe photos, and shopping list.
- Paywall display: verify subscription and extras are visible with expected prices and disabled-payment fallback if configured.
- Promo flow display: verify promo entry/copy and successful display of monthly promo grant path without bypassing entitlement checks.
- Error/retry messages: force safe validation failures and confirm user-facing retry/error copy is clear.
- Callback owner/private chat guards: where manually testable, try a non-private message/callback and a callback from a different user; verify state is not mutated.

## Manual Payment Sandbox Checklist

- Use only sandbox/test payment credentials and sandbox chats. Do not run real charges, captures, refunds, or chargebacks.
- Stars invoice display: verify subscription Stars invoice amount `450`, one-day extra `29`, weekly PDF `141`, title/copy, and payload checksum.
- YooKassa invoice display: verify subscription amount `799 RUB`, one-day extra `50 RUB`, weekly PDF `250 RUB`, title/copy, receipt metadata, and payload checksum.
- Pre-checkout validation: verify valid payload succeeds and invalid, duplicate, wrong-user, expired, or tampered payload fails cleanly.
- Successful payment grant: complete sandbox payment and verify entitlement/access is granted once with expected metadata.
- Duplicate/idempotency behavior: replay or duplicate successful payment update and verify no duplicate grant or double consumption.
- Cancellation/failure behavior: cancel or fail sandbox payment and verify no entitlement grant, with clear retry path.
- Refund/chargeback/reconciliation commands: run only mocked or sandbox-safe flows. Do not touch real payment events.

## Do Not Do Unattended

- Production deploy.
- Live user bot switch.
- Real charge or refund.
- Production DB migration.
- Push, PR, tag, or release.

## Remaining Blockers

- Skipped Postgres integration tests require `DIET_BOT_TEST_DATABASE_URL`.
- Live Telegram/payment sandbox smoke has not been run.
- Admin discount promo UI and admin payment-event reconciliation commands are deferred.
- Payment test-price flag limitation: the runtime flag is production-gated but does not switch invoice amounts.
