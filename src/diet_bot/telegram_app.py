from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import re
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
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
    normalize_cooking_time_preference,
)
from .presentation import (
    format_calculation_summary,
    format_meal_card,
    format_plan_messages,
)
from .pdf_renderer import build_week_plan_pdf
from .json_storage import (
    atomic_write_json,
    json_storage_transaction,
    load_recent_recipe_history_from_json,
    record_recipe_history_in_json,
)
from .payments import (
    PaymentOrder,
    PaymentOrderCreationCode,
    PaymentEventType,
    PaymentPreCheckoutCode,
    PaymentPreCheckoutValidation,
    PaymentProduct,
    PaymentProvider,
    PaymentReconciliationAction,
    PaymentReconciliationInput,
    PaymentReconciliationResult,
    PaymentReversalInput,
    PaymentReversalResult,
    PaymentSuccessfulPaymentInput,
    REDACTED_PAYMENT_VALUE,
    build_payment_invoice_metadata,
    get_payment_product_invoice_metadata,
    redact_admin_actor_metadata,
    redact_payment_payload,
    validate_payment_pre_checkout,
)
from .postgres_store import PostgresDietBotStore
from .promo_codes import (
    PromoCodeActivation,
    PromoCodeDefinition,
    PromoCodeKind,
    PromoCodeRecord,
    activate_promo_code,
    generate_promo_codes,
    load_promo_codes,
    normalize_promo_code,
    promo_code_grant_charge_id,
    save_promo_codes,
)
from .questionnaire import QuestionnaireSession, start_session
from .runtime_config import RuntimeConfig, is_production_environment, load_runtime_config
from .safety import evaluate_safety
from .storage import DietBotStore, RecipeHistoryItem, SupportState
from .subscriptions import (
    MONTHLY_ONE_DAY_LIMIT,
    MONTHLY_WEEKLY_PDF_LIMIT,
    SUBSCRIPTION_PERIOD_SECONDS,
    AttemptConsumption,
    Entitlement,
    PaymentApplication,
    RationKind,
    apply_monthly_access_promo_grant,
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
DISCOUNT_PROMO_CODE_BY_CHAT_ID: dict[int, str] = {}
ADMIN_PROMO_ACTION_BY_CHAT_ID: dict[int, str] = {}
router = Router()
DEFAULT_SUPPORT_CHAT_ID = -5_271_779_108
_RUNTIME_STORE: DietBotStore | None = None
ADMIN_ACCESS_PROMO_CODE_RETRY_LIMIT = 20
ADMIN_PROMO_ACTION_CREATE_DISCOUNT = "create_discount"
ADMIN_PROMO_ACTION_DISABLE_DISCOUNT = "disable_discount"
RECENT_RECIPE_HISTORY_DAYS = 28
RECENT_RECIPE_HISTORY_LIMIT = 140
RECENT_RECIPE_REDUCED_DAYS = 14
RECENT_RECIPE_REDUCED_LIMIT = 70
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RecentRecipeAvoidance:
    full_recipe_ids: frozenset[str]
    full_recipe_keys: frozenset[str]
    reduced_recipe_ids: frozenset[str]
    reduced_recipe_keys: frozenset[str]


@dataclass(frozen=True)
class _WeekPlanBuildResult:
    plans: tuple[MealPlan, ...]
    avoidance_phase: str


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
    "• рецепты и список продуктов по анкете\n\n"
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
PROMO_CODE_DISABLED_TEXT = "Этот промокод сейчас не активен. Если вы получили его от поддержки, напишите нам."
PROMO_CODE_EXPIRED_TEXT = "Срок действия этого промокода закончился."
PROMO_CODE_NOT_ACCESS_TEXT = "Этот промокод не активирует месячный доступ. Сейчас здесь можно применить только промокод на доступ."
PROMO_CODE_DISCOUNT_APPLIED_TEXT = "Промокод на скидку применен. Выберите способ оплаты, и я пересчитаю счет."
SUPPORT_TEXT = "🛟 Техподдержка"
SUPPORT_PROMPT_TEXT = (
    "Опишите проблему одним сообщением.\n\n"
    "Если вопрос по оплате, напишите способ оплаты: карта/SberPay или Telegram Stars, "
    "и что именно произошло."
)
PUBLIC_PAYMENTS_PILOT_TEXT = (
    "Доступ по промокоду на этапе пилота.\n\n"
    "Публичная оплата картой, SberPay и Telegram Stars пока выключена. "
    "Введите промокод или обратитесь к администратору, если доступ уже согласован."
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
    "Собираю недельный PDF....\n\nГотовлю рецепты, список продуктов и файл.",
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
PUBLIC_PAYMENTS_ENABLED = os.getenv("DIET_BOT_PUBLIC_PAYMENTS_ENABLED", "").strip() == "1"
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
CALLBACK_ADMIN_CREATE_MONTHLY_ACCESS_CODE = "diet:admin:create_monthly_access_code"
CALLBACK_ADMIN_CREATE_DISCOUNT_PROMO = "diet:admin:create_discount_promo"
CALLBACK_ADMIN_LIST_DISCOUNT_PROMOS = "diet:admin:list_discount_promos"
CALLBACK_ADMIN_DISABLE_DISCOUNT_PROMO = "diet:admin:disable_discount_promo"
ADMIN_PROMO_CALLBACKS = frozenset(
    {
        CALLBACK_ADMIN_CREATE_MONTHLY_ACCESS_CODE,
        CALLBACK_ADMIN_CREATE_DISCOUNT_PROMO,
        CALLBACK_ADMIN_LIST_DISCOUNT_PROMOS,
        CALLBACK_ADMIN_DISABLE_DISCOUNT_PROMO,
    }
)
CALLBACK_ONE_DAY_PLAN = "diet:one_day"
CALLBACK_WEEK_PLAN_PDF = "diet:week_pdf"
CALLBACK_ANSWER_PREFIX = "diet:answer:"
ADMIN_CREATE_MONTHLY_ACCESS_CODE_TEXT = "🎟 Создать код на месяц"
ADMIN_CREATE_DISCOUNT_PROMO_TEXT = "🏷 Создать/обновить скидку"
ADMIN_LIST_DISCOUNT_PROMOS_TEXT = "📋 Список скидок"
ADMIN_DISABLE_DISCOUNT_PROMO_TEXT = "🚫 Отключить скидку"
ADMIN_PROMO_PANEL_TEXT = "Админ-панель\n\nВыберите действие:"
ADMIN_DISCOUNT_PROMO_INPUT_TEXT = (
    "Отправьте discount promo в формате:\n"
    "CODE PERCENT\n\n"
    "Пример: ANNA20 20"
)
ADMIN_DISABLE_DISCOUNT_PROMO_INPUT_TEXT = "Отправьте CODE скидки, которую нужно отключить."
ADMIN_PROMO_STORAGE_UNAVAILABLE_TEXT = (
    "Discount promo storage не настроен. Скидки можно управлять только при включенном payment storage."
)
SELECTED_ANSWER_PREFIX = "✅ "
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
PAYMENT_PRE_CHECKOUT_FAILED_TEXT = "Payment could not be verified. Please create a new invoice."
PAYMENT_SUCCESSFUL_PAYMENT_REJECTED_TEXT = "\u041f\u043b\u0430\u0442\u0435\u0436 \u043f\u043e\u043b\u0443\u0447\u0435\u043d, \u043d\u043e \u044f \u043d\u0435 \u0441\u043c\u043e\u0433 \u0440\u0430\u0441\u043f\u043e\u0437\u043d\u0430\u0442\u044c \u0435\u0433\u043e \u043d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435. \u041d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0432 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443, \u0447\u0442\u043e\u0431\u044b \u043c\u044b \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u043b\u0438 \u043e\u043f\u043b\u0430\u0442\u0443."
PAYMENT_PAYLOAD_PRODUCTS = {
    PAYLOAD_SUBSCRIPTION_MONTH: PaymentProduct.SUBSCRIPTION_MONTH,
    PAYLOAD_RU_SUBSCRIPTION_MONTH: PaymentProduct.SUBSCRIPTION_MONTH,
    PAYLOAD_EXTRA_ONE_DAY: PaymentProduct.EXTRA_ONE_DAY,
    PAYLOAD_RU_EXTRA_ONE_DAY: PaymentProduct.EXTRA_ONE_DAY,
    PAYLOAD_EXTRA_WEEKLY_PDF: PaymentProduct.EXTRA_WEEKLY_PDF,
    PAYLOAD_RU_EXTRA_WEEKLY_PDF: PaymentProduct.EXTRA_WEEKLY_PDF,
}
PAYMENT_PAYLOAD_PROVIDERS = {
    PAYLOAD_SUBSCRIPTION_MONTH: PaymentProvider.TELEGRAM_STARS,
    PAYLOAD_EXTRA_ONE_DAY: PaymentProvider.TELEGRAM_STARS,
    PAYLOAD_EXTRA_WEEKLY_PDF: PaymentProvider.TELEGRAM_STARS,
    PAYLOAD_RU_SUBSCRIPTION_MONTH: PaymentProvider.YOOKASSA,
    PAYLOAD_RU_EXTRA_ONE_DAY: PaymentProvider.YOOKASSA,
    PAYLOAD_RU_EXTRA_WEEKLY_PDF: PaymentProvider.YOOKASSA,
}
PAYMENT_INVOICE_CREATION_FAILED_TEXT = "Не удалось создать счет для оплаты. Попробуйте позже."
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
    BotCommand(command="plan", description="Показать мой расчет"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
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
    profile = _profile_for_chat(message.chat.id)
    if profile is not None:
        await message.answer(
            "Анкета уже сохранена. Ниже ваш актуальный расчет.\n"
            f"Чтобы изменить данные, нажмите «{CHANGE_PROFILE_TEXT}» в меню.\n\n"
            f"{_format_profile_report(message.chat.id)}",
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
    if _profile_for_chat(message.chat.id) is not None:
        cancel_text = (
            f"Текущее действие отменено ✅\n\n"
            f"Сохраненная анкета осталась без изменений. "
            f"Чтобы изменить ее, нажмите «{CHANGE_PROFILE_TEXT}» в меню."
        )
    else:
        cancel_text = "Текущее действие отменено ✅\n\nЧтобы пройти анкету, выберите нужный пункт в меню."
    await message.answer(cancel_text, reply_markup=_main_menu_keyboard(message.chat.id))


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
    if _is_admin_access_code_command_text(message.text or ""):
        await _admin_access_code_command(message)
        return

    if _is_admin_panel_command_text(message.text or "") and _is_admin_message(message):
        await _send_admin_promo_panel(message)
        return

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


@router.message(Command("payment_event"))
async def payment_event_reconciliation_command(message: Message) -> None:
    if not _is_admin_message(message):
        await message.answer("payment_event command is available only to admins.")
        return

    command = _parse_payment_event_admin_command(message.text or "")
    if command is None:
        await message.answer(_payment_event_admin_usage_text())
        return

    store = _runtime_store()
    if store is None:
        await message.answer("no_op: payment ledger store is not configured")
        return

    if command.mode == "reversal":
        result = _apply_admin_payment_reversal(store, command, message)
        await message.answer(_format_admin_payment_reversal_result(command, result))
        return

    result = _apply_admin_payment_reconciliation(store, command, message)
    await message.answer(_format_admin_payment_reconciliation_result(command, result))


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
    if data not in ADMIN_PROMO_CALLBACKS:
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)

    if data == CALLBACK_ADMIN_CREATE_MONTHLY_ACCESS_CODE:
        if not _is_admin_callback(callback):
            await callback.answer("Command is available only to admins.")
            return
        await callback.answer()
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
        await _send_admin_monthly_access_code(message)
        return

    if data == CALLBACK_ADMIN_CREATE_DISCOUNT_PROMO:
        if not _is_admin_callback(callback):
            await callback.answer("Command is available only to admins.")
            return
        await callback.answer()
        await _start_admin_discount_promo_create(message)
        return

    if data == CALLBACK_ADMIN_LIST_DISCOUNT_PROMOS:
        if not _is_admin_callback(callback):
            await callback.answer("Command is available only to admins.")
            return
        await callback.answer()
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
        await _send_admin_discount_promo_list(message)
        return

    if data == CALLBACK_ADMIN_DISABLE_DISCOUNT_PROMO:
        if not _is_admin_callback(callback):
            await callback.answer("Command is available only to admins.")
            return
        await callback.answer()
        await _start_admin_discount_promo_disable(message)
        return

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
        await _mark_questionnaire_answer_selected(message, session.current_question, option_index)
        await _handle_questionnaire_answer(message, answer)
        return

    await callback.answer()


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    validation = _payment_pre_checkout_validation(pre_checkout_query)
    if validation.approved:
        await pre_checkout_query.answer(ok=True)
        return
    await pre_checkout_query.answer(
        ok=False,
        error_message=PAYMENT_PRE_CHECKOUT_FAILED_TEXT,
    )


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    if payment is None:
        return

    result = _apply_successful_payment(message, payment)
    if result.duplicate:
        await message.answer(
            "Этот платеж уже был обработан. Текущие остатки:\n\n"
            f"{_format_entitlement_status(message.chat.id)}",
            reply_markup=_payment_result_keyboard(message.chat.id, result),
        )
        return
    if not result.processed:
        await message.answer(
            PAYMENT_SUCCESSFUL_PAYMENT_REJECTED_TEXT,
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
    if normalized_command == "payment_event":
        await payment_event_reconciliation_command(message)
        return
    if not await ensure_private_chat(message):
        return
    if chat_id in ADMIN_PROMO_ACTION_BY_CHAT_ID and normalized_command is None:
        if not _is_admin_message(message):
            ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(chat_id, None)
            await message.answer("Command is available only to admins.")
            return
        await _handle_admin_promo_action_input(message, text)
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
    await _send_calculation_options(
        message,
        profile,
        intro_text="Анкета сохранена ✅",
        footer_text=f"Чтобы изменить данные, нажмите «{CHANGE_PROFILE_TEXT}» в меню.",
    )


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


def _storage_backend_mode(config: RuntimeConfig) -> str:
    if config.database_url:
        return "postgres"
    if config.local_json_storage_allowed and not is_production_environment(config.environment):
        return "json"
    if is_production_environment(config.environment):
        raise RuntimeError("Set DIET_BOT_DATABASE_URL for production durable storage.")
    raise RuntimeError("Set DIET_BOT_DATABASE_URL or DIET_BOT_ALLOW_JSON_STORAGE=1 for local JSON storage.")


def _build_store_from_runtime_config(config: RuntimeConfig) -> DietBotStore | None:
    mode = _storage_backend_mode(config)
    if mode == "json":
        return None
    return PostgresDietBotStore(
        config.database_url,
        statement_timeout_ms=config.postgres_statement_timeout_ms,
        lock_timeout_ms=config.postgres_lock_timeout_ms,
    )


def _initialize_runtime_store(config: RuntimeConfig) -> DietBotStore | None:
    global _RUNTIME_STORE

    _RUNTIME_STORE = None
    store = _build_store_from_runtime_config(config)
    if store is not None:
        store.initialize()
    _RUNTIME_STORE = store
    return store


def _apply_runtime_config(config: RuntimeConfig) -> None:
    global ADMIN_USER_IDS
    global PROMO_CODES_STATE_FILE
    global PUBLIC_PAYMENTS_ENABLED
    global STATE_FILE
    global SUBSCRIPTIONS_STATE_FILE
    global SUPPORT_CHAT_ID
    global TELEGRAM_PROVIDER_TOKEN
    global TESTER_CHAT_IDS

    STATE_FILE = config.state_file
    SUBSCRIPTIONS_STATE_FILE = config.subscriptions_state_file
    PROMO_CODES_STATE_FILE = config.promo_codes_state_file
    ADMIN_USER_IDS = set(config.admin_user_ids)
    TESTER_CHAT_IDS = set(config.tester_chat_ids)
    TELEGRAM_PROVIDER_TOKEN = config.telegram_provider_token
    PUBLIC_PAYMENTS_ENABLED = config.public_payments_enabled
    SUPPORT_CHAT_ID = config.support_chat_id or DEFAULT_SUPPORT_CHAT_ID


async def run_bot() -> None:
    global _RUNTIME_STORE

    _RUNTIME_STORE = None
    config = load_runtime_config()
    _apply_runtime_config(config)
    _initialize_runtime_store(config)

    bot = Bot(config.bot_token)
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
    _record_support_state(message.chat.id, "open")
    await message.answer(SUPPORT_PROMPT_TEXT)


async def _start_promo_code_request(message: Message) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    SESSION_BY_CHAT_ID.pop(message.chat.id, None)
    TRIAL_CHAT_IDS.discard(message.chat.id)
    PROMO_CODE_REQUEST_CHAT_IDS.add(message.chat.id)
    await message.answer(_promo_code_retry_text(PROMO_CODE_PROMPT_TEXT))


def _promo_code_retry_text(text: str) -> str:
    return f"{text}\n\nДля отмены отправьте /cancel."


async def _handle_promo_code_request(message: Message, text: str) -> None:
    if not text:
        await message.answer(_promo_code_retry_text(PROMO_CODE_EMPTY_TEXT))
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
        await message.answer(_promo_code_retry_text(PROMO_CODE_ALREADY_USED_TEXT))
        return
    if activation.status == "disabled":
        await message.answer(_promo_code_retry_text(PROMO_CODE_DISABLED_TEXT))
        return
    if activation.status == "expired":
        await message.answer(_promo_code_retry_text(PROMO_CODE_EXPIRED_TEXT))
        return
    if activation.status == "not_access_code":
        if _remember_discount_promo_code_for_chat(message.chat.id, text):
            PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
            await message.answer(
                PROMO_CODE_DISCOUNT_APPLIED_TEXT,
                reply_markup=_subscription_payment_keyboard(),
            )
            return
        await message.answer(_promo_code_retry_text(PROMO_CODE_NOT_ACCESS_TEXT))
        return
    await message.answer(_promo_code_retry_text(PROMO_CODE_NOT_FOUND_TEXT))


async def _handle_support_request(message: Message, text: str) -> None:
    if not text:
        await message.answer(SUPPORT_TEXT_REQUIRED)
        return

    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    sent = await _send_support_request_to_admin(message, text)
    _record_support_state(message.chat.id, "open" if sent else "closed")
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


def _record_support_state(chat_id: int, status: str) -> None:
    store = _runtime_store()
    if store is None:
        return
    store.record_support_state(
        SupportState(
            user_id=chat_id,
            status=status,
            last_request_at=datetime.now().astimezone(),
        ),
    )


def _format_support_admin_message(message: Message, text: str) -> str:
    chat_id = message.chat.id
    entitlement = _entitlement_for_chat(chat_id)
    username = _payment_safe_support_text(_format_support_username(message))
    user_id = _message_user_id(message)
    display_name = _payment_safe_support_text(_format_support_display_name(message))
    profile_status = "есть" if _profile_for_chat(chat_id) is not None else "нет"
    requested_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    request_text = _truncate_support_text(_payment_safe_support_text(text.strip()))

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
            f"processed_payment_charge_count: {len(entitlement.processed_payment_charge_ids)}",
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


def _payment_safe_support_text(text: object) -> str:
    return _payment_admin_safe_reason(text) or ""


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


async def _send_calculation_options(
    message: Message,
    profile: UserProfile,
    *,
    intro_text: str | None = None,
    footer_text: str | None = None,
) -> None:
    await _send_calculation_report(
        message,
        profile,
        reply_markup=_ration_choice_keyboard_for_chat(message.chat.id),
        intro_text=intro_text,
        footer_text=footer_text,
    )


async def _send_calculation_report(
    message: Message,
    profile: UserProfile,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    intro_text: str | None = None,
    footer_text: str | None = None,
) -> None:
    targets = calculate_targets(profile)
    safety = evaluate_safety(profile)
    text = format_calculation_summary(targets, safety)
    if intro_text:
        text = f"{intro_text}\n\n{text}"
    if footer_text:
        text = f"{text}\n\n{footer_text}"
    await message.answer(
        text,
        reply_markup=reply_markup,
    )


async def _send_trial_plan(message: Message, profile: UserProfile) -> None:
    consumption = _consume_generation_attempt(message.chat.id, "one_day")
    if not consumption.allowed:
        await _send_limit_paywall(message, "one_day")
        return

    recipe_history_entries: list[RecipeHistoryItem] = []
    try:
        await _send_calculation_report(message, profile)
        sent = await _send_plan(
            message,
            profile,
            include_default_after_plan_keyboard=False,
            recipe_history_entries=recipe_history_entries,
        )
    except Exception:
        _refund_generation_attempt(message.chat.id, consumption)
        raise

    if not sent:
        _refund_generation_attempt(message.chat.id, consumption)
        return

    if sent:
        _complete_generation_attempt(message.chat.id, consumption)
        _record_successful_generation_history(
            message.chat.id,
            consumption,
            recipe_history_entries,
        )
        await message.answer(
            TRIAL_SUBSCRIPTION_TEXT + "\n\n" + _format_entitlement_status(message.chat.id),
            reply_markup=_trial_subscription_keyboard(),
        )


async def _send_one_day_plan_with_access(message: Message, profile: UserProfile) -> bool:
    consumption = _consume_generation_attempt(message.chat.id, "one_day")
    if not consumption.allowed:
        await _send_limit_paywall(message, "one_day")
        return False

    recipe_history_entries: list[RecipeHistoryItem] = []
    try:
        sent = await _send_plan(
            message,
            profile,
            status_text=_format_entitlement_status(message.chat.id),
            recipe_history_entries=recipe_history_entries,
        )
    except Exception:
        _refund_generation_attempt(message.chat.id, consumption)
        raise

    if not sent:
        _refund_generation_attempt(message.chat.id, consumption)
    else:
        _complete_generation_attempt(message.chat.id, consumption)
        _record_successful_generation_history(
            message.chat.id,
            consumption,
            recipe_history_entries,
        )
    return sent


async def _send_week_plan_with_access(message: Message, profile: UserProfile) -> bool:
    consumption = _consume_generation_attempt(message.chat.id, "weekly_pdf")
    if not consumption.allowed:
        await _send_limit_paywall(message, "weekly_pdf")
        return False

    recipe_history_entries: list[RecipeHistoryItem] = []
    try:
        sent = await _send_week_plan(
            message,
            profile,
            status_text=_format_entitlement_status(message.chat.id),
            recipe_history_entries=recipe_history_entries,
        )
    except Exception:
        _refund_generation_attempt(message.chat.id, consumption)
        raise

    if not sent:
        _refund_generation_attempt(message.chat.id, consumption)
    else:
        _complete_generation_attempt(message.chat.id, consumption)
        _record_successful_generation_history(
            message.chat.id,
            consumption,
            recipe_history_entries,
        )
    return sent


async def _send_plan(
    message: Message,
    profile: UserProfile,
    *,
    final_reply_markup: InlineKeyboardMarkup | None = None,
    include_default_after_plan_keyboard: bool = True,
    status_text: str | None = None,
    recipe_history_entries: list[RecipeHistoryItem] | None = None,
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
    recent_avoidance = _load_recent_recipe_avoidance(chat_id)
    plan_result = build_one_day_plan(
        profile,
        variety_seed=seed,
        avoided_recipe_ids=recent_avoidance.full_recipe_ids,
        avoided_recipe_keys=recent_avoidance.full_recipe_keys,
        recipe_source="curated_only",
    )
    if _plan_uses_avoided_recipes(
        plan_result,
        set(recent_avoidance.full_recipe_ids),
        set(recent_avoidance.full_recipe_keys),
    ):
        logger.info(
            "One-day generation relaxed recent recipe avoidance for chat_id=%s",
            chat_id,
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
    plan_reply_markup = final_reply_markup
    if plan_reply_markup is None and include_default_after_plan_keyboard:
        plan_reply_markup = _after_plan_keyboard(message.chat.id)
    for index, response in enumerate(messages[2:]):
        markup = plan_reply_markup if index == len(messages[2:]) - 1 else None
        await _send_text_chunks(message, response, markup)
    if recipe_history_entries is not None:
        recipe_history_entries.extend(_recipe_history_items_from_plan(plan_result, "one_day"))
    return True


async def _send_week_plan(
    message: Message,
    profile: UserProfile,
    *,
    status_text: str | None = None,
    recipe_history_entries: list[RecipeHistoryItem] | None = None,
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
    recent_avoidance = _load_recent_recipe_avoidance(chat_id)
    try:
        build_result = await asyncio.to_thread(
            _build_week_plans_with_recent_fallback,
            profile,
            seed,
            recent_avoidance,
        )
        plans = build_result.plans
        plan_dates = _week_plan_dates()

        if not _week_plans_are_complete(plans, profile):
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, WEEK_PDF_FAILURE_TEXT)
            return False

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

        if recipe_history_entries is not None:
            for day_index, plan_result in enumerate(plans):
                recipe_history_entries.extend(
                    _recipe_history_items_from_plan(
                        plan_result,
                        "weekly_pdf",
                        day_index=day_index,
                    )
                )
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


def _build_week_plans_with_recent_fallback(
    profile: UserProfile,
    seed: int,
    recent_avoidance: _RecentRecipeAvoidance,
) -> _WeekPlanBuildResult:
    for phase, avoided_recipe_ids, avoided_recipe_keys in _weekly_recent_avoidance_phases(
        recent_avoidance
    ):
        plans = _build_week_plans(
            profile,
            seed,
            set(avoided_recipe_ids),
            set(avoided_recipe_keys),
        )
        if _week_plans_are_complete(plans, profile):
            if phase != "full_recent" and (
                recent_avoidance.full_recipe_ids or recent_avoidance.full_recipe_keys
            ):
                logger.info(
                    "Weekly generation relaxed recent recipe avoidance: "
                    "phase=%s full_ids=%s full_keys=%s kept_ids=%s kept_keys=%s",
                    phase,
                    len(recent_avoidance.full_recipe_ids),
                    len(recent_avoidance.full_recipe_keys),
                    len(avoided_recipe_ids),
                    len(avoided_recipe_keys),
                )
            return _WeekPlanBuildResult(plans=plans, avoidance_phase=phase)

        if avoided_recipe_ids or avoided_recipe_keys:
            logger.info(
                "Weekly generation could not satisfy recent recipe avoidance: "
                "phase=%s avoided_ids=%s avoided_keys=%s",
                phase,
                len(avoided_recipe_ids),
                len(avoided_recipe_keys),
            )

    return _WeekPlanBuildResult(plans=(), avoidance_phase="failed")


def _weekly_recent_avoidance_phases(
    recent_avoidance: _RecentRecipeAvoidance,
) -> tuple[tuple[str, frozenset[str], frozenset[str]], ...]:
    full = (recent_avoidance.full_recipe_ids, recent_avoidance.full_recipe_keys)
    reduced = (
        recent_avoidance.reduced_recipe_ids,
        recent_avoidance.reduced_recipe_keys,
    )
    empty = (frozenset(), frozenset())
    if not (full[0] or full[1]):
        return (("no_recent", empty[0], empty[1]),)

    phases: list[tuple[str, frozenset[str], frozenset[str]]] = [
        ("full_recent", full[0], full[1])
    ]
    if (reduced[0] or reduced[1]) and reduced != full:
        phases.append(("reduced_recent", reduced[0], reduced[1]))
    phases.append(("no_recent", empty[0], empty[1]))
    return tuple(phases)


def _load_recent_recipe_avoidance(
    chat_id: int,
    *,
    now: datetime | None = None,
) -> _RecentRecipeAvoidance:
    current_time = _recent_history_now(now)
    since = current_time - timedelta(days=RECENT_RECIPE_HISTORY_DAYS)
    history_items = _load_structured_recent_recipe_history(chat_id, since=since)
    if history_items:
        return _recent_recipe_avoidance_from_history(history_items, now=current_time)

    _load_chat_history(chat_id)
    return _recent_recipe_avoidance_from_legacy_chat_history(chat_id)


def _load_structured_recent_recipe_history(
    chat_id: int,
    *,
    since: datetime,
) -> list[RecipeHistoryItem]:
    store = _runtime_store()
    if store is not None:
        loader = getattr(store, "load_recent_recipe_history", None)
        if loader is None:
            return []
        try:
            return list(
                loader(
                    chat_id,
                    since=since,
                    limit=RECENT_RECIPE_HISTORY_LIMIT,
                )
            )
        except Exception:
            logger.warning(
                "Recipe history load failed for chat_id=%s; continuing without "
                "structured recent avoidance",
                chat_id,
                exc_info=True,
            )
            return []

    return load_recent_recipe_history_from_json(
        STATE_FILE,
        chat_id,
        since=since,
        limit=RECENT_RECIPE_HISTORY_LIMIT,
    )


def _recent_recipe_avoidance_from_history(
    history_items: Sequence[RecipeHistoryItem],
    *,
    now: datetime,
) -> _RecentRecipeAvoidance:
    sorted_items = sorted(
        history_items,
        key=lambda item: _recipe_history_generated_at(item)
        or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )[:RECENT_RECIPE_HISTORY_LIMIT]
    reduced_since = now - timedelta(days=RECENT_RECIPE_REDUCED_DAYS)
    reduced_items = [
        item
        for item in sorted_items
        if (
            generated_at := _recipe_history_generated_at(item)
        ) is not None
        and generated_at >= reduced_since
    ][:RECENT_RECIPE_REDUCED_LIMIT]
    return _RecentRecipeAvoidance(
        full_recipe_ids=_recipe_history_ids(sorted_items),
        full_recipe_keys=_recipe_history_keys(sorted_items),
        reduced_recipe_ids=_recipe_history_ids(reduced_items),
        reduced_recipe_keys=_recipe_history_keys(reduced_items),
    )


def _recent_recipe_avoidance_from_legacy_chat_history(chat_id: int) -> _RecentRecipeAvoidance:
    recent_ids = _bounded_recent_strings(
        RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, []),
        RECENT_RECIPE_HISTORY_LIMIT,
    )
    recent_keys = _bounded_recent_strings(
        RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, []),
        RECENT_RECIPE_HISTORY_LIMIT,
    )
    reduced_ids = _bounded_recent_strings(recent_ids, RECENT_RECIPE_REDUCED_LIMIT)
    reduced_keys = _bounded_recent_strings(recent_keys, RECENT_RECIPE_REDUCED_LIMIT)
    return _RecentRecipeAvoidance(
        full_recipe_ids=frozenset(recent_ids),
        full_recipe_keys=frozenset(recent_keys),
        reduced_recipe_ids=frozenset(reduced_ids),
        reduced_recipe_keys=frozenset(reduced_keys),
    )


def _recipe_history_ids(items: Sequence[RecipeHistoryItem]) -> frozenset[str]:
    return frozenset(item.recipe_id for item in items if item.recipe_id)


def _recipe_history_keys(items: Sequence[RecipeHistoryItem]) -> frozenset[str]:
    return frozenset(item.recipe_key for item in items if item.recipe_key)


def _recipe_history_generated_at(item: RecipeHistoryItem) -> datetime | None:
    generated_at = item.generated_at
    if generated_at is None:
        return None
    if generated_at.tzinfo is None:
        return generated_at.replace(tzinfo=UTC)
    return generated_at.astimezone(UTC)


def _bounded_recent_strings(values: Sequence[object], limit: int) -> tuple[str, ...]:
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return ()
    return tuple(str(value) for value in values if value)[-bounded_limit:]


def _recent_history_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


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
            has_future_week_days=day_index < WEEK_PLAN_DAYS - 1,
        )
        if not _week_day_plan_is_complete(plan, profile):
            return ()
        plans.append(plan)
        week_recipe_ids.update(meal.recipe_id for meal in plan.meals if meal.recipe_id)
        week_recipe_keys.update(meal.recipe_key for meal in plan.meals if meal.recipe_key)
    if not _week_plans_are_complete(plans, profile):
        return ()
    return tuple(plans)


def _select_week_day_plan(
    profile: UserProfile,
    seed: int,
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
    week_food_ids: set[str],
    carryovers: dict[str, "_BatchCarryover"],
    *,
    has_future_week_days: bool = True,
) -> tuple[MealPlan, dict[str, "_BatchCarryover"]]:
    best_plan: MealPlan | None = None
    best_carryovers: dict[str, _BatchCarryover] | None = None
    best_score: tuple[float, float, float, int] | None = None
    rejected_plan: MealPlan | None = None
    for candidate_index in range(WEEK_PLAN_CANDIDATE_COUNT):
        plan = build_one_day_plan(
            profile,
            variety_seed=seed + candidate_index,
            avoided_recipe_ids=avoided_recipe_ids,
            avoided_recipe_keys=avoided_recipe_keys,
            recipe_source="curated_only",
            allow_avoided_recipe_relaxation=False,
        )
        candidate_carryovers = _copy_carryovers(carryovers)
        plan = _apply_batch_carryovers(plan, candidate_carryovers)
        if _plan_uses_avoided_recipes(plan, avoided_recipe_ids, avoided_recipe_keys):
            rejected_plan = rejected_plan or plan
            continue
        next_avoided_recipe_ids = set(avoided_recipe_ids)
        next_avoided_recipe_ids.update(meal.recipe_id for meal in plan.meals if meal.recipe_id)
        next_avoided_recipe_keys = set(avoided_recipe_keys)
        next_avoided_recipe_keys.update(meal.recipe_key for meal in plan.meals if meal.recipe_key)
        if has_future_week_days and _carryovers_use_avoided_recipes(
            candidate_carryovers,
            next_avoided_recipe_ids,
            next_avoided_recipe_keys,
        ):
            rejected_plan = rejected_plan or plan
            continue
        score = _weekly_day_selection_score(plan, week_food_ids, candidate_index)
        if best_score is None or score > best_score:
            best_plan = plan
            best_carryovers = candidate_carryovers
            best_score = score

    if best_plan is None or best_carryovers is None:
        if rejected_plan is not None:
            return replace(rejected_plan, meals=()), carryovers
        return (
            build_one_day_plan(
                profile,
                variety_seed=seed,
                avoided_recipe_ids=avoided_recipe_ids,
                avoided_recipe_keys=avoided_recipe_keys,
                recipe_source="curated_only",
                allow_avoided_recipe_relaxation=False,
            ),
            carryovers,
        )
    return best_plan, best_carryovers


def _week_plans_are_complete(plans: Sequence[MealPlan], profile: UserProfile) -> bool:
    return len(plans) == WEEK_PLAN_DAYS and all(_week_day_plan_is_complete(plan, profile) for plan in plans)


def _week_day_plan_is_complete(plan: MealPlan, profile: UserProfile) -> bool:
    return plan.safety.can_generate_plan and len(plan.meals) == _expected_meal_count(profile)


def _plan_uses_avoided_recipes(
    plan: MealPlan,
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
) -> bool:
    return any(
        (meal.recipe_id is not None and meal.recipe_id in avoided_recipe_ids)
        or (meal.recipe_key is not None and meal.recipe_key in avoided_recipe_keys)
        for meal in plan.meals
    )


def _carryovers_use_avoided_recipes(
    carryovers: dict[str, "_BatchCarryover"],
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
) -> bool:
    return any(
        (carryover.meal.recipe_id is not None and carryover.meal.recipe_id in avoided_recipe_ids)
        or (carryover.meal.recipe_key is not None and carryover.meal.recipe_key in avoided_recipe_keys)
        for carryover in carryovers.values()
    )


def _expected_meal_count(profile: UserProfile) -> int:
    return min(5, max(3, profile.meal_count))


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


def _weekly_day_selection_score(
    plan: MealPlan,
    week_food_ids: set[str],
    candidate_index: int,
) -> tuple[float, float, float, int]:
    in_calorie_band, calorie_gap = _calorie_fit(plan)
    return (
        1.0 if in_calorie_band else 0.0,
        -calorie_gap,
        _ingredient_reuse_score(plan, week_food_ids),
        -candidate_index,
    )


def _calorie_fit(plan: MealPlan) -> tuple[bool, float]:
    energy = plan.totals.get("energy_kcal")
    target = plan.targets.targets.get("energy_kcal")
    lower, upper = plan.targets.calorie_bounds
    denominator = max(target, 1.0)

    if lower <= energy <= upper:
        return True, abs(energy - target) / denominator
    if energy < lower:
        return False, (lower - energy) / denominator
    return False, (energy - upper) / denominator


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


def _recipe_history_items_from_plan(
    plan_result: MealPlan,
    ration_kind: RationKind,
    *,
    day_index: int | None = None,
) -> list[RecipeHistoryItem]:
    return [
        RecipeHistoryItem(
            recipe_id=meal.recipe_id,
            recipe_key=meal.recipe_key,
            meal_slot=_meal_slot(meal),
            ration_kind=ration_kind,
            day_index=day_index,
            meal_index=meal_index,
        )
        for meal_index, meal in enumerate(plan_result.meals)
        if meal.recipe_id and meal.recipe_key
    ]


def _remember_recipes(chat_id: int, plan_result) -> None:
    _remember_recipe_history_items(
        chat_id,
        _recipe_history_items_from_plan(plan_result, "one_day"),
    )


def _remember_recipe_history_items(
    chat_id: int,
    entries: Sequence[RecipeHistoryItem],
) -> None:
    if not entries:
        return
    id_history = RECENT_RECIPE_IDS_BY_CHAT_ID.setdefault(chat_id, [])
    key_history = RECENT_RECIPE_KEYS_BY_CHAT_ID.setdefault(chat_id, [])
    id_history.extend(entry.recipe_id for entry in entries if entry.recipe_id)
    key_history.extend(entry.recipe_key for entry in entries if entry.recipe_key)
    if len(id_history) > RECENT_RECIPE_LIMIT:
        del id_history[:-RECENT_RECIPE_LIMIT]
    if len(key_history) > RECENT_RECIPE_LIMIT:
        del key_history[:-RECENT_RECIPE_LIMIT]
    _save_chat_history(chat_id)


def _record_successful_generation_history(
    chat_id: int,
    consumption: AttemptConsumption,
    entries: Sequence[RecipeHistoryItem],
) -> None:
    if not consumption.allowed or not entries:
        return

    generation_id = _history_generation_id(consumption)
    entries_with_context = [
        replace(
            entry,
            user_id=chat_id,
            ration_kind=consumption.ration_kind,
            generation_id=entry.generation_id
            if entry.generation_id is not None
            else generation_id,
        )
        for entry in entries
    ]
    store = _runtime_store()
    if store is not None:
        store.record_recipe_history(chat_id, entries_with_context)
        _remember_recipe_history_items(chat_id, entries_with_context)
        return

    record_recipe_history_in_json(STATE_FILE, chat_id, entries_with_context)
    _load_chat_history(chat_id)


def _history_generation_id(consumption: AttemptConsumption) -> int | None:
    raw_generation_id = getattr(consumption, "_postgres_generation_id", None)
    if raw_generation_id is None:
        return None
    try:
        return int(raw_generation_id)
    except (TypeError, ValueError):
        return None


def _runtime_store() -> DietBotStore | None:
    return _RUNTIME_STORE


def _load_chat_state_for_chat(chat_id: int) -> dict[str, object]:
    store = _runtime_store()
    if store is not None:
        return store.load_chat_state(chat_id)
    return dict(_load_state().get(str(chat_id), {}))


def _save_chat_state_for_chat(chat_id: int, chat_state: dict[str, object]) -> None:
    store = _runtime_store()
    if store is not None:
        store.save_chat_state(chat_id, chat_state)
        return

    with json_storage_transaction(STATE_FILE):
        state = _load_state()
        state[str(chat_id)] = dict(chat_state)
        _save_state(state)


def _load_profile_data_for_chat(chat_id: int) -> dict[str, object] | None:
    store = _runtime_store()
    if store is not None:
        return store.load_profile_data(chat_id)
    raw_profile = _load_chat_state_for_chat(chat_id).get("profile")
    return raw_profile if isinstance(raw_profile, dict) else None


def _save_profile_data_for_chat(chat_id: int, profile_data: dict[str, object]) -> None:
    store = _runtime_store()
    if store is not None:
        store.save_profile_data(chat_id, profile_data)
        return

    chat_state = _load_chat_state_for_chat(chat_id)
    chat_state["profile"] = profile_data
    _save_chat_state_for_chat(chat_id, chat_state)


def _load_chat_history(chat_id: int) -> None:
    chat_state = _load_chat_state_for_chat(chat_id)
    RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_ids", []))[-RECENT_RECIPE_LIMIT:]
    RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_keys", []))[-RECENT_RECIPE_LIMIT:]


def _save_chat_history(chat_id: int) -> None:
    chat_state = _load_chat_state_for_chat(chat_id)
    chat_state["recipe_ids"] = RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, [])[-RECENT_RECIPE_LIMIT:]
    chat_state["recipe_keys"] = RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, [])[-RECENT_RECIPE_LIMIT:]
    _save_chat_state_for_chat(chat_id, chat_state)


def _profile_for_chat(chat_id: int) -> UserProfile | None:
    profile = PROFILE_BY_CHAT_ID.get(chat_id)
    if profile is not None:
        return profile

    raw_profile = _load_profile_data_for_chat(chat_id)
    if raw_profile is None:
        return None

    profile = _profile_from_dict(raw_profile)
    if profile is None:
        return None
    PROFILE_BY_CHAT_ID[chat_id] = profile
    return profile


def _save_chat_profile(chat_id: int, profile: UserProfile) -> None:
    _save_profile_data_for_chat(chat_id, _profile_to_dict(profile))


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
        if isinstance(value, dict) and isinstance(value.get("recipe_history"), list):
            chat_state["recipe_history"] = list(value["recipe_history"])
        if isinstance(value, dict) and isinstance(value.get("profile"), dict):
            chat_state["profile"] = value["profile"]
        state[str(chat_id)] = chat_state
    return state


def _save_state(state: dict[str, dict[str, object]]) -> None:
    atomic_write_json(STATE_FILE, state)


def _profile_to_dict(profile: UserProfile) -> dict[str, object]:
    return {
        "age": profile.age,
        "sex": profile.sex.value,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "goal": profile.goal.value,
        "activity": profile.activity.value,
        "meal_count": profile.meal_count,
        "cooking_time": normalize_cooking_time_preference(profile.cooking_time).value,
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
            cooking_time=normalize_cooking_time_preference(raw.get("cooking_time")),
            restrictions=restrictions,
            conditions=conditions,
            allow_lactose_free_dairy=bool(raw.get("allow_lactose_free_dairy", True)),
            allow_gluten_free_oats=bool(raw.get("allow_gluten_free_oats", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _start_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=TRY_FREE_TEXT, callback_data=CALLBACK_START)],
    ]
    if _public_payments_enabled():
        buttons.append(
            [
                InlineKeyboardButton(
                    text=SUBSCRIBE_MONTH_TEXT,
                    callback_data=CALLBACK_SUBSCRIBE,
                ),
            ]
        )
    buttons.extend(
        [
            [InlineKeyboardButton(text=FEATURES_TEXT, callback_data=CALLBACK_FEATURES)],
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )
    return InlineKeyboardMarkup(
        inline_keyboard=buttons,
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


def _public_payments_enabled() -> bool:
    return PUBLIC_PAYMENTS_ENABLED


def _public_payments_disabled_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
        ],
    )


def _subscription_payment_text() -> str:
    if _public_payments_enabled():
        return SUBSCRIPTION_PAYMENT_TEXT
    return (
        "FoodBalance - цифровой сервис персональных рационов питания.\n\n"
        f"{PUBLIC_PAYMENTS_PILOT_TEXT}\n\n"
        "В месячный доступ входит:\n"
        f"• {MONTHLY_WEEKLY_PDF_LIMIT} недельных PDF-рациона\n"
        f"• {MONTHLY_ONE_DAY_LIMIT} рационов на 1 день\n"
        "• рецепты и список продуктов по анкете"
    )


async def _send_public_payments_disabled_notice(message: Message) -> None:
    await message.answer(
        PUBLIC_PAYMENTS_PILOT_TEXT,
        reply_markup=_public_payments_disabled_keyboard(),
    )


async def _send_subscription_payment_options(message: Message) -> None:
    if await _send_active_subscription_notice_if_needed(message):
        return
    await message.answer(_subscription_payment_text(), reply_markup=_subscription_payment_keyboard())


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
    await _send_extra_purchase_subscription_required_message(message)
    return True


async def _send_extra_purchase_subscription_required_message(message: Message) -> None:
    if not _public_payments_enabled():
        await message.answer(
            "Разовые покупки доступны только при активном месячном доступе.\n\n"
            f"{PUBLIC_PAYMENTS_PILOT_TEXT}",
            reply_markup=_public_payments_disabled_keyboard(),
        )
        return
    await message.answer(
        "Разовые покупки доступны только при активной подписке.\n\n"
        "Чтобы продолжить, оформите месячный доступ.",
        reply_markup=_subscription_payment_keyboard(),
    )


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


def _payment_provider_for_payload(payload: str) -> PaymentProvider | None:
    return PAYMENT_PAYLOAD_PROVIDERS.get(payload)


def _payment_product_for_payload(payload: str) -> PaymentProduct | None:
    return PAYMENT_PAYLOAD_PRODUCTS.get(payload)


def _payment_user_id_for_message(message: Message) -> int | None:
    user_id = _message_user_id(message)
    if user_id is not None:
        return user_id
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    return chat_id if isinstance(chat_id, int) else None


async def _create_or_reuse_invoice_payment_order(
    message: Message,
    *,
    provider: PaymentProvider,
    product: PaymentProduct,
) -> PaymentOrder | None:
    store = _runtime_store()
    if store is None:
        await message.answer(PAYMENT_INVOICE_CREATION_FAILED_TEXT)
        return None

    buyer_id = _payment_user_id_for_message(message)
    if buyer_id is None:
        await message.answer(PAYMENT_INVOICE_CREATION_FAILED_TEXT)
        return None

    product_metadata = get_payment_product_invoice_metadata(provider, product)
    promo_code = _pending_discount_promo_code_for_order(message.chat.id, product)
    result = store.create_or_reuse_pending_payment_order(
        user_id=buyer_id,
        delivery_chat_id=message.chat.id,
        provider=provider,
        product=product,
        amount=product_metadata.amount,
        currency=product_metadata.currency,
        promo_code=promo_code,
    )
    if result.accepted and result.order is not None:
        _clear_pending_discount_promo_code(message.chat.id, promo_code)
        return result.order
    if result.code == PaymentOrderCreationCode.ACTIVE_SUBSCRIPTION_REQUIRED:
        await _send_extra_purchase_subscription_required_message(message)
        return None
    await message.answer(PAYMENT_INVOICE_CREATION_FAILED_TEXT)
    return None


def _mark_payment_order_invoice_link(order: PaymentOrder, invoice_link: str) -> None:
    store = _runtime_store()
    marker = getattr(store, "mark_payment_order_invoice_link", None)
    if callable(marker):
        marker(order.order_id, invoice_link)


def _mark_payment_order_invoice_creation_failed(order: PaymentOrder) -> None:
    store = _runtime_store()
    marker = getattr(store, "mark_payment_order_invoice_creation_failed", None)
    if callable(marker):
        marker(order.order_id)


async def _send_stars_invoice_link(message: Message, payload: str) -> None:
    if not _public_payments_enabled():
        await _send_public_payments_disabled_notice(message)
        return
    provider = _payment_provider_for_payload(payload)
    product = _payment_product_for_payload(payload)
    if provider != PaymentProvider.TELEGRAM_STARS or product is None:
        return
    order = await _create_or_reuse_invoice_payment_order(
        message,
        provider=provider,
        product=product,
    )
    if order is None:
        return

    metadata = build_payment_invoice_metadata(order)
    title = PAYMENT_PAYLOAD_TITLES[payload]
    description = PAYMENT_PAYLOAD_DESCRIPTIONS[payload]
    amount = metadata.amount
    if order.invoice_link:
        invoice_link = order.invoice_link
    else:
        try:
            invoice_link = await message.bot.create_invoice_link(
                title=title,
                description=description,
                payload=metadata.payload,
                currency=metadata.currency.value,
                prices=[LabeledPrice(label=title, amount=amount)],
                provider_token="",
                subscription_period=metadata.subscription_period,
            )
        except TelegramAPIError:
            _mark_payment_order_invoice_creation_failed(order)
            await message.answer(PAYMENT_INVOICE_CREATION_FAILED_TEXT)
            return
        _mark_payment_order_invoice_link(order, invoice_link)

    await message.answer(
        f"{title}\n\nСтоимость: {amount} Stars.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить в Telegram", url=invoice_link)],
            ],
        ),
    )


