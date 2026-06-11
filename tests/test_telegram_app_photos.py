import asyncio
import json
import logging
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, FSInputFile

import diet_bot.telegram_app as telegram_app
from diet_bot.chat_state_storage import ChatStateStorageError
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
from diet_bot.payments import (
    PRODUCT_EXTRA_ONE_DAY,
    PRODUCT_EXTRA_WEEKLY_PDF,
    PRODUCT_SUBSCRIPTION_MONTH,
    PROVIDER_TELEGRAM_STARS,
    PROVIDER_YOOKASSA,
    PaymentHandlingResult,
    PaymentOrder,
    PaymentValidationResult,
    decode_payment_order_payload,
    encode_payment_order_payload,
)
from diet_bot.payment_recovery_spool import (
    ALLOWED_SERIALIZED_FIELDS,
    append_payment_recovery_record as write_payment_recovery_record,
    read_payment_recovery_records,
)
from diet_bot.telegram_media_validation import (
    TELEGRAM_MESSAGE_MAX_CHARS,
    TelegramMediaValidationError,
)
from diet_bot.one_day_generation_jobs import (
    AdmitJobResult,
    AdmitJobResultStatus as OneDayAdmitJobResultStatus,
    FinishJobResult,
    FinishJobResultStatus as OneDayFinishJobResultStatus,
    MarkSendStartedResult,
    MarkSendStartedResultStatus as OneDayMarkSendStartedResultStatus,
    MarkValueMessageDeliveredResult,
    MarkValueMessageDeliveredResultStatus,
    OneDayGenerationJob,
    OneDayGenerationRequestSnapshot,
    QueuedJobAdmissionResult,
    QueuedJobAdmissionResultStatus,
    SetExpectedValueMessagesResult,
    SetExpectedValueMessagesResultStatus,
    StartJobResult,
    StartJobResultStatus as OneDayStartJobResultStatus,
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
    CALLBACK_REPEAT,
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
from diet_bot.questionnaire import QUESTIONS, start_session

PRIVACY_URL = "https://foodbalance.example/privacy"
PRIVACY_POLICY_TEXT = "\u041f\u043e\u043b\u0438\u0442\u0438\u043a\u0430 \u043a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u0438"
CHAT_STATE_READ_ERROR_TEXT = "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435 \u0447\u0430\u0442\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435."


def _set_payments_enabled_from_env(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", telegram_app._payments_enabled_from_env(), raising=False)


def _set_support_chat_id_from_env(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID", telegram_app._support_chat_id_from_env(), raising=False)


def _button_callbacks(markup) -> list[str | None]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def _button_text_urls(markup) -> list[tuple[str, str | None]]:
    return [(button.text, button.url) for row in markup.inline_keyboard for button in row]


def _first_callback_data_from_last_message(message) -> str:
    _text, markup = message.texts[-1]
    assert markup is not None
    return markup.inline_keyboard[0][0].callback_data


def _sample_questionnaire_answer(question) -> str:
    if question.options:
        return question.options[0]
    return {
        "age": "32",
        "height_cm": "178",
        "weight_kg": "86",
    }[question.key]


async def _advance_questionnaire_to(message, question_key: str) -> None:
    while True:
        session = SESSION_BY_CHAT_ID.get(message.chat.id)
        assert session is not None
        question = session.current_question
        assert question is not None
        if question.key == question_key:
            return
        await _handle_questionnaire_answer(message, _sample_questionnaire_answer(question))


class FakePromoEntitlementService:
    def __init__(self, *, fail_grants: int = 0) -> None:
        self.fail_grants = fail_grants
        self.grants: list[tuple[int, str]] = []
        self.entitlements: dict[int, telegram_app.Entitlement] = {}

    def apply_subscription_payment(self, chat_id: int, charge_id: str):
        if self.fail_grants:
            self.fail_grants -= 1
            raise telegram_app.EntitlementStorageError("grant failed")
        entitlement = self.entitlements.get(chat_id, telegram_app.Entitlement())
        result = telegram_app.apply_subscription_payment(entitlement, charge_id)
        self.entitlements[chat_id] = entitlement
        self.grants.append((chat_id, charge_id))
        return result

    def get_entitlement(self, chat_id: int) -> telegram_app.Entitlement:
        return self.entitlements.get(chat_id, telegram_app.Entitlement())


@pytest.fixture(autouse=True)
def _enable_payments_for_existing_payment_ui_tests(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", True, raising=False)


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


def test_photo_input_rejects_invalid_local_file_before_telegram(tmp_path: Path) -> None:
    meal = Meal(
        name="Test meal",
        portions=(),
        recipe="Test recipe",
        image_url=str(tmp_path),
    )

    with pytest.raises(TelegramMediaValidationError, match="regular file"):
        _photo_input(meal)


def test_start_keyboard_has_welcome_buttons(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None, raising=False)

    keyboard = _start_keyboard()
    buttons = [row[0] for row in keyboard.inline_keyboard]

    assert [(button.text, button.callback_data) for button in buttons] == [
        (TRY_FREE_TEXT, CALLBACK_START),
        (SUBSCRIBE_MONTH_TEXT, CALLBACK_SUBSCRIBE),
        (FEATURES_TEXT, CALLBACK_FEATURES),
        (PROMO_CODE_TEXT, CALLBACK_PROMO_CODE),
        (SUPPORT_TEXT, CALLBACK_SUPPORT),
        (PRIVACY_POLICY_TEXT, telegram_app.CALLBACK_PRIVACY_POLICY),
    ]
    assert "FoodBalance" in WELCOME_TEXT
    assert WELCOME_PHOTO_PATH.exists()


def test_start_keyboard_includes_privacy_url_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", PRIVACY_URL, raising=False)

    keyboard = _start_keyboard()

    assert (PRIVACY_POLICY_TEXT, PRIVACY_URL) in _button_text_urls(keyboard)


def test_start_keyboard_includes_privacy_callback_when_url_absent(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None, raising=False)

    keyboard = _start_keyboard()

    assert (PRIVACY_POLICY_TEXT, telegram_app.CALLBACK_PRIVACY_POLICY) in [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]


@pytest.mark.anyio
async def test_questionnaire_start_does_not_repeat_privacy_between_questions(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", PRIVACY_URL, raising=False)
    message = FakeMessage()

    await telegram_app._start_questionnaire(message)

    sent_text, markup = message.texts[-1]
    assert sent_text == start_session().current_question.prompt
    buttons = [] if markup is None else _button_text_urls(markup)
    assert (PRIVACY_POLICY_TEXT, PRIVACY_URL) not in buttons


@pytest.mark.anyio
async def test_free_trial_callback_shows_privacy_consent_before_first_question(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None, raising=False)
    chat_id = 51_004
    message = FakeMessage(chat_id)
    callback = FakeCallback(telegram_app.CALLBACK_START, message)

    try:
        await telegram_app.handle_callback(callback)

        text, reply_markup = message.texts[-1]
        buttons = [
            (button.text, button.callback_data)
            for row in reply_markup.inline_keyboard
            for button in row
        ]
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
        telegram_app.PRIVACY_CONSENT_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_privacy_consent_acceptance_continues_to_first_question(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None, raising=False)
    chat_id = 51_005
    message = FakeMessage(chat_id)
    callback = FakeCallback(telegram_app.CALLBACK_PRIVACY_CONSENT_TRIAL, message)

    try:
        await telegram_app.handle_callback(callback)

        text, reply_markup = message.texts[-1]
        assert text == start_session().current_question.prompt
        assert chat_id in telegram_app.PRIVACY_CONSENT_CHAT_IDS
        assert chat_id in telegram_app.SESSION_BY_CHAT_ID
        assert chat_id in telegram_app.TRIAL_CHAT_IDS
        buttons = [] if reply_markup is None else [
            (button.text, button.callback_data)
            for row in reply_markup.inline_keyboard
            for button in row
        ]
        assert (telegram_app.PRIVACY_POLICY_TEXT, telegram_app.CALLBACK_PRIVACY_POLICY) not in buttons
    finally:
        telegram_app.SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.TRIAL_CHAT_IDS.discard(chat_id)
        telegram_app.PRIVACY_CONSENT_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_privacy_policy_callback_is_reachable_without_external_url(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None, raising=False)
    message = FakeMessage(51_006)
    callback = FakeCallback(telegram_app.CALLBACK_PRIVACY_POLICY, message)

    await telegram_app.handle_callback(callback)

    text, reply_markup = message.texts[-1]
    assert "FoodBalance" in text
    assert (telegram_app.SUPPORT_TEXT, telegram_app.CALLBACK_SUPPORT) in [
        (button.text, button.callback_data)
        for row in reply_markup.inline_keyboard
        for button in row
    ]


@pytest.mark.anyio
async def test_run_bot_startup_rejects_production_json_before_bot(monkeypatch) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:test-token")
    monkeypatch.setenv("DIET_BOT_ENV", "production")
    monkeypatch.setenv("DIET_BOT_STORAGE_BACKEND", "json")
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://user:secret@example/db")

    def fail_bot(_token):
        raise AssertionError("Bot must not be constructed for invalid runtime config")

    monkeypatch.setattr(telegram_app, "Bot", fail_bot)

    with pytest.raises(RuntimeError, match="JSON storage is not allowed in production"):
        await telegram_app.run_bot()


@pytest.mark.anyio
async def test_run_bot_startup_json_default_validates_json_storage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "subscriptions.json"
    path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:test-token")
    monkeypatch.setenv("DIET_BOT_ENV", "development")
    monkeypatch.delenv("DIET_BOT_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DIET_BOT_SUBSCRIPTIONS_STATE_FILE", str(path))

    def fail_bot(_token):
        raise AssertionError("Bot must not be constructed before storage validation")

    monkeypatch.setattr(telegram_app, "Bot", fail_bot)

    with pytest.raises(RuntimeError, match="Entitlement state is invalid"):
        await telegram_app.run_bot()


@pytest.mark.anyio
async def test_run_bot_startup_postgres_mode_skips_json_validation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "subscriptions.json"
    path.write_text("{not-json", encoding="utf-8")
    fake_bot = object()
    chat_state_validated: list[str] = []
    validated: list[tuple[str, object]] = []
    weekly_pdf_validated: list[str] = []
    one_day_validated: list[str] = []
    guard_events: list[str] = []
    polled: list[object] = []

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            polled.append(bot)

    async def fake_set_commands(_bot) -> None:
        return None

    def fake_create_store(config):
        return object()

    def fake_validate_store(config, store) -> None:
        validated.append((config.storage_backend, store))

    def fake_validate_weekly_pdf_jobs(config) -> None:
        weekly_pdf_validated.append(config.storage_backend)

    def fake_validate_one_day_jobs(config) -> None:
        one_day_validated.append(config.storage_backend)

    def fake_validate_chat_state(config) -> None:
        chat_state_validated.append(config.storage_backend)

    class FakeGuard:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://user:secret@example/db"
            guard_events.append("guard_init")

        def acquire(self):
            guard_events.append("guard_acquire")
            return self

        def close(self) -> None:
            guard_events.append("guard_close")

    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:test-token")
    monkeypatch.setenv("DIET_BOT_ENV", "development")
    monkeypatch.setenv("DIET_BOT_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://user:secret@example/db")
    monkeypatch.setenv("DIET_BOT_SUBSCRIPTIONS_STATE_FILE", str(path))
    monkeypatch.setitem(
        sys.modules,
        "diet_bot.postgres_single_poller_guard",
        SimpleNamespace(PostgresSinglePollerGuard=FakeGuard),
    )
    monkeypatch.setattr(telegram_app, "create_entitlement_store", fake_create_store, raising=False)
    monkeypatch.setattr(
        telegram_app,
        "validate_entitlement_store_for_startup",
        fake_validate_store,
        raising=False,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_one_day_generation_job_store_for_startup",
        fake_validate_one_day_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_chat_state_store_for_startup",
        fake_validate_chat_state,
    )
    monkeypatch.setattr(telegram_app, "Bot", lambda _token: fake_bot)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    await telegram_app.run_bot()

    assert chat_state_validated == ["postgres"]
    assert validated and validated[0][0] == "postgres"
    assert weekly_pdf_validated == ["postgres"]
    assert one_day_validated == ["postgres"]
    assert guard_events == ["guard_init", "guard_acquire", "guard_close"]
    assert polled == [fake_bot]


@pytest.mark.anyio
async def test_run_bot_starts_configured_one_day_worker_without_real_polling(monkeypatch) -> None:
    fake_bot = object()
    fake_runtime = object()
    events: list[object] = []

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            events.append(("poll", bot))
            await asyncio.sleep(0)

    class FakeWorker:
        def __init__(self, runtime, processor, settings) -> None:
            events.append(
                (
                    "worker_init",
                    runtime,
                    type(processor).__name__,
                    settings.concurrency,
                    settings.lease_seconds,
                    settings.heartbeat_interval_seconds,
                    settings.retry_delay_seconds,
                    settings.max_attempts,
                    settings.idle_sleep_seconds,
                ),
            )

        async def run_forever(self) -> None:
            events.append("worker_run")
            try:
                await asyncio.Event().wait()
            finally:
                events.append("worker_cancelled")

    class FakeGuard:
        def close(self) -> None:
            events.append("guard_close")

    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:test-token")
    monkeypatch.setenv("DIET_BOT_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://user:secret@example/db")
    monkeypatch.setenv("DIET_BOT_ONE_DAY_WORKER_ENABLED", "1")
    monkeypatch.setenv("DIET_BOT_ONE_DAY_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("DIET_BOT_ONE_DAY_WORKER_LEASE_SECONDS", "90")
    monkeypatch.setenv("DIET_BOT_ONE_DAY_WORKER_HEARTBEAT_SECONDS", "10")
    monkeypatch.setenv("DIET_BOT_ONE_DAY_WORKER_RETRY_DELAY_SECONDS", "7")
    monkeypatch.setenv("DIET_BOT_ONE_DAY_WORKER_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("DIET_BOT_ONE_DAY_WORKER_IDLE_SLEEP_SECONDS", "0.2")
    monkeypatch.setattr(telegram_app, "Bot", lambda _token: fake_bot)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", lambda _bot: asyncio.sleep(0))
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_weekly_pdf_job_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_one_day_generation_job_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_payment_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "_acquire_postgres_single_poller_guard", lambda _config: FakeGuard())
    monkeypatch.setattr(telegram_app, "_one_day_generation_job_runtime", lambda: fake_runtime)
    monkeypatch.setattr(telegram_app, "OneDayGenerationWorker", FakeWorker)

    await telegram_app.run_bot()

    assert (
        "worker_init",
        fake_runtime,
        "_TelegramOneDayGenerationJobProcessor",
        2,
        90,
        10,
        7,
        5,
        0.2,
    ) in events
    assert "worker_run" in events
    assert "worker_cancelled" in events
    assert ("poll", fake_bot) in events
    assert "guard_close" in events


@pytest.mark.anyio
async def test_run_bot_starts_configured_weekly_pdf_worker_without_real_polling(monkeypatch) -> None:
    fake_bot = object()
    fake_runtime = object()
    events: list[object] = []

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            events.append(("poll", bot))
            await asyncio.sleep(0)

    class FakeWorker:
        def __init__(self, runtime, processor, settings) -> None:
            events.append(
                (
                    "worker_init",
                    runtime,
                    type(processor).__name__,
                    settings.concurrency,
                    settings.lease_seconds,
                    settings.heartbeat_interval_seconds,
                    settings.retry_delay_seconds,
                    settings.max_attempts,
                    settings.idle_sleep_seconds,
                ),
            )

        async def run_forever(self) -> None:
            events.append("worker_run")
            try:
                await asyncio.Event().wait()
            finally:
                events.append("worker_cancelled")

    class FakeGuard:
        def close(self) -> None:
            events.append("guard_close")

    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:test-token")
    monkeypatch.setenv("DIET_BOT_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://user:secret@example/db")
    monkeypatch.setenv("DIET_BOT_WEEKLY_PDF_WORKER_ENABLED", "1")
    monkeypatch.setenv("DIET_BOT_WEEKLY_PDF_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("DIET_BOT_WEEKLY_PDF_WORKER_LEASE_SECONDS", "90")
    monkeypatch.setenv("DIET_BOT_WEEKLY_PDF_WORKER_HEARTBEAT_SECONDS", "10")
    monkeypatch.setenv("DIET_BOT_WEEKLY_PDF_WORKER_RETRY_DELAY_SECONDS", "7")
    monkeypatch.setenv("DIET_BOT_WEEKLY_PDF_WORKER_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("DIET_BOT_WEEKLY_PDF_WORKER_IDLE_SLEEP_SECONDS", "0.2")
    monkeypatch.setattr(telegram_app, "Bot", lambda _token: fake_bot)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", lambda _bot: asyncio.sleep(0))
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_weekly_pdf_job_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_one_day_generation_job_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_payment_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "_acquire_postgres_single_poller_guard", lambda _config: FakeGuard())
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: fake_runtime)
    monkeypatch.setattr(telegram_app, "WeeklyPdfWorker", FakeWorker)

    await telegram_app.run_bot()

    assert (
        "worker_init",
        fake_runtime,
        "_TelegramWeeklyPdfJobProcessor",
        2,
        90,
        10,
        7,
        5,
        0.2,
    ) in events
    assert "worker_run" in events
    assert "worker_cancelled" in events
    assert ("poll", fake_bot) in events
    assert "guard_close" in events


@pytest.mark.anyio
async def test_one_day_worker_task_exception_is_observed_without_secret_leak(monkeypatch, caplog) -> None:
    fake_runtime = object()

    class CrashingWorker:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def run_forever(self) -> None:
            raise RuntimeError("bot-token-secret should not be logged")

    monkeypatch.setattr(telegram_app, "_one_day_generation_job_runtime", lambda: fake_runtime)
    monkeypatch.setattr(telegram_app, "OneDayGenerationWorker", CrashingWorker)
    caplog.set_level(logging.ERROR, logger="diet_bot.telegram_app")

    task = telegram_app._start_one_day_generation_worker_if_configured(
        SimpleNamespace(one_day_worker_enabled=True),
        object(),
    )

    assert task is not None
    with pytest.raises(RuntimeError):
        await task
    await asyncio.sleep(0)
    assert "One-day worker task stopped unexpectedly" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "bot-token-secret" not in caplog.text


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


def test_promo_code_activation_rolls_back_claim_when_entitlement_grant_fails(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 80_203
    promo_path = tmp_path / "promo_codes.json"
    save_promo_codes(promo_path, {"FB-ABCD-EFGH-2345": PromoCodeRecord()})
    service = FakePromoEntitlementService(fail_grants=1)
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "_entitlement_service", lambda: service)

    with pytest.raises(telegram_app.EntitlementStorageError, match="grant failed"):
        telegram_app._activate_promo_code_for_chat(chat_id, "fb abcd efgh 2345")

    promo_codes = load_promo_codes(promo_path)
    assert promo_codes["FB-ABCD-EFGH-2345"].used_by_chat_id is None
    assert promo_codes["FB-ABCD-EFGH-2345"].used_at is None

    retry = telegram_app._activate_promo_code_for_chat(chat_id, "FB-ABCD-EFGH-2345")

    assert retry.activated
    assert service.grants == [(chat_id, "promo:FB-ABCD-EFGH-2345")]
    assert load_promo_codes(promo_path)["FB-ABCD-EFGH-2345"].used_by_chat_id == chat_id


def test_promo_code_duplicate_after_success_does_not_grant_again(monkeypatch, tmp_path) -> None:
    promo_path = tmp_path / "promo_codes.json"
    save_promo_codes(promo_path, {"FB-ABCD-EFGH-2345": PromoCodeRecord()})
    service = FakePromoEntitlementService()
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "_entitlement_service", lambda: service)

    first = telegram_app._activate_promo_code_for_chat(80_204, "FB-ABCD-EFGH-2345")
    second = telegram_app._activate_promo_code_for_chat(80_205, "FB-ABCD-EFGH-2345")

    assert first.activated
    assert second.status == "already_used"
    assert second.used_by_chat_id == 80_204
    assert service.grants == [(80_204, "promo:FB-ABCD-EFGH-2345")]


@pytest.mark.anyio
async def test_promo_code_handler_returns_entitlement_error_and_allows_retry(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 80_206
    promo_path = tmp_path / "promo_codes.json"
    save_promo_codes(promo_path, {"FB-ABCD-EFGH-2345": PromoCodeRecord()})
    service = FakePromoEntitlementService(fail_grants=1)
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "_entitlement_service", lambda: service)
    PROMO_CODE_REQUEST_CHAT_IDS.add(chat_id)
    first_message = FakeMessage(chat_id, text="FB-ABCD-EFGH-2345")

    try:
        await handle_answer(first_message)

        promo_codes = load_promo_codes(promo_path)
        assert first_message.texts == [(telegram_app.ENTITLEMENT_STORAGE_ERROR_TEXT, None)]
        assert chat_id in PROMO_CODE_REQUEST_CHAT_IDS
        assert promo_codes["FB-ABCD-EFGH-2345"].used_by_chat_id is None
        assert promo_codes["FB-ABCD-EFGH-2345"].used_at is None

        retry_message = FakeMessage(chat_id, text="FB-ABCD-EFGH-2345")
        await handle_answer(retry_message)

        assert chat_id not in PROMO_CODE_REQUEST_CHAT_IDS
        assert service.grants == [(chat_id, "promo:FB-ABCD-EFGH-2345")]
        assert load_promo_codes(promo_path)["FB-ABCD-EFGH-2345"].used_by_chat_id == chat_id
        assert retry_message.texts[-1][1] is not None
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
    monkeypatch.setenv("DIET_BOT_STORAGE_BACKEND", "json")
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
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
async def test_support_chat_missing_does_not_use_default_fallback(monkeypatch, tmp_path) -> None:
    chat_id = 80_104
    monkeypatch.delenv("DIET_BOT_SUPPORT_CHAT_ID", raising=False)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _set_support_chat_id_from_env(monkeypatch)
    SUPPORT_REQUEST_CHAT_IDS.add(chat_id)
    message = FakeMessage(chat_id, text="Need help")
    try:
        await handle_answer(message)

        assert telegram_app.SUPPORT_CHAT_ID is None
        assert chat_id not in SUPPORT_REQUEST_CHAT_IDS
        assert message.bot.sent_messages == []
        assert message.texts[-1][1] is not None
    finally:
        SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)


@pytest.mark.anyio
async def test_support_chat_configured_from_env_still_receives_messages(monkeypatch, tmp_path) -> None:
    chat_id = 80_105
    support_chat_id = -100_555_222
    monkeypatch.setenv("DIET_BOT_SUPPORT_CHAT_ID", str(support_chat_id))
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _set_support_chat_id_from_env(monkeypatch)
    SUPPORT_REQUEST_CHAT_IDS.add(chat_id)
    message = FakeMessage(chat_id, text="Need help")
    try:
        await handle_answer(message)

        assert telegram_app.SUPPORT_CHAT_ID == support_chat_id
        assert message.bot.sent_messages[0]["chat_id"] == support_chat_id
        assert chat_id not in SUPPORT_REQUEST_CHAT_IDS
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
async def test_support_chat_rejects_product_commands_and_myid(monkeypatch, tmp_path) -> None:
    support_chat_id = -5_271_779_108
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID", support_chat_id)
    start_message = FakeMessage(support_chat_id, text="/start", chat_type="supergroup")
    myid_message = FakeMessage(support_chat_id, text="/myid", user_id=70_104, chat_type="supergroup")

    await telegram_app.start(start_message)
    await handle_answer(myid_message)

    assert "private chat" in start_message.texts[-1][0]
    assert start_message.photos == []
    assert "private chat" in myid_message.texts[-1][0]


@pytest.mark.anyio
async def test_group_start_rejects_before_profile_session_or_state_stores(monkeypatch, tmp_path) -> None:
    class FailingStateStore:
        def load_all(self):
            raise AssertionError("chat state store should not be read for group /start")

        def save_all(self, state):
            raise AssertionError("chat state store should not be written for group /start")

        def save_chat_state(self, chat_id, chat_state):
            raise AssertionError("chat state store should not be written for group /start")

    class FailingEntitlementService:
        def get_entitlement(self, chat_id):
            raise AssertionError("entitlement store should not be read for group /start")

    chat_id = -100_101_202
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: FailingStateStore())
    monkeypatch.setattr(telegram_app, "_entitlement_service", lambda: FailingEntitlementService())
    message = FakeMessage(chat_id, text="/start", chat_type="group")

    await telegram_app.start(message)

    assert "private chat" in message.texts[-1][0]
    assert message.photos == []
    assert chat_id not in PROFILE_BY_CHAT_ID
    assert chat_id not in SESSION_BY_CHAT_ID
    assert not (tmp_path / "history.json").exists()
    assert not (tmp_path / "subscriptions.json").exists()


@pytest.mark.anyio
@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
async def test_non_private_callback_rejects_before_state_mutation(monkeypatch, chat_type) -> None:
    chat_id = -100_303_404
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage(chat_id, chat_type=chat_type)
    callback = FakeCallback(CALLBACK_START, message)

    await telegram_app.handle_callback(callback)

    assert "private chat" in callback.answers[-1]
    assert message.texts == []
    assert chat_id not in SESSION_BY_CHAT_ID
    assert chat_id not in TRIAL_CHAT_IDS


@pytest.mark.anyio
async def test_group_hidden_admin_command_denied_without_grant(monkeypatch, tmp_path) -> None:
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {700})
    message = FakeMessage(
        chat_id=-100_505_606,
        text="/330366 91002",
        user_id=700,
        chat_type="supergroup",
    )

    await secret_access_command(message)

    assert "private chat" in message.texts[-1][0]
    assert not subscriptions_path.exists()


@pytest.mark.anyio
async def test_private_start_still_sends_welcome(monkeypatch, tmp_path) -> None:
    chat_id = 80_301
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    message = FakeMessage(chat_id, text="/start", chat_type="private")

    await telegram_app.start(message)

    sent_text, markup = message.texts[-1]
    assert sent_text == WELCOME_TEXT
    callbacks = _button_callbacks(markup)
    assert callbacks[0] == CALLBACK_START
    assert CALLBACK_FEATURES in callbacks
    assert chat_id not in SESSION_BY_CHAT_ID


@pytest.mark.anyio
async def test_private_callback_start_flow_unchanged(monkeypatch) -> None:
    chat_id = 80_302
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage(chat_id, chat_type="private")
    callback = FakeCallback(CALLBACK_START, message)

    try:
        await telegram_app.handle_callback(callback)

        assert callback.answers == [None]
        assert chat_id in SESSION_BY_CHAT_ID
        assert chat_id in TRIAL_CHAT_IDS
        assert message.texts[-1][0] == start_session().current_question.prompt
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        TRIAL_CHAT_IDS.discard(chat_id)


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


def test_subscribe_paywall_and_trial_markups_include_privacy_url_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", PRIVACY_URL, raising=False)

    markups = [
        _subscription_payment_keyboard(),
        _paywall_keyboard(preferred="one_day"),
        _paywall_keyboard(preferred="weekly_pdf"),
        _trial_subscription_keyboard(),
    ]

    for markup in markups:
        assert (PRIVACY_POLICY_TEXT, PRIVACY_URL) in _button_text_urls(markup)


def test_privacy_button_is_omitted_when_url_absent(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", None, raising=False)

    markups = [
        _start_keyboard(),
        _subscription_payment_keyboard(),
        _paywall_keyboard(preferred="one_day"),
        _trial_subscription_keyboard(),
    ]

    for markup in markups:
        assert all(button.url != PRIVACY_URL for row in markup.inline_keyboard for button in row)


def test_default_payments_disabled_hides_payment_buttons(monkeypatch) -> None:
    monkeypatch.delenv("DIET_BOT_PAYMENTS_ENABLED", raising=False)
    _set_payments_enabled_from_env(monkeypatch)
    payment_callbacks = {
        CALLBACK_SUBSCRIBE,
        CALLBACK_PAY_RU_CARD,
        CALLBACK_PAY_TELEGRAM_STARS,
        CALLBACK_PAY_RU_EXTRA_ONE_DAY,
        CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF,
        CALLBACK_BUY_EXTRA_ONE_DAY,
        CALLBACK_BUY_EXTRA_WEEKLY_PDF,
    }

    markups = [
        telegram_app._start_keyboard(),
        _trial_subscription_keyboard(),
        _subscription_payment_keyboard(),
        _paywall_keyboard(preferred="one_day"),
        _paywall_keyboard(preferred="weekly_pdf"),
    ]

    for markup in markups:
        assert payment_callbacks.isdisjoint(_button_callbacks(markup))


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


def test_pre_checkout_rejects_static_payloads(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
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

    assert not _is_valid_pre_checkout(valid_query)
    assert not _is_valid_pre_checkout(wrong_amount_query)
    assert not _is_valid_pre_checkout(wrong_currency_query)
    assert not _is_valid_pre_checkout(valid_rub_query)
    assert not _is_valid_pre_checkout(wrong_rub_amount_query)
    assert not _is_valid_pre_checkout(unknown_payload_query)


def test_pre_checkout_accepts_valid_order_payload_without_chat_validation(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    query = SimpleNamespace(
        invoice_payload=encode_payment_order_payload(order.order_id, order.nonce),
        currency="XTR",
        total_amount=400,
        from_user=SimpleNamespace(id=101),
    )

    assert _is_valid_pre_checkout(query)
    assert service.validations[-1]["chat_id"] is None


def test_pre_checkout_rejects_static_legacy_payload(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    query = SimpleNamespace(
        invoice_payload=PAYLOAD_SUBSCRIPTION_MONTH,
        currency="XTR",
        total_amount=PAYMENT_PAYLOAD_AMOUNTS[PAYLOAD_SUBSCRIPTION_MONTH],
        from_user=SimpleNamespace(id=101),
    )

    assert not _is_valid_pre_checkout(query)
    assert service.validations == []


@pytest.mark.anyio
async def test_send_subscription_invoice_link_creates_recurring_stars_invoice(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    message = FakeMessage()

    await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)

    invoice = message.bot.invoice_links[0]
    assert invoice["currency"] == "XTR"
    assert invoice["provider_token"] == ""
    assert invoice["payload"].startswith("diet:order:v1:")
    assert invoice["prices"][0].amount == SUBSCRIPTION_STARS_AMOUNT
    assert invoice["subscription_period"] == 2_592_000
    assert message.texts[-1][1].inline_keyboard[0][0].url == "https://t.me/invoice/test"


@pytest.mark.anyio
async def test_invoice_link_markups_include_privacy_url_when_configured(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", PRIVACY_URL, raising=False)
    stars_message = FakeMessage(chat_id=202, user_id=101)
    rub_message = FakeMessage(chat_id=303, user_id=102)

    await _send_stars_invoice_link(stars_message, PAYLOAD_SUBSCRIPTION_MONTH)
    await telegram_app._send_yookassa_invoice_link(rub_message, telegram_app.PAYLOAD_RU_SUBSCRIPTION_MONTH)

    assert (PRIVACY_POLICY_TEXT, PRIVACY_URL) in _button_text_urls(stars_message.texts[-1][1])
    assert (PRIVACY_POLICY_TEXT, PRIVACY_URL) in _button_text_urls(rub_message.texts[-1][1])


@pytest.mark.anyio
async def test_stars_invoice_creates_ledger_order_and_uses_order_payload(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    message = FakeMessage(chat_id=202, user_id=101)

    await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)

    invoice = message.bot.invoice_links[0]
    decoded = decode_payment_order_payload(invoice["payload"])
    assert decoded is not None
    assert decoded.order_id == "order_00000001"
    assert decoded.nonce == "nonce_00000001"
    assert invoice["payload"] != PAYLOAD_SUBSCRIPTION_MONTH
    assert service.created_orders == [
        {
            "user_id": 101,
            "chat_id": 202,
            "product": PRODUCT_SUBSCRIPTION_MONTH,
            "provider": PROVIDER_TELEGRAM_STARS,
        },
    ]


@pytest.mark.anyio
async def test_payment_callback_uses_callback_user_as_buyer_and_message_chat_for_delivery(
    monkeypatch,
    tmp_path,
) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage(chat_id=202, user_id=777_000)
    callback = FakeCallback(CALLBACK_PAY_TELEGRAM_STARS, message, user_id=101)

    await telegram_app.handle_callback(callback)

    invoice = message.bot.invoice_links[0]
    decoded = decode_payment_order_payload(invoice["payload"])
    assert decoded is not None
    assert service.created_orders == [
        {
            "user_id": 101,
            "chat_id": 202,
            "product": PRODUCT_SUBSCRIPTION_MONTH,
            "provider": PROVIDER_TELEGRAM_STARS,
        },
    ]

    accepted_query = SimpleNamespace(
        invoice_payload=invoice["payload"],
        currency="XTR",
        total_amount=400,
        from_user=SimpleNamespace(id=101),
    )
    wrong_user_query = SimpleNamespace(
        invoice_payload=invoice["payload"],
        currency="XTR",
        total_amount=400,
        from_user=SimpleNamespace(id=999),
    )

    assert _is_valid_pre_checkout(accepted_query)
    assert not _is_valid_pre_checkout(wrong_user_query)


@pytest.mark.anyio
async def test_rub_invoice_creates_ledger_order_and_uses_order_payload(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    message = FakeMessage(chat_id=202, user_id=101)

    await telegram_app._send_yookassa_invoice_link(message, telegram_app.PAYLOAD_RU_EXTRA_ONE_DAY)

    invoice = message.bot.invoice_links[0]
    decoded = decode_payment_order_payload(invoice["payload"])
    assert decoded is not None
    assert decoded.order_id == "order_00000001"
    assert invoice["payload"] != telegram_app.PAYLOAD_RU_EXTRA_ONE_DAY
    assert invoice["currency"] == "RUB"
    assert service.created_orders == [
        {
            "user_id": 101,
            "chat_id": 202,
            "product": PRODUCT_EXTRA_ONE_DAY,
            "provider": PROVIDER_YOOKASSA,
        },
    ]


@pytest.mark.anyio
async def test_invoice_creation_failure_marks_ledger_order_failed(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    message = FakeMessage(chat_id=202, user_id=101)
    message.bot = FailingInvoiceBot()

    await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)

    assert message.bot.invoice_links == []
    assert service.failed_orders == [("order_00000001", "invoice_creation_failed")]
    assert message.texts


@pytest.mark.anyio
async def test_send_extra_day_invoice_link_creates_one_time_stars_invoice(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    message = FakeMessage()

    await _send_stars_invoice_link(message, PAYLOAD_EXTRA_ONE_DAY)

    invoice = message.bot.invoice_links[0]
    assert invoice["currency"] == "XTR"
    assert invoice["payload"].startswith("diet:order:v1:")
    assert invoice["prices"][0].amount == 35
    assert invoice["subscription_period"] is None


@pytest.mark.anyio
async def test_disabled_payments_blocks_stars_callback(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", False, raising=False)
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage()
    callback = FakeCallback(CALLBACK_PAY_TELEGRAM_STARS, message)

    await telegram_app.handle_callback(callback)

    assert callback.answers == [None]
    assert message.bot.invoice_links == []
    assert message.texts


@pytest.mark.anyio
@pytest.mark.parametrize(
    "callback_data",
    [
        CALLBACK_PAY_TELEGRAM_STARS,
        CALLBACK_BUY_EXTRA_ONE_DAY,
    ],
)
async def test_payment_invoice_callback_fails_closed_when_entitlement_storage_is_corrupt(
    monkeypatch,
    tmp_path,
    callback_data,
) -> None:
    subscriptions_path = tmp_path / "subscriptions.json"
    subscriptions_path.write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage()
    callback = FakeCallback(callback_data, message)

    await telegram_app.handle_callback(callback)

    assert callback.answers == [None]
    assert message.texts == [(telegram_app.ENTITLEMENT_STORAGE_ERROR_TEXT, None)]
    assert message.bot.invoice_links == []


@pytest.mark.anyio
async def test_disabled_payments_blocks_rub_provider_callback(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", False, raising=False)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage()
    callback = FakeCallback(CALLBACK_PAY_RU_CARD, message)

    await telegram_app.handle_callback(callback)

    assert callback.answers == [None]
    assert message.bot.invoice_links == []
    assert message.texts


@pytest.mark.anyio
async def test_enabled_payments_without_provider_blocks_rub_provider_invoice(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "")
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    message = FakeMessage()
    callback = FakeCallback(CALLBACK_PAY_RU_CARD, message)

    await telegram_app.handle_callback(callback)

    assert callback.answers == [None]
    assert message.bot.invoice_links == []
    assert message.texts


@pytest.mark.anyio
async def test_enabled_payments_with_json_runtime_fails_closed_before_invoice(monkeypatch) -> None:
    monkeypatch.setenv("DIET_BOT_PAYMENTS_ENABLED", "1")
    monkeypatch.setenv("DIET_BOT_STORAGE_BACKEND", "json")
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    _set_payments_enabled_from_env(monkeypatch)
    message = FakeMessage(chat_id=202, user_id=101)

    await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)

    assert message.bot.invoice_links == []
    assert message.texts


@pytest.mark.anyio
async def test_ru_card_callback_creates_yookassa_invoice_with_receipt(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
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
    assert invoice["payload"].startswith("diet:order:v1:")
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


def test_successful_payment_order_payload_grants_once_and_validates_chat(monkeypatch) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    payment = SimpleNamespace(
        invoice_payload=encode_payment_order_payload(order.order_id, order.nonce),
        currency="XTR",
        total_amount=400,
        telegram_payment_charge_id="tg-charge-1",
        provider_payment_charge_id=None,
    )

    first = telegram_app._apply_successful_payment(202, payment, user_id=101)
    duplicate = telegram_app._apply_successful_payment(202, payment, user_id=101)

    assert first.processed
    assert first.grant == "subscription"
    assert duplicate.duplicate
    assert not duplicate.processed
    assert [request["chat_id"] for request in service.successful_requests] == [202, 202]
    assert service.grants == [PRODUCT_SUBSCRIPTION_MONTH]


def test_static_legacy_successful_payment_records_unknown_without_grant(monkeypatch, tmp_path) -> None:
    service = FakeTelegramPaymentService()
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    payment = SimpleNamespace(
        invoice_payload=PAYLOAD_SUBSCRIPTION_MONTH,
        currency="XTR",
        total_amount=400,
        telegram_payment_charge_id="tg-charge-static",
        provider_payment_charge_id=None,
    )

    result = telegram_app._apply_successful_payment(202, payment)

    assert not result.processed
    assert service.unknown_payloads == [PAYLOAD_SUBSCRIPTION_MONTH]
    assert telegram_app.load_entitlements(tmp_path / "subscriptions.json") == {}


@pytest.mark.anyio
async def test_successful_payment_ledger_failure_spools_recovery_record_before_notice(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    service = FailingSuccessfulPaymentService(
        telegram_app.PaymentLedgerUnavailable("payment_ledger_unavailable", "ledger down"),
    )
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    spool_path = tmp_path / "payment-recovery" / "payments.jsonl"
    monkeypatch.setenv("DIET_BOT_PAYMENT_RECOVERY_SPOOL", str(spool_path))
    events: list[tuple[str, object]] = []

    def tracking_append(path, record) -> None:
        events.append(("append", record.record_id))
        write_payment_recovery_record(path, record)

    monkeypatch.setattr(telegram_app, "append_payment_recovery_record", tracking_append, raising=False)
    caplog.set_level(logging.CRITICAL, logger=telegram_app.logger.name)

    class RecordingMessage(FakeMessage):
        async def answer(self, text, reply_markup=None):
            events.append(("answer", text))
            return await super().answer(text, reply_markup)

    invoice_payload = encode_payment_order_payload("order_12345678", "nonce_12345678")
    payment = SimpleNamespace(
        invoice_payload=invoice_payload,
        currency="RUB",
        total_amount=59_900,
        telegram_payment_charge_id="tg-charge-1",
        provider_payment_charge_id="provider-charge-1",
        subscription_expiration_date=1_781_234_567,
        order_info={"email": "private@example.test"},
        provider_data={"token": "secret"},
    )
    message = RecordingMessage(202, user_id=101)
    message.successful_payment = payment

    await telegram_app.handle_successful_payment(message)

    result = read_payment_recovery_records(spool_path)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.provider == PROVIDER_YOOKASSA
    assert record.chat_id == 202
    assert record.user_id == 101
    assert record.invoice_payload == invoice_payload
    assert record.telegram_payment_charge_id == "tg-charge-1"
    assert record.provider_payment_charge_id == "provider-charge-1"
    assert record.currency == "RUB"
    assert record.total_amount == 59_900
    assert record.subscription_expiration_date == 1_781_234_567
    assert set(record.to_dict()).issubset(ALLOWED_SERIALIZED_FIELDS)
    assert "private@example.test" not in json.dumps(record.to_dict(), sort_keys=True)
    assert "secret" not in json.dumps(record.to_dict(), sort_keys=True)
    assert [event[0] for event in events] == ["append", "answer"]
    critical_records = [record for record in caplog.records if record.levelno >= logging.CRITICAL]
    assert critical_records
    recovery_record = critical_records[-1]
    assert getattr(recovery_record, "chat_id") != 202
    assert getattr(recovery_record, "user_id") != 101
    for field_name, raw_value in {
        "chat_id": "202",
        "user_id": "101",
        "order_id": "order_12345678",
        "telegram_payment_charge_id": "tg-charge-1",
        "provider_payment_charge_id": "provider-charge-1",
    }.items():
        value = str(getattr(recovery_record, field_name))
        assert value.startswith("<redacted:")
        assert raw_value not in value

    sent_text = message.texts[-1][0]
    assert "\u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u043e\u043b\u0443\u0447\u0435\u043d\u0430" in sent_text
    assert "\u0430\u043a\u0442\u0438\u0432\u0430\u0446\u0438" in sent_text
    assert "\u041d\u0435 \u043e\u043f\u043b\u0430\u0447\u0438\u0432\u0430\u0439\u0442\u0435 \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u043e" in sent_text
    assert "\u043f\u043e\u0434\u0434\u0435\u0440\u0436" in sent_text.lower()
    assert "\u0421\u0447\u0435\u0442 \u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u043d" not in sent_text
    assert "\u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043e\u043f\u043b\u0430\u0442\u0438\u0442\u044c" not in sent_text.lower()


@pytest.mark.anyio
async def test_successful_payment_successful_grant_does_not_spool(monkeypatch) -> None:
    def fail_append(path, record) -> None:
        raise AssertionError("successful grants must not be spooled")

    monkeypatch.setattr(telegram_app, "append_payment_recovery_record", fail_append, raising=False)
    monkeypatch.setattr(
        telegram_app,
        "_apply_successful_payment",
        lambda _chat_id, _payment, *, user_id=None: telegram_app.PaymentApplication(True, "extra_one_day"),
        raising=False,
    )
    monkeypatch.setattr(telegram_app, "_has_active_paid_access", lambda _chat_id: False, raising=False)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status", raising=False)
    payment = SimpleNamespace(
        invoice_payload=encode_payment_order_payload("order_12345678", "nonce_12345678"),
        currency="XTR",
        total_amount=35,
        telegram_payment_charge_id="tg-charge-ok",
        provider_payment_charge_id=None,
    )
    message = FakeMessage(202, user_id=101)
    message.successful_payment = payment

    await telegram_app.handle_successful_payment(message)

    assert message.texts
    assert "\u0430\u043a\u0442\u0438\u0432\u0430\u0446\u0438\u044f \u0434\u043e\u0441\u0442\u0443\u043f\u0430 \u0437\u0430\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442\u0441\u044f" not in message.texts[-1][0]


@pytest.mark.anyio
async def test_successful_payment_spool_append_failure_logs_critical_and_sends_support_message(
    monkeypatch,
    caplog,
) -> None:
    service = FailingSuccessfulPaymentService(
        telegram_app.PaymentLedgerUnavailable("payment_ledger_unavailable", "ledger down"),
    )
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)

    def fail_append(path, record) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(telegram_app, "append_payment_recovery_record", fail_append, raising=False)
    caplog.set_level(logging.CRITICAL, logger=telegram_app.logger.name)
    payment = SimpleNamespace(
        invoice_payload=encode_payment_order_payload("order_12345678", "nonce_12345678"),
        currency="XTR",
        total_amount=400,
        telegram_payment_charge_id="tg-charge-critical",
        provider_payment_charge_id=None,
    )
    message = FakeMessage(202, user_id=101)
    message.successful_payment = payment

    await telegram_app.handle_successful_payment(message)

    critical_records = [record for record in caplog.records if record.levelno >= logging.CRITICAL]
    assert critical_records
    assert not any(getattr(record, "chat_id", None) == 202 for record in critical_records)
    assert not any(getattr(record, "user_id", None) == 101 for record in critical_records)
    assert not any(getattr(record, "telegram_payment_charge_id", None) == "tg-charge-critical" for record in critical_records)
    assert any(
        str(getattr(record, "telegram_payment_charge_id", "")).startswith("<redacted:")
        for record in critical_records
    )
    assert not any("diet:order:v1" in record.getMessage() for record in critical_records)
    sent_text = message.texts[-1][0]
    assert "\u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u043e\u043b\u0443\u0447\u0435\u043d\u0430" in sent_text
    assert "\u043f\u043e\u0434\u0434\u0435\u0440\u0436" in sent_text.lower()
    assert "\u0414\u043e\u0441\u0442\u0443\u043f \u0430\u043a\u0442\u0438\u0432\u0435\u043d" not in sent_text


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
        chat_type="private",
        message_id=None,
    ) -> None:
        self.chat = type("FakeChat", (), {"id": chat_id, "type": chat_type})()
        self.from_user = SimpleNamespace(
            id=chat_id if user_id is None else user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            full_name=" ".join(part for part in (first_name, last_name) if part),
        )
        self.text = text
        self.message_id = chat_id if message_id is None else message_id
        self.bot = FakeInvoiceBot()
        self.photos = []
        self.texts = []
        self.documents = []
        self.edits = []
        self.edited_reply_markups = []

    async def answer_photo(self, **kwargs) -> None:
        self.photos.append(kwargs)

    async def answer(self, text, reply_markup=None):
        self.texts.append((text, reply_markup))
        return FakeSentMessage(self)

    async def answer_document(self, **kwargs) -> None:
        self.documents.append(kwargs)

    async def edit_reply_markup(self, reply_markup=None):
        self.edited_reply_markups.append(reply_markup)


class FakeCallback:
    def __init__(
        self,
        data: str,
        message: FakeMessage,
        *,
        user_id: int | None = None,
        callback_id: str | None = None,
    ) -> None:
        self.id = callback_id or f"callback-{message.chat.id}-{data}"
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=message.chat.id if user_id is None else user_id)
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

    async def send_photo(self, **kwargs) -> None:
        self.sent_messages.append({"photo": True, **kwargs})


class FailingInvoiceBot(FakeInvoiceBot):
    async def create_invoice_link(self, **kwargs) -> str:
        raise TelegramAPIError(SimpleNamespace(), "invoice failed")


class FakeTelegramPaymentService:
    def __init__(self) -> None:
        self.orders: dict[str, PaymentOrder] = {}
        self.created_orders: list[dict[str, object]] = []
        self.failed_orders: list[tuple[str, str | None]] = []
        self.validations: list[dict[str, object]] = []
        self.successful_requests: list[dict[str, object]] = []
        self.grants: list[str] = []
        self.unknown_payloads: list[str] = []
        self._counter = 0
        self._processed_charges: set[str] = set()

    def create_order(self, *, user_id: int, chat_id: int, product: str, provider: str) -> PaymentOrder:
        self._counter += 1
        order = PaymentOrder(
            order_id=f"order_{self._counter:08d}",
            user_id=user_id,
            chat_id=chat_id,
            product=product,
            provider=provider,
            amount=_fake_amount(provider, product),
            currency="XTR" if provider == PROVIDER_TELEGRAM_STARS else "RUB",
            nonce=f"nonce_{self._counter:08d}",
        )
        self.orders[order.order_id] = order
        self.created_orders.append(
            {
                "user_id": user_id,
                "chat_id": chat_id,
                "product": product,
                "provider": provider,
            },
        )
        return order

    def validate_order_payment(
        self,
        payload: str,
        *,
        user_id: int,
        chat_id: int | None,
        provider: str,
        amount: int,
        currency: str,
        require_pending: bool = True,
    ) -> PaymentValidationResult:
        self.validations.append(
            {
                "payload": payload,
                "user_id": user_id,
                "chat_id": chat_id,
                "provider": provider,
                "amount": amount,
                "currency": currency,
                "require_pending": require_pending,
            },
        )
        decoded = decode_payment_order_payload(payload)
        if decoded is None:
            return PaymentValidationResult(False, reason="non_order_payload")
        order = self.orders.get(decoded.order_id)
        if order is None:
            return PaymentValidationResult(False, reason="order_not_found")
        if int(order.user_id) != int(user_id):
            return PaymentValidationResult(False, order, "user_mismatch")
        if chat_id is not None and int(order.chat_id) != int(chat_id):
            return PaymentValidationResult(False, order, "chat_mismatch")
        if order.provider != provider:
            return PaymentValidationResult(False, order, "provider_mismatch")
        if int(order.amount) != int(amount):
            return PaymentValidationResult(False, order, "amount_mismatch")
        if order.currency != currency:
            return PaymentValidationResult(False, order, "currency_mismatch")
        return PaymentValidationResult(True, order)

    def handle_successful_payment(self, **kwargs) -> PaymentHandlingResult:
        self.successful_requests.append(dict(kwargs))
        validation = self.validate_order_payment(
            kwargs["payload"],
            user_id=kwargs["user_id"],
            chat_id=kwargs["chat_id"],
            provider=kwargs["provider"],
            amount=kwargs["amount"],
            currency=kwargs["currency"],
            require_pending=False,
        )
        if not validation.valid:
            self.unknown_payloads.append(kwargs["payload"])
            return PaymentHandlingResult(False, reason=validation.reason)
        charge_id = kwargs["telegram_payment_charge_id"] or kwargs.get("provider_payment_charge_id")
        assert validation.order is not None
        if charge_id in self._processed_charges:
            return PaymentHandlingResult(False, validation.order.product, duplicate=True, reason="duplicate_charge")
        self._processed_charges.add(charge_id)
        self.grants.append(validation.order.product)
        return PaymentHandlingResult(True, validation.order.product)

    def mark_order_failed(self, order_id: str, reason: str | None = None) -> PaymentOrder:
        self.failed_orders.append((order_id, reason))
        order = self.orders[order_id]
        failed = PaymentOrder(
            order_id=order.order_id,
            user_id=order.user_id,
            chat_id=order.chat_id,
            product=order.product,
            provider=order.provider,
            amount=order.amount,
            currency=order.currency,
            nonce=order.nonce,
            status="failed",
            failure_reason=reason,
        )
        self.orders[order_id] = failed
        return failed


class FailingSuccessfulPaymentService:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.successful_requests: list[dict[str, object]] = []

    def handle_successful_payment(self, **kwargs) -> PaymentHandlingResult:
        self.successful_requests.append(dict(kwargs))
        raise self.exc


def _fake_amount(provider: str, product: str) -> int:
    if provider == PROVIDER_TELEGRAM_STARS:
        return {
            PRODUCT_SUBSCRIPTION_MONTH: 400,
            PRODUCT_EXTRA_ONE_DAY: 35,
            PRODUCT_EXTRA_WEEKLY_PDF: 170,
        }[product]
    return {
        PRODUCT_SUBSCRIPTION_MONTH: 59_900,
        PRODUCT_EXTRA_ONE_DAY: 5_000,
        PRODUCT_EXTRA_WEEKLY_PDF: 25_000,
    }[product]


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
        now=datetime.now(UTC),
    )
    entitlement.monthly_one_day_remaining = one_day_remaining
    entitlement.monthly_weekly_pdf_remaining = weekly_pdf_remaining
    entitlement.extra_one_day_remaining = extra_one_day_remaining
    entitlement.extra_weekly_pdf_remaining = extra_weekly_pdf_remaining
    telegram_app.save_entitlements(path, {chat_id: entitlement})
    return entitlement


def _one_day_plan_targets() -> NutritionTargets:
    return NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector({"energy_kcal": 2000}),
        calorie_bounds=(1800, 2200),
        macro_bounds={},
    )


def _one_day_plan_for_runtime_tests(*, meals: tuple[Meal, ...] | None = None, can_generate: bool = True) -> MealPlan:
    if meals is None:
        meals = (
            Meal("Breakfast", (), "Recipe 1", recipe_id="r1"),
            Meal("Lunch", (), "Recipe 2", recipe_key="lunch:curated:r2"),
        )
    return MealPlan(
        meals,
        _one_day_plan_targets(),
        SafetyResult(can_generate_plan=can_generate, red_flags=() if can_generate else ("unsafe",)),
    )


class FakeOneDayGenerationRuntime:
    def __init__(
        self,
        *,
        admit_status: OneDayAdmitJobResultStatus = OneDayAdmitJobResultStatus.ADMITTED,
        queued_status: QueuedJobAdmissionResultStatus | None = None,
        start_status: OneDayStartJobResultStatus = OneDayStartJobResultStatus.STARTED,
        fail_mark_send_started: bool = False,
        duplicate_on_existing_idempotency: bool = False,
        consumption_source: str | None = "free_trial",
    ) -> None:
        self.admit_status = admit_status
        if queued_status is None and admit_status == OneDayAdmitJobResultStatus.ACTIVE_DUPLICATE:
            queued_status = QueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE
        elif queued_status is None and admit_status == OneDayAdmitJobResultStatus.EXISTING_IDEMPOTENCY:
            queued_status = QueuedJobAdmissionResultStatus.EXISTING_IDEMPOTENCY
        elif queued_status is None and start_status == OneDayStartJobResultStatus.DENIED:
            queued_status = QueuedJobAdmissionResultStatus.DENIED
        self.queued_status = queued_status or QueuedJobAdmissionResultStatus.ADMITTED
        self.start_status = start_status
        self.fail_mark_send_started = fail_mark_send_started
        self.duplicate_on_existing_idempotency = duplicate_on_existing_idempotency
        self.consumption_source = consumption_source
        self.calls: list[tuple[str, object]] = []
        self.events: list[str] = []
        self.expected_counts: list[int] = []
        self.delivered_keys: list[str] = []
        self.admitted_snapshots: list[OneDayGenerationRequestSnapshot] = []
        self.job = self._job(chat_id=0, idempotency_key="initial")
        self.jobs_by_idempotency_key: dict[str, OneDayGenerationJob] = {}

    def _job(self, *, chat_id: int, idempotency_key: str) -> OneDayGenerationJob:
        return OneDayGenerationJob(
            job_id=uuid4(),
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            status="queued",
            consumption_source=None,
            refund_status="not_required",
            delivery_status="not_started",
            expected_value_messages=0,
            delivered_value_messages=0,
            stale_after=datetime(2026, 5, 26, tzinfo=UTC),
        )

    def cleanup_stale(self, *, chat_id: int):
        self.events.append("runtime:cleanup_stale")
        self.calls.append(("cleanup_stale", chat_id))

    def admit(self, *, chat_id: int, idempotency_key: str, metadata=None):
        self.events.append("runtime:admit")
        self.calls.append(("admit", {"chat_id": chat_id, "idempotency_key": idempotency_key, "metadata": metadata}))
        if self.duplicate_on_existing_idempotency and idempotency_key in self.jobs_by_idempotency_key:
            self.job = self.jobs_by_idempotency_key[idempotency_key]
            return AdmitJobResult(OneDayAdmitJobResultStatus.EXISTING_IDEMPOTENCY, self.job)
        self.job = self._job(chat_id=chat_id, idempotency_key=idempotency_key)
        self.jobs_by_idempotency_key[idempotency_key] = self.job
        return AdmitJobResult(self.admit_status, self.job)

    def admit_queued(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        request_snapshot: OneDayGenerationRequestSnapshot,
        metadata=None,
        test_access: bool = False,
    ):
        self.events.append("runtime:admit_queued")
        self.calls.append(
            (
                "admit_queued",
                {
                    "chat_id": chat_id,
                    "idempotency_key": idempotency_key,
                    "request_snapshot": request_snapshot,
                    "metadata": metadata,
                    "test_access": test_access,
                },
            )
        )
        if self.duplicate_on_existing_idempotency and idempotency_key in self.jobs_by_idempotency_key:
            self.job = self.jobs_by_idempotency_key[idempotency_key]
            return QueuedJobAdmissionResult(QueuedJobAdmissionResultStatus.EXISTING_IDEMPOTENCY, self.job)
        if self.queued_status != QueuedJobAdmissionResultStatus.ADMITTED:
            return QueuedJobAdmissionResult(self.queued_status, self.job)
        self.job = replace(
            self._job(chat_id=chat_id, idempotency_key=idempotency_key),
            request_snapshot=request_snapshot,
            consumption_source="test_access" if test_access else self.consumption_source,
            refund_status="pending" if not test_access and self.consumption_source in {"free_trial", "monthly", "extra"} else "not_required",
        )
        self.jobs_by_idempotency_key[idempotency_key] = self.job
        self.admitted_snapshots.append(request_snapshot)
        return QueuedJobAdmissionResult(QueuedJobAdmissionResultStatus.ADMITTED, self.job)

    def start_job_and_consume(self, job_id, *, test_access: bool = False):
        self.events.append("runtime:start_job_and_consume")
        self.calls.append(("start_job_and_consume", {"job_id": job_id, "test_access": test_access}))
        self.job = replace(
            self.job,
            status="running",
            consumption_source=self.consumption_source,
            refund_status="pending" if self.consumption_source == "free_trial" else "not_required",
        )
        return StartJobResult(self.start_status, self.job)

    def set_expected_value_messages(self, job_id, expected_count: int):
        self.events.append(f"runtime:set_expected:{expected_count}")
        self.calls.append(("set_expected_value_messages", {"job_id": job_id, "expected_count": expected_count}))
        self.expected_counts.append(expected_count)
        return SetExpectedValueMessagesResult(SetExpectedValueMessagesResultStatus.SET, self.job)

    def mark_send_started(self, job_id):
        self.events.append("runtime:mark_send_started")
        self.calls.append(("mark_send_started", job_id))
        if self.fail_mark_send_started:
            raise RuntimeError("send-start marker failed")
        return MarkSendStartedResult(OneDayMarkSendStartedResultStatus.SEND_STARTED, self.job)

    def mark_value_message_delivered(self, job_id, *, value_message_key: str):
        self.events.append(f"runtime:mark_delivered:{value_message_key}")
        self.calls.append(("mark_value_message_delivered", {"job_id": job_id, "value_message_key": value_message_key}))
        self.delivered_keys.append(value_message_key)
        return MarkValueMessageDeliveredResult(MarkValueMessageDeliveredResultStatus.DELIVERED, self.job)

    def finish_success(self, job_id):
        self.events.append("runtime:finish_success")
        self.calls.append(("finish_success", job_id))
        return FinishJobResult(OneDayFinishJobResultStatus.SUCCEEDED, self.job)

    def finish_failure_and_refund_once(self, job_id, *, reason: str | None = None):
        self.events.append(f"runtime:finish_failure:{reason}")
        self.calls.append(("finish_failure_and_refund_once", {"job_id": job_id, "reason": reason}))
        return FinishJobResult(OneDayFinishJobResultStatus.FAILED, self.job)


def _install_one_day_runtime(monkeypatch, runtime: FakeOneDayGenerationRuntime | None) -> None:
    monkeypatch.setattr(telegram_app, "_ONE_DAY_GENERATION_JOB_RUNTIME", runtime, raising=False)


def _trial_cta_messages(message: FakeMessage) -> list[str]:
    return [text for text, _ in message.texts if text.startswith(TRIAL_SUBSCRIPTION_TEXT)]


class _RecordingChatHistoryStore:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, list[str]]]] = []
        self.memory_snapshots: list[tuple[list[str], list[str]]] = []

    def save_chat_state(self, chat_id: int, chat_state) -> None:
        self.memory_snapshots.append(
            (
                list(RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, [])),
                list(RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, [])),
            )
        )
        self.calls.append(
            (
                chat_id,
                {
                    "recipe_ids": list(chat_state.get("recipe_ids", [])),
                    "recipe_keys": list(chat_state.get("recipe_keys", [])),
                },
            )
        )


class _FailingChatHistoryStore:
    def save_chat_state(self, chat_id: int, chat_state) -> None:
        raise ChatStateStorageError("history save failed")


class _FailingChatHistorySaveStore:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.load_calls = 0
        self.save_calls = 0

    def load_all(self):
        self.load_calls += 1
        return {}

    def save_chat_state(self, chat_id: int, chat_state) -> None:
        self.save_calls += 1
        raise self.exc


class _FailingChatStateLoadStore:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.load_calls = 0

    def load_all(self):
        self.load_calls += 1
        raise self.exc

    def save_chat_state(self, chat_id: int, chat_state) -> None:
        raise AssertionError("read failure tests must not write chat state")


def _install_failing_chat_state_load(monkeypatch, exc: Exception) -> _FailingChatStateLoadStore:
    store = _FailingChatStateLoadStore(exc)
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    return store


def _history_item(recipe_id: str, recipe_key: str) -> telegram_app.RecipeHistoryItem:
    return telegram_app.RecipeHistoryItem(recipe_id=recipe_id, recipe_key=recipe_key)


def test_remember_recipe_history_saves_next_history_before_cache_update(monkeypatch) -> None:
    chat_id = 91_047
    store = _RecordingChatHistoryStore()
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = ["old-id"]
    RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = ["old-key"]

    try:
        telegram_app._remember_recipe_history_items(
            chat_id,
            [_history_item("new-id", "new-key")],
        )

        assert store.calls == [
            (
                chat_id,
                {
                    "recipe_ids": ["old-id", "new-id"],
                    "recipe_keys": ["old-key", "new-key"],
                },
            )
        ]
        assert store.memory_snapshots == [(["old-id"], ["old-key"])]
        assert RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] == ["old-id", "new-id"]
        assert RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] == ["old-key", "new-key"]
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


