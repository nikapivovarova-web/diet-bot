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
- When payments are enabled, set `DIET_BOT_PAYMENT_RECOVERY_SPOOL` to a
  durable absolute path outside the repository, temp directories, and other
  ephemeral filesystems.

Payment recovery spool storage:

- The spool is required only when `DIET_BOT_PAYMENTS_ENABLED=1`.
- The operator must provision the parent directory before startup; bot startup
  must not create the parent directory.
- The path must be absolute, and the target path must be a file path, not a
  directory.
- Ownership and permissions must allow the bot process to create same-directory
  probe files, append-open the existing spool if present, flush, fsync, and
  unlink the startup probe.
- Keep the spool on durable storage with the production data backup and restore
  set. Include it in backup and restore drills alongside the Postgres backup
  artifact.
- Do not place the spool under the repository checkout, `.diet_bot_state` in a
  deploy tree, OS temp directories, container scratch space, or other ephemeral
  filesystems.
- Recovery replay uses the PR45 payment recovery replay tooling documented
  below. Review and fingerprint the immutable spool before dry-run or apply.

## Dependency Lock and Release Artifact

Production and staging installs must use the committed dependency locks under
`requirements/`. Do not install production from unconstrained
`pyproject.toml`, `pip install -e ".[dev]"`, or an operator-local dependency
cache.

Required release identity:

- git commit SHA;
- Python minor version used by the runtime;
- `requirements/prod.txt` SHA256;
- deploy artifact file name and SHA256, if a wheel or container image is built;
- external image digest, if deployment wraps the app in a container outside
  this repository.

This repository does not currently contain a Dockerfile or compose manifest.
If the deployment platform builds a container externally, the image must be
tagged with the git SHA and recorded with an immutable image digest. The
container build must still install from `requirements/prod.txt`.

Before building or packaging, verify the dependency locks from a clean checkout:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements\lock-tools.txt
.\.venv\Scripts\python.exe -m piptools compile requirements\lock-tools.in --resolver=backtracking --strip-extras --no-header --no-emit-index-url --allow-unsafe --output-file=requirements\lock-tools.txt
.\.venv\Scripts\python.exe -m piptools compile pyproject.toml --resolver=backtracking --strip-extras --no-header --no-emit-index-url --output-file=requirements\prod.txt
.\.venv\Scripts\python.exe -m piptools compile pyproject.toml --resolver=backtracking --strip-extras --extra=dev --no-header --no-emit-index-url --output-file=requirements\dev.txt
git diff --exit-code -- requirements\lock-tools.txt requirements\prod.txt requirements\dev.txt
```

Build and verify a production-style install without starting the bot:

```powershell
git rev-parse HEAD
Get-FileHash .\requirements\prod.txt -Algorithm SHA256
python -m venv .venv-release
.\.venv-release\Scripts\python.exe -m pip install -r requirements\prod.txt
.\.venv-release\Scripts\python.exe -m pip install --no-deps .
.\.venv-release\Scripts\python.exe -m pip check
.\.venv-release\Scripts\python.exe -m compileall -q src scripts
```

If the deploy process uses a wheel artifact, build it from the same clean
checkout and record its hash:

```powershell
.\.venv-release\Scripts\python.exe -m pip install -r requirements\lock-tools.txt
.\.venv-release\Scripts\python.exe -m build --wheel
Get-FileHash .\dist\*.whl -Algorithm SHA256
```

Install the wheel by first installing `requirements/prod.txt`, then installing
the wheel with `--no-deps` so deployment does not perform a second floating
resolution.

## Payment Scale Rehearsal

Use this rehearsal before payment enablement work and after payment ledger or
recovery changes. It uses only synthetic successful-payment events, fake
provider identifiers, and a throwaway/local test database or in-memory tests.
It must not set `TELEGRAM_PROVIDER_TOKEN`, enable real payments, start the bot
runtime, call Telegram, call a payment provider, deploy, restart, or touch a
production database.

Run the focused local rehearsal tests:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_payment_scale_rehearsal.py `
  tests\test_payment_service.py `
  tests\test_payment_recovery_spool.py `
  tests\test_payment_recovery_replay.py `
  tests\test_payment_recovery_spool_status.py `
  tests\test_payment_reconciliation_report.py
