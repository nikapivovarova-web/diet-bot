from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from uuid import UUID

from diet_bot.ops import weekly_pdf_manual_review_report as report
from diet_bot.weekly_pdf_jobs import REFUND_STATUS_NOT_REQUIRED, WeeklyPdfJob


def test_report_default_lists_unresolved_jobs_as_redacted_table() -> None:
    now = datetime(2026, 5, 26, 9, 15, tzinfo=UTC)
    job = _job(
        job_id=UUID("00000000-0000-0000-0000-000000000101"),
        chat_id=987654321,
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(minutes=4),
        delivery_status="unknown",
        manual_review_reason="send_started_without_delivery_confirmation",
        finalization_error="stale_after_send_attempt_unconfirmed",
        consumption_source="monthly",
    )
    store = FakeStore(unresolved_jobs=[job])
    stdout = StringIO()

    exit_code = report.main(
        [],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=lambda _dsn: store,
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert exit_code == 0
    assert store.calls == [("unresolved", 100)]
    assert "job_id" in output
    assert str(job.job_id) in output
    assert "unknown" in output
    assert "send_started_without_delivery_confirmation" in output
    assert "stale_after_send_attempt_unconfirmed" in output
    assert "monthly" in output
    assert "987654321" not in output
    assert "secret" not in output
    assert "postgresql://" not in output
    assert "chat:sha256:" in output


def test_report_json_redacts_chat_id_and_excludes_clean_successes() -> None:
    now = datetime(2026, 5, 26, 9, 15, tzinfo=UTC)
    unresolved = _job(
        job_id=UUID("00000000-0000-0000-0000-000000000201"),
        chat_id=222333444,
        created_at=now - timedelta(hours=1),
        updated_at=now,
        delivery_status="unknown",
        manual_review_reason="telegram_upload_unconfirmed",
        finalization_error=None,
        consumption_source="extra",
    )
    clean_delivered = _job(
        job_id=UUID("00000000-0000-0000-0000-000000000202"),
        chat_id=555666777,
        created_at=now - timedelta(hours=1),
        updated_at=now,
        delivery_status="delivered",
        requires_manual_review=False,
        manual_review_reason=None,
        finalization_error=None,
        consumption_source="monthly",
    )
    store = FakeStore(unresolved_jobs=[unresolved], all_review_jobs=[unresolved, clean_delivered])
    stdout = StringIO()

    exit_code = report.main(
        ["--json", "--limit", "5"],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=lambda _dsn: store,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    rendered = json.dumps(payload)
    assert exit_code == 0
    assert payload["mode"] == "weekly_pdf_manual_review"
    assert payload["include_reviewed"] is False
    assert payload["count"] == 1
    assert payload["jobs"][0]["job_id"] == str(unresolved.job_id)
    assert payload["jobs"][0]["chat_id_hash"].startswith("chat:sha256:")
    assert "chat_id" not in payload["jobs"][0]
    assert str(clean_delivered.job_id) not in rendered
    assert "222333444" not in rendered
    assert "555666777" not in rendered
    assert "secret" not in rendered


def test_include_reviewed_uses_read_only_review_query() -> None:
    now = datetime(2026, 5, 26, 9, 15, tzinfo=UTC)
    unresolved = _job(
        job_id=UUID("00000000-0000-0000-0000-000000000301"),
        chat_id=301,
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=2),
        delivery_status="unknown",
    )
    reviewed = _job(
        job_id=UUID("00000000-0000-0000-0000-000000000302"),
        chat_id=302,
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=1),
        delivery_status="unknown",
        manual_reviewed_at=now,
        manual_reviewed_by="ops.alex",
        manual_review_resolution="operator_confirmed_delivery",
        manual_review_note="Ticket MR-302 confirmed delivery in provider export.",
    )
    store = FakeStore(unresolved_jobs=[unresolved], all_review_jobs=[unresolved, reviewed])
    stdout = StringIO()

    exit_code = report.main(
        ["--include-reviewed", "--limit", "2"],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=lambda _dsn: store,
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert exit_code == 0
    assert store.calls == [("manual_review", 2, True)]
    assert str(unresolved.job_id) in output
    assert str(reviewed.job_id) in output
    assert "ops.alex" in output
    assert "operator_confirmed_delivery" in output
    assert "Ticket MR-302" in output


def test_missing_database_url_exits_safely_without_store_access() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = report.main([], env={}, store_factory=FailingStoreFactory(), stdout=stdout, stderr=stderr)

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert "DIET_BOT_DATABASE_URL" in stderr.getvalue()
    assert "postgresql://" not in stderr.getvalue()
    assert "secret" not in stderr.getvalue()


def test_database_errors_are_redacted() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = report.main(
        [],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=lambda _dsn: ExplodingStore(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert "database details redacted" in stderr.getvalue()
    assert "postgresql://" not in stderr.getvalue()
    assert "secret" not in stderr.getvalue()


def test_limit_must_be_positive() -> None:
    stderr = StringIO()

    exit_code = report.main(
        ["--limit", "0"],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=FailingStoreFactory(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "limit must be positive" in stderr.getvalue()


class FakeStore:
    def __init__(
        self,
        *,
        unresolved_jobs: list[WeeklyPdfJob],
        all_review_jobs: list[WeeklyPdfJob] | None = None,
    ) -> None:
        self.unresolved_jobs = list(unresolved_jobs)
        self.all_review_jobs = list(all_review_jobs or unresolved_jobs)
        self.calls: list[tuple] = []

    def get_unresolved_manual_review_jobs(self, *, limit: int) -> list[WeeklyPdfJob]:
        self.calls.append(("unresolved", limit))
        return self.unresolved_jobs[:limit]

    def get_manual_review_jobs(self, *, limit: int, include_reviewed: bool) -> list[WeeklyPdfJob]:
        self.calls.append(("manual_review", limit, include_reviewed))
        jobs = self.all_review_jobs if include_reviewed else self.unresolved_jobs
        return jobs[:limit]

    def admit_job(self, *args, **kwargs):
        raise AssertionError("report must not mutate jobs")

    def start_job_and_consume(self, *args, **kwargs):
        raise AssertionError("report must not mutate jobs")

    def finish_success(self, *args, **kwargs):
        raise AssertionError("report must not mutate jobs")

    def finish_failure_and_refund_once(self, *args, **kwargs):
        raise AssertionError("report must not mutate jobs")


class ExplodingStore:
    def get_unresolved_manual_review_jobs(self, *, limit: int) -> list[WeeklyPdfJob]:
        raise RuntimeError("could not connect to postgresql://user:secret@example.invalid/prod")


class FailingStoreFactory:
    def __call__(self, _dsn: str) -> FakeStore:
        raise AssertionError("store factory should not be called")


def _job(
    *,
    job_id: UUID,
    chat_id: int,
    created_at: datetime,
    updated_at: datetime,
    delivery_status: str,
    status: str = "succeeded",
    refund_status: str = REFUND_STATUS_NOT_REQUIRED,
    consumption_source: str | None = None,
    finalization_error: str | None = None,
    requires_manual_review: bool = True,
    manual_review_reason: str | None = "send_started_without_delivery_confirmation",
    manual_reviewed_at: datetime | None = None,
    manual_reviewed_by: str | None = None,
    manual_review_resolution: str | None = None,
    manual_review_note: str | None = None,
) -> WeeklyPdfJob:
    return WeeklyPdfJob(
        job_id=job_id,
        chat_id=chat_id,
        idempotency_key=f"idem-{job_id}",
        status=status,
        refund_status=refund_status,
        consumption_source=consumption_source,
        stale_after=updated_at + timedelta(minutes=15),
        created_at=created_at,
        updated_at=updated_at,
        finished_at=updated_at,
        finalization_error=finalization_error,
        delivery_status=delivery_status,
        requires_manual_review=requires_manual_review,
        manual_review_reason=manual_review_reason,
        manual_reviewed_at=manual_reviewed_at,
        manual_reviewed_by=manual_reviewed_by,
        manual_review_resolution=manual_review_resolution,
        manual_review_note=manual_review_note,
    )
