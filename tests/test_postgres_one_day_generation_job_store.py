from __future__ import annotations

import os
import re
import shlex
import uuid
from datetime import UTC, datetime, timedelta
from inspect import signature
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from diet_bot.postgres_entitlement_store import PostgresEntitlementStore
from diet_bot.postgres_one_day_generation_job_migrations import MIGRATIONS
from diet_bot.postgres_one_day_generation_job_store import (
    ONE_DAY_GENERATION_JOB_SCHEMA_EXPECTATION,
    PostgresOneDayGenerationJobStore,
)
from diet_bot.subscriptions import Entitlement, apply_subscription_payment
from diet_bot.one_day_generation_jobs import (
    AdmitJobResultStatus,
    FinishJobResultStatus,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MarkSendStartedResultStatus,
    MarkValueMessageDeliveredResultStatus,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    REFUND_STATUS_REFUNDED,
    SetExpectedValueMessagesResultStatus,
    StartJobResultStatus,
)


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
    assert "idx_one_day_generation_jobs_active_chat_unique" in statements
    assert "WHERE status IN ('queued', 'running')" in statements
    assert "idx_one_day_generation_jobs_idempotency_key_unique" in statements
    assert "idx_one_day_generation_jobs_stale" in statements


def test_store_contract_without_connecting_to_postgres() -> None:
    start_signature = signature(PostgresOneDayGenerationJobStore.start_job_and_consume)
    cleanup_signature = signature(PostgresOneDayGenerationJobStore.cleanup_stale)
    delivered_signature = signature(PostgresOneDayGenerationJobStore.mark_value_message_delivered)

    assert "test_access" in start_signature.parameters
    assert "chat_id" in cleanup_signature.parameters
    assert "value_message_key" in delivered_signature.parameters
    assert hasattr(PostgresOneDayGenerationJobStore, "admit_job")
    assert hasattr(PostgresOneDayGenerationJobStore, "get_job")
    assert hasattr(PostgresOneDayGenerationJobStore, "mark_send_started")
    assert hasattr(PostgresOneDayGenerationJobStore, "set_expected_value_messages")
    assert hasattr(PostgresOneDayGenerationJobStore, "finish_failure_and_refund_once")
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
        "idx_one_day_generation_job_value_messages_job",
    }


def test_validate_schema_rejects_missing_required_column(store: PostgresOneDayGenerationJobStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE one_day_generation_jobs DROP COLUMN expected_value_messages")

    with pytest.raises(RuntimeError, match=r"missing columns.*one_day_generation_jobs\.expected_value_messages"):
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


def _running_job_with_expected_count(
    store: PostgresOneDayGenerationJobStore,
    chat_id: int,
    idempotency_key: str,
    now: datetime,
    *,
    expected: int,
):
    job = store.admit_job(
        chat_id=chat_id,
        idempotency_key=idempotency_key,
        stale_after=now + timedelta(minutes=15),
    ).job
    started = store.start_job_and_consume(job.job_id, now=now).job
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