def test_remember_recipe_history_save_failure_leaves_memory_unchanged(monkeypatch) -> None:
    chat_id = 91_048
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: _FailingChatHistoryStore())
    RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = ["old-id"]
    RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = ["old-key"]

    try:
        with pytest.raises(ChatStateStorageError, match="history save failed"):
            telegram_app._remember_recipe_history_items(
                chat_id,
                [_history_item("new-id", "new-key")],
            )

        assert RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] == ["old-id"]
        assert RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] == ["old-key"]
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


def test_remember_recipe_history_save_failure_does_not_create_partial_cache(monkeypatch) -> None:
    chat_id = 91_049
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: _FailingChatHistoryStore())

    try:
        with pytest.raises(ChatStateStorageError, match="history save failed"):
            telegram_app._remember_recipe_history_items(
                chat_id,
                [_history_item("new-id", "new-key")],
            )

        assert chat_id not in RECENT_RECIPE_IDS_BY_CHAT_ID
        assert chat_id not in RECENT_RECIPE_KEYS_BY_CHAT_ID
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


def test_save_chat_history_wraps_raw_backend_exceptions(monkeypatch) -> None:
    chat_id = 91_053
    store = _FailingChatHistorySaveStore(RuntimeError("raw history save failed"))
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)

    with pytest.raises(ChatStateStorageError, match="Could not save chat history") as exc_info:
        telegram_app._save_chat_history(
            chat_id,
            recipe_ids=["new-id"],
            recipe_keys=["new-key"],
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert store.save_calls == 1


def test_remember_recipe_history_raw_save_failure_leaves_memory_unchanged(monkeypatch) -> None:
    chat_id = 91_054
    store = _FailingChatHistorySaveStore(RuntimeError("raw history save failed"))
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = ["old-id"]
    RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = ["old-key"]

    try:
        with pytest.raises(ChatStateStorageError, match="Could not save chat history"):
            telegram_app._remember_recipe_history_items(
                chat_id,
                [_history_item("new-id", "new-key")],
            )

        assert RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] == ["old-id"]
        assert RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] == ["old-key"]
        assert store.save_calls == 1
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


