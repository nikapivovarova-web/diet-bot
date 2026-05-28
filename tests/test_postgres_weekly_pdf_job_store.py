from __future__ import annotations

import os
import re
import shlex
import uuid
from inspect import signature
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pytest

import diet_bot.postgres_weekly_pdf_job_store as weekly_pdf_job_store
from diet_bot.postgres_chat_state_store import PostgresChatStateStore
from diet_bot.postgres_entitlement_store import PostgresEntitlementStore
from diet_bot.postgres_weekly_pdf_job_migrations import MIGRATIONS, SCHEMA_MIGRATIONS_SQL
from diet_bot.postgres_weekly_pdf_job_store import PostgresWeeklyPdfJobStore, WEEKLY_PDF_JOB_SCHEMA_EXPECTATION
from diet_bot.subscriptions import Entitlement, apply_subscription_payment, grant_test_access
from diet_bot.weekly_pdf_jobs import (
    AdmitJobResultStatus,
    ClaimQueuedJobResultStatus,
    ExtendLeaseResultStatus,
    FinishJobResultStatus,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MarkRetryableFailureResultStatus,
    MarkDeliveredResultStatus,
    MarkSendStartedResultStatus,
    QueuedJobAdmissionResultStatus,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    REFUND_STATUS_REFUNDED,
    StartJobResultStatus,
    WeeklyPdfJob,
    WeeklyPdfRequestSnapshot,
)


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


def test_migration_defines_required_indexes_without_connecting_to_postgres() -> None:
    statements = "\n".join(statement for migration in MIGRATIONS for statement in migration.statements)

    assert "CREATE TABLE IF NOT EXISTS weekly_pdf_jobs" in statements
    assert "send_started_at TIMESTAMPTZ" in statements
    assert "delivered_at TIMESTAMPTZ" in statements
    assert "finalization_error TEXT" in statements
    assert "delivery_status TEXT" in statements
    assert "requires_manual_review BOOLEAN NOT NULL DEFAULT false" in statements
    assert "manual_review_reason TEXT" in statements
    assert "manual_reviewed_at TIMESTAMPTZ" in statements
    assert "manual_review_resolution TEXT" in statements
    assert "request_payload_json JSONB" in statements
    assert "profile_json JSONB" in statements
    assert "recent_recipe_ids_json JSONB" in statements
    assert "generation_seed TEXT" in statements
    assert "worker_id TEXT" in statements
    assert "leased_until TIMESTAMPTZ" in statements
    assert "attempt_count INTEGER NOT NULL DEFAULT 0" in statements
    assert "next_attempt_at TIMESTAMPTZ" in statements
    assert "last_error TEXT" in statements
    assert "delivery_status = 'delivered'" in statements
    assert "delivery_status = 'unknown'" in statements
    assert "delivery_status = 'send_started'" in statements
    assert "send_started_at IS NOT NULL" in statements
    assert "delivered_at IS NULL" in statements
    assert "idx_weekly_pdf_jobs_active_chat_unique" in statements
    assert "WHERE status IN ('queued', 'running')" in statements
    assert "idx_weekly_pdf_jobs_idempotency_key_unique" in statements
    assert "idx_weekly_pdf_jobs_stale" in statements
    assert "idx_weekly_pdf_jobs_queue_claim" in statements
    assert "idx_weekly_pdf_jobs_lease_reclaim" in statements


def test_store_pr12b_runtime_contract_without_connecting_to_postgres() -> None:
    start_signature = signature(PostgresWeeklyPdfJobStore.start_job_and_consume)
    cleanup_signature = signature(PostgresWeeklyPdfJobStore.cleanup_stale)
    manual_review_signature = signature(PostgresWeeklyPdfJobStore.get_manual_review_jobs)

    assert "test_access" in start_signature.parameters
    assert "chat_id" in cleanup_signature.parameters
    assert "include_reviewed" in manual_review_signature.parameters
    assert hasattr(PostgresWeeklyPdfJobStore, "admit_queued_job")
    assert hasattr(PostgresWeeklyPdfJobStore, "claim_next_queued_job")
    assert hasattr(PostgresWeeklyPdfJobStore, "extend_lease")
    assert hasattr(PostgresWeeklyPdfJobStore, "mark_retryable_failure")
    assert hasattr(PostgresWeeklyPdfJobStore, "cancel_queued")
    assert hasattr(PostgresWeeklyPdfJobStore, "mark_send_started")
    assert hasattr(PostgresWeeklyPdfJobStore, "mark_delivered")
    assert hasattr(PostgresWeeklyPdfJobStore, "get_manual_review_jobs")
    assert hasattr(PostgresWeeklyPdfJobStore, "get_unresolved_manual_review_jobs")
    assert "send_started_at" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "delivered_at" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "finalization_error" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "delivery_status" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "requires_manual_review" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "manual_review_reason" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "manual_reviewed_at" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "manual_review_resolution" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "request_payload_json" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "profile_json" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "recent_recipe_ids_json" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "generation_seed" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "worker_id" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "leased_until" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "attempt_count" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "next_attempt_at" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "last_error" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "idx_weekly_pdf_jobs_queue_claim" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.indexes
    assert "idx_weekly_pdf_jobs_lease_reclaim" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.indexes


@pytest.fixture
def store() -> PostgresWeeklyPdfJobStore:
    if not TEST_DATABASE_URL:
        pytest.skip("set DIET_BOT_TEST_DATABASE_URL to run Postgres weekly PDF job integration tests")
    try:
        _require_safe_test_database_url(TEST_DATABASE_URL)
    except ValueError as exc:
        pytest.fail(str(exc))

    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema_name = f"diet_bot_test_{uuid.uuid4().hex}"
    admin_dsn = make_conninfo(TEST_DATABASE_URL, connect_timeout="1")
    try:
        _create_test_schema(psycopg, sql, admin_dsn, schema_name)
    except Exception as exc:
        pytest.fail(f"Postgres test database schema setup failed: {exc}")

    scoped_dsn = make_conninfo(
        TEST_DATABASE_URL,
        connect_timeout="1",
        options=f"-c search_path={schema_name}",
    )
    entitlement_store = PostgresEntitlementStore(scoped_dsn, connect_timeout=1, connect_attempts=1)
    candidate = PostgresWeeklyPdfJobStore(scoped_dsn, connect_timeout=1, connect_attempts=1)
    try:
        entitlement_store.initialize()
        candidate.initialize()
    except Exception as exc:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)
        pytest.fail(f"Postgres weekly PDF job test database initialization failed: {exc}")
    try:
        yield candidate
    finally:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)


