from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Protocol
from uuid import UUID

from .log_redaction import redact_identifier
from .weekly_pdf_jobs import (
    AdmitJobResult,
    ClaimQueuedJobResult,
    ClaimQueuedJobResultStatus,
    CleanupStaleResult,
    ExtendLeaseResult,
    ExtendLeaseResultStatus,
    FinishJobResult,
    MarkDeliveredResult,
    MarkDeliveredResultStatus,
    MarkRetryableFailureResult,
    MarkRetryableFailureResultStatus,
    MarkSendStartedResult,
    MarkSendStartedResultStatus,
    QueuedJobAdmissionResult,
    StartJobResult,
    WeeklyPdfJob,
    WeeklyPdfRequestSnapshot,
)


DEFAULT_WEEKLY_PDF_JOB_STALE_AFTER_SECONDS = 30 * 60
DEFAULT_WEEKLY_PDF_JOB_CLEANUP_LIMIT = 10
DEFAULT_WEEKLY_PDF_WORKER_CONCURRENCY = 1
DEFAULT_WEEKLY_PDF_WORKER_LEASE_SECONDS = 5 * 60
DEFAULT_WEEKLY_PDF_WORKER_HEARTBEAT_SECONDS = 60
DEFAULT_WEEKLY_PDF_WORKER_RETRY_DELAY_SECONDS = 30
DEFAULT_WEEKLY_PDF_WORKER_MAX_ATTEMPTS = 3
DEFAULT_WEEKLY_PDF_WORKER_IDLE_SLEEP_SECONDS = 1.0
DEFAULT_WEEKLY_PDF_WORKER_ERROR_BACKOFF_SECONDS = 5.0
DEFAULT_WEEKLY_PDF_WORKER_JOB_TIMEOUT_SECONDS = 15 * 60

logger = logging.getLogger(__name__)