async def _send_yookassa_invoice_link(message: Message, payload: str) -> None:
    if not _public_payments_enabled():
        await _send_public_payments_disabled_notice(message)
        return
    provider_token = TELEGRAM_PROVIDER_TOKEN.strip()
    if not provider_token:
        await message.answer(_ru_card_payment_unavailable_text(payload))
        return

    provider = _payment_provider_for_payload(payload)
    product = _payment_product_for_payload(payload)
    if provider != PaymentProvider.YOOKASSA or product is None:
        return
    order = await _create_or_reuse_invoice_payment_order(
        message,
        provider=provider,
        product=product,
    )
    if order is None:
        return

    metadata = build_payment_invoice_metadata(order)
    amount = metadata.amount
    title = RUB_PAYMENT_PAYLOAD_TITLES[payload]
    description = RUB_PAYMENT_PAYLOAD_DESCRIPTIONS[payload]
    if order.invoice_link:
        invoice_link = order.invoice_link
    else:
        try:
            invoice_link = await message.bot.create_invoice_link(
                title=title,
                description=description,
                payload=metadata.payload,
                currency=metadata.currency.value,
                prices=[LabeledPrice(label=title, amount=amount)],
                provider_token=provider_token,
                need_email=metadata.need_email,
                send_email_to_provider=metadata.send_email_to_provider,
                provider_data=json.dumps(metadata.provider_data, ensure_ascii=False),
            )
        except TelegramAPIError:
            _mark_payment_order_invoice_creation_failed(order)
            await message.answer(PAYMENT_INVOICE_CREATION_FAILED_TEXT)
            return
        _mark_payment_order_invoice_link(order, invoice_link)

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
    return _payment_pre_checkout_validation(pre_checkout_query).approved


