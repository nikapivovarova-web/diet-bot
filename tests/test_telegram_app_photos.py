import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.types import BufferedInputFile, FSInputFile

import diet_bot.telegram_app as telegram_app
from diet_bot.domain import (
    ActivityLevel,
    CookingTimePreference,
    Food,
    FoodPortion,
    Goal,
    Meal,
    MealPlan,
    NutrientVector,
    NutritionTargets,
    SafetyResult,
    Sex,
    UserProfile,
)
from diet_bot.payments import (
    PaymentCurrency,
    PaymentEvent,
    PaymentEventStatus,
    PaymentEventType,
    PaymentOrder,
    PaymentOrderCreationCode,
    PaymentOrderCreationResult,
    PaymentOrderStatus,
    PaymentProduct,
    PaymentProvider,
    PaymentReconciliationAction,
    PaymentReconciliationInput,
    PaymentReconciliationResult,
    PaymentReversalInput,
    PaymentReversalResult,
    PaymentSuccessfulPaymentInput,
    PaymentSuccessfulPaymentResult,
    ProcessedProviderCharge,
    apply_payment_reconciliation as apply_payment_reconciliation_core,
    apply_payment_reversal as apply_payment_reversal_core,
    apply_successful_payment as apply_successful_payment_core,
    create_or_reuse_pending_payment_order,
    decode_payment_order_payload,
    is_active_pending_payment_order,
)
from diet_bot.presentation import format_meal_card, format_week_shopping_list
from diet_bot.promo_codes import (
    PromoCodeActivation,
    PromoCodeDefinition,
    PromoCodeKind,
    PromoCodeRecord,
    calculate_discount_amount,
    load_promo_codes,
    normalize_promo_code,
    promo_code_audit_metadata,
    save_promo_codes,
)
from diet_bot.telegram_app import (
    BOT_COMMANDS,
    BUY_EXTRA_ONE_DAY_RU_CARD_TEXT,
    BUY_EXTRA_ONE_DAY_TEXT,
    BUY_EXTRA_WEEKLY_PDF_RU_CARD_TEXT,
    BUY_EXTRA_WEEKLY_PDF_TEXT,
    CALLBACK_BUY_EXTRA_ONE_DAY,
    CALLBACK_BUY_EXTRA_WEEKLY_PDF,
    CALLBACK_NEW,
    CALLBACK_ONE_DAY_PLAN,
    CALLBACK_FEATURES,
    CALLBACK_PAY_RU_CARD,
    CALLBACK_PAY_RU_EXTRA_ONE_DAY,
    CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF,
    CALLBACK_PAY_TELEGRAM_STARS,
    CALLBACK_PROMO_CODE,
    CALLBACK_START,
    CALLBACK_SUBSCRIBE,
    CALLBACK_SUPPORT,
    CALLBACK_WEEK_PLAN_PDF,
    CHANGE_PROFILE_TEXT,
    DATA_DIR,
    FEATURES_MESSAGE,
    FEATURES_TEXT,
    handle_answer,
    ONE_DAY_PLAN_TEXT,
    PAY_WITH_RU_CARD_TEXT,
    PAY_WITH_TELEGRAM_STARS_TEXT,
    PAYLOAD_EXTRA_ONE_DAY,
    PAYLOAD_SUBSCRIPTION_MONTH,
    PAYMENT_PAYLOAD_AMOUNTS,
    PLAN_COUNT_BY_CHAT_ID,
    PLAN_SEED_OFFSET_BY_CHAT_ID,
    PROMO_CODE_PROMPT_TEXT,
    PROMO_CODE_REQUEST_CHAT_IDS,
    PROMO_CODE_TEXT,
    PROFILE_BY_CHAT_ID,
    RECENT_RECIPE_IDS_BY_CHAT_ID,
    RECENT_RECIPE_KEYS_BY_CHAT_ID,
    SESSION_BY_CHAT_ID,
    SUBSCRIBE_CTA_TEXT,
    SUBSCRIBE_MONTH_TEXT,
    SUBSCRIBER_CABINET_TEXT,
    SUBSCRIBER_ONE_DAY_PLAN_TEXT,
    SUBSCRIBER_WEEK_PLAN_PDF_TEXT,
    SUBSCRIPTIONS_STATE_FILE,
    SUBSCRIPTION_PAYMENT_TEXT,
    SUBSCRIPTION_STARS_AMOUNT,
    SUPPORT_PROMPT_TEXT,
    SUPPORT_REQUEST_CHAT_IDS,
    SUPPORT_TEXT,
    TRIAL_CHAT_IDS,
    TRIAL_SUBSCRIPTION_TEXT,
    TRY_FREE_TEXT,
    WEEK_PLAN_PDF_PLACEHOLDER_TEXT,
    WEEK_PLAN_PDF_TEXT,
    WELCOME_PHOTO_PATH,
    WELCOME_TEXT,
    myid,
    secret_access_command,
    _consume_generation_attempt,
    _format_week_day_header,
    _format_entitlement_status,
    _apply_batch_carryovers,
    _handle_questionnaire_answer,
    _is_valid_pre_checkout,
    _main_menu_keyboard,
    _paywall_keyboard,
    _payment_result_keyboard,
    _photo_input,
    _plan_choice_keyboard,
    _profile_for_chat,
    _send_meal_card,
    _send_stars_invoice_link,
    _send_week_plan,
    _send_welcome_photo,
    _set_bot_commands,
    _start_keyboard,
    _subscriber_cabinet_keyboard,
    _subscription_payment_keyboard,
    _trial_subscription_keyboard,
    _week_plan_dates,
)
from diet_bot.questionnaire import start_session


@pytest.fixture(autouse=True)
def enabled_public_payment_buttons_for_legacy_telegram_tests(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", True, raising=False)


def test_photo_input_resolves_curated_local_photo() -> None:
    photo_path = next((DATA_DIR / "recipe_photos").glob("*.jpg"))
    meal = Meal(
        name="Test meal",
        portions=(),
        recipe="Test recipe",
        image_url=f"recipe_photos/{photo_path.name}",
    )

    photo = _photo_input(meal)

    assert isinstance(photo, FSInputFile)
    assert Path(photo.path) == photo_path


def test_photo_input_keeps_remote_url() -> None:
    meal = Meal(
        name="Test meal",
        portions=(),
        recipe="Test recipe",
        image_url="https://example.com/photo.jpg",
    )

    assert _photo_input(meal) == "https://example.com/photo.jpg"


def test_start_keyboard_has_welcome_buttons() -> None:
    keyboard = _start_keyboard()
    buttons = [row[0] for row in keyboard.inline_keyboard]

    assert [(button.text, button.callback_data) for button in buttons] == [
        (TRY_FREE_TEXT, CALLBACK_START),
        (SUBSCRIBE_MONTH_TEXT, CALLBACK_SUBSCRIBE),
        (FEATURES_TEXT, CALLBACK_FEATURES),
        (PROMO_CODE_TEXT, CALLBACK_PROMO_CODE),
        (SUPPORT_TEXT, CALLBACK_SUPPORT),
    ]
    assert "FoodBalance" in WELCOME_TEXT
    assert WELCOME_PHOTO_PATH.exists()


@pytest.mark.anyio
async def test_promo_code_button_asks_for_code(monkeypatch, tmp_path) -> None:
    chat_id = 80_201
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage(chat_id)
    callback = FakeCallback(CALLBACK_PROMO_CODE, message)
    try:
        await telegram_app.handle_callback(callback)

        assert callback.answers == [None]
        assert chat_id in PROMO_CODE_REQUEST_CHAT_IDS
        assert message.texts[-1] == (
            telegram_app._promo_code_retry_text(PROMO_CODE_PROMPT_TEXT),
            None,
        )
    finally:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_promo_code_activation_grants_monthly_subscription(monkeypatch, tmp_path) -> None:
    chat_id = 80_202
    promo_path = tmp_path / "promo_codes.json"
    subscriptions_path = tmp_path / "subscriptions.json"
    save_promo_codes(promo_path, {"FB-ABCD-EFGH-2345": PromoCodeRecord()})
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    try:
        await handle_answer(FakeMessage(chat_id, text=PROMO_CODE_TEXT))
        code_message = FakeMessage(chat_id, text="fb abcd efgh 2345")

        await handle_answer(code_message)

        sent_text, markup = code_message.texts[-1]
        entitlements = telegram_app.load_entitlements(subscriptions_path)
        entitlement = entitlements[chat_id]
        promo_codes = load_promo_codes(promo_path)

        assert chat_id not in PROMO_CODE_REQUEST_CHAT_IDS
        assert "Поздравляем! Промокод активирован." in sent_text
        assert "4 недельных PDF-рациона" in sent_text
        assert "5 дневных рационов" in sent_text
        assert "Рационы на 1 день: 5 из 5" in sent_text
        assert entitlement.is_subscription_active()
        assert entitlement.monthly_one_day_remaining == 5
        assert entitlement.monthly_weekly_pdf_remaining == 4
        assert promo_codes["FB-ABCD-EFGH-2345"].used_by_chat_id == chat_id
        assert markup.inline_keyboard[0][0].callback_data == CALLBACK_ONE_DAY_PLAN
    finally:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_promo_code_replay_is_rejected_without_extending(monkeypatch, tmp_path) -> None:
    chat_id = 80_203
    promo_path = tmp_path / "promo_codes.json"
    subscriptions_path = tmp_path / "subscriptions.json"
    save_promo_codes(promo_path, {"FB-ABCD-EFGH-2346": PromoCodeRecord()})
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    try:
        await handle_answer(FakeMessage(chat_id, text=PROMO_CODE_TEXT))
        first_message = FakeMessage(chat_id, text="FB-ABCD-EFGH-2346")
        await handle_answer(first_message)
        first_end = telegram_app.load_entitlements(subscriptions_path)[
            chat_id
        ].subscription_period_end

        await handle_answer(FakeMessage(chat_id, text=PROMO_CODE_TEXT))
        replay_message = FakeMessage(chat_id, text="FB-ABCD-EFGH-2346")
        await handle_answer(replay_message)

        entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
        assert replay_message.texts[-1] == (
            telegram_app._promo_code_retry_text(telegram_app.PROMO_CODE_ALREADY_USED_TEXT),
            None,
        )
        assert entitlement.subscription_period_end == first_end
    finally:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_promo_code_activation_rejects_non_redeemable_access_codes(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 80_204
    now = datetime.now(UTC)
    promo_path = tmp_path / "promo_codes.json"
    subscriptions_path = tmp_path / "subscriptions.json"
    cases = [
        (
            "FB-DISA-BLED-2026",
            PromoCodeRecord(active=False),
            telegram_app.PROMO_CODE_DISABLED_TEXT,
        ),
        (
            "FB-EXPI-REDX-2026",
            PromoCodeRecord(expires_at=(now - timedelta(seconds=1)).isoformat()),
            telegram_app.PROMO_CODE_EXPIRED_TEXT,
        ),
        (
            "FB-DISC-OUNT-2026",
            PromoCodeRecord.from_definition(
                PromoCodeDefinition(
                    code="FB-DISC-OUNT-2026",
                    kind=PromoCodeKind.DISCOUNT,
                    max_redemptions=5,
                    discount_percent=15,
                )
            ),
            telegram_app.PROMO_CODE_NOT_ACCESS_TEXT,
        ),
    ]
    save_promo_codes(promo_path, {code: record for code, record, _expected in cases})
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    try:
        for code, _record, expected_text in cases:
            PROMO_CODE_REQUEST_CHAT_IDS.add(chat_id)
            message = FakeMessage(chat_id, text=code)

            await handle_answer(message)

            assert message.texts[-1] == (
                telegram_app._promo_code_retry_text(expected_text),
                None,
            )
            assert chat_id not in telegram_app.load_entitlements(subscriptions_path)
            assert load_promo_codes(promo_path)[code].used_by_chat_id is None
    finally:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_promo_code_activation_extends_existing_monthly_access(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 80_205
    promo_path = tmp_path / "promo_codes.json"
    subscriptions_path = tmp_path / "subscriptions.json"
    code = "FB-ABCD-EFGH-2347"
    now = datetime.now(UTC)
    existing_end = now + timedelta(days=10)
    save_promo_codes(promo_path, {code: PromoCodeRecord()})
    telegram_app.save_entitlements(
        subscriptions_path,
        {
            chat_id: telegram_app.Entitlement(
                subscription_period_start=(now - timedelta(days=20)).isoformat(),
                subscription_period_end=existing_end.isoformat(),
                monthly_one_day_remaining=1,
                monthly_weekly_pdf_remaining=1,
            )
        },
    )
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    try:
        PROMO_CODE_REQUEST_CHAT_IDS.add(chat_id)
        code_message = FakeMessage(chat_id, text=code)

        await handle_answer(code_message)

        entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
        extended_end = datetime.fromisoformat(entitlement.subscription_period_end)
        assert extended_end >= existing_end + timedelta(
            seconds=telegram_app.SUBSCRIPTION_PERIOD_SECONDS - 2
        )
        assert entitlement.monthly_one_day_remaining == 5
        assert entitlement.monthly_weekly_pdf_remaining == 4
    finally:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_admin_secret_command_shows_hidden_promo_panel(monkeypatch) -> None:
    admin_id = 80_250
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    monkeypatch.setattr(
        telegram_app,
        "generate_promo_codes",
        lambda count, *, existing_codes=None: pytest.fail("panel must not create codes"),
        raising=False,
    )

    message = FakeMessage(admin_id, text="/330366", user_id=admin_id)
    await secret_access_command(message)

    sent_text, markup = message.texts[-1]
    button = markup.inline_keyboard[0][0]

    assert "Админ-панель" in sent_text
    assert (button.text, button.callback_data) == (
        "🎟 Создать код на месяц",
        "diet:admin:create_monthly_access_code",
    )


@pytest.mark.anyio
async def test_non_admin_secret_command_does_not_show_hidden_promo_panel(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {80_251})

    message = FakeMessage(80_252, text="/330366", user_id=80_252)
    await secret_access_command(message)

    sent_text, markup = message.texts[-1]

    assert "Админ-панель" not in sent_text
    assert markup is None


@pytest.mark.anyio
async def test_admin_promo_panel_button_creates_monthly_access_code(
    monkeypatch,
    tmp_path,
) -> None:
    admin_id = 80_253
    code = "FB-PANL-MNTH-2026"
    promo_path = tmp_path / "promo_codes.json"
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    monkeypatch.setattr(
        telegram_app,
        "generate_promo_codes",
        lambda count, *, existing_codes=None: [code],
        raising=False,
    )

    message = FakeMessage(admin_id, user_id=admin_id)
    callback = FakeCallback("diet:admin:create_monthly_access_code", message)
    await telegram_app.handle_callback(callback)

    response = message.texts[-1][0]
    created = load_promo_codes(promo_path)[code]

    assert callback.answers == [None]
    assert response.count(code) == 1
    assert "1 month" in response
    assert created.is_monthly_access()
    assert created.max_redemptions == 1
    assert created.per_user_limit == 1


@pytest.mark.anyio
async def test_non_admin_promo_panel_button_is_rejected_without_creating_code(
    monkeypatch,
    tmp_path,
) -> None:
    promo_path = tmp_path / "promo_codes.json"
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {80_254})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    monkeypatch.setattr(
        telegram_app,
        "generate_promo_codes",
        lambda count, *, existing_codes=None: pytest.fail("non-admin callback must not generate codes"),
        raising=False,
    )

    message = FakeMessage(80_255, user_id=80_255)
    callback = FakeCallback("diet:admin:create_monthly_access_code", message)
    await telegram_app.handle_callback(callback)

    assert callback.answers == ["Command is available only to admins."]
    assert message.texts == []
    assert load_promo_codes(promo_path) == {}


@pytest.mark.anyio
async def test_admin_code_command_creates_generated_monthly_access_code(
    monkeypatch,
    tmp_path,
) -> None:
    admin_id = 80_260
    user_id = 80_261
    code = "FB-7KQ9-MNT2-2026"
    promo_path = tmp_path / "promo_codes.json"
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    monkeypatch.setattr(
        telegram_app,
        "generate_promo_codes",
        lambda count, *, existing_codes=None: [code],
        raising=False,
    )

    admin_message = FakeMessage(admin_id, text="/330366 code", user_id=admin_id)
    await secret_access_command(admin_message)

    response = admin_message.texts[-1][0]
    promo_codes = load_promo_codes(promo_path)
    created = promo_codes[code]

    assert response.count(code) == 1
    assert "1 month" in response
    assert "monthly_access" not in response
    assert "storage" not in response.lower()
    assert created.is_monthly_access()
    assert created.active
    assert created.max_redemptions == 1
    assert created.per_user_limit == 1
    assert created.monthly_duration_months == 1

    try:
        await handle_answer(FakeMessage(user_id, text=PROMO_CODE_TEXT))
        activation_message = FakeMessage(user_id, text=code.lower().replace("-", " "))
        await handle_answer(activation_message)

        entitlement = telegram_app.load_entitlements(subscriptions_path)[user_id]
        reloaded = load_promo_codes(promo_path)

        assert entitlement.is_subscription_active()
        assert entitlement.monthly_one_day_remaining == telegram_app.MONTHLY_ONE_DAY_LIMIT
        assert entitlement.monthly_weekly_pdf_remaining == telegram_app.MONTHLY_WEEKLY_PDF_LIMIT
        assert reloaded[code].used_by_chat_id == user_id
    finally:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(user_id)


@pytest.mark.anyio
async def test_admin_code_command_skips_generated_collision(monkeypatch, tmp_path) -> None:
    admin_id = 80_262
    existing_code = "FB-DUPL-ICAT-2026"
    created_code = "FB-UNIQ-CODE-2026"
    promo_path = tmp_path / "promo_codes.json"
    generated = [existing_code, created_code]
    save_promo_codes(promo_path, {existing_code: PromoCodeRecord()})
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)

    def fake_generate_promo_codes(count, *, existing_codes=None):
        return [generated.pop(0)]

    monkeypatch.setattr(
        telegram_app,
        "generate_promo_codes",
        fake_generate_promo_codes,
        raising=False,
    )

    message = FakeMessage(admin_id, text="/330366 code", user_id=admin_id)
    await secret_access_command(message)

    promo_codes = load_promo_codes(promo_path)

    assert created_code in promo_codes
    assert existing_code in promo_codes
    assert message.texts[-1][0].count(created_code) == 1
    assert existing_code not in message.texts[-1][0]


@pytest.mark.anyio
async def test_non_admin_code_command_is_rejected_without_creating_code(
    monkeypatch,
    tmp_path,
) -> None:
    promo_path = tmp_path / "promo_codes.json"
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {80_263})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    monkeypatch.setattr(
        telegram_app,
        "generate_promo_codes",
        lambda count, *, existing_codes=None: pytest.fail("non-admin must not generate codes"),
        raising=False,
    )

    message = FakeMessage(80_264, text="/330366 code", user_id=80_264)
    await secret_access_command(message)

    assert message.texts
    assert load_promo_codes(promo_path) == {}


