from __future__ import annotations

from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.questionnaire import start_session


PRIVATE_CHAT_REQUIRED_TEXT = "Пожалуйста, откройте бота в личном чате, чтобы продолжить."
PRIVATE_CHAT_CALLBACK_TEXT = "Откройте бота в личном чате, чтобы использовать эту кнопку."


class FakeMessage:
    def __init__(
        self,
        chat_id: int = 12345,
        *,
        text: str = "",
        user_id: int | None = None,
        chat_type: str = "private",
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
        self.texts: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None):
        self.texts.append((text, reply_markup))
        return SimpleNamespace()


class FakeCallback:
    def __init__(
        self,
        data: str,
        message: FakeMessage,
        *,
        from_user_id: int | None = None,
    ) -> None:
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(
            id=message.chat.id if from_user_id is None else from_user_id,
            username=None,
            first_name=None,
            last_name=None,
            full_name="",
        )
        self.answers: list[object] = []

    async def answer(self, text=None, show_alert=None) -> None:
        self.answers.append(text if show_alert is None else (text, show_alert))


class FakeGenerationStore:
    def __init__(self) -> None:
        self.entitlement = telegram_app.Entitlement(
            free_trial_used=True,
            test_access_until="2099-01-01T00:00:00+00:00",
            test_access_enabled=True,
        )
        self.consumed: list[tuple[int, str]] = []
        self.completed: list[tuple[int, str, str | None, int | None]] = []
        self.refunded: list[tuple[int, str, str | None]] = []

    def get_entitlement(self, user_id: int) -> object:
        return self.entitlement

    def save_entitlement(self, user_id: int, entitlement: object) -> None:
        self.entitlement = entitlement

    def consume_generation_attempt(self, user_id: int, ration_kind: str) -> object:
        self.consumed.append((user_id, ration_kind))
        consumption = telegram_app.AttemptConsumption(True, ration_kind, "test_access")
        object.__setattr__(consumption, "_postgres_generation_id", len(self.consumed))
        return consumption

    def complete_generation_attempt(
        self,
        user_id: int,
        consumption: object,
        *,
        pdf_path: str | None = None,
        telegram_message_id: int | None = None,
    ) -> None:
        self.completed.append((user_id, consumption.ration_kind, pdf_path, telegram_message_id))

    def refund_generation_attempt(
        self,
        user_id: int,
        consumption: object,
        *,
        error_message: str | None = None,
    ) -> None:
        self.refunded.append((user_id, consumption.ration_kind, error_message))


@pytest.fixture(autouse=True)
def isolated_telegram_runtime_state(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    touched_ids = {
        -100_510_001,
        -100_510_002,
        -100_510_003,
        -100_510_004,
        51_001,
        51_002,
        51_003,
        51_004,
        51_005,
        51_006,
    }
    for chat_id in touched_ids:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.PROFILE_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        telegram_app.SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
        telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)
    yield
    for chat_id in touched_ids:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.PROFILE_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        telegram_app.SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
        telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_group_text_button_is_rejected_without_questionnaire_state() -> None:
    group_id = -100_510_001
    message = FakeMessage(
        group_id,
        text=telegram_app.TRY_FREE_TEXT,
        user_id=51_001,
        chat_type="supergroup",
    )

    await telegram_app.handle_answer(message)

    assert message.texts == [(PRIVATE_CHAT_REQUIRED_TEXT, None)]
    assert group_id not in telegram_app.SESSION_BY_CHAT_ID
    assert group_id not in telegram_app.TRIAL_CHAT_IDS


@pytest.mark.anyio
async def test_support_chat_flow_bypasses_private_chat_guard(monkeypatch) -> None:
    support_chat_id = -100_510_002
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID", support_chat_id)
    telegram_app.SUPPORT_REQUEST_CHAT_IDS.add(support_chat_id)
    telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.add(support_chat_id)
    message = FakeMessage(
        support_chat_id,
        text="support-side message",
        user_id=51_002,
        chat_type="supergroup",
    )

    await telegram_app.handle_answer(message)

    assert message.texts == []
    assert support_chat_id not in telegram_app.SUPPORT_REQUEST_CHAT_IDS
    assert support_chat_id not in telegram_app.PROMO_CODE_REQUEST_CHAT_IDS


