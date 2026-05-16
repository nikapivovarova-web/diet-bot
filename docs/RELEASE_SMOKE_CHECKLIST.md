# Release Smoke Checklist

Use this checklist from the clean worktree before publishing a Telegram bot release.

## 1. Worktree And Env

- Confirm the current branch is `codex/emergency-stabilization`.
- Confirm only release documentation/env files are changed for a docs-only release.
- Confirm `.env.example` contains only placeholders and non-secret launch defaults.
- Confirm local `.env` exists only on the machine or deployment host and is not staged.
- Confirm `DIET_BOT_ENV` is the production/market-launch value on the deployment target; use `development` only for local no-payment smoke.
- Confirm `DIET_BOT_TOKEN` is set to the release Telegram bot token.
- For local/dev JSON smoke only, confirm `DIET_BOT_ALLOW_JSON_STORAGE=1` is set.
- For market launch and payment smoke, confirm `DIET_BOT_DATABASE_URL` points to PostgreSQL and local JSON fallback is not the active storage path.
- For payment invoice smoke, confirm `DIET_BOT_DATABASE_URL` points to Postgres. JSON mode is not valid for invoice smoke because payment orders require durable runtime storage.
- For market launch, confirm `TELEGRAM_PROVIDER_TOKEN` contains the live YooKassa Telegram provider token and is not printed in logs.
- For market launch, confirm `DIET_BOT_PUBLIC_PAYMENTS_ENABLED=1`; public YooKassa/Stars payment buttons must be visible with production prices.
- Confirm `DIET_BOT_PAYMENT_TEST_PRICES_ENABLED=0` for production/public launch.
- Confirm `DIET_BOT_TESTER_CHAT_IDS` is empty for market launch and payment smoke; tester chat grants can mask paywall and payment evidence.
- Use `DIET_BOT_ADMIN_USER_IDS` for owner/admin smoke access and smoke-price eligibility instead of tester-chat grants.
- Stars monthly is an auto-renewing Telegram Stars subscription: production price `450` Stars.
- YooKassa/card monthly access is a one-time 30-day purchase: production price `79900` minor units.
- One-day extra and weekly PDF extra are one-time purchases: `6900` minor units / `40` Stars and `34900` minor units / `199` Stars.
- Controlled-pilot docs are historical records, not the current release target.

## 2. Healthcheck

From `C:\Users\adck8\Documents\New project 2 CLEAN`:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
$env:DIET_BOT_ENV = "development"
$env:DIET_BOT_ALLOW_JSON_STORAGE = "1"

& $py -m diet_bot.healthcheck --package-data-only
& $py -m diet_bot.healthcheck
```

Both commands should print `healthcheck: ok`.

## 3. Test Gates

Fast release gate:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
& $py -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder"
```

Full local suite:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
& $py -m pytest -q -p no:cacheprovider
```

## 4. Start Bot / Deploy Target

Local no-payment smoke can use JSON storage and no provider token:

```powershell
Set-Location "C:\Users\adck8\Documents\New project 2 CLEAN"

$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
$env:DIET_BOT_ENV = "development"
$env:DIET_BOT_ALLOW_JSON_STORAGE = "1"
$env:DIET_BOT_TOKEN = "replace-with-telegram-bot-token"
$env:DIET_BOT_PAYMENT_TEST_PRICES_ENABLED = "0"
Remove-Item Env:\TELEGRAM_PROVIDER_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:\DIET_BOT_PUBLIC_PAYMENTS_ENABLED -ErrorAction SilentlyContinue

