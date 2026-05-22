import json
import os
import re
import shlex
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from diet_bot.entitlement_service import EntitlementService
from diet_bot.entitlement_storage import JsonEntitlementStore
from diet_bot.postgres_entitlement_store import PostgresEntitlementStore
from diet_bot.subscriptions import Entitlement
from scripts import migrate_entitlements_json_to_postgres as migration


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:pass@db.example.com/diet_bot",
        "postgresql://user:pass@db.example.com/postgres",
        "postgresql://user:pass@db.example.com/production",
        "postgresql://user:pass@db.example.com/latest",
        "postgresql://user:pass@db.example.com/contest_prod",
        "postgresql://user:pass@db.example.com/production_testimonial",
        "postgresql://user:pass@db.example.com/attest",
        "postgresql://user:pass@db.example.com/testdrive_prod",
        "dbname=diet_bot_prod user=diet_bot",
        "dbname=latest user=diet_bot",
        "dbname=contest_prod user=diet_bot",
        "dbname=production_testimonial user=diet_bot",
        "dbname=attest user=diet_bot",
        "dbname=testdrive_prod user=diet_bot",
    ],
)
def test_test_database_url_guard_rejects_production_looking_urls(database_url: str) -> None:
    with pytest.raises(ValueError, match="DIET_BOT_TEST_DATABASE_URL"):
        _require_safe_test_database_url(database_url)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:pass@localhost/test",
        "postgresql://user:pass@localhost/test_entitlements",
        "postgresql://user:pass@localhost/diet_bot_test",
        "postgresql://user:pass@localhost/diet-bot-test",
        "postgresql://user:pass@localhost/entitlements_test",
        "postgresql://user:pass@localhost/test-entitlements",
        "postgresql://user:pass@localhost/entitlements-test",
        "postgresql://user:pass@localhost/diet_bot_test_run",
        "postgresql://user:pass@localhost/diet-bot-test-run",
        "postgresql://user:pass@localhost/postgres?options=-csearch_path%3Ddiet_bot_test",
        "postgresql://user:pass@localhost/postgres?options=-csearch_path%3Dtest_schema",
        "postgresql://user:pass@localhost/postgres?options=-csearch_path%3Dentitlements_test",
        "postgresql://user:pass@localhost/postgres?search_path=diet-bot-test",
        "postgresql://user:pass@localhost/postgres?currentSchema=diet_bot_test_run",
        "dbname=diet_bot_prod user=diet_bot options='-c search_path=diet_bot_test'",
        "dbname=test user=diet_bot",
        "dbname=test_entitlements user=diet_bot",
        "dbname=entitlements_test user=diet_bot",
        "dbname=test-entitlements user=diet_bot",
        "dbname=entitlements-test user=diet_bot",
        "dbname=diet_bot_test_run user=diet_bot",
    ],
)
def test_test_database_url_guard_accepts_test_database_or_schema(database_url: str) -> None:
    _require_safe_test_database_url(database_url)


@pytest.fixture
def store() -> PostgresEntitlementStore:
    if not TEST_DATABASE_URL:
        pytest.skip("set DIET_BOT_TEST_DATABASE_URL to run Postgres entitlement integration tests")
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
    candidate = PostgresEntitlementStore(scoped_dsn, connect_timeout=1, connect_attempts=1)
    try:
        candidate.initialize()
    except Exception as exc:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)
        pytest.fail(f"Postgres test database initialization failed: {exc}")
    try:
        yield candidate
    finally:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)


def test_schema_init_is_idempotent(store: PostgresEntitlementStore) -> None:
    store.initialize()
    store.initialize()

    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name IN (
                    'schema_migrations',
                    'entitlements',
                    'entitlement_processed_charge_ids',
                    'entitlement_json_import_runs'
                  )
                """
            )
            tables = {row["table_name"] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conname IN (
                    'chk_entitlements_counters_non_negative',
                    'entitlement_processed_charge_ids_pkey'
                )
                """
            )
            constraints = {row["conname"] for row in cur.fetchall()}
            cur.execute("SELECT count(*) AS count FROM schema_migrations")
            migration_count = int(cur.fetchone()["count"])

    assert tables == {
        "schema_migrations",
        "entitlements",
        "entitlement_processed_charge_ids",
        "entitlement_json_import_runs",
    }
    assert constraints == {
        "chk_entitlements_counters_non_negative",
        "entitlement_processed_charge_ids_pkey",
    }
    assert migration_count >= 2


def test_entitlement_roundtrip(store: PostgresEntitlementStore) -> None:
    chat_id = _chat_id()
    entitlement = Entitlement(
        free_trial_used=True,
        subscription_period_start="2026-05-01T00:00:00+00:00",
        subscription_period_end="2026-06-01T00:00:00+00:00",
        test_access_until="2026-05-30T00:00:00+00:00",
        test_access_enabled=True,
        monthly_one_day_remaining=4,
        monthly_weekly_pdf_remaining=3,
        extra_one_day_remaining=2,
        extra_weekly_pdf_remaining=1,
        processed_payment_charge_ids=["charge-a", "charge-b"],
    )

    store.save_all({chat_id: entitlement})

    assert store.load_all() == {chat_id: entitlement}


