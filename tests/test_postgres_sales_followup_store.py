from __future__ import annotations

import os
import re
import shlex
import uuid
from datetime import UTC, datetime, timedelta
from inspect import signature
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from diet_bot.postgres_chat_state_store import PostgresChatStateStore
from diet_bot.postgres_sales_followup_migrations import MIGRATIONS
from diet_bot.postgres_sales_followup_store import (
    SALES_FOLLOWUP_SCHEMA_EXPECTATION,
    CreateSalesFollowupChainStatus,
    PostgresSalesFollowupStore,
)
from diet_bot.sales_followup import DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY
from diet_bot.sales_followup_runtime import (
    ClaimSalesFollowupJobResultStatus,
    SalesFollowupJobTransitionStatus,
)


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


def test_migration_defines_required_sales_followup_tables_without_connecting_to_postgres() -> None:
    statements = "\n".join(statement for migration in MIGRATIONS for statement in migration.statements)

    assert "CREATE TABLE IF NOT EXISTS sales_followup_chains" in statements
    assert "CREATE TABLE IF NOT EXISTS sales_followup_jobs" in statements
    assert "CREATE TABLE IF NOT EXISTS sales_followup_preferences" in statements
    assert "CREATE TABLE IF NOT EXISTS sales_followup_campaigns" in statements
    assert "trigger_idempotency_key TEXT NOT NULL" in statements
    assert "payload_json JSONB NOT NULL DEFAULT '{}'::jsonb" in statements
    assert "button_set_key TEXT NOT NULL DEFAULT 'sales_followup_default'" in statements
    assert "enabled BOOLEAN NOT NULL DEFAULT false" in statements
    assert "idx_sales_followup_chains_active_chat_campaign_unique" in statements
    assert "idx_sales_followup_chains_trigger_idempotency_key_unique" in statements
    assert "idx_sales_followup_jobs_chain_step_unique" in statements
    assert "idx_sales_followup_jobs_queue_claim" in statements
    assert "idx_sales_followup_jobs_lease_reclaim" in statements
    assert "status IN ('active', 'completed', 'cancelled', 'opted_out', 'suppressed')" in statements
    assert "status IN ('queued', 'running', 'sent', 'skipped', 'cancelled', 'failed', 'unknown')" in statements


def test_store_contract_without_connecting_to_postgres() -> None:
    create_signature = signature(PostgresSalesFollowupStore.create_chain)
    opt_out_signature = signature(PostgresSalesFollowupStore.set_opt_out)

    assert "trigger_idempotency_key" in create_signature.parameters
    assert "triggered_at" in create_signature.parameters
    assert "trigger_job_id" in create_signature.parameters
    assert "opt_out_source" in opt_out_signature.parameters
    assert hasattr(PostgresSalesFollowupStore, "initialize")
    assert hasattr(PostgresSalesFollowupStore, "validate_schema")
    assert hasattr(PostgresSalesFollowupStore, "ensure_campaign")
    assert hasattr(PostgresSalesFollowupStore, "get_campaign")
    assert hasattr(PostgresSalesFollowupStore, "get_chain")
    assert hasattr(PostgresSalesFollowupStore, "get_job")
    assert hasattr(PostgresSalesFollowupStore, "list_jobs_for_chain")
    assert hasattr(PostgresSalesFollowupStore, "claim_next_due_job")
    assert hasattr(PostgresSalesFollowupStore, "extend_lease")
    assert hasattr(PostgresSalesFollowupStore, "mark_send_started")
    assert hasattr(PostgresSalesFollowupStore, "mark_sent")
    assert hasattr(PostgresSalesFollowupStore, "mark_retryable_failure")
    assert hasattr(PostgresSalesFollowupStore, "mark_failed")
    assert hasattr(PostgresSalesFollowupStore, "mark_unknown")
    assert hasattr(PostgresSalesFollowupStore, "skip_job_and_cancel_chain")
    assert SALES_FOLLOWUP_SCHEMA_EXPECTATION.table_columns["sales_followup_chains"] == (
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
    )
    assert "sales_followup_jobs" in SALES_FOLLOWUP_SCHEMA_EXPECTATION.table_columns
    assert "sales_followup_campaigns" in SALES_FOLLOWUP_SCHEMA_EXPECTATION.table_columns
    assert "idx_sales_followup_chains_active_chat_campaign_unique" in SALES_FOLLOWUP_SCHEMA_EXPECTATION.indexes
    assert "idx_sales_followup_jobs_queue_claim" in SALES_FOLLOWUP_SCHEMA_EXPECTATION.indexes


@pytest.fixture
def store() -> PostgresSalesFollowupStore:
    if not TEST_DATABASE_URL:
        pytest.skip("set DIET_BOT_TEST_DATABASE_URL to run Postgres sales follow-up integration tests")
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
    candidate = PostgresSalesFollowupStore(scoped_dsn, connect_timeout=1, connect_attempts=1)
    try:
        candidate.initialize()
    except Exception as exc:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)
        pytest.fail(f"Postgres sales follow-up test database initialization failed: {exc}")
    try:
        yield candidate
    finally:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)


