from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from .postgres_connection import DirectPostgresConnectionProvider, PostgresConnectionProvider
from .postgres_sales_followup_migrations import MIGRATIONS, run_sales_followup_schema_migrations
from .postgres_schema_validation import (
    SCHEMA_MIGRATIONS_COLUMNS,
    PostgresSchemaExpectation,
    validate_postgres_schema,
)
from .sales_followup import (
    DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
    SALES_FOLLOWUP_CAMPAIGN_VERSION,
    build_sales_followup_job_drafts,
)
from .sales_followup_runtime import (
    ClaimSalesFollowupJobResult,
    ClaimSalesFollowupJobResultStatus,
    SalesFollowupJobTransitionResult,
    SalesFollowupJobTransitionStatus,
)


CHAIN_STATUS_ACTIVE = "active"
CHAIN_STATUS_COMPLETED = "completed"
CHAIN_STATUS_CANCELLED = "cancelled"
CHAIN_STATUS_OPTED_OUT = "opted_out"
CHAIN_STATUS_SUPPRESSED = "suppressed"
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SENT = "sent"
JOB_STATUS_SKIPPED = "skipped"
JOB_STATUS_CANCELLED = "cancelled"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_UNKNOWN = "unknown"
DEFAULT_DISABLED_REASON = "Stage 18B storage foundation only; campaign disabled by default."

TERMINAL_JOB_STATUSES = frozenset(
    {JOB_STATUS_SENT, JOB_STATUS_SKIPPED, JOB_STATUS_CANCELLED, JOB_STATUS_FAILED, JOB_STATUS_UNKNOWN}
)
ACTIVE_JOB_STATUSES = frozenset({JOB_STATUS_QUEUED, JOB_STATUS_RUNNING})
CHAIN_TERMINAL_STATUSES = frozenset(
    {CHAIN_STATUS_COMPLETED, CHAIN_STATUS_CANCELLED, CHAIN_STATUS_OPTED_OUT, CHAIN_STATUS_SUPPRESSED}
)


SALES_FOLLOWUP_SCHEMA_EXPECTATION = PostgresSchemaExpectation(
    component="sales follow-up",
    migration_versions=tuple(migration.version for migration in MIGRATIONS),
    table_columns={
        "schema_migrations": SCHEMA_MIGRATIONS_COLUMNS,
        "sales_followup_chains": (
            "chain_id",
            "chat_id",
            "campaign_key",
            "trigger_kind",
            "trigger_job_id",
            "trigger_idempotency_key",
            "triggered_at",
            "status",
            "cancel_reason",
            "created_at",
            "updated_at",
            "cancelled_at",
        ),
        "sales_followup_jobs": (
            "job_id",
            "chain_id",
            "chat_id",
            "campaign_key",
            "step_key",
            "step_index",
            "scheduled_at",
            "next_attempt_at",
            "status",
            "payload_json",
            "button_set_key",
            "send_started_at",
            "sent_at",
            "telegram_message_id",
            "skipped_at",
            "finished_at",
            "skip_reason",
            "failure_reason",
            "last_error",
            "worker_id",
            "leased_until",
            "attempt_count",
            "heartbeat_at",
            "created_at",
            "updated_at",
        ),
        "sales_followup_preferences": (
            "chat_id",
            "opted_out_at",
            "opt_out_source",
            "created_at",
            "updated_at",
        ),
        "sales_followup_campaigns": (
            "campaign_key",
            "enabled",
            "version",
            "disabled_reason",
            "created_at",
            "updated_at",
        ),
    },
    indexes=(
        "idx_sales_followup_chains_trigger_idempotency_key_unique",
        "idx_sales_followup_chains_active_chat_campaign_unique",
        "idx_sales_followup_jobs_chain_step_unique",
        "idx_sales_followup_jobs_queue_claim",
        "idx_sales_followup_jobs_lease_reclaim",
    ),
    constraints=(
        "sales_followup_chains_pkey",
        "chk_sales_followup_chains_campaign_key_non_empty",
        "chk_sales_followup_chains_trigger_kind_non_empty",
        "chk_sales_followup_chains_trigger_idempotency_key_non_empty",
        "chk_sales_followup_chains_status",
        "sales_followup_jobs_pkey",
        "chk_sales_followup_jobs_campaign_key_non_empty",
        "chk_sales_followup_jobs_step_key_non_empty",
        "chk_sales_followup_jobs_step_index_positive",
        "chk_sales_followup_jobs_status",
        "chk_sales_followup_jobs_payload_object",
        "chk_sales_followup_jobs_button_set_key_non_empty",
        "chk_sales_followup_jobs_worker_id_non_empty",
        "chk_sales_followup_jobs_attempt_count_non_negative",
        "sales_followup_preferences_pkey",
        "chk_sales_followup_preferences_opt_out_source_non_empty",
        "sales_followup_campaigns_pkey",
        "chk_sales_followup_campaigns_campaign_key_non_empty",
        "chk_sales_followup_campaigns_version_non_empty",
        "chk_sales_followup_campaigns_disabled_reason_non_empty",
    ),
    remediation="Run sales follow-up migrations before use.",
)


