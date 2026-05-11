from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.domain import ActivityLevel, CookingTimePreference, Goal, Sex, UserProfile
from diet_bot.questionnaire import QUESTIONS


class FakeMessage:
    def __init__(self, chat_id: int = 120_001, *, text: str = "", user_id: int | None = None) -> None:
        self.chat = SimpleNamespace(id=chat_id, type="private")
        self.from_user = SimpleNamespace(
            id=chat_id if user_id is None else user_id,
            username=None,
            first_name=None,
            last_name=None,
            full_name="",
        )
        self.text = text
        self.bot = SimpleNamespace()
        self.texts = []
        self.photos = []
        self.reply_markup_edits = []

    async def answer(self, text, reply_markup=None):
        self.texts.append((text, reply_markup))
        return self

    async def answer_photo(self, **kwargs):
        self.photos.append(kwargs)
        return self

    async def edit_reply_markup(self, reply_markup=None):
        self.reply_markup_edits.append(reply_markup)
        return self


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage, *, from_user_id: int | None = None) -> None:
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(
            id=message.chat.id if from_user_id is None else from_user_id,
            username=None,
            first_name=None,
            last_name=None,
            full_name="",
        )
        self.answers = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append(text if show_alert is None else (text, show_alert))


@pytest.fixture(autouse=True)
def isolated_telegram_state(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", "")
    monkeypatch.setattr(telegram_app, "COMMAND_THROTTLE_SECONDS", 0.0)
    monkeypatch.setattr(telegram_app, "PLAN_THROTTLE_SECONDS", 0.0)
    monkeypatch.setattr(telegram_app, "CALLBACK_THROTTLE_SECONDS", 0.0)
    monkeypatch.setattr(telegram_app, "_remember_user_from_message", lambda message: None)
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    telegram_app.TELEGRAM_RATE_LIMITER.reset()
    telegram_app.INCOMING_THROTTLE.reset()
    yield
    telegram_app.SESSION_BY_CHAT_ID.clear()
    telegram_app.TRIAL_CHAT_IDS.clear()
    telegram_app.PROFILE_BY_CHAT_ID.clear()
    telegram_app.PLAN_COUNT_BY_CHAT_ID.clear()
    telegram_app.PLAN_SEED_OFFSET_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID.clear()
    telegram_app.SUPPORT_REQUEST_CHAT_IDS.clear()
    telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.clear()
    telegram_app.GENERATION_LOCKS_BY_CHAT_ID.clear()
    telegram_app.TELEGRAM_RATE_LIMITER.reset()
    telegram_app.INCOMING_THROTTLE.reset()


def test_production_support_privacy_pre_payment_smoke(monkeypatch) -> None:
    support_chat_id = -100_555_111_222
    privacy_url = "https://foodbalance.app/privacy"
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID_RAW", str(support_chat_id))
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID", support_chat_id)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", privacy_url)

    telegram_app.validate_runtime_config()

    for keyboard in [
        telegram_app._start_keyboard(),
        telegram_app._subscription_payment_keyboard(),
    ]:
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        assert any(button.callback_data == telegram_app.CALLBACK_SUPPORT for button in buttons)
        assert any(button.url == privacy_url for button in buttons)


