from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

from diet_bot.log_redaction import redact_identifier
from diet_bot.payment_recovery_spool import PaymentRecoverySpoolSummary, summarize_payment_recovery_spool
from diet_bot.postgres_connection import redact_postgres_text


DEFAULT_DATABASE_URL_ENV = "DIET_BOT_DATABASE_URL"
DEFAULT_PAYMENT_RECOVERY_SPOOL_ENV = "DIET_BOT_PAYMENT_RECOVERY_SPOOL"

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
PAYMENT_STATUSES = ("pending", "paid", "granted", "failed")
REQUIRED_TABLES = (
    "schema_migrations",
    "entitlements",
    "payment_orders",
    "payment_charges",
    "payment_events",
    "one_day_generation_jobs",
    "weekly_pdf_jobs",
)

_POSTGRES_DSN_RE = re.compile(r"\bpostgres(?:ql)?://[^\s\"'<>]+", flags=re.IGNORECASE)


ConnectionFactory = Callable[[str], Any]


@dataclass(frozen=True)
class AlertThresholds:
    queue_warn: int = 10
    queue_fail: int = 50
    stale_warn_seconds: int = 30 * 60
    stale_fail_seconds: int = 2 * 60 * 60
    manual_review_warn: int = 1
    manual_review_fail: int = 10
    recovery_spool_warn_count: int = 1
    recovery_spool_fail_count: int = 10
    recovery_spool_warn_after_seconds: int = 60 * 60
    recovery_spool_fail_after_seconds: int = 4 * 60 * 60

    def to_dict(self) -> dict[str, int]:
        return {
            "queue_warn": self.queue_warn,
            "queue_fail": self.queue_fail,
            "stale_warn_seconds": self.stale_warn_seconds,
            "stale_fail_seconds": self.stale_fail_seconds,
            "manual_review_warn": self.manual_review_warn,
            "manual_review_fail": self.manual_review_fail,
            "recovery_spool_warn_count": self.recovery_spool_warn_count,
            "recovery_spool_fail_count": self.recovery_spool_fail_count,
            "recovery_spool_warn_after_seconds": self.recovery_spool_warn_after_seconds,
            "recovery_spool_fail_after_seconds": self.recovery_spool_fail_after_seconds,
        }


@dataclass(frozen=True)
class OpsAlert:
    severity: str
    code: str
    message: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "action": self.action,
        }


@dataclass(frozen=True)
class SchemaSummary:
    present_tables: tuple[str, ...]
    missing_tables: tuple[str, ...]
    migration_count: int
    latest_migration_version: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "present_tables": list(self.present_tables),
            "missing_tables": list(self.missing_tables),
            "migration_count": self.migration_count,
            "latest_migration_version": self.latest_migration_version,
        }


@dataclass(frozen=True)
class EntitlementSummary:
    total_count: int
    active_count: int

    def to_dict(self) -> dict[str, int]:
        return {"total_count": self.total_count, "active_count": self.active_count}


@dataclass(frozen=True)
class PaymentSummary:
    counts_by_status: Mapping[str, int]
    paid_not_granted_count: int
    old_pending_count: int
    failed_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "counts_by_status": _status_counts(self.counts_by_status, PAYMENT_STATUSES),
            "paid_not_granted_count": self.paid_not_granted_count,
            "old_pending_count": self.old_pending_count,
            "failed_count": self.failed_count,
        }


@dataclass(frozen=True)
class JobQueueSummary:
    counts_by_status: Mapping[str, int]
    stale_count: int
    max_stale_age_seconds: int | None
    manual_review_count: int
    failed_manual_review_count: int

    @property
    def queued_count(self) -> int:
        return int(self.counts_by_status.get("queued", 0))

    @property
    def running_count(self) -> int:
        return int(self.counts_by_status.get("running", 0))

    def to_dict(self) -> dict[str, object]:
        return {
            "counts_by_status": _status_counts(self.counts_by_status, JOB_STATUSES),
            "queued_count": self.queued_count,
            "running_count": self.running_count,
            "stale_count": self.stale_count,
            "max_stale_age_seconds": self.max_stale_age_seconds,
            "manual_review_count": self.manual_review_count,
            "failed_manual_review_count": self.failed_manual_review_count,
        }