class CreateSalesFollowupChainStatus(str, Enum):
    CREATED = "created"
    EXISTING_IDEMPOTENCY = "existing_idempotency"
    ACTIVE_DUPLICATE = "active_duplicate"


@dataclass(frozen=True)
class SalesFollowupChain:
    chain_id: UUID
    chat_id: int
    campaign_key: str
    trigger_kind: str
    trigger_job_id: UUID | None
    trigger_idempotency_key: str
    triggered_at: datetime
    status: str
    cancel_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    cancelled_at: datetime | None = None


@dataclass(frozen=True)
class SalesFollowupJob:
    job_id: UUID
    chain_id: UUID
    chat_id: int
    campaign_key: str
    step_key: str
    step_index: int
    scheduled_at: datetime
    next_attempt_at: datetime
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    button_set_key: str = "sales_followup_default"
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
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", dict(self.payload))


@dataclass(frozen=True)
class SalesFollowupPreference:
    chat_id: int
    opted_out_at: datetime | None
    opt_out_source: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SalesFollowupCampaign:
    campaign_key: str
    enabled: bool
    version: str
    disabled_reason: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class CreateSalesFollowupChainResult:
    status: CreateSalesFollowupChainStatus
    chain: SalesFollowupChain
    jobs: tuple[SalesFollowupJob, ...]


