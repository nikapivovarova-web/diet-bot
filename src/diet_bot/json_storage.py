from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

if os.name == "nt":
    import msvcrt
else:
    import fcntl


_LOCK_BYTE_COUNT = 1
_LOCK_POLL_INTERVAL_SECONDS = 0.01
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_THREAD_STATE = threading.local()


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