@dataclass(frozen=True)
class DatabaseHealthSnapshot:
    connected: bool
    schema: SchemaSummary
    entitlements: EntitlementSummary
    payments: PaymentSummary
    one_day: JobQueueSummary
    weekly: JobQueueSummary
    error: str | None = None

    @classmethod
    def unavailable(cls, error: str) -> DatabaseHealthSnapshot:
        empty_jobs = JobQueueSummary(
            counts_by_status={status: 0 for status in JOB_STATUSES},
            stale_count=0,
            max_stale_age_seconds=None,
            manual_review_count=0,
            failed_manual_review_count=0,
        )
        return cls(
            connected=False,
            schema=SchemaSummary(present_tables=(), missing_tables=REQUIRED_TABLES, migration_count=0, latest_migration_version=None),
            entitlements=EntitlementSummary(total_count=0, active_count=0),
            payments=PaymentSummary(
                counts_by_status={status: 0 for status in PAYMENT_STATUSES},
                paid_not_granted_count=0,
                old_pending_count=0,
                failed_count=0,
            ),
            one_day=empty_jobs,
            weekly=empty_jobs,
            error=error,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "connected": self.connected,
            "schema": self.schema.to_dict(),
            "entitlements": self.entitlements.to_dict(),
            "payments": self.payments.to_dict(),
            "one_day": self.one_day.to_dict(),
            "weekly_pdf": self.weekly.to_dict(),
        }
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True)
class RecoverySpoolHealth:
    configured: bool
    status: str
    path: str | None = None
    exists: bool = False
    bytes: int = 0
    record_count: int = 0
    malformed_line_count: int = 0
    duplicate_record_count: int = 0
    oldest_created_at: str | None = None
    newest_created_at: str | None = None
    oldest_age_seconds: int | None = None
    newest_age_seconds: int | None = None
    reasons: tuple[str, ...] = ()

    @classmethod
    def skipped(cls) -> RecoverySpoolHealth:
        return cls(configured=False, status="skip", reasons=("spool_not_configured",))

    @classmethod
    def from_summary(cls, summary: PaymentRecoverySpoolSummary) -> RecoverySpoolHealth:
        return cls(
            configured=True,
            status=summary.status,
            path=redact_identifier("path", summary.path),
            exists=summary.exists,
            bytes=summary.bytes,
            record_count=summary.record_count,
            malformed_line_count=summary.malformed_line_count,
            duplicate_record_count=summary.duplicate_record_count,
            oldest_created_at=summary.oldest_created_at,
            newest_created_at=summary.newest_created_at,
            oldest_age_seconds=summary.oldest_age_seconds,
            newest_age_seconds=summary.newest_age_seconds,
            reasons=tuple(summary.reasons),
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "configured": self.configured,
            "status": self.status,
            "exists": self.exists,
            "bytes": self.bytes,
            "record_count": self.record_count,
            "malformed_line_count": self.malformed_line_count,
            "duplicate_record_count": self.duplicate_record_count,
            "oldest_created_at": self.oldest_created_at,
            "newest_created_at": self.newest_created_at,
            "oldest_age_seconds": self.oldest_age_seconds,
            "newest_age_seconds": self.newest_age_seconds,
            "reasons": list(self.reasons),
        }
        if self.path is not None:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class ReconciliationSummary:
    supplied: bool
    has_findings: bool = False
    counts: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "supplied": self.supplied,
            "has_findings": self.has_findings,
            "counts": dict(self.counts),
        }


@dataclass(frozen=True)
class OpsHealthReport:
    status: str
    generated_at: str
    thresholds: AlertThresholds
    database: DatabaseHealthSnapshot
    recovery_spool: RecoverySpoolHealth
    reconciliation: ReconciliationSummary
    alerts: tuple[OpsAlert, ...]

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "mode": "ops_health_summary",
            "status": self.status,
            "generated_at": self.generated_at,
            "thresholds": self.thresholds.to_dict(),
            "database": self.database.to_dict(),
            "payment_recovery_spool": self.recovery_spool.to_dict(),
            "reconciliation": self.reconciliation.to_dict(),
            "alerts": [alert.to_dict() for alert in self.alerts],
        }


