# Controlled Telegram QA Runbook

This runbook is for a limited Telegram QA pass before any real tester touches
the bot. It does not authorize production deploys, production starts, production
restarts, live payments, or Telegram API probing.

## Hard Boundaries

- Use a separate Telegram test bot token only. Never reuse the production bot
  token.
- Use an isolated staging, local, test, or throwaway Postgres database only.
  Do not point QA at the production database or production schema.
- Leave payments disabled. Keep `DIET_BOT_PAYMENTS_ENABLED` unset or set to
  `0`.
- Do not set `TELEGRAM_PROVIDER_TOKEN`.
- Do not use real users, paid users, or public bot announcements for QA.
- Scope QA to the explicit tester chat IDs in `DIET_BOT_TESTER_CHAT_IDS`.
- Do not run production deploy/start/restart commands for this QA pass.
- Do not run Telegram API probes such as `getUpdates`.

## Required QA Environment

Use deployment-approved secret handling. The values below are placeholders; do
not paste real tokens or DSNs into tickets, docs, commits, or pull requests.

```powershell
$env:DIET_BOT_ENV = "controlled-qa"
$env:DIET_BOT_TOKEN = "<separate-test-bot-token>"
$env:DIET_BOT_CONTROLLED_QA_BOT_TOKEN_MARKER = "test"
$env:DIET_BOT_STORAGE_BACKEND = "postgres"
$env:DIET_BOT_DATABASE_URL = "<isolated-staging-or-throwaway-postgres-dsn>"
$env:DIET_BOT_CONTROLLED_QA_DATABASE_MARKER = "staging"
$env:DIET_BOT_TESTER_CHAT_IDS = "<comma-separated-limited-tester-chat-ids>"
$env:DIET_BOT_PAYMENTS_ENABLED = "0"
Remove-Item Env:\TELEGRAM_PROVIDER_TOKEN -ErrorAction SilentlyContinue
```

Allowed `DIET_BOT_CONTROLLED_QA_DATABASE_MARKER` values are `local`,
`staging`, `stage`, `test`, `testing`, `throwaway`, and `sandbox`. The marker is
an explicit operator attestation; the preflight does not print or infer safety
from the DSN text.

## Preflight

Run the controlled-QA preflight before any staging bot start:

```powershell
.\.venv\Scripts\python.exe -m scripts.ops.production_preflight --mode controlled-qa
```

The controlled-QA preflight must not start the bot runtime or poller, must not
create a Telegram `Bot`, must not call Telegram API methods, and must not call a
payment provider. Output must not contain full DSNs, bot tokens, provider tokens, or raw tester chat IDs.

The preflight must pass before a separately approved staging QA run proceeds. A
failure is a startup blocker until the listed issue is fixed.

The preflight proves:

- the environment is explicitly non-production and not `production` or `prod`;
- the Telegram token has been explicitly marked as a test or sandbox token;
- Postgres storage and `DIET_BOT_DATABASE_URL` are configured;
- the database has an explicit non-production marker;
- payments are disabled and `TELEGRAM_PROVIDER_TOKEN` is absent;
- `DIET_BOT_TESTER_CHAT_IDS` contains at least one tester chat ID;
- the configured Postgres database is reachable;
- chat state, entitlement, weekly PDF job, one-day generation job, payment
  ledger schema, and single-poller guard checks pass.

The preflight intentionally does not prove:

- Telegram accepts the token or that the bot username is the intended test bot;
- the DSN is non-production beyond the operator marker and approved secret path;
- webhook or polling behavior;
- tester device behavior in Telegram;
- payment provider credentials or live payment authorization;
- that unknown people cannot message the test bot if the token or username is
  shared outside the tester list.

## QA Run

After preflight passes and the QA window is approved, start only the isolated
staging/test bot process with the environment above. Capture stdout/stderr or
platform logs for the whole run. Do not dump the full environment into logs.
Share the test bot only with the listed testers and keep the test window short.

The QA checklist should cover only the approved tester flows. Do not use real
payment cards, real provider tokens, paid users, or production data. If a tester
needs paid-mode behavior, use the configured tester access path instead of live
payments.

## Post-Run Checks

Preserve the preflight output and QA logs with secrets redacted. Then run the
manual-review reports against the same isolated QA database:

```powershell
.\.venv\Scripts\python.exe -m scripts.ops.weekly_pdf_manual_review_report --json --limit 50
.\.venv\Scripts\python.exe -m scripts.ops.one_day_manual_review_report --json --limit 50
```

Review any manual-review rows before closing QA. The reports are read-only and
must not print the DSN, tokens, raw chat IDs, idempotency keys, or metadata
payloads. If the QA owner approves closing a manual-review row in the isolated
QA database, use `scripts.ops.manual_review_resolution --dry-run` first and
then `--apply` with an operator name and ticket note. The resolver is audit-only:
it preserves delivery/refund fields and does not call Telegram or perform
refunds.

## Cleanup

- Stop only the staging/test bot process used for QA. Do not touch production.
- Preserve redacted logs, preflight output, report output, commit SHA, and tester
  list owner for audit.
- Remove the test bot token and QA-only environment variables from the operator
  shell or staging runner.
- Drop or archive the throwaway QA database according to the QA data-retention
  decision. Never reuse it as production state.
- Confirm `DIET_BOT_PAYMENTS_ENABLED` remains unset or `0` and
  `TELEGRAM_PROVIDER_TOKEN` remains absent.
