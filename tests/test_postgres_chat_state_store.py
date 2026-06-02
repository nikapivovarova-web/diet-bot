import json
import os
import re
import shlex
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from diet_bot.chat_state_storage import ChatStateStorageError, JsonChatStateStore
from diet_bot.postgres_chat_state_store import PostgresChatStateStore
from scripts import migrate_history_json_to_postgres as migration


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
                  AND table_name IN (
                    'schema_migrations',
                    'chat_profiles',
                    'chat_recipe_history',
                    'chat_privacy_consents',
                    'chat_state_json_import_runs'
                  )
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
                    'chat_privacy_consents_pkey',
                    'chk_chat_profiles_profile_json_object',
                    'chk_chat_recipe_history_recipe_ids_array',
                    'chk_chat_recipe_history_recipe_keys_array',
                    'chk_chat_privacy_consents_consent_json_object'
                )
                """
            )
            constraints = {row["conname"] for row in cur.fetchall()}

    assert tables == {
        "schema_migrations",
        "chat_profiles",
        "chat_recipe_history",
        "chat_privacy_consents",
        "chat_state_json_import_runs",
    }
    assert constraints == {
        "chat_profiles_pkey",
        "chat_recipe_history_pkey",
        "chat_privacy_consents_pkey",
        "chk_chat_profiles_profile_json_object",
        "chk_chat_recipe_history_recipe_ids_array",
        "chk_chat_recipe_history_recipe_keys_array",
        "chk_chat_privacy_consents_consent_json_object",
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


def test_privacy_consent_roundtrip_does_not_overwrite_profile_or_history(store: PostgresChatStateStore) -> None:
    chat_id = _chat_id()
    profile = {"age": 41, "goal": "maintain"}
    privacy_consent = {
        "accepted": True,
        "accepted_at": "2026-05-31T12:00:00+00:00",
        "text_sha256": "f" * 64,
        "policy_url": "https://foodbalance.example/privacy",
        "schema_version": 1,
    }

    store.save_chat_state(chat_id, {"profile": profile})
    store.save_chat_state(chat_id, {"recipe_ids": ["r010"], "recipe_keys": ["main:r010"]})
    store.save_chat_state(chat_id, {"privacy_consent": privacy_consent})

    assert store.load_chat_state(chat_id) == {
        "profile": profile,
        "recipe_ids": ["r010"],
        "recipe_keys": ["main:r010"],
        "privacy_consent": privacy_consent,
    }
    assert store.load_all()[str(chat_id)]["privacy_consent"] == privacy_consent


def test_row_level_load_chat_state_reads_only_requested_chat(store: PostgresChatStateStore) -> None:
    chat_id = _chat_id()
    other_chat_id = _chat_id()
    requested_state = {
        "profile": {"age": 41, "goal": "maintain"},
        "recipe_ids": ["r010"],
        "recipe_keys": ["main:r010"],
    }
    other_state = {
        "profile": {"age": 29, "goal": "lose"},
        "recipe_ids": ["r020"],
        "recipe_keys": ["main:r020"],
    }
    store.save_all({str(chat_id): requested_state, str(other_chat_id): other_state})

    assert store.load_chat_state(chat_id) == requested_state
    assert store.load_chat_state(_chat_id()) == {}


def test_json_migration_apply_writes_profile_history_and_is_idempotent(
    tmp_path: Path,
    store: PostgresChatStateStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "history.json"
    chat_id = _chat_id()
    history_only_chat_id = _chat_id()
    _write_source(
        source,
        {
            str(chat_id): {
                "profile": {"age": 35, "goal": "maintain"},
                "recipe_ids": ["r001", "r002", "r001"],
                "recipe_keys": ["breakfast:r001", "main:r002"],
            },
            str(history_only_chat_id): {
                "recipe_ids": ["r010"],
                "recipe_keys": ["snack:r010", "snack:r011"],
            },
        },
    )
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
        "total_chats": 2,
        "profiles": 1,
        "chats_with_recipe_ids": 2,
        "chats_with_recipe_keys": 2,
        "recipe_history_chats": 2,
        "invalid_skipped_records": 0,
    }
    assert store.load_all() == JsonChatStateStore(source).load_all()

    assert migration.main(args, env={}) == 0
    second_payload = json.loads(capsys.readouterr().out)
    assert second_payload == first_payload
    assert store.load_all() == JsonChatStateStore(source).load_all()


def test_json_migration_refuses_non_empty_target_by_default_and_leaves_rows(
    tmp_path: Path,
    store: PostgresChatStateStore,
) -> None:
    existing_chat_id = _chat_id()
    existing_state = {
        str(existing_chat_id): {
            "profile": {"age": 40, "goal": "maintain"},
            "recipe_ids": ["old-r"],
            "recipe_keys": ["old-key"],
        },
    }
    store.save_all(existing_state)

    source = tmp_path / "history.json"
    _write_source(source, {str(_chat_id()): {"recipe_ids": ["new-r"], "recipe_keys": ["new-key"]}})

    with pytest.raises(migration.MigrationError, match="non-empty"):
        migration.main(
            [
                "--source",
                str(source),
                "--migration-id",
                f"migration-{uuid.uuid4().hex}",
                "--apply",
                "--database-url",
                store.dsn,
            ],
            env={},
        )

    assert store.load_all() == existing_state


def test_json_migration_allows_non_empty_target_replacement(
    tmp_path: Path,
    store: PostgresChatStateStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.save_all({str(_chat_id()): {"recipe_ids": ["old-r"], "recipe_keys": ["old-key"]}})

    source = tmp_path / "history.json"
    _write_source(
        source,
        {
            str(_chat_id()): {
                "profile": {"age": 28, "goal": "gain"},
                "recipe_ids": ["new-r"],
                "recipe_keys": ["new-key"],
            },
        },
    )

    assert migration.main(
        [
            "--source",
            str(source),
            "--migration-id",
            f"migration-{uuid.uuid4().hex}",
            "--apply",
            "--allow-non-empty-target",
            "--database-url",
            store.dsn,
        ],
        env={},
    ) == 0
    capsys.readouterr()

    assert store.load_all() == JsonChatStateStore(source).load_all()


def test_json_migration_same_migration_id_with_different_fingerprint_fails(
    tmp_path: Path,
    store: PostgresChatStateStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "history.json"
    migration_id = f"migration-{uuid.uuid4().hex}"
    _write_source(source, {str(_chat_id()): {"recipe_ids": ["r001"], "recipe_keys": []}})
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

    _write_source(source, {str(_chat_id()): {"recipe_ids": ["r002"], "recipe_keys": []}})

    with pytest.raises(migration.MigrationError, match="different source fingerprint"):
        migration.main(args, env={})


def test_json_migration_same_migration_id_with_non_applied_status_fails(
    tmp_path: Path,
    store: PostgresChatStateStore,
) -> None:
    source = tmp_path / "history.json"
    migration_id = f"migration-{uuid.uuid4().hex}"
    _write_source(source, {str(_chat_id()): {"recipe_ids": ["r001"], "recipe_keys": []}})

    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_state_json_import_runs (
                    migration_id,
                    source_fingerprint,
                    source_metadata_json,
                    result_json,
                    status
                )
                VALUES (%s, %s, '{}'::jsonb, '{}'::jsonb, 'started')
                """,
                (migration_id, migration._source_fingerprint(source)),
            )

    with pytest.raises(migration.MigrationError, match="status"):
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


def _write_source(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
