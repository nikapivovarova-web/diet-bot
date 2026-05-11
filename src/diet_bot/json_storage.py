from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

if os.name == "nt":
    import msvcrt
else:
    import fcntl


_PROCESS_LOCK = threading.RLock()
_THREAD_STATE = threading.local()


@contextmanager
def json_storage_transaction(*paths: Path) -> Iterator[None]:
    lock_path = _lock_path_for(paths)
    with _PROCESS_LOCK:
        depth = getattr(_THREAD_STATE, "depth", 0)
        if depth:
            _THREAD_STATE.depth = depth + 1
            try:
                yield
            finally:
                _THREAD_STATE.depth -= 1
            return

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            _lock_file(lock_file)
            _THREAD_STATE.depth = 1
            try:
                yield
            finally:
                _THREAD_STATE.depth = 0
                _unlock_file(lock_file)


def _lock_path_for(paths: tuple[Path, ...]) -> Path:
    parents = [Path(path).expanduser().parent for path in paths if path]
    if not parents:
        return Path(".diet_bot_state") / ".json_storage.lock"
    try:
        common_parent = Path(os.path.commonpath([str(parent.resolve(strict=False)) for parent in parents]))
    except (OSError, ValueError):
        common_parent = parents[0]
    return common_parent / ".json_storage.lock"


def _lock_file(lock_file: BinaryIO) -> None:
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
    lock_file.seek(0)
    if os.name == "nt":
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)


def _unlock_file(lock_file: BinaryIO) -> None:
    lock_file.seek(0)
    if os.name == "nt":
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