class PostgresSalesFollowupStore:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = 5,
        connect_attempts: int = 3,
        retry_base_delay: float = 0.2,
        retry_max_delay: float = 1.0,
        connection_provider: PostgresConnectionProvider | None = None,
    ) -> None:
        self.dsn = dsn
        self.connect_timeout = connect_timeout
        self.connect_attempts = max(1, connect_attempts)
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self._connection_provider = connection_provider or DirectPostgresConnectionProvider(
            dsn,
            connect_timeout=connect_timeout,
            connect_attempts=self.connect_attempts,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
        )

    def initialize(self) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    run_sales_followup_schema_migrations(cur)

    def validate_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                validate_postgres_schema(cur, SALES_FOLLOWUP_SCHEMA_EXPECTATION)

    def ensure_campaign(
        self,
        campaign_key: str = DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        *,
        version: str = SALES_FOLLOWUP_CAMPAIGN_VERSION,
        disabled_reason: str = DEFAULT_DISABLED_REASON,
    ) -> SalesFollowupCampaign:
        campaign_key = _required_text(campaign_key, "campaign_key")
        version = _required_text(version, "version")
        disabled_reason = _optional_text(disabled_reason)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    return self._ensure_campaign_cur(
                        cur,
                        campaign_key,
                        version=version,
                        disabled_reason=disabled_reason,
                    )

    def get_campaign(self, campaign_key: str) -> SalesFollowupCampaign | None:
        campaign_key = _required_text(campaign_key, "campaign_key")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM sales_followup_campaigns
                    WHERE campaign_key = %s
                    """,
                    (campaign_key,),
                )
                row = cur.fetchone()
        return _campaign_from_row(row) if row is not None else None

    def create_chain(
        self,
        *,
        chat_id: int,
        campaign_key: str = DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind: str,
        trigger_idempotency_key: str,
        triggered_at: datetime,
        trigger_job_id: UUID | str | None = None,
        chain_id: UUID | str | None = None,
        now: datetime | None = None,
    ) -> CreateSalesFollowupChainResult:
        campaign_key = _required_text(campaign_key, "campaign_key")
        trigger_kind = _required_text(trigger_kind, "trigger_kind")
        trigger_idempotency_key = _required_text(trigger_idempotency_key, "trigger_idempotency_key")
        normalized_triggered_at = _normalize_datetime(triggered_at)
        current_time = _normalize_datetime(now)
        candidate_chain_id = _coerce_uuid(chain_id) if chain_id is not None else uuid4()
        normalized_trigger_job_id = _coerce_uuid(trigger_job_id) if trigger_job_id is not None else None
        drafts = build_sales_followup_job_drafts(
            chat_id=int(chat_id),
            campaign_key=campaign_key,
            triggered_at=normalized_triggered_at,
        )

        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._ensure_campaign_cur(
                        cur,
                        campaign_key,
                        version=SALES_FOLLOWUP_CAMPAIGN_VERSION,
                        disabled_reason=DEFAULT_DISABLED_REASON,
                    )

                    existing_idempotency = self._get_chain_by_idempotency_key_cur(cur, trigger_idempotency_key)
                    if existing_idempotency is not None:
                        return CreateSalesFollowupChainResult(
                            CreateSalesFollowupChainStatus.EXISTING_IDEMPOTENCY,
                            existing_idempotency,
                            self._list_jobs_for_chain_cur(cur, existing_idempotency.chain_id),
                        )

                    active_duplicate = self._get_active_chain_for_chat_campaign_cur(cur, chat_id, campaign_key)
                    if active_duplicate is not None:
                        return CreateSalesFollowupChainResult(
                            CreateSalesFollowupChainStatus.ACTIVE_DUPLICATE,
                            active_duplicate,
                            self._list_jobs_for_chain_cur(cur, active_duplicate.chain_id),
                        )

                    cur.execute(
                        """
                        INSERT INTO sales_followup_chains (
                            chain_id,
                            chat_id,
                            campaign_key,
                            trigger_kind,
                            trigger_job_id,
                            trigger_idempotency_key,
                            triggered_at,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING *
                        """,
                        (
                            candidate_chain_id,
                            int(chat_id),
                            campaign_key,
                            trigger_kind,
                            normalized_trigger_job_id,
                            trigger_idempotency_key,
                            normalized_triggered_at,
                            current_time,
                            current_time,
                        ),
                    )
                    row = cur.fetchone()
                    if row is None:
                        existing_idempotency = self._get_chain_by_idempotency_key_cur(cur, trigger_idempotency_key)
                        if existing_idempotency is not None:
                            return CreateSalesFollowupChainResult(
                                CreateSalesFollowupChainStatus.EXISTING_IDEMPOTENCY,
                                existing_idempotency,
                                self._list_jobs_for_chain_cur(cur, existing_idempotency.chain_id),
                            )
                        active_duplicate = self._get_active_chain_for_chat_campaign_cur(cur, chat_id, campaign_key)
                        if active_duplicate is not None:
                            return CreateSalesFollowupChainResult(
                                CreateSalesFollowupChainStatus.ACTIVE_DUPLICATE,
                                active_duplicate,
                                self._list_jobs_for_chain_cur(cur, active_duplicate.chain_id),
                            )
                        raise RuntimeError("Sales follow-up chain admission conflict could not be resolved.")

                    chain = _chain_from_row(row)
                    for draft in drafts:
                        cur.execute(
                            """
                            INSERT INTO sales_followup_jobs (
                                job_id,
                                chain_id,
                                chat_id,
                                campaign_key,
                                step_key,
                                step_index,
                                scheduled_at,
                                next_attempt_at,
                                status,
                                payload_json,
                                button_set_key,
                                created_at,
                                updated_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s)
                            """,
                            (
                                uuid4(),
                                chain.chain_id,
                                draft.chat_id,
                                draft.campaign_key,
                                draft.step_key,
                                draft.step_index,
                                draft.scheduled_at,
                                draft.next_attempt_at,
                                _jsonb(draft.payload),
                                draft.button_set_key,
                                current_time,
                                current_time,
                            ),
                        )

                    return CreateSalesFollowupChainResult(
                        CreateSalesFollowupChainStatus.CREATED,
                        chain,
                        self._list_jobs_for_chain_cur(cur, chain.chain_id),
                    )

    def get_chain(self, chain_id: UUID | str) -> SalesFollowupChain | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM sales_followup_chains
                    WHERE chain_id = %s
                    """,
                    (_coerce_uuid(chain_id),),
                )
                row = cur.fetchone()
        return _chain_from_row(row) if row is not None else None

    def list_jobs_for_chain(self, chain_id: UUID | str) -> tuple[SalesFollowupJob, ...]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._list_jobs_for_chain_cur(cur, _coerce_uuid(chain_id))

    def get_job(self, job_id: UUID | str) -> SalesFollowupJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._get_job_cur(cur, job_id)

    def claim_next_due_job(
        self,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime | None = None,
    ) -> ClaimSalesFollowupJobResult:
        worker_id = _required_text(worker_id, "worker_id")
        current_time = _normalize_datetime(now)
        lease_until = _normalize_datetime(lease_until)
        if lease_until <= current_time:
            raise ValueError("lease_until must be after now")
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        WITH candidate AS (
                            SELECT j.job_id
                            FROM sales_followup_jobs j
                            JOIN sales_followup_chains c ON c.chain_id = j.chain_id
                            WHERE c.status = 'active'
                              AND (
                                (
                                    j.status = 'queued'
                                    AND j.scheduled_at <= %s
                                    AND j.next_attempt_at <= %s
                                    AND (j.leased_until IS NULL OR j.leased_until <= %s)
                                )
                                OR (
                                    j.status = 'running'
                                    AND j.leased_until IS NOT NULL
                                    AND j.leased_until <= %s
                                    AND j.send_started_at IS NULL
                                    AND j.sent_at IS NULL
                                )
                              )
                              AND NOT EXISTS (
                                SELECT 1
                                FROM sales_followup_jobs earlier
                                WHERE earlier.chain_id = j.chain_id
                                  AND earlier.step_index < j.step_index
                                  AND earlier.status IN ('queued', 'running')
                              )
                            ORDER BY
                                COALESCE(j.next_attempt_at, j.scheduled_at),
                                j.scheduled_at,
                                j.step_index,
                                j.job_id
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        UPDATE sales_followup_jobs
                        SET status = 'running',
                            worker_id = %s,
                            leased_until = %s,
                            heartbeat_at = %s,
                            updated_at = %s
                        WHERE job_id = (SELECT job_id FROM candidate)
                        RETURNING *
                        """,
                        (
                            current_time,
                            current_time,
                            current_time,
                            current_time,
                            worker_id,
                            lease_until,
                            current_time,
                            current_time,
                        ),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return ClaimSalesFollowupJobResult(ClaimSalesFollowupJobResultStatus.EMPTY, None)
                    return ClaimSalesFollowupJobResult(ClaimSalesFollowupJobResultStatus.CLAIMED, _job_from_row(row))

    def extend_lease(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult:
        worker_id = _required_text(worker_id, "worker_id")
        current_time = _normalize_datetime(now)
        lease_until = _normalize_datetime(lease_until)
        if lease_until <= current_time:
            raise ValueError("lease_until must be after now")
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.NOT_FOUND, None)
                    if job.status != JOB_STATUS_RUNNING or job.leased_until is None:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.INVALID_STATE, job)
                    if job.worker_id != worker_id:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
                    cur.execute(
                        """
                        UPDATE sales_followup_jobs
                        SET leased_until = %s,
                            heartbeat_at = %s,
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (lease_until, current_time, current_time, job.job_id),
                    )
                    return SalesFollowupJobTransitionResult(
                        SalesFollowupJobTransitionStatus.UPDATED,
                        _job_from_row(cur.fetchone()),
                    )

    def mark_send_started(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult:
        worker_id = _required_text(worker_id, "worker_id")
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.NOT_FOUND, None)
                    if job.status in TERMINAL_JOB_STATUSES:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.ALREADY_TERMINAL, job)
                    if job.status != JOB_STATUS_RUNNING:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.INVALID_STATE, job)
                    if job.worker_id != worker_id:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
                    cur.execute(
                        """
                        UPDATE sales_followup_jobs
                        SET send_started_at = COALESCE(send_started_at, %s),
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (current_time, current_time, job.job_id),
                    )
                    return SalesFollowupJobTransitionResult(
                        SalesFollowupJobTransitionStatus.UPDATED,
                        _job_from_row(cur.fetchone()),
                    )

    def mark_sent(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        telegram_message_id: int | None,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult:
        worker_id = _required_text(worker_id, "worker_id")
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.NOT_FOUND, None)
                    if job.status in TERMINAL_JOB_STATUSES:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.ALREADY_TERMINAL, job)
                    if job.status != JOB_STATUS_RUNNING:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.INVALID_STATE, job)
                    if job.worker_id != worker_id:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
                    cur.execute(
                        """
                        UPDATE sales_followup_jobs
                        SET status = 'sent',
                            sent_at = COALESCE(sent_at, %s),
                            finished_at = COALESCE(finished_at, %s),
                            telegram_message_id = COALESCE(%s, telegram_message_id),
                            worker_id = NULL,
                            leased_until = NULL,
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (
                            current_time,
                            current_time,
                            int(telegram_message_id) if telegram_message_id is not None else None,
                            current_time,
                            job.job_id,
                        ),
                    )
                    updated = _job_from_row(cur.fetchone())
                    self._complete_chain_if_no_active_jobs_cur(cur, updated.chain_id, now=current_time)
                    return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def mark_retryable_failure(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        error: str | None,
        next_attempt_at: datetime,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult:
        worker_id = _required_text(worker_id, "worker_id")
        current_time = _normalize_datetime(now)
        next_attempt_at = _normalize_datetime(next_attempt_at)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.NOT_FOUND, None)
                    if job.status in TERMINAL_JOB_STATUSES:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.ALREADY_TERMINAL, job)
                    if job.status != JOB_STATUS_RUNNING:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.INVALID_STATE, job)
                    if job.worker_id != worker_id:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
                    cur.execute(
                        """
                        UPDATE sales_followup_jobs
                        SET status = 'queued',
                            worker_id = NULL,
                            leased_until = NULL,
                            next_attempt_at = %s,
                            attempt_count = attempt_count + 1,
                            send_started_at = NULL,
                            last_error = COALESCE(%s, last_error),
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (next_attempt_at, _optional_text(error), current_time, job.job_id),
                    )
                    return SalesFollowupJobTransitionResult(
                        SalesFollowupJobTransitionStatus.UPDATED,
                        _job_from_row(cur.fetchone()),
                    )

    def mark_failed(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        reason: str | None,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult:
        worker_id = _required_text(worker_id, "worker_id")
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.NOT_FOUND, None)
                    if job.status in TERMINAL_JOB_STATUSES:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.ALREADY_TERMINAL, job)
                    if job.status != JOB_STATUS_RUNNING:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.INVALID_STATE, job)
                    if job.worker_id != worker_id:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
                    cur.execute(
                        """
                        UPDATE sales_followup_jobs
                        SET status = 'failed',
                            worker_id = NULL,
                            leased_until = NULL,
                            failure_reason = COALESCE(%s, failure_reason),
                            last_error = COALESCE(%s, last_error),
                            finished_at = COALESCE(finished_at, %s),
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (_optional_text(reason), _optional_text(reason), current_time, current_time, job.job_id),
                    )
                    updated = _job_from_row(cur.fetchone())
                    self._complete_chain_if_no_active_jobs_cur(cur, updated.chain_id, now=current_time)
                    return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def mark_unknown(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        error: str | None,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult:
        worker_id = _required_text(worker_id, "worker_id")
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.NOT_FOUND, None)
                    if job.status in TERMINAL_JOB_STATUSES:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.ALREADY_TERMINAL, job)
                    if job.status != JOB_STATUS_RUNNING:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.INVALID_STATE, job)
                    if job.worker_id != worker_id:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
                    cur.execute(
                        """
                        UPDATE sales_followup_jobs
                        SET status = 'unknown',
                            worker_id = NULL,
                            leased_until = NULL,
                            last_error = COALESCE(%s, last_error),
                            finished_at = COALESCE(finished_at, %s),
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (_optional_text(error), current_time, current_time, job.job_id),
                    )
                    updated = _job_from_row(cur.fetchone())
                    self._complete_chain_if_no_active_jobs_cur(cur, updated.chain_id, now=current_time)
                    return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def skip_job_and_cancel_chain(
        self,
        job_id: UUID | str,
        *,
        worker_id: str,
        reason: str,
        chain_status: str = CHAIN_STATUS_CANCELLED,
        now: datetime | None = None,
    ) -> SalesFollowupJobTransitionResult:
        worker_id = _required_text(worker_id, "worker_id")
        reason = _required_text(reason, "reason")
        chain_status = _chain_terminal_status(chain_status)
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.NOT_FOUND, None)
                    if job.status in TERMINAL_JOB_STATUSES:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.ALREADY_TERMINAL, job)
                    if job.worker_id is not None and job.worker_id != worker_id:
                        return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.WORKER_MISMATCH, job)
                    cur.execute(
                        """
                        UPDATE sales_followup_jobs
                        SET status = 'skipped',
                            worker_id = NULL,
                            leased_until = NULL,
                            skipped_at = COALESCE(skipped_at, %s),
                            finished_at = COALESCE(finished_at, %s),
                            skip_reason = COALESCE(%s, skip_reason),
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (current_time, current_time, reason, current_time, job.job_id),
                    )
                    updated = _job_from_row(cur.fetchone())
                    cur.execute(
                        """
                        UPDATE sales_followup_jobs
                        SET status = 'cancelled',
                            worker_id = NULL,
                            leased_until = NULL,
                            skipped_at = COALESCE(skipped_at, %s),
                            finished_at = COALESCE(finished_at, %s),
                            skip_reason = COALESCE(%s, skip_reason),
                            updated_at = %s
                        WHERE chain_id = %s
                          AND step_index > %s
                          AND status IN ('queued', 'running')
                        """,
                        (current_time, current_time, reason, current_time, job.chain_id, job.step_index),
                    )
                    cur.execute(
                        """
                        UPDATE sales_followup_chains
                        SET status = %s,
                            cancel_reason = COALESCE(%s, cancel_reason),
                            cancelled_at = COALESCE(cancelled_at, %s),
                            updated_at = %s
                        WHERE chain_id = %s
                        """,
                        (chain_status, reason, current_time, current_time, job.chain_id),
                    )
                    return SalesFollowupJobTransitionResult(SalesFollowupJobTransitionStatus.UPDATED, updated)

    def cancel_active_jobs_for_chat_campaign(
        self,
        *,
        chat_id: int,
        campaign_key: str = DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        reason: str,
        chain_status: str = CHAIN_STATUS_OPTED_OUT,
        now: datetime | None = None,
    ) -> int:
        campaign_key = _required_text(campaign_key, "campaign_key")
        reason = _required_text(reason, "reason")
        chain_status = _chain_terminal_status(chain_status)
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        WITH active_chains AS (
                            SELECT chain_id
                            FROM sales_followup_chains
                            WHERE chat_id = %s
                              AND campaign_key = %s
                              AND status = 'active'
                            FOR UPDATE
                        ),
                        cancelled_jobs AS (
                            UPDATE sales_followup_jobs
                            SET status = 'cancelled',
                                worker_id = NULL,
                                leased_until = NULL,
                                skipped_at = COALESCE(skipped_at, %s),
                                finished_at = COALESCE(finished_at, %s),
                                skip_reason = COALESCE(%s, skip_reason),
                                updated_at = %s
                            WHERE chain_id IN (SELECT chain_id FROM active_chains)
                              AND status IN ('queued', 'running')
                              AND send_started_at IS NULL
                              AND sent_at IS NULL
                            RETURNING job_id
                        ),
                        updated_chains AS (
                            UPDATE sales_followup_chains
                            SET status = %s,
                                cancel_reason = COALESCE(%s, cancel_reason),
                                cancelled_at = COALESCE(cancelled_at, %s),
                                updated_at = %s
                            WHERE chain_id IN (SELECT chain_id FROM active_chains)
                            RETURNING chain_id
                        )
                        SELECT COUNT(*) AS cancelled_count
                        FROM cancelled_jobs
                        """,
                        (
                            int(chat_id),
                            campaign_key,
                            current_time,
                            current_time,
                            reason,
                            current_time,
                            chain_status,
                            reason,
                            current_time,
                            current_time,
                        ),
                    )
                    row = cur.fetchone()
        if row is None:
            return 0
        if isinstance(row, Mapping):
            return int(row["cancelled_count"])
        return int(row[0])

    def set_opt_out(
        self,
        chat_id: int,
        *,
        opt_out_source: str,
        now: datetime | None = None,
    ) -> SalesFollowupPreference:
        opt_out_source = _required_text(opt_out_source, "opt_out_source")
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO sales_followup_preferences (
                            chat_id,
                            opted_out_at,
                            opt_out_source,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (chat_id) DO UPDATE SET
                            opted_out_at = EXCLUDED.opted_out_at,
                            opt_out_source = EXCLUDED.opt_out_source,
                            updated_at = EXCLUDED.updated_at
                        RETURNING *
                        """,
                        (int(chat_id), current_time, opt_out_source, current_time, current_time),
                    )
                    return _preference_from_row(cur.fetchone())

    def get_preference(self, chat_id: int) -> SalesFollowupPreference | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM sales_followup_preferences
                    WHERE chat_id = %s
                    """,
                    (int(chat_id),),
                )
                row = cur.fetchone()
        return _preference_from_row(row) if row is not None else None

    def _ensure_campaign_cur(
        self,
        cur: Any,
        campaign_key: str,
        *,
        version: str,
        disabled_reason: str | None,
    ) -> SalesFollowupCampaign:
        cur.execute(
            """
            INSERT INTO sales_followup_campaigns (
                campaign_key,
                enabled,
                version,
                disabled_reason
            )
            VALUES (%s, false, %s, %s)
            ON CONFLICT (campaign_key) DO UPDATE SET
                version = EXCLUDED.version,
                disabled_reason = COALESCE(
                    sales_followup_campaigns.disabled_reason,
                    EXCLUDED.disabled_reason
                ),
                updated_at = now()
            RETURNING *
            """,
            (campaign_key, version, disabled_reason),
        )
        return _campaign_from_row(cur.fetchone())

    def _get_chain_by_idempotency_key_cur(
        self,
        cur: Any,
        trigger_idempotency_key: str,
    ) -> SalesFollowupChain | None:
        cur.execute(
            """
            SELECT *
            FROM sales_followup_chains
            WHERE trigger_idempotency_key = %s
            """,
            (trigger_idempotency_key,),
        )
        row = cur.fetchone()
        return _chain_from_row(row) if row is not None else None

    def _get_active_chain_for_chat_campaign_cur(
        self,
        cur: Any,
        chat_id: int,
        campaign_key: str,
    ) -> SalesFollowupChain | None:
        cur.execute(
            """
            SELECT *
            FROM sales_followup_chains
            WHERE chat_id = %s
              AND campaign_key = %s
              AND status = 'active'
            ORDER BY created_at, chain_id
            LIMIT 1
            """,
            (int(chat_id), campaign_key),
        )
        row = cur.fetchone()
        return _chain_from_row(row) if row is not None else None

    def _list_jobs_for_chain_cur(self, cur: Any, chain_id: UUID) -> tuple[SalesFollowupJob, ...]:
        cur.execute(
            """
            SELECT *
            FROM sales_followup_jobs
            WHERE chain_id = %s
            ORDER BY step_index, scheduled_at, job_id
            """,
            (chain_id,),
        )
        return tuple(_job_from_row(row) for row in cur.fetchall())

    def _get_job_cur(
        self,
        cur: Any,
        job_id: UUID | str,
        *,
        for_update: bool = False,
    ) -> SalesFollowupJob | None:
        suffix = " FOR UPDATE" if for_update else ""
        cur.execute(f"SELECT * FROM sales_followup_jobs WHERE job_id = %s{suffix}", (_coerce_uuid(job_id),))
        row = cur.fetchone()
        return _job_from_row(row) if row is not None else None

    def _complete_chain_if_no_active_jobs_cur(self, cur: Any, chain_id: UUID, *, now: datetime) -> None:
        cur.execute(
            """
            SELECT 1
            FROM sales_followup_jobs
            WHERE chain_id = %s
              AND status IN ('queued', 'running')
            LIMIT 1
            """,
            (chain_id,),
        )
        if cur.fetchone() is not None:
            return
        cur.execute(
            """
            UPDATE sales_followup_chains
            SET status = 'completed',
                updated_at = %s
            WHERE chain_id = %s
              AND status = 'active'
            """,
            (now, chain_id),
        )

    def _connect(self):
        return self._connection_provider.connect()

    def close(self) -> None:
        self._connection_provider.close()


def _chain_from_row(row: Mapping[str, Any]) -> SalesFollowupChain:
    return SalesFollowupChain(
        chain_id=_coerce_uuid(row["chain_id"]),
        chat_id=int(row["chat_id"]),
        campaign_key=str(row["campaign_key"]),
        trigger_kind=str(row["trigger_kind"]),
        trigger_job_id=_coerce_uuid(row["trigger_job_id"]) if row["trigger_job_id"] is not None else None,
        trigger_idempotency_key=str(row["trigger_idempotency_key"]),
        triggered_at=_normalize_datetime(row["triggered_at"]),
        status=str(row["status"]),
        cancel_reason=_optional_text(row["cancel_reason"]),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
        cancelled_at=_datetime_or_none(row["cancelled_at"]),
    )


def _job_from_row(row: Mapping[str, Any]) -> SalesFollowupJob:
    return SalesFollowupJob(
        job_id=_coerce_uuid(row["job_id"]),
        chain_id=_coerce_uuid(row["chain_id"]),
        chat_id=int(row["chat_id"]),
        campaign_key=str(row["campaign_key"]),
        step_key=str(row["step_key"]),
        step_index=int(row["step_index"]),
        scheduled_at=_normalize_datetime(row["scheduled_at"]),
        next_attempt_at=_normalize_datetime(row["next_attempt_at"]),
        status=str(row["status"]),
        payload=_json_mapping(row["payload_json"]),
        button_set_key=str(row["button_set_key"]),
        send_started_at=_datetime_or_none(row["send_started_at"]),
        sent_at=_datetime_or_none(row["sent_at"]),
        telegram_message_id=int(row["telegram_message_id"]) if row["telegram_message_id"] is not None else None,
        skipped_at=_datetime_or_none(row["skipped_at"]),
        finished_at=_datetime_or_none(row["finished_at"]),
        skip_reason=_optional_text(row["skip_reason"]),
        failure_reason=_optional_text(row["failure_reason"]),
        last_error=_optional_text(row["last_error"]),
        worker_id=_optional_text(row["worker_id"]),
        leased_until=_datetime_or_none(row["leased_until"]),
        attempt_count=int(row["attempt_count"]),
        heartbeat_at=_datetime_or_none(row["heartbeat_at"]),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
    )


def _preference_from_row(row: Mapping[str, Any]) -> SalesFollowupPreference:
    return SalesFollowupPreference(
        chat_id=int(row["chat_id"]),
        opted_out_at=_datetime_or_none(row["opted_out_at"]),
        opt_out_source=_optional_text(row["opt_out_source"]),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
    )


def _campaign_from_row(row: Mapping[str, Any]) -> SalesFollowupCampaign:
    return SalesFollowupCampaign(
        campaign_key=str(row["campaign_key"]),
        enabled=bool(row["enabled"]),
        version=str(row["version"]),
        disabled_reason=_optional_text(row["disabled_reason"]),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
    )


def _json_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        loaded = json.loads(value)
        return dict(loaded or {})
    return dict(value or {})


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _coerce_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _required_text(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _chain_terminal_status(value: str) -> str:
    status = _required_text(value, "chain_status")
    if status not in CHAIN_TERMINAL_STATUSES:
        raise ValueError(f"unsupported sales follow-up chain terminal status: {status}")
    return status


def _normalize_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    return None