@pytest.mark.anyio
async def test_admin_code_command_does_not_accept_custom_code_argument(
    monkeypatch,
    tmp_path,
) -> None:
    admin_id = 80_265
    promo_path = tmp_path / "promo_codes.json"
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", None)
    monkeypatch.setattr(
        telegram_app,
        "generate_promo_codes",
        lambda count, *, existing_codes=None: pytest.fail("custom code args must not generate codes"),
        raising=False,
    )

    message = FakeMessage(admin_id, text="/330366 code MYCODE", user_id=admin_id)
    await secret_access_command(message)

    assert load_promo_codes(promo_path) == {}


@pytest.mark.anyio
async def test_features_button_sends_capabilities_text(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    message = FakeMessage(text=FEATURES_TEXT)

    await handle_answer(message)

    sent_text, markup = message.texts[-1]
    assert sent_text == FEATURES_MESSAGE
    assert "PDF" in sent_text
    assert "витамины и минералы" in sent_text
    assert markup is not None


@pytest.mark.anyio
async def test_support_callback_starts_request_mode(monkeypatch, tmp_path) -> None:
    chat_id = 80_101
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage(chat_id)
    callback = FakeCallback(CALLBACK_SUPPORT, message)
    try:
        await telegram_app.handle_callback(callback)

        assert callback.answers == [None]
        assert chat_id in SUPPORT_REQUEST_CHAT_IDS
        assert message.texts[-1] == (SUPPORT_PROMPT_TEXT, None)
    finally:
        SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_support_message_is_sent_to_admin_chat_with_context(monkeypatch, tmp_path) -> None:
    chat_id = 80_102
    support_chat_id = -100_555_111
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID", support_chat_id)
    _save_active_subscription(
        subscriptions_path,
        chat_id,
        one_day_remaining=2,
        weekly_pdf_remaining=1,
        extra_one_day_remaining=1,
    )
    PROFILE_BY_CHAT_ID[chat_id] = profile_with()
    SUPPORT_REQUEST_CHAT_IDS.add(chat_id)
    message = FakeMessage(
        chat_id,
        text="Не прошла оплата картой, деньги списались.",
        user_id=70_102,
        username="client102",
        first_name="Иван",
        last_name="Петров",
    )
    try:
        await handle_answer(message)

        assert chat_id not in SUPPORT_REQUEST_CHAT_IDS
        assert message.texts[-1][0].startswith("Обращение отправлено")
        assert message.texts[-1][1] is not None
        assert len(message.bot.sent_messages) == 1
        sent = message.bot.sent_messages[0]
        admin_text = sent["text"]
        assert sent["chat_id"] == support_chat_id
        assert "Не прошла оплата картой" in admin_text
        assert f"chat_id: {chat_id}" in admin_text
        assert "user_id: 70102" in admin_text
        assert "username: @client102" in admin_text
        assert "имя: Иван Петров" in admin_text
        assert "анкета: есть" in admin_text
        assert "Рационы на 1 день: 2 из 5" in admin_text
        assert "monthly_one_day_remaining: 2" in admin_text
        assert "extra_one_day_remaining: 1" in admin_text
    finally:
        SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


def test_support_admin_message_redacts_payment_sensitive_text_and_charge_ids(monkeypatch, tmp_path) -> None:
    chat_id = 80_104
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    telegram_app.save_entitlements(
        subscriptions_path,
        {
            chat_id: telegram_app.Entitlement(
                processed_payment_charge_ids=[
                    "telegram_stars:tg-charge-support-secret",
                    "provider-charge-support-secret",
                ],
            )
        },
    )
    message = FakeMessage(
        chat_id,
        user_id=70_104,
        username="client104",
        first_name="buyer@example.com",
        last_name="+79991234567",
    )
    admin_text = telegram_app._format_support_admin_message(
        message,
        (
            "email buyer@example.com phone +79991234567 order_info provider_data "
            "receipt customer bot 123456789:ABCdefGhijKLMnopQRStuVWXyz "
            "provider 381764678:TEST:provider-secret "
            "db postgresql://diet_bot:secret@example.com/db "
            "telegram_payment_charge_id=tg-charge-support-secret "
            "provider_payment_charge_id=provider-charge-support-secret"
        ),
    )

    for secret in (
        "buyer@example.com",
        "+79991234567",
        "order_info",
        "provider_data",
        "receipt",
        "customer",
        "123456789:ABCdefGhijKLMnopQRStuVWXyz",
        "381764678:TEST:provider-secret",
        "postgresql://diet_bot:secret@example.com/db",
        "tg-charge-support-secret",
        "provider-charge-support-secret",
        "processed_payment_charge_ids",
    ):
        assert secret not in admin_text


@pytest.mark.anyio
async def test_support_message_without_config_exits_support_mode(monkeypatch, tmp_path) -> None:
    chat_id = 80_103
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID", None)
    SUPPORT_REQUEST_CHAT_IDS.add(chat_id)
    message = FakeMessage(chat_id, text="Нужна помощь")
    try:
        await handle_answer(message)

        assert chat_id not in SUPPORT_REQUEST_CHAT_IDS
        assert message.bot.sent_messages == []
        assert "Техподдержка временно не настроена" in message.texts[-1][0]
        assert message.texts[-1][1] is not None
    finally:
        SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_support_chat_ignores_regular_messages(monkeypatch, tmp_path) -> None:
    support_chat_id = -5_271_779_108
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID", support_chat_id)
    SUPPORT_REQUEST_CHAT_IDS.add(support_chat_id)
    message = FakeMessage(support_chat_id, text="Коллеги, смотрим оплату")
    try:
        await handle_answer(message)

        assert message.texts == []
        assert support_chat_id not in SUPPORT_REQUEST_CHAT_IDS
    finally:
        SUPPORT_REQUEST_CHAT_IDS.discard(support_chat_id)


@pytest.mark.anyio
async def test_support_chat_ignores_product_commands_but_keeps_myid(monkeypatch, tmp_path) -> None:
    support_chat_id = -5_271_779_108
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID", support_chat_id)
    start_message = FakeMessage(support_chat_id, text="/start")
    myid_message = FakeMessage(support_chat_id, text="/myid", user_id=70_104)

    await telegram_app.start(start_message)
    await handle_answer(myid_message)

    assert start_message.texts == []
    assert start_message.photos == []
    assert "chat_id: -5271779108" in myid_message.texts[-1][0]
    assert "user_id: 70104" in myid_message.texts[-1][0]


def test_subscriber_cabinet_keyboard_shows_limits_without_upsells(monkeypatch, tmp_path) -> None:
    chat_id = 81_001
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _save_active_subscription(
        tmp_path / "subscriptions.json",
        chat_id,
        one_day_remaining=3,
        weekly_pdf_remaining=2,
        extra_one_day_remaining=1,
    )

    keyboard = _main_menu_keyboard(chat_id)
    buttons = [row[0] for row in keyboard.inline_keyboard]
    button_texts = [button.text for button in buttons]

    assert [(button.text, button.callback_data) for button in buttons] == [
        (f"{SUBSCRIBER_ONE_DAY_PLAN_TEXT} - осталось 3 из 5 + 1 доп.", CALLBACK_ONE_DAY_PLAN),
        (f"{SUBSCRIBER_WEEK_PLAN_PDF_TEXT} - осталось 2 из 4", CALLBACK_WEEK_PLAN_PDF),
        (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
        (SUPPORT_TEXT, CALLBACK_SUPPORT),
    ]
    assert TRY_FREE_TEXT not in button_texts
    assert SUBSCRIBE_MONTH_TEXT not in button_texts
    assert BUY_EXTRA_ONE_DAY_TEXT not in button_texts
    assert BUY_EXTRA_WEEKLY_PDF_TEXT not in button_texts


@pytest.mark.anyio
async def test_start_sends_subscriber_cabinet_instead_of_free_trial(monkeypatch, tmp_path) -> None:
    chat_id = 81_002
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _save_active_subscription(tmp_path / "subscriptions.json", chat_id, one_day_remaining=4, weekly_pdf_remaining=3)
    message = FakeMessage(chat_id)

    await telegram_app.start(message)

    sent_text, markup = message.texts[-1]
    buttons = [row[0] for row in markup.inline_keyboard]
    assert sent_text.startswith(SUBSCRIBER_CABINET_TEXT)
    assert "Рационы на 1 день: 4 из 5" in sent_text
    assert "Анкета: пока нет сохраненного отчета" in sent_text
    assert [(button.text, button.callback_data) for button in buttons] == [
        (f"{SUBSCRIBER_ONE_DAY_PLAN_TEXT} - осталось 4 из 5", CALLBACK_ONE_DAY_PLAN),
        (f"{SUBSCRIBER_WEEK_PLAN_PDF_TEXT} - осталось 3 из 4", CALLBACK_WEEK_PLAN_PDF),
        (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
        (SUPPORT_TEXT, CALLBACK_SUPPORT),
    ]


@pytest.mark.anyio
async def test_subscriber_cabinet_includes_profile_report(monkeypatch, tmp_path) -> None:
    chat_id = 81_004
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _save_active_subscription(tmp_path / "subscriptions.json", chat_id, one_day_remaining=4, weekly_pdf_remaining=3)
    PROFILE_BY_CHAT_ID[chat_id] = profile_with()
    message = FakeMessage(chat_id)
    try:
        await telegram_app.start(message)

        sent_text, _ = message.texts[-1]
        assert sent_text.startswith(SUBSCRIBER_CABINET_TEXT)
        assert "Ваш расчет" in sent_text
        assert "ИМТ (индекс массы тела)" in sent_text
        assert "Цель на день" in sent_text
    finally:
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


def test_subscription_payment_result_opens_subscriber_cabinet(monkeypatch, tmp_path) -> None:
    chat_id = 81_003
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _save_active_subscription(tmp_path / "subscriptions.json", chat_id, one_day_remaining=5, weekly_pdf_remaining=4)

    keyboard = _payment_result_keyboard(chat_id, telegram_app.PaymentApplication(True, "subscription"))
    buttons = [row[0] for row in keyboard.inline_keyboard]

    assert [(button.text, button.callback_data) for button in buttons] == [
        (f"{SUBSCRIBER_ONE_DAY_PLAN_TEXT} - осталось 5 из 5", CALLBACK_ONE_DAY_PLAN),
        (f"{SUBSCRIBER_WEEK_PLAN_PDF_TEXT} - осталось 4 из 4", CALLBACK_WEEK_PLAN_PDF),
        (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
        (SUPPORT_TEXT, CALLBACK_SUPPORT),
    ]


def test_subscription_payment_keyboard_has_monthly_options_only() -> None:
    keyboard = _subscription_payment_keyboard()
    buttons = [row[0] for row in keyboard.inline_keyboard]

    assert SUBSCRIPTION_STARS_AMOUNT == 400
    assert "599 ₽" in SUBSCRIPTION_PAYMENT_TEXT
    assert "400 Stars" in SUBSCRIPTION_PAYMENT_TEXT
    assert "4 недельных PDF-рациона" in SUBSCRIPTION_PAYMENT_TEXT
    assert "5 рационов на 1 день" in SUBSCRIPTION_PAYMENT_TEXT
    assert "Разовые покупки" not in SUBSCRIPTION_PAYMENT_TEXT
    assert "50 ₽" not in SUBSCRIPTION_PAYMENT_TEXT
    assert "250 ₽" not in SUBSCRIPTION_PAYMENT_TEXT
    assert "не является медицинской консультацией" in SUBSCRIPTION_PAYMENT_TEXT
    assert [(button.text, button.callback_data) for button in buttons] == [
        (PAY_WITH_RU_CARD_TEXT, CALLBACK_PAY_RU_CARD),
        (PAY_WITH_TELEGRAM_STARS_TEXT, CALLBACK_PAY_TELEGRAM_STARS),
        (PROMO_CODE_TEXT, CALLBACK_PROMO_CODE),
    ]


def test_paywall_keyboard_prioritizes_relevant_extra_purchase() -> None:
    day_keyboard = _paywall_keyboard(preferred="one_day")
    week_keyboard = _paywall_keyboard(preferred="weekly_pdf")

    assert (day_keyboard.inline_keyboard[0][0].text, day_keyboard.inline_keyboard[0][0].callback_data) == (
        BUY_EXTRA_ONE_DAY_RU_CARD_TEXT,
        CALLBACK_PAY_RU_EXTRA_ONE_DAY,
    )
    assert (day_keyboard.inline_keyboard[1][0].text, day_keyboard.inline_keyboard[1][0].callback_data) == (
        BUY_EXTRA_ONE_DAY_TEXT,
        CALLBACK_BUY_EXTRA_ONE_DAY,
    )
    assert (week_keyboard.inline_keyboard[0][0].text, week_keyboard.inline_keyboard[0][0].callback_data) == (
        BUY_EXTRA_WEEKLY_PDF_RU_CARD_TEXT,
        CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF,
    )
    assert (week_keyboard.inline_keyboard[1][0].text, week_keyboard.inline_keyboard[1][0].callback_data) == (
        BUY_EXTRA_WEEKLY_PDF_TEXT,
        CALLBACK_BUY_EXTRA_WEEKLY_PDF,
    )
    assert [(row[0].text, row[0].callback_data) for row in day_keyboard.inline_keyboard[2:]] == [
        (BUY_EXTRA_WEEKLY_PDF_RU_CARD_TEXT, CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF),
        (BUY_EXTRA_WEEKLY_PDF_TEXT, CALLBACK_BUY_EXTRA_WEEKLY_PDF),
    ]
    assert [(row[0].text, row[0].callback_data) for row in week_keyboard.inline_keyboard[2:]] == [
        (BUY_EXTRA_ONE_DAY_RU_CARD_TEXT, CALLBACK_PAY_RU_EXTRA_ONE_DAY),
        (BUY_EXTRA_ONE_DAY_TEXT, CALLBACK_BUY_EXTRA_ONE_DAY),
    ]


@pytest.mark.anyio
async def test_active_subscription_limit_paywall_offers_only_extra_purchases(monkeypatch, tmp_path) -> None:
    chat_id = 81_005
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _save_active_subscription(tmp_path / "subscriptions.json", chat_id, one_day_remaining=0, weekly_pdf_remaining=2)
    message = FakeMessage(chat_id)

    await telegram_app._send_limit_paywall(message, "one_day")

    sent_text, markup = message.texts[-1]
    buttons = [row[0] for row in markup.inline_keyboard]

    assert "Можно дождаться следующего обновления подписки или купить разовую попытку." in sent_text
    assert "Следующее обновление подписки" in sent_text
    assert (PAY_WITH_RU_CARD_TEXT, CALLBACK_PAY_RU_CARD) not in [
        (button.text, button.callback_data)
        for button in buttons
    ]
    assert (PAY_WITH_TELEGRAM_STARS_TEXT, CALLBACK_PAY_TELEGRAM_STARS) not in [
        (button.text, button.callback_data)
        for button in buttons
    ]
    assert [(button.text, button.callback_data) for button in buttons] == [
        (BUY_EXTRA_ONE_DAY_RU_CARD_TEXT, CALLBACK_PAY_RU_EXTRA_ONE_DAY),
        (BUY_EXTRA_ONE_DAY_TEXT, CALLBACK_BUY_EXTRA_ONE_DAY),
        (BUY_EXTRA_WEEKLY_PDF_RU_CARD_TEXT, CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF),
        (BUY_EXTRA_WEEKLY_PDF_TEXT, CALLBACK_BUY_EXTRA_WEEKLY_PDF),
    ]


@pytest.mark.anyio
async def test_free_limit_paywall_offers_monthly_access_only(monkeypatch, tmp_path) -> None:
    chat_id = 81_006
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    telegram_app.save_entitlements(subscriptions_path, {chat_id: telegram_app.Entitlement(free_trial_used=True)})
    message = FakeMessage(chat_id)

    await telegram_app._send_limit_paywall(message, "one_day")

    sent_text, markup = message.texts[-1]
    buttons = [row[0] for row in markup.inline_keyboard]

    assert "Чтобы продолжить, оформите месячный доступ." in sent_text
    assert "купить разовую попытку" not in sent_text
    assert [(button.text, button.callback_data) for button in buttons] == [
        (PAY_WITH_RU_CARD_TEXT, CALLBACK_PAY_RU_CARD),
        (PAY_WITH_TELEGRAM_STARS_TEXT, CALLBACK_PAY_TELEGRAM_STARS),
        (PROMO_CODE_TEXT, CALLBACK_PROMO_CODE),
    ]


@pytest.mark.anyio
async def test_pre_checkout_approves_valid_durable_order(monkeypatch) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(_pending_payment_order())
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    query = FakePreCheckoutQuery(
        invoice_payload=order.payload,
        user_id=order.user_id,
        currency=order.currency.value,
        total_amount=order.amount,
    )

    await telegram_app.handle_pre_checkout(query)

    approved_order = store.load_payment_order(order.order_id)
    assert query.answers == [{"ok": True, "error_message": None}]
    assert approved_order is not None
    assert approved_order.pre_checkout_approved_at is not None
    assert store.pre_checkout_approvals == [order.order_id]
    assert _is_valid_pre_checkout(query)


@pytest.mark.anyio
async def test_pre_checkout_rejects_static_legacy_payload(monkeypatch) -> None:
    store = FakePaymentStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    query = FakePreCheckoutQuery(
        invoice_payload=PAYLOAD_SUBSCRIPTION_MONTH,
        user_id=12345,
        currency="XTR",
        total_amount=PAYMENT_PAYLOAD_AMOUNTS[PAYLOAD_SUBSCRIPTION_MONTH],
    )

    await telegram_app.handle_pre_checkout(query)

    assert query.answers == [{"ok": False, "error_message": telegram_app.PAYMENT_PRE_CHECKOUT_FAILED_TEXT}]
    assert store.pre_checkout_approvals == []
    assert not _is_valid_pre_checkout(query)


@pytest.mark.anyio
async def test_pre_checkout_rejects_tampered_nonce(monkeypatch) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(_pending_payment_order())
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    query = FakePreCheckoutQuery(
        invoice_payload=f"diet:order:{order.order_id}:nonce_tampered",
        user_id=order.user_id,
        currency=order.currency.value,
        total_amount=order.amount,
    )

    await telegram_app.handle_pre_checkout(query)

    assert query.answers == [{"ok": False, "error_message": telegram_app.PAYMENT_PRE_CHECKOUT_FAILED_TEXT}]
    assert store.pre_checkout_approvals == []
    assert not _is_valid_pre_checkout(query)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("currency", "total_amount"),
    [
        ("RUB", 400),
        ("XTR", 399),
    ],
)
async def test_pre_checkout_rejects_wrong_amount_or_currency(
    monkeypatch,
    currency: str,
    total_amount: int,
) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(_pending_payment_order())
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    query = FakePreCheckoutQuery(
        invoice_payload=order.payload,
        user_id=order.user_id,
        currency=currency,
        total_amount=total_amount,
    )

    await telegram_app.handle_pre_checkout(query)

    assert query.answers == [{"ok": False, "error_message": telegram_app.PAYMENT_PRE_CHECKOUT_FAILED_TEXT}]
    assert store.pre_checkout_approvals == []
    assert not _is_valid_pre_checkout(query)


@pytest.mark.anyio
async def test_pre_checkout_rejects_expired_order(monkeypatch) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(
        _pending_payment_order(expires_at=datetime.now(UTC) - timedelta(seconds=1)),
    )
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    query = FakePreCheckoutQuery(
        invoice_payload=order.payload,
        user_id=order.user_id,
        currency=order.currency.value,
        total_amount=order.amount,
    )

    await telegram_app.handle_pre_checkout(query)

    expired_order = store.load_payment_order(order.order_id)
    assert query.answers == [{"ok": False, "error_message": telegram_app.PAYMENT_PRE_CHECKOUT_FAILED_TEXT}]
    assert expired_order is not None
    assert expired_order.status == PaymentOrderStatus.EXPIRED
    assert store.expired_order_ids == [order.order_id]
    assert store.pre_checkout_approvals == []


@pytest.mark.anyio
async def test_extra_pre_checkout_without_active_subscription_is_rejected(monkeypatch) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(
        _pending_payment_order(
            order_id="order_extra",
            nonce="nonce_extra",
            product=PaymentProduct.EXTRA_ONE_DAY,
            amount=35,
        ),
    )
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    query = FakePreCheckoutQuery(
        invoice_payload=order.payload,
        user_id=order.user_id,
        currency=order.currency.value,
        total_amount=order.amount,
    )

    await telegram_app.handle_pre_checkout(query)

    assert query.answers == [{"ok": False, "error_message": telegram_app.PAYMENT_PRE_CHECKOUT_FAILED_TEXT}]
    assert store.pre_checkout_approvals == []
    assert not _is_valid_pre_checkout(query)


@pytest.mark.anyio
async def test_pre_checkout_failure_message_is_safe(monkeypatch) -> None:
    store = SensitiveFailurePaymentStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    query = FakePreCheckoutQuery(
        invoice_payload="diet:order:order_secret:nonce_secret",
        user_id=12345,
        currency="XTR",
        total_amount=400,
    )

    await telegram_app.handle_pre_checkout(query)

    answer = query.answers[-1]
    message = answer["error_message"] or ""
    assert answer["ok"] is False
    for secret in (
        "postgresql://diet_bot:secret@example.com/db",
        "123456789:ABCdefGhijKLMnopQRStuVWXyz",
        "381764678:TEST:provider-secret",
        "diet:order:order_secret:nonce_secret",
        "order_secret",
        "nonce_secret",
    ):
        assert secret not in message


@pytest.mark.anyio
async def test_successful_payment_handler_grants_subscription_once_through_store(monkeypatch) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(_pending_payment_order())
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(order.delivery_chat_id, user_id=order.user_id)
    message.successful_payment = _successful_payment_for_order(
        order,
        telegram_charge_id="tg-charge-sub1",
    )

    await telegram_app.handle_successful_payment(message)

    entitlement = store.get_entitlement(order.user_id)
    received = store.successful_payment_inputs[0]
    assert entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == telegram_app.MONTHLY_ONE_DAY_LIMIT
    assert entitlement.monthly_weekly_pdf_remaining == telegram_app.MONTHLY_WEEKLY_PDF_LIMIT
    assert store.load_payment_order(order.order_id).status == PaymentOrderStatus.PAID
    assert store.processed_charge_ids() == ["tg-charge-sub1"]
    assert received.payload == order.payload
    assert received.provider == PaymentProvider.TELEGRAM_STARS
    assert received.telegram_charge_id == "tg-charge-sub1"
    assert received.provider_charge_id is None
    assert received.user_id == order.user_id
    assert received.delivery_chat_id == order.delivery_chat_id
    assert received.currency == PaymentCurrency.XTR
    assert received.total_amount == order.amount
    assert message.texts[-1][0].startswith(
        telegram_app._payment_success_text(
            telegram_app.PaymentApplication(True, "subscription"),
        ),
    )


@pytest.mark.anyio
async def test_duplicate_successful_payment_handler_does_not_grant_twice(monkeypatch) -> None:
    chat_id = 12345
    store = FakePaymentStore(entitlements={chat_id: _active_payment_entitlement()})
    order = store.insert_payment_order(
        _pending_payment_order(
            order_id="order_extra_day",
            nonce="nonce_extra_day",
            product=PaymentProduct.EXTRA_ONE_DAY,
            amount=35,
        ),
    )
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    first = FakeMessage(chat_id)
    first.successful_payment = _successful_payment_for_order(
        order,
        telegram_charge_id="tg-charge-extra1",
    )
    duplicate = FakeMessage(chat_id)
    duplicate.successful_payment = first.successful_payment

    await telegram_app.handle_successful_payment(first)
    await telegram_app.handle_successful_payment(duplicate)

    entitlement = store.get_entitlement(chat_id)
    assert entitlement.extra_one_day_remaining == 1
    assert store.processed_charge_ids() == ["tg-charge-extra1"]
    assert [event.status for event in store.payment_events] == [
        PaymentEventStatus.PROCESSED,
        PaymentEventStatus.DUPLICATE,
    ]
    assert duplicate.texts[-1][1] is not None


@pytest.mark.anyio
async def test_successful_payment_handler_rejects_tampered_payload_without_grant(monkeypatch) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(_pending_payment_order())
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(order.delivery_chat_id, user_id=order.user_id)
    message.successful_payment = _successful_payment_for_order(
        order,
        payload=f"diet:order:{order.order_id}:nonce_tampered",
        telegram_charge_id="tg-charge-tampered1",
    )

    await telegram_app.handle_successful_payment(message)

    assert not store.get_entitlement(order.user_id).is_subscription_active()
    assert store.load_payment_order(order.order_id).status == PaymentOrderStatus.PENDING
    assert store.processed_charge_ids() == []
    assert store.payment_events[-1].status == PaymentEventStatus.IGNORED_NON_TERMINAL
    assert message.texts[-1][0] == telegram_app.PAYMENT_SUCCESSFUL_PAYMENT_REJECTED_TEXT


@pytest.mark.anyio
async def test_orphan_successful_payment_handler_does_not_grant_and_returns_safe_message(monkeypatch) -> None:
    store = FakePaymentStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage()
    message.successful_payment = _successful_payment_for_order(
        _pending_payment_order(order_id="order_missing", nonce="nonce_missing"),
        telegram_charge_id="tg-charge-orphan1",
    )

    await telegram_app.handle_successful_payment(message)

    assert not store.get_entitlement(message.chat.id).is_subscription_active()
    assert store.processed_charge_ids() == []
    assert store.payment_events[-1].status == PaymentEventStatus.ORPHAN_RECOVERABLE
    assert message.texts[-1][0] == telegram_app.PAYMENT_SUCCESSFUL_PAYMENT_REJECTED_TEXT
    for secret in ("tg-charge-orphan1", "order_missing", "nonce_missing"):
        assert secret not in message.texts[-1][0]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("message_kwargs", "payment_kwargs"),
    [
        ({"user_id": 99999}, {}),
        ({"chat_id": 99999, "user_id": 12345}, {}),
        ({}, {"total_amount": 399}),
        ({}, {"currency": "RUB"}),
    ],
)
async def test_successful_payment_handler_rejects_wrong_user_chat_amount_or_currency(
    monkeypatch,
    message_kwargs: dict[str, int],
    payment_kwargs: dict[str, object],
) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(_pending_payment_order())
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(**message_kwargs)
    message.successful_payment = _successful_payment_for_order(
        order,
        telegram_charge_id="tg-charge-mismatch1",
        **payment_kwargs,
    )

    await telegram_app.handle_successful_payment(message)

    assert not store.get_entitlement(order.user_id).is_subscription_active()
    assert store.load_payment_order(order.order_id).status == PaymentOrderStatus.PENDING
    assert store.processed_charge_ids() == []
    assert store.payment_events[-1].status == PaymentEventStatus.IGNORED_NON_TERMINAL


@pytest.mark.anyio
async def test_extra_successful_payment_handler_grants_only_with_active_subscription(monkeypatch) -> None:
    chat_id = 12345
    store = FakePaymentStore(entitlements={chat_id: _active_payment_entitlement()})
    order = store.insert_payment_order(
        _pending_payment_order(
            order_id="order_extra_active",
            nonce="nonce_extra_active",
            product=PaymentProduct.EXTRA_WEEKLY_PDF,
            amount=170,
        ),
    )
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(chat_id)
    message.successful_payment = _successful_payment_for_order(
        order,
        telegram_charge_id="tg-charge-weekly-extra1",
        total_amount=170,
    )

    await telegram_app.handle_successful_payment(message)

    entitlement = store.get_entitlement(chat_id)
    assert entitlement.extra_weekly_pdf_remaining == 1
    assert store.load_payment_order(order.order_id).status == PaymentOrderStatus.PAID
    assert store.processed_charge_ids() == ["tg-charge-weekly-extra1"]


@pytest.mark.anyio
async def test_extra_successful_payment_handler_without_active_subscription_does_not_grant(monkeypatch) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(
        _pending_payment_order(
            order_id="order_extra_inactive",
            nonce="nonce_extra_inactive",
            product=PaymentProduct.EXTRA_ONE_DAY,
            amount=35,
        ),
    )
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage(order.delivery_chat_id, user_id=order.user_id)
    message.successful_payment = _successful_payment_for_order(
        order,
        telegram_charge_id="tg-charge-extra-inactive1",
    )

    await telegram_app.handle_successful_payment(message)

    entitlement = store.get_entitlement(order.user_id)
    assert entitlement.extra_one_day_remaining == 0
    assert store.load_payment_order(order.order_id).status == PaymentOrderStatus.PENDING
    assert store.processed_charge_ids() == []
    assert store.payment_events[-1].status == PaymentEventStatus.IGNORED_NON_TERMINAL


@pytest.mark.anyio
async def test_successful_payment_handler_does_not_call_legacy_direct_apply_path(monkeypatch) -> None:
    store = FakePaymentStore()
    order = store.insert_payment_order(_pending_payment_order())
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(
        telegram_app,
        "apply_subscription_payment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy path called")),
    )
    message = FakeMessage(order.delivery_chat_id, user_id=order.user_id)
    message.successful_payment = _successful_payment_for_order(
        order,
        telegram_charge_id="tg-charge-core1",
    )

    await telegram_app.handle_successful_payment(message)

    assert store.get_entitlement(order.user_id).is_subscription_active()
    assert store.successful_payment_inputs


