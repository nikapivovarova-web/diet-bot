from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from .storage import RecipeHistoryItem

if os.name == "nt":
    import msvcrt
else:
    import fcntl


_LOCK_BYTE_COUNT = 1
_LOCK_POLL_INTERVAL_SECONDS = 0.01
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_THREAD_STATE = threading.local()
RECIPE_HISTORY_JSON_LIMIT = 400
RECIPE_HISTORY_COMPAT_LIMIT = 160


class JsonStorageLockError(TimeoutError):
    """Raised when a JSON storage lock cannot be acquired in time."""


@dataclass
class _HeldLock:
    lock_path: Path
    lock_file: BinaryIO
    process_lock: threading.RLock
    depth: int = 1


@contextmanager
def json_storage_transaction(*paths: Path, timeout_seconds: float = 2.0) -> Iterator[None]:
    """Hold bounded, path-based JSON storage locks for local development state files."""
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative.")

    lock_paths = _lock_paths_for(paths)
    deadline = time.monotonic() + timeout_seconds
    acquired_keys: list[str] = []

    try:
        for lock_path in lock_paths:
            key = _lock_key(lock_path)
            _acquire_lock(lock_path, key, deadline, timeout_seconds)
            acquired_keys.append(key)
        yield
    finally:
        for key in reversed(acquired_keys):
            _release_lock(key)


def atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON atomically via a same-directory temporary file and replace."""
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=target_path.parent,
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as temp_file:
            json.dump(payload, temp_file, ensure_ascii=False, sort_keys=True)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, target_path)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def record_recipe_history_in_json(
    path: Path,
    user_id: int,
    entries: Sequence[RecipeHistoryItem],
    *,
    limit: int = RECIPE_HISTORY_JSON_LIMIT,
    compat_limit: int = RECIPE_HISTORY_COMPAT_LIMIT,
) -> None:
    if not entries:
        return

    current_time = datetime.now(UTC)
    incoming_payloads = [
        _recipe_history_item_to_json(entry, current_time=current_time)
        for entry in entries
    ]
    with json_storage_transaction(path):
        state = _load_json_state(path)
        chat_key = str(user_id)
        chat_state = _coerce_chat_state(state.get(chat_key))
        existing_payloads = _coerce_recipe_history_payloads(chat_state.get("recipe_history"))
        existing_keys = {
            key
            for payload in existing_payloads
            if (key := _recipe_history_idempotency_key(payload)) is not None
        }

        appended_payloads: list[dict[str, object]] = []
        for payload in incoming_payloads:
            key = _recipe_history_idempotency_key(payload)
            if key is not None and key in existing_keys:
                continue
            existing_payloads.append(payload)
            appended_payloads.append(payload)
            if key is not None:
                existing_keys.add(key)

        chat_state["recipe_history"] = _prune_recipe_history_payloads(
            existing_payloads,
            limit=limit,
        )
        if appended_payloads:
            chat_state["recipe_ids"] = _append_compat_values(
                chat_state.get("recipe_ids"),
                [str(payload["recipe_id"]) for payload in appended_payloads],
                limit=compat_limit,
            )
            chat_state["recipe_keys"] = _append_compat_values(
                chat_state.get("recipe_keys"),
                [str(payload["recipe_key"]) for payload in appended_payloads],
                limit=compat_limit,
            )
        state[chat_key] = chat_state
        atomic_write_json(path, state)


def load_recent_recipe_history_from_json(
    path: Path,
    user_id: int,
    *,
    since: datetime | None = None,
    limit: int = RECIPE_HISTORY_JSON_LIMIT,
) -> list[RecipeHistoryItem]:
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return []

    state = _load_json_state(path)
    chat_state = _coerce_chat_state(state.get(str(user_id)))
    since_at = _normalize_json_datetime(since) if since is not None else None
    items = [
        item
        for payload in _coerce_recipe_history_payloads(chat_state.get("recipe_history"))
        if (item := _recipe_history_item_from_json(payload, user_id=user_id)) is not None
    ]
    if since_at is not None:
        items = [
            item
            for item in items
            if item.generated_at is not None and item.generated_at >= since_at
        ]
    items.sort(
        key=lambda item: item.generated_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return items[:bounded_limit]


def _lock_paths_for(paths: tuple[Path, ...]) -> list[Path]:
    if not paths:
        raise ValueError("json_storage_transaction requires at least one path.")

    paths_by_key: dict[str, Path] = {}
    for path in paths:
        lock_path = _target_lock_path(Path(path))
        paths_by_key.setdefault(_lock_key(lock_path), lock_path)
    return [paths_by_key[key] for key in sorted(paths_by_key)]


def _target_lock_path(path: Path) -> Path:
    expanded_path = path.expanduser()
    return expanded_path.with_name(f"{expanded_path.name}.lock")


def _lock_key(lock_path: Path) -> str:
    return os.path.normcase(str(lock_path.resolve(strict=False)))


def _held_locks() -> dict[str, _HeldLock]:
    held_locks = getattr(_THREAD_STATE, "held_locks", None)
    if held_locks is None:
        held_locks = {}
        _THREAD_STATE.held_locks = held_locks
    return held_locks


def _process_lock_for(key: str) -> threading.RLock:
    with _PROCESS_LOCKS_GUARD:
        process_lock = _PROCESS_LOCKS.get(key)
        if process_lock is None:
            process_lock = threading.RLock()
            _PROCESS_LOCKS[key] = process_lock
        return process_lock


def _acquire_lock(
    lock_path: Path,
    key: str,
    deadline: float,
    timeout_seconds: float,
) -> None:
    held_locks = _held_locks()
    held_lock = held_locks.get(key)
    if held_lock is not None:
        held_lock.depth += 1
        return

    process_lock = _process_lock_for(key)
    remaining_seconds = max(0.0, deadline - time.monotonic())
    if not process_lock.acquire(timeout=remaining_seconds):
        raise _timeout_error(lock_path, timeout_seconds)

    lock_file: BinaryIO | None = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+b")
        _ensure_lock_byte(lock_file)
        _acquire_file_lock(lock_file, lock_path, deadline, timeout_seconds)
        held_locks[key] = _HeldLock(
            lock_path=lock_path,
            lock_file=lock_file,
            process_lock=process_lock,
        )
    except Exception:
        if lock_file is not None:
            lock_file.close()
        process_lock.release()
        raise


def _release_lock(key: str) -> None:
    held_locks = _held_locks()
    held_lock = held_locks[key]
    held_lock.depth -= 1
    if held_lock.depth > 0:
        return

    try:
        _unlock_file(held_lock.lock_file)
    finally:
        try:
            held_lock.lock_file.close()
        finally:
            del held_locks[key]
            held_lock.process_lock.release()


def _ensure_lock_byte(lock_file: BinaryIO) -> None:
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() > 0:
        lock_file.seek(0)
        return

    lock_file.write(b"\0")
    lock_file.flush()
    os.fsync(lock_file.fileno())
    lock_file.seek(0)


def _acquire_file_lock(
    lock_file: BinaryIO,
    lock_path: Path,
    deadline: float,
    timeout_seconds: float,
) -> None:
    while True:
        try:
            lock_file.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, _LOCK_BYTE_COUNT)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            now = time.monotonic()
            if now >= deadline:
                raise _timeout_error(lock_path, timeout_seconds) from exc
            time.sleep(min(_LOCK_POLL_INTERVAL_SECONDS, deadline - now))


def _unlock_file(lock_file: BinaryIO) -> None:
    lock_file.seek(0)
    if os.name == "nt":
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, _LOCK_BYTE_COUNT)
    else:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _timeout_error(lock_path: Path, timeout_seconds: float) -> JsonStorageLockError:
    return JsonStorageLockError(
        f"Timed out after {timeout_seconds:g} seconds waiting for JSON storage lock {lock_path}."
    )


def _load_json_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _coerce_chat_state(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_recipe_history_payloads(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _recipe_history_item_to_json(
    item: RecipeHistoryItem,
    *,
    current_time: datetime,
) -> dict[str, object]:
    generated_at = _normalize_json_datetime(item.generated_at or current_time)
    return {
        "recipe_id": str(item.recipe_id),
        "recipe_key": str(item.recipe_key),
        "meal_slot": str(item.meal_slot),
        "ration_kind": str(item.ration_kind),
        "generation_id": _optional_json_int(item.generation_id),
        "generated_at": generated_at.isoformat(),
        "day_index": _optional_json_int(item.day_index),
        "meal_index": max(0, int(item.meal_index)),
    }


def _recipe_history_item_from_json(
    payload: dict[str, object],
    *,
    user_id: int | None = None,
) -> RecipeHistoryItem | None:
    recipe_id = _non_empty_json_text(payload.get("recipe_id"))
    recipe_key = _non_empty_json_text(payload.get("recipe_key"))
    meal_slot = _non_empty_json_text(payload.get("meal_slot"))
    ration_kind = payload.get("ration_kind")
    generated_at = _parse_json_datetime(payload.get("generated_at"))
    if (
        recipe_id is None
        or recipe_key is None
        or meal_slot is None
        or ration_kind not in {"one_day", "weekly_pdf"}
        or generated_at is None
    ):
        return None
    return RecipeHistoryItem(
        recipe_id,
        recipe_key,
        meal_slot,
        ration_kind,  # type: ignore[arg-type]
        generation_id=_optional_json_int(payload.get("generation_id")),
        generated_at=generated_at,
        day_index=_optional_json_int(payload.get("day_index")),
        meal_index=max(0, _optional_json_int(payload.get("meal_index")) or 0),
        user_id=user_id,
    )


def _recipe_history_idempotency_key(payload: dict[str, object]) -> tuple[int, int, int, str] | None:
    generation_id = _optional_json_int(payload.get("generation_id"))
    recipe_id = _non_empty_json_text(payload.get("recipe_id"))
    if generation_id is None or recipe_id is None:
        return None
    day_index = _optional_json_int(payload.get("day_index"))
    meal_index = _optional_json_int(payload.get("meal_index")) or 0
    return generation_id, day_index if day_index is not None else -1, meal_index, recipe_id


def _prune_recipe_history_payloads(
    payloads: list[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return []
    payloads.sort(
        key=lambda payload: _parse_json_datetime(payload.get("generated_at"))
        or datetime.min.replace(tzinfo=UTC),
    )
    return payloads[-bounded_limit:]


def _append_compat_values(
    existing: object,
    values: list[str],
    *,
    limit: int,
) -> list[str]:
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return []
    history = [str(value) for value in existing] if isinstance(existing, list) else []
    history.extend(value for value in values if value)
    return history[-bounded_limit:]


def _normalize_json_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_json_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _normalize_json_datetime(value)
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        return _normalize_json_datetime(datetime.fromisoformat(text))
    except ValueError:
        return None


def _optional_json_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _non_empty_json_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
