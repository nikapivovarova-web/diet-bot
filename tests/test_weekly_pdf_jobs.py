from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diet_bot.weekly_pdf_jobs import (
    AdmitJobResult,
    AdmitJobResultStatus,
    CleanupStaleResult,
    FinishJobResult,
    FinishJobResultStatus,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    StartJobResult,
    StartJobResultStatus,
    WeeklyPdfJob,
    refund_status_for_consumption_source,
)


def test_active_statuses_are_queued_and_running_only() -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)

    queued = _job(status=JOB_STATUS_QUEUED, now=now)
    running = _job(status=JOB_STATUS_RUNNING, now=now)
    succeeded = _job(status=JOB_STATUS_SUCCEEDED, now=now)
    failed = _job(status=JOB_STATUS_FAILED, now=now)
    cancelled = _job(status=JOB_STATUS_CANCELLED, now=now)

    assert queued.is_active
    assert running.is_active
    assert not succeeded.is_active
    assert not failed.is_active
    assert not cancelled.is_active


@pytest.mark.parametrize("source", ["monthly", "extra"])
def test_refundable_consumption_sources_start_pending_refund(source: str) -> None:
    assert refund_status_for_consumption_source(source) == REFUND_STATUS_PENDING


@pytest.mark.parametrize("source", [None, "test_access"])
def test_non_quota_consumption_sources_do_not_require_refund(source: str | None) -> None:
    assert refund_status_for_consumption_source(source) == REFUND_STATUS_NOT_REQUIRED


def test_job_metadata_is_copied_on_creation() -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    metadata = {"request_id": "weekly-1"}

    job = _job(status=JOB_STATUS_QUEUED, now=now, metadata=metadata)
    metadata["request_id"] = "mutated"

    assert job.metadata == {"request_id": "weekly-1"}


def test_result_wrappers_expose_explicit_statuses() -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    job = _job(status=JOB_STATUS_QUEUED, now=now)

    admit = AdmitJobResult(AdmitJobResultStatus.ADMITTED, job)
    start = StartJobResult(StartJobResultStatus.ALREADY_RUNNING, job)
    finish = FinishJobResult(FinishJobResultStatus.INVALID_STATE, job)
    cleanup = CleanupStaleResult([finish])

    assert admit.status.value == "admitted"
    assert start.status.value == "already_running"
    assert finish.status.value == "invalid_state"
    assert cleanup.jobs == [job]


def _job(
    *,
    status: str,
    now: datetime,
    metadata: dict[str, object] | None = None,
) -> WeeklyPdfJob:
    return WeeklyPdfJob(
        job_id=uuid4(),
        chat_id=123,
        idempotency_key="idem-123",
        status=status,
        refund_status=REFUND_STATUS_NOT_REQUIRED,
        consumption_source=None,
        stale_after=now + timedelta(minutes=15),
        metadata=metadata or {},
        created_at=now,
        updated_at=now,
    )
