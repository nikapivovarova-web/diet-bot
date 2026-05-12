from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardRemove,
    SuccessfulPayment,
)

from .builder import build_one_day_plan
from .calculator import calculate_targets
from .domain import (
    ActivityLevel,
    BatchPrep,
    ConditionCode,
    CookingTimePreference,
    Food,
    FoodPortion,
    Goal,
    Meal,
    MealPlan,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
)
from .presentation import (
    format_calculation_summary,
    format_meal_card,
    format_plan_messages,
)
from .pdf_renderer import build_week_plan_pdf
from .promo_codes import PromoCodeActivation, activate_promo_code
from .questionnaire import QuestionnaireSession, start_session
from .safety import evaluate_safety
from .subscriptions import (
    MONTHLY_ONE_DAY_LIMIT,
    MONTHLY_WEEKLY_PDF_LIMIT,
    SUBSCRIPTION_PERIOD_SECONDS,
    AttemptConsumption,
    Entitlement,
    PaymentApplication,
    RationKind,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_subscription_payment,
    consume_one_day_attempt,
    consume_weekly_pdf_attempt,
    grant_test_access,
    load_entitlements,
    refund_attempt,
    revoke_test_access,
    save_entitlements,
    set_test_access_enabled,
)
from .validation import validate_plan


SESSION_BY_CHAT_ID: dict[int, QuestionnaireSession] = {}
TRIAL_CHAT_IDS: set[int] = set()
PROFILE_BY_CHAT_ID: dict[int, UserProfile] = {}
PLAN_COUNT_BY_CHAT_ID: dict[int, int] = {}
PLAN_SEED_OFFSET_BY_CHAT_ID: dict[int, int] = {}
RECENT_RECIPE_IDS_BY_CHAT_ID: dict[int, list[str]] = {}
RECENT_RECIPE_KEYS_BY_CHAT_ID: dict[int, list[str]] = {}
SUPPORT_REQUEST_CHAT_IDS: set[int] = set()
PROMO_CODE_REQUEST_CHAT_IDS: set[int] = set()
router = Router()
DEFAULT_SUPPORT_CHAT_ID = -5_271_779_108


def _parse_id_set(raw: str | None) -> set[int]:
    ids: set[int] = set()
    for item in re.split(r"[\s,;]+", raw or ""):
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            continue
    return ids


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _is_support_chat(chat_id: int) -> bool:
    return SUPPORT_CHAT_ID is not None and chat_id == SUPPORT_CHAT_ID


PRIVATE_CHAT_REQUIRED_TEXT = "Пожалуйста, откройте бота в личном чате, чтобы продолжить."
PRIVATE_CHAT_CALLBACK_TEXT = "Откройте бота в личном чате, чтобы использовать эту кнопку."


def is_private_chat(message: Message) -> bool:
    chat = getattr(message, "chat", None)
    chat_type = getattr(chat, "type", None)
    chat_type_value = getattr(chat_type, "value", chat_type)
    if chat_type_value is not None:
        return chat_type_value == "private"
    chat_id = getattr(chat, "id", None)
    return isinstance(chat_id, int) and chat_id > 0


async def ensure_private_chat(message: Message) -> bool:
    if is_private_chat(message):
        return True
    await message.answer(PRIVATE_CHAT_REQUIRED_TEXT)
    return False


def _callback_user_id(callback: CallbackQuery) -> int | None:
    user = getattr(callback, "from_user", None)
    user_id = getattr(user, "id", None)
    if isinstance(user_id, int):
        return user_id
    message = getattr(callback, "message", None)
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    if isinstance(chat_id, int) and message is not None and is_private_chat(message):
        return chat_id
    return None


async def _answer_private_chat_callback(callback: CallbackQuery) -> None:
    with suppress(TypeError):
        await callback.answer(PRIVATE_CHAT_CALLBACK_TEXT, show_alert=True)
        return
    await callback.answer(PRIVATE_CHAT_CALLBACK_TEXT)

