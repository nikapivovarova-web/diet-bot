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
    MarkDeliveredResult,
    MarkDeliveredResultStatus,
    MarkSendStartedResult,
    MarkSendStartedResultStatus,
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


def test_job_tracks_delivery_and_finalization_fields() -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    delivered_at = now + timedelta(seconds=10)
    send_started_at = now + timedelta(seconds=3)

    job = WeeklyPdfJob(
        job_id=uuid4(),
        chat_id=123,
        idempotency_key="idem-123",
        status=JOB_STATUS_SUCCEEDED,
        refund_status=REFUND_STATUS_NOT_REQUIRED,
        consumption_source="monthly",
        stale_after=now + timedelta(minutes=15),
        send_started_at=send_started_at,
        delivered_at=delivered_at,
        finalization_error="stale_after_delivery",
        delivery_status="delivered",
    )

    assert job.send_started_at == send_started_at
    assert job.delivered_at == delivered_at
    assert job.finalization_error == "stale_after_delivery"
    assert job.delivery_status == "delivered"
    assert job.requires_manual_review is False
    assert job.manual_review_reason is None


def test_job_defaults_to_not_started_delivery_without_manual_review() -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)

    job = _job(status=JOB_STATUS_QUEUED, now=now)

    assert job.delivery_status == "not_started"
    assert job.requires_manual_review is False
    assert job.manual_review_reason is None
    assert job.manual_reviewed_at is None
    assert job.manual_review_resolution is None


def test_result_wrappers_expose_explicit_statuses() -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    job = _job(status=JOB_STATUS_QUEUED, now=now)

    admit = AdmitJobResult(AdmitJobResultStatus.ADMITTED, job)
    start = StartJobResult(StartJobResultStatus.ALREADY_RUNNING, job)
    finish = FinishJobResult(FinishJobResultStatus.INVALID_STATE, job)
    delivered = MarkDeliveredResult(MarkDeliveredResultStatus.DELIVERED, job)
    send_started = MarkSendStartedResult(MarkSendStartedResultStatus.SEND_STARTED, job)
    cleanup = CleanupStaleResult([finish])

    assert admit.status.value == "admitted"
    assert start.status.value == "already_running"
    assert finish.status.value == "invalid_state"
    assert delivered.status.value == "delivered"
    assert send_started.status.value == "send_started"
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
