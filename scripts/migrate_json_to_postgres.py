from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from diet_bot.promo_codes import PromoCodeRecord, load_promo_codes
from diet_bot.subscriptions import Entitlement


LIMITED_SCOPE = "non_payment_state_only"
LIMITED_MODE_MESSAGE = "limited migration: only non-payment state is applied"
SUCCESSFUL_ORDER_STATUSES = {"paid", "succeeded", "successful", "completed"}


class MigrationSafetyError(RuntimeError):
    pass


class MigrationResult:
    def __init__(
        self,
        *,
        dry_run: bool,
        applied: bool,
        already_applied: bool,
        scope: str,
        summary: dict[str, int],
        audit: dict[str, Any],
    ) -> None:
        self.dry_run = dry_run
        self.applied = applied
        self.already_applied = already_applied
        self.scope = scope
        self.summary = summary
        self.audit = audit

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "applied": self.applied,
            "already_applied": self.already_applied,
            "scope": self.scope,
            "summary": self.summary,
            "audit": self.audit,
        }


def run_migration(argv: list[str] | None = None, *, store: Any | None = None) -> MigrationResult:
    args = _parse_args(argv)
    apply_requested = bool(args.apply)
    scope = args.scope or ("payment_ledger_required" if args.require_payment_ledger else LIMITED_SCOPE)
    limited_mode = scope == LIMITED_SCOPE

    if apply_requested:
        _validate_apply_guard(args)

    sources = _load_sources(args)
    plan = _build_plan(sources, limited_mode=limited_mode)
    audit = _build_audit(args, plan, apply_requested=apply_requested, limited_mode=limited_mode)

    if not apply_requested:
        return MigrationResult(
            dry_run=True,
            applied=False,
            already_applied=False,
            scope=scope,
            summary=dict(plan["summary"]),
            audit=audit,
        )

    target_store = store if store is not None else _build_postgres_store(args.database_url)
    if _migration_already_applied(target_store, args.migration_id):
        audit["already_applied"] = True
        return MigrationResult(
            dry_run=False,
            applied=False,
            already_applied=True,
            scope=scope,
            summary=dict(plan["summary"]),
            audit=audit,
        )

    _apply_plan(target_store, plan)
    _record_migration_applied(target_store, args.migration_id, scope, plan["summary"])
    return MigrationResult(
        dry_run=False,
        applied=True,
        already_applied=False,
        scope=scope,
        summary=dict(plan["summary"]),
        audit=audit,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_migration(argv)
    except MigrationSafetyError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=_json_default))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Guarded JSON-to-Postgres migration for FoodBalance bot state.",
    )
    parser.add_argument("--migration-id", required=True)
    parser.add_argument("--database-url", default=os.getenv("DIET_BOT_DATABASE_URL", ""))
    parser.add_argument("--state-file", type=Path, default=Path(".diet_bot_state/history.json"))
    parser.add_argument(
        "--subscriptions-file",
        type=Path,
        default=Path(".diet_bot_state/subscriptions.json"),
    )
    parser.add_argument(
        "--promo-codes-file",
        type=Path,
        default=Path(".diet_bot_state/promo_codes.json"),
    )
    parser.add_argument(
        "--payment-orders-file",
        type=Path,
        default=Path(".diet_bot_state/payment_orders.json"),
    )
    parser.add_argument("--profiles-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--require-payment-ledger", action="store_true")
    parser.add_argument("--scope", choices=[LIMITED_SCOPE])
    parser.add_argument("--acknowledge-no-payment-ledger", action="store_true")
    return parser.parse_args(argv)


def _validate_apply_guard(args: argparse.Namespace) -> None:
    limited_pair = args.scope == LIMITED_SCOPE and args.acknowledge_no_payment_ledger
    if args.acknowledge_no_payment_ledger and args.scope != LIMITED_SCOPE:
        raise MigrationSafetyError(
            "--acknowledge-no-payment-ledger is only valid with --scope non_payment_state_only."
        )
    if args.scope == LIMITED_SCOPE and not args.acknowledge_no_payment_ledger:
        raise MigrationSafetyError(
            "Apply with --scope non_payment_state_only requires --acknowledge-no-payment-ledger."
        )
    if not args.require_payment_ledger and not limited_pair:
        raise MigrationSafetyError(
            "Apply requires --require-payment-ledger or the explicit limited pair "
            "--scope non_payment_state_only --acknowledge-no-payment-ledger. "
            "Processed charge ids are not a payment ledger."
        )