START_PLAN_TEXT = "🥗 Составить план"
TRY_FREE_TEXT = "🥗 Попробовать бесплатно"
SUBSCRIBE_MONTH_TEXT = "💳 Подписка на месяц - 599 ₽"
SUBSCRIBE_CTA_TEXT = "💳 Оформить подписку"
SUBSCRIPTION_PRICE_RUB = 599
EXTRA_ONE_DAY_PRICE_RUB = 50
EXTRA_WEEKLY_PDF_PRICE_RUB = 250
SUBSCRIPTION_STARS_AMOUNT = 400
EXTRA_ONE_DAY_STARS_AMOUNT = 35
EXTRA_WEEKLY_PDF_STARS_AMOUNT = 170
SUBSCRIPTION_PAYMENT_TEXT = (
    "FoodBalance - цифровой сервис персональных рационов питания.\n\n"
    f"Месячный доступ - {SUBSCRIPTION_PRICE_RUB} ₽ или {SUBSCRIPTION_STARS_AMOUNT} Stars.\n\n"
    "Включено:\n"
    f"• {MONTHLY_WEEKLY_PDF_LIMIT} недельных PDF-рациона\n"
    f"• {MONTHLY_ONE_DAY_LIMIT} рационов на 1 день\n"
    "• рецепты и список покупок по анкете\n\n"
    "Сервис носит информационный характер и не является медицинской консультацией."
)
PAY_WITH_TELEGRAM_STARS_TEXT = f"⭐ Оплатить подписку - {SUBSCRIPTION_STARS_AMOUNT} Stars"
PAY_WITH_RU_CARD_TEXT = f"💳 Оплатить картой / SberPay - {SUBSCRIPTION_PRICE_RUB} ₽"
BUY_EXTRA_ONE_DAY_TEXT = f"⭐ Купить 1 дневной рацион - {EXTRA_ONE_DAY_STARS_AMOUNT} Stars"
BUY_EXTRA_WEEKLY_PDF_TEXT = f"⭐ Купить 1 недельный PDF - {EXTRA_WEEKLY_PDF_STARS_AMOUNT} Stars"
BUY_EXTRA_ONE_DAY_RU_CARD_TEXT = f"🥗 Купить 1 дневной рацион - {EXTRA_ONE_DAY_PRICE_RUB} ₽"
BUY_EXTRA_WEEKLY_PDF_RU_CARD_TEXT = f"📄 Купить недельный PDF - {EXTRA_WEEKLY_PDF_PRICE_RUB} ₽"
FEATURES_TEXT = "✨ Что умеет этот бот"
FEATURES_MESSAGE = (
    "Что умеет FoodBalance\n\n"
    "Я помогаю собрать питание под вас без лишней сложности и догадок.\n\n"
    "• сохраняю ваши данные и цели в анкете\n"
    "• рассчитываю ИМТ, калории, воду, БЖУ, витамины и минералы\n"
    "• подбираю рацион под цель, режим и предпочтения\n"
    "• показываю понятные порции и состав блюд\n"
    "• собираю PDF с меню, рецептами и списком покупок\n"
    "• учитываю ограничения, исключения и доступные функции подписки\n\n"
    "Начните с анкеты - дальше бот соберет понятный план питания."
)
PROMO_CODE_TEXT = "🎟️ Ввести промокод"
PROMO_CODE_PROMPT_TEXT = "Введите промокод одним сообщением."
PROMO_CODE_EMPTY_TEXT = "Пожалуйста, отправьте промокод текстом."
PROMO_CODE_NOT_FOUND_TEXT = "Не нашел такой промокод. Проверьте написание и отправьте код еще раз."
PROMO_CODE_ALREADY_USED_TEXT = "Этот промокод уже был активирован. Каждый промокод действует только один раз."
SUPPORT_TEXT = "🛟 Техподдержка"
SUPPORT_PROMPT_TEXT = (
    "Опишите проблему одним сообщением.\n\n"
    "Если вопрос по оплате, напишите способ оплаты: карта/SberPay или Telegram Stars, "
    "и что именно произошло."
)
SUPPORT_SENT_TEXT = "Обращение отправлено в техподдержку. Мы проверим и свяжемся с вами, если потребуется."
SUPPORT_UNAVAILABLE_TEXT = "Техподдержка временно не настроена. Попробуйте, пожалуйста, позже."
SUPPORT_TEXT_REQUIRED = "Пожалуйста, опишите проблему текстом одним сообщением."
REPEAT_PLAN_TEXT = "🔄 Составить еще один рацион"
NEW_PROFILE_TEXT = "📝 Новая анкета"
CHANGE_PROFILE_TEXT = "📝 Изменить анкету"
ONE_DAY_PLAN_TEXT = "Составить рацион на 1 день"
WEEK_PLAN_PDF_TEXT = "Составить рацион на неделю (PDF)"
WEEK_PLAN_PDF_PLACEHOLDER_TEXT = "Функция рациона на неделю в PDF пока в разработке."
SUBSCRIBER_CABINET_TEXT = "Доступ активен. Выберите действие:"
SUBSCRIBER_ONE_DAY_PLAN_TEXT = "Получить рацион на 1 день"
SUBSCRIBER_WEEK_PLAN_PDF_TEXT = "Получить рацион на неделю PDF"
WEEK_PLAN_DAYS = 7
WEEK_PLAN_CANDIDATE_COUNT = 4
WEEK_PDF_STATUS_UPDATE_SECONDS = 4.0
WEEK_PDF_STATUS_INITIAL_TEXT = (
    "Собираю недельный PDF.\n\n"
    "Это может занять до минуты. Пожалуйста, не запускайте расчет повторно."
)
WEEK_PDF_STATUS_FRAMES = (
    "Собираю недельный PDF.\n\nПодбираю блюда под вашу анкету.",
    "Собираю недельный PDF..\n\nПроверяю аллергии, ограничения и исключенные продукты.",
    "Собираю недельный PDF...\n\nСчитаю КБЖУ, витамины и минералы.",
    "Собираю недельный PDF....\n\nГотовлю рецепты, список покупок и файл.",
)
WEEK_PDF_UPLOAD_TEXT = "PDF собран. Загружаю файл в чат."
WEEK_PDF_DONE_TEXT = "Готово. PDF отправлен ниже."
WEEK_PDF_FAILURE_TEXT = "PDF не удалось подготовить или отправить. Попробуйте позже."
TELEGRAM_DOCUMENT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_BATCH_TOTAL_UNITS = 6
DEFAULT_BATCH_SERVING_UNITS = 2
DEFAULT_BATCH_SERVINGS = DEFAULT_BATCH_TOTAL_UNITS // DEFAULT_BATCH_SERVING_UNITS
MUFFIN_UNIT_FORMS = ("маффин", "маффина", "маффинов")
BAR_UNIT_FORMS = ("батончик", "батончика", "батончиков")
CRACKER_UNIT_FORMS = ("крекер", "крекера", "крекеров")
BATCH_CONTAINER_RE = re.compile(r"(?:форма|форму|ячейк|капсул|выпека)")
RECENT_RECIPE_LIMIT = 160
DATA_DIR = Path(__file__).with_name("data")
WELCOME_PHOTO_PATH = DATA_DIR / "welcome_foodbalance.png"
DEFAULT_STATE_FILE = Path(__file__).resolve().parents[2] / ".diet_bot_state" / "history.json"
STATE_FILE = Path(os.getenv("DIET_BOT_STATE_FILE", str(DEFAULT_STATE_FILE)))
DEFAULT_SUBSCRIPTIONS_STATE_FILE = DEFAULT_STATE_FILE.with_name("subscriptions.json")
SUBSCRIPTIONS_STATE_FILE = Path(os.getenv("DIET_BOT_SUBSCRIPTIONS_STATE_FILE", str(DEFAULT_SUBSCRIPTIONS_STATE_FILE)))
DEFAULT_PROMO_CODES_STATE_FILE = DEFAULT_STATE_FILE.with_name("promo_codes.json")
PROMO_CODES_STATE_FILE = Path(os.getenv("DIET_BOT_PROMO_CODES_STATE_FILE", str(DEFAULT_PROMO_CODES_STATE_FILE)))
ADMIN_USER_IDS = _parse_id_set(os.getenv("DIET_BOT_ADMIN_USER_IDS"))
TESTER_CHAT_IDS = _parse_id_set(os.getenv("DIET_BOT_TESTER_CHAT_IDS"))
TELEGRAM_PROVIDER_TOKEN = os.getenv("TELEGRAM_PROVIDER_TOKEN", "").strip()
SUPPORT_CHAT_ID = _parse_optional_int(os.getenv("DIET_BOT_SUPPORT_CHAT_ID")) or DEFAULT_SUPPORT_CHAT_ID
CALLBACK_START = "diet:start"
CALLBACK_REPEAT = "diet:repeat"
CALLBACK_NEW = "diet:new"
CALLBACK_SUBSCRIBE = "diet:subscribe_month"
CALLBACK_PAY_TELEGRAM_STARS = "diet:pay_stars"
CALLBACK_PAY_RU_CARD = "diet:pay_ru_card"
CALLBACK_PAY_RU_EXTRA_ONE_DAY = "diet:pay_ru_extra_one_day"
CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF = "diet:pay_ru_extra_weekly_pdf"
CALLBACK_BUY_EXTRA_ONE_DAY = "diet:buy_extra_one_day"
CALLBACK_BUY_EXTRA_WEEKLY_PDF = "diet:buy_extra_weekly_pdf"
CALLBACK_FEATURES = "diet:features"
CALLBACK_PROMO_CODE = "diet:promo_code"
CALLBACK_SUPPORT = "diet:support"
CALLBACK_ONE_DAY_PLAN = "diet:one_day"
CALLBACK_WEEK_PLAN_PDF = "diet:week_pdf"
CALLBACK_ANSWER_PREFIX = "diet:answer:"
PAYLOAD_SUBSCRIPTION_MONTH = "diet:stars:subscription_month"
PAYLOAD_EXTRA_ONE_DAY = "diet:stars:extra_one_day"
PAYLOAD_EXTRA_WEEKLY_PDF = "diet:stars:extra_weekly_pdf"
PAYLOAD_RU_SUBSCRIPTION_MONTH = "diet:rub:subscription_month"
PAYLOAD_RU_EXTRA_ONE_DAY = "diet:rub:extra_one_day"
PAYLOAD_RU_EXTRA_WEEKLY_PDF = "diet:rub:extra_weekly_pdf"
PAYMENT_PAYLOAD_AMOUNTS = {
    PAYLOAD_SUBSCRIPTION_MONTH: SUBSCRIPTION_STARS_AMOUNT,
    PAYLOAD_EXTRA_ONE_DAY: EXTRA_ONE_DAY_STARS_AMOUNT,
    PAYLOAD_EXTRA_WEEKLY_PDF: EXTRA_WEEKLY_PDF_STARS_AMOUNT,
}
RUB_PAYMENT_PAYLOAD_AMOUNTS = {
    PAYLOAD_RU_SUBSCRIPTION_MONTH: SUBSCRIPTION_PRICE_RUB * 100,
    PAYLOAD_RU_EXTRA_ONE_DAY: EXTRA_ONE_DAY_PRICE_RUB * 100,
    PAYLOAD_RU_EXTRA_WEEKLY_PDF: EXTRA_WEEKLY_PDF_PRICE_RUB * 100,
}
PAYMENT_PAYLOAD_TITLES = {
    PAYLOAD_SUBSCRIPTION_MONTH: "FoodBalance: подписка на месяц",
    PAYLOAD_EXTRA_ONE_DAY: "FoodBalance: 1 дневной рацион",
    PAYLOAD_EXTRA_WEEKLY_PDF: "FoodBalance: 1 недельный PDF",
}
RUB_PAYMENT_PAYLOAD_TITLES = {
    PAYLOAD_RU_SUBSCRIPTION_MONTH: "FoodBalance: подписка на месяц",
    PAYLOAD_RU_EXTRA_ONE_DAY: "FoodBalance: 1 дневной рацион",
    PAYLOAD_RU_EXTRA_WEEKLY_PDF: "FoodBalance: 1 недельный PDF",
}
PAYMENT_PAYLOAD_DESCRIPTIONS = {
    PAYLOAD_SUBSCRIPTION_MONTH: "30 дней доступа: 4 недельных PDF и 5 дневных рационов.",
    PAYLOAD_EXTRA_ONE_DAY: "Разовая дополнительная попытка для рациона на 1 день.",
    PAYLOAD_EXTRA_WEEKLY_PDF: "Разовая дополнительная попытка для недельного PDF-рациона.",
}
RUB_PAYMENT_PAYLOAD_DESCRIPTIONS = {
    PAYLOAD_RU_SUBSCRIPTION_MONTH: "30 дней доступа: 4 недельных PDF и 5 дневных рационов.",
    PAYLOAD_RU_EXTRA_ONE_DAY: "Разовая дополнительная попытка для рациона на 1 день.",
    PAYLOAD_RU_EXTRA_WEEKLY_PDF: "Разовая дополнительная попытка для недельного PDF-рациона.",
}
WELCOME_TEXT = (
    "Привет! Я FoodBalance — ваш персональный помощник по сбалансированному питанию 🥗\n\n"
    "Я подберу рецепты под ваши цели, рассчитаю КБЖУ, витамины и минералы, помогу собрать рацион так, "
    "чтобы питание было не только полезным, но и вкусным, удобным и реалистичным.\n\n"
    "Вы сможете получать блюда под свои предпочтения, режим, ограничения и нужную калорийность — "
    "без хаоса, ручных подсчётов и скучных однотипных меню.\n\n"
    "Начнём с короткой анкеты, чтобы я лучше понял, что вам подходит 👇"
)
TRIAL_SUBSCRIPTION_TEXT = (
    "Это пробный рацион на 1 день, чтобы вы могли увидеть, как работает FoodBalance.\n\n"
    "В месячную подписку входят 4 недельных рациона и 5 дополнительных дневных рационов. "
    "Если рацион на какой-то день не подойдёт, вы сможете заменить его на другой.\n\n"
    "Чтобы получать полноценные рационы, оформите доступ на месяц."
)
BOT_COMMANDS = (
    BotCommand(command="start", description="Открыть стартовое меню"),
    BotCommand(command="plan", description="Заполнить анкету для рациона"),
    BotCommand(command="cancel", description="Сбросить активную анкету"),
)


@router.message(Command("start"))
async def start(message: Message) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
    if _is_support_chat(message.chat.id):
        return
    if not await ensure_private_chat(message):
        return
    await _send_welcome_photo(message)
    if _has_active_paid_access(message.chat.id):
        await message.answer(
            _subscriber_cabinet_text(message.chat.id),
            reply_markup=_subscriber_cabinet_keyboard(message.chat.id),
        )
        return
    if _profile_for_chat(message.chat.id) is not None:
        await message.answer(
            "Анкета уже сохранена. Можно сразу составить рацион или изменить анкету.",
            reply_markup=_main_menu_keyboard(message.chat.id),
        )
        return
    await message.answer(WELCOME_TEXT, reply_markup=_start_keyboard())


@router.message(Command("plan"))
async def plan(message: Message) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
    if _is_support_chat(message.chat.id):
        return
    if not await ensure_private_chat(message):
        return
    profile = _profile_for_chat(message.chat.id)
    if profile is not None:
        await _send_calculation_options(message, profile)
        return
    await _start_questionnaire(message)


@router.message(Command("cancel"))
async def cancel(message: Message) -> None:
    SESSION_BY_CHAT_ID.pop(message.chat.id, None)
    TRIAL_CHAT_IDS.discard(message.chat.id)
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
    if _is_support_chat(message.chat.id):
        return
    if not await ensure_private_chat(message):
        return
    await message.answer("Анкета сброшена ✅", reply_markup=_main_menu_keyboard(message.chat.id))


@router.message(Command("myid"))
async def myid(message: Message) -> None:
    user_id = _message_user_id(message)
    lines = [
        "Ваши Telegram ID:",
        f"chat_id: {message.chat.id}",
    ]
    if user_id is not None:
        lines.append(f"user_id: {user_id}")
    lines.extend(
        [
            "",
            "Для тестового доступа пришлите chat_id администратору.",
        ],
    )
    await message.answer("\n".join(lines))


