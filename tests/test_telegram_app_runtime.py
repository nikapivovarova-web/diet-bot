from __future__ import annotations

import json
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
        self.analytics_events: list[dict[str, object]] = []

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

    def record_analytics_event(self, **kwargs) -> object:
        self.analytics_events.append(dict(kwargs))
        return SimpleNamespace(id=len(self.analytics_events), **kwargs)


class FakeAnalyticsStore:
    def __init__(self) -> None:
        self.entitlements: dict[int, telegram_app.Entitlement] = {}
        self.attributions: dict[int, object] = {}
        self.analytics_events: list[dict[str, object]] = []

    def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
        return self.entitlements.get(user_id, telegram_app.Entitlement())

    def save_entitlement(
        self,
        user_id: int,
        entitlement: telegram_app.Entitlement,
    ) -> None:
        self.entitlements[user_id] = entitlement

    def load_profile_data(self, user_id: int) -> dict[str, object] | None:
        return None

    def get_user_attribution(self, user_id: int) -> object | None:
        return self.attributions.get(user_id)

    def set_user_attribution(
        self,
        user_id: int,
        *,
        source: str | None,
        campaign: str | None,
        referral: str | None,
    ) -> object:
        if user_id not in self.attributions:
            self.attributions[user_id] = SimpleNamespace(
                user_id=user_id,
                source=source,
                campaign=campaign,
                referral=referral,
            )
        return self.attributions[user_id]

    def record_analytics_event(self, **kwargs) -> object:
        self.analytics_events.append(dict(kwargs))
        return SimpleNamespace(id=len(self.analytics_events), **kwargs)


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


class FakeDiscountPaymentStore(FakePromoAdminStore):
    def __init__(
        self,
        *,
        discount_percent: int | None = 70,
        discount_amount: int | None = None,
        code: str | None = None,
        accepted: bool = True,
    ) -> None:
        promo_code = code or (
            f"ANNA{discount_percent}" if discount_percent is not None else "RUBFIX"
        )
        super().__init__(
            [
                telegram_app.PromoCodeDefinition(
                    code=promo_code,
                    kind=telegram_app.PromoCodeKind.DISCOUNT,
                    max_redemptions=10,
                    discount_percent=discount_percent,
                    discount_amount=discount_amount,
                )
            ]
        )
        self.accepted = accepted
        self.created_orders: list[dict[str, object]] = []
        self.invoice_links: list[tuple[str, str]] = []
        self.orders: list[telegram_app.PaymentOrder] = []
        self.analytics_events: list[dict[str, object]] = []

    def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
        return telegram_app.Entitlement()

    def save_entitlement(
        self,
        user_id: int,
        entitlement: telegram_app.Entitlement,
    ) -> None:
        pass

    def activate_promo_code(
        self,
        user_id: int,
        raw_code: str,
    ) -> telegram_app.PromoCodeActivation:
        return telegram_app.PromoCodeActivation(
            "not_access_code",
            telegram_app.normalize_promo_code(raw_code),
            user_id,
        )

    def create_or_reuse_pending_payment_order(
        self,
        *,
        user_id: int,
        delivery_chat_id: int | None,
        provider: telegram_app.PaymentProvider,
        product: telegram_app.PaymentProduct,
        amount: int,
        currency,
        promo_code: str | None = None,
        pricing_context: str | None = None,
    ):
        self.created_orders.append(
            {
                "user_id": user_id,
                "delivery_chat_id": delivery_chat_id,
                "provider": provider,
                "product": product,
                "amount": amount,
                "currency": currency,
                "promo_code": promo_code,
                "pricing_context": pricing_context,
            }
        )
        if not self.accepted:
            return SimpleNamespace(
                accepted=False,
                code=telegram_app.PaymentOrderCreationCode.PROMO_INVALID_DISCOUNT,
                order=None,
            )

        discount_amount = 0
        promo_code_id = None
        promo_code_hash = None
        promo_code_suffix = None
        if promo_code is not None:
            promo = self.get_promo_code(promo_code, active_only=True)
            assert promo is not None
            if promo.discount_percent is not None:
                discount_amount = amount * promo.discount_percent // 100
            else:
                discount_amount = promo.discount_amount or 0
            if discount_amount <= 0 or amount - discount_amount <= 0:
                return SimpleNamespace(
                    accepted=False,
                    code=telegram_app.PaymentOrderCreationCode.PROMO_INVALID_DISCOUNT,
                    order=None,
                )
            promo_code_id = 7
            promo_code_hash = "d" * 64
            promo_code_suffix = promo.code[-4:]

        order = telegram_app.PaymentOrder(
            order_id=f"order_{len(self.orders) + 1}",
            nonce=f"nonce_{len(self.orders) + 1}",
            user_id=user_id,
            delivery_chat_id=delivery_chat_id,
            provider=provider,
            product=product,
            amount=amount - discount_amount,
            currency=currency,
            list_amount=amount,
            discount_amount=discount_amount,
            promo_code_id=promo_code_id,
            promo_code_hash=promo_code_hash,
            promo_code_suffix=promo_code_suffix,
            metadata={"pricing_context": pricing_context} if pricing_context else {},
        )
        self.orders.append(order)
        return SimpleNamespace(
            accepted=True,
            code=telegram_app.PaymentOrderCreationCode.CREATED,
            order=order,
        )

    def mark_payment_order_invoice_link(
        self,
        order_id: str,
        invoice_link: str,
    ) -> None:
        self.invoice_links.append((order_id, invoice_link))

    def record_analytics_event(self, **kwargs) -> object:
        self.analytics_events.append(dict(kwargs))
        return SimpleNamespace(id=len(self.analytics_events), **kwargs)


@pytest.fixture(autouse=True)
def isolated_telegram_runtime_state(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", False, raising=False)
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
        51_017,
        51_018,
        51_019,
        51_020,
        51_021,
        51_022,
        51_023,
        51_024,
        51_025,
        51_026,
        51_027,
        51_028,
        51_029,
        51_030,
        51_031,
        51_032,
        51_033,
        51_034,
        51_035,
        51_036,
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
async def test_start_payload_stores_first_touch_attribution(monkeypatch) -> None:
    chat_id = 51_030
    store = FakeAnalyticsStore()

    async def no_welcome_photo(message) -> None:
        return None

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "_send_welcome_photo", no_welcome_photo)

    first_message = FakeMessage(chat_id, text="/start ig_ad_001")
    second_message = FakeMessage(chat_id, text="/start tt_ad_002")

    await telegram_app.start(first_message)
    await telegram_app.start(second_message)

    attribution = store.attributions[chat_id]
    assert attribution.source == "ig"
    assert attribution.campaign == "ig_ad_001"
    assert attribution.referral == "ig_ad_001"
    assert [event["event_name"] for event in store.analytics_events] == [
        "bot_start",
        "bot_start",
    ]
    assert store.analytics_events[0]["source"] == "ig"
    assert store.analytics_events[1]["source"] == "ig"
    assert first_message.texts
    assert second_message.texts


@pytest.mark.anyio
async def test_start_analytics_write_failure_does_not_break_handler(
    monkeypatch,
    caplog,
) -> None:
    chat_id = 51_031

    class FailingAnalyticsStore(FakeAnalyticsStore):
        def set_user_attribution(self, *args, **kwargs) -> object:
            raise RuntimeError("analytics attribution unavailable")

        def record_analytics_event(self, **kwargs) -> object:
            raise RuntimeError("analytics event unavailable")

    async def no_welcome_photo(message) -> None:
        return None

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", FailingAnalyticsStore())
    monkeypatch.setattr(telegram_app, "_send_welcome_photo", no_welcome_photo)
    caplog.set_level("WARNING", logger=telegram_app.__name__)

    message = FakeMessage(chat_id, text="/start ig_ad_001")
    await telegram_app.start(message)

    assert message.texts
    assert "analytics" in caplog.text.lower()