def evaluate_ops_health(
    snapshot: DatabaseHealthSnapshot,
    *,
    thresholds: AlertThresholds,
    recovery_spool: RecoverySpoolHealth | None,
    reconciliation: ReconciliationSummary | None = None,
    generated_at: datetime | None = None,
) -> OpsHealthReport:
    alerts: list[OpsAlert] = []
    if not snapshot.connected:
        alerts.append(
            OpsAlert(
                severity=STATUS_FAIL,
                code="db_unavailable",
                message="Postgres connection or health query failed.",
                action="Treat as a startup and incident blocker; verify secret-manager DSN, network, database availability, and recent maintenance before starting bot workers.",
            )
        )
    if snapshot.connected and snapshot.schema.missing_tables:
        alerts.append(
            OpsAlert(
                severity=STATUS_FAIL,
                code="schema_missing_tables",
                message="Required application tables are missing: " + ", ".join(snapshot.schema.missing_tables),
                action="Stop launch work and run the approved migration/preflight process against the intended database.",
            )
        )

    alerts.extend(_job_alerts("one_day", "one-day generation", snapshot.one_day, thresholds))
    alerts.extend(_job_alerts("weekly_pdf", "weekly PDF", snapshot.weekly, thresholds))
    alerts.extend(_payment_alerts(snapshot.payments))

    spool = recovery_spool or RecoverySpoolHealth.skipped()
    alerts.extend(_recovery_spool_alerts(spool, thresholds))

    reconciliation_summary = reconciliation or ReconciliationSummary(supplied=False)
    if reconciliation_summary.supplied and reconciliation_summary.has_findings:
        alerts.append(
            OpsAlert(
                severity=STATUS_WARN,
                code="payment_reconciliation_findings",
                message="Local payment reconciliation input produced non-matching rows.",
                action="Review the local provider export, ledger export, and recovery spool before enabling or closing payment operations.",
            )
        )

    current_time = datetime.now(UTC) if generated_at is None else _normalize_datetime(generated_at)
    status = _overall_status(alerts)
    return OpsHealthReport(
        status=status,
        generated_at=current_time.isoformat(timespec="seconds"),
        thresholds=thresholds,
        database=snapshot,
        recovery_spool=spool,
        reconciliation=reconciliation_summary,
        alerts=tuple(alerts),
    )


def summarize_recovery_spool_for_health(
    path: str | Path,
    *,
    thresholds: AlertThresholds,
    now: datetime | None = None,
) -> RecoverySpoolHealth:
    summary = summarize_payment_recovery_spool(
        path,
        now=now,
        warn_after=timedelta(seconds=thresholds.recovery_spool_warn_after_seconds),
        fail_after=timedelta(seconds=thresholds.recovery_spool_fail_after_seconds),
        max_records=thresholds.recovery_spool_fail_count - 1,
    )
    return RecoverySpoolHealth.from_summary(summary)


