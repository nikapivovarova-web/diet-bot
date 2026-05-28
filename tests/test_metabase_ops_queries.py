from __future__ import annotations

from pathlib import Path


QUERY_DIR = Path("scripts/ops/sql/metabase")


def test_metabase_ops_query_pack_exists_and_uses_known_schema_names() -> None:
    expected = {
        "active_entitlements_count.sql",
        "new_paid_grants_by_day.sql",
        "failed_payment_recovery_candidates.sql",
        "one_day_queue_depth_by_status.sql",
        "one_day_failed_manual_review_rows.sql",
        "weekly_pdf_queue_depth_by_status.sql",
        "weekly_pdf_failed_manual_review_rows.sql",
        "jobs_older_than_threshold.sql",
        "schema_migration_version_summary.sql",
    }

    existing = {path.name for path in QUERY_DIR.glob("*.sql")}

    assert expected <= existing

    combined = "\n".join((QUERY_DIR / name).read_text(encoding="utf-8") for name in sorted(expected))
    for table_name in (
        "entitlements",
        "payment_orders",
        "payment_charges",
        "payment_events",
        "one_day_generation_jobs",
        "weekly_pdf_jobs",
        "schema_migrations",
    ):
        assert table_name in combined
    for status in ("queued", "running", "succeeded", "failed", "cancelled", "granted", "paid", "pending"):
        assert status in combined


def test_metabase_ops_queries_do_not_expose_raw_chat_ids_or_secret_placeholders() -> None:
    for path in QUERY_DIR.glob("*.sql"):
        sql = path.read_text(encoding="utf-8").lower()
        assert "telegram_provider_token" not in sql
        assert "bot_token" not in sql
        assert "password" not in sql
        assert "database_url" not in sql
        assert "select *" not in sql
        if "chat_id" in sql:
            assert "chat_id_hash" in sql


def test_metabase_manual_review_queries_filter_resolved_backlog() -> None:
    weekly_sql = (QUERY_DIR / "weekly_pdf_failed_manual_review_rows.sql").read_text(encoding="utf-8").lower()
    one_day_sql = (QUERY_DIR / "one_day_failed_manual_review_rows.sql").read_text(encoding="utf-8").lower()

    assert "manual_reviewed_at is null" in weekly_sql
    assert "manual_reviewed_at is null" in one_day_sql
    assert "manual_reviewed_by" in weekly_sql
    assert "manual_reviewed_by" in one_day_sql
    assert "manual_review_note" in weekly_sql
    assert "manual_review_note" in one_day_sql


def test_metabase_pack_and_alert_actions_are_documented_in_runbook() -> None:
    query_doc = Path("docs/ops/metabase-ops-queries.md").read_text(encoding="utf-8")
    runbook = Path("docs/production-runbook.md").read_text(encoding="utf-8")

    assert "scripts/ops/sql/metabase" in query_doc
    assert "Backup/restore drill status is not stored in the application database" in query_doc
    assert "Metabase Operations Dashboard" in runbook
    assert "Runtime Ops Health Summary" in runbook
    for alert in (
        "queue backlog",
        "worker stalled",
        "recovery spool non-empty",
        "manual-review backlog",
        "backup failure",
        "DB unavailable",
        "Telegram send/rate-limit spike",
    ):
        assert alert in runbook