def test_analytics_properties_drop_sensitive_profile_and_payment_fields(
    monkeypatch,
) -> None:
    store = FakeAnalyticsStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)

    telegram_app._record_analytics_event(
        user_id=51_032,
        chat_id=51_032,
        event_name="questionnaire_completed",
        properties={
            "provider": "telegram_stars",
            "weight_kg": 70,
            "height_cm": 170,
            "medical_details": "hypertension",
            "raw_questionnaire_answers": {"goal": "fat_loss"},
            "nested": {
                "amount": 450,
                "telegram_payment_charge_id": "tg-secret",
            },
        },
    )

    properties = store.analytics_events[0]["properties_json"]
    assert properties == {
        "provider": "telegram_stars",
        "nested": {"amount": 450},
    }


@pytest.mark.anyio
async def test_payment_success_records_safe_analytics_properties(monkeypatch) -> None:
    chat_id = 51_033

    class FakePaymentSuccessStore(FakeAnalyticsStore):
        def apply_successful_payment(self, payment_input):
            order = telegram_app.PaymentOrder(
                order_id="order_analytics",
                nonce="nonce_analytics",
                user_id=chat_id,
                delivery_chat_id=chat_id,
                provider=telegram_app.PaymentProvider.YOOKASSA,
                product=telegram_app.PaymentProduct.SUBSCRIPTION_MONTH,
                amount=79_900,
                currency="RUB",
                list_amount=79_900,
                metadata={"pricing_context": "launch"},
            )
            return SimpleNamespace(processed=True, duplicate=False, order=order)

    store = FakePaymentSuccessStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(chat_id)
    message.successful_payment = SimpleNamespace(
        currency="RUB",
        total_amount=79_900,
        invoice_payload="diet:order:order_analytics:nonce_analytics",
        telegram_payment_charge_id="tg-secret",
        provider_payment_charge_id="provider-secret",
    )

    await telegram_app.handle_successful_payment(message)

    event = store.analytics_events[0]
    assert event["event_name"] == "payment_success"
    assert event["properties_json"] == {
        "provider": "yookassa",
        "product": "subscription_month",
        "amount": 79_900,
        "currency": "RUB",
        "pricing_context": "launch",
    }
    assert "charge" not in json.dumps(event["properties_json"])
    assert message.texts


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
            self.analytics_events: list[dict[str, object]] = []

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

        def record_analytics_event(self, **kwargs) -> object:
            self.analytics_events.append(dict(kwargs))
            return SimpleNamespace(id=len(self.analytics_events), **kwargs)

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
    assert replay_message.texts[-1] == (
        telegram_app._promo_code_retry_text(telegram_app.PROMO_CODE_ALREADY_USED_TEXT),
        None,
    )
    assert entitlement.subscription_period_end == first_end
    assert store.analytics_events[-1]["event_name"] == "promo_applied"
    assert store.analytics_events[-1]["properties_json"] == {
        "promo_kind": "monthly_access",
        "promo_code_suffix": "2026",
    }


def test_subscription_payment_keyboard_offers_promo_code_entry() -> None:
    keyboard = telegram_app._subscription_payment_keyboard()
    buttons = [
        button
        for row in keyboard.inline_keyboard
        for button in row
    ]

    promo_buttons = [
        button
        for button in buttons
        if button.text == telegram_app.PROMO_CODE_TEXT
    ]

    assert len(promo_buttons) == 1
    assert promo_buttons[0].callback_data == telegram_app.CALLBACK_PROMO_CODE


