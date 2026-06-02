from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Awaitable, Protocol
from uuid import UUID

from .log_redaction import redact_identifier


DEFAULT_SALES_FOLLOWUP_WORKER_CONCURRENCY = 1
DEFAULT_SALES_FOLLOWUP_WORKER_LEASE_SECONDS = 5 * 60
DEFAULT_SALES_FOLLOWUP_WORKER_HEARTBEAT_SECONDS = 60
DEFAULT_SALES_FOLLOWUP_WORKER_RETRY_DELAY_SECONDS = 30
DEFAULT_SALES_FOLLOWUP_WORKER_MAX_ATTEMPTS = 3
DEFAULT_SALES_FOLLOWUP_WORKER_IDLE_SLEEP_SECONDS = 1.0
DEFAULT_SALES_FOLLOWUP_WORKER_ERROR_BACKOFF_SECONDS = 5.0
DEFAULT_SALES_FOLLOWUP_WORKER_JOB_TIMEOUT_SECONDS = 60.0

logger = logging.getLogger(__name__)


class ClaimSalesFollowupJobResultStatus(str, Enum):
    CLAIMED = "claimed"
    EMPTY = "empty"


@dataclass(frozen=True)
class ClaimSalesFollowupJobResult:
    status: ClaimSalesFollowupJobResultStatus
    job: object | None = None


class SalesFollowupJobTransitionStatus(str, Enum):
    UPDATED = "updated"
    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    WORKER_MISMATCH = "worker_mismatch"
    ALREADY_TERMINAL = "already_terminal"


@dataclass(frozen=True)
class SalesFollowupJobTransitionResult:
    status: SalesFollowupJobTransitionStatus
    job: object | None = None


@dataclass(frozen=True)
class SalesFollowupEligibility:
    eligible: bool
    reason: str | None = None
    chain_status: str = "cancelled"

    @classmethod
    def allowed(cls) -> "SalesFollowupEligibility":
        return cls(True)

    @classmethod
    def blocked(cls, reason: str, *, chain_status: str = "cancelled") -> "SalesFollowupEligibility":
        return cls(False, reason, chain_status)


@dataclass(frozen=True)
class SalesFollowupSendRequest:
    job_id: UUID | str
    chat_id: int
    step_key: str
    step_index: int
    message_text: str
    button_label: str | None = None
    target_callback_data: str | None = None
    payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        payload = dict(self.payload or {})
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True)
class SalesFollowupSendResult:
    telegram_message_id: int | None = None


class SalesFollowupSendError(RuntimeError):
    pass


class SalesFollowupTransientSendError(SalesFollowupSendError):
    pass


class SalesFollowupPermanentSendError(SalesFollowupSendError):
    pass


class SalesFollowupUnknownSendOutcome(SalesFollowupSendError):
    pass


class SalesFollowupSender(Protocol):
    async def send(self, request: SalesFollowupSendRequest) -> SalesFollowupSendResult: ...


SalesFollowupEligibilityChecker = Callable[
    [object],
    SalesFollowupEligibility | Awaitable[SalesFollowupEligibility],
]


