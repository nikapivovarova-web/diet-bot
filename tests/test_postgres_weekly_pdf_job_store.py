from __future__ import annotations

import os
import re
import shlex
import uuid
from inspect import signature
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from diet_bot.postgres_entitlement_store import PostgresEntitlementStore
from diet_bot.postgres_weekly_pdf_job_migrations import MIGRATIONS
from diet_bot.postgres_weekly_pdf_job_store import PostgresWeeklyPdfJobStore, WEEKLY_PDF_JOB_SCHEMA_EXPECTATION
from diet_bot.subscriptions import Entitlement, apply_subscription_payment, grant_test_access
from diet_bot.weekly_pdf_jobs import (
    AdmitJobResultStatus,
    FinishJobResultStatus,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MarkDeliveredResultStatus,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    REFUND_STATUS_REFUNDED,
    StartJobResultStatus,
)


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


def test_migration_defines_required_indexes_without_connecting_to_postgres() -> None:
    statements = "\n".join(statement for migration in MIGRATIONS for statement in migration.statements)

    assert "CREATE TABLE IF NOT EXISTS weekly_pdf_jobs" in statements
    assert "delivered_at TIMESTAMPTZ" in statements
    assert "finalization_error TEXT" in statements
    assert "idx_weekly_pdf_jobs_active_chat_unique" in statements
    assert "WHERE status IN ('queued', 'running')" in statements
    assert "idx_weekly_pdf_jobs_idempotency_key_unique" in statements
    assert "idx_weekly_pdf_jobs_stale" in statements


def test_store_pr12b_runtime_contract_without_connecting_to_postgres() -> None:
    start_signature = signature(PostgresWeeklyPdfJobStore.start_job_and_consume)
    cleanup_signature = signature(PostgresWeeklyPdfJobStore.cleanup_stale)

    assert "test_access" in start_signature.parameters
    assert "chat_id" in cleanup_signature.parameters
    assert hasattr(PostgresWeeklyPdfJobStore, "cancel_queued")
    assert hasattr(PostgresWeeklyPdfJobStore, "mark_delivered")
    assert "delivered_at" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]
    assert "finalization_error" in WEEKLY_PDF_JOB_SCHEMA_EXPECTATION.table_columns["weekly_pdf_jobs"]


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
                    'idx_weekly_pdf_jobs_stale'
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
                  AND column_name IN ('delivered_at', 'finalization_error')
                """
            )
            new_columns = {row["column_name"] for row in cur.fetchall()}

    assert tables == {"schema_migrations", "weekly_pdf_jobs"}
    assert indexes == {
        "idx_weekly_pdf_jobs_active_chat_unique",
        "idx_weekly_pdf_jobs_idempotency_key_unique",
        "idx_weekly_pdf_jobs_stale",
    }
    assert new_columns == {"delivered_at", "finalization_error"}


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
    assert _weekly_remaining(store, chat_id) == 0


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
    assert cleaned_again.jobs == []
    assert _weekly_remaining(store, chat_id) == 1


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
