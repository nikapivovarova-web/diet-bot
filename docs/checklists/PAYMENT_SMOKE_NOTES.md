# Payment Smoke Notes

Date: 2026-05-13

Scope: manual payment smoke notes only. This document records observed results and safety reminders from the in-progress payments smoke. It does not approve paid launch and does not change payment or storage behavior.

## Preflight Reminder

- Run from `C:\Users\adck8\Documents\New project 2 CLEAN`.
- Confirm exactly one bot process is polling with the active Telegram bot token. Two processes with the same token can trigger `TelegramConflictError`.
- Keep `DIET_BOT_TESTER_CHAT_IDS` empty for payment smoke. If it contains the test chat id, test access is always true and payment access checks are not meaningful.
- Use the intended local PostgreSQL URL for the smoke environment and verify it is not printed in logs.
- Treat YooKassa and Telegram Stars paths as potentially real payments. Do not run a YooKassa real-payment checkout or spend Stars without separate explicit approval.

## Checked

- Bot startup/polling conflict behavior when duplicate bot instances use the same Telegram token.
- Payment-smoke access conditions with `DIET_BOT_TESTER_CHAT_IDS`.
- `/cancel` behavior during the Telegram UX flow.
- Free trial path through the first free ration.
- Weekly PDF delivery/design state as part of payment-adjacent smoke.
- YooKassa shop/provider safety before attempting checkout.

## Passed

- After stopping the extra bot process, the polling conflict was resolved.
- With payment smoke configured correctly, `DIET_BOT_TESTER_CHAT_IDS` should remain empty so test access does not mask payment gates.
- Free trial behaved as expected: after the first free ration, `free_trial_used=true`.

## Known Issues

- `/cancel` UX is misleading: it resets only the current action/flow, not the saved questionnaire/profile.
- Weekly PDF design is still the old/basic design. PDF redesign is a separate future phase, not part of this payment smoke slice.
- A YooKassa shop was identified as real-payment capable. Do not perform a real YooKassa payment without separate explicit consent.

## Smoke Limits

- This smoke was manual and focused on payment-adjacent behavior and safety observations, not full paid-launch approval.
- YooKassa and Telegram Stars can involve real charges depending on provider/shop/account configuration.
- Do not treat test-access success as evidence of paid entitlement success when `DIET_BOT_TESTER_CHAT_IDS` is set.
- Refunds, chargebacks, admin reconciliation, and full durable payment-ledger evidence remain separate launch-gate work.

## 2026-05-15 Storage/Payment Staging Smoke

Scope: local PostgreSQL staging smoke on commit `3731bd6` from `C:\Users\adck8\Documents\New project 2 CLEAN`. No code changes, no push, no YooKassa charge, and no Telegram Stars spend were performed.

PostgreSQL lane:

- Docker Desktop was not initially running. After starting Docker Desktop, existing container `diet-bot-test-postgres` was started and exposed `localhost:5432`.
- Runtime smoke used `DIET_BOT_DATABASE_URL=postgresql://diet_bot@localhost:5432/diet_bot_test` and `DIET_BOT_TEST_DATABASE_URL=postgresql://diet_bot@localhost:5432/diet_bot_test`.
- `DIET_BOT_ALLOW_JSON_STORAGE` was unset for the Postgres/runtime checks.
- `PostgresDietBotStore.initialize()` applied the current migration set: `migrations_applied=6`; store healthcheck returned `postgres_healthcheck=ok`.
- Strict runtime healthcheck passed: `healthcheck: ok`.
- JSON fallback without DB URL and without `DIET_BOT_ALLOW_JSON_STORAGE=1` was rejected with the expected runtime-config error.

Storage/runtime automated checks:

- Initial combined run was split after two environment-sensitive healthcheck tests inherited the Postgres DB URL and two persistent-DB payment tests hit stale fixed fake charge aliases from earlier test runs.
- Test DB cleanup was limited to known fake aliases with `order_id IS NULL`: removed 4 `processed_provider_charges` rows and 8 `payment_events` rows for `tg-charge-ru1`, `provider-charge-ru1`, `tg-charge-discount1`, and `provider-charge-discount1`.
- Storage/config/migration guard command passed: `32 passed, 1 skipped`.
- Postgres integration command passed: `33 passed`.
- Coverage included migrations, strict storage config, JSON fallback rejection, user/profile persistence, recipe history persistence, generation consumption/lock/refund behavior, promo redemption persistence, payment order/pre-checkout persistence, and successful-payment event/charge-alias persistence.
- No dedicated restart-durability helper/test was found in this slice; persistence was verified through Postgres round-trips and fresh DB connections in the existing integration tests.

Payment model/staging checks without real charges:

- Payment command passed with `TELEGRAM_PROVIDER_TOKEN` unset and fake/provider test IDs only: `137 passed, 21 deselected`.
- Coverage included create/reuse pending order, nonce payload validation, durable pre-checkout validation, successful-payment idempotency, fake charge alias recording, refunds, chargebacks, cancel-subscription events, orphan/pending reversal reconciliation, redaction, discounts, and promo-payment interaction.

Remaining paid-release blocker:

- Real provider smoke was not run because YooKassa/Telegram Stars can create real charges and no separate explicit approval/credentialed staging provider instruction was given.
- Paid launch remains blocked until either a staging provider smoke is run with explicit credentials/test-payment approval and recorded evidence, or public real-payment paths are disabled for the pilot.