def test_processed_charge_ids_roundtrip_and_save_is_idempotent(store: PostgresEntitlementStore) -> None:
    chat_id = _chat_id()
    entitlement = Entitlement(processed_payment_charge_ids=["charge-a", "charge-b"])

    store.save_all({chat_id: entitlement})
    store.save_all({chat_id: entitlement})

    assert store.load_all()[chat_id].processed_payment_charge_ids == ["charge-a", "charge-b"]
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS count FROM entitlement_processed_charge_ids WHERE chat_id = %s",
                (chat_id,),
            )
            assert int(cur.fetchone()["count"]) == 2


def test_entitlement_service_works_over_postgres_store(store: PostgresEntitlementStore) -> None:
    now = datetime(2026, 5, 22, tzinfo=UTC)
    chat_id = _chat_id()
    service = EntitlementService(store)

    service.apply_subscription_payment(
        chat_id,
        "charge-subscription",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    consumption = service.consume_weekly_pdf(chat_id, now=now)
    service.refund_weekly_pdf(chat_id, consumption)

    entitlement = service.get_entitlement(chat_id, now=now)
    assert consumption.allowed
    assert consumption.source == "monthly"
    assert entitlement.monthly_weekly_pdf_remaining == 4
    assert service.has_processed_charge_id(chat_id, "charge-subscription")


def test_json_migration_apply_validates_parity_and_rerun_is_idempotent(
    tmp_path: Path,
    store: PostgresEntitlementStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "subscriptions.json"
    entitlements = {
        _chat_id(): Entitlement(monthly_one_day_remaining=5, processed_payment_charge_ids=["charge-1"]),
        _chat_id(): Entitlement(extra_weekly_pdf_remaining=2),
    }
    _write_source(source, entitlements)
    migration_id = f"migration-{uuid.uuid4().hex}"

    args = [
        "--source",
        str(source),
        "--migration-id",
        migration_id,
        "--apply",
        "--database-url",
        store.dsn,
    ]

    assert migration.main(args, env={}) == 0
    first_payload = json.loads(capsys.readouterr().out)
    assert first_payload["mode"] == "apply"
    assert first_payload["report"] == {
        "entitlements": 2,
        "processed_charge_ids": 1,
    }
    assert store.load_all() == JsonEntitlementStore(source).load_all()

    assert migration.main(args, env={}) == 0
    second_payload = json.loads(capsys.readouterr().out)
    assert second_payload == first_payload
    assert store.load_all() == JsonEntitlementStore(source).load_all()


def test_json_migration_same_migration_id_with_different_fingerprint_fails(
    tmp_path: Path,
    store: PostgresEntitlementStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "subscriptions.json"
    migration_id = f"migration-{uuid.uuid4().hex}"
    _write_source(source, {_chat_id(): Entitlement(monthly_one_day_remaining=1)})

    args = [
        "--source",
        str(source),
        "--migration-id",
        migration_id,
        "--apply",
        "--database-url",
        store.dsn,
    ]
    assert migration.main(args, env={}) == 0
    capsys.readouterr()

    _write_source(source, {_chat_id(): Entitlement(monthly_one_day_remaining=2)})

    with pytest.raises(migration.MigrationError, match="different source fingerprint"):
        migration.main(args, env={})


def test_corrupt_source_leaves_no_target_or_import_run(
    tmp_path: Path,
    store: PostgresEntitlementStore,
) -> None:
    source = tmp_path / "subscriptions.json"
    migration_id = f"migration-{uuid.uuid4().hex}"
    source.write_text("{not-json", encoding="utf-8")

    with pytest.raises(Exception):
        migration.main(
            [
                "--source",
                str(source),
                "--migration-id",
                migration_id,
                "--apply",
                "--database-url",
                store.dsn,
            ],
            env={},
        )

    assert store.load_all() == {}
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS count FROM entitlement_json_import_runs WHERE migration_id = %s",
                (migration_id,),
            )
            assert int(cur.fetchone()["count"]) == 0


def _require_safe_test_database_url(database_url: str) -> None:
    names = _database_or_schema_names(database_url)
    if any(_is_explicit_test_name(name) for name in names):
        return
    raise ValueError(
        "DIET_BOT_TEST_DATABASE_URL must name an explicit test database or schema "
        "(database name or search_path schema must use an explicit test name); refusing to initialize "
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


def _chat_id() -> int:
    return 9_000_000_000 + uuid.uuid4().int % 900_000_000


def _write_source(path: Path, entitlements: dict[int, Entitlement]) -> None:
    path.write_text(
        json.dumps(
            {str(chat_id): entitlement.to_dict() for chat_id, entitlement in entitlements.items()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
