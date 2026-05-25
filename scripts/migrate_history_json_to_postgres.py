from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from diet_bot.chat_state_storage import ChatState, ChatStateByChatId, _normalize_chat_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / ".diet_bot_state" / "history.json"
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1
PostgresChatStateStore: Any | None = None


class MigrationError(RuntimeError):
    """Raised when a history JSON import cannot be applied safely."""


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate history JSON chat state into PostgreSQL.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--migration-id", required=True)
    parser.add_argument("--database-url")
    parser.add_argument(
        "--allow-non-empty-target",
        action="store_true",
        help="allow replacing chat state tables that already contain rows",
    )
    parser.add_argument("--expected-source-fingerprint")
    parser.add_argument("--expected-chat-count", type=_non_negative_int)
    parser.add_argument("--expected-profile-count", type=_non_negative_int)
    parser.add_argument("--expected-recipe-history-chat-count", type=_non_negative_int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the import into PostgreSQL")
    mode.add_argument("--dry-run", action="store_true", help="preview the import without a DB connection")
    args = parser.parse_args(argv)

    source_env = dict(os.environ if env is None else env)
    source = args.source
    _require_existing_source(source)
    source_metadata = _source_metadata(source)
    source_fingerprint = _source_fingerprint(source)
    chat_state, invalid_skipped_records = _load_source(source)
    report = _report(chat_state, invalid_skipped_records=invalid_skipped_records)
    _validate_expected_source(
        source_fingerprint=source_fingerprint,
        report=report,
        expected_source_fingerprint=args.expected_source_fingerprint,
        expected_chat_count=args.expected_chat_count,
        expected_profile_count=args.expected_profile_count,
        expected_recipe_history_chat_count=args.expected_recipe_history_chat_count,
    )

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

    store = _postgres_chat_state_store_cls()(database_url)
    store.initialize()
    try:
        result_payload = store.apply_json_import(
            migration_id=args.migration_id,
            source_fingerprint=source_fingerprint,
            source_metadata=source_metadata,
            chat_state=chat_state,
            result_payload=payload,
            allow_non_empty_target=args.allow_non_empty_target,
        )
    except Exception as exc:
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(str(exc)) from exc
    print(json.dumps(result_payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _load_source(path: Path) -> tuple[ChatStateByChatId, int]:
    raw = _read_source_text(path)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"source JSON contains invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"source JSON must be an object: {path}")

    normalized: ChatStateByChatId = {}
    invalid_skipped_records = 0
    for raw_chat_id, raw_chat_state in payload.items():
        chat_id = _normalize_chat_id(raw_chat_id)
        if chat_id is None or not isinstance(raw_chat_state, Mapping):
            invalid_skipped_records += 1
            continue
        normalized[chat_id] = _normalize_chat_state(raw_chat_state, source=path)
    return normalized, invalid_skipped_records


def _report(chat_state: Mapping[str, ChatState], *, invalid_skipped_records: int) -> dict[str, int]:
    chats_with_recipe_ids = sum(1 for chat in chat_state.values() if chat.get("recipe_ids"))
    chats_with_recipe_keys = sum(1 for chat in chat_state.values() if chat.get("recipe_keys"))
    return {
        "total_chats": len(chat_state),
        "profiles": sum(1 for chat in chat_state.values() if "profile" in chat),
        "chats_with_recipe_ids": chats_with_recipe_ids,
        "chats_with_recipe_keys": chats_with_recipe_keys,
        "recipe_history_chats": sum(
            1
            for chat in chat_state.values()
            if chat.get("recipe_ids") or chat.get("recipe_keys")
        ),
        "invalid_skipped_records": invalid_skipped_records,
    }


def _validate_expected_source(
    *,
    source_fingerprint: str,
    report: dict[str, int],
    expected_source_fingerprint: str | None,
    expected_chat_count: int | None,
    expected_profile_count: int | None,
    expected_recipe_history_chat_count: int | None,
) -> None:
    if expected_source_fingerprint is not None:
        expected = expected_source_fingerprint.strip().lower()
        if expected != source_fingerprint:
            raise SystemExit(
                "source fingerprint mismatch: "
                f"expected {expected_source_fingerprint}, got {source_fingerprint}",
            )
    _validate_expected_count(
        label="chat count",
        report_key="total_chats",
        report=report,
        expected=expected_chat_count,
    )
    _validate_expected_count(
        label="profile count",
        report_key="profiles",
        report=report,
        expected=expected_profile_count,
    )
    _validate_expected_count(
        label="recipe history chat count",
        report_key="recipe_history_chats",
        report=report,
        expected=expected_recipe_history_chat_count,
    )


def _validate_expected_count(
    *,
    label: str,
    report_key: str,
    report: dict[str, int],
    expected: int | None,
) -> None:
    if expected is not None and report[report_key] != expected:
        raise SystemExit(f"{label} mismatch: expected {expected}, got {report[report_key]}")


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
    digest.update(b"chat-state-json-v1\0")
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_source_text(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"could not read source JSON: {path}") from exc
    if not raw.strip():
        raise SystemExit(f"source JSON is empty: {path}")
    return raw


def _normalize_chat_id(value: object) -> str | None:
    try:
        chat_id = int(str(value))
    except (TypeError, ValueError):
        return None
    if chat_id < _BIGINT_MIN or chat_id > _BIGINT_MAX:
        return None
    return str(chat_id)


def _postgres_chat_state_store_cls() -> Any:
    global PostgresChatStateStore
    if PostgresChatStateStore is None:
        from diet_bot.postgres_chat_state_store import PostgresChatStateStore as store_cls

        PostgresChatStateStore = store_cls
    return PostgresChatStateStore


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {value!r}")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
