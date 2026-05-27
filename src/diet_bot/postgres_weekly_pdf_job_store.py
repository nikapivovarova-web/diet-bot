from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .postgres_connection import DirectPostgresConnectionProvider, PostgresConnectionProvider
from .postgres_entitlement_store import ENTITLEMENT_MAP_LOCK_ID
from .postgres_schema_validation import (
    SCHEMA_MIGRATIONS_COLUMNS,
    PostgresSchemaExpectation,
    validate_postgres_schema,
)
from .postgres_weekly_pdf_job_migrations import MIGRATIONS, run_weekly_pdf_job_schema_migrations
from .subscriptions import AttemptConsumption, Entitlement, consume_weekly_pdf_attempt, refund_attempt
from .weekly_pdf_jobs import (
    AdmitJobResult,
    AdmitJobResultStatus,
    CleanupStaleResult,
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_SEND_STARTED,
    DELIVERY_STATUS_UNKNOWN,
    FinishJobResult,
    FinishJobResultStatus,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MarkDeliveredResult,
    MarkDeliveredResultStatus,
    MarkSendStartedResult,
    MarkSendStartedResultStatus,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    REFUND_STATUS_REFUNDED,
    StartJobResult,
    StartJobResultStatus,
    TERMINAL_JOB_STATUSES,
    WeeklyPdfJob,
    refund_status_for_consumption_source,
)


WEEKLY_PDF_JOB_SCHEMA_EXPECTATION = PostgresSchemaExpectation(
    component="weekly PDF job",
    migration_versions=tuple(migration.version for migration in MIGRATIONS),
    table_columns={
        "schema_migrations": SCHEMA_MIGRATIONS_COLUMNS,
        "weekly_pdf_jobs": (
            "job_id",
            "chat_id",
            "idempotency_key",
            "status",
            "refund_status",
            "consumption_source",
            "stale_after",
            "metadata_json",
            "failure_reason",
            "send_started_at",
            "delivered_at",
            "finalization_error",
            "delivery_status",
            "requires_manual_review",
            "manual_review_reason",
            "manual_reviewed_at",
            "manual_review_resolution",
            "created_at",
            "updated_at",
            "started_at",
            "heartbeat_at",
            "finished_at",
        ),
    },
    indexes=(
        "idx_weekly_pdf_jobs_active_chat_unique",
        "idx_weekly_pdf_jobs_idempotency_key_unique",
        "idx_weekly_pdf_jobs_stale",
    ),
    remediation="Run weekly PDF job migrations before use.",
)