@pytest.mark.anyio
async def test_new_user_start_consent_questionnaire_smoke(monkeypatch) -> None:
    chat_id = 120_101
    message = FakeMessage(chat_id, text="/start")
    generated_profiles = []

    async def fake_send_trial_plan(sent_message, profile):
        generated_profiles.append((sent_message.chat.id, profile))
        await sent_message.answer("fake trial plan")

    monkeypatch.setattr(telegram_app, "_send_trial_plan", fake_send_trial_plan)

    await telegram_app.start(message)
    await telegram_app.handle_callback(FakeCallback(telegram_app.CALLBACK_START, message))
    await telegram_app.handle_callback(FakeCallback(telegram_app.CALLBACK_CONSENT_TRIAL, message))

    assert telegram_app.SESSION_BY_CHAT_ID[chat_id].current_question == QUESTIONS[0]
    assert chat_id in telegram_app.TRIAL_CHAT_IDS
    assert message.texts[-1][0] == QUESTIONS[0].prompt

    for answer in [
        "32",
        QUESTIONS[1].options[0],
        "178",
        "86",
        QUESTIONS[4].options[0],
        QUESTIONS[5].options[2],
        "4",
        QUESTIONS[7].options[0],
        "нет",
        "нет",
        "нет",
        "нет",
    ]:
        await telegram_app.handle_answer(FakeMessage(chat_id, text=answer))

    assert chat_id not in telegram_app.SESSION_BY_CHAT_ID
    assert chat_id not in telegram_app.TRIAL_CHAT_IDS
    assert telegram_app.PROFILE_BY_CHAT_ID[chat_id].age == 32
    assert generated_profiles == [(chat_id, telegram_app.PROFILE_BY_CHAT_ID[chat_id])]


@pytest.mark.anyio
async def test_age_50_advances_to_who_are_you_question() -> None:
    chat_id = 120_102
    message = FakeMessage(chat_id)

    await telegram_app.handle_callback(FakeCallback(telegram_app.CALLBACK_START, message))
    await telegram_app.handle_callback(FakeCallback(telegram_app.CALLBACK_CONSENT_TRIAL, message))
    answer_message = FakeMessage(chat_id, text="50")
    await telegram_app.handle_answer(answer_message)

    session = telegram_app.SESSION_BY_CHAT_ID[chat_id]
    sent_text, markup = answer_message.texts[-1]

    assert session.current_question == QUESTIONS[1]
    assert session.current_question.key == "sex"
    assert sent_text == QUESTIONS[1].prompt
    assert markup.inline_keyboard[0][0].callback_data.endswith(":sex:0")


@pytest.mark.anyio
async def test_cancel_during_questionnaire_resets_session_without_profile() -> None:
    chat_id = 120_103
    message = FakeMessage(chat_id)

    await telegram_app.handle_callback(FakeCallback(telegram_app.CALLBACK_START, message))
    await telegram_app.handle_callback(FakeCallback(telegram_app.CALLBACK_CONSENT_TRIAL, message))
    await telegram_app.handle_answer(FakeMessage(chat_id, text="50"))

    assert chat_id in telegram_app.SESSION_BY_CHAT_ID
    await telegram_app.cancel(FakeMessage(chat_id, text="/cancel"))

    assert chat_id not in telegram_app.SESSION_BY_CHAT_ID
    assert chat_id not in telegram_app.TRIAL_CHAT_IDS
    assert chat_id not in telegram_app.PROFILE_BY_CHAT_ID


@pytest.mark.anyio
async def test_plan_with_ready_profile_shows_menu_without_questionnaire() -> None:
    chat_id = 120_104
    telegram_app.PROFILE_BY_CHAT_ID[chat_id] = _profile()
    message = FakeMessage(chat_id, text="/plan")

    await telegram_app.plan(message)

    sent_text, markup = message.texts[-1]
    buttons = [(row[0].text, row[0].callback_data) for row in markup.inline_keyboard]

    assert chat_id not in telegram_app.SESSION_BY_CHAT_ID
    assert "Ваш расчет" in sent_text
    assert buttons == [
        (telegram_app.ONE_DAY_PLAN_TEXT, telegram_app.CALLBACK_ONE_DAY_PLAN),
        (telegram_app.WEEK_PLAN_PDF_TEXT, telegram_app.CALLBACK_WEEK_PLAN_PDF),
        (telegram_app.CHANGE_PROFILE_TEXT, telegram_app.CALLBACK_NEW),
        (telegram_app.SUPPORT_TEXT, telegram_app.CALLBACK_SUPPORT),
    ]


def _profile() -> UserProfile:
    return UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=4,
        cooking_time=CookingTimePreference.QUICK,
    )