@pytest.mark.anyio
async def test_admin_command_flow_bypasses_private_chat_guard(monkeypatch, tmp_path) -> None:
    admin_user_id = 51_003
    target_chat_id = 51_004
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    message = FakeMessage(
        -100_510_003,
        text=f"/330366 {target_chat_id}",
        user_id=admin_user_id,
        chat_type="supergroup",
    )

    await telegram_app.handle_answer(message)

    assert message.texts
    assert str(target_chat_id) in message.texts[-1][0]
    assert target_chat_id in telegram_app.load_entitlements(tmp_path / "subscriptions.json")


@pytest.mark.anyio
async def test_group_callback_does_not_change_private_questionnaire_state() -> None:
    owner_id = 51_004
    group_id = -100_510_004
    private_session = start_session()
    telegram_app.SESSION_BY_CHAT_ID[owner_id] = private_session
    message = FakeMessage(group_id, user_id=owner_id, chat_type="supergroup")
    callback = FakeCallback(telegram_app.CALLBACK_START, message, from_user_id=owner_id)

    await telegram_app.handle_callback(callback)

    assert callback.answers == [(PRIVATE_CHAT_CALLBACK_TEXT, True)]
    assert telegram_app.SESSION_BY_CHAT_ID[owner_id] is private_session
    assert group_id not in telegram_app.SESSION_BY_CHAT_ID
    assert group_id not in telegram_app.TRIAL_CHAT_IDS


@pytest.mark.anyio
async def test_foreign_private_callback_is_rejected_without_state_change() -> None:
    owner_id = 51_005
    foreign_user_id = 51_001
    message = FakeMessage(owner_id, user_id=owner_id)
    callback = FakeCallback(
        telegram_app.CALLBACK_PROMO_CODE,
        message,
        from_user_id=foreign_user_id,
    )

    await telegram_app.handle_callback(callback)

    assert callback.answers == [(PRIVATE_CHAT_CALLBACK_TEXT, True)]
    assert owner_id not in telegram_app.PROMO_CODE_REQUEST_CHAT_IDS
    assert foreign_user_id not in telegram_app.PROMO_CODE_REQUEST_CHAT_IDS


@pytest.mark.anyio
async def test_promo_code_runtime_store_activation_grants_access_and_rejects_replay(
    monkeypatch,
) -> None:
    chat_id = 51_006

    class FakePromoStore:
        def __init__(self) -> None:
            self.entitlements: dict[int, telegram_app.Entitlement] = {}
            self.redeemed_codes: set[str] = set()

        def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
            return self.entitlements.get(user_id, telegram_app.Entitlement())

        def save_entitlement(
            self,
            user_id: int,
            entitlement: telegram_app.Entitlement,
        ) -> None:
            self.entitlements[user_id] = entitlement

        def activate_promo_code(
            self,
            user_id: int,
            raw_code: str,
        ) -> telegram_app.PromoCodeActivation:
            if raw_code in self.redeemed_codes:
                return telegram_app.PromoCodeActivation("already_used", raw_code, user_id)
            entitlement = self.get_entitlement(user_id)
            telegram_app.apply_monthly_access_promo_grant(
                entitlement,
                telegram_app.promo_code_grant_charge_id(raw_code),
            )
            self.save_entitlement(user_id, entitlement)
            self.redeemed_codes.add(raw_code)
            return telegram_app.PromoCodeActivation("activated", raw_code, user_id)

    store = FakePromoStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)

    telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.add(chat_id)
    first_message = FakeMessage(chat_id, text="FB-RUNT-IMEE-2026")
    await telegram_app.handle_answer(first_message)
    first_end = store.get_entitlement(chat_id).subscription_period_end

    telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.add(chat_id)
    replay_message = FakeMessage(chat_id, text="FB-RUNT-IMEE-2026")
    await telegram_app.handle_answer(replay_message)

    entitlement = store.get_entitlement(chat_id)
    assert entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == telegram_app.MONTHLY_ONE_DAY_LIMIT
    assert entitlement.monthly_weekly_pdf_remaining == telegram_app.MONTHLY_WEEKLY_PDF_LIMIT
    assert first_message.texts[-1][1].inline_keyboard[0][0].callback_data == (
        telegram_app.CALLBACK_ONE_DAY_PLAN
    )
    assert replay_message.texts[-1] == (telegram_app.PROMO_CODE_ALREADY_USED_TEXT, None)
    assert entitlement.subscription_period_end == first_end


