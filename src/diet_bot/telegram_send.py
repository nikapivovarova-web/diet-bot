from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)


DEFAULT_TELEGRAM_SEND_MAX_ATTEMPTS = 3
DEFAULT_TELEGRAM_SEND_BASE_BACKOFF_SECONDS = 0.5
DEFAULT_TELEGRAM_SEND_MAX_BACKOFF_SECONDS = 30.0
DEFAULT_TELEGRAM_SEND_JITTER_RATIO = 0.2
DEFAULT_TELEGRAM_SEND_CONCURRENCY = 4

logger = logging.getLogger(__name__)
_LONG_IDENTIFIER_PATTERN = re.compile(r"\d{5,}")
_TOKEN_LIKE_PATTERN = re.compile(r"\d{5,}[_:-][A-Za-z0-9_-]{8,}")

T = TypeVar("T")
TelegramSendOperation = Callable[[], Awaitable[T]]
TelegramSendSleep = Callable[[float], Awaitable[None]]


class TelegramSendFailureClass(str, Enum):
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class TelegramSendStatus(str, Enum):
    SUCCESS = "success"
    RETRY_EXHAUSTED = "retry_exhausted"
    PERMANENT_FAILURE = "permanent_failure"
    UNKNOWN_FAILURE = "unknown_failure"


@dataclass(frozen=True)
class TelegramSendSettings:
    max_attempts: int = DEFAULT_TELEGRAM_SEND_MAX_ATTEMPTS
    base_backoff_seconds: float = DEFAULT_TELEGRAM_SEND_BASE_BACKOFF_SECONDS
    max_backoff_seconds: float = DEFAULT_TELEGRAM_SEND_MAX_BACKOFF_SECONDS
    jitter_ratio: float = DEFAULT_TELEGRAM_SEND_JITTER_RATIO


@dataclass(frozen=True)
class TelegramSendResult:
    status: TelegramSendStatus
    classification: TelegramSendFailureClass
    attempts: int
    operation_name: str
    error_type: str | None = None
    retry_after_seconds: float | None = None

    @property
    def ok(self) -> bool:
        return self.status == TelegramSendStatus.SUCCESS


class TelegramSendError(RuntimeError):
    def __init__(self, result: TelegramSendResult) -> None:
        self.result = result
        super().__init__(
            "Telegram send failed "
            f"operation={result.operation_name} "
            f"status={result.status.value} "
            f"classification={result.classification.value} "
            f"attempts={result.attempts} "
            f"error_type={result.error_type or 'unknown'}"
        )


class TelegramSendLimiter:
    def __init__(self, concurrency: int = DEFAULT_TELEGRAM_SEND_CONCURRENCY) -> None:
        self.concurrency = max(1, int(concurrency))
        self._semaphores_by_loop: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        semaphore = self._semaphores_by_loop.get(loop)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self.concurrency)
            self._semaphores_by_loop[loop] = semaphore
        return semaphore

    async def run(self, operation: TelegramSendOperation[T]) -> T:
        async with self._semaphore():
            return await operation()


DEFAULT_TELEGRAM_SEND_SETTINGS = TelegramSendSettings()
DEFAULT_TELEGRAM_SEND_LIMITER = TelegramSendLimiter()


async def safe_telegram_send(
    operation: TelegramSendOperation[T],
    *,
    operation_name: str = "telegram_send",
    settings: TelegramSendSettings | None = None,
    limiter: TelegramSendLimiter | None = None,
    sleep: TelegramSendSleep = asyncio.sleep,
) -> T:
    effective_settings = settings or DEFAULT_TELEGRAM_SEND_SETTINGS
    effective_limiter = limiter or DEFAULT_TELEGRAM_SEND_LIMITER

    async def retry_loop() -> T:
        return await _send_with_retries(
            operation,
            operation_name=_safe_operation_name(operation_name),
            settings=effective_settings,
            sleep=sleep,
        )

    return await effective_limiter.run(retry_loop)


def classify_telegram_send_exception(exc: BaseException) -> TelegramSendFailureClass:
    if isinstance(exc, TelegramRetryAfter):
        return TelegramSendFailureClass.RETRYABLE
    if isinstance(exc, (TelegramNetworkError, TelegramServerError)):
        return TelegramSendFailureClass.RETRYABLE
    if isinstance(
        exc,
        (
            TelegramForbiddenError,
            TelegramNotFound,
            TelegramUnauthorizedError,
            TelegramEntityTooLarge,
        ),
    ):
        return TelegramSendFailureClass.PERMANENT
    if isinstance(exc, TelegramBadRequest):
        message = str(exc).lower()
        if any(
            marker in message
            for marker in (
                "bot was blocked",
                "chat not found",
                "user is deactivated",
                "message is too long",
                "entity too large",
            )
        ):
            return TelegramSendFailureClass.PERMANENT
        return TelegramSendFailureClass.UNKNOWN
    if isinstance(exc, TelegramAPIError):
        return TelegramSendFailureClass.UNKNOWN
    return TelegramSendFailureClass.UNKNOWN