def test_subscription_payment_keyboard_hides_paid_buttons_when_public_payments_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", False, raising=False)

    keyboard = telegram_app._subscription_payment_keyboard()
    buttons = [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert buttons == [
        (telegram_app.PROMO_CODE_TEXT, telegram_app.CALLBACK_PROMO_CODE),
    ]
    assert all(
        callback
        not in {
            telegram_app.CALLBACK_PAY_RU_CARD,
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
        }
        for _, callback in buttons
    )


def test_subscription_payment_keyboard_shows_paid_buttons_when_public_payments_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)

    keyboard = telegram_app._subscription_payment_keyboard()
    buttons = [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert buttons == [
        (telegram_app.PAY_WITH_RU_CARD_TEXT, telegram_app.CALLBACK_PAY_RU_CARD),
        (
            telegram_app.PAY_WITH_TELEGRAM_STARS_TEXT,
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
        ),
        (telegram_app.PROMO_CODE_TEXT, telegram_app.CALLBACK_PROMO_CODE),
    ]


def test_subscription_payment_keyboard_distinguishes_stars_auto_renew_and_yookassa_one_time(
    monkeypatch,
) -> None:
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)

    keyboard = telegram_app._subscription_payment_keyboard(chat_id=51_024, user_id=51_024)
    buttons = [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert (
        "💳 Разовый доступ на 30 дней - 799 ₽",
        telegram_app.CALLBACK_PAY_RU_CARD,
    ) in buttons
    assert (
        "⭐ Подписка с автопродлением - 450 Stars",
        telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
    ) in buttons


def test_active_stars_auto_renew_keyboard_does_not_offer_second_stars_subscription(
    monkeypatch,
) -> None:
    chat_id = 51_025
    entitlement = telegram_app.Entitlement(
        subscription_period_end="2026-06-15T10:00:00+00:00",
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
    )

    class FakeEntitlementStore:
        def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
            return entitlement

        def save_entitlement(
            self,
            user_id: int,
            updated: telegram_app.Entitlement,
        ) -> None:
            pass

        def load_profile_data(self, chat_id: int) -> dict[str, object] | None:
            return None

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", FakeEntitlementStore())

    keyboard = telegram_app._subscription_payment_keyboard(chat_id=chat_id, user_id=chat_id)
    buttons = [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert all(
        callback != telegram_app.CALLBACK_PAY_TELEGRAM_STARS
        for _, callback in buttons
    )
    assert any(callback == telegram_app.CALLBACK_PAY_RU_CARD for _, callback in buttons)
    assert any(callback == telegram_app.CALLBACK_PROMO_CODE for _, callback in buttons)


def test_canceled_active_stars_subscription_keyboard_does_not_offer_second_stars_subscription(
    monkeypatch,
) -> None:
    chat_id = 51_025
    entitlement = telegram_app.Entitlement(
        subscription_period_end="2026-06-15T10:00:00+00:00",
        subscription_source="telegram_stars",
        auto_renew_status="canceled",
    )

    class FakeEntitlementStore:
        def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
            return entitlement

        def save_entitlement(
            self,
            user_id: int,
            updated: telegram_app.Entitlement,
        ) -> None:
            pass

        def load_profile_data(self, chat_id: int) -> dict[str, object] | None:
            return None

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", FakeEntitlementStore())

    keyboard = telegram_app._subscription_payment_keyboard(chat_id=chat_id, user_id=chat_id)
    buttons = [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert all(
        callback != telegram_app.CALLBACK_PAY_TELEGRAM_STARS
        for _, callback in buttons
    )
    assert any(callback == telegram_app.CALLBACK_PAY_RU_CARD for _, callback in buttons)
    assert any(callback == telegram_app.CALLBACK_PROMO_CODE for _, callback in buttons)


def test_subscription_payment_text_shows_production_prices_without_discount(
    monkeypatch,
) -> None:
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)

    text = telegram_app._subscription_payment_text(chat_id=51_026, user_id=51_026)

    assert f"{telegram_app.SUBSCRIPTION_PRICE_RUB} ₽" in text
    assert f"{telegram_app.SUBSCRIPTION_STARS_AMOUNT} Stars" in text
    assert "скид" not in text.lower()


def test_subscription_payment_text_describes_yookassa_as_one_time_and_stars_as_auto_renew(
    monkeypatch,
) -> None:
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)

    text = telegram_app._subscription_payment_text(chat_id=51_026, user_id=51_026)

    assert "Telegram Stars: автопродляемая подписка на месяц" in text
    assert "YooKassa: разовый доступ на 30 дней" in text


@pytest.mark.parametrize(
    ("source", "auto_renew_status", "expected", "forbidden"),
    [
        (
            "telegram_stars",
            "enabled",
            "Автопродление Telegram Stars включено. Следующее обновление периода: 15.06.2026",
            "Разовый доступ",
        ),
        (
            "telegram_stars",
            "unknown",
            "Статус автопродления Telegram Stars уточняется. Доступ действует до: 15.06.2026",
            "Следующее обновление",
        ),
        (
            "telegram_stars",
            "canceled",
            "Автопродление Telegram Stars отменено. Доступ действует до: 15.06.2026",
            "Следующее обновление",
        ),
        (
            "yookassa",
            "not_applicable",
            "Разовый доступ через YooKassa действует до: 15.06.2026",
            "автопродлен",
        ),
    ],
)
def test_subscriber_cabinet_uses_renewal_wording_only_for_stars_auto_renew(
    monkeypatch,
    source: str,
    auto_renew_status: str,
    expected: str,
    forbidden: str,
) -> None:
    chat_id = 51_031
    entitlement = telegram_app.Entitlement(
        subscription_period_end="2026-06-15T10:00:00+00:00",
        subscription_source=source,
        auto_renew_status=auto_renew_status,
        monthly_one_day_remaining=2,
        monthly_weekly_pdf_remaining=3,
    )

    class FakeEntitlementStore:
        def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
            return entitlement

        def save_entitlement(
            self,
            user_id: int,
            updated: telegram_app.Entitlement,
        ) -> None:
            pass

        def load_profile_data(self, chat_id: int) -> dict[str, object] | None:
            return None

    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", FakeEntitlementStore())

    text = telegram_app._subscriber_cabinet_text(chat_id)

    assert expected in text
    assert forbidden.lower() not in text.lower()


@pytest.mark.parametrize(
    ("entitlement", "expected_button", "expected_callback"),
    [
        (
            telegram_app.Entitlement(
                subscription_period_end="2026-06-15T10:00:00+00:00",
                subscription_source="telegram_stars",
                auto_renew_status="enabled",
                stars_subscription_charge_id="stars-sub-active",
            ),
            "Отключить автопродление",
            telegram_app.CALLBACK_STARS_AUTO_RENEW_CANCEL,
        ),
        (
            telegram_app.Entitlement(
                subscription_period_end="2026-06-15T10:00:00+00:00",
                subscription_source="telegram_stars",
                auto_renew_status="canceled",
                stars_subscription_charge_id="stars-sub-canceled",
            ),
            "Возобновить автопродление",
            telegram_app.CALLBACK_STARS_AUTO_RENEW_ENABLE,
        ),
    ],
)
def test_subscriber_cabinet_shows_stars_auto_renew_management_buttons(
    entitlement: telegram_app.Entitlement,
    expected_button: str,
    expected_callback: str,
) -> None:
    keyboard = telegram_app._subscriber_cabinet_keyboard(51_032, entitlement=entitlement)
    buttons = [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert (expected_button, expected_callback) in buttons


@pytest.mark.parametrize(
    "entitlement",
    [
        telegram_app.Entitlement(
            subscription_period_end="2026-06-15T10:00:00+00:00",
            subscription_source="telegram_stars",
            auto_renew_status="unknown",
            stars_subscription_charge_id="stars-sub-unknown",
        ),
        telegram_app.Entitlement(
            subscription_period_end="2026-06-15T10:00:00+00:00",
            subscription_source="telegram_stars",
            auto_renew_status="enabled",
            stars_subscription_charge_id=None,
        ),
        telegram_app.Entitlement(
            subscription_period_end="2026-06-15T10:00:00+00:00",
            subscription_source="yookassa",
            auto_renew_status="not_applicable",
        ),
        telegram_app.Entitlement(
            subscription_period_end="2026-06-15T10:00:00+00:00",
            subscription_source="promo",
            auto_renew_status="not_applicable",
        ),
        telegram_app.Entitlement(
            subscription_period_end="2026-06-15T10:00:00+00:00",
            subscription_source="admin",
            auto_renew_status="not_applicable",
        ),
        telegram_app.Entitlement(
            subscription_period_end="2026-06-15T10:00:00+00:00",
            subscription_source="legacy",
            auto_renew_status="unknown",
        ),
    ],
)
def test_subscriber_cabinet_hides_unsafe_or_non_stars_auto_renew_buttons(
    entitlement: telegram_app.Entitlement,
) -> None:
    keyboard = telegram_app._subscriber_cabinet_keyboard(51_032, entitlement=entitlement)
    buttons = [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert ("Отключить автопродление", telegram_app.CALLBACK_STARS_AUTO_RENEW_CANCEL) not in buttons
    assert ("Возобновить автопродление", telegram_app.CALLBACK_STARS_AUTO_RENEW_ENABLE) not in buttons


class FakeStarsAutoRenewStore:
    def __init__(self, entitlement: telegram_app.Entitlement) -> None:
        self.entitlement = entitlement
        self.saved: list[telegram_app.Entitlement] = []
        self.payment_reversal_inputs: list[telegram_app.PaymentReversalInput] = []
        self.analytics_events: list[dict[str, object]] = []

    def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
        return self.entitlement

    def save_entitlement(
        self,
        user_id: int,
        entitlement: telegram_app.Entitlement,
    ) -> None:
        self.entitlement = entitlement
        self.saved.append(telegram_app.Entitlement.from_dict(entitlement.to_dict()))

    def load_profile_data(self, chat_id: int) -> dict[str, object] | None:
        return None

    def apply_payment_reversal(
        self,
        reversal: telegram_app.PaymentReversalInput,
        *,
        now=None,
    ) -> object:
        self.payment_reversal_inputs.append(reversal)
        return SimpleNamespace(processed=True)

    def record_analytics_event(self, **kwargs) -> object:
        self.analytics_events.append(dict(kwargs))
        return SimpleNamespace(id=len(self.analytics_events), **kwargs)


class FakeStarsSubscriptionBot:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[int, str, bool]] = []

    async def edit_user_star_subscription(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        is_canceled: bool,
    ) -> bool:
        self.calls.append((user_id, telegram_payment_charge_id, is_canceled))
        if self.fail:
            raise telegram_app.TelegramAPIError(
                method=SimpleNamespace(),
                message="telegram unavailable",
            )
        return True


@pytest.mark.anyio
async def test_cancel_stars_auto_renew_calls_telegram_and_keeps_current_access(
    monkeypatch,
) -> None:
    chat_id = 51_033
    entitlement = telegram_app.Entitlement(
        subscription_period_start="2026-05-15T10:00:00+00:00",
        subscription_period_end="2026-06-15T10:00:00+00:00",
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
        stars_subscription_charge_id="stars-sub-cancel",
        monthly_one_day_remaining=2,
        monthly_weekly_pdf_remaining=3,
    )
    store = FakeStarsAutoRenewStore(entitlement)
    bot = FakeStarsSubscriptionBot()
    message = FakeMessage(chat_id)
    message.bot = bot
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)

    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_STARS_AUTO_RENEW_CANCEL, message)
    )

    updated = store.entitlement
    assert bot.calls == [(chat_id, "stars-sub-cancel", True)]
    assert updated.auto_renew_status == "canceled"
    assert updated.is_subscription_active(datetime(2026, 5, 16, 10, 0, tzinfo=UTC))
    assert updated.monthly_one_day_remaining == 2
    assert updated.monthly_weekly_pdf_remaining == 3
    assert store.payment_reversal_inputs[0].event_type == telegram_app.PaymentEventType.CANCEL_SUBSCRIPTION
    assert store.payment_reversal_inputs[0].telegram_charge_id == "stars-sub-cancel"
    assert store.analytics_events[-1]["event_name"] == "stars_auto_renew_canceled"
    assert store.analytics_events[-1]["properties_json"] == {
        "provider": "telegram_stars",
        "action": "cancel",
    }
    assert "отключено" in message.texts[-1][0].lower()


