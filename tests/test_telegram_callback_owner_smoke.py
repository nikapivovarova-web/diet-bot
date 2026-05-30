from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.questionnaire import QUESTIONS


def test_questionnaire_callback_data_keeps_session_token_and_step() -> None:
    chat_id = 52_001
    telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID[chat_id] = "owner-token"
    try:
        callback_data = telegram_app._question_answer_callback_data(
            1,
            chat_id=chat_id,
            step_index=2,
        )
    finally:
        telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.pop(chat_id, None)

    assert callback_data == f"{telegram_app.CALLBACK_ANSWER_PREFIX}owner-token:2:1"
    assert telegram_app._parse_questionnaire_answer_callback(callback_data) == (
        "owner-token",
        2,
        1,
    )


def test_product_private_chat_guard_texts_are_available() -> None:
    assert telegram_app.PRIVATE_CHAT_REQUIRED_TEXT.startswith(
        "Пожалуйста, откройте бота в личном чате, чтобы продолжить."
    )
    assert telegram_app.PRIVATE_CHAT_CALLBACK_TEXT.startswith(
        "Откройте бота в личном чате, чтобы использовать эту кнопку."
    )
    assert "private chat" in telegram_app.PRIVATE_CHAT_REQUIRED_TEXT
    assert "private chat" in telegram_app.PRIVATE_CHAT_CALLBACK_TEXT


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.type = "private"


class EditableMessage:
    def __init__(self, chat_id: int) -> None:
        self.chat = FakeChat(chat_id)
        self.answers: list[tuple[str, object | None]] = []
        self.edited_reply_markups: list[object] = []

    async def answer(self, text: str, reply_markup: object | None = None) -> None:
        self.answers.append((text, reply_markup))

    async def edit_reply_markup(self, reply_markup: object | None = None) -> None:
        self.edited_reply_markups.append(reply_markup)


class FakeCallback:
    def __init__(self, data: str, message: EditableMessage, user_id: int) -> None:
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=user_id)
        self.answers: list[tuple[str | None, bool | None]] = []

    async def answer(self, text: str | None = None, show_alert: bool | None = None) -> None:
        self.answers.append((text, show_alert))


def _button_texts(reply_markup: object | None) -> list[str]:
    if reply_markup is None:
        return []
    return [
        button.text
        for row in getattr(reply_markup, "inline_keyboard", [])
        for button in row
    ]


def test_question_keyboard_marks_selected_answer_with_product_check() -> None:
    chat_id = 52_002
    telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID[chat_id] = "owner-token"
    try:
        keyboard = telegram_app._question_keyboard(
            SimpleNamespace(options=("👨 Мужчина", "👩 Женщина")),
            selected_index=1,
            chat_id=chat_id,
            step_index=2,
        )
    finally:
        telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.pop(chat_id, None)

    assert _button_texts(keyboard)[:2] == ["👨 Мужчина", f"{telegram_app.SELECTED_ANSWER_PREFIX}👩 Женщина"]


def test_answer_callback_marks_selected_option_and_keeps_owner_token(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_id = 52_003
    message = EditableMessage(chat_id)
    session = telegram_app.QuestionnaireSession({"age": "32"}, step_index=1)
    telegram_app.SESSION_BY_CHAT_ID[chat_id] = session
    telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID[chat_id] = "owner-token"
    callback_data = telegram_app._question_answer_callback_data(
        1,
        chat_id=chat_id,
        step_index=session.step_index,
    )
    callback = FakeCallback(callback_data, message, user_id=chat_id)
    monkeypatch.setattr(telegram_app, "Message", EditableMessage)

    try:
        asyncio.run(telegram_app.handle_callback(callback))
    finally:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.pop(chat_id, None)

    assert callback.answers[-1][0] == "👩 Женщина"
    assert message.edited_reply_markups
    assert f"{telegram_app.SELECTED_ANSWER_PREFIX}👩 Женщина" in _button_texts(message.edited_reply_markups[-1])
    assert message.answers[-1][0] == QUESTIONS[2].prompt