def test_schema_init_is_idempotent(store: PostgresWeeklyPdfJobStore) -> None:
    store.initialize()
    store.initialize()
    store.validate_schema()

    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name IN ('schema_migrations', 'weekly_pdf_jobs')
                """
            )
            tables = {row["table_name"] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname IN (
                    'idx_weekly_pdf_jobs_active_chat_unique',
                    'idx_weekly_pdf_jobs_idempotency_key_unique',
                    'idx_weekly_pdf_jobs_stale',
                    'idx_weekly_pdf_jobs_queue_claim',
                    'idx_weekly_pdf_jobs_lease_reclaim'
                  )
                """
            )
            indexes = {row["indexname"] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'weekly_pdf_jobs'
                  AND column_name IN (
                    'send_started_at',
                    'delivered_at',
                    'finalization_error',
                    'delivery_status',
                    'requires_manual_review',
                    'manual_review_reason',
                    'manual_reviewed_at',
                    'manual_review_resolution',
                    'request_payload_json',
                    'profile_json',
                    'recent_recipe_ids_json',
                    'generation_seed',
                    'worker_id',
                    'leased_until',
                    'attempt_count',
                    'next_attempt_at',
                    'last_error'
                  )
                """
            )
            new_columns = {row["column_name"] for row in cur.fetchall()}

    assert tables == {"schema_migrations", "weekly_pdf_jobs"}
    assert indexes == {
        "idx_weekly_pdf_jobs_active_chat_unique",
        "idx_weekly_pdf_jobs_idempotency_key_unique",
        "idx_weekly_pdf_jobs_stale",
        "idx_weekly_pdf_jobs_queue_claim",
        "idx_weekly_pdf_jobs_lease_reclaim",
    }
    assert new_columns == {
        "send_started_at",
        "delivered_at",
        "finalization_error",
        "delivery_status",
        "requires_manual_review",
        "manual_review_reason",
        "manual_reviewed_at",
        "manual_review_resolution",
        "request_payload_json",
        "profile_json",
        "recent_recipe_ids_json",
        "generation_seed",
        "worker_id",
        "leased_until",
        "attempt_count",
        "next_attempt_at",
        "last_error",
    }


def test_migration_backfills_delivery_review_state() -> None:
    if not TEST_DATABASE_URL:
        pytest.skip("set DIET_BOT_TEST_DATABASE_URL to run Postgres weekly PDF job integration tests")
    try:
        _require_safe_test_database_url(TEST_DATABASE_URL)
    except ValueError as exc:
        pytest.fail(str(exc))

    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from psycopg.rows import dict_row

    schema_name = f"diet_bot_test_{uuid.uuid4().hex}"
    admin_dsn = make_conninfo(TEST_DATABASE_URL, connect_timeout="1")
    scoped_dsn = make_conninfo(
        TEST_DATABASE_URL,
        connect_timeout="1",
        options=f"-c search_path={schema_name}",
    )
    delivered_job_id = uuid.uuid4()
    unknown_job_id = uuid.uuid4()
    not_started_job_id = uuid.uuid4()
    active_send_job_id = uuid.uuid4()
    now = datetime(2026, 5, 23, tzinfo=UTC)

    _create_test_schema(psycopg, sql, admin_dsn, schema_name)
    try:
        _install_legacy_weekly_pdf_job_schema(psycopg, scoped_dsn)
        with psycopg.connect(scoped_dsn) as conn:
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
                        send_started_at,
                        delivered_at,
                        finalization_error
                    )
                    VALUES
                        (%s, 201, 'legacy-delivered', 'succeeded', 'not_required', %s, %s, %s, NULL),
                        (%s, 202, 'legacy-unknown', 'succeeded', 'not_required', %s, %s, NULL, 'telegram_upload_failed'),
                        (%s, 203, 'legacy-not-started', 'queued', 'not_required', %s, NULL, NULL, NULL),
                        (%s, 204, 'legacy-active-send', 'running', 'pending', %s, %s, NULL, NULL)
                    """,
                    (
                        delivered_job_id,
                        now + timedelta(minutes=15),
                        now + timedelta(seconds=1),
                        now + timedelta(seconds=2),
                        unknown_job_id,
                        now + timedelta(minutes=15),
                        now + timedelta(seconds=3),
                        not_started_job_id,
                        now + timedelta(minutes=15),
                        active_send_job_id,
                        now + timedelta(minutes=15),
                        now + timedelta(seconds=4),
                    ),
                )

        candidate = PostgresWeeklyPdfJobStore(scoped_dsn, connect_timeout=1, connect_attempts=1)
        candidate.initialize()
        candidate.validate_schema()

        with psycopg.connect(scoped_dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        job_id,
                        delivery_status,
                        requires_manual_review,
                        manual_review_reason,
                        manual_reviewed_at,
                        manual_review_resolution
                    FROM weekly_pdf_jobs
                    WHERE job_id = ANY(%s)
                    """,
                    ([delivered_job_id, unknown_job_id, not_started_job_id, active_send_job_id],),
                )
                rows = {row["job_id"]: row for row in cur.fetchall()}
    finally:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)

    assert rows[delivered_job_id]["delivery_status"] == "delivered"
    assert rows[delivered_job_id]["requires_manual_review"] is False
    assert rows[delivered_job_id]["manual_review_reason"] is None
    assert rows[unknown_job_id]["delivery_status"] == "unknown"
    assert rows[unknown_job_id]["requires_manual_review"] is True
    assert rows[unknown_job_id]["manual_review_reason"] == "telegram_upload_failed"
    assert rows[unknown_job_id]["manual_reviewed_at"] is None
    assert rows[unknown_job_id]["manual_review_resolution"] is None
    assert rows[not_started_job_id]["delivery_status"] == "not_started"
    assert rows[not_started_job_id]["requires_manual_review"] is False
    assert rows[active_send_job_id]["delivery_status"] == "send_started"
    assert rows[active_send_job_id]["requires_manual_review"] is False


def test_weekly_then_chat_state_migrations_create_both_schemas(store: PostgresWeeklyPdfJobStore) -> None:
    chat_state_store = PostgresChatStateStore(store.dsn, connect_timeout=1, connect_attempts=1)

    chat_state_store.initialize()

    store.validate_schema()
    chat_state_store.validate_schema()
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name IN (
                    'schema_migrations',
                    'weekly_pdf_jobs',
                    'chat_profiles',
                    'chat_recipe_history',
                    'chat_state_json_import_runs'
                  )
                """
            )
            tables = {row["table_name"] for row in cur.fetchall()}

    assert tables == {
        "schema_migrations",
        "weekly_pdf_jobs",
        "chat_profiles",
        "chat_recipe_history",
        "chat_state_json_import_runs",
    }