@pytest.mark.anyio
async def test_reenable_stars_auto_renew_calls_telegram_and_keeps_current_access(
    monkeypatch,
) -> None:
    chat_id = 51_034
    entitlement = telegram_app.Entitlement(
        subscription_period_start="2026-05-15T10:00:00+00:00",
        subscription_period_end="2026-06-15T10:00:00+00:00",
        subscription_source="telegram_stars",
        auto_renew_status="canceled",
        stars_subscription_charge_id="stars-sub-enable",
        monthly_one_day_remaining=1,
        monthly_weekly_pdf_remaining=2,
    )
    store = FakeStarsAutoRenewStore(entitlement)
    bot = FakeStarsSubscriptionBot()
    message = FakeMessage(chat_id)
    message.bot = bot
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)

    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_STARS_AUTO_RENEW_ENABLE, message)
    )

    updated = store.entitlement
    assert bot.calls == [(chat_id, "stars-sub-enable", False)]
    assert updated.auto_renew_status == "enabled"
    assert updated.is_subscription_active(datetime(2026, 5, 16, 10, 0, tzinfo=UTC))
    assert updated.monthly_one_day_remaining == 1
    assert updated.monthly_weekly_pdf_remaining == 2
    assert store.payment_reversal_inputs == []
    assert store.analytics_events[-1]["event_name"] == "stars_auto_renew_reenabled"
    assert store.analytics_events[-1]["properties_json"] == {
        "provider": "telegram_stars",
        "action": "reenable",
    }
    assert "включено" in message.texts[-1][0].lower()


@pytest.mark.anyio
async def test_stars_auto_renew_api_failure_does_not_mutate_local_status(
    monkeypatch,
) -> None:
    chat_id = 51_035
    entitlement = telegram_app.Entitlement(
        subscription_period_end="2026-06-15T10:00:00+00:00",
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
        stars_subscription_charge_id="stars-sub-failure",
        monthly_one_day_remaining=2,
        monthly_weekly_pdf_remaining=3,
    )
    before = entitlement.to_dict()
    store = FakeStarsAutoRenewStore(entitlement)
    bot = FakeStarsSubscriptionBot(fail=True)
    message = FakeMessage(chat_id)
    message.bot = bot
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)

    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_STARS_AUTO_RENEW_CANCEL, message)
    )

    assert bot.calls == [(chat_id, "stars-sub-failure", True)]
    assert store.entitlement.to_dict() == before
    assert store.saved == []
    assert store.payment_reversal_inputs == []
    assert "поддерж" in message.texts[-1][0].lower()


@pytest.mark.anyio
async def test_discount_promo_payment_screen_shows_discounted_amounts_after_entry(
    monkeypatch,
) -> None:
    chat_id = 51_026
    store = FakeDiscountPaymentStore(discount_percent=70)
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)

    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_PROMO_CODE, FakeMessage(chat_id))
    )
    input_message = FakeMessage(chat_id, text="anna70")
    await telegram_app.handle_answer(input_message)

    sent_text, markup = input_message.texts[-1]
    buttons = [
        (button.text, button.callback_data)
        for row in markup.inline_keyboard
        for button in row
    ]
    payment_text = telegram_app._subscription_payment_text(
        chat_id=chat_id,
        user_id=chat_id,
    )

    assert "70%" in sent_text
    assert "239.70 ₽" in sent_text
    assert "135 Stars" in sent_text
    assert "70%" in payment_text
    assert "239.70 ₽" in payment_text
    assert "135 Stars" in payment_text
    assert ("💳 Разовый доступ на 30 дней - 239.70 ₽", telegram_app.CALLBACK_PAY_RU_CARD) in buttons
    assert ("⭐ Подписка с автопродлением - 135 Stars", telegram_app.CALLBACK_PAY_TELEGRAM_STARS) in buttons


@pytest.mark.anyio
async def test_yookassa_only_discount_keeps_stars_button_full_price_with_notice(
    monkeypatch,
) -> None:
    chat_id = 51_029
    store = FakeDiscountPaymentStore(
        discount_percent=None,
        discount_amount=15_000,
        code="RUB150",
    )
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)

    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_PROMO_CODE, FakeMessage(chat_id))
    )
    input_message = FakeMessage(chat_id, text="rub150")
    await telegram_app.handle_answer(input_message)

    sent_text, markup = input_message.texts[-1]
    buttons = [
        (button.text, button.callback_data)
        for row in markup.inline_keyboard
        for button in row
    ]

    assert "150 ₽" in sent_text
    assert "Telegram Stars без скидки: 450 Stars." in sent_text
    assert ("💳 Разовый доступ на 30 дней - 649 ₽", telegram_app.CALLBACK_PAY_RU_CARD) in buttons
    assert (
        telegram_app.PAY_WITH_TELEGRAM_STARS_TEXT,
        telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
    ) in buttons


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("callback_data", "button_callback", "expected_display", "expected_amount"),
    [
        (telegram_app.CALLBACK_PAY_RU_CARD, telegram_app.CALLBACK_PAY_RU_CARD, "239.70 ₽", 23_970),
        (
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
            "135 Stars",
            135,
        ),
    ],
)
async def test_discount_promo_invoice_amount_matches_displayed_discounted_amount(
    monkeypatch,
    callback_data: str,
    button_callback: str,
    expected_display: str,
    expected_amount: int,
) -> None:
    chat_id = 51_027

    class FakeInvoiceBot:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create_invoice_link(self, **kwargs):
            self.calls.append(kwargs)
            return "https://invoice.test/discounted"

    store = FakeDiscountPaymentStore(discount_percent=70)
    bot = FakeInvoiceBot()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")

    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_PROMO_CODE, FakeMessage(chat_id))
    )
    input_message = FakeMessage(chat_id, text="anna70")
    await telegram_app.handle_answer(input_message)
    _, markup = input_message.texts[-1]
    display_button = next(
        button
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data == button_callback
    )

    payment_message = FakeMessage(chat_id)
    payment_message.bot = bot
    await telegram_app.handle_callback(FakeCallback(callback_data, payment_message))

    assert expected_display in display_button.text
    assert store.created_orders[0]["promo_code"] == "ANNA70"
    assert bot.calls[0]["prices"][0].amount == expected_amount
    assert expected_display in payment_message.texts[-1][0]
    assert chat_id not in telegram_app.DISCOUNT_PROMO_CODE_BY_CHAT_ID
    invoice_event = store.analytics_events[-1]
    assert invoice_event["event_name"] == "invoice_created"
    assert invoice_event["properties_json"]["product"] == "subscription_month"
    assert invoice_event["properties_json"]["amount"] == expected_amount
    assert "charge" not in json.dumps(invoice_event["properties_json"])