@pytest.mark.anyio
async def test_payment_event_command_requires_admin(monkeypatch) -> None:
    store = FakePaymentStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {71_900})
    message = FakeMessage(
        text="/payment_event refund telegram_stars tg-secret-refund",
        user_id=71_901,
    )

    await telegram_app.payment_event_reconciliation_command(message)

    response = message.texts[-1][0]
    assert "only to admins" in response
    assert "tg-secret-refund" not in response
    assert store.payment_reversal_inputs == []
    assert store.payment_reconciliation_inputs == []


@pytest.mark.anyio
async def test_admin_refund_command_calls_reversal_core_and_returns_redacted_status(monkeypatch) -> None:
    admin_id = 71_902
    store = FakePaymentStore()
    order = _paid_store_order(
        store,
        order_id="order_refund_secret",
        charge_id="tg-refund-secret",
    )
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(
        text=(
            "/payment_event refund telegram_stars tg-refund-secret "
            "buyer@example.com +79991234567 order_info 123456789:ABCdefGhijKLMnopQRStuVWXyz"
        ),
        user_id=admin_id,
    )
    duplicate = FakeMessage(
        text="/payment_event refund telegram_stars tg-refund-secret retry",
        user_id=admin_id,
    )

    await telegram_app.payment_event_reconciliation_command(message)
    await telegram_app.payment_event_reconciliation_command(duplicate)

    response = message.texts[-1][0]
    duplicate_response = duplicate.texts[-1][0]
    entitlement = store.get_entitlement(order.user_id)
    assert store.payment_reversal_inputs[0].event_type == PaymentEventType.REFUND
    assert store.payment_reversal_inputs[0].provider == PaymentProvider.TELEGRAM_STARS
    assert store.payment_reversal_inputs[0].telegram_charge_id == "tg-refund-secret"
    assert response.startswith("processed: reversal applied")
    assert duplicate_response.startswith("duplicate: reversal no-op")
    assert not entitlement.is_subscription_active()
    _assert_admin_payment_response_is_redacted(response)