& $py -m diet_bot.telegram_app
```

Expected: the process starts polling without a startup config error.

Market-launch deployment must use durable production-style values instead of the local JSON smoke block:

```powershell
$env:DIET_BOT_ENV = "production"
$env:DIET_BOT_ALLOW_JSON_STORAGE = "0"
$env:DIET_BOT_DATABASE_URL = "postgresql://replace-with-production-postgres-url"
$env:DIET_BOT_TOKEN = "replace-with-release-telegram-bot-token"
$env:TELEGRAM_PROVIDER_TOKEN = "replace-with-live-yookassa-telegram-provider-token"
$env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "1"
$env:DIET_BOT_PAYMENT_TEST_PRICES_ENABLED = "0"
$env:DIET_BOT_ADMIN_USER_IDS = "replace-with-owner-telegram-user-id"
$env:DIET_BOT_TESTER_CHAT_IDS = ""
```

## 5. Manual Telegram Smoke

- Send `/start`; confirm the bot replies with the welcome flow and usable buttons.
- Start a one-day plan; complete sex, age, height, weight, goal, activity, meal count, allergies/restrictions, and excluded-food prompts.
- Confirm the generated one-day plan includes meals, portions, daily totals, and a shopping list.
- Tap the option to generate another one-day plan from the same profile; confirm a different/new plan is returned.
- Send `/plan`; confirm the plan flow can be started from the command.
- Send `/cancel` during an active flow; confirm state is cleared and the user can start again.
- If `DIET_BOT_SUPPORT_CHAT_ID` is configured, smoke the support request path and confirm the support chat receives the request.
- With admin access or an active paid subscription, request the weekly PDF ration; confirm Telegram receives a document attachment with a PDF file.
- For weekly PDF failures, confirm the bot shows a PDF failure/status message and does not send a text weekly-menu fallback.
- Confirm weekly PDF success sends only the PDF document plus its caption; no text fallback menu should appear before or after the document.
- Confirm `DIET_BOT_TESTER_CHAT_IDS` remains empty during payment smoke so paywall and payment gates are not bypassed.
- With `DIET_BOT_PUBLIC_PAYMENTS_ENABLED=1`, open the subscription/paywall path as a non-tester user and confirm YooKassa/card and Telegram Stars invoice buttons are visible.
- Confirm production prices are shown: monthly `799 RUB` / `450` Stars, one-day extra `69 RUB` / `40` Stars, weekly PDF extra `349 RUB` / `199` Stars.
- Confirm the Stars monthly path is labeled/handled as a subscription, while the card monthly path is a one-time 30-day access purchase.
- Confirm no `[TEST]` labels or smoke prices are visible while production pricing is active.
- If `TELEGRAM_PROVIDER_TOKEN` is empty in a non-launch local smoke, confirm card payment attempts do not create a broken invoice and the user receives a configuration message.
- If `TELEGRAM_PROVIDER_TOKEN` is set, smoke invoice creation only with the approved launch/payment-smoke account and record redacted evidence.

## 6. Payment Happy Path Smoke

Run this against the market-launch deployment or a production-equivalent deployment before opening paid traffic. It is the paid launch gate for YooKassa/Card, Telegram Stars, entitlement grants, and PDF delivery evidence.

Paid public release is blocked if public payments are disabled, payment test prices are enabled, tester chat grants are configured, or recorded YooKassa and Telegram Stars evidence is missing.

Payment invoice smoke must run with `DIET_BOT_DATABASE_URL` configured for Postgres. Do not use `DIET_BOT_ALLOW_JSON_STORAGE=1` or JSON fallback for this slice; invoice creation requires durable payment order storage and JSON mode should report unavailable/durable-store-required.

### Provider Smoke With Test Prices (Not Launch Config)

Use this slice only when the owner is ready to manually test provider checkout with minimal amounts. Do not run real payments from the development machine as part of this checklist, and do not leave these smoke settings in the production/public launch environment.

Set these env vars for the smoke deployment/session:

```powershell
$env:DIET_BOT_DATABASE_URL = "postgresql://diet_bot@localhost:5432/diet_bot_test"
Remove-Item Env:\DIET_BOT_ALLOW_JSON_STORAGE -ErrorAction SilentlyContinue
$env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "1"
$env:DIET_BOT_PAYMENT_TEST_PRICES_ENABLED = "1"
$env:DIET_BOT_ADMIN_USER_IDS = "replace-with-owner-telegram-user-id"
$env:DIET_BOT_TESTER_CHAT_IDS = ""
$env:TELEGRAM_PROVIDER_TOKEN = "replace-with-yookassa-telegram-test-provider-token"
```

Expected behavior:

- Only users whose Telegram user id is in `DIET_BOT_ADMIN_USER_IDS` should be used for this smoke. Keep tester chat ids empty so free/test access does not mask payment gates.
- Telegram Stars monthly smoke invoice uses provider `telegram_stars`, currency `XTR`, amount `1`, and the normal recurring 30-day subscription period.
- YooKassa/card monthly smoke invoice uses provider `yookassa`, currency `RUB`, amount `10_000` minor units (`100.00 RUB`), `need_email=True`, `send_email_to_provider=True`, and receipt provider data for `100.00 RUB`.
- Non-tester users still see and receive production subscription prices: `450` Stars or `79900` minor units (`799.00 RUB`).
- Pending discount promo codes are not consumed by this test-price smoke order; verify normal promo behavior separately with production pricing.

After the smoke, immediately turn the slice off:

```powershell
$env:DIET_BOT_PAYMENT_TEST_PRICES_ENABLED = "0"
```

Also confirm the deployment/runtime environment has payment test prices disabled before leaving the smoke session.

### Preflight Production-Like Config

- Confirm the bot build, branch, commit, deployment target, and `DIET_BOT_ENV` value.
- Confirm `DIET_BOT_DATABASE_URL` is configured for the production-like environment.
- Confirm JSON fallback is not active; invoice smoke in JSON mode is invalid and must stop with a durable-store-required/unavailable message.
- Confirm `DIET_BOT_PUBLIC_PAYMENTS_ENABLED=1` for market launch and that production pricing is active.
- Confirm the deployment uses durable DB-backed storage for payment orders, payment events, processed provider charges, entitlements, promo/test grants, and generation state.
- Confirm production-like startup rejects JSON paid-state fallback and the active environment is not writing payment state to local JSON files.
- Run strict healthcheck and save the exact redacted output.
- Confirm Telegram bot token, YooKassa provider token, database URL, support/admin ids, and any receipt/customer data are absent from logs.
- Confirm privacy/support path is visible before YooKassa/card payment collects email/receipt data.
- Confirm disposable test users/orders are used and a DB restore/reset plan exists before live-provider smoke.

### Subscription Invoices

- Telegram Stars monthly subscription:
  - Create a `subscription_month` invoice with provider `telegram_stars`, currency `XTR`, amount `450`, and recurring 30-day subscription period.
  - Confirm invoice payload is an order nonce payload like `diet:order:<order_id>:<nonce>`, not a static product payload.
  - Pay through Telegram Stars and confirm the order becomes `paid`, a `successful_payment` event is recorded, processed charge aliases are stored, and the monthly entitlement period plus limits are active.
  - Try to start a second active Stars monthly subscription and confirm the duplicate subscription guard prevents a second grant or second active managed subscription.
  - In the subscriber cabinet, cancel Stars renewal; confirm the paid access period remains active until period end.
  - In the subscriber cabinet, re-enable Stars renewal and confirm the cabinet status reflects renewal enabled again.
- YooKassa/card monthly access:
  - Create a `subscription_month` invoice with provider `yookassa`, currency `RUB`, amount `79900`, `need_email=True`, `send_email_to_provider=True`, and receipt provider data.
  - Complete a test card payment through Telegram Payments and confirm durable order/event/processed-charge/entitlement transition for one-time 30-day access.
  - Confirm the subscriber cabinet renewal controls are absent on the card monthly access path.
  - Confirm email, phone, full `order_info`, receipt/customer payload, provider token, bot token, and database URL are not present in general logs or support messages.

### Extras And Access Rules

- With an active paid subscription, buy `extra_one_day`; confirm exactly one extra one-day attempt is granted and recorded against the paid order/event.
- With an active paid subscription, buy `extra_weekly_pdf`; confirm exactly one extra weekly PDF attempt is granted and recorded against the paid order/event.
- Without an active paid subscription, attempt `extra_one_day` and `extra_weekly_pdf`; confirm the purchase is rejected before checkout where possible and remains rejected at final application if state changes between invoice and success.
- Generate a one-day ration after subscription or extra purchase and confirm the expected quota source is consumed once.
- Generate a weekly PDF after subscription or extra purchase and confirm Telegram receives a document PDF, with no text weekly-menu fallback.

### Rejection, Replay, And Durability

- `pre_checkout` reject checks where feasible:
  - tampered payload or nonce;
  - expired pending order;
  - wrong amount;
  - wrong currency/provider family;
  - wrong user or delivery chat, if a test helper or safe manual setup exists.
- Replay the same `successful_payment` update or fixture twice; confirm the second run is duplicate/no-op and does not grant subscription limits or extras again.
- Restart the bot process after a successful payment; confirm orders, events, processed charges, entitlements, extras, and generation quota state survive restart.
- Repeat one idempotency/replay check after restart.

### Evidence Checklist

- Bot/environment: bot username/id, deployment target, branch, commit SHA, `DIET_BOT_ENV`, and timestamp.
- Healthcheck: exact command and redacted output.
- Order evidence: internal `order_id`, provider, product, amount, currency, status, timestamps, and invoice link presence without leaking tokens.
- Charge evidence: Telegram/provider charge ids redacted or partially masked; do not paste full charge ids into general release notes.
- DB evidence: redacted query/output showing order status, payment event status, processed charge record, entitlement period/limits, and relevant generation quota state.
- User-facing evidence: screenshots of invoice, payment success, entitlement/cabinet status, extra purchase result, and PDF document delivery.
- Log evidence: only short snippets with secrets, tokens, database URLs, email, phone, receipt/customer data, and full raw provider payloads redacted.

### Non-Goals And Launch Gate

- Stars renewal cancel/re-enable belongs in the current subscription smoke. Refund, chargeback, and admin reconciliation smoke belong in a separate section after that wiring exists.
- Do not approve production launch until P0 paid-launch items are complete and this manual payment smoke passes with recorded evidence.

## 7. Release Notes

- Record the exact healthcheck output.
- Record the fast-test command and result.
- Record the full-test command and result if it was run for the release.
- Record manual Telegram smoke results, including the weekly PDF-only check.
- Record that the release is market launch mode with public payments enabled, production prices active, payment test prices disabled, and tester chat grants empty.
- Record payment happy-path smoke evidence only after the production-like payment stack exists and the smoke is actually run.