@pytest.mark.anyio
async def test_active_stars_auto_renew_direct_invoice_request_is_not_created(
    monkeypatch,
) -> None:
    chat_id = 51_030
    entitlement = telegram_app.Entitlement(
        subscription_period_end="2026-06-15T10:00:00+00:00",
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
    )

    class FakeInvoiceBot:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create_invoice_link(self, **kwargs):
            self.calls.append(kwargs)
            return "https://invoice.test/duplicate-stars"

    class FakeStarsStore:
        def __init__(self) -> None:
            self.created_orders: list[dict[str, object]] = []

        def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
            return entitlement

        def save_entitlement(
            self,
            user_id: int,
            updated: telegram_app.Entitlement,
        ) -> None:
            pass

        def create_or_reuse_pending_payment_order(
            self,
            **kwargs,
        ):
            self.created_orders.append(kwargs)
            return SimpleNamespace(
                accepted=True,
                code=telegram_app.PaymentOrderCreationCode.CREATED,
                order=telegram_app.PaymentOrder(
                    order_id="order_duplicate_stars",
                    nonce="nonce_duplicate_stars",
                    user_id=chat_id,
                    delivery_chat_id=chat_id,
                    provider=telegram_app.PaymentProvider.TELEGRAM_STARS,
                    product=telegram_app.PaymentProduct.SUBSCRIPTION_MONTH,
                    amount=telegram_app.SUBSCRIPTION_STARS_AMOUNT,
                    currency="XTR",
                    created_at=datetime(2026, 5, 16, 10, 0, tzinfo=UTC),
                    expires_at=datetime(2026, 5, 16, 10, 15, tzinfo=UTC),
                ),
            )

    store = FakeStarsStore()
    bot = FakeInvoiceBot()
    message = FakeMessage(chat_id)
    message.bot = bot
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)

    await telegram_app._send_stars_invoice_link(
        message,
        telegram_app.PAYLOAD_SUBSCRIPTION_MONTH,
        buyer_user_id=chat_id,
    )

    assert store.created_orders == []
    assert bot.calls == []
    assert "Telegram Stars" in message.texts[-1][0]
    assert "автопродление" in message.texts[-1][0].lower()


@pytest.mark.anyio
async def test_pending_discount_is_kept_when_order_creation_is_rejected(
    monkeypatch,
) -> None:
    chat_id = 51_028

    class FakeInvoiceBot:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create_invoice_link(self, **kwargs):
            self.calls.append(kwargs)
            return "https://invoice.test/rejected"

    store = FakeDiscountPaymentStore(discount_percent=70, accepted=False)
    bot = FakeInvoiceBot()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    telegram_app.DISCOUNT_PROMO_CODE_BY_CHAT_ID[chat_id] = "ANNA70"

    payment_message = FakeMessage(chat_id)
    payment_message.bot = bot
    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_PAY_RU_CARD, payment_message)
    )

    assert store.created_orders[0]["promo_code"] == "ANNA70"
    assert bot.calls == []
    assert telegram_app.DISCOUNT_PROMO_CODE_BY_CHAT_ID[chat_id] == "ANNA70"


def test_payment_test_price_gate_requires_public_flag_test_flag_and_tester_or_admin(
    monkeypatch,
) -> None:
    admin_user_id = 51_022
    tester_chat_id = 51_023
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", {tester_chat_id})

    assert telegram_app._payment_pricing_context_for_identity(
        user_id=admin_user_id,
        chat_id=900_001,
    ) == telegram_app.PAYMENT_TEST_SMOKE_PRICING_CONTEXT
    assert telegram_app._payment_pricing_context_for_identity(
        user_id=900_002,
        chat_id=tester_chat_id,
    ) == telegram_app.PAYMENT_TEST_SMOKE_PRICING_CONTEXT
    assert telegram_app._payment_pricing_context_for_identity(
        user_id=900_003,
        chat_id=900_003,
    ) is None

    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", False, raising=False)
    assert telegram_app._payment_pricing_context_for_identity(
        user_id=admin_user_id,
        chat_id=tester_chat_id,
    ) is None

    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", False, raising=False)
    assert telegram_app._payment_pricing_context_for_identity(
        user_id=admin_user_id,
        chat_id=tester_chat_id,
    ) is None


def test_subscription_payment_ui_shows_test_price_only_for_tester(
    monkeypatch,
) -> None:
    tester_chat_id = 51_023
    non_tester_chat_id = 900_003
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", set())
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", {tester_chat_id})

    tester_keyboard = telegram_app._subscription_payment_keyboard(
        chat_id=tester_chat_id,
        user_id=tester_chat_id,
    )
    non_tester_keyboard = telegram_app._subscription_payment_keyboard(
        chat_id=non_tester_chat_id,
        user_id=non_tester_chat_id,
    )
    tester_buttons = [
        (button.text, button.callback_data)
        for row in tester_keyboard.inline_keyboard
        for button in row
    ]
    non_tester_buttons = [
        (button.text, button.callback_data)
        for row in non_tester_keyboard.inline_keyboard
        for button in row
    ]

    assert tester_buttons[:2] == [
        (
            telegram_app.PAY_WITH_RU_CARD_TEST_TEXT,
            telegram_app.CALLBACK_PAY_RU_CARD,
        ),
        (
            telegram_app.PAY_WITH_TELEGRAM_STARS_TEST_TEXT,
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
        ),
    ]
    assert tester_buttons[0][0].startswith("[TEST]")
    assert tester_buttons[1][0].startswith("[TEST]")
    assert non_tester_buttons == [
        (telegram_app.PAY_WITH_RU_CARD_TEXT, telegram_app.CALLBACK_PAY_RU_CARD),
        (
            telegram_app.PAY_WITH_TELEGRAM_STARS_TEXT,
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
        ),
        (telegram_app.PROMO_CODE_TEXT, telegram_app.CALLBACK_PROMO_CODE),
    ]
    assert "[TEST]" in telegram_app._subscription_payment_text(
        chat_id=tester_chat_id,
        user_id=tester_chat_id,
    )
    assert "[TEST]" not in telegram_app._subscription_payment_text(
        chat_id=non_tester_chat_id,
        user_id=non_tester_chat_id,
    )


