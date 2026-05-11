from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from diet_bot.payments import PaymentOrder
from diet_bot.postgres_store import PostgresDietBotStore
from diet_bot.promo_codes import PromoCodeRecord, promo_code_lookup_key
from diet_bot.subscriptions import Entitlement


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = PROJECT_ROOT / ".diet_bot_state"
LEGACY_CHARGE_PROVIDERS = ("telegram_stars", "yookassa", "telegram")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate diet bot JSON state into PostgreSQL.")
    parser.add_argument("--database-url", default=os.getenv("DIET_BOT_DATABASE_URL"))
    parser.add_argument("--migration-id", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Write the import into PostgreSQL.")
    mode.add_argument("--dry-run", action="store_true", help="Preview the import without writing data. This is the default.")
    parser.add_argument("--history", type=Path, default=DEFAULT_STATE_DIR / "history.json")
    parser.add_argument("--subscriptions", type=Path, default=DEFAULT_STATE_DIR / "subscriptions.json")
    parser.add_argument("--promo-codes", type=Path, default=DEFAULT_STATE_DIR / "promo_codes.json")
    parser.add_argument("--payment-orders", type=Path, default=DEFAULT_STATE_DIR / "payment_orders.json")
    parser.add_argument(
        "--processed-payment-charges",
        type=Path,
        default=DEFAULT_STATE_DIR / "processed_payment_charges.json",
    )
    args = parser.parse_args()

    dry_run = not args.apply
    paths = _migration_paths(args)
    source_summary = _source_summary(paths)
    source_fingerprint = _source_fingerprint(paths)
    store = _store_for_run(args.database_url, apply=args.apply)

    if dry_run:
        report = migrate_all(store, paths, dry_run=True)
        print(
            json.dumps(
                _audit_payload(
                    mode="dry_run",
                    migration_id=args.migration_id,
                    source_fingerprint=source_fingerprint,
                    source_summary=source_summary,
                    report=report,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    assert store is not None
    store.initialize()
    with store.json_import_lock():
        run_id = store.begin_json_import_run(
            migration_id=args.migration_id,
            source_fingerprint=source_fingerprint,
            source_summary=source_summary,
        )
        try:
            report = migrate_all(store, paths, dry_run=False)
        except Exception as exc:
            failure_payload = _audit_payload(
                mode="apply",
                migration_id=args.migration_id,
                source_fingerprint=source_fingerprint,
                source_summary=source_summary,
                report={},
                import_run_id=run_id,
                error={"type": exc.__class__.__name__, "message": str(exc)},
            )
            store.finish_json_import_run(run_id, status="failed", result=failure_payload)
            raise

        audit_payload = _audit_payload(
            mode="apply",
            migration_id=args.migration_id,
            source_fingerprint=source_fingerprint,
            source_summary=source_summary,
            report=report,
            import_run_id=run_id,
        )
        store.finish_json_import_run(run_id, status="applied", result=audit_payload)
        print(json.dumps(audit_payload, ensure_ascii=False, indent=2))


def migrate_all(
    store: PostgresDietBotStore | None,
    paths: dict[str, Path],
    *,
    dry_run: bool,
) -> dict[str, dict[str, int]]:
    return {
        "history": migrate_history(store, paths["history"], dry_run=dry_run),
        "subscriptions": migrate_subscriptions(store, paths["subscriptions"], dry_run=dry_run),
        "processed_payment_charge_registry": migrate_processed_payment_charges(
            store,
            paths["processed_payment_charges"],
            dry_run=dry_run,
        ),
        "payment_orders": migrate_payment_orders(store, paths["payment_orders"], dry_run=dry_run),
        "promo_codes": migrate_promo_codes(store, paths["promo_codes"], dry_run=dry_run),
    }


def migrate_history(
    store: PostgresDietBotStore | None,
    path: Path,
    *,
    dry_run: bool = False,
    protect_existing: bool = True,
) -> dict[str, int]:
    raw = _load_json_file(path, default={})
    if not isinstance(raw, dict):
        raise RuntimeError(f"{path} must contain a JSON object.")

    migrated_chats = 0
    migrated_profiles = 0
    skipped_existing_chats = 0
    skipped_existing_profiles = 0
    skipped_invalid_chats = 0
    for chat_id_text, value in raw.items():
        try:
            chat_id = int(chat_id_text)
        except (TypeError, ValueError):
            skipped_invalid_chats += 1
            continue
        if not isinstance(value, dict):
            skipped_invalid_chats += 1
            continue

        recipe_ids = [str(item) for item in value.get("recipe_ids", []) if str(item)]
        recipe_keys = [str(item) for item in value.get("recipe_keys", []) if str(item)]
        if protect_existing and _target_exists(store, "chat_state_exists", chat_id):
            skipped_existing_chats += 1
        else:
            if not dry_run:
                _require_store(store).save_chat_history(chat_id, recipe_ids=recipe_ids, recipe_keys=recipe_keys)
            migrated_chats += 1

        profile = value.get("profile")
        if isinstance(profile, dict):
            if protect_existing and _target_exists(store, "profile_exists", chat_id):
                skipped_existing_profiles += 1
            else:
                if not dry_run:
                    _require_store(store).save_profile_data(chat_id, profile)
                migrated_profiles += 1

    return {
        "chats": migrated_chats,
        "profiles": migrated_profiles,
        "skipped_existing_chats": skipped_existing_chats,
        "skipped_existing_profiles": skipped_existing_profiles,
        "skipped_invalid_chats": skipped_invalid_chats,
    }


def migrate_subscriptions(
    store: PostgresDietBotStore | None,
    path: Path,
    *,
    dry_run: bool = False,
    protect_existing: bool = True,
) -> dict[str, int]:
    raw = _load_json_file(path, default={})
    if not isinstance(raw, dict):
        raise RuntimeError(f"{path} must contain a JSON object.")

    migrated = 0
    migrated_charges = 0
    skipped_existing_entitlements = 0
    skipped_invalid_entitlements = 0
    for chat_id_text, value in raw.items():
        try:
            chat_id = int(chat_id_text)
        except (TypeError, ValueError):
            skipped_invalid_entitlements += 1
            continue
        if not isinstance(value, dict):
            skipped_invalid_entitlements += 1
            continue
        if protect_existing and _target_exists(store, "entitlement_exists", chat_id):
            skipped_existing_entitlements += 1
            continue

        entitlement = Entitlement.from_dict(value)
        if not dry_run:
            _require_store(store).save_entitlement(chat_id, entitlement)
        for stored_charge_id in entitlement.processed_payment_charge_ids:
            migrated_charges += _import_processed_charge_id(
                store,
                chat_id,
                stored_charge_id,
                dry_run=dry_run,
                protect_existing=protect_existing,
            )
        migrated += 1
    return {
        "entitlements": migrated,
        "processed_payment_charges": migrated_charges,
        "skipped_existing_entitlements": skipped_existing_entitlements,
        "skipped_invalid_entitlements": skipped_invalid_entitlements,
    }


def migrate_payment_orders(
    store: PostgresDietBotStore | None,
    path: Path,
    *,
    dry_run: bool = False,
    protect_existing: bool = True,
) -> dict[str, int]:
    raw = _load_json_file(path, default={"orders": {}})
    if not isinstance(raw, dict):
        raise RuntimeError(f"{path} must contain a payment order object.")

    raw_orders = raw.get("orders", {})
    if not isinstance(raw_orders, dict):
        raise RuntimeError(f"{path} orders must contain a JSON object.")

    migrated = 0
    skipped = 0
    skipped_existing = 0
    for value in raw_orders.values():
        if not isinstance(value, dict):
            skipped += 1
            continue
        order = PaymentOrder.from_dict(value)
        if order is None:
            skipped += 1
            continue
        if protect_existing and _target_exists(store, "payment_order_exists", order.order_id):
            skipped_existing += 1
            continue
        if not dry_run:
            _require_store(store).create_payment_order(order)
        migrated += 1
    return {"orders": migrated, "skipped_orders": skipped, "skipped_existing_orders": skipped_existing}


def migrate_processed_payment_charges(
    store: PostgresDietBotStore | None,
    path: Path,
    *,
    dry_run: bool = False,
    protect_existing: bool = True,
) -> dict[str, int]:
    raw = _load_json_file(path, default={})
    data = raw.get("processed_charges", raw) if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a processed payment charge object.")

    migrated = 0
    skipped = 0
    skipped_existing = 0
    for value in data.values():
        if not isinstance(value, dict):
            skipped += 1
            continue
        provider = str(value.get("provider", "")).strip()
        charge_id = str(value.get("charge_id", "")).strip()
        user_id = _optional_int(value.get("user_id"))
        if not provider or not charge_id or user_id is None:
            skipped += 1
            continue
        if protect_existing and _processed_charge_exists(store, provider=provider, charge_id=charge_id):
            skipped_existing += 1
            continue
        if dry_run:
            migrated += 1
            continue
        inserted = _require_store(store).import_processed_payment_charge(
            user_id,
            provider=provider,
            charge_id=charge_id,
            raw_payload={
                "source": "json_processed_charge_registry_migration",
                "registry_entry": value,
            },
            status="processed",
        )
        if inserted:
            migrated += 1
        else:
            skipped_existing += 1
    return {
        "processed_payment_charges": migrated,
        "skipped_processed_payment_charges": skipped,
        "skipped_existing_processed_payment_charges": skipped_existing,
    }


def migrate_promo_codes(
    store: PostgresDietBotStore | None,
    path: Path,
    *,
    dry_run: bool = False,
    protect_existing: bool = True,
) -> dict[str, int]:
    raw = _load_json_file(path, default={})
    data = raw.get("codes", raw) if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a promo code object.")

    migrated = 0
    used = 0
    skipped_existing = 0
    skipped_invalid = 0
    for code, value in data.items():
        lookup_key = promo_code_lookup_key(str(code))
        if not lookup_key:
            skipped_invalid += 1
            continue
        if protect_existing and _target_exists(store, "promo_code_exists", lookup_key):
            skipped_existing += 1
            continue
        record = PromoCodeRecord.from_dict(value) if isinstance(value, dict) else PromoCodeRecord()
        if not dry_run:
            _require_store(store).import_promo_record(lookup_key, record)
        migrated += 1
        if record.used_by_chat_id is not None:
            used += 1
    return {
        "promo_codes": migrated,
        "redemptions": used,
        "skipped_existing_promo_codes": skipped_existing,
        "skipped_invalid_promo_codes": skipped_invalid,
    }


def _import_processed_charge_id(
    store: PostgresDietBotStore | None,
    user_id: int,
    stored_charge_id: str,
    *,
    dry_run: bool,
    protect_existing: bool,
) -> int:
    count = 0
    for provider, charge_id in _payment_charge_rows(stored_charge_id):
        if protect_existing and _processed_charge_exists(store, provider=provider, charge_id=charge_id):
            continue
        if dry_run:
            count += 1
            continue
        inserted = _require_store(store).import_processed_payment_charge(
            user_id,
            provider=provider,
            charge_id=charge_id,
            raw_payload={
                "source": "json_migration",
                "stored_charge_id": stored_charge_id,
            },
            status="processed",
        )
        if inserted:
            count += 1
    return count


def _payment_charge_rows(stored_charge_id: str) -> list[tuple[str, str]]:
    text = str(stored_charge_id).strip()
    if not text:
        return []
    if ":" in text:
        provider, charge_id = (part.strip() for part in text.split(":", 1))
        if provider and charge_id:
            return [(provider, charge_id)]
    return [(provider, text) for provider in LEGACY_CHARGE_PROVIDERS]


def _migration_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "history": args.history,
        "subscriptions": args.subscriptions,
        "promo_codes": args.promo_codes,
        "payment_orders": args.payment_orders,
        "processed_payment_charges": args.processed_payment_charges,
    }


def _source_summary(paths: dict[str, Path]) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for name, path in paths.items():
        if not path.exists():
            summary[name] = {"path": str(path), "exists": False, "bytes": 0}
            continue
        stat = path.stat()
        summary[name] = {
            "path": str(path),
            "exists": True,
            "bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        }
    return summary


def _source_fingerprint(paths: dict[str, Path]) -> str:
    digest = hashlib.sha256()
    for name in sorted(paths):
        path = paths[name]
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        if not path.exists():
            digest.update(b"missing")
            digest.update(b"\0")
            continue
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _audit_payload(
    *,
    mode: str,
    migration_id: str,
    source_fingerprint: str,
    source_summary: dict[str, Any],
    report: dict[str, Any],
    import_run_id: int | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": mode,
        "migration_id": migration_id,
        "source_fingerprint": source_fingerprint,
        "source_summary": source_summary,
        "report": report,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    if import_run_id is not None:
        payload["import_run_id"] = import_run_id
    if error is not None:
        payload["error"] = error
    return payload


def _store_for_run(database_url: str | None, *, apply: bool) -> PostgresDietBotStore | None:
    if not apply:
        return None
    if not database_url:
        raise SystemExit("Set DIET_BOT_DATABASE_URL or pass --database-url when using --apply.")
    return PostgresDietBotStore(database_url)


def _target_exists(store: object | None, method_name: str, *args: object) -> bool:
    if store is None:
        return False
    method = getattr(store, method_name, None)
    if method is None:
        return False
    return bool(method(*args))


def _processed_charge_exists(store: object | None, *, provider: str, charge_id: str) -> bool:
    if store is None:
        return False
    method = getattr(store, "processed_payment_charge_exists", None)
    if method is None:
        return False
    return bool(method(provider=provider, charge_id=charge_id))


def _require_store(store: PostgresDietBotStore | None) -> PostgresDietBotStore:
    if store is None:
        raise RuntimeError("A PostgreSQL store is required when --apply is used.")
    return store


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_json_file(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc


if __name__ == "__main__":
    main()
