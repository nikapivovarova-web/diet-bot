from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .one_day_generation_jobs import (
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_PARTIAL,
    DELIVERY_STATUS_SEND_STARTED,
    DELIVERY_STATUS_UNKNOWN,
    AdmitJobResult,
    AdmitJobResultStatus,
    CleanupStaleResult,
    FinishJobResult,
    FinishJobResultStatus,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MarkSendStartedResult,
    MarkSendStartedResultStatus,
    MarkValueMessageDeliveredResult,
    MarkValueMessageDeliveredResultStatus,
    OneDayGenerationJob,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    REFUND_STATUS_REFUNDED,
    SetExpectedValueMessagesResult,
    SetExpectedValueMessagesResultStatus,
    StartJobResult,
    StartJobResultStatus,
    TERMINAL_JOB_STATUSES,
    refund_status_for_consumption_source,
)
from .postgres_entitlement_store import ENTITLEMENT_MAP_LOCK_ID
from .postgres_one_day_generation_job_migrations import (
    MIGRATIONS,
    run_one_day_generation_job_schema_migrations,
)
from .postgres_schema_validation import (
    SCHEMA_MIGRATIONS_COLUMNS,
    PostgresSchemaExpectation,
    validate_postgres_schema,
)
from .subscriptions import AttemptConsumption, Entitlement, consume_one_day_attempt, refund_attempt


ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION = PostgresSchemaExpectation(
    component="one-day generation job",
    migration_versions=tuple(migration.version for migration in MIGRATIONS),
    table_columns={
        "schema_migrations": SCHEMA_MIGRATIONS_COLUMNS,
        "one_day_generation_jobs": (
            "job_id",
            "chat_id",
            "idempotency_key",
            "status",
            "consumption_source",
            "refund_status",
            "delivery_status",
            "expected_value_messages",
            "delivered_value_messages",
            "send_started_at",
            "first_value_delivered_at",
            "delivered_at",
            "stale_after",
            "failure_reason",
            "finalization_error",
            "requires_manual_review",
            "metadata_json",
            "created_at",
            "updated_at",
            "started_at",
            "heartbeat_at",
            "finished_at",
        ),
        "one_day_generation_job_value_messages": (
            "job_id",
            "value_message_key",
            "delivered_at",
        ),
    },
    indexes=(
        "idx_one_day_generation_jobs_active_chat_unique",
        "idx_one_day_generation_jobs_idempotency_key_unique",
        "idx_one_day_generation_jobs_stale",
        "idx_one_day_generation_job_value_messages_job",
    ),
    remediation="Run one-day generation job migrations before use.",
)


