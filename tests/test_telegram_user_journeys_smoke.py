from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app


class FakeChat:
    def __init__(self, chat_id: int, chat_type: str = "private") -> None:
        self.id = chat_id
        self.type = chat_type


class FakeMessage:
    def __init__(self, chat_id: int, text: str = "", user_id: int | None = None) -> None:
        self.chat = FakeChat(chat_id)
        self.text = text
        self.from_user = SimpleNamespace(id=chat_id if user_id is None else user_id)
        self.answers: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup: object | None = None) -> object:
        self.answers.append((text, reply_markup))
        return SimpleNamespace(edit_text=lambda _text: None)


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage, user_id: int | None = None) -> None:
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=message.chat.id if user_id is None else user_id)
        self.answers: list[str | None] = []

    async def answer(self, text: str | None = None, show_alert: bool | None = None) -> None:
        self.answers.append(text)


class InMemoryChatStateStore:
    def __init__(self, state: dict[str, dict[str, object]] | None = None) -> None:
        self.state = state or {}
        self.save_calls: list[tuple[int, dict[str, object]]] = []

    def load_chat_state(self, chat_id: int) -> dict[str, object]:
        return dict(self.state.get(str(chat_id), {}))

    def save_chat_state(self, chat_id: int, chat_state: dict[str, object]) -> None:
        current = dict(self.state.get(str(chat_id), {}))
        current.update(dict(chat_state))
        self.state[str(chat_id)] = current
        self.save_calls.append((int(chat_id), dict(chat_state)))

    def load_all(self) -> dict[str, dict[str, object]]:
        return {chat_id: dict(state) for chat_id, state in self.state.items()}

    def save_all(self, state: dict[str, dict[str, object]]) -> None:
        self.state = {chat_id: dict(chat_state) for chat_id, chat_state in state.items()}


class FailingConsentSaveStore(InMemoryChatStateStore):
    def save_chat_state(self, chat_id: int, chat_state: dict[str, object]) -> None:
        raise telegram_app.ChatStateStorageError("consent save failed")


def _keyboard_buttons(reply_markup: object | None) -> list[tuple[str, str | None]]:
    if reply_markup is None:
        return []
    return [
        (button.text, button.callback_data)
        for row in getattr(reply_markup, "inline_keyboard", [])
        for button in row
    ]


def test_privacy_consent_text_matches_required_copy() -> None:
    assert telegram_app.PRIVACY_CONSENT_TEXT == (
        "Перед началом нужно подтвердить согласие с политикой конфиденциальности FoodBalance. "
        "Мы используем данные анкеты только для расчета рациона, проверки доступа и поддержки."
    )


def test_free_trial_callback_shows_privacy_consent_before_first_question(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_id = 51_004
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None)
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: InMemoryChatStateStore())
    message = FakeMessage(chat_id)
    callback = FakeCallback(telegram_app.CALLBACK_START, message)

    try:
        asyncio.run(telegram_app.handle_callback(callback))

        text, reply_markup = message.answers[-1]
        buttons = _keyboard_buttons(reply_markup)
        assert text == telegram_app.PRIVACY_CONSENT_TEXT
        assert buttons == [
            (telegram_app.PRIVACY_CONSENT_ACCEPT_TEXT, telegram_app.CALLBACK_PRIVACY_CONSENT_TRIAL),
            (telegram_app.PRIVACY_POLICY_TEXT, telegram_app.CALLBACK_PRIVACY_POLICY),
            (telegram_app.SUPPORT_TEXT, telegram_app.CALLBACK_SUPPORT),
        ]
        assert chat_id not in telegram_app.SESSION_BY_CHAT_ID
        assert chat_id not in telegram_app.TRIAL_CHAT_IDS
    finally:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        getattr(telegram_app, "PRIVACY_CONSENT_CHAT_IDS", set()).discard(chat_id)


def test_privacy_consent_acceptance_continues_to_first_question(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_id = 51_005
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None)
    store = InMemoryChatStateStore()
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    message = FakeMessage(chat_id)
    callback = FakeCallback(telegram_app.CALLBACK_PRIVACY_CONSENT_TRIAL, message)

    try:
        asyncio.run(telegram_app.handle_callback(callback))

        text, reply_markup = message.answers[-1]
        buttons = _keyboard_buttons(reply_markup)
        assert text == telegram_app.start_session().current_question.prompt
        assert chat_id in telegram_app.PRIVACY_CONSENT_CHAT_IDS
        assert store.save_calls
        assert "privacy_consent" in store.save_calls[-1][1]
        assert chat_id in telegram_app.SESSION_BY_CHAT_ID
        assert chat_id in telegram_app.TRIAL_CHAT_IDS
        assert all(button_text != telegram_app.PRIVACY_POLICY_TEXT for button_text, _ in buttons)
    finally:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        getattr(telegram_app, "PRIVACY_CONSENT_CHAT_IDS", set()).discard(chat_id)


