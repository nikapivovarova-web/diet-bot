# FoodBalance Recovery Integration: Payments / Promo / Subscriptions Transfer

## Scope

Stage 5 restored product payment, promo, and subscription semantics while preserving hardened master ownership of payment durability.

No live Telegram polling/webhooks were launched. No live payment API calls, captures, refunds, chargebacks, deploy, push, PR, tag, or commit were performed.

## Product Semantics Restored

- Product prices:
  - subscription: `799 RUB` / `450 Stars`
  - extra one-day ration: `50 RUB` / `29 Stars`
  - extra weekly PDF: `250 RUB` / `141 Stars`
- YooKassa subscription invoice copy/receipt now describes one-time 30-day access.
- Telegram Stars subscription invoices retain `subscription_period=2_592_000` for managed monthly auto-renewal.
- Entitlements now carry managed subscription metadata:
  - `subscription_source`
  - `auto_renew_status`
  - `stars_subscription_charge_id`
  - `last_subscription_payment_charge_id`
  - `current_period_payment_order_id`
- Successful Telegram Stars subscription grants mark `subscription_source="telegram_stars"` and `auto_renew_status="enabled"` through the Postgres transactional payment grant path.
- YooKassa monthly grants mark `subscription_source="yookassa"` and remain one-time 30-day access.
- Monthly promo grants mark `subscription_source="promo"` and preserve rollback on entitlement grant failure.
- Promo model now supports monthly-access and discount definitions, disabled/expired state, percent/fixed discount calculation, and discount promos that cannot be activated as access codes.
- Runtime config now has public-payment and payment-test-price flags:
  - `DIET_BOT_PUBLIC_PAYMENTS_ENABLED`
  - `DIET_BOT_PAYMENT_TEST_PRICES_ENABLED`
  - production startup rejects payment test prices.

## Master Hardening Preserved

- Master `PaymentService` remains the payment entry point for order creation, pre-checkout validation, successful payment handling, duplicate charge handling, and orphan/non-order event recording.
- Master checksum-bearing `diet:order:v1:<order_id>:<nonce>:<checksum>` invoice payloads were kept.
- Postgres payment ledger transactionality was kept: order lock, charge uniqueness, event uniqueness, and atomic payment-and-entitlement grant.
- Payment recovery spool/replay/reconciliation modules were kept and covered by tests.
- Telegram successful-payment ledger failure still spools recovery records before notifying delayed activation/support.
- Runtime payment startup still requires Postgres, database URL, payment ledger schema validation, and absolute configured recovery spool when payments are enabled.
- Telegram UI payment buttons remain hidden unless hardened payment runtime flags allow them.
- No product JSON-store payment path was copied.

## Schema Change

An additive entitlement migration was required because managed Stars subscription metadata must survive the production Postgres path and durable job refund/consumption updates.

Added migration:

- `src/diet_bot/postgres_entitlement_migrations.py`
  - `202605290001 Add managed subscription metadata to entitlements`

Added nullable/defaulted columns:

- `subscription_source TEXT NOT NULL DEFAULT 'none'`
- `auto_renew_status TEXT NOT NULL DEFAULT 'not_applicable'`
- `stars_subscription_charge_id TEXT`
- `last_subscription_payment_charge_id TEXT`
- `current_period_payment_order_id TEXT`

All master entitlement read/write helpers touched by payment grants or durable one-day/weekly PDF jobs were updated to preserve these fields.

## Files Changed In Stage 5

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

## TDD / RED Evidence

- Initial payment/promo/subscription collection failed because product promo/subscription symbols were missing:
  - `PromoCodeDefinition`
  - `has_active_managed_stars_subscription`
- Price-focused RED run failed on old master values:
  - Stars `400/35/170`
  - YooKassa subscription `59_900`
  - Telegram UI labels still `599 RUB` / `400 Stars`

## Tests And Checks

Passed:

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
  - only Windows CRLF checkout warnings.

Notes:

- PowerShell did not expand the literal `tests/test_payments*.py` argument; the equivalent explicit command was run as `tests/test_payments.py`.
- No Postgres integration tests were run because no explicit disposable `DIET_BOT_TEST_DATABASE_URL` was provided.

## Remaining Risks / Deferred Items

- Admin discount create/list/disable UI and admin `/payment_event` reconciliation commands are still not exposed. The model pieces are present, but authorization/audit/UI wiring should remain gated.
- Payment test-price flag is parsed and production-gated, but test-price invoice amounts are not enabled in this stage. This avoids accidental price switching without a broader pricing-context ledger design.
- Live YooKassa/Stars sandbox smoke remains manual and requires user-approved test credentials.