class PostgresOneDayGenerationJobStore:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = 5,
        connect_attempts: int = 3,
        retry_base_delay: float = 0.2,
        retry_max_delay: float = 1.0,
    ) -> None:
        self.dsn = dsn
        self.connect_timeout = connect_timeout
        self.connect_attempts = max(1, connect_attempts)
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay

    def initialize(self) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    run_one_day_generation_job_schema_migrations(cur)

    def validate_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                validate_postgres_schema(cur, ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION)

    def admit_job(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        stale_after: datetime,
        metadata: Mapping[str, Any] | None = None,
        job_id: UUID | str | None = None,
    ) -> AdmitJobResult:
        idempotency_key = _required_text(idempotency_key, "idempotency_key")
        candidate_job_id = _coerce_uuid(job_id) if job_id is not None else uuid4()
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO one_day_generation_jobs (
                            job_id,
                            chat_id,
                            idempotency_key,
                            status,
                            refund_status,
                            stale_after,
                            metadata_json
                        )
                        VALUES (%s, %s, %s, 'queued', 'not_required', %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING *
                        """,
                        (
                            candidate_job_id,
                            int(chat_id),
                            idempotency_key,
                            _normalize_datetime(stale_after),
                            _jsonb(dict(metadata or {})),
                        ),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        return AdmitJobResult(AdmitJobResultStatus.ADMITTED, _job_from_row(row))

                    existing_idempotency = self._get_job_by_idempotency_key_cur(cur, idempotency_key)
                    if existing_idempotency is not None:
                        return AdmitJobResult(AdmitJobResultStatus.EXISTING_IDEMPOTENCY, existing_idempotency)

                    active_duplicate = self._get_active_job_for_chat_cur(cur, chat_id)
                    if active_duplicate is not None:
                        return AdmitJobResult(AdmitJobResultStatus.ACTIVE_DUPLICATE, active_duplicate)

        raise RuntimeError("One-day generation job admission conflict could not be resolved.")

    def get_job(self, job_id: UUID | str) -> OneDayGenerationJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._get_job_cur(cur, job_id)

    def get_active_job_for_chat(self, chat_id: int) -> OneDayGenerationJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._get_active_job_for_chat_cur(cur, chat_id)

    def start_job_and_consume(
        self,
        job_id: UUID | str,
        *,
        now: datetime | None = None,
        stale_after: datetime | None = None,
        test_access: bool = False,
    ) -> StartJobResult:
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return StartJobResult(StartJobResultStatus.NOT_FOUND, None)
                    if job.status == JOB_STATUS_RUNNING:
                        return StartJobResult(StartJobResultStatus.ALREADY_RUNNING, job)
                    if job.status in TERMINAL_JOB_STATUSES:
                        return StartJobResult(StartJobResultStatus.TERMINAL, job)
                    if job.status != JOB_STATUS_QUEUED:
                        return StartJobResult(StartJobResultStatus.TERMINAL, job)

                    if test_access:
                        consumption_source = "test_access"
                    else:
                        _lock_entitlement_map_cur(cur)
                        entitlement = _load_entitlement_cur(cur, job.chat_id)
                        consumption = consume_one_day_attempt(entitlement, current_time)
                        _upsert_entitlement_cur(cur, job.chat_id, entitlement)

                        if not consumption.allowed:
                            denied_job = self._mark_job_failed_without_refund_cur(
                                cur,
                                job,
                                reason="one_day_entitlement_unavailable",
                                now=current_time,
                            )
                            return StartJobResult(StartJobResultStatus.DENIED, denied_job)
                        consumption_source = consumption.source

                    refund_status = refund_status_for_consumption_source(consumption_source)
                    cur.execute(
                        """
                        UPDATE one_day_generation_jobs
                        SET status = 'running',
                            consumption_source = %s,
                            refund_status = %s,
                            stale_after = %s,
                            started_at = COALESCE(started_at, %s),
                            heartbeat_at = %s,
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (
                            consumption_source,
                            refund_status,
                            _normalize_datetime(stale_after) if stale_after is not None else job.stale_after,
                            current_time,
                            current_time,
                            current_time,
                            job.job_id,
                        ),
                    )
                    return StartJobResult(StartJobResultStatus.STARTED, _job_from_row(cur.fetchone()))

    def heartbeat(
        self,
        job_id: UUID | str,
        *,
        now: datetime | None = None,
        stale_after: datetime | None = None,
    ) -> OneDayGenerationJob | None:
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None or job.status != JOB_STATUS_RUNNING:
                        return job
                    cur.execute(
                        """
                        UPDATE one_day_generation_jobs
                        SET heartbeat_at = %s,
                            stale_after = %s,
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (
                            current_time,
                            _normalize_datetime(stale_after) if stale_after is not None else job.stale_after,
                            current_time,
                            job.job_id,
                        ),
                    )
                    return _job_from_row(cur.fetchone())

    def mark_send_started(self, job_id: UUID | str, *, now: datetime | None = None) -> MarkSendStartedResult:
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return MarkSendStartedResult(MarkSendStartedResultStatus.NOT_FOUND, None)
                    if job.status != JOB_STATUS_RUNNING:
                        return MarkSendStartedResult(MarkSendStartedResultStatus.INVALID_STATE, job)
                    if job.send_started_at is not None:
                        return MarkSendStartedResult(MarkSendStartedResultStatus.ALREADY_SEND_STARTED, job)
                    cur.execute(
                        """
                        UPDATE one_day_generation_jobs
                        SET send_started_at = %s,
                            delivery_status = CASE
                                WHEN first_value_delivered_at IS NULL THEN %s
                                ELSE delivery_status
                            END,
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (current_time, DELIVERY_STATUS_SEND_STARTED, current_time, job.job_id),
                    )
                    return MarkSendStartedResult(
                        MarkSendStartedResultStatus.SEND_STARTED,
                        _job_from_row(cur.fetchone()),
                    )

    def set_expected_value_messages(
        self,
        job_id: UUID | str,
        expected_count: int,
        *,
        now: datetime | None = None,
    ) -> SetExpectedValueMessagesResult:
        expected_count = int(expected_count)
        if expected_count <= 0:
            raise ValueError("expected_count must be positive")
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return SetExpectedValueMessagesResult(SetExpectedValueMessagesResultStatus.NOT_FOUND, None)
                    if job.status != JOB_STATUS_RUNNING:
                        return SetExpectedValueMessagesResult(
                            SetExpectedValueMessagesResultStatus.INVALID_STATE,
                            job,
                        )
                    if job.expected_value_messages == expected_count:
                        return SetExpectedValueMessagesResult(
                            SetExpectedValueMessagesResultStatus.ALREADY_SET,
                            job,
                        )
                    if job.expected_value_messages != 0 or job.delivered_value_messages > expected_count:
                        return SetExpectedValueMessagesResult(
                            SetExpectedValueMessagesResultStatus.INVALID_STATE,
                            job,
                        )
                    cur.execute(
                        """
                        UPDATE one_day_generation_jobs
                        SET expected_value_messages = %s,
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (expected_count, current_time, job.job_id),
                    )
                    return SetExpectedValueMessagesResult(
                        SetExpectedValueMessagesResultStatus.SET,
                        _job_from_row(cur.fetchone()),
                    )

    def mark_value_message_delivered(
        self,
        job_id: UUID | str,
        *,
        value_message_key: str,
        now: datetime | None = None,
    ) -> MarkValueMessageDeliveredResult:
        value_message_key = _required_text(value_message_key, "value_message_key")
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return MarkValueMessageDeliveredResult(
                            MarkValueMessageDeliveredResultStatus.NOT_FOUND,
                            None,
                        )
                    if job.status != JOB_STATUS_RUNNING or job.expected_value_messages <= 0:
                        return MarkValueMessageDeliveredResult(
                            MarkValueMessageDeliveredResultStatus.INVALID_STATE,
                            job,
                        )
                    if job.delivered_value_messages >= job.expected_value_messages:
                        if self._value_message_delivery_exists_cur(cur, job.job_id, value_message_key):
                            return MarkValueMessageDeliveredResult(
                                MarkValueMessageDeliveredResultStatus.ALREADY_DELIVERED,
                                job,
                            )
                        return MarkValueMessageDeliveredResult(
                            MarkValueMessageDeliveredResultStatus.ALREADY_COMPLETE,
                            job,
                        )
                    cur.execute(
                        """
                        INSERT INTO one_day_generation_job_value_messages (
                            job_id,
                            value_message_key,
                            delivered_at
                        )
                        VALUES (%s, %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING delivered_at
                        """,
                        (job.job_id, value_message_key, current_time),
                    )
                    inserted = cur.fetchone()
                    if inserted is None:
                        return MarkValueMessageDeliveredResult(
                            MarkValueMessageDeliveredResultStatus.ALREADY_DELIVERED,
                            job,
                        )

                    delivered_count = job.delivered_value_messages + 1
                    delivery_complete = delivered_count >= job.expected_value_messages
                    cur.execute(
                        """
                        UPDATE one_day_generation_jobs
                        SET delivered_value_messages = %s,
                            first_value_delivered_at = COALESCE(first_value_delivered_at, %s),
                            delivered_at = CASE WHEN %s THEN COALESCE(delivered_at, %s) ELSE delivered_at END,
                            delivery_status = %s,
                            requires_manual_review = false,
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (
                            delivered_count,
                            current_time,
                            delivery_complete,
                            current_time,
                            DELIVERY_STATUS_DELIVERED if delivery_complete else DELIVERY_STATUS_PARTIAL,
                            current_time,
                            job.job_id,
                        ),
                    )
                    return MarkValueMessageDeliveredResult(
                        MarkValueMessageDeliveredResultStatus.DELIVERED,
                        _job_from_row(cur.fetchone()),
                    )

    def finish_success(self, job_id: UUID | str, *, now: datetime | None = None) -> FinishJobResult:
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return FinishJobResult(FinishJobResultStatus.NOT_FOUND, None)
                    if job.status in TERMINAL_JOB_STATUSES:
                        return FinishJobResult(FinishJobResultStatus.ALREADY_TERMINAL, job)
                    if job.status != JOB_STATUS_RUNNING:
                        return FinishJobResult(FinishJobResultStatus.INVALID_STATE, job)
                    if job.expected_value_messages <= 0 or job.delivered_value_messages < job.expected_value_messages:
                        return FinishJobResult(FinishJobResultStatus.INVALID_STATE, job)
                    cur.execute(
                        """
                        UPDATE one_day_generation_jobs
                        SET status = 'succeeded',
                            refund_status = 'not_required',
                            delivery_status = %s,
                            requires_manual_review = false,
                            delivered_at = COALESCE(delivered_at, %s),
                            finished_at = COALESCE(finished_at, %s),
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (DELIVERY_STATUS_DELIVERED, current_time, current_time, current_time, job.job_id),
                    )
                    return FinishJobResult(FinishJobResultStatus.SUCCEEDED, _job_from_row(cur.fetchone()))

    def finish_failure_and_refund_once(
        self,
        job_id: UUID | str,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> FinishJobResult:
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return FinishJobResult(FinishJobResultStatus.NOT_FOUND, None)
                    return self._finish_failure_and_refund_once_cur(
                        cur,
                        job,
                        reason=reason,
                        now=current_time,
                    )

    def cancel_queued(
        self,
        job_id: UUID | str,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> FinishJobResult:
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return FinishJobResult(FinishJobResultStatus.NOT_FOUND, None)
                    if job.status in TERMINAL_JOB_STATUSES:
                        return FinishJobResult(FinishJobResultStatus.ALREADY_TERMINAL, job)
                    if job.status != JOB_STATUS_QUEUED:
                        return FinishJobResult(FinishJobResultStatus.INVALID_STATE, job)
                    return FinishJobResult(
                        FinishJobResultStatus.CANCELLED,
                        self._cancel_queued_job_cur(cur, job, reason=reason, now=current_time),
                    )

    def list_stale_candidates(self, *, now: datetime | None = None, limit: int = 100) -> list[OneDayGenerationJob]:
        current_time = _normalize_datetime(now)
        bounded_limit = min(500, max(1, int(limit)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM one_day_generation_jobs
                    WHERE status IN ('queued', 'running')
                      AND stale_after <= %s
                    ORDER BY stale_after, created_at, job_id
                    LIMIT %s
                    """,
                    (current_time, bounded_limit),
                )
                return [_job_from_row(row) for row in cur.fetchall()]

    def cleanup_stale(
        self,
        *,
        chat_id: int,
        now: datetime | None = None,
        limit: int = 10,
    ) -> CleanupStaleResult:
        current_time = _normalize_datetime(now)
        bounded_limit = min(25, max(1, int(limit)))
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT *
                        FROM one_day_generation_jobs
                        WHERE chat_id = %s
                          AND status IN ('queued', 'running')
                          AND stale_after <= %s
                        ORDER BY stale_after, created_at, job_id
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                        """,
                        (int(chat_id), current_time, bounded_limit),
                    )
                    stale_jobs = [_job_from_row(row) for row in cur.fetchall()]
                    job_results: list[FinishJobResult] = []
                    for job in stale_jobs:
                        if job.status == JOB_STATUS_QUEUED:
                            job_results.append(
                                FinishJobResult(
                                    FinishJobResultStatus.CANCELLED,
                                    self._cancel_queued_job_cur(
                                        cur,
                                        job,
                                        reason="one_day_generation_job_stale",
                                        now=current_time,
                                    ),
                                )
                            )
                        elif job.status == JOB_STATUS_RUNNING:
                            if (
                                job.expected_value_messages > 0
                                and job.delivered_value_messages >= job.expected_value_messages
                            ):
                                job_results.append(
                                    FinishJobResult(
                                        FinishJobResultStatus.SUCCEEDED,
                                        self._finish_delivered_job_cur(
                                            cur,
                                            job,
                                            finalization_error="stale_after_complete_delivery",
                                            now=current_time,
                                        ),
                                    )
                                )
                            else:
                                job_results.append(
                                    self._finish_failure_and_refund_once_cur(
                                        cur,
                                        job,
                                        reason="one_day_generation_job_stale",
                                        now=current_time,
                                    )
                                )
                    return CleanupStaleResult(job_results)

    def _get_job_by_idempotency_key_cur(self, cur: Any, idempotency_key: str) -> OneDayGenerationJob | None:
        cur.execute(
            """
            SELECT *
            FROM one_day_generation_jobs
            WHERE idempotency_key = %s
            """,
            (idempotency_key,),
        )
        row = cur.fetchone()
        return _job_from_row(row) if row is not None else None

    def _get_active_job_for_chat_cur(self, cur: Any, chat_id: int) -> OneDayGenerationJob | None:
        cur.execute(
            """
            SELECT *
            FROM one_day_generation_jobs
            WHERE chat_id = %s
              AND status IN ('queued', 'running')
            ORDER BY created_at, job_id
            LIMIT 1
            """,
            (int(chat_id),),
        )
        row = cur.fetchone()
        return _job_from_row(row) if row is not None else None

    def _get_job_cur(self, cur: Any, job_id: UUID | str, *, for_update: bool = False) -> OneDayGenerationJob | None:
        suffix = " FOR UPDATE" if for_update else ""
        cur.execute(f"SELECT * FROM one_day_generation_jobs WHERE job_id = %s{suffix}", (_coerce_uuid(job_id),))
        row = cur.fetchone()
        return _job_from_row(row) if row is not None else None

    def _value_message_delivery_exists_cur(
        self,
        cur: Any,
        job_id: UUID,
        value_message_key: str,
    ) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM one_day_generation_job_value_messages
            WHERE job_id = %s
              AND value_message_key = %s
            """,
            (job_id, value_message_key),
        )
        return cur.fetchone() is not None

    def _cancel_queued_job_cur(
        self,
        cur: Any,
        job: OneDayGenerationJob,
        *,
        reason: str | None = None,
        now: datetime,
    ) -> OneDayGenerationJob:
        cur.execute(
            """
            UPDATE one_day_generation_jobs
            SET status = 'cancelled',
                refund_status = 'not_required',
                failure_reason = COALESCE(%s, failure_reason),
                finished_at = COALESCE(finished_at, %s),
                updated_at = %s
            WHERE job_id = %s
            RETURNING *
            """,
            (_optional_text(reason), now, now, job.job_id),
        )
        return _job_from_row(cur.fetchone())

    def _mark_job_failed_without_refund_cur(
        self,
        cur: Any,
        job: OneDayGenerationJob,
        *,
        reason: str | None,
        now: datetime,
    ) -> OneDayGenerationJob:
        cur.execute(
            """
            UPDATE one_day_generation_jobs
            SET status = 'failed',
                refund_status = 'not_required',
                failure_reason = COALESCE(%s, failure_reason),
                finished_at = COALESCE(finished_at, %s),
                updated_at = %s
            WHERE job_id = %s
            RETURNING *
            """,
            (_optional_text(reason), now, now, job.job_id),
        )
        return _job_from_row(cur.fetchone())

    def _finish_delivered_job_cur(
        self,
        cur: Any,
        job: OneDayGenerationJob,
        *,
        finalization_error: str | None,
        now: datetime,
    ) -> OneDayGenerationJob:
        cur.execute(
            """
            UPDATE one_day_generation_jobs
            SET status = %s,
                refund_status = 'not_required',
                finalization_error = COALESCE(%s, finalization_error),
                delivery_status = %s,
                requires_manual_review = false,
                delivered_at = COALESCE(delivered_at, %s),
                finished_at = COALESCE(finished_at, %s),
                updated_at = %s
            WHERE job_id = %s
            RETURNING *
            """,
            (
                JOB_STATUS_SUCCEEDED,
                _optional_text(finalization_error),
                DELIVERY_STATUS_DELIVERED,
                now,
                now,
                now,
                job.job_id,
            ),
        )
        return _job_from_row(cur.fetchone())

    def _finish_partial_delivery_failure_cur(
        self,
        cur: Any,
        job: OneDayGenerationJob,
        *,
        reason: str | None,
        now: datetime,
    ) -> OneDayGenerationJob:
        cur.execute(
            """
            UPDATE one_day_generation_jobs
            SET status = 'failed',
                refund_status = 'not_required',
                finalization_error = COALESCE(%s, finalization_error),
                delivery_status = %s,
                requires_manual_review = true,
                finished_at = COALESCE(finished_at, %s),
                updated_at = %s
            WHERE job_id = %s
            RETURNING *
            """,
            (_optional_text(reason), DELIVERY_STATUS_UNKNOWN, now, now, job.job_id),
        )
        return _job_from_row(cur.fetchone())

    def _finish_failure_and_refund_once_cur(
        self,
        cur: Any,
        job: OneDayGenerationJob,
        *,
        reason: str | None,
        now: datetime,
    ) -> FinishJobResult:
        if job.status in TERMINAL_JOB_STATUSES:
            return FinishJobResult(FinishJobResultStatus.ALREADY_TERMINAL, job)
        if job.expected_value_messages > 0 and job.delivered_value_messages >= job.expected_value_messages:
            return FinishJobResult(
                FinishJobResultStatus.SUCCEEDED,
                self._finish_delivered_job_cur(
                    cur,
                    job,
                    finalization_error=reason,
                    now=now,
                ),
            )
        if job.first_value_delivered_at is not None or job.delivered_value_messages > 0:
            return FinishJobResult(
                FinishJobResultStatus.FAILED,
                self._finish_partial_delivery_failure_cur(
                    cur,
                    job,
                    reason=reason,
                    now=now,
                ),
            )

        refund_status = job.refund_status
        if job.refund_status == REFUND_STATUS_PENDING and job.consumption_source in {"monthly", "extra", "free_trial"}:
            _lock_entitlement_map_cur(cur)
            entitlement = _load_entitlement_cur(cur, job.chat_id)
            refund_attempt(
                entitlement,
                AttemptConsumption(True, "one_day", job.consumption_source),
            )
            _upsert_entitlement_cur(cur, job.chat_id, entitlement)
            refund_status = REFUND_STATUS_REFUNDED
        elif job.refund_status != REFUND_STATUS_REFUNDED:
            refund_status = REFUND_STATUS_NOT_REQUIRED

        cur.execute(
            """
            UPDATE one_day_generation_jobs
            SET status = 'failed',
                refund_status = %s,
                failure_reason = COALESCE(%s, failure_reason),
                finished_at = COALESCE(finished_at, %s),
                updated_at = %s
            WHERE job_id = %s
            RETURNING *
            """,
            (refund_status, _optional_text(reason), now, now, job.job_id),
        )
        return FinishJobResult(FinishJobResultStatus.FAILED, _job_from_row(cur.fetchone()))

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install PostgreSQL driver with `pip install psycopg[binary]`.") from exc

        last_error: Exception | None = None
        for attempt in range(1, self.connect_attempts + 1):
            try:
                return psycopg.connect(
                    self.dsn,
                    row_factory=dict_row,
                    connect_timeout=self.connect_timeout,
                )
            except psycopg.OperationalError as exc:
                last_error = exc
                if attempt >= self.connect_attempts:
                    break
                delay = min(self.retry_max_delay, self.retry_base_delay * (2 ** (attempt - 1)))
                time.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Could not connect to PostgreSQL.")


