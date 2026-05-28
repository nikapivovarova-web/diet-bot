from __future__ import annotations

import logging

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage

from diet_bot.telegram_send import (
    TelegramSendError,
    TelegramSendFailureClass,
    TelegramSendSettings,
    TelegramSendStatus,
    safe_telegram_send,
)


def _send_message_method(*, chat_id: int = 123_456) -> SendMessage:
    return SendMessage(chat_id=chat_id, text="test")


@pytest.mark.anyio
async def test_safe_telegram_send_success_path() -> None:
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        return "sent"

    result = await safe_telegram_send(operation, operation_name="unit_success")

    assert result == "sent"
    assert attempts == 1


@pytest.mark.anyio
async def test_safe_telegram_send_respects_retry_after_with_fake_sleep() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TelegramRetryAfter(
                method=_send_message_method(),
                message="flood control",
                retry_after=2,
            )
        return "sent"

    result = await safe_telegram_send(
        operation,
        operation_name="unit_retry_after",
        settings=TelegramSendSettings(max_attempts=3, jitter_ratio=0),
        sleep=sleep,
    )

    assert result == "sent"
    assert attempts == 2
    assert sleeps == [2.0]


@pytest.mark.anyio
async def test_safe_telegram_send_retries_transient_network_error_then_succeeds() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TelegramNetworkError(method=_send_message_method(), message="temporary network error")
        return "sent"

    result = await safe_telegram_send(
        operation,
        operation_name="unit_network_retry",
        settings=TelegramSendSettings(
            max_attempts=3,
            base_backoff_seconds=0.25,
            max_backoff_seconds=2.0,
            jitter_ratio=0,
        ),
        sleep=sleep,
    )

    assert result == "sent"
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


@pytest.mark.anyio
async def test_safe_telegram_send_treats_forbidden_chat_as_permanent() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise TelegramForbiddenError(method=_send_message_method(), message="bot was blocked by the user")

    with pytest.raises(TelegramSendError) as raised:
        await safe_telegram_send(
            operation,
            operation_name="unit_forbidden",
            settings=TelegramSendSettings(max_attempts=3, jitter_ratio=0),
            sleep=sleep,
        )

    assert attempts == 1
    assert sleeps == []
    assert raised.value.result.status == TelegramSendStatus.PERMANENT_FAILURE
    assert raised.value.result.classification == TelegramSendFailureClass.PERMANENT


@pytest.mark.anyio
async def test_safe_telegram_send_exhausts_bounded_retries_with_typed_error() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise TelegramNetworkError(method=_send_message_method(), message="temporary network error")

    with pytest.raises(TelegramSendError) as raised:
        await safe_telegram_send(
            operation,
            operation_name="unit_retry_exhausted",
            settings=TelegramSendSettings(
                max_attempts=2,
                base_backoff_seconds=0.25,
                jitter_ratio=0,
            ),
            sleep=sleep,
        )

    assert attempts == 2
    assert sleeps == [0.25]
    assert raised.value.result.status == TelegramSendStatus.RETRY_EXHAUSTED
    assert raised.value.result.classification == TelegramSendFailureClass.RETRYABLE


@pytest.mark.anyio
async def test_safe_telegram_send_logs_classification_without_raw_identifiers(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="diet_bot.telegram_send")

    async def operation() -> str:
        raise TelegramRetryAfter(
            method=_send_message_method(chat_id=987_654_321),
            message="token 123:ABC should not be logged",
            retry_after=1,
        )

    with pytest.raises(TelegramSendError):
        await safe_telegram_send(
            operation,
            operation_name="unit_log_redaction_chat_987654321",
            settings=TelegramSendSettings(max_attempts=1, jitter_ratio=0),
        )

    assert "retryable" in caplog.text
    assert "987654321" not in caplog.text
    assert "123:ABC" not in caplog.text
    assert "token" not in caplog.text.lower()