@router.message(Command("330366"))
async def secret_access_command(message: Message) -> None:
    action, target_chat_id = _parse_test_access_command(message.text or "")
    if target_chat_id is not None:
        if not _is_admin_message(message):
            await message.answer("Команда для выдачи доступа доступна только администратору.")
            return
        if action == "revoke":
            _revoke_test_access_for_chat(target_chat_id)
            await message.answer(f"Тестовый доступ отключен для chat_id {target_chat_id}.")
            return
        entitlement = _grant_test_access_to_chat(target_chat_id)
        test_access_end = entitlement.test_access_end_datetime()
        until_text = f" до {test_access_end:%d.%m.%Y}" if test_access_end else ""
        await message.answer(
            f"Тестовый доступ выдан для chat_id {target_chat_id}{until_text}.",
        )
        return

    if action == "enable":
        enabled, _ = _set_test_access_mode(message.chat.id, True)
        if enabled:
            await message.answer("Тестовый платный режим включен.")
        else:
            await message.answer("Тестовый доступ для вашего chat_id не выдан или уже истек.")
        return

    if action == "disable":
        disabled, _ = _set_test_access_mode(message.chat.id, False)
        if disabled:
            await message.answer("Тестовый режим выключен. Сейчас вы видите бесплатный сценарий.")
        else:
            await message.answer("Тестовый доступ для вашего chat_id не выдан или уже истек.")
        return

    if action == "help":
        await message.answer(
            "Форматы:\n"
            "/330366 123456789 - выдать тестовый доступ\n"
            "/330366 off 123456789 - забрать тестовый доступ\n"
            "/330366 on - включить платный тестовый режим\n"
            "/330366 off - выключить и посмотреть бесплатную цепочку",
        )
        return

    await message.answer(_format_test_access_command_status(message.chat.id))


@router.callback_query()
async def handle_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""
    message = callback.message
    if not isinstance(message, Message):
        await _answer_private_chat_callback(callback)
        return

    if _is_support_chat(message.chat.id):
        await callback.answer()
        return
    if not is_private_chat(message):
        await _answer_private_chat_callback(callback)
        return
    callback_user_id = _callback_user_id(callback)
    if callback_user_id is None or callback_user_id != message.chat.id:
        await _answer_private_chat_callback(callback)
        return

    if data != CALLBACK_SUPPORT:
        SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    if data != CALLBACK_PROMO_CODE:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)

    if data == CALLBACK_SUPPORT:
        await callback.answer()
        await _start_support_request(message)
        return

    if data == CALLBACK_START:
        await callback.answer()
        await _start_questionnaire(message, is_trial=True)
        return

    if data == CALLBACK_NEW:
        await callback.answer()
        await _start_questionnaire(message)
        return

    if data == CALLBACK_SUBSCRIBE:
        await callback.answer()
        await _send_subscription_payment_options(message)
        return

    if data == CALLBACK_PAY_TELEGRAM_STARS:
        await callback.answer()
        if await _send_active_subscription_notice_if_needed(message):
            return
        await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)
        return

    if data == CALLBACK_PAY_RU_CARD:
        await callback.answer()
        if await _send_active_subscription_notice_if_needed(message):
            return
        await _send_yookassa_invoice_link(message, PAYLOAD_RU_SUBSCRIPTION_MONTH)
        return

    if data == CALLBACK_PAY_RU_EXTRA_ONE_DAY:
        await callback.answer()
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_yookassa_invoice_link(message, PAYLOAD_RU_EXTRA_ONE_DAY)
        return

    if data == CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF:
        await callback.answer()
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_yookassa_invoice_link(message, PAYLOAD_RU_EXTRA_WEEKLY_PDF)
        return

    if data == CALLBACK_BUY_EXTRA_ONE_DAY:
        await callback.answer()
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_stars_invoice_link(message, PAYLOAD_EXTRA_ONE_DAY)
        return

    if data == CALLBACK_BUY_EXTRA_WEEKLY_PDF:
        await callback.answer()
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_stars_invoice_link(message, PAYLOAD_EXTRA_WEEKLY_PDF)
        return

    if data == CALLBACK_FEATURES:
        await callback.answer()
        await message.answer(FEATURES_MESSAGE, reply_markup=_main_menu_keyboard(message.chat.id))
        return

    if data == CALLBACK_PROMO_CODE:
        await callback.answer()
        await _start_promo_code_request(message)
        return

    if data == CALLBACK_REPEAT:
        await callback.answer()
        await _repeat_plan(message)
        return

    if data == CALLBACK_ONE_DAY_PLAN:
        await callback.answer()
        profile = _profile_for_chat(message.chat.id)
        if profile is None:
            await _start_questionnaire(message)
            return
        await _send_one_day_plan_with_access(message, profile)
        return

    if data == CALLBACK_WEEK_PLAN_PDF:
        await callback.answer()
        profile = _profile_for_chat(message.chat.id)
        if profile is None:
            await _start_questionnaire(message)
            return
        await _send_week_plan_with_access(message, profile)
        return

    if data.startswith(CALLBACK_ANSWER_PREFIX):
        session = SESSION_BY_CHAT_ID.get(message.chat.id)
        if session is None or session.current_question is None:
            await callback.answer("Анкета уже не активна")
            await message.answer(
                "Нажмите кнопку, чтобы составить рацион 👇",
                reply_markup=_main_menu_keyboard(message.chat.id),
            )
            return

        try:
            option_index = int(data.removeprefix(CALLBACK_ANSWER_PREFIX))
            answer = session.current_question.options[option_index]
        except (ValueError, IndexError):
            await callback.answer("Кнопка устарела")
            await message.answer(session.current_question.prompt, reply_markup=_question_keyboard(session.current_question))
            return

        await callback.answer(answer)
        await _handle_questionnaire_answer(message, answer)
        return

    await callback.answer()


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    if _is_valid_pre_checkout(pre_checkout_query):
        await pre_checkout_query.answer(ok=True)
        return
    await pre_checkout_query.answer(
        ok=False,
        error_message="Не удалось проверить платеж. Попробуйте создать счет заново.",
    )


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    if payment is None:
        return

    result = _apply_successful_payment(message.chat.id, payment)
    if result.duplicate:
        await message.answer(
            "Этот платеж уже был обработан. Текущие остатки:\n\n"
            f"{_format_entitlement_status(message.chat.id)}",
            reply_markup=_payment_result_keyboard(message.chat.id, result),
        )
        return
    if not result.processed:
        await message.answer(
            "Платеж получен, но я не смог распознать его назначение. Напишите в поддержку, чтобы мы проверили оплату.",
            reply_markup=_subscription_payment_keyboard(),
        )
        return

    status_text = (
        _subscriber_cabinet_text(message.chat.id)
        if result.grant == "subscription" or _has_active_paid_access(message.chat.id)
        else _format_entitlement_status(message.chat.id)
    )
    await message.answer(
        _payment_success_text(result) + "\n\n" + status_text,
        reply_markup=_payment_result_keyboard(message.chat.id, result),
    )


@router.message()
async def handle_answer(message: Message) -> None:
    chat_id = message.chat.id
    text = (message.text or "").strip()
    normalized_command = _normalize_command_text(text)
    if normalized_command == "myid":
        await myid(message)
        return
    if _is_support_chat(chat_id):
        SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
        PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)
        return
    if normalized_command == "330366":
        await secret_access_command(message)
        return
    if not await ensure_private_chat(message):
        return
    if text == SUPPORT_TEXT:
        await _start_support_request(message)
        return
    if chat_id in SUPPORT_REQUEST_CHAT_IDS and normalized_command is None:
        await _handle_support_request(message, text)
        return
    if text == PROMO_CODE_TEXT:
        await _start_promo_code_request(message)
        return
    if chat_id in PROMO_CODE_REQUEST_CHAT_IDS and normalized_command is None:
        await _handle_promo_code_request(message, text)
        return
    if text == TRY_FREE_TEXT:
        await _start_questionnaire(message, is_trial=True)
        return
    if text in {START_PLAN_TEXT, NEW_PROFILE_TEXT, CHANGE_PROFILE_TEXT}:
        await _start_questionnaire(message)
        return
    if text == SUBSCRIBE_MONTH_TEXT:
        await _send_subscription_payment_options(message)
        return
    if text == FEATURES_TEXT:
        await message.answer(FEATURES_MESSAGE, reply_markup=_main_menu_keyboard(chat_id))
        return
    if text == REPEAT_PLAN_TEXT:
        await _repeat_plan(message)
        return
    if text == ONE_DAY_PLAN_TEXT or text.startswith(SUBSCRIBER_ONE_DAY_PLAN_TEXT):
        profile = _profile_for_chat(chat_id)
        if profile is None:
            await _start_questionnaire(message)
            return
        await _send_one_day_plan_with_access(message, profile)
        return
    if text == WEEK_PLAN_PDF_TEXT or text.startswith(SUBSCRIBER_WEEK_PLAN_PDF_TEXT):
        profile = _profile_for_chat(chat_id)
        if profile is None:
            await _start_questionnaire(message)
            return
        await _send_week_plan_with_access(message, profile)
        return

    session = SESSION_BY_CHAT_ID.get(chat_id)
    if session is None:
        await message.answer("Нажмите кнопку, чтобы составить рацион 👇", reply_markup=_main_menu_keyboard(chat_id))
        return

    await _handle_questionnaire_answer(message, text)


async def _handle_questionnaire_answer(message: Message, text: str) -> None:
    chat_id = message.chat.id
    session = SESSION_BY_CHAT_ID.get(chat_id)
    if session is None:
        await message.answer("Нажмите кнопку, чтобы составить рацион 👇", reply_markup=_main_menu_keyboard(chat_id))
        return

    next_session, error = session.receive(text)
    if error:
        await message.answer(error)
        await message.answer(
            session.current_question.prompt,
            reply_markup=_question_keyboard(session.current_question),
        )
        return

    early_stop = next_session.should_stop_after_answer()
    if early_stop:
        SESSION_BY_CHAT_ID.pop(chat_id, None)
        TRIAL_CHAT_IDS.discard(chat_id)
        await message.answer(early_stop, reply_markup=_main_menu_keyboard(chat_id))
        return

    SESSION_BY_CHAT_ID[chat_id] = next_session
    if not next_session.is_complete:
        await message.answer(
            next_session.current_question.prompt,
            reply_markup=_question_keyboard(next_session.current_question),
        )
        return

    profile = next_session.build_profile()
    PROFILE_BY_CHAT_ID[chat_id] = profile
    _save_chat_profile(chat_id, profile)
    PLAN_COUNT_BY_CHAT_ID[chat_id] = 0
    PLAN_SEED_OFFSET_BY_CHAT_ID[chat_id] = random.SystemRandom().randrange(1, 1_000_000_000)
    _load_chat_history(chat_id)
    SESSION_BY_CHAT_ID.pop(chat_id, None)
    is_trial = chat_id in TRIAL_CHAT_IDS
    TRIAL_CHAT_IDS.discard(chat_id)
    if is_trial:
        await _send_trial_plan(message, profile)
        return
    await _send_calculation_options(message, profile)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_bot() -> None:
    token = (os.getenv("DIET_BOT_TOKEN") or "").strip() or (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN.")
    bot = Bot(token)
    await _set_bot_commands(bot)
    dispatcher = create_dispatcher()
    await dispatcher.start_polling(bot)


def main() -> None:
    asyncio.run(run_bot())


def _telegram_chunks(text: str, limit: int = 3900) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def _set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)


