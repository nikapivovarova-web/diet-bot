from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diet_bot.weekly_pdf_job_runtime import WeeklyPdfJobRuntime
from diet_bot.weekly_pdf_jobs import (
    AdmitJobResult,
    AdmitJobResultStatus,
    FinishJobResult,
    FinishJobResultStatus,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MarkDeliveredResult,
    MarkDeliveredResultStatus,
    MarkSendStartedResult,
    MarkSendStartedResultStatus,
    REFUND_STATUS_NOT_REQUIRED,
    StartJobResult,
    StartJobResultStatus,
    WeeklyPdfJob,
)


def test_json_runtime_factory_and_startup_validation_do_not_import_postgres_store(monkeypatch) -> None:
    from diet_bot.weekly_pdf_job_runtime import validate_weekly_pdf_job_runtime_for_startup

    monkeypatch.delitem(sys.modules, "diet_bot.postgres_weekly_pdf_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    imported: list[str] = []

    def fail_import(name, *_args, **_kwargs):
        imported.append(name)
        if name.startswith(("diet_bot.postgres_weekly_pdf_job_store", "psycopg")):
            raise AssertionError("JSON backend must not import Postgres weekly PDF store")
        return original_import(name, *_args, **_kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    runtime = WeeklyPdfJobRuntime.from_config(
        type("Config", (), {"storage_backend": "json", "database_url": None})(),
    )

    assert runtime is None
    assert "diet_bot.postgres_weekly_pdf_job_store" not in imported
    validate_weekly_pdf_job_runtime_for_startup(
        type("Config", (), {"storage_backend": "json", "database_url": None})(),
    )
    assert "diet_bot.postgres_weekly_pdf_job_store" not in sys.modules
    assert "psycopg" not in sys.modules


def test_postgres_runtime_factory_constructs_store_without_initializing(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    fake_module = types.ModuleType("diet_bot.postgres_weekly_pdf_job_store")

    class FakePostgresWeeklyPdfJobStore:
        def __init__(self, dsn: str, **_kwargs) -> None:
            calls.append(("construct", dsn))

        def initialize(self) -> None:
            calls.append(("initialize", None))
            raise AssertionError("runtime factory must not auto-migrate")

        def validate_schema(self) -> None:
            calls.append(("validate_schema", None))

    fake_module.PostgresWeeklyPdfJobStore = FakePostgresWeeklyPdfJobStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_weekly_pdf_job_store", fake_module)

    runtime = WeeklyPdfJobRuntime.from_config(
        type(
            "Config",
            (),
            {
                "storage_backend": "postgres",
                "database_url": "postgresql://user:secret@example/db",
            },
        )(),
    )

    assert runtime is not None
    assert calls == [("construct", "postgresql://user:secret@example/db")]


def test_postgres_startup_validation_validates_schema_without_initializing(monkeypatch) -> None:
    from diet_bot.weekly_pdf_job_runtime import validate_weekly_pdf_job_runtime_for_startup

    calls: list[tuple[str, str | None]] = []
    fake_module = types.ModuleType("diet_bot.postgres_weekly_pdf_job_store")

    class FakePostgresWeeklyPdfJobStore:
        def __init__(self, dsn: str, **_kwargs) -> None:
            calls.append(("construct", dsn))

        def initialize(self) -> None:
            calls.append(("initialize", None))
            raise AssertionError("startup validation must not auto-migrate")

        def validate_schema(self) -> None:
            calls.append(("validate_schema", None))

    fake_module.PostgresWeeklyPdfJobStore = FakePostgresWeeklyPdfJobStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_weekly_pdf_job_store", fake_module)

    validate_weekly_pdf_job_runtime_for_startup(
        type(
            "Config",
            (),
            {
                "storage_backend": "postgres",
                "database_url": "postgresql://user:secret@example/db",
            },
        )(),
    )

    assert calls == [
        ("construct", "postgresql://user:secret@example/db"),
        ("validate_schema", None),
    ]


def test_postgres_startup_validation_wraps_schema_failure(monkeypatch) -> None:
    from diet_bot.weekly_pdf_job_runtime import validate_weekly_pdf_job_runtime_for_startup

    fake_module = types.ModuleType("diet_bot.postgres_weekly_pdf_job_store")

    class FakePostgresWeeklyPdfJobStore:
        def __init__(self, _dsn: str, **_kwargs) -> None:
            pass

        def initialize(self) -> None:
            raise AssertionError("startup validation must not auto-migrate")

        def validate_schema(self) -> None:
            raise RuntimeError("missing weekly_pdf_jobs")

    fake_module.PostgresWeeklyPdfJobStore = FakePostgresWeeklyPdfJobStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_weekly_pdf_job_store", fake_module)

    with pytest.raises(RuntimeError, match="run weekly PDF job migrations before startup"):
        validate_weekly_pdf_job_runtime_for_startup(
            type(
                "Config",
                (),
                {
                    "storage_backend": "postgres",
                    "database_url": "postgresql://user:secret@example/db",
                },
            )(),
        )


def test_runtime_admit_duplicate_does_not_start_or_consume() -> None:
    store = FakeWeeklyPdfStore()
    active_job = _job(status=JOB_STATUS_RUNNING, chat_id=101)
    store.next_admit = AdmitJobResult(AdmitJobResultStatus.ACTIVE_DUPLICATE, active_job)
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW)

    result = runtime.admit(chat_id=101, idempotency_key="idem-duplicate")

    assert result.status == AdmitJobResultStatus.ACTIVE_DUPLICATE
    assert store.calls == [("admit", 101, "idem-duplicate")]


def test_runtime_existing_idempotency_does_not_start_or_consume() -> None:
    store = FakeWeeklyPdfStore()
    existing_job = _job(status=JOB_STATUS_QUEUED, chat_id=101)
    store.next_admit = AdmitJobResult(AdmitJobResultStatus.EXISTING_IDEMPOTENCY, existing_job)
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW)

    result = runtime.admit(chat_id=101, idempotency_key="idem-existing")

    assert result.status == AdmitJobResultStatus.EXISTING_IDEMPOTENCY
    assert store.calls == [("admit", 101, "idem-existing")]


def test_start_consumes_only_when_runner_starts() -> None:
    store = FakeWeeklyPdfStore()
    admitted = _job(status=JOB_STATUS_QUEUED, chat_id=102)
    running = _job(status=JOB_STATUS_RUNNING, chat_id=102)
    store.next_admit = AdmitJobResult(AdmitJobResultStatus.ADMITTED, admitted)
    store.next_start = StartJobResult(StartJobResultStatus.STARTED, running)
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW)

    admission = runtime.admit(chat_id=102, idempotency_key="idem-start")
    assert admission.status == AdmitJobResultStatus.ADMITTED
    assert store.calls == [("admit", 102, "idem-start")]

    started = runtime.start_job_and_consume(admitted.job_id)

    assert started.status == StartJobResultStatus.STARTED
    assert store.calls == [
        ("admit", 102, "idem-start"),
        ("start", admitted.job_id, False),
    ]