def test_remember_recipe_history_keeps_bounded_window(monkeypatch) -> None:
    chat_id = 91_050
    store = _RecordingChatHistoryStore()
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    old_ids = [f"old-id-{index}" for index in range(telegram_app.RECENT_RECIPE_LIMIT - 1)]
    old_keys = [f"old-key-{index}" for index in range(telegram_app.RECENT_RECIPE_LIMIT - 1)]
    RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = list(old_ids)
    RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = list(old_keys)

    try:
        telegram_app._remember_recipe_history_items(
            chat_id,
            [
                _history_item("new-id-1", "new-key-1"),
                _history_item("new-id-2", "new-key-2"),
            ],
        )

        expected_ids = (old_ids + ["new-id-1", "new-id-2"])[-telegram_app.RECENT_RECIPE_LIMIT:]
        expected_keys = (old_keys + ["new-key-1", "new-key-2"])[-telegram_app.RECENT_RECIPE_LIMIT:]
        assert store.calls == [(chat_id, {"recipe_ids": expected_ids, "recipe_keys": expected_keys})]
        assert RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] == expected_ids
        assert RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] == expected_keys
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


def test_one_day_recipe_history_order_remains_meal_order(monkeypatch) -> None:
    chat_id = 91_051
    store = _RecordingChatHistoryStore()
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    plan = _one_day_plan_for_runtime_tests(
        meals=(
            Meal("Breakfast", (), "Recipe 1", recipe_id="breakfast-id", recipe_key="breakfast:key"),
            Meal("Lunch", (), "Recipe 2", recipe_id="lunch-id", recipe_key="lunch:key"),
            Meal("Dinner", (), "Recipe 3", recipe_id="dinner-id", recipe_key="dinner:key"),
        )
    )

    try:
        telegram_app._remember_recipes(chat_id, plan)

        assert store.calls == [
            (
                chat_id,
                {
                    "recipe_ids": ["breakfast-id", "lunch-id", "dinner-id"],
                    "recipe_keys": ["breakfast:key", "lunch:key", "dinner:key"],
                },
            )
        ]
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


