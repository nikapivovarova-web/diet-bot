from __future__ import annotations

import sys
import types
import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diet_bot.one_day_generation_jobs import (
    ClaimQueuedJobResult,
    ClaimQueuedJobResultStatus,
    ExtendLeaseResult,
    ExtendLeaseResultStatus,
    FinishJobResult,
    FinishJobResultStatus,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MarkRetryableFailureResult,
    MarkRetryableFailureResultStatus,
    MarkSendStartedResult,
    MarkSendStartedResultStatus,
    MarkValueMessageDeliveredResult,
    MarkValueMessageDeliveredResultStatus,
    OneDayGenerationJob,
    OneDayGenerationRequestSnapshot,
    QueuedJobAdmissionResult,
    QueuedJobAdmissionResultStatus,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    REFUND_STATUS_REFUNDED,
    SetExpectedValueMessagesResult,
    SetExpectedValueMessagesResultStatus,
)
from diet_bot.one_day_generation_job_runtime import (
    OneDayGenerationDelivery,
    OneDayGenerationJobRuntime,
    OneDayGenerationValueMessage,
    OneDayGenerationWorker,
    OneDayGenerationWorkerSettings,
    validate_one_day_generation_job_store_for_startup,
)


def test_json_startup_validation_does_not_import_postgres_store(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    imported: list[str] = []

    def fail_import(name, *_args, **_kwargs):
        imported.append(name)
        if name.startswith(("diet_bot.postgres_one_day_generation_job_store", "psycopg")):
            raise AssertionError("JSON backend must not import Postgres one-day generation job store")
        return original_import(name, *_args, **_kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    validate_one_day_generation_job_store_for_startup(
        type("Config", (), {"storage_backend": "json", "database_url": None})(),
    )

    assert "diet_bot.postgres_one_day_generation_job_store" not in imported
    assert "diet_bot.postgres_one_day_generation_job_store" not in sys.modules
    assert "psycopg" not in sys.modules


def test_json_runtime_from_config_does_not_import_postgres_store(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    imported: list[str] = []

    def fail_import(name, *_args, **_kwargs):
        imported.append(name)
        if name.startswith(("diet_bot.postgres_one_day_generation_job_store", "psycopg")):
            raise AssertionError("JSON backend must not import Postgres one-day generation job store")
        return original_import(name, *_args, **_kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    runtime = OneDayGenerationJobRuntime.from_config(
        type("Config", (), {"storage_backend": "json", "database_url": None})(),
    )

    assert runtime is None
    assert "diet_bot.postgres_one_day_generation_job_store" not in imported
    assert "diet_bot.postgres_one_day_generation_job_store" not in sys.modules
    assert "psycopg" not in sys.modules


def test_postgres_runtime_from_config_constructs_store(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    fake_module = types.ModuleType("diet_bot.postgres_one_day_generation_job_store")

    class FakePostgresOneDayGenerationJobStore:
        def __init__(self, dsn: str, **_kwargs) -> None:
            calls.append(("construct", dsn))

    fake_module.PostgresOneDayGenerationJobStore = FakePostgresOneDayGenerationJobStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", fake_module)

    runtime = OneDayGenerationJobRuntime.from_config(
        type(
            "Config",
            (),
            {
                "storage_backend": "postgres",
                "database_url": "postgresql://user:secret@example/db",
            },
        )(),
    )

    assert isinstance(runtime, OneDayGenerationJobRuntime)
    assert calls == [("construct", "postgresql://user:secret@example/db")]


def test_runtime_wrapper_methods_delegate_timestamps_and_stale_settings() -> None:
    now = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
    returns = {
        "admit_job": object(),
        "start_job_and_consume": object(),
        "set_expected_value_messages": object(),
        "mark_send_started": object(),
        "mark_value_message_delivered": object(),
        "finish_success": object(),
        "finish_failure_and_refund_once": object(),
        "cleanup_stale": object(),
    }
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeStore:
        def admit_job(self, **kwargs):
            calls.append(("admit_job", kwargs))
            return returns["admit_job"]

        def start_job_and_consume(self, job_id, **kwargs):
            calls.append(("start_job_and_consume", {"job_id": job_id, **kwargs}))
            return returns["start_job_and_consume"]

        def set_expected_value_messages(self, job_id, expected_count, **kwargs):
            calls.append(
                (
                    "set_expected_value_messages",
                    {"job_id": job_id, "expected_count": expected_count, **kwargs},
                )
            )
            return returns["set_expected_value_messages"]

        def mark_send_started(self, job_id, **kwargs):
            calls.append(("mark_send_started", {"job_id": job_id, **kwargs}))
            return returns["mark_send_started"]

        def mark_value_message_delivered(self, job_id, **kwargs):
            calls.append(("mark_value_message_delivered", {"job_id": job_id, **kwargs}))
            return returns["mark_value_message_delivered"]

        def finish_success(self, job_id, **kwargs):
            calls.append(("finish_success", {"job_id": job_id, **kwargs}))
            return returns["finish_success"]

        def finish_failure_and_refund_once(self, job_id, **kwargs):
            calls.append(("finish_failure_and_refund_once", {"job_id": job_id, **kwargs}))
            return returns["finish_failure_and_refund_once"]

        def cleanup_stale(self, **kwargs):
            calls.append(("cleanup_stale", kwargs))
            return returns["cleanup_stale"]

    runtime = OneDayGenerationJobRuntime(
        FakeStore(),
        now=lambda: now,
        stale_after_seconds=90,
        cleanup_limit=4,
    )

    assert runtime.admit(chat_id=123, idempotency_key="event-1", metadata={"source": "test"}) is returns["admit_job"]
    assert runtime.start_job_and_consume("job-1", test_access=True) is returns["start_job_and_consume"]
    assert runtime.set_expected_value_messages("job-1", 6) is returns["set_expected_value_messages"]
    assert runtime.mark_send_started("job-1") is returns["mark_send_started"]
    assert (
        runtime.mark_value_message_delivered("job-1", value_message_key="meal:00:r1")
        is returns["mark_value_message_delivered"]
    )
    assert runtime.finish_success("job-1") is returns["finish_success"]
    assert (
        runtime.finish_failure_and_refund_once("job-1", reason="one_day_failed")
        is returns["finish_failure_and_refund_once"]
    )
    assert runtime.cleanup_stale(chat_id=123) is returns["cleanup_stale"]

    assert calls == [
        (
            "admit_job",
            {
                "chat_id": 123,
                "idempotency_key": "event-1",
                "stale_after": now + timedelta(seconds=90),
                "metadata": {"source": "test"},
            },
        ),
        (
            "start_job_and_consume",
            {
                "job_id": "job-1",
                "now": now,
                "stale_after": now + timedelta(seconds=90),
                "test_access": True,
            },
        ),
        ("set_expected_value_messages", {"job_id": "job-1", "expected_count": 6, "now": now}),
        ("mark_send_started", {"job_id": "job-1", "now": now}),
        (
            "mark_value_message_delivered",
            {"job_id": "job-1", "value_message_key": "meal:00:r1", "now": now},
        ),
        ("finish_success", {"job_id": "job-1", "now": now}),
        ("finish_failure_and_refund_once", {"job_id": "job-1", "reason": "one_day_failed", "now": now}),
        ("cleanup_stale", {"chat_id": 123, "now": now, "limit": 4}),
    ]


def test_runtime_queue_worker_methods_delegate_timestamps_and_lease_settings() -> None:
    now = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
    returns = {
        "admit_queued_job": object(),
        "claim_next_queued_job": object(),
        "extend_lease": object(),
        "mark_retryable_failure": object(),
    }
    calls: list[tuple[str, dict[str, object]]] = []
    snapshot = OneDayGenerationRequestSnapshot(
        request_kind="telegram_one_day",
        profile={"age": 32},
        recent_recipe_ids=("r001",),
        generation_seed="123",
    )

    class FakeStore:
        def admit_queued_job(self, **kwargs):
            calls.append(("admit_queued_job", kwargs))
            return returns["admit_queued_job"]

        def claim_next_queued_job(self, **kwargs):
            calls.append(("claim_next_queued_job", kwargs))
            return returns["claim_next_queued_job"]

        def extend_lease(self, job_id, **kwargs):
            calls.append(("extend_lease", {"job_id": job_id, **kwargs}))
            return returns["extend_lease"]

        def mark_retryable_failure(self, job_id, **kwargs):
            calls.append(("mark_retryable_failure", {"job_id": job_id, **kwargs}))
            return returns["mark_retryable_failure"]

    runtime = OneDayGenerationJobRuntime(
        FakeStore(),
        now=lambda: now,
        stale_after_seconds=120,
    )

    assert (
        runtime.admit_queued(
            chat_id=321,
            idempotency_key="queued-1",
            request_snapshot=snapshot,
            metadata={"source": "test"},
            test_access=True,
        )
        is returns["admit_queued_job"]
    )
    assert (
        runtime.claim_next_queued_job(worker_id="worker-a", lease_seconds=300)
        is returns["claim_next_queued_job"]
    )
    assert (
        runtime.extend_lease("job-1", worker_id="worker-a", lease_seconds=180)
        is returns["extend_lease"]
    )
    assert (
        runtime.mark_retryable_failure(
            "job-1",
            worker_id="worker-a",
            error="temporary",
            retry_delay_seconds=30,
        )
        is returns["mark_retryable_failure"]
    )

    assert calls == [
        (
            "admit_queued_job",
            {
                "chat_id": 321,
                "idempotency_key": "queued-1",
                "stale_after": now + timedelta(seconds=120),
                "request_snapshot": snapshot,
                "metadata": {"source": "test"},
                "now": now,
                "test_access": True,
            },
        ),
        (
            "claim_next_queued_job",
            {
                "worker_id": "worker-a",
                "lease_until": now + timedelta(seconds=300),
                "now": now,
            },
        ),
        (
            "extend_lease",
            {
                "job_id": "job-1",
                "worker_id": "worker-a",
                "lease_until": now + timedelta(seconds=180),
                "now": now,
            },
        ),
        (
            "mark_retryable_failure",
            {
                "job_id": "job-1",
                "worker_id": "worker-a",
                "error": "temporary",
                "next_attempt_at": now + timedelta(seconds=30),
                "now": now,
            },
        ),
    ]


@pytest.mark.anyio
async def test_worker_claims_leased_jobs_and_finalizes_value_delivery_with_bounded_concurrency() -> None:
    store = _InMemoryOneDayGenerationJobStore(default_quota=1)
    runtime = OneDayGenerationJobRuntime(store)
    for chat_id in range(1, 7):
        runtime.admit_queued(
            chat_id=chat_id,
            idempotency_key=f"job-{chat_id}",
            request_snapshot=_snapshot(chat_id),
        )
    processor = _RecordingProcessor(send_delay=0)
    worker = OneDayGenerationWorker(
        runtime,
        processor,
        OneDayGenerationWorkerSettings(
            worker_id="worker-a",
            concurrency=2,
            lease_seconds=300,
            heartbeat_interval_seconds=3600,
            max_attempts=1,
        ),
    )

    processed = await worker.run_until_empty(max_batches=10)

    assert processed == 6
    assert processor.max_active_planners <= 2
    assert all(job.status == JOB_STATUS_SUCCEEDED for job in store.jobs_by_id.values())
    assert all(job.delivery_status == "delivered" for job in store.jobs_by_id.values())
    assert all(job.expected_value_messages == 2 for job in store.jobs_by_id.values())
    assert all(job.delivered_value_messages == 2 for job in store.jobs_by_id.values())
    assert {call[0] for call in store.calls} >= {
        "claim_next_queued_job",
        "set_expected_value_messages",
        "mark_send_started",
        "mark_value_message_delivered",
        "finish_success",
    }


@pytest.mark.anyio
async def test_worker_generates_from_persisted_snapshot() -> None:
    store = _InMemoryOneDayGenerationJobStore(default_quota=1)
    runtime = OneDayGenerationJobRuntime(store)
    snapshot = OneDayGenerationRequestSnapshot(
        request_kind="telegram_one_day",
        profile={"age": 44, "goal": "persisted"},
        recent_recipe_ids=("persisted-r001",),
        generation_seed="98765",
    )
    runtime.admit_queued(chat_id=42, idempotency_key="snapshot-job", request_snapshot=snapshot)
    processor = _RecordingProcessor()
    worker = OneDayGenerationWorker(
        runtime,
        processor,
        OneDayGenerationWorkerSettings(worker_id="worker-a", concurrency=1, max_attempts=3),
    )

    await worker.run_until_empty(max_batches=2)

    assert processor.snapshots == [snapshot]
    assert processor.snapshots[0].profile == {"age": 44, "goal": "persisted"}
    assert processor.snapshots[0].recent_recipe_ids == ("persisted-r001",)
    assert processor.snapshots[0].generation_seed == "98765"


@pytest.mark.anyio
async def test_worker_retries_pre_send_failure_then_refunds_once_after_max_attempts() -> None:
    store = _InMemoryOneDayGenerationJobStore(default_quota=1)
    runtime = OneDayGenerationJobRuntime(store)
    admitted = runtime.admit_queued(chat_id=77, idempotency_key="retry-job", request_snapshot=_snapshot(77)).job
    processor = _FailingProcessor(RuntimeError("planner temporarily failed"))
    worker = OneDayGenerationWorker(
        runtime,
        processor,
        OneDayGenerationWorkerSettings(
            worker_id="worker-a",
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
    assert failed.delivered_value_messages == 0
    assert store.quota_by_chat_id[77] == 1
    assert ("mark_retryable_failure", admitted.job_id) in store.calls
    assert ("finish_failure_and_refund_once", admitted.job_id) in store.calls


@pytest.mark.anyio
async def test_worker_partial_delivery_failure_requires_manual_review_without_refund() -> None:
    store = _InMemoryOneDayGenerationJobStore(default_quota=1)
    runtime = OneDayGenerationJobRuntime(store)
    admitted = runtime.admit_queued(chat_id=88, idempotency_key="partial-job", request_snapshot=_snapshot(88)).job
    processor = _RecordingProcessor(fail_value_key="summary:shopping")
    worker = OneDayGenerationWorker(
        runtime,
        processor,
        OneDayGenerationWorkerSettings(worker_id="worker-a", concurrency=1, max_attempts=1),
    )

    processed = await worker.run_once()
    failed = store.jobs_by_id[admitted.job_id]

    assert processed == 1
    assert failed.status == JOB_STATUS_FAILED
    assert failed.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert failed.delivery_status == "unknown"
    assert failed.requires_manual_review is True
    assert failed.delivered_value_messages == 1
    assert store.quota_by_chat_id[88] == 0
    assert ("mark_retryable_failure", admitted.job_id) not in store.calls


@pytest.mark.anyio
async def test_worker_run_forever_recovers_from_transient_claim_exception_and_shuts_down(caplog) -> None:
    class FlakyClaimStore(_InMemoryOneDayGenerationJobStore):
        def __init__(self) -> None:
            super().__init__(default_quota=1)
            self.claim_attempts = 0

        def claim_next_queued_job(self, **kwargs):
            self.claim_attempts += 1
            if self.claim_attempts == 1:
                raise RuntimeError("postgresql://user:secret@example/db transient outage")
            return super().claim_next_queued_job(**kwargs)

    store = FlakyClaimStore()
    runtime = OneDayGenerationJobRuntime(store)
    admitted = runtime.admit_queued(chat_id=99, idempotency_key="flaky-claim", request_snapshot=_snapshot(99)).job
    processor = _RecordingProcessor()
    worker = OneDayGenerationWorker(
        runtime,
        processor,
        OneDayGenerationWorkerSettings(
            worker_id="worker-a",
            concurrency=1,
            heartbeat_interval_seconds=3600,
            max_attempts=1,
            idle_sleep_seconds=0.01,
            error_backoff_seconds=0.01,
        ),
    )
    stop_event = asyncio.Event()
    caplog.set_level(logging.ERROR, logger="diet_bot.one_day_generation_job_runtime")

    task = asyncio.create_task(worker.run_forever(stop_event))
    try:
        for _ in range(100):
            if store.jobs_by_id[admitted.job_id].status == JOB_STATUS_SUCCEEDED:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("worker did not process the queued job after transient claim failure")
    finally:
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)

    assert store.claim_attempts >= 2
    assert store.jobs_by_id[admitted.job_id].status == JOB_STATUS_SUCCEEDED
    assert processor.sent_keys == [(99, "meal:00:breakfast"), (99, "summary:shopping")]
    assert "One-day worker iteration failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "postgresql://user:secret@example/db" not in caplog.text


@pytest.mark.anyio
async def test_worker_empty_delivery_refunds_before_failure_follow_up() -> None:
    store = _InMemoryOneDayGenerationJobStore(default_quota=1)
    runtime = OneDayGenerationJobRuntime(store)
    admitted = runtime.admit_queued(chat_id=111, idempotency_key="empty-delivery", request_snapshot=_snapshot(111)).job
    follow_ups: list[tuple[int, str, int]] = []
    worker = OneDayGenerationWorker(
        runtime,
        _EmptyDeliveryProcessor(store, follow_ups),
        OneDayGenerationWorkerSettings(worker_id="worker-a", concurrency=1, max_attempts=1),
    )

    processed = await worker.run_once()
    failed = store.jobs_by_id[admitted.job_id]

    assert processed == 1
    assert failed.status == JOB_STATUS_FAILED
    assert failed.refund_status == REFUND_STATUS_REFUNDED
    assert failed.failure_reason == "one_day_worker_empty_delivery"
    assert failed.send_started_at is None
    assert store.quota_by_chat_id[111] == 1
    assert follow_ups == [(111, REFUND_STATUS_REFUNDED, 1)]
    assert ("mark_send_started", admitted.job_id) not in store.calls


@pytest.mark.anyio
async def test_worker_empty_trial_delivery_resets_trial_before_failure_follow_up() -> None:
    store = _InMemoryOneDayGenerationJobStore(default_quota=0, consumption_source="free_trial")
    runtime = OneDayGenerationJobRuntime(store)
    admitted = runtime.admit_queued(chat_id=112, idempotency_key="empty-trial", request_snapshot=_snapshot(112)).job
    follow_ups: list[tuple[int, str, int]] = []
    worker = OneDayGenerationWorker(
        runtime,
        _EmptyDeliveryProcessor(store, follow_ups),
        OneDayGenerationWorkerSettings(worker_id="worker-a", concurrency=1, max_attempts=1),
    )

    processed = await worker.run_once()
    failed = store.jobs_by_id[admitted.job_id]

    assert processed == 1
    assert failed.status == JOB_STATUS_FAILED
    assert failed.refund_status == REFUND_STATUS_REFUNDED
    assert store.free_trial_used_by_chat_id[112] is False
    assert store.consumed_count_by_chat_id[112] == 1
    assert follow_ups == [(112, REFUND_STATUS_REFUNDED, 0)]
    assert ("mark_send_started", admitted.job_id) not in store.calls


@pytest.mark.anyio
async def test_synthetic_1000_user_rehearsal_accepts_dedupes_and_processes_with_bounded_concurrency() -> None:
    store = _InMemoryOneDayGenerationJobStore(default_quota=1)
    runtime = OneDayGenerationJobRuntime(store)
    accepted = 0
    duplicates = 0
    for chat_id in range(1, 1001):
        result = runtime.admit_queued(
            chat_id=chat_id,
            idempotency_key=f"mass:{chat_id}",
            request_snapshot=_snapshot(chat_id),
        )
        if result.status == QueuedJobAdmissionResultStatus.ADMITTED:
            accepted += 1
        duplicate = runtime.admit_queued(
            chat_id=chat_id,
            idempotency_key=f"mass:{chat_id}:duplicate",
            request_snapshot=_snapshot(chat_id),
        )
        if duplicate.status == QueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE:
            duplicates += 1

    processor = _RecordingProcessor(
        pre_send_failure_chat_ids={17},
        partial_failure_chat_ids={29},
        send_delay=0,
    )
    worker = OneDayGenerationWorker(
        runtime,
        processor,
        OneDayGenerationWorkerSettings(
            worker_id="worker-a",
            concurrency=5,
            retry_delay_seconds=0,
            max_attempts=1,
        ),
    )

    processed = await worker.run_until_empty(max_batches=300)
    jobs = list(store.jobs_by_id.values())
    pre_send_failure = store.job_by_chat_id[17]
    partial_failure = store.job_by_chat_id[29]

    assert accepted == 1000
    assert duplicates == 1000
    assert processed == 1000
    assert processor.max_active_planners <= 5
    assert sum(1 for job in jobs if job.status == JOB_STATUS_SUCCEEDED) == 998
    assert pre_send_failure.status == JOB_STATUS_FAILED
    assert pre_send_failure.refund_status == REFUND_STATUS_REFUNDED
    assert store.quota_by_chat_id[17] == 1
    assert partial_failure.status == JOB_STATUS_FAILED
    assert partial_failure.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert partial_failure.requires_manual_review is True
    assert store.quota_by_chat_id[29] == 0
    assert all(count == 1 for count in store.consumed_count_by_chat_id.values())
    assert all(job.chat_id == chat_id for chat_id, job in store.job_by_chat_id.items())


def test_postgres_startup_validation_validates_schema_without_initializing(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    fake_module = types.ModuleType("diet_bot.postgres_one_day_generation_job_store")

    class FakePostgresOneDayGenerationJobStore:
        def __init__(self, dsn: str, **_kwargs) -> None:
            calls.append(("construct", dsn))

        def initialize(self) -> None:
            calls.append(("initialize", None))
            raise AssertionError("startup validation must not auto-migrate")

        def validate_schema(self) -> None:
            calls.append(("validate_schema", None))

    fake_module.PostgresOneDayGenerationJobStore = FakePostgresOneDayGenerationJobStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", fake_module)

    validate_one_day_generation_job_store_for_startup(
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
    fake_module = types.ModuleType("diet_bot.postgres_one_day_generation_job_store")

    class FakePostgresOneDayGenerationJobStore:
        def __init__(self, _dsn: str, **_kwargs) -> None:
            pass

        def initialize(self) -> None:
            raise AssertionError("startup validation must not auto-migrate")

        def validate_schema(self) -> None:
            raise RuntimeError("missing one_day_generation_jobs")

    fake_module.PostgresOneDayGenerationJobStore = FakePostgresOneDayGenerationJobStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", fake_module)

    with pytest.raises(RuntimeError, match="run one-day generation job migrations before startup"):
        validate_one_day_generation_job_store_for_startup(
            type(
                "Config",
                (),
                {
                    "storage_backend": "postgres",
                    "database_url": "postgresql://user:secret@example/db",
                },
            )(),
        )


def _snapshot(chat_id: int) -> OneDayGenerationRequestSnapshot:
    return OneDayGenerationRequestSnapshot(
        request_kind="telegram_one_day",
        request_payload={"chat_id": chat_id, "recent_recipe_keys": [f"key-{chat_id}"]},
        profile={"age": 30 + chat_id % 10},
        recent_recipe_ids=(f"r{chat_id:03d}",),
        generation_seed=str(10_000 + chat_id),
    )


class _RecordingProcessor:
    def __init__(
        self,
        *,
        fail_value_key: str | None = None,
        pre_send_failure_chat_ids: set[int] | None = None,
        partial_failure_chat_ids: set[int] | None = None,
        send_delay: float | None = None,
    ) -> None:
        self.fail_value_key = fail_value_key
        self.pre_send_failure_chat_ids = pre_send_failure_chat_ids or set()
        self.partial_failure_chat_ids = partial_failure_chat_ids or set()
        self.send_delay = send_delay
        self.snapshots: list[OneDayGenerationRequestSnapshot] = []
        self.active_planners = 0
        self.max_active_planners = 0
        self.sent_keys: list[tuple[int, str]] = []

    async def prepare_delivery(self, job: OneDayGenerationJob) -> OneDayGenerationDelivery:
        assert job.request_snapshot is not None
        self.active_planners += 1
        self.max_active_planners = max(self.max_active_planners, self.active_planners)
        try:
            await asyncio.sleep(0)
            self.snapshots.append(job.request_snapshot)
            if job.chat_id in self.pre_send_failure_chat_ids:
                raise RuntimeError("injected planner failure")
            return OneDayGenerationDelivery(
                value_messages=(
                    OneDayGenerationValueMessage(
                        value_message_key="meal:00:breakfast",
                        send=lambda job=job: self._send(job.chat_id, "meal:00:breakfast"),
                    ),
                    OneDayGenerationValueMessage(
                        value_message_key="summary:shopping",
                        send=lambda job=job: self._send(job.chat_id, "summary:shopping"),
                    ),
                ),
            )
        finally:
            self.active_planners -= 1

    async def _send(self, chat_id: int, key: str) -> None:
        if self.send_delay is not None:
            await asyncio.sleep(self.send_delay)
        else:
            await asyncio.sleep(0)
        if key == self.fail_value_key or (chat_id in self.partial_failure_chat_ids and key == "summary:shopping"):
            raise RuntimeError("injected send failure")
        self.sent_keys.append((chat_id, key))


class _FailingProcessor:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def prepare_delivery(self, _job: OneDayGenerationJob) -> OneDayGenerationDelivery:
        raise self.exc


class _EmptyDeliveryProcessor:
    def __init__(self, store: "_InMemoryOneDayGenerationJobStore", follow_ups: list[tuple[int, str, int]]) -> None:
        self.store = store
        self.follow_ups = follow_ups

    async def prepare_delivery(self, job: OneDayGenerationJob) -> OneDayGenerationDelivery:
        async def follow_up() -> None:
            saved = self.store.jobs_by_id[job.job_id]
            self.follow_ups.append((job.chat_id, saved.refund_status, self.store.quota_by_chat_id.get(job.chat_id, 0)))

        return OneDayGenerationDelivery(value_messages=(), failure_follow_up=follow_up)


class _InMemoryOneDayGenerationJobStore:
    def __init__(self, *, default_quota: int, consumption_source: str = "monthly") -> None:
        self.default_quota = default_quota
        self.consumption_source = consumption_source
        self.jobs_by_id: dict[object, OneDayGenerationJob] = {}
        self.idempotency_index: dict[str, object] = {}
        self.job_by_chat_id: dict[int, OneDayGenerationJob] = {}
        self.quota_by_chat_id: dict[int, int] = {}
        self.free_trial_used_by_chat_id: dict[int, bool] = {}
        self.consumed_count_by_chat_id: dict[int, int] = {}
        self.calls: list[tuple[str, object]] = []

    def admit_queued_job(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        stale_after: datetime,
        request_snapshot: OneDayGenerationRequestSnapshot,
        metadata=None,
        now: datetime | None = None,
        test_access: bool = False,
        job_id=None,
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
        if not test_access and self.consumption_source == "free_trial":
            if self.free_trial_used_by_chat_id.get(chat_id, False):
                return QueuedJobAdmissionResult(
                    QueuedJobAdmissionResultStatus.DENIED,
                    None,
                    "one_day_entitlement_unavailable",
                )
            self.free_trial_used_by_chat_id[chat_id] = True
            self.consumed_count_by_chat_id[chat_id] = self.consumed_count_by_chat_id.get(chat_id, 0) + 1
            consumption_source = "free_trial"
            refund_status = REFUND_STATUS_PENDING
        elif not test_access:
            quota = self.quota_by_chat_id.setdefault(chat_id, self.default_quota)
            if quota <= 0:
                return QueuedJobAdmissionResult(
                    QueuedJobAdmissionResultStatus.DENIED,
                    None,
                    "one_day_entitlement_unavailable",
                )
            self.quota_by_chat_id[chat_id] = quota - 1
            self.consumed_count_by_chat_id[chat_id] = self.consumed_count_by_chat_id.get(chat_id, 0) + 1
            consumption_source = self.consumption_source
            refund_status = REFUND_STATUS_PENDING
        else:
            consumption_source = "test_access"
            refund_status = REFUND_STATUS_NOT_REQUIRED
        job = OneDayGenerationJob(
            job_id=job_id or uuid4(),
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            status=JOB_STATUS_QUEUED,
            consumption_source=consumption_source,
            refund_status=refund_status,
            delivery_status="not_started",
            expected_value_messages=0,
            delivered_value_messages=0,
            stale_after=stale_after,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
            request_snapshot=request_snapshot,
        )
        self.jobs_by_id[job.job_id] = job
        self.idempotency_index[idempotency_key] = job.job_id
        self.job_by_chat_id[chat_id] = job
        return QueuedJobAdmissionResult(QueuedJobAdmissionResultStatus.ADMITTED, job)

    def claim_next_queued_job(
        self,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime | None = None,
    ) -> ClaimQueuedJobResult:
        self.calls.append(("claim_next_queued_job", worker_id))
        for job in sorted(self.jobs_by_id.values(), key=lambda candidate: candidate.chat_id):
            if job.status != JOB_STATUS_QUEUED:
                continue
            if job.next_attempt_at is not None and now is not None and job.next_attempt_at > now:
                continue
            claimed = replace(
                job,
                status=JOB_STATUS_RUNNING,
                worker_id=worker_id,
                leased_until=lease_until,
                started_at=job.started_at or now,
                heartbeat_at=now,
                updated_at=now,
            )
            self._save(claimed)
            return ClaimQueuedJobResult(ClaimQueuedJobResultStatus.CLAIMED, claimed)
        return ClaimQueuedJobResult(ClaimQueuedJobResultStatus.EMPTY, None)

    def extend_lease(
        self,
        job_id,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime | None = None,
    ) -> ExtendLeaseResult:
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
        now: datetime | None = None,
    ) -> MarkRetryableFailureResult:
        self.calls.append(("mark_retryable_failure", job_id))
        job = self.jobs_by_id[job_id]
        if job.worker_id != worker_id:
            return MarkRetryableFailureResult(MarkRetryableFailureResultStatus.WORKER_MISMATCH, job)
        if job.send_started_at is not None or job.delivered_value_messages > 0:
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

    def set_expected_value_messages(
        self,
        job_id,
        expected_count: int,
        *,
        now: datetime | None = None,
    ) -> SetExpectedValueMessagesResult:
        self.calls.append(("set_expected_value_messages", job_id))
        job = self.jobs_by_id[job_id]
        updated = replace(job, expected_value_messages=expected_count, updated_at=now)
        self._save(updated)
        return SetExpectedValueMessagesResult(SetExpectedValueMessagesResultStatus.SET, updated)

    def mark_send_started(self, job_id, *, now: datetime | None = None) -> MarkSendStartedResult:
        self.calls.append(("mark_send_started", job_id))
        job = self.jobs_by_id[job_id]
        updated = replace(job, send_started_at=now, delivery_status="send_started", updated_at=now)
        self._save(updated)
        return MarkSendStartedResult(MarkSendStartedResultStatus.SEND_STARTED, updated)

    def mark_value_message_delivered(
        self,
        job_id,
        *,
        value_message_key: str,
        now: datetime | None = None,
    ) -> MarkValueMessageDeliveredResult:
        self.calls.append(("mark_value_message_delivered", job_id))
        job = self.jobs_by_id[job_id]
        delivered_count = job.delivered_value_messages + 1
        complete = delivered_count >= job.expected_value_messages
        updated = replace(
            job,
            delivered_value_messages=delivered_count,
            first_value_delivered_at=job.first_value_delivered_at or now,
            delivered_at=now if complete else job.delivered_at,
            delivery_status="delivered" if complete else "partial",
            updated_at=now,
        )
        self._save(updated)
        return MarkValueMessageDeliveredResult(MarkValueMessageDeliveredResultStatus.DELIVERED, updated)

    def finish_success(self, job_id, *, now: datetime | None = None) -> FinishJobResult:
        self.calls.append(("finish_success", job_id))
        job = self.jobs_by_id[job_id]
        updated = replace(
            job,
            status=JOB_STATUS_SUCCEEDED,
            refund_status=REFUND_STATUS_NOT_REQUIRED,
            delivery_status="delivered",
            finished_at=now,
            updated_at=now,
            requires_manual_review=False,
        )
        self._save(updated)
        return FinishJobResult(FinishJobResultStatus.SUCCEEDED, updated)

    def finish_failure_and_refund_once(
        self,
        job_id,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> FinishJobResult:
        self.calls.append(("finish_failure_and_refund_once", job_id))
        job = self.jobs_by_id[job_id]
        if job.delivered_value_messages > 0 or job.send_started_at is not None:
            updated = replace(
                job,
                status=JOB_STATUS_FAILED,
                refund_status=REFUND_STATUS_NOT_REQUIRED,
                delivery_status="unknown",
                finalization_error=reason,
                requires_manual_review=True,
                finished_at=now,
                updated_at=now,
            )
        else:
            refund_status = REFUND_STATUS_REFUNDED if job.refund_status == REFUND_STATUS_PENDING else REFUND_STATUS_NOT_REQUIRED
            if refund_status == REFUND_STATUS_REFUNDED:
                if job.consumption_source == "free_trial":
                    self.free_trial_used_by_chat_id[job.chat_id] = False
                else:
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

    def _save(self, job: OneDayGenerationJob) -> None:
        self.jobs_by_id[job.job_id] = job
        self.job_by_chat_id[job.chat_id] = job
