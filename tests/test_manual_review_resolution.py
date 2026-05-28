from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from uuid import UUID

from diet_bot.one_day_generation_jobs import OneDayGenerationJob
from diet_bot.ops import manual_review_resolution as resolver
from diet_bot.weekly_pdf_jobs import WeeklyPdfJob


NOW = datetime(2026, 5, 28, 12, 30, tzinfo=UTC)
WEEKLY_JOB_ID = UUID("00000000-0000-0000-0000-000000007001")
ONE_DAY_JOB_ID = UUID("00000000-0000-0000-0000-000000008001")


def test_weekly_resolve_dry_run_does_not_mutate_and_redacts_chat_id() -> None:
    store = FakeWeeklyStore(_weekly_job(job_id=WEEKLY_JOB_ID, chat_id=987654321))
    stdout = StringIO()

    exit_code = resolver.main(
        [
            "--job-type",
            "weekly-pdf",
            "--job-id",
            str(WEEKLY_JOB_ID),
            "--operator",
            "ops.alex",
            "--resolution",
            "confirmed_delivered",
            "--note",
            "Ticket MR-7 checked provider export and bot logs for chat 987654321.",
            "--dry-run",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=_factory({"weekly-pdf": store}),
        stdout=stdout,
        now=lambda: NOW,
    )

    output = stdout.getvalue()
    assert exit_code == 0
    assert store.calls == [("get", WEEKLY_JOB_ID)]
    assert "dry_run" in output
    assert str(WEEKLY_JOB_ID) in output
    assert "chat:sha256:" in output
    assert "987654321" not in output
    assert "secret" not in output
    assert store.job.manual_reviewed_at is None


def test_weekly_resolve_dry_run_redacts_secret_note_from_output() -> None:
    note = "checked postgresql://ops:super-secret@example.invalid/prod password=cleartext"
    store = FakeWeeklyStore(_weekly_job(job_id=WEEKLY_JOB_ID, chat_id=701))
    stdout = StringIO()

    exit_code = resolver.main(
        [
            "--job-type",
            "weekly-pdf",
            "--job-id",
            str(WEEKLY_JOB_ID),
            "--operator",
            "ops.alex",
            "--resolution",
            "confirmed_delivered",
            "--note",
            note,
            "--dry-run",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=_factory({"weekly-pdf": store}),
        stdout=stdout,
        now=lambda: NOW,
    )

    output = stdout.getvalue()
    assert exit_code == 0
    assert "checked postgresql://" in output
    assert "example.invalid/prod" in output
    assert "password=<redacted:secret>" in output
    assert "super-secret" not in output
    assert "cleartext" not in output
    assert store.job.manual_reviewed_at is None


def test_weekly_resolve_apply_marks_audit_fields_without_refund_changes() -> None:
    store = FakeWeeklyStore(
        _weekly_job(job_id=WEEKLY_JOB_ID, chat_id=701, refund_status="pending", delivery_status="unknown")
    )
    stdout = StringIO()

    exit_code = resolver.main(
        [
            "--job-type",
            "weekly-pdf",
            "--job-id",
            str(WEEKLY_JOB_ID),
            "--operator",
            "ops.alex",
            "--resolution",
            "confirmed_delivered",
            "--note",
            "Ticket MR-7 checked provider export and bot logs.",
            "--apply",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=_factory({"weekly-pdf": store}),
        stdout=stdout,
        now=lambda: NOW,
    )

    assert exit_code == 0
    assert store.calls == [
        (
            "resolve",
            WEEKLY_JOB_ID,
            "ops.alex",
            "confirmed_delivered",
            "Ticket MR-7 checked provider export and bot logs.",
            NOW,
            False,
        )
    ]
    assert "resolved" in stdout.getvalue()
    assert store.job.manual_reviewed_at == NOW
    assert store.job.manual_reviewed_by == "ops.alex"
    assert store.job.manual_review_resolution == "confirmed_delivered"
    assert store.job.manual_review_note == "Ticket MR-7 checked provider export and bot logs."
    assert store.job.delivery_status == "unknown"
    assert store.job.refund_status == "pending"


def test_weekly_resolve_apply_redacts_secret_note_from_output_but_stores_raw_note() -> None:
    note = "Ticket MR-12 checked token=raw-provider-token-123 and secret=raw-secret-456."
    store = FakeWeeklyStore(_weekly_job(job_id=WEEKLY_JOB_ID, chat_id=701))
    stdout = StringIO()

    exit_code = resolver.main(
        [
            "--job-type",
            "weekly-pdf",
            "--job-id",
            str(WEEKLY_JOB_ID),
            "--operator",
            "ops.alex",
            "--resolution",
            "confirmed_delivered",
            "--note",
            note,
            "--apply",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=_factory({"weekly-pdf": store}),
        stdout=stdout,
        now=lambda: NOW,
    )

    output = stdout.getvalue()
    assert exit_code == 0
    assert "Ticket MR-12 checked" in output
    assert "token=<redacted:secret>" in output
    assert "secret=<redacted:secret>" in output
    assert "raw-provider-token-123" not in output
    assert "raw-secret-456" not in output
    assert store.job.manual_review_note == note


def test_weekly_resolve_apply_is_idempotent() -> None:
    reviewed = _weekly_job(
        job_id=WEEKLY_JOB_ID,
        chat_id=702,
        manual_reviewed_at=NOW - timedelta(minutes=5),
        manual_reviewed_by="ops.first",
        manual_review_resolution="confirmed_delivered",
        manual_review_note="Earlier ticket.",
    )
    store = FakeWeeklyStore(reviewed)
    stdout = StringIO()

    exit_code = resolver.main(
        [
            "--job-type",
            "weekly-pdf",
            "--job-id",
            str(WEEKLY_JOB_ID),
            "--operator",
            "ops.second",
            "--resolution",
            "confirmed_delivered",
            "--note",
            "Repeated ticket.",
            "--apply",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=_factory({"weekly-pdf": store}),
        stdout=stdout,
        now=lambda: NOW,
    )

    assert exit_code == 0
    assert "already_resolved" in stdout.getvalue()
    assert store.job.manual_reviewed_at == NOW - timedelta(minutes=5)
    assert store.job.manual_reviewed_by == "ops.first"
    assert store.job.manual_review_note == "Earlier ticket."


def test_one_day_resolve_apply_marks_audit_fields_and_redacts_chat_id() -> None:
    store = FakeOneDayStore(_one_day_job(job_id=ONE_DAY_JOB_ID, chat_id=222333444, refund_status="pending"))
    stdout = StringIO()

    exit_code = resolver.main(
        [
            "--job-type",
            "one-day",
            "--job-id",
            str(ONE_DAY_JOB_ID),
            "--operator",
            "ops.mira",
            "--resolution",
            "no_refund_confirmed",
            "--note",
            "Ticket MR-8 verified partial delivery; no refund from this tool.",
            "--apply",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=_factory({"one-day": store}),
        stdout=stdout,
        now=lambda: NOW,
    )

    output = stdout.getvalue()
    assert exit_code == 0
    assert store.job.manual_reviewed_at == NOW
    assert store.job.manual_reviewed_by == "ops.mira"
    assert store.job.manual_review_resolution == "no_refund_confirmed"
    assert store.job.manual_review_note == "Ticket MR-8 verified partial delivery; no refund from this tool."
    assert store.job.refund_status == "pending"
    assert "222333444" not in output
    assert "chat:sha256:" in output


def test_one_day_resolve_dry_run_does_not_mutate() -> None:
    store = FakeOneDayStore(_one_day_job(job_id=ONE_DAY_JOB_ID, chat_id=801))

    exit_code = resolver.main(
        [
            "--job-type",
            "one-day",
            "--job-id",
            str(ONE_DAY_JOB_ID),
            "--operator",
            "ops.mira",
            "--resolution",
            "no_refund_confirmed",
            "--note",
            "Ticket MR-8 verified manually.",
            "--dry-run",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=_factory({"one-day": store}),
        stdout=StringIO(),
        now=lambda: NOW,
    )

    assert exit_code == 0
    assert store.calls == [("get", ONE_DAY_JOB_ID)]
    assert store.job.manual_reviewed_at is None


def test_resolve_refuses_non_manual_review_by_default() -> None:
    store = FakeWeeklyStore(_weekly_job(job_id=WEEKLY_JOB_ID, chat_id=703, requires_manual_review=False))
    stdout = StringIO()
    stderr = StringIO()

    exit_code = resolver.main(
        [
            "--job-type",
            "weekly-pdf",
            "--job-id",
            str(WEEKLY_JOB_ID),
            "--operator",
            "ops.alex",
            "--resolution",
            "operator_override",
            "--note",
            "Ticket MR-9.",
            "--apply",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=_factory({"weekly-pdf": store}),
        stdout=stdout,
        stderr=stderr,
        now=lambda: NOW,
    )

    assert exit_code == 1
    assert "not_manual_review" in stdout.getvalue()
    assert store.job.manual_reviewed_at is None


def test_resolve_allows_documented_non_manual_review_override() -> None:
    store = FakeWeeklyStore(_weekly_job(job_id=WEEKLY_JOB_ID, chat_id=704, requires_manual_review=False))

    exit_code = resolver.main(
        [
            "--job-type",
            "weekly-pdf",
            "--job-id",
            str(WEEKLY_JOB_ID),
            "--operator",
            "ops.alex",
            "--resolution",
            "operator_override",
            "--note",
            "Ticket MR-10 records audit-only closure.",
            "--allow-non-manual-review",
            "--apply",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=_factory({"weekly-pdf": store}),
        stdout=StringIO(),
        now=lambda: NOW,
    )

    assert exit_code == 0
    assert store.job.manual_reviewed_at == NOW


def test_missing_database_url_is_redacted_and_does_not_access_store() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = resolver.main(
        [
            "--job-type",
            "weekly-pdf",
            "--job-id",
            str(WEEKLY_JOB_ID),
            "--operator",
            "ops.alex",
            "--resolution",
            "confirmed_delivered",
            "--note",
            "Ticket MR-11.",
            "--dry-run",
        ],
        env={},
        store_factory=lambda _job_type, _dsn: (_ for _ in ()).throw(AssertionError("must not connect")),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert "DIET_BOT_DATABASE_URL" in stderr.getvalue()
    assert "postgresql://" not in stderr.getvalue()


class FakeWeeklyStore:
    def __init__(self, job: WeeklyPdfJob) -> None:
        self.job = job
        self.calls: list[tuple] = []

    def get_job(self, job_id: UUID | str) -> WeeklyPdfJob | None:
        coerced = UUID(str(job_id))
        self.calls.append(("get", coerced))
        if coerced == self.job.job_id:
            return self.job
        return None

    def resolve_manual_review(
        self,
        job_id: UUID | str,
        *,
        resolved_by: str,
        resolution: str,
        note: str,
        now: datetime | None = None,
        allow_non_manual_review: bool = False,
    ) -> SimpleNamespace:
        coerced = UUID(str(job_id))
        self.calls.append(("resolve", coerced, resolved_by, resolution, note, now, allow_non_manual_review))
        if coerced != self.job.job_id:
            return SimpleNamespace(status="not_found", job=None)
        if self.job.manual_reviewed_at is not None:
            return SimpleNamespace(status="already_resolved", job=self.job)
        if not self.job.requires_manual_review and not allow_non_manual_review:
            return SimpleNamespace(status="not_manual_review", job=self.job)
        self.job = replace(
            self.job,
            manual_reviewed_at=now,
            manual_reviewed_by=resolved_by,
            manual_review_resolution=resolution,
            manual_review_note=note,
        )
        return SimpleNamespace(status="resolved", job=self.job)


class FakeOneDayStore:
    def __init__(self, job: OneDayGenerationJob) -> None:
        self.job = job
        self.calls: list[tuple] = []

    def get_job(self, job_id: UUID | str) -> OneDayGenerationJob | None:
        coerced = UUID(str(job_id))
        self.calls.append(("get", coerced))
        if coerced == self.job.job_id:
            return self.job
        return None

    def resolve_manual_review(
        self,
        job_id: UUID | str,
        *,
        resolved_by: str,
        resolution: str,
        note: str,
        now: datetime | None = None,
        allow_non_manual_review: bool = False,
    ) -> SimpleNamespace:
        coerced = UUID(str(job_id))
        self.calls.append(("resolve", coerced, resolved_by, resolution, note, now, allow_non_manual_review))
        if coerced != self.job.job_id:
            return SimpleNamespace(status="not_found", job=None)
        if self.job.manual_reviewed_at is not None:
            return SimpleNamespace(status="already_resolved", job=self.job)
        if not self.job.requires_manual_review and not allow_non_manual_review:
            return SimpleNamespace(status="not_manual_review", job=self.job)
        self.job = replace(
            self.job,
            manual_reviewed_at=now,
            manual_reviewed_by=resolved_by,
            manual_review_resolution=resolution,
            manual_review_note=note,
        )
        return SimpleNamespace(status="resolved", job=self.job)


def _factory(stores: dict[str, object]):
    def factory(job_type: str, _dsn: str) -> object:
        return stores[job_type]

    return factory


def _weekly_job(
    *,
    job_id: UUID,
    chat_id: int,
    requires_manual_review: bool = True,
    refund_status: str = "not_required",
    delivery_status: str = "unknown",
    manual_reviewed_at: datetime | None = None,
    manual_reviewed_by: str | None = None,
    manual_review_resolution: str | None = None,
    manual_review_note: str | None = None,
) -> WeeklyPdfJob:
    return WeeklyPdfJob(
        job_id=job_id,
        chat_id=chat_id,
        idempotency_key=f"idem-{job_id}",
        status="succeeded",
        refund_status=refund_status,
        consumption_source="monthly",
        stale_after=NOW + timedelta(minutes=15),
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(minutes=1),
        finished_at=NOW - timedelta(minutes=1),
        delivery_status=delivery_status,
        requires_manual_review=requires_manual_review,
        manual_review_reason="send_started_without_delivery_confirmation" if requires_manual_review else None,
        manual_reviewed_at=manual_reviewed_at,
        manual_reviewed_by=manual_reviewed_by,
        manual_review_resolution=manual_review_resolution,
        manual_review_note=manual_review_note,
    )


def _one_day_job(
    *,
    job_id: UUID,
    chat_id: int,
    requires_manual_review: bool = True,
    refund_status: str = "not_required",
    manual_reviewed_at: datetime | None = None,
) -> OneDayGenerationJob:
    return OneDayGenerationJob(
        job_id=job_id,
        chat_id=chat_id,
        idempotency_key=f"idem-{job_id}",
        status="succeeded",
        consumption_source="monthly",
        refund_status=refund_status,
        delivery_status="unknown",
        expected_value_messages=2,
        delivered_value_messages=1,
        stale_after=NOW + timedelta(minutes=15),
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(minutes=1),
        finished_at=NOW - timedelta(minutes=1),
        finalization_error="stale_after_send_attempt_unconfirmed",
        requires_manual_review=requires_manual_review,
        manual_reviewed_at=manual_reviewed_at,
    )
