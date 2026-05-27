from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .chat_state_storage import (
    ChatState,
    ChatStateByChatId,
    ChatStateStorageError,
    _normalize_chat_state,
    _normalize_state,
)
from .postgres_chat_state_migrations import MIGRATIONS, run_chat_state_schema_migrations
from .postgres_schema_validation import (
    SCHEMA_MIGRATIONS_COLUMNS,
    PostgresSchemaExpectation,
    validate_postgres_schema,
)


CHAT_STATE_IMPORT_LOCK_ID = 4_382_026_052_300_002
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1

CHAT_STATE_SCHEMA_EXPECTATION = PostgresSchemaExpectation(
    component="chat state",
    migration_versions=tuple(migration.version for migration in MIGRATIONS),
    table_columns={
        "schema_migrations": SCHEMA_MIGRATIONS_COLUMNS,
        "chat_profiles": (
            "chat_id",
            "profile_json",
            "profile_format_version",
            "created_at",
            "updated_at",
            "version",
        ),
        "chat_recipe_history": (
            "chat_id",
            "recipe_ids",
            "recipe_keys",
            "created_at",
            "updated_at",
            "version",
        ),
        "chat_state_json_import_runs": (
            "migration_id",
            "source_fingerprint",
            "source_metadata_json",
            "result_json",
            "status",
            "started_at",
            "finished_at",
        ),
    },
    indexes=("chat_profiles_pkey", "chat_recipe_history_pkey"),
    constraints=(
        "chk_chat_profiles_profile_json_object",
        "chk_chat_profiles_profile_format_version_positive",
        "chk_chat_profiles_version_positive",
        "chk_chat_recipe_history_recipe_ids_array",
        "chk_chat_recipe_history_recipe_keys_array",
        "chk_chat_recipe_history_version_positive",
        "chk_chat_state_json_import_runs_status",
    ),
    remediation="Run chat state migrations before startup.",
)


