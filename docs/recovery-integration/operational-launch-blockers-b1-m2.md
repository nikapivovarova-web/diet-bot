# Operational Launch Blockers B-1/M-2 Evidence

Date: 2026-06-02

Scope: operational evidence for B-1 production-env validation visibility and
M-2 backup/restore drill only. This pass did not start the bot, call Telegram,
call `getUpdates`, enable payments, set provider credentials, run payment
refund/cancel/reversal flows, deploy, push, merge, commit, tag, or use a
production database for destructive testing.

## Provenance

- Workdir: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `35c2c8584e5cd1afc93c1bd9b8a8997a9d2b1c93`
- Pre-existing dirty tracked files at the start of this pass:
  - `src/diet_bot/builder.py`
  - `src/diet_bot/postgres_sales_followup_migrations.py`
  - `src/diet_bot/telegram_app.py`
  - `tests/test_postgres_migration_versions.py`
  - `tests/test_postgres_sales_followup_store.py`
  - `tests/test_safety_and_builder.py`

## B-1: Production Env Visibility

Status: CLOSED for the validation process.

The latest verified non-payment readiness gate closed B-1 for validation:
strict healthcheck, controlled-QA preflight, and production-mode preflight
passed without printing secret values. This evidence closes production-env
visibility for the validation process only; it does not enable provider
credentials or authorize payment/refund/cancel/reversal flows.

Current closure state before the payment/provider gate:

- H-1: CLOSED.
- M-1: CLOSED.
- M-2: CLOSED.
- B-1: CLOSED for the validation process.
- Remaining paid-launch/large-advertising gate: payment/provider acceptance.

## M-2: Backup/Restore Drill

Status: CLOSED for disposable/local drill evidence.

Native local PostgreSQL client commands were not on PATH, and no explicit
`DIET_BOT_PG_DUMP_PATH`, `DIET_BOT_CREATEDB_PATH`,
`DIET_BOT_PG_RESTORE_PATH`, or `DIET_BOT_DROPDB_PATH` overrides were set.
Instead of installing global tools, this pass used scoped temporary client
shims backed by the already-local `postgres:16-alpine` Docker image.

The drill used only a disposable local Docker Postgres instance. It created a
generated source database, initialized the required FoodBalance Postgres store
schemas, seeded one row in each critical table, ran the repo backup script, ran
the repo restore drill script with source-to-restore row-count comparison, then
dropped both generated databases.

Sanitized evidence bundle:

- Evidence root:
  `C:\Users\adck8\AppData\Local\Temp\foodbalance-b1-m2-20260602105657-27a77a87`
- Source database:
  `diet_bot_restore_source_test_43a6070cccea48b5a008254ac399d6ee`
- Backup file:
  `C:\Users\adck8\AppData\Local\Temp\foodbalance-b1-m2-20260602105657-27a77a87\ops-backups\diet-bot-postgres-backup-20260602T065704Z.dump`
- Backup size: `55599` bytes
- Restore database:
  `diet_bot_restore_drill_20260602t065706z_89cd3039`
- Restore cleanup: `dropdb` ran; restore database was not kept
- Required table count compared: `17`
- Source-to-restore row counts: all matched
- Row-count mismatch waiver: not used
- Remaining generated databases after cleanup: none

Commands, with disposable secrets intentionally omitted:

```powershell
docker run --rm -d --name <generated-local-container> `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=<disposable-local-password> `
  -e POSTGRES_DB=postgres `
  -p 127.0.0.1:<free-local-port>:5432 `
  postgres:16-alpine

$env:DIET_BOT_BACKUP_DATABASE_URL = "<disposable-source-dsn>"
$env:DIET_BOT_RESTORE_ADMIN_DATABASE_URL = "<disposable-admin-dsn>"
$env:DIET_BOT_PG_DUMP_PATH = "<temp-shim>\pg_dump.cmd"
$env:DIET_BOT_CREATEDB_PATH = "<temp-shim>\createdb.cmd"
$env:DIET_BOT_PG_RESTORE_PATH = "<temp-shim>\pg_restore.cmd"
$env:DIET_BOT_DROPDB_PATH = "<temp-shim>\dropdb.cmd"

.\.venv\Scripts\python.exe .\scripts\ops\postgres_backup.py `
  --source-url-env DIET_BOT_BACKUP_DATABASE_URL `
  --output-dir "<evidence-root>\ops-backups"

.\.venv\Scripts\python.exe .\scripts\ops\postgres_restore_drill.py `
  --backup-file "<evidence-root>\ops-backups\diet-bot-postgres-backup-20260602T065704Z.dump" `
  --admin-url-env DIET_BOT_RESTORE_ADMIN_DATABASE_URL `
  --compare-source-url-env DIET_BOT_BACKUP_DATABASE_URL
```

## Verdict

Ready for the payment/provider gate. H-1, M-1, M-2, and B-1 are closed for the
pre-payment validation process. The remaining gate before public paid launch or
large advertising is payment/provider acceptance only.