def test_runtime_test_access_start_does_not_mutate_entitlement_or_refund() -> None:
    store = FakeWeeklyPdfStore()
    admitted = _job(status=JOB_STATUS_QUEUED, chat_id=103)
    running = _job(status=JOB_STATUS_RUNNING, chat_id=103, consumption_source="test_access")
    failed = _job(status=JOB_STATUS_FAILED, chat_id=103, consumption_source="test_access")
    store.next_admit = AdmitJobResult(AdmitJobResultStatus.ADMITTED, admitted)
    store.next_start = StartJobResult(StartJobResultStatus.STARTED, running)
    store.next_failure = FinishJobResult(FinishJobResultStatus.FAILED, failed)
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW)

    runtime.admit(chat_id=103, idempotency_key="idem-test")
    started = runtime.start_job_and_consume(admitted.job_id, test_access=True)
    failed_result = runtime.finish_failure_and_refund_once(admitted.job_id, reason="send_failed")

    assert started.job.consumption_source == "test_access"
    assert failed_result.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert store.calls == [
        ("admit", 103, "idem-test"),
        ("start", admitted.job_id, True),
        ("failure", admitted.job_id, "send_failed"),
    ]


def test_runtime_success_and_failure_delegate_to_store_once() -> None:
    store = FakeWeeklyPdfStore()
    running = _job(status=JOB_STATUS_RUNNING, chat_id=104)
    succeeded = _job(status=JOB_STATUS_SUCCEEDED, chat_id=104)
    failed = _job(status=JOB_STATUS_FAILED, chat_id=104)
    store.next_start = StartJobResult(StartJobResultStatus.STARTED, running)
    store.next_success = FinishJobResult(FinishJobResultStatus.SUCCEEDED, succeeded)
    store.next_failure = FinishJobResult(FinishJobResultStatus.FAILED, failed)
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW)

    runtime.start_job_and_consume(running.job_id)
    success = runtime.finish_success(running.job_id)
    failure = runtime.finish_failure_and_refund_once(running.job_id, reason="late")

    assert success.status == FinishJobResultStatus.SUCCEEDED
    assert failure.status == FinishJobResultStatus.FAILED
    assert store.calls == [
        ("start", running.job_id, False),
        ("success", running.job_id),
        ("failure", running.job_id, "late"),
    ]


def test_runtime_mark_delivered_delegates_to_store_once() -> None:
    store = FakeWeeklyPdfStore()
    running = _job(status=JOB_STATUS_RUNNING, chat_id=104)
    store.next_delivered = MarkDeliveredResult(MarkDeliveredResultStatus.DELIVERED, running)
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW)

    result = runtime.mark_delivered(running.job_id)

    assert result.status == MarkDeliveredResultStatus.DELIVERED
    assert store.calls == [("delivered", running.job_id)]


