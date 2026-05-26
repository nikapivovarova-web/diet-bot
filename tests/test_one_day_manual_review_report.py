from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from uuid import UUID

from diet_bot.one_day_generation_jobs import OneDayGenerationJob
from diet_bot.ops import one_day_manual_review_report as report


def test_report_default_lists_unresolved_one_day_jobs_as_redacted_table() -> None:
    now = datetime(2026, 5, 26, 9, 15, tzinfo=UTC)
    job = _job(
        job_id=UUID("00000000-0000-0000-0000-000000001001"),
        chat_id=987654321,
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(minutes=4),
        finished_at=now - timedelta(minutes=3),
        status="succeeded",
        delivery_status="unknown",
        consumption_source="monthly",
        expected_value_messages=2,
        delivered_value_messages=0,
        finalization_error="stale_after_send_attempt_unconfirmed",
    )
    clean_delivered = _job(
        job_id=UUID("00000000-0000-0000-0000-000000001002"),
        chat_id=123123123,
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(minutes=4),
        finished_at=now - timedelta(minutes=3),
        status="succeeded",
        delivery_status="delivered",
        expected_value_messages=2,
        delivered_value_messages=2,
        requires_manual_review=False,
    )
    store = FakeStore(unresolved_jobs=[job], all_jobs=[job, clean_delivered])
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
    assert str(clean_delivered.job_id) not in output
    assert "unknown" in output
    assert "monthly" in output
    assert "2" in output
    assert "0" in output
    assert "stale_after_send_attempt_unconfirmed" in output
    assert "987654321" not in output
    assert "123123123" not in output
    assert "secret" not in output
    assert "postgresql://" not in output
    assert "idem-" not in output
    assert "metadata" not in output
    assert "chat:sha256:" in output


def test_report_json_redacts_sensitive_fields() -> None:
    now = datetime(2026, 5, 26, 9, 15, tzinfo=UTC)
    job = _job(
        job_id=UUID("00000000-0000-0000-0000-000000001101"),
        chat_id=222333444,
        created_at=now - timedelta(hours=1),
        updated_at=now,
        finished_at=now,
        delivery_status="unknown",
        consumption_source="extra",
        expected_value_messages=3,
        delivered_value_messages=1,
        failure_reason="second_message_failed",
        finalization_error="one_day_generation_job_stale",
        metadata={"telegram_message_id": 42, "secret": "payload-secret"},
    )
    store = FakeStore(unresolved_jobs=[job])
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
    assert payload["mode"] == "one_day_manual_review"
    assert payload["limit"] == 5
    assert payload["count"] == 1
    assert payload["jobs"][0]["job_id"] == str(job.job_id)
    assert payload["jobs"][0]["expected_value_messages"] == 3
    assert payload["jobs"][0]["delivered_value_messages"] == 1
    assert payload["jobs"][0]["requires_manual_review"] is True
    assert payload["jobs"][0]["chat_id_hash"].startswith("chat:sha256:")
    assert "chat_id" not in payload["jobs"][0]
    assert "idempotency_key" not in payload["jobs"][0]
    assert "metadata" not in payload["jobs"][0]
    assert "222333444" not in rendered
    assert "payload-secret" not in rendered
    assert "secret" not in rendered
    assert "postgresql://" not in rendered


def test_include_reviewed_is_not_supported_without_review_fields() -> None:
    stderr = StringIO()

    exit_code = report.main(
        ["--include-reviewed"],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=FailingStoreFactory(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "unrecognized arguments: --include-reviewed" in stderr.getvalue()


def test_database_url_env_can_be_overridden() -> None:
    now = datetime(2026, 5, 26, 9, 15, tzinfo=UTC)
    store = FakeStore(
        unresolved_jobs=[
            _job(
                job_id=UUID("00000000-0000-0000-0000-000000001151"),
                chat_id=151,
                created_at=now,
                updated_at=now,
                finished_at=now,
                delivery_status="unknown",
            )
        ]
    )
    seen_dsns: list[str] = []

    def store_factory(dsn: str) -> FakeStore:
        seen_dsns.append(dsn)
        return store

    exit_code = report.main(
        ["--database-url-env", "ONE_DAY_REVIEW_DATABASE_URL"],
        env={"ONE_DAY_REVIEW_DATABASE_URL": "postgresql://user:custom-secret@example.invalid/prod"},
        store_factory=store_factory,
        stdout=StringIO(),
    )

    assert exit_code == 0
    assert seen_dsns == ["postgresql://user:custom-secret@example.invalid/prod"]


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


def test_report_uses_read_only_store_query() -> None:
    now = datetime(2026, 5, 26, 9, 15, tzinfo=UTC)
    store = FakeStore(
        unresolved_jobs=[
            _job(
                job_id=UUID("00000000-0000-0000-0000-000000001201"),
                chat_id=201,
                created_at=now,
                updated_at=now,
                finished_at=now,
                delivery_status="unknown",
            )
        ]
    )

    exit_code = report.main(
        ["--limit", "3"],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret@example.invalid/prod"},
        store_factory=lambda _dsn: store,
        stdout=StringIO(),
    )

    assert exit_code == 0
    assert store.calls == [("unresolved", 3)]


class FakeStore:
    def __init__(
        self,
        *,
        unresolved_jobs: list[OneDayGenerationJob],
        all_jobs: list[OneDayGenerationJob] | None = None,
    ) -> None:
        self.unresolved_jobs = list(unresolved_jobs)
        self.all_jobs = list(all_jobs or unresolved_jobs)
        self.calls: list[tuple] = []

    def get_unresolved_manual_review_jobs(self, *, limit: int) -> list[OneDayGenerationJob]:
        self.calls.append(("unresolved", limit))
        return [job for job in self.unresolved_jobs if job.requires_manual_review][:limit]

    def admit_job(self, *args, **kwargs):
        raise AssertionError("report must not mutate jobs")

    def start_job_and_consume(self, *args, **kwargs):
        raise AssertionError("report must not mutate jobs")

    def finish_success(self, *args, **kwargs):
        raise AssertionError("report must not mutate jobs")

    def finish_failure_and_refund_once(self, *args, **kwargs):
        raise AssertionError("report must not mutate jobs")

    def cleanup_stale(self, *args, **kwargs):
        raise AssertionError("report must not mutate jobs")


class ExplodingStore:
    def get_unresolved_manual_review_jobs(self, *, limit: int) -> list[OneDayGenerationJob]:
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
    finished_at: datetime | None = None,
    status: str = "succeeded",
    refund_status: str = "not_required",
    consumption_source: str | None = None,
    delivery_status: str,
    expected_value_messages: int = 2,
    delivered_value_messages: int = 0,
    failure_reason: str | None = None,
    finalization_error: str | None = None,
    requires_manual_review: bool = True,
    metadata: dict[str, object] | None = None,
) -> OneDayGenerationJob:
    return OneDayGenerationJob(
        job_id=job_id,
        chat_id=chat_id,
        idempotency_key=f"idem-{job_id}",
        status=status,
        refund_status=refund_status,
        consumption_source=consumption_source,
        delivery_status=delivery_status,
        expected_value_messages=expected_value_messages,
        delivered_value_messages=delivered_value_messages,
        stale_after=updated_at + timedelta(minutes=15),
        metadata=dict(metadata or {}),
        created_at=created_at,
        updated_at=updated_at,
        finished_at=finished_at,
        failure_reason=failure_reason,
        finalization_error=finalization_error,
        requires_manual_review=requires_manual_review,
    )