def _lock_entitlement_map_cur(cur: Any) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (ENTITLEMENT_MAP_LOCK_ID,))


def _load_entitlement_cur(cur: Any, chat_id: int) -> Entitlement:
    cur.execute(
        """
        SELECT
            chat_id,
            free_trial_used,
            subscription_period_start,
            subscription_period_end,
            test_access_until,
            test_access_enabled,
            monthly_one_day_remaining,
            monthly_weekly_pdf_remaining,
            extra_one_day_remaining,
            extra_weekly_pdf_remaining
        FROM entitlements
        WHERE chat_id = %s
        FOR UPDATE
        """,
        (int(chat_id),),
    )
    row = cur.fetchone()
    if row is None:
        return Entitlement()
    entitlement = Entitlement(
        free_trial_used=bool(row["free_trial_used"]),
        subscription_period_start=_optional_text(row["subscription_period_start"]),
        subscription_period_end=_optional_text(row["subscription_period_end"]),
        test_access_until=_optional_text(row["test_access_until"]),
        test_access_enabled=bool(row["test_access_enabled"]),
        monthly_one_day_remaining=int(row["monthly_one_day_remaining"]),
        monthly_weekly_pdf_remaining=int(row["monthly_weekly_pdf_remaining"]),
        extra_one_day_remaining=int(row["extra_one_day_remaining"]),
        extra_weekly_pdf_remaining=int(row["extra_weekly_pdf_remaining"]),
        processed_payment_charge_ids=[],
    )
    cur.execute(
        """
        SELECT charge_id
        FROM entitlement_processed_charge_ids
        WHERE chat_id = %s
        ORDER BY position, recorded_at, charge_id
        """,
        (int(chat_id),),
    )
    entitlement.processed_payment_charge_ids = [str(item["charge_id"]) for item in cur.fetchall()]
    return entitlement


