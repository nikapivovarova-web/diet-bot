from __future__ import annotations

import asyncio

import pytest

from diet_bot.one_day_generation_queue import OneDayGenerationQueue


@pytest.mark.anyio
async def test_queue_accepts_concurrency_plus_max_queued_and_rejects_overflow() -> None:
    queue = OneDayGenerationQueue(max_concurrency=2, max_queued=3)
    release = asyncio.Event()

    async def wait_for_release() -> bool:
        await release.wait()
        return True

    admissions = [queue.submit(wait_for_release) for _ in range(5)]
    overflow = queue.submit(wait_for_release)

    assert [admission.accepted for admission in admissions] == [True, True, True, True, True]
    assert overflow.accepted is False
    assert overflow.future is None
    assert queue.snapshot() == {
        "active": 2,
        "queued": 3,
        "pending": 5,
        "max_concurrency": 2,
        "max_queued": 3,
    }

    release.set()
    assert await asyncio.gather(*(admission.future for admission in admissions if admission.future)) == [
        True,
        True,
        True,
        True,
        True,
    ]
    assert queue.snapshot()["pending"] == 0


@pytest.mark.anyio
async def test_queue_never_exceeds_configured_worker_concurrency() -> None:
    queue = OneDayGenerationQueue(max_concurrency=3, max_queued=20)
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def runner() -> int:
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return max_active

    admissions = [queue.submit(runner) for _ in range(20)]

    assert all(admission.accepted for admission in admissions)
    await asyncio.gather(*(admission.future for admission in admissions if admission.future))
    assert max_active <= 3
    assert queue.snapshot()["pending"] == 0


@pytest.mark.anyio
async def test_queue_propagates_exceptions_and_releases_slots() -> None:
    queue = OneDayGenerationQueue(max_concurrency=1, max_queued=1)

    async def fail() -> bool:
        raise RuntimeError("planner failed")

    async def succeed() -> bool:
        return True

    failed = queue.submit(fail)
    queued = queue.submit(succeed)

    assert failed.future is not None
    assert queued.future is not None
    with pytest.raises(RuntimeError, match="planner failed"):
        await failed.future
    assert await queued.future is True
    assert queue.snapshot()["pending"] == 0


@pytest.mark.anyio
async def test_queue_close_rejects_new_work_and_cancels_waiting_jobs() -> None:
    queue = OneDayGenerationQueue(max_concurrency=1, max_queued=1)
    release = asyncio.Event()

    async def wait_for_release() -> bool:
        await release.wait()
        return True

    active = queue.submit(wait_for_release)
    queued = queue.submit(wait_for_release)

    assert active.future is not None
    assert queued.future is not None
    queue.close(cancel_queued=True)

    assert queue.submit(wait_for_release).accepted is False
    assert queued.future.cancelled()

    release.set()
    assert await active.future is True
    assert queue.snapshot()["pending"] == 0


@pytest.mark.anyio
async def test_queue_rehearsal_1000_requests_caps_admissions_and_worker_concurrency() -> None:
    queue = OneDayGenerationQueue(max_concurrency=4, max_queued=12)
    release = asyncio.Event()
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def runner() -> bool:
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await release.wait()
        async with lock:
            active -= 1
        return True

    admissions = [queue.submit(runner) for _ in range(1000)]
    accepted = [admission for admission in admissions if admission.accepted]
    rejected = [admission for admission in admissions if not admission.accepted]

    assert len(accepted) <= 16
    assert len(rejected) == 1000 - len(accepted)
    assert all(admission.future is None for admission in rejected)
    assert queue.snapshot()["active"] <= 4
    assert queue.snapshot()["queued"] <= 12

    release.set()
    await asyncio.gather(*(admission.future for admission in accepted if admission.future))
    assert max_active <= 4
    assert queue.snapshot()["pending"] == 0