def _load_sources(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "state": _read_json_object(args.state_file),
        "subscriptions": _read_json_object(args.subscriptions_file),
        "promo_codes": load_promo_codes(args.promo_codes_file),
        "payment_orders": _load_payment_orders(args.payment_orders_file),
        "profiles": _read_json_object(args.profiles_file) if args.profiles_file else {},
    }


def _build_plan(sources: dict[str, Any], *, limited_mode: bool) -> dict[str, Any]:
    summary = _empty_summary()
    chat_states, profiles_from_state = _extract_chat_states_and_profiles(sources["state"])
    profiles = dict(profiles_from_state)
    profiles.update(_normalize_profiles(sources["profiles"]))
    entitlements, entitlement_stats = _extract_entitlements(
        sources["subscriptions"],
        limited_mode=limited_mode,
    )
    payment_orders, payment_order_stats = _normalize_payment_orders(sources["payment_orders"])

    summary["chat_states"] = len(chat_states)
    summary["profiles"] = len(profiles)
    summary["entitlements"] = len(entitlements)
    summary["promo_codes"] = len(sources["promo_codes"])
    summary["payment_orders"] = len(payment_orders)
    summary["payment_orders_metadata_only"] = len(payment_orders)
    summary.update(entitlement_stats)
    summary.update(payment_order_stats)

    return {
        "chat_states": chat_states,
        "profiles": profiles,
        "entitlements": entitlements,
        "promo_codes": sources["promo_codes"],
        "payment_orders": payment_orders,
        "summary": summary,
    }


def _build_audit(
    args: argparse.Namespace,
    plan: dict[str, Any],
    *,
    apply_requested: bool,
    limited_mode: bool,
) -> dict[str, Any]:
    limitations = [LIMITED_MODE_MESSAGE] if limited_mode else []
    warnings: list[str] = []
    if plan["summary"]["processed_charge_ids_ignored"]:
        warnings.append("processed charge ids were imported only as non-ledger metadata and ignored in limited mode")
    if plan["summary"]["successful_payment_orders_not_applied"]:
        warnings.append("successful payment order statuses were not applied as payments")

    return {
        "migration_id": args.migration_id,
        "write_mode": "apply" if apply_requested else "dry_run",
        "scope": LIMITED_SCOPE if limited_mode else "payment_ledger_required",
        "limitations": limitations,
        "warnings": warnings,
        "source_files": {
            "state": str(args.state_file),
            "subscriptions": str(args.subscriptions_file),
            "promo_codes": str(args.promo_codes_file),
            "payment_orders": str(args.payment_orders_file),
            "profiles": str(args.profiles_file) if args.profiles_file else None,
        },
        "would_write": dict(plan["summary"]),
    }


def _apply_plan(store: Any, plan: dict[str, Any]) -> None:
    for chat_id, state in sorted(plan["chat_states"].items()):
        store.save_chat_state(chat_id, state)
    for user_id, profile in sorted(plan["profiles"].items()):
        store.save_profile_data(user_id, profile)
    for user_id, entitlement in sorted(plan["entitlements"].items()):
        store.save_entitlement(user_id, entitlement)
    for code, record in sorted(plan["promo_codes"].items()):
        store.upsert_promo_code(code, record)
    for order in plan["payment_orders"]:
        _apply_payment_order_metadata(store, order)