async def _send_with_retries(
    operation: TelegramSendOperation[T],
    *,
    operation_name: str,
    settings: TelegramSendSettings,
    sleep: TelegramSendSleep,
) -> T:
    max_attempts = max(1, int(settings.max_attempts))
    for attempt in range(1, max_attempts + 1):
        try:
            result = await operation()
        except Exception as exc:
            classification = classify_telegram_send_exception(exc)
            retry_after = _retry_after_seconds(exc)
            if classification == TelegramSendFailureClass.PERMANENT:
                _log_send_failure(
                    operation_name=operation_name,
                    status=TelegramSendStatus.PERMANENT_FAILURE,
                    classification=classification,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    exc=exc,
                    retry_after=retry_after,
                )
                raise TelegramSendError(
                    TelegramSendResult(
                        status=TelegramSendStatus.PERMANENT_FAILURE,
                        classification=classification,
                        attempts=attempt,
                        operation_name=operation_name,
                        error_type=type(exc).__name__,
                        retry_after_seconds=retry_after,
                    )
                ) from exc
            if classification == TelegramSendFailureClass.UNKNOWN:
                _log_send_failure(
                    operation_name=operation_name,
                    status=TelegramSendStatus.UNKNOWN_FAILURE,
                    classification=classification,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    exc=exc,
                    retry_after=retry_after,
                )
                raise TelegramSendError(
                    TelegramSendResult(
                        status=TelegramSendStatus.UNKNOWN_FAILURE,
                        classification=classification,
                        attempts=attempt,
                        operation_name=operation_name,
                        error_type=type(exc).__name__,
                        retry_after_seconds=retry_after,
                    )
                ) from exc
            if attempt >= max_attempts:
                _log_send_failure(
                    operation_name=operation_name,
                    status=TelegramSendStatus.RETRY_EXHAUSTED,
                    classification=classification,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    exc=exc,
                    retry_after=retry_after,
                )
                raise TelegramSendError(
                    TelegramSendResult(
                        status=TelegramSendStatus.RETRY_EXHAUSTED,
                        classification=classification,
                        attempts=attempt,
                        operation_name=operation_name,
                        error_type=type(exc).__name__,
                        retry_after_seconds=retry_after,
                    )
                ) from exc

            delay = _retry_delay_seconds(exc, attempt=attempt, settings=settings)
            logger.warning(
                "Telegram send retry scheduled operation=%s attempt=%d max_attempts=%d "
                "classification=%s error_type=%s retry_delay_seconds=%.3f",
                operation_name,
                attempt,
                max_attempts,
                classification.value,
                type(exc).__name__,
                delay,
            )
            await sleep(delay)
        else:
            return result

    raise RuntimeError("unreachable telegram send retry loop state")


def _retry_delay_seconds(exc: BaseException, *, attempt: int, settings: TelegramSendSettings) -> float:
    retry_after = _retry_after_seconds(exc)
    if retry_after is not None:
        return retry_after

    base = max(0.0, float(settings.base_backoff_seconds))
    maximum = max(base, float(settings.max_backoff_seconds))
    delay = min(maximum, base * (2 ** max(0, attempt - 1)))
    jitter_ratio = max(0.0, float(settings.jitter_ratio))
    if delay > 0 and jitter_ratio > 0:
        delay += random.uniform(0, delay * jitter_ratio)
    return delay


def _retry_after_seconds(exc: BaseException) -> float | None:
    raw_retry_after = getattr(exc, "retry_after", None)
    if raw_retry_after is None:
        return None
    try:
        retry_after = float(raw_retry_after)
    except (TypeError, ValueError):
        return None
    return max(0.0, retry_after)


def _log_send_failure(
    *,
    operation_name: str,
    status: TelegramSendStatus,
    classification: TelegramSendFailureClass,
    attempt: int,
    max_attempts: int,
    exc: BaseException,
    retry_after: float | None,
) -> None:
    logger.warning(
        "Telegram send failed operation=%s status=%s classification=%s "
        "attempt=%d max_attempts=%d error_type=%s retry_after_seconds=%s",
        operation_name,
        status.value,
        classification.value,
        attempt,
        max_attempts,
        type(exc).__name__,
        f"{retry_after:.3f}" if retry_after is not None else "none",
    )


def _safe_operation_name(operation_name: str) -> str:
    safe = "".join(
        character if character.isascii() and (character.isalnum() or character in {"_", "-", "."}) else "_"
        for character in str(operation_name).strip()
    )
    safe = _TOKEN_LIKE_PATTERN.sub("token", safe)
    safe = _LONG_IDENTIFIER_PATTERN.sub("id", safe)
    return safe[:80] or "telegram_send"