def _payment_pre_checkout_validation(
    pre_checkout_query: PreCheckoutQuery,
) -> PaymentPreCheckoutValidation:
    store = _runtime_store()
    user_id = _pre_checkout_user_id(pre_checkout_query)
    if store is None or user_id is None:
        return _payment_pre_checkout_rejection()

    try:
        return validate_payment_pre_checkout(
            store,
            payload=str(getattr(pre_checkout_query, "invoice_payload", "")),
            user_id=user_id,
            currency=str(getattr(pre_checkout_query, "currency", "")),
            total_amount=int(getattr(pre_checkout_query, "total_amount", -1)),
        )
    except Exception:
        return _payment_pre_checkout_rejection()


def _pre_checkout_user_id(pre_checkout_query: PreCheckoutQuery) -> int | None:
    user = getattr(pre_checkout_query, "from_user", None)
    user_id = getattr(user, "id", None)
    return user_id if isinstance(user_id, int) else None


def _payment_pre_checkout_rejection() -> PaymentPreCheckoutValidation:
    return PaymentPreCheckoutValidation(
        approved=False,
        code=PaymentPreCheckoutCode.ORDER_NOT_FOUND,
        message=PAYMENT_PRE_CHECKOUT_FAILED_TEXT,
    )


def _load_entitlement_for_chat(chat_id: int) -> Entitlement:
    store = _runtime_store()
    if store is not None:
        return store.get_entitlement(chat_id)
    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    return entitlements.get(chat_id, Entitlement())