def _apply_payment_order_metadata(store: Any, order: dict[str, Any]) -> None:
    order_id = str(order["order_id"])
    if hasattr(store, "load_payment_order") and store.load_payment_order(order_id) is not None:
        return

    store.create_payment_order(
        order_id=order_id,
        nonce=str(order["nonce"]),
        user_id=int(order["user_id"]),
        delivery_chat_id=order.get("delivery_chat_id"),
        product=str(order["product"]),
        provider=str(order["provider"]),
        amount=int(order["amount"]),
        currency=str(order["currency"]),
        expires_at=order["expires_at"],
    )
    invoice_link = order.get("invoice_link")
    if invoice_link and hasattr(store, "mark_payment_order_invoice_link"):
        store.mark_payment_order_invoice_link(order_id, str(invoice_link))

    status = str(order.get("status", "pending"))
    if status == "expired" and hasattr(store, "mark_payment_order_expired"):
        store.mark_payment_order_expired(order_id)
    elif status == "failed_invoice_creation" and hasattr(
        store,
        "mark_payment_order_invoice_creation_failed",
    ):
        store.mark_payment_order_invoice_creation_failed(order_id)


def _extract_chat_states_and_profiles(
    raw_state: dict[str, Any],
) -> tuple[dict[int, dict[str, object]], dict[int, dict[str, object]]]:
    chat_states: dict[int, dict[str, object]] = {}
    profiles: dict[int, dict[str, object]] = {}
    for raw_chat_id, raw_value in raw_state.items():
        chat_id = _optional_int(raw_chat_id)
        if chat_id is None or not isinstance(raw_value, dict):
            continue
        profile = raw_value.get("profile")
        if isinstance(profile, dict):
            profiles[chat_id] = dict(profile)
        chat_state = {
            str(key): value
            for key, value in raw_value.items()
            if key != "profile"
        }
        if chat_state:
            chat_states[chat_id] = chat_state
    return chat_states, profiles


def _normalize_profiles(raw_profiles: dict[str, Any]) -> dict[int, dict[str, object]]:
    profiles: dict[int, dict[str, object]] = {}
    for raw_user_id, raw_profile in raw_profiles.items():
        user_id = _optional_int(raw_user_id)
        if user_id is not None and isinstance(raw_profile, dict):
            profiles[user_id] = dict(raw_profile)
    return profiles


def _extract_entitlements(
    raw_subscriptions: dict[str, Any],
    *,
    limited_mode: bool,
) -> tuple[dict[int, Entitlement], dict[str, int]]:
    entitlements: dict[int, Entitlement] = {}
    paid_sanitized = 0
    processed_ignored = 0
    for raw_user_id, raw_entitlement in raw_subscriptions.items():
        user_id = _optional_int(raw_user_id)
        if user_id is None or not isinstance(raw_entitlement, dict):
            continue
        entitlement = Entitlement.from_dict(raw_entitlement)
        if limited_mode:
            if _has_paid_launch_state(entitlement):
                paid_sanitized += 1
            if entitlement.processed_payment_charge_ids:
                processed_ignored += 1
            entitlement = _non_payment_entitlement(entitlement)
        entitlements[user_id] = entitlement
    return entitlements, {
        "paid_entitlements_sanitized": paid_sanitized,
        "processed_charge_ids_ignored": processed_ignored,
    }


def _non_payment_entitlement(entitlement: Entitlement) -> Entitlement:
    return Entitlement(
        free_trial_used=entitlement.free_trial_used,
        test_access_until=entitlement.test_access_until,
        test_access_enabled=entitlement.test_access_enabled,
    )


def _has_paid_launch_state(entitlement: Entitlement) -> bool:
    return any(
        [
            entitlement.subscription_period_start,
            entitlement.subscription_period_end,
            entitlement.monthly_one_day_remaining,
            entitlement.monthly_weekly_pdf_remaining,
            entitlement.extra_one_day_remaining,
            entitlement.extra_weekly_pdf_remaining,
            entitlement.processed_payment_charge_ids,
        ]
    )


def _load_payment_orders(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path)
    if isinstance(raw, dict):
        raw_orders = raw.get("orders", raw)
    else:
        raw_orders = raw

    if isinstance(raw_orders, list):
        return [dict(order) for order in raw_orders if isinstance(order, dict)]
    if isinstance(raw_orders, dict):
        orders: list[dict[str, Any]] = []
        for order_id, raw_order in raw_orders.items():
            if not isinstance(raw_order, dict):
                continue
            order = dict(raw_order)
            order.setdefault("order_id", str(order_id))
            orders.append(order)
        return orders
    return []