def test_privacy_consent_acceptance_is_loaded_from_chat_state_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_id = 51_007
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None)
    store = InMemoryChatStateStore()
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    accept_message = FakeMessage(chat_id)
    accept_callback = FakeCallback(telegram_app.CALLBACK_PRIVACY_CONSENT_TRIAL, accept_message)

    try:
        asyncio.run(telegram_app.handle_callback(accept_callback))
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        telegram_app.PRIVACY_CONSENT_CHAT_IDS.discard(chat_id)

        restart_message = FakeMessage(chat_id)
        asyncio.run(telegram_app._start_questionnaire_with_privacy_consent(restart_message))

        text, reply_markup = restart_message.answers[-1]
        assert text == telegram_app.start_session().current_question.prompt
        assert text != telegram_app.PRIVACY_CONSENT_TEXT
        assert chat_id in telegram_app.PRIVACY_CONSENT_CHAT_IDS
        assert not _keyboard_buttons(reply_markup)
    finally:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        telegram_app.PRIVACY_CONSENT_CHAT_IDS.discard(chat_id)


def test_privacy_consent_save_failure_does_not_start_questionnaire(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_id = 51_008
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: FailingConsentSaveStore())
    message = FakeMessage(chat_id)
    callback = FakeCallback(telegram_app.CALLBACK_PRIVACY_CONSENT_TRIAL, message)

    try:
        asyncio.run(telegram_app.handle_callback(callback))

        text, reply_markup = message.answers[-1]
        assert text == telegram_app.PRIVACY_CONSENT_STORAGE_ERROR_TEXT
        assert reply_markup is None
        assert chat_id not in telegram_app.PRIVACY_CONSENT_CHAT_IDS
        assert chat_id not in telegram_app.SESSION_BY_CHAT_ID
        assert chat_id not in telegram_app.TRIAL_CHAT_IDS
    finally:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        telegram_app.PRIVACY_CONSENT_CHAT_IDS.discard(chat_id)


def test_questionnaire_question_markup_does_not_include_privacy_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None)

    session = telegram_app.QuestionnaireSession({"age": "32"}, step_index=1)
    keyboard = telegram_app._question_keyboard_for_session(51_006, session)
    buttons = _keyboard_buttons(keyboard)

    assert buttons
    assert all(button_text != telegram_app.PRIVACY_POLICY_TEXT for button_text, _ in buttons)