class WeeklyPdfJobStore(Protocol):
    def admit_job(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        stale_after: datetime,
        metadata: Mapping[str, Any] | None = None,
    ) -> AdmitJobResult: ...

    def admit_queued_job(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        stale_after: datetime,
        request_snapshot: WeeklyPdfRequestSnapshot,
        metadata: Mapping[str, Any] | None = None,
        now: datetime | None = None,
        test_access: bool = False,
        job_id: UUID | str | None = None,
    ) -> QueuedJobAdmissionResult: ...

    def claim_next_queued_job(
        self,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime | None = None,
    ) -> ClaimQueuedJobResult: ...

    def extend_lease(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime | None = None,
    ) -> ExtendLeaseResult: ...

    def mark_retryable_failure(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        error: str | None,
        next_attempt_at: datetime,
        now: datetime | None = None,
    ) -> MarkRetryableFailureResult: ...

    def start_job_and_consume(
        self,
        job_id: UUID | str,
        *,
        now: datetime | None = None,
        stale_after: datetime | None = None,
        test_access: bool = False,
    ) -> StartJobResult: ...

    def finish_success(self, job_id: UUID | str, *, now: datetime | None = None) -> FinishJobResult: ...

    def mark_delivered(self, job_id: UUID | str, *, now: datetime | None = None) -> MarkDeliveredResult: ...

    def mark_send_started(self, job_id: UUID | str, *, now: datetime | None = None) -> MarkSendStartedResult: ...

    def finish_failure_and_refund_once(
        self,
        job_id: UUID | str,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> FinishJobResult: ...

    def cancel_queued(
        self,
        job_id: UUID | str,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> FinishJobResult: ...

    def cleanup_stale(
        self,
        *,
        chat_id: int,
        now: datetime | None = None,
        limit: int = DEFAULT_WEEKLY_PDF_JOB_CLEANUP_LIMIT,
    ) -> CleanupStaleResult: ...


WeeklyPdfSendStartedCallback = Callable[[], None]
WeeklyPdfDeliveredCallback = Callable[[], None]


@dataclass(frozen=True)
class WeeklyPdfDelivery:
    send: Callable[[WeeklyPdfSendStartedCallback, WeeklyPdfDeliveredCallback], Awaitable[bool]]
    after_success: Callable[[], Awaitable[None]] | None = None
    failure_follow_up: Callable[[], Awaitable[None]] | None = None


class WeeklyPdfJobProcessor(Protocol):
    async def prepare_delivery(self, job: WeeklyPdfJob) -> WeeklyPdfDelivery: ...


@dataclass(frozen=True)
class WeeklyPdfWorkerSettings:
    worker_id: str = "weekly-pdf-worker"
    concurrency: int = DEFAULT_WEEKLY_PDF_WORKER_CONCURRENCY
    lease_seconds: int = DEFAULT_WEEKLY_PDF_WORKER_LEASE_SECONDS
    heartbeat_interval_seconds: int = DEFAULT_WEEKLY_PDF_WORKER_HEARTBEAT_SECONDS
    retry_delay_seconds: int = DEFAULT_WEEKLY_PDF_WORKER_RETRY_DELAY_SECONDS
    max_attempts: int = DEFAULT_WEEKLY_PDF_WORKER_MAX_ATTEMPTS
    idle_sleep_seconds: float = DEFAULT_WEEKLY_PDF_WORKER_IDLE_SLEEP_SECONDS
    error_backoff_seconds: float = DEFAULT_WEEKLY_PDF_WORKER_ERROR_BACKOFF_SECONDS
    job_timeout_seconds: float = DEFAULT_WEEKLY_PDF_WORKER_JOB_TIMEOUT_SECONDS

    @classmethod
    def from_config(cls, config: object, *, worker_id: str | None = None) -> "WeeklyPdfWorkerSettings":
        return cls(
            worker_id=worker_id or str(getattr(config, "weekly_pdf_worker_id", None) or "weekly-pdf-worker"),
            concurrency=max(1, int(getattr(config, "weekly_pdf_worker_concurrency", cls.concurrency))),
            lease_seconds=max(1, int(getattr(config, "weekly_pdf_worker_lease_seconds", cls.lease_seconds))),
            heartbeat_interval_seconds=max(
                1,
                int(getattr(config, "weekly_pdf_worker_heartbeat_seconds", cls.heartbeat_interval_seconds)),
            ),
            retry_delay_seconds=max(
                0,
                int(getattr(config, "weekly_pdf_worker_retry_delay_seconds", cls.retry_delay_seconds)),
            ),
            max_attempts=max(1, int(getattr(config, "weekly_pdf_worker_max_attempts", cls.max_attempts))),
            idle_sleep_seconds=max(
                0.1,
                float(getattr(config, "weekly_pdf_worker_idle_sleep_seconds", cls.idle_sleep_seconds)),
            ),
            error_backoff_seconds=max(
                0.1,
                float(getattr(config, "weekly_pdf_worker_error_backoff_seconds", cls.error_backoff_seconds)),
            ),
            job_timeout_seconds=max(
                0.001,
                float(getattr(config, "weekly_pdf_worker_job_timeout_seconds", cls.job_timeout_seconds)),
            ),
        )


class WeeklyPdfWorker:
    def __init__(
        self,
        runtime: "WeeklyPdfJobRuntime",
        processor: WeeklyPdfJobProcessor,
        settings: WeeklyPdfWorkerSettings | None = None,
    ) -> None:
        self.runtime = runtime
        self.processor = processor
        self.settings = settings or WeeklyPdfWorkerSettings()

    async def run_once(self) -> int:
        claimed_jobs: list[WeeklyPdfJob] = []
        for _ in range(max(1, int(self.settings.concurrency))):
            claim = self.runtime.claim_next_queued_job(
                worker_id=self.settings.worker_id,
                lease_seconds=self.settings.lease_seconds,
            )
            if claim.status == ClaimQueuedJobResultStatus.EMPTY:
                break
            if claim.status == ClaimQueuedJobResultStatus.CLAIMED and claim.job is not None:
                claimed_jobs.append(claim.job)
                continue
            break

        if not claimed_jobs:
            return 0

        await asyncio.gather(*(self._process_claimed_job(job) for job in claimed_jobs))
        return len(claimed_jobs)

    async def run_until_empty(self, *, max_batches: int = 100) -> int:
        processed = 0
        for _ in range(max(1, int(max_batches))):
            batch_count = await self.run_once()
            if batch_count == 0:
                break
            processed += batch_count
        return processed

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            try:
                processed = await self.run_once()
            except Exception as exc:
                backoff_seconds = max(0.1, float(self.settings.error_backoff_seconds))
                logger.error(
                    "Weekly PDF worker iteration failed; worker_id=%s error_type=%s backoff_seconds=%.3f",
                    self.settings.worker_id,
                    type(exc).__name__,
                    backoff_seconds,
                )
                await self._sleep_or_stop(stop_event, backoff_seconds)
                continue
            if processed:
                continue
            await self._sleep_or_stop(stop_event, self.settings.idle_sleep_seconds)

    async def _sleep_or_stop(self, stop_event: asyncio.Event | None, seconds: float) -> None:
        delay_seconds = max(0.1, float(seconds))
        try:
            if stop_event is None:
                await asyncio.sleep(delay_seconds)
            else:
                await asyncio.wait_for(stop_event.wait(), timeout=delay_seconds)
        except TimeoutError:
            return

    async def _process_claimed_job(self, job: WeeklyPdfJob) -> None:
        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(self._heartbeat_until_stopped(job.job_id, stop_heartbeat))
        send_started = False
        delivered = False

        def mark_send_started() -> None:
            nonlocal send_started
            self._require_send_started(self.runtime.mark_send_started(job.job_id))
            send_started = True

        def mark_delivered() -> None:
            nonlocal delivered
            self._require_delivered(self.runtime.mark_delivered(job.job_id))
            delivered = True

        async def process_job() -> None:
            if job.request_snapshot is None:
                self.runtime.finish_failure_and_refund_once(job.job_id, reason="weekly_pdf_worker_missing_snapshot")
                return

            delivery = await self.processor.prepare_delivery(job)
            sent = await delivery.send(mark_send_started, mark_delivered)
            if not sent:
                self._handle_processing_failure(
                    job,
                    RuntimeError("weekly_pdf_worker_not_sent"),
                    send_started=send_started,
                    delivered=delivered,
                )
                await self._send_failure_follow_up(job, delivery.failure_follow_up)
                return

            self._require_success(self.runtime.finish_success(job.job_id))
            if delivery.after_success is not None:
                try:
                    await delivery.after_success()
                except Exception:
                    logger.exception("Weekly PDF post-success callback failed for chat_id=%s", job.chat_id)

        try:
            await asyncio.wait_for(
                process_job(),
                timeout=max(0.001, float(self.settings.job_timeout_seconds)),
            )
        except TimeoutError as exc:
            logger.error(
                "Weekly PDF worker job timed out; worker_id=%s job_id=%s timeout_seconds=%.3f",
                self.settings.worker_id,
                redact_identifier("job", job.job_id),
                max(0.001, float(self.settings.job_timeout_seconds)),
            )
            self._handle_processing_failure(job, exc, send_started=send_started, delivered=delivered)
        except Exception as exc:
            self._handle_processing_failure(job, exc, send_started=send_started, delivered=delivered)
        finally:
            stop_heartbeat.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _heartbeat_until_stopped(self, job_id: UUID | str, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=max(1, int(self.settings.heartbeat_interval_seconds)),
                )
                return
            except TimeoutError:
                try:
                    result = self.runtime.extend_lease(
                        job_id,
                        worker_id=self.settings.worker_id,
                        lease_seconds=self.settings.lease_seconds,
                    )
                except Exception as exc:
                    logger.error(
                        "Weekly PDF worker lease extension failed; worker_id=%s job_id=%s error_type=%s",
                        self.settings.worker_id,
                        redact_identifier("job", job_id),
                        type(exc).__name__,
                    )
                    continue
                if result.status != ExtendLeaseResultStatus.EXTENDED:
                    logger.warning(
                        "Weekly PDF worker lease extension did not extend worker_id=%s job_id=%s status=%s",
                        self.settings.worker_id,
                        redact_identifier("job", job_id),
                        result.status.value,
                    )

    async def _send_failure_follow_up(
        self,
        job: WeeklyPdfJob,
        follow_up: Callable[[], Awaitable[None]] | None,
    ) -> None:
        if follow_up is None:
            return
        try:
            await follow_up()
        except Exception as exc:
            logger.error(
                "Weekly PDF worker failure follow-up failed; chat_id=%s job_id=%s error_type=%s",
                redact_identifier("chat", job.chat_id),
                redact_identifier("job", job.job_id),
                type(exc).__name__,
            )

    def _handle_processing_failure(
        self,
        job: WeeklyPdfJob,
        exc: Exception,
        *,
        send_started: bool,
        delivered: bool,
    ) -> None:
        if send_started or delivered:
            self.runtime.finish_failure_and_refund_once(job.job_id, reason="weekly_pdf_worker_delivery_unknown")
            return

        if job.attempt_count + 1 < max(1, int(self.settings.max_attempts)):
            try:
                retry = self.runtime.mark_retryable_failure(
                    job.job_id,
                    worker_id=self.settings.worker_id,
                    error=type(exc).__name__,
                    retry_delay_seconds=self.settings.retry_delay_seconds,
                )
                if retry.status == MarkRetryableFailureResultStatus.MARKED:
                    return
            except Exception:
                logger.exception("Failed to requeue weekly PDF job_id=%s after transient worker failure", job.job_id)

        self.runtime.finish_failure_and_refund_once(job.job_id, reason="weekly_pdf_worker_failed")

    @staticmethod
    def _require_send_started(result: MarkSendStartedResult) -> None:
        if result.status not in {
            MarkSendStartedResultStatus.SEND_STARTED,
            MarkSendStartedResultStatus.ALREADY_SEND_STARTED,
        }:
            raise RuntimeError(f"weekly PDF send-start marker was not persisted: {result.status.value}")

    @staticmethod
    def _require_delivered(result: MarkDeliveredResult) -> None:
        if result.status not in {
            MarkDeliveredResultStatus.DELIVERED,
            MarkDeliveredResultStatus.ALREADY_DELIVERED,
        }:
            raise RuntimeError(f"weekly PDF delivered marker was not persisted: {result.status.value}")

    @staticmethod
    def _require_success(result: FinishJobResult) -> None:
        from .weekly_pdf_jobs import FinishJobResultStatus

        if result.status not in {
            FinishJobResultStatus.SUCCEEDED,
            FinishJobResultStatus.ALREADY_TERMINAL,
        }:
            raise RuntimeError(f"weekly PDF job was not finalized as success: {result.status.value}")


@dataclass
class WeeklyPdfJobRuntime:
    store: WeeklyPdfJobStore
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    stale_after_seconds: int = DEFAULT_WEEKLY_PDF_JOB_STALE_AFTER_SECONDS
    cleanup_limit: int = DEFAULT_WEEKLY_PDF_JOB_CLEANUP_LIMIT

    @classmethod
    def from_config(cls, config: object) -> "WeeklyPdfJobRuntime | None":
        if getattr(config, "storage_backend", "json") != "postgres":
            return None
        return cls(_create_postgres_weekly_pdf_job_store(config))

    def admit(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> AdmitJobResult:
        current_time = _normalize_datetime(self.now())
        return self.store.admit_job(
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            stale_after=self._stale_after(current_time),
            metadata=metadata,
        )

    def admit_queued(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        request_snapshot: WeeklyPdfRequestSnapshot,
        metadata: Mapping[str, Any] | None = None,
        test_access: bool = False,
    ) -> QueuedJobAdmissionResult:
        current_time = _normalize_datetime(self.now())
        return self.store.admit_queued_job(
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            stale_after=self._stale_after(current_time),
            request_snapshot=request_snapshot,
            metadata=metadata,
            now=current_time,
            test_access=test_access,
        )

    def claim_next_queued_job(self, *, worker_id: str, lease_seconds: int) -> ClaimQueuedJobResult:
        current_time = _normalize_datetime(self.now())
        return self.store.claim_next_queued_job(
            worker_id=worker_id,
            lease_until=current_time + timedelta(seconds=max(1, int(lease_seconds))),
            now=current_time,
        )

    def extend_lease(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> ExtendLeaseResult:
        current_time = _normalize_datetime(self.now())
        return self.store.extend_lease(
            job_id,
            worker_id=worker_id,
            lease_until=current_time + timedelta(seconds=max(1, int(lease_seconds))),
            now=current_time,
        )

    def mark_retryable_failure(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        error: str | None,
        retry_delay_seconds: int,
    ) -> MarkRetryableFailureResult:
        current_time = _normalize_datetime(self.now())
        return self.store.mark_retryable_failure(
            job_id,
            worker_id=worker_id,
            error=error,
            next_attempt_at=current_time + timedelta(seconds=max(0, int(retry_delay_seconds))),
            now=current_time,
        )

    def start_job_and_consume(
        self,
        job_id: UUID | str,
        *,
        test_access: bool = False,
    ) -> StartJobResult:
        current_time = _normalize_datetime(self.now())
        return self.store.start_job_and_consume(
            job_id,
            now=current_time,
            stale_after=self._stale_after(current_time),
            test_access=test_access,
        )

    def finish_success(self, job_id: UUID | str) -> FinishJobResult:
        return self.store.finish_success(job_id, now=_normalize_datetime(self.now()))

    def mark_delivered(self, job_id: UUID | str) -> MarkDeliveredResult:
        return self.store.mark_delivered(job_id, now=_normalize_datetime(self.now()))

    def mark_send_started(self, job_id: UUID | str) -> MarkSendStartedResult:
        return self.store.mark_send_started(job_id, now=_normalize_datetime(self.now()))

    def finish_failure_and_refund_once(self, job_id: UUID | str, *, reason: str | None = None) -> FinishJobResult:
        return self.store.finish_failure_and_refund_once(
            job_id,
            reason=reason,
            now=_normalize_datetime(self.now()),
        )

    def cancel_admitted_job(self, job_id: UUID | str, *, reason: str | None = None) -> FinishJobResult:
        return self.store.cancel_queued(
            job_id,
            reason=reason,
            now=_normalize_datetime(self.now()),
        )

    def cleanup_stale(self, *, chat_id: int) -> CleanupStaleResult:
        return self.store.cleanup_stale(
            chat_id=chat_id,
            now=_normalize_datetime(self.now()),
            limit=max(1, int(self.cleanup_limit)),
        )

    def _stale_after(self, now: datetime) -> datetime:
        return now + timedelta(seconds=max(1, int(self.stale_after_seconds)))


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def validate_weekly_pdf_job_runtime_for_startup(config: object) -> None:
    if getattr(config, "storage_backend", "json") != "postgres":
        return

    store = _create_postgres_weekly_pdf_job_store(config)
    try:
        store.validate_schema()
    except Exception as exc:
        raise RuntimeError(
            "Postgres weekly PDF job storage is not ready; "
            "run weekly PDF job migrations before startup.",
        ) from exc


def _create_postgres_weekly_pdf_job_store(config: object):
    database_url = getattr(config, "database_url", None)
    if not database_url:
        raise RuntimeError("DIET_BOT_DATABASE_URL is required for weekly PDF Postgres jobs.")

    from .postgres_connection import get_shared_postgres_connection_provider
    from .postgres_weekly_pdf_job_store import PostgresWeeklyPdfJobStore

    return PostgresWeeklyPdfJobStore(
        str(database_url),
        connection_provider=get_shared_postgres_connection_provider(config),
    )
