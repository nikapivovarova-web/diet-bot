import os
import re
import shlex
import uuid
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from diet_bot.chat_state_storage import ChatStateStorageError
from diet_bot.postgres_chat_state_store import PostgresChatStateStore


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


@pytest.fixture
def store() -> PostgresChatStateStore:
    if not TEST_DATABASE_URL:
        pytest.skip("set DIET_BOT_TEST_DATABASE_URL to run Postgres chat state integration tests")
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
    candidate = PostgresChatStateStore(scoped_dsn, connect_timeout=1, connect_attempts=1)
    try:
        candidate.initialize()
    except Exception as exc:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)
        pytest.fail(f"Postgres chat state initialization failed: {exc}")
    try:
        yield candidate
    finally:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)


def test_initialize_creates_schema_and_validate_schema_passes(store: PostgresChatStateStore) -> None:
    store.initialize()
    store.validate_schema()

    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name IN ('schema_migrations', 'chat_profiles', 'chat_recipe_history')
                """
            )
            tables = {row["table_name"] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conname IN (
                    'chat_profiles_pkey',
                    'chat_recipe_history_pkey',
                    'chk_chat_profiles_profile_json_object',
                    'chk_chat_recipe_history_recipe_ids_array',
                    'chk_chat_recipe_history_recipe_keys_array'
                )
                """
            )
            constraints = {row["conname"] for row in cur.fetchall()}

    assert tables == {"schema_migrations", "chat_profiles", "chat_recipe_history"}
    assert constraints == {
        "chat_profiles_pkey",
        "chat_recipe_history_pkey",
        "chk_chat_profiles_profile_json_object",
        "chk_chat_recipe_history_recipe_ids_array",
        "chk_chat_recipe_history_recipe_keys_array",
    }


def test_validate_schema_rejects_missing_required_migration_version(store: PostgresChatStateStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM schema_migrations")

    with pytest.raises(ChatStateStorageError, match="missing migration versions"):
        store.validate_schema()


def test_validate_schema_rejects_missing_table(store: PostgresChatStateStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE chat_profiles")

    with pytest.raises(ChatStateStorageError, match="missing tables.*chat_profiles"):
        store.validate_schema()


def test_validate_schema_rejects_missing_critical_column(store: PostgresChatStateStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE chat_profiles DROP COLUMN profile_format_version")

    with pytest.raises(ChatStateStorageError, match=r"missing columns.*chat_profiles\.profile_format_version"):
        store.validate_schema()


def test_validate_schema_rejects_missing_critical_check(store: PostgresChatStateStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE chat_profiles DROP CONSTRAINT chk_chat_profiles_profile_json_object")

    with pytest.raises(ChatStateStorageError, match="missing constraints.*chk_chat_profiles_profile_json_object"):
        store.validate_schema()


def test_validate_schema_rejects_missing_critical_index(store: PostgresChatStateStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE chat_profiles DROP CONSTRAINT chat_profiles_pkey")

    with pytest.raises(ChatStateStorageError, match="missing indexes.*chat_profiles_pkey"):
        store.validate_schema()


def test_profile_upsert_roundtrip_and_version_timestamp_change(store: PostgresChatStateStore) -> None:
    chat_id = _chat_id()
    profile = {"age": 32, "sex": "female", "goal": "maintain"}
    updated_profile = {"age": 33, "sex": "female", "goal": "lose"}

    store.save_chat_state(chat_id, {"profile": profile})
    first_row = _profile_metadata(store, chat_id)

    store.save_chat_state(chat_id, {"profile": updated_profile})
    second_row = _profile_metadata(store, chat_id)

    assert store.load_all()[str(chat_id)]["profile"] == updated_profile
    assert first_row["version"] == 1
    assert second_row["version"] == 2
    assert second_row["updated_at"] > first_row["updated_at"]


def test_recipe_history_roundtrip_preserves_current_ids_and_keys_shape(store: PostgresChatStateStore) -> None:
    chat_id = _chat_id()

    store.save_chat_state(
        chat_id,
        {
            "recipe_ids": ["r001", "r002"],
            "recipe_keys": ["breakfast:r001", "main:r002"],
        },
    )

    assert store.load_all() == {
        str(chat_id): {
            "recipe_ids": ["r001", "r002"],
            "recipe_keys": ["breakfast:r001", "main:r002"],
        },
    }


def test_profile_and_history_updates_do_not_overwrite_each_other(store: PostgresChatStateStore) -> None:
    chat_id = _chat_id()
    first_profile = {"age": 41, "goal": "maintain"}
    second_profile = {"age": 42, "goal": "gain"}

    store.save_chat_state(chat_id, {"profile": first_profile})
    store.save_chat_state(chat_id, {"recipe_ids": ["r010"], "recipe_keys": ["main:r010"]})
    store.save_chat_state(chat_id, {"profile": second_profile})
    store.save_chat_state(chat_id, {"recipe_keys": ["main:r011"]})

    assert store.load_all()[str(chat_id)] == {
        "profile": second_profile,
        "recipe_ids": ["r010"],
        "recipe_keys": ["main:r011"],
    }


def _profile_metadata(store: PostgresChatStateStore, chat_id: int) -> dict[str, object]:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version, updated_at FROM chat_profiles WHERE chat_id = %s",
                (chat_id,),
            )
            return dict(cur.fetchone())


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


def _chat_id() -> int:
    return 9_000_000_000 + uuid.uuid4().int % 900_000_000
