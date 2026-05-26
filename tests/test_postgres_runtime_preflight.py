from __future__ import annotations

import os
import re
import shlex
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from diet_bot.chat_state_runtime import validate_chat_state_store_for_startup
from diet_bot.entitlement_runtime import create_entitlement_store, validate_entitlement_store_for_startup
from diet_bot.one_day_generation_job_runtime import validate_one_day_generation_job_store_for_startup
from diet_bot.payment_runtime import validate_payment_runtime_for_startup
from diet_bot.postgres_chat_state_store import PostgresChatStateStore
from diet_bot.postgres_entitlement_store import PostgresEntitlementStore
from diet_bot.postgres_one_day_generation_job_store import PostgresOneDayGenerationJobStore
from diet_bot.postgres_payment_store import PostgresPaymentStore
from diet_bot.postgres_single_poller_guard import PostgresSinglePollerGuard
from diet_bot.postgres_weekly_pdf_job_store import PostgresWeeklyPdfJobStore
from diet_bot.runtime_config import RuntimeConfig, load_runtime_config, validate_startup
from diet_bot.weekly_pdf_job_runtime import validate_weekly_pdf_job_runtime_for_startup


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


@dataclass(frozen=True)
class ScopedPostgres:
    dsn: str


@pytest.fixture
def scoped_postgres() -> Iterator[ScopedPostgres]:
    if not TEST_DATABASE_URL:
        pytest.skip("set DIET_BOT_TEST_DATABASE_URL to run Postgres runtime preflight integration tests")
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
    try:
        yield ScopedPostgres(scoped_dsn)
    finally:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)


def test_startup_preflight_validators_pass_against_fully_migrated_postgres(
    scoped_postgres: ScopedPostgres,
    tmp_path: Path,
) -> None:
    _initialize_required_postgres_schemas(scoped_postgres.dsn)
    config = _runtime_config(scoped_postgres.dsn, tmp_path, payments_enabled=True)

    _run_startup_preflight_validators(config)

    assert config.payments_enabled is True
    assert config.storage_backend == "postgres"
    assert config.telegram_provider_token == ""


def test_weekly_pdf_startup_validation_fails_when_schema_is_missing(
    scoped_postgres: ScopedPostgres,
    tmp_path: Path,
) -> None:
    _initialize_required_postgres_schemas(scoped_postgres.dsn, skip={"weekly_pdf"})
    config = _runtime_config(scoped_postgres.dsn, tmp_path, payments_enabled=False)

    with pytest.raises(RuntimeError, match="Postgres weekly PDF job storage is not ready"):
        validate_weekly_pdf_job_runtime_for_startup(config)


def test_one_day_startup_validation_fails_when_schema_is_missing(
    scoped_postgres: ScopedPostgres,
    tmp_path: Path,
) -> None:
    _initialize_required_postgres_schemas(scoped_postgres.dsn, skip={"one_day"})
    config = _runtime_config(scoped_postgres.dsn, tmp_path, payments_enabled=False)

    with pytest.raises(RuntimeError, match="Postgres one-day generation job storage is not ready"):
        validate_one_day_generation_job_store_for_startup(config)


def test_single_poller_guard_uses_real_postgres_advisory_lock(scoped_postgres: ScopedPostgres) -> None:
    lock_id = uuid.uuid4().int & ((1 << 63) - 1)
    guard_a = PostgresSinglePollerGuard(scoped_postgres.dsn, lock_id=lock_id).acquire()
    guard_b = PostgresSinglePollerGuard(scoped_postgres.dsn, lock_id=lock_id)
    try:
        with pytest.raises(RuntimeError, match="another production poller is already active"):
            guard_b.acquire()

        guard_a.close()
        guard_b.acquire()
    finally:
        guard_a.close()
        guard_b.close()


def _run_startup_preflight_validators(config: RuntimeConfig) -> None:
    assert validate_startup(config) == ()
    validate_chat_state_store_for_startup(config)
    validate_entitlement_store_for_startup(config, create_entitlement_store(config))
    validate_weekly_pdf_job_runtime_for_startup(config)
    validate_one_day_generation_job_store_for_startup(config)
    validate_payment_runtime_for_startup(config)


def _runtime_config(database_url: str, tmp_path: Path, *, payments_enabled: bool) -> RuntimeConfig:
    env = {
        "DIET_BOT_TOKEN": "123456:test-token",
        "DIET_BOT_ENV": "production",
        "DIET_BOT_STORAGE_BACKEND": "postgres",
        "DIET_BOT_DATABASE_URL": database_url,
        "DIET_BOT_SUPPORT_CHAT_ID": "123456",
        "DIET_BOT_PRIVACY_POLICY_URL": "https://example.test/privacy",
        "DIET_BOT_PAYMENT_RECOVERY_SPOOL": str(tmp_path / "payment_recovery.jsonl"),
    }
    if payments_enabled:
        env["DIET_BOT_PAYMENTS_ENABLED"] = "1"
    return load_runtime_config(env)


def _initialize_required_postgres_schemas(database_url: str, *, skip: set[str] | None = None) -> None:
    skipped = skip or set()
    if "entitlement" not in skipped:
        PostgresEntitlementStore(database_url, connect_timeout=1, connect_attempts=1).initialize()
    if "payment" not in skipped:
        PostgresPaymentStore(database_url, connect_timeout=1, connect_attempts=1).initialize()
    if "chat_state" not in skipped:
        PostgresChatStateStore(database_url, connect_timeout=1, connect_attempts=1).initialize()
    if "weekly_pdf" not in skipped:
        PostgresWeeklyPdfJobStore(database_url, connect_timeout=1, connect_attempts=1).initialize()
    if "one_day" not in skipped:
        PostgresOneDayGenerationJobStore(database_url, connect_timeout=1, connect_attempts=1).initialize()


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