def test_weekly_recipe_history_order_remains_day_then_meal(monkeypatch) -> None:
    chat_id = 91_052
    store = _RecordingChatHistoryStore()
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    plans = (
        _one_day_plan_for_runtime_tests(
            meals=(
                Meal("Day 1 Breakfast", (), "Recipe 1", recipe_id="day-1-breakfast", recipe_key="d1:breakfast"),
                Meal("Day 1 Dinner", (), "Recipe 2", recipe_id="day-1-dinner", recipe_key="d1:dinner"),
            )
        ),
        _one_day_plan_for_runtime_tests(
            meals=(
                Meal("Day 2 Breakfast", (), "Recipe 3", recipe_id="day-2-breakfast", recipe_key="d2:breakfast"),
                Meal("Day 2 Dinner", (), "Recipe 4", recipe_id="day-2-dinner", recipe_key="d2:dinner"),
            )
        ),
    )
    entries: list[telegram_app.RecipeHistoryItem] = []
    for day_index, plan_result in enumerate(plans):
        entries.extend(
            telegram_app._recipe_history_items_from_plan(
                plan_result,
                "weekly_pdf",
                day_index=day_index,
            )
        )

    try:
        telegram_app._remember_recipe_history_items(chat_id, entries)

        assert store.calls == [
            (
                chat_id,
                {
                    "recipe_ids": [
                        "day-1-breakfast",
                        "day-1-dinner",
                        "day-2-breakfast",
                        "day-2-dinner",
                    ],
                    "recipe_keys": [
                        "d1:breakfast",
                        "d1:dinner",
                        "d2:breakfast",
                        "d2:dinner",
                    ],
                },
            )
        ]
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "load_error",
    [
        ChatStateStorageError("json profile load failed"),
        RuntimeError("postgres profile load failed"),
    ],
)
async def test_plan_chat_state_read_failure_sends_notice_without_questionnaire(monkeypatch, load_error) -> None:
    chat_id = 92_010
    store = _install_failing_chat_state_load(monkeypatch, load_error)
    questionnaire_started = False
    calculation_sent = False

    async def fail_start_questionnaire(*_args, **_kwargs) -> None:
        nonlocal questionnaire_started
        questionnaire_started = True
        raise AssertionError("profile read failure must not start questionnaire")

    async def fail_send_calculation_options(*_args, **_kwargs) -> None:
        nonlocal calculation_sent
        calculation_sent = True
        raise AssertionError("profile read failure must not send calculation options")

    monkeypatch.setattr(telegram_app, "_start_questionnaire", fail_start_questionnaire)
    monkeypatch.setattr(telegram_app, "_send_calculation_options", fail_send_calculation_options)
    message = FakeMessage(chat_id)

    try:
        await telegram_app.plan(message)

        assert message.texts == [(CHAT_STATE_READ_ERROR_TEXT, None)]
        assert store.load_calls == 1
        assert not questionnaire_started
        assert not calculation_sent
        assert chat_id not in SESSION_BY_CHAT_ID
        assert chat_id not in PROFILE_BY_CHAT_ID
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("entry_text", "load_error"),
    [
        (ONE_DAY_PLAN_TEXT, ChatStateStorageError("json profile load failed")),
        (telegram_app.REPEAT_PLAN_TEXT, RuntimeError("postgres profile load failed")),
    ],
)
async def test_one_day_profile_read_failure_sends_notice_without_generation_or_consumption(
    monkeypatch,
    entry_text,
    load_error,
) -> None:
    chat_id = 92_011
    store = _install_failing_chat_state_load(monkeypatch, load_error)
    generation_called = False
    consumption_called = False

    async def fail_send_one_day_plan_with_access(*_args, **_kwargs) -> bool:
        nonlocal generation_called
        generation_called = True
        raise AssertionError("profile read failure must not generate a one-day plan")

    def fail_consume_generation_attempt(*_args, **_kwargs):
        nonlocal consumption_called
        consumption_called = True
        raise AssertionError("profile read failure must not consume an attempt")

    monkeypatch.setattr(telegram_app, "_send_one_day_plan_with_access", fail_send_one_day_plan_with_access)
    monkeypatch.setattr(telegram_app, "_consume_generation_attempt", fail_consume_generation_attempt)
    message = FakeMessage(chat_id, text=entry_text)

    try:
        await handle_answer(message)

        assert message.texts == [(CHAT_STATE_READ_ERROR_TEXT, None)]
        assert store.load_calls == 1
        assert not generation_called
        assert not consumption_called
        assert chat_id not in SESSION_BY_CHAT_ID
        assert chat_id not in PROFILE_BY_CHAT_ID
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "load_error",
    [
        ChatStateStorageError("json profile load failed"),
        RuntimeError("postgres profile load failed"),
    ],
)
async def test_weekly_profile_read_failure_sends_notice_without_queue(monkeypatch, load_error) -> None:
    chat_id = 92_012
    store = _install_failing_chat_state_load(monkeypatch, load_error)
    queue_called = False

    async def fail_send_week_plan_with_access(*_args, **_kwargs) -> bool:
        nonlocal queue_called
        queue_called = True
        raise AssertionError("profile read failure must not enqueue a weekly PDF")

    monkeypatch.setattr(telegram_app, "_send_week_plan_with_access", fail_send_week_plan_with_access)
    message = FakeMessage(chat_id, text=WEEK_PLAN_PDF_TEXT)

    try:
        await handle_answer(message)

        assert message.texts == [(CHAT_STATE_READ_ERROR_TEXT, None)]
        assert store.load_calls == 1
        assert not queue_called
        assert chat_id not in SESSION_BY_CHAT_ID
        assert chat_id not in PROFILE_BY_CHAT_ID
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


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
        ("promo", "Ввести промокод"),
        ("privacy", "Политика конфиденциальности"),
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
    telegram_app.grant_test_access(entitlement, now=datetime.now(UTC))
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
async def test_week_plan_history_read_failure_stops_status_and_returns_false(monkeypatch, tmp_path) -> None:
    chat_id = 92_003
    store = _install_failing_chat_state_load(monkeypatch, RuntimeError("postgres history load failed"))

    def fail_build_week_plans_with_recent_fallback(*_args, **_kwargs):
        raise AssertionError("weekly history read failure must not fallback to empty history")

    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(
        telegram_app,
        "_build_week_plans_with_recent_fallback",
        fail_build_week_plans_with_recent_fallback,
    )
    message = FakeMessage(chat_id)
    try:
        sent = await _send_week_plan(message, profile_with())

        assert sent is False
        assert store.load_calls == 1
        assert message.documents == []
        assert message.texts[0][0] == telegram_app.WEEK_PDF_STATUS_INITIAL_TEXT
        assert message.edits
        assert message.edits[-1][0] == CHAT_STATE_READ_ERROR_TEXT
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
async def test_questionnaire_completion_save_failure_preserves_state_without_plan(
    monkeypatch, tmp_path
) -> None:
    chat_id = 91_045
    save_saw_cached_profile = None
    load_history_called = False
    calculation_options_called = False
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    SESSION_BY_CHAT_ID[chat_id] = start_session()
    PLAN_COUNT_BY_CHAT_ID[chat_id] = 7
    PLAN_SEED_OFFSET_BY_CHAT_ID[chat_id] = 11
    message = FakeMessage(chat_id)

    def failing_save_chat_profile(saved_chat_id, profile) -> None:
        nonlocal save_saw_cached_profile
        assert saved_chat_id == chat_id
        save_saw_cached_profile = saved_chat_id in PROFILE_BY_CHAT_ID
        raise ChatStateStorageError("profile save failed")

    def fake_load_chat_history(_chat_id) -> None:
        nonlocal load_history_called
        load_history_called = True

    async def fake_send_calculation_options(*_args, **_kwargs) -> None:
        nonlocal calculation_options_called
        calculation_options_called = True

    monkeypatch.setattr(telegram_app, "_save_chat_profile", failing_save_chat_profile)
    monkeypatch.setattr(telegram_app, "_load_chat_history", fake_load_chat_history)
    monkeypatch.setattr(telegram_app, "_send_calculation_options", fake_send_calculation_options)

    try:
        await _advance_questionnaire_to(message, "excluded_foods")
        original_session = SESSION_BY_CHAT_ID[chat_id]
        assert original_session.current_question is not None
        assert original_session.current_question.key == "excluded_foods"
        sent_before_completion = len(message.texts)
        final_answer = _sample_questionnaire_answer(original_session.current_question)
        await _handle_questionnaire_answer(message, final_answer)

        new_texts = [text for text, _ in message.texts[sent_before_completion:]]
        assert new_texts == ["Не удалось сохранить анкету. Попробуйте позже."]
        assert save_saw_cached_profile is False
        assert chat_id not in PROFILE_BY_CHAT_ID
        assert chat_id in SESSION_BY_CHAT_ID
        stored_session = SESSION_BY_CHAT_ID[chat_id]
        assert stored_session is original_session
        assert stored_session == original_session
        assert not stored_session.is_complete
        assert stored_session.current_question is not None
        assert stored_session.current_question.key == "excluded_foods"
        assert PLAN_COUNT_BY_CHAT_ID[chat_id] == 7
        assert PLAN_SEED_OFFSET_BY_CHAT_ID[chat_id] == 11
        assert not load_history_called
        assert not calculation_options_called
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