def test_validate_schema_rejects_missing_critical_column(store: PostgresWeeklyPdfJobStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE weekly_pdf_jobs DROP COLUMN delivered_at")

    with pytest.raises(RuntimeError, match=r"missing columns.*weekly_pdf_jobs\.delivered_at"):
        store.validate_schema()


def test_two_store_instances_admit_same_chat_to_one_active_job_only(
    store: PostgresWeeklyPdfJobStore,
) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    first_store = store
    second_store = PostgresWeeklyPdfJobStore(store.dsn, connect_timeout=1, connect_attempts=1)

    first_result = first_store.admit_job(
        chat_id=101,
        idempotency_key="first-chat-101",
        stale_after=now + timedelta(minutes=15),
        metadata={"source": "first"},
    )
    second_result = second_store.admit_job(
        chat_id=101,
        idempotency_key="second-chat-101",
        stale_after=now + timedelta(minutes=15),
        metadata={"source": "second"},
    )
    first = first_result.job
    second = second_result.job

    assert first_result.status == AdmitJobResultStatus.ADMITTED
    assert second_result.status == AdmitJobResultStatus.ACTIVE_DUPLICATE
    assert second.job_id == first.job_id
    assert second.status == JOB_STATUS_QUEUED
    assert store.get_active_job_for_chat(101) == first
    assert _active_job_count(store, 101) == 1


def test_same_idempotency_key_returns_existing_job(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)

    first_result = store.admit_job(
        chat_id=102,
        idempotency_key="weekly-idem-102",
        stale_after=now + timedelta(minutes=15),
        metadata={"request": "original"},
    )
    second_result = store.admit_job(
        chat_id=999,
        idempotency_key="weekly-idem-102",
        stale_after=now + timedelta(minutes=30),
        metadata={"request": "duplicate"},
    )
    first = first_result.job
    second = second_result.job

    assert first_result.status == AdmitJobResultStatus.ADMITTED
    assert second_result.status == AdmitJobResultStatus.EXISTING_IDEMPOTENCY
    assert second == first
    assert second.chat_id == 102
    assert second.metadata == {"request": "original"}


def test_admit_queued_job_persists_snapshot_consumes_quota_and_dedupes(
    store: PostgresWeeklyPdfJobStore,
) -> None:
    now = datetime(2026, 5, 28, tzinfo=UTC)
    chat_id = 120
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=2)
    snapshot = WeeklyPdfRequestSnapshot(
        request_payload={"source": "telegram_weekly_pdf", "recent_recipe_keys": ["r:key"]},
        profile={"age": 34, "goal": "balance"},
        recent_recipe_ids=("r001", "r002"),
        generation_seed="123456",
    )

    first = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="weekly-durable-admit",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=snapshot,
        metadata={"source": "durable"},
        now=now,
    )
    idempotent = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="weekly-durable-admit",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=WeeklyPdfRequestSnapshot(profile={"different": True}),
        now=now + timedelta(seconds=1),
    )
    active_duplicate = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="weekly-durable-duplicate",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=WeeklyPdfRequestSnapshot(profile={"other": True}),
        now=now + timedelta(seconds=2),
    )

    assert first.status == QueuedJobAdmissionResultStatus.ADMITTED
    assert first.job is not None
    assert first.job.status == JOB_STATUS_QUEUED
    assert first.job.consumption_source == "monthly"
    assert first.job.refund_status == REFUND_STATUS_PENDING
    assert first.job.request_snapshot == snapshot
    assert first.job.metadata == {"source": "durable"}
    assert idempotent.status == QueuedJobAdmissionResultStatus.EXISTING_IDEMPOTENCY
    assert idempotent.job == first.job
    assert active_duplicate.status == QueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE
    assert active_duplicate.job == first.job
    assert _weekly_remaining(store, chat_id) == 1
    assert _active_job_count(store, chat_id) == 1
    assert store.get_job(first.job.job_id) == first.job


def test_admit_queued_job_denied_without_job_or_quota_mutation(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 28, tzinfo=UTC)
    chat_id = 121
    _save_exhausted_entitlement(store, chat_id)

    result = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="weekly-durable-denied",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=WeeklyPdfRequestSnapshot(profile={"age": 40}),
        now=now,
    )

    assert result.status == QueuedJobAdmissionResultStatus.DENIED
    assert result.job is None
    assert result.denial_reason == "weekly_pdf_entitlement_unavailable"
    assert store.get_active_job_for_chat(chat_id) is None
    assert _weekly_remaining(store, chat_id) == 0


def test_start_job_does_not_double_consume_durable_admission(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 28, tzinfo=UTC)
    chat_id = 124
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=2)
    admitted = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="weekly-durable-start",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=WeeklyPdfRequestSnapshot(profile={"age": 41}),
        now=now,
    ).job

    started = store.start_job_and_consume(
        admitted.job_id,
        now=now + timedelta(seconds=1),
        stale_after=now + timedelta(minutes=31),
    )

    assert started.status == StartJobResultStatus.STARTED
    assert started.job.status == JOB_STATUS_RUNNING
    assert started.job.consumption_source == "monthly"
    assert started.job.refund_status == REFUND_STATUS_PENDING
    assert _weekly_remaining(store, chat_id) == 1