```

The rehearsal must prove:

- a synthetic successful payment grants the entitlement once;
- duplicate successful-payment charge events do not double-grant;
- a simulated ledger outage after Telegram charge notification writes the
  recovery spool;
- recovery dry-run identifies a replayable candidate;
- recovery apply grants exactly once;
- repeated recovery apply is idempotent and reports already recovered.

Preserve the test command and commit SHA in the release evidence. Treat this as
proof of local safety wiring only; real payment enablement still requires a
separate explicit approval.

## Payment Reconciliation Report

Use the reconciliation report with local files only. It accepts a synthetic or
exported fake-provider charge file plus a local payment ledger export file in
JSON or CSV. It never calls Telegram, never calls a payment provider API, and
does not require or read `TELEGRAM_PROVIDER_TOKEN`.

Example with JSONL output:

```powershell
.\.venv\Scripts\python.exe .\scripts\ops\payment_reconciliation_report.py `
  --provider-export ".\ops-input\fake-provider-charges.json" `
  --ledger-export ".\ops-input\payment-ledger-export.json" `
  --recovery-spool ".\ops-input\payment-recovery-spool.jsonl" `
  --format jsonl
```

The report categorizes local rows as:

- `matched_paid_granted`;
- `charged_but_not_granted`;
- `granted_but_no_provider_charge`;
- `duplicate_provider_charge_order`;
- `recovery_spool_candidate`.

Report output redacts order ids, chat/user ids, Telegram charge ids, provider
charge ids, invoice payloads, and raw spool content. Keep the input exports in
the operator evidence bundle, not in the repository.

## Payment Recovery Spool Status

Use spool status before payment enablement checks and during any incident where
the recovery spool is non-empty. The status command reports aggregate count,
bytes, malformed-line count, duplicate count, oldest/newest timestamps, and
oldest/newest age. It does not print invoice payloads, raw charge ids,
chat/user ids, tokens, or DSNs.

Example warning after 2 hours and failing after 8 hours:

```powershell
.\.venv\Scripts\python.exe .\scripts\ops\payment_recovery_replay.py status `
  --spool ".\ops-input\payment-recovery-spool.jsonl" `
  --warn-after-hours 2 `
  --fail-after-hours 8 `
  --max-records 100 `
  --json
```

If the status is `warn`, inspect and schedule replay. If the status is `fail`,
stop payment enablement or incident closure until the spool is reviewed,
reconciled, and replayed or explicitly waived by the payment operator.

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

## Postgres Backup And Restore Drill

Use this drill to prove a Postgres custom-format backup can be restored into a
generated disposable database. The drill prints sanitized JSON only: it reports
env var names, generated database names, backup file metadata, and table counts,
never raw DSNs, passwords, Telegram tokens, profile JSON, or payment payloads.

The machine running the drill must have PostgreSQL client tools installed:
`pg_dump` for backup and `createdb`, `pg_restore`, and `dropdb` for restore.
The scripts discover these tools from `PATH`, including Windows `.exe` and
`.cmd` executables. If `PATH` discovery is not suitable, set explicit executable
path overrides before running the scripts:

```powershell
$env:DIET_BOT_PG_DUMP_PATH = "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"
$env:DIET_BOT_CREATEDB_PATH = "C:\Program Files\PostgreSQL\16\bin\createdb.exe"
$env:DIET_BOT_PG_RESTORE_PATH = "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe"
$env:DIET_BOT_DROPDB_PATH = "C:\Program Files\PostgreSQL\16\bin\dropdb.exe"
```

Create the backup with a dedicated backup URL env var. Do not use
`DIET_BOT_DATABASE_URL`; the script intentionally does not fall back to the
runtime database URL.

```powershell
$env:DIET_BOT_BACKUP_DATABASE_URL = "<postgres-backup-dsn>"
.\.venv\Scripts\python.exe .\scripts\ops\postgres_backup.py `
  --source-url-env DIET_BOT_BACKUP_DATABASE_URL `
  --output-dir ".\ops-backups"
```

Run the restore drill with an admin URL that is allowed to create and drop only
the generated drill database. The restore target name is generated with a
`diet_bot_restore_drill_` marker and is dropped by default.

```powershell
$env:DIET_BOT_RESTORE_ADMIN_DATABASE_URL = "<postgres-admin-dsn>"
.\.venv\Scripts\python.exe .\scripts\ops\postgres_restore_drill.py `
  --backup-file ".\ops-backups\diet-bot-postgres-backup-YYYYMMDDTHHMMSSZ.dump" `
  --admin-url-env DIET_BOT_RESTORE_ADMIN_DATABASE_URL
```