def test_question_keyboard_marks_selected_answer_with_product_check() -> None:
    chat_id = 91_030
    telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID[chat_id] = "owner-token"
    try:
        keyboard = telegram_app._question_keyboard(
            SimpleNamespace(options=("male", "female")),
            selected_index=1,
            chat_id=chat_id,
            step_index=2,
        )
    finally:
        telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.pop(chat_id, None)

    buttons = [button.text for row in keyboard.inline_keyboard for button in row]
    assert buttons[:2] == ["male", f"{telegram_app.SELECTED_ANSWER_PREFIX}female"]


@pytest.mark.anyio
async def test_current_questionnaire_callback_advances_normally(monkeypatch, tmp_path) -> None:
    chat_id = 91_031
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    message = FakeMessage(chat_id)
    try:
        await telegram_app._start_questionnaire(message)
        await _advance_questionnaire_to(message, "sex")
        callback_data = _first_callback_data_from_last_message(message)
        selected_answer = SESSION_BY_CHAT_ID[chat_id].current_question.options[0]

        callback = FakeCallback(callback_data, message)
        await telegram_app.handle_callback(callback)

        session = SESSION_BY_CHAT_ID[chat_id]
        assert callback.answers == [selected_answer]
        assert session.current_question.key == "height_cm"
        assert session.answers["sex"] == selected_answer
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        getattr(telegram_app, "QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID", {}).pop(chat_id, None)


@pytest.mark.anyio
async def test_answer_callback_marks_selected_option_and_keeps_owner_token(monkeypatch, tmp_path) -> None:
    chat_id = 91_030
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    message = FakeMessage(chat_id)
    session = telegram_app.QuestionnaireSession({"age": "32"}, step_index=1)
    SESSION_BY_CHAT_ID[chat_id] = session
    telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID[chat_id] = "owner-token"
    callback_data = telegram_app._question_answer_callback_data(
        1,
        chat_id=chat_id,
        step_index=session.step_index,
    )
    callback = FakeCallback(callback_data, message, user_id=chat_id)

    try:
        await telegram_app.handle_callback(callback)
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.pop(chat_id, None)

    selected_answer = QUESTIONS[1].options[1]
    assert callback.answers[-1] == selected_answer
    assert message.edited_reply_markups
    assert f"{telegram_app.SELECTED_ANSWER_PREFIX}{selected_answer}" in [
        button.text
        for row in message.edited_reply_markups[-1].inline_keyboard
        for button in row
    ]
    assert message.texts[-1][0] == QUESTIONS[2].prompt


@pytest.mark.anyio
async def test_repeated_questionnaire_callback_delivery_does_not_advance_again(monkeypatch, tmp_path) -> None:
    chat_id = 91_032
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    message = FakeMessage(chat_id)
    try:
        await telegram_app._start_questionnaire(message)
        await _advance_questionnaire_to(message, "goal")
        callback_data = _first_callback_data_from_last_message(message)
        selected_answer = SESSION_BY_CHAT_ID[chat_id].current_question.options[0]

        await telegram_app.handle_callback(FakeCallback(callback_data, message))
        repeated_callback = FakeCallback(callback_data, message)
        await telegram_app.handle_callback(repeated_callback)

        session = SESSION_BY_CHAT_ID[chat_id]
        assert repeated_callback.answers[-1]
        assert session.current_question.key == "activity"
        assert session.answers["goal"] == selected_answer
        assert "activity" not in session.answers
        assert chat_id not in PROFILE_BY_CHAT_ID
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        getattr(telegram_app, "QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID", {}).pop(chat_id, None)


@pytest.mark.anyio
async def test_stale_questionnaire_callback_from_previous_step_does_not_complete(monkeypatch, tmp_path) -> None:
    chat_id = 91_033
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    message = FakeMessage(chat_id)
    try:
        await telegram_app._start_questionnaire(message)
        await _advance_questionnaire_to(message, "conditions")
        stale_callback_data = _first_callback_data_from_last_message(message)
        await _handle_questionnaire_answer(
            message,
            _sample_questionnaire_answer(SESSION_BY_CHAT_ID[chat_id].current_question),
        )

        stale_callback = FakeCallback(stale_callback_data, message)
        await telegram_app.handle_callback(stale_callback)

        session = SESSION_BY_CHAT_ID.get(chat_id)
        assert stale_callback.answers[-1]
        assert session is not None
        assert session.current_question.key == "excluded_foods"
        assert "excluded_foods" not in session.answers
        assert chat_id not in PROFILE_BY_CHAT_ID
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)
        getattr(telegram_app, "QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID", {}).pop(chat_id, None)


@pytest.mark.anyio
async def test_cancelled_questionnaire_callback_does_not_mutate_restarted_flow(monkeypatch, tmp_path) -> None:
    chat_id = 91_034
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    message = FakeMessage(chat_id)
    try:
        await telegram_app._start_questionnaire(message)
        await _advance_questionnaire_to(message, "sex")
        cancelled_callback_data = _first_callback_data_from_last_message(message)

        await telegram_app.cancel(FakeMessage(chat_id))
        await telegram_app._start_questionnaire(message)
        await _advance_questionnaire_to(message, "sex")

        stale_callback = FakeCallback(cancelled_callback_data, message)
        await telegram_app.handle_callback(stale_callback)

        session = SESSION_BY_CHAT_ID[chat_id]
        assert stale_callback.answers[-1]
        assert session.current_question.key == "sex"
        assert "sex" not in session.answers
        assert chat_id not in PROFILE_BY_CHAT_ID
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        getattr(telegram_app, "QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID", {}).pop(chat_id, None)


@pytest.mark.anyio
async def test_concurrent_duplicate_questionnaire_callback_same_chat_stales_second(monkeypatch, tmp_path) -> None:
    chat_id = 91_035
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    message = FakeMessage(chat_id)
    first_answer_started = asyncio.Event()
    release_first_answer = asyncio.Event()
    second_answer_started = asyncio.Event()
    release_second_answer = asyncio.Event()
    plan_calls = 0

    class BlockingFirstCallback(FakeCallback):
        async def answer(self, text=None) -> None:
            self.answers.append(text)
            first_answer_started.set()
            await release_first_answer.wait()

    class PausingSecondCallback(FakeCallback):
        async def answer(self, text=None) -> None:
            self.answers.append(text)
            second_answer_started.set()
            await release_second_answer.wait()

    async def fake_send_plan(*_args, **_kwargs) -> bool:
        nonlocal plan_calls
        plan_calls += 1
        return True

    monkeypatch.setattr(telegram_app, "_send_plan", fake_send_plan)
    first_task = None
    second_task = None
    try:
        await telegram_app._start_questionnaire(message, is_trial=True)
        await _advance_questionnaire_to(message, "conditions")
        callback_data = _first_callback_data_from_last_message(message)
        selected_answer = SESSION_BY_CHAT_ID[chat_id].current_question.options[0]

        first_callback = BlockingFirstCallback(callback_data, message)
        second_callback = PausingSecondCallback(callback_data, message)
        first_task = asyncio.create_task(telegram_app.handle_callback(first_callback))
        await asyncio.wait_for(first_answer_started.wait(), timeout=1)

        second_task = asyncio.create_task(telegram_app.handle_callback(second_callback))
        try:
            await asyncio.wait_for(second_answer_started.wait(), timeout=0.1)
        except TimeoutError:
            pass
        else:
            release_second_answer.set()
            await asyncio.sleep(0)

        release_first_answer.set()
        release_second_answer.set()
        await asyncio.gather(first_task, second_task)

        session = SESSION_BY_CHAT_ID.get(chat_id)
        entitlement = telegram_app.load_entitlements(subscriptions_path).get(chat_id, telegram_app.Entitlement())
        assert first_callback.answers == [selected_answer]
        assert second_callback.answers[-1] == telegram_app.STALE_QUESTIONNAIRE_CALLBACK_TEXT
        assert session is not None
        assert session.current_question.key == "excluded_foods"
        assert session.answers["conditions"] == selected_answer
        assert "excluded_foods" not in session.answers
        assert chat_id not in PROFILE_BY_CHAT_ID
        assert plan_calls == 0
        assert entitlement.free_trial_used is False
    finally:
        release_first_answer.set()
        release_second_answer.set()
        cleanup_tasks = [task for task in (first_task, second_task) if task is not None and not task.done()]
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        TRIAL_CHAT_IDS.discard(chat_id)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)
        getattr(telegram_app, "QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID", {}).pop(chat_id, None)
        getattr(telegram_app, "_QUESTIONNAIRE_CALLBACK_LOCK_BY_CHAT_ID", {}).pop(chat_id, None)


