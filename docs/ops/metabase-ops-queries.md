# Metabase Ops Query Pack

This pack is a read-only dashboard layer for FoodBalance operations. Copy the SQL files from `scripts/ops/sql/metabase` into Metabase questions against the approved read-only Postgres connection. Do not paste DSNs, bot tokens, provider tokens, or production secrets into Metabase question text.

## Query List

- `active_entitlements_count.sql`: active subscription, test-access, and remaining-attempt inventory.
- `new_paid_grants_by_day.sql`: daily paid/granted order volume by product, provider, currency, and status.
- `failed_payment_recovery_candidates.sql`: paid-not-granted, old pending, failed, and orphan successful-payment candidates.
- `one_day_queue_depth_by_status.sql`: one-day durable queue depth and stale counts by status.
- `one_day_failed_manual_review_rows.sql`: one-day failed/unresolved manual-review rows with hashed chat identifiers and manual-resolution audit fields.
- `weekly_pdf_queue_depth_by_status.sql`: weekly PDF durable queue depth and stale counts by status.
- `weekly_pdf_failed_manual_review_rows.sql`: weekly PDF failed/unresolved manual-review rows with hashed chat identifiers and manual-resolution audit fields.
- `jobs_older_than_threshold.sql`: active one-day and weekly jobs older than the dashboard threshold.
- `schema_migration_version_summary.sql`: applied schema migration versions by component.

## Dashboard Layout

Use Metabase as visibility, not as the alerting source of truth. Pin these cards in this order:

1. Active entitlements and paid grants by day.
2. Payment recovery candidates.
3. One-day queue depth and one-day failed/manual-review rows.
4. Weekly PDF queue depth and weekly failed/manual-review rows.
5. Jobs older than threshold.
6. Schema migration version summary.

Backup/restore drill status is not stored in the application database. Keep it as an external evidence card or linked operator artifact from the sanitized JSON emitted by `scripts/ops/postgres_backup.py` and `scripts/ops/postgres_restore_drill.py`.

## Safety Notes

The row-level query files hash `chat_id` as `chat_id_hash` and avoid `SELECT *`.
Resolved manual-review rows are filtered out of unresolved backlog cards by
`manual_reviewed_at IS NULL`; use the report tools with `--include-reviewed` for
audit comparison. Restrict dashboard access to operators who already have
production-read approval, and use the runtime ops health summary for threshold
exit codes and incident gating.
