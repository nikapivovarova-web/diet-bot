from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
    REFUND_STATUS_NOT_REQUIRED,
    StartJobResult,
    StartJobResultStatus,
    WeeklyPdfJob,
)


def test_json_runtime_factory_does_not_import_postgres_store(monkeypatch) -> None:
    imported: list[str] = []

    def fail_import(name, *_args, **_kwargs):
        imported.append(name)
        if name == "diet_bot.postgres_weekly_pdf_job_store":
            raise AssertionError("JSON backend must not import Postgres weekly PDF store")
        return original_import(name, *_args, **_kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    runtime = WeeklyPdfJobRuntime.from_config(
        type("Config", (), {"storage_backend": "json", "database_url": None})(),
    )

    assert runtime is None
    assert "diet_bot.postgres_weekly_pdf_job_store" not in imported


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
