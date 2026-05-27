from __future__ import annotations

import asyncio
import threading

import pytest

from diet_bot.db_executor import (
    DEFAULT_DB_EXECUTOR_MAX_QUEUE_SIZE,
    DEFAULT_DB_EXECUTOR_MAX_WORKERS,
    BoundedDbExecutor,
    DbExecutorBusy,
    DbExecutorSettings,
    settings_from_env,
)


def test_db_executor_settings_parse_defaults_and_valid_overrides() -> None:
    defaults = settings_from_env({})
    assert defaults.max_workers == DEFAULT_DB_EXECUTOR_MAX_WORKERS
    assert defaults.max_queue_size == DEFAULT_DB_EXECUTOR_MAX_QUEUE_SIZE

    overridden = settings_from_env(
        {
            "DIET_BOT_DB_EXECUTOR_MAX_WORKERS": "2",
            "DIET_BOT_DB_EXECUTOR_MAX_QUEUE_SIZE": "3",
            "DIET_BOT_DB_EXECUTOR_QUEUE_TIMEOUT_SECONDS": "0.25",
        },
    )

    assert overridden == DbExecutorSettings(
        max_workers=2,
        max_queue_size=3,
        queue_timeout_seconds=0.25,
    )


def test_db_executor_runs_sync_callable_off_event_loop_thread() -> None:
    async def scenario() -> None:
        loop_thread = threading.get_ident()
        executor = BoundedDbExecutor(DbExecutorSettings(max_workers=1, max_queue_size=1))
        try:
            worker_thread = await executor.run(threading.get_ident)
        finally:
            executor.shutdown(wait=True)

        assert worker_thread != loop_thread

    asyncio.run(scenario())


def test_db_executor_propagates_sync_callable_exceptions() -> None:
    async def scenario() -> None:
        executor = BoundedDbExecutor(DbExecutorSettings(max_workers=1, max_queue_size=1))
        try:
            with pytest.raises(ValueError, match="boom"):
                await executor.run(_raise_value_error)
        finally:
            executor.shutdown(wait=True)

    asyncio.run(scenario())


def test_db_executor_rejects_when_workers_and_queue_are_full() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        executor = BoundedDbExecutor(
            DbExecutorSettings(max_workers=1, max_queue_size=0, queue_timeout_seconds=0.01),
        )
        try:
            first = asyncio.create_task(executor.run(_wait_for_release, started, release))
            assert await asyncio.to_thread(started.wait, 1)

            with pytest.raises(DbExecutorBusy):
                await executor.run(lambda: "second")

            release.set()
            assert await first == "released"
        finally:
            release.set()
            executor.shutdown(wait=True)

    asyncio.run(scenario())


def test_cancelled_await_keeps_capacity_reserved_until_thread_finishes() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        executor = BoundedDbExecutor(
            DbExecutorSettings(max_workers=1, max_queue_size=0, queue_timeout_seconds=0.01),
        )
        try:
            first = asyncio.create_task(executor.run(_wait_for_release, started, release))
            assert await asyncio.to_thread(started.wait, 1)

            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first

            with pytest.raises(DbExecutorBusy):
                await executor.run(lambda: "too-early")

            release.set()
            await asyncio.sleep(0.05)
            assert await executor.run(lambda: "after-release") == "after-release"
        finally:
            release.set()
            executor.shutdown(wait=True)

    asyncio.run(scenario())


def _raise_value_error() -> None:
    raise ValueError("boom")


def _wait_for_release(started: threading.Event, release: threading.Event) -> str:
    started.set()
    release.wait(timeout=2)
    return "released"
