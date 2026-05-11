# Telegram Diet Bot MVP

MVP for a Telegram nutrition assistant for adults 18+.

The current runtime is an `aiogram` polling bot. There is no HTTP API, webhook
mode, FastAPI app, Uvicorn server, nginx config, or HTTP `/health` endpoint in
this deployment path.

## What The Bot Does

- BMI, BMR, TDEE, calories, macros, and micronutrient targets.
- Allergy, gluten, lactose, and disease caution filters.
- Built-in curated recipe and nutrition data.
- One-day and weekly nutrition planning with portion and diversity guardrails.
- Telegram flows for questionnaires, plans, payments, subscriptions, support,
  promo codes, and PDF delivery.

OpenAI chef/dietitian adapters are planned for the future and can be installed
with the optional `ai` dependency group when that integration exists.

## Environment Setup

Create a local env file from the example:

```bash
cp .env.example .env
```

Fill in real values in `.env`. Do not commit `.env`. The healthcheck rejects
empty values and obvious placeholders such as `YOUR_POSTGRES_PASSWORD`.

### Required Env

- `DIET_BOT_ENV`: use `development` for local experiments and `production` for
  server/Docker production readiness checks.
- `DIET_BOT_TOKEN` or `TELEGRAM_BOT_TOKEN`: Telegram bot token. Set one of them.
- `DIET_BOT_DATABASE_URL`: PostgreSQL connection string. Required for Docker and
  production-like runs.
- `DIET_BOT_SUPPORT_CHAT_ID`: required in production. Telegram chat id where
  support requests are sent; private supergroups usually start with `-100`.
- `DIET_BOT_PRIVACY_POLICY_URL`: required in production. Must be a public HTTPS
  URL, not localhost, `.local`, or an example domain.

In production the bot refuses to start without `DIET_BOT_SUPPORT_CHAT_ID` and
`DIET_BOT_PRIVACY_POLICY_URL`.

### Payments

- `TELEGRAM_PROVIDER_TOKEN`: Telegram Payments provider token for YooKassa/card
  payments. Leave empty only when those payments are not configured.

### Docker Compose Database

- `POSTGRES_DB`: PostgreSQL database name used by the bundled Compose service.
- `POSTGRES_USER`: PostgreSQL user used by the bundled Compose service.
- `POSTGRES_PASSWORD`: PostgreSQL password used by the bundled Compose service.

`DIET_BOT_DATABASE_URL` must point to the same database. With the bundled Compose
PostgreSQL service, the host name is `postgres`.

For the local Docker setup, set one real password in both places:

```env
POSTGRES_PASSWORD=replace-with-a-real-local-password
DIET_BOT_DATABASE_URL=postgresql://diet_bot:replace-with-a-real-local-password@postgres:5432/diet_bot
```

### Optional Env

- `DIET_BOT_ADMIN_USER_IDS` or `DIET_BOT_ADMIN_IDS`: comma/space/semicolon-separated admin Telegram IDs.
- `DIET_BOT_TESTER_CHAT_IDS`: comma/space/semicolon-separated tester chat IDs.
- `DIET_BOT_ANALYTICS_ENABLED`: set to `1` to record product analytics events.
  When PostgreSQL is active, events are archived in `analytics_events`.
- `POSTHOG_API_KEY`: optional PostHog project API key. If empty, analytics can
  still be stored in PostgreSQL when enabled, but nothing is sent to PostHog.
- `POSTHOG_HOST`: optional PostHog host. Defaults to `https://app.posthog.com`.
  In production, it must be a public HTTPS URL when `POSTHOG_API_KEY` is set.
- `DIET_BOT_ANALYTICS_ID_SALT`: optional secret salt for pseudonymous PostHog
  `distinct_id` values and sanitized log identifiers. Changing it rotates
  analytics identities.
- `DIET_BOT_TEST_ACCESS_COMMAND`: optional hidden test-access command name,
  without the leading slash. Leave empty to disable the command.
- `DIET_BOT_DROP_PENDING_UPDATES`: set to `1` to drop stale Telegram updates when
  clearing webhook state before polling.
- `DIET_BOT_GENERATION_CLEANUP_INTERVAL_SECONDS`: stale generation cleanup loop
  interval. Defaults to `300`.
- `DIET_BOT_ALLOW_LEGACY_PAYLOADS_UNTIL`: optional ISO datetime for accepting
  legacy payment payloads during rotation.
