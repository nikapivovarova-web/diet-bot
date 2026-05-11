from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest

import diet_bot.telegram_app as telegram_app
from diet_bot.subscriptions import Entitlement, save_entitlements


class FakeSupportMessage:
    def __init__(self, chat_id: int, *, chat_type: str = "private", text: str = "") -> None:
        self.chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.from_user = SimpleNamespace(id=chat_id, username="user", full_name="User Name")
        self.text = text
        self.answers: list[str] = []

    async def answer(self, text: str, **_kwargs):
        self.answers.append(text)
        return SimpleNamespace(text=text)


class FailingInvoiceBot:
    async def create_invoice_link(self, **_kwargs):
        raise TelegramBadRequest(SimpleNamespace(), "invoice failed")


@pytest.mark.anyio
async def test_support_group_commands_are_ignored_without_private_guard_reply(monkeypatch) -> None:
    chat_id = -100123456
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID", chat_id)
    message = FakeSupportMessage(chat_id, chat_type="supergroup", text="/start")

    await telegram_app.start(message)

    assert message.answers == []


def test_support_admin_message_does_not_include_payment_charge_ids(monkeypatch, tmp_path) -> None:
    chat_id = 99_901
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "")
    monkeypatch.setattr(telegram_app, "_POSTGRES_STORE", None)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    telegram_app.PROFILE_BY_CHAT_ID.pop(chat_id, None)
    save_entitlements(
        telegram_app.SUBSCRIPTIONS_STATE_FILE,
        {
            chat_id: Entitlement(
                processed_payment_charge_ids=[
                    "telegram_stars:secret-charge-id",
                ],
            )
        },
    )
    message = FakeSupportMessage(chat_id, text="help")

    admin_text = telegram_app._format_support_admin_message(message, "Need help")

    assert "secret-charge-id" not in admin_text
    assert "processed_payment_charge_ids" not in admin_text


@pytest.mark.anyio
async def test_invoice_exception_log_extra_hashes_identifiers(monkeypatch, tmp_path) -> None:
    chat_id = 99_902
    captured_extras: list[dict[str, object]] = []
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "")
    monkeypatch.setattr(telegram_app, "_POSTGRES_STORE", None)
    monkeypatch.setattr(telegram_app, "PAYMENT_ORDERS_STATE_FILE", tmp_path / "payment_orders.json")
    monkeypatch.setattr(
        telegram_app.logger,
        "exception",
        lambda _message, *args, **kwargs: captured_extras.append(kwargs.get("extra") or {}),
    )
    message = FakeSupportMessage(chat_id, text="/pay")
    message.bot = FailingInvoiceBot()

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)

    assert captured_extras
    extra = captured_extras[-1]
    assert "user_id" not in extra
    assert "order_id" not in extra
    assert extra["user_hash"] != str(chat_id)
    assert str(chat_id) not in extra["user_hash"]
    assert str(chat_id) not in extra["order_hash"]


@pytest.mark.anyio
async def test_hidden_test_access_command_is_disabled_without_env(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "TEST_ACCESS_COMMAND", "")
    legacy_command = "".join(("330", "366"))
    message = FakeSupportMessage(99_903, text=f"/{legacy_command}")

    await telegram_app.secret_access_command(message)

    assert message.answers == [telegram_app.TEST_ACCESS_COMMAND_DISABLED_TEXT]


def test_privacy_policy_mentions_telegram_and_support_metadata() -> None:
    text = telegram_app.PRIVACY_POLICY_MESSAGE.lower()

    assert "username" in text
    assert "first_name" in text
    assert "telegram metadata" in text
    assert "support metadata" in text