def fetch_database_health_snapshot(conn: Any) -> DatabaseHealthSnapshot:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        row = cur.fetchone()
        if _row_value(row, "ok", 0) != 1:
            raise RuntimeError("Postgres connectivity probe returned an unexpected result.")

        present_tables = _fetch_present_tables(cur)
        missing_tables = tuple(table for table in REQUIRED_TABLES if table not in present_tables)
        schema = _fetch_schema_summary(cur, present_tables, missing_tables)
        entitlements = (
            _fetch_entitlement_summary(cur)
            if "entitlements" in present_tables
            else EntitlementSummary(total_count=0, active_count=0)
        )
        payments = (
            _fetch_payment_summary(cur)
            if "payment_orders" in present_tables
            else PaymentSummary(
                counts_by_status={status: 0 for status in PAYMENT_STATUSES},
                paid_not_granted_count=0,
                old_pending_count=0,
                failed_count=0,
            )
        )
        one_day = (
            _fetch_job_queue_summary(cur, "one_day_generation_jobs", has_reviewed_fields=False)
            if "one_day_generation_jobs" in present_tables
            else _empty_job_summary()
        )
        weekly = (
            _fetch_job_queue_summary(cur, "weekly_pdf_jobs", has_reviewed_fields=True)
            if "weekly_pdf_jobs" in present_tables
            else _empty_job_summary()
        )
    return DatabaseHealthSnapshot(
        connected=True,
        schema=schema,
        entitlements=entitlements,
        payments=payments,
        one_day=one_day,
        weekly=weekly,
    )


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    *,
    connection_factory: ConnectionFactory | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = _build_parser()
    args = parser.parse_args(argv)
    source_env = os.environ if env is None else env
    thresholds = _thresholds_from_args(args)

    database_url = source_env.get(args.database_url_env, "").strip()
    if not database_url:
        snapshot = DatabaseHealthSnapshot.unavailable(f"Set {args.database_url_env} to read Postgres health.")
    else:
        factory = connection_factory or _connect_postgres
        try:
            with factory(database_url) as conn:
                snapshot = fetch_database_health_snapshot(conn)
        except Exception as exc:
            snapshot = DatabaseHealthSnapshot.unavailable(_redact_text(str(exc) or exc.__class__.__name__, dsn=database_url))

    spool_path = str(args.recovery_spool or source_env.get(DEFAULT_PAYMENT_RECOVERY_SPOOL_ENV, "")).strip()
    recovery_spool = None
    if spool_path:
        try:
            recovery_spool = summarize_recovery_spool_for_health(spool_path, thresholds=thresholds)
        except Exception as exc:
            redacted_path = redact_identifier("path", spool_path)
            recovery_spool = RecoverySpoolHealth(
                configured=True,
                status=STATUS_FAIL,
                path=redacted_path,
                reasons=(_redact_text(str(exc) or exc.__class__.__name__).replace(spool_path, redacted_path),),
            )

    reconciliation = _reconciliation_from_args(args)
    report = evaluate_ops_health(
        snapshot,
        thresholds=thresholds,
        recovery_spool=recovery_spool,
        reconciliation=reconciliation,
    )

    if args.format == "json":
        json.dump(report.to_redacted_dict(), stdout, ensure_ascii=False, indent=2, sort_keys=True)
        stdout.write("\n")
    else:
        stdout.write(render_table(report))

    if report.status == STATUS_FAIL:
        return 1
    if args.fail_on_alert and report.status in {STATUS_WARN, STATUS_FAIL}:
        return 1
    return 0


