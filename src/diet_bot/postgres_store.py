from __future__ import annotations

from typing import Any

from .postgres_migrations import run_postgres_migrations
from .storage import UserIdentity


class PostgresDietBotStore:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = 5,
        statement_timeout_ms: int = 5000,
        lock_timeout_ms: int = 1000,
        connect_attempts: int = 1,
    ) -> None:
        self.dsn = dsn
        self.connect_timeout = _positive_int(connect_timeout, name="connect_timeout")
        self.statement_timeout_ms = _positive_int(
            statement_timeout_ms,
            name="statement_timeout_ms",
        )
        self.lock_timeout_ms = _positive_int(lock_timeout_ms, name="lock_timeout_ms")
        self.connect_attempts = _positive_int(connect_attempts, name="connect_attempts")

    def initialize(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                run_postgres_migrations(cur)

    def healthcheck(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
        if row is None or int(row["ok"]) != 1:
            raise RuntimeError("PostgreSQL healthcheck failed")

    def remember_user(self, user: UserIdentity) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, user)

    def load_profile_data(self, user_id: int) -> dict[str, object] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT profile_json FROM profiles WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        profile = row["profile_json"]
        return dict(profile) if isinstance(profile, dict) else None

    def save_profile_data(self, user_id: int, profile_data: dict[str, object]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(user_id))
                cur.execute(
                    """
                    INSERT INTO profiles (user_id, profile_json)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET profile_json = EXCLUDED.profile_json,
                        updated_at = now()
                    """,
                    (user_id, _jsonb(profile_data)),
                )

    def load_chat_state(self, chat_id: int) -> dict[str, object]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state_json FROM chat_state WHERE chat_id = %s",
                    (chat_id,),
                )
                row = cur.fetchone()
        if row is None:
            return {}
        state = row["state_json"]
        return dict(state) if isinstance(state, dict) else {}

    def save_chat_state(self, chat_id: int, state: dict[str, object]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(chat_id))
                cur.execute(
                    """
                    INSERT INTO chat_state (chat_id, state_json)
                    VALUES (%s, %s)
                    ON CONFLICT (chat_id) DO UPDATE
                    SET state_json = EXCLUDED.state_json,
                        updated_at = now()
                    """,
                    (chat_id, _jsonb(state)),
                )

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        last_error: Exception | None = None
        for _attempt in range(self.connect_attempts):
            try:
                conn = psycopg.connect(
                    self.dsn,
                    connect_timeout=self.connect_timeout,
                    row_factory=dict_row,
                )
                self._configure_connection(conn)
                return conn
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise RuntimeError("PostgreSQL connection was not attempted")

    def _configure_connection(self, conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (f"{self.statement_timeout_ms}ms",),
            )
            cur.execute(
                "SELECT set_config('lock_timeout', %s, false)",
                (f"{self.lock_timeout_ms}ms",),
            )

    def _remember_user_cur(self, cur: Any, user: UserIdentity) -> None:
        cur.execute(
            """
            INSERT INTO users (telegram_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_seen_at = now()
            """,
            (user.telegram_id, user.username, user.first_name),
        )


def _jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _positive_int(value: int, *, name: str) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value