@pytest.mark.anyio
async def test_questionnaire_callback_different_chats_do_not_block_each_other(monkeypatch, tmp_path) -> None:
    first_chat_id = 91_036
    second_chat_id = 91_037
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    first_message = FakeMessage(first_chat_id)
    second_message = FakeMessage(second_chat_id)
    first_answer_started = asyncio.Event()
    release_first_answer = asyncio.Event()
    second_answer_started = asyncio.Event()

    class BlockingFirstCallback(FakeCallback):
        async def answer(self, text=None) -> None:
            self.answers.append(text)
            first_answer_started.set()
            await release_first_answer.wait()

    class TrackingSecondCallback(FakeCallback):
        async def answer(self, text=None) -> None:
            self.answers.append(text)
            second_answer_started.set()

    first_task = None
    second_task = None
    try:
        await telegram_app._start_questionnaire(first_message)
        await telegram_app._start_questionnaire(second_message)
        await _advance_questionnaire_to(first_message, "sex")
        await _advance_questionnaire_to(second_message, "sex")
        first_callback_data = _first_callback_data_from_last_message(first_message)
        second_callback_data = _first_callback_data_from_last_message(second_message)
        first_answer = SESSION_BY_CHAT_ID[first_chat_id].current_question.options[0]
        second_answer = SESSION_BY_CHAT_ID[second_chat_id].current_question.options[0]

        first_callback = BlockingFirstCallback(first_callback_data, first_message)
        second_callback = TrackingSecondCallback(second_callback_data, second_message)
        first_task = asyncio.create_task(telegram_app.handle_callback(first_callback))
        await asyncio.wait_for(first_answer_started.wait(), timeout=1)

        second_task = asyncio.create_task(telegram_app.handle_callback(second_callback))
        await asyncio.wait_for(second_answer_started.wait(), timeout=1)

        second_session = SESSION_BY_CHAT_ID[second_chat_id]
        assert second_callback.answers == [second_answer]
        assert second_session.current_question.key == "height_cm"
        assert second_session.answers["sex"] == second_answer

        release_first_answer.set()
        await first_task
        first_session = SESSION_BY_CHAT_ID[first_chat_id]
        assert first_callback.answers == [first_answer]
        assert first_session.current_question.key == "height_cm"
        assert first_session.answers["sex"] == first_answer
    finally:
        release_first_answer.set()
        cleanup_tasks = [task for task in (first_task, second_task) if task is not None and not task.done()]
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        for chat_id in (first_chat_id, second_chat_id):
            SESSION_BY_CHAT_ID.pop(chat_id, None)
            PROFILE_BY_CHAT_ID.pop(chat_id, None)
            getattr(telegram_app, "QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID", {}).pop(chat_id, None)
            getattr(telegram_app, "_QUESTIONNAIRE_CALLBACK_LOCK_BY_CHAT_ID", {}).pop(chat_id, None)


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
async def test_one_day_plan_double_callback_same_chat_consumes_once(monkeypatch, tmp_path) -> None:
    chat_id = 91_020
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    _save_active_subscription(subscriptions_path, chat_id, one_day_remaining=2, weekly_pdf_remaining=1)
    PROFILE_BY_CHAT_ID[chat_id] = profile_with()
    first_message = FakeMessage(chat_id)
    second_message = FakeMessage(chat_id)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    send_calls = 0

    async def controlled_send_plan(message, *_args, **_kwargs) -> bool:
        nonlocal send_calls
        send_calls += 1
        if message.chat.id == chat_id and send_calls == 1:
            first_started.set()
            await release_first.wait()
        return True

    monkeypatch.setattr(telegram_app, "_send_plan", controlled_send_plan)
    first_task = None
    try:
        first_task = asyncio.create_task(telegram_app.handle_callback(FakeCallback(CALLBACK_ONE_DAY_PLAN, first_message)))
        await asyncio.wait_for(first_started.wait(), timeout=1)

        await telegram_app.handle_callback(FakeCallback(CALLBACK_ONE_DAY_PLAN, second_message))
        entitlement_after_duplicate = telegram_app.load_entitlements(subscriptions_path)[chat_id]

        assert send_calls == 1
        assert entitlement_after_duplicate.monthly_one_day_remaining == 1
        assert second_message.texts == [(telegram_app.ONE_DAY_PLAN_ALREADY_RUNNING_TEXT, None)]

        release_first.set()
        await first_task
        final_entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
        assert final_entitlement.monthly_one_day_remaining == 1
    finally:
        release_first.set()
        if first_task is not None and not first_task.done():
            await asyncio.gather(first_task, return_exceptions=True)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_concurrent_one_day_requests_same_chat_consume_once(monkeypatch, tmp_path) -> None:
    chat_id = 91_021
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    _save_active_subscription(subscriptions_path, chat_id, one_day_remaining=2, weekly_pdf_remaining=1)
    first_message = FakeMessage(chat_id)
    second_message = FakeMessage(chat_id)
    third_message = FakeMessage(chat_id)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    send_calls = 0

    async def controlled_send_plan(message, *_args, **_kwargs) -> bool:
        nonlocal send_calls
        send_calls += 1
        if message.chat.id == chat_id and send_calls == 1:
            first_started.set()
            await release_first.wait()
        return True

    monkeypatch.setattr(telegram_app, "_send_plan", controlled_send_plan)
    first_task = None
    try:
        first_task = asyncio.create_task(telegram_app._send_one_day_plan_with_access(first_message, profile_with()))
        await asyncio.wait_for(first_started.wait(), timeout=1)

        duplicate_sent = await telegram_app._send_one_day_plan_with_access(second_message, profile_with())
        entitlement_after_duplicate = telegram_app.load_entitlements(subscriptions_path)[chat_id]

        assert duplicate_sent is False
        assert send_calls == 1
        assert entitlement_after_duplicate.monthly_one_day_remaining == 1
        assert second_message.texts == [(telegram_app.ONE_DAY_PLAN_ALREADY_RUNNING_TEXT, None)]

        release_first.set()
        assert await first_task is True

        retry_sent = await telegram_app._send_one_day_plan_with_access(third_message, profile_with())
        final_entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
        assert retry_sent is True
        assert send_calls == 2
        assert final_entitlement.monthly_one_day_remaining == 0
    finally:
        release_first.set()
        if first_task is not None and not first_task.done():
            await asyncio.gather(first_task, return_exceptions=True)


@pytest.mark.anyio
async def test_one_day_failure_releases_guard_and_allows_retry(monkeypatch, tmp_path) -> None:
    chat_id = 91_022
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    _save_active_subscription(subscriptions_path, chat_id, one_day_remaining=1, weekly_pdf_remaining=1)
    send_calls = 0

    async def flaky_send_plan(*_args, **_kwargs) -> bool:
        nonlocal send_calls
        send_calls += 1
        if send_calls == 1:
            raise RuntimeError("one-day send failed")
        return True

    monkeypatch.setattr(telegram_app, "_send_plan", flaky_send_plan)

    with pytest.raises(RuntimeError, match="one-day send failed"):
        await telegram_app._send_one_day_plan_with_access(FakeMessage(chat_id), profile_with())

    after_failure = telegram_app.load_entitlements(subscriptions_path)[chat_id]
    assert after_failure.monthly_one_day_remaining == 1

    sent = await telegram_app._send_one_day_plan_with_access(FakeMessage(chat_id), profile_with())

    after_retry = telegram_app.load_entitlements(subscriptions_path)[chat_id]
    assert sent is True
    assert send_calls == 2
    assert after_retry.monthly_one_day_remaining == 0


@pytest.mark.anyio
async def test_one_day_generation_different_chats_do_not_block_each_other(monkeypatch, tmp_path) -> None:
    first_chat_id = 91_023
    second_chat_id = 91_024
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    _save_active_subscription(subscriptions_path, first_chat_id, one_day_remaining=1, weekly_pdf_remaining=1)
    _save_active_subscription(subscriptions_path, second_chat_id, one_day_remaining=1, weekly_pdf_remaining=1)
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_requests = asyncio.Event()
    started_chat_ids: list[int] = []

    async def controlled_send_plan(message, *_args, **_kwargs) -> bool:
        started_chat_ids.append(message.chat.id)
        if message.chat.id == first_chat_id:
            first_started.set()
        if message.chat.id == second_chat_id:
            second_started.set()
        await release_requests.wait()
        return True

    monkeypatch.setattr(telegram_app, "_send_plan", controlled_send_plan)
    first_task = asyncio.create_task(
        telegram_app._send_one_day_plan_with_access(FakeMessage(first_chat_id), profile_with())
    )
    second_task = None
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1)

        second_task = asyncio.create_task(
            telegram_app._send_one_day_plan_with_access(FakeMessage(second_chat_id), profile_with())
        )
        await asyncio.wait_for(second_started.wait(), timeout=1)

        release_requests.set()
        assert await first_task is True
        assert await second_task is True
        assert started_chat_ids == [first_chat_id, second_chat_id]
    finally:
        release_requests.set()
        cleanup_tasks = [first_task]
        if second_task is not None:
            cleanup_tasks.append(second_task)
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)


@pytest.mark.anyio
async def test_one_day_json_backend_preserves_legacy_consume_refund_behavior(monkeypatch, tmp_path) -> None:
    chat_id = 91_025
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    _install_one_day_runtime(monkeypatch, None)
    _save_active_subscription(subscriptions_path, chat_id, one_day_remaining=1, weekly_pdf_remaining=1)
    send_calls = 0

    async def fake_send_plan(*_args, **_kwargs) -> bool:
        nonlocal send_calls
        send_calls += 1
        return True

    monkeypatch.setattr(telegram_app, "_send_plan", fake_send_plan)

    sent = await telegram_app._send_one_day_plan_with_access(FakeMessage(chat_id), profile_with())

    entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
    assert sent is True
    assert send_calls == 1
    assert entitlement.monthly_one_day_remaining == 0


@pytest.mark.anyio
async def test_one_day_json_history_save_failure_after_meals_is_best_effort(monkeypatch, tmp_path) -> None:
    chat_id = 91_055
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    _install_one_day_runtime(monkeypatch, None)
    _save_active_subscription(subscriptions_path, chat_id, one_day_remaining=1, weekly_pdf_remaining=1)
    store = _FailingChatHistorySaveStore(ChatStateStorageError("history save failed"))
    plan = _one_day_plan_for_runtime_tests(
        meals=(
            Meal("Breakfast", (), "Recipe 1", recipe_id="r1", recipe_key="breakfast:key"),
            Meal("Lunch", (), "Recipe 2", recipe_id="r2", recipe_key="lunch:key"),
        )
    )
    sent_meals: list[str] = []
    sent_summaries: list[str] = []

    async def fake_send_meal_card(_message, meal) -> None:
        sent_meals.append(meal.name)

    async def fake_send_text_chunks(_message, text, _reply_markup=None) -> None:
        sent_summaries.append(text)

    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    monkeypatch.setattr(telegram_app, "build_one_day_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(telegram_app, "_send_meal_card", fake_send_meal_card)
    monkeypatch.setattr(telegram_app, "_send_text_chunks", fake_send_text_chunks)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")

    try:
        sent = await telegram_app._send_one_day_plan_with_access(FakeMessage(chat_id), profile_with())

        entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
        assert sent is True
        assert sent_meals == ["Breakfast", "Lunch"]
        assert len(sent_summaries) == 2
        assert entitlement.monthly_one_day_remaining == 0
        assert store.load_calls == 1
        assert store.save_calls == 1
        assert RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, []) == []
        assert RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, []) == []
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_one_day_history_read_failure_returns_false_and_refunds_json_attempt(monkeypatch, tmp_path) -> None:
    chat_id = 91_045
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    _install_one_day_runtime(monkeypatch, None)
    _save_active_subscription(subscriptions_path, chat_id, one_day_remaining=1, weekly_pdf_remaining=1)
    store = _install_failing_chat_state_load(monkeypatch, ChatStateStorageError("json history load failed"))

    def fail_build_one_day_plan(*_args, **_kwargs):
        raise AssertionError("one-day history read failure must not fallback to empty history")

    monkeypatch.setattr(telegram_app, "build_one_day_plan", fail_build_one_day_plan)
    message = FakeMessage(chat_id)

    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
    assert sent is False
    assert store.load_calls == 1
    assert entitlement.monthly_one_day_remaining == 1
    assert message.texts[0][0] == telegram_app.ONE_DAY_PLAN_STATUS_TEXT
    assert message.edits
    assert message.edits[-1][0] == CHAT_STATE_READ_ERROR_TEXT