@pytest.mark.anyio
async def test_admin_chargeback_command_calls_reversal_core_and_returns_redacted_status(monkeypatch) -> None:
    admin_id = 71_903
    store = FakePaymentStore()
    _paid_store_order(
        store,
        order_id="order_chargeback_secret",
        charge_id="tg-chargeback-secret",
        product=PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
        entitlement=telegram_app.Entitlement(
            subscription_period_start=datetime.now(UTC).isoformat(),
            subscription_period_end=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
        ),
    )
    assert store.get_entitlement(12345).extra_one_day_remaining == 1
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(
        text="/payment_event chargeback telegram_stars tg-chargeback-secret",
        user_id=admin_id,
    )

    await telegram_app.payment_event_reconciliation_command(message)

    response = message.texts[-1][0]
    assert store.payment_reversal_inputs[0].event_type == PaymentEventType.CHARGEBACK
    assert store.get_entitlement(12345).extra_one_day_remaining == 0
    assert response.startswith("processed: reversal applied")
    assert "tg-chargeback-secret" not in response


@pytest.mark.anyio
async def test_admin_cancel_command_records_cancel_and_keeps_paid_period(monkeypatch) -> None:
    admin_id = 71_904
    store = FakePaymentStore()
    order = _paid_store_order(
        store,
        order_id="order_cancel_secret",
        charge_id="tg-cancel-secret",
    )
    before = store.get_entitlement(order.user_id).to_dict()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(
        text="/payment_event cancel_subscription telegram_stars tg-cancel-secret",
        user_id=admin_id,
    )

    await telegram_app.payment_event_reconciliation_command(message)

    entitlement = store.get_entitlement(order.user_id)
    assert store.payment_reversal_inputs[0].event_type == PaymentEventType.CANCEL_SUBSCRIPTION
    assert entitlement.to_dict() == before
    assert entitlement.is_subscription_active()
    assert message.texts[-1][0].startswith("processed: reversal applied")


@pytest.mark.anyio
async def test_admin_reconcile_orphan_command_calls_reconciliation_core_once(monkeypatch) -> None:
    admin_id = 71_905
    store = FakePaymentStore()
    now = datetime.now(UTC)
    order = store.insert_payment_order(
        _pending_payment_order(
            order_id="order_reconcile_secret",
            nonce="nonce_reconcile_secret",
            expires_at=now + timedelta(minutes=5),
        ),
    )
    orphan = PaymentEvent(
        event_id="evt_orphan_secret",
        event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
        provider=PaymentProvider.TELEGRAM_STARS,
        order_id="order_missing_secret",
        charge_id="tg-orphan-secret",
        telegram_charge_id="tg-orphan-secret",
        user_id=order.user_id,
        delivery_chat_id=order.delivery_chat_id,
        product=order.product,
        amount=order.amount,
        currency=order.currency,
        status=PaymentEventStatus.ORPHAN_RECOVERABLE,
        reason="order_not_found",
        raw_payload_redacted={"email": "[REDACTED]"},
    )
    store.insert_payment_event(orphan)
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(
        text=(
            "/payment_event reconcile_orphan evt_orphan_secret order_reconcile_secret "
            "matched buyer@example.com +79991234567"
        ),
        user_id=admin_id,
    )
    duplicate = FakeMessage(
        text="/payment_event reconcile_orphan evt_orphan_secret order_reconcile_secret retry",
        user_id=admin_id,
    )

    await telegram_app.payment_event_reconciliation_command(message)
    await telegram_app.payment_event_reconciliation_command(duplicate)

    response = message.texts[-1][0]
    duplicate_response = duplicate.texts[-1][0]
    assert len(store.payment_reconciliation_inputs) == 2
    assert store.payment_reconciliation_inputs[0].action == PaymentReconciliationAction.RECONCILE_ORPHAN_SUCCESS
    assert store.payment_reconciliation_inputs[0].target_event_id == "evt_orphan_secret"
    assert store.payment_reconciliation_inputs[0].target_order_id == "order_reconcile_secret"
    assert store.get_entitlement(order.user_id).is_subscription_active()
    assert response.startswith("processed: reconciliation applied")
    assert duplicate_response.startswith("duplicate: reconciliation no-op")
    _assert_admin_payment_response_is_redacted(response)


@pytest.mark.anyio
async def test_admin_ignore_orphan_command_closes_event_with_redacted_reason(monkeypatch) -> None:
    admin_id = 71_906
    store = FakePaymentStore()
    event = PaymentEvent(
        event_id="evt_ignore_secret",
        event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
        provider=PaymentProvider.TELEGRAM_STARS,
        order_id=None,
        charge_id="tg-ignore-secret",
        telegram_charge_id="tg-ignore-secret",
        status=PaymentEventStatus.ORPHAN_RECOVERABLE,
        reason="order_not_found",
    )
    store.insert_payment_event(event)
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(
        text=(
            "/payment_event ignore evt_ignore_secret buyer@example.com +79991234567 "
            "order_info provider_data receipt customer "
            "123456789:ABCdefGhijKLMnopQRStuVWXyz "
            "381764678:TEST:provider-secret "
            "postgresql://diet_bot:secret@example.com/db"
        ),
        user_id=admin_id,
    )

    await telegram_app.payment_event_reconciliation_command(message)

    ignored = store.load_payment_event("evt_ignore_secret")
    response = message.texts[-1][0]
    assert store.payment_reconciliation_inputs[0].action == PaymentReconciliationAction.IGNORE_EVENT
    assert ignored is not None
    assert ignored.status == PaymentEventStatus.IGNORED_NON_TERMINAL
    assert response.startswith("processed: reconciliation applied")
    _assert_admin_payment_response_is_redacted(response)


@pytest.mark.anyio
async def test_send_subscription_invoice_link_creates_recurring_stars_invoice(monkeypatch) -> None:
    store = FakePaymentStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage()

    await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)

    invoice = message.bot.invoice_links[0]
    order_id, nonce = decode_payment_order_payload(invoice["payload"])
    order = store.orders[0]

    assert invoice["currency"] == "XTR"
    assert invoice["provider_token"] == ""
    assert invoice["payload"] != PAYLOAD_SUBSCRIPTION_MONTH
    assert invoice["payload"] == f"diet:order:{order_id}:{nonce}"
    assert order.order_id == order_id
    assert order.nonce == nonce
    assert order.user_id == message.chat.id
    assert order.delivery_chat_id == message.chat.id
    assert order.provider == PaymentProvider.TELEGRAM_STARS
    assert order.product == PaymentProduct.SUBSCRIPTION_MONTH
    assert order.amount == SUBSCRIPTION_STARS_AMOUNT
    assert order.currency == PaymentCurrency.XTR
    assert order.invoice_link == "https://t.me/invoice/test"
    assert store.invoice_link_updates == [(order.order_id, "https://t.me/invoice/test")]
    assert invoice["prices"][0].amount == SUBSCRIPTION_STARS_AMOUNT
    assert invoice["subscription_period"] == 2_592_000
    assert message.texts[-1][1].inline_keyboard[0][0].url == "https://t.me/invoice/test"


@pytest.mark.anyio
async def test_send_extra_day_invoice_link_creates_one_time_stars_invoice(monkeypatch) -> None:
    store = FakePaymentStore(entitlements={12345: _active_payment_entitlement()})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage()

    await _send_stars_invoice_link(message, PAYLOAD_EXTRA_ONE_DAY)

    invoice = message.bot.invoice_links[0]
    order_id, nonce = decode_payment_order_payload(invoice["payload"])
    order = store.orders[0]

    assert invoice["currency"] == "XTR"
    assert invoice["payload"] == f"diet:order:{order_id}:{nonce}"
    assert order.product == PaymentProduct.EXTRA_ONE_DAY
    assert invoice["prices"][0].amount == 35
    assert invoice["subscription_period"] is None


@pytest.mark.anyio
async def test_repeated_stars_invoice_tap_reuses_active_pending_order(monkeypatch) -> None:
    store = FakePaymentStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage()

    await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)
    await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)

    assert len(store.orders) == 1
    assert len(message.bot.invoice_links) == 1
    assert len(message.texts) == 2
    assert store.orders[0].invoice_link == "https://t.me/invoice/test"
    assert message.texts[-1][1].inline_keyboard[0][0].url == "https://t.me/invoice/test"


