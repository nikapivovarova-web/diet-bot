from __future__ import annotations

import sys
import types
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diet_bot.weekly_pdf_job_runtime import (
    WeeklyPdfDelivery,
    WeeklyPdfJobRuntime,
    WeeklyPdfWorker,
    WeeklyPdfWorkerSettings,
)
from diet_bot.weekly_pdf_jobs import (
    AdmitJobResult,
    AdmitJobResultStatus,
    ClaimQueuedJobResult,
    ClaimQueuedJobResultStatus,
    ExtendLeaseResult,
    ExtendLeaseResultStatus,
    FinishJobResult,
    FinishJobResultStatus,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MarkRetryableFailureResult,
    MarkRetryableFailureResultStatus,
    MarkDeliveredResult,
    MarkDeliveredResultStatus,
    MarkSendStartedResult,
    MarkSendStartedResultStatus,
    QueuedJobAdmissionResult,
    QueuedJobAdmissionResultStatus,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    REFUND_STATUS_REFUNDED,
    StartJobResult,
    StartJobResultStatus,
    WeeklyPdfJob,
    WeeklyPdfRequestSnapshot,
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


def test_runtime_queue_worker_methods_delegate_timestamps_and_lease_settings() -> None:
    store = FakeWeeklyPdfStore()
    runtime = WeeklyPdfJobRuntime(store, now=lambda: NOW, stale_after_seconds=120)
    snapshot = WeeklyPdfRequestSnapshot(
        request_payload={"source": "test"},
        profile={"age": 34},
        recent_recipe_ids=("r001",),
        generation_seed="456",
    )

    runtime.admit_queued(
        chat_id=107,
        idempotency_key="idem-durable",
        request_snapshot=snapshot,
        metadata={"source": "unit"},
        test_access=True,
    )
    runtime.claim_next_queued_job(worker_id="worker-a", lease_seconds=300)
    runtime.extend_lease("job-1", worker_id="worker-a", lease_seconds=180)
    runtime.mark_retryable_failure(
        "job-1",
        worker_id="worker-a",
        error="temporary",
        retry_delay_seconds=30,
    )

    assert store.calls[-4:] == [
        (
            "admit_queued",
            107,
            "idem-durable",
            NOW + timedelta(seconds=120),
            snapshot,
            {"source": "unit"},
            True,
        ),
        ("claim", "worker-a", NOW + timedelta(seconds=300)),
        ("extend", "job-1", "worker-a", NOW + timedelta(seconds=180)),
        ("retryable", "job-1", "worker-a", "temporary", NOW + timedelta(seconds=30)),
    ]


@pytest.mark.anyio
async def test_worker_processes_durable_weekly_queue_with_bounded_concurrency() -> None:
    store = _InMemoryWeeklyPdfJobStore(default_quota=1)
    runtime = WeeklyPdfJobRuntime(store)
    for chat_id in range(1, 7):
        runtime.admit_queued(
            chat_id=chat_id,
            idempotency_key=f"weekly:{chat_id}",
            request_snapshot=_weekly_snapshot(chat_id),
        )
    processor = _RecordingWeeklyPdfProcessor(send_delay=0)
    worker = WeeklyPdfWorker(
        runtime,
        processor,
        WeeklyPdfWorkerSettings(
            worker_id="weekly-worker-a",
            concurrency=2,
            lease_seconds=300,
            heartbeat_interval_seconds=3600,
            max_attempts=1,
        ),
    )

    processed = await worker.run_until_empty(max_batches=10)

    assert processed == 6
    assert processor.max_active_builders <= 2
    assert all(job.status == JOB_STATUS_SUCCEEDED for job in store.jobs_by_id.values())
    assert all(job.delivery_status == "delivered" for job in store.jobs_by_id.values())
    assert {call[0] for call in store.calls} >= {
        "claim_next_queued_job",
        "mark_send_started",
        "mark_delivered",
        "finish_success",
    }


@pytest.mark.anyio
async def test_worker_retries_pre_send_failure_then_refunds_once_after_max_attempts() -> None:
    store = _InMemoryWeeklyPdfJobStore(default_quota=1)
    runtime = WeeklyPdfJobRuntime(store)
    admitted = runtime.admit_queued(
        chat_id=77,
        idempotency_key="weekly-retry",
        request_snapshot=_weekly_snapshot(77),
    ).job
    processor = _FailingWeeklyPdfProcessor(RuntimeError("builder temporarily failed"))
    worker = WeeklyPdfWorker(
        runtime,
        processor,
        WeeklyPdfWorkerSettings(
            worker_id="weekly-worker-a",
            concurrency=1,
            retry_delay_seconds=0,
            max_attempts=2,
        ),
    )

    first_batch = await worker.run_once()
    second_batch = await worker.run_once()
    failed = store.jobs_by_id[admitted.job_id]

    assert first_batch == 1
    assert second_batch == 1
    assert failed.status == JOB_STATUS_FAILED
    assert failed.refund_status == REFUND_STATUS_REFUNDED
    assert failed.send_started_at is None
    assert store.quota_by_chat_id[77] == 1
    assert ("mark_retryable_failure", admitted.job_id) in store.calls
    assert ("finish_failure_and_refund_once", admitted.job_id) in store.calls


@pytest.mark.anyio
async def test_worker_send_started_failure_requires_manual_review_without_refund() -> None:
    store = _InMemoryWeeklyPdfJobStore(default_quota=1)
    runtime = WeeklyPdfJobRuntime(store)
    admitted = runtime.admit_queued(
        chat_id=88,
        idempotency_key="weekly-send-started-failure",
        request_snapshot=_weekly_snapshot(88),
    ).job
    processor = _RecordingWeeklyPdfProcessor(send_started_failure_chat_ids={88})
    worker = WeeklyPdfWorker(
        runtime,
        processor,
        WeeklyPdfWorkerSettings(worker_id="weekly-worker-a", concurrency=1, max_attempts=1),
    )

    processed = await worker.run_once()
    saved = store.jobs_by_id[admitted.job_id]

    assert processed == 1
    assert saved.status == JOB_STATUS_SUCCEEDED
    assert saved.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert saved.delivery_status == "unknown"
    assert saved.requires_manual_review is True
    assert saved.send_started_at is not None
    assert store.quota_by_chat_id[88] == 0
    assert ("mark_retryable_failure", admitted.job_id) not in store.calls


@pytest.mark.anyio
async def test_synthetic_500_weekly_pdf_requests_dedupe_and_process_with_bounded_worker() -> None:
    store = _InMemoryWeeklyPdfJobStore(default_quota=1)
    runtime = WeeklyPdfJobRuntime(store)
    accepted = 0
    duplicates = 0
    for chat_id in range(1, 501):
        admission = runtime.admit_queued(
            chat_id=chat_id,
            idempotency_key=f"burst:{chat_id}",
            request_snapshot=_weekly_snapshot(chat_id),
        )
        if admission.status == QueuedJobAdmissionResultStatus.ADMITTED:
            accepted += 1
        duplicate = runtime.admit_queued(
            chat_id=chat_id,
            idempotency_key=f"burst:{chat_id}:duplicate",
            request_snapshot=_weekly_snapshot(chat_id),
        )
        if duplicate.status == QueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE:
            duplicates += 1

    processor = _RecordingWeeklyPdfProcessor(
        pre_send_failure_chat_ids={17},
        send_started_failure_chat_ids={29},
        send_delay=0,
    )
    worker = WeeklyPdfWorker(
        runtime,
        processor,
        WeeklyPdfWorkerSettings(
            worker_id="weekly-worker-a",
            concurrency=5,
            retry_delay_seconds=0,
            max_attempts=1,
        ),
    )

    processed = await worker.run_until_empty(max_batches=120)
    jobs = list(store.jobs_by_id.values())
    pre_send_failure = store.job_by_chat_id[17]
    send_started_unknown = store.job_by_chat_id[29]

    assert accepted == 500
    assert duplicates == 500
    assert processed == 500
    assert processor.max_active_builders <= 5
    assert sum(1 for job in jobs if job.status == JOB_STATUS_FAILED) == 1
    assert sum(1 for job in jobs if job.delivery_status == "delivered") == 498
    assert pre_send_failure.status == JOB_STATUS_FAILED
    assert pre_send_failure.refund_status == REFUND_STATUS_REFUNDED
    assert store.quota_by_chat_id[17] == 1
    assert send_started_unknown.status == JOB_STATUS_SUCCEEDED
    assert send_started_unknown.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert send_started_unknown.requires_manual_review is True
    assert store.quota_by_chat_id[29] == 0
    assert all(count == 1 for count in store.consumed_count_by_chat_id.values())


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

    def admit_queued_job(
        self,
        *,
        chat_id,
        idempotency_key,
        stale_after,
        request_snapshot,
        metadata=None,
        now=None,
        test_access=False,
    ):
        self.calls.append(
            (
                "admit_queued",
                chat_id,
                idempotency_key,
                stale_after,
                request_snapshot,
                metadata,
                test_access,
            )
        )
        return QueuedJobAdmissionResult(
            QueuedJobAdmissionResultStatus.ADMITTED,
            _job(status=JOB_STATUS_QUEUED, chat_id=chat_id),
        )

    def claim_next_queued_job(self, *, worker_id, lease_until, now=None):
        self.calls.append(("claim", worker_id, lease_until))
        return ClaimQueuedJobResult(ClaimQueuedJobResultStatus.EMPTY, None)

    def extend_lease(self, job_id, *, worker_id, lease_until, now=None):
        self.calls.append(("extend", job_id, worker_id, lease_until))
        return ExtendLeaseResult(ExtendLeaseResultStatus.EXTENDED, _job(status=JOB_STATUS_RUNNING, chat_id=1))

    def mark_retryable_failure(self, job_id, *, worker_id, error, next_attempt_at, now=None):
        self.calls.append(("retryable", job_id, worker_id, error, next_attempt_at))
        return MarkRetryableFailureResult(
            MarkRetryableFailureResultStatus.MARKED,
            _job(status=JOB_STATUS_QUEUED, chat_id=1),
        )


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


def _weekly_snapshot(chat_id: int) -> WeeklyPdfRequestSnapshot:
    return WeeklyPdfRequestSnapshot(
        request_payload={"chat_id": chat_id, "recent_recipe_keys": [f"key-{chat_id}"]},
        profile={"age": 30 + chat_id % 10},
        recent_recipe_ids=(f"r{chat_id:03d}",),
        generation_seed=str(10_000 + chat_id),
    )


class _RecordingWeeklyPdfProcessor:
    def __init__(
        self,
        *,
        pre_send_failure_chat_ids: set[int] | None = None,
        send_started_failure_chat_ids: set[int] | None = None,
        send_delay: float | None = None,
    ) -> None:
        self.pre_send_failure_chat_ids = pre_send_failure_chat_ids or set()
        self.send_started_failure_chat_ids = send_started_failure_chat_ids or set()
        self.send_delay = send_delay
        self.active_builders = 0
        self.max_active_builders = 0
        self.snapshots: list[WeeklyPdfRequestSnapshot] = []

    async def prepare_delivery(self, job: WeeklyPdfJob) -> WeeklyPdfDelivery:
        assert job.request_snapshot is not None
        self.active_builders += 1
        self.max_active_builders = max(self.max_active_builders, self.active_builders)
        try:
            await asyncio.sleep(0)
            self.snapshots.append(job.request_snapshot)
            if job.chat_id in self.pre_send_failure_chat_ids:
                raise RuntimeError("injected builder failure")

            async def send(on_send_started, on_delivered) -> bool:
                on_send_started()
                if self.send_delay is not None:
                    await asyncio.sleep(self.send_delay)
                else:
                    await asyncio.sleep(0)
                if job.chat_id in self.send_started_failure_chat_ids:
                    raise RuntimeError("injected upload failure")
                on_delivered()
                return True

            return WeeklyPdfDelivery(send=send)
        finally:
            self.active_builders -= 1


class _FailingWeeklyPdfProcessor:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def prepare_delivery(self, _job: WeeklyPdfJob) -> WeeklyPdfDelivery:
        raise self.exc


class _InMemoryWeeklyPdfJobStore:
    def __init__(self, *, default_quota: int) -> None:
        self.default_quota = default_quota
        self.jobs_by_id: dict[object, WeeklyPdfJob] = {}
        self.idempotency_index: dict[str, object] = {}
        self.job_by_chat_id: dict[int, WeeklyPdfJob] = {}
        self.quota_by_chat_id: dict[int, int] = {}
        self.consumed_count_by_chat_id: dict[int, int] = {}
        self.calls: list[tuple] = []

    def admit_queued_job(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        stale_after: datetime,
        request_snapshot: WeeklyPdfRequestSnapshot,
        metadata=None,
        now: datetime | None = None,
        test_access: bool = False,
    ) -> QueuedJobAdmissionResult:
        self.calls.append(("admit_queued_job", chat_id))
        existing_id = self.idempotency_index.get(idempotency_key)
        if existing_id is not None:
            return QueuedJobAdmissionResult(
                QueuedJobAdmissionResultStatus.EXISTING_IDEMPOTENCY,
                self.jobs_by_id[existing_id],
            )
        active = self.job_by_chat_id.get(chat_id)
        if active is not None and active.status in {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING}:
            return QueuedJobAdmissionResult(QueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE, active)
        if test_access:
            consumption_source = "test_access"
            refund_status = REFUND_STATUS_NOT_REQUIRED
        else:
            quota = self.quota_by_chat_id.setdefault(chat_id, self.default_quota)
            if quota <= 0:
                return QueuedJobAdmissionResult(
                    QueuedJobAdmissionResultStatus.DENIED,
                    None,
                    "weekly_pdf_entitlement_unavailable",
                )
            self.quota_by_chat_id[chat_id] = quota - 1
            self.consumed_count_by_chat_id[chat_id] = self.consumed_count_by_chat_id.get(chat_id, 0) + 1
            consumption_source = "monthly"
            refund_status = REFUND_STATUS_PENDING
        job = WeeklyPdfJob(
            job_id=uuid4(),
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            status=JOB_STATUS_QUEUED,
            refund_status=refund_status,
            consumption_source=consumption_source,
            stale_after=stale_after,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
            request_snapshot=request_snapshot,
        )
        self._save(job)
        self.idempotency_index[idempotency_key] = job.job_id
        return QueuedJobAdmissionResult(QueuedJobAdmissionResultStatus.ADMITTED, job)

    def claim_next_queued_job(self, *, worker_id: str, lease_until: datetime, now=None) -> ClaimQueuedJobResult:
        self.calls.append(("claim_next_queued_job", worker_id))
        for job in sorted(self.jobs_by_id.values(), key=lambda candidate: candidate.chat_id):
            if job.status == JOB_STATUS_QUEUED:
                if job.next_attempt_at is not None and now is not None and job.next_attempt_at > now:
                    continue
            elif not (
                job.status == JOB_STATUS_RUNNING
                and job.leased_until is not None
                and now is not None
                and job.leased_until <= now
                and job.send_started_at is None
                and job.delivered_at is None
            ):
                continue
            claimed = replace(
                job,
                status=JOB_STATUS_RUNNING,
                worker_id=worker_id,
                leased_until=lease_until,
                next_attempt_at=None,
                started_at=job.started_at or now,
                heartbeat_at=now,
                updated_at=now,
            )
            self._save(claimed)
            return ClaimQueuedJobResult(ClaimQueuedJobResultStatus.CLAIMED, claimed)
        return ClaimQueuedJobResult(ClaimQueuedJobResultStatus.EMPTY, None)

    def extend_lease(self, job_id, *, worker_id: str, lease_until: datetime, now=None) -> ExtendLeaseResult:
        self.calls.append(("extend_lease", job_id))
        job = self.jobs_by_id.get(job_id)
        if job is None:
            return ExtendLeaseResult(ExtendLeaseResultStatus.NOT_FOUND, None)
        if job.status != JOB_STATUS_RUNNING:
            return ExtendLeaseResult(ExtendLeaseResultStatus.INVALID_STATE, job)
        if job.worker_id != worker_id:
            return ExtendLeaseResult(ExtendLeaseResultStatus.WORKER_MISMATCH, job)
        updated = replace(job, leased_until=lease_until, heartbeat_at=now, updated_at=now)
        self._save(updated)
        return ExtendLeaseResult(ExtendLeaseResultStatus.EXTENDED, updated)

    def mark_retryable_failure(
        self,
        job_id,
        *,
        worker_id: str,
        error: str | None,
        next_attempt_at: datetime,
        now=None,
    ) -> MarkRetryableFailureResult:
        self.calls.append(("mark_retryable_failure", job_id))
        job = self.jobs_by_id[job_id]
        if job.worker_id != worker_id:
            return MarkRetryableFailureResult(MarkRetryableFailureResultStatus.WORKER_MISMATCH, job)
        if job.send_started_at is not None or job.delivered_at is not None:
            return MarkRetryableFailureResult(MarkRetryableFailureResultStatus.INVALID_STATE, job)
        updated = replace(
            job,
            status=JOB_STATUS_QUEUED,
            worker_id=None,
            leased_until=None,
            next_attempt_at=next_attempt_at,
            attempt_count=job.attempt_count + 1,
            last_error=error,
            updated_at=now,
        )
        self._save(updated)
        return MarkRetryableFailureResult(MarkRetryableFailureResultStatus.MARKED, updated)

    def mark_send_started(self, job_id, *, now=None) -> MarkSendStartedResult:
        self.calls.append(("mark_send_started", job_id))
        job = self.jobs_by_id[job_id]
        updated = replace(job, send_started_at=now, delivery_status="send_started", updated_at=now)
        self._save(updated)
        return MarkSendStartedResult(MarkSendStartedResultStatus.SEND_STARTED, updated)

    def mark_delivered(self, job_id, *, now=None) -> MarkDeliveredResult:
        self.calls.append(("mark_delivered", job_id))
        job = self.jobs_by_id[job_id]
        updated = replace(job, delivered_at=now, delivery_status="delivered", updated_at=now)
        self._save(updated)
        return MarkDeliveredResult(MarkDeliveredResultStatus.DELIVERED, updated)

    def finish_success(self, job_id, *, now=None) -> FinishJobResult:
        self.calls.append(("finish_success", job_id))
        job = self.jobs_by_id[job_id]
        updated = replace(
            job,
            status=JOB_STATUS_SUCCEEDED,
            refund_status=REFUND_STATUS_NOT_REQUIRED,
            delivery_status="delivered" if job.delivered_at is not None else "unknown",
            requires_manual_review=job.delivered_at is None,
            manual_review_reason=None if job.delivered_at is not None else "send_started_without_delivery_confirmation",
            finished_at=now,
            updated_at=now,
        )
        self._save(updated)
        return FinishJobResult(FinishJobResultStatus.SUCCEEDED, updated)

    def finish_failure_and_refund_once(self, job_id, *, reason=None, now=None) -> FinishJobResult:
        self.calls.append(("finish_failure_and_refund_once", job_id))
        job = self.jobs_by_id[job_id]
        if job.send_started_at is not None or job.delivered_at is not None:
            updated = replace(
                job,
                status=JOB_STATUS_SUCCEEDED,
                refund_status=REFUND_STATUS_NOT_REQUIRED,
                delivery_status="delivered" if job.delivered_at is not None else "unknown",
                finalization_error=reason,
                requires_manual_review=job.delivered_at is None,
                manual_review_reason=None if job.delivered_at is not None else reason,
                finished_at=now,
                updated_at=now,
            )
            self._save(updated)
            return FinishJobResult(FinishJobResultStatus.SUCCEEDED, updated)
        refund_status = REFUND_STATUS_REFUNDED if job.refund_status == REFUND_STATUS_PENDING else REFUND_STATUS_NOT_REQUIRED
        if refund_status == REFUND_STATUS_REFUNDED:
            self.quota_by_chat_id[job.chat_id] = self.quota_by_chat_id.get(job.chat_id, 0) + 1
        updated = replace(
            job,
            status=JOB_STATUS_FAILED,
            refund_status=refund_status,
            failure_reason=reason,
            finished_at=now,
            updated_at=now,
        )
        self._save(updated)
        return FinishJobResult(FinishJobResultStatus.FAILED, updated)

    def _save(self, job: WeeklyPdfJob) -> None:
        self.jobs_by_id[job.job_id] = job
        self.job_by_chat_id[job.chat_id] = job