async def _start_support_request(message: Message) -> None:
    PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
    SUPPORT_REQUEST_CHAT_IDS.add(message.chat.id)
    await message.answer(SUPPORT_PROMPT_TEXT)


async def _start_promo_code_request(message: Message) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    SESSION_BY_CHAT_ID.pop(message.chat.id, None)
    TRIAL_CHAT_IDS.discard(message.chat.id)
    PROMO_CODE_REQUEST_CHAT_IDS.add(message.chat.id)
    await message.answer(PROMO_CODE_PROMPT_TEXT)


async def _handle_promo_code_request(message: Message, text: str) -> None:
    if not text:
        await message.answer(PROMO_CODE_EMPTY_TEXT)
        return

    activation = _activate_promo_code_for_chat(message.chat.id, text)
    if activation.activated:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
        await message.answer(
            _promo_code_success_text(message.chat.id),
            reply_markup=_subscriber_cabinet_keyboard(message.chat.id),
        )
        return
    if activation.status == "already_used":
        await message.answer(PROMO_CODE_ALREADY_USED_TEXT)
        return
    await message.answer(PROMO_CODE_NOT_FOUND_TEXT)


async def _handle_support_request(message: Message, text: str) -> None:
    if not text:
        await message.answer(SUPPORT_TEXT_REQUIRED)
        return

    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    sent = await _send_support_request_to_admin(message, text)
    if sent:
        await message.answer(SUPPORT_SENT_TEXT, reply_markup=_main_menu_keyboard(message.chat.id))
        return
    await message.answer(SUPPORT_UNAVAILABLE_TEXT, reply_markup=_main_menu_keyboard(message.chat.id))


async def _send_support_request_to_admin(message: Message, text: str) -> bool:
    if SUPPORT_CHAT_ID is None:
        return False

    try:
        await message.bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            text=_format_support_admin_message(message, text),
        )
    except (AttributeError, TelegramAPIError):
        return False
    return True


def _format_support_admin_message(message: Message, text: str) -> str:
    chat_id = message.chat.id
    entitlement = _entitlement_for_chat(chat_id)
    username = _format_support_username(message)
    user_id = _message_user_id(message)
    display_name = _format_support_display_name(message)
    profile_status = "есть" if _profile_for_chat(chat_id) is not None else "нет"
    requested_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    request_text = _truncate_support_text(text.strip())

    return "\n".join(
        [
            "🛟 Новое обращение в техподдержку",
            "",
            f"Время: {requested_at}",
            f"chat_id: {chat_id}",
            f"user_id: {user_id if user_id is not None else 'не указан'}",
            f"username: {username}",
            f"имя: {display_name}",
            f"анкета: {profile_status}",
            "",
            "Статус доступа:",
            _format_entitlement_status(chat_id),
            "",
            "Остатки в entitlement:",
            f"monthly_one_day_remaining: {entitlement.monthly_one_day_remaining}",
            f"monthly_weekly_pdf_remaining: {entitlement.monthly_weekly_pdf_remaining}",
            f"extra_one_day_remaining: {entitlement.extra_one_day_remaining}",
            f"extra_weekly_pdf_remaining: {entitlement.extra_weekly_pdf_remaining}",
            f"free_trial_used: {entitlement.free_trial_used}",
            f"subscription_period_start: {entitlement.subscription_period_start or 'нет'}",
            f"subscription_period_end: {entitlement.subscription_period_end or 'нет'}",
            f"test_access_until: {entitlement.test_access_until or 'нет'}",
            "processed_payment_charge_ids: "
            + (", ".join(entitlement.processed_payment_charge_ids[-5:]) or "нет"),
            "",
            "Текст обращения:",
            request_text,
        ],
    )


def _format_support_username(message: Message) -> str:
    user = getattr(message, "from_user", None)
    username = str(getattr(user, "username", "") or "").strip()
    return f"@{username}" if username else "не указан"


def _format_support_display_name(message: Message) -> str:
    user = getattr(message, "from_user", None)
    full_name = str(getattr(user, "full_name", "") or "").strip()
    if full_name:
        return full_name
    parts = [
        str(getattr(user, "first_name", "") or "").strip(),
        str(getattr(user, "last_name", "") or "").strip(),
    ]
    display_name = " ".join(part for part in parts if part)
    return display_name or "не указано"


def _truncate_support_text(text: str, limit: int = 2400) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 15].rstrip() + "\n...[сокращено]"


async def _start_questionnaire(message: Message, *, is_trial: bool = False) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    session = start_session()
    SESSION_BY_CHAT_ID[message.chat.id] = session
    if is_trial:
        TRIAL_CHAT_IDS.add(message.chat.id)
    else:
        TRIAL_CHAT_IDS.discard(message.chat.id)
    await message.answer(
        session.current_question.prompt,
        reply_markup=_question_keyboard(session.current_question),
    )


async def _repeat_plan(message: Message) -> None:
    profile = _profile_for_chat(message.chat.id)
    if profile is None:
        await _start_questionnaire(message)
        return
    await _send_one_day_plan_with_access(message, profile)


async def _send_calculation_options(message: Message, profile: UserProfile) -> None:
    await _send_calculation_report(message, profile, reply_markup=_ration_choice_keyboard_for_chat(message.chat.id))


async def _send_calculation_report(
    message: Message,
    profile: UserProfile,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    targets = calculate_targets(profile)
    safety = evaluate_safety(profile)
    await message.answer(
        format_calculation_summary(targets, safety),
        reply_markup=reply_markup,
    )


async def _send_trial_plan(message: Message, profile: UserProfile) -> None:
    consumption = _consume_generation_attempt(message.chat.id, "one_day")
    if not consumption.allowed:
        await _send_limit_paywall(message, "one_day")
        return

    try:
        await _send_calculation_report(message, profile)
        sent = await _send_plan(message, profile, include_default_after_plan_keyboard=False)
    except Exception:
        _refund_generation_attempt(message.chat.id, consumption)
        raise

    if not sent:
        _refund_generation_attempt(message.chat.id, consumption)
        return

    if sent:
        await message.answer(
            TRIAL_SUBSCRIPTION_TEXT + "\n\n" + _format_entitlement_status(message.chat.id),
            reply_markup=_trial_subscription_keyboard(),
        )


async def _send_one_day_plan_with_access(message: Message, profile: UserProfile) -> bool:
    consumption = _consume_generation_attempt(message.chat.id, "one_day")
    if not consumption.allowed:
        await _send_limit_paywall(message, "one_day")
        return False

    try:
        sent = await _send_plan(
            message,
            profile,
            status_text=_format_entitlement_status(message.chat.id),
        )
    except Exception:
        _refund_generation_attempt(message.chat.id, consumption)
        raise

    if not sent:
        _refund_generation_attempt(message.chat.id, consumption)
    return sent


async def _send_week_plan_with_access(message: Message, profile: UserProfile) -> bool:
    consumption = _consume_generation_attempt(message.chat.id, "weekly_pdf")
    if not consumption.allowed:
        await _send_limit_paywall(message, "weekly_pdf")
        return False

    try:
        sent = await _send_week_plan(
            message,
            profile,
            status_text=_format_entitlement_status(message.chat.id),
        )
    except Exception:
        _refund_generation_attempt(message.chat.id, consumption)
        raise

    if not sent:
        _refund_generation_attempt(message.chat.id, consumption)
    return sent


async def _send_plan(
    message: Message,
    profile: UserProfile,
    *,
    final_reply_markup: InlineKeyboardMarkup | None = None,
    include_default_after_plan_keyboard: bool = True,
    status_text: str | None = None,
) -> bool:
    chat_id = message.chat.id
    count = PLAN_COUNT_BY_CHAT_ID.get(chat_id, 0)
    seed_offset = PLAN_SEED_OFFSET_BY_CHAT_ID.setdefault(
        chat_id,
        random.SystemRandom().randrange(1, 1_000_000_000),
    )
    seed = seed_offset + count
    PLAN_COUNT_BY_CHAT_ID[chat_id] = count + 1
    await message.answer("Считаю рацион и проверяю ограничения... 🧮", reply_markup=ReplyKeyboardRemove())
    _load_chat_history(chat_id)
    recent_recipe_ids = set(RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, []))
    recent_recipe_keys = set(RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, []))
    plan_result = build_one_day_plan(
        profile,
        variety_seed=seed,
        avoided_recipe_ids=recent_recipe_ids,
        avoided_recipe_keys=recent_recipe_keys,
        recipe_source="curated_only",
    )
    plan_result = _annotate_batch_prep(plan_result)
    if not plan_result.safety.can_generate_plan:
        messages = format_plan_messages(plan_result, validate_plan(plan_result))
        await _send_text_chunks(message, messages[0], _after_plan_keyboard(message.chat.id))
        return False
    if not plan_result.meals:
        await message.answer(
            "Не смог собрать рацион только из проверенной таблицы рецептов под эти ограничения. "
            "Попробуйте новую анкету с менее жесткими исключениями.",
            reply_markup=_after_plan_keyboard(message.chat.id),
        )
        return False

    validation = validate_plan(plan_result)
    messages = list(format_plan_messages(plan_result, validation))
    if status_text and len(messages) > 2:
        messages[-1] = f"{messages[-1]}\n\n{status_text}"
    for meal in plan_result.meals:
        await _send_meal_card(message, meal)
    _remember_recipes(chat_id, plan_result)
    plan_reply_markup = final_reply_markup
    if plan_reply_markup is None and include_default_after_plan_keyboard:
        plan_reply_markup = _after_plan_keyboard(message.chat.id)
    for index, response in enumerate(messages[2:]):
        markup = plan_reply_markup if index == len(messages[2:]) - 1 else None
        await _send_text_chunks(message, response, markup)
    return True


