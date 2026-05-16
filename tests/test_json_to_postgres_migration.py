from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from diet_bot.subscriptions import Entitlement


def test_migration_dry_run_writes_nothing(tmp_path: Path) -> None:
    migration = _migration_module()
    paths = _write_json_sources(
        tmp_path,
        state={
            "101": {
                "recipe_ids": ["breakfast-1"],
                "recipe_keys": ["breakfast-key"],
                "profile": {"goal": "lose", "meal_count": 4},
            },
        },
        subscriptions={"101": {"free_trial_used": True}},
        promo_codes={"FB-ABCD-EFGH-2345": {}},
    )
    store = FakeStore()

    result = migration.run_migration(_argv(paths, "dry-run-001"), store=store)

    assert result.dry_run is True
    assert result.applied is False
    assert result.summary["chat_states"] == 1
    assert result.summary["profiles"] == 1
    assert result.summary["entitlements"] == 1
    assert result.summary["promo_codes"] == 1
    assert result.audit["write_mode"] == "dry_run"
    assert result.audit["would_write"]["chat_states"] == 1
    assert store.calls == []
    assert store.chat_states == {}
    assert store.profiles == {}
    assert store.entitlements == {}
    assert store.promo_codes == {}
    assert store.applied_migration_ids == set()


def test_migration_apply_is_one_shot_by_migration_id(tmp_path: Path) -> None:
    migration = _migration_module()
    paths = _write_json_sources(
        tmp_path,
        state={"101": {"recipe_ids": ["one"], "profile": {"goal": "maintain"}}},
    )
    store = FakeStore()
    args = _argv(
        paths,
        "one-shot-001",
        "--apply",
        "--scope",
        "non_payment_state_only",
        "--acknowledge-no-payment-ledger",
    )

    first = migration.run_migration(args, store=store)
    calls_after_first_apply = list(store.calls)
    second = migration.run_migration(args, store=store)

    assert first.applied is True
    assert first.already_applied is False
    assert second.applied is False
    assert second.already_applied is True
    assert store.applied_migration_ids == {"one-shot-001"}
    assert store.calls == calls_after_first_apply


def test_migration_imports_history_profiles_entitlements_and_promo_codes(tmp_path: Path) -> None:
    migration = _migration_module()
    paths = _write_json_sources(
        tmp_path,
        state={
            "101": {
                "recipe_ids": ["breakfast-1", "dinner-2"],
                "recipe_keys": ["breakfast", "dinner"],
                "profile": {"age": 35, "goal": "lose", "meal_count": 4},
            },
        },
        subscriptions={
            "101": {
                "free_trial_used": True,
                "subscription_period_start": "2026-05-01T00:00:00+00:00",
                "subscription_period_end": "2026-06-01T00:00:00+00:00",
                "monthly_one_day_remaining": 5,
                "monthly_weekly_pdf_remaining": 4,
                "processed_payment_charge_ids": ["charge-old"],
            },
        },
        promo_codes={
            "FB-ABCD-EFGH-2345": {},
            "FB-WXYZ-2345-6789": {
                "used_by_chat_id": 202,
                "used_at": "2026-05-10T12:00:00+00:00",
            },
        },
    )
    store = FakeStore()

    result = migration.run_migration(
        _argv(
            paths,
            "import-core-001",
            "--apply",
            "--scope",
            "non_payment_state_only",
            "--acknowledge-no-payment-ledger",
        ),
        store=store,
    )

    assert result.applied is True
    assert store.chat_states[101] == {
        "recipe_ids": ["breakfast-1", "dinner-2"],
        "recipe_keys": ["breakfast", "dinner"],
    }
    assert store.profiles[101] == {"age": 35, "goal": "lose", "meal_count": 4}
    assert store.entitlements[101].free_trial_used is True
    assert store.entitlements[101].subscription_period_start is None
    assert store.entitlements[101].subscription_period_end is None
    assert store.entitlements[101].monthly_one_day_remaining == 0
    assert store.entitlements[101].monthly_weekly_pdf_remaining == 0
    assert store.entitlements[101].processed_payment_charge_ids == []
    assert sorted(store.promo_codes) == ["FB-ABCD-EFGH-2345", "FB-WXYZ-2345-6789"]
    assert store.promo_codes["FB-WXYZ-2345-6789"].used_by_chat_id == 202
    assert result.summary["paid_entitlements_sanitized"] == 1
    assert result.summary["processed_charge_ids_ignored"] == 1


def test_migration_blocks_paid_launch_without_payment_ledger_ack(tmp_path: Path) -> None:
    migration = _migration_module()
    paths = _write_json_sources(
        tmp_path,
        subscriptions={
            "101": {
                "subscription_period_end": "2026-06-01T00:00:00+00:00",
                "monthly_one_day_remaining": 5,
                "processed_payment_charge_ids": ["charge-old"],
            },
        },
    )
    store = FakeStore()

    with pytest.raises(migration.MigrationSafetyError, match="payment ledger"):
        migration.run_migration(_argv(paths, "blocked-001", "--apply"), store=store)

    assert store.calls == []
    assert store.applied_migration_ids == set()


