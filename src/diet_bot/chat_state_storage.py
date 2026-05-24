from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from threading import RLock


ChatState = dict[str, object]
ChatStateByChatId = dict[str, ChatState]


class ChatStateStorageError(RuntimeError):
    """Base error for JSON chat state persistence failures."""


class ChatStateCorrupt(ChatStateStorageError):
    """Raised when an existing JSON chat state file is not valid state."""


_LOCKS_BY_PATH: dict[Path, RLock] = {}
_LOCKS_GUARD = RLock()


def _lock_for_path(path: Path) -> RLock:
    key = path.resolve(strict=False)
    with _LOCKS_GUARD:
        lock = _LOCKS_BY_PATH.get(key)
        if lock is None:
            lock = RLock()
            _LOCKS_BY_PATH[key] = lock
        return lock


class JsonChatStateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = _lock_for_path(self.path)

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.name + ".bak")

    def load_all(self) -> ChatStateByChatId:
        with self._lock:
            return self._load_all_locked()

    def save_all(self, state: Mapping[str, Mapping[str, object]]) -> None:
        with self._lock:
            self._load_all_locked()
            self._replace_with_state(state)

    def save_chat_state(self, chat_id: int, chat_state: Mapping[str, object]) -> None:
        with self._lock:
            state = self._load_all_locked()
            current = dict(state.get(str(chat_id), {}))
            if "recipe_ids" in chat_state:
                current["recipe_ids"] = chat_state["recipe_ids"]
            if "recipe_keys" in chat_state:
                current["recipe_keys"] = chat_state["recipe_keys"]
            if "profile" in chat_state:
                current["profile"] = chat_state["profile"]
            state[str(chat_id)] = _normalize_chat_state(current, source=self.path)
            self._replace_with_state(state)

    def _load_all_locked(self) -> ChatStateByChatId:
        try:
            return self._load_path(self.path, missing_ok=True)
        except ChatStateCorrupt as primary_error:
            return self._recover_from_backup(primary_error)

    def _recover_from_backup(self, primary_error: ChatStateCorrupt) -> ChatStateByChatId:
        try:
            state = self._load_path(self.backup_path, missing_ok=False)
        except ChatStateStorageError as backup_error:
            raise primary_error from backup_error
        self._replace_primary_with_state(state)
        return state

    def _load_path(self, path: Path, *, missing_ok: bool) -> ChatStateByChatId:
        if not path.exists():
            if missing_ok:
                return {}
            raise ChatStateStorageError(f"Chat state backup does not exist: {path}")
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ChatStateStorageError(f"Could not read chat state: {path}") from exc
        return _parse_chat_state(raw, source=path)

    def _replace_with_state(self, state: Mapping[str, Mapping[str, object]]) -> None:
        payload = _serialize_chat_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        backup_temp_path = self._write_temp_file(payload)
        primary_temp_path = self._write_temp_file(payload)
        try:
            os.replace(backup_temp_path, self.backup_path)
            os.replace(primary_temp_path, self.path)
            _fsync_parent_dir(self.path)
        except OSError as exc:
            with suppress(OSError):
                backup_temp_path.unlink()
            with suppress(OSError):
                primary_temp_path.unlink()
            raise ChatStateStorageError(f"Could not save chat state: {self.path}") from exc

    def _replace_primary_with_state(self, state: Mapping[str, Mapping[str, object]]) -> None:
        payload = _serialize_chat_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._write_temp_file(payload)
        try:
            os.replace(temp_path, self.path)
            _fsync_parent_dir(self.path)
        except OSError as exc:
            with suppress(OSError):
                temp_path.unlink()
            raise ChatStateStorageError(f"Could not restore chat state from backup: {self.path}") from exc

    def _write_temp_file(self, payload: str) -> Path:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            with suppress(OSError):
                temp_path.unlink()
            raise ChatStateStorageError(f"Could not write chat state temp file: {temp_path}") from exc
        return temp_path


def _parse_chat_state(raw: str, *, source: Path) -> ChatStateByChatId:
    if not raw.strip():
        raise ChatStateCorrupt(f"Chat state is empty: {source}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChatStateCorrupt(f"Chat state contains invalid JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise ChatStateCorrupt(f"Chat state must be a JSON object: {source}")
    return _normalize_state(payload, source=source)


def _serialize_chat_state(state: Mapping[str, Mapping[str, object]]) -> str:
    try:
        normalized = _normalize_state(state, source=Path("<memory>"))
        return json.dumps(normalized, ensure_ascii=False, indent=2)
    except TypeError as exc:
        raise ChatStateStorageError("Chat state contains a value that is not JSON serializable") from exc


def _normalize_state(state: Mapping[str, object], *, source: Path) -> ChatStateByChatId:
    if not isinstance(state, Mapping):
        raise ChatStateStorageError(f"Chat state must be a mapping: {source}")
    normalized: ChatStateByChatId = {}
    for chat_id, raw_chat_state in state.items():
        if not isinstance(raw_chat_state, Mapping):
            raise ChatStateCorrupt(f"Chat state contains a non-object chat entry: {source}")
        normalized[str(chat_id)] = _normalize_chat_state(raw_chat_state, source=source)
    return normalized


def _normalize_chat_state(raw: Mapping[str, object], *, source: Path) -> ChatState:
    if not isinstance(raw, Mapping):
        raise ChatStateStorageError(f"Chat state entry must be a mapping: {source}")
    chat_state: ChatState = {
        "recipe_ids": _string_list(raw.get("recipe_ids", [])),
        "recipe_keys": _string_list(raw.get("recipe_keys", [])),
    }
    profile = raw.get("profile")
    if isinstance(profile, Mapping):
        chat_state["profile"] = dict(profile)
    return chat_state


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _fsync_parent_dir(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
