from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from .one_day_generation_jobs import (
    AdmitJobResult,
    ClaimQueuedJobResult,
    CleanupStaleResult,
    ExtendLeaseResult,
    FinishJobResult,
    MarkRetryableFailureResult,
    MarkSendStartedResult,
    MarkValueMessageDeliveredResult,
    OneDayGenerationRequestSnapshot,
    QueuedJobAdmissionResult,
    SetExpectedValueMessagesResult,
    StartJobResult,
)


DEFAULT_ONE_DAY_GENERATION_JOB_STALE_AFTER_SECONDS = 30 * 60
DEFAULT_ONE_DAY_GENERATION_JOB_CLEANUP_LIMIT = 10


class OneDayGenerationJobStore(Protocol):
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
        request_snapshot: OneDayGenerationRequestSnapshot,
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

    def set_expected_value_messages(
        self,
        job_id: UUID | str,
        expected_count: int,
        *,
        now: datetime | None = None,
    ) -> SetExpectedValueMessagesResult: ...

    def mark_send_started(self, job_id: UUID | str, *, now: datetime | None = None) -> MarkSendStartedResult: ...

    def mark_value_message_delivered(
        self,
        job_id: UUID | str,
        *,
        value_message_key: str,
        now: datetime | None = None,
    ) -> MarkValueMessageDeliveredResult: ...

    def finish_success(self, job_id: UUID | str, *, now: datetime | None = None) -> FinishJobResult: ...

    def finish_failure_and_refund_once(
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
        limit: int = DEFAULT_ONE_DAY_GENERATION_JOB_CLEANUP_LIMIT,
    ) -> CleanupStaleResult: ...


@dataclass
class OneDayGenerationJobRuntime:
    store: OneDayGenerationJobStore
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    stale_after_seconds: int = DEFAULT_ONE_DAY_GENERATION_JOB_STALE_AFTER_SECONDS
    cleanup_limit: int = DEFAULT_ONE_DAY_GENERATION_JOB_CLEANUP_LIMIT

    @classmethod
    def from_config(cls, config: object) -> "OneDayGenerationJobRuntime | None":
        if getattr(config, "storage_backend", "json") != "postgres":
            return None
        return cls(_create_postgres_one_day_generation_job_store(config))

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

    def start_job_and_consume(self, job_id: UUID | str, *, test_access: bool = False) -> StartJobResult:
        current_time = _normalize_datetime(self.now())
        return self.store.start_job_and_consume(
            job_id,
            now=current_time,
            stale_after=self._stale_after(current_time),
            test_access=test_access,
        )

    def set_expected_value_messages(
        self,
        job_id: UUID | str,
        expected_count: int,
    ) -> SetExpectedValueMessagesResult:
        return self.store.set_expected_value_messages(
            job_id,
            expected_count,
            now=_normalize_datetime(self.now()),
        )

    def mark_send_started(self, job_id: UUID | str) -> MarkSendStartedResult:
        return self.store.mark_send_started(job_id, now=_normalize_datetime(self.now()))

    def mark_value_message_delivered(
        self,
        job_id: UUID | str,
        *,
        value_message_key: str,
    ) -> MarkValueMessageDeliveredResult:
        return self.store.mark_value_message_delivered(
            job_id,
            value_message_key=value_message_key,
            now=_normalize_datetime(self.now()),
        )

    def finish_success(self, job_id: UUID | str) -> FinishJobResult:
        return self.store.finish_success(job_id, now=_normalize_datetime(self.now()))

    def finish_failure_and_refund_once(self, job_id: UUID | str, *, reason: str | None = None) -> FinishJobResult:
        return self.store.finish_failure_and_refund_once(
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


def validate_one_day_generation_job_store_for_startup(config: object) -> None:
    if getattr(config, "storage_backend", "json") != "postgres":
        return

    store = _create_postgres_one_day_generation_job_store(config)
    try:
        store.validate_schema()
    except Exception as exc:
        raise RuntimeError(
            "Postgres one-day generation job storage is not ready; "
            "run one-day generation job migrations before startup.",
        ) from exc


def _create_postgres_one_day_generation_job_store(config: object):
    database_url = getattr(config, "database_url", None)
    if not database_url:
        raise RuntimeError("DIET_BOT_DATABASE_URL is required for one-day generation Postgres jobs.")

    from .postgres_connection import get_shared_postgres_connection_provider
    from .postgres_one_day_generation_job_store import PostgresOneDayGenerationJobStore

    return PostgresOneDayGenerationJobStore(
        str(database_url),
        connection_provider=get_shared_postgres_connection_provider(config),
    )
