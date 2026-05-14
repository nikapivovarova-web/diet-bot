from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.questionnaire import start_session
from diet_bot.storage import RecipeHistoryItem


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
        self.recorded: list[tuple[int, tuple[RecipeHistoryItem, ...]]] = []
        self.recent_history: list[RecipeHistoryItem] = []
        self.chat_states: dict[int, dict[str, object]] = {}
        self.events: list[str] = []

    def load_chat_state(self, chat_id: int) -> dict[str, object]:
        return dict(self.chat_states.get(chat_id, {}))

    def save_chat_state(self, chat_id: int, state: dict[str, object]) -> None:
        self.chat_states[chat_id] = dict(state)

    def get_entitlement(self, user_id: int) -> object:
        return self.entitlement

    def save_entitlement(self, user_id: int, entitlement: object) -> None:
        self.entitlement = entitlement

    def consume_generation_attempt(self, user_id: int, ration_kind: str) -> object:
        self.consumed.append((user_id, ration_kind))
        self.events.append(f"consume:{ration_kind}")
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
        self.events.append(f"complete:{consumption.ration_kind}")

    def refund_generation_attempt(
        self,
        user_id: int,
        consumption: object,
        *,
        error_message: str | None = None,
    ) -> None:
        self.refunded.append((user_id, consumption.ration_kind, error_message))
        self.events.append(f"refund:{consumption.ration_kind}")

    def record_recipe_history(
        self,
        user_id: int,
        entries: list[RecipeHistoryItem] | tuple[RecipeHistoryItem, ...],
    ) -> None:
        self.recorded.append((user_id, tuple(entries)))
        ration_kind = entries[0].ration_kind if entries else "empty"
        self.events.append(f"record:{ration_kind}:{len(entries)}")

    def load_recent_recipe_history(
        self,
        user_id: int,
        *,
        since: datetime | None = None,
        limit: int = 400,
    ) -> list[RecipeHistoryItem]:
        self.events.append(f"load_history:{user_id}:{limit}")
        items = [
            item
            for item in self.recent_history
            if since is None or (item.generated_at is not None and item.generated_at >= since)
        ]
        return items[:limit]


class FakePromoAdminStore:
    def __init__(
        self,
        promos: list[telegram_app.PromoCodeDefinition] | None = None,
    ) -> None:
        self.promos: dict[str, telegram_app.PromoCodeDefinition] = {}
        self.disabled_codes: list[str] = []
        for promo in promos or []:
            self.promos[promo.code] = promo

    def create_promo_code(
        self,
        promo: telegram_app.PromoCodeDefinition,
    ) -> telegram_app.PromoCodeDefinition:
        definition = telegram_app.PromoCodeDefinition(**promo.to_dict())
        self.promos[definition.code] = definition
        return definition

    def get_promo_code(
        self,
        raw_code: str,
        *,
        active_only: bool = False,
        now=None,
    ) -> telegram_app.PromoCodeDefinition | None:
        code = telegram_app.normalize_promo_code(raw_code)
        promo = self.promos.get(code)
        if promo is None:
            return None
        if active_only and not promo.is_active_at(now):
            return None
        return promo

    def list_promo_codes(
        self,
        *,
        kind=None,
        active_only: bool = False,
        now=None,
    ) -> list[telegram_app.PromoCodeDefinition]:
        promos = list(self.promos.values())
        if kind is not None:
            promos = [promo for promo in promos if promo.kind == kind]
        if active_only:
            promos = [promo for promo in promos if promo.is_active_at(now)]
        return sorted(promos, key=lambda promo: promo.code)

    def disable_promo_code(
        self,
        raw_code: str,
        *,
        kind=None,
    ) -> telegram_app.PromoCodeDefinition | None:
        code = telegram_app.normalize_promo_code(raw_code)
        promo = self.promos.get(code)
        if promo is None or (kind is not None and promo.kind != kind):
            return None
        disabled = telegram_app.PromoCodeDefinition(
            **{**promo.to_dict(), "active": False}
        )
        self.promos[code] = disabled
        self.disabled_codes.append(code)
        return disabled


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
        51_007,
        51_008,
        51_009,
        51_010,
        51_011,
        51_012,
        51_013,
        51_014,
        51_015,
        51_016,
    }
    for chat_id in touched_ids:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.PROFILE_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        telegram_app.SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
        telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)
        telegram_app.DISCOUNT_PROMO_CODE_BY_CHAT_ID.pop(chat_id, None)
        getattr(telegram_app, "ADMIN_PROMO_ACTION_BY_CHAT_ID", {}).pop(chat_id, None)
    yield
    for chat_id in touched_ids:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.PROFILE_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        telegram_app.SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
        telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)
        telegram_app.DISCOUNT_PROMO_CODE_BY_CHAT_ID.pop(chat_id, None)
        getattr(telegram_app, "ADMIN_PROMO_ACTION_BY_CHAT_ID", {}).pop(chat_id, None)


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
async def test_admin_panel_contains_discount_management_buttons(monkeypatch) -> None:
    admin_user_id = 51_007
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    message = FakeMessage(admin_user_id, text="/330366", user_id=admin_user_id)

    await telegram_app.handle_answer(message)

    reply_markup = message.texts[-1][1]
    button_texts = [
        button.text
        for row in reply_markup.inline_keyboard
        for button in row
    ]
    assert button_texts == [
        "🎟 Создать код на месяц",
        "🏷 Создать/обновить скидку",
        "📋 Список скидок",
        "🚫 Отключить скидку",
    ]


