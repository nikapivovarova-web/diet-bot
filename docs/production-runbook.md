# Production Runbook

This runbook is for controlled production cutover of the Telegram Diet Bot.
It is intentionally operational only: it does not enable live payments, does
not require Telegram API QA, and does not run migrations automatically at bot
startup.

## Non-goals

- Do not enable live payments in this cutover.
- Do not set `TELEGRAM_PROVIDER_TOKEN` unless payment QA or payment enablement is explicitly approved.
- Do not enable `DIET_BOT_PAYMENTS_ENABLED` unless payment enablement is explicitly approved.
- Do not perform Telegram API QA such as `getUpdates` unless separately approved.
- Do not rely on bot startup to apply migrations.

## Production Environment Checklist

Production must use Postgres-backed storage. JSON storage is allowed only for
local development and for the pre-cutover source backup.

Required production configuration:

- `DIET_BOT_ENV=production`
- `DIET_BOT_TOKEN` or `TELEGRAM_BOT_TOKEN`
- `DIET_BOT_STORAGE_BACKEND=postgres`
- `DIET_BOT_DATABASE_URL`
- `DIET_BOT_SUPPORT_CHAT_ID`
- `DIET_BOT_PRIVACY_POLICY_URL`

Required support and privacy checks:

- The support chat id must route to the operational support chat.
- The privacy policy URL must be a public HTTP(S) URL.
- The bot must be able to show support and privacy information before payment enablement is considered.

Payment configuration:

- Payments remain off by default.
- Leave `DIET_BOT_PAYMENTS_ENABLED` unset or set to `0`.
- Leave `TELEGRAM_PROVIDER_TOKEN` unset unless payment QA or live payment enablement is explicitly approved.
- Do not add any payment provider token to shell history, logs, docs, or pull request text.

## Backup First

Before any migration, freeze writes as much as the operating model allows and
copy the JSON/state files to a timestamped backup location.

Back up at least:

- `.diet_bot_state/history.json`
- `.diet_bot_state/subscriptions.json`
- `.diet_bot_state/promo_codes.json`

Keep the backup read-only. Use the backed-up `subscriptions.json` as the source
for entitlement import and the backed-up `history.json` as the source for chat
state import so both migrations are reproducible.

## Migration Order

Run migrations explicitly, in this order, before starting the production bot.
Use deployment-approved secret handling for the Postgres DSN. The snippets
below use placeholders only.

1. Back up JSON/state first.

2. Apply entitlement migrations.

   ```powershell
   @'
   from diet_bot.postgres_entitlement_store import PostgresEntitlementStore

   PostgresEntitlementStore("<postgres-dsn>").initialize()
   '@ | .\.venv\Scripts\python.exe -
   ```

3. Migrate JSON entitlements to Postgres.

   Dry-run from the backup first:

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\migrate_entitlements_json_to_postgres.py `
     --source "<backup-dir>\subscriptions.json" `
     --migration-id "prod-entitlements-YYYYMMDD-HHMM" `
     --dry-run
   ```

   Apply only after the dry-run report is reviewed:

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\migrate_entitlements_json_to_postgres.py `
     --source "<backup-dir>\subscriptions.json" `
     --migration-id "prod-entitlements-YYYYMMDD-HHMM" `
     --database-url "<postgres-dsn>" `
     --apply
   ```

4. Apply weekly PDF job migrations explicitly.

   ```powershell
   @'
   from diet_bot.postgres_weekly_pdf_job_store import PostgresWeeklyPdfJobStore

   PostgresWeeklyPdfJobStore("<postgres-dsn>").initialize()
   '@ | .\.venv\Scripts\python.exe -
   ```

5. Apply chat state schema migrations explicitly.

   ```powershell
   @'
   from diet_bot.postgres_chat_state_store import PostgresChatStateStore

   PostgresChatStateStore("<postgres-dsn>").initialize()
   '@ | .\.venv\Scripts\python.exe -
   ```

6. Migrate JSON chat state history to Postgres.

   Dry-run from the backup first:

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\migrate_history_json_to_postgres.py `
     --source "<backup-dir>\history.json" `
     --migration-id "prod-history-YYYYMMDD-HHMM" `
     --dry-run
   ```

   Apply only after the dry-run report is reviewed:

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\migrate_history_json_to_postgres.py `
     --source "<backup-dir>\history.json" `
     --migration-id "prod-history-YYYYMMDD-HHMM" `
     --database-url "<postgres-dsn>" `
     --apply
   ```

7. Keep payment ledger migrations dormant and optional while payments are off.

   Payment ledger tables are not required for this cutover with payments
   disabled. Treat any payment ledger migration, provider-token setup, or live
   payment behavior as a separate approved payment change.

## Healthcheck And Preflight Order

Preflight should happen after configuration is loaded and after the required
schema/data migrations above are complete.

1. Confirm production env values are present through the deployment secret manager.
2. Confirm payments are disabled and provider token is absent unless separately approved.
3. Run strict config healthcheck:

   ```powershell
   .\.venv\Scripts\python.exe -m diet_bot.healthcheck --strict-production
   ```

4. Confirm the healthcheck reports `issues: none`.
5. Confirm the healthcheck prints only safe summaries such as `set` or `missing`, never secret values.
6. Confirm there is exactly one intended poller before startup.

Bot startup validates runtime configuration and Postgres schema readiness. It
must fail fast if required production config or schema is missing. Startup does
not apply migrations.

## One Poller Only

Run exactly one long-polling bot process for a bot token.

- Do not overlap old and new pollers with the same token.
- Do not run blue/green polling replicas unless the polling model has been changed.
- Stop or scale down the old poller before starting the new production poller.
- If startup fails, keep the old known-good poller as the rollback target rather than repeatedly restarting the new one.

## Controlled Cutover Sequence

1. Announce the cutover window and pause nonessential operator changes.
2. Back up JSON/state files.
3. Apply entitlement migrations.
4. Dry-run and then apply the JSON entitlement import.
5. Apply weekly PDF job migrations.
6. Apply chat state schema migrations.
7. Dry-run and then apply the JSON history/chat-state import.
8. Leave payment ledger migrations dormant unless separately approved.
9. Run strict production healthcheck.
10. Confirm only one poller will run.
11. Stop the old poller.
12. Start the new poller once.
13. Monitor process logs and health signals.

Do not use Telegram API calls or manual Telegram QA as part of this sequence
unless that QA is separately approved.

## Rollback Notes

Rollback depends on whether the new poller has processed production traffic.

- Before new traffic: stop the new poller, keep the Postgres migration records for audit, and restore the old poller with the original JSON/state files.
- After new traffic: stop the new poller, preserve a Postgres backup first, then decide whether to keep Postgres as source of truth or perform a supervised data rollback. Do not overwrite JSON/state from stale backups without an explicit data decision.
- After Postgres writes begin, JSON/state files are stale unless explicitly exported from Postgres. Do not restore stale JSON over Postgres production state; rollback must restore a known-good Postgres backup/snapshot or follow an explicit export/rollback procedure.
- If weekly PDF job migration succeeds but startup fails, it is safe to leave the dormant table in place while rolling back application code.
- If payments remain disabled, no payment ledger rollback should be needed.

## Operator Safety Notes

- Never print bot tokens, provider tokens, or database DSNs in tickets, chat, logs, or pull requests.
- Do not put production DSNs or provider tokens into README examples.
- Use a unique entitlement `--migration-id` for each attempted import.
- Use a unique history/chat-state `--migration-id` for each attempted import.
- Keep the JSON backup and migration output together for audit.
- Treat payment enablement as a separate runbook and approval path.