def render_table(report: OpsHealthReport) -> str:
    lines = [
        "runtime ops health summary",
        f"status={report.status}",
        f"generated_at={report.generated_at}",
        f"db_connected={str(report.database.connected).lower()}",
    ]
    if report.database.error:
        lines.append(f"db_error={report.database.error}")
    lines.extend(
        [
            f"schema_missing_tables={len(report.database.schema.missing_tables)}",
            f"active_entitlements={report.database.entitlements.active_count}",
            (
                "one_day queued={queued} running={running} stale={stale} manual_review={review}".format(
                    queued=report.database.one_day.queued_count,
                    running=report.database.one_day.running_count,
                    stale=report.database.one_day.stale_count,
                    review=report.database.one_day.manual_review_count,
                )
            ),
            (
                "weekly_pdf queued={queued} running={running} stale={stale} manual_review={review}".format(
                    queued=report.database.weekly.queued_count,
                    running=report.database.weekly.running_count,
                    stale=report.database.weekly.stale_count,
                    review=report.database.weekly.manual_review_count,
                )
            ),
            (
                "payment_orders pending={pending} paid={paid} granted={granted} failed={failed} paid_not_granted={paid_not_granted}".format(
                    pending=report.database.payments.counts_by_status.get("pending", 0),
                    paid=report.database.payments.counts_by_status.get("paid", 0),
                    granted=report.database.payments.counts_by_status.get("granted", 0),
                    failed=report.database.payments.counts_by_status.get("failed", 0),
                    paid_not_granted=report.database.payments.paid_not_granted_count,
                )
            ),
            (
                "payment_recovery_spool configured={configured} status={status} records={records} oldest_age_seconds={age}".format(
                    configured=str(report.recovery_spool.configured).lower(),
                    status=report.recovery_spool.status,
                    records=report.recovery_spool.record_count,
                    age=report.recovery_spool.oldest_age_seconds,
                )
            ),
        ]
    )
    if not report.alerts:
        lines.append("alerts=none")
    else:
        lines.append("alerts:")
        for alert in report.alerts:
            lines.append(f"- {alert.severity} {alert.code}: {alert.message} action={alert.action}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize runtime ops health from Postgres and local recovery spool state without Telegram API calls.",
    )
    parser.add_argument("--database-url-env", default=DEFAULT_DATABASE_URL_ENV)
    parser.add_argument("--recovery-spool", type=Path)
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--fail-on-alert", action="store_true")
    parser.add_argument("--queue-warn", type=_non_negative_int, default=AlertThresholds.queue_warn)
    parser.add_argument("--queue-fail", type=_non_negative_int, default=AlertThresholds.queue_fail)
    parser.add_argument("--stale-warn-minutes", type=_non_negative_float, default=AlertThresholds.stale_warn_seconds / 60)
    parser.add_argument("--stale-fail-minutes", type=_non_negative_float, default=AlertThresholds.stale_fail_seconds / 60)
    parser.add_argument("--manual-review-warn", type=_non_negative_int, default=AlertThresholds.manual_review_warn)
    parser.add_argument("--manual-review-fail", type=_non_negative_int, default=AlertThresholds.manual_review_fail)
    parser.add_argument(
        "--recovery-spool-warn-count",
        type=_non_negative_int,
        default=AlertThresholds.recovery_spool_warn_count,
    )
    parser.add_argument(
        "--recovery-spool-fail-count",
        type=_positive_int,
        default=AlertThresholds.recovery_spool_fail_count,
    )
    parser.add_argument(
        "--recovery-spool-warn-after-hours",
        type=_non_negative_float,
        default=AlertThresholds.recovery_spool_warn_after_seconds / 3600,
    )
    parser.add_argument(
        "--recovery-spool-fail-after-hours",
        type=_non_negative_float,
        default=AlertThresholds.recovery_spool_fail_after_seconds / 3600,
    )
    parser.add_argument("--provider-export", type=Path)
    parser.add_argument("--ledger-export", type=Path)
    parser.add_argument("--reconciliation-recovery-spool", type=Path)
    return parser


def _thresholds_from_args(args: argparse.Namespace) -> AlertThresholds:
    return AlertThresholds(
        queue_warn=args.queue_warn,
        queue_fail=args.queue_fail,
        stale_warn_seconds=int(args.stale_warn_minutes * 60),
        stale_fail_seconds=int(args.stale_fail_minutes * 60),
        manual_review_warn=args.manual_review_warn,
        manual_review_fail=args.manual_review_fail,
        recovery_spool_warn_count=args.recovery_spool_warn_count,
        recovery_spool_fail_count=args.recovery_spool_fail_count,
        recovery_spool_warn_after_seconds=int(args.recovery_spool_warn_after_hours * 3600),
        recovery_spool_fail_after_seconds=int(args.recovery_spool_fail_after_hours * 3600),
    )


def _connect_postgres(dsn: str) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5)