async def _send_week_plan(
    message: Message,
    profile: UserProfile,
    *,
    status_text: str | None = None,
) -> bool:
    chat_id = message.chat.id
    count = PLAN_COUNT_BY_CHAT_ID.get(chat_id, 0)
    seed_offset = PLAN_SEED_OFFSET_BY_CHAT_ID.setdefault(
        chat_id,
        random.SystemRandom().randrange(1, 1_000_000_000),
    )
    seed = seed_offset + count
    PLAN_COUNT_BY_CHAT_ID[chat_id] = count + WEEK_PLAN_DAYS * WEEK_PLAN_CANDIDATE_COUNT
    status_message = await message.answer(
        WEEK_PDF_STATUS_INITIAL_TEXT,
        reply_markup=ReplyKeyboardRemove(),
    )
    status_task = asyncio.create_task(_animate_week_pdf_status(message, status_message))
    _load_chat_history(chat_id)
    recent_recipe_ids = set(RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, []))
    recent_recipe_keys = set(RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, []))
    try:
        plans = await asyncio.to_thread(
            _build_week_plans,
            profile,
            seed,
            recent_recipe_ids,
            recent_recipe_keys,
        )
        plan_dates = _week_plan_dates()

        first_plan = plans[0]
        if not first_plan.safety.can_generate_plan:
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, "Не могу собрать PDF по этой анкете.")
            messages = format_plan_messages(first_plan, validate_plan(first_plan))
            await _send_text_chunks(message, messages[0], _after_plan_keyboard(message.chat.id))
            return False
        if any(not plan.meals for plan in plans):
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, "Не смог собрать PDF под эти ограничения.")
            await message.answer(
                "Не смог собрать рацион на всю неделю только из проверенной таблицы рецептов под эти ограничения. "
                "Попробуйте новую анкету с менее жесткими исключениями.",
                reply_markup=_after_plan_keyboard(message.chat.id),
            )
            return False

        try:
            pdf_data, pdf_filename = await asyncio.to_thread(_build_week_pdf_payload, plans, plan_dates)
            _validate_week_pdf_payload_size(pdf_data, pdf_filename)
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, WEEK_PDF_UPLOAD_TEXT)
            await _send_week_pdf_document(
                message,
                pdf_data,
                pdf_filename,
                status_text=status_text,
            )
        except Exception:
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, WEEK_PDF_FAILURE_TEXT)
            return False

        await _edit_week_pdf_status(status_message, WEEK_PDF_DONE_TEXT)

        for plan_result in plans:
            _remember_recipes(chat_id, plan_result)
        return True
    finally:
        await _stop_week_pdf_status(status_task)


async def _send_week_pdf_document(
    message: Message,
    pdf_data: bytes,
    pdf_filename: str,
    *,
    status_text: str | None = None,
) -> None:
    caption = "Готово - ваш рацион на неделю в PDF."
    if status_text:
        caption = f"{caption}\n\n{status_text}"
    await message.answer_document(
        document=BufferedInputFile(pdf_data, filename=pdf_filename),
        caption=caption,
        reply_markup=_after_plan_keyboard(message.chat.id),
    )


def _build_week_pdf_payload(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
) -> tuple[bytes, str]:
    pdf_path = Path(build_week_plan_pdf(plans, plan_dates))
    try:
        return pdf_path.read_bytes(), pdf_path.name
    finally:
        with suppress(OSError):
            pdf_path.unlink()


def _validate_week_pdf_payload_size(pdf_data: bytes, pdf_filename: str) -> None:
    if len(pdf_data) <= TELEGRAM_DOCUMENT_MAX_BYTES:
        return
    raise ValueError(
        f"Weekly PDF {pdf_filename!r} is {len(pdf_data)} bytes; "
        f"Telegram document limit is {TELEGRAM_DOCUMENT_MAX_BYTES} bytes."
    )


async def _animate_week_pdf_status(message: Message, status_message: Message) -> None:
    frame_index = 0
    while True:
        await _send_week_pdf_chat_action(message)
        await _edit_week_pdf_status(status_message, WEEK_PDF_STATUS_FRAMES[frame_index % len(WEEK_PDF_STATUS_FRAMES)])
        frame_index += 1
        await asyncio.sleep(WEEK_PDF_STATUS_UPDATE_SECONDS)


async def _send_week_pdf_chat_action(message: Message) -> None:
    with suppress(Exception):
        await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_document")


async def _edit_week_pdf_status(status_message: Message, text: str) -> None:
    with suppress(TelegramAPIError, AttributeError):
        await status_message.edit_text(text)


async def _stop_week_pdf_status(status_task: asyncio.Task) -> None:
    if status_task.done():
        with suppress(asyncio.CancelledError, Exception):
            await status_task
        return
    status_task.cancel()
    with suppress(asyncio.CancelledError):
        await status_task


def _build_week_plans(
    profile: UserProfile,
    seed: int,
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
) -> tuple[MealPlan, ...]:
    plans: list[MealPlan] = []
    week_recipe_ids = set(avoided_recipe_ids)
    week_recipe_keys = set(avoided_recipe_keys)
    carryovers: dict[str, _BatchCarryover] = {}
    for day_index in range(WEEK_PLAN_DAYS):
        week_food_ids = _week_food_ids(plans)
        plan, carryovers = _select_week_day_plan(
            profile,
            seed + day_index * WEEK_PLAN_CANDIDATE_COUNT,
            week_recipe_ids,
            week_recipe_keys,
            week_food_ids,
            carryovers,
        )
        plans.append(plan)
        week_recipe_ids.update(meal.recipe_id for meal in plan.meals if meal.recipe_id)
        week_recipe_keys.update(meal.recipe_key for meal in plan.meals if meal.recipe_key)
    return tuple(plans)


def _select_week_day_plan(
    profile: UserProfile,
    seed: int,
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
    week_food_ids: set[str],
    carryovers: dict[str, "_BatchCarryover"],
) -> tuple[MealPlan, dict[str, "_BatchCarryover"]]:
    best_plan: MealPlan | None = None
    best_carryovers: dict[str, _BatchCarryover] | None = None
    best_score: tuple[float, int] | None = None
    for candidate_index in range(WEEK_PLAN_CANDIDATE_COUNT):
        plan = build_one_day_plan(
            profile,
            variety_seed=seed + candidate_index,
            avoided_recipe_ids=avoided_recipe_ids,
            avoided_recipe_keys=avoided_recipe_keys,
            recipe_source="curated_only",
        )
        candidate_carryovers = _copy_carryovers(carryovers)
        plan = _apply_batch_carryovers(plan, candidate_carryovers)
        score = (_ingredient_reuse_score(plan, week_food_ids), -candidate_index)
        if best_score is None or score > best_score:
            best_plan = plan
            best_carryovers = candidate_carryovers
            best_score = score

    if best_plan is None or best_carryovers is None:
        return (
            build_one_day_plan(
                profile,
                variety_seed=seed,
                avoided_recipe_ids=avoided_recipe_ids,
                avoided_recipe_keys=avoided_recipe_keys,
                recipe_source="curated_only",
            ),
            carryovers,
        )
    return best_plan, best_carryovers


def _copy_carryovers(carryovers: dict[str, "_BatchCarryover"]) -> dict[str, "_BatchCarryover"]:
    return {
        slot: _BatchCarryover(meal=carryover.meal, remaining_servings=carryover.remaining_servings)
        for slot, carryover in carryovers.items()
    }


def _week_food_ids(plans: Sequence[MealPlan]) -> set[str]:
    return {portion.food.id for plan in plans for meal in plan.meals for portion in meal.portions}


def _ingredient_reuse_score(plan: MealPlan, week_food_ids: set[str]) -> float:
    if not plan.meals:
        return -10_000.0
    plan_food_ids = {portion.food.id for meal in plan.meals for portion in meal.portions}
    if not plan_food_ids:
        return -1_000.0
    reused = plan_food_ids & week_food_ids
    new_items = plan_food_ids - week_food_ids
    shared_grams = sum(
        portion.grams
        for meal in plan.meals
        for portion in meal.portions
        if portion.food.id in week_food_ids
    )
    return len(reused) * 2.0 + shared_grams / 200.0 - len(new_items) * 4.0


@dataclass
class _BatchCarryover:
    meal: Meal
    remaining_servings: int


def _annotate_batch_prep(plan: MealPlan) -> MealPlan:
    return _apply_batch_carryovers(plan, {})


def _apply_batch_carryovers(plan: MealPlan, carryovers: dict[str, _BatchCarryover]) -> MealPlan:
    meals: list[Meal] = []
    consumed_slots: set[str] = set()
    created_slots: set[str] = set()
    for meal in plan.meals:
        slot = _meal_slot(meal)
        carryover = carryovers.get(slot)
        if carryover and slot not in consumed_slots:
            meals.append(_carryover_meal(carryover.meal))
            carryover.remaining_servings -= 1
            if carryover.remaining_servings <= 0:
                carryovers.pop(slot, None)
            consumed_slots.add(slot)
            continue

        if slot in carryovers or slot in consumed_slots or slot in created_slots:
            meals.append(meal)
            continue

        batch = _batch_prep_for(meal)
        if batch is None:
            meals.append(meal)
            continue

        batch_meal = replace(meal, batch=batch)
        meals.append(batch_meal)
        remaining_servings = batch.serving_count - 1
        if remaining_servings > 0:
            carryovers[slot] = _BatchCarryover(batch_meal, remaining_servings)
            created_slots.add(slot)

    return replace(plan, meals=tuple(meals))


def _carryover_meal(meal: Meal) -> Meal:
    if meal.batch is None:
        return meal
    return replace(meal, batch=replace(meal.batch, is_carryover=True))


def _batch_prep_for(meal: Meal) -> BatchPrep | None:
    if not _is_batch_recipe(meal):
        return None
    batch_portions = tuple(_batch_portion(portion) for portion in meal.portions)
    if not batch_portions:
        return None
    return BatchPrep(
        total_units=DEFAULT_BATCH_TOTAL_UNITS,
        serving_units=DEFAULT_BATCH_SERVING_UNITS,
        unit_forms=_batch_unit_forms(meal),
        batch_portions=batch_portions,
    )


def _is_batch_recipe(meal: Meal) -> bool:
    name = meal.name.lower()
    text = f"{meal.name} {meal.recipe}".lower()
    if "английск" in text:
        return False
    if "маффин" in text and BATCH_CONTAINER_RE.search(text):
        return True
    if ("батончик" in name or "гранола" in name) and ("против" in text or "форм" in text or "нареж" in text):
        return True
    if ("крекер" in name or "лепешк" in name or "лепёшк" in name) and (
        "против" in text or "нареж" in text or "выпека" in text
    ):
        return True
    return False