def test_runtime_mark_send_started_delegates_to_store_once() -> None:
    store = FakeWeeklyPdfStore()
    running = _job(status=JOB_STATUS_RUNNING, chat_id=104)
    store.next_send_started = MarkSendStartedResult(MarkSendStartedResultStatus.SEND_STARTED, running)
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW)

    result = runtime.mark_send_started(running.job_id)

    assert result.status == MarkSendStartedResultStatus.SEND_STARTED
    assert store.calls == [("send_started", running.job_id)]


def test_runtime_scoped_cleanup_uses_chat_id_and_small_limit() -> None:
    store = FakeWeeklyPdfStore()
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW)

    runtime.cleanup_stale(chat_id=105)

    assert store.calls == [("cleanup", 105, 10)]


def test_runtime_cancels_admitted_queued_job_without_refund() -> None:
    store = FakeWeeklyPdfStore()
    queued = _job(status=JOB_STATUS_QUEUED, chat_id=106)
    cancelled = _job(status=JOB_STATUS_CANCELLED, chat_id=106)
    store.next_cancel = FinishJobResult(FinishJobResultStatus.CANCELLED, cancelled)
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW)

    result = runtime.cancel_admitted_job(queued.job_id, reason="local_queue_submit_failed")

    assert result.status == FinishJobResultStatus.CANCELLED
    assert result.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert store.calls == [("cancel", queued.job_id, "local_queue_submit_failed")]


NOW = datetime(2026, 5, 23, 12, 0, tzinfo=UTC)


class FakeWeeklyPdfStore:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.next_admit: AdmitJobResult | None = None
        self.next_start: StartJobResult | None = None
        self.next_success: FinishJobResult | None = None
        self.next_failure: FinishJobResult | None = None
        self.next_delivered: MarkDeliveredResult | None = None
        self.next_send_started: MarkSendStartedResult | None = None
        self.next_cancel: FinishJobResult | None = None

    def admit_job(self, *, chat_id, idempotency_key, stale_after, metadata=None):
        self.calls.append(("admit", chat_id, idempotency_key))
        return self.next_admit or AdmitJobResult(
            AdmitJobResultStatus.ADMITTED,
            _job(status=JOB_STATUS_QUEUED, chat_id=chat_id),
        )

    def start_job_and_consume(self, job_id, *, now=None, stale_after=None, test_access=False):
        self.calls.append(("start", job_id, test_access))
        return self.next_start or StartJobResult(
            StartJobResultStatus.STARTED,
            _job(status=JOB_STATUS_RUNNING, chat_id=1),
        )

    def finish_success(self, job_id, *, now=None):
        self.calls.append(("success", job_id))
        return self.next_success or FinishJobResult(
            FinishJobResultStatus.SUCCEEDED,
            _job(status=JOB_STATUS_SUCCEEDED, chat_id=1),
        )

    def finish_failure_and_refund_once(self, job_id, *, reason=None, now=None):
        self.calls.append(("failure", job_id, reason))
        return self.next_failure or FinishJobResult(
            FinishJobResultStatus.FAILED,
            _job(status=JOB_STATUS_FAILED, chat_id=1),
        )

    def mark_delivered(self, job_id, *, now=None):
        self.calls.append(("delivered", job_id))
        return self.next_delivered or MarkDeliveredResult(
            MarkDeliveredResultStatus.DELIVERED,
            _job(status=JOB_STATUS_RUNNING, chat_id=1),
        )

    def mark_send_started(self, job_id, *, now=None):
        self.calls.append(("send_started", job_id))
        return self.next_send_started or MarkSendStartedResult(
            MarkSendStartedResultStatus.SEND_STARTED,
            _job(status=JOB_STATUS_RUNNING, chat_id=1),
        )

    def cancel_queued(self, job_id, *, reason=None, now=None):
        self.calls.append(("cancel", job_id, reason))
        return self.next_cancel or FinishJobResult(
            FinishJobResultStatus.CANCELLED,
            _job(status=JOB_STATUS_CANCELLED, chat_id=1),
        )

    def cleanup_stale(self, *, chat_id=None, now=None, limit=100):
        self.calls.append(("cleanup", chat_id, limit))
        return None


def _job(
    *,
    status: str,
    chat_id: int,
    consumption_source: str | None = None,
) -> WeeklyPdfJob:
    return WeeklyPdfJob(
        job_id=uuid4(),
        chat_id=chat_id,
        idempotency_key=f"idem-{chat_id}",
        status=status,
        refund_status=REFUND_STATUS_NOT_REQUIRED,
        consumption_source=consumption_source,
        stale_after=NOW + timedelta(minutes=15),
    )