@pytest.mark.anyio
async def test_extra_invoice_without_active_subscription_returns_refusal(monkeypatch) -> None:
    store = FakePaymentStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage()

    await _send_stars_invoice_link(message, PAYLOAD_EXTRA_ONE_DAY)

    assert store.orders == []
    assert message.bot.invoice_links == []
    sent_text, markup = message.texts[-1]
    assert "Разовые покупки доступны только при активной подписке." in sent_text
    assert markup.inline_keyboard[0][0].callback_data == CALLBACK_PAY_RU_CARD


@pytest.mark.anyio
async def test_create_invoice_link_failure_marks_payment_order_failed(monkeypatch) -> None:
    store = FakePaymentStore(entitlements={12345: _active_payment_entitlement()})
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    message = FakeMessage()
    message.bot = FailingInvoiceBot()

    await _send_stars_invoice_link(message, PAYLOAD_EXTRA_ONE_DAY)

    assert len(store.orders) == 1
    assert store.orders[0].status == PaymentOrderStatus.FAILED_INVOICE_CREATION
    assert store.failed_invoice_creation_order_ids == [store.orders[0].order_id]
    assert message.bot.invoice_links == []
    assert message.texts == [("Не удалось создать счет для оплаты. Попробуйте позже.", None)]


@pytest.mark.anyio
async def test_ru_card_callback_creates_yookassa_invoice_with_receipt(monkeypatch) -> None:
    store = FakePaymentStore()
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage()
    callback = FakeCallback(CALLBACK_PAY_RU_CARD, message)

    await telegram_app.handle_callback(callback)

    invoice = message.bot.invoice_links[0]
    provider_data = json.loads(invoice["provider_data"])
    item = provider_data["receipt"]["items"][0]

    assert callback.answers == [None]
    assert invoice["currency"] == "RUB"
    assert invoice["provider_token"] == "provider-token"
    order_id, nonce = decode_payment_order_payload(invoice["payload"])
    order = store.orders[0]
    assert order.order_id == order_id
    assert order.nonce == nonce
    assert order.provider == PaymentProvider.YOOKASSA
    assert order.product == PaymentProduct.SUBSCRIPTION_MONTH
    assert invoice["payload"] == order.payload
    assert invoice["prices"][0].amount == 59_900
    assert invoice["need_email"] is True
    assert invoice["send_email_to_provider"] is True
    assert item == {
        "description": "FoodBalance monthly access",
        "quantity": "1.00",
        "amount": {
            "value": "599.00",
            "currency": "RUB",
        },
        "vat_code": 1,
        "payment_mode": "full_payment",
        "payment_subject": "service",
    }
    assert store.invoice_link_updates == [(order.order_id, "https://t.me/invoice/test")]
    assert message.texts[-1][0] == "FoodBalance: подписка на месяц\n\nСтоимость: 599 ₽."
    assert message.texts[-1][1].inline_keyboard[0][0].url == "https://t.me/invoice/test"


@pytest.mark.anyio
async def test_entered_discount_code_applies_to_next_yookassa_invoice(monkeypatch) -> None:
    code = "FB-DISC-OUNT-2026"
    store = FakePaymentStore(
        promo_codes={
            code: PromoCodeDefinition(
                code=code,
                kind=PromoCodeKind.DISCOUNT,
                max_redemptions=5,
                discount_percent=20,
            )
        }
    )
    monkeypatch.setattr(telegram_app, "_RUNTIME_STORE", store)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage()
    PROMO_CODE_REQUEST_CHAT_IDS.add(message.chat.id)

    await handle_answer(FakeMessage(message.chat.id, text=code))
    callback = FakeCallback(CALLBACK_PAY_RU_CARD, message)
    await telegram_app.handle_callback(callback)

    invoice = message.bot.invoice_links[0]
    order = store.orders[0]
    provider_data = json.loads(invoice["provider_data"])
    assert invoice["prices"][0].amount == 47_920
    assert provider_data["receipt"]["items"][0]["amount"] == {
        "value": "479.20",
        "currency": "RUB",
    }
    assert order.amount == 47_920
    assert order.list_amount == 59_900
    assert order.discount_amount == 11_980
    assert order.promo_code_suffix == "2026"
    assert store.payment_order_promo_codes == [code]
    assert code not in str(order.metadata)


@pytest.mark.anyio
async def test_active_subscription_cannot_buy_monthly_card_again(monkeypatch, tmp_path) -> None:
    chat_id = 81_007
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    _save_active_subscription(tmp_path / "subscriptions.json", chat_id, one_day_remaining=4, weekly_pdf_remaining=3)
    message = FakeMessage(chat_id)
    callback = FakeCallback(CALLBACK_PAY_RU_CARD, message)

    await telegram_app.handle_callback(callback)

    sent_text, markup = message.texts[-1]

    assert callback.answers == [None]
    assert message.bot.invoice_links == []
    assert "Месячный доступ уже активен." in sent_text
    assert "Повторно купить месячный доступ можно после окончания текущего периода." in sent_text
    assert markup.inline_keyboard[0][0].callback_data == CALLBACK_ONE_DAY_PLAN


@pytest.mark.anyio
async def test_ru_invoice_without_provider_token_shows_unavailable_message(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "")
    message = FakeMessage()

    await telegram_app._send_yookassa_invoice_link(message, telegram_app.PAYLOAD_RU_EXTRA_ONE_DAY)

    assert message.bot.invoice_links == []
    sent_text, markup = message.texts[-1]
    assert "FoodBalance: 1 дневной рацион" in sent_text
    assert "Стоимость: 50 ₽." in sent_text
    assert "ЮKassa сейчас недоступна" in sent_text
    assert markup is None


def test_trial_subscription_keyboard_has_cta_button() -> None:
    keyboard = _trial_subscription_keyboard()
    button = keyboard.inline_keyboard[0][0]

    assert (button.text, button.callback_data) == (SUBSCRIBE_CTA_TEXT, CALLBACK_SUBSCRIBE)
    assert "пробный рацион на 1 день" in TRIAL_SUBSCRIPTION_TEXT
    assert "4 недельных рациона" in TRIAL_SUBSCRIPTION_TEXT
    assert "5 дополнительных дневных рационов" in TRIAL_SUBSCRIPTION_TEXT


def test_question_keyboard_marks_selected_option_only() -> None:
    session, error = start_session().receive("32")
    assert error is None
    question = session.current_question

    keyboard = telegram_app._question_keyboard(question, selected_index=1)
    button_texts = [row[0].text for row in keyboard.inline_keyboard]

    assert button_texts[1] == f"✅ {question.options[1]}"
    assert button_texts[0] == question.options[0]
    assert all(not text.startswith("✅ ") for text in button_texts[:1])


def test_question_keyboard_switches_selected_marker_without_duplicates() -> None:
    session, error = start_session().receive("32")
    assert error is None
    question = session.current_question

    keyboard = telegram_app._question_keyboard(question, selected_index=0)
    switched_keyboard = telegram_app._question_keyboard(question, selected_index=1)

    first_texts = [row[0].text for row in keyboard.inline_keyboard]
    switched_texts = [row[0].text for row in switched_keyboard.inline_keyboard]
    assert sum(text.startswith("✅ ") for text in first_texts) == 1
    assert sum(text.startswith("✅ ") for text in switched_texts) == 1
    assert switched_texts[0] == question.options[0]
    assert switched_texts[1] == f"✅ {question.options[1]}"


def test_plan_choice_keyboard_has_day_and_week_pdf_buttons() -> None:
    keyboard = _plan_choice_keyboard()
    buttons = [row[0] for row in keyboard.inline_keyboard]

    assert [(button.text, button.callback_data) for button in buttons] == [
        (ONE_DAY_PLAN_TEXT, CALLBACK_ONE_DAY_PLAN),
        (WEEK_PLAN_PDF_TEXT, CALLBACK_WEEK_PLAN_PDF),
        (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
        (SUPPORT_TEXT, CALLBACK_SUPPORT),
    ]
    assert WEEK_PLAN_PDF_PLACEHOLDER_TEXT == "Функция рациона на неделю в PDF пока в разработке."


def test_week_plan_dates_start_tomorrow() -> None:
    dates = _week_plan_dates(date(2026, 5, 7))

    assert dates[0] == date(2026, 5, 8)
    assert dates[-1] == date(2026, 5, 14)
    assert _format_week_day_header(1, dates[0]) == "📅 День 1 — 08.05.2026"


def test_batch_muffin_carryover_reuses_recipe_until_finished() -> None:
    flour = Food(id="wheat_flour", name="пшеничная мука", category="grains", nutrients_per_100g=NutrientVector())
    egg = Food(id="egg", name="яйцо", category="protein", nutrients_per_100g=NutrientVector())
    yogurt = Food(id="greek_yogurt", name="греческий йогурт", category="dairy", nutrients_per_100g=NutrientVector())
    targets = NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector({"energy_kcal": 2000}),
        calorie_bounds=(1800, 2200),
        macro_bounds={},
    )
    safety = SafetyResult(can_generate_plan=True)
    muffin = Meal(
        "🥣 Перекус: Бананово-овсяные маффины с коричневым маслом",
        (FoodPortion(flour, 3), FoodPortion(egg, 25)),
        "Разогрейте духовку и выстелите 12 ячеек формы бумажными капсулами. Выпекайте маффины.",
        recipe_id="muffin",
        recipe_key="snack:curated:muffin",
    )
    yogurt_meal = Meal(
        "🥣 Перекус: Йогурт",
        (FoodPortion(yogurt, 170),),
        "Смешайте.",
        recipe_id="yogurt",
        recipe_key="snack:curated:yogurt",
    )
    plans = [
        MealPlan((muffin,), targets, safety),
        MealPlan((yogurt_meal,), targets, safety),
        MealPlan((yogurt_meal,), targets, safety),
        MealPlan((yogurt_meal,), targets, safety),
    ]

    carryovers = {}
    adjusted = tuple(_apply_batch_carryovers(plan, carryovers) for plan in plans)

    assert adjusted[0].meals[0].recipe_id == "muffin"
    assert adjusted[0].meals[0].batch
    assert not adjusted[0].meals[0].batch.is_carryover
    assert [plan.meals[0].recipe_id for plan in adjusted] == ["muffin", "muffin", "muffin", "yogurt"]
    assert adjusted[1].meals[0].batch and adjusted[1].meals[0].batch.is_carryover
    assert adjusted[2].meals[0].batch and adjusted[2].meals[0].batch.is_carryover

    first_card = format_meal_card(adjusted[0].meals[0])
    carryover_card = format_meal_card(adjusted[1].meals[0])
    shopping = format_week_shopping_list(adjusted[:3])

    assert "Приготовьте 6 маффинов на 3 перекуса" in first_card
    assert "сегодня съешьте только 2 маффина" in first_card
    assert "Остальные 4 маффина уберите на следующие 2 перекуса" in first_card
    assert "выстелите 6 ячеек формы" in first_card
    assert "12 ячеек формы" not in first_card
    assert "яйцо - 2 шт." in first_card
    assert "пшеничная мука - 30 г" in first_card
    assert "Съешьте 2 маффина из приготовленной партии" in carryover_card
    assert "пшеничная мука: 30 г" in shopping
    assert "яйцо: 100 г" in shopping


def test_batch_bar_recipe_uses_bar_wording() -> None:
    oats = Food(id="oats", name="овсяные хлопья", category="grains", nutrients_per_100g=NutrientVector())
    honey = Food(id="honey", name="мед", category="sweetener", nutrients_per_100g=NutrientVector())
    targets = NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector({"energy_kcal": 2000}),
        calorie_bounds=(1800, 2200),
        macro_bounds={},
    )
    safety = SafetyResult(can_generate_plan=True)
    bar = Meal(
        "🥣 Второй перекус: Мягкие овсяно-изюмные гранола-батончики",
        (FoodPortion(oats, 8), FoodPortion(honey, 8)),
        "Выложите массу в форму, выпекайте и нарежьте на батончики.",
        recipe_id="bar",
        recipe_key="snack:curated:bar",
    )

    adjusted = _apply_batch_carryovers(MealPlan((bar,), targets, safety), {})
    card = format_meal_card(adjusted.meals[0])

    assert "Приготовьте 6 батончиков на 3 перекуса" in card
    assert "сегодня съешьте только 2 батончика" in card
    assert "маффин" not in card


def test_batch_cracker_recipe_uses_cracker_wording() -> None:
    rye_flour = Food(id="rye_flour", name="ржаная мука", category="grains", nutrients_per_100g=NutrientVector())
    egg = Food(id="egg", name="яйцо", category="protein", nutrients_per_100g=NutrientVector())
    targets = NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector({"energy_kcal": 2000}),
        calorie_bounds=(1800, 2200),
        macro_bounds={},
    )
    safety = SafetyResult(can_generate_plan=True)
    cracker = Meal(
        "🥣 Перекус: Ржаные крекеры с тыквенными семечками",
        (FoodPortion(rye_flour, 8), FoodPortion(egg, 50)),
        "Застелите два противня пергаментом, раскатайте тесто и нарежьте на крекеры.",
        recipe_id="cracker",
        recipe_key="snack:curated:cracker",
    )

    adjusted = _apply_batch_carryovers(MealPlan((cracker,), targets, safety), {})
    card = format_meal_card(adjusted.meals[0])

    assert adjusted.meals[0].batch
    assert "Приготовьте 6 крекеров на 3 перекуса" in card
    assert "сегодня съешьте только 2 крекера" in card
    assert "маффин" not in card


class FakeMessage:
    def __init__(
        self,
        chat_id=12345,
        *,
        text="",
        user_id=None,
        username=None,
        first_name=None,
        last_name=None,
    ) -> None:
        self.chat = type("FakeChat", (), {"id": chat_id})()
        self.from_user = SimpleNamespace(
            id=chat_id if user_id is None else user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            full_name=" ".join(part for part in (first_name, last_name) if part),
        )
        self.text = text
        self.successful_payment = None
        self.bot = FakeInvoiceBot()
        self.photos = []
        self.texts = []
        self.documents = []
        self.edits = []
        self.reply_markup_edits = []

    async def answer_photo(self, **kwargs) -> None:
        self.photos.append(kwargs)

    async def answer(self, text, reply_markup=None):
        self.texts.append((text, reply_markup))
        return FakeSentMessage(self)

    async def answer_document(self, **kwargs) -> None:
        self.documents.append(kwargs)

    async def edit_reply_markup(self, reply_markup=None, **kwargs) -> None:
        self.reply_markup_edits.append((reply_markup, kwargs))


class FailingDocumentMessage(FakeMessage):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.document_attempts = []

    async def answer_document(self, **kwargs) -> None:
        self.document_attempts.append(kwargs)
        raise RuntimeError("telegram send failed")


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message
        self.answers = []

    async def answer(self, text=None) -> None:
        self.answers.append(text)