@pytest.mark.anyio
async def test_subscribe_callback_uses_actor_for_test_price_ui_when_message_author_is_bot(
    monkeypatch,
) -> None:
    admin_user_id = 51_022
    bot_user_id = 900_100
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", set())

    message = FakeMessage(admin_user_id, user_id=bot_user_id)
    await telegram_app.handle_callback(
        FakeCallback(
            telegram_app.CALLBACK_SUBSCRIBE,
            message,
            from_user_id=admin_user_id,
        )
    )

    sent_text, markup = message.texts[-1]
    buttons = [
        (button.text, button.callback_data)
        for row in markup.inline_keyboard
        for button in row
    ]

    assert "[TEST]" in sent_text
    assert buttons[:2] == [
        (
            telegram_app.PAY_WITH_RU_CARD_TEST_TEXT,
            telegram_app.CALLBACK_PAY_RU_CARD,
        ),
        (
            telegram_app.PAY_WITH_TELEGRAM_STARS_TEST_TEXT,
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
        ),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "callback_data",
    [
        telegram_app.CALLBACK_PAY_RU_CARD,
        telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
        telegram_app.CALLBACK_PAY_RU_EXTRA_ONE_DAY,
        telegram_app.CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF,
        telegram_app.CALLBACK_BUY_EXTRA_ONE_DAY,
        telegram_app.CALLBACK_BUY_EXTRA_WEEKLY_PDF,
    ],
)
async def test_public_payment_callbacks_show_pilot_promo_text_when_disabled(
    monkeypatch,
    callback_data: str,
) -> None:
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", False, raising=False)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    message = FakeMessage(51_021)

    await telegram_app.handle_callback(FakeCallback(callback_data, message))

    sent_text, markup = message.texts[-1]
    buttons = [
        (button.text, button.callback_data)
        for row in markup.inline_keyboard
        for button in row
    ]
    assert "промокод" in sent_text.lower()
    assert "пилот" in sent_text.lower()
    assert buttons == [
        (telegram_app.PROMO_CODE_TEXT, telegram_app.CALLBACK_PROMO_CODE),
    ]


def test_paywall_keyboard_keeps_extra_one_time_purchase_buttons(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)

    keyboard = telegram_app._paywall_keyboard(preferred="weekly_pdf")
    buttons = [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert (
        telegram_app.BUY_EXTRA_WEEKLY_PDF_RU_CARD_TEXT,
        telegram_app.CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF,
    ) in buttons
    assert (
        telegram_app.BUY_EXTRA_WEEKLY_PDF_TEXT,
        telegram_app.CALLBACK_BUY_EXTRA_WEEKLY_PDF,
    ) in buttons
    assert (
        telegram_app.BUY_EXTRA_ONE_DAY_RU_CARD_TEXT,
        telegram_app.CALLBACK_PAY_RU_EXTRA_ONE_DAY,
    ) in buttons
    assert (
        telegram_app.BUY_EXTRA_ONE_DAY_TEXT,
        telegram_app.CALLBACK_BUY_EXTRA_ONE_DAY,
    ) in buttons


@pytest.mark.anyio
async def test_limit_paywall_records_analytics_event(monkeypatch) -> None:
    chat_id = 51_036
    store = FakeAnalyticsStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)

    message = FakeMessage(chat_id)
    await telegram_app._send_limit_paywall(message, "one_day")

    assert message.texts
    event = store.analytics_events[-1]
    assert event["event_name"] == "paywall_shown"
    assert event["properties_json"] == {
        "ration_kind": "one_day",
        "has_active_subscription": False,
        "public_payments_enabled": True,
    }


@pytest.mark.anyio
async def test_public_payment_flag_does_not_expose_admin_payment_commands(
    monkeypatch,
) -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.commands: tuple[object, ...] = ()

        async def set_my_commands(self, commands) -> None:
            self.commands = tuple(commands)

    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", False, raising=False)
    bot = FakeBot()

    await telegram_app._set_bot_commands(bot)

    command_names = [command.command for command in bot.commands]
    assert "payment_event" not in command_names
    assert "330366" not in command_names


@pytest.mark.anyio
async def test_promo_code_button_monthly_access_flow_grants_access(
    monkeypatch,
) -> None:
    chat_id = 51_017

    class FakeMonthlyPromoStore:
        def __init__(self) -> None:
            self.entitlements: dict[int, telegram_app.Entitlement] = {}

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
            entitlement = self.get_entitlement(user_id)
            telegram_app.apply_monthly_access_promo_grant(
                entitlement,
                telegram_app.promo_code_grant_charge_id(raw_code),
            )
            self.save_entitlement(user_id, entitlement)
            return telegram_app.PromoCodeActivation("activated", raw_code, user_id)

    store = FakeMonthlyPromoStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    start_message = FakeMessage(chat_id)

    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_PROMO_CODE, start_message)
    )
    input_message = FakeMessage(chat_id, text="FB-USER-FLOW-2026")
    await telegram_app.handle_answer(input_message)

    entitlement = store.get_entitlement(chat_id)
    assert entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == telegram_app.MONTHLY_ONE_DAY_LIMIT
    assert entitlement.monthly_weekly_pdf_remaining == telegram_app.MONTHLY_WEEKLY_PDF_LIMIT
    assert chat_id not in telegram_app.PROMO_CODE_REQUEST_CHAT_IDS
    assert input_message.texts[-1][1].inline_keyboard[0][0].callback_data == (
        telegram_app.CALLBACK_ONE_DAY_PLAN
    )


@pytest.mark.anyio
async def test_invalid_promo_code_message_keeps_retry_state_and_mentions_cancel(
    monkeypatch,
) -> None:
    chat_id = 51_018

    def fake_activation(
        _chat_id: int,
        _promo_code: str,
    ) -> telegram_app.PromoCodeActivation:
        return telegram_app.PromoCodeActivation("not_found", "UNKNOWN")

    monkeypatch.setattr(telegram_app, "_activate_promo_code_for_chat", fake_activation)
    telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.add(chat_id)

    message = FakeMessage(chat_id, text="wrong-code")
    await telegram_app.handle_answer(message)

    assert chat_id in telegram_app.PROMO_CODE_REQUEST_CHAT_IDS
    assert "/cancel" in message.texts[-1][0]


@pytest.mark.anyio
async def test_discount_promo_code_applies_to_next_yookassa_invoice(
    monkeypatch,
) -> None:
    chat_id = 51_019

    class FakeInvoiceBot:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create_invoice_link(self, **kwargs):
            self.calls.append(kwargs)
            return "https://invoice.test/discounted"

    class FakeDiscountPaymentStore:
        def __init__(self) -> None:
            self.entitlements: dict[int, telegram_app.Entitlement] = {}
            self.created_orders: list[dict[str, object]] = []
            self.invoice_links: list[tuple[str, str]] = []

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
            return telegram_app.PromoCodeActivation(
                "not_access_code",
                telegram_app.normalize_promo_code(raw_code),
                user_id,
            )

        def get_promo_code(
            self,
            raw_code: str,
            *,
            active_only: bool = False,
            now=None,
        ) -> telegram_app.PromoCodeDefinition | None:
            code = telegram_app.normalize_promo_code(raw_code)
            if code != "ANNA20":
                return None
            promo = telegram_app.PromoCodeDefinition(
                code="ANNA20",
                kind=telegram_app.PromoCodeKind.DISCOUNT,
                max_redemptions=10,
                discount_percent=20,
            )
            return promo if not active_only or promo.is_active_at(now) else None

        def create_or_reuse_pending_payment_order(
            self,
            *,
            user_id: int,
            delivery_chat_id: int | None,
            provider: telegram_app.PaymentProvider,
            product: telegram_app.PaymentProduct,
            amount: int,
            currency,
            promo_code: str | None = None,
            pricing_context: str | None = None,
        ):
            discount_amount = 15_980
            self.created_orders.append(
                {
                    "user_id": user_id,
                    "delivery_chat_id": delivery_chat_id,
                    "provider": provider,
                    "product": product,
                    "amount": amount,
                    "currency": currency,
                    "promo_code": promo_code,
                    "pricing_context": pricing_context,
                }
            )
            order = telegram_app.PaymentOrder(
                order_id="order_discounted",
                nonce="nonce_discounted",
                user_id=user_id,
                delivery_chat_id=delivery_chat_id,
                provider=provider,
                product=product,
                amount=amount - discount_amount,
                currency=currency,
                list_amount=amount,
                discount_amount=discount_amount,
                promo_code_id=7,
                promo_code_hash="c" * 64,
                promo_code_suffix="NA20",
            )
            return SimpleNamespace(
                accepted=True,
                code=telegram_app.PaymentOrderCreationCode.CREATED,
                order=order,
            )

        def mark_payment_order_invoice_link(
            self,
            order_id: str,
            invoice_link: str,
        ) -> None:
            self.invoice_links.append((order_id, invoice_link))

    store = FakeDiscountPaymentStore()
    bot = FakeInvoiceBot()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")

    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_PROMO_CODE, FakeMessage(chat_id))
    )
    await telegram_app.handle_answer(FakeMessage(chat_id, text="anna20"))

    payment_message = FakeMessage(chat_id)
    payment_message.bot = bot
    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_PAY_RU_CARD, payment_message)
    )

    assert store.created_orders[0]["promo_code"] == "ANNA20"
    assert bot.calls[0]["prices"][0].amount == 63_920
    assert store.invoice_links == [("order_discounted", "https://invoice.test/discounted")]
    assert chat_id not in telegram_app.DISCOUNT_PROMO_CODE_BY_CHAT_ID


