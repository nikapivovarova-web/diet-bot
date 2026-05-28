from __future__ import annotations

import os
import re
import shlex
import uuid
from datetime import UTC, datetime, timedelta
from inspect import signature
from urllib.parse import parse_qs, unquote, urlparse

import pytest

import diet_bot.postgres_one_day_generation_job_store as one_day_job_store
from diet_bot.one_day_generation_jobs import (
    AdmitJobResultStatus,
    ClaimQueuedJobResultStatus,
    FinishJobResultStatus,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    ManualReviewResolutionResultStatus,
    MarkSendStartedResultStatus,
    MarkRetryableFailureResultStatus,
    MarkValueMessageDeliveredResultStatus,
    OneDayGenerationJob,
    OneDayGenerationRequestSnapshot,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    REFUND_STATUS_REFUNDED,
    QueuedJobAdmissionResultStatus,
    SetExpectedValueMessagesResultStatus,
    StartJobResultStatus,
)
from diet_bot.postgres_entitlement_store import PostgresEntitlementStore
from diet_bot.postgres_one_day_generation_job_migrations import MIGRATIONS
from diet_bot.postgres_one_day_generation_job_store import (
    ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION,
    PostgresOneDayGenerationJobStore,
)
from diet_bot.subscriptions import Entitlement, apply_subscription_payment


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


def test_migration_defines_required_schema_without_connecting_to_postgres() -> None:
    statements = "\n".join(statement for migration in MIGRATIONS for statement in migration.statements)

    assert "CREATE TABLE IF NOT EXISTS one_day_generation_jobs" in statements
    assert "CREATE TABLE IF NOT EXISTS one_day_generation_job_value_messages" in statements
    assert "expected_value_messages INTEGER NOT NULL DEFAULT 0" in statements
    assert "delivered_value_messages INTEGER NOT NULL DEFAULT 0" in statements
    assert "send_started_at TIMESTAMPTZ" in statements
    assert "first_value_delivered_at TIMESTAMPTZ" in statements
    assert "delivered_at TIMESTAMPTZ" in statements
    assert "finalization_error TEXT" in statements
    assert "requires_manual_review BOOLEAN NOT NULL DEFAULT false" in statements
    assert "manual_reviewed_at TIMESTAMPTZ" in statements
    assert "manual_reviewed_by TEXT" in statements
    assert "manual_review_resolution TEXT" in statements
    assert "manual_review_note TEXT" in statements
    assert "request_payload_json JSONB" in statements
    assert "request_kind TEXT" in statements
    assert "profile_json JSONB" in statements
    assert "recent_recipe_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb" in statements
    assert "generation_seed TEXT" in statements
    assert "worker_id TEXT" in statements
    assert "leased_until TIMESTAMPTZ" in statements
    assert "attempt_count INTEGER NOT NULL DEFAULT 0" in statements
    assert "next_attempt_at TIMESTAMPTZ" in statements
    assert "last_error TEXT" in statements
    assert "idx_one_day_generation_jobs_active_chat_unique" in statements
    assert "WHERE status IN ('queued', 'running')" in statements
    assert "idx_one_day_generation_jobs_idempotency_key_unique" in statements
    assert "idx_one_day_generation_jobs_stale" in statements
    assert "idx_one_day_generation_jobs_queue_claim" in statements
    assert "idx_one_day_generation_jobs_lease_reclaim" in statements


def test_store_contract_without_connecting_to_postgres() -> None:
    start_signature = signature(PostgresOneDayGenerationJobStore.start_job_and_consume)
    cleanup_signature = signature(PostgresOneDayGenerationJobStore.cleanup_stale)
    delivered_signature = signature(PostgresOneDayGenerationJobStore.mark_value_message_delivered)
    resolve_signature = signature(PostgresOneDayGenerationJobStore.resolve_manual_review)

    assert "test_access" in start_signature.parameters
    assert "chat_id" in cleanup_signature.parameters
    assert "value_message_key" in delivered_signature.parameters
    assert "resolved_by" in resolve_signature.parameters
    assert "resolution" in resolve_signature.parameters
    assert "note" in resolve_signature.parameters
    assert "allow_non_manual_review" in resolve_signature.parameters
    assert hasattr(PostgresOneDayGenerationJobStore, "admit_job")
    assert hasattr(PostgresOneDayGenerationJobStore, "admit_queued_job")
    assert hasattr(PostgresOneDayGenerationJobStore, "claim_next_queued_job")
    assert hasattr(PostgresOneDayGenerationJobStore, "extend_lease")
    assert hasattr(PostgresOneDayGenerationJobStore, "mark_retryable_failure")
    assert hasattr(PostgresOneDayGenerationJobStore, "get_job")
    assert hasattr(PostgresOneDayGenerationJobStore, "mark_send_started")
    assert hasattr(PostgresOneDayGenerationJobStore, "set_expected_value_messages")
    assert hasattr(PostgresOneDayGenerationJobStore, "finish_failure_and_refund_once")
    assert hasattr(PostgresOneDayGenerationJobStore, "get_unresolved_manual_review_jobs")
    assert hasattr(PostgresOneDayGenerationJobStore, "get_manual_review_jobs")
    assert hasattr(PostgresOneDayGenerationJobStore, "resolve_manual_review")
    assert "expected_value_messages" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns[
        "one_day_generation_jobs"
    ]
    assert "delivered_value_messages" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns[
        "one_day_generation_jobs"
    ]
    assert "first_value_delivered_at" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns[
        "one_day_generation_jobs"
    ]
    assert "one_day_generation_job_value_messages" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns
    assert "manual_reviewed_at" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns["one_day_generation_jobs"]
    assert "manual_reviewed_by" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns["one_day_generation_jobs"]
    assert "manual_review_resolution" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns[
        "one_day_generation_jobs"
    ]
    assert "manual_review_note" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns["one_day_generation_jobs"]
    assert "request_payload_json" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns[
        "one_day_generation_jobs"
    ]
    assert "leased_until" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.table_columns["one_day_generation_jobs"]
    assert "idx_one_day_generation_jobs_queue_claim" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.indexes
    assert "idx_one_day_generation_jobs_lease_reclaim" in ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION.indexes