- `DIET_BOT_ALLOW_JSON_STORAGE`: set to `1` only for local development when
  intentionally running without PostgreSQL. Production must leave this disabled
  and set `DIET_BOT_DATABASE_URL`.
- `DIET_BOT_STATE_FILE`, `DIET_BOT_SUBSCRIPTIONS_STATE_FILE`,
  `DIET_BOT_PROMO_CODES_STATE_FILE`, `DIET_BOT_PAYMENT_ORDERS_STATE_FILE`:
  local JSON state paths used only when `DIET_BOT_ALLOW_JSON_STORAGE=1` and
  `DIET_BOT_DATABASE_URL` is not set.

## Local Run

Install the package in a virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

Set the minimum local environment and run the polling bot:

```powershell
$env:DIET_BOT_TOKEN = "123456:telegram-token"
$env:DIET_BOT_DATABASE_URL = "postgresql://user:password@localhost:5432/diet_bot"
.\.venv\Scripts\diet-bot-telegram.exe
```

For local development without PostgreSQL, omit `DIET_BOT_DATABASE_URL` and set
`DIET_BOT_ALLOW_JSON_STORAGE=1`. The bot will use local JSON state files guarded
by a process/file lock for dev convenience. This JSON fallback is best-effort
development storage only: it is not crash-safe, not delivery-recoverable, and has
no recovery journal. Production must use PostgreSQL.

## Docker Compose Deployment

Edit `.env`, validate the Compose file, then build and start the bot plus
PostgreSQL:

```bash
docker compose config
docker compose up -d --build
```

The Docker build uses `requirements.lock` for production runtime dependencies,
installs the package with `--no-deps`, and runs the bot as a non-root user. The
`.dockerignore` file allow-lists only the files needed for the image, so `.env`,
local JSON state, tmp files, dumps, backups, tests, and local tooling are not
sent in the build context.

The Docker image build also runs:

```bash
python -m diet_bot.healthcheck --package-data-only
```

This fails the build if packaged JSON, PNG, or recipe-photo data is missing from
the installed wheel.

Watch bot logs:

```bash
docker compose logs -f bot
```

Restart only the bot:

```bash
docker compose restart bot
```

Stop the stack:

```bash
docker compose down
```

The bot container healthcheck runs:

```bash
python -m diet_bot.healthcheck --strict --polling-liveness
```

It verifies packaged data, production env values, support/privacy
configuration, pre-payment support/privacy buttons, and PostgreSQL with
`SELECT 1`. It also checks the local polling heartbeat file to catch a stuck or
dead polling process. It does not call the Telegram API. This keeps Docker
healthchecks local and avoids polling an external API every 30 seconds.

After startup, confirm the local Compose stack:

```bash
docker compose ps
docker compose exec bot python -m diet_bot.healthcheck --strict --polling-liveness
docker compose --profile smoke run --rm bot-smoke
```

The `bot` service should be healthy. If it is unhealthy, check that `.env`
contains `DIET_BOT_ENV=production`, a real bot token, a non-empty
`POSTGRES_PASSWORD`, a matching `DIET_BOT_DATABASE_URL`,
`DIET_BOT_SUPPORT_CHAT_ID`, and a public HTTPS `DIET_BOT_PRIVACY_POLICY_URL`.
The `bot-smoke` profile runs
`python -m diet_bot.healthcheck --strict --telegram` once and exits.

## Manual Health Checks

Check required local prerequisites:

```bash
python -m diet_bot.healthcheck
```

Check only packaged data, which is the same smoke used during Docker image
builds:

```bash
python -m diet_bot.healthcheck --package-data-only
```

Check production prerequisites, including packaged data, PostgreSQL, support,
privacy, and pre-payment buttons:

```bash
python -m diet_bot.healthcheck --strict
```

Check production prerequisites plus local polling liveness:

```bash
python -m diet_bot.healthcheck --strict --polling-liveness
```

Manually verify the Telegram token with `getMe` and the configured support chat
with `getChat`:

```bash
python -m diet_bot.healthcheck --strict --telegram
```

Use `--telegram` only for manual smoke checks.

## Server Readiness

Before moving the same setup to a server, create the server `.env` with real
secrets and run the full container smoke there:

```bash
docker compose config
docker compose up -d --build
docker compose exec bot python -m diet_bot.healthcheck --strict
docker compose --profile smoke run --rm bot-smoke
```

