from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from diet_bot.entitlement_storage import JsonEntitlementStore
from diet_bot.postgres_entitlement_store import PostgresEntitlementStore
from diet_bot.subscriptions import Entitlement


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / ".diet_bot_state" / "subscriptions.json"


class MigrationError(RuntimeError):
    """Raised when an entitlement JSON import cannot be applied safely."""


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate entitlement JSON state into PostgreSQL.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--migration-id", required=True)
    parser.add_argument("--database-url")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the import into PostgreSQL")
    mode.add_argument("--dry-run", action="store_true", help="preview the import without a DB connection")
    args = parser.parse_args(argv)

    source_env = dict(os.environ if env is None else env)
    source = args.source
    _require_existing_source(source)
    source_metadata = _source_metadata(source)
    source_fingerprint = _source_fingerprint(source)
    entitlements = JsonEntitlementStore(source).load_all()
    report = _report(entitlements)
    mode_name = "apply" if args.apply else "dry_run"
    payload = _payload(
        mode=mode_name,
        migration_id=args.migration_id,
        source_fingerprint=source_fingerprint,
        source_metadata=source_metadata,
        report=report,
    )

    if not args.apply:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    database_url = args.database_url or source_env.get("DIET_BOT_DATABASE_URL")
    if not database_url:
        raise SystemExit("Pass --database-url or set DIET_BOT_DATABASE_URL when using --apply.")

    store = PostgresEntitlementStore(database_url)
    store.initialize()
    try:
        result_payload = store.apply_json_import(
            migration_id=args.migration_id,
            source_fingerprint=source_fingerprint,
            source_metadata=source_metadata,
            entitlements=entitlements,
            result_payload=payload,
        )
    except Exception as exc:
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(str(exc)) from exc
    print(json.dumps(result_payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _report(entitlements: dict[int, Entitlement]) -> dict[str, int]:
    return {
        "entitlements": len(entitlements),
        "processed_charge_ids": sum(
            len(entitlement.processed_payment_charge_ids)
            for entitlement in entitlements.values()
        ),
    }


def _payload(
    *,
    mode: str,
    migration_id: str,
    source_fingerprint: str,
    source_metadata: dict[str, Any],
    report: dict[str, int],
) -> dict[str, Any]:
    return {
        "mode": mode,
        "migration_id": migration_id,
        "source_fingerprint": source_fingerprint,
        "source": source_metadata,
        "report": report,
        "finished_at": datetime.now(UTC).isoformat(),
    }


def _source_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "bytes": 0,
        }
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def _require_existing_source(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"source JSON does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"source JSON is not a file: {path}")


def _source_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"entitlements-json-v1\0")
    if not path.exists():
        digest.update(b"missing")
    else:
        digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
