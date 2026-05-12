from __future__ import annotations

import os
import uuid
from typing import Any

import pytest


pytestmark = pytest.mark.postgres_integration


def test_postgres_initialize_is_idempotent_and_records_migrations() -> None:
    from diet_bot.postgres_migrations import POSTGRES_MIGRATIONS

    store = _store()

    store.initialize()
    store.initialize()

    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version, description FROM schema_migrations ORDER BY version")
            migration_rows = cur.fetchall()

    recorded = {str(row["version"]): str(row["description"]) for row in migration_rows}
    for migration in POSTGRES_MIGRATIONS:
        assert recorded[migration.version] == migration.description


def test_postgres_connection_applies_statement_and_lock_timeouts() -> None:
    store = _store(statement_timeout_ms=1234, lock_timeout_ms=234)
    store.initialize()

    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    current_setting('statement_timeout') AS statement_timeout,
                    current_setting('lock_timeout') AS lock_timeout
                """
            )
            row = cur.fetchone()

    assert row["statement_timeout"] == "1234ms"
    assert row["lock_timeout"] == "234ms"


def test_postgres_remember_user_upserts_last_seen() -> None:
    from diet_bot.storage import UserIdentity

    store = _store()
    user_id = _unique_user_id()
    try:
        store.remember_user(UserIdentity(user_id, username="old-name", first_name="Old"))
        with store._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET last_seen_at = TIMESTAMPTZ '2026-01-01 00:00:00+00' WHERE telegram_id = %s",
                    (user_id,),
                )

        store.remember_user(UserIdentity(user_id, username="new-name", first_name="New"))

        with store._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT username, first_name, created_at, last_seen_at
                    FROM users
                    WHERE telegram_id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()

        assert row["username"] == "new-name"
        assert row["first_name"] == "New"
        assert row["last_seen_at"] > row["created_at"]
    finally:
        _cleanup_users(store, user_id)


def test_postgres_profile_round_trips_json() -> None:
    store = _store()
    user_id = _unique_user_id()
    profile = {
        "goal": "fat_loss",
        "calories": 1840,
        "allergies": ["peanut", "shrimp"],
        "flags": {"vegetarian": False, "include_snacks": True},
        "notes": None,
    }
    try:
        store.save_profile_data(user_id, profile)

        assert store.load_profile_data(user_id) == profile
    finally:
        _cleanup_users(store, user_id)


def test_postgres_chat_state_round_trips_recent_history() -> None:
    store = _store()
    chat_id = _unique_user_id()
    state = {
        "recent_history": [
            {"role": "user", "content": "I want a weekly meal plan"},
            {"role": "assistant", "content": "Collecting profile"},
        ],
        "recipe_ids": ["breakfast-1", "dinner-2"],
        "metadata": {"questionnaire_step": 3, "done": False},
    }
    try:
        store.save_chat_state(chat_id, state)

        assert store.load_chat_state(chat_id) == state
    finally:
        _cleanup_users(store, chat_id)


def _store(**kwargs: Any):
    from diet_bot.postgres_store import PostgresDietBotStore

    store = PostgresDietBotStore(_test_database_url(), **kwargs)
    store.initialize()
    return store


def _test_database_url() -> str:
    database_url = os.getenv("DIET_BOT_TEST_DATABASE_URL")
    assert database_url
    return database_url


def _unique_user_id() -> int:
    return 9_000_000_000 + uuid.uuid4().int % 900_000_000


def _cleanup_users(store: Any, *user_ids: int) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE telegram_id = ANY(%s)", (list(user_ids),))
