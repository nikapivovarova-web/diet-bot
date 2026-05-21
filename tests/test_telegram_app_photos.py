import json
from datetime import UTC, date, datetime
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
from diet_bot.presentation import format_meal_card, format_week_shopping_list
from diet_bot.promo_codes import PromoCodeRecord, load_promo_codes, save_promo_codes
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
        assert message.texts[-1] == (PROMO_CODE_PROMPT_TEXT, None)
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
    ]


def test_pre_checkout_validates_payload_currency_and_amount() -> None:
    valid_query = SimpleNamespace(
        invoice_payload=PAYLOAD_SUBSCRIPTION_MONTH,
        currency="XTR",
        total_amount=PAYMENT_PAYLOAD_AMOUNTS[PAYLOAD_SUBSCRIPTION_MONTH],
    )
    wrong_amount_query = SimpleNamespace(
        invoice_payload=PAYLOAD_SUBSCRIPTION_MONTH,
        currency="XTR",
        total_amount=PAYMENT_PAYLOAD_AMOUNTS[PAYLOAD_SUBSCRIPTION_MONTH] + 1,
    )
    wrong_currency_query = SimpleNamespace(
        invoice_payload=PAYLOAD_SUBSCRIPTION_MONTH,
        currency="RUB",
        total_amount=PAYMENT_PAYLOAD_AMOUNTS[PAYLOAD_SUBSCRIPTION_MONTH],
    )
    valid_rub_query = SimpleNamespace(
        invoice_payload=telegram_app.PAYLOAD_RU_SUBSCRIPTION_MONTH,
        currency="RUB",
        total_amount=telegram_app.RUB_PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_RU_SUBSCRIPTION_MONTH],
    )
    wrong_rub_amount_query = SimpleNamespace(
        invoice_payload=telegram_app.PAYLOAD_RU_SUBSCRIPTION_MONTH,
        currency="RUB",
        total_amount=telegram_app.RUB_PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_RU_SUBSCRIPTION_MONTH] + 1,
    )
    unknown_payload_query = SimpleNamespace(
        invoice_payload="diet:rub:unknown",
        currency="RUB",
        total_amount=0,
    )

    assert _is_valid_pre_checkout(valid_query)
    assert not _is_valid_pre_checkout(wrong_amount_query)
    assert not _is_valid_pre_checkout(wrong_currency_query)
    assert _is_valid_pre_checkout(valid_rub_query)
    assert not _is_valid_pre_checkout(wrong_rub_amount_query)
    assert not _is_valid_pre_checkout(unknown_payload_query)


@pytest.mark.anyio
async def test_send_subscription_invoice_link_creates_recurring_stars_invoice() -> None:
    message = FakeMessage()

    await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)

    invoice = message.bot.invoice_links[0]
    assert invoice["currency"] == "XTR"
    assert invoice["provider_token"] == ""
    assert invoice["payload"] == PAYLOAD_SUBSCRIPTION_MONTH
    assert invoice["prices"][0].amount == SUBSCRIPTION_STARS_AMOUNT
    assert invoice["subscription_period"] == 2_592_000
    assert message.texts[-1][1].inline_keyboard[0][0].url == "https://t.me/invoice/test"


@pytest.mark.anyio
async def test_send_extra_day_invoice_link_creates_one_time_stars_invoice() -> None:
    message = FakeMessage()

    await _send_stars_invoice_link(message, PAYLOAD_EXTRA_ONE_DAY)

    invoice = message.bot.invoice_links[0]
    assert invoice["currency"] == "XTR"
    assert invoice["payload"] == PAYLOAD_EXTRA_ONE_DAY
    assert invoice["prices"][0].amount == 35
    assert invoice["subscription_period"] is None


@pytest.mark.anyio
async def test_ru_card_callback_creates_yookassa_invoice_with_receipt(monkeypatch) -> None:
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
    assert invoice["payload"] == telegram_app.PAYLOAD_RU_SUBSCRIPTION_MONTH
    assert invoice["prices"][0].amount == 59_900
    assert invoice["need_email"] is True
    assert invoice["send_email_to_provider"] is True
    assert item == {
        "description": "FoodBalance: подписка на месяц",
        "quantity": "1.00",
        "amount": {
            "value": "599.00",
            "currency": "RUB",
        },
        "vat_code": 1,
        "payment_mode": "full_payment",
        "payment_subject": "service",
    }
    assert message.texts[-1][0] == "FoodBalance: подписка на месяц\n\nСтоимость: 599 ₽."
    assert message.texts[-1][1].inline_keyboard[0][0].url == "https://t.me/invoice/test"


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
        self.bot = FakeInvoiceBot()
        self.photos = []
        self.texts = []
        self.documents = []
        self.edits = []

    async def answer_photo(self, **kwargs) -> None:
        self.photos.append(kwargs)

    async def answer(self, text, reply_markup=None):
        self.texts.append((text, reply_markup))
        return FakeSentMessage(self)

    async def answer_document(self, **kwargs) -> None:
        self.documents.append(kwargs)


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message
        self.answers = []

    async def answer(self, text=None) -> None:
        self.answers.append(text)


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


