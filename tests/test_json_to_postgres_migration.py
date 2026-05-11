from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from diet_bot.payments import PaymentOrder
from diet_bot.postgres_store import PostgresDietBotStore
from diet_bot.promo_codes import PromoCodeRecord, promo_code_lookup_key
from diet_bot.subscriptions import Entitlement
from scripts.migrate_json_to_postgres import (
    migrate_all,
    migrate_history,
    migrate_payment_orders,
    migrate_processed_payment_charges,
    migrate_promo_codes,
    migrate_subscriptions,
)


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")
postgres_integration = pytest.mark.postgres_integration


class FakePostgresStore:
    def __init__(self) -> None:
        self.entitlements: dict[int, Entitlement] = {}
        self.orders: list[PaymentOrder] = []
        self.charges: set[tuple[str, str]] = set()
        self.history: dict[int, dict[str, object]] = {}
        self.profiles: dict[int, dict[str, object]] = {}
        self.promo_codes: set[str] = set()

    def save_entitlement(self, user_id: int, entitlement: Entitlement) -> None:
        self.entitlements[user_id] = entitlement

    def save_chat_history(self, chat_id: int, *, recipe_ids: list[str], recipe_keys: list[str]) -> None:
        self.history[chat_id] = {"recipe_ids": recipe_ids, "recipe_keys": recipe_keys}

    def save_profile_data(self, user_id: int, profile_data: dict[str, object]) -> None:
        self.profiles[user_id] = profile_data

    def create_payment_order(self, order: PaymentOrder) -> None:
        self.orders.append(order)

    def import_promo_record(self, code: str, record: PromoCodeRecord) -> None:
        self.promo_codes.add(promo_code_lookup_key(code))

    def import_processed_payment_charge(
        self,
        user_id: int,
        *,
        provider: str,
        charge_id: str,
        amount: int | None = None,
        currency: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        status: str = "processed",
    ) -> bool:
        key = (provider, charge_id)
        if key in self.charges:
            return False
        self.charges.add(key)
        return True

    def chat_state_exists(self, chat_id: int) -> bool:
        return chat_id in self.history

    def profile_exists(self, user_id: int) -> bool:
        return user_id in self.profiles

    def entitlement_exists(self, user_id: int) -> bool:
        return user_id in self.entitlements

    def payment_order_exists(self, order_id: str) -> bool:
        return any(order.order_id == order_id for order in self.orders)

    def processed_payment_charge_exists(self, *, provider: str, charge_id: str) -> bool:
        return (provider, charge_id) in self.charges

    def promo_code_exists(self, code: str) -> bool:
        return promo_code_lookup_key(code) in self.promo_codes


