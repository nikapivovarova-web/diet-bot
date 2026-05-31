from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from diet_bot.sales_followup_runtime import (
    ClaimSalesFollowupJobResult,
    ClaimSalesFollowupJobResultStatus,
    SalesFollowupEligibility,
    SalesFollowupJobRuntime,
    SalesFollowupJobTransitionResult,
    SalesFollowupJobTransitionStatus,
    SalesFollowupPermanentSendError,
    SalesFollowupSendRequest,
    SalesFollowupSendResult,
    SalesFollowupTransientSendError,
    SalesFollowupUnknownSendOutcome,
    SalesFollowupWorker,
    SalesFollowupWorkerSettings,
)


NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
CHAIN_ID = UUID("11111111-1111-1111-1111-111111111111")
JOB_ID = UUID("22222222-2222-2222-2222-222222222222")
FUTURE_JOB_ID = UUID("33333333-3333-3333-3333-333333333333")


@dataclass(frozen=True)
class _Job:
    job_id: UUID
    chain_id: UUID
    chat_id: int
    campaign_key: str
    step_key: str
    step_index: int
    scheduled_at: datetime
    next_attempt_at: datetime
    status: str = "queued"
    payload: dict[str, object] | None = None
    send_started_at: datetime | None = None
    sent_at: datetime | None = None
    telegram_message_id: int | None = None
    skipped_at: datetime | None = None
    finished_at: datetime | None = None
    skip_reason: str | None = None
    failure_reason: str | None = None
    last_error: str | None = None
    worker_id: str | None = None
    leased_until: datetime | None = None
    attempt_count: int = 0
    heartbeat_at: datetime | None = None

    def __post_init__(self) -> None:
        payload = self.payload or {
            "message_text": "mock sales follow-up",
            "button_label": "Open",
            "target_callback_data": "diet:week_pdf",
        }
        object.__setattr__(self, "payload", dict(payload))