def profile_with(**kwargs) -> UserProfile:
    data = {
        "age": 32,
        "sex": Sex.MALE,
        "height_cm": 178,
        "weight_kg": 86,
        "goal": Goal.LOSE,
        "activity": ActivityLevel.MODERATE,
        "meal_count": 4,
        "cooking_time": CookingTimePreference.QUICK,
    }
    data.update(kwargs)
    return UserProfile(**data)


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


@pytest.mark.anyio
async def test_set_bot_commands_registers_start_menu_commands() -> None:
    bot = FakeBot()

    await _set_bot_commands(bot)

    assert bot.commands == BOT_COMMANDS
    assert "grant_test_access" not in [command.command for command in bot.commands]
    assert "330366" not in [command.command for command in bot.commands]
    assert [(command.command, command.description) for command in bot.commands] == [
        ("start", "Открыть стартовое меню"),
        ("plan", "Заполнить анкету для рациона"),
        ("cancel", "Сбросить активную анкету"),
    ]
    assert "myid" not in [command.command for command in bot.commands]


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
    pdf_path = tmp_path / "week.pdf"

    def fake_build_week_plan_pdf(plans, plan_dates):
        assert len(plans) == 7
        assert len(plan_dates) == 7
        pdf_path.write_bytes(b"%PDF-1.4\n%test\n%%EOF\n")
        return pdf_path

    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "build_week_plan_pdf", fake_build_week_plan_pdf)
    message = FakeMessage(chat_id)
    try:
        sent = await _send_week_plan(message, profile_with())

        assert sent
        assert len(message.documents) == 1
        document = message.documents[0]["document"]
        assert isinstance(document, BufferedInputFile)
        assert document.filename == telegram_app._week_pdf_download_filename(_week_plan_dates())
        assert document.data == b"%PDF-1.4\n%test\n%%EOF\n"
        assert message.documents[0]["reply_markup"] is not None
        assert not pdf_path.exists()
        assert "PDF" in message.texts[0][0]
        assert message.edits
        assert message.edits[-1][0] == telegram_app.WEEK_PDF_DONE_TEXT
        assert message.bot.chat_actions
        assert not any("День 1" in text for text, _ in message.texts[1:])
    finally:
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_week_plan_pdf_failure_does_not_send_text_fallback(monkeypatch, tmp_path) -> None:
    chat_id = 92_002

    def failing_build_week_plan_pdf(plans, plan_dates):
        raise RuntimeError("pdf failed")

    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "build_week_plan_pdf", failing_build_week_plan_pdf)
    message = FakeMessage(chat_id)
    try:
        sent = await _send_week_plan(message, profile_with())

        sent_text = "\n".join(text for text, _ in message.texts)
        assert not sent
        assert message.documents == []
        assert message.edits
        assert message.edits[-1][0] == telegram_app.WEEK_PDF_FAILURE_TEXT
        assert "PDF" in sent_text
        assert "\u0414\u0435\u043d\u044c 1" not in sent_text
        assert "\u041e\u0431\u0449\u0438\u0439 \u0441\u043f\u0438\u0441\u043e\u043a \u043f\u043e\u043a\u0443\u043f\u043e\u043a" not in sent_text
    finally:
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


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
            "до 15 минут",
            "нет",
            "нет",
            "нет",
            "нет",
        ]:
            await _handle_questionnaire_answer(message, answer)

        assert chat_id not in SESSION_BY_CHAT_ID
        assert PROFILE_BY_CHAT_ID[chat_id].cooking_time == "quick"
        sent_text, markup = message.texts[-1]
        assert "Ваш расчет" in sent_text
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
            "до 15 минут",
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
        assert PROFILE_BY_CHAT_ID[chat_id].cooking_time == "quick"
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