def test_schema_init_is_idempotent(store: PostgresSalesFollowupStore) -> None:
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
                  AND table_name = ANY(%s)
                """,
                (
                    [
                        "schema_migrations",
                        "sales_followup_chains",
                        "sales_followup_jobs",
                        "sales_followup_preferences",
                        "sales_followup_campaigns",
                    ],
                ),
            )
            tables = {row["table_name"] for row in cur.fetchall()}

    assert tables == {
        "schema_migrations",
        "sales_followup_chains",
        "sales_followup_jobs",
        "sales_followup_preferences",
        "sales_followup_campaigns",
    }


def test_sales_followup_migrations_validate_after_chat_state_migrations_in_shared_schema(
    store: PostgresSalesFollowupStore,
) -> None:
    chat_state_store = PostgresChatStateStore(store.dsn, connect_timeout=1, connect_attempts=1)
    chat_state_store.initialize()

    store.initialize()
    store.validate_schema()
    chat_state_store.validate_schema()


def test_create_chain_is_idempotent_and_creates_exact_eight_jobs(store: PostgresSalesFollowupStore) -> None:
    triggered_at = datetime(2026, 5, 31, 9, 15, tzinfo=UTC)

    first = store.create_chain(
        chat_id=101,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind="free_one_day_delivery",
        trigger_idempotency_key="sales-followup:free_trial_v1:101:job-1",
        triggered_at=triggered_at,
    )
    second = store.create_chain(
        chat_id=999,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind="free_one_day_delivery",
        trigger_idempotency_key="sales-followup:free_trial_v1:101:job-1",
        triggered_at=triggered_at + timedelta(hours=1),
    )

    assert first.status == CreateSalesFollowupChainStatus.CREATED
    assert second.status == CreateSalesFollowupChainStatus.EXISTING_IDEMPOTENCY
    assert second.chain.chain_id == first.chain.chain_id
    assert len(first.jobs) == 8
    assert len(second.jobs) == 8
    assert [job.step_index for job in first.jobs] == list(range(1, 9))
    assert [job.scheduled_at for job in first.jobs] == [
        triggered_at + offset
        for offset in (
            timedelta(hours=2),
            timedelta(days=1),
            timedelta(days=2),
            timedelta(days=3),
            timedelta(days=7),
            timedelta(days=14),
            timedelta(days=30),
            timedelta(days=45),
        )
    ]
    assert first.jobs[0].payload["message_text"].startswith("Как тебе рацион?")
    assert first.jobs[0].payload["button_label"] == "Получить рацион на неделю"
    assert first.jobs[0].payload["target_callback_data"] == "diet:week_pdf"
    assert first.jobs[3].payload["message_text"].count("FOOD20") == 1
    assert first.jobs[3].payload["button_label"] == "Оформить подписку"
    assert first.jobs[3].payload["target_callback_data"] == "diet:subscribe_month"


def test_create_chain_prevents_second_active_chain_for_chat_and_campaign(
    store: PostgresSalesFollowupStore,
) -> None:
    triggered_at = datetime(2026, 5, 31, 9, 15, tzinfo=UTC)

    first = store.create_chain(
        chat_id=202,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind="free_one_day_delivery",
        trigger_idempotency_key="sales-followup:free_trial_v1:202:job-1",
        triggered_at=triggered_at,
    )
    second = store.create_chain(
        chat_id=202,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind="free_one_day_delivery",
        trigger_idempotency_key="sales-followup:free_trial_v1:202:job-2",
        triggered_at=triggered_at + timedelta(minutes=5),
    )

    assert first.status == CreateSalesFollowupChainStatus.CREATED
    assert second.status == CreateSalesFollowupChainStatus.ACTIVE_DUPLICATE
    assert second.chain.chain_id == first.chain.chain_id
    assert len(second.jobs) == 8


def test_campaign_default_is_disabled_and_opt_out_preference_round_trips(
    store: PostgresSalesFollowupStore,
) -> None:
    opted_out_at = datetime(2026, 5, 31, 10, 30, tzinfo=UTC)

    campaign = store.ensure_campaign(
        DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        version="stage18b",
        disabled_reason="Stage 18B storage foundation only.",
    )
    preference = store.set_opt_out(303, opt_out_source="unit_test", now=opted_out_at)

    assert campaign.enabled is False
    assert campaign.disabled_reason == "Stage 18B storage foundation only."
    assert store.get_campaign(DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY) == campaign
    assert preference.chat_id == 303
    assert preference.opted_out_at == opted_out_at
    assert preference.opt_out_source == "unit_test"
    assert store.get_preference(303) == preference


def test_claim_due_job_marks_running_and_sent_with_message_id(store: PostgresSalesFollowupStore) -> None:
    now = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    chain = store.create_chain(
        chat_id=404,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind="free_one_day_delivery",
        trigger_idempotency_key="sales-followup:free_trial_v1:404:job-1",
        triggered_at=now - timedelta(hours=3),
        now=now - timedelta(hours=3),
    )

    claim = store.claim_next_due_job(
        worker_id="sales-worker-a",
        lease_until=now + timedelta(minutes=5),
        now=now,
    )

    assert claim.status == ClaimSalesFollowupJobResultStatus.CLAIMED
    assert claim.job is not None
    assert claim.job.job_id == chain.jobs[0].job_id
    assert claim.job.status == "running"
    assert claim.job.worker_id == "sales-worker-a"
    assert claim.job.leased_until == now + timedelta(minutes=5)
    assert claim.job.heartbeat_at == now

    started = store.mark_send_started(claim.job.job_id, worker_id="sales-worker-a", now=now)
    sent = store.mark_sent(
        claim.job.job_id,
        worker_id="sales-worker-a",
        telegram_message_id=5050,
        now=now + timedelta(seconds=1),
    )

    assert started.status == SalesFollowupJobTransitionStatus.UPDATED
    assert sent.status == SalesFollowupJobTransitionStatus.UPDATED
    assert sent.job is not None
    assert sent.job.status == "sent"
    assert sent.job.send_started_at == now
    assert sent.job.sent_at == now + timedelta(seconds=1)
    assert sent.job.finished_at == now + timedelta(seconds=1)
    assert sent.job.telegram_message_id == 5050


def test_future_job_is_not_claimed(store: PostgresSalesFollowupStore) -> None:
    now = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    store.create_chain(
        chat_id=405,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind="free_one_day_delivery",
        trigger_idempotency_key="sales-followup:free_trial_v1:405:job-1",
        triggered_at=now,
    )

    claim = store.claim_next_due_job(
        worker_id="sales-worker-a",
        lease_until=now + timedelta(minutes=5),
        now=now,
    )

    assert claim.status == ClaimSalesFollowupJobResultStatus.EMPTY
    assert claim.job is None


def test_expired_running_lease_can_be_reclaimed_before_send_started(store: PostgresSalesFollowupStore) -> None:
    now = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    chain = store.create_chain(
        chat_id=406,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind="free_one_day_delivery",
        trigger_idempotency_key="sales-followup:free_trial_v1:406:job-1",
        triggered_at=now - timedelta(hours=3),
    )
    first_claim = store.claim_next_due_job(
        worker_id="sales-worker-a",
        lease_until=now + timedelta(seconds=10),
        now=now,
    )

    reclaimed = store.claim_next_due_job(
        worker_id="sales-worker-b",
        lease_until=now + timedelta(minutes=6),
        now=now + timedelta(seconds=11),
    )

    assert first_claim.status == ClaimSalesFollowupJobResultStatus.CLAIMED
    assert reclaimed.status == ClaimSalesFollowupJobResultStatus.CLAIMED
    assert reclaimed.job is not None
    assert reclaimed.job.job_id == chain.jobs[0].job_id
    assert reclaimed.job.worker_id == "sales-worker-b"
    assert reclaimed.job.heartbeat_at == now + timedelta(seconds=11)


def test_retry_unknown_and_suppression_transitions_are_terminal(
    store: PostgresSalesFollowupStore,
) -> None:
    now = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    first_chain = store.create_chain(
        chat_id=407,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind="free_one_day_delivery",
        trigger_idempotency_key="sales-followup:free_trial_v1:407:job-1",
        triggered_at=now - timedelta(hours=3),
    )
    first_claim = store.claim_next_due_job(
        worker_id="sales-worker-a",
        lease_until=now + timedelta(minutes=5),
        now=now,
    )
    assert first_claim.job is not None
    store.mark_send_started(first_claim.job.job_id, worker_id="sales-worker-a", now=now)
    unknown = store.mark_unknown(
        first_claim.job.job_id,
        worker_id="sales-worker-a",
        error="send_started_without_delivery_confirmation",
        now=now + timedelta(seconds=2),
    )

    assert unknown.status == SalesFollowupJobTransitionStatus.UPDATED
    assert unknown.job is not None
    assert unknown.job.status == "unknown"
    assert unknown.job.finished_at == now + timedelta(seconds=2)
    assert unknown.job.last_error == "send_started_without_delivery_confirmation"

    second_chain = store.create_chain(
        chat_id=408,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        trigger_kind="free_one_day_delivery",
        trigger_idempotency_key="sales-followup:free_trial_v1:408:job-1",
        triggered_at=now - timedelta(hours=3),
    )
    second_claim = store.claim_next_due_job(
        worker_id="sales-worker-a",
        lease_until=now + timedelta(minutes=5),
        now=now,
    )
    assert second_claim.job is not None
    suppressed = store.skip_job_and_cancel_chain(
        second_claim.job.job_id,
        worker_id="sales-worker-a",
        reason="permanent_send_failure",
        chain_status="suppressed",
        now=now + timedelta(seconds=3),
    )

    assert suppressed.status == SalesFollowupJobTransitionStatus.UPDATED
    assert suppressed.job is not None
    assert suppressed.job.status == "skipped"
    assert suppressed.job.skip_reason == "permanent_send_failure"
    assert store.get_chain(second_chain.chain.chain_id).status == "suppressed"
    future_jobs = store.list_jobs_for_chain(second_chain.chain.chain_id)[1:]
    assert {job.status for job in future_jobs} == {"cancelled"}
    assert store.get_chain(first_chain.chain.chain_id).status == "active"


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
