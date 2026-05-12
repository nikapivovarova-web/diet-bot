from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
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


def test_postgres_entitlement_round_trips_existing_model() -> None:
    from diet_bot.subscriptions import Entitlement

    store = _store()
    user_id = _unique_user_id()
    entitlement = Entitlement(
        free_trial_used=True,
        subscription_period_start="2026-05-10T00:00:00+00:00",
        subscription_period_end="2026-06-09T00:00:00+00:00",
        test_access_until="2027-05-10T00:00:00+00:00",
        test_access_enabled=True,
        monthly_one_day_remaining=3,
        monthly_weekly_pdf_remaining=2,
        extra_one_day_remaining=1,
        extra_weekly_pdf_remaining=4,
        processed_payment_charge_ids=["charge-1", "charge-2"],
    )
    try:
        store.save_entitlement(user_id, entitlement)

        assert store.get_entitlement(user_id) == entitlement
    finally:
        _cleanup_users(store, user_id)


def test_postgres_generation_consumption_and_refund_are_atomic() -> None:
    from diet_bot.subscriptions import Entitlement, apply_subscription_payment, grant_test_access

    store = _store()
    user_id = _unique_user_id()
    test_access_user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-subscription",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 1
    test_access_entitlement = Entitlement(monthly_one_day_remaining=2, monthly_weekly_pdf_remaining=3)
    grant_test_access(test_access_entitlement, now=now)
    try:
        store.save_entitlement(user_id, entitlement)
        store.save_entitlement(test_access_user_id, test_access_entitlement)

        consumed = store.consume_generation_attempt(user_id, "one_day")
        store.refund_generation_attempt(user_id, consumed, error_message="builder failed")
        store.refund_generation_attempt(user_id, consumed, error_message="late duplicate")
        test_access_consumed = store.consume_generation_attempt(test_access_user_id, "weekly_pdf")
        store.refund_generation_attempt(
            test_access_user_id,
            test_access_consumed,
            error_message="test access failure",
        )

        generation = _latest_generation_for_user(store, user_id)
        events = _events_for_generation(store, generation["id"])
        test_access_generation = _latest_generation_for_user(store, test_access_user_id)
        test_access_events = _events_for_generation(store, test_access_generation["id"])

        assert consumed.allowed
        assert consumed.source == "monthly"
        assert store.get_entitlement(user_id).monthly_one_day_remaining == 1
        assert generation["status"] == "failed"
        assert [event["event_type"] for event in events] == ["consume", "refund"]
        assert events[0]["generation_id"] == generation["id"]
        assert events[0]["delta_generations"] == -1
        assert events[1]["related_event_id"] == events[0]["id"]
        assert events[1]["delta_generations"] == 1

        assert test_access_consumed.allowed
        assert test_access_consumed.source == "test_access"
        reloaded_test_access = store.get_entitlement(test_access_user_id)
        assert reloaded_test_access.monthly_one_day_remaining == 2
        assert reloaded_test_access.monthly_weekly_pdf_remaining == 3
        assert [event["event_type"] for event in test_access_events] == ["consume", "refund"]
        assert [event["amount"] for event in test_access_events] == [0, 0]
        assert [event["delta_generations"] for event in test_access_events] == [0, 0]
    finally:
        _cleanup_users(store, user_id, test_access_user_id)


def test_postgres_one_active_generation_per_user() -> None:
    from diet_bot.subscriptions import Entitlement, apply_subscription_payment

    store = _store()
    user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-subscription",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 2
    try:
        store.save_entitlement(user_id, entitlement)

        first = store.consume_generation_attempt(user_id, "one_day")
        second = store.consume_generation_attempt(user_id, "one_day")
        store.refund_generation_attempt(user_id, first, error_message="release active lock")
        third = store.consume_generation_attempt(user_id, "one_day")

        assert first.allowed
        assert not second.allowed
        assert third.allowed
        assert _active_generation_count(store, user_id) == 1
    finally:
        _cleanup_users(store, user_id)


def test_postgres_stale_generation_cleanup_refunds_once() -> None:
    from diet_bot.subscriptions import Entitlement, apply_subscription_payment

    store = _store()
    user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-subscription",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 1
    try:
        store.save_entitlement(user_id, entitlement)
        consumed = store.consume_generation_attempt(user_id, "one_day")
        generation = _latest_generation_for_user(store, user_id)
        _age_generation(store, generation["id"], now - timedelta(minutes=45))

        cleaned = store.cleanup_stale_generations(now=now)
        cleaned_again = store.cleanup_stale_generations(now=now)
        store.refund_generation_attempt(user_id, consumed, error_message="late duplicate")

        generation = _latest_generation_for_user(store, user_id)
        events = _events_for_generation(store, generation["id"])
        assert consumed.allowed
        assert cleaned == 1
        assert cleaned_again == 0
        assert store.get_entitlement(user_id).monthly_one_day_remaining == 1
        assert generation["status"] == "failed_timeout"
        assert [event["event_type"] for event in events] == ["consume", "refund"]
    finally:
        _cleanup_users(store, user_id)


def test_postgres_completed_generation_is_not_refunded_by_late_failure() -> None:
    from diet_bot.subscriptions import Entitlement, apply_subscription_payment

    store = _store()
    user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-subscription",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_weekly_pdf_remaining = 1
    try:
        store.save_entitlement(user_id, entitlement)
        consumed = store.consume_generation_attempt(user_id, "weekly_pdf")
        assert store.start_generation_delivery(user_id, consumed)
        store.complete_generation_attempt(
            user_id,
            consumed,
            pdf_path="/tmp/weekly-ration.pdf",
            telegram_message_id=12345,
        )

        store.refund_generation_attempt(user_id, consumed, error_message="late delivery failure")
        cleaned = store.cleanup_stale_generations(now=now + timedelta(hours=2))

        generation = _latest_generation_for_user(store, user_id)
        events = _events_for_generation(store, generation["id"])
        assert consumed.allowed
        assert cleaned == 0
        assert store.get_entitlement(user_id).monthly_weekly_pdf_remaining == 0
        assert generation["status"] == "completed"
        assert generation["pdf_path"] == "/tmp/weekly-ration.pdf"
        assert generation["telegram_message_id"] == 12345
        assert [event["event_type"] for event in events] == ["consume"]
    finally:
        _cleanup_users(store, user_id)


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


def _latest_generation_for_user(store: Any, user_id: int) -> dict[str, Any]:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM generation_records
                WHERE user_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
    assert row is not None
    return dict(row)


def _events_for_generation(store: Any, generation_id: int) -> list[dict[str, Any]]:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, generation_id, event_type, source, amount, related_event_id,
                       delta_generations, metadata_json
                FROM entitlement_events
                WHERE generation_id = %s
                ORDER BY id
                """,
                (generation_id,),
            )
            return [dict(row) for row in cur.fetchall()]


def _active_generation_count(store: Any, user_id: int) -> int:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS active_count
                FROM generation_records
                WHERE user_id = %s AND status IN ('generating', 'delivering')
                """,
                (user_id,),
            )
            row = cur.fetchone()
    return int(row["active_count"])


def _age_generation(store: Any, generation_id: int, when: datetime) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE generation_records
                SET heartbeat_at = %s,
                    expires_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (when, when, when, generation_id),
            )