def test_start_shows_foodbalance_branding_and_product_menu_buttons(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_welcome_photo(_message: FakeMessage) -> None:
        return None

    async def no_paid_access(_chat_id: int) -> bool:
        return False

    async def no_saved_profile(_chat_id: int) -> None:
        return None

    monkeypatch.setattr(telegram_app, "_send_welcome_photo", no_welcome_photo)
    monkeypatch.setattr(telegram_app, "_has_active_paid_access_async", no_paid_access)
    monkeypatch.setattr(telegram_app, "_profile_for_chat_async", no_saved_profile)
    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", True)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None)

    message = FakeMessage(51_001, "/start")
    asyncio.run(telegram_app.start(message))

    text, reply_markup = message.answers[-1]
    buttons = _keyboard_buttons(reply_markup)

    assert "FoodBalance" in text
    assert "персональный помощник" in text
    assert buttons[:5] == [
        (telegram_app.TRY_FREE_TEXT, telegram_app.CALLBACK_START),
        ("💳 Доступ на 30 дней - 799 ₽", telegram_app.CALLBACK_SUBSCRIBE),
        (telegram_app.FEATURES_TEXT, telegram_app.CALLBACK_FEATURES),
        (telegram_app.PROMO_CODE_TEXT, telegram_app.CALLBACK_PROMO_CODE),
        (telegram_app.SUPPORT_TEXT, telegram_app.CALLBACK_SUPPORT),
    ]
    assert (telegram_app.PRIVACY_POLICY_TEXT, telegram_app.CALLBACK_PRIVACY_POLICY) in buttons


def test_payment_ui_uses_product_labels_without_applying_payment_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_grant(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Keyboard rendering must not apply payment grants")

    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", True)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None)
    monkeypatch.setattr(telegram_app, "apply_subscription_payment", fail_grant)

    keyboard = telegram_app._subscription_payment_keyboard()
    buttons = _keyboard_buttons(keyboard)

    assert buttons == [
        ("💳 Разовый доступ на 30 дней - 799 ₽", telegram_app.CALLBACK_PAY_RU_CARD),
        ("⭐ Подписка с автопродлением - 450 Stars", telegram_app.CALLBACK_PAY_TELEGRAM_STARS),
        (telegram_app.PROMO_CODE_TEXT, telegram_app.CALLBACK_PROMO_CODE),
        (telegram_app.SUPPORT_TEXT, telegram_app.CALLBACK_SUPPORT),
        (telegram_app.PRIVACY_POLICY_TEXT, telegram_app.CALLBACK_PRIVACY_POLICY),
    ]


def test_disabled_payment_ui_keeps_promo_entry_without_paid_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", False)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None)

    keyboard = telegram_app._subscription_payment_keyboard()
    buttons = _keyboard_buttons(keyboard)

    assert "Публичная оплата картой, SberPay и Telegram Stars пока выключена" in (
        telegram_app.PAYMENTS_DISABLED_TEXT
    )
    assert buttons == [
        (telegram_app.PROMO_CODE_TEXT, telegram_app.CALLBACK_PROMO_CODE),
        (telegram_app.SUPPORT_TEXT, telegram_app.CALLBACK_SUPPORT),
        (telegram_app.PRIVACY_POLICY_TEXT, telegram_app.CALLBACK_PRIVACY_POLICY),
    ]


def test_promo_command_starts_existing_promo_flow() -> None:
    chat_id = 51_002
    message = FakeMessage(chat_id, "/promo")
    try:
        asyncio.run(telegram_app.promo(message))

        assert chat_id in telegram_app.PROMO_CODE_REQUEST_CHAT_IDS
        assert message.answers[-1][0] == telegram_app.PROMO_CODE_PROMPT_TEXT
    finally:
        telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)


def test_main_plan_menu_keeps_promo_and_privacy_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None)

    buttons = _keyboard_buttons(telegram_app._plan_choice_keyboard())

    assert (telegram_app.PROMO_CODE_TEXT, telegram_app.CALLBACK_PROMO_CODE) in buttons
    assert (telegram_app.PRIVACY_POLICY_TEXT, telegram_app.CALLBACK_PRIVACY_POLICY) in buttons


def test_privacy_policy_is_reachable_without_external_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None)
    message = FakeMessage(51_003, "/privacy")

    asyncio.run(telegram_app.privacy(message))

    text, reply_markup = message.answers[-1]
    assert "Политика конфиденциальности FoodBalance" in text
    assert "персонального рациона" in text
    assert (telegram_app.SUPPORT_TEXT, telegram_app.CALLBACK_SUPPORT) in _keyboard_buttons(reply_markup)


def test_admin_330366_opens_promo_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {700})
    message = FakeMessage(700, "/330366", user_id=700)

    asyncio.run(telegram_app.secret_access_command(message))

    text, reply_markup = message.answers[-1]
    buttons = _keyboard_buttons(reply_markup)
    assert text == telegram_app.ADMIN_PROMO_PANEL_TEXT
    assert (telegram_app.ADMIN_CREATE_MONTHLY_ACCESS_CODE_TEXT, telegram_app.CALLBACK_ADMIN_CREATE_MONTHLY_ACCESS_CODE) in buttons
    assert (telegram_app.ADMIN_CREATE_DISCOUNT_PROMO_TEXT, telegram_app.CALLBACK_ADMIN_CREATE_DISCOUNT_PROMO) in buttons
    assert (telegram_app.ADMIN_LIST_DISCOUNT_PROMOS_TEXT, telegram_app.CALLBACK_ADMIN_LIST_DISCOUNT_PROMOS) in buttons
    assert (telegram_app.ADMIN_DISABLE_DISCOUNT_PROMO_TEXT, telegram_app.CALLBACK_ADMIN_DISABLE_DISCOUNT_PROMO) in buttons


def test_non_admin_330366_does_not_open_admin_promo_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {700})
    monkeypatch.setattr(telegram_app, "_format_test_access_command_status", lambda _chat_id: "STATUS")
    message = FakeMessage(701, "/330366", user_id=701)

    asyncio.run(telegram_app.secret_access_command(message))

    text, reply_markup = message.answers[-1]
    assert text == "Command is available only to admins."
    assert reply_markup is None