def _normalize_payment_orders(raw_orders: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    orders: list[dict[str, Any]] = []
    successful_not_applied = 0
    for raw_order in raw_orders:
        order = _normalize_payment_order(raw_order)
        if order is None:
            continue
        if str(order.get("status", "")).lower() in SUCCESSFUL_ORDER_STATUSES:
            successful_not_applied += 1
        orders.append(order)
    return orders, {"successful_payment_orders_not_applied": successful_not_applied}


def _normalize_payment_order(raw_order: dict[str, Any]) -> dict[str, Any] | None:
    order_id = _optional_str(raw_order.get("order_id"))
    user_id = _optional_int(raw_order.get("user_id"))
    product = _optional_str(raw_order.get("product"))
    provider = _optional_str(raw_order.get("provider"))
    currency = _optional_str(raw_order.get("currency"))
    if not order_id or user_id is None or not product or not provider or not currency:
        return None
    amount = _non_negative_int(raw_order.get("amount"))
    expires_at = _parse_datetime(raw_order.get("expires_at")) or datetime.now(UTC) + timedelta(days=1)
    status = _optional_str(raw_order.get("status")) or "pending"
    normalized = {
        "order_id": order_id,
        "nonce": _optional_str(raw_order.get("nonce")) or f"json-migration:{order_id}",
        "user_id": user_id,
        "delivery_chat_id": _optional_int(raw_order.get("delivery_chat_id")),
        "product": product,
        "provider": provider,
        "amount": amount,
        "currency": currency,
        "status": status,
        "invoice_link": _optional_str(raw_order.get("invoice_link")),
        "expires_at": expires_at,
    }
    return normalized


def _migration_already_applied(store: Any, migration_id: str) -> bool:
    if hasattr(store, "has_json_migration"):
        return bool(store.has_json_migration(migration_id))
    if not hasattr(store, "_connect"):
        return False
    with store._connect() as conn:
        with conn.cursor() as cur:
            _ensure_tracking_table(cur)
            cur.execute(
                "SELECT 1 FROM json_to_postgres_migrations WHERE migration_id = %s",
                (migration_id,),
            )
            return cur.fetchone() is not None


def _record_migration_applied(
    store: Any,
    migration_id: str,
    scope: str,
    summary: dict[str, int],
) -> None:
    if hasattr(store, "record_json_migration"):
        store.record_json_migration(migration_id, dict(summary))
        return
    if not hasattr(store, "_connect"):
        return
    with store._connect() as conn:
        with conn.cursor() as cur:
            _ensure_tracking_table(cur)
            cur.execute(
                """
                INSERT INTO json_to_postgres_migrations (migration_id, scope, summary_json)
                VALUES (%s, %s, %s)
                ON CONFLICT (migration_id) DO NOTHING
                """,
                (migration_id, scope, _jsonb(dict(summary))),
            )


def _ensure_tracking_table(cur: Any) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS json_to_postgres_migrations (
            migration_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _build_postgres_store(database_url: str) -> Any:
    if not database_url:
        raise MigrationSafetyError("--database-url or DIET_BOT_DATABASE_URL is required for --apply.")
    from diet_bot.postgres_store import PostgresDietBotStore

    store = PostgresDietBotStore(database_url)
    store.initialize()
    return store


def _read_json_object(path: Path) -> dict[str, Any]:
    raw = _read_json(path)
    return raw if isinstance(raw, dict) else {}


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _empty_summary() -> dict[str, int]:
    return {
        "chat_states": 0,
        "profiles": 0,
        "entitlements": 0,
        "promo_codes": 0,
        "payment_orders": 0,
        "payment_orders_metadata_only": 0,
        "paid_entitlements_sanitized": 0,
        "processed_charge_ids_ignored": 0,
        "successful_payment_orders_not_applied": 0,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
