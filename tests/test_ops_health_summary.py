from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from diet_bot.payment_recovery_spool import PaymentRecoveryRecord, append_payment_recovery_record


def test_queue_depth_and_stale_jobs_escalate_from_warn_to_fail() -> None:
    from diet_bot.ops import ops_health_summary as health

    thresholds = health.AlertThresholds(
        queue_warn=2,
        queue_fail=5,
        stale_warn_seconds=300,
        stale_fail_seconds=900,
        manual_review_warn=1,
        manual_review_fail=10,
        recovery_spool_warn_count=1,
        recovery_spool_fail_count=10,
        recovery_spool_warn_after_seconds=3600,
        recovery_spool_fail_after_seconds=14_400,
    )
    snapshot = _snapshot(
        one_day=health.JobQueueSummary(
            counts_by_status={"queued": 3, "running": 1},
            stale_count=1,
            max_stale_age_seconds=600,
            manual_review_count=0,
            failed_manual_review_count=0,
        )
    )

    report = health.evaluate_ops_health(snapshot, thresholds=thresholds, recovery_spool=None)

    assert report.status == "warn"
    assert {alert.code for alert in report.alerts} >= {
        "one_day_queue_depth_warn",
        "one_day_stale_jobs_warn",
    }

    failing_snapshot = replace(
        snapshot,
        one_day=replace(
            snapshot.one_day,
            counts_by_status={"queued": 6, "running": 1},
            max_stale_age_seconds=1_200,
        ),
    )

    failing_report = health.evaluate_ops_health(failing_snapshot, thresholds=thresholds, recovery_spool=None)

    assert failing_report.status == "fail"
    assert {alert.code for alert in failing_report.alerts} >= {
        "one_day_queue_depth_fail",
        "one_day_stale_jobs_fail",
    }


def test_manual_review_and_recovery_spool_backlog_trigger_alerts(tmp_path: Path) -> None:
    from diet_bot.ops import ops_health_summary as health

    thresholds = health.AlertThresholds(
        queue_warn=10,
        queue_fail=50,
        stale_warn_seconds=300,
        stale_fail_seconds=900,
        manual_review_warn=1,
        manual_review_fail=2,
        recovery_spool_warn_count=1,
        recovery_spool_fail_count=3,
        recovery_spool_warn_after_seconds=60,
        recovery_spool_fail_after_seconds=120,
    )
    now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    spool_path = tmp_path / "payment-recovery.jsonl"
    append_payment_recovery_record(
        spool_path,
        PaymentRecoveryRecord(
            provider="telegram_stars",
            chat_id=123456789,
            user_id=987654321,
            invoice_payload="invoice-payload",
            telegram_payment_charge_id="telegram-charge-1",
            currency="XTR",
            total_amount=100,
            created_at=datetime(2026, 5, 28, 11, 55, tzinfo=UTC),
        ),
    )
    spool = health.summarize_recovery_spool_for_health(spool_path, thresholds=thresholds, now=now)
    snapshot = _snapshot(
        weekly=health.JobQueueSummary(
            counts_by_status={"queued": 0, "running": 0},
            stale_count=0,
            max_stale_age_seconds=None,
            manual_review_count=2,
            failed_manual_review_count=1,
        )
    )

    report = health.evaluate_ops_health(snapshot, thresholds=thresholds, recovery_spool=spool)
    payload = report.to_redacted_dict()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert report.status == "fail"
    assert {alert.code for alert in report.alerts} >= {
        "weekly_pdf_manual_review_fail",
        "payment_recovery_spool_oldest_age_fail",
    }
    assert str(spool_path) not in serialized
    assert "123456789" not in serialized
    assert "987654321" not in serialized
    assert "telegram-charge-1" not in serialized


def test_db_unavailable_returns_nonzero_and_redacts_dsn() -> None:
    from diet_bot.ops import ops_health_summary as health

    stdout = io.StringIO()
    stderr = io.StringIO()
    dsn = "postgresql://ops_user:super-secret@db.example.invalid/diet_bot"

    exit_code = health.main(
        ["--fail-on-alert"],
        env={"DIET_BOT_DATABASE_URL": dsn},
        connection_factory=lambda _dsn: (_ for _ in ()).throw(RuntimeError(f"cannot connect to {dsn}")),
        stdout=stdout,
        stderr=stderr,
    )

    output = stdout.getvalue() + stderr.getvalue()
    assert exit_code == 1
    assert "db_unavailable" in output
    assert dsn not in output
    assert "super-secret" not in output
    assert "postgresql://<redacted>" in output


def _snapshot(
    *,
    one_day: object | None = None,
    weekly: object | None = None,
):
    from diet_bot.ops import ops_health_summary as health

    empty_queue = health.JobQueueSummary(
        counts_by_status={"queued": 0, "running": 0},
        stale_count=0,
        max_stale_age_seconds=None,
        manual_review_count=0,
        failed_manual_review_count=0,
    )
    return health.DatabaseHealthSnapshot(
        connected=True,
        schema=health.SchemaSummary(
            present_tables=tuple(health.REQUIRED_TABLES),
            missing_tables=(),
            migration_count=7,
            latest_migration_version="202605280001",
        ),
        entitlements=health.EntitlementSummary(total_count=4, active_count=2),
        payments=health.PaymentSummary(
            counts_by_status={"pending": 0, "paid": 0, "granted": 0, "failed": 0},
            paid_not_granted_count=0,
            old_pending_count=0,
            failed_count=0,
        ),
        one_day=one_day or empty_queue,
        weekly=weekly or empty_queue,
    )
