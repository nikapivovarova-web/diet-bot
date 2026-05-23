from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from .weekly_pdf_jobs import (
    AdmitJobResult,
    CleanupStaleResult,
    FinishJobResult,
    StartJobResult,
)


DEFAULT_WEEKLY_PDF_JOB_STALE_AFTER_SECONDS = 30 * 60
DEFAULT_WEEKLY_PDF_JOB_CLEANUP_LIMIT = 10


class WeeklyPdfJobStore(Protocol):
    def admit_job(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        stale_after: datetime,
        metadata: Mapping[str, Any] | None = None,
    ) -> AdmitJobResult: ...

    def start_job_and_consume(
        self,
        job_id: UUID | str,
        *,
        now: datetime | None = None,
        stale_after: datetime | None = None,
        test_access: bool = False,
    ) -> StartJobResult: ...

    def finish_success(self, job_id: UUID | str, *, now: datetime | None = None) -> FinishJobResult: ...

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
        database_url = getattr(config, "database_url", None)
        if not database_url:
            raise RuntimeError("DIET_BOT_DATABASE_URL is required for weekly PDF Postgres jobs.")

        from .postgres_weekly_pdf_job_store import PostgresWeeklyPdfJobStore

        store = PostgresWeeklyPdfJobStore(str(database_url))
        store.initialize()
        return cls(store)

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