@pytest.mark.anyio
async def test_test_smoke_yookassa_invoice_uses_override_without_consuming_pending_discount(
    monkeypatch,
) -> None:
    chat_id = 51_023

    class FakeInvoiceBot:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create_invoice_link(self, **kwargs):
            self.calls.append(kwargs)
            return "https://invoice.test/smoke"

    class FakeTestPricePaymentStore:
        def __init__(self) -> None:
            self.created_orders: list[dict[str, object]] = []
            self.invoice_links: list[tuple[str, str]] = []

        def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
            return telegram_app.Entitlement()

        def save_entitlement(
            self,
            user_id: int,
            entitlement: telegram_app.Entitlement,
        ) -> None:
            pass

        def create_or_reuse_pending_payment_order(
            self,
            *,
            user_id: int,
            delivery_chat_id: int | None,
            provider: telegram_app.PaymentProvider,
            product: telegram_app.PaymentProduct,
            amount: int,
            currency,
            promo_code: str | None = None,
            pricing_context: str | None = None,
        ):
            self.created_orders.append(
                {
                    "user_id": user_id,
                    "delivery_chat_id": delivery_chat_id,
                    "provider": provider,
                    "product": product,
                    "amount": amount,
                    "currency": currency,
                    "promo_code": promo_code,
                    "pricing_context": pricing_context,
                }
            )
            order = telegram_app.PaymentOrder(
                order_id="order_smoke",
                nonce="nonce_smoke",
                user_id=user_id,
                delivery_chat_id=delivery_chat_id,
                provider=provider,
                product=product,
                amount=amount,
                currency=currency,
                list_amount=amount,
                metadata={"pricing_context": pricing_context} if pricing_context else {},
            )
            return SimpleNamespace(
                accepted=True,
                code=telegram_app.PaymentOrderCreationCode.CREATED,
                order=order,
            )

        def mark_payment_order_invoice_link(
            self,
            order_id: str,
            invoice_link: str,
        ) -> None:
            self.invoice_links.append((order_id, invoice_link))

    store = FakeTestPricePaymentStore()
    bot = FakeInvoiceBot()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", {chat_id})
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", set())
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    telegram_app.DISCOUNT_PROMO_CODE_BY_CHAT_ID[chat_id] = "ANNA20"

    tester_keyboard = telegram_app._subscription_payment_keyboard(
        chat_id=chat_id,
        user_id=chat_id,
    )
    tester_buttons = [
        (button.text, button.callback_data)
        for row in tester_keyboard.inline_keyboard
        for button in row
    ]
    tester_text = telegram_app._subscription_payment_text(
        chat_id=chat_id,
        user_id=chat_id,
    )
    assert tester_buttons[:2] == [
        (
            telegram_app.PAY_WITH_RU_CARD_TEST_TEXT,
            telegram_app.CALLBACK_PAY_RU_CARD,
        ),
        (
            telegram_app.PAY_WITH_TELEGRAM_STARS_TEST_TEXT,
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
        ),
    ]
    assert "[TEST]" in tester_text
    assert telegram_app.TEST_SUBSCRIPTION_PRICE_RUB == 100
    assert "100" in telegram_app.PAY_WITH_RU_CARD_TEST_TEXT
    assert "100" in tester_text
    assert "ANNA20" not in tester_text

    payment_message = FakeMessage(chat_id)
    payment_message.bot = bot
    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_PAY_RU_CARD, payment_message)
    )

    assert store.created_orders[0]["amount"] == 10_000
    assert store.created_orders[0]["promo_code"] is None
    assert store.created_orders[0]["pricing_context"] == (
        telegram_app.PAYMENT_TEST_SMOKE_PRICING_CONTEXT
    )
    assert bot.calls[0]["prices"][0].amount == 10_000
    provider_data = json.loads(str(bot.calls[0]["provider_data"]))
    assert provider_data["receipt"]["items"][0]["amount"] == {
        "value": "100.00",
        "currency": "RUB",
    }
    assert telegram_app.DISCOUNT_PROMO_CODE_BY_CHAT_ID[chat_id] == "ANNA20"
    assert store.invoice_links == [("order_smoke", "https://invoice.test/smoke")]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("callback_data", "expected_amount"),
    [
        (telegram_app.CALLBACK_PAY_TELEGRAM_STARS, 1),
        (telegram_app.CALLBACK_PAY_RU_CARD, 10_000),
    ],
)
async def test_admin_callback_actor_gets_test_price_when_message_author_is_bot(
    monkeypatch,
    callback_data: str,
    expected_amount: int,
) -> None:
    admin_user_id = 51_022
    bot_user_id = 900_100

    class FakeInvoiceBot:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create_invoice_link(self, **kwargs):
            self.calls.append(kwargs)
            return "https://invoice.test/admin-smoke"

    class FakePaymentStore:
        def __init__(self) -> None:
            self.created_orders: list[dict[str, object]] = []
            self.orders: list[telegram_app.PaymentOrder] = []

        def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
            return telegram_app.Entitlement()

        def save_entitlement(
            self,
            user_id: int,
            entitlement: telegram_app.Entitlement,
        ) -> None:
            pass

        def create_or_reuse_pending_payment_order(
            self,
            *,
            user_id: int,
            delivery_chat_id: int | None,
            provider: telegram_app.PaymentProvider,
            product: telegram_app.PaymentProduct,
            amount: int,
            currency,
            promo_code: str | None = None,
            pricing_context: str | None = None,
        ):
            order = telegram_app.PaymentOrder(
                order_id=f"order_{len(self.orders) + 1}",
                nonce="nonce_admin_smoke",
                user_id=user_id,
                delivery_chat_id=delivery_chat_id,
                provider=provider,
                product=product,
                amount=amount,
                currency=currency,
                list_amount=amount,
                metadata={"pricing_context": pricing_context} if pricing_context else {},
            )
            self.created_orders.append(
                {
                    "user_id": user_id,
                    "delivery_chat_id": delivery_chat_id,
                    "amount": amount,
                    "currency": currency,
                    "pricing_context": pricing_context,
                }
            )
            self.orders.append(order)
            return SimpleNamespace(
                accepted=True,
                code=telegram_app.PaymentOrderCreationCode.CREATED,
                order=order,
            )

    store = FakePaymentStore()
    bot = FakeInvoiceBot()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", set())
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")

    payment_message = FakeMessage(admin_user_id, user_id=bot_user_id)
    payment_message.bot = bot
    await telegram_app.handle_callback(
        FakeCallback(callback_data, payment_message, from_user_id=admin_user_id)
    )

    assert store.created_orders[0]["user_id"] == admin_user_id
    assert store.created_orders[0]["delivery_chat_id"] == admin_user_id
    assert store.created_orders[0]["amount"] == expected_amount
    assert store.created_orders[0]["pricing_context"] == (
        telegram_app.PAYMENT_TEST_SMOKE_PRICING_CONTEXT
    )
    assert store.orders[0].metadata["pricing_context"] == (
        telegram_app.PAYMENT_TEST_SMOKE_PRICING_CONTEXT
    )
    assert bot.calls[0]["prices"][0].amount == expected_amount