@pytest.mark.anyio
async def test_non_admin_330366_does_not_show_admin_panel(monkeypatch) -> None:
    admin_user_id = 51_007
    non_admin_user_id = 51_016
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    message = FakeMessage(non_admin_user_id, text="/330366", user_id=non_admin_user_id)

    await telegram_app.handle_answer(message)

    assert message.texts
    assert message.texts[-1][0] != telegram_app.ADMIN_PROMO_PANEL_TEXT
    assert message.texts[-1][1] is None


@pytest.mark.anyio
async def test_admin_can_create_update_and_apply_discount_from_state_input(
    monkeypatch,
) -> None:
    admin_user_id = 51_008
    customer_id = 51_009
    store = FakePromoAdminStore()
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(admin_user_id, user_id=admin_user_id)

    callback = FakeCallback(
        "diet:admin:create_discount_promo",
        message,
        from_user_id=admin_user_id,
    )
    await telegram_app.handle_callback(callback)
    await telegram_app.handle_answer(
        FakeMessage(admin_user_id, text=" anna20 20 ", user_id=admin_user_id)
    )

    created = store.promos["ANNA20"]
    assert created.kind == telegram_app.PromoCodeKind.DISCOUNT
    assert created.active
    assert created.discount_percent == 20

    update_callback = FakeCallback(
        "diet:admin:create_discount_promo",
        message,
        from_user_id=admin_user_id,
    )
    await telegram_app.handle_callback(update_callback)
    update_message = FakeMessage(admin_user_id, text="anna20 30", user_id=admin_user_id)
    await telegram_app.handle_answer(update_message)

    updated = store.promos["ANNA20"]
    assert updated.active
    assert updated.discount_percent == 30
    assert "ANNA20" in update_message.texts[-1][0]
    assert "30%" in update_message.texts[-1][0]
    assert telegram_app._remember_discount_promo_code_for_chat(customer_id, "anna20")
    assert telegram_app._pending_discount_promo_code_for_order(
        customer_id,
        telegram_app.PaymentProduct.SUBSCRIPTION_MONTH,
    ) == "ANNA20"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "admin_text",
    ["", "ANNA20", "ANNA20 xx", "ANNA20 0", "ANNA20 100", "AN NA20 20"],
)
async def test_admin_discount_create_rejects_invalid_input(
    monkeypatch,
    admin_text: str,
) -> None:
    admin_user_id = 51_010
    store = FakePromoAdminStore()
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(admin_user_id, user_id=admin_user_id)
    callback = FakeCallback(
        "diet:admin:create_discount_promo",
        message,
        from_user_id=admin_user_id,
    )

    await telegram_app.handle_callback(callback)
    input_message = FakeMessage(admin_user_id, text=admin_text, user_id=admin_user_id)
    await telegram_app.handle_answer(input_message)

    assert store.promos == {}
    assert input_message.texts


@pytest.mark.anyio
@pytest.mark.parametrize(
    "callback_data",
    [
        "diet:admin:create_discount_promo",
        "diet:admin:list_discount_promos",
        "diet:admin:disable_discount_promo",
    ],
)
async def test_non_admin_cannot_trigger_admin_discount_callback_or_state(
    monkeypatch,
    callback_data: str,
) -> None:
    admin_user_id = 51_011
    non_admin_user_id = 51_012
    store = FakePromoAdminStore()
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    non_admin_message = FakeMessage(non_admin_user_id, user_id=non_admin_user_id)
    callback = FakeCallback(
        callback_data,
        non_admin_message,
        from_user_id=non_admin_user_id,
    )

    await telegram_app.handle_callback(callback)
    getattr(telegram_app, "ADMIN_PROMO_ACTION_BY_CHAT_ID", {})[
        non_admin_user_id
    ] = "create_discount"
    await telegram_app.handle_answer(
        FakeMessage(non_admin_user_id, text="BAD20 20", user_id=non_admin_user_id)
    )

    assert callback.answers == ["Command is available only to admins."]
    assert store.promos == {}