For a source-to-restore row-count comparison, freeze writes first and keep them
frozen until the backup and comparison finish. Without frozen writes, row-count
differences can reflect normal traffic rather than restore failure.

```powershell
.\.venv\Scripts\python.exe .\scripts\ops\postgres_restore_drill.py `
  --backup-file ".\ops-backups\diet-bot-postgres-backup-YYYYMMDDTHHMMSSZ.dump" `
  --admin-url-env DIET_BOT_RESTORE_ADMIN_DATABASE_URL `
  --compare-source-url-env DIET_BOT_BACKUP_DATABASE_URL
```

Safety rules:

- Do not restore into any existing, production, or manually named database.
- Use `--keep-restore-db` only for supervised inspection, then drop the generated drill database manually.
- Do not run migrations, deploys, restarts, bot startup, Telegram API calls, or payment actions as part of this drill.
- Keep the sanitized JSON summaries with the backup artifact for audit.

## Payment Recovery Replay

Use this only for a reviewed payment recovery spool. The replay tool never
edits the spool; apply mode writes a separate redacted result JSONL file for
audit. No Telegram API call is needed.

Back up the production database first with the approved backup process. Keep
the backup artifact, the immutable spool, the list/dry-run outputs, and the
apply result JSONL together.

1. Put the reviewed spool in a read-only operator location. Do not edit,
   reformat, sort, or trim the spool after review starts.

2. List the spool and capture its fingerprint.

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\ops\payment_recovery_replay.py list `
     --spool ".\ops-input\payment-recovery-spool.jsonl" `
     --json
   ```

   Copy the reported `spool.fingerprint` value. It is formatted as
   `sha256:<digest>` and must be reused unchanged for dry-run and apply.

3. Run the database-backed dry-run preflight with the expected fingerprint.

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\ops\payment_recovery_replay.py dry-run `
     --spool ".\ops-input\payment-recovery-spool.jsonl" `
     --database-url-env DIET_BOT_DATABASE_URL `
     --expected-spool-fingerprint "sha256:<digest>" `
     --json
   ```

4. Review every blocked record before applying. Apply mode only attempts
   records whose preflight status is `replayable_candidate`. Records reported
   as `already_recovered` are recorded as no-op success, and blocked records
   are not applied.

5. Apply with the same expected fingerprint and a new result JSONL path.

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\ops\payment_recovery_replay.py apply `
     --spool ".\ops-input\payment-recovery-spool.jsonl" `
     --database-url-env DIET_BOT_DATABASE_URL `
     --expected-spool-fingerprint "sha256:<digest>" `
     --result-jsonl ".\ops-audit\payment-recovery-apply-YYYYMMDDTHHMMSSZ.jsonl"
   ```

6. Verify recovered orders and grants directly in the payment ledger and
   entitlement data using approved read-only database inspection. Do not use
   Telegram `getUpdates`, manual Telegram QA, provider token changes, deploys,
   restarts, or schema changes for this replay.

Exit codes:

- `0`: selected records were recovered, already recovered, or no-op skipped as already recovered.
- `1`: validation or apply blockers remain; inspect the redacted result JSONL.
- `2`: usage, config, or spool fingerprint mismatch; do not apply.
- `3`: database or unexpected runtime failure; stop and preserve the audit files.

Result JSONL rows contain only redacted audit fields: `timestamp`,
`record_id`, `preflight_status`, `apply_status`, `reason`, amount/currency,
provider, and redacted chat, user, and charge identifiers. They must not
contain invoice payloads, full charge IDs, chat/user IDs, tokens, raw provider
payloads, or database DSNs.

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

7. Apply one-day generation job migrations explicitly.

   ```powershell
   @'
   from diet_bot.postgres_one_day_generation_job_store import PostgresOneDayGenerationJobStore

   PostgresOneDayGenerationJobStore("<postgres-dsn>").initialize()
   '@ | .\.venv\Scripts\python.exe -
   ```

8. Apply payment ledger migrations with payments still disabled.

   ```powershell
   @'
   from diet_bot.postgres_payment_store import PostgresPaymentStore

   PostgresPaymentStore("<postgres-dsn>").initialize()
   '@ | .\.venv\Scripts\python.exe -
   ```

   This prepares the ledger schema for production preflight and future payment
   enablement. It does not enable live payments, does not require
   `TELEGRAM_PROVIDER_TOKEN`, and does not call Telegram or a payment provider.

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