def _save_entitlement_for_chat(chat_id: int, entitlement: Entitlement) -> None:
    store = _runtime_store()
    if store is not None:
        store.save_entitlement(chat_id, entitlement)
        return

    with json_storage_transaction(SUBSCRIPTIONS_STATE_FILE):
        entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
        entitlements[chat_id] = entitlement
        save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)


def _apply_successful_payment(message: Message, payment: SuccessfulPayment) -> PaymentApplication:
    store = _runtime_store()
    payment_input = _successful_payment_input_for_message(message, payment)
    if store is None or payment_input is None:
        return PaymentApplication(False)

    try:
        result = store.apply_successful_payment(payment_input)
    except Exception:
        return PaymentApplication(False)
    return _payment_application_from_successful_payment_result(result)


def _successful_payment_input_for_message(
    message: Message,
    payment: SuccessfulPayment,
) -> PaymentSuccessfulPaymentInput | None:
    user_id = _payment_user_id_for_message(message)
    delivery_chat_id = getattr(getattr(message, "chat", None), "id", None)
    provider = _successful_payment_provider_for_currency(getattr(payment, "currency", None))
    if user_id is None or not isinstance(delivery_chat_id, int) or provider is None:
        return None

    try:
        return PaymentSuccessfulPaymentInput(
            payload=str(getattr(payment, "invoice_payload", "")),
            provider=provider,
            telegram_charge_id=str(getattr(payment, "telegram_payment_charge_id", "")),
            provider_charge_id=getattr(payment, "provider_payment_charge_id", None),
            user_id=user_id,
            delivery_chat_id=delivery_chat_id,
            currency=str(getattr(payment, "currency", "")),
            total_amount=int(getattr(payment, "total_amount", -1)),
            subscription_expiration_timestamp=_successful_payment_subscription_expiration(payment),
        )
    except (TypeError, ValueError):
        return None