@pytest.mark.anyio
async def test_run_bot_rejects_blank_token_before_creating_bot(monkeypatch) -> None:
    created_tokens: list[str] = []

    class UnexpectedBot:
        def __init__(self, token: str) -> None:
            created_tokens.append(token)
            raise AssertionError("Bot must not be created without a real token")

    monkeypatch.setenv("DIET_BOT_TOKEN", "   ")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(telegram_app, "Bot", UnexpectedBot)

    with pytest.raises(RuntimeError, match="Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN."):
        await telegram_app.run_bot()

    assert created_tokens == []


def profile_with(**kwargs) -> object:
    data = {
        "age": 35,
        "sex": telegram_app.Sex.FEMALE,
        "height_cm": 170.0,
        "weight_kg": 70.0,
        "goal": telegram_app.Goal.MAINTAIN,
        "activity": telegram_app.ActivityLevel.LIGHT,
        "meal_count": 4,
        "cooking_time": telegram_app.CookingTimePreference.SIMPLE,
        "restrictions": (),
        "conditions": (),
        "allow_lactose_free_dairy": True,
        "allow_gluten_free_oats": False,
    }
    data.update(kwargs)
    return telegram_app.UserProfile(**data)


@pytest.mark.anyio
async def test_successful_one_day_access_generation_completes_postgres_lock(monkeypatch) -> None:
    chat_id = 52_001
    store = FakeGenerationStore()
    message = FakeMessage(chat_id)

    async def fake_send_plan(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "_send_plan", fake_send_plan)

    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    assert sent is True
    assert store.consumed == [(chat_id, "one_day")]
    assert store.completed == [(chat_id, "one_day", None, None)]
    assert store.refunded == []


@pytest.mark.anyio
async def test_successful_weekly_pdf_access_generation_completes_postgres_lock(monkeypatch) -> None:
    chat_id = 52_002
    store = FakeGenerationStore()
    message = FakeMessage(chat_id)

    async def fake_send_week_plan(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    assert sent is True
    assert store.consumed == [(chat_id, "weekly_pdf")]
    assert store.completed == [(chat_id, "weekly_pdf", None, None)]
    assert store.refunded == []


@pytest.mark.anyio
async def test_run_bot_initializes_store_before_polling_when_database_url_exists(
    monkeypatch,
) -> None:
    events: list[str] = []

    class FakeStore:
        def __init__(self, dsn: str, **_kwargs: object) -> None:
            events.append(f"store:{dsn}")

        def initialize(self) -> None:
            events.append("store.initialize")

    class FakeBot:
        def __init__(self, token: str) -> None:
            events.append(f"bot:{token}")

    class FakeDispatcher:
        async def start_polling(self, bot: FakeBot) -> None:
            events.append("polling")

    async def fake_set_bot_commands(bot: FakeBot) -> None:
        events.append("commands")

    monkeypatch.setenv("DIET_BOT_ENV", "development")
    monkeypatch.setenv("DIET_BOT_TOKEN", "local-token")
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://diet_bot@localhost:5432/diet_bot")
    monkeypatch.delenv("DIET_BOT_ALLOW_JSON_STORAGE", raising=False)
    monkeypatch.setattr(telegram_app, "PostgresDietBotStore", FakeStore)
    monkeypatch.setattr(telegram_app, "Bot", FakeBot)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_bot_commands)

    await telegram_app.run_bot()

    assert events == [
        "store:postgresql://diet_bot@localhost:5432/diet_bot",
        "store.initialize",
        "bot:local-token",
        "commands",
        "polling",
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("database_url", "expected_error"),
    [
        ("", "DIET_BOT_ALLOW_JSON_STORAGE=1"),
        ("not-a-postgres-url", "DIET_BOT_DATABASE_URL must be a PostgreSQL URL"),
    ],
)
async def test_run_bot_rejects_blank_or_invalid_storage_config_before_creating_bot(
    monkeypatch,
    database_url: str,
    expected_error: str,
) -> None:
    created_tokens: list[str] = []

    class UnexpectedBot:
        def __init__(self, token: str) -> None:
            created_tokens.append(token)
            raise AssertionError("Bot must not be constructed with invalid storage config")

    monkeypatch.setenv("DIET_BOT_ENV", "development")
    monkeypatch.setenv("DIET_BOT_TOKEN", "local-token")
    if database_url:
        monkeypatch.setenv("DIET_BOT_DATABASE_URL", database_url)
    else:
        monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DIET_BOT_ALLOW_JSON_STORAGE", raising=False)
    monkeypatch.setattr(telegram_app, "Bot", UnexpectedBot)

    with pytest.raises(RuntimeError, match=expected_error):
        await telegram_app.run_bot()

    assert created_tokens == []