class FakePreCheckoutQuery:
    def __init__(
        self,
        *,
        invoice_payload: str,
        user_id: int,
        currency: str,
        total_amount: int,
    ) -> None:
        self.invoice_payload = invoice_payload
        self.from_user = SimpleNamespace(id=user_id)
        self.currency = currency
        self.total_amount = total_amount
        self.answers = []

    async def answer(self, *, ok: bool, error_message: str | None = None) -> None:
        self.answers.append({"ok": ok, "error_message": error_message})


class FakeSentMessage:
    def __init__(self, source: FakeMessage) -> None:
        self.source = source

    async def edit_text(self, text, **kwargs) -> None:
        self.source.edits.append((text, kwargs))


class FakeBot:
    def __init__(self) -> None:
        self.commands = None

    async def set_my_commands(self, commands) -> None:
        self.commands = commands


class FakeInvoiceBot:
    def __init__(self) -> None:
        self.invoice_links = []
        self.chat_actions = []
        self.sent_messages = []

    async def create_invoice_link(self, **kwargs) -> str:
        self.invoice_links.append(kwargs)
        return "https://t.me/invoice/test"

    async def send_chat_action(self, **kwargs) -> None:
        self.chat_actions.append(kwargs)

    async def send_message(self, **kwargs) -> None:
        self.sent_messages.append(kwargs)


class FailingInvoiceBot(FakeInvoiceBot):
    async def create_invoice_link(self, **kwargs) -> str:
        raise telegram_app.TelegramAPIError(SimpleNamespace(), "invoice unavailable")


class FakePaymentStore:
    def __init__(
        self,
        *,
        entitlements: dict[int, telegram_app.Entitlement] | None = None,
        promo_codes: dict[str, PromoCodeDefinition] | None = None,
    ) -> None:
        self.orders: list[PaymentOrder] = []
        self.entitlements = dict(entitlements or {})
        self.promo_codes = {
            normalize_promo_code(code): promo for code, promo in dict(promo_codes or {}).items()
        }
        self.payment_order_promo_codes: list[str] = []
        self.invoice_link_updates: list[tuple[str, str]] = []
        self.failed_invoice_creation_order_ids: list[str] = []
        self.pre_checkout_approvals: list[str] = []
        self.expired_order_ids: list[str] = []
        self.payment_events: list[PaymentEvent] = []
        self.processed_provider_charges: list[ProcessedProviderCharge] = []
        self.successful_payment_inputs: list[PaymentSuccessfulPaymentInput] = []
        self.payment_reversal_inputs: list[PaymentReversalInput] = []
        self.payment_reconciliation_inputs: list[PaymentReconciliationInput] = []
        self._sequence = 0

    def get_entitlement(self, user_id: int) -> telegram_app.Entitlement:
        return self.entitlements.setdefault(user_id, telegram_app.Entitlement())

    def save_entitlement(self, user_id: int, entitlement: telegram_app.Entitlement) -> None:
        self.entitlements[user_id] = entitlement

    def load_profile_data(self, user_id: int) -> dict[str, object] | None:
        return None

    def create_or_reuse_pending_payment_order(
        self,
        *,
        user_id: int,
        delivery_chat_id: int | None,
        provider: PaymentProvider | str,
        product: PaymentProduct | str,
        amount: int,
        currency: PaymentCurrency | str,
        now: datetime | None = None,
        ttl_seconds: int = 900,
        promo_code: str | None = None,
    ) -> PaymentOrderCreationResult:
        list_amount = amount
        discount_amount = 0
        promo_code_id = None
        promo_redemption_id = None
        promo_code_hash = None
        promo_code_suffix = None
        metadata: dict[str, object] = {}
        if promo_code is not None:
            normalized = normalize_promo_code(promo_code)
            promo = self.promo_codes.get(normalized)
            if promo is None:
                return PaymentOrderCreationResult(
                    accepted=False,
                    code=PaymentOrderCreationCode.PROMO_NOT_FOUND,
                )
            if promo.kind != PromoCodeKind.DISCOUNT:
                return PaymentOrderCreationResult(
                    accepted=False,
                    code=PaymentOrderCreationCode.PROMO_NOT_DISCOUNT,
                )
            discount_amount = calculate_discount_amount(promo, list_amount)
            amount = list_amount - discount_amount
            promo_code_id = 1
            promo_redemption_id = len(self.payment_order_promo_codes) + 1
            audit_metadata = promo_code_audit_metadata(
                normalized,
                promo_code_id=promo_code_id,
                discount_amount=discount_amount,
                final_amount=amount,
            )
            promo_code_hash = str(audit_metadata["code_hash"])
            promo_code_suffix = str(audit_metadata["code_suffix"])
            metadata = audit_metadata
            self.payment_order_promo_codes.append(normalized)
        self._sequence += 1
        sequence = self._sequence
        result = create_or_reuse_pending_payment_order(
            self,
            user_id=user_id,
            delivery_chat_id=delivery_chat_id,
            provider=provider,
            product=product,
            amount=amount,
            currency=currency,
            now=now,
            ttl_seconds=ttl_seconds,
            order_id_factory=lambda: f"order_{sequence}",
            nonce_factory=lambda: f"nonce_{sequence}",
        )
        if result.order is None or promo_code is None:
            return result
        discounted_order = replace(
            result.order,
            list_amount=list_amount,
            discount_amount=discount_amount,
            promo_code_id=promo_code_id,
            promo_redemption_id=promo_redemption_id,
            promo_code_hash=promo_code_hash,
            promo_code_suffix=promo_code_suffix,
            metadata=metadata,
        )
        self.orders[-1] = discounted_order
        return replace(result, order=discounted_order)

    def find_active_pending_payment_order(
        self,
        *,
        user_id: int,
        delivery_chat_id: int | None,
        provider: PaymentProvider,
        product: PaymentProduct,
        amount: int,
        currency: PaymentCurrency,
        now: datetime,
        promo_code_id: int | None = None,
    ) -> PaymentOrder | None:
        for order in reversed(self.orders):
            if (
                order.user_id == user_id
                and order.delivery_chat_id == delivery_chat_id
                and order.provider == provider
                and order.product == product
                and order.amount == amount
                and order.currency == currency
                and order.promo_code_id == promo_code_id
                and is_active_pending_payment_order(order, now=now)
            ):
                return order
        return None

    def insert_payment_order(self, order: PaymentOrder) -> PaymentOrder:
        self.orders.append(order)
        return order

    def get_promo_code(
        self,
        raw_code: str,
        *,
        active_only: bool = False,
        now: datetime | None = None,
    ) -> PromoCodeDefinition | None:
        promo = self.promo_codes.get(normalize_promo_code(raw_code))
        if promo is None:
            return None
        if active_only and not promo.is_active_at(now):
            return None
        return promo

    def activate_promo_code(self, user_id: int, raw_code: str) -> PromoCodeActivation:
        promo = self.promo_codes.get(normalize_promo_code(raw_code))
        if promo is None:
            return PromoCodeActivation("not_found", normalize_promo_code(raw_code))
        if promo.kind != PromoCodeKind.MONTHLY_ACCESS:
            return PromoCodeActivation("not_access_code", promo.code)
        return PromoCodeActivation("activated", promo.code, user_id)

    def load_payment_order(self, order_id: str) -> PaymentOrder | None:
        for order in self.orders:
            if order.order_id == order_id:
                return order
        return None

    def mark_payment_order_invoice_link(self, order_id: str, invoice_link: str) -> None:
        self.invoice_link_updates.append((order_id, invoice_link))
        for index, order in enumerate(self.orders):
            if order.order_id == order_id:
                self.orders[index] = replace(order, invoice_link=invoice_link)
                return

    def mark_payment_order_invoice_creation_failed(self, order_id: str) -> None:
        self.failed_invoice_creation_order_ids.append(order_id)
        for index, order in enumerate(self.orders):
            if order.order_id == order_id:
                self.orders[index] = replace(
                    order,
                    status=PaymentOrderStatus.FAILED_INVOICE_CREATION,
                )
                return

    def record_payment_order_pre_checkout_approved(
        self,
        order_id: str,
        approved_at: datetime | None = None,
    ) -> PaymentOrder | None:
        approved_at = approved_at or datetime.now(UTC)
        for index, order in enumerate(self.orders):
            if order.order_id != order_id:
                continue
            updated = replace(
                order,
                pre_checkout_approved_at=approved_at,
                updated_at=approved_at,
            )
            self.orders[index] = updated
            self.pre_checkout_approvals.append(order_id)
            return updated
        return None

    def mark_payment_order_expired(self, order_id: str) -> None:
        for index, order in enumerate(self.orders):
            if order.order_id != order_id:
                continue
            self.orders[index] = replace(
                order,
                status=PaymentOrderStatus.EXPIRED,
            )
            self.expired_order_ids.append(order_id)
            return

    def apply_successful_payment(
        self,
        successful_payment: PaymentSuccessfulPaymentInput,
        *,
        now: datetime | None = None,
    ) -> PaymentSuccessfulPaymentResult:
        self.successful_payment_inputs.append(successful_payment)
        return apply_successful_payment_core(self, successful_payment, now=now)

    def apply_payment_reversal(
        self,
        reversal: PaymentReversalInput,
        *,
        now: datetime | None = None,
    ) -> PaymentReversalResult:
        self.payment_reversal_inputs.append(reversal)
        return apply_payment_reversal_core(self, reversal, now=now)

    def apply_payment_reconciliation(
        self,
        reconciliation: PaymentReconciliationInput,
        *,
        now: datetime | None = None,
    ) -> PaymentReconciliationResult:
        self.payment_reconciliation_inputs.append(reconciliation)
        return apply_payment_reconciliation_core(self, reconciliation, now=now)

    def insert_payment_event(self, event: PaymentEvent) -> PaymentEvent:
        self.payment_events.append(event)
        return event

    def load_payment_event(self, event_id: str) -> PaymentEvent | None:
        for event in self.payment_events:
            if event.event_id == event_id:
                return event
        return None

    def update_payment_event(self, event: PaymentEvent) -> PaymentEvent:
        for index, existing in enumerate(self.payment_events):
            if existing.event_id == event.event_id:
                self.payment_events[index] = event
                return event
        self.payment_events.append(event)
        return event

    def find_payment_event(
        self,
        *,
        provider: PaymentProvider,
        charge_id: str,
        event_type: PaymentEventType | None = None,
        statuses: tuple[PaymentEventStatus, ...] = (),
    ) -> PaymentEvent | None:
        for event in reversed(self.payment_events):
            if event.provider != provider:
                continue
            if event_type is not None and event.event_type != event_type:
                continue
            if statuses and event.status not in statuses:
                continue
            if charge_id in {
                event.charge_id,
                event.telegram_charge_id,
                event.provider_charge_id,
            }:
                return event
        return None

    def find_processed_provider_charge(
        self,
        *,
        provider: PaymentProvider,
        charge_id: str,
        event_type: PaymentEventType,
    ) -> ProcessedProviderCharge | None:
        for processed in self.processed_provider_charges:
            if (
                processed.provider == provider
                and processed.charge_id == charge_id
                and processed.event_type == event_type
            ):
                return processed
        return None

    def insert_processed_provider_charge(
        self,
        charge: ProcessedProviderCharge,
    ) -> ProcessedProviderCharge:
        existing = self.find_processed_provider_charge(
            provider=charge.provider,
            charge_id=charge.charge_id,
            event_type=charge.event_type,
        )
        if existing is not None:
            return existing
        self.processed_provider_charges.append(charge)
        return charge

    def mark_payment_order_paid(
        self,
        order_id: str,
        paid_at: datetime,
    ) -> PaymentOrder | None:
        for index, order in enumerate(self.orders):
            if order.order_id != order_id:
                continue
            updated = replace(
                order,
                status=PaymentOrderStatus.PAID,
                paid_at=paid_at,
                updated_at=paid_at,
            )
            self.orders[index] = updated
            return updated
        return None

    def processed_charge_ids(
        self,
        event_type: PaymentEventType = PaymentEventType.SUCCESSFUL_PAYMENT,
    ) -> list[str]:
        return [
            charge.charge_id
            for charge in self.processed_provider_charges
            if charge.event_type == event_type
        ]


class SensitiveFailurePaymentStore(FakePaymentStore):
    def load_payment_order(self, order_id: str) -> PaymentOrder | None:
        raise RuntimeError(
            "db postgresql://diet_bot:secret@example.com/db "
            "bot 123456789:ABCdefGhijKLMnopQRStuVWXyz "
            "provider 381764678:TEST:provider-secret "
            f"payload diet:order:{order_id}:nonce_secret"
        )


def _pending_payment_order(
    *,
    order_id: str = "order_pre",
    nonce: str = "nonce_pre",
    user_id: int = 12345,
    delivery_chat_id: int | None = 12345,
    provider: PaymentProvider = PaymentProvider.TELEGRAM_STARS,
    product: PaymentProduct = PaymentProduct.SUBSCRIPTION_MONTH,
    amount: int = 400,
    currency: PaymentCurrency = PaymentCurrency.XTR,
    expires_at: datetime | None = None,
) -> PaymentOrder:
    return PaymentOrder(
        order_id=order_id,
        nonce=nonce,
        user_id=user_id,
        delivery_chat_id=delivery_chat_id,
        provider=provider,
        product=product,
        amount=amount,
        currency=currency,
        status=PaymentOrderStatus.PENDING,
        expires_at=expires_at or (datetime.now(UTC) + timedelta(minutes=5)),
    )


def _paid_store_order(
    store: FakePaymentStore,
    *,
    order_id: str,
    charge_id: str,
    product: PaymentProduct = PaymentProduct.SUBSCRIPTION_MONTH,
    amount: int = 400,
    entitlement: telegram_app.Entitlement | None = None,
) -> PaymentOrder:
    now = datetime.now(UTC)
    order = store.insert_payment_order(
        _pending_payment_order(
            order_id=order_id,
            nonce=f"nonce_{order_id}",
            product=product,
            amount=amount,
            expires_at=now + timedelta(minutes=5),
        ),
    )
    if entitlement is not None:
        store.entitlements[order.user_id] = entitlement
    result = store.apply_successful_payment(
        PaymentSuccessfulPaymentInput(
            payload=order.payload,
            provider=order.provider,
            telegram_charge_id=charge_id,
            user_id=order.user_id,
            delivery_chat_id=order.delivery_chat_id,
            currency=order.currency,
            total_amount=order.amount,
        ),
        now=now,
    )
    assert result.processed is True
    return order