def _successful_payment_provider_for_currency(currency: object) -> PaymentProvider | None:
    if str(currency) == "XTR":
        return PaymentProvider.TELEGRAM_STARS
    if str(currency) == "RUB":
        return PaymentProvider.YOOKASSA
    return None


def _successful_payment_subscription_expiration(payment: SuccessfulPayment) -> int | None:
    expiration = getattr(payment, "subscription_expiration_date", None)
    if expiration is None:
        expiration = getattr(payment, "subscription_expiration_timestamp", None)
    return expiration if isinstance(expiration, int) else None


def _payment_application_from_successful_payment_result(result: object) -> PaymentApplication:
    processed = bool(getattr(result, "processed", False))
    duplicate = bool(getattr(result, "duplicate", False))
    order = getattr(result, "order", None)
    grant = (
        _payment_grant_for_order_product(getattr(order, "product", None))
        if processed or duplicate
        else None
    )
    return PaymentApplication(processed, grant, duplicate=duplicate)


def _payment_grant_for_order_product(product: object) -> str | None:
    if product == PaymentProduct.SUBSCRIPTION_MONTH:
        return "subscription"
    if product == PaymentProduct.EXTRA_ONE_DAY:
        return "extra_one_day"
    if product == PaymentProduct.EXTRA_WEEKLY_PDF:
        return "extra_weekly_pdf"
    return None


