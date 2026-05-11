from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.telegram_app import handle_answer
from diet_bot.questionnaire import start_session


class FakeMessage:
    def __init__(
        self,
        chat_id=12345,
        *,
        text="",
        user_id=None,
        chat_type="private",
    ) -> None:
        self.chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.from_user = SimpleNamespace(
            id=chat_id if user_id is None else user_id,
            username=None,
            first_name=None,
            last_name=None,
            full_name="",
        )
        self.text = text
        self.texts = []
        self.reply_markup_edits = []

    async def answer(self, text, reply_markup=None):
        self.texts.append((text, reply_markup))
        return SimpleNamespace()

    async def edit_reply_markup(self, reply_markup=None) -> None:
        self.reply_markup_edits.append(reply_markup)


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage, *, from_user_id: int | None = None) -> None:
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(
            id=message.from_user.id if from_user_id is None else from_user_id,
            username=None,
            first_name=None,
            last_name=None,
            full_name="",
        )
        self.answers = []

    async def answer(self, text=None, show_alert=None) -> None:
        self.answers.append(text if show_alert is None else (text, show_alert))


@pytest.fixture(autouse=True)
def isolated_telegram_owner_state(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "CALLBACK_THROTTLE_SECONDS", 0.0)
    monkeypatch.setattr(telegram_app, "COMMAND_THROTTLE_SECONDS", 0.0)
    telegram_app.TELEGRAM_RATE_LIMITER.reset()
    telegram_app.INCOMING_THROTTLE.reset()
    touched_ids = {
        51_001,
        51_002,
        51_003,
        51_004,
        51_005,
        51_006,
        51_007,
        51_008,
        51_009,
        900_001,
    }
    for user_id in touched_ids:
        telegram_app.SESSION_BY_CHAT_ID.pop(user_id, None)
        telegram_app.PROFILE_BY_CHAT_ID.pop(user_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(user_id)
        telegram_app.SUPPORT_REQUEST_CHAT_IDS.discard(user_id)
        telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.discard(user_id)
    yield
    for user_id in touched_ids:
        telegram_app.SESSION_BY_CHAT_ID.pop(user_id, None)
        telegram_app.PROFILE_BY_CHAT_ID.pop(user_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(user_id)
        telegram_app.SUPPORT_REQUEST_CHAT_IDS.discard(user_id)
        telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.discard(user_id)
    telegram_app.TELEGRAM_RATE_LIMITER.reset()
    telegram_app.INCOMING_THROTTLE.reset()


@pytest.mark.anyio
async def test_callback_from_user_owns_questionnaire_state_when_bot_sent_message() -> None:
    owner_id = 51_001
    bot_id = 900_001
    message = FakeMessage(chat_id=owner_id, user_id=bot_id)
    callback = FakeCallback(telegram_app.CALLBACK_CONSENT_TRIAL, message, from_user_id=owner_id)

    await telegram_app.handle_callback(callback)

    assert callback.answers == [None]
    assert owner_id in telegram_app.SESSION_BY_CHAT_ID
    assert owner_id in telegram_app.TRIAL_CHAT_IDS
    assert bot_id not in telegram_app.SESSION_BY_CHAT_ID


@pytest.mark.anyio
async def test_callback_message_bot_author_does_not_become_promo_owner() -> None:
    owner_id = 51_003
    bot_id = 900_001
    message = FakeMessage(chat_id=owner_id, user_id=bot_id)
    callback = FakeCallback(telegram_app.CALLBACK_PROMO_CODE, message, from_user_id=owner_id)

    await telegram_app.handle_callback(callback)

    assert callback.answers == [None]
    assert owner_id in telegram_app.PROMO_CODE_REQUEST_CHAT_IDS
    assert bot_id not in telegram_app.PROMO_CODE_REQUEST_CHAT_IDS
    assert bot_id not in telegram_app.SESSION_BY_CHAT_ID


@pytest.mark.anyio
@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
async def test_group_callback_does_not_change_private_questionnaire_state(chat_type: str) -> None:
    owner_id = 51_004
    group_id = -100_510_004
    private_session = start_session()
    telegram_app.SESSION_BY_CHAT_ID[owner_id] = private_session
    message = FakeMessage(chat_id=group_id, user_id=owner_id, chat_type=chat_type)
    callback = FakeCallback(telegram_app.CALLBACK_CONSENT_TRIAL, message, from_user_id=owner_id)

    await telegram_app.handle_callback(callback)

    assert callback.answers == [(telegram_app.PRIVATE_CHAT_CALLBACK_TEXT, True)]
    assert telegram_app.SESSION_BY_CHAT_ID[owner_id] is private_session
    assert group_id not in telegram_app.SESSION_BY_CHAT_ID
    assert group_id not in telegram_app.PROFILE_BY_CHAT_ID


@pytest.mark.anyio
async def test_foreign_old_answer_callback_is_rejected_without_state_change() -> None:
    owner_id = 51_005
    foreign_user_id = 51_006
    bot_id = 900_001
    message = FakeMessage(chat_id=owner_id, user_id=bot_id)
    stale_callback = FakeCallback(
        f"{telegram_app.CALLBACK_ANSWER_PREFIX}old123:sex:0",
        message,
        from_user_id=foreign_user_id,
    )

    await telegram_app.handle_callback(stale_callback)

    assert stale_callback.answers == [(telegram_app.PRIVATE_CHAT_CALLBACK_TEXT, True)]
    assert message.reply_markup_edits == []
    assert bot_id not in telegram_app.SESSION_BY_CHAT_ID
    assert foreign_user_id not in telegram_app.SESSION_BY_CHAT_ID


@pytest.mark.anyio
async def test_myid_bot_mention_is_accepted_as_myid_command() -> None:
    message = FakeMessage(chat_id=51_007, text="/myid@FoodBalanceBot", user_id=51_008)

    await handle_answer(message)

    sent_text = message.texts[-1][0]
    assert "chat_id: 51007" in sent_text
    assert "user_id: 51008" in sent_text
    assert 900_001 not in telegram_app.SESSION_BY_CHAT_ID