def _batch_unit_forms(meal: Meal) -> tuple[str, str, str]:
    text = f"{meal.name} {meal.recipe}".lower()
    if "батончик" in text or "гранола" in text:
        return BAR_UNIT_FORMS
    if "крекер" in text or "лепешк" in text or "лепёшк" in text:
        return CRACKER_UNIT_FORMS
    return MUFFIN_UNIT_FORMS


def _batch_portion(portion: FoodPortion) -> FoodPortion:
    grams = round(portion.grams * DEFAULT_BATCH_SERVINGS, 1)
    return portion.food.portion(_practical_batch_grams(portion.food, grams))


def _practical_batch_grams(food: Food, grams: float) -> float:
    name = food.name.lower()
    if food.id == "egg":
        return float(max(50, math.ceil(grams / 50) * 50))
    if food.id == "banana" or food.category == "fruit":
        return round(max(grams, 60), 1)
    if food.id in {"wheat_flour", "spelt_flour"} or "мука" in name:
        return round(max(grams, 30), 1)
    if food.id == "oats" or "овся" in name:
        return round(max(grams, 20), 1)
    if food.category == "dairy":
        return round(max(grams, 50), 1)
    if food.category == "fat":
        return round(max(grams, 15), 1)
    if food.category == "sweetener":
        return round(max(grams, 15), 1)
    if food.category == "nuts_seeds":
        return round(max(grams, 10), 1)
    return round(grams, 1)


def _meal_slot(meal: Meal) -> str:
    if meal.recipe_key:
        return meal.recipe_key.split(":", 1)[0]
    name = meal.name.lower()
    if "завтрак" in name:
        return "breakfast"
    if "перекус" in name:
        return "snack"
    return "main"


def _week_plan_dates(today: date | None = None) -> tuple[date, ...]:
    start_date = (today or date.today()) + timedelta(days=1)
    return tuple(start_date + timedelta(days=offset) for offset in range(WEEK_PLAN_DAYS))


def _format_week_day_header(day_index: int, plan_date: date) -> str:
    return f"📅 День {day_index} — {plan_date:%d.%m.%Y}"


def _remember_recipes(chat_id: int, plan_result) -> None:
    id_history = RECENT_RECIPE_IDS_BY_CHAT_ID.setdefault(chat_id, [])
    key_history = RECENT_RECIPE_KEYS_BY_CHAT_ID.setdefault(chat_id, [])
    id_history.extend(meal.recipe_id for meal in plan_result.meals if meal.recipe_id)
    key_history.extend(meal.recipe_key for meal in plan_result.meals if meal.recipe_key)
    if len(id_history) > RECENT_RECIPE_LIMIT:
        del id_history[:-RECENT_RECIPE_LIMIT]
    if len(key_history) > RECENT_RECIPE_LIMIT:
        del key_history[:-RECENT_RECIPE_LIMIT]
    _save_chat_history(chat_id)


def _load_chat_history(chat_id: int) -> None:
    state = _load_state()
    chat_state = state.get(str(chat_id), {})
    RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_ids", []))[-RECENT_RECIPE_LIMIT:]
    RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_keys", []))[-RECENT_RECIPE_LIMIT:]


def _save_chat_history(chat_id: int) -> None:
    state = _load_state()
    chat_state = dict(state.get(str(chat_id), {}))
    chat_state["recipe_ids"] = RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, [])[-RECENT_RECIPE_LIMIT:]
    chat_state["recipe_keys"] = RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, [])[-RECENT_RECIPE_LIMIT:]
    state[str(chat_id)] = chat_state
    _save_state(state)


def _profile_for_chat(chat_id: int) -> UserProfile | None:
    profile = PROFILE_BY_CHAT_ID.get(chat_id)
    if profile is not None:
        return profile

    state = _load_state()
    raw_profile = state.get(str(chat_id), {}).get("profile")
    if not isinstance(raw_profile, dict):
        return None

    profile = _profile_from_dict(raw_profile)
    if profile is None:
        return None
    PROFILE_BY_CHAT_ID[chat_id] = profile
    return profile


def _save_chat_profile(chat_id: int, profile: UserProfile) -> None:
    state = _load_state()
    chat_state = dict(state.get(str(chat_id), {}))
    chat_state["profile"] = _profile_to_dict(profile)
    state[str(chat_id)] = chat_state
    _save_state(state)


def _load_state() -> dict[str, dict[str, object]]:
    if not STATE_FILE.exists():
        return {}
    try:
        loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    state: dict[str, dict[str, object]] = {}
    for chat_id, value in loaded.items():
        chat_state: dict[str, object] = {
            "recipe_ids": list(value.get("recipe_ids", [])) if isinstance(value, dict) else [],
            "recipe_keys": list(value.get("recipe_keys", [])) if isinstance(value, dict) else [],
        }
        if isinstance(value, dict) and isinstance(value.get("profile"), dict):
            chat_state["profile"] = value["profile"]
        state[str(chat_id)] = chat_state
    return state


def _save_state(state: dict[str, dict[str, object]]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _profile_to_dict(profile: UserProfile) -> dict[str, object]:
    return {
        "age": profile.age,
        "sex": profile.sex.value,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "goal": profile.goal.value,
        "activity": profile.activity.value,
        "meal_count": profile.meal_count,
        "cooking_time": profile.cooking_time.value,
        "restrictions": [
            {
                "type": restriction.type.value,
                "value": restriction.value,
                "severity": restriction.severity,
            }
            for restriction in profile.restrictions
        ],
        "conditions": [condition.value for condition in profile.conditions],
        "allow_lactose_free_dairy": profile.allow_lactose_free_dairy,
        "allow_gluten_free_oats": profile.allow_gluten_free_oats,
    }


def _profile_from_dict(raw: dict[str, object]) -> UserProfile | None:
    try:
        raw_restrictions = raw.get("restrictions", [])
        if not isinstance(raw_restrictions, list):
            raw_restrictions = []
        raw_conditions = raw.get("conditions", [])
        if not isinstance(raw_conditions, list):
            raw_conditions = []
        restrictions = tuple(
            Restriction(
                RestrictionType(str(item["type"])),
                str(item["value"]),
                str(item.get("severity", "hard")),
            )
            for item in raw_restrictions
            if isinstance(item, dict)
        )
        conditions = tuple(ConditionCode(str(condition)) for condition in raw_conditions)
        return UserProfile(
            age=int(raw["age"]),
            sex=Sex(str(raw["sex"])),
            height_cm=float(raw["height_cm"]),
            weight_kg=float(raw["weight_kg"]),
            goal=Goal(str(raw["goal"])),
            activity=ActivityLevel(str(raw["activity"])),
            meal_count=int(raw.get("meal_count", 4)),
            cooking_time=CookingTimePreference(str(raw.get("cooking_time", CookingTimePreference.LONG.value))),
            restrictions=restrictions,
            conditions=conditions,
            allow_lactose_free_dairy=bool(raw.get("allow_lactose_free_dairy", True)),
            allow_gluten_free_oats=bool(raw.get("allow_gluten_free_oats", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=TRY_FREE_TEXT, callback_data=CALLBACK_START)],
            [InlineKeyboardButton(text=SUBSCRIBE_MONTH_TEXT, callback_data=CALLBACK_SUBSCRIBE)],
            [InlineKeyboardButton(text=FEATURES_TEXT, callback_data=CALLBACK_FEATURES)],
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _main_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    entitlement = _entitlement_for_chat(chat_id)
    if _has_active_paid_access(chat_id, entitlement):
        return _subscriber_cabinet_keyboard(chat_id, entitlement=entitlement)
    if _profile_for_chat(chat_id) is not None:
        return _plan_choice_keyboard()
    return _start_keyboard()


def _ration_choice_keyboard_for_chat(chat_id: int) -> InlineKeyboardMarkup:
    entitlement = _entitlement_for_chat(chat_id)
    if _has_active_paid_access(chat_id, entitlement):
        return _subscriber_cabinet_keyboard(chat_id, entitlement=entitlement)
    return _plan_choice_keyboard()


def _subscriber_cabinet_text(chat_id: int) -> str:
    return f"{SUBSCRIBER_CABINET_TEXT}\n\n{_format_entitlement_status(chat_id)}\n\n{_format_profile_report(chat_id)}"


def _format_profile_report(chat_id: int) -> str:
    profile = _profile_for_chat(chat_id)
    if profile is None:
        return "Анкета: пока нет сохраненного отчета. Заполните анкету, и здесь появятся ИМТ, калории, вода и БЖУ."
    targets = calculate_targets(profile)
    safety = evaluate_safety(profile)
    return format_calculation_summary(targets, safety)


def _subscriber_cabinet_keyboard(
    chat_id: int,
    *,
    entitlement: Entitlement | None = None,
) -> InlineKeyboardMarkup:
    entitlement = entitlement or _entitlement_for_chat(chat_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_subscriber_one_day_button_text(chat_id, entitlement),
                    callback_data=CALLBACK_ONE_DAY_PLAN,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=_subscriber_week_pdf_button_text(chat_id, entitlement),
                    callback_data=CALLBACK_WEEK_PLAN_PDF,
                ),
            ],
            [InlineKeyboardButton(text=CHANGE_PROFILE_TEXT, callback_data=CALLBACK_NEW)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _subscriber_one_day_button_text(chat_id: int, entitlement: Entitlement) -> str:
    if _has_test_access(chat_id, entitlement):
        return SUBSCRIBER_ONE_DAY_PLAN_TEXT
    extra_text = _extra_attempts_text(entitlement.extra_one_day_remaining)
    return (
        f"{SUBSCRIBER_ONE_DAY_PLAN_TEXT} - осталось "
        f"{entitlement.monthly_one_day_remaining} из {MONTHLY_ONE_DAY_LIMIT}{extra_text}"
    )


def _subscriber_week_pdf_button_text(chat_id: int, entitlement: Entitlement) -> str:
    if _has_test_access(chat_id, entitlement):
        return SUBSCRIBER_WEEK_PLAN_PDF_TEXT
    extra_text = _extra_attempts_text(entitlement.extra_weekly_pdf_remaining)
    return (
        f"{SUBSCRIBER_WEEK_PLAN_PDF_TEXT} - осталось "
        f"{entitlement.monthly_weekly_pdf_remaining} из {MONTHLY_WEEKLY_PDF_LIMIT}{extra_text}"
    )


def _extra_attempts_text(extra_remaining: int) -> str:
    return f" + {extra_remaining} доп." if extra_remaining else ""


def _payment_result_keyboard(chat_id: int, result: PaymentApplication) -> InlineKeyboardMarkup:
    if result.grant == "subscription" or _has_active_paid_access(chat_id):
        return _subscriber_cabinet_keyboard(chat_id)
    if result.grant in {"extra_one_day", "extra_weekly_pdf"}:
        return _plan_choice_keyboard()
    return _subscription_payment_keyboard()


async def _send_subscription_payment_options(message: Message) -> None:
    if await _send_active_subscription_notice_if_needed(message):
        return
    await message.answer(SUBSCRIPTION_PAYMENT_TEXT, reply_markup=_subscription_payment_keyboard())


async def _send_active_subscription_notice_if_needed(message: Message) -> bool:
    entitlement = _entitlement_for_chat(message.chat.id)
    if not entitlement.is_subscription_active():
        return False
    await message.answer(
        _active_subscription_notice_text(entitlement),
        reply_markup=_subscriber_cabinet_keyboard(message.chat.id, entitlement=entitlement),
    )
    return True


async def _send_extra_purchase_subscription_notice_if_needed(message: Message) -> bool:
    entitlement = _entitlement_for_chat(message.chat.id)
    if entitlement.is_subscription_active() and not _is_free_preview_mode(message.chat.id, entitlement):
        return False
    await message.answer(
        "Разовые покупки доступны только при активной подписке.\n\n"
        "Чтобы продолжить, оформите месячный доступ.",
        reply_markup=_subscription_payment_keyboard(),
    )
    return True


def _active_subscription_notice_text(entitlement: Entitlement) -> str:
    renewal = _format_next_renewal_line(entitlement)
    lines = ["Месячный доступ уже активен."]
    if renewal:
        lines.append(renewal)
    lines.append("Повторно купить месячный доступ можно после окончания текущего периода.")
    return "\n".join(lines)


def _ru_card_payment_unavailable_text(payload: str) -> str:
    title = RUB_PAYMENT_PAYLOAD_TITLES.get(payload, "Оплата FoodBalance")
    amount = RUB_PAYMENT_PAYLOAD_AMOUNTS.get(payload, 0)
    return (
        f"{title}\n\n"
        f"Стоимость: {_format_kopecks_for_display(amount)} ₽.\n\n"
        "Оплата картой через ЮKassa сейчас недоступна. Попробуйте позже или оплатите через Telegram Stars."
    )


async def _send_stars_invoice_link(message: Message, payload: str) -> None:
    amount = PAYMENT_PAYLOAD_AMOUNTS[payload]
    title = PAYMENT_PAYLOAD_TITLES[payload]
    description = PAYMENT_PAYLOAD_DESCRIPTIONS[payload]
    subscription_period = SUBSCRIPTION_PERIOD_SECONDS if payload == PAYLOAD_SUBSCRIPTION_MONTH else None
    invoice_link = await message.bot.create_invoice_link(
        title=title,
        description=description,
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=amount)],
        provider_token="",
        subscription_period=subscription_period,
    )
    await message.answer(
        f"{title}\n\nСтоимость: {amount} Stars.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить в Telegram", url=invoice_link)],
            ],
        ),
    )


