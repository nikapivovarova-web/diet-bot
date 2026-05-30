from __future__ import annotations

import os
import re
import shlex
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from diet_bot.postgres_promo_migrations import MIGRATIONS
from diet_bot.postgres_promo_store import PROMO_SCHEMA_EXPECTATION, PostgresPromoStore
from diet_bot.promo_codes import PromoCodeDefinition, PromoCodeKind, PromoCodeRecord


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


def test_promo_migration_declares_required_tables_indexes_and_constraints() -> None:
    statements = "\n".join(statement for migration in MIGRATIONS for statement in migration.statements)

    assert "CREATE TABLE IF NOT EXISTS promo_codes" in statements
    assert "CREATE TABLE IF NOT EXISTS promo_code_redemptions" in statements
    assert "CREATE TABLE IF NOT EXISTS promo_import_runs" in statements
    assert "idx_promo_code_redemptions_code_chat_active_unique" in statements
    assert "chk_promo_codes_discount_shape" in statements
    assert "chk_promo_code_redemptions_status" in statements

    assert PROMO_SCHEMA_EXPECTATION.table_columns["promo_codes"][:4] == (
        "code",
        "kind",
        "discount_type",
        "discount_percent",
    )
    assert "promo_code_redemptions" in PROMO_SCHEMA_EXPECTATION.table_columns
    assert "promo_import_runs" in PROMO_SCHEMA_EXPECTATION.table_columns
    assert "idx_promo_code_redemptions_code_chat_active_unique" in PROMO_SCHEMA_EXPECTATION.indexes
    assert "chk_promo_codes_discount_shape" in PROMO_SCHEMA_EXPECTATION.constraints


def test_store_api_surface_is_ready_for_future_wiring() -> None:
    required_methods = {
        "initialize",
        "validate_schema",
        "create_or_update_promo_code",
        "update_promo_code",
        "get_promo_code",
        "list_active_promo_codes",
        "disable_promo_code",
        "redeem_promo_code",
        "reserve_promo_code",
        "finalize_promo_redemption",
        "release_promo_redemption",
        "get_redemption_status",
        "import_json_state",
    }

    assert required_methods <= set(dir(PostgresPromoStore))


@pytest.fixture
def store() -> PostgresPromoStore:
    if not TEST_DATABASE_URL:
        pytest.skip("set DIET_BOT_TEST_DATABASE_URL to run Postgres promo integration tests")
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
    candidate = PostgresPromoStore(scoped_dsn, connect_timeout=1, connect_attempts=1)
    try:
        candidate.initialize()
    except Exception as exc:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)
        pytest.fail(f"Postgres promo test database initialization failed: {exc}")
    try:
        yield candidate
    finally:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)


def test_schema_init_is_idempotent(store: PostgresPromoStore) -> None:
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
                    'promo_codes',
                    'promo_code_redemptions',
                    'promo_import_runs'
                  )
                """
            )
            tables = {row["table_name"] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE connamespace = current_schema()::regnamespace
                  AND conname IN (
                    'promo_codes_pkey',
                    'chk_promo_codes_kind',
                    'chk_promo_codes_discount_shape',
                    'promo_code_redemptions_pkey',
                    'chk_promo_code_redemptions_status'
                  )
                """
            )
            constraints = {row["conname"] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname IN (
                    'idx_promo_codes_active_kind',
                    'idx_promo_code_redemptions_code_chat_active_unique',
                    'idx_promo_code_redemptions_idempotency_key_unique'
                  )
                """
            )
            indexes = {row["indexname"] for row in cur.fetchall()}

    assert tables == {"schema_migrations", "promo_codes", "promo_code_redemptions", "promo_import_runs"}
    assert constraints == {
        "promo_codes_pkey",
        "chk_promo_codes_kind",
        "chk_promo_codes_discount_shape",
        "promo_code_redemptions_pkey",
        "chk_promo_code_redemptions_status",
    }
    assert indexes == {
        "idx_promo_codes_active_kind",
        "idx_promo_code_redemptions_code_chat_active_unique",
        "idx_promo_code_redemptions_idempotency_key_unique",
    }


def test_create_get_list_and_disable_promo_code(store: PostgresPromoStore) -> None:
    expires_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    stored = store.create_or_update_promo_code(
        PromoCodeDefinition(
            code="fb disc test 2026",
            kind=PromoCodeKind.DISCOUNT,
            max_redemptions=5,
            per_user_limit=1,
            discount_percent=20,
            expires_at=expires_at,
        ),
        created_by=7001,
        metadata={"campaign": "stage19"},
    )

    loaded = store.get_promo_code("FB-DISC-TEST-2026")
    active_codes = store.list_active_promo_codes(now=datetime(2026, 5, 30, tzinfo=UTC))
    disabled = store.disable_promo_code("fb disc test 2026", disabled_by=7002)

    assert stored.code == "FB-DISC-TEST-2026"
    assert loaded is not None
    assert loaded.code == "FB-DISC-TEST-2026"
    assert loaded.kind == PromoCodeKind.DISCOUNT
    assert loaded.discount_percent == 20
    assert loaded.max_redemptions == 5
    assert loaded.expires_at == "2026-06-01T12:00:00+00:00"
    assert loaded.created_by == 7001
    assert loaded.metadata == {"campaign": "stage19"}
    assert [promo.code for promo in active_codes] == ["FB-DISC-TEST-2026"]
    assert disabled is not None
    assert disabled.active is False
    assert store.list_active_promo_codes(now=datetime(2026, 5, 30, tzinfo=UTC)) == []


def test_redeem_same_chat_same_code_is_idempotent(store: PostgresPromoStore) -> None:
    now = datetime(2026, 5, 30, 10, 0, tzinfo=UTC)
    store.create_or_update_promo_code(PromoCodeDefinition(code="FB-ONCE-ONLY-2026"))

    first = store.redeem_promo_code(
        "fb once only 2026",
        chat_id=101,
        user_id=201,
        idempotency_key="idem-once-101-first",
        now=now,
        metadata={"grant": "monthly"},
    )
    retry = store.redeem_promo_code(
        "FB-ONCE-ONLY-2026",
        chat_id=101,
        user_id=201,
        idempotency_key="idem-once-101-retry",
        now=now + timedelta(seconds=1),
    )
    status = store.get_redemption_status("FB-ONCE-ONLY-2026", 101)

    assert first.status == "redeemed"
    assert retry.status == "already_redeemed"
    assert first.redemption is not None
    assert retry.redemption == first.redemption
    assert status == first.redemption
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS count FROM promo_code_redemptions")
            assert int(cur.fetchone()["count"]) == 1


def test_single_use_code_cannot_be_redeemed_by_another_chat(store: PostgresPromoStore) -> None:
    store.create_or_update_promo_code(PromoCodeDefinition(code="FB-SING-LEUS-2026"))

    first = store.redeem_promo_code("FB-SING-LEUS-2026", chat_id=301, idempotency_key="single-301")
    second = store.redeem_promo_code("FB-SING-LEUS-2026", chat_id=302, idempotency_key="single-302")

    assert first.status == "redeemed"
    assert second.status == "already_used"
    assert second.redemption is None


def test_multi_use_code_respects_max_uses(store: PostgresPromoStore) -> None:
    store.create_or_update_promo_code(
        PromoCodeDefinition(code="FB-MULT-USES-2026", max_redemptions=2),
    )

    first = store.redeem_promo_code("FB-MULT-USES-2026", chat_id=401, idempotency_key="multi-401")
    second = store.redeem_promo_code("FB-MULT-USES-2026", chat_id=402, idempotency_key="multi-402")
    third = store.redeem_promo_code("FB-MULT-USES-2026", chat_id=403, idempotency_key="multi-403")

    assert first.status == "redeemed"
    assert second.status == "redeemed"
    assert third.status == "max_uses_reached"
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS count
                FROM promo_code_redemptions
                WHERE code = 'FB-MULT-USES-2026'
                """
            )
            assert int(cur.fetchone()["count"]) == 2