@pytest.fixture
def store() -> PostgresOneDayGenerationJobStore:
    if not TEST_DATABASE_URL:
        pytest.skip("set DIET_BOT_TEST_DATABASE_URL to run Postgres one-day job integration tests")
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
    candidate = PostgresOneDayGenerationJobStore(scoped_dsn, connect_timeout=1, connect_attempts=1)
    try:
        entitlement_store.initialize()
        candidate.initialize()
    except Exception as exc:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)
        pytest.fail(f"Postgres one-day job test database initialization failed: {exc}")
    try:
        yield candidate
    finally:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)


def test_schema_init_is_idempotent(store: PostgresOneDayGenerationJobStore) -> None:
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
                  AND table_name IN (
                    'schema_migrations',
                    'one_day_generation_jobs',
                    'one_day_generation_job_value_messages'
                  )
                """
            )
            tables = {row["table_name"] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname IN (
                    'idx_one_day_generation_jobs_active_chat_unique',
                    'idx_one_day_generation_jobs_idempotency_key_unique',
                    'idx_one_day_generation_jobs_stale',
                    'idx_one_day_generation_jobs_queue_claim',
                    'idx_one_day_generation_jobs_lease_reclaim',
                    'idx_one_day_generation_job_value_messages_job'
                  )
                """
            )
            indexes = {row["indexname"] for row in cur.fetchall()}

    assert tables == {
        "schema_migrations",
        "one_day_generation_jobs",
        "one_day_generation_job_value_messages",
    }
    assert indexes == {
        "idx_one_day_generation_jobs_active_chat_unique",
        "idx_one_day_generation_jobs_idempotency_key_unique",
        "idx_one_day_generation_jobs_stale",
        "idx_one_day_generation_jobs_queue_claim",
        "idx_one_day_generation_jobs_lease_reclaim",
        "idx_one_day_generation_job_value_messages_job",
    }


def test_validate_schema_rejects_missing_required_column(store: PostgresOneDayGenerationJobStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE one_day_generation_jobs DROP COLUMN expected_value_messages")

    with pytest.raises(RuntimeError, match=r"missing columns.*one_day_generation_jobs\.expected_value_messages"):
        store.validate_schema()


def test_validate_schema_rejects_missing_required_table(store: PostgresOneDayGenerationJobStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE one_day_generation_job_value_messages")

    with pytest.raises(RuntimeError, match=r"missing tables.*one_day_generation_job_value_messages"):
        store.validate_schema()


def test_admit_creates_queued_job_defaults(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)

    result = store.admit_job(
        chat_id=101,
        idempotency_key="one-day-admit-defaults",
        stale_after=now + timedelta(minutes=15),
        metadata={"source": "unit-test"},
    )
    job = result.job

    assert result.status == AdmitJobResultStatus.ADMITTED
    assert job.status == JOB_STATUS_QUEUED
    assert job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert job.consumption_source is None
    assert job.expected_value_messages == 0
    assert job.delivered_value_messages == 0
    assert job.delivery_status == "not_started"
    assert job.requires_manual_review is False
    assert job.metadata == {"source": "unit-test"}
    assert store.get_job(job.job_id) == job


def test_active_duplicate_same_chat_returns_existing_job(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)

    first = store.admit_job(
        chat_id=102,
        idempotency_key="one-day-active-first",
        stale_after=now + timedelta(minutes=15),
    )
    second = store.admit_job(
        chat_id=102,
        idempotency_key="one-day-active-second",
        stale_after=now + timedelta(minutes=15),
    )

    assert first.status == AdmitJobResultStatus.ADMITTED
    assert second.status == AdmitJobResultStatus.ACTIVE_DUPLICATE
    assert second.job == first.job
    assert _active_job_count(store, 102) == 1


def test_idempotency_key_returns_existing_job(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)

    first = store.admit_job(
        chat_id=103,
        idempotency_key="one-day-idempotent-key",
        stale_after=now + timedelta(minutes=15),
        metadata={"request": "original"},
    )
    second = store.admit_job(
        chat_id=999,
        idempotency_key="one-day-idempotent-key",
        stale_after=now + timedelta(minutes=30),
        metadata={"request": "duplicate"},
    )

    assert first.status == AdmitJobResultStatus.ADMITTED
    assert second.status == AdmitJobResultStatus.EXISTING_IDEMPOTENCY
    assert second.job == first.job
    assert second.job.chat_id == 103
    assert second.job.metadata == {"request": "original"}


def test_admit_queued_job_persists_request_snapshot_and_consumes_quota(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 126
    _save_subscription(store, chat_id, now=now, one_day_remaining=2)
    snapshot = OneDayGenerationRequestSnapshot(
        request_kind="telegram_one_day",
        request_payload={"callback_query_id": "cb-126", "locale": "ru"},
        profile={"goal": "balance", "calories": 1800},
        recent_recipe_ids=("r001", "r002"),
        generation_seed="seed-126",
    )

    result = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="one-day-durable-admit",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=snapshot,
        metadata={"source": "durable"},
        now=now,
    )
    job = result.job

    assert result.status == QueuedJobAdmissionResultStatus.ADMITTED
    assert job is not None
    assert job.status == JOB_STATUS_QUEUED
    assert job.consumption_source == "monthly"
    assert job.refund_status == REFUND_STATUS_PENDING
    assert job.request_snapshot == snapshot
    assert job.metadata == {"source": "durable"}
    assert job.attempt_count == 0
    assert job.worker_id is None
    assert job.leased_until is None
    assert _one_day_remaining(store, chat_id) == 1
    assert store.get_job(job.job_id) == job


def test_admit_queued_job_duplicate_requests_do_not_double_consume(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 127
    _save_subscription(store, chat_id, now=now, one_day_remaining=3)
    snapshot = _durable_snapshot("duplicate")

    first = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="one-day-durable-duplicate",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=snapshot,
        now=now,
    )
    idempotent = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="one-day-durable-duplicate",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=_durable_snapshot("idempotent-retry"),
        now=now + timedelta(seconds=1),
    )
    active_duplicate = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="one-day-durable-active-duplicate",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=_durable_snapshot("active-duplicate"),
        now=now + timedelta(seconds=2),
    )

    assert first.status == QueuedJobAdmissionResultStatus.ADMITTED
    assert idempotent.status == QueuedJobAdmissionResultStatus.EXISTING_IDEMPOTENCY
    assert active_duplicate.status == QueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE
    assert idempotent.job == first.job
    assert active_duplicate.job == first.job
    assert _active_job_count(store, chat_id) == 1
    assert _one_day_remaining(store, chat_id) == 2