def _payment_success_text(result: PaymentApplication) -> str:
    if result.grant == "subscription":
        return "Подписка активна. Лимиты на этот месяц обновлены."
    if result.grant == "extra_one_day":
        return "Готово: добавлена 1 попытка для дневного рациона."
    if result.grant == "extra_weekly_pdf":
        return "Готово: добавлена 1 попытка для недельного PDF."
    return "Платеж обработан."


def _activate_promo_code_for_chat(chat_id: int, promo_code: str) -> PromoCodeActivation:
    store = _runtime_store()
    if store is not None:
        return store.activate_promo_code(chat_id, promo_code)

    with json_storage_transaction(PROMO_CODES_STATE_FILE, SUBSCRIPTIONS_STATE_FILE):
        activation = activate_promo_code(PROMO_CODES_STATE_FILE, promo_code, chat_id)
        if not activation.activated:
            return activation

        entitlement = _load_entitlement_for_chat(chat_id)
        apply_monthly_access_promo_grant(
            entitlement,
            promo_code_grant_charge_id(activation.code),
        )
        _save_entitlement_for_chat(chat_id, entitlement)
        return activation


def _remember_discount_promo_code_for_chat(chat_id: int, promo_code: str) -> bool:
    store = _runtime_store()
    getter = getattr(store, "get_promo_code", None)
    if not callable(getter):
        return False
    try:
        promo = getter(promo_code, active_only=True)
    except Exception:
        return False
    if promo is None or getattr(promo, "kind", None) != PromoCodeKind.DISCOUNT:
        return False
    DISCOUNT_PROMO_CODE_BY_CHAT_ID[chat_id] = normalize_promo_code(promo_code)
    return True


def _pending_discount_promo_code_for_order(
    chat_id: int,
    product: PaymentProduct,
) -> str | None:
    if product != PaymentProduct.SUBSCRIPTION_MONTH:
        return None
    return DISCOUNT_PROMO_CODE_BY_CHAT_ID.get(chat_id)


def _clear_pending_discount_promo_code(chat_id: int, promo_code: str | None) -> None:
    if promo_code is None:
        return
    if DISCOUNT_PROMO_CODE_BY_CHAT_ID.get(chat_id) == promo_code:
        DISCOUNT_PROMO_CODE_BY_CHAT_ID.pop(chat_id, None)


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


def _is_admin_callback(callback: CallbackQuery) -> bool:
    user_id = _callback_user_id(callback)
    return bool(user_id is not None and user_id in ADMIN_USER_IDS)


@dataclass(frozen=True)
class _PaymentEventAdminCommand:
    mode: str
    action: str
    event_type: PaymentEventType | None = None
    provider: PaymentProvider | None = None
    charge_alias: str | None = None
    reconciliation_action: PaymentReconciliationAction | None = None
    target_event_id: str | None = None
    target_order_id: str | None = None
    reason: str | None = None


def _parse_payment_event_admin_command(text: str) -> _PaymentEventAdminCommand | None:
    args = text.split()
    if not args:
        return None
    args = args[1:]
    if not args:
        return None

    action = args[0].strip().lower().replace("-", "_")
    if action in {"refund", "chargeback", "cancel", "cancel_subscription"}:
        if len(args) < 3:
            return None
        provider = _parse_payment_admin_provider(args[1])
        charge_alias = args[2].strip()
        if provider is None or not charge_alias:
            return None
        event_type = (
            PaymentEventType.CANCEL_SUBSCRIPTION
            if action in {"cancel", "cancel_subscription"}
            else PaymentEventType(action)
        )
        return _PaymentEventAdminCommand(
            mode="reversal",
            action=action,
            event_type=event_type,
            provider=provider,
            charge_alias=charge_alias,
            reason=_payment_admin_safe_reason(" ".join(args[3:]) or None),
        )

    if action in {"reconcile", "reconcile_orphan", "reconcile_orphan_success"}:
        if len(args) < 2:
            return None
        if action == "reconcile" and len(args) == 2:
            return _PaymentEventAdminCommand(
                mode="reconciliation",
                action=action,
                reconciliation_action=PaymentReconciliationAction.RECONCILE_PENDING_REVERSAL,
                target_event_id=args[1].strip() or None,
            )
        if len(args) < 3:
            return None
        return _PaymentEventAdminCommand(
            mode="reconciliation",
            action=action,
            reconciliation_action=PaymentReconciliationAction.RECONCILE_ORPHAN_SUCCESS,
            target_event_id=args[1].strip() or None,
            target_order_id=args[2].strip() or None,
            reason=_payment_admin_safe_reason(" ".join(args[3:]) or None),
        )

    if action in {"reconcile_pending", "reconcile_pending_reversal"}:
        if len(args) < 2:
            return None
        return _PaymentEventAdminCommand(
            mode="reconciliation",
            action=action,
            reconciliation_action=PaymentReconciliationAction.RECONCILE_PENDING_REVERSAL,
            target_event_id=args[1].strip() or None,
            reason=_payment_admin_safe_reason(" ".join(args[2:]) or None),
        )

    if action in {"ignore", "close"}:
        if len(args) < 2:
            return None
        return _PaymentEventAdminCommand(
            mode="reconciliation",
            action=action,
            reconciliation_action=PaymentReconciliationAction.IGNORE_EVENT,
            target_event_id=args[1].strip() or None,
            reason=_payment_admin_safe_reason(" ".join(args[2:]) or None),
        )

    return None


def _payment_event_admin_usage_text() -> str:
    return (
        "Usage:\n"
        "/payment_event refund <provider> <charge_alias> [reason]\n"
        "/payment_event chargeback <provider> <charge_alias> [reason]\n"
        "/payment_event cancel_subscription <provider> <charge_alias> [reason]\n"
        "/payment_event reconcile_orphan <event_id> <order_id> [reason]\n"
        "/payment_event reconcile_pending <event_id> [reason]\n"
        "/payment_event ignore <event_id> <reason>"
    )


def _parse_payment_admin_provider(value: str) -> PaymentProvider | None:
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "stars": PaymentProvider.TELEGRAM_STARS,
        "telegram": PaymentProvider.TELEGRAM_STARS,
        "telegram_stars": PaymentProvider.TELEGRAM_STARS,
        "xtr": PaymentProvider.TELEGRAM_STARS,
        "card": PaymentProvider.YOOKASSA,
        "rub": PaymentProvider.YOOKASSA,
        "yookassa": PaymentProvider.YOOKASSA,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return PaymentProvider(normalized)
    except ValueError:
        return None


