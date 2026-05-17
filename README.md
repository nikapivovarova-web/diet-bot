# Telegram Diet Bot MVP

MVP for a Telegram nutrition assistant for adults 18+.

The current clean release state focuses on:

- deterministic nutrition planning for one-day rations;
- Telegram polling with `/start`, `/plan`, and `/cancel`;
- explicit local/dev JSON state files for history, subscriptions, and promo codes;
- market-launch public YooKassa/Stars payments with production pricing;
- a fast local healthcheck for package data and runtime config;
- weekly ration delivery as a PDF document only.

Runtime storage must be selected explicitly. Local/dev JSON storage requires `DIET_BOT_ALLOW_JSON_STORAGE=1`; production-like or durable runs require `DIET_BOT_DATABASE_URL`.

## Environment

The app reads process environment variables. `.env.example` is a safe template with placeholders; copy it to `.env` only for your machine or deployment shell. `.env` and `.env.*` are ignored by git and must not be committed.

Required for local bot polling:

- `PYTHONPATH=src` when running from source without installing the package.
- `DIET_BOT_ENV=development` or another non-production value.
- `DIET_BOT_TOKEN=<telegram bot token>` from BotFather.
- Storage choice: set `DIET_BOT_ALLOW_JSON_STORAGE=1` for local/dev JSON, or set `DIET_BOT_DATABASE_URL=<postgresql://...>` for production-like durable storage.

Optional settings:

- `TELEGRAM_BOT_TOKEN`: legacy alias used only when `DIET_BOT_TOKEN` is empty.
- `TELEGRAM_PROVIDER_TOKEN`: Telegram/YooKassa provider token for card payments; required for market-launch YooKassa invoices and left empty only for local no-card smoke.
- `DIET_BOT_PUBLIC_PAYMENTS_ENABLED`: set `1` for market launch so public YooKassa/Stars invoice buttons are visible. Use value `0` only for local no-payment smoke or explicitly historical controlled-pilot runs.
- `DIET_BOT_PAYMENT_TEST_PRICES_ENABLED`: keep `0` for production and public launch. Approved provider smoke uses separate smoke pricing: 1 Star for the recurring Stars monthly subscription and 100 RUB / 10_000 minor units for one-time YooKassa monthly access.
- `DIET_BOT_SUPPORT_CHAT_ID`: support chat target.
- `DIET_BOT_ADMIN_USER_IDS`: comma/space/semicolon separated Telegram user IDs.
- `DIET_BOT_TESTER_CHAT_IDS`: comma/space/semicolon separated tester chat IDs. Keep empty for market launch and payment smoke because tester access can mask paywall behavior; use `DIET_BOT_ADMIN_USER_IDS` for owner/admin smoke, including smoke prices.
- `DIET_BOT_STATE_FILE`: default `.diet_bot_state/history.json`.
- `DIET_BOT_SUBSCRIPTIONS_STATE_FILE`: default `.diet_bot_state/subscriptions.json`.
- `DIET_BOT_PROMO_CODES_STATE_FILE`: default `.diet_bot_state/promo_codes.json`.

## Launch Attribution

Ad and launch attribution is first-party only and requires PostgreSQL storage. Telegram deep-link campaign payloads use this format:

```text
https://t.me/FoodbalanceRu_bot?start=<source>_<campaign>
```

Example: `https://t.me/FoodbalanceRu_bot?start=ig_ad_001`. The first valid `/start` payload stores first-touch source/campaign/referral for that Telegram user; repeated `/start` payloads do not overwrite it.

No payment webhook or external PDF service env is required in this clean state. Do not rely on implicit JSON fallback; set either `DIET_BOT_ALLOW_JSON_STORAGE=1` for local/dev JSON or `DIET_BOT_DATABASE_URL` for production-like storage.

## Payment Model

- Telegram Stars monthly is a true auto-renewing Telegram Stars subscription: production price `450` Stars, smoke price `1` Star, and the subscription behavior still applies in smoke.
- YooKassa/card monthly is a one-time 30-day access purchase: production price `799 RUB`, smoke price `100 RUB` / `10_000` minor units. Users buy the next period manually.
- One-day extra and weekly PDF extra are one-time purchases: production prices `69 RUB` / `40` Stars and `349 RUB` / `199` Stars.
- The subscriber cabinet exposes cancel/re-enable controls only for Stars subscription renewal. Canceling renewal keeps paid access active until the current period end.

## Run Telegram Bot Locally

From the clean worktree for local no-payment smoke:

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

If you use a virtualenv inside the clean worktree, set `$py` to `.\.venv\Scripts\python.exe` after installing the project dependencies. Do not use the local JSON smoke block as a market-launch deployment config.

## Healthcheck

Package/data-only healthcheck:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
& $py -m diet_bot.healthcheck --package-data-only
```

Default local runtime healthcheck:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
$env:DIET_BOT_ENV = "development"
$env:DIET_BOT_ALLOW_JSON_STORAGE = "1"
& $py -m diet_bot.healthcheck
```

Expected success output is `healthcheck: ok`.

## Tests

Fast release gate, excluding slow PDF builder checks:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
& $py -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder"
```

Full local test suite:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
& $py -m pytest -q -p no:cacheprovider
```

## Weekly PDF Delivery

Weekly rations are delivered only as a Telegram PDF document. The bot must not send a text weekly-menu fallback when PDF rendering, file size validation, or document upload fails. Release smoke should verify this behavior manually and through the existing tests.

## Release Smoke

Before a release, run the manual Telegram smoke checklist in `docs/RELEASE_SMOKE_CHECKLIST.md`.

Market launch requires public payments enabled, production prices, a live YooKassa Telegram provider token, production PostgreSQL storage, disabled payment test prices, and empty tester chat grants. Use `DIET_BOT_ADMIN_USER_IDS` for owner/admin smoke access so payment gates are not hidden by tester access. Do not run public launch with payment test prices enabled.