async def _send_yookassa_invoice_link(message: Message, payload: str) -> None:
    provider_token = TELEGRAM_PROVIDER_TOKEN.strip()
    if not provider_token:
        await message.answer(_ru_card_payment_unavailable_text(payload))
        return

    amount = RUB_PAYMENT_PAYLOAD_AMOUNTS[payload]
    title = RUB_PAYMENT_PAYLOAD_TITLES[payload]
    description = RUB_PAYMENT_PAYLOAD_DESCRIPTIONS[payload]
    try:
        invoice_link = await message.bot.create_invoice_link(
            title=title,
            description=description,
            payload=payload,
            currency="RUB",
            prices=[LabeledPrice(label=title, amount=amount)],
            provider_token=provider_token,
            need_email=True,
            send_email_to_provider=True,
            provider_data=json.dumps(_yookassa_provider_data(payload), ensure_ascii=False),
        )
    except TelegramAPIError:
        await message.answer("Не удалось создать счет для оплаты. Попробуйте позже.")
        return

    await message.answer(
        f"{title}\n\nСтоимость: {_format_kopecks_for_display(amount)} ₽.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить в Telegram", url=invoice_link)],
            ],
        ),
    )


def _yookassa_provider_data(payload: str) -> dict[str, object]:
    amount = RUB_PAYMENT_PAYLOAD_AMOUNTS[payload]
    title = RUB_PAYMENT_PAYLOAD_TITLES[payload]
    return {
        "receipt": {
            "items": [
                {
                    "description": title,
                    "quantity": "1.00",
                    "amount": {
                        "value": _format_kopecks_as_rub(amount),
                        "currency": "RUB",
                    },
                    "vat_code": 1,
                    "payment_mode": "full_payment",
                    "payment_subject": "service",
                },
            ],
        },
    }


def _format_kopecks_as_rub(amount: int) -> str:
    return f"{amount / 100:.2f}"


def _format_kopecks_for_display(amount: int) -> str:
    rubles, kopecks = divmod(amount, 100)
    if kopecks == 0:
        return str(rubles)
    return f"{rubles}.{kopecks:02d}"


def _is_valid_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> bool:
    expected_amount = PAYMENT_PAYLOAD_AMOUNTS.get(pre_checkout_query.invoice_payload)
    if expected_amount is not None:
        return pre_checkout_query.currency == "XTR" and pre_checkout_query.total_amount == expected_amount

    expected_rub_amount = RUB_PAYMENT_PAYLOAD_AMOUNTS.get(pre_checkout_query.invoice_payload)
    return (
        expected_rub_amount is not None
        and pre_checkout_query.currency == "RUB"
        and pre_checkout_query.total_amount == expected_rub_amount
    )


def _apply_successful_payment(chat_id: int, payment: SuccessfulPayment) -> PaymentApplication:
    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements.get(chat_id, Entitlement())
    charge_id = payment.telegram_payment_charge_id
    payload = payment.invoice_payload

    if payload in {PAYLOAD_SUBSCRIPTION_MONTH, PAYLOAD_RU_SUBSCRIPTION_MONTH}:
        result = apply_subscription_payment(
            entitlement,
            charge_id,
            subscription_expiration_timestamp=getattr(payment, "subscription_expiration_date", None),
        )
    elif payload in {PAYLOAD_EXTRA_ONE_DAY, PAYLOAD_RU_EXTRA_ONE_DAY}:
        result = apply_extra_one_day_payment(entitlement, charge_id)
    elif payload in {PAYLOAD_EXTRA_WEEKLY_PDF, PAYLOAD_RU_EXTRA_WEEKLY_PDF}:
        result = apply_extra_weekly_pdf_payment(entitlement, charge_id)
    else:
        return PaymentApplication(False)

    entitlements[chat_id] = entitlement
    save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
    return result


def _payment_success_text(result: PaymentApplication) -> str:
    if result.grant == "subscription":
        return "Подписка активна. Лимиты на этот месяц обновлены."
    if result.grant == "extra_one_day":
        return "Готово: добавлена 1 попытка для дневного рациона."
    if result.grant == "extra_weekly_pdf":
        return "Готово: добавлена 1 попытка для недельного PDF."
    return "Платеж обработан."


def _activate_promo_code_for_chat(chat_id: int, promo_code: str) -> PromoCodeActivation:
    activation = activate_promo_code(PROMO_CODES_STATE_FILE, promo_code, chat_id)
    if not activation.activated:
        return activation

    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements.get(chat_id, Entitlement())
    apply_subscription_payment(entitlement, f"promo:{activation.code}")
    entitlements[chat_id] = entitlement
    save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
    return activation


def _promo_code_success_text(chat_id: int) -> str:
    return (
        "Поздравляем! Промокод активирован.\n\n"
        "У вас активировалась месячная подписка. Теперь вы можете сгенерировать "
        f"{MONTHLY_WEEKLY_PDF_LIMIT} недельных PDF-рациона и "
        f"{MONTHLY_ONE_DAY_LIMIT} дневных рационов.\n\n"
        f"{_format_entitlement_status(chat_id)}"
    )


def _message_user_id(message: Message) -> int | None:
    user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)
    return user_id if isinstance(user_id, int) else None


def _normalize_command_text(text: str) -> str | None:
    first_token = text.split(maxsplit=1)[0] if text else ""
    if not first_token.startswith("/"):
        return None
    command = first_token[1:].split("@", 1)[0].lower()
    return command or None


def _is_admin_message(message: Message) -> bool:
    user_id = _message_user_id(message)
    return bool(user_id is not None and user_id in ADMIN_USER_IDS)


def _parse_test_access_command(text: str) -> tuple[str, int | None]:
    args = text.split()[1:]
    if not args:
        return "status", None

    first = args[0].lower()
    if first in {"on", "enable", "вкл"}:
        target_chat_id = _parse_first_int(args[1]) if len(args) > 1 else None
        return ("grant", target_chat_id) if target_chat_id is not None else ("enable", None)
    if first in {"off", "disable", "выкл"}:
        target_chat_id = _parse_first_int(args[1]) if len(args) > 1 else None
        return ("revoke", target_chat_id) if target_chat_id is not None else ("disable", None)

    target_chat_id = _parse_first_int(first)
    if target_chat_id is not None:
        return "grant", target_chat_id
    return "help", None


def _parse_first_int(text: str) -> int | None:
    match = re.search(r"-?\d+", text)
    return int(match.group(0)) if match else None


def _grant_test_access_to_chat(
    chat_id: int,
    *,
    now: datetime | None = None,
) -> Entitlement:
    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements.get(chat_id, Entitlement())
    grant_test_access(entitlement, now=now)
    entitlements[chat_id] = entitlement
    save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
    return entitlement


def _revoke_test_access_for_chat(chat_id: int) -> Entitlement:
    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements.get(chat_id, Entitlement())
    revoke_test_access(entitlement)
    entitlements[chat_id] = entitlement
    save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
    return entitlement


def _set_test_access_mode(chat_id: int, enabled: bool) -> tuple[bool, Entitlement]:
    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements.get(chat_id, Entitlement())
    changed = set_test_access_enabled(entitlement, enabled)
    entitlements[chat_id] = entitlement
    save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
    return changed, entitlement


def _has_test_access(chat_id: int, entitlement: Entitlement | None = None) -> bool:
    return chat_id in TESTER_CHAT_IDS or bool(entitlement and entitlement.is_test_access_active())


def _is_free_preview_mode(chat_id: int, entitlement: Entitlement | None = None) -> bool:
    if chat_id in TESTER_CHAT_IDS:
        return False
    entitlement = entitlement or _entitlement_for_chat(chat_id)
    return entitlement.is_test_access_available() and not entitlement.test_access_enabled