@pytest.mark.anyio
async def test_admin_callback_actor_gets_test_price_when_message_author_is_none(
    monkeypatch,
) -> None:
    admin_user_id = 51_022

    class FakeInvoiceBot:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create_invoice_link(self, **kwargs):
            self.calls.append(kwargs)
            return "https://invoice.test/admin-smoke"

    class FakePaymentStore:
        def __init__(self) -> None:
            self.orders: list[telegram_app.PaymentOrder] = []

        def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
            return telegram_app.Entitlement()

        def save_entitlement(
            self,
            user_id: int,
            entitlement: telegram_app.Entitlement,
        ) -> None:
            pass

        def create_or_reuse_pending_payment_order(
            self,
            *,
            user_id: int,
            delivery_chat_id: int | None,
            provider: telegram_app.PaymentProvider,
            product: telegram_app.PaymentProduct,
            amount: int,
            currency,
            promo_code: str | None = None,
            pricing_context: str | None = None,
        ):
            order = telegram_app.PaymentOrder(
                order_id="order_none_author",
                nonce="nonce_none_author",
                user_id=user_id,
                delivery_chat_id=delivery_chat_id,
                provider=provider,
                product=product,
                amount=amount,
                currency=currency,
                list_amount=amount,
                metadata={"pricing_context": pricing_context} if pricing_context else {},
            )
            self.orders.append(order)
            return SimpleNamespace(
                accepted=True,
                code=telegram_app.PaymentOrderCreationCode.CREATED,
                order=order,
            )

    store = FakePaymentStore()
    bot = FakeInvoiceBot()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_user_id})
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", set())

    payment_message = FakeMessage(admin_user_id)
    payment_message.from_user = None
    payment_message.bot = bot
    await telegram_app.handle_callback(
        FakeCallback(
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
            payment_message,
            from_user_id=admin_user_id,
        )
    )

    assert store.orders[0].user_id == admin_user_id
    assert store.orders[0].delivery_chat_id == admin_user_id
    assert store.orders[0].metadata["pricing_context"] == (
        telegram_app.PAYMENT_TEST_SMOKE_PRICING_CONTEXT
    )
    assert bot.calls[0]["prices"][0].amount == 1


@pytest.mark.anyio
async def test_non_admin_callback_actor_keeps_production_stars_amount(monkeypatch) -> None:
    non_admin_user_id = 51_024
    bot_user_id = 900_100

    class FakeInvoiceBot:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create_invoice_link(self, **kwargs):
            self.calls.append(kwargs)
            return "https://invoice.test/production"

    class FakePaymentStore:
        def __init__(self) -> None:
            self.created_orders: list[dict[str, object]] = []

        def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
            return telegram_app.Entitlement()

        def save_entitlement(
            self,
            user_id: int,
            entitlement: telegram_app.Entitlement,
        ) -> None:
            pass

        def create_or_reuse_pending_payment_order(
            self,
            *,
            user_id: int,
            delivery_chat_id: int | None,
            provider: telegram_app.PaymentProvider,
            product: telegram_app.PaymentProduct,
            amount: int,
            currency,
            promo_code: str | None = None,
            pricing_context: str | None = None,
        ):
            self.created_orders.append(
                {
                    "user_id": user_id,
                    "delivery_chat_id": delivery_chat_id,
                    "amount": amount,
                    "pricing_context": pricing_context,
                }
            )
            return SimpleNamespace(
                accepted=True,
                code=telegram_app.PaymentOrderCreationCode.CREATED,
                order=telegram_app.PaymentOrder(
                    order_id="order_production",
                    nonce="nonce_production",
                    user_id=user_id,
                    delivery_chat_id=delivery_chat_id,
                    provider=provider,
                    product=product,
                    amount=amount,
                    currency=currency,
                    list_amount=amount,
                ),
            )

    store = FakePaymentStore()
    bot = FakeInvoiceBot()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {51_022})
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", set())

    payment_message = FakeMessage(non_admin_user_id, user_id=bot_user_id)
    payment_message.bot = bot
    await telegram_app.handle_callback(
        FakeCallback(
            telegram_app.CALLBACK_PAY_TELEGRAM_STARS,
            payment_message,
            from_user_id=non_admin_user_id,
        )
    )

    assert store.created_orders[0]["user_id"] == non_admin_user_id
    assert store.created_orders[0]["delivery_chat_id"] == non_admin_user_id
    assert store.created_orders[0]["amount"] == telegram_app.SUBSCRIPTION_STARS_AMOUNT
    assert store.created_orders[0]["pricing_context"] is None
    assert bot.calls[0]["prices"][0].amount == telegram_app.SUBSCRIPTION_STARS_AMOUNT


@pytest.mark.anyio
async def test_json_storage_payment_smoke_reports_durable_store_required(monkeypatch) -> None:
    chat_id = 51_025
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)

    message = FakeMessage(chat_id)
    await telegram_app.handle_callback(
        FakeCallback(telegram_app.CALLBACK_PAY_TELEGRAM_STARS, message)
    )

    text = message.texts[-1][0]
    assert "unavailable" in text
    assert "durable payment storage" in text
    assert "DIET_BOT_DATABASE_URL" in text


@pytest.mark.anyio
async def test_cancel_exits_promo_input_without_deleting_saved_profile() -> None:
    chat_id = 51_020
    profile = profile_with()
    telegram_app.PROFILE_BY_CHAT_ID[chat_id] = profile
    telegram_app.PROMO_CODE_REQUEST_CHAT_IDS.add(chat_id)

    await telegram_app.cancel(FakeMessage(chat_id, text="/cancel"))

    assert chat_id not in telegram_app.PROMO_CODE_REQUEST_CHAT_IDS
    assert telegram_app.PROFILE_BY_CHAT_ID[chat_id] is profile


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
    assert store.analytics_events[-1]["event_name"] == "ration_delivered"
    assert store.analytics_events[-1]["properties_json"] == {
        "ration_kind": "one_day",
        "attempt_source": "test_access",
        "generation_id": 1,
    }


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
    assert store.analytics_events[-1]["event_name"] == "weekly_pdf_delivered"
    assert store.analytics_events[-1]["properties_json"] == {
        "ration_kind": "weekly_pdf",
        "attempt_source": "test_access",
        "generation_id": 1,
    }


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
        def __init__(self, dsn: str, **kwargs: object) -> None:
            events.append(f"store:{dsn}")
            assert kwargs["pool_max_size"] == 11

        def initialize(self) -> None:
            events.append("store.initialize")

        def close(self) -> None:
            events.append("store.close")

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
    monkeypatch.setenv("DIET_BOT_DB_POOL_MAX_SIZE", "11")
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
        "store.close",
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