class _FakeSalesFollowupStore:
    def __init__(self, jobs: list[_Job], *, campaign_enabled: bool = True, opted_out: bool = False) -> None:
        self.jobs = {job.job_id: job for job in jobs}
        self.chain_status = {job.chain_id: "active" for job in jobs}
        self.campaigns = {
            "free_trial_v1": SimpleNamespace(campaign_key="free_trial_v1", enabled=campaign_enabled),
        }
        self.preferences = (
            {jobs[0].chat_id: SimpleNamespace(opted_out_at=NOW, opt_out_source="unit_test")}
            if opted_out and jobs
            else {}
        )
        self.calls: list[tuple[object, ...]] = []

    def get_campaign(self, campaign_key: str):
        return self.campaigns.get(campaign_key)

    def get_preference(self, chat_id: int):
        return self.preferences.get(int(chat_id))

    def claim_next_due_job(self, *, worker_id: str, lease_until: datetime, now: datetime | None = None):
        current_time = now or NOW
        self.calls.append(("claim_next_due_job", worker_id))
        candidates: list[_Job] = []
        for job in self.jobs.values():
            if self.chain_status.get(job.chain_id) != "active":
                continue
            if self._has_unfinished_earlier_job(job):
                continue
            queued_due = (
                job.status == "queued"
                and job.scheduled_at <= current_time
                and job.next_attempt_at <= current_time
            )
            reclaimable = (
                job.status == "running"
                and job.leased_until is not None
                and job.leased_until <= current_time
                and job.send_started_at is None
                and job.sent_at is None
            )
            if queued_due or reclaimable:
                candidates.append(job)
        if not candidates:
            return ClaimSalesFollowupJobResult(ClaimSalesFollowupJobResultStatus.EMPTY, None)
        candidate = sorted(candidates, key=lambda item: (item.next_attempt_at, item.scheduled_at, item.step_index))[0]
        claimed = replace(
            candidate,
            status="running",
            worker_id=worker_id,
            leased_until=lease_until,
            heartbeat_at=current_time,
        )
        self.jobs[claimed.job_id] = claimed
        return ClaimSalesFollowupJobResult(ClaimSalesFollowupJobResultStatus.CLAIMED, claimed)

    def extend_lease(self, job_id, *, worker_id: str, lease_until: datetime, now: datetime | None = None):
        job = self.jobs[job_id]
        if job.worker_id != worker_id:
            return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
        updated = replace(job, leased_until=lease_until, heartbeat_at=now or NOW)
        self.jobs[job_id] = updated
        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def mark_send_started(self, job_id, *, worker_id: str, now: datetime | None = None):
        job = self.jobs[job_id]
        if job.worker_id != worker_id:
            return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
        updated = replace(job, send_started_at=now or NOW)
        self.jobs[job_id] = updated
        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def mark_sent(self, job_id, *, worker_id: str, telegram_message_id: int | None, now: datetime | None = None):
        job = self.jobs[job_id]
        if job.worker_id != worker_id:
            return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
        updated = replace(
            job,
            status="sent",
            sent_at=now or NOW,
            finished_at=now or NOW,
            telegram_message_id=telegram_message_id,
            worker_id=None,
            leased_until=None,
        )
        self.jobs[job_id] = updated
        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def mark_retryable_failure(
        self,
        job_id,
        *,
        worker_id: str,
        error: str | None,
        next_attempt_at: datetime,
        now: datetime | None = None,
    ):
        job = self.jobs[job_id]
        if job.worker_id != worker_id:
            return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
        updated = replace(
            job,
            status="queued",
            worker_id=None,
            leased_until=None,
            next_attempt_at=next_attempt_at,
            attempt_count=job.attempt_count + 1,
            send_started_at=None,
            last_error=error,
        )
        self.jobs[job_id] = updated
        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def mark_failed(self, job_id, *, worker_id: str, reason: str | None, now: datetime | None = None):
        job = self.jobs[job_id]
        updated = replace(
            job,
            status="failed",
            worker_id=None,
            leased_until=None,
            finished_at=now or NOW,
            failure_reason=reason,
        )
        self.jobs[job_id] = updated
        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def mark_unknown(self, job_id, *, worker_id: str, error: str | None, now: datetime | None = None):
        job = self.jobs[job_id]
        updated = replace(
            job,
            status="unknown",
            worker_id=None,
            leased_until=None,
            finished_at=now or NOW,
            last_error=error,
        )
        self.jobs[job_id] = updated
        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def skip_job_and_cancel_chain(
        self,
        job_id,
        *,
        worker_id: str,
        reason: str,
        chain_status: str = "cancelled",
        now: datetime | None = None,
    ):
        job = self.jobs[job_id]
        current_time = now or NOW
        updated = replace(
            job,
            status="skipped",
            worker_id=None,
            leased_until=None,
            skipped_at=current_time,
            finished_at=current_time,
            skip_reason=reason,
        )
        self.jobs[job_id] = updated
        self.chain_status[job.chain_id] = chain_status
        for other in list(self.jobs.values()):
            if other.chain_id == job.chain_id and other.step_index > job.step_index and other.status == "queued":
                self.jobs[other.job_id] = replace(
                    other,
                    status="cancelled",
                    skipped_at=current_time,
                    finished_at=current_time,
                    skip_reason=reason,
                )
        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def _has_unfinished_earlier_job(self, job: _Job) -> bool:
        return any(
            other.chain_id == job.chain_id
            and other.step_index < job.step_index
            and other.status in {"queued", "running"}
            for other in self.jobs.values()
        )


class _FakeSender:
    def __init__(self, result: SalesFollowupSendResult | Exception | None = None, *, delay: float = 0) -> None:
        self.result = result or SalesFollowupSendResult(telegram_message_id=901)
        self.delay = delay
        self.requests: list[SalesFollowupSendRequest] = []

    async def send(self, request: SalesFollowupSendRequest) -> SalesFollowupSendResult:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _job(
    *,
    job_id: UUID = JOB_ID,
    scheduled_at: datetime = NOW - timedelta(minutes=1),
    next_attempt_at: datetime | None = None,
    status: str = "queued",
    worker_id: str | None = None,
    leased_until: datetime | None = None,
    send_started_at: datetime | None = None,
    attempt_count: int = 0,
) -> _Job:
    return _Job(
        job_id=job_id,
        chain_id=CHAIN_ID,
        chat_id=4242,
        campaign_key="free_trial_v1",
        step_key="m01_two_hours",
        step_index=1,
        scheduled_at=scheduled_at,
        next_attempt_at=next_attempt_at or scheduled_at,
        status=status,
        worker_id=worker_id,
        leased_until=leased_until,
        send_started_at=send_started_at,
        attempt_count=attempt_count,
    )


