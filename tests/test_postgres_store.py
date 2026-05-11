import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.payments import (
    PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
    PAYMENT_EVENT_CHARGEBACK,
    PAYMENT_EVENT_REFUND,
    PaymentOrder,
)
from diet_bot.postgres_store import PostgresDietBotStore
from diet_bot.promo_codes import promo_code_lookup_key
from diet_bot.subscriptions import (
    LEDGER_EVENT_CONSUME,
    LEDGER_EVENT_REFUND,
    Entitlement,
    MONTHLY_ONE_DAY_LIMIT,
    MONTHLY_WEEKLY_PDF_LIMIT,
    apply_subscription_payment,
)


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


def test_postgres_payment_idempotency_uses_provider_and_charge_id() -> None:
    store = _store()
    user_id = _unique_user_id()
    other_user_id = _unique_user_id()
    charge_id = f"charge-{uuid.uuid4().hex}"
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-subscription",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    try:
        store.save_entitlement(user_id, entitlement)

        first = store.apply_payment(
            user_id,
            provider="yookassa",
            charge_id=charge_id,
            grant="extra_one_day",
            amount=5_000,
            currency="RUB",
            raw_payload={"source": "test"},
        )
        duplicate = store.apply_payment(
            other_user_id,
            provider="yookassa",
            charge_id=charge_id,
            grant="extra_one_day",
            amount=5_000,
            currency="RUB",
            raw_payload={"source": "test"},
        )
        same_charge_other_provider = store.apply_payment(
            user_id,
            provider="telegram_stars",
            charge_id=charge_id,
            grant="extra_one_day",
            amount=35,
            currency="XTR",
            raw_payload={"source": "test"},
        )

        assert first.processed
        assert duplicate.duplicate
        assert same_charge_other_provider.processed
        assert store.get_entitlement(user_id).extra_one_day_remaining == 2
        assert store.get_entitlement(other_user_id).extra_one_day_remaining == 0
    finally:
        _cleanup_users(store, user_id, other_user_id)