class SalesFollowupJobStore(Protocol):
    def get_campaign(self, campaign_key: str) -> object | None: ...

    def get_preference(self, chat_id: int) -> object | None: ...

    def claim_next_due_job(
        self,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime | None = None,
    ) -> ClaimSalesFollowupJobResult: ...

    def extend_lease(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult: ...

    def mark_send_started(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult: ...

    def mark_sent(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        telegram_message_id: int | None,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult: ...

    def mark_retryable_failure(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        error: str | None,
        next_attempt_at: datetime,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult: ...

    def mark_failed(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        reason: str | None,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult: ...

    def mark_unknown(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        error: str | None,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult: ...

    def skip_job_and_cancel_chain(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        reason: str,
        chain_status: str = "cancelled",
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult: ...


@dataclass(frozen=True)
class SalesFollowupWorkerSettings:
    worker_id: str = "sales-followup-worker"
    concurrency: int = DEFAULT_SALES_FOLLOWUP_WORKER_CONCURRENCY
    lease_seconds: int = DEFAULT_SALES_FOLLOWUP_WORKER_LEASE_SECONDS
    heartbeat_interval_seconds: int = DEFAULT_SALES_FOLLOWUP_WORKER_HEARTBEAT_SECONDS
    retry_delay_seconds: int = DEFAULT_SALES_FOLLOWUP_WORKER_RETRY_DELAY_SECONDS
    max_attempts: int = DEFAULT_SALES_FOLLOWUP_WORKER_MAX_ATTEMPTS
    idle_sleep_seconds: float = DEFAULT_SALES_FOLLOWUP_WORKER_IDLE_SLEEP_SECONDS
    error_backoff_seconds: float = DEFAULT_SALES_FOLLOWUP_WORKER_ERROR_BACKOFF_SECONDS
    job_timeout_seconds: float = DEFAULT_SALES_FOLLOWUP_WORKER_JOB_TIMEOUT_SECONDS

    @classmethod
    def from_config(cls, config: object, *, worker_id: str | None = None) -> "SalesFollowupWorkerSettings":
        return cls(
            worker_id=worker_id or str(getattr(config, "sales_followup_worker_id", None) or "sales-followup-worker"),
            concurrency=max(1, int(getattr(config, "sales_followup_worker_concurrency", cls.concurrency))),
            lease_seconds=max(1, int(getattr(config, "sales_followup_worker_lease_seconds", cls.lease_seconds))),
            heartbeat_interval_seconds=max(
                1,
                int(getattr(config, "sales_followup_worker_heartbeat_seconds", cls.heartbeat_interval_seconds)),
            ),
            retry_delay_seconds=max(
                0,
                int(getattr(config, "sales_followup_worker_retry_delay_seconds", cls.retry_delay_seconds)),
            ),
            max_attempts=max(1, int(getattr(config, "sales_followup_worker_max_attempts", cls.max_attempts))),
            idle_sleep_seconds=max(
                0.1,
                float(getattr(config, "sales_followup_worker_idle_sleep_seconds", cls.idle_sleep_seconds)),
            ),
            error_backoff_seconds=max(
                0.1,
                float(getattr(config, "sales_followup_worker_error_backoff_seconds", cls.error_backoff_seconds)),
            ),
            job_timeout_seconds=max(
                0.001,
                float(getattr(config, "sales_followup_worker_job_timeout_seconds", cls.job_timeout_seconds)),
            ),
        )


class SalesFollowupWorker:
    def __init__(
        self,
        runtime: "SalesFollowupJobRuntime",
        sender: SalesFollowupSender,
        *,
        eligibility_checker: SalesFollowupEligibilityChecker | None = None,
        settings: SalesFollowupWorkerSettings | None = None,
    ) -> None:
        self.runtime = runtime
        self.sender = sender
        self.eligibility_checker = eligibility_checker
        self.settings = settings or SalesFollowupWorkerSettings()

    async def run_once(self) -> int:
        claimed_jobs: list[object] = []
        for _ in range(max(1, int(self.settings.concurrency))):
            claim = self.runtime.claim_next_due_job(
                worker_id=self.settings.worker_id,
                lease_seconds=self.settings.lease_seconds,
            )
            if claim.status == ClaimSalesFollowupJobResultStatus.EMPTY:
                break
            if claim.status == ClaimSalesFollowupJobResultStatus.CLAIMED and claim.job is not None:
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
                    "Sales follow-up worker iteration failed; worker_id=%s error_type=%s backoff_seconds=%.3f",
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

    async def _process_claimed_job(self, job: object) -> None:
        job_id = _job_id(job)
        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(self._heartbeat_until_stopped(job_id, stop_heartbeat))
        send_started = False

        def mark_local_send_started() -> None:
            nonlocal send_started
            send_started = True

        try:
            await asyncio.wait_for(
                self._process_claimed_job_inner(job, lambda: send_started, mark_local_send_started),
                timeout=max(0.001, float(self.settings.job_timeout_seconds)),
            )
        except TimeoutError as exc:
            logger.error(
                "Sales follow-up worker job timed out; worker_id=%s job_id=%s timeout_seconds=%.3f",
                self.settings.worker_id,
                redact_identifier("job", job_id),
                max(0.001, float(self.settings.job_timeout_seconds)),
            )
            self._handle_processing_failure(job, exc, send_started=send_started)
        except Exception as exc:
            self._handle_processing_failure(job, exc, send_started=send_started)
        finally:
            stop_heartbeat.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _process_claimed_job_inner(
        self,
        job: object,
        get_send_started: Callable[[], bool],
        mark_local_send_started: Callable[[], None],
    ) -> None:
        eligibility = await self._recheck_eligibility(job)
        if not eligibility.eligible:
            self._require_updated(
                self.runtime.skip_job_and_cancel_chain(
                    _job_id(job),
                    worker_id=self.settings.worker_id,
                    reason=eligibility.reason or "not_eligible",
                    chain_status=eligibility.chain_status,
                )
            )
            return

        try:
            self._require_updated(self.runtime.mark_send_started(_job_id(job), worker_id=self.settings.worker_id))
            mark_local_send_started()
            result = await self.sender.send(_send_request_from_job(job))
        except SalesFollowupPermanentSendError:
            self._require_updated(
                self.runtime.skip_job_and_cancel_chain(
                    _job_id(job),
                    worker_id=self.settings.worker_id,
                    reason="permanent_send_failure",
                    chain_status="suppressed",
                )
            )
            return
        except SalesFollowupTransientSendError as exc:
            self._handle_processing_failure(job, exc, send_started=get_send_started(), force_retry=True)
            return
        except SalesFollowupUnknownSendOutcome as exc:
            self._require_updated(
                self.runtime.mark_unknown(
                    _job_id(job),
                    worker_id=self.settings.worker_id,
                    error=type(exc).__name__,
                )
            )
            return
        except Exception as exc:
            self._handle_processing_failure(job, exc, send_started=get_send_started())
            return

        self._require_updated(
            self.runtime.mark_sent(
                _job_id(job),
                worker_id=self.settings.worker_id,
                telegram_message_id=result.telegram_message_id,
            )
        )

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
                        "Sales follow-up worker lease extension failed; worker_id=%s job_id=%s error_type=%s",
                        self.settings.worker_id,
                        redact_identifier("job", job_id),
                        type(exc).__name__,
                    )
                    continue
                if result.status != SalesFollowupJobTransitionStatus.UPDATED:
                    logger.warning(
                        "Sales follow-up worker lease extension did not extend worker_id=%s job_id=%s status=%s",
                        self.settings.worker_id,
                        redact_identifier("job", job_id),
                        result.status.value,
                    )

    async def _recheck_eligibility(self, job: object) -> SalesFollowupEligibility:
        campaign = self.runtime.get_campaign(str(getattr(job, "campaign_key", "")))
        if campaign is None or not bool(getattr(campaign, "enabled", False)):
            return SalesFollowupEligibility.blocked("campaign_disabled", chain_status="cancelled")

        preference = self.runtime.get_preference(int(getattr(job, "chat_id")))
        if getattr(preference, "opted_out_at", None) is not None:
            return SalesFollowupEligibility.blocked("opted_out", chain_status="opted_out")

        if self.eligibility_checker is None:
            return SalesFollowupEligibility.allowed()

        result = self.eligibility_checker(job)
        if hasattr(result, "__await__"):
            return await result  # type: ignore[no-any-return]
        return result

    def _handle_processing_failure(
        self,
        job: object,
        exc: Exception,
        *,
        send_started: bool,
        force_retry: bool = False,
    ) -> None:
        if send_started and not force_retry:
            self._require_updated(
                self.runtime.mark_unknown(
                    _job_id(job),
                    worker_id=self.settings.worker_id,
                    error=type(exc).__name__,
                )
            )
            return

        if int(getattr(job, "attempt_count", 0)) + 1 < max(1, int(self.settings.max_attempts)):
            try:
                retry = self.runtime.mark_retryable_failure(
                    _job_id(job),
                    worker_id=self.settings.worker_id,
                    error=type(exc).__name__,
                    retry_delay_seconds=self.settings.retry_delay_seconds,
                )
                if retry.status == SalesFollowupJobTransitionStatus.UPDATED:
                    return
            except Exception:
                logger.exception("Failed to requeue sales follow-up job_id=%s after worker failure", _job_id(job))

        self._require_updated(
            self.runtime.mark_failed(
                _job_id(job),
                worker_id=self.settings.worker_id,
                reason="sales_followup_worker_failed",
            )
        )

    @staticmethod
    def _require_updated(result: SalesFollowupJobTransitionResult) -> None:
        if result.status != SalesFollowupJobTransitionStatus.UPDATED:
            raise RuntimeError(f"sales follow-up job transition was not persisted: {result.status.value}")


@dataclass
class SalesFollowupJobRuntime:
    store: SalesFollowupJobStore
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    @classmethod
    def from_config(cls, config: object) -> "SalesFollowupJobRuntime | None":
        if not bool(getattr(config, "sales_followup_worker_enabled", False)):
            return None
        if getattr(config, "storage_backend", "json") != "postgres":
            return None
        return cls(_create_postgres_sales_followup_store(config))

    def get_campaign(self, campaign_key: str) -> object | None:
        return self.store.get_campaign(campaign_key)

    def get_preference(self, chat_id: int) -> object | None:
        return self.store.get_preference(chat_id)

    def claim_next_due_job(self, *, worker_id: str, lease_seconds: int) -> ClaimSalesFollowupJobResult:
        current_time = _normalize_datetime(self.now())
        return self.store.claim_next_due_job(
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
    ) -> SalesFollowupJobTransitionResult:
        current_time = _normalize_datetime(self.now())
        return self.store.extend_lease(
            job_id,
            worker_id=worker_id,
            lease_until=current_time + timedelta(seconds=max(1, int(lease_seconds))),
            now=current_time,
        )

    def mark_send_started(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
    ) -> SalesFollowupJobTransitionResult:
        return self.store.mark_send_started(
            job_id,
            worker_id=worker_id,
            now=_normalize_datetime(self.now()),
        )

    def mark_sent(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        telegram_message_id: int | None,
    ) -> SalesFollowupJobTransitionResult:
        return self.store.mark_sent(
            job_id,
            worker_id=worker_id,
            telegram_message_id=telegram_message_id,
            now=_normalize_datetime(self.now()),
        )

    def mark_retryable_failure(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        error: str | None,
        retry_delay_seconds: int,
    ) -> SalesFollowupJobTransitionResult:
        current_time = _normalize_datetime(self.now())
        return self.store.mark_retryable_failure(
            job_id,
            worker_id=worker_id,
            error=error,
            next_attempt_at=current_time + timedelta(seconds=max(0, int(retry_delay_seconds))),
            now=current_time,
        )

    def mark_failed(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        reason: str | None,
    ) -> SalesFollowupJobTransitionResult:
        return self.store.mark_failed(
            job_id,
            worker_id=worker_id,
            reason=reason,
            now=_normalize_datetime(self.now()),
        )

    def mark_unknown(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        error: str | None,
    ) -> SalesFollowupJobTransitionResult:
        return self.store.mark_unknown(
            job_id,
            worker_id=worker_id,
            error=error,
            now=_normalize_datetime(self.now()),
        )

    def skip_job_and_cancel_chain(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        reason: str,
        chain_status: str = "cancelled",
    ) -> SalesFollowupJobTransitionResult:
        return self.store.skip_job_and_cancel_chain(
            job_id,
            worker_id=worker_id,
            reason=reason,
            chain_status=chain_status,
            now=_normalize_datetime(self.now()),
        )


def _job_id(job: object) -> UUID | str:
    return getattr(job, "job_id")


def _send_request_from_job(job: object) -> SalesFollowupSendRequest:
    payload = dict(getattr(job, "payload", {}) or {})
    return SalesFollowupSendRequest(
        job_id=_job_id(job),
        chat_id=int(getattr(job, "chat_id")),
        step_key=str(getattr(job, "step_key")),
        step_index=int(getattr(job, "step_index")),
        message_text=str(payload.get("message_text") or ""),
        button_label=_optional_text(payload.get("button_label")),
        target_callback_data=_optional_text(payload.get("target_callback_data")),
        payload=payload,
    )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _create_postgres_sales_followup_store(config: object):
    database_url = getattr(config, "database_url", None)
    if not database_url:
        raise RuntimeError("DIET_BOT_DATABASE_URL is required for sales follow-up Postgres jobs.")

    from .postgres_connection import get_shared_postgres_connection_provider
    from .postgres_sales_followup_store import PostgresSalesFollowupStore

    return PostgresSalesFollowupStore(
        str(database_url),
        connection_provider=get_shared_postgres_connection_provider(config),
    )
