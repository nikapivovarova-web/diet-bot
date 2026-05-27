from __future__ import annotations

import asyncio
import atexit
import os
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from threading import RLock
from typing import ParamSpec, TypeVar


DEFAULT_DB_EXECUTOR_MAX_WORKERS = 4
DEFAULT_DB_EXECUTOR_MAX_QUEUE_SIZE = 16
DEFAULT_DB_EXECUTOR_QUEUE_TIMEOUT_SECONDS = 2.0

DB_EXECUTOR_MAX_WORKERS_ENV = "DIET_BOT_DB_EXECUTOR_MAX_WORKERS"
DB_EXECUTOR_MAX_QUEUE_SIZE_ENV = "DIET_BOT_DB_EXECUTOR_MAX_QUEUE_SIZE"
DB_EXECUTOR_QUEUE_TIMEOUT_SECONDS_ENV = "DIET_BOT_DB_EXECUTOR_QUEUE_TIMEOUT_SECONDS"

P = ParamSpec("P")
T = TypeVar("T")


class DbExecutorBusy(RuntimeError):
    """Raised when the bounded DB executor cannot accept more work quickly."""


@dataclass(frozen=True)
class DbExecutorSettings:
    max_workers: int = DEFAULT_DB_EXECUTOR_MAX_WORKERS
    max_queue_size: int = DEFAULT_DB_EXECUTOR_MAX_QUEUE_SIZE
    queue_timeout_seconds: float = DEFAULT_DB_EXECUTOR_QUEUE_TIMEOUT_SECONDS

    @property
    def max_in_flight(self) -> int:
        return self.max_workers + self.max_queue_size


class BoundedDbExecutor:
    """Bound synchronous DB calls before they enter a dedicated thread pool.

    The semaphore caps running plus queued work. If no slot is available within
    ``queue_timeout_seconds``, callers fail fast with ``DbExecutorBusy`` instead
    of creating unbounded executor work.
    """

    def __init__(self, settings: DbExecutorSettings | None = None) -> None:
        self.settings = _normalize_settings(settings or DbExecutorSettings())
        self._executor = ThreadPoolExecutor(
            max_workers=self.settings.max_workers,
            thread_name_prefix="diet-bot-db",
        )
        self._slots = asyncio.BoundedSemaphore(self.settings.max_in_flight)
        self._shutdown = False

    async def run(self, func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
        if self._shutdown:
            raise RuntimeError("DB executor is shut down.")

        try:
            await asyncio.wait_for(
                self._slots.acquire(),
                timeout=self.settings.queue_timeout_seconds,
            )
        except TimeoutError as exc:
            raise DbExecutorBusy("DB executor queue is full.") from exc

        released = False

        def release_slot_once(_future: object | None = None) -> None:
            nonlocal released
            if released:
                return
            released = True
            self._slots.release()

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor, partial(func, *args, **kwargs))
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            future.add_done_callback(release_slot_once)
            raise
        finally:
            if future.done():
                release_slot_once()

    def shutdown(self, *, wait: bool = True) -> None:
        self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=True)


_DEFAULT_EXECUTOR: BoundedDbExecutor | None = None
_DEFAULT_EXECUTOR_LOCK = RLock()


def settings_from_env(env: Mapping[str, str] | None = None) -> DbExecutorSettings:
    source = os.environ if env is None else env
    return DbExecutorSettings(
        max_workers=_int_from_env(
            source,
            DB_EXECUTOR_MAX_WORKERS_ENV,
            DEFAULT_DB_EXECUTOR_MAX_WORKERS,
            minimum=1,
        ),
        max_queue_size=_int_from_env(
            source,
            DB_EXECUTOR_MAX_QUEUE_SIZE_ENV,
            DEFAULT_DB_EXECUTOR_MAX_QUEUE_SIZE,
            minimum=0,
        ),
        queue_timeout_seconds=_float_from_env(
            source,
            DB_EXECUTOR_QUEUE_TIMEOUT_SECONDS_ENV,
            DEFAULT_DB_EXECUTOR_QUEUE_TIMEOUT_SECONDS,
            minimum=0.001,
        ),
    )


def get_db_executor() -> BoundedDbExecutor:
    global _DEFAULT_EXECUTOR
    with _DEFAULT_EXECUTOR_LOCK:
        if _DEFAULT_EXECUTOR is None:
            _DEFAULT_EXECUTOR = BoundedDbExecutor(settings_from_env())
        return _DEFAULT_EXECUTOR


async def run_db_call(func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    return await get_db_executor().run(func, *args, **kwargs)


def reset_db_executor_for_tests() -> None:
    global _DEFAULT_EXECUTOR
    with _DEFAULT_EXECUTOR_LOCK:
        executor = _DEFAULT_EXECUTOR
        _DEFAULT_EXECUTOR = None
    if executor is not None:
        executor.shutdown(wait=True)


def _normalize_settings(settings: DbExecutorSettings) -> DbExecutorSettings:
    return DbExecutorSettings(
        max_workers=max(1, int(settings.max_workers)),
        max_queue_size=max(0, int(settings.max_queue_size)),
        queue_timeout_seconds=max(0.001, float(settings.queue_timeout_seconds)),
    )


def _int_from_env(
    env: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int,
) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    return value


def _float_from_env(
    env: Mapping[str, str],
    key: str,
    default: float,
    *,
    minimum: float,
) -> float:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    return value


atexit.register(reset_db_executor_for_tests)