def _future_job() -> _Job:
    return _Job(
        job_id=FUTURE_JOB_ID,
        chain_id=CHAIN_ID,
        chat_id=4242,
        campaign_key="free_trial_v1",
        step_key="m02_one_day",
        step_index=2,
        scheduled_at=NOW + timedelta(days=1),
        next_attempt_at=NOW + timedelta(days=1),
    )


def _run(coro):
    return asyncio.run(coro)


def _worker(
    store: _FakeSalesFollowupStore,
    sender: _FakeSender,
    *,
    eligibility_checker=None,
    max_attempts: int = 3,
) -> SalesFollowupWorker:
    runtime = SalesFollowupJobRuntime(store, now=lambda: NOW)
    return SalesFollowupWorker(
        runtime,
        sender,
        eligibility_checker=eligibility_checker,
        settings=SalesFollowupWorkerSettings(
            worker_id="worker-a",
            concurrency=1,
            lease_seconds=300,
            heartbeat_interval_seconds=3600,
            retry_delay_seconds=60,
            max_attempts=max_attempts,
        ),
    )


def test_worker_claims_due_queued_job_and_marks_mocked_send_success() -> None:
    store = _FakeSalesFollowupStore([_job()])
    sender = _FakeSender(SalesFollowupSendResult(telegram_message_id=777))
    worker = _worker(store, sender)

    processed = _run(worker.run_once())

    assert processed == 1
    assert len(sender.requests) == 1
    assert sender.requests[0].chat_id == 4242
    saved = store.jobs[JOB_ID]
    assert saved.status == "sent"
    assert saved.send_started_at == NOW
    assert saved.sent_at == NOW
    assert saved.finished_at == NOW
    assert saved.telegram_message_id == 777


def test_worker_does_not_claim_future_job() -> None:
    store = _FakeSalesFollowupStore([_job(scheduled_at=NOW + timedelta(hours=2))])
    sender = _FakeSender()
    worker = _worker(store, sender)

    processed = _run(worker.run_once())

    assert processed == 0
    assert sender.requests == []
    assert store.jobs[JOB_ID].status == "queued"


def test_worker_skips_and_cancels_when_campaign_is_disabled() -> None:
    store = _FakeSalesFollowupStore([_job(), _future_job()], campaign_enabled=False)
    sender = _FakeSender()
    worker = _worker(store, sender)

    processed = _run(worker.run_once())

    assert processed == 1
    assert sender.requests == []
    assert store.jobs[JOB_ID].status == "skipped"
    assert store.jobs[JOB_ID].skip_reason == "campaign_disabled"
    assert store.jobs[FUTURE_JOB_ID].status == "cancelled"
    assert store.chain_status[CHAIN_ID] == "cancelled"


def test_worker_skips_and_cancels_when_paid_access_is_active() -> None:
    store = _FakeSalesFollowupStore([_job(), _future_job()])
    sender = _FakeSender()
    worker = _worker(
        store,
        sender,
        eligibility_checker=lambda job: SalesFollowupEligibility(False, "active_paid_access"),
    )

    _run(worker.run_once())

    assert sender.requests == []
    assert store.jobs[JOB_ID].status == "skipped"
    assert store.jobs[JOB_ID].skip_reason == "active_paid_access"
    assert store.jobs[FUTURE_JOB_ID].status == "cancelled"


def test_worker_skips_and_cancels_when_weekly_pdf_access_exists() -> None:
    store = _FakeSalesFollowupStore([_job(), _future_job()])
    sender = _FakeSender()
    worker = _worker(
        store,
        sender,
        eligibility_checker=lambda job: SalesFollowupEligibility(False, "weekly_pdf_access"),
    )

    _run(worker.run_once())

    assert sender.requests == []
    assert store.jobs[JOB_ID].status == "skipped"
    assert store.jobs[JOB_ID].skip_reason == "weekly_pdf_access"
    assert store.jobs[FUTURE_JOB_ID].status == "cancelled"


def test_worker_skips_and_cancels_when_chat_is_not_private() -> None:
    store = _FakeSalesFollowupStore([_job(), _future_job()])
    sender = _FakeSender()
    worker = _worker(
        store,
        sender,
        eligibility_checker=lambda job: SalesFollowupEligibility(False, "non_private_chat"),
    )

    _run(worker.run_once())

    assert sender.requests == []
    assert store.jobs[JOB_ID].status == "skipped"
    assert store.jobs[JOB_ID].skip_reason == "non_private_chat"
    assert store.jobs[FUTURE_JOB_ID].status == "cancelled"