def _successful_payment_for_order(
    order: PaymentOrder,
    *,
    payload: str | None = None,
    telegram_charge_id: str = "tg-charge-1",
    provider_charge_id: str | None = None,
    currency: PaymentCurrency | str | None = None,
    total_amount: int | None = None,
    subscription_expiration_date: int | None = None,
) -> SimpleNamespace:
    payment_currency = currency or order.currency
    if isinstance(payment_currency, PaymentCurrency):
        payment_currency = payment_currency.value
    return SimpleNamespace(
        invoice_payload=payload or order.payload,
        currency=payment_currency,
        total_amount=order.amount if total_amount is None else total_amount,
        telegram_payment_charge_id=telegram_charge_id,
        provider_payment_charge_id=provider_charge_id,
        subscription_expiration_date=subscription_expiration_date,
    )


def _assert_admin_payment_response_is_redacted(response: str) -> None:
    for secret in (
        "tg-refund-secret",
        "tg-orphan-secret",
        "tg-ignore-secret",
        "buyer@example.com",
        "+79991234567",
        "order_info",
        "provider_data",
        "receipt",
        "customer",
        "123456789:ABCdefGhijKLMnopQRStuVWXyz",
        "381764678:TEST:provider-secret",
        "postgresql://diet_bot:secret@example.com/db",
        "order_refund_secret",
        "order_reconcile_secret",
        "evt_orphan_secret",
    ):
        assert secret not in response


def profile_with(**kwargs) -> UserProfile:
    data = {
        "age": 32,
        "sex": Sex.MALE,
        "height_cm": 178,
        "weight_kg": 86,
        "goal": Goal.LOSE,
        "activity": ActivityLevel.MODERATE,
        "meal_count": 4,
        "cooking_time": CookingTimePreference.SIMPLE,
    }
    data.update(kwargs)
    return UserProfile(**data)


def test_saved_profile_maps_legacy_cooking_time_values_to_effort_modes() -> None:
    raw_profile = {
        "age": 32,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 86,
        "goal": "lose",
        "activity": "moderate",
        "meal_count": 4,
    }

    quick_profile = telegram_app._profile_from_dict({**raw_profile, "cooking_time": "quick"})
    medium_profile = telegram_app._profile_from_dict({**raw_profile, "cooking_time": "medium"})
    long_profile = telegram_app._profile_from_dict({**raw_profile, "cooking_time": "long"})
    unknown_profile = telegram_app._profile_from_dict({**raw_profile, "cooking_time": "surprise"})

    assert quick_profile is not None
    assert medium_profile is not None
    assert long_profile is not None
    assert unknown_profile is not None
    assert quick_profile.cooking_time == CookingTimePreference.SIMPLE
    assert medium_profile.cooking_time == CookingTimePreference.SIMPLE
    assert long_profile.cooking_time == CookingTimePreference.INTERESTING
    assert unknown_profile.cooking_time == CookingTimePreference.SIMPLE
    assert telegram_app._profile_to_dict(long_profile)["cooking_time"] == "interesting"


def _telegram_one_day_plan_fixture() -> MealPlan:
    food = Food(
        id="one_day_sentinel_food",
        name="One Day Ingredient Sentinel",
        category="test",
        nutrients_per_100g=NutrientVector(
            {
                "energy_kcal": 200,
                "protein_g": 20,
                "fat_g": 8,
                "carbohydrate_g": 22,
            }
        ),
    )
    meal = Meal(
        "One Day Text Sentinel",
        (FoodPortion(food, 100),),
        "Cook the one day text sentinel.",
        recipe_id="one_day_sentinel_recipe",
        recipe_key="one-day:sentinel",
    )
    targets = NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector(
            {
                "energy_kcal": 200,
                "protein_g": 20,
                "fat_g": 8,
                "carbohydrate_g": 22,
            }
        ),
        calorie_bounds=(100, 300),
        macro_bounds={},
    )
    return MealPlan((meal,), targets, SafetyResult(can_generate_plan=True))


def _telegram_week_plan_fixture() -> tuple[MealPlan, ...]:
    food = Food(
        id="weekly_sentinel_food",
        name="Weekly Plan Ingredient Sentinel",
        category="test",
        nutrients_per_100g=NutrientVector({"energy_kcal": 100}),
    )
    meals = tuple(
        Meal(
            f"Weekly Plan Text Sentinel {index}",
            (FoodPortion(food, 100),),
            "Cook the weekly text sentinel.",
            recipe_id=f"weekly_sentinel_recipe_{index}",
            recipe_key=f"weekly:sentinel:{index}",
        )
        for index in range(3)
    )
    targets = NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector({"energy_kcal": 2000}),
        calorie_bounds=(1800, 2200),
        macro_bounds={},
    )
    plan = MealPlan(meals, targets, SafetyResult(can_generate_plan=True))
    return (plan,) * 7


def _patch_fast_week_plan(monkeypatch, tmp_path, pdf_bytes: bytes | None = b"%PDF-1.4\n%test\n%%EOF\n") -> Path:
    pdf_path = tmp_path / "week.pdf"
    plans = _telegram_week_plan_fixture()

    def fake_build_week_plans_with_recent_fallback(*_args, **_kwargs):
        return telegram_app._WeekPlanBuildResult(
            plans=plans,
            avoidance_phase="full_recent",
        )

    def fake_build_week_plan_pdf(_plans, _plan_dates):
        if pdf_bytes is None:
            raise RuntimeError("pdf failed")
        pdf_path.write_bytes(pdf_bytes)
        return pdf_path

    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(
        telegram_app,
        "_build_week_plans_with_recent_fallback",
        fake_build_week_plans_with_recent_fallback,
    )
    monkeypatch.setattr(telegram_app, "build_week_plan_pdf", fake_build_week_plan_pdf)
    monkeypatch.setattr(
        telegram_app,
        "_week_plan_dates",
        lambda today=None: tuple(date(2026, 5, day) for day in range(8, 15)),
    )
    return pdf_path


def _sent_text(message: FakeMessage) -> str:
    return "\n".join(text for text, _ in message.texts)


def _assert_weekly_text_fallback_not_sent(message: FakeMessage) -> None:
    sent_text = _sent_text(message)

    assert "Weekly Plan Text Sentinel" not in sent_text
    assert "Weekly Plan Ingredient Sentinel" not in sent_text


def _clear_week_plan_state(chat_id: int) -> None:
    PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
    PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
    RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
    RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


def _save_active_subscription(
    path: Path,
    chat_id: int,
    *,
    one_day_remaining: int,
    weekly_pdf_remaining: int,
    extra_one_day_remaining: int = 0,
    extra_weekly_pdf_remaining: int = 0,
) -> telegram_app.Entitlement:
    entitlement = telegram_app.Entitlement()
    telegram_app.apply_subscription_payment(
        entitlement,
        f"charge-{chat_id}",
        now=datetime(2026, 5, 8, tzinfo=UTC),
    )
    entitlement.monthly_one_day_remaining = one_day_remaining
    entitlement.monthly_weekly_pdf_remaining = weekly_pdf_remaining
    entitlement.extra_one_day_remaining = extra_one_day_remaining
    entitlement.extra_weekly_pdf_remaining = extra_weekly_pdf_remaining
    telegram_app.save_entitlements(path, {chat_id: entitlement})
    return entitlement


def _active_payment_entitlement() -> telegram_app.Entitlement:
    entitlement = telegram_app.Entitlement()
    telegram_app.apply_subscription_payment(
        entitlement,
        "charge-active",
        now=datetime(2026, 5, 8, tzinfo=UTC),
    )
    entitlement.subscription_period_end = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    return entitlement


@pytest.mark.anyio
async def test_set_bot_commands_registers_start_menu_commands() -> None:
    bot = FakeBot()

    await _set_bot_commands(bot)

    assert bot.commands == BOT_COMMANDS
    command_names = [command.command for command in bot.commands]
    assert "grant_test_access" not in command_names
    assert "330366" not in command_names
    assert "payment_event" not in command_names
    assert "admin" not in command_names
    assert "promo" not in command_names
    assert [(command.command, command.description) for command in bot.commands] == [
        ("start", "Открыть стартовое меню"),
        ("plan", "Показать мой расчет"),
        ("cancel", "Отменить текущее действие"),
    ]
    assert "myid" not in command_names


@pytest.mark.anyio
async def test_start_with_saved_profile_shows_calculation_summary_and_plan_buttons(monkeypatch, tmp_path) -> None:
    chat_id = 91_030
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    PROFILE_BY_CHAT_ID[chat_id] = profile_with()
    message = FakeMessage(chat_id, text="/start")
    try:
        await telegram_app.start(message)

        sent_text, markup = message.texts[-1]
        buttons = [row[0] for row in markup.inline_keyboard]

        assert sent_text.startswith("Анкета уже сохранена.")
        assert "Ваш расчет" in sent_text
        assert "ИМТ (индекс массы тела)" in sent_text
        assert "Поддерживающая калорийность" in sent_text
        assert "Питьевая вода" in sent_text
        assert "БЖУ" in sent_text
        assert [(button.text, button.callback_data) for button in buttons] == [
            (ONE_DAY_PLAN_TEXT, CALLBACK_ONE_DAY_PLAN),
            (WEEK_PLAN_PDF_TEXT, CALLBACK_WEEK_PLAN_PDF),
            (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
            (SUPPORT_TEXT, CALLBACK_SUPPORT),
        ]
    finally:
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_one_day_generation_still_sends_status_meal_and_final_keyboard(monkeypatch, tmp_path) -> None:
    chat_id = 91_032
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "build_one_day_plan", lambda *_args, **_kwargs: _telegram_one_day_plan_fixture())
    message = FakeMessage(chat_id)
    try:
        sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

        sent_text = _sent_text(message)
        final_text, final_markup = message.texts[-1]
        final_buttons = [row[0] for row in final_markup.inline_keyboard]

        assert sent is True
        assert message.texts[0][0].startswith("Считаю рацион")
        assert "One Day Text Sentinel" in sent_text
        assert "🛒 Список продуктов" in final_text
        assert [(button.text, button.callback_data) for button in final_buttons] == [
            (telegram_app.REPEAT_PLAN_TEXT, telegram_app.CALLBACK_REPEAT),
            (telegram_app.NEW_PROFILE_TEXT, CALLBACK_NEW),
            (SUPPORT_TEXT, CALLBACK_SUPPORT),
        ]
    finally:
        _clear_week_plan_state(chat_id)


@pytest.mark.anyio
async def test_cancel_clarifies_saved_profile_is_kept() -> None:
    chat_id = 91_031
    saved_profile = profile_with()
    SESSION_BY_CHAT_ID[chat_id] = start_session()
    TRIAL_CHAT_IDS.add(chat_id)
    SUPPORT_REQUEST_CHAT_IDS.add(chat_id)
    PROMO_CODE_REQUEST_CHAT_IDS.add(chat_id)
    PROFILE_BY_CHAT_ID[chat_id] = saved_profile
    message = FakeMessage(chat_id, text="/cancel")
    try:
        await telegram_app.cancel(message)

        sent_text, markup = message.texts[-1]
        buttons = [row[0] for row in markup.inline_keyboard]

        assert chat_id not in SESSION_BY_CHAT_ID
        assert chat_id not in TRIAL_CHAT_IDS
        assert chat_id not in SUPPORT_REQUEST_CHAT_IDS
        assert chat_id not in PROMO_CODE_REQUEST_CHAT_IDS
        assert PROFILE_BY_CHAT_ID[chat_id] is saved_profile
        assert sent_text.startswith("Текущее действие отменено")
        assert "Сохраненная анкета осталась" in sent_text
        assert CHANGE_PROFILE_TEXT in sent_text
        assert "Анкета сброшена" not in sent_text
        assert [(button.text, button.callback_data) for button in buttons] == [
            (ONE_DAY_PLAN_TEXT, CALLBACK_ONE_DAY_PLAN),
            (WEEK_PLAN_PDF_TEXT, CALLBACK_WEEK_PLAN_PDF),
            (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
            (SUPPORT_TEXT, CALLBACK_SUPPORT),
        ]
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        TRIAL_CHAT_IDS.discard(chat_id)
        SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
        PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_myid_reports_chat_and_user_ids() -> None:
    message = FakeMessage(chat_id=22_222, user_id=11_111)

    await myid(message)

    sent_text = message.texts[-1][0]
    assert "chat_id: 22222" in sent_text
    assert "user_id: 11111" in sent_text


@pytest.mark.anyio
async def test_myid_fallback_works_from_catch_all_handler() -> None:
    message = FakeMessage(chat_id=33_333, text="/myid@FoodBalanceBot", user_id=44_444)

    await handle_answer(message)

    sent_text = message.texts[-1][0]
    assert "chat_id: 33333" in sent_text
    assert "user_id: 44444" in sent_text


@pytest.mark.anyio
async def test_numeric_test_access_command_requires_admin_for_target(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {700})
    message = FakeMessage(
        chat_id=700,
        text="/330366 91002",
        user_id=701,
    )

    await secret_access_command(message)

    assert message.texts
    assert not (tmp_path / "subscriptions.json").exists()


@pytest.mark.anyio
async def test_admin_can_grant_persistent_test_access(monkeypatch, tmp_path) -> None:
    target_chat_id = 91_002
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {700})
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", set())
    message = FakeMessage(
        chat_id=700,
        text=f"/330366 {target_chat_id}",
        user_id=700,
    )

    await secret_access_command(message)

    entitlements = telegram_app.load_entitlements(tmp_path / "subscriptions.json")
    entitlement = entitlements[target_chat_id]
    assert entitlement.is_test_access_active()
    assert _consume_generation_attempt(target_chat_id, "weekly_pdf").source == "test_access"
    assert "PDF" not in _format_entitlement_status(target_chat_id)


@pytest.mark.anyio
async def test_tester_can_toggle_test_access_mode(monkeypatch, tmp_path) -> None:
    target_chat_id = 91_003
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {700})
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", set())

    await secret_access_command(FakeMessage(chat_id=700, text=f"/330366 {target_chat_id}", user_id=700))
    await secret_access_command(FakeMessage(chat_id=target_chat_id, text="/330366 off", user_id=target_chat_id))

    assert not _consume_generation_attempt(target_chat_id, "weekly_pdf").allowed

    await secret_access_command(FakeMessage(chat_id=target_chat_id, text="/330366 on", user_id=target_chat_id))

    assert _consume_generation_attempt(target_chat_id, "weekly_pdf").source == "test_access"


