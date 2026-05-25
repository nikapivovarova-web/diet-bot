from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from .subscriptions import AttemptSource


JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"

REFUND_STATUS_NOT_REQUIRED = "not_required"
REFUND_STATUS_PENDING = "pending"
REFUND_STATUS_REFUNDED = "refunded"

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
RefundStatus = Literal["not_required", "pending", "refunded"]

ACTIVE_JOB_STATUSES = frozenset({JOB_STATUS_QUEUED, JOB_STATUS_RUNNING})
TERMINAL_JOB_STATUSES = frozenset({JOB_STATUS_SUCCEEDED, JOB_STATUS_FAILED, JOB_STATUS_CANCELLED})
REFUNDABLE_CONSUMPTION_SOURCES = frozenset({"monthly", "extra"})


@dataclass(frozen=True)
class WeeklyPdfJob:
    job_id: UUID
    chat_id: int
    idempotency_key: str
    status: JobStatus
    refund_status: RefundStatus
    consumption_source: AttemptSource | None
    stale_after: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    failure_reason: str | None = None
    delivered_at: datetime | None = None
    finalization_error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_JOB_STATUSES


class AdmitJobResultStatus(str, Enum):
    ADMITTED = "admitted"
    EXISTING_IDEMPOTENCY = "existing_idempotency"
    ACTIVE_DUPLICATE = "active_duplicate"


@dataclass(frozen=True)
class AdmitJobResult:
    status: AdmitJobResultStatus
    job: WeeklyPdfJob


class StartJobResultStatus(str, Enum):
    STARTED = "started"
    ALREADY_RUNNING = "already_running"
    TERMINAL = "terminal"
    NOT_FOUND = "not_found"
    DENIED = "denied"


@dataclass(frozen=True)
class StartJobResult:
    status: StartJobResultStatus
    job: WeeklyPdfJob | None


class FinishJobResultStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ALREADY_TERMINAL = "already_terminal"
    INVALID_STATE = "invalid_state"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class FinishJobResult:
    status: FinishJobResultStatus
    job: WeeklyPdfJob | None


class MarkDeliveredResultStatus(str, Enum):
    DELIVERED = "delivered"
    ALREADY_DELIVERED = "already_delivered"
    INVALID_STATE = "invalid_state"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class MarkDeliveredResult:
    status: MarkDeliveredResultStatus
    job: WeeklyPdfJob | None


@dataclass(frozen=True)
class CleanupStaleResult:
    job_results: Sequence[FinishJobResult] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_results", tuple(self.job_results))

    @property
    def jobs(self) -> list[WeeklyPdfJob]:
        return [result.job for result in self.job_results if result.job is not None]


def refund_status_for_consumption_source(source: str | None) -> RefundStatus:
    if source in REFUNDABLE_CONSUMPTION_SOURCES:
        return REFUND_STATUS_PENDING
    return REFUND_STATUS_NOT_REQUIRED