def test_claim_retry_and_expired_lease_reclaim(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 28, tzinfo=UTC)
    _save_subscription(store, 122, now=now, weekly_pdf_remaining=1)
    _save_subscription(store, 123, now=now, weekly_pdf_remaining=1)
    first = store.admit_queued_job(
        chat_id=122,
        idempotency_key="weekly-claim-first",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=WeeklyPdfRequestSnapshot(profile={"chat": 122}),
        now=now,
    ).job
    second = store.admit_queued_job(
        chat_id=123,
        idempotency_key="weekly-claim-second",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=WeeklyPdfRequestSnapshot(profile={"chat": 123}),
        now=now + timedelta(seconds=1),
    ).job

    claimed_first = store.claim_next_queued_job(
        worker_id="worker-a",
        lease_until=now + timedelta(minutes=5),
        now=now + timedelta(seconds=2),
    )
    retryable = store.mark_retryable_failure(
        claimed_first.job.job_id,
        worker_id="worker-a",
        error="temporary_builder_error",
        next_attempt_at=now + timedelta(minutes=10),
        now=now + timedelta(minutes=1),
    )
    too_early = store.claim_next_queued_job(
        worker_id="worker-b",
        lease_until=now + timedelta(minutes=5),
        now=now + timedelta(minutes=2),
    )
    reclaimed_retry = store.claim_next_queued_job(
        worker_id="worker-b",
        lease_until=now + timedelta(minutes=15),
        now=now + timedelta(minutes=10),
    )
    extended = store.extend_lease(
        reclaimed_retry.job.job_id,
        worker_id="worker-b",
        lease_until=now + timedelta(minutes=20),
        now=now + timedelta(minutes=11),
    )
    claimed_second = store.claim_next_queued_job(
        worker_id="worker-c",
        lease_until=now + timedelta(minutes=15),
        now=now + timedelta(minutes=12),
    )
    blocked = store.claim_next_queued_job(
        worker_id="worker-d",
        lease_until=now + timedelta(minutes=30),
        now=now + timedelta(minutes=13),
    )
    reclaimed_expired = store.claim_next_queued_job(
        worker_id="worker-d",
        lease_until=now + timedelta(minutes=30),
        now=now + timedelta(minutes=21),
    )

    assert claimed_first.status == ClaimQueuedJobResultStatus.CLAIMED
    assert claimed_first.job.job_id == first.job_id
    assert retryable.status == MarkRetryableFailureResultStatus.MARKED
    assert retryable.job.status == JOB_STATUS_QUEUED
    assert retryable.job.attempt_count == 1
    assert retryable.job.next_attempt_at == now + timedelta(minutes=10)
    assert too_early.status == ClaimQueuedJobResultStatus.CLAIMED
    assert too_early.job.job_id == second.job_id
    assert reclaimed_retry.status == ClaimQueuedJobResultStatus.CLAIMED
    assert reclaimed_retry.job.job_id == first.job_id
    assert reclaimed_retry.job.worker_id == "worker-b"
    assert extended.status == ExtendLeaseResultStatus.EXTENDED
    assert extended.job.leased_until == now + timedelta(minutes=20)
    assert claimed_second.status == ClaimQueuedJobResultStatus.EMPTY
    assert blocked.status == ClaimQueuedJobResultStatus.EMPTY
    assert reclaimed_expired.status == ClaimQueuedJobResultStatus.CLAIMED
    assert reclaimed_expired.job.job_id == first.job_id
    assert reclaimed_expired.job.worker_id == "worker-d"


def test_queued_job_does_not_consume_entitlement(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 103
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)

    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="queued-no-consume",
        stale_after=now + timedelta(minutes=15),
    ).job

    assert job.status == JOB_STATUS_QUEUED
    assert _weekly_remaining(store, chat_id) == 1


def test_new_jobs_default_to_not_started_delivery_without_manual_review(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 119

    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="new-job-delivery-review-defaults",
        stale_after=now + timedelta(minutes=15),
    ).job

    assert job.delivery_status == "not_started"
    assert job.requires_manual_review is False
    assert job.manual_review_reason is None
    assert job.manual_reviewed_at is None
    assert job.manual_review_resolution is None


def test_start_job_consumes_once(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 104
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="start-consumes-once",
        stale_after=now + timedelta(minutes=15),
    ).job

    started_result = store.start_job_and_consume(job.job_id, now=now)
    started = started_result.job

    assert started_result.status == StartJobResultStatus.STARTED
    assert started.status == JOB_STATUS_RUNNING
    assert started.consumption_source == "monthly"
    assert started.refund_status == REFUND_STATUS_PENDING
    assert _weekly_remaining(store, chat_id) == 0


def test_retry_start_on_running_job_does_not_consume_again(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 105
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=2)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="retry-start-running",
        stale_after=now + timedelta(minutes=15),
    ).job

    first_result = store.start_job_and_consume(job.job_id, now=now)
    second_result = store.start_job_and_consume(job.job_id, now=now + timedelta(seconds=1))
    first = first_result.job
    second = second_result.job

    assert first_result.status == StartJobResultStatus.STARTED
    assert second_result.status == StartJobResultStatus.ALREADY_RUNNING
    assert first.status == JOB_STATUS_RUNNING
    assert second.status == JOB_STATUS_RUNNING
    assert _weekly_remaining(store, chat_id) == 1