@pytest.mark.anyio
async def test_test_access_off_previews_free_menu_even_with_subscription(monkeypatch, tmp_path) -> None:
    target_chat_id = 91_013
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", set())
    entitlement = _save_active_subscription(
        subscriptions_path,
        target_chat_id,
        one_day_remaining=4,
        weekly_pdf_remaining=3,
    )
    telegram_app.grant_test_access(entitlement, now=datetime(2026, 5, 8, tzinfo=UTC))
    telegram_app.save_entitlements(subscriptions_path, {target_chat_id: entitlement})
    PROFILE_BY_CHAT_ID[target_chat_id] = profile_with()

    try:
        await secret_access_command(
            FakeMessage(chat_id=target_chat_id, text="/330366 off", user_id=target_chat_id),
        )
        message = FakeMessage(target_chat_id)

        await telegram_app.start(message)
        weekly_consumption = _consume_generation_attempt(target_chat_id, "weekly_pdf")
        one_day_consumption = _consume_generation_attempt(target_chat_id, "one_day")
        paywall_message = FakeMessage(target_chat_id)
        await telegram_app._send_limit_paywall(paywall_message, "weekly_pdf")

        sent_text, markup = message.texts[-1]
        paywall_text, _ = paywall_message.texts[-1]
        buttons = [row[0] for row in markup.inline_keyboard]
        saved_entitlement = telegram_app.load_entitlements(subscriptions_path)[target_chat_id]

        assert not telegram_app._has_active_paid_access(target_chat_id)
        assert sent_text.startswith("Анкета уже сохранена.")
        assert [(button.text, button.callback_data) for button in buttons] == [
            (ONE_DAY_PLAN_TEXT, CALLBACK_ONE_DAY_PLAN),
            (WEEK_PLAN_PDF_TEXT, CALLBACK_WEEK_PLAN_PDF),
            (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
            (SUPPORT_TEXT, CALLBACK_SUPPORT),
        ]
        assert not weekly_consumption.allowed
        assert one_day_consumption.source == "free_trial"
        assert "Следующее обновление подписки" not in paywall_text
        assert "бесплатный сценарий" in paywall_text
        assert saved_entitlement.is_subscription_active()
        assert saved_entitlement.monthly_one_day_remaining == 4
        assert saved_entitlement.monthly_weekly_pdf_remaining == 3
    finally:
        PROFILE_BY_CHAT_ID.pop(target_chat_id, None)


@pytest.mark.anyio
async def test_week_plan_sends_pdf_document(monkeypatch, tmp_path) -> None:
    chat_id = 92_001
    pdf_path = _patch_fast_week_plan(monkeypatch, tmp_path)
    message = FakeMessage(chat_id)
    history_entries = []
    try:
        sent = await _send_week_plan(
            message,
            profile_with(meal_count=3),
            recipe_history_entries=history_entries,
        )

        assert sent is True
        assert len(message.documents) == 1
        document = message.documents[0]["document"]
        assert isinstance(document, BufferedInputFile)
        assert document.filename == "week.pdf"
        assert document.data == b"%PDF-1.4\n%test\n%%EOF\n"
        assert message.documents[0]["reply_markup"] is not None
        assert not pdf_path.exists()
        assert message.texts[0][0].startswith("Собираю недельный PDF")
        assert message.edits
        assert message.edits[-1][0] == "Готово. PDF отправлен ниже."
        assert message.bot.chat_actions
        assert len(history_entries) == 21
        assert {entry.recipe_id for entry in history_entries} == {
            "weekly_sentinel_recipe_0",
            "weekly_sentinel_recipe_1",
            "weekly_sentinel_recipe_2",
        }
        assert {entry.ration_kind for entry in history_entries} == {"weekly_pdf"}
        assert [entry.day_index for entry in history_entries] == [
            day_index for day_index in range(7) for _ in range(3)
        ]
        assert [entry.meal_index for entry in history_entries] == [0, 1, 2] * 7
        _assert_weekly_text_fallback_not_sent(message)
    finally:
        _clear_week_plan_state(chat_id)


@pytest.mark.anyio
async def test_week_plan_render_failure_does_not_send_text_fallback(monkeypatch, tmp_path) -> None:
    chat_id = 92_002
    _patch_fast_week_plan(monkeypatch, tmp_path, pdf_bytes=None)
    message = FakeMessage(chat_id)
    history_entries = []
    try:
        sent = await _send_week_plan(
            message,
            profile_with(meal_count=3),
            recipe_history_entries=history_entries,
        )

        assert sent is False
        assert message.documents == []
        assert message.edits
        assert "PDF" in message.edits[-1][0]
        assert history_entries == []
        _assert_weekly_text_fallback_not_sent(message)
    finally:
        _clear_week_plan_state(chat_id)


@pytest.mark.anyio
async def test_week_plan_oversize_pdf_does_not_send_text_fallback(monkeypatch, tmp_path) -> None:
    chat_id = 92_003
    _patch_fast_week_plan(monkeypatch, tmp_path, pdf_bytes=b"oversized pdf payload")
    monkeypatch.setattr(telegram_app, "TELEGRAM_DOCUMENT_MAX_BYTES", 5)
    message = FakeMessage(chat_id)
    history_entries = []
    try:
        sent = await _send_week_plan(
            message,
            profile_with(meal_count=3),
            recipe_history_entries=history_entries,
        )

        assert sent is False
        assert message.documents == []
        assert message.edits
        assert "PDF" in message.edits[-1][0]
        assert history_entries == []
        _assert_weekly_text_fallback_not_sent(message)
    finally:
        _clear_week_plan_state(chat_id)


@pytest.mark.anyio
async def test_week_plan_document_send_failure_does_not_send_text_fallback(monkeypatch, tmp_path) -> None:
    chat_id = 92_004
    _patch_fast_week_plan(monkeypatch, tmp_path)
    message = FailingDocumentMessage(chat_id)
    history_entries = []
    try:
        sent = await _send_week_plan(
            message,
            profile_with(meal_count=3),
            recipe_history_entries=history_entries,
        )

        assert sent is False
        assert len(message.document_attempts) == 1
        assert message.documents == []
        assert message.edits
        assert "PDF" in message.edits[-1][0]
        assert history_entries == []
        _assert_weekly_text_fallback_not_sent(message)
    finally:
        _clear_week_plan_state(chat_id)


@pytest.mark.anyio
async def test_week_plan_with_access_refunds_limit_when_pdf_not_delivered(monkeypatch, tmp_path) -> None:
    chat_id = 92_005
    subscriptions_path = tmp_path / "subscriptions.json"
    _save_active_subscription(subscriptions_path, chat_id, one_day_remaining=1, weekly_pdf_remaining=1)

    async def fake_send_week_plan(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)
    message = FakeMessage(chat_id)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())
    entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]

    assert sent is False
    assert entitlement.monthly_weekly_pdf_remaining == 1


@pytest.mark.anyio
async def test_answer_callback_marks_selected_option_and_sends_next_question(monkeypatch) -> None:
    chat_id = 91_000
    session, error = start_session().receive("32")
    assert error is None
    question = session.current_question
    SESSION_BY_CHAT_ID[chat_id] = session
    message = FakeMessage(chat_id)
    callback = FakeCallback(f"{telegram_app.CALLBACK_ANSWER_PREFIX}1", message)
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    try:
        await telegram_app.handle_callback(callback)

        edited_markup, edit_kwargs = message.reply_markup_edits[-1]
        button_texts = [row[0].text for row in edited_markup.inline_keyboard]
        assert edit_kwargs == {}
        assert sum(text.startswith("✅ ") for text in button_texts) == 1
        assert button_texts[0] == question.options[0]
        assert button_texts[1] == f"✅ {question.options[1]}"

        assert SESSION_BY_CHAT_ID[chat_id].current_question.key == "height_cm"
        sent_text, sent_markup = message.texts[-1]
        assert sent_text == SESSION_BY_CHAT_ID[chat_id].current_question.prompt
        assert sent_markup is None
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_questionnaire_completion_sends_calculation_and_plan_buttons(monkeypatch, tmp_path) -> None:
    chat_id = 91_001
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    SESSION_BY_CHAT_ID[chat_id] = start_session()
    message = FakeMessage(chat_id)
    try:
        for answer in [
            "32",
            "мужчина",
            "178",
            "86",
            "похудение",
            "умеренная",
            "4",
            "Побыстрее и попроще",
            "нет",
            "нет",
            "нет",
            "нет",
        ]:
            await _handle_questionnaire_answer(message, answer)

        assert chat_id not in SESSION_BY_CHAT_ID
        assert PROFILE_BY_CHAT_ID[chat_id].cooking_time == "simple"
        sent_text, markup = message.texts[-1]
        assert "Анкета сохранена" in sent_text
        assert "Ваш расчет" in sent_text
        assert CHANGE_PROFILE_TEXT in sent_text
        assert "Считаю рацион" not in "\n".join(text for text, _ in message.texts)
        assert [(row[0].text, row[0].callback_data) for row in markup.inline_keyboard] == [
            (ONE_DAY_PLAN_TEXT, CALLBACK_ONE_DAY_PLAN),
            (WEEK_PLAN_PDF_TEXT, CALLBACK_WEEK_PLAN_PDF),
            (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
            (SUPPORT_TEXT, CALLBACK_SUPPORT),
        ]
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_saved_questionnaire_profile_survives_memory_reset(monkeypatch, tmp_path) -> None:
    chat_id = 91_021
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    SESSION_BY_CHAT_ID[chat_id] = start_session()
    message = FakeMessage(chat_id)
    try:
        for answer in [
            "32",
            "мужчина",
            "178",
            "86",
            "похудение",
            "умеренная",
            "4",
            "Побыстрее и попроще",
            "нет",
            "нет",
            "нет",
            "грибы",
        ]:
            await _handle_questionnaire_answer(message, answer)

        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        restored_profile = _profile_for_chat(chat_id)
        plan_message = FakeMessage(chat_id)
        await telegram_app.plan(plan_message)

        sent_text, markup = plan_message.texts[-1]
        buttons = [row[0] for row in markup.inline_keyboard]

        assert restored_profile is not None
        assert restored_profile.weight_kg == 86
        assert restored_profile.restrictions[-1].value == "грибы"
        assert chat_id not in SESSION_BY_CHAT_ID
        assert "Ваш расчет" in sent_text
        assert [(button.text, button.callback_data) for button in buttons] == [
            (ONE_DAY_PLAN_TEXT, CALLBACK_ONE_DAY_PLAN),
            (WEEK_PLAN_PDF_TEXT, CALLBACK_WEEK_PLAN_PDF),
            (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
            (SUPPORT_TEXT, CALLBACK_SUPPORT),
        ]
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_subscriber_can_change_questionnaire_without_losing_limits(monkeypatch, tmp_path) -> None:
    chat_id = 91_011
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    _save_active_subscription(subscriptions_path, chat_id, one_day_remaining=2, weekly_pdf_remaining=1)
    before = telegram_app.load_entitlements(subscriptions_path)[chat_id].to_dict()
    message = FakeMessage(chat_id, text=CHANGE_PROFILE_TEXT)
    try:
        await handle_answer(message)

        for answer in [
            "32",
            "мужчина",
            "178",
            "86",
            "похудение",
            "умеренная",
            "4",
            "до 15 минут",
            "нет",
            "нет",
            "нет",
            "нет",
        ]:
            await _handle_questionnaire_answer(message, answer)

        after = telegram_app.load_entitlements(subscriptions_path)[chat_id].to_dict()
        sent_text, markup = message.texts[-1]
        buttons = [row[0] for row in markup.inline_keyboard]

        assert before == after
        assert chat_id not in SESSION_BY_CHAT_ID
        assert "Ваш расчет" in sent_text
        assert [(button.text, button.callback_data) for button in buttons] == [
            (f"{SUBSCRIBER_ONE_DAY_PLAN_TEXT} - осталось 2 из 5", CALLBACK_ONE_DAY_PLAN),
            (f"{SUBSCRIBER_WEEK_PLAN_PDF_TEXT} - осталось 1 из 4", CALLBACK_WEEK_PLAN_PDF),
            (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
            (SUPPORT_TEXT, CALLBACK_SUPPORT),
        ]
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_trial_questionnaire_completion_sends_one_day_plan_and_subscription_cta(monkeypatch, tmp_path) -> None:
    chat_id = 91_002
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    SESSION_BY_CHAT_ID[chat_id] = start_session()
    TRIAL_CHAT_IDS.add(chat_id)
    message = FakeMessage(chat_id)
    try:
        for answer in [
            "32",
            "мужчина",
            "178",
            "86",
            "похудение",
            "умеренная",
            "4",
            "до 15 минут",
            "нет",
            "нет",
            "нет",
            "нет",
        ]:
            await _handle_questionnaire_answer(message, answer)

        sent_text = "\n".join(text for text, _ in message.texts)
        final_text, final_markup = message.texts[-1]

        assert chat_id not in SESSION_BY_CHAT_ID
        assert chat_id not in TRIAL_CHAT_IDS
        assert PROFILE_BY_CHAT_ID[chat_id].cooking_time == "simple"
        assert "Ваш расчет" in sent_text
        assert "Считаю рацион" in sent_text
        assert final_text.startswith(TRIAL_SUBSCRIPTION_TEXT)
        assert "Рационы на 1 день: 0 из 5" in final_text
        assert final_markup.inline_keyboard[0][0].text == SUBSCRIBE_CTA_TEXT
        assert final_markup.inline_keyboard[0][0].callback_data == CALLBACK_SUBSCRIBE
        assert all(
            not (
                hasattr(markup, "inline_keyboard")
                and [(row[0].text, row[0].callback_data) for row in markup.inline_keyboard]
                == [
                    (ONE_DAY_PLAN_TEXT, CALLBACK_ONE_DAY_PLAN),
                    (WEEK_PLAN_PDF_TEXT, CALLBACK_WEEK_PLAN_PDF),
                    (CHANGE_PROFILE_TEXT, CALLBACK_NEW),
                    (SUPPORT_TEXT, CALLBACK_SUPPORT),
                ]
            )
            for _, markup in message.texts
        )
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        TRIAL_CHAT_IDS.discard(chat_id)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_long_meal_card_sends_photo_without_duplicate_title() -> None:
    meal = Meal(
        name="🌙 Ужин: Боул с бататом, фасолью и рисом",
        portions=(),
        recipe=" ".join(["Подробное приготовление блюда."] * 80),
        image_url="https://example.com/photo.jpg",
    )
    message = FakeMessage()

    await _send_meal_card(message, meal)

    assert message.photos == [{"photo": "https://example.com/photo.jpg"}]
    assert len(message.texts) == 1
    sent_text = message.texts[0][0]
    assert sent_text.count("🌙 Ужин: Боул с бататом, фасолью и рисом") == 1


@pytest.mark.anyio
async def test_welcome_photo_sends_local_asset() -> None:
    message = FakeMessage()

    await _send_welcome_photo(message)

    assert len(message.photos) == 1
    photo = message.photos[0]["photo"]
    assert isinstance(photo, FSInputFile)
    assert Path(photo.path) == WELCOME_PHOTO_PATH