def test_migration_limited_mode_reports_non_payment_state_only(tmp_path: Path) -> None:
    migration = _migration_module()
    paths = _write_json_sources(
        tmp_path,
        subscriptions={
            "101": {
                "subscription_period_end": "2026-06-01T00:00:00+00:00",
                "monthly_one_day_remaining": 5,
            },
        },
    )
    store = FakeStore()

    result = migration.run_migration(
        _argv(
            paths,
            "limited-001",
            "--apply",
            "--scope",
            "non_payment_state_only",
            "--acknowledge-no-payment-ledger",
        ),
        store=store,
    )

    assert result.scope == "non_payment_state_only"
    assert result.audit["write_mode"] == "apply"
    assert result.audit["limitations"] == [
        "limited migration: only non-payment state is applied"
    ]
    assert store.entitlements[101].subscription_period_end is None
    assert store.entitlements[101].monthly_one_day_remaining == 0


def test_migration_imports_payment_orders_as_metadata_without_granting_access(tmp_path: Path) -> None:
    migration = _migration_module()
    paths = _write_json_sources(
        tmp_path,
        payment_orders=[
            {
                "order_id": "order-101",
                "nonce": "nonce-101",
                "user_id": 101,
                "delivery_chat_id": 101,
                "product": "subscription_month",
                "provider": "telegram_stars",
                "amount": 400,
                "currency": "XTR",
                "status": "pending",
                "invoice_link": "https://pay.example.test/invoice",
                "expires_at": "2026-05-13T12:00:00+00:00",
            }
        ],
    )
    store = FakeStore()

    result = migration.run_migration(
        _argv(
            paths,
            "orders-001",
            "--apply",
            "--scope",
            "non_payment_state_only",
            "--acknowledge-no-payment-ledger",
        ),
        store=store,
    )

    assert result.applied is True
    assert result.summary["payment_orders"] == 1
    assert result.summary["payment_orders_metadata_only"] == 1
    assert store.payment_orders["order-101"]["status"] == "pending"
    assert store.payment_orders["order-101"]["invoice_link"] == "https://pay.example.test/invoice"
    assert 101 not in store.entitlements
    assert not any(call[0] == "save_entitlement" for call in store.calls)


def test_migration_preserves_managed_subscription_defaults_for_old_json(tmp_path: Path) -> None:
    migration = _migration_module()
    paths = _write_json_sources(
        tmp_path,
        subscriptions={"101": {"free_trial_used": True}},
    )
    store = FakeStore()

    migration.run_migration(
        _argv(
            paths,
            "defaults-001",
            "--apply",
            "--scope",
            "non_payment_state_only",
            "--acknowledge-no-payment-ledger",
        ),
        store=store,
    )

    entitlement = store.entitlements[101]
    assert entitlement.subscription_source == "none"
    assert entitlement.auto_renew_status == "not_applicable"
    assert entitlement.stars_subscription_charge_id is None
    assert entitlement.last_subscription_payment_charge_id is None
    assert entitlement.current_period_payment_order_id is None


def test_migration_backfills_subscription_source_from_successful_monthly_order(
    tmp_path: Path,
) -> None:
    migration = _migration_module()
    paths = _write_json_sources(
        tmp_path,
        subscriptions={
            "101": {
                "subscription_period_start": "2026-05-01T00:00:00+00:00",
                "subscription_period_end": "2099-06-01T00:00:00+00:00",
                "monthly_one_day_remaining": 5,
                "monthly_weekly_pdf_remaining": 4,
            },
            "202": {
                "subscription_period_start": "2026-05-01T00:00:00+00:00",
                "subscription_period_end": "2099-06-01T00:00:00+00:00",
                "monthly_one_day_remaining": 5,
                "monthly_weekly_pdf_remaining": 4,
            },
        },
        payment_orders=[
            {
                "order_id": "order-stars-101",
                "nonce": "nonce-stars-101",
                "user_id": 101,
                "delivery_chat_id": 101,
                "product": "subscription_month",
                "provider": "telegram_stars",
                "amount": 450,
                "currency": "XTR",
                "status": "paid",
                "expires_at": "2026-05-13T12:00:00+00:00",
            },
            {
                "order_id": "order-yookassa-202",
                "nonce": "nonce-yookassa-202",
                "user_id": 202,
                "delivery_chat_id": 202,
                "product": "subscription_month",
                "provider": "yookassa",
                "amount": 79_900,
                "currency": "RUB",
                "status": "paid",
                "expires_at": "2026-05-13T12:00:00+00:00",
            },
        ],
    )
    store = FakeStore()

    migration.run_migration(
        _argv(paths, "paid-source-001", "--apply", "--require-payment-ledger"),
        store=store,
    )

    stars = store.entitlements[101]
    yookassa = store.entitlements[202]
    assert stars.subscription_source == "telegram_stars"
    assert stars.auto_renew_status == "enabled"
    assert stars.current_period_payment_order_id == "order-stars-101"
    assert yookassa.subscription_source == "yookassa"
    assert yookassa.auto_renew_status == "not_applicable"
    assert yookassa.current_period_payment_order_id == "order-yookassa-202"