def _upsert_entitlement_cur(cur: Any, chat_id: int, entitlement: Entitlement) -> None:
    cur.execute(
        """
        INSERT INTO entitlements (
            chat_id,
            free_trial_used,
            subscription_period_start,
            subscription_period_end,
            test_access_until,
            test_access_enabled,
            monthly_one_day_remaining,
            monthly_weekly_pdf_remaining,
            extra_one_day_remaining,
            extra_weekly_pdf_remaining
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chat_id) DO UPDATE SET
            free_trial_used = EXCLUDED.free_trial_used,
            subscription_period_start = EXCLUDED.subscription_period_start,
            subscription_period_end = EXCLUDED.subscription_period_end,
            test_access_until = EXCLUDED.test_access_until,
            test_access_enabled = EXCLUDED.test_access_enabled,
            monthly_one_day_remaining = EXCLUDED.monthly_one_day_remaining,
            monthly_weekly_pdf_remaining = EXCLUDED.monthly_weekly_pdf_remaining,
            extra_one_day_remaining = EXCLUDED.extra_one_day_remaining,
            extra_weekly_pdf_remaining = EXCLUDED.extra_weekly_pdf_remaining,
            updated_at = now(),
            version = entitlements.version + 1
        """,
        (
            int(chat_id),
            entitlement.free_trial_used,
            entitlement.subscription_period_start,
            entitlement.subscription_period_end,
            entitlement.test_access_until,
            entitlement.test_access_enabled,
            entitlement.monthly_one_day_remaining,
            entitlement.monthly_weekly_pdf_remaining,
            entitlement.extra_one_day_remaining,
            entitlement.extra_weekly_pdf_remaining,
        ),
    )
    cur.execute("DELETE FROM entitlement_processed_charge_ids WHERE chat_id = %s", (int(chat_id),))
    for position, charge_id in enumerate(_unique_charge_ids(entitlement.processed_payment_charge_ids)):
        cur.execute(
            """
            INSERT INTO entitlement_processed_charge_ids (chat_id, charge_id, position)
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id, charge_id) DO UPDATE SET
                position = EXCLUDED.position
            """,
            (int(chat_id), charge_id, position),
        )