def test_admit_queued_job_denied_without_queued_job_or_quota_mutation(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 128
    _save_exhausted_entitlement(store, chat_id)

    result = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="one-day-durable-denied",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=_durable_snapshot("denied"),
        now=now,
    )
    saved = PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).load_all()[chat_id]

    assert result.status == QueuedJobAdmissionResultStatus.DENIED
    assert result.job is None
    assert result.denial_reason == "one_day_entitlement_unavailable"
    assert store.get_active_job_for_chat(chat_id) is None
    assert saved.monthly_one_day_remaining == 0
    assert saved.extra_one_day_remaining == 0
    assert saved.free_trial_used is True


def test_start_job_and_consume_does_not_double_consume_durable_admission(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 134
    _save_subscription(store, chat_id, now=now, one_day_remaining=2)
    admitted = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="one-day-durable-start-compat",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=_durable_snapshot("start-compat"),
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
    assert _one_day_remaining(store, chat_id) == 1


def test_claim_next_queued_job_respects_order_and_lease(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    _save_subscription(store, 129, now=now, one_day_remaining=1)
    _save_subscription(store, 130, now=now, one_day_remaining=1)
    first = store.admit_queued_job(
        chat_id=129,
        idempotency_key="one-day-durable-claim-first",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=_durable_snapshot("claim-first"),
        now=now,
    ).job
    second = store.admit_queued_job(
        chat_id=130,
        idempotency_key="one-day-durable-claim-second",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=_durable_snapshot("claim-second"),
        now=now + timedelta(seconds=1),
    ).job

    claimed_first = store.claim_next_queued_job(
        worker_id="worker-a",
        lease_until=now + timedelta(minutes=5),
        now=now + timedelta(seconds=2),
    )
    claimed_second = store.claim_next_queued_job(
        worker_id="worker-b",
        lease_until=now + timedelta(minutes=5),
        now=now + timedelta(seconds=3),
    )
    empty = store.claim_next_queued_job(
        worker_id="worker-c",
        lease_until=now + timedelta(minutes=5),
        now=now + timedelta(seconds=4),
    )

    assert claimed_first.status == ClaimQueuedJobResultStatus.CLAIMED
    assert claimed_first.job is not None
    assert claimed_first.job.job_id == first.job_id
    assert claimed_first.job.status == JOB_STATUS_RUNNING
    assert claimed_first.job.worker_id == "worker-a"
    assert claimed_first.job.leased_until == now + timedelta(minutes=5)
    assert claimed_second.status == ClaimQueuedJobResultStatus.CLAIMED
    assert claimed_second.job is not None
    assert claimed_second.job.job_id == second.job_id
    assert empty.status == ClaimQueuedJobResultStatus.EMPTY
    assert empty.job is None


def test_claim_does_not_reclaim_active_lease_until_expired(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 131
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    admitted = store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="one-day-durable-expired-lease",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=_durable_snapshot("expired-lease"),
        now=now,
    ).job

    claimed = store.claim_next_queued_job(
        worker_id="worker-a",
        lease_until=now + timedelta(minutes=5),
        now=now + timedelta(seconds=1),
    )
    blocked = store.claim_next_queued_job(
        worker_id="worker-b",
        lease_until=now + timedelta(minutes=10),
        now=now + timedelta(minutes=1),
    )
    reclaimed = store.claim_next_queued_job(
        worker_id="worker-b",
        lease_until=now + timedelta(minutes=10),
        now=now + timedelta(minutes=6),
    )

    assert claimed.job is not None
    assert claimed.job.job_id == admitted.job_id
    assert blocked.status == ClaimQueuedJobResultStatus.EMPTY
    assert reclaimed.status == ClaimQueuedJobResultStatus.CLAIMED
    assert reclaimed.job is not None
    assert reclaimed.job.job_id == admitted.job_id
    assert reclaimed.job.worker_id == "worker-b"
    assert reclaimed.job.leased_until == now + timedelta(minutes=10)


def test_extend_lease_updates_worker_heartbeat(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 132
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="one-day-durable-heartbeat",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=_durable_snapshot("heartbeat"),
        now=now,
    )
    claimed = store.claim_next_queued_job(
        worker_id="worker-a",
        lease_until=now + timedelta(minutes=5),
        now=now + timedelta(seconds=1),
    ).job

    extended = store.extend_lease(
        claimed.job_id,
        worker_id="worker-a",
        lease_until=now + timedelta(minutes=15),
        now=now + timedelta(minutes=2),
    )

    assert extended.status.name == "EXTENDED"
    assert extended.job is not None
    assert extended.job.worker_id == "worker-a"
    assert extended.job.leased_until == now + timedelta(minutes=15)
    assert extended.job.heartbeat_at == now + timedelta(minutes=2)


def test_retryable_failure_requeues_with_next_attempt_and_increments_attempt_count(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 133
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    store.admit_queued_job(
        chat_id=chat_id,
        idempotency_key="one-day-durable-retryable",
        stale_after=now + timedelta(minutes=30),
        request_snapshot=_durable_snapshot("retryable"),
        now=now,
    )
    claimed = store.claim_next_queued_job(
        worker_id="worker-a",
        lease_until=now + timedelta(minutes=5),
        now=now + timedelta(seconds=1),
    ).job

    retryable = store.mark_retryable_failure(
        claimed.job_id,
        worker_id="worker-a",
        error="temporary_builder_error",
        next_attempt_at=now + timedelta(minutes=10),
        now=now + timedelta(minutes=2),
    )
    too_early = store.claim_next_queued_job(
        worker_id="worker-b",
        lease_until=now + timedelta(minutes=15),
        now=now + timedelta(minutes=5),
    )
    reclaimed = store.claim_next_queued_job(
        worker_id="worker-b",
        lease_until=now + timedelta(minutes=20),
        now=now + timedelta(minutes=10),
    )

    assert retryable.status == MarkRetryableFailureResultStatus.MARKED
    assert retryable.job is not None
    assert retryable.job.status == JOB_STATUS_QUEUED
    assert retryable.job.worker_id is None
    assert retryable.job.leased_until is None
    assert retryable.job.attempt_count == 1
    assert retryable.job.next_attempt_at == now + timedelta(minutes=10)
    assert retryable.job.last_error == "temporary_builder_error"
    assert too_early.status == ClaimQueuedJobResultStatus.EMPTY
    assert reclaimed.status == ClaimQueuedJobResultStatus.CLAIMED
    assert reclaimed.job is not None
    assert reclaimed.job.job_id == claimed.job_id
    assert reclaimed.job.worker_id == "worker-b"
    assert reclaimed.job.attempt_count == 1


def test_start_job_consumes_one_day_attempt_once(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 104
    _save_subscription(store, chat_id, now=now, one_day_remaining=2)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="one-day-start-consume-once",
        stale_after=now + timedelta(minutes=15),
    ).job

    first = store.start_job_and_consume(job.job_id, now=now)
    second = store.start_job_and_consume(job.job_id, now=now + timedelta(seconds=1))

    assert first.status == StartJobResultStatus.STARTED
    assert first.job.status == JOB_STATUS_RUNNING
    assert first.job.consumption_source == "monthly"
    assert first.job.refund_status == REFUND_STATUS_PENDING
    assert second.status == StartJobResultStatus.ALREADY_RUNNING
    assert _one_day_remaining(store, chat_id) == 1


def test_expected_message_count_can_be_set_once_idempotently(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 105
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="one-day-expected-count",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job

    first = store.set_expected_value_messages(started.job_id, 3, now=now + timedelta(seconds=1))
    second = store.set_expected_value_messages(started.job_id, 3, now=now + timedelta(seconds=2))
    different = store.set_expected_value_messages(started.job_id, 4, now=now + timedelta(seconds=3))

    assert first.status == SetExpectedValueMessagesResultStatus.SET
    assert first.job.expected_value_messages == 3
    assert second.status == SetExpectedValueMessagesResultStatus.ALREADY_SET
    assert second.job.expected_value_messages == 3
    assert different.status == SetExpectedValueMessagesResultStatus.INVALID_STATE
    assert different.job.expected_value_messages == 3


def test_delivered_message_counter_is_idempotent(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 106
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    started = _running_job_with_expected_count(store, chat_id, "one-day-delivery-idempotent", now, expected=2)

    first = store.mark_value_message_delivered(
        started.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=2),
    )
    duplicate = store.mark_value_message_delivered(
        started.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=3),
    )
    second = store.mark_value_message_delivered(
        started.job_id,
        value_message_key="meal-lunch",
        now=now + timedelta(seconds=4),
    )

    assert first.status == MarkValueMessageDeliveredResultStatus.DELIVERED
    assert first.job.delivered_value_messages == 1
    assert first.job.first_value_delivered_at == now + timedelta(seconds=2)
    assert first.job.delivery_status == "partial"
    assert duplicate.status == MarkValueMessageDeliveredResultStatus.ALREADY_DELIVERED
    assert duplicate.job.delivered_value_messages == 1
    assert second.status == MarkValueMessageDeliveredResultStatus.DELIVERED
    assert second.job.delivered_value_messages == 2
    assert second.job.delivery_status == "delivered"
    assert second.job.delivered_at == now + timedelta(seconds=4)


def test_final_delivered_message_retry_is_idempotent(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 112
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    started = _running_job_with_expected_count(store, chat_id, "one-day-final-delivery-retry", now, expected=1)

    first = store.mark_value_message_delivered(
        started.job_id,
        value_message_key="full-plan",
        now=now + timedelta(seconds=2),
    )
    retry = store.mark_value_message_delivered(
        started.job_id,
        value_message_key="full-plan",
        now=now + timedelta(seconds=3),
    )

    assert first.status == MarkValueMessageDeliveredResultStatus.DELIVERED
    assert retry.status == MarkValueMessageDeliveredResultStatus.ALREADY_DELIVERED
    assert retry.job.delivered_value_messages == 1
    assert retry.job.delivered_at == now + timedelta(seconds=2)


def test_finish_success_requires_all_expected_messages_delivered(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 107
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    started = _running_job_with_expected_count(store, chat_id, "one-day-success-blocked", now, expected=2)
    store.mark_value_message_delivered(
        started.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=2),
    )

    blocked = store.finish_success(started.job_id, now=now + timedelta(seconds=3))
    store.mark_value_message_delivered(
        started.job_id,
        value_message_key="meal-lunch",
        now=now + timedelta(seconds=4),
    )
    succeeded = store.finish_success(started.job_id, now=now + timedelta(seconds=5))

    assert blocked.status == FinishJobResultStatus.INVALID_STATE
    assert blocked.job.status == JOB_STATUS_RUNNING
    assert blocked.job.delivered_value_messages == 1
    assert succeeded.status == FinishJobResultStatus.SUCCEEDED
    assert succeeded.job.status == JOB_STATUS_SUCCEEDED
    assert succeeded.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert succeeded.job.delivery_status == "delivered"
    assert succeeded.job.requires_manual_review is False
    assert _one_day_remaining(store, chat_id) == 0


def test_finish_failure_before_delivery_refunds_consumed_attempt_once(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 108
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    started = _running_job_with_expected_count(store, chat_id, "one-day-failure-refund", now, expected=2)

    failed = store.finish_failure_and_refund_once(
        started.job_id,
        reason="generation_failed",
        now=now + timedelta(seconds=2),
    )
    failed_again = store.finish_failure_and_refund_once(
        started.job_id,
        reason="generation_failed",
        now=now + timedelta(seconds=3),
    )

    assert failed.status == FinishJobResultStatus.FAILED
    assert failed.job.status == JOB_STATUS_FAILED
    assert failed.job.refund_status == REFUND_STATUS_REFUNDED
    assert failed.job.failure_reason == "generation_failed"
    assert failed.job.delivery_status == "not_started"
    assert failed.job.requires_manual_review is False
    assert failed_again.status == FinishJobResultStatus.ALREADY_TERMINAL
    assert _one_day_remaining(store, chat_id) == 1


def test_finish_failure_after_partial_delivery_keeps_consumption_and_requires_review(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 109
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    started = _running_job_with_expected_count(store, chat_id, "one-day-partial-failure", now, expected=2)
    store.mark_value_message_delivered(
        started.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=2),
    )

    failed = store.finish_failure_and_refund_once(
        started.job_id,
        reason="second_message_failed",
        now=now + timedelta(seconds=3),
    )

    assert failed.status == FinishJobResultStatus.FAILED
    assert failed.job.status == JOB_STATUS_FAILED
    assert failed.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert failed.job.finalization_error == "second_message_failed"
    assert failed.job.delivery_status == "unknown"
    assert failed.job.requires_manual_review is True
    assert failed.job.delivered_value_messages == 1
    assert _one_day_remaining(store, chat_id) == 0


def test_finish_failure_after_send_started_without_value_delivery_closes_unknown_without_refund(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    send_started_at = now + timedelta(seconds=1)
    job = OneDayGenerationJob(
        job_id=uuid.uuid4(),
        chat_id=113,
        idempotency_key="one-day-send-started-no-delivery-no-refund",
        status=JOB_STATUS_RUNNING,
        consumption_source="monthly",
        refund_status=REFUND_STATUS_PENDING,
        delivery_status="send_started",
        expected_value_messages=2,
        delivered_value_messages=0,
        stale_after=now + timedelta(minutes=15),
        started_at=now,
        send_started_at=send_started_at,
    )

    def fail_refund_path(*_args, **_kwargs):
        raise AssertionError("send-started failures must not enter entitlement refund handling")

    monkeypatch.setattr(one_day_job_store, "_lock_entitlement_map_cur", fail_refund_path)
    monkeypatch.setattr(one_day_job_store, "_load_entitlement_cur", fail_refund_path)
    monkeypatch.setattr(one_day_job_store, "refund_attempt", fail_refund_path)
    monkeypatch.setattr(one_day_job_store, "_upsert_entitlement_cur", fail_refund_path)

    cursor = FakeOneDayJobCursor(job)
    store = PostgresOneDayGenerationJobStore("postgresql://unit-test")

    result = store._finish_failure_and_refund_once_cur(
        cursor,
        job,
        reason="telegram_upload_failed",
        now=now + timedelta(seconds=2),
    )

    assert result.status == FinishJobResultStatus.SUCCEEDED
    assert result.job.status == JOB_STATUS_SUCCEEDED
    assert result.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert result.job.send_started_at == send_started_at
    assert result.job.delivered_value_messages == 0
    assert result.job.delivered_at is None
    assert result.job.failure_reason is None
    assert result.job.finalization_error == "telegram_upload_failed"
    assert result.job.delivery_status == "unknown"
    assert result.job.requires_manual_review is True


def test_free_trial_failure_before_delivery_resets_trial_flag(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 110
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="one-day-free-trial-refund",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job

    failed = store.finish_failure_and_refund_once(
        started.job_id,
        reason="generation_failed",
        now=now + timedelta(seconds=1),
    )
    saved = PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).load_all()[chat_id]

    assert started.consumption_source == "free_trial"
    assert started.refund_status == REFUND_STATUS_PENDING
    assert failed.job.refund_status == REFUND_STATUS_REFUNDED
    assert saved.free_trial_used is False


def test_mark_send_started_sets_timestamp(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 111
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="one-day-send-started",
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job

    first = store.mark_send_started(started.job_id, now=now + timedelta(seconds=1))
    second = store.mark_send_started(started.job_id, now=now + timedelta(seconds=2))

    assert first.status == MarkSendStartedResultStatus.SEND_STARTED
    assert first.job.send_started_at == now + timedelta(seconds=1)
    assert first.job.delivery_status == "send_started"
    assert second.status == MarkSendStartedResultStatus.ALREADY_SEND_STARTED
    assert second.job.send_started_at == now + timedelta(seconds=1)


def test_cleanup_stale_queued_job_cancels_without_refund(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 114
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key="one-day-stale-queued-cancel",
        stale_after=now - timedelta(seconds=1),
    ).job

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now)

    assert [cleaned_job.job_id for cleaned_job in cleaned.jobs] == [job.job_id]
    assert cleaned.job_results[0].status == FinishJobResultStatus.CANCELLED
    assert cleaned.jobs[0].status == JOB_STATUS_CANCELLED
    assert cleaned.jobs[0].refund_status == REFUND_STATUS_NOT_REQUIRED
    assert cleaned.jobs[0].failure_reason == "one_day_generation_job_stale"
    assert _one_day_remaining(store, chat_id) == 1
    assert store.get_active_job_for_chat(chat_id) is None


def test_cleanup_stale_running_before_send_start_refunds(store: PostgresOneDayGenerationJobStore) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 115
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    started = _running_job_with_expected_count(
        store,
        chat_id,
        "one-day-stale-running-refund",
        now,
        expected=2,
        stale_after=now - timedelta(seconds=1),
    )

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now)
    cleaned_again = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(minutes=1))

    assert [cleaned_job.job_id for cleaned_job in cleaned.jobs] == [started.job_id]
    assert cleaned.job_results[0].status == FinishJobResultStatus.FAILED
    assert cleaned.jobs[0].status == JOB_STATUS_FAILED
    assert cleaned.jobs[0].refund_status == REFUND_STATUS_REFUNDED
    assert cleaned.jobs[0].send_started_at is None
    assert cleaned.jobs[0].delivery_status == "not_started"
    assert cleaned.jobs[0].requires_manual_review is False
    assert cleaned_again.jobs == []
    assert _one_day_remaining(store, chat_id) == 1


def test_cleanup_stale_running_after_send_start_without_delivery_closes_unknown_no_refund(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 116
    send_started_at = now + timedelta(seconds=1)
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    started = _running_job_with_expected_count(
        store,
        chat_id,
        "one-day-stale-send-started-no-delivery",
        now,
        expected=2,
        stale_after=now - timedelta(seconds=1),
    )
    store.mark_send_started(started.job_id, now=send_started_at)

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(seconds=2))
    cleaned_again = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(minutes=1))

    assert [cleaned_job.job_id for cleaned_job in cleaned.jobs] == [started.job_id]
    assert cleaned.job_results[0].status == FinishJobResultStatus.SUCCEEDED
    assert cleaned.jobs[0].status == JOB_STATUS_SUCCEEDED
    assert cleaned.jobs[0].refund_status == REFUND_STATUS_NOT_REQUIRED
    assert cleaned.jobs[0].send_started_at == send_started_at
    assert cleaned.jobs[0].delivered_value_messages == 0
    assert cleaned.jobs[0].delivered_at is None
    assert cleaned.jobs[0].finalization_error == "stale_after_send_attempt_unconfirmed"
    assert cleaned.jobs[0].delivery_status == "unknown"
    assert cleaned.jobs[0].requires_manual_review is True
    assert cleaned_again.jobs == []
    assert store.get_active_job_for_chat(chat_id) is None
    assert _one_day_remaining(store, chat_id) == 0


def test_cleanup_stale_partial_delivery_keeps_consumption_and_requires_review(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 117
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    started = _running_job_with_expected_count(
        store,
        chat_id,
        "one-day-stale-partial-delivery",
        now,
        expected=2,
        stale_after=now - timedelta(seconds=1),
    )
    store.mark_value_message_delivered(
        started.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=1),
    )

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(seconds=2))

    assert [cleaned_job.job_id for cleaned_job in cleaned.jobs] == [started.job_id]
    assert cleaned.job_results[0].status == FinishJobResultStatus.FAILED
    assert cleaned.jobs[0].status == JOB_STATUS_FAILED
    assert cleaned.jobs[0].refund_status == REFUND_STATUS_NOT_REQUIRED
    assert cleaned.jobs[0].delivered_value_messages == 1
    assert cleaned.jobs[0].finalization_error == "one_day_generation_job_stale"
    assert cleaned.jobs[0].delivery_status == "unknown"
    assert cleaned.jobs[0].requires_manual_review is True
    assert _one_day_remaining(store, chat_id) == 0


def test_cleanup_stale_complete_delivery_succeeds_without_refund(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    chat_id = 118
    _save_subscription(store, chat_id, now=now, one_day_remaining=1)
    started = _running_job_with_expected_count(
        store,
        chat_id,
        "one-day-stale-complete-delivery",
        now,
        expected=2,
        stale_after=now - timedelta(seconds=1),
    )
    store.mark_value_message_delivered(
        started.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=1),
    )
    store.mark_value_message_delivered(
        started.job_id,
        value_message_key="meal-lunch",
        now=now + timedelta(seconds=2),
    )

    cleaned = store.cleanup_stale(chat_id=chat_id, now=now + timedelta(seconds=3))

    assert [cleaned_job.job_id for cleaned_job in cleaned.jobs] == [started.job_id]
    assert cleaned.job_results[0].status == FinishJobResultStatus.SUCCEEDED
    assert cleaned.jobs[0].status == JOB_STATUS_SUCCEEDED
    assert cleaned.jobs[0].refund_status == REFUND_STATUS_NOT_REQUIRED
    assert cleaned.jobs[0].delivered_value_messages == 2
    assert cleaned.jobs[0].finalization_error == "stale_after_complete_delivery"
    assert cleaned.jobs[0].delivery_status == "delivered"
    assert cleaned.jobs[0].requires_manual_review is False
    assert _one_day_remaining(store, chat_id) == 0


def test_list_stale_candidates_selects_active_stale_jobs_only(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    queued = store.admit_job(
        chat_id=119,
        idempotency_key="one-day-list-stale-queued",
        stale_after=now - timedelta(minutes=3),
    ).job
    _save_subscription(store, 120, now=now, one_day_remaining=1)
    running = _running_job_with_expected_count(
        store,
        120,
        "one-day-list-stale-running",
        now,
        expected=1,
        stale_after=now - timedelta(minutes=2),
    )
    store.admit_job(
        chat_id=121,
        idempotency_key="one-day-list-non-stale-queued",
        stale_after=now + timedelta(minutes=1),
    )
    cancelled = store.admit_job(
        chat_id=122,
        idempotency_key="one-day-list-terminal-cancelled",
        stale_after=now - timedelta(minutes=1),
    ).job
    store.cancel_queued(cancelled.job_id, reason="test-terminal", now=now)

    candidates = store.list_stale_candidates(now=now, limit=10)

    assert [candidate.job_id for candidate in candidates] == [queued.job_id, running.job_id]


def test_unresolved_manual_review_query_returns_only_review_required_jobs(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    _save_subscription(store, 123, now=now, one_day_remaining=1)
    unknown = _running_job_with_expected_count(
        store,
        123,
        "one-day-review-query-unknown",
        now,
        expected=2,
        stale_after=now - timedelta(seconds=1),
    )
    store.mark_send_started(unknown.job_id, now=now + timedelta(seconds=1))
    store.cleanup_stale(chat_id=123, now=now + timedelta(seconds=2))

    _save_subscription(store, 124, now=now, one_day_remaining=1)
    partial = _running_job_with_expected_count(
        store,
        124,
        "one-day-review-query-partial",
        now,
        expected=2,
        stale_after=now - timedelta(seconds=1),
    )
    store.mark_value_message_delivered(
        partial.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=1),
    )
    store.cleanup_stale(chat_id=124, now=now + timedelta(seconds=2))

    _save_subscription(store, 125, now=now, one_day_remaining=1)
    delivered = _running_job_with_expected_count(
        store,
        125,
        "one-day-review-query-delivered",
        now,
        expected=2,
    )
    store.mark_value_message_delivered(
        delivered.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=1),
    )
    store.mark_value_message_delivered(
        delivered.job_id,
        value_message_key="meal-lunch",
        now=now + timedelta(seconds=2),
    )
    store.finish_success(delivered.job_id, now=now + timedelta(seconds=3))

    reviews = store.get_unresolved_manual_review_jobs(limit=10)
    limited = store.get_unresolved_manual_review_jobs(limit=1)

    assert [job.job_id for job in reviews] == [unknown.job_id, partial.job_id]
    assert [job.delivery_status for job in reviews] == ["unknown", "unknown"]
    assert [job.delivered_value_messages for job in reviews] == [0, 1]
    assert all(job.requires_manual_review for job in reviews)
    assert delivered.job_id not in {job.job_id for job in reviews}
    assert [job.job_id for job in limited] == [unknown.job_id]


def test_resolve_manual_review_marks_audit_fields_without_changing_refund_or_delivery(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    _save_subscription(store, 126, now=now, one_day_remaining=1)
    job = _running_job_with_expected_count(
        store,
        126,
        "one-day-review-resolve",
        now,
        expected=2,
        stale_after=now - timedelta(seconds=1),
    )
    store.mark_value_message_delivered(
        job.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=1),
    )
    store.cleanup_stale(chat_id=126, now=now + timedelta(seconds=2))
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE one_day_generation_jobs
                SET refund_status = 'pending'
                WHERE job_id = %s
                """,
                (job.job_id,),
            )

    result = store.resolve_manual_review(
        job.job_id,
        resolved_by="ops.mira",
        resolution="no_refund_confirmed",
        note="Ticket MR-126 checked partial delivery; no refund from this tool.",
        now=now + timedelta(minutes=5),
    )
    repeated = store.resolve_manual_review(
        job.job_id,
        resolved_by="ops.second",
        resolution="no_refund_confirmed",
        note="Repeated ticket should not overwrite audit metadata.",
        now=now + timedelta(minutes=6),
    )
    unresolved = store.get_unresolved_manual_review_jobs(limit=10)
    reviewed = store.get_manual_review_jobs(limit=10, include_reviewed=True)

    assert result.status == ManualReviewResolutionResultStatus.RESOLVED
    assert result.job.manual_reviewed_at == now + timedelta(minutes=5)
    assert result.job.manual_reviewed_by == "ops.mira"
    assert result.job.manual_review_resolution == "no_refund_confirmed"
    assert result.job.manual_review_note == "Ticket MR-126 checked partial delivery; no refund from this tool."
    assert result.job.delivery_status == "unknown"
    assert result.job.refund_status == "pending"
    assert repeated.status == ManualReviewResolutionResultStatus.ALREADY_RESOLVED
    assert repeated.job.manual_reviewed_by == "ops.mira"
    assert job.job_id not in {review.job_id for review in unresolved}
    assert job.job_id in {review.job_id for review in reviewed}


def test_resolve_manual_review_refuses_non_review_without_override(
    store: PostgresOneDayGenerationJobStore,
) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    _save_subscription(store, 127, now=now, one_day_remaining=1)
    delivered = _running_job_with_expected_count(
        store,
        127,
        "one-day-review-resolve-clean",
        now,
        expected=1,
    )
    store.mark_value_message_delivered(
        delivered.job_id,
        value_message_key="meal-breakfast",
        now=now + timedelta(seconds=1),
    )
    store.finish_success(delivered.job_id, now=now + timedelta(seconds=2))

    refused = store.resolve_manual_review(
        delivered.job_id,
        resolved_by="ops.mira",
        resolution="operator_override",
        note="Ticket MR-127.",
        now=now + timedelta(minutes=5),
    )
    overridden = store.resolve_manual_review(
        delivered.job_id,
        resolved_by="ops.mira",
        resolution="operator_override",
        note="Ticket MR-127 records audit-only closure.",
        now=now + timedelta(minutes=6),
        allow_non_manual_review=True,
    )

    assert refused.status == ManualReviewResolutionResultStatus.NOT_MANUAL_REVIEW
    assert refused.job.manual_reviewed_at is None
    assert overridden.status == ManualReviewResolutionResultStatus.RESOLVED
    assert overridden.job.manual_reviewed_at == now + timedelta(minutes=6)
    assert overridden.job.requires_manual_review is False
    assert overridden.job.delivery_status == "delivered"
    assert overridden.job.refund_status == "not_required"


def _running_job_with_expected_count(
    store: PostgresOneDayGenerationJobStore,
    chat_id: int,
    idempotency_key: str,
    now: datetime,
    *,
    expected: int,
    stale_after: datetime | None = None,
):
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key=idempotency_key,
        stale_after=stale_after or now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(
        job.job_id,
        now=now,
        stale_after=stale_after,
    ).job
    set_result = store.set_expected_value_messages(started.job_id, expected, now=now + timedelta(seconds=1))
    assert set_result.status == SetExpectedValueMessagesResultStatus.SET
    return set_result.job


def _save_subscription(
    store: PostgresOneDayGenerationJobStore,
    chat_id: int,
    *,
    now: datetime,
    one_day_remaining: int,
) -> None:
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        f"charge-{chat_id}",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = one_day_remaining
    PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).save_all({chat_id: entitlement})


def _save_exhausted_entitlement(store: PostgresOneDayGenerationJobStore, chat_id: int) -> None:
    entitlement = Entitlement(free_trial_used=True)
    PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).save_all({chat_id: entitlement})


def _durable_snapshot(label: str) -> OneDayGenerationRequestSnapshot:
    return OneDayGenerationRequestSnapshot(
        request_kind="telegram_one_day",
        request_payload={"label": label},
        profile={"goal": "maintenance"},
        recent_recipe_ids=(f"recent-{label}",),
        generation_seed=f"seed-{label}",
    )


def _one_day_remaining(store: PostgresOneDayGenerationJobStore, chat_id: int) -> int:
    entitlement = PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).load_all()[chat_id]
    return entitlement.monthly_one_day_remaining


def _active_job_count(store: PostgresOneDayGenerationJobStore, chat_id: int) -> int:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS count
                FROM one_day_generation_jobs
                WHERE chat_id = %s
                  AND status IN ('queued', 'running')
                """,
                (chat_id,),
            )
            return int(cur.fetchone()["count"])


class FakeOneDayJobCursor:
    def __init__(self, job: OneDayGenerationJob) -> None:
        self.job = job
        self.row = _one_day_job_row(job)

    def execute(self, query: str, params: tuple) -> None:
        assert "refund_status = 'not_required'" in query
        status, finalization_error, delivery_status, finished_at, updated_at, job_id = params
        assert job_id == self.job.job_id
        self.row = _one_day_job_row(
            self.job,
            status=status,
            refund_status=REFUND_STATUS_NOT_REQUIRED,
            finalization_error=finalization_error,
            delivery_status=delivery_status,
            requires_manual_review=True,
            finished_at=finished_at,
            updated_at=updated_at,
        )

    def fetchone(self):
        return self.row


def _one_day_job_row(job: OneDayGenerationJob, **overrides):
    row = {
        "job_id": job.job_id,
        "chat_id": job.chat_id,
        "idempotency_key": job.idempotency_key,
        "status": job.status,
        "consumption_source": job.consumption_source,
        "refund_status": job.refund_status,
        "delivery_status": job.delivery_status,
        "expected_value_messages": job.expected_value_messages,
        "delivered_value_messages": job.delivered_value_messages,
        "stale_after": job.stale_after,
        "metadata_json": job.metadata,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "heartbeat_at": job.heartbeat_at,
        "finished_at": job.finished_at,
        "send_started_at": job.send_started_at,
        "first_value_delivered_at": job.first_value_delivered_at,
        "delivered_at": job.delivered_at,
        "failure_reason": job.failure_reason,
        "finalization_error": job.finalization_error,
        "requires_manual_review": job.requires_manual_review,
        "manual_reviewed_at": job.manual_reviewed_at,
        "manual_reviewed_by": job.manual_reviewed_by,
        "manual_review_resolution": job.manual_review_resolution,
        "manual_review_note": job.manual_review_note,
    }
    row.update(overrides)
    return row


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