@pytest.mark.anyio
async def test_admin_discount_list_shows_active_discounts_only(monkeypatch) -> None:
    admin_user_id = 51_013
    store = FakePromoAdminStore(
        [
            telegram_app.PromoCodeDefinition(
                code="ANNA20",
                kind=telegram_app.PromoCodeKind.DISCOUNT,
                max_redemptions=10,
                per_user_limit=1,
                discount_percent=20,
                used_count=3,
                expires_at="2026-06-01T12:00:00+00:00",
            ),
            telegram_app.PromoCodeDefinition(
                code="OLD10",
                kind=telegram_app.PromoCodeKind.DISCOUNT,
                active=False,
                max_redemptions=10,
                discount_percent=10,
            ),
            telegram_app.PromoCodeDefinition(
                code="ACCESS1",
                kind=telegram_app.PromoCodeKind.MONTHLY_ACCESS,
                active=True,
            ),
        ]
    )
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(admin_user_id, user_id=admin_user_id)
    callback = FakeCallback(
        "diet:admin:list_discount_promos",
        message,
        from_user_id=admin_user_id,
    )

    await telegram_app.handle_callback(callback)

    response_text = message.texts[-1][0]
    assert "ANNA20" in response_text
    assert "20%" in response_text
    assert "3/10" in response_text
    assert "2026-06-01" in response_text
    assert "OLD10" not in response_text
    assert "ACCESS1" not in response_text


@pytest.mark.anyio
async def test_admin_discount_disable_deactivates_discount_and_rejects_monthly(
    monkeypatch,
) -> None:
    admin_user_id = 51_014
    store = FakePromoAdminStore(
        [
            telegram_app.PromoCodeDefinition(
                code="ANNA20",
                kind=telegram_app.PromoCodeKind.DISCOUNT,
                max_redemptions=10,
                discount_percent=20,
            ),
            telegram_app.PromoCodeDefinition(
                code="ACCESS1",
                kind=telegram_app.PromoCodeKind.MONTHLY_ACCESS,
            ),
        ]
    )
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(admin_user_id, user_id=admin_user_id)

    await telegram_app.handle_callback(
        FakeCallback(
            "diet:admin:disable_discount_promo",
            message,
            from_user_id=admin_user_id,
        )
    )
    disabled_message = FakeMessage(admin_user_id, text="anna20", user_id=admin_user_id)
    await telegram_app.handle_answer(disabled_message)

    assert not store.promos["ANNA20"].active
    assert store.disabled_codes == ["ANNA20"]
    assert "ANNA20" in disabled_message.texts[-1][0]

    await telegram_app.handle_callback(
        FakeCallback(
            "diet:admin:disable_discount_promo",
            message,
            from_user_id=admin_user_id,
        )
    )
    monthly_message = FakeMessage(admin_user_id, text="ACCESS1", user_id=admin_user_id)
    await telegram_app.handle_answer(monthly_message)

    assert store.promos["ACCESS1"].active
    assert store.disabled_codes == ["ANNA20"]
    assert "monthly_access" in monthly_message.texts[-1][0]


@pytest.mark.anyio
async def test_admin_monthly_access_button_still_creates_monthly_code(
    monkeypatch,
    tmp_path,
) -> None:
    admin_user_id = 51_015
    promo_path = tmp_path / "promo_codes.json"
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    message = FakeMessage(admin_user_id, user_id=admin_user_id)
    callback = FakeCallback(
        telegram_app.CALLBACK_ADMIN_CREATE_MONTHLY_ACCESS_CODE,
        message,
        from_user_id=admin_user_id,
    )

    await telegram_app.handle_callback(callback)

    promo_codes = telegram_app.load_promo_codes(promo_path)
    assert len(promo_codes) == 1
    assert next(iter(promo_codes.values())).is_monthly_access()
    assert "Access: 1 month." in message.texts[-1][0]


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