## Production Preflight CLI

Run the production preflight after the required migrations and data imports are
complete, but before any deploy/start/restart action and before starting a
Telegram poller.

```powershell
.\.venv\Scripts\python.exe -m scripts.ops.production_preflight
```

The command is safe to run from an operator shell with production configuration
loaded through the approved secret manager. It never starts the bot runtime,
never starts polling, never creates a Telegram `Bot`, never calls Telegram API
methods such as `getUpdates`, and never calls a payment provider.

The preflight proves:

- strict production runtime configuration is present;
- `DIET_BOT_ENV` is `production` or `prod`;
- Postgres connectivity works with `DIET_BOT_DATABASE_URL`;
- entitlements, chat state, weekly PDF jobs, one-day generation jobs, and
  payment ledger schema/migration expectations are present;
- payment recovery spool readiness when payments are enabled or
  `DIET_BOT_PAYMENT_RECOVERY_SPOOL` is configured;
- the Postgres single-poller advisory guard can be acquired and released.

The preflight intentionally does not prove:

- Telegram bot token validity against Telegram servers;
- webhook/polling behavior or `getUpdates` behavior;
- support chat reachability or privacy URL public reachability;
- payment provider credentials or live payment authorization;
- that migrations should be applied automatically.

Output is operator-oriented `PASS`/`FAIL`/`SKIP` text and must not contain full
DSNs, bot tokens, provider tokens, payment payloads, raw chat IDs, or raw payment
identifiers. A failure exits nonzero and should be treated as a startup blocker
until the listed remediation is complete.

When `DIET_BOT_PAYMENTS_ENABLED=1`, the preflight requires
`TELEGRAM_PROVIDER_TOKEN` to be structurally present because production payment
UI includes provider-backed card payment paths. It only checks presence and does
not print or use the token. Keep payments disabled and leave the provider token
unset unless payment enablement is explicitly approved.

The payment recovery spool check may create same-directory probe files and may
create an empty configured spool file if it does not already exist. The
single-poller guard check briefly acquires the configured Postgres advisory lock
and releases it before the command exits.

## Runtime Ops Health Summary

Run the runtime ops health summary after preflight for launch readiness and on an
operator schedule during traffic. It is read-only: it connects to Postgres,
summarizes the local payment recovery spool if configured, optionally compares
local reconciliation files, and never starts the bot runtime, starts polling,
calls Telegram, calls `getUpdates`, or contacts a payment provider.

```powershell
$env:DIET_BOT_DATABASE_URL = "<postgres-dsn-from-secret-manager>"
$env:DIET_BOT_PAYMENT_RECOVERY_SPOOL = "<absolute-payment-recovery-spool-path>"
.\.venv\Scripts\python.exe -m scripts.ops.ops_health_summary --format table --fail-on-alert
```

Default alert thresholds are intentionally conservative:

- queue backlog: warning at 10 queued rows, fail at 50 queued rows per queue;
- worker stalled: warning when stale active jobs are at least 30 minutes old,
  fail at 2 hours;
- manual-review backlog: warning at 1 unresolved row, fail at 10 unresolved
  rows per queue;
- recovery spool non-empty: warning at 1 record, fail at 10 records;
- recovery spool age: warning at 1 hour, fail at 4 hours;
- DB unavailable: fail immediately.

Adjust thresholds with command flags only for an incident or load-test ticket,
and record the override in the operator notes. Use `--format json` for alert
ingestion. Use `--provider-export`, `--ledger-export`, and optionally
`--reconciliation-recovery-spool` only with local fake/synthetic files; the
command does not fetch provider data.

Alert owner actions:

- queue backlog: check worker logs, durable queue claims, concurrency settings,
  and whether exactly one intended poller/worker set is active; pause launch
  expansion until the queue drains or an approved recovery plan exists.
- worker stalled: preserve logs, inspect lease/heartbeat updates, and recover
  through approved retry/manual-review tooling only.
- recovery spool non-empty: preserve the immutable spool, run spool status and
  payment reconciliation, then dry-run recovery replay before any apply.
- manual-review backlog: run the relevant manual-review report, assign an
  operator owner, and decide customer action from existing evidence.
- backup failure: stop cutover work, rerun the backup/restore drill with
  sanitized output, and keep the failed artifact/log in the operator ticket.
- DB unavailable: treat as a launch blocker; verify the secret-manager DSN,
  database availability, network path, and recent maintenance.