def test_migration_imports_processed_charge_ids_from_json_entitlements(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.json"
    path.write_text(
        json.dumps(
            {
                "123": Entitlement(
                    processed_payment_charge_ids=[
                        "telegram_stars:charge-known-provider",
                        "legacy-charge",
                    ],
                ).to_dict()
            }
        ),
        encoding="utf-8",
    )
    store = FakePostgresStore()

    report = migrate_subscriptions(store, path)

    assert report == {
        "entitlements": 1,
        "processed_payment_charges": 4,
        "skipped_existing_entitlements": 0,
        "skipped_invalid_entitlements": 0,
    }
    assert ("telegram_stars", "charge-known-provider") in store.charges
    assert ("telegram_stars", "legacy-charge") in store.charges
    assert ("yookassa", "legacy-charge") in store.charges
    assert ("telegram", "legacy-charge") in store.charges


def test_migration_imports_payment_orders(tmp_path: Path) -> None:
    path = tmp_path / "payment_orders.json"
    order = PaymentOrder.create(
        user_id=123,
        delivery_chat_id=123,
        product="subscription_month",
        provider="telegram_stars",
        amount=499,
        currency="XTR",
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )
    path.write_text(json.dumps({"orders": {order.order_id: order.to_dict()}}), encoding="utf-8")
    store = FakePostgresStore()

    report = migrate_payment_orders(store, path)

    assert report == {"orders": 1, "skipped_orders": 0, "skipped_existing_orders": 0}
    assert store.orders == [order]


def test_migration_imports_processed_charge_registry(tmp_path: Path) -> None:
    path = tmp_path / "processed_payment_charges.json"
    path.write_text(
        json.dumps(
            {
                "telegram_stars:registry-charge": {
                    "provider": "telegram_stars",
                    "charge_id": "registry-charge",
                    "user_id": 123,
                    "kind": "extra_one_day",
                    "created_at": "2026-05-11T20:20:00+00:00",
                },
                "broken": {
                    "provider": "telegram_stars",
                    "charge_id": "",
                    "user_id": 123,
                },
            }
        ),
        encoding="utf-8",
    )
    store = FakePostgresStore()

    report = migrate_processed_payment_charges(store, path)

    assert report == {
        "processed_payment_charges": 1,
        "skipped_processed_payment_charges": 1,
        "skipped_existing_processed_payment_charges": 0,
    }
    assert ("telegram_stars", "registry-charge") in store.charges


def test_migration_dry_run_does_not_write_to_store(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    subscriptions_path = tmp_path / "subscriptions.json"
    payment_orders_path = tmp_path / "payment_orders.json"
    processed_charges_path = tmp_path / "processed_payment_charges.json"
    promo_codes_path = tmp_path / "promo_codes.json"
    order = PaymentOrder.create(
        user_id=123,
        delivery_chat_id=123,
        product="subscription_month",
        provider="telegram_stars",
        amount=499,
        currency="XTR",
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )
    history_path.write_text(
        json.dumps({"123": {"recipe_ids": ["r1"], "recipe_keys": ["k1"], "profile": {"goal": "fit"}}}),
        encoding="utf-8",
    )
    subscriptions_path.write_text(json.dumps({"123": Entitlement(extra_one_day_remaining=1).to_dict()}), encoding="utf-8")
    payment_orders_path.write_text(json.dumps({"orders": {order.order_id: order.to_dict()}}), encoding="utf-8")
    processed_charges_path.write_text(
        json.dumps({"telegram_stars:c1": {"provider": "telegram_stars", "charge_id": "c1", "user_id": 123}}),
        encoding="utf-8",
    )
    promo_codes_path.write_text(json.dumps({"codes": {"FB-AAAA-BBBB-CCCC": PromoCodeRecord().to_dict()}}), encoding="utf-8")
    store = FakePostgresStore()

    report = migrate_all(
        store,
        {
            "history": history_path,
            "subscriptions": subscriptions_path,
            "payment_orders": payment_orders_path,
            "processed_payment_charges": processed_charges_path,
            "promo_codes": promo_codes_path,
        },
        dry_run=True,
    )

    assert report["history"]["chats"] == 1
    assert report["subscriptions"]["entitlements"] == 1
    assert report["payment_orders"]["orders"] == 1
    assert report["processed_payment_charge_registry"]["processed_payment_charges"] == 1
    assert report["promo_codes"]["promo_codes"] == 1
    assert store.history == {}
    assert store.entitlements == {}
    assert store.orders == []
    assert store.charges == set()
    assert store.promo_codes == set()


def test_migration_apply_skips_existing_targets(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.json"
    path.write_text(json.dumps({"123": Entitlement(extra_one_day_remaining=5).to_dict()}), encoding="utf-8")
    store = FakePostgresStore()
    store.entitlements[123] = Entitlement(extra_one_day_remaining=1)

    report = migrate_subscriptions(store, path)

    assert report["entitlements"] == 0
    assert report["skipped_existing_entitlements"] == 1
    assert store.entitlements[123].extra_one_day_remaining == 1


@postgres_integration
def test_live_postgres_migration_round_trips_json_snapshot_and_runtime_paths(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    store = PostgresDietBotStore(TEST_DATABASE_URL)
    store.initialize()

    user_id = _unique_live_user_id()
    other_user_id = _unique_live_user_id()
    run_id = uuid.uuid4().hex
    now = datetime(2026, 5, 11, tzinfo=UTC)
    subscription_end = now + timedelta(days=30)
    migrated_charge_id = f"migration-charge-{run_id}"
    registry_charge_id = f"registry-charge-{run_id}"
    payment_charge_id = f"payment-order-charge-{run_id}"
    promo_code = f"FB-{run_id[:4]}-{run_id[4:8]}-{run_id[8:12]}".upper()
    order = PaymentOrder.create(
        user_id=user_id,
        delivery_chat_id=user_id,
        product="subscription_month",
        provider="telegram_stars",
        amount=499,
        currency="XTR",
        now=now,
    )

    history_path = tmp_path / "history.json"
    subscriptions_path = tmp_path / "subscriptions.json"
    payment_orders_path = tmp_path / "payment_orders.json"
    processed_charges_path = tmp_path / "processed_payment_charges.json"
    promo_codes_path = tmp_path / "promo_codes.json"

    history_path.write_text(
        json.dumps(
            {
                str(user_id): {
                    "recipe_ids": ["recipe-live"],
                    "recipe_keys": ["breakfast-live"],
                    "profile": {"goal": "maintenance", "calories": 2100},
                }
            }
        ),
        encoding="utf-8",
    )
    subscriptions_path.write_text(
        json.dumps(
            {
                str(user_id): Entitlement(
                    subscription_period_start=now.isoformat(),
                    subscription_period_end=subscription_end.isoformat(),
                    monthly_one_day_remaining=2,
                    monthly_weekly_pdf_remaining=1,
                    processed_payment_charge_ids=[f"telegram_stars:{migrated_charge_id}"],
                ).to_dict()
            }
        ),
        encoding="utf-8",
    )
    payment_orders_path.write_text(
        json.dumps({"orders": {order.order_id: order.to_dict()}}),
        encoding="utf-8",
    )
    processed_charges_path.write_text(
        json.dumps(
            {
                f"telegram_stars:{registry_charge_id}": {
                    "provider": "telegram_stars",
                    "charge_id": registry_charge_id,
                    "user_id": user_id,
                    "kind": "subscription",
                    "created_at": now.isoformat(),
                }
            }
        ),
        encoding="utf-8",
    )
    promo_codes_path.write_text(
        json.dumps(
            {
                "codes": {
                    promo_code: PromoCodeRecord(
                        used_by_chat_id=user_id,
                        used_at=now.isoformat(),
                    ).to_dict()
                }
            }
        ),
        encoding="utf-8",
    )

    try:
        assert migrate_history(store, history_path) == {
            "chats": 1,
            "profiles": 1,
            "skipped_existing_chats": 0,
            "skipped_existing_profiles": 0,
            "skipped_invalid_chats": 0,
        }
        assert migrate_subscriptions(store, subscriptions_path) == {
            "entitlements": 1,
            "processed_payment_charges": 1,
            "skipped_existing_entitlements": 0,
            "skipped_invalid_entitlements": 0,
        }
        assert migrate_processed_payment_charges(store, processed_charges_path) == {
            "processed_payment_charges": 1,
            "skipped_processed_payment_charges": 0,
            "skipped_existing_processed_payment_charges": 0,
        }
        assert migrate_payment_orders(store, payment_orders_path) == {
            "orders": 1,
            "skipped_orders": 0,
            "skipped_existing_orders": 0,
        }
        assert migrate_promo_codes(store, promo_codes_path) == {
            "promo_codes": 1,
            "redemptions": 1,
            "skipped_existing_promo_codes": 0,
            "skipped_invalid_promo_codes": 0,
        }

        state = store.load_chat_state(user_id)
        assert state["recipe_ids"] == ["recipe-live"]
        assert state["recipe_keys"] == ["breakfast-live"]
        assert state["profile"] == {"goal": "maintenance", "calories": 2100}
        entitlement = store.get_entitlement(user_id)
        assert entitlement.monthly_one_day_remaining == 2
        assert entitlement.monthly_weekly_pdf_remaining == 1
        assert entitlement.is_subscription_active(now)
        assert not store.import_processed_payment_charge(
            other_user_id,
            provider="telegram_stars",
            charge_id=migrated_charge_id,
            raw_payload={"source": "duplicate-check"},
        )
        assert not store.import_processed_payment_charge(
            other_user_id,
            provider="telegram_stars",
            charge_id=registry_charge_id,
            raw_payload={"source": "registry-duplicate-check"},
        )
        assert store.get_payment_order(order.order_id) == order
        assert store.activate_promo_code(user_id, promo_code).status == "already_used"

        paid = store.apply_payment_order(
            user_id,
            order_id=order.order_id,
            nonce=order.nonce,
            delivery_chat_id=order.delivery_chat_id,
            provider=order.provider,
            charge_id=payment_charge_id,
            amount=order.amount,
            currency=order.currency,
            raw_payload={"source": "live-migration-test"},
        )
        duplicate = store.apply_payment_order(
            other_user_id,
            order_id=order.order_id,
            nonce=order.nonce,
            delivery_chat_id=order.delivery_chat_id,
            provider=order.provider,
            charge_id=payment_charge_id,
            amount=order.amount,
            currency=order.currency,
            raw_payload={"source": "live-migration-test-duplicate"},
        )
        assert paid.processed
        assert duplicate.duplicate
        assert store.get_payment_order(order.order_id).status == "paid"

        generation = store.consume_generation_attempt(user_id, "one_day")
        locked = store.consume_generation_attempt(user_id, "weekly_pdf")
        assert generation.allowed
        assert generation.meal_plan_id is not None
        assert not locked.allowed
        assert locked.denial_reason == "already_generating"

        store.refund_generation_attempt(user_id, generation, error_message="live migration test")
        after_refund = store.consume_generation_attempt(user_id, "one_day")
        assert after_refund.allowed
        assert after_refund.meal_plan_id is not None
        store.complete_generation_attempt(user_id, after_refund, pdf_path="live-migration-test.pdf")
    finally:
        _cleanup_live_users(store, user_id, other_user_id)
        _cleanup_live_promo_codes(store, promo_code)


def _unique_live_user_id() -> int:
    return 8_000_000_000 + uuid.uuid4().int % 900_000_000


def _cleanup_live_users(store: PostgresDietBotStore, *user_ids: int) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE telegram_id = ANY(%s)", (list(user_ids),))


def _cleanup_live_promo_codes(store: PostgresDietBotStore, *codes: str) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            lookup_keys = [promo_code_lookup_key(code) for code in codes]
            cur.execute("DELETE FROM promo_codes WHERE code = ANY(%s)", (lookup_keys,))