def _history_item(
    index: int,
    *,
    ration_kind: str,
    day_index: int | None = None,
    meal_index: int | None = None,
) -> RecipeHistoryItem:
    slot_index = index if meal_index is None else meal_index
    meal_slot = ["breakfast", "snack_1", "lunch", "snack_2", "dinner"][slot_index % 5]
    return RecipeHistoryItem(
        recipe_id=f"recipe-{index}",
        recipe_key=f"{meal_slot}:curated:recipe-{index}",
        meal_slot=meal_slot,
        ration_kind=ration_kind,  # type: ignore[arg-type]
        day_index=day_index,
        meal_index=slot_index,
    )


def _fake_week_plans(profile: telegram_app.UserProfile) -> tuple[telegram_app.MealPlan, ...]:
    targets = telegram_app.calculate_targets(profile)
    safety = telegram_app.evaluate_safety(profile)
    meal_count = max(3, min(5, profile.meal_count))
    slots = ["breakfast", "snack_1", "lunch", "snack_2", "dinner"]
    plans = []
    for day_index in range(7):
        meals = tuple(
            telegram_app.Meal(
                name=f"Meal {day_index}-{meal_index}",
                portions=(),
                recipe="Test recipe",
                recipe_id=f"week-{day_index}-{meal_index}",
                recipe_key=f"{slots[meal_index]}:curated:week-{day_index}-{meal_index}",
            )
            for meal_index in range(meal_count)
        )
        plans.append(telegram_app.MealPlan(meals, targets, safety))
    return tuple(plans)


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
async def test_successful_one_day_access_generation_records_recipe_history(monkeypatch) -> None:
    chat_id = 52_101
    store = FakeGenerationStore()
    message = FakeMessage(chat_id)

    async def fake_send_plan(*_args, recipe_history_entries=None, **_kwargs) -> bool:
        assert recipe_history_entries is not None
        recipe_history_entries.extend(
            [
                _history_item(0, ration_kind="one_day", meal_index=0),
                _history_item(1, ration_kind="one_day", meal_index=1),
            ]
        )
        return True

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "_send_plan", fake_send_plan)

    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    assert sent is True
    assert store.completed == [(chat_id, "one_day", None, None)]
    assert store.refunded == []
    assert len(store.recorded) == 1
    recorded_user_id, entries = store.recorded[0]
    assert recorded_user_id == chat_id
    assert [entry.recipe_id for entry in entries] == ["recipe-0", "recipe-1"]
    assert {entry.ration_kind for entry in entries} == {"one_day"}
    assert {entry.generation_id for entry in entries} == {1}
    assert store.events == ["consume:one_day", "complete:one_day", "record:one_day:2"]


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
async def test_successful_weekly_pdf_access_generation_records_35_recipe_history_entries(
    monkeypatch,
) -> None:
    chat_id = 52_102
    store = FakeGenerationStore()
    message = FakeMessage(chat_id)

    async def fake_send_week_plan(*_args, recipe_history_entries=None, **_kwargs) -> bool:
        assert recipe_history_entries is not None
        for day_index in range(7):
            for meal_index in range(5):
                recipe_history_entries.append(
                    _history_item(
                        day_index * 5 + meal_index,
                        ration_kind="weekly_pdf",
                        day_index=day_index,
                        meal_index=meal_index,
                    )
                )
        return True

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with(meal_count=5))

    assert sent is True
    assert store.completed == [(chat_id, "weekly_pdf", None, None)]
    assert store.refunded == []
    assert len(store.recorded) == 1
    recorded_user_id, entries = store.recorded[0]
    assert recorded_user_id == chat_id
    assert len(entries) == 35
    assert {entry.ration_kind for entry in entries} == {"weekly_pdf"}
    assert {entry.generation_id for entry in entries} == {1}
    assert [entry.day_index for entry in entries[:5]] == [0, 0, 0, 0, 0]
    assert [entry.meal_index for entry in entries[:5]] == [0, 1, 2, 3, 4]