def _apply_admin_payment_reversal(
    store: DietBotStore,
    command: _PaymentEventAdminCommand,
    message: Message,
) -> PaymentReversalResult:
    telegram_charge_id, provider_charge_id = _payment_charge_ids_from_alias(command.charge_alias)
    reversal = PaymentReversalInput(
        event_type=command.event_type,
        provider=command.provider,
        telegram_charge_id=telegram_charge_id,
        provider_charge_id=provider_charge_id,
        reason=command.reason,
        raw_payload=_admin_payment_event_raw_payload(message, command),
    )
    return store.apply_payment_reversal(reversal)


def _apply_admin_payment_reconciliation(
    store: DietBotStore,
    command: _PaymentEventAdminCommand,
    message: Message,
) -> PaymentReconciliationResult:
    reconciliation = PaymentReconciliationInput(
        action=command.reconciliation_action,
        target_event_id=command.target_event_id,
        target_order_id=command.target_order_id,
        admin_actor=_payment_admin_actor(message),
        reason=command.reason,
    )
    return store.apply_payment_reconciliation(reconciliation)


def _payment_charge_ids_from_alias(charge_alias: str | None) -> tuple[str | None, str | None]:
    text = str(charge_alias or "").strip()
    lowered = text.lower()
    for prefix in ("provider:", "provider_charge:", "pc:"):
        if lowered.startswith(prefix):
            value = text[len(prefix):].strip()
            return None, value or None
    for prefix in ("telegram:", "telegram_charge:", "tg:"):
        if lowered.startswith(prefix):
            value = text[len(prefix):].strip()
            return value or None, None
    return (text or None), (text or None)


def _admin_payment_event_raw_payload(
    message: Message,
    command: _PaymentEventAdminCommand,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": "admin_payment_event_command",
        "action": command.action,
        "admin_actor": redact_admin_actor_metadata(_payment_admin_actor(message)),
    }
    if command.reason:
        payload["reason"] = command.reason
    return payload


def _payment_admin_actor(message: Message) -> dict[str, object]:
    actor: dict[str, object] = {"chat_id": message.chat.id}
    user_id = _message_user_id(message)
    if user_id is not None:
        actor["admin_id"] = user_id
    return actor


def _format_admin_payment_reversal_result(
    command: _PaymentEventAdminCommand,
    result: PaymentReversalResult,
) -> str:
    status = _admin_payment_result_status(result)
    headline = (
        "processed: reversal applied"
        if status == "processed"
        else "duplicate: reversal no-op"
        if status == "duplicate"
        else "no_op: reversal did not change access"
    )
    lines = [
        headline,
        f"result: {status}",
        f"event_type: {_enum_value(command.event_type)}",
        f"provider: {_enum_value(command.provider)}",
        f"code: {_enum_value(result.code)}",
    ]
    _append_admin_payment_result_details(lines, order=getattr(result, "order", None), event=getattr(result, "event", None))
    return "\n".join(lines)


def _format_admin_payment_reconciliation_result(
    command: _PaymentEventAdminCommand,
    result: PaymentReconciliationResult,
) -> str:
    status = _admin_payment_result_status(result)
    headline = (
        "processed: reconciliation applied"
        if status == "processed"
        else "duplicate: reconciliation no-op"
        if status == "duplicate"
        else "no_op: reconciliation did not change access"
    )
    target_event = getattr(result, "target_event", None)
    order = getattr(result, "order", None)
    lines = [
        headline,
        f"result: {status}",
        f"action: {_enum_value(command.reconciliation_action)}",
        f"code: {_enum_value(result.code)}",
    ]
    if target_event is None and command.target_event_id:
        lines.append(f"event: {_short_payment_identifier(command.target_event_id)}")
    _append_admin_payment_result_details(lines, order=order, event=target_event)
    return "\n".join(lines)


def _admin_payment_result_status(result: object) -> str:
    if bool(getattr(result, "duplicate", False)):
        return "duplicate"
    if bool(getattr(result, "processed", False)):
        return "processed"
    return "no_op"


def _append_admin_payment_result_details(
    lines: list[str],
    *,
    order: PaymentOrder | None,
    event: object,
) -> None:
    if order is not None:
        lines.append(f"order: {_short_payment_identifier(order.order_id)}")
    if event is not None:
        event_id = getattr(event, "event_id", None)
        if event_id:
            lines.append(f"event: {_short_payment_identifier(str(event_id))}")
        reason = _payment_admin_safe_reason(getattr(event, "reason", None))
        if reason:
            lines.append(f"reason: {reason}")


def _payment_admin_safe_reason(reason: object) -> str | None:
    if reason is None:
        return None
    text = str(redact_payment_payload(str(reason).strip())).strip()
    if not text:
        return None
    for sensitive_word in ("order_info", "provider_data", "receipt", "customer"):
        text = re.sub(re.escape(sensitive_word), REDACTED_PAYMENT_VALUE, text, flags=re.IGNORECASE)
    return text


def _short_payment_identifier(value: str | None) -> str:
    text = str(value or "").strip()
    if len(text) <= 10:
        return text
    return f"{text[:4]}...{text[-4:]}"


def _enum_value(value: object) -> str:
    enum_value = getattr(value, "value", None)
    return str(enum_value if enum_value is not None else value)


def _is_admin_access_code_command_text(text: str) -> bool:
    args = text.split()[1:]
    return len(args) == 1 and args[0].strip().lower() == "code"


def _is_admin_panel_command_text(text: str) -> bool:
    return _normalize_command_text(text) == "330366" and not text.split()[1:]


def _admin_promo_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=ADMIN_CREATE_MONTHLY_ACCESS_CODE_TEXT,
                    callback_data=CALLBACK_ADMIN_CREATE_MONTHLY_ACCESS_CODE,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=ADMIN_CREATE_DISCOUNT_PROMO_TEXT,
                    callback_data=CALLBACK_ADMIN_CREATE_DISCOUNT_PROMO,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=ADMIN_LIST_DISCOUNT_PROMOS_TEXT,
                    callback_data=CALLBACK_ADMIN_LIST_DISCOUNT_PROMOS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=ADMIN_DISABLE_DISCOUNT_PROMO_TEXT,
                    callback_data=CALLBACK_ADMIN_DISABLE_DISCOUNT_PROMO,
                ),
            ],
        ],
    )


async def _send_admin_promo_panel(message: Message) -> None:
    await message.answer(
        ADMIN_PROMO_PANEL_TEXT,
        reply_markup=_admin_promo_panel_keyboard(),
    )


@dataclass(frozen=True)
class _AdminDiscountPromoInput:
    code: str
    percent: int


def _set_admin_promo_action(chat_id: int, action: str) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)
    SESSION_BY_CHAT_ID.pop(chat_id, None)
    ADMIN_PROMO_ACTION_BY_CHAT_ID[chat_id] = action


async def _start_admin_discount_promo_create(message: Message) -> None:
    _set_admin_promo_action(message.chat.id, ADMIN_PROMO_ACTION_CREATE_DISCOUNT)
    await message.answer(ADMIN_DISCOUNT_PROMO_INPUT_TEXT)


async def _start_admin_discount_promo_disable(message: Message) -> None:
    _set_admin_promo_action(message.chat.id, ADMIN_PROMO_ACTION_DISABLE_DISCOUNT)
    await message.answer(ADMIN_DISABLE_DISCOUNT_PROMO_INPUT_TEXT)


async def _handle_admin_promo_action_input(message: Message, text: str) -> None:
    action = ADMIN_PROMO_ACTION_BY_CHAT_ID.get(message.chat.id)
    if action == ADMIN_PROMO_ACTION_CREATE_DISCOUNT:
        parsed, error = _parse_admin_discount_promo_input(text)
        if error is not None or parsed is None:
            await message.answer(error or ADMIN_DISCOUNT_PROMO_INPUT_TEXT)
            return
        promo, error = _create_or_update_admin_discount_promo(parsed)
        if error is not None or promo is None:
            await message.answer(error or ADMIN_PROMO_STORAGE_UNAVAILABLE_TEXT)
            return
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
        await message.answer(
            f"Скидка активна: {promo.code}\nРазмер скидки: {promo.discount_percent}%."
        )
        return

    if action == ADMIN_PROMO_ACTION_DISABLE_DISCOUNT:
        code, error = _parse_admin_discount_code_input(text)
        if error is not None or code is None:
            await message.answer(error or ADMIN_DISABLE_DISCOUNT_PROMO_INPUT_TEXT)
            return
        promo, error = _disable_admin_discount_promo(code)
        if error is not None or promo is None:
            await message.answer(error or f"Discount promo code {code} не найден.")
            return
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
        await message.answer(f"Скидка отключена: {promo.code}.")
        return

    ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)


def _parse_admin_discount_promo_input(
    text: str,
) -> tuple[_AdminDiscountPromoInput | None, str | None]:
    stripped = text.strip()
    if not stripped:
        return None, "Отправьте код и процент скидки в формате CODE PERCENT."

    parts = stripped.split()
    if len(parts) == 1:
        return None, "Не указан процент скидки. Формат: CODE PERCENT."
    if len(parts) > 2:
        return None, "Код должен быть без пробелов. Формат: CODE PERCENT."

    code = normalize_promo_code(parts[0].strip().upper())
    if not code:
        return None, "Код не должен быть пустым."

    try:
        percent = int(parts[1])
    except ValueError:
        return None, "Процент скидки должен быть числом от 1 до 90."

    if percent < 1 or percent > 90:
        return None, "Процент скидки должен быть от 1 до 90."
    return _AdminDiscountPromoInput(code=code, percent=percent), None


def _parse_admin_discount_code_input(text: str) -> tuple[str | None, str | None]:
    stripped = text.strip()
    if not stripped:
        return None, "Отправьте CODE скидки."
    parts = stripped.split()
    if len(parts) != 1:
        return None, "Код скидки должен быть без пробелов."
    code = normalize_promo_code(parts[0].strip().upper())
    if not code:
        return None, "Код не должен быть пустым."
    return code, None