- Telegram send/rate-limit spike: if logs or metrics show send failures or
  rate-limit responses, pause launch expansion, inspect send throttling and
  delivery markers, and use manual-review reports for ambiguous deliveries.

## Metabase Operations Dashboard

Metabase is the dashboard layer, not a replacement for runtime alerts. Install
or administer Metabase outside this repository, connect it only through an
approved read-only Postgres user, and keep DSNs/secrets in the deployment secret
manager rather than in dashboard SQL.

Create Metabase questions from the SQL pack in `scripts/ops/sql/metabase` and
keep the dashboard list aligned with `docs/ops/metabase-ops-queries.md`:

- active entitlements count;
- new paid grants/orders by day;
- failed payment/recovery candidates;
- one-day queue depth by status and failed/manual-review rows;
- weekly PDF queue depth by status and failed/manual-review rows;
- jobs older than threshold;
- schema migration version summary.

Backup/restore drill status is not represented in application tables. Attach or
link the sanitized JSON output from backup and restore drill runs as external
operator evidence.

## Weekly PDF Manual-Review Report

Run this report when reviewing weekly PDF delivery health. It is read-only and
lists unresolved jobs where the bot recorded a weekly PDF send attempt that
still needs operator evidence.

```powershell
$env:DIET_BOT_DATABASE_URL = "<postgres-dsn-from-secret-manager>"
.\.venv\Scripts\python.exe -m scripts.ops.weekly_pdf_manual_review_report --limit 50
```

For ticket attachment or structured review, use JSON output:

```powershell
.\.venv\Scripts\python.exe -m scripts.ops.weekly_pdf_manual_review_report --json --limit 50
```

If the deployment secret manager exposes the DSN under a different variable,
pass `--database-url-env <env-name>` instead of copying the DSN into the command.

The report does not print the DSN, bot tokens, provider tokens, raw chat IDs, or
idempotency keys. Chat IDs are shown only as stable `chat:sha256:<prefix>`
hashes so operators can compare repeated rows without exposing the raw
identifier.

Interpretation:

- `delivery_status=unknown` means Telegram upload was started, but the bot does
  not have a delivered marker. The user may or may not have received the PDF.
- `manual_review_reason` and `finalization_error` explain why the row entered
  manual review, for example stale finalization after a send attempt.
- `refund_status=not_required` on unknown delivery is intentional. Do not
  auto-refund or auto-credit from this report because delivery is ambiguous.
- Clean delivered successes are excluded. Rows with `manual_reviewed_at` are
  excluded by default; use `--include-reviewed` only for audit comparison.

Recovery workflow:

1. Capture the report output and the review time in the operator ticket.
2. Check application logs and existing operator/support evidence for the hashed
   chat/job pair. Do not use Telegram `getUpdates`, ad hoc Telegram QA, provider
   token changes, or production DB writes to investigate.
3. For unknown delivery, decide the customer action outside the bot: manual
   credit, manual refund, or no action. Record the evidence and decision in the
   operator ticket.
4. Do not mutate `weekly_pdf_jobs` manually and do not mark rows resolved until
   approved resolution tooling exists.

## One-Day Manual-Review Report

Run this report when reviewing one-day generation delivery health. It is
read-only and lists unresolved one-day jobs where the bot recorded ambiguous or
partial value-message delivery that still needs operator evidence.

```powershell
$env:DIET_BOT_DATABASE_URL = "<postgres-dsn-from-secret-manager>"
.\.venv\Scripts\python.exe -m scripts.ops.one_day_manual_review_report --limit 50
```

For ticket attachment or structured review, use JSON output:

```powershell
.\.venv\Scripts\python.exe -m scripts.ops.one_day_manual_review_report --json --limit 50
```

If the deployment secret manager exposes the DSN under a different variable,
pass `--database-url-env <env-name>` instead of copying the DSN into the command.

The report does not print the DSN, bot tokens, provider tokens, raw chat IDs,
idempotency keys, or metadata payloads. Chat IDs are shown only as stable
`chat:sha256:<prefix>` hashes so operators can compare repeated rows without
exposing the raw identifier.

Interpretation:

- `delivery_status=unknown` means the bot cannot prove complete delivery. The
  user may have received no value messages or only some value messages.
- Compare `expected_value_messages` and `delivered_value_messages` to distinguish
  no confirmed delivery from partial confirmed delivery.
- `failure_reason` and `finalization_error` explain why the row entered manual
  review, for example stale finalization after a send attempt or partial
  delivery failure.