def test_postgres_initialize_is_idempotent_and_records_migrations() -> None:
    store = _store()

    store.initialize()

    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS count FROM schema_migrations")
            migration_count = int(cur.fetchone()["count"])
            cur.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conname IN (
                    'chk_entitlements_counters_non_negative',
                    'chk_payment_orders_status_allowed',
                    'chk_payment_events_provider_allowed'
                )
                """
            )
            constraints = {row["conname"] for row in cur.fetchall()}

    assert migration_count >= 3
    assert constraints == {
        "chk_entitlements_counters_non_negative",
        "chk_payment_orders_status_allowed",
        "chk_payment_events_provider_allowed",
    }


def test_postgres_constraints_reject_negative_runtime_counters() -> None:
    store = _store()
    user_id = _unique_user_id()

    try:
        with pytest.raises(Exception):
            with store._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO users (telegram_id) VALUES (%s)", (user_id,))
                    cur.execute(
                        """
                        INSERT INTO entitlements (user_id, monthly_one_day_remaining)
                        VALUES (%s, -1)
                        """,
                        (user_id,),
                    )
    finally:
        _cleanup_users(store, user_id)


def test_postgres_json_import_run_is_one_shot() -> None:
    store = _store()
    migration_id = f"json-import-{uuid.uuid4().hex}"
    try:
        with store.json_import_lock():
            run_id = store.begin_json_import_run(
                migration_id=migration_id,
                source_fingerprint="fingerprint-1",
                source_summary={"history": {"exists": False}},
            )
            store.finish_json_import_run(run_id, status="applied", result={"ok": True})

        with store.json_import_lock():
            with pytest.raises(RuntimeError, match="already been applied"):
                store.begin_json_import_run(
                    migration_id=f"{migration_id}-second",
                    source_fingerprint="fingerprint-1",
                    source_summary={"history": {"exists": False}},
                )
    finally:
        with store._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM import_runs WHERE migration_id = %s", (migration_id,))


def test_postgres_pre_checkout_marks_expired_pending_order(monkeypatch) -> None:
    store = _store()
    user_id = _unique_user_id()
    order = PaymentOrder.create(
        user_id=user_id,
        delivery_chat_id=user_id,
        product="subscription_month",
        provider="telegram_stars",
        amount=400,
        currency="XTR",
        now=datetime.now(UTC) - timedelta(hours=2),
        ttl_seconds=60,
    )
    try:
        store.create_payment_order(order)
        monkeypatch.setattr(telegram_app, "_postgres_store", lambda: store)

        query = SimpleNamespace(
            invoice_payload=order.payload,
            currency=order.currency,
            total_amount=order.amount,
            from_user=SimpleNamespace(id=user_id),
        )

        assert not telegram_app._is_valid_pre_checkout(query)
        expired_order = store.get_payment_order(order.order_id)
        assert expired_order is not None
        assert expired_order.status == "expired"
    finally:
        _cleanup_users(store, user_id)


def test_postgres_extra_payment_requires_active_subscription() -> None:
    store = _store()
    user_id = _unique_user_id()
    try:
        result = store.apply_payment(
            user_id,
            provider="yookassa",
            charge_id=f"charge-{uuid.uuid4().hex}",
            grant="extra_one_day",
            amount=5_000,
            currency="RUB",
            raw_payload={"source": "test"},
        )

        assert not result.processed
        assert result.grant == "extra_one_day"
        assert store.get_entitlement(user_id).extra_one_day_remaining == 0
    finally:
        _cleanup_users(store, user_id)


def test_postgres_refund_revokes_access_and_cancel_keeps_paid_period() -> None:
    store = _store()
    refunded_user_id = _unique_user_id()
    cancelled_user_id = _unique_user_id()
    refund_charge_id = f"refund-{uuid.uuid4().hex}"
    cancel_charge_id = f"cancel-{uuid.uuid4().hex}"
    try:
        refund_payment = store.apply_payment(
            refunded_user_id,
            provider="telegram_stars",
            charge_id=refund_charge_id,
            grant="subscription",
            amount=400,
            currency="XTR",
            raw_payload={"source": "test"},
        )
        refund_event = store.apply_payment_event(
            refunded_user_id,
            event_type=PAYMENT_EVENT_REFUND,
            provider="telegram_stars",
            charge_id=refund_charge_id,
            amount=400,
            currency="XTR",
            raw_payload={"source": "test-refund"},
        )
        duplicate_refund = store.apply_payment_event(
            refunded_user_id,
            event_type=PAYMENT_EVENT_REFUND,
            provider="telegram_stars",
            charge_id=refund_charge_id,
            amount=400,
            currency="XTR",
            raw_payload={"source": "duplicate"},
        )

        cancel_payment = store.apply_payment(
            cancelled_user_id,
            provider="telegram_stars",
            charge_id=cancel_charge_id,
            grant="subscription",
            amount=400,
            currency="XTR",
            raw_payload={"source": "test"},
        )
        cancel_event = store.apply_payment_event(
            cancelled_user_id,
            event_type=PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
            provider="telegram_stars",
            charge_id=cancel_charge_id,
            amount=400,
            currency="XTR",
            raw_payload={"source": "test-cancel"},
        )

        assert refund_payment.processed
        assert refund_event.processed
        assert duplicate_refund.duplicate
        assert not store.get_entitlement(refunded_user_id).is_subscription_active()
        assert store.get_entitlement(refunded_user_id).monthly_one_day_remaining == 0
        assert store.get_entitlement(refunded_user_id).monthly_weekly_pdf_remaining == 0
        assert cancel_payment.processed
        assert cancel_event.processed
        assert store.get_entitlement(cancelled_user_id).is_subscription_active()
        assert store.get_entitlement(cancelled_user_id).monthly_one_day_remaining == MONTHLY_ONE_DAY_LIMIT
        assert store.get_entitlement(cancelled_user_id).monthly_weekly_pdf_remaining == MONTHLY_WEEKLY_PDF_LIMIT
    finally:
        _cleanup_users(store, refunded_user_id, cancelled_user_id)


def test_postgres_chargeback_reverses_extra_attempt_without_stopping_subscription() -> None:
    store = _store()
    user_id = _unique_user_id()
    subscription_charge_id = f"subscription-{uuid.uuid4().hex}"
    extra_charge_id = f"extra-{uuid.uuid4().hex}"
    try:
        subscription = store.apply_payment(
            user_id,
            provider="telegram_stars",
            charge_id=subscription_charge_id,
            grant="subscription",
            amount=400,
            currency="XTR",
            raw_payload={"source": "test-subscription"},
        )
        extra = store.apply_payment(
            user_id,
            provider="telegram_stars",
            charge_id=extra_charge_id,
            grant="extra_one_day",
            amount=35,
            currency="XTR",
            raw_payload={"source": "test-extra"},
        )
        chargeback = store.apply_payment_event(
            user_id,
            event_type=PAYMENT_EVENT_CHARGEBACK,
            provider="telegram_stars",
            charge_id=extra_charge_id,
            amount=35,
            currency="XTR",
            raw_payload={"source": "test-chargeback"},
        )
        entitlement = store.get_entitlement(user_id)

        assert subscription.processed
        assert extra.processed
        assert chargeback.processed
        assert entitlement.is_subscription_active()
        assert entitlement.extra_one_day_remaining == 0
    finally:
        _cleanup_users(store, user_id)


def test_postgres_refund_after_consumed_extra_is_ignored_with_precise_reason() -> None:
    store = _store()
    user_id = _unique_user_id()
    subscription_charge_id = f"subscription-{uuid.uuid4().hex}"
    extra_charge_id = f"extra-{uuid.uuid4().hex}"
    try:
        subscription = store.apply_payment(
            user_id,
            provider="telegram_stars",
            charge_id=subscription_charge_id,
            grant="subscription",
            amount=400,
            currency="XTR",
            raw_payload={"source": "test-subscription"},
        )
        extra = store.apply_payment(
            user_id,
            provider="telegram_stars",
            charge_id=extra_charge_id,
            grant="extra_one_day",
            amount=35,
            currency="XTR",
            raw_payload={"source": "test-extra"},
        )
        entitlement = store.get_entitlement(user_id)
        entitlement.monthly_one_day_remaining = 1
        store.save_entitlement(user_id, entitlement)

        monthly = store.consume_generation_attempt(user_id, "one_day")
        consumed_extra = store.consume_generation_attempt(user_id, "one_day")
        refund = store.apply_payment_event(
            user_id,
            event_type=PAYMENT_EVENT_REFUND,
            provider="telegram_stars",
            charge_id=extra_charge_id,
            amount=35,
            currency="XTR",
            raw_payload={"source": "test-refund"},
        )
        updated = store.get_entitlement(user_id)

        assert subscription.processed
        assert extra.processed
        assert monthly.source == "monthly"
        assert consumed_extra.source == "extra"
        assert not refund.processed
        assert refund.reason == "extra_already_consumed"
        assert updated.extra_one_day_remaining == 0
    finally:
        _cleanup_users(store, user_id)


def test_postgres_unknown_and_orphan_events_do_not_grant_access() -> None:
    store = _store()
    user_id = _unique_user_id()
    try:
        unknown = store.apply_payment_event(
            user_id,
            event_type="provider-surprise",
            provider="yookassa",
            charge_id=f"unknown-{uuid.uuid4().hex}",
            amount=1_000,
            currency="RUB",
            raw_payload={"source": "unknown"},
        )
        orphan_refund = store.apply_payment_event(
            user_id,
            event_type=PAYMENT_EVENT_REFUND,
            provider="yookassa",
            charge_id=f"orphan-{uuid.uuid4().hex}",
            amount=1_000,
            currency="RUB",
            raw_payload={"source": "orphan"},
        )
        entitlement = store.get_entitlement(user_id)

        assert not unknown.processed
        assert unknown.reason == "unknown_event_type"
        assert not orphan_refund.processed
        assert orphan_refund.reason == "original_payment_not_found"
        assert not entitlement.is_subscription_active()
        assert entitlement.extra_one_day_remaining == 0
        assert entitlement.extra_weekly_pdf_remaining == 0
    finally:
        _cleanup_users(store, user_id)


def test_postgres_promo_redemption_is_one_per_user_and_respects_max_uses() -> None:
    store = _store()
    user_id = _unique_user_id()
    other_user_id = _unique_user_id()
    code = f"FB-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:4]}".upper()
    try:
        store.upsert_promo_code(code, max_uses=1)

        first = store.activate_promo_code(user_id, code, now=datetime(2026, 5, 10, tzinfo=UTC))
        repeated_by_same_user = store.activate_promo_code(user_id, code)
        exhausted_for_other_user = store.activate_promo_code(other_user_id, code)

        assert first.activated
        assert repeated_by_same_user.status == "already_used"
        assert exhausted_for_other_user.status == "not_found"
        assert store.get_entitlement(user_id).is_subscription_active(datetime(2026, 5, 10, tzinfo=UTC))
        assert not store.get_entitlement(other_user_id).is_subscription_active(datetime(2026, 5, 10, tzinfo=UTC))
    finally:
        _cleanup_users(store, user_id, other_user_id)
        _cleanup_promo_codes(store, code)


def test_postgres_generation_consumption_and_refund_are_persisted() -> None:
    store = _store()
    user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-charge",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 1
    try:
        store.save_entitlement(user_id, entitlement)

        consumed = store.consume_generation_attempt(user_id, "one_day")
        denied = store.consume_generation_attempt(user_id, "one_day")
        store.refund_generation_attempt(user_id, consumed, error_message="test failure")
        store.refund_generation_attempt(user_id, consumed, error_message="duplicate refund")
        after_refund = store.consume_generation_attempt(user_id, "one_day")

        assert consumed.allowed
        assert consumed.source == "monthly"
        assert consumed.meal_plan_id is not None
        assert not denied.allowed
        assert denied.denial_reason == "already_generating"
        assert after_refund.allowed
        assert after_refund.source == "monthly"
        events = _events_for_meal_plan(store, consumed.meal_plan_id)
        assert [event["event_type"] for event in events] == [LEDGER_EVENT_CONSUME, LEDGER_EVENT_REFUND]
        assert events[0]["source"] == "monthly_one_day"
        assert events[0]["delta_generations"] == -1
        assert events[0]["amount"] == 1
        assert events[1]["related_event_id"] == events[0]["id"]
        assert events[1]["delta_generations"] == 1
    finally:
        _cleanup_users(store, user_id)


def test_postgres_records_analytics_events() -> None:
    store = _store()
    user_id = _unique_user_id()
    try:
        store.record_analytics_event(
            user_id,
            "checkout_started",
            {
                "product": "subscription_month",
                "provider": "telegram_stars",
            },
        )

        with store._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, event_name, properties_json
                    FROM analytics_events
                    WHERE user_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (user_id,),
                )
                row = cur.fetchone()

        assert row["user_id"] == user_id
        assert row["event_name"] == "checkout_started"
        assert row["properties_json"] == {
            "product": "subscription_month",
            "provider": "telegram_stars",
        }
    finally:
        _cleanup_users(store, user_id)


def test_postgres_stale_generation_cleanup_releases_lock_and_refunds_once() -> None:
    store = _store()
    user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-charge",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 1
    try:
        store.save_entitlement(user_id, entitlement)
        stale = store.consume_generation_attempt(user_id, "one_day")
        assert stale.allowed
        assert stale.meal_plan_id is not None

        _age_meal_plan(store, stale.meal_plan_id)
        next_attempt = store.consume_generation_attempt(user_id, "one_day")

        assert next_attempt.allowed
        assert next_attempt.meal_plan_id != stale.meal_plan_id
        assert store.get_entitlement(user_id).monthly_one_day_remaining == 0
        assert _meal_plan_status(store, stale.meal_plan_id) == "failed_timeout"
        stale_events = _events_for_meal_plan(store, stale.meal_plan_id)
        assert [event["event_type"] for event in stale_events] == [LEDGER_EVENT_CONSUME, LEDGER_EVENT_REFUND]

    finally:
        _cleanup_users(store, user_id)


def test_postgres_global_stale_cleanup_refunds_without_user_retry() -> None:
    store = _store()
    user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-charge",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 1
    try:
        store.save_entitlement(user_id, entitlement)
        stale = store.consume_generation_attempt(user_id, "one_day")
        assert stale.allowed
        assert stale.meal_plan_id is not None

        _age_meal_plan(store, stale.meal_plan_id)
        cleaned = store.cleanup_stale_generations()
        cleaned_again = store.cleanup_stale_generations()
        store.complete_generation_attempt(user_id, stale)

        assert cleaned == 1
        assert cleaned_again == 0
        assert store.get_entitlement(user_id).monthly_one_day_remaining == 1
        assert _meal_plan_status(store, stale.meal_plan_id) == "failed_timeout"
        stale_events = _events_for_meal_plan(store, stale.meal_plan_id)
        assert [event["event_type"] for event in stale_events] == [LEDGER_EVENT_CONSUME, LEDGER_EVENT_REFUND]
    finally:
        _cleanup_users(store, user_id)


def test_postgres_heartbeat_keeps_old_generation_active() -> None:
    store = _store()
    user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-charge",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 1
    try:
        store.save_entitlement(user_id, entitlement)
        generation = store.consume_generation_attempt(user_id, "one_day")
        assert generation.allowed
        assert generation.meal_plan_id is not None

        _age_meal_plan(store, generation.meal_plan_id)
        assert store.heartbeat_generation_attempt(user_id, generation)
        cleaned = store.cleanup_stale_generations()
        denied = store.consume_generation_attempt(user_id, "one_day")

        assert cleaned == 0
        assert not denied.allowed
        assert denied.denial_reason == "already_generating"
        assert store.get_entitlement(user_id).monthly_one_day_remaining == 0
        assert _meal_plan_status(store, generation.meal_plan_id) == "generating"
    finally:
        _cleanup_users(store, user_id)


def test_postgres_delivering_generation_holds_lock_and_times_out_once() -> None:
    store = _store()
    user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-charge",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_weekly_pdf_remaining = 1
    try:
        store.save_entitlement(user_id, entitlement)
        generation = store.consume_generation_attempt(user_id, "weekly_pdf")
        assert generation.allowed
        assert generation.meal_plan_id is not None
        assert store.start_generation_delivery(user_id, generation)

        denied = store.consume_generation_attempt(user_id, "weekly_pdf")
        _age_meal_plan(store, generation.meal_plan_id)
        cleaned = store.cleanup_stale_generations()
        cleaned_again = store.cleanup_stale_generations()
        store.refund_generation_attempt(user_id, generation, error_message="late duplicate")

        assert not denied.allowed
        assert denied.denial_reason == "already_generating"
        assert cleaned == 1
        assert cleaned_again == 0
        assert store.get_entitlement(user_id).monthly_weekly_pdf_remaining == 1
        assert _meal_plan_status(store, generation.meal_plan_id) == "failed_timeout"
        stale_events = _events_for_meal_plan(store, generation.meal_plan_id)
        assert [event["event_type"] for event in stale_events] == [LEDGER_EVENT_CONSUME, LEDGER_EVENT_REFUND]
    finally:
        _cleanup_users(store, user_id)


def test_postgres_completed_generation_is_not_refunded_by_late_failure() -> None:
    store = _store()
    user_id = _unique_user_id()
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-charge",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 1
    try:
        store.save_entitlement(user_id, entitlement)
        generation = store.consume_generation_attempt(user_id, "one_day")
        assert generation.allowed
        assert generation.meal_plan_id is not None
        assert store.start_generation_delivery(user_id, generation)
        store.complete_generation_attempt(user_id, generation, telegram_message_id=123)

        store.refund_generation_attempt(user_id, generation, error_message="late failure")
        cleaned = store.cleanup_stale_generations()
        row = _meal_plan_row(store, generation.meal_plan_id)

        assert cleaned == 0
        assert store.get_entitlement(user_id).monthly_one_day_remaining == 0
        assert row["status"] == "completed"
        assert row["telegram_message_id"] == 123
        events = _events_for_meal_plan(store, generation.meal_plan_id)
        assert [event["event_type"] for event in events] == [LEDGER_EVENT_CONSUME]
    finally:
        _cleanup_users(store, user_id)


def _store() -> PostgresDietBotStore:
    assert TEST_DATABASE_URL is not None
    store = PostgresDietBotStore(TEST_DATABASE_URL)
    store.initialize()
    return store


def _unique_user_id() -> int:
    return 9_000_000_000 + uuid.uuid4().int % 900_000_000


def _cleanup_users(store: PostgresDietBotStore, *user_ids: int) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE telegram_id = ANY(%s)", (list(user_ids),))


def _cleanup_promo_codes(store: PostgresDietBotStore, *codes: str) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM promo_codes WHERE code = ANY(%s)", ([promo_code_lookup_key(code) for code in codes],))


def _events_for_meal_plan(store: PostgresDietBotStore, meal_plan_id: int) -> list[dict]:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, event_type, source, amount, delta_generations, related_event_id
                FROM entitlement_events
                WHERE meal_plan_id = %s
                  AND event_type IN (%s, %s)
                ORDER BY id
                """,
                (meal_plan_id, LEDGER_EVENT_CONSUME, LEDGER_EVENT_REFUND),
            )
            return list(cur.fetchall())


def _age_meal_plan(store: PostgresDietBotStore, meal_plan_id: int) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE meal_plans
                SET updated_at = now() - interval '31 minutes',
                    heartbeat_at = now() - interval '31 minutes',
                    expires_at = now() - interval '1 minute'
                WHERE id = %s
                """,
                (meal_plan_id,),
            )


def _meal_plan_row(store: PostgresDietBotStore, meal_plan_id: int) -> dict:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM meal_plans WHERE id = %s", (meal_plan_id,))
            return dict(cur.fetchone())


def _meal_plan_status(store: PostgresDietBotStore, meal_plan_id: int) -> str:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM meal_plans WHERE id = %s", (meal_plan_id,))
            return str(cur.fetchone()["status"])