@pytest.mark.anyio
async def test_postgres_one_day_history_read_failure_uses_runtime_failure_not_legacy_refund(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 91_046
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    runtime = FakeOneDayGenerationRuntime()
    _install_one_day_runtime(monkeypatch, runtime)
    store = _install_failing_chat_state_load(monkeypatch, RuntimeError("postgres history load failed"))

    def fail_build_one_day_plan(*_args, **_kwargs):
        raise AssertionError("one-day history read failure must not fallback to empty history")

    def fail_legacy_refund(*_args, **_kwargs):
        raise AssertionError("Postgres one-day read failures must use runtime finalization")

    monkeypatch.setattr(telegram_app, "build_one_day_plan", fail_build_one_day_plan)
    monkeypatch.setattr(telegram_app, "_refund_generation_attempt", fail_legacy_refund)
    message = FakeMessage(chat_id, message_id=229)

    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    assert sent is False
    assert store.load_calls == 1
    assert runtime.events == ["runtime:cleanup_stale"]
    assert message.texts[0][0] == telegram_app.ONE_DAY_PLAN_STATUS_TEXT
    assert message.edits
    assert message.edits[-1][0] == CHAT_STATE_READ_ERROR_TEXT


@pytest.mark.anyio
@pytest.mark.parametrize(
    "admit_status",
    [OneDayAdmitJobResultStatus.ACTIVE_DUPLICATE, OneDayAdmitJobResultStatus.EXISTING_IDEMPOTENCY],
)
async def test_postgres_one_day_duplicate_admission_does_not_consume_or_generate(
    monkeypatch,
    admit_status,
) -> None:
    chat_id = 91_026
    runtime = FakeOneDayGenerationRuntime(admit_status=admit_status)
    _install_one_day_runtime(monkeypatch, runtime)

    def fail_consume(*_args, **_kwargs):
        raise AssertionError("Postgres duplicate admission must not use legacy consume path")

    async def fail_send_plan(*_args, **_kwargs) -> bool:
        raise AssertionError("Postgres duplicate admission must not generate a one-day plan")

    monkeypatch.setattr(telegram_app, "_consume_generation_attempt", fail_consume)
    monkeypatch.setattr(telegram_app, "_send_plan", fail_send_plan)

    sent = await telegram_app._send_one_day_plan_with_access(
        FakeMessage(chat_id, message_id=410),
        profile_with(),
        idempotency_key="telegram_callback:duplicate:diet:one_day",
    )

    assert sent is False
    assert runtime.calls == [
        ("cleanup_stale", chat_id),
        (
            "admit_queued",
            {
                "chat_id": chat_id,
                "idempotency_key": "telegram_callback:duplicate:diet:one_day",
                "request_snapshot": runtime.calls[1][1]["request_snapshot"],
                "metadata": {"source": "telegram_one_day"},
                "test_access": False,
            },
        ),
    ]


@pytest.mark.anyio
async def test_postgres_one_day_paid_request_durable_admits_and_returns_accepted_without_generation(
    monkeypatch,
) -> None:
    chat_id = 91_057
    runtime = FakeOneDayGenerationRuntime(consumption_source="monthly")
    message = FakeMessage(chat_id, message_id=501)
    _install_one_day_runtime(monkeypatch, runtime)

    async def fake_load_history(loaded_chat_id: int) -> None:
        RECENT_RECIPE_IDS_BY_CHAT_ID[loaded_chat_id] = ["persisted-r1"]
        RECENT_RECIPE_KEYS_BY_CHAT_ID[loaded_chat_id] = ["breakfast:persisted-r1"]

    async def fail_send_plan(*_args, **_kwargs) -> bool:
        raise AssertionError("Durable one-day admission must not generate in the Telegram handler")

    def fail_legacy_consume(*_args, **_kwargs):
        raise AssertionError("Durable one-day admission must consume inside the durable store")

    monkeypatch.setattr(telegram_app, "_load_chat_history_async", fake_load_history)
    monkeypatch.setattr(telegram_app, "_send_plan", fail_send_plan)
    monkeypatch.setattr(telegram_app, "_consume_generation_attempt", fail_legacy_consume)

    try:
        sent = await telegram_app._send_one_day_plan_with_access(
            message,
            profile_with(age=39),
            idempotency_key="paid-durable-key",
        )

        assert sent is True
        assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
        admit_call = next(payload for name, payload in runtime.calls if name == "admit_queued")
        snapshot = admit_call["request_snapshot"]
        assert admit_call["idempotency_key"] == "paid-durable-key"
        assert admit_call["metadata"] == {"source": "telegram_one_day"}
        assert admit_call["test_access"] is False
        assert snapshot.request_kind == "telegram_one_day"
        assert snapshot.profile["age"] == 39
        assert snapshot.recent_recipe_ids == ("persisted-r1",)
        assert snapshot.request_payload["recent_recipe_keys"] == ["breakfast:persisted-r1"]
        assert snapshot.generation_seed
        assert "start_job_and_consume" not in [name for name, _ in runtime.calls]
        assert not _contains_one_day_normal_rejection(message)
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_postgres_one_day_duplicate_active_request_returns_already_active_without_generation(
    monkeypatch,
) -> None:
    chat_id = 91_058
    runtime = FakeOneDayGenerationRuntime(
        queued_status=QueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE,
        consumption_source="monthly",
    )
    message = FakeMessage(chat_id, message_id=502)
    _install_one_day_runtime(monkeypatch, runtime)

    async def fail_send_plan(*_args, **_kwargs) -> bool:
        raise AssertionError("Active duplicate must not generate in the Telegram handler")

    async def fake_load_history(_chat_id: int) -> None:
        return None

    monkeypatch.setattr(telegram_app, "_load_chat_history_async", fake_load_history)
    monkeypatch.setattr(telegram_app, "_send_plan", fail_send_plan)

    sent = await telegram_app._send_one_day_plan_with_access(
        message,
        profile_with(),
        idempotency_key="paid-duplicate-key",
    )

    assert sent is False
    assert message.texts == [(telegram_app.ONE_DAY_PLAN_ALREADY_RUNNING_TEXT, None)]
    assert [name for name, _ in runtime.calls] == ["cleanup_stale", "admit_queued"]
    assert not _contains_one_day_normal_rejection(message)


@pytest.mark.anyio
async def test_postgres_trial_request_durable_admits_without_calculation_generation_or_cta(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 91_059
    runtime = FakeOneDayGenerationRuntime(consumption_source="free_trial")
    message = FakeMessage(chat_id, message_id=503)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _install_one_day_runtime(monkeypatch, runtime)

    async def fail_send_calculation_report(*_args, **_kwargs) -> None:
        raise AssertionError("Durable trial admission must not send calculation in the handler")

    async def fail_send_plan(*_args, **_kwargs) -> bool:
        raise AssertionError("Durable trial admission must not generate in the handler")

    async def fake_load_history(loaded_chat_id: int) -> None:
        RECENT_RECIPE_IDS_BY_CHAT_ID[loaded_chat_id] = ["trial-r1"]
        RECENT_RECIPE_KEYS_BY_CHAT_ID[loaded_chat_id] = ["trial:key:r1"]

    monkeypatch.setattr(telegram_app, "_load_chat_history_async", fake_load_history)
    monkeypatch.setattr(telegram_app, "_send_calculation_report", fail_send_calculation_report)
    monkeypatch.setattr(telegram_app, "_send_plan", fail_send_plan)

    try:
        await telegram_app._send_trial_plan(message, profile_with(age=41), idempotency_key="trial-durable-key")

        assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
        admit_call = next(payload for name, payload in runtime.calls if name == "admit_queued")
        snapshot = admit_call["request_snapshot"]
        assert admit_call["metadata"] == {"source": "telegram_trial"}
        assert admit_call["test_access"] is False
        assert snapshot.request_kind == "telegram_trial"
        assert snapshot.profile["age"] == 41
        assert snapshot.recent_recipe_ids == ("trial-r1",)
        assert snapshot.request_payload["recent_recipe_keys"] == ["trial:key:r1"]
        assert snapshot.request_payload["include_calculation_report"] is True
        assert snapshot.request_payload["include_trial_subscription_cta"] is True
        assert _trial_cta_messages(message) == []
        assert "start_job_and_consume" not in [name for name, _ in runtime.calls]
        assert not _contains_one_day_normal_rejection(message)
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_postgres_trial_duplicate_request_returns_already_active_and_does_not_double_consume(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 91_060
    runtime = FakeOneDayGenerationRuntime(
        duplicate_on_existing_idempotency=True,
        consumption_source="free_trial",
    )
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _install_one_day_runtime(monkeypatch, runtime)

    async def fake_send_plan(*_args, **_kwargs) -> bool:
        raise AssertionError("Durable duplicate trial admission must not generate in the handler")

    monkeypatch.setattr(telegram_app, "_send_plan", fake_send_plan)

    first_message = FakeMessage(chat_id, message_id=504)
    second_message = FakeMessage(chat_id, message_id=505)
    await telegram_app._send_trial_plan(first_message, profile_with(), idempotency_key="trial-repeat-key")
    await telegram_app._send_trial_plan(second_message, profile_with(), idempotency_key="trial-repeat-key")

    assert first_message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert second_message.texts == [(telegram_app.ONE_DAY_PLAN_ALREADY_RUNNING_TEXT, None)]
    assert [name for name, _ in runtime.calls].count("admit_queued") == 2
    assert [name for name, _ in runtime.calls].count("start_job_and_consume") == 0
    assert len(runtime.admitted_snapshots) == 1
    assert _trial_cta_messages(first_message) == []
    assert _trial_cta_messages(second_message) == []


def _contains_one_day_normal_rejection(message: FakeMessage) -> bool:
    forbidden = (
        "Попробуйте позже",
        "Сервис недоступен",
        "Высокая нагрузка",
        "Очередь заполнена",
        "Не удалось поставить в очередь",
        "Слишком много запросов",
        "Рацион сейчас недоступен",
    )
    return any(any(item in text for item in forbidden) for text, _markup in message.texts)


@pytest.mark.anyio
async def test_postgres_one_day_denied_start_sends_paywall(monkeypatch) -> None:
    chat_id = 91_027
    runtime = FakeOneDayGenerationRuntime(start_status=OneDayStartJobResultStatus.DENIED)
    paywalls: list[str] = []
    _install_one_day_runtime(monkeypatch, runtime)

    async def fake_send_limit_paywall(message, ration_kind) -> None:
        paywalls.append(ration_kind)
        await message.answer(f"paywall:{ration_kind}")

    async def fail_send_plan(*_args, **_kwargs) -> bool:
        raise AssertionError("Denied Postgres start must not generate a one-day plan")

    monkeypatch.setattr(telegram_app, "_send_limit_paywall", fake_send_limit_paywall)
    monkeypatch.setattr(telegram_app, "_send_plan", fail_send_plan)

    sent = await telegram_app._send_one_day_plan_with_access(FakeMessage(chat_id, message_id=411), profile_with())

    assert sent is False
    assert paywalls == ["one_day"]
    assert [name for name, _ in runtime.calls] == ["cleanup_stale", "admit_queued"]


@pytest.mark.anyio
async def test_postgres_one_day_successful_callback_marks_value_delivery(monkeypatch) -> None:
    chat_id = 91_028
    runtime = FakeOneDayGenerationRuntime()
    message = FakeMessage(chat_id, message_id=412)
    _install_one_day_runtime(monkeypatch, runtime)
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    PROFILE_BY_CHAT_ID[chat_id] = profile_with()
    plan = _one_day_plan_for_runtime_tests()

    async def fake_send_meal_card(_message, meal) -> None:
        runtime.events.append(f"telegram:meal:{meal.recipe_id or meal.recipe_key}")

    async def fake_send_text_chunks(_message, text, _reply_markup=None) -> None:
        runtime.events.append(f"telegram:summary:{text.splitlines()[0]}")

    monkeypatch.setattr(telegram_app, "build_one_day_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(telegram_app, "_send_meal_card", fake_send_meal_card)
    monkeypatch.setattr(telegram_app, "_send_text_chunks", fake_send_text_chunks)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status-text")
    try:
        await telegram_app.handle_callback(
            FakeCallback(CALLBACK_ONE_DAY_PLAN, message, callback_id="callback-success-1"),
        )

        admit_call = next(payload for name, payload in runtime.calls if name == "admit_queued")
        assert admit_call["idempotency_key"] == f"telegram_callback:callback-success-1:{CALLBACK_ONE_DAY_PLAN}"
        assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
        assert runtime.expected_counts == []
        assert runtime.delivered_keys == []
    finally:
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_postgres_one_day_acceptance_does_not_write_history_in_handler(monkeypatch, tmp_path) -> None:
    chat_id = 91_056
    runtime = FakeOneDayGenerationRuntime()
    store = _FailingChatHistorySaveStore(ChatStateStorageError("history save failed"))
    message = FakeMessage(chat_id, message_id=413)

    _install_one_day_runtime(monkeypatch, runtime)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)

    def fail_build_one_day_plan(*_args, **_kwargs):
        raise AssertionError("Durable one-day admission must not generate in the Telegram handler")

    monkeypatch.setattr(telegram_app, "build_one_day_plan", fail_build_one_day_plan)

    try:
        sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

        assert sent is True
        assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
        assert [name for name, _ in runtime.calls] == ["cleanup_stale", "admit_queued"]
        assert runtime.delivered_keys == []
        assert store.load_calls == 1
        assert store.save_calls == 0
        assert RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, []) == []
        assert RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, []) == []
    finally:
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_postgres_one_day_text_request_uses_message_id_idempotency(monkeypatch) -> None:
    chat_id = 91_029
    runtime = FakeOneDayGenerationRuntime()
    _install_one_day_runtime(monkeypatch, runtime)
    PROFILE_BY_CHAT_ID[chat_id] = profile_with()

    async def fail_send_plan(*_args, **_kwargs) -> bool:
        raise AssertionError("Durable one-day admission must not generate in the Telegram handler")

    monkeypatch.setattr(telegram_app, "_send_plan", fail_send_plan)
    try:
        message = FakeMessage(chat_id, text=ONE_DAY_PLAN_TEXT, message_id=222)
        await handle_answer(message)

        admit_call = next(payload for name, payload in runtime.calls if name == "admit_queued")
        assert admit_call["idempotency_key"] == f"telegram_message:{chat_id}:222:one_day"
        assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    finally:
        PROFILE_BY_CHAT_ID.pop(chat_id, None)


@pytest.mark.anyio
async def test_postgres_repeat_callback_and_text_requests_use_one_day_runtime(monkeypatch) -> None:
    callback_chat_id = 91_030
    text_chat_id = 91_031
    callback_runtime = FakeOneDayGenerationRuntime()
    text_runtime = FakeOneDayGenerationRuntime()
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    PROFILE_BY_CHAT_ID[callback_chat_id] = profile_with()
    PROFILE_BY_CHAT_ID[text_chat_id] = profile_with()

    async def fail_send_plan(*_args, **_kwargs) -> bool:
        raise AssertionError("Durable repeat admission must not generate in the Telegram handler")

    monkeypatch.setattr(telegram_app, "_send_plan", fail_send_plan)
    try:
        _install_one_day_runtime(monkeypatch, callback_runtime)
        callback_message = FakeMessage(callback_chat_id, message_id=223)
        await telegram_app.handle_callback(
            FakeCallback(CALLBACK_REPEAT, callback_message, callback_id="repeat-cb-1"),
        )
        callback_admit = next(payload for name, payload in callback_runtime.calls if name == "admit_queued")

        _install_one_day_runtime(monkeypatch, text_runtime)
        text_message = FakeMessage(text_chat_id, text=telegram_app.REPEAT_PLAN_TEXT, message_id=224)
        await handle_answer(text_message)
        text_admit = next(payload for name, payload in text_runtime.calls if name == "admit_queued")

        assert callback_admit["idempotency_key"] == f"telegram_callback:repeat-cb-1:{CALLBACK_REPEAT}"
        assert text_admit["idempotency_key"] == f"telegram_message:{text_chat_id}:224:repeat"
        assert callback_message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
        assert text_message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    finally:
        PROFILE_BY_CHAT_ID.pop(callback_chat_id, None)
        PROFILE_BY_CHAT_ID.pop(text_chat_id, None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "plan",
    [
        _one_day_plan_for_runtime_tests(meals=(), can_generate=True),
        _one_day_plan_for_runtime_tests(meals=(), can_generate=False),
    ],
)
async def test_postgres_one_day_handler_accepts_without_pre_worker_generation(
    monkeypatch,
    plan,
) -> None:
    chat_id = 91_032
    runtime = FakeOneDayGenerationRuntime()
    _install_one_day_runtime(monkeypatch, runtime)

    def fail_old_refund(*_args, **_kwargs):
        raise AssertionError("Postgres one-day failures must not use legacy JSON refund path")

    def fail_build_one_day_plan(*_args, **_kwargs):
        raise AssertionError("Durable one-day admission must not generate in the Telegram handler")

    monkeypatch.setattr(telegram_app, "build_one_day_plan", fail_build_one_day_plan)
    monkeypatch.setattr(telegram_app, "_refund_generation_attempt", fail_old_refund)

    message = FakeMessage(chat_id, message_id=225)
    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    assert sent is True
    assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert "runtime:mark_send_started" not in runtime.events
    assert not any(event.startswith("runtime:finish_failure:") for event in runtime.events)


@pytest.mark.anyio
async def test_postgres_one_day_send_start_marker_failure_refunds_before_value_send(monkeypatch) -> None:
    chat_id = 91_033
    runtime = FakeOneDayGenerationRuntime(fail_mark_send_started=True)
    _install_one_day_runtime(monkeypatch, runtime)

    async def fail_send_meal_card(*_args, **_kwargs) -> None:
        raise AssertionError("Durable one-day admission must not send value messages in the Telegram handler")

    monkeypatch.setattr(telegram_app, "_send_meal_card", fail_send_meal_card)

    message = FakeMessage(chat_id, message_id=226)
    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    assert sent is True
    assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert "runtime:mark_send_started" not in runtime.events
    assert runtime.delivered_keys == []


@pytest.mark.anyio
async def test_postgres_one_day_send_failure_after_send_start_uses_runtime_no_legacy_refund(monkeypatch) -> None:
    chat_id = 91_034
    runtime = FakeOneDayGenerationRuntime()
    _install_one_day_runtime(monkeypatch, runtime)
    async def fail_send_meal_card(*_args, **_kwargs) -> None:
        raise AssertionError("Durable one-day admission must not send value messages in the Telegram handler")

    def fail_old_refund(*_args, **_kwargs):
        raise AssertionError("Postgres one-day failures must not use legacy JSON refund path")

    monkeypatch.setattr(telegram_app, "_send_meal_card", fail_send_meal_card)
    monkeypatch.setattr(telegram_app, "_refund_generation_attempt", fail_old_refund)

    message = FakeMessage(chat_id, message_id=227)
    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    assert sent is True
    assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert "runtime:mark_send_started" not in runtime.events
    assert runtime.delivered_keys == []
    assert not any(event.startswith("runtime:finish_failure:") for event in runtime.events)


@pytest.mark.anyio
async def test_postgres_one_day_partial_delivery_failure_uses_runtime_no_legacy_refund(monkeypatch) -> None:
    chat_id = 91_035
    runtime = FakeOneDayGenerationRuntime()
    _install_one_day_runtime(monkeypatch, runtime)
    async def flaky_send_meal_card(_message, _meal) -> None:
        raise AssertionError("Durable one-day admission must not send value messages in the Telegram handler")

    def fail_old_refund(*_args, **_kwargs):
        raise AssertionError("Postgres partial delivery must not use legacy JSON refund path")

    monkeypatch.setattr(telegram_app, "_send_meal_card", flaky_send_meal_card)
    monkeypatch.setattr(telegram_app, "_refund_generation_attempt", fail_old_refund)

    message = FakeMessage(chat_id, message_id=228)
    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    assert sent is True
    assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert runtime.delivered_keys == []
    assert not any(event.startswith("runtime:finish_failure:") for event in runtime.events)


@pytest.mark.anyio
async def test_send_trial_plan_keeps_legacy_path_without_one_day_job_runtime(monkeypatch, tmp_path) -> None:
    chat_id = 91_036
    subscriptions_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    _install_one_day_runtime(monkeypatch, None)
    message = FakeMessage(chat_id, message_id=229)

    async def fake_send_plan(*_args, **_kwargs) -> bool:
        return True

    async def fake_send_calculation_report(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(telegram_app, "_send_calculation_report", fake_send_calculation_report)
    monkeypatch.setattr(telegram_app, "_send_plan", fake_send_plan)

    await telegram_app._send_trial_plan(message, profile_with())

    entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
    assert entitlement.free_trial_used is True
    assert message.texts[-1][0].startswith(TRIAL_SUBSCRIPTION_TEXT)


@pytest.mark.anyio
async def test_telegram_one_day_worker_processor_sends_trial_delivery_and_cta_after_success(
    monkeypatch,
) -> None:
    chat_id = 91_037
    bot = FakeInvoiceBot()
    plan = _one_day_plan_for_runtime_tests()
    events: list[str] = []
    build_kwargs: dict[str, object] = {}

    def fake_build_one_day_plan(profile, **kwargs):
        assert profile.age == 44
        build_kwargs.update(kwargs)
        return plan

    async def fake_send_calculation_report(_message, _profile, **_kwargs) -> None:
        events.append("telegram:calculation")

    async def fake_send_meal_card(_message, meal) -> None:
        events.append(f"telegram:meal:{meal.recipe_id or meal.recipe_key}")

    async def fake_send_text_chunks(_message, text, _reply_markup=None) -> None:
        events.append(f"telegram:summary:{text.splitlines()[0]}")

    async def fake_remember_history(*_args, **_kwargs) -> None:
        events.append("history:remember")

    async def fake_format_entitlement_status(_chat_id: int) -> str:
        return "trial-status"

    monkeypatch.setattr(telegram_app, "build_one_day_plan", fake_build_one_day_plan)
    monkeypatch.setattr(telegram_app, "_send_calculation_report", fake_send_calculation_report)
    monkeypatch.setattr(telegram_app, "_send_meal_card", fake_send_meal_card)
    monkeypatch.setattr(telegram_app, "_send_text_chunks", fake_send_text_chunks)
    monkeypatch.setattr(telegram_app, "_remember_recipe_history_items_best_effort_async", fake_remember_history)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status_async", fake_format_entitlement_status)

    snapshot = OneDayGenerationRequestSnapshot(
        request_kind="telegram_trial",
        request_payload={
            "include_calculation_report": True,
            "include_default_after_plan_keyboard": False,
            "include_entitlement_status": False,
            "include_trial_subscription_cta": True,
            "recent_recipe_keys": ["breakfast:old"],
        },
        profile=telegram_app._profile_to_dict(profile_with(age=44)),
        recent_recipe_ids=("old-id",),
        generation_seed="1234",
    )
    job = OneDayGenerationJob(
        job_id=uuid4(),
        chat_id=chat_id,
        idempotency_key="telegram_trial_session:91037:trial-token:one_day",
        status="running",
        consumption_source="free_trial",
        refund_status="not_required",
        delivery_status="not_started",
        expected_value_messages=0,
        delivered_value_messages=0,
        stale_after=datetime(2026, 5, 8, tzinfo=UTC),
        request_snapshot=snapshot,
    )

    delivery = await telegram_app._TelegramOneDayGenerationJobProcessor(bot).prepare_delivery(job)
    delivered_keys = [value_message.value_message_key for value_message in delivery.value_messages]

    if delivery.before_value_messages is not None:
        await delivery.before_value_messages()
    for value_message in delivery.value_messages:
        await value_message.send()
    if delivery.after_success is not None:
        await delivery.after_success()

    assert build_kwargs["variety_seed"] == 1234
    assert build_kwargs["avoided_recipe_ids"] == {"old-id"}
    assert build_kwargs["avoided_recipe_keys"] == {"breakfast:old"}
    assert build_kwargs["recipe_source"] == "curated_only"
    assert delivered_keys == [
        "meal:00:r1",
        "meal:01:lunch:curated:r2",
        "summary:daily_totals",
        "summary:shopping",
    ]
    assert events[:3] == [
        "telegram:calculation",
        "telegram:meal:r1",
        "telegram:meal:lunch:curated:r2",
    ]
    assert events[3].startswith("telegram:summary:")
    assert events[4].startswith("telegram:summary:")
    assert events[-1] == "history:remember"
    assert bot.sent_messages[-1]["text"] == TRIAL_SUBSCRIPTION_TEXT + "\n\ntrial-status"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "plan",
    [
        _one_day_plan_for_runtime_tests(meals=(), can_generate=True),
        _one_day_plan_for_runtime_tests(meals=(), can_generate=False),
    ],
)
async def test_telegram_one_day_worker_processor_sends_no_plan_failure_follow_up(
    monkeypatch,
    plan,
) -> None:
    chat_id = 91_044
    bot = FakeInvoiceBot()

    monkeypatch.setattr(telegram_app, "build_one_day_plan", lambda *_args, **_kwargs: plan)

    snapshot = OneDayGenerationRequestSnapshot(
        request_kind="telegram_one_day",
        request_payload={
            "include_default_after_plan_keyboard": True,
            "recent_recipe_keys": ["breakfast:old"],
        },
        profile=telegram_app._profile_to_dict(profile_with(age=44)),
        recent_recipe_ids=("old-id",),
        generation_seed="1234",
    )
    job = OneDayGenerationJob(
        job_id=uuid4(),
        chat_id=chat_id,
        idempotency_key="telegram_message:91044:1:one_day",
        status="running",
        consumption_source="monthly",
        refund_status="pending",
        delivery_status="not_started",
        expected_value_messages=0,
        delivered_value_messages=0,
        stale_after=datetime(2026, 5, 8, tzinfo=UTC),
        request_snapshot=snapshot,
    )

    delivery = await telegram_app._TelegramOneDayGenerationJobProcessor(bot).prepare_delivery(job)

    assert delivery.value_messages == ()
    assert delivery.failure_follow_up is not None
    await delivery.failure_follow_up()
    assert bot.sent_messages[-1]["chat_id"] == chat_id
    assert bot.sent_messages[-1]["text"] == telegram_app.ONE_DAY_PLAN_NO_PLAN_FOLLOW_UP_TEXT
    assert bot.sent_messages[-1]["reply_markup"] is not None
    lower_text = bot.sent_messages[-1]["text"].lower()
    assert "попроб" not in lower_text
    assert "нагруз" not in lower_text
    assert "очеред" not in lower_text
    assert "недоступ" not in lower_text


@pytest.mark.anyio
async def test_postgres_trial_duplicate_idempotency_does_not_consume_or_generate_twice(monkeypatch, tmp_path) -> None:
    chat_id = 91_038
    runtime = FakeOneDayGenerationRuntime(duplicate_on_existing_idempotency=True)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _install_one_day_runtime(monkeypatch, runtime)

    async def fake_send_calculation_report(*_args, **_kwargs) -> None:
        raise AssertionError("Durable trial admission must not send calculation in the Telegram handler")

    async def fake_send_plan(
        *_args,
        on_expected_value_messages=None,
        on_value_send_start=None,
        on_value_message_delivered=None,
        **_kwargs,
    ) -> bool:
        raise AssertionError("Durable trial admission must not generate in the Telegram handler")

    monkeypatch.setattr(telegram_app, "_send_calculation_report", fake_send_calculation_report)
    monkeypatch.setattr(telegram_app, "_send_plan", fake_send_plan)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "trial-status")

    first_message = FakeMessage(chat_id, message_id=231)
    second_message = FakeMessage(chat_id, message_id=232)
    await telegram_app._send_trial_plan(first_message, profile_with(), idempotency_key="trial-key")
    await telegram_app._send_trial_plan(second_message, profile_with(), idempotency_key="trial-key")

    assert [name for name, _ in runtime.calls].count("admit_queued") == 2
    assert [name for name, _ in runtime.calls].count("start_job_and_consume") == 0
    assert len(runtime.admitted_snapshots) == 1
    assert first_message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert second_message.texts == [(telegram_app.ONE_DAY_PLAN_ALREADY_RUNNING_TEXT, None)]


