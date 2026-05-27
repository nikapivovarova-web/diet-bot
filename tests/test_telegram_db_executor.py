from __future__ import annotations

from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.payments import encode_payment_order_payload


@pytest.mark.anyio
async def test_pre_checkout_handler_dispatches_validation_through_db_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_run_db_call(func, *args, **kwargs):
        assert kwargs == {}
        calls.append((func, args))
        return func(*args)

    query = _FakePreCheckoutQuery()
    monkeypatch.setattr(telegram_app, "run_db_call", fake_run_db_call, raising=False)
    monkeypatch.setattr(telegram_app, "_is_valid_pre_checkout", lambda _query: True)

    await telegram_app.handle_pre_checkout(query)

    assert calls == [(telegram_app._is_valid_pre_checkout, (query,))]
    assert query.answers == [{"ok": True}]


@pytest.mark.anyio
async def test_successful_payment_handler_dispatches_apply_through_db_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    async def fake_run_db_call(func, *args, **kwargs):
        calls.append((func, args, dict(kwargs)))
        return func(*args, **kwargs)

    payment = SimpleNamespace(
        invoice_payload=encode_payment_order_payload("order_12345678", "nonce_12345678"),
        currency="XTR",
        total_amount=35,
        telegram_payment_charge_id="tg-charge-ok",
        provider_payment_charge_id=None,
    )
    message = _FakeMessage(chat_id=202, user_id=101, payment=payment)

    monkeypatch.setattr(telegram_app, "run_db_call", fake_run_db_call, raising=False)
    monkeypatch.setattr(
        telegram_app,
        "_apply_successful_payment",
        lambda _chat_id, _payment, *, user_id=None: telegram_app.PaymentApplication(
            True,
            "extra_one_day",
        ),
    )
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    monkeypatch.setattr(telegram_app, "_has_active_paid_access", lambda _chat_id: False)

    await telegram_app.handle_successful_payment(message)

    apply_calls = [call for call in calls if call[0] is telegram_app._apply_successful_payment]
    assert apply_calls == [
        (
            telegram_app._apply_successful_payment,
            (202, payment),
            {"user_id": 101},
        ),
    ]
    assert message.texts


@pytest.mark.anyio
async def test_profile_load_notice_dispatches_chat_state_read_through_db_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_run_db_call(func, *args, **kwargs):
        assert kwargs == {}
        calls.append((func, args))
        return func(*args)

    message = _FakeMessage(chat_id=303, user_id=303)
    monkeypatch.setattr(telegram_app, "run_db_call", fake_run_db_call, raising=False)
    monkeypatch.setattr(telegram_app, "_should_dispatch_storage_db_calls", lambda: True)
    monkeypatch.setattr(telegram_app, "_profile_for_chat", lambda _chat_id: None)

    loaded, profile = await telegram_app._load_profile_for_message_or_notice(message)

    assert loaded is True
    assert profile is None
    assert calls == [(telegram_app._profile_for_chat, (303,))]


@pytest.mark.anyio
async def test_profile_load_notice_keeps_json_storage_on_sync_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_run_db_call(*_args, **_kwargs):
        raise AssertionError("JSON storage should not be dispatched through DB executor")

    message = _FakeMessage(chat_id=404, user_id=404)
    monkeypatch.setattr(telegram_app, "run_db_call", fail_run_db_call, raising=False)
    monkeypatch.setattr(telegram_app, "_should_dispatch_storage_db_calls", lambda: False)
    monkeypatch.setattr(telegram_app, "_profile_for_chat", lambda _chat_id: None)

    loaded, profile = await telegram_app._load_profile_for_message_or_notice(message)

    assert loaded is True
    assert profile is None


class _FakePreCheckoutQuery:
    def __init__(self) -> None:
        self.answers: list[dict[str, object]] = []

    async def answer(self, **kwargs) -> None:
        self.answers.append(dict(kwargs))


class _FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.type = "private"


class _FakeFromUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class _FakeMessage:
    def __init__(self, *, chat_id: int, user_id: int, payment: object | None = None) -> None:
        self.chat = _FakeChat(chat_id)
        self.from_user = _FakeFromUser(user_id)
        self.successful_payment = payment
        self.texts: list[tuple[str, object | None]] = []

    async def answer(self, text, reply_markup=None):
        self.texts.append((text, reply_markup))
        return self
