# Telegram Diet Bot MVP

MVP for a Telegram nutrition assistant for adults 18+.

The current clean release state focuses on:

- deterministic nutrition planning for one-day rations;
- Telegram polling with `/start`, `/plan`, and `/cancel`;
- explicit local/dev JSON state files for history, subscriptions, and promo codes;
- a fast local healthcheck for package data and runtime config;
- weekly ration delivery as a PDF document only.

Runtime storage must be selected explicitly. Local/dev JSON storage requires `DIET_BOT_ALLOW_JSON_STORAGE=1`; production-like or durable runs require `DIET_BOT_DATABASE_URL`.

## Local Environment

The app reads process environment variables. `.env.example` is a safe template for local values; copy it to `.env` only for your machine or deployment shell. `.env` and `.env.*` are ignored by git and must not be committed.

Required for local bot polling:

- `PYTHONPATH=src` when running from source without installing the package.
- `DIET_BOT_ENV=development` or another non-production value.
- `DIET_BOT_TOKEN=<telegram bot token>` from BotFather.
- Storage choice: set `DIET_BOT_ALLOW_JSON_STORAGE=1` for local/dev JSON, or set `DIET_BOT_DATABASE_URL=<postgresql://...>` for production-like durable storage.

Optional local settings:

- `TELEGRAM_BOT_TOKEN`: legacy alias used only when `DIET_BOT_TOKEN` is empty.
- `TELEGRAM_PROVIDER_TOKEN`: Telegram/YooKassa provider token for card payments; leave empty for local smoke if card payments are not being tested.
- `DIET_BOT_SUPPORT_CHAT_ID`: support chat target.
- `DIET_BOT_ADMIN_USER_IDS`: comma/space/semicolon separated Telegram user IDs.
- `DIET_BOT_TESTER_CHAT_IDS`: comma/space/semicolon separated tester chat IDs.
- `DIET_BOT_STATE_FILE`: default `.diet_bot_state/history.json`.
- `DIET_BOT_SUBSCRIPTIONS_STATE_FILE`: default `.diet_bot_state/subscriptions.json`.
- `DIET_BOT_PROMO_CODES_STATE_FILE`: default `.diet_bot_state/promo_codes.json`.

No payment webhook or external PDF service env is required in this clean state. Do not rely on implicit JSON fallback; set either `DIET_BOT_ALLOW_JSON_STORAGE=1` for local/dev JSON or `DIET_BOT_DATABASE_URL` for production-like storage.

## Run Telegram Bot Locally

From the clean worktree:

```powershell
Set-Location "C:\Users\adck8\Documents\New project 2 CLEAN"

$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
$env:DIET_BOT_ENV = "development"
$env:DIET_BOT_ALLOW_JSON_STORAGE = "1"
$env:DIET_BOT_TOKEN = "replace-with-telegram-bot-token"
$env:TELEGRAM_PROVIDER_TOKEN = ""

& $py -m diet_bot.telegram_app
```

If you use a virtualenv inside the clean worktree, set `$py` to `.\.venv\Scripts\python.exe` after installing the project dependencies.

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