def _create_or_update_admin_discount_promo(
    parsed: _AdminDiscountPromoInput,
) -> tuple[PromoCodeDefinition | None, str | None]:
    store = _runtime_store()
    getter = getattr(store, "get_promo_code", None)
    creator = getattr(store, "create_promo_code", None)
    if store is None or not callable(getter) or not callable(creator):
        return None, ADMIN_PROMO_STORAGE_UNAVAILABLE_TEXT

    existing = getter(parsed.code)
    if existing is not None and existing.kind != PromoCodeKind.DISCOUNT:
        return (
            None,
            f"Код {parsed.code} уже существует как {existing.kind.value}. Через discount flow его не меняю.",
        )

    definition = PromoCodeDefinition(
        code=parsed.code,
        kind=PromoCodeKind.DISCOUNT,
        active=True,
        expires_at=existing.expires_at if existing is not None else None,
        max_redemptions=existing.max_redemptions if existing is not None else None,
        per_user_limit=existing.per_user_limit if existing is not None else 1,
        discount_percent=parsed.percent,
        used_count=existing.used_count if existing is not None else 0,
        metadata={"source": "admin_discount_panel"},
    )
    return creator(definition), None


async def _send_admin_discount_promo_list(message: Message) -> None:
    promos, error = _list_admin_discount_promos()
    if error is not None:
        await message.answer(error)
        return
    await message.answer(_format_admin_discount_promo_list(promos))


def _list_admin_discount_promos() -> tuple[list[PromoCodeDefinition], str | None]:
    store = _runtime_store()
    lister = getattr(store, "list_promo_codes", None)
    if store is None or not callable(lister):
        return [], ADMIN_PROMO_STORAGE_UNAVAILABLE_TEXT
    promos = lister(kind=PromoCodeKind.DISCOUNT, active_only=True)
    return [
        promo
        for promo in promos
        if promo.kind == PromoCodeKind.DISCOUNT and promo.is_active_at()
    ], None


def _format_admin_discount_promo_list(promos: list[PromoCodeDefinition]) -> str:
    if not promos:
        return "Активных discount promo codes нет."

    lines = ["Активные discount promo codes:"]
    for promo in sorted(promos, key=lambda item: item.code):
        discount = (
            f"{promo.discount_percent}%"
            if promo.discount_percent is not None
            else f"{promo.discount_amount} minor units"
        )
        limit = str(promo.max_redemptions) if promo.max_redemptions is not None else "без лимита"
        expires_at = f", до {promo.expires_at[:10]}" if promo.expires_at else ""
        lines.append(
            f"{promo.code} — {discount}, использовано {promo.used_count}/{limit}{expires_at}"
        )
    return "\n".join(lines)


def _disable_admin_discount_promo(
    code: str,
) -> tuple[PromoCodeDefinition | None, str | None]:
    store = _runtime_store()
    getter = getattr(store, "get_promo_code", None)
    disabler = getattr(store, "disable_promo_code", None)
    creator = getattr(store, "create_promo_code", None)
    if store is None or not callable(getter):
        return None, ADMIN_PROMO_STORAGE_UNAVAILABLE_TEXT

    existing = getter(code)
    if existing is None:
        return None, f"Discount promo code {code} не найден."
    if existing.kind != PromoCodeKind.DISCOUNT:
        return (
            None,
            f"Код {code} имеет тип {existing.kind.value}. Через discount flow отключаются только discount promo.",
        )

    if callable(disabler):
        disabled = disabler(code, kind=PromoCodeKind.DISCOUNT)
        return disabled, None if disabled is not None else f"Discount promo code {code} не найден."

    if not callable(creator):
        return None, ADMIN_PROMO_STORAGE_UNAVAILABLE_TEXT
    disabled = PromoCodeDefinition(**{**existing.to_dict(), "active": False})
    return creator(disabled), None


async def _admin_access_code_command(message: Message) -> None:
    if not _is_admin_message(message):
        await message.answer("Command is available only to admins.")
        return

    await _send_admin_monthly_access_code(message)


async def _send_admin_monthly_access_code(message: Message) -> None:
    promo = _create_admin_monthly_access_promo_code()
    await message.answer(
        "\n".join(
            [
                "Created promo code:",
                promo.code,
                "Access: 1 month.",
            ]
        )
    )


def _create_admin_monthly_access_promo_code() -> PromoCodeDefinition:
    store = _runtime_store()
    if store is not None:
        return _create_admin_monthly_access_promo_code_in_store(store)
    return _create_admin_monthly_access_promo_code_in_json(PROMO_CODES_STATE_FILE)


def _create_admin_monthly_access_promo_code_in_store(
    store: DietBotStore,
) -> PromoCodeDefinition:
    for _attempt in range(ADMIN_ACCESS_PROMO_CODE_RETRY_LIMIT):
        code = _generate_admin_monthly_access_promo_code()
        if store.get_promo_code(code) is not None:
            continue
        return store.create_promo_code(_admin_monthly_access_promo_definition(code))
    raise RuntimeError("Could not generate a unique monthly access promo code.")


def _create_admin_monthly_access_promo_code_in_json(path: Path) -> PromoCodeDefinition:
    with json_storage_transaction(path):
        promo_codes = load_promo_codes(path)
        for _attempt in range(ADMIN_ACCESS_PROMO_CODE_RETRY_LIMIT):
            code = _generate_admin_monthly_access_promo_code(set(promo_codes))
            if code in promo_codes:
                continue
            definition = _admin_monthly_access_promo_definition(code)
            promo_codes[code] = PromoCodeRecord.from_definition(definition)
            save_promo_codes(path, promo_codes)
            return definition
    raise RuntimeError("Could not generate a unique monthly access promo code.")


def _generate_admin_monthly_access_promo_code(
    existing_codes: set[str] | None = None,
) -> str:
    return generate_promo_codes(1, existing_codes=existing_codes)[0]


def _admin_monthly_access_promo_definition(code: str) -> PromoCodeDefinition:
    return PromoCodeDefinition(
        code=code,
        kind=PromoCodeKind.MONTHLY_ACCESS,
        active=True,
        max_redemptions=1,
        per_user_limit=1,
        monthly_duration_months=1,
        metadata={"source": "admin_access_code_command"},
    )


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
    entitlement = _load_entitlement_for_chat(chat_id)
    grant_test_access(entitlement, now=now)
    _save_entitlement_for_chat(chat_id, entitlement)
    return entitlement


def _revoke_test_access_for_chat(chat_id: int) -> Entitlement:
    entitlement = _load_entitlement_for_chat(chat_id)
    revoke_test_access(entitlement)
    _save_entitlement_for_chat(chat_id, entitlement)
    return entitlement


def _set_test_access_mode(chat_id: int, enabled: bool) -> tuple[bool, Entitlement]:
    entitlement = _load_entitlement_for_chat(chat_id)
    changed = set_test_access_enabled(entitlement, enabled)
    _save_entitlement_for_chat(chat_id, entitlement)
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

    store = _runtime_store()
    entitlement = _load_entitlement_for_chat(chat_id)
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
        _save_entitlement_for_chat(chat_id, entitlement)
        return consumption
    if store is not None:
        return store.consume_generation_attempt(chat_id, ration_kind)
    elif ration_kind == "weekly_pdf":
        consumption = consume_weekly_pdf_attempt(entitlement)
    else:
        consumption = consume_one_day_attempt(entitlement)
    _save_entitlement_for_chat(chat_id, entitlement)
    return consumption


def _refund_generation_attempt(chat_id: int, consumption: AttemptConsumption) -> None:
    store = _runtime_store()
    if store is not None and getattr(consumption, "_postgres_generation_id", None) is not None:
        store.refund_generation_attempt(chat_id, consumption)
        return

    entitlement = _load_entitlement_for_chat(chat_id)
    refund_attempt(entitlement, consumption)
    _save_entitlement_for_chat(chat_id, entitlement)


def _complete_generation_attempt(chat_id: int, consumption: AttemptConsumption) -> None:
    store = _runtime_store()
    if store is not None and getattr(consumption, "_postgres_generation_id", None) is not None:
        store.complete_generation_attempt(chat_id, consumption)


def _entitlement_for_chat(chat_id: int) -> Entitlement:
    entitlement = _load_entitlement_for_chat(chat_id)
    entitlement.expire_if_needed()
    _save_entitlement_for_chat(chat_id, entitlement)
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
        if _public_payments_enabled():
            lines.extend(
                [
                    "",
                    "Можно дождаться следующего обновления подписки или купить разовую попытку.",
                ],
            )
            reply_markup = _paywall_keyboard(preferred=ration_kind)
        else:
            lines.extend(["", PUBLIC_PAYMENTS_PILOT_TEXT])
            reply_markup = _public_payments_disabled_keyboard()
    else:
        if _public_payments_enabled():
            lines.extend(
                [
                    "",
                    "Чтобы продолжить, оформите месячный доступ.",
                ],
            )
        else:
            lines.extend(["", PUBLIC_PAYMENTS_PILOT_TEXT])
        reply_markup = _subscription_payment_keyboard()
    await message.answer(
        "\n".join(lines),
        reply_markup=reply_markup,
    )


def _subscription_payment_keyboard() -> InlineKeyboardMarkup:
    if not _public_payments_enabled():
        return _public_payments_disabled_keyboard()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=PAY_WITH_RU_CARD_TEXT, callback_data=CALLBACK_PAY_RU_CARD)],
            [InlineKeyboardButton(text=PAY_WITH_TELEGRAM_STARS_TEXT, callback_data=CALLBACK_PAY_TELEGRAM_STARS)],
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
        ],
    )


def _paywall_keyboard(*, preferred: str) -> InlineKeyboardMarkup:
    if not _public_payments_enabled():
        return _public_payments_disabled_keyboard()
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
    if not _public_payments_enabled():
        return _public_payments_disabled_keyboard()
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


def _question_keyboard(question, *, selected_index: int | None = None) -> InlineKeyboardMarkup | None:
    if not question or not question.options:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{SELECTED_ANSWER_PREFIX}{option}" if index == selected_index else option,
                    callback_data=f"{CALLBACK_ANSWER_PREFIX}{index}",
                )
            ]
            for index, option in enumerate(question.options)
        ],
    )


async def _mark_questionnaire_answer_selected(message: Message, question, option_index: int) -> None:
    with suppress(TelegramAPIError, AttributeError, TypeError):
        await message.edit_reply_markup(reply_markup=_question_keyboard(question, selected_index=option_index))


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