class PostgresWeeklyPdfJobStore:
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
                    run_weekly_pdf_job_schema_migrations(cur)

    def validate_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                validate_postgres_schema(cur, WEEKLY_PDF_JOB_SCHEMA_EXPECTATION)

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
                        INSERT INTO weekly_pdf_jobs (
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

        raise RuntimeError("Weekly PDF job admission conflict could not be resolved.")

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
                        consumption = consume_weekly_pdf_attempt(entitlement, current_time)
                        _upsert_entitlement_cur(cur, job.chat_id, entitlement)

                        if not consumption.allowed:
                            denied_job = self._mark_job_failed_without_refund_cur(
                                cur,
                                job,
                                reason="weekly_pdf_entitlement_unavailable",
                                now=current_time,
                            )
                            return StartJobResult(StartJobResultStatus.DENIED, denied_job)
                        consumption_source = consumption.source

                    refund_status = refund_status_for_consumption_source(consumption_source)
                    cur.execute(
                        """
                        UPDATE weekly_pdf_jobs
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
    ) -> WeeklyPdfJob | None:
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None or job.status != JOB_STATUS_RUNNING:
                        return job
                    cur.execute(
                        """
                        UPDATE weekly_pdf_jobs
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

    def mark_delivered(self, job_id: UUID | str, *, now: datetime | None = None) -> MarkDeliveredResult:
        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = self._get_job_cur(cur, job_id, for_update=True)
                    if job is None:
                        return MarkDeliveredResult(MarkDeliveredResultStatus.NOT_FOUND, None)
                    if job.status != JOB_STATUS_RUNNING:
                        return MarkDeliveredResult(MarkDeliveredResultStatus.INVALID_STATE, job)
                    if job.delivered_at is not None:
                        return MarkDeliveredResult(MarkDeliveredResultStatus.ALREADY_DELIVERED, job)
                    cur.execute(
                        """
                        UPDATE weekly_pdf_jobs
                        SET delivered_at = %s,
                            delivery_status = %s,
                            requires_manual_review = false,
                            manual_review_reason = NULL,
                            manual_reviewed_at = NULL,
                            manual_review_resolution = NULL,
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (current_time, DELIVERY_STATUS_DELIVERED, current_time, job.job_id),
                    )
                    return MarkDeliveredResult(MarkDeliveredResultStatus.DELIVERED, _job_from_row(cur.fetchone()))

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
                        UPDATE weekly_pdf_jobs
                        SET send_started_at = %s,
                            delivery_status = %s,
                            requires_manual_review = false,
                            manual_review_reason = NULL,
                            manual_reviewed_at = NULL,
                            manual_review_resolution = NULL,
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
                    cur.execute(
                        """
                        UPDATE weekly_pdf_jobs
                        SET status = 'succeeded',
                            refund_status = 'not_required',
                            delivery_status = CASE
                                WHEN delivered_at IS NOT NULL THEN %s
                                WHEN send_started_at IS NOT NULL THEN %s
                                ELSE delivery_status
                            END,
                            requires_manual_review = CASE
                                WHEN delivered_at IS NOT NULL THEN false
                                WHEN send_started_at IS NOT NULL THEN true
                                ELSE false
                            END,
                            manual_review_reason = CASE
                                WHEN delivered_at IS NOT NULL THEN NULL
                                WHEN send_started_at IS NOT NULL THEN COALESCE(
                                    NULLIF(finalization_error, ''),
                                    'send_started_without_delivery_confirmation'
                                )
                                ELSE NULL
                            END,
                            manual_reviewed_at = CASE
                                WHEN delivered_at IS NOT NULL OR send_started_at IS NOT NULL THEN NULL
                                ELSE manual_reviewed_at
                            END,
                            manual_review_resolution = CASE
                                WHEN delivered_at IS NOT NULL OR send_started_at IS NOT NULL THEN NULL
                                ELSE manual_review_resolution
                            END,
                            finished_at = COALESCE(finished_at, %s),
                            updated_at = %s
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (
                            DELIVERY_STATUS_DELIVERED,
                            DELIVERY_STATUS_UNKNOWN,
                            current_time,
                            current_time,
                            job.job_id,
                        ),
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
                        FROM weekly_pdf_jobs
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
                                    self._cancel_queued_job_cur(cur, job, reason="weekly_pdf_job_stale", now=current_time),
                                )
                            )
                        elif job.status == JOB_STATUS_RUNNING:
                            if job.delivered_at is not None:
                                job_results.append(
                                    FinishJobResult(
                                        FinishJobResultStatus.SUCCEEDED,
                                        self._finish_delivered_job_cur(
                                            cur,
                                            job,
                                            finalization_error="stale_after_delivery",
                                            now=current_time,
                                        ),
                                    )
                                )
                            else:
                                if job.send_started_at is not None:
                                    job_results.append(
                                        FinishJobResult(
                                            FinishJobResultStatus.SUCCEEDED,
                                            self._finish_send_started_unconfirmed_job_cur(
                                                cur,
                                                job,
                                                finalization_error="stale_after_send_attempt_unconfirmed",
                                                now=current_time,
                                            ),
                                        )
                                    )
                                else:
                                    job_results.append(
                                        self._finish_failure_and_refund_once_cur(
                                            cur,
                                            job,
                                            reason="weekly_pdf_job_stale",
                                            now=current_time,
                                        )
                                    )
                    return CleanupStaleResult(job_results)

    def get_active_job_for_chat(self, chat_id: int) -> WeeklyPdfJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._get_active_job_for_chat_cur(cur, chat_id)

    def get_unresolved_manual_review_jobs(self, *, limit: int = 100) -> list[WeeklyPdfJob]:
        return self.get_manual_review_jobs(limit=limit, include_reviewed=False)

    def get_manual_review_jobs(self, *, limit: int = 100, include_reviewed: bool = False) -> list[WeeklyPdfJob]:
        bounded_limit = min(500, max(1, int(limit)))
        reviewed_filter = "" if include_reviewed else "AND manual_reviewed_at IS NULL"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM weekly_pdf_jobs
                    WHERE requires_manual_review = true
                      {reviewed_filter}
                    ORDER BY
                        CASE WHEN manual_reviewed_at IS NULL THEN 0 ELSE 1 END,
                        updated_at,
                        created_at,
                        job_id
                    LIMIT %s
                    """,
                    (bounded_limit,),
                )
                return [_job_from_row(row) for row in cur.fetchall()]

    def _get_job_by_idempotency_key(self, idempotency_key: str) -> WeeklyPdfJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._get_job_by_idempotency_key_cur(cur, idempotency_key)

    def _get_active_job_for_chat_cur(self, cur: Any, chat_id: int) -> WeeklyPdfJob | None:
        cur.execute(
            """
            SELECT *
            FROM weekly_pdf_jobs
            WHERE chat_id = %s
              AND status IN ('queued', 'running')
            ORDER BY created_at, job_id
            LIMIT 1
            """,
            (int(chat_id),),
        )
        row = cur.fetchone()
        return _job_from_row(row) if row is not None else None

    def _get_job_by_idempotency_key_cur(self, cur: Any, idempotency_key: str) -> WeeklyPdfJob | None:
        cur.execute(
            """
            SELECT *
            FROM weekly_pdf_jobs
            WHERE idempotency_key = %s
            """,
            (idempotency_key,),
        )
        row = cur.fetchone()
        return _job_from_row(row) if row is not None else None

    def _get_job_cur(self, cur: Any, job_id: UUID | str, *, for_update: bool = False) -> WeeklyPdfJob | None:
        suffix = " FOR UPDATE" if for_update else ""
        cur.execute(f"SELECT * FROM weekly_pdf_jobs WHERE job_id = %s{suffix}", (_coerce_uuid(job_id),))
        row = cur.fetchone()
        return _job_from_row(row) if row is not None else None

    def _cancel_queued_job_cur(
        self,
        cur: Any,
        job: WeeklyPdfJob,
        *,
        reason: str | None = None,
        now: datetime,
    ) -> WeeklyPdfJob:
        cur.execute(
            """
            UPDATE weekly_pdf_jobs
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
        job: WeeklyPdfJob,
        *,
        reason: str | None,
        now: datetime,
    ) -> WeeklyPdfJob:
        cur.execute(
            """
            UPDATE weekly_pdf_jobs
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
        job: WeeklyPdfJob,
        *,
        finalization_error: str | None,
        now: datetime,
    ) -> WeeklyPdfJob:
        cur.execute(
            """
            UPDATE weekly_pdf_jobs
            SET status = %s,
                refund_status = 'not_required',
                finalization_error = COALESCE(%s, finalization_error),
                delivery_status = %s,
                requires_manual_review = false,
                manual_review_reason = NULL,
                manual_reviewed_at = NULL,
                manual_review_resolution = NULL,
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
                job.job_id,
            ),
        )
        return _job_from_row(cur.fetchone())

    def _finish_send_started_unconfirmed_job_cur(
        self,
        cur: Any,
        job: WeeklyPdfJob,
        *,
        finalization_error: str | None,
        now: datetime,
    ) -> WeeklyPdfJob:
        cur.execute(
            """
            UPDATE weekly_pdf_jobs
            SET status = %s,
                refund_status = 'not_required',
                finalization_error = COALESCE(%s, finalization_error),
                delivery_status = %s,
                requires_manual_review = true,
                manual_review_reason = COALESCE(
                    NULLIF(%s, ''),
                    NULLIF(finalization_error, ''),
                    'send_started_without_delivery_confirmation'
                ),
                manual_reviewed_at = NULL,
                manual_review_resolution = NULL,
                finished_at = COALESCE(finished_at, %s),
                updated_at = %s
            WHERE job_id = %s
            RETURNING *
            """,
            (
                JOB_STATUS_SUCCEEDED,
                _optional_text(finalization_error),
                DELIVERY_STATUS_UNKNOWN,
                _optional_text(finalization_error),
                now,
                now,
                job.job_id,
            ),
        )
        return _job_from_row(cur.fetchone())

    def _finish_failure_and_refund_once_cur(
        self,
        cur: Any,
        job: WeeklyPdfJob,
        *,
        reason: str | None,
        now: datetime,
    ) -> FinishJobResult:
        if job.status in TERMINAL_JOB_STATUSES:
            return FinishJobResult(FinishJobResultStatus.ALREADY_TERMINAL, job)
        if job.delivered_at is not None:
            return FinishJobResult(
                FinishJobResultStatus.SUCCEEDED,
                self._finish_delivered_job_cur(
                    cur,
                    job,
                    finalization_error=reason,
                    now=now,
                ),
            )
        if job.send_started_at is not None:
            return FinishJobResult(
                FinishJobResultStatus.SUCCEEDED,
                self._finish_send_started_unconfirmed_job_cur(
                    cur,
                    job,
                    finalization_error=reason,
                    now=now,
                ),
            )

        refund_status = job.refund_status
        if job.refund_status == REFUND_STATUS_PENDING and job.consumption_source in {"monthly", "extra"}:
            _lock_entitlement_map_cur(cur)
            entitlement = _load_entitlement_cur(cur, job.chat_id)
            refund_attempt(
                entitlement,
                AttemptConsumption(True, "weekly_pdf", job.consumption_source),
            )
            _upsert_entitlement_cur(cur, job.chat_id, entitlement)
            refund_status = REFUND_STATUS_REFUNDED
        elif job.refund_status != REFUND_STATUS_REFUNDED:
            refund_status = REFUND_STATUS_NOT_REQUIRED

        cur.execute(
            """
            UPDATE weekly_pdf_jobs
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
        return self._connection_provider.connect()

    def close(self) -> None:
        self._connection_provider.close()


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


def _job_from_row(row: Any) -> WeeklyPdfJob:
    return WeeklyPdfJob(
        job_id=_coerce_uuid(row["job_id"]),
        chat_id=int(row["chat_id"]),
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),
        refund_status=str(row["refund_status"]),
        consumption_source=_optional_text(row["consumption_source"]),
        stale_after=_normalize_datetime(row["stale_after"]),
        metadata=dict(row["metadata_json"] or {}),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
        started_at=_datetime_or_none(row["started_at"]),
        heartbeat_at=_datetime_or_none(row["heartbeat_at"]),
        finished_at=_datetime_or_none(row["finished_at"]),
        failure_reason=_optional_text(row["failure_reason"]),
        send_started_at=_datetime_or_none(row["send_started_at"]),
        delivered_at=_datetime_or_none(row["delivered_at"]),
        finalization_error=_optional_text(row["finalization_error"]),
        delivery_status=str(row["delivery_status"]),
        requires_manual_review=bool(row["requires_manual_review"]),
        manual_review_reason=_optional_text(row["manual_review_reason"]),
        manual_reviewed_at=_datetime_or_none(row["manual_reviewed_at"]),
        manual_review_resolution=_optional_text(row["manual_review_resolution"]),
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