@pytest.mark.anyio
async def test_postgres_trial_denied_start_sends_existing_paywall_without_cta(monkeypatch, tmp_path) -> None:
    chat_id = 91_039
    runtime = FakeOneDayGenerationRuntime(start_status=OneDayStartJobResultStatus.DENIED)
    message = FakeMessage(chat_id, message_id=233)
    paywalls: list[str] = []
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _install_one_day_runtime(monkeypatch, runtime)

    async def fake_send_limit_paywall(message, ration_kind) -> None:
        paywalls.append(ration_kind)
        await message.answer(f"paywall:{ration_kind}")

    async def fail_send_calculation_report(*_args, **_kwargs) -> None:
        raise AssertionError("Denied trial runtime start must not send calculation report")

    async def fail_send_plan(*_args, **_kwargs) -> bool:
        raise AssertionError("Denied trial runtime start must not generate a plan")

    monkeypatch.setattr(telegram_app, "_send_limit_paywall", fake_send_limit_paywall)
    monkeypatch.setattr(telegram_app, "_send_calculation_report", fail_send_calculation_report)
    monkeypatch.setattr(telegram_app, "_send_plan", fail_send_plan)

    await telegram_app._send_trial_plan(message, profile_with(), idempotency_key="denied-trial-key")

    assert paywalls == ["one_day"]
    assert [name for name, _ in runtime.calls] == ["cleanup_stale", "admit_queued"]
    assert _trial_cta_messages(message) == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "plan",
    [
        _one_day_plan_for_runtime_tests(meals=(), can_generate=True),
        _one_day_plan_for_runtime_tests(meals=(), can_generate=False),
    ],
)
async def test_postgres_trial_generation_failure_before_send_start_refunds_with_runtime(
    monkeypatch,
    tmp_path,
    plan,
) -> None:
    chat_id = 91_040
    runtime = FakeOneDayGenerationRuntime()
    message = FakeMessage(chat_id, message_id=234)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _install_one_day_runtime(monkeypatch, runtime)

    def fail_old_refund(*_args, **_kwargs):
        raise AssertionError("Postgres trial failures must not use legacy JSON refund path")

    def fail_build_one_day_plan(*_args, **_kwargs):
        raise AssertionError("Durable trial admission must not generate in the Telegram handler")

    monkeypatch.setattr(telegram_app, "build_one_day_plan", fail_build_one_day_plan)
    monkeypatch.setattr(telegram_app, "_refund_generation_attempt", fail_old_refund)

    await telegram_app._send_trial_plan(message, profile_with(), idempotency_key="pre-send-failure-trial-key")

    assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert "runtime:mark_send_started" not in runtime.events
    assert not any(event.startswith("runtime:finish_failure:") for event in runtime.events)
    assert _trial_cta_messages(message) == []


@pytest.mark.anyio
async def test_postgres_trial_send_start_marker_failure_refunds_before_value_send(monkeypatch, tmp_path) -> None:
    chat_id = 91_041
    runtime = FakeOneDayGenerationRuntime(fail_mark_send_started=True)
    message = FakeMessage(chat_id, message_id=235)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _install_one_day_runtime(monkeypatch, runtime)

    async def fail_send_meal_card(*_args, **_kwargs) -> None:
        raise AssertionError("Durable trial admission must not send value messages in the Telegram handler")

    monkeypatch.setattr(telegram_app, "_send_meal_card", fail_send_meal_card)

    await telegram_app._send_trial_plan(message, profile_with(), idempotency_key="marker-failure-trial-key")

    assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert "runtime:mark_send_started" not in runtime.events
    assert runtime.delivered_keys == []
    assert _trial_cta_messages(message) == []


@pytest.mark.anyio
async def test_postgres_trial_send_failure_after_send_start_uses_runtime_no_cta(monkeypatch, tmp_path) -> None:
    chat_id = 91_042
    runtime = FakeOneDayGenerationRuntime()
    message = FakeMessage(chat_id, message_id=236)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _install_one_day_runtime(monkeypatch, runtime)

    async def fail_send_meal_card(*_args, **_kwargs) -> None:
        raise AssertionError("Durable trial admission must not send value messages in the Telegram handler")

    def fail_old_refund(*_args, **_kwargs):
        raise AssertionError("Postgres trial failures must not use legacy JSON refund path")

    monkeypatch.setattr(telegram_app, "_send_meal_card", fail_send_meal_card)
    monkeypatch.setattr(telegram_app, "_refund_generation_attempt", fail_old_refund)

    await telegram_app._send_trial_plan(message, profile_with(), idempotency_key="post-start-failure-trial-key")

    assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert "runtime:mark_send_started" not in runtime.events
    assert runtime.delivered_keys == []
    assert not any(event.startswith("runtime:finish_failure:") for event in runtime.events)
    assert _trial_cta_messages(message) == []


@pytest.mark.anyio
async def test_postgres_trial_partial_delivery_failure_uses_runtime_no_cta(monkeypatch, tmp_path) -> None:
    chat_id = 91_043
    runtime = FakeOneDayGenerationRuntime()
    message = FakeMessage(chat_id, message_id=237)
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    _install_one_day_runtime(monkeypatch, runtime)

    async def flaky_send_meal_card(_message, _meal) -> None:
        raise AssertionError("Durable trial admission must not send value messages in the Telegram handler")

    def fail_old_refund(*_args, **_kwargs):
        raise AssertionError("Postgres trial partial delivery must not use legacy JSON refund path")

    monkeypatch.setattr(telegram_app, "_send_meal_card", flaky_send_meal_card)
    monkeypatch.setattr(telegram_app, "_refund_generation_attempt", fail_old_refund)

    await telegram_app._send_trial_plan(message, profile_with(), idempotency_key="partial-failure-trial-key")

    assert message.texts == [(telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)]
    assert runtime.delivered_keys == []
    assert not any(event.startswith("runtime:finish_failure:") for event in runtime.events)
    assert _trial_cta_messages(message) == []


@pytest.mark.anyio
async def test_trial_questionnaire_completion_uses_session_token_for_postgres_idempotency(monkeypatch, tmp_path) -> None:
    chat_id = 91_044
    runtime = FakeOneDayGenerationRuntime()
    message = FakeMessage(chat_id, message_id=238)
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app.secrets, "token_urlsafe", lambda _size: "trial-token")
    _install_one_day_runtime(monkeypatch, runtime)

    async def fake_send_calculation_report(*_args, **_kwargs) -> None:
        return None

    async def fake_send_plan(
        *_args,
        on_expected_value_messages=None,
        on_value_send_start=None,
        on_value_message_delivered=None,
        **_kwargs,
    ) -> bool:
        raise AssertionError("Durable trial admission must not generate in the Telegram handler")

    monkeypatch.setattr(telegram_app, "_send_calculation_report", fake_send_calculation_report)
    monkeypatch.setattr(telegram_app, "_send_plan", fake_send_plan)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "trial-status")
    try:
        await telegram_app._start_questionnaire(message, is_trial=True)
        while chat_id in SESSION_BY_CHAT_ID:
            session = SESSION_BY_CHAT_ID[chat_id]
            await _handle_questionnaire_answer(message, _sample_questionnaire_answer(session.current_question))

        admit_call = next(payload for name, payload in runtime.calls if name == "admit_queued")
        assert admit_call["idempotency_key"] == f"telegram_trial_session:{chat_id}:trial-token:one_day"
        assert message.texts[-1] == (telegram_app.ONE_DAY_PLAN_ACCEPTED_TEXT, None)
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        TRIAL_CHAT_IDS.discard(chat_id)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)
        getattr(telegram_app, "QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID", {}).pop(chat_id, None)


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
async def test_trial_questionnaire_completion_save_failure_preserves_trial_state_without_plan(
    monkeypatch, tmp_path
) -> None:
    chat_id = 91_046
    save_saw_cached_profile = None
    load_history_called = False
    trial_plan_called = False
    calculation_options_called = False
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    SESSION_BY_CHAT_ID[chat_id] = start_session()
    TRIAL_CHAT_IDS.add(chat_id)
    telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID[chat_id] = "trial-token"
    PLAN_COUNT_BY_CHAT_ID[chat_id] = 7
    PLAN_SEED_OFFSET_BY_CHAT_ID[chat_id] = 11
    message = FakeMessage(chat_id)

    def failing_save_chat_profile(saved_chat_id, profile) -> None:
        nonlocal save_saw_cached_profile
        assert saved_chat_id == chat_id
        save_saw_cached_profile = saved_chat_id in PROFILE_BY_CHAT_ID
        raise ChatStateStorageError("profile save failed")

    def fake_load_chat_history(_chat_id) -> None:
        nonlocal load_history_called
        load_history_called = True

    async def fake_send_trial_plan(*_args, **_kwargs) -> None:
        nonlocal trial_plan_called
        trial_plan_called = True

    async def fake_send_calculation_options(*_args, **_kwargs) -> None:
        nonlocal calculation_options_called
        calculation_options_called = True

    monkeypatch.setattr(telegram_app, "_save_chat_profile", failing_save_chat_profile)
    monkeypatch.setattr(telegram_app, "_load_chat_history", fake_load_chat_history)
    monkeypatch.setattr(telegram_app, "_send_trial_plan", fake_send_trial_plan)
    monkeypatch.setattr(telegram_app, "_send_calculation_options", fake_send_calculation_options)

    try:
        await _advance_questionnaire_to(message, "excluded_foods")
        original_session = SESSION_BY_CHAT_ID[chat_id]
        assert original_session.current_question is not None
        assert original_session.current_question.key == "excluded_foods"
        sent_before_completion = len(message.texts)
        final_answer = _sample_questionnaire_answer(original_session.current_question)
        await _handle_questionnaire_answer(message, final_answer)

        new_texts = [text for text, _ in message.texts[sent_before_completion:]]
        assert new_texts == ["Не удалось сохранить анкету. Попробуйте позже."]
        assert save_saw_cached_profile is False
        assert chat_id in TRIAL_CHAT_IDS
        assert chat_id in SESSION_BY_CHAT_ID
        stored_session = SESSION_BY_CHAT_ID[chat_id]
        assert stored_session is original_session
        assert stored_session == original_session
        assert not stored_session.is_complete
        assert stored_session.current_question is not None
        assert stored_session.current_question.key == "excluded_foods"
        assert telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID[chat_id] == "trial-token"
        assert chat_id not in PROFILE_BY_CHAT_ID
        assert PLAN_COUNT_BY_CHAT_ID[chat_id] == 7
        assert PLAN_SEED_OFFSET_BY_CHAT_ID[chat_id] == 11
        assert not load_history_called
        assert not trial_plan_called
        assert not calculation_options_called
    finally:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        TRIAL_CHAT_IDS.discard(chat_id)
        PROFILE_BY_CHAT_ID.pop(chat_id, None)
        PLAN_COUNT_BY_CHAT_ID.pop(chat_id, None)
        PLAN_SEED_OFFSET_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.pop(chat_id, None)


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
async def test_invalid_local_meal_photo_falls_back_to_text_before_telegram(tmp_path: Path) -> None:
    meal = Meal(
        name="Local Photo Meal",
        portions=(),
        recipe="Serve as text because the local photo path is invalid.",
        image_url=str(tmp_path),
    )
    message = FakeMessage()

    await _send_meal_card(message, meal)

    assert message.photos == []
    assert len(message.texts) == 1
    assert "Local Photo Meal" in message.texts[0][0]


@pytest.mark.anyio
async def test_send_text_chunks_never_sends_over_telegram_message_limit() -> None:
    message = FakeMessage()
    text = "x" * (TELEGRAM_MESSAGE_MAX_CHARS + 100)

    await telegram_app._send_text_chunks(message, text)

    assert len(message.texts) == 2
    assert all(0 < len(chunk) <= TELEGRAM_MESSAGE_MAX_CHARS for chunk, _ in message.texts)


@pytest.mark.anyio
async def test_welcome_photo_sends_local_asset() -> None:
    message = FakeMessage()

    await _send_welcome_photo(message)

    assert len(message.photos) == 1
    photo = message.photos[0]["photo"]
    assert isinstance(photo, FSInputFile)
    assert Path(photo.path) == WELCOME_PHOTO_PATH