def test_expired_and_disabled_codes_cannot_redeem(store: PostgresPromoStore) -> None:
    now = datetime(2026, 5, 30, 10, 0, tzinfo=UTC)
    store.create_or_update_promo_code(
        PromoCodeDefinition(
            code="FB-EXPI-REDX-2026",
            expires_at=now - timedelta(seconds=1),
        ),
    )
    store.create_or_update_promo_code(
        PromoCodeDefinition(
            code="FB-DISA-BLED-2026",
            active=False,
        ),
    )

    expired = store.redeem_promo_code("FB-EXPI-REDX-2026", chat_id=501, now=now)
    disabled = store.redeem_promo_code("FB-DISA-BLED-2026", chat_id=502, now=now)

    assert expired.status == "expired"
    assert disabled.status == "disabled"
    assert store.get_redemption_status("FB-EXPI-REDX-2026", 501) is None
    assert store.get_redemption_status("FB-DISA-BLED-2026", 502) is None


def test_import_json_state_preserves_promo_fields_and_used_status(store: PostgresPromoStore) -> None:
    used_at = "2026-05-29T12:34:56+00:00"
    expires_at = "2026-06-30T00:00:00+00:00"
    migration_id = f"promo-import-{uuid.uuid4().hex}"
    records = {
        "fb json used 2026": PromoCodeRecord(
            active=True,
            max_redemptions=1,
            per_user_limit=1,
            expires_at=expires_at,
            monthly_duration_months=2,
            used_by_chat_id=601,
            used_at=used_at,
        ),
        "FB-DISC-IMPT-2026": PromoCodeRecord(
            kind=PromoCodeKind.DISCOUNT,
            active=False,
            max_redemptions=7,
            per_user_limit=1,
            expires_at=expires_at,
            discount_percent=15,
        ),
    }

    first = store.import_json_state(
        records,
        migration_id=migration_id,
        source_fingerprint="sha256:test",
        source_metadata={"source": "unit"},
    )
    second = store.import_json_state(
        records,
        migration_id=migration_id,
        source_fingerprint="sha256:test",
        source_metadata={"source": "unit"},
    )
    used = store.get_promo_code("FB-JSON-USED-2026")
    discount = store.get_promo_code("FB-DISC-IMPT-2026")
    redemption = store.get_redemption_status("FB-JSON-USED-2026", 601)

    assert first == second
    assert first["promo_codes"] == 2
    assert first["redemptions"] == 1
    assert used is not None
    assert used.monthly_duration_months == 2
    assert used.expires_at == expires_at
    assert discount is not None
    assert discount.active is False
    assert discount.kind == PromoCodeKind.DISCOUNT
    assert discount.discount_percent == 15
    assert redemption is not None
    assert redemption.status == "redeemed"
    assert redemption.source == "json_import"
    assert redemption.entitlement_charge_id == "promo:FB-JSON-USED-2026"
    assert redemption.redeemed_at == datetime.fromisoformat(used_at)
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS count
                FROM promo_code_redemptions
                WHERE code = 'FB-JSON-USED-2026'
                """
            )
            assert int(cur.fetchone()["count"]) == 1
            cur.execute(
                """
                SELECT status, result_json
                FROM promo_import_runs
                WHERE migration_id = %s
                """,
                (migration_id,),
            )
            import_run = cur.fetchone()
    assert import_run["status"] == "applied"
    assert dict(import_run["result_json"]) == first


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
