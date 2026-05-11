import asyncio

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.state_cache import BoundedTTLDict
from diet_bot.telegram_rate_limit import IncomingThrottle, TelegramRateLimiter


async def _no_sleep(_delay: float) -> None:
    return None


def test_generation_locks_are_bounded_after_many_chat_ids() -> None:
    cache = telegram_app.GENERATION_LOCKS_BY_CHAT_ID
    sentinel_chat_id = -1
    cache.clear()
    try:
        sentinel_lock = telegram_app._generation_lock_for_chat(sentinel_chat_id)

        for chat_id in range(200_000):
            telegram_app._generation_lock_for_chat(chat_id)

        telegram_app.prune_chat_state_caches()

        assert len(cache) <= cache.max_size
        assert sentinel_chat_id not in cache
        recreated_lock = telegram_app._generation_lock_for_chat(sentinel_chat_id)
        assert recreated_lock is not sentinel_lock
        assert not recreated_lock.locked()
    finally:
        cache.clear()


@pytest.mark.anyio
async def test_generation_lock_cache_keeps_locked_entries_until_release() -> None:
    cache: BoundedTTLDict[int, asyncio.Lock] = BoundedTTLDict(
        max_size=1,
        ttl_seconds=60,
        evictable=lambda lock: not lock.locked(),
    )
    held_lock = asyncio.Lock()
    await held_lock.acquire()

    cache[1] = held_lock
    cache[2] = asyncio.Lock()

    assert 1 in cache
    assert 2 in cache

    held_lock.release()
    cache.prune()

    assert len(cache) == 1


@pytest.mark.anyio
async def test_rate_limit_state_is_bounded_after_many_chat_ids() -> None:
    cap = 1_000
    throttle = IncomingThrottle(cache_max_size=cap, cache_ttl_seconds=60)
    limiter = TelegramRateLimiter(
        per_chat_interval=1.0,
        global_interval=0.0,
        cache_max_size=cap,
        cache_ttl_seconds=60,
        sleep=_no_sleep,
    )

    for chat_id in range(200_000):
        decision = await throttle.check("start", chat_id, 1.0)
        await limiter.wait("send_message", chat_id=chat_id)
        assert decision.allowed

    throttle.prune()
    limiter.prune()

    assert throttle.tracked_key_count <= cap
    assert limiter.tracked_chat_count <= cap