def test_finish_failure_refunds_once(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 106
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="failure-refund-once",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job

    failed_result = store.finish_failure_and_refund_once(started.job_id, reason="send_failed", now=now)
    failed_again_result = store.finish_failure_and_refund_once(started.job_id, reason="send_failed", now=now)
    failed = failed_result.job
    failed_again = failed_again_result.job

    assert failed_result.status == FinishJobResultStatus.FAILED
    assert failed_again_result.status == FinishJobResultStatus.ALREADY_TERMINAL
    assert failed.status == JOB_STATUS_FAILED
    assert failed.refund_status == REFUND_STATUS_REFUNDED
    assert failed.delivered_at is None
    assert failed_again.refund_status == REFUND_STATUS_REFUNDED
    assert _weekly_remaining(store, chat_id) == 1


def test_finish_failure_after_send_started_closes_without_refund(monkeypatch) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    send_started_at = now + timedelta(seconds=5)
    job = WeeklyPdfJob(
        job_id=uuid.uuid4(),
        chat_id=118,
        idempotency_key="failure-after-send-started-no-refund",
        status=JOB_STATUS_RUNNING,
        refund_status=REFUND_STATUS_PENDING,
        consumption_source="monthly",
        stale_after=now + timedelta(minutes=15),
        started_at=now,
        send_started_at=send_started_at,
    )

    def fail_refund_path(*_args, **_kwargs):
        raise AssertionError("send-started failures must not enter entitlement refund handling")

    monkeypatch.setattr(weekly_pdf_job_store, "_lock_entitlement_map_cur", fail_refund_path)
    monkeypatch.setattr(weekly_pdf_job_store, "_load_entitlement_cur", fail_refund_path)
    monkeypatch.setattr(weekly_pdf_job_store, "refund_attempt", fail_refund_path)
    monkeypatch.setattr(weekly_pdf_job_store, "_upsert_entitlement_cur", fail_refund_path)

    cursor = FakeJobCursor(job)
    store = PostgresWeeklyPdfJobStore("postgresql://unit-test")

    result = store._finish_failure_and_refund_once_cur(
        cursor,
        job,
        reason="telegram_upload_failed",
        now=now + timedelta(seconds=10),
    )

    assert result.status == FinishJobResultStatus.SUCCEEDED
    assert result.job.status == JOB_STATUS_SUCCEEDED
    assert result.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert result.job.send_started_at == send_started_at
    assert result.job.delivered_at is None
    assert result.job.failure_reason is None
    assert result.job.finalization_error == "telegram_upload_failed"
    assert result.job.delivery_status == "unknown"
    assert result.job.requires_manual_review is True
    assert result.job.manual_review_reason == "telegram_upload_failed"


def test_finish_failure_after_send_started_preserves_consumed_quota(
    store: PostgresWeeklyPdfJobStore,
) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 118
    send_started_at = now + timedelta(seconds=5)
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="failure-after-send-started-preserves-quota",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job
    send_started = store.mark_send_started(started.job_id, now=send_started_at).job

    failed_result = store.finish_failure_and_refund_once(
        started.job_id,
        reason="telegram_upload_failed",
        now=now + timedelta(seconds=10),
    )
    failed_again_result = store.finish_failure_and_refund_once(
        started.job_id,
        reason="telegram_upload_failed",
        now=now + timedelta(seconds=20),
    )

    assert send_started.send_started_at == send_started_at
    assert failed_result.status == FinishJobResultStatus.SUCCEEDED
    assert failed_again_result.status == FinishJobResultStatus.ALREADY_TERMINAL
    assert failed_result.job.status == JOB_STATUS_SUCCEEDED
    assert failed_result.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert failed_result.job.send_started_at == send_started_at
    assert failed_result.job.delivered_at is None
    assert failed_result.job.failure_reason is None
    assert failed_result.job.finalization_error == "telegram_upload_failed"
    assert failed_result.job.delivery_status == "unknown"
    assert failed_result.job.requires_manual_review is True
    assert failed_result.job.manual_review_reason == "telegram_upload_failed"
    assert failed_again_result.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert store.get_active_job_for_chat(chat_id) is None
    assert _weekly_remaining(store, chat_id) == 0


def test_delivered_failure_closes_successfully_without_refund(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 112
    delivered_at = now + timedelta(seconds=5)
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="delivered-failure-no-refund",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job

    delivered = store.mark_delivered(started.job_id, now=delivered_at)
    failed_result = store.finish_failure_and_refund_once(
        started.job_id,
        reason="status_done_failed",
        now=now + timedelta(seconds=6),
    )

    assert delivered.status == MarkDeliveredResultStatus.DELIVERED
    assert delivered.job.delivered_at == delivered_at
    assert failed_result.status == FinishJobResultStatus.SUCCEEDED
    assert failed_result.job.status == JOB_STATUS_SUCCEEDED
    assert failed_result.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert failed_result.job.delivered_at == delivered_at
    assert failed_result.job.finalization_error == "status_done_failed"
    assert failed_result.job.delivery_status == "delivered"
    assert failed_result.job.requires_manual_review is False
    assert failed_result.job.manual_review_reason is None
    assert _weekly_remaining(store, chat_id) == 0


def test_mark_send_started_sets_timestamp(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 115
    send_started_at = now + timedelta(seconds=5)
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="send-started-sets-timestamp",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job

    result = store.mark_send_started(started.job_id, now=send_started_at)

    assert result.status == MarkSendStartedResultStatus.SEND_STARTED
    assert result.job.status == JOB_STATUS_RUNNING
    assert result.job.send_started_at == send_started_at
    assert result.job.delivery_status == "send_started"
    assert result.job.requires_manual_review is False
    assert result.job.delivered_at is None


def test_mark_send_started_is_idempotent(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 116
    send_started_at = now + timedelta(seconds=5)
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="send-started-idempotent",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job

    first = store.mark_send_started(started.job_id, now=send_started_at)
    second = store.mark_send_started(started.job_id, now=send_started_at + timedelta(seconds=30))

    assert first.status == MarkSendStartedResultStatus.SEND_STARTED
    assert second.status == MarkSendStartedResultStatus.ALREADY_SEND_STARTED
    assert second.job.send_started_at == send_started_at
    assert second.job.delivery_status == "send_started"


def test_mark_delivered_updates_delivery_status_and_clears_manual_review(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 120
    delivered_at = now + timedelta(seconds=5)
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="mark-delivered-clears-review",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE weekly_pdf_jobs
                SET delivery_status = 'unknown',
                    requires_manual_review = true,
                    manual_review_reason = 'previously_unknown'
                WHERE job_id = %s
                """,
                (started.job_id,),
            )

    result = store.mark_delivered(started.job_id, now=delivered_at)

    assert result.status == MarkDeliveredResultStatus.DELIVERED
    assert result.job.delivered_at == delivered_at
    assert result.job.delivery_status == "delivered"
    assert result.job.requires_manual_review is False
    assert result.job.manual_review_reason is None
    assert result.job.manual_reviewed_at is None
    assert result.job.manual_review_resolution is None


def test_unresolved_manual_review_query_returns_only_open_reviews(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    open_first_job_id = uuid.uuid4()
    open_second_job_id = uuid.uuid4()
    reviewed_job_id = uuid.uuid4()
    clean_job_id = uuid.uuid4()
    with store._connect() as conn:
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
                    delivery_status,
                    requires_manual_review,
                    manual_review_reason,
                    manual_reviewed_at,
                    manual_review_resolution,
                    created_at,
                    updated_at,
                    finished_at
                )
                VALUES
                    (%s, 301, 'manual-open-1', 'succeeded', 'not_required', %s, 'unknown', true,
                        'telegram_upload_failed', NULL, NULL, %s, %s, %s),
                    (%s, 302, 'manual-reviewed', 'succeeded', 'not_required', %s, 'unknown', true,
                        'telegram_upload_failed', %s, 'delivered_confirmed', %s, %s, %s),
                    (%s, 303, 'manual-clean', 'succeeded', 'not_required', %s, 'delivered', false,
                        NULL, NULL, NULL, %s, %s, %s),
                    (%s, 304, 'manual-open-2', 'succeeded', 'not_required', %s, 'unknown', true,
                        'stale_after_send_attempt_unconfirmed', NULL, NULL, %s, %s, %s)
                """,
                (
                    open_first_job_id,
                    now + timedelta(minutes=15),
                    now,
                    now,
                    now,
                    reviewed_job_id,
                    now + timedelta(minutes=15),
                    now + timedelta(minutes=5),
                    now + timedelta(seconds=1),
                    now + timedelta(seconds=1),
                    now + timedelta(seconds=1),
                    clean_job_id,
                    now + timedelta(minutes=15),
                    now + timedelta(seconds=2),
                    now + timedelta(seconds=2),
                    now + timedelta(seconds=2),
                    open_second_job_id,
                    now + timedelta(minutes=15),
                    now + timedelta(seconds=3),
                    now + timedelta(seconds=3),
                    now + timedelta(seconds=3),
                ),
            )

    unresolved = store.get_unresolved_manual_review_jobs(limit=10)

    assert [job.job_id for job in unresolved] == [open_first_job_id, open_second_job_id]
    assert [job.delivery_status for job in unresolved] == ["unknown", "unknown"]
    assert all(job.requires_manual_review for job in unresolved)
    assert [job.manual_review_reason for job in unresolved] == [
        "telegram_upload_failed",
        "stale_after_send_attempt_unconfirmed",
    ]
    assert all(job.manual_reviewed_at is None for job in unresolved)


def test_manual_review_query_can_include_reviewed_jobs(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    open_job_id = uuid.uuid4()
    reviewed_job_id = uuid.uuid4()
    clean_job_id = uuid.uuid4()
    with store._connect() as conn:
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
                    delivery_status,
                    requires_manual_review,
                    manual_review_reason,
                    manual_reviewed_at,
                    manual_review_resolution,
                    created_at,
                    updated_at,
                    finished_at
                )
                VALUES
                    (%s, 311, 'manual-include-open', 'succeeded', 'not_required', %s, 'unknown', true,
                        'telegram_upload_failed', NULL, NULL, %s, %s, %s),
                    (%s, 312, 'manual-include-reviewed', 'succeeded', 'not_required', %s, 'unknown', true,
                        'telegram_upload_failed', %s, 'operator_confirmed_delivery', %s, %s, %s),
                    (%s, 313, 'manual-include-clean', 'succeeded', 'not_required', %s, 'delivered', false,
                        NULL, NULL, NULL, %s, %s, %s)
                """,
                (
                    open_job_id,
                    now + timedelta(minutes=15),
                    now,
                    now,
                    now,
                    reviewed_job_id,
                    now + timedelta(minutes=15),
                    now + timedelta(minutes=5),
                    now + timedelta(seconds=1),
                    now + timedelta(seconds=1),
                    now + timedelta(seconds=1),
                    clean_job_id,
                    now + timedelta(minutes=15),
                    now + timedelta(seconds=2),
                    now + timedelta(seconds=2),
                    now + timedelta(seconds=2),
                ),
            )

    jobs = store.get_manual_review_jobs(limit=10, include_reviewed=True)

    assert [job.job_id for job in jobs] == [open_job_id, reviewed_job_id]
    assert jobs[0].manual_reviewed_at is None
    assert jobs[1].manual_reviewed_at == now + timedelta(minutes=5)
    assert jobs[1].manual_review_resolution == "operator_confirmed_delivery"


def test_cleanup_stale_running_job_refunds_once(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 107
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="stale-running-refund",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now, stale_after=now - timedelta(seconds=1)).job

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now)
    cleaned_again = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(minutes=1))

    assert [job.job_id for job in cleaned.jobs] == [started.job_id]
    assert cleaned.job_results[0].status == FinishJobResultStatus.FAILED
    assert cleaned.jobs[0].status == JOB_STATUS_FAILED
    assert cleaned.jobs[0].refund_status == REFUND_STATUS_REFUNDED
    assert cleaned.jobs[0].send_started_at is None
    assert cleaned_again.jobs == []
    assert _weekly_remaining(store, chat_id) == 1


def test_cleanup_stale_send_started_running_job_succeeds_without_refund(
    store: PostgresWeeklyPdfJobStore,
) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 117
    send_started_at = now + timedelta(seconds=5)
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="stale-send-started-running-no-refund",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now, stale_after=now - timedelta(seconds=1)).job
    store.mark_send_started(started.job_id, now=send_started_at)

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(seconds=10))
    cleaned_again = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(minutes=1))

    assert [job.job_id for job in cleaned.jobs] == [started.job_id]
    assert cleaned.job_results[0].status == FinishJobResultStatus.SUCCEEDED
    assert cleaned.jobs[0].status == JOB_STATUS_SUCCEEDED
    assert cleaned.jobs[0].refund_status == REFUND_STATUS_NOT_REQUIRED
    assert cleaned.jobs[0].send_started_at == send_started_at
    assert cleaned.jobs[0].delivered_at is None
    assert cleaned.jobs[0].finalization_error == "stale_after_send_attempt_unconfirmed"
    assert cleaned.jobs[0].delivery_status == "unknown"
    assert cleaned.jobs[0].requires_manual_review is True
    assert cleaned.jobs[0].manual_review_reason == "stale_after_send_attempt_unconfirmed"
    assert cleaned_again.jobs == []
    assert store.get_active_job_for_chat(chat_id) is None
    assert _weekly_remaining(store, chat_id) == 0


def test_cleanup_stale_delivered_running_job_succeeds_without_refund(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 113
    delivered_at = now + timedelta(seconds=5)
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="stale-delivered-running-no-refund",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now, stale_after=now - timedelta(seconds=1)).job
    store.mark_delivered(started.job_id, now=delivered_at)

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(seconds=10))
    cleaned_again = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(minutes=1))

    assert [job.job_id for job in cleaned.jobs] == [started.job_id]
    assert cleaned.job_results[0].status == FinishJobResultStatus.SUCCEEDED
    assert cleaned.jobs[0].status == JOB_STATUS_SUCCEEDED
    assert cleaned.jobs[0].refund_status == REFUND_STATUS_NOT_REQUIRED
    assert cleaned.jobs[0].delivered_at == delivered_at
    assert cleaned.jobs[0].finalization_error == "stale_after_delivery"
    assert cleaned.jobs[0].delivery_status == "delivered"
    assert cleaned.jobs[0].requires_manual_review is False
    assert cleaned.jobs[0].manual_review_reason is None
    assert cleaned_again.jobs == []
    assert _weekly_remaining(store, chat_id) == 0


def test_cleanup_stale_queued_job_cancels_without_refund(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 108
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="stale-queued-cancel",
        stale_after=now - timedelta(seconds=1),
    ).job

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now)

    assert [cleaned_job.job_id for cleaned_job in cleaned.jobs] == [job.job_id]
    assert cleaned.job_results[0].status == FinishJobResultStatus.CANCELLED
    assert cleaned.jobs[0].status == JOB_STATUS_CANCELLED
    assert cleaned.jobs[0].refund_status == REFUND_STATUS_NOT_REQUIRED
    assert _weekly_remaining(store, chat_id) == 1
    assert store.get_active_job_for_chat(chat_id) is None


def test_cleanup_stale_preserves_durable_queued_job(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 28, tzinfo=UTC)
    chat_id = 126
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    admitted = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="durable-stale-queued-preserved",
        stale_after=now - timedelta(seconds=1),
        request_snapshot=WeeklyPdfRequestSnapshot(profile={"age": 36}),
        now=now - timedelta(minutes=31),
    ).job

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now)
    active = store.get_active_job_for_chat(chat_id)

    assert cleaned.jobs == []
    assert active is not None
    assert active.job_id == admitted.job_id
    assert active.status == JOB_STATUS_QUEUED
    assert active.request_snapshot == admitted.request_snapshot
    assert _weekly_remaining(store, chat_id) == 0


def test_test_access_job_does_not_mutate_quota_or_refund(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 109
    entitlement = Entitlement(monthly_weekly_pdf_remaining=0)
    grant_test_access(entitlement, now=now)
    PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).save_all({chat_id: entitlement})
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="test-access-job",
        stale_after=now + timedelta(minutes=15),
    ).job

    started = store.start_job_and_consume(job.job_id, now=now).job
    failed = store.finish_failure_and_refund_once(started.job_id, reason="send_failed", now=now).job
    saved = PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).load_all()[chat_id]

    assert started.status == JOB_STATUS_RUNNING
    assert started.consumption_source == "test_access"
    assert started.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert failed.status == JOB_STATUS_FAILED
    assert failed.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert saved.monthly_weekly_pdf_remaining == 0
    assert saved.is_test_access_active(now)


def test_test_access_flag_job_does_not_create_or_refund_entitlement(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 110
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="test-access-flag-job",
        stale_after=now + timedelta(minutes=15),
    ).job

    started = store.start_job_and_consume(job.job_id, now=now, test_access=True).job
    failed = store.finish_failure_and_refund_once(started.job_id, reason="send_failed", now=now).job
    saved = PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).load_all()

    assert started.status == JOB_STATUS_RUNNING
    assert started.consumption_source == "test_access"
    assert started.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert failed.status == JOB_STATUS_FAILED
    assert failed.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert chat_id not in saved


def test_finish_success_rejects_queued_job_without_status_change(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 110
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="queued-success-rejected",
        stale_after=now + timedelta(minutes=15),
    ).job

    result = store.finish_success(job.job_id, now=now)
    saved = store.get_active_job_for_chat(chat_id)

    assert result.status == FinishJobResultStatus.INVALID_STATE
    assert result.job == job
    assert saved is not None
    assert saved.status == JOB_STATUS_QUEUED
    assert saved.finished_at is None
    assert _weekly_remaining(store, chat_id) == 1


def test_finish_success_allows_running_job(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 111
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="running-success-allowed",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job

    result = store.finish_success(started.job_id, now=now + timedelta(seconds=1))

    assert result.status == FinishJobResultStatus.SUCCEEDED
    assert result.job.status == JOB_STATUS_SUCCEEDED
    assert result.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert result.job.delivery_status == "not_started"
    assert result.job.requires_manual_review is False


def test_finish_success_after_send_started_requires_manual_review(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 121
    send_started_at = now + timedelta(seconds=5)
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="success-send-started-without-delivery",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job
    store.mark_send_started(started.job_id, now=send_started_at)

    result = store.finish_success(started.job_id, now=now + timedelta(seconds=6))

    assert result.status == FinishJobResultStatus.SUCCEEDED
    assert result.job.status == JOB_STATUS_SUCCEEDED
    assert result.job.delivery_status == "unknown"
    assert result.job.requires_manual_review is True
    assert result.job.manual_review_reason == "send_started_without_delivery_confirmation"
    assert result.job.delivered_at is None
    assert _weekly_remaining(store, chat_id) == 0


def test_finish_success_preserves_delivered_marker(store: PostgresWeeklyPdfJobStore) -> None:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    chat_id = 114
    delivered_at = now + timedelta(seconds=5)
    _save_subscription(store, chat_id, now=now, weekly_pdf_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="success-preserves-delivered",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job
    delivered = store.mark_delivered(started.job_id, now=delivered_at)

    result = store.finish_success(started.job_id, now=now + timedelta(seconds=6))

    assert delivered.status == MarkDeliveredResultStatus.DELIVERED
    assert result.status == FinishJobResultStatus.SUCCEEDED
    assert result.job.status == JOB_STATUS_SUCCEEDED
    assert result.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert result.job.delivered_at == delivered_at
    assert result.job.finalization_error is None
    assert result.job.delivery_status == "delivered"
    assert result.job.requires_manual_review is False
    assert _weekly_remaining(store, chat_id) == 0


def _save_subscription(
    store: PostgresWeeklyPdfJobStore,
    chat_id: int,
    *,
    now: datetime,
    weekly_pdf_remaining: int,
) -> None:
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        f"charge-{chat_id}",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_weekly_pdf_remaining = weekly_pdf_remaining
    PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).save_all({chat_id: entitlement})


def _weekly_remaining(store: PostgresWeeklyPdfJobStore, chat_id: int) -> int:
    entitlement = PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).load_all()[chat_id]
    return entitlement.monthly_weekly_pdf_remaining


class FakeJobCursor:
    def __init__(self, job: WeeklyPdfJob) -> None:
        self.job = job
        self.row = _job_row(job)

    def execute(self, query: str, params: tuple) -> None:
        assert "refund_status = 'not_required'" in query
        status, finalization_error, delivery_status, manual_review_reason, finished_at, updated_at, job_id = params
        assert job_id == self.job.job_id
        self.row = _job_row(
            self.job,
            status=status,
            refund_status=REFUND_STATUS_NOT_REQUIRED,
            finalization_error=finalization_error,
            delivery_status=delivery_status,
            requires_manual_review=True,
            manual_review_reason=manual_review_reason,
            manual_reviewed_at=None,
            manual_review_resolution=None,
            finished_at=finished_at,
            updated_at=updated_at,
        )

    def fetchone(self):
        return self.row


def _job_row(job: WeeklyPdfJob, **overrides):
    row = {
        "job_id": job.job_id,
        "chat_id": job.chat_id,
        "idempotency_key": job.idempotency_key,
        "status": job.status,
        "refund_status": job.refund_status,
        "consumption_source": job.consumption_source,
        "stale_after": job.stale_after,
        "metadata_json": job.metadata,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "heartbeat_at": job.heartbeat_at,
        "finished_at": job.finished_at,
        "failure_reason": job.failure_reason,
        "send_started_at": job.send_started_at,
        "delivered_at": job.delivered_at,
        "finalization_error": job.finalization_error,
        "delivery_status": job.delivery_status,
        "requires_manual_review": job.requires_manual_review,
        "manual_review_reason": job.manual_review_reason,
        "manual_reviewed_at": job.manual_reviewed_at,
        "manual_review_resolution": job.manual_review_resolution,
        "request_payload_json": None if job.request_snapshot is None else job.request_snapshot.request_payload,
        "profile_json": None if job.request_snapshot is None else job.request_snapshot.profile,
        "recent_recipe_ids_json": [] if job.request_snapshot is None else list(job.request_snapshot.recent_recipe_ids),
        "generation_seed": None if job.request_snapshot is None else job.request_snapshot.generation_seed,
        "worker_id": job.worker_id,
        "leased_until": job.leased_until,
        "attempt_count": job.attempt_count,
        "next_attempt_at": job.next_attempt_at,
        "last_error": job.last_error,
    }
    row.update(overrides)
    return row


def _active_job_count(store: PostgresWeeklyPdfJobStore, chat_id: int) -> int:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS count
                FROM weekly_pdf_jobs
                WHERE chat_id = %s
                  AND status IN ('queued', 'running')
                """,
                (chat_id,),
            )
            return int(cur.fetchone()["count"])


def _require_safe_test_database_url(database_url: str) -> None:
    names = _database_or_schema_names(database_url)
    if any(_is_explicit_test_name(name) for name in names):
        return
    raise ValueError(
        "DIET_BOT_TEST_DATABASE_URL must name an explicit test database or schema; refusing to initialize "
        "or clean up integration test tables."
    )


def _is_explicit_test_name(name: str) -> bool:
    normalized = name.strip().strip("'\"").lower()
    if normalized in {"test", "diet_bot_test", "diet-bot-test"}:
        return True
    return (
        normalized.startswith("test_")
        or normalized.endswith("_test")
        or normalized.startswith("test-")
        or normalized.endswith("-test")
        or "_test_" in normalized
        or "-test-" in normalized
    )


def _database_or_schema_names(database_url: str) -> list[str]:
    text = database_url.strip()
    names: list[str] = []
    if "://" in text:
        parsed = urlparse(text)
        database = unquote(parsed.path.lstrip("/"))
        if database:
            names.append(database)
        query = {key.lower(): value for key, value in parse_qs(parsed.query).items()}
        for option in query.get("options", []):
            names.extend(_search_path_names(option))
        for schema_key in ("search_path", "currentschema"):
            for value in query.get(schema_key, []):
                names.extend(_split_schema_names(value))
        return names

    fields = _parse_conninfo_fields(text)
    database = fields.get("dbname")
    if database:
        names.append(database)
    if "options" in fields:
        names.extend(_search_path_names(fields["options"]))
    if "search_path" in fields:
        names.extend(_split_schema_names(fields["search_path"]))
    return names


def _parse_conninfo_fields(conninfo: str) -> dict[str, str]:
    try:
        tokens = shlex.split(conninfo)
    except ValueError:
        tokens = conninfo.split()
    fields: dict[str, str] = {}
    for token in tokens:
        key, separator, value = token.partition("=")
        if separator:
            fields[key.lower()] = value
    return fields


def _search_path_names(options: str) -> list[str]:
    match = re.search(r"search_path(?:=|\s+)([^\s]+)", options, flags=re.IGNORECASE)
    if not match:
        return []
    return _split_schema_names(match.group(1))


def _split_schema_names(value: str) -> list[str]:
    names: list[str] = []
    for raw_name in value.split(","):
        name = raw_name.strip().strip("'\"")
        if name and name not in {"$user", "public"}:
            names.append(name)
    return names


def _install_legacy_weekly_pdf_job_schema(psycopg: object, database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_MIGRATIONS_SQL)
            for migration in MIGRATIONS[:-1]:
                for statement in migration.statements:
                    statement = statement.strip()
                    if statement:
                        cur.execute(statement)
                cur.execute(
                    """
                    INSERT INTO schema_migrations (version, description)
                    VALUES (%s, %s)
                    """,
                    (migration.version, migration.description),
                )


def _create_test_schema(psycopg: object, sql: object, database_url: str, schema_name: str) -> None:
    _require_generated_test_schema(schema_name)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))


def _drop_test_schema(psycopg: object, sql: object, database_url: str, schema_name: str) -> None:
    _require_generated_test_schema(schema_name)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))


def _require_generated_test_schema(schema_name: str) -> None:
    if not re.fullmatch(r"diet_bot_test_[0-9a-f]{32}", schema_name):
        raise ValueError(f"refusing to manage unsafe test schema name: {schema_name}")