class PostgresChatStateStore:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = 5,
        connect_attempts: int = 3,
        retry_base_delay: float = 0.2,
        retry_max_delay: float = 1.0,
    ) -> None:
        self.dsn = dsn
        self.connect_timeout = connect_timeout
        self.connect_attempts = max(1, connect_attempts)
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay

    def initialize(self) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    run_chat_state_schema_migrations(cur)

    def validate_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                validate_postgres_schema(
                    cur,
                    CHAT_STATE_SCHEMA_EXPECTATION,
                    error_cls=ChatStateStorageError,
                )

    def load_all(self) -> ChatStateByChatId:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._load_all_cur(cur)

    def load_chat_state(self, chat_id: int) -> ChatState:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._load_chat_state_cur(cur, int(chat_id))

    def save_all(self, state: Mapping[str, Mapping[str, object]]) -> None:
        normalized = _normalize_import_chat_state(state)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._replace_chat_state_cur(cur, normalized)

    def apply_json_import(
        self,
        *,
        migration_id: str,
        source_fingerprint: str,
        source_metadata: Mapping[str, Any],
        chat_state: Mapping[str, Mapping[str, object]],
        result_payload: Mapping[str, Any],
        allow_non_empty_target: bool = False,
    ) -> dict[str, Any]:
        normalized = _normalize_import_chat_state(chat_state)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._lock_import_cur(cur)
                    cur.execute(
                        """
                        SELECT migration_id, source_fingerprint, result_json, status
                        FROM chat_state_json_import_runs
                        WHERE migration_id = %s
                        FOR UPDATE
                        """,
                        (migration_id,),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        if str(existing["source_fingerprint"]) != source_fingerprint:
                            raise ChatStateStorageError(
                                f"JSON import migration_id {migration_id!r} has a different source fingerprint.",
                            )
                        if str(existing["status"]) != "applied":
                            raise ChatStateStorageError(
                                f"JSON import migration_id {migration_id!r} is recorded with status "
                                f"{existing['status']!r}.",
                            )
                        return dict(existing["result_json"])

                    if not allow_non_empty_target:
                        self._require_empty_json_import_target_cur(cur)

                    cur.execute(
                        """
                        INSERT INTO chat_state_json_import_runs (
                            migration_id,
                            source_fingerprint,
                            source_metadata_json,
                            result_json,
                            status
                        )
                        VALUES (%s, %s, %s, '{}'::jsonb, 'started')
                        """,
                        (migration_id, source_fingerprint, _jsonb(dict(source_metadata))),
                    )
                    self._replace_chat_state_cur(cur, normalized)
                    loaded = self._load_all_cur(cur)
                    if loaded != normalized:
                        raise ChatStateStorageError(
                            "Postgres chat state parity check failed after JSON import.",
                        )

                    payload = dict(result_payload)
                    cur.execute(
                        """
                        UPDATE chat_state_json_import_runs
                        SET status = 'applied',
                            result_json = %s,
                            finished_at = now()
                        WHERE migration_id = %s
                        """,
                        (_jsonb(payload), migration_id),
                    )
                    return payload

    def save_chat_state(self, chat_id: int, chat_state: Mapping[str, object]) -> None:
        chat_id = int(chat_id)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if "profile" in chat_state:
                        profile = chat_state["profile"]
                        if isinstance(profile, Mapping):
                            normalized = _normalize_chat_state({"profile": profile}, source=_MEMORY_SOURCE)
                            self._upsert_profile_cur(cur, chat_id, normalized["profile"])
                        else:
                            cur.execute("DELETE FROM chat_profiles WHERE chat_id = %s", (chat_id,))

                    if "recipe_ids" in chat_state or "recipe_keys" in chat_state:
                        existing = self._load_history_cur(cur, chat_id, for_update=True)
                        merged = dict(existing)
                        if "recipe_ids" in chat_state:
                            merged["recipe_ids"] = chat_state["recipe_ids"]
                        if "recipe_keys" in chat_state:
                            merged["recipe_keys"] = chat_state["recipe_keys"]
                        normalized = _normalize_chat_state(merged, source=_MEMORY_SOURCE)
                        self._upsert_history_cur(
                            cur,
                            chat_id,
                            normalized.get("recipe_ids", []),
                            normalized.get("recipe_keys", []),
                        )

    def _load_all_cur(self, cur: Any) -> ChatStateByChatId:
        state: dict[str, ChatState] = {}
        cur.execute(
            """
            SELECT chat_id, profile_json
            FROM chat_profiles
            ORDER BY chat_id
            """
        )
        for row in cur.fetchall():
            chat_id = str(int(row["chat_id"]))
            state[chat_id] = _normalize_chat_state(
                {"profile": dict(row["profile_json"] or {})},
                source=_MEMORY_SOURCE,
            )

        cur.execute(
            """
            SELECT chat_id, recipe_ids, recipe_keys
            FROM chat_recipe_history
            ORDER BY chat_id
            """
        )
        for row in cur.fetchall():
            chat_id = str(int(row["chat_id"]))
            current = dict(state.get(chat_id, {}))
            current["recipe_ids"] = list(row["recipe_ids"] or [])
            current["recipe_keys"] = list(row["recipe_keys"] or [])
            state[chat_id] = _normalize_chat_state(current, source=_MEMORY_SOURCE)
        return state

    def _load_chat_state_cur(self, cur: Any, chat_id: int) -> ChatState:
        current: dict[str, object] = {}
        cur.execute(
            """
            SELECT profile_json
            FROM chat_profiles
            WHERE chat_id = %s
            """,
            (int(chat_id),),
        )
        profile_row = cur.fetchone()
        if profile_row is not None:
            current["profile"] = dict(profile_row["profile_json"] or {})

        cur.execute(
            """
            SELECT recipe_ids, recipe_keys
            FROM chat_recipe_history
            WHERE chat_id = %s
            """,
            (int(chat_id),),
        )
        history_row = cur.fetchone()
        if history_row is not None:
            current["recipe_ids"] = list(history_row["recipe_ids"] or [])
            current["recipe_keys"] = list(history_row["recipe_keys"] or [])

        if not current:
            return {}
        return _normalize_chat_state(current, source=_MEMORY_SOURCE)

    def _load_history_cur(self, cur: Any, chat_id: int, *, for_update: bool = False) -> ChatState:
        suffix = " FOR UPDATE" if for_update else ""
        cur.execute(
            f"""
            SELECT recipe_ids, recipe_keys
            FROM chat_recipe_history
            WHERE chat_id = %s{suffix}
            """,
            (int(chat_id),),
        )
        row = cur.fetchone()
        if row is None:
            return _normalize_chat_state({}, source=_MEMORY_SOURCE)
        return _normalize_chat_state(
            {
                "recipe_ids": list(row["recipe_ids"] or []),
                "recipe_keys": list(row["recipe_keys"] or []),
            },
            source=_MEMORY_SOURCE,
        )

    def _replace_chat_state_cur(self, cur: Any, normalized: ChatStateByChatId) -> None:
        chat_ids = sorted(int(chat_id) for chat_id in normalized)
        if chat_ids:
            cur.execute("DELETE FROM chat_profiles WHERE NOT (chat_id = ANY(%s))", (chat_ids,))
            cur.execute("DELETE FROM chat_recipe_history WHERE NOT (chat_id = ANY(%s))", (chat_ids,))
        else:
            cur.execute("DELETE FROM chat_profiles")
            cur.execute("DELETE FROM chat_recipe_history")

        for chat_id_text in sorted(normalized, key=int):
            chat_id = int(chat_id_text)
            chat_state = normalized[chat_id_text]
            if "profile" in chat_state:
                self._upsert_profile_cur(cur, chat_id, chat_state["profile"])
            else:
                cur.execute("DELETE FROM chat_profiles WHERE chat_id = %s", (chat_id,))
            self._upsert_history_cur(
                cur,
                chat_id,
                chat_state.get("recipe_ids", []),
                chat_state.get("recipe_keys", []),
            )

    def _upsert_profile_cur(self, cur: Any, chat_id: int, profile: object) -> None:
        if not isinstance(profile, Mapping):
            raise ChatStateStorageError(f"Invalid profile value for chat_id {chat_id}")
        cur.execute(
            """
            INSERT INTO chat_profiles (chat_id, profile_json)
            VALUES (%s, %s)
            ON CONFLICT (chat_id) DO UPDATE SET
                profile_json = EXCLUDED.profile_json,
                updated_at = clock_timestamp(),
                version = chat_profiles.version + 1
            """,
            (int(chat_id), _jsonb(dict(profile))),
        )

    def _upsert_history_cur(
        self,
        cur: Any,
        chat_id: int,
        recipe_ids: object,
        recipe_keys: object,
    ) -> None:
        normalized = _normalize_chat_state(
            {"recipe_ids": recipe_ids, "recipe_keys": recipe_keys},
            source=_MEMORY_SOURCE,
        )
        cur.execute(
            """
            INSERT INTO chat_recipe_history (chat_id, recipe_ids, recipe_keys)
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE SET
                recipe_ids = EXCLUDED.recipe_ids,
                recipe_keys = EXCLUDED.recipe_keys,
                updated_at = clock_timestamp(),
                version = chat_recipe_history.version + 1
            """,
            (
                int(chat_id),
                _jsonb(normalized["recipe_ids"]),
                _jsonb(normalized["recipe_keys"]),
            ),
        )

    def _lock_import_cur(self, cur: Any) -> None:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (CHAT_STATE_IMPORT_LOCK_ID,))

    def _require_empty_json_import_target_cur(self, cur: Any) -> None:
        counts = self._json_import_target_counts_cur(cur)
        if not any(counts.values()):
            return
        formatted_counts = ", ".join(f"{name}={count}" for name, count in counts.items())
        raise ChatStateStorageError(
            "Refusing JSON chat state import into non-empty Postgres target "
            f"({formatted_counts}). Pass --allow-non-empty-target only after verifying "
            "the replacement is intentional.",
        )

    def _json_import_target_counts_cur(self, cur: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table_name in ("chat_profiles", "chat_recipe_history"):
            cur.execute(f"SELECT count(*) AS count FROM {table_name}")
            counts[table_name] = int(cur.fetchone()["count"])
        return counts

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install PostgreSQL driver with `pip install psycopg[binary]`.") from exc

        last_error: Exception | None = None
        for attempt in range(1, self.connect_attempts + 1):
            try:
                return psycopg.connect(
                    self.dsn,
                    row_factory=dict_row,
                    connect_timeout=self.connect_timeout,
                )
            except psycopg.OperationalError as exc:
                last_error = exc
                if attempt >= self.connect_attempts:
                    break
                delay = min(self.retry_max_delay, self.retry_base_delay * (2 ** (attempt - 1)))
                time.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Could not connect to PostgreSQL.")


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _normalize_import_chat_state(state: Mapping[str, Mapping[str, object]]) -> ChatStateByChatId:
    normalized = _normalize_state(state, source=_MEMORY_SOURCE)
    canonical: ChatStateByChatId = {}
    for chat_id_text, chat_state in normalized.items():
        try:
            chat_id = int(chat_id_text)
        except (TypeError, ValueError) as exc:
            raise ChatStateStorageError(f"Invalid chat state chat id: {chat_id_text!r}") from exc
        if chat_id < _BIGINT_MIN or chat_id > _BIGINT_MAX:
            raise ChatStateStorageError(f"Invalid chat state chat id: {chat_id_text!r}")
        canonical[str(chat_id)] = chat_state
    return canonical


_MEMORY_SOURCE = Path("<memory>")
