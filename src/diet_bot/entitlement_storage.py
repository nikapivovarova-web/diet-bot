from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from threading import RLock
from typing import Protocol

from .subscriptions import Entitlement


class EntitlementStorageError(RuntimeError):
    """Base error for entitlement state persistence failures."""


class EntitlementStateCorrupt(EntitlementStorageError):
    """Raised when the entitlement JSON file exists but is not valid state."""


class EntitlementStore(Protocol):
    def load_all(self) -> dict[int, Entitlement]:
        ...

    def save_all(self, entitlements: Mapping[int, Entitlement]) -> None:
        ...

    def transact(self) -> Iterator[dict[int, Entitlement]]:
        ...


class JsonEntitlementStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = RLock()

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.name + ".bak")

    def load_all(self) -> dict[int, Entitlement]:
        with self._lock:
            return self._load_path(self.path, missing_ok=True)

    def save_all(self, entitlements: Mapping[int, Entitlement]) -> None:
        with self._lock:
            primary_exists = self.path.exists()
            if primary_exists:
                self._load_path(self.path, missing_ok=False)
            self._replace_with_state(entitlements, create_backup=primary_exists)

    @contextmanager
    def transact(self) -> Iterator[dict[int, Entitlement]]:
        with self._lock:
            entitlements = self.load_all()
            yield entitlements
            self.save_all(entitlements)

    def recover_from_backup(self) -> dict[int, Entitlement]:
        with self._lock:
            if not self.backup_path.exists():
                raise EntitlementStorageError(f"Entitlement backup does not exist: {self.backup_path}")
            entitlements = self._load_path(self.backup_path, missing_ok=False)
            self._replace_with_state(entitlements, create_backup=False)
            return entitlements

    def _load_path(self, path: Path, *, missing_ok: bool) -> dict[int, Entitlement]:
        if not path.exists():
            if missing_ok:
                return {}
            raise EntitlementStorageError(f"Entitlement state file does not exist: {path}")
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise EntitlementStorageError(f"Could not read entitlement state: {path}") from exc
        return _parse_entitlement_state(raw, source=path)

    def _replace_with_state(
        self,
        entitlements: Mapping[int, Entitlement],
        *,
        create_backup: bool,
    ) -> None:
        payload = _serialize_entitlements(entitlements)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._write_temp_file(payload)
        try:
            if create_backup:
                self._copy_primary_to_backup()
            os.replace(temp_path, self.path)
            _fsync_parent_dir(self.path)
        except EntitlementStorageError:
            with suppress(OSError):
                temp_path.unlink()
            raise
        except OSError as exc:
            with suppress(OSError):
                temp_path.unlink()
            raise EntitlementStorageError(f"Could not save entitlement state: {self.path}") from exc

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
            raise EntitlementStorageError(f"Could not write entitlement temp file: {temp_path}") from exc
        return temp_path

    def _copy_primary_to_backup(self) -> None:
        try:
            shutil.copy2(self.path, self.backup_path)
            with self.backup_path.open("r+b") as handle:
                os.fsync(handle.fileno())
        except OSError as exc:
            raise EntitlementStorageError(f"Could not create entitlement backup: {self.backup_path}") from exc


def _parse_entitlement_state(raw: str, *, source: Path) -> dict[int, Entitlement]:
    if not raw.strip():
        raise EntitlementStateCorrupt(f"Entitlement state is empty: {source}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EntitlementStateCorrupt(f"Entitlement state contains invalid JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise EntitlementStateCorrupt(f"Entitlement state must be a JSON object: {source}")

    entitlements: dict[int, Entitlement] = {}
    for raw_chat_id, raw_entitlement in payload.items():
        try:
            chat_id = int(raw_chat_id)
        except (TypeError, ValueError) as exc:
            raise EntitlementStateCorrupt(
                f"Entitlement state contains a non-integer chat id: {source}",
            ) from exc
        if not isinstance(raw_entitlement, dict):
            raise EntitlementStateCorrupt(
                f"Entitlement state contains a non-object entitlement for chat_id {chat_id}: {source}",
            )
        entitlements[chat_id] = Entitlement.from_dict(raw_entitlement)
    return entitlements


def _serialize_entitlements(entitlements: Mapping[int, Entitlement]) -> str:
    payload: dict[str, dict[str, object]] = {}
    for raw_chat_id, entitlement in sorted(entitlements.items()):
        try:
            chat_id = int(raw_chat_id)
        except (TypeError, ValueError) as exc:
            raise EntitlementStorageError(f"Invalid entitlement chat id: {raw_chat_id!r}") from exc
        if not isinstance(entitlement, Entitlement):
            raise EntitlementStorageError(f"Invalid entitlement value for chat_id {chat_id}")
        payload[str(chat_id)] = entitlement.to_dict()
    return json.dumps(payload, ensure_ascii=False, indent=2)


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