def test_migration_marks_active_unproved_monthly_access_legacy_unknown(
    tmp_path: Path,
) -> None:
    migration = _migration_module()
    paths = _write_json_sources(
        tmp_path,
        subscriptions={
            "101": {
                "subscription_period_start": "2026-05-01T00:00:00+00:00",
                "subscription_period_end": "2099-06-01T00:00:00+00:00",
                "monthly_one_day_remaining": 5,
                "monthly_weekly_pdf_remaining": 4,
            },
        },
    )
    store = FakeStore()

    migration.run_migration(
        _argv(paths, "legacy-001", "--apply", "--require-payment-ledger"),
        store=store,
    )

    entitlement = store.entitlements[101]
    assert entitlement.subscription_source == "legacy"
    assert entitlement.auto_renew_status == "unknown"
    assert entitlement.current_period_payment_order_id is None


@dataclass
class FakeStore:
    chat_states: dict[int, dict[str, Any]] = field(default_factory=dict)
    profiles: dict[int, dict[str, Any]] = field(default_factory=dict)
    entitlements: dict[int, Entitlement] = field(default_factory=dict)
    promo_codes: dict[str, Any] = field(default_factory=dict)
    payment_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    applied_migration_ids: set[str] = field(default_factory=set)
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def initialize(self) -> None:
        self.calls.append(("initialize", None))

    def has_json_migration(self, migration_id: str) -> bool:
        return migration_id in self.applied_migration_ids

    def record_json_migration(self, migration_id: str, summary: dict[str, Any]) -> None:
        self.calls.append(("record_json_migration", migration_id, dict(summary)))
        self.applied_migration_ids.add(migration_id)

    def save_chat_state(self, chat_id: int, state: dict[str, object]) -> None:
        self.calls.append(("save_chat_state", chat_id, dict(state)))
        self.chat_states[chat_id] = dict(state)

    def save_profile_data(self, user_id: int, profile_data: dict[str, object]) -> None:
        self.calls.append(("save_profile_data", user_id, dict(profile_data)))
        self.profiles[user_id] = dict(profile_data)

    def save_entitlement(self, user_id: int, entitlement: Entitlement) -> None:
        self.calls.append(("save_entitlement", user_id, entitlement.to_dict()))
        self.entitlements[user_id] = Entitlement.from_dict(entitlement.to_dict())

    def upsert_promo_code(self, code: str, record: Any) -> None:
        self.calls.append(("upsert_promo_code", code, record.to_dict()))
        self.promo_codes[code] = record

    def load_payment_order(self, order_id: str) -> dict[str, Any] | None:
        return self.payment_orders.get(order_id)

    def create_payment_order(self, **order: Any) -> dict[str, Any]:
        self.calls.append(("create_payment_order", dict(order)))
        stored = dict(order)
        stored["status"] = "pending"
        stored["invoice_link"] = None
        self.payment_orders[stored["order_id"]] = stored
        return stored

    def mark_payment_order_invoice_link(self, order_id: str, invoice_link: str) -> None:
        self.calls.append(("mark_payment_order_invoice_link", order_id, invoice_link))
        self.payment_orders[order_id]["invoice_link"] = invoice_link

    def mark_payment_order_expired(self, order_id: str) -> None:
        self.calls.append(("mark_payment_order_expired", order_id))
        self.payment_orders[order_id]["status"] = "expired"

    def mark_payment_order_invoice_creation_failed(self, order_id: str) -> None:
        self.calls.append(("mark_payment_order_invoice_creation_failed", order_id))
        self.payment_orders[order_id]["status"] = "failed_invoice_creation"


def _migration_module() -> Any:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "migrate_json_to_postgres.py"
    if not script_path.exists():
        pytest.fail("scripts/migrate_json_to_postgres.py does not exist yet")
    spec = importlib.util.spec_from_file_location("migrate_json_to_postgres", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json_sources(
    tmp_path: Path,
    *,
    state: dict[str, Any] | None = None,
    subscriptions: dict[str, Any] | None = None,
    promo_codes: dict[str, Any] | None = None,
    payment_orders: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> dict[str, Path]:
    paths = {
        "state": tmp_path / "history.json",
        "subscriptions": tmp_path / "subscriptions.json",
        "promo_codes": tmp_path / "promo_codes.json",
        "payment_orders": tmp_path / "payment_orders.json",
    }
    _write_json(paths["state"], state or {})
    _write_json(paths["subscriptions"], subscriptions or {})
    _write_json(paths["promo_codes"], {"codes": promo_codes or {}})
    _write_json(paths["payment_orders"], {"orders": payment_orders or []})
    return paths


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _argv(paths: dict[str, Path], migration_id: str, *extra_args: str) -> list[str]:
    return [
        "--migration-id",
        migration_id,
        "--state-file",
        str(paths["state"]),
        "--subscriptions-file",
        str(paths["subscriptions"]),
        "--promo-codes-file",
        str(paths["promo_codes"]),
        "--payment-orders-file",
        str(paths["payment_orders"]),
        *extra_args,
    ]