The strict healthcheck proves the container can read its env, packaged data, and
PostgreSQL and that polling liveness is fresh. The smoke profile proves the same
container image can also reach Telegram `getMe` and the configured support chat.

## Production Operations

The production runbook is in `docs/production-runbook.md`.

Create a PostgreSQL backup with retention:

```bash
BACKUP_DIR=/srv/diet-bot/backups RETENTION_DAYS=14 scripts/ops/backup_postgres.sh
```

Restore a backup into a disposable test database:

```bash
BACKUP_FILE=/srv/diet-bot/backups/diet_bot_YYYYMMDDTHHMMSSZ.dump \
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/diet_bot_test \
RESTORE_CONFIRM_TEST_DB=1 \
scripts/ops/restore_postgres_drill.sh
```

Run the local-only smoke/liveness check from cron or systemd alert hooks:

```bash
scripts/ops/smoke_liveness.sh
```

The backup and restore scripts read credentials from `DATABASE_URL`, `PG*`
environment variables, or Compose service env. They do not contain passwords.
The liveness script exits non-zero when config, PostgreSQL, or polling heartbeat
checks fail.

## JSON To PostgreSQL Migration

One-time migration from the old JSON state:

```powershell
$env:DIET_BOT_DATABASE_URL = "postgresql://user:password@localhost:5432/diet_bot"
.\.venv\Scripts\python.exe scripts\migrate_json_to_postgres.py --migration-id "prod-json-import-2026-05-11"
.\.venv\Scripts\python.exe scripts\migrate_json_to_postgres.py --apply --migration-id "prod-json-import-2026-05-11"
```

The first command is the default dry-run and prints an audit report without
writing imported state. The second command applies the import once, records it
in PostgreSQL `import_runs`, and refuses to reuse the same `--migration-id`.
Existing Postgres rows are treated as live state and are skipped, not
overwritten. After migration, production should keep `DIET_BOT_DATABASE_URL` set
so runtime state is stored in PostgreSQL only.

Promo-code runtime state stores hashed lookup keys, not plaintext bearer codes.
Keep any plaintext export used for distribution outside the deployed bot state
and delete it after the codes have been sent.

## Troubleshooting

If the bot does not answer:

1. Check `docker compose ps` and confirm `postgres` is healthy.
2. Run `docker compose logs -f bot`.
3. Run `docker compose exec bot python -m diet_bot.healthcheck --strict`.
4. Run `docker compose exec bot python -m diet_bot.healthcheck --strict --telegram`
   for a manual Telegram token smoke check.
5. Confirm that only one bot process is polling the same Telegram token.

FastAPI, Uvicorn, nginx, and webhook setup are intentionally absent for now.
They should be added only if the project gets a real HTTP API or webhook runtime.

## Tests

Fast tests are the required PR gate:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

Slow recipe/PDF builder checks are intentionally split out of the PR gate:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m slow_pdf_builder
```

Before any release that uses PostgreSQL, the live PostgreSQL integration path
must pass against a staging/test database:

```powershell
$env:DIET_BOT_TEST_DATABASE_URL = "postgresql://user:password@localhost:5432/diet_bot_test"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m postgres_integration --require-postgres tests/test_postgres_store.py tests/test_json_to_postgres_migration.py
```

Those tests run `PostgresDietBotStore.initialize()`, JSON-to-PostgreSQL migration
coverage, payment/order handling, generation locks, and refund behavior on a real
PostgreSQL database. `--require-postgres` makes the release check fail instead
of silently skipping when `DIET_BOT_TEST_DATABASE_URL` is missing.

For a full local release rehearsal with a test PostgreSQL database:

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:DIET_BOT_TEST_DATABASE_URL = "postgresql://user:password@localhost:5432/diet_bot_test"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --require-postgres
```

CI policy:

- `pull_request` and regular branch `push` run only the `fast` job.
- `integration-postgres` runs on `workflow_dispatch` and `v*` tag pushes.
- `slow-pdf-builder` runs on `workflow_dispatch`, schedule, and `v*` tag pushes.
- `full-suite` runs on `workflow_dispatch`, schedule, and `v*` tag pushes with a longer timeout.
- Docker smoke is manual or release-tag only.

Use `docs/regression-checklist.md` before release candidates and risky changes.
Cleanup of ignored local artifacts belongs in a separate hygiene PR and should
not be mixed with test, CI, or bot logic changes.

## Demo

```powershell
.\.venv\Scripts\python.exe -m diet_bot.demo
```