def _job_from_row(row: Any) -> OneDayGenerationJob:
    return OneDayGenerationJob(
        job_id=_coerce_uuid(row["job_id"]),
        chat_id=int(row["chat_id"]),
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),
        consumption_source=_optional_text(row["consumption_source"]),
        refund_status=str(row["refund_status"]),
        delivery_status=str(row["delivery_status"]),
        expected_value_messages=int(row["expected_value_messages"]),
        delivered_value_messages=int(row["delivered_value_messages"]),
        stale_after=_normalize_datetime(row["stale_after"]),
        metadata=dict(row["metadata_json"] or {}),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
        started_at=_datetime_or_none(row["started_at"]),
        heartbeat_at=_datetime_or_none(row["heartbeat_at"]),
        finished_at=_datetime_or_none(row["finished_at"]),
        send_started_at=_datetime_or_none(row["send_started_at"]),
        first_value_delivered_at=_datetime_or_none(row["first_value_delivered_at"]),
        delivered_at=_datetime_or_none(row["delivered_at"]),
        failure_reason=_optional_text(row["failure_reason"]),
        finalization_error=_optional_text(row["finalization_error"]),
        requires_manual_review=bool(row["requires_manual_review"]),
    )


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


def _unique_charge_ids(charge_ids: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for charge_id in charge_ids:
        text = str(charge_id).strip()
        if not text or text in seen:
            continue
        unique.append(text)
        seen.add(text)
    return unique


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)
