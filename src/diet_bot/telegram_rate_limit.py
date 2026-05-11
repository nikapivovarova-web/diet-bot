from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from typing import TypeVar

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from .state_cache import BoundedTTLDict


logger = logging.getLogger(__name__)
T = TypeVar("T")
DEFAULT_RATE_LIMIT_CACHE_MAX_SIZE = 100_000
DEFAULT_RATE_LIMIT_CACHE_TTL_SECONDS = 15 * 60


@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    retry_after: float = 0.0


class IncomingThrottle:
    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        cache_max_size: int = DEFAULT_RATE_LIMIT_CACHE_MAX_SIZE,
        cache_ttl_seconds: float = DEFAULT_RATE_LIMIT_CACHE_TTL_SECONDS,
    ) -> None:
        self._monotonic = monotonic
        self._last_seen: BoundedTTLDict[tuple[str, Hashable], float] = BoundedTTLDict(
            max_size=cache_max_size,
            ttl_seconds=cache_ttl_seconds,
            monotonic=monotonic,
        )
        self._lock = asyncio.Lock()

    async def check(self, action: str, user_key: Hashable, interval: float) -> ThrottleDecision:
        if interval <= 0:
            return ThrottleDecision(allowed=True)
        async with self._lock:
            now = self._monotonic()
            key = (action, user_key)
            last_seen = self._last_seen.get(key)
            if last_seen is not None:
                retry_after = interval - (now - last_seen)
                if retry_after > 0:
                    logger.info(
                        "Incoming user throttle applied",
                        extra={"action": action, "retry_after_seconds": round(retry_after, 3)},
                    )
                    return ThrottleDecision(allowed=False, retry_after=retry_after)
            self._last_seen[key] = now
            return ThrottleDecision(allowed=True)

    def reset(self) -> None:
        self._last_seen.clear()

    def prune(self) -> None:
        self._last_seen.prune()

    @property
    def tracked_key_count(self) -> int:
        return len(self._last_seen)


class TelegramRateLimiter:
    def __init__(
        self,
        *,
        per_chat_interval: float = 1.0,
        global_interval: float = 1.0 / 23.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        cache_max_size: int = DEFAULT_RATE_LIMIT_CACHE_MAX_SIZE,
        cache_ttl_seconds: float = DEFAULT_RATE_LIMIT_CACHE_TTL_SECONDS,
    ) -> None:
        self.per_chat_interval = per_chat_interval
        self.global_interval = global_interval
        self._monotonic = monotonic
        self._sleep = sleep
        self._chat_next_allowed: BoundedTTLDict[Hashable, float] = BoundedTTLDict(
            max_size=cache_max_size,
            ttl_seconds=cache_ttl_seconds,
            monotonic=monotonic,
        )
        self._chat_lock = asyncio.Lock()
        self._global_next_allowed = 0.0
        self._global_lock = asyncio.Lock()

    async def run(
        self,
        operation_name: str,
        call: Callable[[], Awaitable[T]],
        *,
        chat_id: Hashable | None = None,
        attempts: int = 3,
        base_delay: float = 0.7,
        max_delay: float | None = None,
        rate_limit: bool = True,
    ) -> T:
        last_error: TelegramAPIError | None = None

        for attempt in range(1, attempts + 1):
            if rate_limit:
                await self.wait(operation_name, chat_id=chat_id)
            try:
                return await call()
            except TelegramRetryAfter as exc:
                last_error = exc
                delay = float(exc.retry_after)
                if max_delay is not None:
                    delay = min(delay, max_delay)
                logger.warning(
                    "Telegram retry_after received",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt,
                        "attempts": attempts,
                        "retry_after_seconds": delay,
                    },
                )
            except (TelegramNetworkError, TelegramServerError) as exc:
                last_error = exc
                delay = base_delay * (2 ** (attempt - 1))
                if max_delay is not None:
                    delay = min(delay, max_delay)
                logger.warning(
                    "Temporary Telegram API error",
                    extra={"operation": operation_name, "attempt": attempt, "attempts": attempts},
                )
            except TelegramAPIError:
                raise

            if attempt < attempts:
                await self._sleep_for(delay)

        assert last_error is not None
        raise last_error

    async def wait(self, operation_name: str, *, chat_id: Hashable | None = None) -> None:
        if chat_id is not None:
            await self._wait_chat(operation_name, chat_id)
        await self._wait_global(operation_name)

    async def _wait_chat(self, operation_name: str, chat_id: Hashable) -> None:
        wait_seconds = await self._reserve_chat_slot(chat_id)
        if wait_seconds > 0:
            logger.info(
                "Telegram per-chat rate limit wait",
                extra={"operation": operation_name, "wait_seconds": round(wait_seconds, 3)},
            )
            await self._sleep_for(wait_seconds)

    async def _wait_global(self, operation_name: str) -> None:
        wait_seconds = await self._reserve_global_slot()
        if wait_seconds > 0:
            logger.info(
                "Telegram global rate limit wait",
                extra={"operation": operation_name, "wait_seconds": round(wait_seconds, 3)},
            )
            await self._sleep_for(wait_seconds)

    async def _reserve_chat_slot(self, chat_id: Hashable) -> float:
        if self.per_chat_interval <= 0:
            return 0.0
        async with self._chat_lock:
            now = self._monotonic()
            next_allowed = self._chat_next_allowed.get(chat_id, 0.0)
            wait_seconds = max(0.0, next_allowed - now)
            self._chat_next_allowed[chat_id] = max(now, next_allowed) + self.per_chat_interval
            return wait_seconds

    async def _reserve_global_slot(self) -> float:
        if self.global_interval <= 0:
            return 0.0
        async with self._global_lock:
            now = self._monotonic()
            wait_seconds = max(0.0, self._global_next_allowed - now)
            self._global_next_allowed = max(now, self._global_next_allowed) + self.global_interval
            return wait_seconds

    def reset(self) -> None:
        self._chat_next_allowed.clear()
        self._global_next_allowed = 0.0

    def prune(self) -> None:
        self._chat_next_allowed.prune()

    @property
    def tracked_chat_count(self) -> int:
        return len(self._chat_next_allowed)

    async def _sleep_for(self, delay: float) -> None:
        sleep = self._sleep or asyncio.sleep
        await sleep(delay)
