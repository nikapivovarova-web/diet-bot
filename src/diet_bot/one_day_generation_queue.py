from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass
class OneDayGenerationQueueAdmission(Generic[T]):
    accepted: bool
    future: asyncio.Future[T] | None
    starts_immediately: bool = False
    ahead_count: int = 0


@dataclass
class _OneDayGenerationQueueJob(Generic[T]):
    runner: Callable[[], Awaitable[T]]
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[T]


class OneDayGenerationQueue:
    def __init__(self, *, max_concurrency: int, max_queued: int) -> None:
        self.max_concurrency = max(1, int(max_concurrency))
        self.max_queued = max(0, int(max_queued))
        self._queue: deque[_OneDayGenerationQueueJob] = deque()
        self._active_count = 0
        self._closed = False
        self._lock = RLock()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            queued = len(self._queue)
            return {
                "active": self._active_count,
                "queued": queued,
                "pending": self._active_count + queued,
                "max_concurrency": self.max_concurrency,
                "max_queued": self.max_queued,
            }

    def submit(self, runner: Callable[[], Awaitable[T]]) -> OneDayGenerationQueueAdmission[T]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        job = _OneDayGenerationQueueJob(runner=runner, loop=loop, future=future)

        with self._lock:
            pending_count = self._active_count + len(self._queue)
            if self._closed or pending_count >= self.max_concurrency + self.max_queued:
                return OneDayGenerationQueueAdmission(accepted=False, future=None)

            starts_immediately = not self._queue and self._active_count < self.max_concurrency
            ahead_count = 0 if starts_immediately else pending_count
            self._queue.append(job)
            jobs_to_start = self._dispatch_locked()

        self._start_jobs(jobs_to_start)
        return OneDayGenerationQueueAdmission(
            accepted=True,
            future=future,
            starts_immediately=starts_immediately,
            ahead_count=ahead_count,
        )

    def cancel(self, future: asyncio.Future[object]) -> None:
        with self._lock:
            remaining: deque[_OneDayGenerationQueueJob] = deque()
            removed = False
            for job in self._queue:
                if job.future is future:
                    removed = True
                    continue
                remaining.append(job)
            if not removed:
                return
            self._queue = remaining
            if not future.done():
                future.cancel()

    def close(self, *, cancel_queued: bool = True) -> None:
        with self._lock:
            self._closed = True
            queued_jobs = list(self._queue)
            self._queue.clear()
        if cancel_queued:
            for job in queued_jobs:
                if not job.future.done():
                    job.future.cancel()

    def _dispatch_locked(self) -> list[_OneDayGenerationQueueJob]:
        jobs_to_start: list[_OneDayGenerationQueueJob] = []
        while self._queue and self._active_count < self.max_concurrency:
            job = self._queue.popleft()
            self._active_count += 1
            jobs_to_start.append(job)
        return jobs_to_start

    def _start_jobs(self, jobs: Sequence[_OneDayGenerationQueueJob]) -> None:
        for job in jobs:
            job.loop.create_task(self._run_job(job))

    async def _run_job(self, job: _OneDayGenerationQueueJob[T]) -> None:
        try:
            result = await job.runner()
        except Exception as exc:
            if not job.future.done():
                job.future.set_exception(exc)
        else:
            if not job.future.done():
                job.future.set_result(result)
        finally:
            with self._lock:
                self._active_count = max(0, self._active_count - 1)
                jobs_to_start = self._dispatch_locked()
            self._start_jobs(jobs_to_start)