def _fetch_present_tables(cur: Any) -> set[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        """,
        (list(REQUIRED_TABLES),),
    )
    return {str(row["table_name"]) for row in cur.fetchall()}


def _fetch_schema_summary(cur: Any, present_tables: set[str], missing_tables: tuple[str, ...]) -> SchemaSummary:
    migration_count = 0
    latest_migration_version = None
    if "schema_migrations" in present_tables:
        cur.execute(
            """
            SELECT
                count(*) AS migration_count,
                max(version) AS latest_migration_version
            FROM schema_migrations
            """
        )
        row = cur.fetchone()
        migration_count = _int_value(row, "migration_count")
        latest = _row_value(row, "latest_migration_version")
        latest_migration_version = str(latest) if latest is not None else None
    return SchemaSummary(
        present_tables=tuple(table for table in REQUIRED_TABLES if table in present_tables),
        missing_tables=missing_tables,
        migration_count=migration_count,
        latest_migration_version=latest_migration_version,
    )


def _fetch_entitlement_summary(cur: Any) -> EntitlementSummary:
    cur.execute(
        """
        SELECT
            count(*) AS total_count,
            count(*) FILTER (
                WHERE monthly_one_day_remaining > 0
                   OR monthly_weekly_pdf_remaining > 0
                   OR extra_one_day_remaining > 0
                   OR extra_weekly_pdf_remaining > 0
                   OR (
                        NULLIF(subscription_period_end, '') IS NOT NULL
                        AND NULLIF(subscription_period_end, '')::timestamptz > now()
                   )
                   OR (
                        test_access_enabled IS TRUE
                        AND NULLIF(test_access_until, '') IS NOT NULL
                        AND NULLIF(test_access_until, '')::timestamptz > now()
                   )
            ) AS active_count
        FROM entitlements
        """
    )
    row = cur.fetchone()
    return EntitlementSummary(
        total_count=_int_value(row, "total_count"),
        active_count=_int_value(row, "active_count"),
    )


def _fetch_payment_summary(cur: Any) -> PaymentSummary:
    cur.execute(
        """
        SELECT status, count(*) AS row_count
        FROM payment_orders
        GROUP BY status
        """
    )
    counts = {status: 0 for status in PAYMENT_STATUSES}
    for row in cur.fetchall():
        counts[str(row["status"])] = _int_value(row, "row_count")

    cur.execute(
        """
        SELECT
            count(*) FILTER (
                WHERE status = 'paid'
                  AND granted_at IS NULL
            ) AS paid_not_granted_count,
            count(*) FILTER (
                WHERE status = 'pending'
                  AND created_at < now() - interval '15 minutes'
            ) AS old_pending_count,
            count(*) FILTER (WHERE status = 'failed') AS failed_count
        FROM payment_orders
        """
    )
    row = cur.fetchone()
    return PaymentSummary(
        counts_by_status=counts,
        paid_not_granted_count=_int_value(row, "paid_not_granted_count"),
        old_pending_count=_int_value(row, "old_pending_count"),
        failed_count=_int_value(row, "failed_count"),
    )


def _fetch_job_queue_summary(cur: Any, table_name: str, *, has_reviewed_fields: bool) -> JobQueueSummary:
    quoted = _quote_known_job_table(table_name)
    cur.execute(
        f"""
        SELECT status, count(*) AS row_count
        FROM {quoted}
        GROUP BY status
        """
    )
    counts = {status: 0 for status in JOB_STATUSES}
    for row in cur.fetchall():
        counts[str(row["status"])] = _int_value(row, "row_count")

    cur.execute(
        f"""
        SELECT
            count(*) AS stale_count,
            max(EXTRACT(EPOCH FROM (now() - stale_after))) AS max_stale_age_seconds
        FROM {quoted}
        WHERE status IN ('queued', 'running')
          AND stale_after < now()
        """
    )
    stale = cur.fetchone()

    review_filter = "requires_manual_review IS TRUE"
    if has_reviewed_fields:
        review_filter += " AND manual_reviewed_at IS NULL"
    cur.execute(
        f"""
        SELECT
            count(*) AS manual_review_count,
            count(*) FILTER (WHERE status = 'failed') AS failed_manual_review_count
        FROM {quoted}
        WHERE {review_filter}
        """
    )
    review = cur.fetchone()
    return JobQueueSummary(
        counts_by_status=counts,
        stale_count=_int_value(stale, "stale_count"),
        max_stale_age_seconds=_optional_int_value(stale, "max_stale_age_seconds"),
        manual_review_count=_int_value(review, "manual_review_count"),
        failed_manual_review_count=_int_value(review, "failed_manual_review_count"),
    )


def _empty_job_summary() -> JobQueueSummary:
    return JobQueueSummary(
        counts_by_status={status: 0 for status in JOB_STATUSES},
        stale_count=0,
        max_stale_age_seconds=None,
        manual_review_count=0,
        failed_manual_review_count=0,
    )


def _job_alerts(
    prefix: str,
    label: str,
    summary: JobQueueSummary,
    thresholds: AlertThresholds,
) -> tuple[OpsAlert, ...]:
    alerts: list[OpsAlert] = []
    if summary.queued_count >= thresholds.queue_fail:
        alerts.append(
            OpsAlert(
                severity=STATUS_FAIL,
                code=f"{prefix}_queue_depth_fail",
                message=f"{label} queued depth is {summary.queued_count}, at or above fail threshold {thresholds.queue_fail}.",
                action="Pause launch expansion, inspect worker logs and durable queue claims, and drain or deliberately cancel only through approved tooling.",
            )
        )
    elif summary.queued_count >= thresholds.queue_warn:
        alerts.append(
            OpsAlert(
                severity=STATUS_WARN,
                code=f"{prefix}_queue_depth_warn",
                message=f"{label} queued depth is {summary.queued_count}, at or above warning threshold {thresholds.queue_warn}.",
                action="Watch worker throughput, confirm exactly one intended poller/worker set, and prepare a drain plan if the backlog keeps growing.",
            )
        )

    stale_age = summary.max_stale_age_seconds
    if summary.stale_count and stale_age is not None and stale_age >= thresholds.stale_fail_seconds:
        alerts.append(
            OpsAlert(
                severity=STATUS_FAIL,
                code=f"{prefix}_stale_jobs_fail",
                message=f"{label} has {summary.stale_count} stale active jobs; oldest stale age is {stale_age} seconds.",
                action="Treat worker as stalled: stop further rollout, inspect worker leases/heartbeats, preserve logs, and recover via approved retry or manual-review flow.",
            )
        )
    elif summary.stale_count and (stale_age is None or stale_age >= thresholds.stale_warn_seconds):
        alerts.append(
            OpsAlert(
                severity=STATUS_WARN,
                code=f"{prefix}_stale_jobs_warn",
                message=f"{label} has {summary.stale_count} stale active jobs.",
                action="Inspect queue workers and logs before traffic increases; confirm heartbeats are updating and stale cleanup is safe.",
            )
        )

    if summary.manual_review_count >= thresholds.manual_review_fail:
        alerts.append(
            OpsAlert(
                severity=STATUS_FAIL,
                code=f"{prefix}_manual_review_fail",
                message=f"{label} manual-review backlog is {summary.manual_review_count}.",
                action="Assign an operator owner, run the manual-review report, and resolve customer-facing action before launch expansion.",
            )
        )
    elif summary.manual_review_count >= thresholds.manual_review_warn:
        alerts.append(
            OpsAlert(
                severity=STATUS_WARN,
                code=f"{prefix}_manual_review_warn",
                message=f"{label} manual-review backlog is {summary.manual_review_count}.",
                action="Run the manual-review report and attach evidence to the operator ticket.",
            )
        )
    return tuple(alerts)


def _payment_alerts(summary: PaymentSummary) -> tuple[OpsAlert, ...]:
    alerts: list[OpsAlert] = []
    if summary.paid_not_granted_count:
        alerts.append(
            OpsAlert(
                severity=STATUS_FAIL,
                code="payment_paid_not_granted",
                message=f"{summary.paid_not_granted_count} payment orders are paid but not granted.",
                action="Stop payment enablement work, inspect ledger/recovery records, and reconcile before any customer-facing payment launch.",
            )
        )
    if summary.old_pending_count:
        alerts.append(
            OpsAlert(
                severity=STATUS_WARN,
                code="payment_old_pending_orders",
                message=f"{summary.old_pending_count} payment orders have remained pending for more than 15 minutes.",
                action="Review invoice creation logs and provider/provider-export evidence before enabling more payment traffic.",
            )
        )
    return tuple(alerts)


def _recovery_spool_alerts(
    spool: RecoverySpoolHealth,
    thresholds: AlertThresholds,
) -> tuple[OpsAlert, ...]:
    if not spool.configured:
        return ()
    alerts: list[OpsAlert] = []
    if spool.malformed_line_count:
        alerts.append(
            OpsAlert(
                severity=STATUS_FAIL,
                code="payment_recovery_spool_malformed_fail",
                message=f"Payment recovery spool has {spool.malformed_line_count} malformed lines.",
                action="Freeze payment incident closure, preserve the immutable spool, and review malformed lines before replay.",
            )
        )
    if spool.record_count >= thresholds.recovery_spool_fail_count:
        alerts.append(
            OpsAlert(
                severity=STATUS_FAIL,
                code="payment_recovery_spool_count_fail",
                message=f"Payment recovery spool has {spool.record_count} records.",
                action="Stop payment launch, reconcile the spool, and dry-run recovery replay before any apply.",
            )
        )
    elif spool.record_count >= thresholds.recovery_spool_warn_count:
        alerts.append(
            OpsAlert(
                severity=STATUS_WARN,
                code="payment_recovery_spool_non_empty_warn",
                message=f"Payment recovery spool is non-empty with {spool.record_count} records.",
                action="Inspect spool status, reconcile against local ledger/provider exports, and schedule recovery review.",
            )
        )
    if spool.oldest_age_seconds is not None and spool.oldest_age_seconds >= thresholds.recovery_spool_fail_after_seconds:
        alerts.append(
            OpsAlert(
                severity=STATUS_FAIL,
                code="payment_recovery_spool_oldest_age_fail",
                message=f"Oldest payment recovery spool record age is {spool.oldest_age_seconds} seconds.",
                action="Treat as an active payment incident until reviewed, reconciled, and replayed or explicitly waived.",
            )
        )
    elif spool.oldest_age_seconds is not None and spool.oldest_age_seconds >= thresholds.recovery_spool_warn_after_seconds:
        alerts.append(
            OpsAlert(
                severity=STATUS_WARN,
                code="payment_recovery_spool_oldest_age_warn",
                message=f"Oldest payment recovery spool record age is {spool.oldest_age_seconds} seconds.",
                action="Schedule operator review before the fail threshold is reached.",
            )
        )
    return tuple(alerts)


def _reconciliation_from_args(args: argparse.Namespace) -> ReconciliationSummary:
    if not args.provider_export and not args.ledger_export:
        return ReconciliationSummary(supplied=False)
    if not args.provider_export or not args.ledger_export:
        raise SystemExit("--provider-export and --ledger-export must be supplied together.")

    from diet_bot.payment_reconciliation import load_reconciliation_rows, reconcile_payment_exports
    from diet_bot.payment_recovery_spool import read_payment_recovery_records

    provider_rows = load_reconciliation_rows(args.provider_export)
    ledger_rows = load_reconciliation_rows(args.ledger_export)
    recovery_records = ()
    if args.reconciliation_recovery_spool:
        recovery_records = read_payment_recovery_records(args.reconciliation_recovery_spool).records
    report = reconcile_payment_exports(provider_rows, ledger_rows, recovery_records=recovery_records)
    return ReconciliationSummary(supplied=True, has_findings=report.has_findings, counts=report.counts)


def _overall_status(alerts: Sequence[OpsAlert]) -> str:
    if any(alert.severity == STATUS_FAIL for alert in alerts):
        return STATUS_FAIL
    if any(alert.severity == STATUS_WARN for alert in alerts):
        return STATUS_WARN
    return STATUS_OK


def _status_counts(counts: Mapping[str, int], statuses: Sequence[str]) -> dict[str, int]:
    return {status: int(counts.get(status, 0)) for status in statuses}


def _quote_known_job_table(table_name: str) -> str:
    if table_name not in {"one_day_generation_jobs", "weekly_pdf_jobs"}:
        raise ValueError(f"unexpected job table: {table_name!r}")
    return '"' + table_name + '"'


def _row_value(row: Any, key: str, index: int | None = None) -> Any:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return row.get(key)
    if index is not None:
        return row[index]
    return getattr(row, key, None)


def _int_value(row: Any, key: str) -> int:
    value = _row_value(row, key)
    if value is None:
        return 0
    return int(value)


def _optional_int_value(row: Any, key: str) -> int | None:
    value = _row_value(row, key)
    if value is None:
        return None
    return int(value)


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _redact_text(text: str, *, dsn: str | None = None) -> str:
    redacted = str(text)
    if dsn:
        redacted = redacted.replace(str(dsn), "postgresql://<redacted>")
    redacted = _POSTGRES_DSN_RE.sub("postgresql://<redacted>", redacted)
    return redact_postgres_text(redacted)


if __name__ == "__main__":
    raise SystemExit(main())