def _has_active_paid_access(chat_id: int, entitlement: Entitlement | None = None) -> bool:
    entitlement = entitlement or _entitlement_for_chat(chat_id)
    if _is_free_preview_mode(chat_id, entitlement):
        return False
    return _has_test_access(chat_id, entitlement) or entitlement.is_subscription_active()


def _format_test_access_command_status(chat_id: int) -> str:
    if chat_id in TESTER_CHAT_IDS:
        return "Тестовый платный режим активен через настройки запуска бота."

    entitlement = _entitlement_for_chat(chat_id)
    if not entitlement.is_test_access_available():
        return "Тестовый доступ для вашего chat_id не выдан или уже истек."

    test_access_end = entitlement.test_access_end_datetime()
    until_text = f"\nДействует до: {test_access_end:%d.%m.%Y}" if test_access_end else ""
    if entitlement.test_access_enabled:
        return (
            "Тестовый платный режим включен."
            + until_text
            + "\nКоманда для бесплатного режима: /330366 off"
        )
    return (
        "Тестовый режим выключен. Сейчас вы видите бесплатный сценарий."
        + until_text
        + "\nКоманда для платного режима: /330366 on"
    )


def _format_test_access_status(entitlement: Entitlement) -> str:
    lines = [
        "Тестовый доступ активен.",
        "Лимиты для проверки не списываются.",
    ]
    test_access_end = entitlement.test_access_end_datetime()
    if test_access_end is not None:
        lines.append(f"Действует до: {test_access_end:%d.%m.%Y}")
    return "\n".join(lines)


def _consume_generation_attempt(chat_id: int, ration_kind: RationKind) -> AttemptConsumption:
    if chat_id in TESTER_CHAT_IDS:
        return AttemptConsumption(True, ration_kind, "test_access")

    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements.get(chat_id, Entitlement())
    if _is_free_preview_mode(chat_id, entitlement):
        preview_entitlement = replace(
            entitlement,
            subscription_period_start=None,
            subscription_period_end=None,
            monthly_one_day_remaining=0,
            monthly_weekly_pdf_remaining=0,
            extra_one_day_remaining=0,
            extra_weekly_pdf_remaining=0,
            test_access_enabled=False,
        )
        if ration_kind == "weekly_pdf":
            consumption = consume_weekly_pdf_attempt(preview_entitlement)
        else:
            consumption = consume_one_day_attempt(preview_entitlement)
        entitlement.free_trial_used = preview_entitlement.free_trial_used
    elif ration_kind == "weekly_pdf":
        consumption = consume_weekly_pdf_attempt(entitlement)
    else:
        consumption = consume_one_day_attempt(entitlement)
    entitlements[chat_id] = entitlement
    save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
    return consumption


def _refund_generation_attempt(chat_id: int, consumption: AttemptConsumption) -> None:
    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements.get(chat_id, Entitlement())
    refund_attempt(entitlement, consumption)
    entitlements[chat_id] = entitlement
    save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)


def _entitlement_for_chat(chat_id: int) -> Entitlement:
    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements.get(chat_id, Entitlement())
    entitlement.expire_if_needed()
    entitlements[chat_id] = entitlement
    save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
    return entitlement


def _format_entitlement_status(chat_id: int) -> str:
    entitlement = _entitlement_for_chat(chat_id)
    if _is_free_preview_mode(chat_id, entitlement):
        lines = ["Тестовый режим выключен. Сейчас вы видите бесплатный сценарий."]
        if entitlement.free_trial_used:
            lines.append("Бесплатный пробный рацион на 1 день уже использован.")
        else:
            lines.append("Доступен бесплатный пробный рацион на 1 день.")
        return "\n".join(lines)
    if _has_test_access(chat_id, entitlement):
        return _format_test_access_status(entitlement)
    lines = [
        "Осталось:",
        f"Рационы на 1 день: {entitlement.monthly_one_day_remaining} из {MONTHLY_ONE_DAY_LIMIT}",
        f"PDF на неделю: {entitlement.monthly_weekly_pdf_remaining} из {MONTHLY_WEEKLY_PDF_LIMIT}",
    ]
    if entitlement.extra_one_day_remaining or entitlement.extra_weekly_pdf_remaining:
        lines.extend(
            [
                "",
                "Дополнительно куплено:",
                f"Рационы на 1 день: {entitlement.extra_one_day_remaining}",
                f"PDF на неделю: {entitlement.extra_weekly_pdf_remaining}",
            ],
        )
    return "\n".join(lines)


def _format_next_renewal_line(entitlement: Entitlement) -> str | None:
    if not entitlement.is_subscription_active():
        return None
    period_end = entitlement.subscription_end_datetime()
    if period_end is None:
        return None
    return f"Следующее обновление подписки: {period_end:%d.%m.%Y}"


async def _send_limit_paywall(message: Message, ration_kind: str) -> None:
    entitlement = _entitlement_for_chat(message.chat.id)
    has_active_subscription = (
        entitlement.is_subscription_active()
        and not _is_free_preview_mode(message.chat.id, entitlement)
    )
    lines = [
        "Лимит для этого типа рациона закончился.",
        "",
        _format_entitlement_status(message.chat.id),
    ]
    next_renewal = (
        None
        if _is_free_preview_mode(message.chat.id, entitlement)
        else _format_next_renewal_line(entitlement)
    )
    if next_renewal:
        lines.extend(["", next_renewal])
    if has_active_subscription:
        lines.extend(
            [
                "",
                "Можно дождаться следующего обновления подписки или купить разовую попытку.",
            ],
        )
        reply_markup = _paywall_keyboard(preferred=ration_kind)
    else:
        lines.extend(
            [
                "",
                "Чтобы продолжить, оформите месячный доступ.",
            ],
        )
        reply_markup = _subscription_payment_keyboard()
    await message.answer(
        "\n".join(lines),
        reply_markup=reply_markup,
    )


def _subscription_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=PAY_WITH_RU_CARD_TEXT, callback_data=CALLBACK_PAY_RU_CARD)],
            [InlineKeyboardButton(text=PAY_WITH_TELEGRAM_STARS_TEXT, callback_data=CALLBACK_PAY_TELEGRAM_STARS)],
        ],
    )


def _paywall_keyboard(*, preferred: str) -> InlineKeyboardMarkup:
    extra_one_day_stars_button = InlineKeyboardButton(
        text=BUY_EXTRA_ONE_DAY_TEXT,
        callback_data=CALLBACK_BUY_EXTRA_ONE_DAY,
    )
    extra_one_day_card_button = InlineKeyboardButton(
        text=BUY_EXTRA_ONE_DAY_RU_CARD_TEXT,
        callback_data=CALLBACK_PAY_RU_EXTRA_ONE_DAY,
    )
    extra_weekly_pdf_stars_button = InlineKeyboardButton(
        text=BUY_EXTRA_WEEKLY_PDF_TEXT,
        callback_data=CALLBACK_BUY_EXTRA_WEEKLY_PDF,
    )
    extra_weekly_pdf_card_button = InlineKeyboardButton(
        text=BUY_EXTRA_WEEKLY_PDF_RU_CARD_TEXT,
        callback_data=CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF,
    )
    extra_buttons = (
        [
            extra_weekly_pdf_card_button,
            extra_weekly_pdf_stars_button,
            extra_one_day_card_button,
            extra_one_day_stars_button,
        ]
        if preferred == "weekly_pdf"
        else [
            extra_one_day_card_button,
            extra_one_day_stars_button,
            extra_weekly_pdf_card_button,
            extra_weekly_pdf_stars_button,
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [extra_buttons[0]],
            [extra_buttons[1]],
            [extra_buttons[2]],
            [extra_buttons[3]],
        ],
    )


def _trial_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=SUBSCRIBE_CTA_TEXT, callback_data=CALLBACK_SUBSCRIBE)],
        ],
    )


def _after_plan_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    if chat_id is not None:
        entitlement = _entitlement_for_chat(chat_id)
        if _has_active_paid_access(chat_id, entitlement):
            return _subscriber_cabinet_keyboard(chat_id, entitlement=entitlement)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=REPEAT_PLAN_TEXT, callback_data=CALLBACK_REPEAT)],
            [InlineKeyboardButton(text=NEW_PROFILE_TEXT, callback_data=CALLBACK_NEW)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _plan_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ONE_DAY_PLAN_TEXT, callback_data=CALLBACK_ONE_DAY_PLAN)],
            [InlineKeyboardButton(text=WEEK_PLAN_PDF_TEXT, callback_data=CALLBACK_WEEK_PLAN_PDF)],
            [InlineKeyboardButton(text=CHANGE_PROFILE_TEXT, callback_data=CALLBACK_NEW)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _question_keyboard(question) -> InlineKeyboardMarkup | None:
    if not question or not question.options:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=option, callback_data=f"{CALLBACK_ANSWER_PREFIX}{index}")]
            for index, option in enumerate(question.options)
        ],
    )


async def _send_welcome_photo(message: Message) -> None:
    if not WELCOME_PHOTO_PATH.exists():
        return
    try:
        await message.answer_photo(photo=FSInputFile(WELCOME_PHOTO_PATH))
    except TelegramAPIError:
        return


async def _send_meal_card(message: Message, meal: Meal) -> None:
    text = format_meal_card(meal, include_photo_credit=bool(meal.image_attribution))
    photo = _photo_input(meal)
    if photo is None:
        await _send_text_chunks(message, text)
        return

    try:
        if len(text) <= 1024:
            await message.answer_photo(photo=photo, caption=text)
            return
        await message.answer_photo(photo=photo)
    except TelegramAPIError:
        await _send_text_chunks(message, text)
        return

    await _send_text_chunks(message, text)


def _photo_input(meal: Meal) -> str | FSInputFile | None:
    if not meal.image_url:
        return None
    if meal.image_url.startswith(("http://", "https://")):
        return meal.image_url

    path = Path(meal.image_url)
    if not path.is_absolute():
        data_path = DATA_DIR / path
        project_path = Path(__file__).resolve().parents[2] / path
        path = data_path if data_path.exists() else project_path

    if not path.exists():
        return None
    return FSInputFile(path)


async def _send_text_chunks(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardRemove | None = None,
) -> None:
    chunks = _telegram_chunks(text)
    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        await message.answer(chunk, reply_markup=markup)


if __name__ == "__main__":
    main()