def test_worker_skips_and_cancels_opted_out_chat() -> None:
    store = _FakeSalesFollowupStore([_job(), _future_job()], opted_out=True)
    sender = _FakeSender()
    worker = _worker(store, sender)

    _run(worker.run_once())

    assert sender.requests == []
    assert store.jobs[JOB_ID].status == "skipped"
    assert store.jobs[JOB_ID].skip_reason == "opted_out"
    assert store.jobs[FUTURE_JOB_ID].status == "cancelled"
    assert store.chain_status[CHAIN_ID] == "opted_out"


def test_worker_requeues_transient_send_failure_with_bounded_retry_time() -> None:
    store = _FakeSalesFollowupStore([_job()])
    sender = _FakeSender(SalesFollowupTransientSendError("retry later"))
    worker = _worker(store, sender)

    _run(worker.run_once())

    saved = store.jobs[JOB_ID]
    assert len(sender.requests) == 1
    assert saved.status == "queued"
    assert saved.next_attempt_at == NOW + timedelta(seconds=60)
    assert saved.attempt_count == 1
    assert saved.send_started_at is None
    assert saved.last_error == "SalesFollowupTransientSendError"


def test_worker_suppresses_chain_on_permanent_send_failure() -> None:
    store = _FakeSalesFollowupStore([_job(), _future_job()])
    sender = _FakeSender(SalesFollowupPermanentSendError("bot blocked"))
    worker = _worker(store, sender)

    _run(worker.run_once())

    assert len(sender.requests) == 1
    assert store.jobs[JOB_ID].status == "skipped"
    assert store.jobs[JOB_ID].skip_reason == "permanent_send_failure"
    assert store.jobs[FUTURE_JOB_ID].status == "cancelled"
    assert store.chain_status[CHAIN_ID] == "suppressed"


def test_worker_marks_unknown_send_outcome_for_manual_review_without_retry() -> None:
    store = _FakeSalesFollowupStore([_job()])
    sender = _FakeSender(SalesFollowupUnknownSendOutcome("connection lost after send"))
    worker = _worker(store, sender)

    _run(worker.run_once())

    saved = store.jobs[JOB_ID]
    assert len(sender.requests) == 1
    assert saved.status == "unknown"
    assert saved.finished_at == NOW
    assert saved.last_error == "SalesFollowupUnknownSendOutcome"
    assert saved.attempt_count == 0


def test_worker_reclaims_expired_running_lease_before_send_started() -> None:
    store = _FakeSalesFollowupStore(
        [
            _job(
                status="running",
                worker_id="old-worker",
                leased_until=NOW - timedelta(seconds=1),
            )
        ]
    )
    sender = _FakeSender()
    worker = _worker(store, sender)

    _run(worker.run_once())

    assert len(sender.requests) == 1
    assert store.jobs[JOB_ID].status == "sent"


def test_duplicate_workers_do_not_send_same_job_twice() -> None:
    store = _FakeSalesFollowupStore([_job()])
    sender = _FakeSender(delay=0.01)
    runtime = SalesFollowupJobRuntime(store, now=lambda: NOW)
    worker_a = SalesFollowupWorker(
        runtime,
        sender,
        settings=SalesFollowupWorkerSettings(worker_id="worker-a", heartbeat_interval_seconds=3600),
    )
    worker_b = SalesFollowupWorker(
        runtime,
        sender,
        settings=SalesFollowupWorkerSettings(worker_id="worker-b", heartbeat_interval_seconds=3600),
    )

    async def run_both():
        return await asyncio.gather(worker_a.run_once(), worker_b.run_once())

    processed = _run(run_both())

    assert sorted(processed) == [0, 1]
    assert len(sender.requests) == 1
    assert store.jobs[JOB_ID].telegram_message_id == 901


def test_worker_marks_failed_when_max_attempts_are_exhausted() -> None:
    store = _FakeSalesFollowupStore([_job(attempt_count=2)])
    sender = _FakeSender(SalesFollowupTransientSendError("retry later"))
    worker = _worker(store, sender, max_attempts=3)

    _run(worker.run_once())

    saved = store.jobs[JOB_ID]
    assert saved.status == "failed"
    assert saved.failure_reason == "sales_followup_worker_failed"
    assert saved.attempt_count == 2