@pytest.mark.anyio
async def test_weekly_pdf_generation_uses_structured_recent_history_from_runtime_store(
    monkeypatch,
) -> None:
    chat_id = 52_202
    store = FakeGenerationStore()
    store.recent_history = [
        RecipeHistoryItem(
            recipe_id="recent-breakfast",
            recipe_key="breakfast:curated:recent-breakfast",
            meal_slot="breakfast",
            ration_kind="weekly_pdf",
            generated_at=datetime.now(UTC),
        )
    ]
    message = FakeMessage(chat_id)
    profile = profile_with(meal_count=3)
    captured_avoids: list[tuple[set[str], set[str]]] = []

    def fake_build_week_plans(
        _profile,
        _seed,
        avoided_recipe_ids,
        avoided_recipe_keys,
    ):
        captured_avoids.append((set(avoided_recipe_ids), set(avoided_recipe_keys)))
        return _fake_week_plans(profile)

    async def fake_animate_week_pdf_status(*_args, **_kwargs) -> None:
        return None

    async def fake_send_week_pdf_document(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "_build_week_plans", fake_build_week_plans)
    monkeypatch.setattr(telegram_app, "_animate_week_pdf_status", fake_animate_week_pdf_status)
    monkeypatch.setattr(telegram_app, "_build_week_pdf_payload", lambda *_args: (b"%PDF", "week.pdf"))
    monkeypatch.setattr(telegram_app, "_send_week_pdf_document", fake_send_week_pdf_document)

    sent = await telegram_app._send_week_plan(message, profile, recipe_history_entries=[])

    assert sent is True
    assert captured_avoids[0] == (
        {"recent-breakfast"},
        {"breakfast:curated:recent-breakfast"},
    )


@pytest.mark.anyio
async def test_one_day_generation_uses_structured_recent_history_from_runtime_store(
    monkeypatch,
) -> None:
    chat_id = 52_201
    store = FakeGenerationStore()
    store.recent_history = [
        RecipeHistoryItem(
            recipe_id="recent-lunch",
            recipe_key="lunch:curated:recent-lunch",
            meal_slot="lunch",
            ration_kind="one_day",
            generated_at=datetime.now(UTC),
        )
    ]
    message = FakeMessage(chat_id)
    profile = profile_with(meal_count=3)
    captured_avoids: list[tuple[set[str], set[str]]] = []

    def fake_build_one_day_plan(
        _profile,
        *,
        avoided_recipe_ids,
        avoided_recipe_keys,
        **_kwargs,
    ):
        captured_avoids.append((set(avoided_recipe_ids), set(avoided_recipe_keys)))
        return telegram_app.MealPlan(
            (),
            telegram_app.calculate_targets(profile),
            telegram_app.evaluate_safety(profile),
        )

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "build_one_day_plan", fake_build_one_day_plan)

    sent = await telegram_app._send_plan(message, profile)

    assert sent is False
    assert captured_avoids == [
        ({"recent-lunch"}, {"lunch:curated:recent-lunch"}),
    ]


def test_recent_recipe_avoidance_without_store_or_history_is_empty(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")

    avoidance = telegram_app._load_recent_recipe_avoidance(52_203)

    assert avoidance.full_recipe_ids == frozenset()
    assert avoidance.full_recipe_keys == frozenset()


@pytest.mark.anyio
async def test_failed_one_day_access_generation_does_not_record_recipe_history(monkeypatch) -> None:
    chat_id = 52_103
    store = FakeGenerationStore()
    message = FakeMessage(chat_id)

    async def fake_send_plan(*_args, recipe_history_entries=None, **_kwargs) -> bool:
        if recipe_history_entries is not None:
            recipe_history_entries.append(_history_item(0, ration_kind="one_day"))
        return False

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "_send_plan", fake_send_plan)

    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    assert sent is False
    assert store.completed == []
    assert store.refunded == [(chat_id, "one_day", None)]
    assert store.recorded == []


@pytest.mark.anyio
async def test_failed_weekly_pdf_access_generation_does_not_record_recipe_history(monkeypatch) -> None:
    chat_id = 52_104
    store = FakeGenerationStore()
    message = FakeMessage(chat_id)

    async def fake_send_week_plan(*_args, recipe_history_entries=None, **_kwargs) -> bool:
        if recipe_history_entries is not None:
            recipe_history_entries.append(_history_item(0, ration_kind="weekly_pdf"))
        return False

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with(meal_count=5))

    assert sent is False
    assert store.completed == []
    assert store.refunded == [(chat_id, "weekly_pdf", None)]
    assert store.recorded == []


def test_successful_generation_history_json_recording_is_idempotent(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 52_105
    state_path = tmp_path / "history.json"
    consumption = telegram_app.AttemptConsumption(True, "one_day", "subscription")
    object.__setattr__(consumption, "_postgres_generation_id", 777)
    entry = _history_item(0, ration_kind="one_day")

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    monkeypatch.setattr(telegram_app, "STATE_FILE", state_path)

    telegram_app._record_successful_generation_history(chat_id, consumption, [entry])
    telegram_app._record_successful_generation_history(chat_id, consumption, [entry])

    stored = __import__("json").loads(state_path.read_text(encoding="utf-8"))
    chat_state = stored[str(chat_id)]
    assert len(chat_state["recipe_history"]) == 1
    assert chat_state["recipe_ids"] == ["recipe-0"]


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