- `refund_status=not_required` on unknown or partial delivery is intentional
  when any Telegram delivery may have occurred. Do not auto-refund or
  auto-credit from this report because delivery is ambiguous.
- Clean delivered successes are excluded. One-day jobs do not currently have
  reviewed-at or resolution fields, so there is no `--include-reviewed` mode.

Recovery workflow:

1. Capture the report output and the review time in the operator ticket.
2. Check application logs and existing operator/support evidence for the hashed
   chat/job pair. Do not use Telegram `getUpdates`, ad hoc Telegram QA, provider
   token changes, production DB writes, or bot runtime changes to investigate.
3. For unknown or partial delivery, decide the customer action outside the bot:
   manual credit, manual refund, or no action. Record the evidence and decision
   in the operator ticket.
4. Do not mutate `one_day_generation_jobs` manually and do not mark rows
   resolved until approved resolution tooling exists.

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
6. Apply one-day generation job migrations.
7. Apply chat state schema migrations.
8. Dry-run and then apply the JSON history/chat-state import.
9. Apply payment ledger migrations with payments still disabled.
10. Run strict production healthcheck.
11. Run production preflight.
12. Confirm only one poller will run.
13. Stop the old poller.
14. Start the new poller once.
15. Monitor process logs and health signals.

Do not use Telegram API calls or manual Telegram QA as part of this sequence
unless that QA is separately approved.

## Staging and Production Parity Checklist

Before production cutover, staging must rehearse the same release inputs without
touching production services:

- same git SHA, `requirements/prod.txt`, and wheel/container artifact intended
  for production;
- same Python minor version and same install pattern:
  `pip install -r requirements/prod.txt` followed by `pip install --no-deps`
  for the application artifact;
- same strict healthcheck and production preflight commands, with staging-safe
  environment values;
- isolated staging Postgres database and no production DSN;
- isolated staging bot token only if a separately approved staging bot run is
  performed;
- `TELEGRAM_PROVIDER_TOKEN` unset and payments disabled unless a separate
  payment QA or payment enablement approval explicitly says otherwise;
- same worker/poller flags, scheduler flags, and concurrency settings that
  production will use, with a recorded confirmation that only one poller can
  run for the token;
- same migration order rehearsed against staging data;
- monitoring, log redaction checks, queue-depth dashboards, and operator alert
  routes armed before the production window;
- rollback target identified by previous git SHA, previous artifact hash or
  image digest, and previous runtime configuration.

## Rollback Notes

Rollback depends on whether the new poller has processed production traffic.

- Before new traffic: stop the new poller, keep the Postgres migration records
  for audit, and restore the previous known-good application artifact or
  container image by its recorded SHA/digest.
- After new traffic: stop the new poller, preserve a fresh Postgres backup
  first, then decide whether to keep Postgres as source of truth or perform a
  supervised data rollback. Do not overwrite JSON/state from stale backups
  without an explicit data decision.
- After Postgres writes begin, JSON/state files are stale unless explicitly
  exported from Postgres. Do not restore stale JSON over Postgres production
  state; rollback must restore a known-good Postgres backup/snapshot or follow
  an explicit export/rollback procedure.
- If a schema migration succeeds but application startup fails, prefer rolling
  back application code/artifact first while leaving compatible dormant tables
  in place. Revert schema only with a migration-specific data decision and a
  fresh backup.
- Keep the previous artifact or image digest, previous git SHA, previous
  `requirements/prod.txt` SHA256, and previous runtime configuration in the
  operator ticket before cutover starts.
- Respect poller order during rollback: stop the failed/new poller first,
  verify it is not running, then start the previous known-good poller once.
- If payments remain disabled, no payment ledger rollback should be needed.

## Operator Safety Notes

- Never print bot tokens, provider tokens, or database DSNs in tickets, chat, logs, or pull requests.
- Production logs must not contain raw Telegram chat/user IDs, payment order IDs,
  Telegram/provider charge IDs, or job IDs. Use the centralized redacted
  fingerprints for correlation; raw identifiers belong only in access-controlled
  database rows or reviewed recovery tools.
- Do not put production DSNs or provider tokens into README examples.
- Use a unique entitlement `--migration-id` for each attempted import.
- Use a unique history/chat-state `--migration-id` for each attempted import.
- Keep the JSON backup and migration output together for audit.
- Treat payment enablement as a separate runbook and approval path.
