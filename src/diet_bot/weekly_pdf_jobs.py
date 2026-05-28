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

DELIVERY_STATUS_NOT_STARTED = "not_started"
DELIVERY_STATUS_SEND_STARTED = "send_started"
DELIVERY_STATUS_DELIVERED = "delivered"
DELIVERY_STATUS_UNKNOWN = "unknown"

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
RefundStatus = Literal["not_required", "pending", "refunded"]
DeliveryStatus = Literal["not_started", "send_started", "delivered", "unknown"]

ACTIVE_JOB_STATUSES = frozenset({JOB_STATUS_QUEUED, JOB_STATUS_RUNNING})
TERMINAL_JOB_STATUSES = frozenset({JOB_STATUS_SUCCEEDED, JOB_STATUS_FAILED, JOB_STATUS_CANCELLED})
REFUNDABLE_CONSUMPTION_SOURCES = frozenset({"monthly", "extra"})


@dataclass(frozen=True)
class WeeklyPdfRequestSnapshot:
    request_payload: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] = field(default_factory=dict)
    recent_recipe_ids: Sequence[str] = field(default_factory=tuple)
    generation_seed: str | None = None

    def __post_init__(self) -> None:
        generation_seed = None
        if self.generation_seed is not None:
            generation_seed = str(self.generation_seed).strip() or None
        object.__setattr__(self, "request_payload", dict(self.request_payload or {}))
        object.__setattr__(self, "profile", dict(self.profile or {}))
        object.__setattr__(
            self,
            "recent_recipe_ids",
            tuple(
                recipe_id
                for recipe_id in (str(item).strip() for item in self.recent_recipe_ids or ())
                if recipe_id
            ),
        )
        object.__setattr__(self, "generation_seed", generation_seed)


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
    send_started_at: datetime | None = None
    delivered_at: datetime | None = None
    finalization_error: str | None = None
    delivery_status: DeliveryStatus = DELIVERY_STATUS_NOT_STARTED
    requires_manual_review: bool = False
    manual_review_reason: str | None = None
    manual_reviewed_at: datetime | None = None
    manual_reviewed_by: str | None = None
    manual_review_resolution: str | None = None
    manual_review_note: str | None = None
    request_snapshot: WeeklyPdfRequestSnapshot | None = None
    worker_id: str | None = None
    leased_until: datetime | None = None
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    last_error: str | None = None

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


class QueuedJobAdmissionResultStatus(str, Enum):
    ADMITTED = "admitted"
    EXISTING_IDEMPOTENCY = "existing_idempotency"
    ACTIVE_DUPLICATE = "active_duplicate"
    DENIED = "denied"


@dataclass(frozen=True)
class QueuedJobAdmissionResult:
    status: QueuedJobAdmissionResultStatus
    job: WeeklyPdfJob | None = None
    denial_reason: str | None = None


class ClaimQueuedJobResultStatus(str, Enum):
    CLAIMED = "claimed"
    EMPTY = "empty"


@dataclass(frozen=True)
class ClaimQueuedJobResult:
    status: ClaimQueuedJobResultStatus
    job: WeeklyPdfJob | None = None


class ExtendLeaseResultStatus(str, Enum):
    EXTENDED = "extended"
    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    WORKER_MISMATCH = "worker_mismatch"


@dataclass(frozen=True)
class ExtendLeaseResult:
    status: ExtendLeaseResultStatus
    job: WeeklyPdfJob | None = None


class MarkRetryableFailureResultStatus(str, Enum):
    MARKED = "marked"
    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    WORKER_MISMATCH = "worker_mismatch"


@dataclass(frozen=True)
class MarkRetryableFailureResult:
    status: MarkRetryableFailureResultStatus
    job: WeeklyPdfJob | None = None


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


class MarkSendStartedResultStatus(str, Enum):
    SEND_STARTED = "send_started"
    ALREADY_SEND_STARTED = "already_send_started"
    INVALID_STATE = "invalid_state"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class MarkSendStartedResult:
    status: MarkSendStartedResultStatus
    job: WeeklyPdfJob | None


class ManualReviewResolutionResultStatus(str, Enum):
    RESOLVED = "resolved"
    ALREADY_RESOLVED = "already_resolved"
    NOT_FOUND = "not_found"
    NOT_MANUAL_REVIEW = "not_manual_review"


@dataclass(frozen=True)
class ManualReviewResolutionResult:
    status: ManualReviewResolutionResultStatus
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
