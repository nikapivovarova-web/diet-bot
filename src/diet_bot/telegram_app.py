from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, TypeVar

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    ErrorEvent,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    RefundedPayment,
    ReplyKeyboardRemove,
    SuccessfulPayment,
)

from .analytics import (
    DEFAULT_ANALYTICS_ID_SALT,
    DEFAULT_POSTHOG_HOST,
    AnalyticsConfig,
    PreparedAnalyticsEvent,
    prepare_analytics_event,
    pseudonymous_identifier,
    record_event_in_store,
    send_event_to_posthog,
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
from .json_storage import json_storage_transaction
from .presentation import (
    format_calculation_summary,
    format_daily_totals,
    format_meal_card,
    format_plan_messages,
    format_week_shopping_list,
)
from .pdf_renderer import build_week_plan_pdf
from .payments import (
    PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
    PAYMENT_EVENT_CHARGEBACK,
    PAYMENT_EVENT_STATUS_DUPLICATE,
    PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
    PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE,
    PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
    PAYMENT_EVENT_STATUS_PROCESSED,
    PAYMENT_EVENT_TRANSITIONAL_STATUSES,
    PAYMENT_EVENT_REFUND,
    PAYMENT_EVENT_SUCCESSFUL,
    PaymentEvent,
    PaymentEventApplication,
    PaymentOrder,
    PaymentProduct,
    ProcessedPaymentCharge,
    ProcessedPaymentChargeState,
    add_processed_payment_charge,
    decode_payment_order_payload,
    find_payment_event,
    find_successful_payment_event,
    load_processed_payment_charge_state,
    load_payment_event_state,
    load_payment_order_state,
    processed_payment_charge_exists,
    PROCESSED_PAYMENT_CHARGE_LEGACY_PROVIDER,
    record_orphan_payment as record_file_orphan_payment,
    record_payment_event,
    remember_payment_order,
    save_processed_payment_charge_state,
    save_payment_order_state,
    terminal_payment_adjustment_exists,
)
from .postgres_store import PostgresDietBotStore
from .profile_normalization import normalize_stored_condition_codes, normalize_stored_free_text_items
from .promo_codes import PromoCodeActivation, activate_promo_code, promo_code_lookup_key
from .questionnaire import QuestionnaireSession, start_session
from .runtime_config import (
    is_production_environment,
    parse_support_chat_id,
    validate_database_url,
    validate_production_runtime_config,
)
from .safety import evaluate_safety
from .subscriptions import (
    MONTHLY_ONE_DAY_LIMIT,
    MONTHLY_WEEKLY_PDF_LIMIT,
    SUBSCRIPTION_PERIOD_SECONDS,
    AttemptConsumption,
    Entitlement,
    PaymentGrant,
    PaymentApplication,
    RationKind,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_payment_reversal,
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
from .state_cache import BoundedTTLDict, BoundedTTLSet
from .telegram_rate_limit import IncomingThrottle, TelegramRateLimiter, ThrottleDecision
from .validation import validate_plan


logger = logging.getLogger(__name__)
T = TypeVar("T")
ButtonStyle = Literal["primary", "success", "danger"]
GENERATION_HEARTBEAT_INTERVAL_SECONDS = 60
POLLING_HEARTBEAT_FILE_ENV = "DIET_BOT_POLLING_HEARTBEAT_FILE"
POLLING_HEARTBEAT_INTERVAL_ENV = "DIET_BOT_POLLING_HEARTBEAT_INTERVAL_SECONDS"
DEFAULT_POLLING_HEARTBEAT_FILE = "/tmp/diet_bot_polling_heartbeat.json"
DEFAULT_POLLING_HEARTBEAT_INTERVAL_SECONDS = 15
CHAT_STATE_CACHE_MAX_SIZE = 100_000
CHAT_STATE_CACHE_TTL_SECONDS = 24 * 60 * 60
GENERATION_LOCK_CACHE_TTL_SECONDS = 30 * 60
SESSION_BY_CHAT_ID: BoundedTTLDict[int, QuestionnaireSession] = BoundedTTLDict(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=CHAT_STATE_CACHE_TTL_SECONDS,
)
TRIAL_CHAT_IDS: BoundedTTLSet[int] = BoundedTTLSet(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=CHAT_STATE_CACHE_TTL_SECONDS,
)
PROFILE_BY_CHAT_ID: BoundedTTLDict[int, UserProfile] = BoundedTTLDict(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=CHAT_STATE_CACHE_TTL_SECONDS,
)
PLAN_COUNT_BY_CHAT_ID: BoundedTTLDict[int, int] = BoundedTTLDict(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=CHAT_STATE_CACHE_TTL_SECONDS,
)
PLAN_SEED_OFFSET_BY_CHAT_ID: BoundedTTLDict[int, int] = BoundedTTLDict(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=CHAT_STATE_CACHE_TTL_SECONDS,
)
RECENT_RECIPE_IDS_BY_CHAT_ID: BoundedTTLDict[int, list[str]] = BoundedTTLDict(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=CHAT_STATE_CACHE_TTL_SECONDS,
)
RECENT_RECIPE_KEYS_BY_CHAT_ID: BoundedTTLDict[int, list[str]] = BoundedTTLDict(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=CHAT_STATE_CACHE_TTL_SECONDS,
)
SUPPORT_REQUEST_CHAT_IDS: BoundedTTLSet[int] = BoundedTTLSet(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=CHAT_STATE_CACHE_TTL_SECONDS,
)


@dataclass(frozen=True)
class GenerationDeliveryResult:
    sent: bool
    telegram_message_id: int | None = None

    def __bool__(self) -> bool:
        return self.sent


PROMO_CODE_REQUEST_CHAT_IDS: BoundedTTLSet[int] = BoundedTTLSet(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=CHAT_STATE_CACHE_TTL_SECONDS,
)
GENERATION_LOCKS_BY_CHAT_ID: BoundedTTLDict[int, asyncio.Lock] = BoundedTTLDict(
    max_size=CHAT_STATE_CACHE_MAX_SIZE,
    ttl_seconds=GENERATION_LOCK_CACHE_TTL_SECONDS,
    evictable=lambda lock: not lock.locked(),
)
TELEGRAM_RATE_LIMITER = TelegramRateLimiter()
INCOMING_THROTTLE = IncomingThrottle()
EFFECTIVE_INTERACTION_USER: ContextVar[Any | None] = ContextVar("effective_interaction_user", default=None)
router = Router()


def prune_chat_state_caches() -> None:
    for cache in (
        SESSION_BY_CHAT_ID,
        TRIAL_CHAT_IDS,
        PROFILE_BY_CHAT_ID,
        PLAN_COUNT_BY_CHAT_ID,
        PLAN_SEED_OFFSET_BY_CHAT_ID,
        RECENT_RECIPE_IDS_BY_CHAT_ID,
        RECENT_RECIPE_KEYS_BY_CHAT_ID,
        SUPPORT_REQUEST_CHAT_IDS,
        PROMO_CODE_REQUEST_CHAT_IDS,
        GENERATION_LOCKS_BY_CHAT_ID,
    ):
        cache.prune()
    TELEGRAM_RATE_LIMITER.prune()
    INCOMING_THROTTLE.prune()


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


def _polling_heartbeat_path() -> Path:
    return Path(os.getenv(POLLING_HEARTBEAT_FILE_ENV, DEFAULT_POLLING_HEARTBEAT_FILE))


def _polling_heartbeat_interval_seconds() -> int:
    return max(
        1,
        _parse_optional_int(os.getenv(POLLING_HEARTBEAT_INTERVAL_ENV))
        or DEFAULT_POLLING_HEARTBEAT_INTERVAL_SECONDS,
    )


def _write_polling_heartbeat(state: str = "polling") -> None:
    path = _polling_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "state": state,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _remove_polling_heartbeat() -> None:
    with suppress(Exception):
        _polling_heartbeat_path().unlink()


async def _polling_heartbeat_loop() -> None:
    interval_seconds = _polling_heartbeat_interval_seconds()
    while True:
        _write_polling_heartbeat("polling")
        await asyncio.sleep(interval_seconds)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_env_command_name(raw: str | None) -> str:
    command = (raw or "").strip().lower().lstrip("/")
    command = command.split("@", 1)[0]
    if re.fullmatch(r"[a-z0-9_]{1,32}", command):
        return command
    return ""


def _parse_support_chat_id(raw: str | None) -> int | None:
    return parse_support_chat_id(raw)


def _parse_optional_datetime(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def telegram_api_call_with_retry(
    operation_name: str,
    call: Callable[[], Awaitable[T]],
    *,
    chat_id: object | None = None,
    attempts: int = 3,
    base_delay: float = 0.7,
    max_delay: float | None = None,
    rate_limit: bool = True,
) -> T:
    return await TELEGRAM_RATE_LIMITER.run(
        operation_name,
        call,
        chat_id=chat_id,
        attempts=attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        rate_limit=rate_limit,
    )


def _chat_id_from_message(message: Message) -> int | None:
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    return chat_id if isinstance(chat_id, int) else None


def _chat_id_from_callback(callback: CallbackQuery) -> int | None:
    message = getattr(callback, "message", None)
    if isinstance(message, Message):
        return _chat_id_from_message(message)
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    return chat_id if isinstance(chat_id, int) else None


async def safe_answer(message: Message, text: str, **kwargs: Any) -> Message:
    return await telegram_api_call_with_retry(
        "send_message",
        lambda: message.answer(text, **kwargs),
        chat_id=_chat_id_from_message(message),
    )


async def safe_answer_photo(message: Message, **kwargs: Any) -> Message:
    return await telegram_api_call_with_retry(
        "send_photo",
        lambda: message.answer_photo(**kwargs),
        chat_id=_chat_id_from_message(message),
    )


async def safe_answer_document(message: Message, **kwargs: Any) -> Message:
    return await telegram_api_call_with_retry(
        "send_document",
        lambda: message.answer_document(**kwargs),
        chat_id=_chat_id_from_message(message),
    )


async def safe_edit_reply_markup(message: Message, **kwargs: Any) -> Message:
    return await telegram_api_call_with_retry(
        "edit_message_reply_markup",
        lambda: message.edit_reply_markup(**kwargs),
        chat_id=_chat_id_from_message(message),
    )


async def safe_edit_text(message: Message, text: str, **kwargs: Any) -> Message:
    return await telegram_api_call_with_retry(
        "edit_message_text",
        lambda: message.edit_text(text, **kwargs),
        chat_id=_chat_id_from_message(message),
    )


async def safe_callback_answer(callback: CallbackQuery, text: str | None = None, **kwargs: Any) -> None:
    await telegram_api_call_with_retry(
        "answer_callback_query",
        lambda: callback.answer(text, **kwargs),
        chat_id=_chat_id_from_callback(callback),
    )


async def safe_pre_checkout_answer(pre_checkout_query: PreCheckoutQuery, **kwargs: Any) -> None:
    await telegram_api_call_with_retry(
        "answer_pre_checkout_query",
        lambda: pre_checkout_query.answer(**kwargs),
    )


async def _run_storage_io(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await asyncio.to_thread(func, *args, **kwargs)


POSTHOG_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="diet-bot-posthog")


def _log_identifier(value: object | None, *, prefix: str) -> str:
    salt = os.getenv("DIET_BOT_ANALYTICS_ID_SALT", "").strip() or DEFAULT_ANALYTICS_ID_SALT
    return pseudonymous_identifier(value, salt=salt, prefix=prefix)


def _track_event(
    user_id: int | None,
    event_name: str,
    properties: dict[str, object] | None = None,
) -> tuple[AnalyticsConfig, PreparedAnalyticsEvent] | None:
    config = AnalyticsConfig.from_env()
    if not config.enabled:
        return None
    prepared_event = prepare_analytics_event(event_name, properties)
    if prepared_event is None:
        return None

    try:
        store = _postgres_store()
    except Exception:
        logger.exception("Could not prepare analytics store.", extra={"event_name": prepared_event.name})
    else:
        if store is not None:
            record_event_in_store(store, user_id, prepared_event)
    return config, prepared_event


async def _track_event_async(
    user_id: int | None,
    event_name: str,
    properties: dict[str, object] | None = None,
) -> None:
    result = await _run_storage_io(_track_event, user_id, event_name, properties)
    if result is None:
        return
    config, prepared_event = result
    if config.posthog_api_key:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(POSTHOG_EXECUTOR, send_event_to_posthog, config, user_id, prepared_event)


async def safe_bot_send_message(bot: Bot, *, chat_id: int, text: str, **kwargs: Any) -> Message:
    return await telegram_api_call_with_retry(
        "send_message",
        lambda: bot.send_message(chat_id=chat_id, text=text, **kwargs),
        chat_id=chat_id,
    )


async def safe_send_chat_action(bot: Bot, *, chat_id: int, action: str) -> None:
    await telegram_api_call_with_retry(
        "send_chat_action",
        lambda: bot.send_chat_action(chat_id=chat_id, action=action),
        chat_id=chat_id,
    )


async def safe_create_invoice_link(bot: Bot, *, chat_id: int | None = None, **kwargs: Any) -> str:
    return await telegram_api_call_with_retry(
        "create_invoice_link",
        lambda: bot.create_invoice_link(**kwargs),
        chat_id=chat_id,
    )


def _is_support_chat(chat_id: int) -> bool:
    return SUPPORT_CHAT_ID is not None and chat_id == SUPPORT_CHAT_ID


PRIVATE_CHAT_REQUIRED_TEXT = "Для анкеты, рациона и подписки откройте бота в личных сообщениях."
PRIVATE_CHAT_CALLBACK_TEXT = "Откройте бота в личных сообщениях"
GENERIC_USER_ERROR_TEXT = "Не смог обработать запрос. Попробуйте ещё раз через минуту или напишите в поддержку."
CALLBACK_THROTTLE_SECONDS = 0.7
COMMAND_THROTTLE_SECONDS = 2.5
PLAN_THROTTLE_SECONDS = 7.0
SUPPORT_THROTTLE_SECONDS = 60.0
CALLBACK_THROTTLED_TEXT = "Секунду, уже обрабатываю."
COMMAND_THROTTLED_TEXT = "Подождите пару секунд и попробуйте снова."
PLAN_THROTTLED_TEXT = "Я уже обрабатываю предыдущий запрос. Попробуйте еще раз через несколько секунд."
SUPPORT_THROTTLED_TEXT = "Недавно уже было сообщение в поддержку. Попробуйте отправить следующее через минуту."


def is_private_chat(message: Message) -> bool:
    chat_type = getattr(message.chat, "type", None)
    return chat_type == "private" or getattr(chat_type, "value", None) == "private"


async def ensure_private_chat(message: Message) -> bool:
    if is_private_chat(message):
        return True
    await safe_answer(message, PRIVATE_CHAT_REQUIRED_TEXT)
    return False


def _can_show_myid(message: Message) -> bool:
    return is_private_chat(message) or _is_support_chat(message.chat.id) or _is_admin_message(message)


def _message_owner_id(message: Message) -> int:
    return _message_user_id(message) or message.chat.id


def _callback_user_id(callback: CallbackQuery) -> int | None:
    user = getattr(callback, "from_user", None)
    user_id = getattr(user, "id", None)
    return user_id if isinstance(user_id, int) else None


async def _check_incoming_throttle(action: str, owner_id: int, interval: float) -> ThrottleDecision:
    return await INCOMING_THROTTLE.check(action, owner_id, interval)


async def _throttle_message_action(message: Message, action: str, interval: float, text: str) -> bool:
    decision = await _check_incoming_throttle(action, _message_owner_id(message), interval)
    if decision.allowed:
        return False
    await safe_answer(message, text)
    return True


async def _throttle_callback_action(callback: CallbackQuery, owner_id: int) -> bool:
    decision = await _check_incoming_throttle("callback", owner_id, CALLBACK_THROTTLE_SECONDS)
    if decision.allowed:
        return False
    await safe_callback_answer(callback, CALLBACK_THROTTLED_TEXT)
    return True

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
    "При оплате картой/SberPay YooKassa и Telegram могут запросить email для фискального чека.\n\n"
    "Сервис носит информационный характер и не является медицинской консультацией."
)
PAY_WITH_TELEGRAM_STARS_TEXT = f"⭐ Оплатить подписку - {SUBSCRIPTION_STARS_AMOUNT} Stars"
PAY_WITH_RU_CARD_TEXT = f"💳 Оплатить картой / SberPay - {SUBSCRIPTION_PRICE_RUB} ₽"
BUY_EXTRA_ONE_DAY_TEXT = f"⭐ Купить 1 дневной рацион - {EXTRA_ONE_DAY_STARS_AMOUNT} Stars"
BUY_EXTRA_WEEKLY_PDF_TEXT = f"⭐ Купить 1 недельный PDF - {EXTRA_WEEKLY_PDF_STARS_AMOUNT} Stars"
BUY_EXTRA_ONE_DAY_RU_CARD_TEXT = f"🥗 Купить 1 дневной рацион - {EXTRA_ONE_DAY_PRICE_RUB} ₽"
BUY_EXTRA_WEEKLY_PDF_RU_CARD_TEXT = f"📄 Купить недельный PDF - {EXTRA_WEEKLY_PDF_PRICE_RUB} ₽"
PRIVACY_POLICY_TEXT = "Политика конфиденциальности"
CONSENT_ACCEPT_TEXT = "Согласен, начать анкету"
CONSENT_REQUEST_TEXT = (
    "Перед анкетой нужно ваше согласие на обработку данных.\n\n"
    "FoodBalance использует ответы анкеты: возраст, рост, вес, цель, активность, "
    "пищевые ограничения, аллергии, непереносимости, заболевания/состояния и исключенные продукты. "
    "Эти данные нужны, чтобы рассчитать рацион и учесть ограничения.\n\n"
    "При оплате картой/SberPay YooKassa и Telegram могут запросить email для фискального чека.\n\n"
    f"Нажимая «{CONSENT_ACCEPT_TEXT}», вы подтверждаете согласие на обработку этих данных "
    "и понимаете, что сервис не заменяет медицинскую консультацию."
)
PRIVACY_POLICY_MESSAGE = (
    "Политика конфиденциальности FoodBalance\n\n"
    "Мы обрабатываем данные, которые вы отправляете боту: Telegram ID, username, first_name/display name, ответы анкеты "
    "(возраст, рост, вес, цель, активность, пищевые ограничения, аллергии, непереносимости, "
    "заболевания/состояния и исключенные продукты), а также технические сведения о доступе, оплате и обращениях в поддержку.\n\n"
    "Эти данные используются для расчета рационов, учета ограничений, обработки подписки, поддержки "
    "и предотвращения повторной обработки платежей. При обращении в поддержку мы передаем администратору текст обращения "
    "и служебный support metadata: Telegram metadata, статус доступа, остаток лимитов, наличие анкеты и способ оплаты без банковских данных.\n\n"
    "При оплате картой/SberPay YooKassa и Telegram могут запросить email для фискального чека. "
    "Бот хранит сведения о заказе и доступе, но не получает данные банковской карты.\n\n"
    "Данные не используются для рекламных рассылок. Рационы носят информационный характер "
    "и не заменяют консультацию врача."
)
FEATURES_TEXT = "❓ Что умеет бот / FAQ"
FEATURES_MESSAGE = (
    "Что умеет FoodBalance / FAQ\n\n"
    "FoodBalance собирает персональные рационы по короткой анкете: учитывает цель, режим, "
    "предпочтения, ограничения и исключенные продукты. В рационе есть понятные порции, КБЖУ, "
    "витамины, минералы, рецепты и список покупок.\n\n"
    "Пробный рацион\n"
    "• можно бесплатно получить 1 рацион на 1 день\n"
    "• это быстрый способ посмотреть, как бот подбирает блюда и считает показатели\n"
    "• после пробного рациона для продолжения нужен месячный доступ\n\n"
    "Подписка и лимиты\n"
    f"• месячный доступ стоит {SUBSCRIPTION_PRICE_RUB} ₽ или {SUBSCRIPTION_STARS_AMOUNT} Stars\n"
    f"• в месяц входит {MONTHLY_ONE_DAY_LIMIT} рационов на 1 день и "
    f"{MONTHLY_WEEKLY_PDF_LIMIT} недельных PDF-рациона\n"
    "• остаток лимитов бот показывает в меню и после генерации\n"
    "• если лимит закончился, можно дождаться обновления подписки или купить разовую попытку\n\n"
    "PDF на неделю\n"
    "• недельный PDF включает меню на 7 дней, рецепты и список покупок\n"
    "• сборка PDF может занять до минуты\n"
    "• PDF доступен в подписке или как дополнительная разовая покупка\n\n"
    "Оплата\n"
    "• оплатить можно картой/SberPay или Telegram Stars\n"
    "• при оплате картой YooKassa и Telegram могут запросить email для фискального чека\n"
    "• после успешной оплаты доступ включается автоматически\n\n"
    "Промокоды\n"
    "• промокод вводится одной строкой через кнопку «Ввести промокод»\n"
    "• один промокод можно активировать только один раз\n\n"
    "Поддержка\n"
    "• если что-то не сработало, нажмите «Техподдержка» и опишите вопрос одним сообщением\n"
    "• по оплате укажите способ оплаты: карта/SberPay или Telegram Stars\n\n"
    "Команды: /start - меню, /plan - анкета, /help - справка, /cancel - сброс анкеты.\n\n"
    "Сервис носит информационный характер и не является медицинской консультацией."
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
WEEK_PDF_FALLBACK_TEXT = "PDF не удалось собрать. Отправляю рацион текстом."
# Telegram Bot API sendDocument limit: 50 MB.
# Keep 1 MiB headroom for PDF and transport overhead:
# https://core.telegram.org/bots/api#senddocument
TELEGRAM_DOCUMENT_MAX_BYTES = 49 * 1024 * 1024
VALIDATION_FAILED_TEXT = (
    "Не смог безопасно собрать рацион под эти ограничения. "
    "Попытка не списана, попробуйте изменить анкету или исключенные продукты."
)
GENERATION_ALREADY_RUNNING_TEXT = "Уже собираю рацион. Дождитесь результата, повторно запускать не нужно."
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
DEFAULT_PAYMENT_ORDERS_STATE_FILE = DEFAULT_STATE_FILE.with_name("payment_orders.json")
PAYMENT_ORDERS_STATE_FILE = Path(os.getenv("DIET_BOT_PAYMENT_ORDERS_STATE_FILE", str(DEFAULT_PAYMENT_ORDERS_STATE_FILE)))
_PAYMENT_EVENTS_STATE_FILE_ENV = os.getenv("DIET_BOT_PAYMENT_EVENTS_STATE_FILE", "").strip()
PAYMENT_EVENTS_STATE_FILE: Path | None = (
    Path(_PAYMENT_EVENTS_STATE_FILE_ENV) if _PAYMENT_EVENTS_STATE_FILE_ENV else None
)
DIET_BOT_DATABASE_URL = os.getenv("DIET_BOT_DATABASE_URL", "").strip()
DIET_BOT_ENV = os.getenv(
    "DIET_BOT_ENV",
    os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")),
).strip().lower()
ALLOW_JSON_STORAGE = _env_bool("DIET_BOT_ALLOW_JSON_STORAGE", False)
GENERATION_CLEANUP_INTERVAL_SECONDS = max(
    60,
    _parse_optional_int(os.getenv("DIET_BOT_GENERATION_CLEANUP_INTERVAL_SECONDS")) or 300,
)
ADMIN_USER_IDS = _parse_id_set(os.getenv("DIET_BOT_ADMIN_USER_IDS")) | _parse_id_set(os.getenv("DIET_BOT_ADMIN_IDS"))
TESTER_CHAT_IDS = _parse_id_set(os.getenv("DIET_BOT_TESTER_CHAT_IDS"))
TEST_ACCESS_COMMAND = _parse_env_command_name(os.getenv("DIET_BOT_TEST_ACCESS_COMMAND"))
TEST_ACCESS_COMMAND_DISABLED_TEXT = "Тестовая команда отключена."
TELEGRAM_PROVIDER_TOKEN = os.getenv("TELEGRAM_PROVIDER_TOKEN", "").strip()
POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "").strip()
POSTHOG_HOST = os.getenv("POSTHOG_HOST", DEFAULT_POSTHOG_HOST).strip() or DEFAULT_POSTHOG_HOST
SUPPORT_CHAT_ID_RAW = os.getenv("DIET_BOT_SUPPORT_CHAT_ID")
SUPPORT_CHAT_ID = _parse_support_chat_id(SUPPORT_CHAT_ID_RAW)
PRIVACY_POLICY_URL = os.getenv("DIET_BOT_PRIVACY_POLICY_URL", "").strip()
ALLOW_LEGACY_PAYMENT_PAYLOADS = _env_bool("DIET_BOT_ALLOW_LEGACY_PAYMENT_PAYLOADS", False)
ALLOW_LEGACY_PAYLOADS_UNTIL = _parse_optional_datetime(
    os.getenv("DIET_BOT_ALLOW_LEGACY_PAYLOADS_UNTIL")
)
_POSTGRES_STORE: PostgresDietBotStore | None = None
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
CALLBACK_CONSENT_REGULAR = "diet:consent"
CALLBACK_CONSENT_TRIAL = "diet:consent_trial"
CALLBACK_FEATURES = "diet:features"
CALLBACK_PRIVACY_POLICY = "diet:privacy"
CALLBACK_PRIVACY_POLICY_REGULAR = "diet:privacy_regular"
CALLBACK_PRIVACY_POLICY_TRIAL = "diet:privacy_trial"
CALLBACK_PROMO_CODE = "diet:promo_code"
CALLBACK_SUPPORT = "diet:support"
CALLBACK_ONE_DAY_PLAN = "diet:one_day"
CALLBACK_WEEK_PLAN_PDF = "diet:week_pdf"
CALLBACK_ANSWER_PREFIX = "diet:answer:"
ANSWER_CALLBACK_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9]{6,10}$")
ANSWER_CALLBACK_QUESTION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ANSWER_CALLBACK_INDEX_RE = re.compile(r"^[0-9]+$")
STALE_ANSWER_CALLBACK_TEXT = "Эта кнопка устарела. Отвечайте на последний вопрос."
BUTTON_STYLE_PRIMARY: ButtonStyle = "primary"
BUTTON_STYLE_SUCCESS: ButtonStyle = "success"
BUTTON_STYLE_DANGER: ButtonStyle = "danger"
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
PAYMENT_INVOICE_CREATION_FAILED_TEXT = "Не удалось создать счёт для оплаты. Попробуйте позже."
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
    BotCommand(command="help", description="Справка и FAQ"),
    BotCommand(command="support", description="Написать в поддержку"),
    BotCommand(command="privacy", description="Политика конфиденциальности"),
    BotCommand(command="cancel", description="Сбросить активную анкету"),
)


@router.message(Command("start"))
async def start(message: Message) -> None:
    if _is_support_chat(message.chat.id):
        return
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    if await _throttle_message_action(message, "command", COMMAND_THROTTLE_SECONDS, COMMAND_THROTTLED_TEXT):
        return
    await _track_event_async(owner_id, "bot_started", {"source": "command"})
    SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
    await _send_welcome_photo(message)
    if await _run_storage_io(_has_active_paid_access, owner_id):
        cabinet_text = await _run_storage_io(_subscriber_cabinet_text, owner_id)
        reply_markup = await _run_storage_io(_subscriber_cabinet_keyboard, owner_id)
        await safe_answer(message, 
            cabinet_text,
            reply_markup=reply_markup,
        )
        return
    if await _run_storage_io(_profile_for_chat, owner_id) is not None:
        reply_markup = await _run_storage_io(_main_menu_keyboard, owner_id)
        await safe_answer(message, 
            "Анкета уже сохранена. Можно сразу составить рацион или изменить анкету.",
            reply_markup=reply_markup,
        )
        return
    await safe_answer(message, WELCOME_TEXT, reply_markup=_start_keyboard())


@router.message(Command("plan"))
async def plan(message: Message) -> None:
    if _is_support_chat(message.chat.id):
        return
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    if await _throttle_message_action(message, "plan", PLAN_THROTTLE_SECONDS, PLAN_THROTTLED_TEXT):
        return
    SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
    profile = await _run_storage_io(_profile_for_chat, owner_id)
    if profile is not None:
        await _send_calculation_options(message, profile)
        return
    await _request_questionnaire_consent(message)


@router.message(Command("cancel"))
async def cancel(message: Message) -> None:
    if _is_support_chat(message.chat.id):
        return
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    if await _throttle_message_action(message, "command", COMMAND_THROTTLE_SECONDS, COMMAND_THROTTLED_TEXT):
        return
    SESSION_BY_CHAT_ID.pop(owner_id, None)
    TRIAL_CHAT_IDS.discard(owner_id)
    SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
    reply_markup = await _run_storage_io(_main_menu_keyboard, owner_id)
    await safe_answer(message, "Анкета сброшена ✅", reply_markup=reply_markup)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    if _is_support_chat(message.chat.id):
        return
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    if await _throttle_message_action(message, "command", COMMAND_THROTTLE_SECONDS, COMMAND_THROTTLED_TEXT):
        return
    SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
    await _send_help_message(message, owner_id)


@router.message(Command("support"))
async def support_command(message: Message) -> None:
    if _is_support_chat(message.chat.id):
        return
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    if await _throttle_message_action(message, "command", COMMAND_THROTTLE_SECONDS, COMMAND_THROTTLED_TEXT):
        return
    await _start_support_request(message)


@router.message(Command("privacy"))
async def privacy_command(message: Message) -> None:
    if _is_support_chat(message.chat.id):
        return
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    if await _throttle_message_action(message, "command", COMMAND_THROTTLE_SECONDS, COMMAND_THROTTLED_TEXT):
        return
    SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
    await _send_privacy_policy(message, owner_id)


@router.message(Command("myid"))
async def myid(message: Message) -> None:
    if not _can_show_myid(message):
        await safe_answer(message, PRIVATE_CHAT_REQUIRED_TEXT)
        return
    await _run_storage_io(_remember_user_from_message, message)
    if await _throttle_message_action(message, "command", COMMAND_THROTTLE_SECONDS, COMMAND_THROTTLED_TEXT):
        return
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
    await safe_answer(message, "\n".join(lines))


def _test_access_command_token() -> str:
    return f"/{TEST_ACCESS_COMMAND}" if TEST_ACCESS_COMMAND else "/<DIET_BOT_TEST_ACCESS_COMMAND>"


def _is_test_access_command(command: str | None) -> bool:
    return bool(TEST_ACCESS_COMMAND and command == TEST_ACCESS_COMMAND)


async def secret_access_command(message: Message) -> None:
    if not _is_test_access_command(_normalize_command_text(message.text or "")):
        await safe_answer(message, TEST_ACCESS_COMMAND_DISABLED_TEXT)
        return
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    if await _throttle_message_action(message, "command", COMMAND_THROTTLE_SECONDS, COMMAND_THROTTLED_TEXT):
        return
    action, target_chat_id = _parse_test_access_command(message.text or "")
    if target_chat_id is not None:
        if not _is_admin_message(message):
            await safe_answer(message, "Команда для выдачи доступа доступна только администратору.")
            return
        if action == "revoke":
            await _run_storage_io(_revoke_test_access_for_chat, target_chat_id)
            await safe_answer(message, f"Тестовый доступ отключен для chat_id {target_chat_id}.")
            return
        entitlement = await _run_storage_io(_grant_test_access_to_chat, target_chat_id)
        test_access_end = entitlement.test_access_end_datetime()
        until_text = f" до {test_access_end:%d.%m.%Y}" if test_access_end else ""
        await safe_answer(message, 
            f"Тестовый доступ выдан для chat_id {target_chat_id}{until_text}.",
        )
        return

    if action == "enable":
        enabled, _ = await _run_storage_io(_set_test_access_mode, owner_id, True)
        if enabled:
            await safe_answer(message, "Тестовый платный режим включен.")
        else:
            await safe_answer(message, "Тестовый доступ для вашего chat_id не выдан или уже истек.")
        return

    if action == "disable":
        disabled, _ = await _run_storage_io(_set_test_access_mode, owner_id, False)
        if disabled:
            await safe_answer(message, "Тестовый режим выключен. Сейчас вы видите бесплатный сценарий.")
        else:
            await safe_answer(message, "Тестовый доступ для вашего chat_id не выдан или уже истек.")
        return

    if action == "help":
        command = _test_access_command_token()
        await safe_answer(message, 
            "Форматы:\n"
            f"{command} 123456789 - выдать тестовый доступ\n"
            f"{command} off 123456789 - забрать тестовый доступ\n"
            f"{command} on - включить платный тестовый режим\n"
            f"{command} off - выключить и посмотреть бесплатную цепочку",
        )
        return

    status_text = await _run_storage_io(_format_test_access_command_status, owner_id)
    await safe_answer(message, status_text)


@dataclass(frozen=True)
class AdminPaymentEventCommand:
    event_type: str
    provider: str
    charge_id: str
    user_id: int | None = None
    action: str = "apply"
    lookup_id: str | None = None


@router.message(Command("payment_event"))
async def payment_event_reconciliation_command(message: Message) -> None:
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    if not _is_admin_message(message):
        await safe_answer(message, "payment_event command is available only to admins.")
        return

    command = _parse_payment_event_reconciliation_command(message.text or "")
    if command is None:
        await safe_answer(message, _payment_event_reconciliation_usage_text())
        return

    if command.action == "reconcile":
        admin_id = _message_user_id(message)
        result = await _run_storage_io(
            _reconcile_admin_payment_event,
            command.lookup_id or command.charge_id,
            admin_id=admin_id,
            admin_chat_id=message.chat.id,
        )
        await safe_answer(message, _admin_payment_reconcile_result_text(command.lookup_id or command.charge_id, result))
        return

    resolved_user_id = await _run_storage_io(
        _resolve_successful_payment_user_id,
        provider=command.provider,
        charge_id=command.charge_id,
    )
    if command.user_id is not None and resolved_user_id is not None and command.user_id != resolved_user_id:
        await safe_answer(
            message,
            "ignored: user_id_mismatch\n"
            f"event_type: {command.event_type}\n"
            f"provider: {command.provider}\n"
            f"charge_id: {command.charge_id}\n"
            f"provided_user_id: {command.user_id}\n"
            f"payment_user_id: {resolved_user_id}",
        )
        return

    target_user_id = command.user_id or resolved_user_id
    if target_user_id is None:
        await safe_answer(
            message,
            "ignored: original_payment_not_found\n"
            f"event_type: {command.event_type}\n"
            f"provider: {command.provider}\n"
            f"charge_id: {command.charge_id}\n"
            "Pass user_id explicitly only after confirming the original payment exists.",
        )
        return

    admin_id = _message_user_id(message)
    result = await _run_storage_io(
        _apply_admin_payment_event,
        target_user_id,
        command,
        admin_id=admin_id,
        admin_chat_id=message.chat.id,
    )
    await safe_answer(message, _admin_payment_event_result_text(command, target_user_id, result))


@dataclass(frozen=True)
class AnswerCallbackPayload:
    session_id: str
    question_key: str
    option_index: int


def _parse_answer_callback_data(data: str) -> AnswerCallbackPayload | None:
    if not data.startswith(CALLBACK_ANSWER_PREFIX):
        return None

    parts = data.removeprefix(CALLBACK_ANSWER_PREFIX).split(":")
    if len(parts) != 3:
        return None

    session_id, question_key, option_index_raw = parts
    if not ANSWER_CALLBACK_SESSION_ID_RE.fullmatch(session_id):
        return None
    if not ANSWER_CALLBACK_QUESTION_KEY_RE.fullmatch(question_key):
        return None
    if not ANSWER_CALLBACK_INDEX_RE.fullmatch(option_index_raw):
        return None

    return AnswerCallbackPayload(
        session_id=session_id,
        question_key=question_key,
        option_index=int(option_index_raw),
    )


async def _remove_inline_keyboard(message: Message) -> None:
    with suppress(TelegramAPIError):
        await safe_edit_reply_markup(message, reply_markup=None)


async def _answer_stale_question_callback(callback: CallbackQuery, message: Message) -> None:
    await safe_callback_answer(callback, STALE_ANSWER_CALLBACK_TEXT)
    await _remove_inline_keyboard(message)


@router.callback_query()
async def handle_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""
    message = callback.message
    if not isinstance(message, Message):
        await safe_callback_answer(callback, PRIVATE_CHAT_CALLBACK_TEXT, show_alert=True)
        return
    if not is_private_chat(message):
        await safe_callback_answer(callback, PRIVATE_CHAT_CALLBACK_TEXT, show_alert=True)
        return
    callback_user_id = _callback_user_id(callback)
    if callback_user_id is None or callback_user_id != message.chat.id:
        await safe_callback_answer(callback, PRIVATE_CHAT_CALLBACK_TEXT, show_alert=True)
        return
    interaction_user = getattr(callback, "from_user", None)
    token = EFFECTIVE_INTERACTION_USER.set(interaction_user) if interaction_user is not None else None
    try:
        await _handle_callback_with_effective_user(callback, message, data)
    finally:
        if token is not None:
            EFFECTIVE_INTERACTION_USER.reset(token)


async def _handle_callback_with_effective_user(callback: CallbackQuery, message: Message, data: str) -> None:
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)

    if _is_support_chat(message.chat.id):
        await safe_callback_answer(callback)
        return

    if await _throttle_callback_action(callback, owner_id):
        return

    if data != CALLBACK_SUPPORT:
        SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    if data != CALLBACK_PROMO_CODE:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)

    if data == CALLBACK_SUPPORT:
        await safe_callback_answer(callback)
        await _start_support_request(message)
        return

    if data == CALLBACK_START:
        await safe_callback_answer(callback)
        await _request_questionnaire_consent(message, is_trial=True)
        return

    if data == CALLBACK_NEW:
        await safe_callback_answer(callback)
        await _request_questionnaire_consent(message)
        return

    if data == CALLBACK_CONSENT_TRIAL:
        await safe_callback_answer(callback)
        await _remove_inline_keyboard(message)
        await _start_questionnaire(message, is_trial=True)
        return

    if data == CALLBACK_CONSENT_REGULAR:
        await safe_callback_answer(callback)
        await _remove_inline_keyboard(message)
        await _start_questionnaire(message)
        return

    if data == CALLBACK_SUBSCRIBE:
        await safe_callback_answer(callback)
        await _send_subscription_payment_options(message)
        return

    if data == CALLBACK_PAY_TELEGRAM_STARS:
        await safe_callback_answer(callback)
        if await _send_active_subscription_notice_if_needed(message):
            return
        await _send_stars_invoice_link(message, PAYLOAD_SUBSCRIPTION_MONTH)
        return

    if data == CALLBACK_PAY_RU_CARD:
        await safe_callback_answer(callback)
        if await _send_active_subscription_notice_if_needed(message):
            return
        await _send_yookassa_invoice_link(message, PAYLOAD_RU_SUBSCRIPTION_MONTH)
        return

    if data == CALLBACK_PAY_RU_EXTRA_ONE_DAY:
        await safe_callback_answer(callback)
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_yookassa_invoice_link(message, PAYLOAD_RU_EXTRA_ONE_DAY)
        return

    if data == CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF:
        await safe_callback_answer(callback)
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_yookassa_invoice_link(message, PAYLOAD_RU_EXTRA_WEEKLY_PDF)
        return

    if data == CALLBACK_BUY_EXTRA_ONE_DAY:
        await safe_callback_answer(callback)
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_stars_invoice_link(message, PAYLOAD_EXTRA_ONE_DAY)
        return

    if data == CALLBACK_BUY_EXTRA_WEEKLY_PDF:
        await safe_callback_answer(callback)
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_stars_invoice_link(message, PAYLOAD_EXTRA_WEEKLY_PDF)
        return

    if data == CALLBACK_FEATURES:
        await safe_callback_answer(callback)
        await _send_help_message(message, owner_id)
        return

    if data == CALLBACK_PRIVACY_POLICY:
        await safe_callback_answer(callback)
        await _send_privacy_policy(message, owner_id)
        return

    if data == CALLBACK_PRIVACY_POLICY_TRIAL:
        await safe_callback_answer(callback)
        await _send_privacy_policy(message, owner_id, reply_markup=_consent_keyboard(is_trial=True))
        return

    if data == CALLBACK_PRIVACY_POLICY_REGULAR:
        await safe_callback_answer(callback)
        await _send_privacy_policy(message, owner_id, reply_markup=_consent_keyboard())
        return

    if data == CALLBACK_PROMO_CODE:
        await safe_callback_answer(callback)
        await _start_promo_code_request(message)
        return

    if data == CALLBACK_REPEAT:
        await safe_callback_answer(callback)
        await _repeat_plan(message)
        return

    if data == CALLBACK_ONE_DAY_PLAN:
        await safe_callback_answer(callback)
        profile = await _run_storage_io(_profile_for_chat, owner_id)
        if profile is None:
            await _request_questionnaire_consent(message)
            return
        await _send_one_day_plan_with_access(message, profile)
        return

    if data == CALLBACK_WEEK_PLAN_PDF:
        await safe_callback_answer(callback)
        profile = await _run_storage_io(_profile_for_chat, owner_id)
        if profile is None:
            await _request_questionnaire_consent(message)
            return
        await _send_week_plan_with_access(message, profile)
        return

    if data.startswith(CALLBACK_ANSWER_PREFIX):
        session = SESSION_BY_CHAT_ID.get(owner_id)
        question = session.current_question if session is not None else None
        payload = _parse_answer_callback_data(data)
        if (
            session is None
            or question is None
            or payload is None
            or payload.session_id != session.session_id
            or payload.question_key != question.key
        ):
            await _answer_stale_question_callback(callback, message)
            return

        try:
            answer = question.options[payload.option_index]
        except IndexError:
            await _answer_stale_question_callback(callback, message)
            return

        await safe_callback_answer(callback, answer)
        await _remove_inline_keyboard(message)
        await _handle_questionnaire_answer(message, answer)
        return

    await safe_callback_answer(callback)


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    if await _run_storage_io(_is_valid_pre_checkout, pre_checkout_query):
        await safe_pre_checkout_answer(pre_checkout_query, ok=True)
        return
    await safe_pre_checkout_answer(pre_checkout_query, 
        ok=False,
        error_message="Не удалось проверить платеж. Попробуйте создать счет заново.",
    )


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    payment = message.successful_payment
    if payment is None:
        return

    result = await _run_storage_io(_apply_successful_payment, owner_id, payment, message.chat.id)
    payment_event_properties = {
        "source": "payment_handler",
        "product": _payment_product_for_grant(result.grant) or "unknown",
        "provider": _payment_provider_for_payment(payment),
        "amount": payment.total_amount,
        "currency": payment.currency,
    }
    if result.duplicate:
        await _track_event_async(
            owner_id,
            "payment_failed",
            {
                **payment_event_properties,
                "result": "duplicate",
                "reason": "duplicate_payment",
            },
        )
        status_text = await _run_storage_io(_format_entitlement_status, owner_id)
        reply_markup = await _run_storage_io(_payment_result_keyboard, owner_id, result)
        await safe_answer(message, 
            "Этот платеж уже был обработан. Текущие остатки:\n\n"
            f"{status_text}",
            reply_markup=reply_markup,
        )
        return
    if not result.processed:
        await _track_event_async(
            owner_id,
            "payment_failed",
            {
                **payment_event_properties,
                "result": "failure",
                "reason": "payment_not_applied",
            },
        )
        await safe_answer(message, 
            "Платеж получен, но я не смог распознать его назначение. Напишите в поддержку, чтобы мы проверили оплату.",
            reply_markup=_subscription_payment_keyboard(),
        )
        return

    await _track_event_async(
        owner_id,
        "payment_succeeded",
        {
            **payment_event_properties,
            "result": "success",
        },
    )
    status_text = await _run_storage_io(_payment_success_status_text, owner_id, result)
    reply_markup = await _run_storage_io(_payment_result_keyboard, owner_id, result)
    await safe_answer(message, 
        _payment_success_text(result) + "\n\n" + status_text,
        reply_markup=reply_markup,
    )


@router.message(F.refunded_payment)
async def handle_refunded_payment(message: Message) -> None:
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    payment = message.refunded_payment
    if payment is None:
        return

    result = await _run_storage_io(_apply_refunded_payment, owner_id, payment)
    text = await _run_storage_io(_payment_event_result_text, owner_id, result)
    reply_markup = await _run_storage_io(_main_menu_keyboard, owner_id)
    await safe_answer(
        message,
        text,
        reply_markup=reply_markup,
    )


@router.message()
async def handle_answer(message: Message) -> None:
    delivery_chat_id = message.chat.id
    text = (message.text or "").strip()
    normalized_command = _normalize_command_text(text)
    if normalized_command == "myid":
        await myid(message)
        return
    if _is_support_chat(delivery_chat_id):
        SUPPORT_REQUEST_CHAT_IDS.discard(delivery_chat_id)
        PROMO_CODE_REQUEST_CHAT_IDS.discard(delivery_chat_id)
        return
    if not await ensure_private_chat(message):
        return
    await _run_storage_io(_remember_user_from_message, message)
    owner_id = _message_owner_id(message)
    if normalized_command == "help":
        SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
        PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
        await _send_help_message(message, owner_id)
        return
    if normalized_command == "support":
        await _start_support_request(message)
        return
    if normalized_command == "privacy":
        SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
        PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
        await _send_privacy_policy(message, owner_id)
        return
    if _is_test_access_command(normalized_command):
        await secret_access_command(message)
        return
    if text == SUPPORT_TEXT:
        await _start_support_request(message)
        return
    if (
        owner_id in SUPPORT_REQUEST_CHAT_IDS
        or delivery_chat_id in SUPPORT_REQUEST_CHAT_IDS
    ) and normalized_command is None:
        await _handle_support_request(message, text)
        return
    if text == PROMO_CODE_TEXT:
        await _start_promo_code_request(message)
        return
    if (
        owner_id in PROMO_CODE_REQUEST_CHAT_IDS
        or delivery_chat_id in PROMO_CODE_REQUEST_CHAT_IDS
    ) and normalized_command is None:
        await _handle_promo_code_request(message, text)
        return
    if text == PRIVACY_POLICY_TEXT:
        await _send_privacy_policy(message, owner_id)
        return
    if text == TRY_FREE_TEXT:
        await _request_questionnaire_consent(message, is_trial=True)
        return
    if text in {START_PLAN_TEXT, NEW_PROFILE_TEXT, CHANGE_PROFILE_TEXT}:
        await _request_questionnaire_consent(message)
        return
    if text == SUBSCRIBE_MONTH_TEXT:
        await _send_subscription_payment_options(message)
        return
    if text == FEATURES_TEXT:
        await _send_help_message(message, owner_id)
        return
    if text == REPEAT_PLAN_TEXT:
        await _repeat_plan(message)
        return
    if text == ONE_DAY_PLAN_TEXT or text.startswith(SUBSCRIBER_ONE_DAY_PLAN_TEXT):
        profile = await _run_storage_io(_profile_for_chat, owner_id)
        if profile is None:
            await _request_questionnaire_consent(message)
            return
        await _send_one_day_plan_with_access(message, profile)
        return
    if text == WEEK_PLAN_PDF_TEXT or text.startswith(SUBSCRIBER_WEEK_PLAN_PDF_TEXT):
        profile = await _run_storage_io(_profile_for_chat, owner_id)
        if profile is None:
            await _request_questionnaire_consent(message)
            return
        await _send_week_plan_with_access(message, profile)
        return

    session = SESSION_BY_CHAT_ID.get(owner_id)
    if session is None:
        reply_markup = await _run_storage_io(_main_menu_keyboard, owner_id)
        await safe_answer(message, "Нажмите кнопку, чтобы составить рацион 👇", reply_markup=reply_markup)
        return

    await _handle_questionnaire_answer(message, text)


async def _handle_questionnaire_answer(message: Message, text: str) -> None:
    owner_id = _message_owner_id(message)
    session = SESSION_BY_CHAT_ID.get(owner_id)
    if session is None:
        reply_markup = await _run_storage_io(_main_menu_keyboard, owner_id)
        await safe_answer(message, "Нажмите кнопку, чтобы составить рацион 👇", reply_markup=reply_markup)
        return

    next_session, error = session.receive(text)
    if error:
        await safe_answer(message, error)
        await safe_answer(message, 
            session.current_question.prompt,
            reply_markup=_question_keyboard(session),
        )
        return

    early_stop = next_session.should_stop_after_answer()
    if early_stop:
        SESSION_BY_CHAT_ID.pop(owner_id, None)
        TRIAL_CHAT_IDS.discard(owner_id)
        reply_markup = await _run_storage_io(_main_menu_keyboard, owner_id)
        await safe_answer(message, early_stop, reply_markup=reply_markup)
        return

    SESSION_BY_CHAT_ID[owner_id] = next_session
    if not next_session.is_complete:
        await safe_answer(message, 
            next_session.current_question.prompt,
            reply_markup=_question_keyboard(next_session),
        )
        return

    profile = next_session.build_profile()
    PROFILE_BY_CHAT_ID[owner_id] = profile
    await _run_storage_io(_save_chat_profile, owner_id, profile)
    PLAN_COUNT_BY_CHAT_ID[owner_id] = 0
    PLAN_SEED_OFFSET_BY_CHAT_ID[owner_id] = random.SystemRandom().randrange(1, 1_000_000_000)
    await _run_storage_io(_load_chat_history, owner_id)
    SESSION_BY_CHAT_ID.pop(owner_id, None)
    is_trial = owner_id in TRIAL_CHAT_IDS
    TRIAL_CHAT_IDS.discard(owner_id)
    await _track_event_async(owner_id, "questionnaire_completed", {"is_trial": is_trial})
    if is_trial:
        await _send_trial_plan(message, profile)
        return
    await _send_calculation_options(message, profile)


@router.errors()
async def handle_global_error(event: ErrorEvent) -> bool:
    exception = event.exception
    logger.error(
        "Unhandled Telegram update error",
        extra={"exception_type": exception.__class__.__name__},
        exc_info=(type(exception), exception, exception.__traceback__),
    )
    await _send_sanitized_error_to_user(event)
    return True


async def _send_sanitized_error_to_user(event: ErrorEvent) -> None:
    update = getattr(event, "update", None)
    callback = getattr(update, "callback_query", None)
    if callback is not None:
        with suppress(Exception):
            await safe_callback_answer(callback, GENERIC_USER_ERROR_TEXT, show_alert=True)
        return

    pre_checkout_query = getattr(update, "pre_checkout_query", None)
    if pre_checkout_query is not None:
        with suppress(Exception):
            await safe_pre_checkout_answer(
                pre_checkout_query,
                ok=False,
                error_message="Не удалось проверить платёж. Попробуйте создать счёт заново.",
            )
        return

    message = _message_from_error_update(update)
    if message is not None and not _is_support_chat(message.chat.id):
        with suppress(Exception):
            await safe_answer(message, GENERIC_USER_ERROR_TEXT)


def _message_from_error_update(update: object) -> Message | None:
    for attribute in ("message", "edited_message", "channel_post"):
        value = getattr(update, attribute, None)
        if isinstance(value, Message) or (
            value is not None and hasattr(value, "chat") and hasattr(value, "answer")
        ):
            return value
    return None


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def _prepare_polling_webhook_state(bot: Bot) -> None:
    drop_pending_updates = _env_bool("DIET_BOT_DROP_PENDING_UPDATES", default=False)
    webhook_info = await telegram_api_call_with_retry(
        "get_webhook_info",
        lambda: bot.get_webhook_info(),
        attempts=3,
        max_delay=5.0,
    )
    if not webhook_info.url:
        if drop_pending_updates:
            logger.info("Telegram webhook is not active, dropping pending updates before polling")
            await telegram_api_call_with_retry(
                "delete_webhook",
                lambda: bot.delete_webhook(drop_pending_updates=True),
                attempts=3,
                max_delay=5.0,
            )
            logger.info("Pending Telegram updates dropped, polling can start")
            return
        logger.info("Telegram webhook is not active, polling can start")
        return

    logger.warning(
        "Active Telegram webhook detected before polling. Deleting webhook.",
        extra={
            "pending_update_count": webhook_info.pending_update_count,
            "drop_pending_updates": drop_pending_updates,
        },
    )

    await telegram_api_call_with_retry(
        "delete_webhook",
        lambda: bot.delete_webhook(drop_pending_updates=drop_pending_updates),
        attempts=3,
        max_delay=5.0,
    )
    logger.info("Telegram webhook deleted, polling can start")


async def run_bot() -> None:
    token = os.getenv("DIET_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN.")
    _validate_storage_config()
    validate_runtime_config()
    bot: Bot | None = None
    cleanup_task: asyncio.Task | None = None
    heartbeat_task: asyncio.Task | None = None
    try:
        bot = Bot(token)
        await _prepare_polling_webhook_state(bot)
        await _set_bot_commands(bot)
        dispatcher = create_dispatcher()
        store = await _run_storage_io(_postgres_store)
        if store is not None:
            await _cleanup_stale_generations_once(store)
            cleanup_task = asyncio.create_task(_stale_generation_cleanup_loop(store))
        _write_polling_heartbeat("polling")
        heartbeat_task = asyncio.create_task(_polling_heartbeat_loop())
        await dispatcher.start_polling(bot)
    finally:
        with suppress(Exception):
            _write_polling_heartbeat("stopping")
        for task in (cleanup_task, heartbeat_task):
            if task is not None:
                task.cancel()
        for task in (cleanup_task, heartbeat_task):
            if task is not None:
                with suppress(asyncio.CancelledError, Exception):
                    await task
        if bot is not None:
            with suppress(Exception):
                await bot.session.close()
        _remove_polling_heartbeat()


def main() -> None:
    asyncio.run(run_bot())


def _is_production_environment() -> bool:
    return is_production_environment(DIET_BOT_ENV)


def _json_storage_fallback_allowed() -> bool:
    return ALLOW_JSON_STORAGE and not _is_production_environment()


def _missing_production_database_error() -> RuntimeError:
    return RuntimeError(
        "DIET_BOT_DATABASE_URL is required in production; "
        "set DIET_BOT_ALLOW_JSON_STORAGE=1 only for local development without PostgreSQL."
    )


def _validate_storage_config() -> None:
    database_url_errors = validate_database_url(DIET_BOT_DATABASE_URL)
    if database_url_errors:
        raise RuntimeError(database_url_errors[0])
    if not DIET_BOT_DATABASE_URL and not _json_storage_fallback_allowed():
        raise _missing_production_database_error()


def validate_runtime_config() -> None:
    runtime_errors = validate_production_runtime_config(
        environment=DIET_BOT_ENV,
        support_chat_id=SUPPORT_CHAT_ID_RAW,
        privacy_policy_url=PRIVACY_POLICY_URL,
        posthog_api_key=POSTHOG_API_KEY,
        posthog_host=POSTHOG_HOST,
    )
    if runtime_errors:
        raise RuntimeError(runtime_errors[0])


def _postgres_store() -> PostgresDietBotStore | None:
    database_url_errors = validate_database_url(DIET_BOT_DATABASE_URL)
    if database_url_errors:
        raise RuntimeError(database_url_errors[0])
    if not DIET_BOT_DATABASE_URL:
        if not _json_storage_fallback_allowed():
            raise _missing_production_database_error()
        return None
    global _POSTGRES_STORE
    if _POSTGRES_STORE is None:
        _POSTGRES_STORE = PostgresDietBotStore(DIET_BOT_DATABASE_URL)
        _POSTGRES_STORE.initialize()
    return _POSTGRES_STORE


def _json_storage_runtime_paths() -> tuple[Path, ...]:
    events_path = (
        PAYMENT_EVENTS_STATE_FILE
        if PAYMENT_EVENTS_STATE_FILE is not None
        else PAYMENT_ORDERS_STATE_FILE.with_name("payment_events.json")
    )
    return (
        STATE_FILE,
        SUBSCRIPTIONS_STATE_FILE,
        PROMO_CODES_STATE_FILE,
        PAYMENT_ORDERS_STATE_FILE,
        events_path,
        _processed_payment_charges_state_file(),
    )


async def _cleanup_stale_generations_once(store: PostgresDietBotStore | None = None) -> int:
    active_store = store
    if active_store is None:
        active_store = await _run_storage_io(_postgres_store)
    if active_store is None:
        return 0
    cleaned = await asyncio.to_thread(active_store.cleanup_stale_generations)
    if cleaned:
        logger.info("Cleaned up %s stale generation(s).", cleaned)
    return cleaned


async def _stale_generation_cleanup_loop(store: PostgresDietBotStore) -> None:
    while True:
        await asyncio.sleep(GENERATION_CLEANUP_INTERVAL_SECONDS)
        try:
            await _cleanup_stale_generations_once(store)
        except Exception:
            logger.exception("Could not clean up stale generations.")


def _remember_user_from_message(message: Message) -> None:
    store = _postgres_store()
    if store is None:
        return
    user = _effective_message_user(message)
    user_id = _message_user_id(message)
    if user_id is None:
        return
    store.upsert_user(
        user_id,
        username=_optional_user_text(getattr(user, "username", None)),
        first_name=_optional_user_text(getattr(user, "first_name", None)),
    )


def _optional_user_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
    try:
        await telegram_api_call_with_retry(
            "set_my_commands",
            lambda: bot.set_my_commands(BOT_COMMANDS),
            attempts=3,
            max_delay=5.0,
        )
    except TelegramAPIError:
        logger.exception("Failed to set bot commands; bot will continue without command menu update")


async def _start_support_request(message: Message) -> None:
    owner_id = _message_owner_id(message)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
    SUPPORT_REQUEST_CHAT_IDS.add(owner_id)
    await _track_event_async(owner_id, "support_requested", {"source": "support_start"})
    await safe_answer(message, SUPPORT_PROMPT_TEXT)


async def _start_promo_code_request(message: Message) -> None:
    owner_id = _message_owner_id(message)
    SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    SESSION_BY_CHAT_ID.pop(owner_id, None)
    TRIAL_CHAT_IDS.discard(owner_id)
    PROMO_CODE_REQUEST_CHAT_IDS.add(owner_id)
    await safe_answer(message, PROMO_CODE_PROMPT_TEXT)


async def _handle_promo_code_request(message: Message, text: str) -> None:
    owner_id = _message_owner_id(message)
    if not text:
        await safe_answer(message, PROMO_CODE_EMPTY_TEXT)
        return

    activation = await _run_storage_io(_activate_promo_code_for_chat, owner_id, text)
    if activation.activated:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
        PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
        await _track_event_async(owner_id, "promo_redeemed", {"result": "success"})
        success_text = await _run_storage_io(_promo_code_success_text, owner_id)
        reply_markup = await _run_storage_io(_subscriber_cabinet_keyboard, owner_id)
        await safe_answer(message, 
            success_text,
            reply_markup=reply_markup,
        )
        return
    if activation.status == "already_used":
        await safe_answer(message, PROMO_CODE_ALREADY_USED_TEXT)
        return
    await safe_answer(message, PROMO_CODE_NOT_FOUND_TEXT)


async def _handle_support_request(message: Message, text: str) -> None:
    owner_id = _message_owner_id(message)
    if not text:
        await safe_answer(message, SUPPORT_TEXT_REQUIRED)
        return
    decision = await _check_incoming_throttle("support", owner_id, SUPPORT_THROTTLE_SECONDS)
    if not decision.allowed:
        await safe_answer(message, SUPPORT_THROTTLED_TEXT)
        return

    SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    sent = await _send_support_request_to_admin(message, text)
    reply_markup = await _run_storage_io(_main_menu_keyboard, owner_id)
    if sent:
        await safe_answer(message, SUPPORT_SENT_TEXT, reply_markup=reply_markup)
        return
    await safe_answer(message, SUPPORT_UNAVAILABLE_TEXT, reply_markup=reply_markup)


async def _send_support_request_to_admin(message: Message, text: str) -> bool:
    if SUPPORT_CHAT_ID is None:
        logger.warning("Support request was not delivered because DIET_BOT_SUPPORT_CHAT_ID is not configured.")
        return False

    try:
        admin_text = await _run_storage_io(_format_support_admin_message, message, text)
        await safe_bot_send_message(message.bot, 
            chat_id=SUPPORT_CHAT_ID,
            text=admin_text,
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
    requested_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
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


async def _request_questionnaire_consent(message: Message, *, is_trial: bool = False) -> None:
    owner_id = _message_owner_id(message)
    SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(owner_id)
    SESSION_BY_CHAT_ID.pop(owner_id, None)
    TRIAL_CHAT_IDS.discard(owner_id)
    await safe_answer(message, CONSENT_REQUEST_TEXT, reply_markup=_consent_keyboard(is_trial=is_trial))


def _consent_keyboard(*, is_trial: bool = False) -> InlineKeyboardMarkup:
    accept_callback = CALLBACK_CONSENT_TRIAL if is_trial else CALLBACK_CONSENT_REGULAR
    privacy_callback = CALLBACK_PRIVACY_POLICY_TRIAL if is_trial else CALLBACK_PRIVACY_POLICY_REGULAR
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button(text=CONSENT_ACCEPT_TEXT, callback_data=accept_callback, style=BUTTON_STYLE_PRIMARY)],
            [_privacy_policy_button(callback_data=privacy_callback)],
            [_inline_button(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


async def _send_privacy_policy(
    message: Message,
    owner_id: int,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if reply_markup is None:
        reply_markup = await _run_storage_io(_main_menu_keyboard, owner_id)
    await safe_answer(message, 
        PRIVACY_POLICY_MESSAGE,
        reply_markup=reply_markup,
    )


async def _start_questionnaire(message: Message, *, is_trial: bool = False) -> None:
    owner_id = _message_owner_id(message)
    SUPPORT_REQUEST_CHAT_IDS.discard(owner_id)
    if is_trial and await _run_storage_io(_has_active_paid_access, owner_id):
        is_trial = False
    session = start_session()
    SESSION_BY_CHAT_ID[owner_id] = session
    if is_trial:
        TRIAL_CHAT_IDS.add(owner_id)
    else:
        TRIAL_CHAT_IDS.discard(owner_id)
    await _track_event_async(
        owner_id,
        "questionnaire_started",
        {"source": "consent", "is_trial": is_trial},
    )
    await safe_answer(message, 
        session.current_question.prompt,
        reply_markup=_question_keyboard(session),
    )


async def _repeat_plan(message: Message) -> None:
    profile = await _run_storage_io(_profile_for_chat, _message_owner_id(message))
    if profile is None:
        await _request_questionnaire_consent(message)
        return
    await _send_one_day_plan_with_access(message, profile)


async def _send_calculation_options(message: Message, profile: UserProfile) -> None:
    reply_markup = await _run_storage_io(_ration_choice_keyboard_for_chat, _message_owner_id(message))
    await _send_calculation_report(message, profile, reply_markup=reply_markup)


async def _send_calculation_report(
    message: Message,
    profile: UserProfile,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    targets = calculate_targets(profile)
    safety = evaluate_safety(profile)
    await safe_answer(message, 
        format_calculation_summary(targets, safety),
        reply_markup=reply_markup,
    )


def _generation_lock_for_chat(chat_id: int) -> asyncio.Lock:
    lock = GENERATION_LOCKS_BY_CHAT_ID.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        GENERATION_LOCKS_BY_CHAT_ID[chat_id] = lock
    return lock


async def _acquire_generation_lock_or_none(chat_id: int) -> asyncio.Lock | None:
    lock = _generation_lock_for_chat(chat_id)
    if lock.locked():
        return None
    await lock.acquire()
    return lock


async def _send_generation_denial(
    message: Message,
    consumption: AttemptConsumption,
    ration_kind: RationKind,
) -> None:
    if consumption.denial_reason == "already_generating":
        await safe_answer(message, GENERATION_ALREADY_RUNNING_TEXT)
        return
    await _send_limit_paywall(message, ration_kind)


async def _heartbeat_generation_attempt_async(chat_id: int, consumption: AttemptConsumption) -> None:
    with suppress(Exception):
        await _run_storage_io(_heartbeat_generation_attempt, chat_id, consumption)


async def _generation_heartbeat_loop(chat_id: int, consumption: AttemptConsumption) -> None:
    while True:
        await asyncio.sleep(GENERATION_HEARTBEAT_INTERVAL_SECONDS)
        await _heartbeat_generation_attempt_async(chat_id, consumption)


async def _stop_generation_heartbeat(task: asyncio.Task | None) -> None:
    if task is None:
        return
    if task.done():
        with suppress(asyncio.CancelledError, Exception):
            await task
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _start_generation_delivery_async(chat_id: int, consumption: AttemptConsumption) -> bool:
    try:
        return await _run_storage_io(_start_generation_delivery, chat_id, consumption)
    except Exception:
        logger.exception("Could not mark generation delivery started.")
        return False


def _telegram_message_id(message: object) -> int | None:
    message_id = getattr(message, "message_id", None)
    if message_id is None:
        message_id = getattr(message, "id", None)
    try:
        return int(message_id)
    except (TypeError, ValueError):
        return None


def _delivery_result_message_id(result: object) -> int | None:
    if isinstance(result, GenerationDeliveryResult):
        return result.telegram_message_id
    return _telegram_message_id(result)


def _plan_validation_errors(plan: MealPlan) -> tuple[str, ...]:
    return validate_plan(plan).errors


def _week_validation_errors(plans: Sequence[MealPlan]) -> tuple[str, ...]:
    errors: list[str] = []
    for day_index, plan in enumerate(plans, start=1):
        errors.extend(f"day {day_index}: {error}" for error in _plan_validation_errors(plan))
    return tuple(dict.fromkeys(errors))


async def _send_validation_failure(message: Message, *, owner_id: int, scope: str, errors: Sequence[str]) -> None:
    logger.warning("Generated %s plan failed validation: %s", scope, "; ".join(errors))
    reply_markup = await _run_storage_io(_after_plan_keyboard, owner_id)
    await safe_answer(message, VALIDATION_FAILED_TEXT, reply_markup=reply_markup)


async def _send_trial_plan(message: Message, profile: UserProfile) -> None:
    owner_id = _message_owner_id(message)
    await _track_event_async(
        owner_id,
        "plan_requested",
        {"source": "trial", "ration_kind": "one_day"},
    )
    lock = await _acquire_generation_lock_or_none(owner_id)
    if lock is None:
        await safe_answer(message, GENERATION_ALREADY_RUNNING_TEXT)
        return
    try:
        await _send_trial_plan_locked(message, profile)
    finally:
        lock.release()


async def _send_trial_plan_locked(message: Message, profile: UserProfile) -> None:
    owner_id = _message_owner_id(message)
    consumption = await _run_storage_io(_consume_generation_attempt, owner_id, "one_day")
    if not consumption.allowed:
        await _send_generation_denial(message, consumption, "one_day")
        return

    try:
        await _send_calculation_report(message, profile)
        sent = await _send_plan(
            message,
            profile,
            include_default_after_plan_keyboard=False,
            consumption=consumption,
        )
    except Exception:
        await _run_storage_io(_refund_generation_attempt, owner_id, consumption)
        raise

    if not sent:
        await _run_storage_io(_refund_generation_attempt, owner_id, consumption)
        return

    if sent:
        await _run_storage_io(
            _complete_generation_attempt,
            owner_id,
            consumption,
            telegram_message_id=_delivery_result_message_id(sent),
        )
        status_text = await _run_storage_io(_format_entitlement_status, owner_id)
        await safe_answer(message, 
            TRIAL_SUBSCRIPTION_TEXT + "\n\n" + status_text,
            reply_markup=_trial_subscription_keyboard(),
        )


async def _send_one_day_plan_with_access(message: Message, profile: UserProfile) -> bool:
    owner_id = _message_owner_id(message)
    await _track_event_async(
        owner_id,
        "plan_requested",
        {"source": "generation", "ration_kind": "one_day"},
    )
    lock = await _acquire_generation_lock_or_none(owner_id)
    if lock is None:
        await safe_answer(message, GENERATION_ALREADY_RUNNING_TEXT)
        return False
    try:
        return await _send_one_day_plan_with_access_locked(message, profile)
    finally:
        lock.release()


async def _send_one_day_plan_with_access_locked(message: Message, profile: UserProfile) -> bool:
    owner_id = _message_owner_id(message)
    consumption = await _run_storage_io(_consume_generation_attempt, owner_id, "one_day")
    if not consumption.allowed:
        await _send_generation_denial(message, consumption, "one_day")
        return False

    try:
        status_text = await _run_storage_io(_format_entitlement_status, owner_id)
        sent = await _send_plan(
            message,
            profile,
            status_text=status_text,
            consumption=consumption,
        )
    except Exception:
        await _run_storage_io(_refund_generation_attempt, owner_id, consumption)
        raise

    if not sent:
        await _run_storage_io(_refund_generation_attempt, owner_id, consumption)
    else:
        await _run_storage_io(
            _complete_generation_attempt,
            owner_id,
            consumption,
            telegram_message_id=_delivery_result_message_id(sent),
        )
    return bool(sent)


async def _send_week_plan_with_access(message: Message, profile: UserProfile) -> bool:
    owner_id = _message_owner_id(message)
    await _track_event_async(
        owner_id,
        "weekly_pdf_requested",
        {"source": "generation", "ration_kind": "weekly_pdf"},
    )
    lock = await _acquire_generation_lock_or_none(owner_id)
    if lock is None:
        await safe_answer(message, GENERATION_ALREADY_RUNNING_TEXT)
        return False
    try:
        return await _send_week_plan_with_access_locked(message, profile)
    finally:
        lock.release()


async def _send_week_plan_with_access_locked(message: Message, profile: UserProfile) -> bool:
    owner_id = _message_owner_id(message)
    consumption = await _run_storage_io(_consume_generation_attempt, owner_id, "weekly_pdf")
    if not consumption.allowed:
        await _send_generation_denial(message, consumption, "weekly_pdf")
        return False

    try:
        status_text = await _run_storage_io(_format_entitlement_status, owner_id)
        sent = await _send_week_plan(
            message,
            profile,
            status_text=status_text,
            consumption=consumption,
        )
    except Exception:
        await _run_storage_io(_refund_generation_attempt, owner_id, consumption)
        raise

    if not sent:
        await _run_storage_io(_refund_generation_attempt, owner_id, consumption)
        status_text = await _run_storage_io(_format_entitlement_status, owner_id)
        reply_markup = await _run_storage_io(_after_plan_keyboard, owner_id)
        await safe_answer(
            message,
            "PDF не был отправлен, поэтому попытка не списана. Лимит возвращен.\n\n"
            f"{status_text}",
            reply_markup=reply_markup,
        )
    else:
        await _run_storage_io(
            _complete_generation_attempt,
            owner_id,
            consumption,
            telegram_message_id=_delivery_result_message_id(sent),
        )
    return bool(sent)


async def _send_plan(
    message: Message,
    profile: UserProfile,
    *,
    final_reply_markup: InlineKeyboardMarkup | None = None,
    include_default_after_plan_keyboard: bool = True,
    status_text: str | None = None,
    consumption: AttemptConsumption | None = None,
) -> GenerationDeliveryResult:
    owner_id = _message_owner_id(message)
    count = PLAN_COUNT_BY_CHAT_ID.get(owner_id, 0)
    seed_offset = PLAN_SEED_OFFSET_BY_CHAT_ID.setdefault(
        owner_id,
        random.SystemRandom().randrange(1, 1_000_000_000),
    )
    seed = seed_offset + count
    PLAN_COUNT_BY_CHAT_ID[owner_id] = count + 1
    if consumption is not None:
        await _heartbeat_generation_attempt_async(owner_id, consumption)
    await safe_answer(message, "Считаю рацион и проверяю ограничения... 🧮", reply_markup=ReplyKeyboardRemove())
    await _run_storage_io(_load_chat_history, owner_id)
    recent_recipe_ids = set(RECENT_RECIPE_IDS_BY_CHAT_ID.get(owner_id, []))
    recent_recipe_keys = set(RECENT_RECIPE_KEYS_BY_CHAT_ID.get(owner_id, []))
    plan_result = build_one_day_plan(
        profile,
        variety_seed=seed,
        avoided_recipe_ids=recent_recipe_ids,
        avoided_recipe_keys=recent_recipe_keys,
        recipe_source="curated_only",
    )
    plan_result = _annotate_batch_prep(plan_result)
    if consumption is not None:
        await _heartbeat_generation_attempt_async(owner_id, consumption)
    if not plan_result.safety.can_generate_plan:
        messages = format_plan_messages(plan_result, validate_plan(plan_result))
        reply_markup = await _run_storage_io(_after_plan_keyboard, owner_id)
        await _send_text_chunks(message, messages[0], reply_markup)
        return GenerationDeliveryResult(False)
    if not plan_result.meals:
        reply_markup = await _run_storage_io(_after_plan_keyboard, owner_id)
        await safe_answer(message, 
            "Не смог собрать рацион только из проверенной таблицы рецептов под эти ограничения. "
            "Попробуйте новую анкету с менее жесткими исключениями.",
            reply_markup=reply_markup,
        )
        return GenerationDeliveryResult(False)

    validation = validate_plan(plan_result)
    if validation.errors:
        await _send_validation_failure(message, owner_id=owner_id, scope="one-day", errors=validation.errors)
        return GenerationDeliveryResult(False)

    messages = list(format_plan_messages(plan_result, validation))
    if status_text and len(messages) > 2:
        messages[-1] = f"{messages[-1]}\n\n{status_text}"
    if consumption is not None and not await _start_generation_delivery_async(owner_id, consumption):
        return GenerationDeliveryResult(False)
    last_message: object | None = None
    for meal in plan_result.meals:
        last_message = await _send_meal_card(message, meal) or last_message
    await _run_storage_io(_remember_recipes, owner_id, plan_result)
    plan_reply_markup = final_reply_markup
    if plan_reply_markup is None and include_default_after_plan_keyboard:
        plan_reply_markup = await _run_storage_io(_after_plan_keyboard, owner_id)
    for index, response in enumerate(messages[2:]):
        markup = plan_reply_markup if index == len(messages[2:]) - 1 else None
        last_message = await _send_text_chunks(message, response, markup) or last_message
    return GenerationDeliveryResult(True, _telegram_message_id(last_message))


async def _send_week_plan(
    message: Message,
    profile: UserProfile,
    *,
    status_text: str | None = None,
    consumption: AttemptConsumption | None = None,
) -> GenerationDeliveryResult:
    owner_id = _message_owner_id(message)
    count = PLAN_COUNT_BY_CHAT_ID.get(owner_id, 0)
    seed_offset = PLAN_SEED_OFFSET_BY_CHAT_ID.setdefault(
        owner_id,
        random.SystemRandom().randrange(1, 1_000_000_000),
    )
    seed = seed_offset + count
    PLAN_COUNT_BY_CHAT_ID[owner_id] = count + WEEK_PLAN_DAYS * WEEK_PLAN_CANDIDATE_COUNT
    status_message = await safe_answer(message, 
        WEEK_PDF_STATUS_INITIAL_TEXT,
        reply_markup=ReplyKeyboardRemove(),
    )
    status_task = asyncio.create_task(_animate_week_pdf_status(message, status_message))
    heartbeat_task = (
        asyncio.create_task(_generation_heartbeat_loop(owner_id, consumption))
        if consumption is not None
        else None
    )
    if consumption is not None:
        await _heartbeat_generation_attempt_async(owner_id, consumption)
    await _run_storage_io(_load_chat_history, owner_id)
    recent_recipe_ids = set(RECENT_RECIPE_IDS_BY_CHAT_ID.get(owner_id, []))
    recent_recipe_keys = set(RECENT_RECIPE_KEYS_BY_CHAT_ID.get(owner_id, []))
    try:
        plans = await asyncio.to_thread(
            _build_week_plans,
            profile,
            seed,
            recent_recipe_ids,
            recent_recipe_keys,
        )
        if consumption is not None:
            await _heartbeat_generation_attempt_async(owner_id, consumption)
        plan_dates = _week_plan_dates()

        first_plan = plans[0]
        if not first_plan.safety.can_generate_plan:
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, "Не могу собрать PDF по этой анкете.")
            messages = format_plan_messages(first_plan, validate_plan(first_plan))
            reply_markup = await _run_storage_io(_after_plan_keyboard, owner_id)
            await _send_text_chunks(message, messages[0], reply_markup)
            return GenerationDeliveryResult(False)
        if any(not plan.meals for plan in plans):
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, "Не смог собрать PDF под эти ограничения.")
            reply_markup = await _run_storage_io(_after_plan_keyboard, owner_id)
            await safe_answer(message, 
                "Не смог собрать рацион на всю неделю только из проверенной таблицы рецептов под эти ограничения. "
                "Попробуйте новую анкету с менее жесткими исключениями.",
                reply_markup=reply_markup,
            )
            return GenerationDeliveryResult(False)

        validation_errors = _week_validation_errors(plans)
        if validation_errors:
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, "Не смог безопасно собрать PDF под эти ограничения.")
            await _send_validation_failure(message, owner_id=owner_id, scope="weekly PDF", errors=validation_errors)
            return GenerationDeliveryResult(False)

        used_text_fallback = False
        try:
            pdf_data, pdf_filename = await asyncio.to_thread(_build_week_pdf_payload, plans, plan_dates)
            if consumption is not None:
                await _heartbeat_generation_attempt_async(owner_id, consumption)
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, WEEK_PDF_UPLOAD_TEXT)
            if consumption is not None and not await _start_generation_delivery_async(owner_id, consumption):
                return GenerationDeliveryResult(False)
            delivery_message = await _send_week_pdf_document(
                message,
                pdf_data,
                pdf_filename,
                status_text=status_text,
            )
        except Exception:
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, WEEK_PDF_FALLBACK_TEXT)
            await safe_answer(message, "Не удалось создать PDF-файл, отправляю рацион текстом.")
            if consumption is not None and not await _start_generation_delivery_async(owner_id, consumption):
                return GenerationDeliveryResult(False)
            text_message = await _send_week_plan_as_text(message, plans, plan_dates)
            delivery_message = text_message
            used_text_fallback = True

        if not used_text_fallback:
            await _edit_week_pdf_status(status_message, WEEK_PDF_DONE_TEXT)

        for plan_result in plans:
            await _run_storage_io(_remember_recipes, owner_id, plan_result)
        return GenerationDeliveryResult(True, _telegram_message_id(delivery_message))
    finally:
        await _stop_generation_heartbeat(heartbeat_task)
        await _stop_week_pdf_status(status_task)


async def _send_week_pdf_document(
    message: Message,
    pdf_data: bytes,
    pdf_filename: str,
    *,
    status_text: str | None = None,
) -> Message | None:
    if len(pdf_data) > TELEGRAM_DOCUMENT_MAX_BYTES:
        raise ValueError(
            f"PDF is too large for Telegram upload: {len(pdf_data)} bytes "
            f"> {TELEGRAM_DOCUMENT_MAX_BYTES} bytes"
        )

    caption = "Готово - ваш рацион на неделю в PDF."
    if status_text:
        caption = f"{caption}\n\n{status_text}"
    reply_markup = await _run_storage_io(_after_plan_keyboard, _message_owner_id(message))
    return await safe_answer_document(
        message,
        document=BufferedInputFile(pdf_data, filename=pdf_filename),
        caption=caption,
        reply_markup=reply_markup,
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


async def _animate_week_pdf_status(message: Message, status_message: Message) -> None:
    frame_index = 0
    while True:
        await _send_week_pdf_chat_action(message)
        await _edit_week_pdf_status(status_message, WEEK_PDF_STATUS_FRAMES[frame_index % len(WEEK_PDF_STATUS_FRAMES)])
        frame_index += 1
        await asyncio.sleep(WEEK_PDF_STATUS_UPDATE_SECONDS)


async def _send_week_pdf_chat_action(message: Message) -> None:
    with suppress(Exception):
        await safe_send_chat_action(message.bot, chat_id=message.chat.id, action="upload_document")


async def _edit_week_pdf_status(status_message: Message, text: str) -> None:
    with suppress(TelegramAPIError, AttributeError):
        await safe_edit_text(status_message, text)


async def _stop_week_pdf_status(status_task: asyncio.Task) -> None:
    if status_task.done():
        with suppress(asyncio.CancelledError, Exception):
            await status_task
        return
    status_task.cancel()
    with suppress(asyncio.CancelledError):
        await status_task


async def _send_week_plan_as_text(
    message: Message,
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    *,
    status_text: str | None = None,
) -> Message | None:
    owner_id = _message_owner_id(message)
    sections: list[str] = []
    for day_index, (plan_result, plan_date) in enumerate(zip(plans, plan_dates), start=1):
        sections.append(_format_week_day_header(day_index, plan_date))
        for meal in plan_result.meals:
            sections.append(format_meal_card(meal, include_photo_credit=bool(meal.image_attribution)))
        sections.append(format_daily_totals(plan_result))
        await _run_storage_io(_remember_recipes, owner_id, plan_result)

    shopping_list = format_week_shopping_list(plans)
    if status_text:
        shopping_list = f"{shopping_list}\n\n{status_text}"
    sections.append(shopping_list)
    reply_markup = await _run_storage_io(_after_plan_keyboard, owner_id)
    return await _send_text_chunks(message, "\n\n".join(sections), reply_markup)


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
    best_score: tuple[int, int, float, int] | None = None
    for candidate_index in range(WEEK_PLAN_CANDIDATE_COUNT):
        plan = build_one_day_plan(
            profile,
            variety_seed=seed + candidate_index,
            avoided_recipe_ids=avoided_recipe_ids,
            avoided_recipe_keys=avoided_recipe_keys,
            recipe_source="curated_only",
        )
        carryover_options = [(_copy_carryovers(carryovers), 1)]
        if carryovers:
            carryover_options.append(({}, 0))
        for candidate_carryovers, carryover_preference in carryover_options:
            candidate_plan = _apply_batch_carryovers(plan, candidate_carryovers)
            validation = validate_plan(candidate_plan)
            score = (
                0 if validation.errors else 1,
                carryover_preference,
                _ingredient_reuse_score(candidate_plan, week_food_ids),
                -candidate_index,
            )
            if best_score is None or score > best_score:
                best_plan = candidate_plan
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
    store = _postgres_store()
    if store is not None:
        chat_state = store.load_chat_state(chat_id)
        RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_ids", []))[-RECENT_RECIPE_LIMIT:]
        RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_keys", []))[-RECENT_RECIPE_LIMIT:]
        return

    state = _load_state()
    chat_state = state.get(str(chat_id), {})
    RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_ids", []))[-RECENT_RECIPE_LIMIT:]
    RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_keys", []))[-RECENT_RECIPE_LIMIT:]


def _save_chat_history(chat_id: int) -> None:
    store = _postgres_store()
    if store is not None:
        store.save_chat_history(
            chat_id,
            recipe_ids=RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, [])[-RECENT_RECIPE_LIMIT:],
            recipe_keys=RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, [])[-RECENT_RECIPE_LIMIT:],
        )
        return

    with json_storage_transaction(*_json_storage_runtime_paths()):
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

    store = _postgres_store()
    if store is not None:
        raw_profile = store.load_profile_data(chat_id)
        if raw_profile is None:
            return None
        profile = _profile_from_dict(raw_profile)
        if profile is None:
            return None
        PROFILE_BY_CHAT_ID[chat_id] = profile
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
    store = _postgres_store()
    if store is not None:
        store.save_profile_data(chat_id, _profile_to_dict(profile))
        return

    with json_storage_transaction(*_json_storage_runtime_paths()):
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
    except OSError as exc:
        raise RuntimeError(f"Could not read chat state file {STATE_FILE}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid chat state file {STATE_FILE}: {exc}") from exc
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
    tmp_path = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with json_storage_transaction(STATE_FILE):
        try:
            tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(STATE_FILE)
        finally:
            with suppress(OSError):
                tmp_path.unlink()


def _profile_to_dict(profile: UserProfile) -> dict[str, object]:
    restrictions = _normalize_profile_restrictions(profile.restrictions)
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
            for restriction in restrictions
        ],
        "conditions": [condition.value for condition in dict.fromkeys(profile.conditions)],
        "allow_lactose_free_dairy": profile.allow_lactose_free_dairy,
        "allow_gluten_free_oats": profile.allow_gluten_free_oats,
    }


def _profile_from_dict(raw: dict[str, object]) -> UserProfile | None:
    try:
        raw_conditions = raw.get("conditions", [])
        restrictions = _profile_restrictions_from_saved_data(raw)
        conditions = list(normalize_stored_condition_codes(raw_conditions))
        conditions.extend(
            normalize_stored_condition_codes(
                [restriction.value for restriction in restrictions if restriction.type == RestrictionType.INTOLERANCE]
            )
        )
        profile = UserProfile(
            age=int(raw["age"]),
            sex=Sex(str(raw["sex"])),
            height_cm=float(raw["height_cm"]),
            weight_kg=float(raw["weight_kg"]),
            goal=Goal(str(raw["goal"])),
            activity=ActivityLevel(str(raw["activity"])),
            meal_count=int(raw.get("meal_count", 4)),
            cooking_time=CookingTimePreference(str(raw.get("cooking_time", CookingTimePreference.LONG.value))),
            restrictions=restrictions,
            conditions=tuple(dict.fromkeys(conditions)),
            allow_lactose_free_dairy=bool(raw.get("allow_lactose_free_dairy", True)),
            allow_gluten_free_oats=bool(raw.get("allow_gluten_free_oats", False)),
        )
        if not _profile_has_valid_measurements(profile):
            return None
        return profile
    except (KeyError, TypeError, ValueError):
        return None


def _profile_has_valid_measurements(profile: UserProfile) -> bool:
    return (
        1 <= profile.age <= 120
        and 90 <= profile.height_cm <= 240
        and 25 <= profile.weight_kg <= 300
        and profile.meal_count in {3, 4, 5}
    )


def _normalize_profile_restrictions(restrictions: Sequence[Restriction]) -> tuple[Restriction, ...]:
    normalized: list[Restriction] = []
    seen: set[tuple[RestrictionType, str, str]] = set()
    for restriction in restrictions:
        for value in normalize_stored_free_text_items(restriction.value):
            key = (restriction.type, value, restriction.severity)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(Restriction(restriction.type, value, restriction.severity))
    return tuple(normalized)


def _profile_restrictions_from_saved_data(raw: dict[str, object]) -> tuple[Restriction, ...]:
    restrictions: list[Restriction] = []
    raw_restrictions = raw.get("restrictions", [])
    if isinstance(raw_restrictions, list):
        for item in raw_restrictions:
            if not isinstance(item, dict):
                continue
            try:
                restriction_type = RestrictionType(str(item["type"]))
            except (KeyError, ValueError):
                continue
            severity = str(item.get("severity", "hard"))
            for value in normalize_stored_free_text_items(item.get("value")):
                restrictions.append(Restriction(restriction_type, value, severity))

    restrictions.extend(_field_restrictions(raw.get("allergies"), RestrictionType.ALLERGY))
    restrictions.extend(_field_restrictions(raw.get("intolerances"), RestrictionType.INTOLERANCE))
    restrictions.extend(_field_restrictions(raw.get("excluded_foods"), RestrictionType.EXCLUDED_FOOD))
    return _normalize_profile_restrictions(tuple(restrictions))


def _field_restrictions(value: object, restriction_type: RestrictionType) -> tuple[Restriction, ...]:
    return tuple(Restriction(restriction_type, item) for item in normalize_stored_free_text_items(value))


def _inline_button(
    *,
    text: str,
    callback_data: str | None = None,
    url: str | None = None,
    style: ButtonStyle | None = None,
    icon_custom_emoji_id: str | None = None,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        url=url,
        style=style,
        icon_custom_emoji_id=icon_custom_emoji_id,
    )


def _privacy_policy_button(*, callback_data: str = CALLBACK_PRIVACY_POLICY) -> InlineKeyboardButton:
    if PRIVACY_POLICY_URL:
        return _inline_button(text=PRIVACY_POLICY_TEXT, url=PRIVACY_POLICY_URL)
    return _inline_button(text=PRIVACY_POLICY_TEXT, callback_data=callback_data)


def _payment_guardrail_keyboard_rows() -> list[list[InlineKeyboardButton]]:
    return [
        [_privacy_policy_button()],
        [_inline_button(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
    ]


def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button(text=TRY_FREE_TEXT, callback_data=CALLBACK_START, style=BUTTON_STYLE_PRIMARY)],
            [_inline_button(text=SUBSCRIBE_MONTH_TEXT, callback_data=CALLBACK_SUBSCRIBE, style=BUTTON_STYLE_SUCCESS)],
            [_inline_button(text=FEATURES_TEXT, callback_data=CALLBACK_FEATURES)],
            [_privacy_policy_button()],
            [_inline_button(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [_inline_button(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _main_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    entitlement = _entitlement_for_chat(chat_id)
    if _has_active_paid_access(chat_id, entitlement):
        return _subscriber_cabinet_keyboard(chat_id, entitlement=entitlement)
    if _profile_for_chat(chat_id) is not None:
        return _plan_choice_keyboard()
    return _start_keyboard()


async def _send_help_message(message: Message, owner_id: int) -> None:
    reply_markup = await _run_storage_io(_main_menu_keyboard, owner_id)
    await safe_answer(message, FEATURES_MESSAGE, reply_markup=reply_markup)


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
                _inline_button(
                    text=_subscriber_one_day_button_text(chat_id, entitlement),
                    callback_data=CALLBACK_ONE_DAY_PLAN,
                    style=BUTTON_STYLE_PRIMARY,
                ),
            ],
            [
                _inline_button(
                    text=_subscriber_week_pdf_button_text(chat_id, entitlement),
                    callback_data=CALLBACK_WEEK_PLAN_PDF,
                    style=BUTTON_STYLE_PRIMARY,
                ),
            ],
            [_inline_button(text=CHANGE_PROFILE_TEXT, callback_data=CALLBACK_NEW, style=BUTTON_STYLE_DANGER)],
            [_inline_button(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
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


def _payment_success_status_text(chat_id: int, result: PaymentApplication) -> str:
    if result.grant == "subscription" or _has_active_paid_access(chat_id):
        return _subscriber_cabinet_text(chat_id)
    return _format_entitlement_status(chat_id)


async def _send_subscription_payment_options(message: Message) -> None:
    if await _send_active_subscription_notice_if_needed(message):
        return
    await safe_answer(message, SUBSCRIPTION_PAYMENT_TEXT, reply_markup=_subscription_payment_keyboard())


async def _send_active_subscription_notice_if_needed(message: Message) -> bool:
    owner_id = _message_owner_id(message)
    entitlement = await _run_storage_io(_entitlement_for_chat, owner_id)
    if not entitlement.is_subscription_active():
        return False
    if not _has_monthly_limits_remaining(entitlement):
        return False
    await safe_answer(message, 
        _active_subscription_notice_text(entitlement),
        reply_markup=_subscriber_cabinet_keyboard(owner_id, entitlement=entitlement),
    )
    return True


async def _send_extra_purchase_subscription_notice_if_needed(message: Message) -> bool:
    owner_id = _message_owner_id(message)
    entitlement = await _run_storage_io(_entitlement_for_chat, owner_id)
    if entitlement.is_subscription_active() and not _is_free_preview_mode(owner_id, entitlement):
        return False
    await safe_answer(message, 
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
    lines.append("Повторно купить месячный доступ можно, когда закончатся текущие лимиты или период.")
    return "\n".join(lines)


def _ru_card_payment_unavailable_text(payload: str) -> str:
    title = RUB_PAYMENT_PAYLOAD_TITLES.get(payload, "Оплата FoodBalance")
    amount = RUB_PAYMENT_PAYLOAD_AMOUNTS.get(payload, 0)
    return (
        f"{title}\n\n"
        f"Стоимость: {_format_kopecks_for_display(amount)} ₽.\n\n"
        "Оплата картой через ЮKassa сейчас недоступна. Попробуйте позже или оплатите через Telegram Stars."
    )


def _payment_product_for_payload(payload: str) -> PaymentProduct | None:
    if payload in {PAYLOAD_SUBSCRIPTION_MONTH, PAYLOAD_RU_SUBSCRIPTION_MONTH}:
        return "subscription_month"
    if payload in {PAYLOAD_EXTRA_ONE_DAY, PAYLOAD_RU_EXTRA_ONE_DAY}:
        return "extra_one_day"
    if payload in {PAYLOAD_EXTRA_WEEKLY_PDF, PAYLOAD_RU_EXTRA_WEEKLY_PDF}:
        return "extra_weekly_pdf"
    return None


def _create_payment_order(
    user_id: int,
    *,
    delivery_chat_id: int | None,
    product: PaymentProduct,
    provider: str,
    amount: int,
    currency: str,
    is_recurring: bool = False,
) -> PaymentOrder:
    reusable_order = _find_reusable_payment_order(
        user_id=user_id,
        delivery_chat_id=delivery_chat_id,
        product=product,
        provider=provider,
        amount=amount,
        currency=currency,
        is_recurring=is_recurring,
    )
    if reusable_order is not None:
        return reusable_order

    order = PaymentOrder.create(
        user_id=user_id,
        delivery_chat_id=delivery_chat_id,
        product=product,
        provider=provider,
        amount=amount,
        currency=currency,
        is_recurring=is_recurring,
    )
    store = _postgres_store()
    if store is not None:
        store.create_payment_order(order)
    else:
        remember_payment_order(PAYMENT_ORDERS_STATE_FILE, order)
    return order


def _find_reusable_payment_order(
    *,
    user_id: int,
    delivery_chat_id: int | None,
    product: PaymentProduct,
    provider: str,
    amount: int,
    currency: str,
    is_recurring: bool,
) -> PaymentOrder | None:
    store = _postgres_store()
    if store is not None:
        return store.find_active_payment_order(
            user_id=user_id,
            delivery_chat_id=delivery_chat_id,
            product=product,
            provider=provider,
            amount=amount,
            currency=currency,
            is_recurring=is_recurring,
        )

    state = load_payment_order_state(PAYMENT_ORDERS_STATE_FILE)
    candidates = sorted(
        state.orders.values(),
        key=lambda order: order.created_at,
        reverse=True,
    )
    for order in candidates:
        if (
            order.user_id == user_id
            and order.delivery_chat_id == delivery_chat_id
            and order.product == product
            and order.provider == provider
            and order.amount == amount
            and order.currency == currency
            and order.is_recurring == is_recurring
            and order.status == "pending"
            and order.invoice_link
            and not order.is_expired()
        ):
            return order
    return None


def _get_payment_order(order_id: str) -> PaymentOrder | None:
    store = _postgres_store()
    if store is not None:
        return store.get_payment_order(order_id)
    return load_payment_order_state(PAYMENT_ORDERS_STATE_FILE).orders.get(order_id)


def _set_payment_order_invoice_link(order: PaymentOrder, invoice_link: str) -> PaymentOrder:
    updated_order = order.with_invoice_link(invoice_link)
    store = _postgres_store()
    if store is not None:
        stored_order = store.set_payment_order_invoice_link(order.order_id, invoice_link)
        return stored_order or updated_order
    _save_file_payment_order(updated_order)
    return updated_order


def _save_file_payment_order(order: PaymentOrder) -> None:
    with json_storage_transaction(*_json_storage_runtime_paths()):
        state = load_payment_order_state(PAYMENT_ORDERS_STATE_FILE)
        state.orders[order.order_id] = order
        save_payment_order_state(PAYMENT_ORDERS_STATE_FILE, state)


def _payment_events_state_file() -> Path:
    if PAYMENT_EVENTS_STATE_FILE is not None:
        return PAYMENT_EVENTS_STATE_FILE
    return PAYMENT_ORDERS_STATE_FILE.with_name("payment_events.json")


def _processed_payment_charges_state_file() -> Path:
    return PAYMENT_ORDERS_STATE_FILE.with_name("processed_payment_charges.json")


def _mark_payment_order_failed_invoice_creation(order: PaymentOrder) -> None:
    store = _postgres_store()
    if store is not None:
        store.mark_payment_order_failed_invoice_creation(order.order_id)
        return
    _save_file_payment_order(order.mark_failed_invoice_creation())


def _mark_payment_order_expired(order: PaymentOrder) -> None:
    store = _postgres_store()
    if store is not None:
        store.mark_payment_order_expired(order.order_id)
        return
    _save_file_payment_order(order.mark_expired())


async def _send_stars_invoice_link(message: Message, payload: str) -> None:
    if not await ensure_private_chat(message):
        return
    buyer_id = _message_user_id(message)
    if buyer_id is None:
        await safe_answer(message, PRIVATE_CHAT_REQUIRED_TEXT)
        return
    amount = PAYMENT_PAYLOAD_AMOUNTS[payload]
    title = PAYMENT_PAYLOAD_TITLES[payload]
    description = PAYMENT_PAYLOAD_DESCRIPTIONS[payload]
    product = _payment_product_for_payload(payload)
    if product is None:
        return
    await _track_event_async(
        buyer_id,
        "checkout_started",
        {
            "source": "payment_button",
            "product": product,
            "provider": "telegram_stars",
            "amount": amount,
            "currency": "XTR",
        },
    )
    order = await _run_storage_io(
        _create_payment_order,
        buyer_id,
        delivery_chat_id=message.chat.id,
        product=product,
        provider="telegram_stars",
        amount=amount,
        currency="XTR",
        is_recurring=payload == PAYLOAD_SUBSCRIPTION_MONTH,
    )
    if order.invoice_link:
        await safe_answer(message,
            f"{title}\n\nСтоимость: {amount} Stars.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [_inline_button(text="Оплатить в Telegram", url=order.invoice_link, style=BUTTON_STYLE_SUCCESS)],
                ],
            ),
        )
        return
    subscription_period = SUBSCRIPTION_PERIOD_SECONDS if payload == PAYLOAD_SUBSCRIPTION_MONTH else None
    try:
        invoice_link = await safe_create_invoice_link(
            message.bot,
            chat_id=message.chat.id,
            title=title,
            description=description,
            payload=order.payload,
            currency="XTR",
            prices=[LabeledPrice(label=title, amount=amount)],
            provider_token="",
            subscription_period=subscription_period,
        )
    except TelegramAPIError:
        await _run_storage_io(_mark_payment_order_failed_invoice_creation, order)
        await _track_event_async(
            buyer_id,
            "payment_failed",
            {
                "source": "invoice_creation",
                "product": product,
                "provider": "telegram_stars",
                "amount": amount,
                "currency": "XTR",
                "reason": "invoice_creation_failed",
                "result": "failure",
            },
        )
        logger.exception(
            "Failed to create Stars invoice link",
            extra={
                "order_hash": _log_identifier(order.order_id, prefix="order"),
                "user_hash": _log_identifier(order.user_id, prefix="tg"),
                "product": order.product,
            },
        )
        await safe_answer(message, PAYMENT_INVOICE_CREATION_FAILED_TEXT)
        return
    order = await _run_storage_io(_set_payment_order_invoice_link, order, invoice_link)
    await _track_event_async(
        buyer_id,
        "invoice_created",
        {
            "source": "invoice_creation",
            "product": product,
            "provider": "telegram_stars",
            "amount": amount,
            "currency": "XTR",
        },
    )
    await safe_answer(message, 
        f"{title}\n\nСтоимость: {amount} Stars.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [_inline_button(text="Оплатить в Telegram", url=invoice_link, style=BUTTON_STYLE_SUCCESS)],
            ],
        ),
    )


async def _send_yookassa_invoice_link(message: Message, payload: str) -> None:
    if not await ensure_private_chat(message):
        return
    buyer_id = _message_user_id(message)
    if buyer_id is None:
        await safe_answer(message, PRIVATE_CHAT_REQUIRED_TEXT)
        return
    provider_token = TELEGRAM_PROVIDER_TOKEN.strip()
    if not provider_token:
        await _track_event_async(
            buyer_id,
            "payment_failed",
            {
                "source": "invoice_creation",
                "product": _payment_product_for_payload(payload) or "unknown",
                "provider": "yookassa",
                "amount": RUB_PAYMENT_PAYLOAD_AMOUNTS.get(payload, 0),
                "currency": "RUB",
                "reason": "provider_token_missing",
                "result": "failure",
            },
        )
        await safe_answer(message, _ru_card_payment_unavailable_text(payload))
        return

    amount = RUB_PAYMENT_PAYLOAD_AMOUNTS[payload]
    title = RUB_PAYMENT_PAYLOAD_TITLES[payload]
    description = RUB_PAYMENT_PAYLOAD_DESCRIPTIONS[payload]
    product = _payment_product_for_payload(payload)
    if product is None:
        return
    await _track_event_async(
        buyer_id,
        "checkout_started",
        {
            "source": "payment_button",
            "product": product,
            "provider": "yookassa",
            "amount": amount,
            "currency": "RUB",
        },
    )
    order = await _run_storage_io(
        _create_payment_order,
        buyer_id,
        delivery_chat_id=message.chat.id,
        product=product,
        provider="yookassa",
        amount=amount,
        currency="RUB",
    )
    if order.invoice_link:
        await safe_answer(message,
            (
                f"{title}\n\n"
                f"Стоимость: {_format_kopecks_for_display(amount)} ₽.\n\n"
                "Для фискального чека YooKassa и Telegram могут запросить email."
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [_inline_button(text="Оплатить в Telegram", url=order.invoice_link, style=BUTTON_STYLE_SUCCESS)],
                    [_privacy_policy_button()],
                ],
            ),
        )
        return
    try:
        invoice_link = await safe_create_invoice_link(
            message.bot,
            chat_id=message.chat.id,
            title=title,
            description=description,
            payload=order.payload,
            currency="RUB",
            prices=[LabeledPrice(label=title, amount=amount)],
            provider_token=provider_token,
            need_email=True,
            send_email_to_provider=True,
            provider_data=json.dumps(_yookassa_provider_data(title, amount), ensure_ascii=False),
        )
    except TelegramAPIError:
        await _run_storage_io(_mark_payment_order_failed_invoice_creation, order)
        await _track_event_async(
            buyer_id,
            "payment_failed",
            {
                "source": "invoice_creation",
                "product": product,
                "provider": "yookassa",
                "amount": amount,
                "currency": "RUB",
                "reason": "invoice_creation_failed",
                "result": "failure",
            },
        )
        logger.exception(
            "Failed to create YooKassa invoice link",
            extra={
                "order_hash": _log_identifier(order.order_id, prefix="order"),
                "user_hash": _log_identifier(order.user_id, prefix="tg"),
                "product": order.product,
            },
        )
        await safe_answer(message, PAYMENT_INVOICE_CREATION_FAILED_TEXT)
        return

    order = await _run_storage_io(_set_payment_order_invoice_link, order, invoice_link)
    await _track_event_async(
        buyer_id,
        "invoice_created",
        {
            "source": "invoice_creation",
            "product": product,
            "provider": "yookassa",
            "amount": amount,
            "currency": "RUB",
        },
    )
    await safe_answer(message, 
        (
            f"{title}\n\n"
            f"Стоимость: {_format_kopecks_for_display(amount)} ₽.\n\n"
            "Для фискального чека YooKassa и Telegram могут запросить email."
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [_inline_button(text="Оплатить в Telegram", url=invoice_link, style=BUTTON_STYLE_SUCCESS)],
                [_privacy_policy_button()],
            ],
        ),
    )


def _yookassa_provider_data(title: str, amount: int) -> dict[str, object]:
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
    decoded = decode_payment_order_payload(pre_checkout_query.invoice_payload)
    if decoded is not None:
        order_id, nonce = decoded
        return _is_valid_order_pre_checkout(pre_checkout_query, order_id, nonce)
    return _is_valid_legacy_pre_checkout(pre_checkout_query)


def _is_valid_order_pre_checkout(
    pre_checkout_query: PreCheckoutQuery,
    order_id: str,
    nonce: str,
) -> bool:
    buyer_id = _pre_checkout_user_id(pre_checkout_query)
    if buyer_id is None:
        return False
    order = _get_payment_order(order_id)
    if order is None:
        return False
    if order.nonce != nonce:
        return False
    if order.user_id != buyer_id:
        return False
    if order.status != "pending":
        return False
    if order.is_expired():
        _mark_payment_order_expired(order)
        return False
    if order.currency != pre_checkout_query.currency:
        return False
    if order.amount != pre_checkout_query.total_amount:
        return False
    if order.product != "subscription_month":
        entitlement = _entitlement_for_chat(buyer_id)
        if not entitlement.is_subscription_active():
            return False
    return True


def _is_valid_legacy_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> bool:
    if not _legacy_payment_payloads_enabled():
        return False
    return _is_legacy_monthly_payment(
        payload=pre_checkout_query.invoice_payload,
        currency=pre_checkout_query.currency,
        amount=pre_checkout_query.total_amount,
    )


def _pre_checkout_user_id(pre_checkout_query: PreCheckoutQuery) -> int | None:
    user = getattr(pre_checkout_query, "from_user", None)
    user_id = getattr(user, "id", None)
    return user_id if isinstance(user_id, int) else None


def _is_legacy_monthly_payment(*, payload: str, currency: str, amount: int) -> bool:
    if payload == PAYLOAD_SUBSCRIPTION_MONTH:
        return currency == "XTR" and amount == PAYMENT_PAYLOAD_AMOUNTS[PAYLOAD_SUBSCRIPTION_MONTH]
    if payload == PAYLOAD_RU_SUBSCRIPTION_MONTH:
        return currency == "RUB" and amount == RUB_PAYMENT_PAYLOAD_AMOUNTS[PAYLOAD_RU_SUBSCRIPTION_MONTH]
    return False


def _payment_provider_for_payment(payment: SuccessfulPayment) -> str:
    if payment.currency == "XTR":
        return "telegram_stars"
    if payment.currency == "RUB":
        return "yookassa"
    return payment.currency.lower() or "telegram"


def _payment_charge_id(payment: SuccessfulPayment) -> str:
    provider = _payment_provider_for_payment(payment)
    telegram_charge_id = _payment_telegram_charge_id(payment)
    provider_charge_id = _payment_provider_charge_id(payment)
    if provider == "yookassa" and provider_charge_id:
        return provider_charge_id
    return str(telegram_charge_id or provider_charge_id)


def _payment_telegram_charge_id(payment: SuccessfulPayment) -> str:
    telegram_charge_id = getattr(payment, "telegram_payment_charge_id", "") or ""
    return str(telegram_charge_id)


def _payment_provider_charge_id(payment: SuccessfulPayment) -> str:
    provider_charge_id = getattr(payment, "provider_payment_charge_id", "") or ""
    return str(provider_charge_id)


def _payment_raw_payload(payment: SuccessfulPayment) -> dict[str, object]:
    return {
        "invoice_payload": getattr(payment, "invoice_payload", None),
        "currency": getattr(payment, "currency", None),
        "total_amount": getattr(payment, "total_amount", None),
        "telegram_payment_charge_id": getattr(payment, "telegram_payment_charge_id", None),
        "provider_payment_charge_id": getattr(payment, "provider_payment_charge_id", None),
        "is_recurring": getattr(payment, "is_recurring", None),
        "is_first_recurring": getattr(payment, "is_first_recurring", None),
        "subscription_expiration_date": getattr(payment, "subscription_expiration_date", None),
    }


def _normalize_payment_event_type(event_type: str) -> str:
    normalized = str(event_type).strip().lower().replace("-", "_")
    if normalized in {
        PAYMENT_EVENT_SUCCESSFUL,
        PAYMENT_EVENT_REFUND,
        PAYMENT_EVENT_CHARGEBACK,
        PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
    }:
        return normalized
    return "unknown"


def _parse_payment_event_reconciliation_command(text: str) -> AdminPaymentEventCommand | None:
    args = text.split()[1:]
    if len(args) == 2 and args[0].strip().lower() == "reconcile":
        lookup_id = args[1].strip()
        if not lookup_id:
            return None
        return AdminPaymentEventCommand(
            event_type="reconcile",
            provider="",
            charge_id=lookup_id,
            action="reconcile",
            lookup_id=lookup_id,
        )

    if len(args) not in {3, 4}:
        return None

    event_type = _normalize_payment_event_type(args[0])
    if event_type not in {
        PAYMENT_EVENT_REFUND,
        PAYMENT_EVENT_CHARGEBACK,
        PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
    }:
        return None

    provider = args[1].strip().lower().replace("-", "_")
    charge_id = args[2].strip()
    if not provider or not charge_id:
        return None

    user_id = None
    if len(args) == 4:
        user_id = _parse_optional_int(args[3])
        if user_id is None:
            return None

    return AdminPaymentEventCommand(
        event_type=event_type,
        provider=provider,
        charge_id=charge_id,
        user_id=user_id,
    )


def _payment_event_reconciliation_usage_text() -> str:
    return (
        "Usage:\n"
        "/payment_event reconcile <event_id|telegram_charge_id|provider_charge_id>\n"
        "/payment_event refund <provider> <charge_id> [user_id]\n"
        "/payment_event chargeback <provider> <charge_id> [user_id]\n"
        "/payment_event cancel_subscription <provider> <charge_id> [user_id]"
    )


def _resolve_successful_payment_user_id(*, provider: str, charge_id: str) -> int | None:
    store = _postgres_store()
    if store is not None:
        return store.find_successful_payment_user_id(provider=provider, charge_id=charge_id)

    state = load_payment_event_state(_payment_events_state_file())
    successful_event = find_successful_payment_event(state, provider=provider, charge_id=charge_id)
    return successful_event.user_id if successful_event is not None else None


def _apply_admin_payment_event(
    user_id: int,
    command: AdminPaymentEventCommand,
    *,
    admin_id: int | None,
    admin_chat_id: int,
) -> PaymentEventApplication:
    return _apply_payment_event(
        user_id,
        event_type=command.event_type,
        provider=command.provider,
        charge_id=command.charge_id,
        raw_payload={
            "source": "admin_reconciliation_command",
            "admin_hash": _log_identifier(admin_id, prefix="admin"),
            "admin_chat_hash": _log_identifier(admin_chat_id, prefix="chat"),
            "user_hash": _log_identifier(user_id, prefix="tg"),
            "event_type": command.event_type,
            "provider": command.provider,
        },
    )


def _admin_payment_event_result_text(
    command: AdminPaymentEventCommand,
    user_id: int,
    result: PaymentEventApplication,
) -> str:
    if result.duplicate:
        status = "already_processed"
        headline = "already_processed: event already applied"
    elif result.processed:
        status = "processed"
        headline = "processed: event applied"
    else:
        status = result.status or PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL
        headline = f"{status}: event did not change access"

    lines = [
        headline,
        f"result: {status}",
        f"event_type: {command.event_type}",
        f"provider: {command.provider}",
        f"charge_id: {command.charge_id}",
        f"user_id: {user_id}",
    ]
    if result.product:
        lines.append(f"product: {result.product}")
    if result.reason:
        lines.append(f"reason: {result.reason}")
    return "\n".join(lines)


def _admin_payment_reconcile_result_text(
    lookup_id: str,
    result: PaymentEventApplication,
) -> str:
    status = result.status or (
        PAYMENT_EVENT_STATUS_PROCESSED
        if result.processed
        else PAYMENT_EVENT_STATUS_DUPLICATE
        if result.duplicate
        else PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL
    )
    lines = [
        f"{status}: reconciliation finished",
        f"result: {status}",
        f"lookup_id: {lookup_id}",
        f"event_type: {result.event_type}",
    ]
    if result.product:
        lines.append(f"product: {result.product}")
    if result.reason:
        lines.append(f"reason: {result.reason}")
    return "\n".join(lines)


def _legacy_payment_payloads_enabled() -> bool:
    if not ALLOW_LEGACY_PAYMENT_PAYLOADS:
        return False
    return ALLOW_LEGACY_PAYLOADS_UNTIL is None or datetime.now(UTC) <= ALLOW_LEGACY_PAYLOADS_UNTIL


def _record_file_successful_payment_event(
    *,
    user_id: int,
    provider: str,
    charge_id: str,
    telegram_charge_id: str | None = None,
    provider_charge_id: str | None = None,
    product: str,
    amount: int | None,
    currency: str | None,
    raw_payload: dict[str, object],
) -> None:
    record_payment_event(
        _payment_events_state_file(),
        PaymentEvent.create(
            event_type=PAYMENT_EVENT_SUCCESSFUL,
            provider=provider,
            charge_id=charge_id,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            user_id=user_id,
            product=product,
            amount=amount,
            currency=currency,
            status=PAYMENT_EVENT_STATUS_PROCESSED,
            raw_payload=raw_payload,
        ),
    )


def _record_file_orphan_payment_event(
    *,
    user_id: int,
    provider: str,
    charge_id: str,
    telegram_charge_id: str | None = None,
    provider_charge_id: str | None = None,
    amount: int | None,
    currency: str | None,
    reason: str,
    raw_payload: dict[str, object],
) -> None:
    if not charge_id:
        return
    record_payment_event(
        _payment_events_state_file(),
        PaymentEvent.create(
            event_type=PAYMENT_EVENT_SUCCESSFUL,
            provider=provider,
            charge_id=charge_id,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            user_id=user_id,
            amount=amount,
            currency=currency,
            status=PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE,
            reason=reason,
            raw_payload=raw_payload,
        ),
    )


def _load_processed_payment_charge_registry() -> ProcessedPaymentChargeState:
    path = _processed_payment_charges_state_file()
    state = load_processed_payment_charge_state(path)
    if _backfill_processed_payment_charge_registry(state):
        save_processed_payment_charge_state(path, state)
    return state


def _backfill_processed_payment_charge_registry(state: ProcessedPaymentChargeState) -> bool:
    changed = False
    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    for user_id, entitlement in entitlements.items():
        for stored_charge_id in entitlement.processed_payment_charge_ids:
            changed = _add_legacy_processed_payment_charge(
                state,
                user_id=user_id,
                stored_charge_id=stored_charge_id,
            ) or changed

    payment_events = load_payment_event_state(_payment_events_state_file())
    for event in payment_events.events:
        if event.event_type != PAYMENT_EVENT_SUCCESSFUL or event.status != "processed":
            continue
        changed = add_processed_payment_charge(
            state,
            ProcessedPaymentCharge.create(
                provider=event.provider,
                charge_id=event.charge_id,
                telegram_charge_id=event.telegram_charge_id,
                provider_charge_id=event.provider_charge_id,
                user_id=event.user_id,
                kind=_payment_registry_kind_for_product(event.product),
                created_at=event.created_at or None,
            ),
        ) or changed
    return changed


def _add_legacy_processed_payment_charge(
    state: ProcessedPaymentChargeState,
    *,
    user_id: int,
    stored_charge_id: str,
) -> bool:
    stored_charge_id = str(stored_charge_id).strip()
    if not stored_charge_id:
        return False
    if ":" in stored_charge_id:
        provider, charge_id = stored_charge_id.split(":", 1)
        provider = provider.strip()
        charge_id = charge_id.strip()
    else:
        provider = PROCESSED_PAYMENT_CHARGE_LEGACY_PROVIDER
        charge_id = stored_charge_id
    if not provider or not charge_id:
        return False
    return add_processed_payment_charge(
        state,
        ProcessedPaymentCharge.create(
            provider=provider,
            charge_id=charge_id,
            user_id=user_id,
            kind="legacy",
        ),
    )


def _remember_processed_payment_charge(
    state: ProcessedPaymentChargeState,
    *,
    user_id: int,
    provider: str,
    charge_id: str,
    telegram_charge_id: str | None = None,
    provider_charge_id: str | None = None,
    kind: str,
) -> bool:
    return add_processed_payment_charge(
        state,
        ProcessedPaymentCharge.create(
            provider=provider,
            charge_id=charge_id,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            user_id=user_id,
            kind=kind,
        ),
    )


def _payment_registry_kind_for_product(product: str | None) -> str | None:
    if product == "subscription_month":
        return "subscription"
    if product in {"extra_one_day", "extra_weekly_pdf"}:
        return product
    return None


def _apply_refunded_payment(user_id: int, payment: RefundedPayment) -> PaymentEventApplication:
    return _apply_payment_event(
        user_id,
        event_type=PAYMENT_EVENT_REFUND,
        provider=_payment_provider_for_payment(payment),  # type: ignore[arg-type]
        charge_id=_payment_charge_id(payment),  # type: ignore[arg-type]
        amount=getattr(payment, "total_amount", None),
        currency=getattr(payment, "currency", None),
        raw_payload=_payment_raw_payload(payment),  # type: ignore[arg-type]
    )


def _apply_payment_event(
    user_id: int,
    *,
    event_type: str,
    provider: str,
    charge_id: str,
    amount: int | None = None,
    currency: str | None = None,
    raw_payload: dict[str, object] | None = None,
) -> PaymentEventApplication:
    normalized_event_type = _normalize_payment_event_type(event_type)
    store = _postgres_store()
    if store is not None:
        return store.apply_payment_event(
            user_id,
            event_type=normalized_event_type,
            provider=provider,
            charge_id=charge_id,
            amount=amount,
            currency=currency,
            raw_payload=dict(raw_payload or {}),
        )
    return _apply_file_payment_event(
        user_id,
        event_type=normalized_event_type,
        provider=provider,
        charge_id=charge_id,
        amount=amount,
        currency=currency,
        raw_payload=dict(raw_payload or {}),
    )


def _apply_file_payment_event(
    user_id: int,
    *,
    event_type: str,
    provider: str,
    charge_id: str,
    amount: int | None,
    currency: str | None,
    raw_payload: dict[str, object],
) -> PaymentEventApplication:
    if not charge_id:
        return PaymentEventApplication(
            False,
            event_type,
            reason="missing_charge_id",
            status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
        )

    with json_storage_transaction(*_json_storage_runtime_paths()):
        events_path = _payment_events_state_file()
        state = load_payment_event_state(events_path)
        if event_type == "unknown":
            existing = find_payment_event(
                state,
                provider=provider,
                charge_id=charge_id,
                event_type=event_type,
            )
            inserted = record_payment_event(
                events_path,
                PaymentEvent.create(
                    event_type=event_type,
                    provider=provider,
                    charge_id=charge_id,
                    user_id=user_id,
                    amount=amount,
                    currency=currency,
                    status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
                    reason="unknown_event_type",
                    raw_payload=raw_payload,
                ),
            )
            return PaymentEventApplication(
                False,
                event_type,
                duplicate=bool(existing and existing.status == PAYMENT_EVENT_STATUS_PROCESSED),
                reason="unknown_event_type" if inserted or existing else "duplicate_event",
                status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
            )

        if event_type == PAYMENT_EVENT_SUCCESSFUL:
            return PaymentEventApplication(
                False,
                event_type,
                reason="successful_payment_uses_specific_handler",
                status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
            )

        if terminal_payment_adjustment_exists(
            state,
            event_type=event_type,
            provider=provider,
            charge_id=charge_id,
        ):
            successful_event = find_successful_payment_event(state, provider=provider, charge_id=charge_id)
            record_payment_event(
                events_path,
                PaymentEvent.create(
                    event_type=event_type,
                    provider=provider,
                    charge_id=charge_id,
                    telegram_charge_id=successful_event.telegram_charge_id if successful_event else None,
                    provider_charge_id=successful_event.provider_charge_id if successful_event else None,
                    user_id=user_id,
                    product=successful_event.product if successful_event else None,
                    amount=amount,
                    currency=currency,
                    status=PAYMENT_EVENT_STATUS_DUPLICATE,
                    reason="duplicate_event",
                    raw_payload=raw_payload,
                ),
            )
            return PaymentEventApplication(
                False,
                event_type,
                product=successful_event.product if successful_event else None,
                duplicate=True,
                reason="duplicate_event",
                status=PAYMENT_EVENT_STATUS_DUPLICATE,
            )

        successful_event = find_successful_payment_event(state, provider=provider, charge_id=charge_id)
        if successful_event is None or not successful_event.product:
            existing_pending = find_payment_event(
                state,
                provider=provider,
                charge_id=charge_id,
                event_type=event_type,
                statuses=PAYMENT_EVENT_TRANSITIONAL_STATUSES,
            )
            if existing_pending is not None:
                return PaymentEventApplication(
                    False,
                    event_type,
                    reason="original_payment_not_found",
                    status=PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
                )
            inserted = record_payment_event(
                events_path,
                PaymentEvent.create(
                    event_type=event_type,
                    provider=provider,
                    charge_id=charge_id,
                    user_id=user_id,
                    amount=amount,
                    currency=currency,
                    status=PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
                    reason="original_payment_not_found",
                    raw_payload=raw_payload,
                ),
            )
            return PaymentEventApplication(
                False,
                event_type,
                duplicate=False,
                reason="original_payment_not_found" if inserted else "pending_reconciliation_exists",
                status=PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
            )

        entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
        entitlement = entitlements.get(user_id, Entitlement())
        reversal = apply_payment_reversal(
            entitlement,
            successful_event.product,
            event_type,  # type: ignore[arg-type]
        )
        status = (
            PAYMENT_EVENT_STATUS_PROCESSED
            if reversal.processed
            else PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL
        )
        reason = reversal.reason
        inserted = record_payment_event(
            events_path,
            PaymentEvent.create(
                event_type=event_type,
                provider=provider,
                charge_id=charge_id,
                telegram_charge_id=successful_event.telegram_charge_id,
                provider_charge_id=successful_event.provider_charge_id,
                user_id=user_id,
                product=successful_event.product,
                amount=amount,
                currency=currency,
                status=status,
                reason=reason,
                raw_payload={
                    **raw_payload,
                    "successful_payment_event": successful_event.to_dict(),
                },
            ),
        )
        if not inserted:
            return PaymentEventApplication(
                False,
                event_type,
                product=successful_event.product,
                duplicate=True,
                reason="duplicate_event",
                status=PAYMENT_EVENT_STATUS_DUPLICATE,
            )
        entitlements[user_id] = entitlement
        save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
        return PaymentEventApplication(
            reversal.processed,
            event_type,
            product=successful_event.product,
            reason=reason,
            status=status,
        )


def _reconcile_file_pending_payment_events_for_charge(
    *,
    user_id: int,
    provider: str,
    charge_id: str,
) -> list[PaymentEventApplication]:
    state = load_payment_event_state(_payment_events_state_file())
    pending_events = [
        event
        for event in state.events
        if event.user_id == user_id
        and event.provider == provider
        and event.event_type in {
            PAYMENT_EVENT_REFUND,
            PAYMENT_EVENT_CHARGEBACK,
            PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
        }
        and event.status == PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION
        and charge_id in {
            event.charge_id,
            event.telegram_charge_id or "",
            event.provider_charge_id or "",
            str(event.raw_payload.get("telegram_payment_charge_id") or ""),
            str(event.raw_payload.get("provider_payment_charge_id") or ""),
        }
    ]
    results: list[PaymentEventApplication] = []
    for event in pending_events:
        results.append(
            _apply_file_payment_event(
                user_id,
                event_type=event.event_type,
                provider=event.provider,
                charge_id=event.charge_id,
                amount=event.amount,
                currency=event.currency,
                raw_payload={
                    **event.raw_payload,
                    "source": "automatic_pending_reconciliation",
                    "payment_event_id": event.event_id,
                },
            )
        )
    return results


def _reconcile_admin_payment_event(
    lookup_id: str,
    *,
    admin_id: int | None,
    admin_chat_id: int,
) -> PaymentEventApplication:
    lookup_id = str(lookup_id).strip()
    if not lookup_id:
        return PaymentEventApplication(
            False,
            "reconcile",
            reason="missing_lookup_id",
            status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
        )

    store = _postgres_store()
    if store is not None:
        event = store.find_payment_event_for_reconciliation(lookup_id)
        if event is None:
            processed_event = store.find_payment_event_for_reconciliation(
                lookup_id,
                statuses={PAYMENT_EVENT_STATUS_PROCESSED},
            )
            if processed_event is not None:
                return PaymentEventApplication(
                    False,
                    processed_event.event_type,
                    product=processed_event.product,
                    duplicate=True,
                    reason="already_processed",
                    status=PAYMENT_EVENT_STATUS_DUPLICATE,
                )
            return PaymentEventApplication(
                False,
                "reconcile",
                reason="payment_event_not_found",
                status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
            )
        return _reconcile_payment_event_object(event, admin_id=admin_id, admin_chat_id=admin_chat_id)

    with json_storage_transaction(*_json_storage_runtime_paths()):
        state = load_payment_event_state(_payment_events_state_file())
        event = find_payment_event(
            state,
            event_id=lookup_id,
            statuses=PAYMENT_EVENT_TRANSITIONAL_STATUSES,
        ) or find_payment_event(
            state,
            charge_id=lookup_id,
            statuses=PAYMENT_EVENT_TRANSITIONAL_STATUSES,
        )
        if event is None:
            processed_event = find_payment_event(
                state,
                event_id=lookup_id,
                statuses={PAYMENT_EVENT_STATUS_PROCESSED},
            ) or find_payment_event(
                state,
                charge_id=lookup_id,
                statuses={PAYMENT_EVENT_STATUS_PROCESSED},
            )
            if processed_event is not None:
                return PaymentEventApplication(
                    False,
                    processed_event.event_type,
                    product=processed_event.product,
                    duplicate=True,
                    reason="already_processed",
                    status=PAYMENT_EVENT_STATUS_DUPLICATE,
                )
            return PaymentEventApplication(
                False,
                "reconcile",
                reason="payment_event_not_found",
                status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
            )
        return _reconcile_payment_event_object(event, admin_id=admin_id, admin_chat_id=admin_chat_id)


def _reconcile_payment_event_object(
    event: PaymentEvent,
    *,
    admin_id: int | None,
    admin_chat_id: int,
) -> PaymentEventApplication:
    if event.user_id is None:
        return PaymentEventApplication(
            False,
            event.event_type,
            reason="missing_event_user_id",
            status=event.status,
        )
    raw_payload = {
        **event.raw_payload,
        "source": "admin_reconciliation_replay",
        "admin_hash": _log_identifier(admin_id, prefix="admin"),
        "admin_chat_hash": _log_identifier(admin_chat_id, prefix="chat"),
        "reconciled_event_id": event.event_id,
    }
    if event.event_type == PAYMENT_EVENT_SUCCESSFUL:
        payment = _payment_from_event(event, raw_payload)
        result = _apply_successful_payment(event.user_id, payment)
        return PaymentEventApplication(
            result.processed,
            PAYMENT_EVENT_SUCCESSFUL,
            product=_payment_product_for_grant(result.grant),
            duplicate=result.duplicate,
            reason=result.reason,
            status=(
                PAYMENT_EVENT_STATUS_PROCESSED
                if result.processed
                else PAYMENT_EVENT_STATUS_DUPLICATE
                if result.duplicate
                else PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE
            ),
        )
    if event.event_type in {
        PAYMENT_EVENT_REFUND,
        PAYMENT_EVENT_CHARGEBACK,
        PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
    }:
        return _apply_payment_event(
            event.user_id,
            event_type=event.event_type,
            provider=event.provider,
            charge_id=event.charge_id,
            amount=event.amount,
            currency=event.currency,
            raw_payload=raw_payload,
        )
    return PaymentEventApplication(
        False,
        event.event_type,
        reason="unsupported_reconciliation_event_type",
        status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
    )


def _payment_from_event(event: PaymentEvent, raw_payload: dict[str, object]) -> SuccessfulPayment:
    return SimpleNamespace(
        invoice_payload=str(raw_payload.get("invoice_payload") or ""),
        currency=str(event.currency or raw_payload.get("currency") or ""),
        total_amount=int(event.amount if event.amount is not None else raw_payload.get("total_amount") or 0),
        telegram_payment_charge_id=event.telegram_charge_id
        or str(raw_payload.get("telegram_payment_charge_id") or ""),
        provider_payment_charge_id=event.provider_charge_id
        or str(raw_payload.get("provider_payment_charge_id") or ""),
        is_recurring=bool(raw_payload.get("is_recurring", False)),
        is_first_recurring=bool(raw_payload.get("is_first_recurring", False)),
        subscription_expiration_date=raw_payload.get("subscription_expiration_date"),
    )  # type: ignore[return-value]


def _apply_successful_payment(
    user_id: int,
    payment: SuccessfulPayment,
    delivery_chat_id: int | None = None,
) -> PaymentApplication:
    decoded = decode_payment_order_payload(payment.invoice_payload)
    if decoded is not None:
        order_id, nonce = decoded
        return _apply_order_successful_payment(user_id, payment, order_id, nonce, delivery_chat_id)
    return _apply_legacy_successful_payment(user_id, payment)


def _apply_order_successful_payment(
    user_id: int,
    payment: SuccessfulPayment,
    order_id: str,
    nonce: str,
    delivery_chat_id: int | None,
) -> PaymentApplication:
    store = _postgres_store()
    if store is not None:
        return store.apply_order_payment(
            user_id,
            order_id=order_id,
            nonce=nonce,
            delivery_chat_id=delivery_chat_id,
            provider=_payment_provider_for_payment(payment),
            charge_id=_payment_charge_id(payment),
            telegram_charge_id=_payment_telegram_charge_id(payment),
            provider_charge_id=_payment_provider_charge_id(payment),
            amount=payment.total_amount,
            currency=payment.currency,
            raw_payload=_payment_raw_payload(payment),
            is_recurring_payment=bool(getattr(payment, "is_recurring", False)),
            is_first_recurring_payment=bool(getattr(payment, "is_first_recurring", False)),
            subscription_expiration_timestamp=getattr(payment, "subscription_expiration_date", None),
        )
    return _apply_file_order_successful_payment(user_id, payment, order_id, nonce, delivery_chat_id)


def _apply_file_order_successful_payment(
    user_id: int,
    payment: SuccessfulPayment,
    order_id: str,
    nonce: str,
    delivery_chat_id: int | None,
) -> PaymentApplication:
    with json_storage_transaction(*_json_storage_runtime_paths()):
        return _apply_file_order_successful_payment_locked(user_id, payment, order_id, nonce, delivery_chat_id)


def _apply_file_order_successful_payment_locked(
    user_id: int,
    payment: SuccessfulPayment,
    order_id: str,
    nonce: str,
    delivery_chat_id: int | None,
) -> PaymentApplication:
    state = load_payment_order_state(PAYMENT_ORDERS_STATE_FILE)
    order = state.orders.get(order_id)
    if order is None:
        _record_orphan_successful_payment(user_id, payment, "order_not_found")
        return PaymentApplication(False)

    grant = _payment_grant_for_order_product(order.product)
    charge_id = _payment_charge_id(payment)
    telegram_charge_id = _payment_telegram_charge_id(payment)
    provider_charge_id = _payment_provider_charge_id(payment)
    provider = _payment_provider_for_payment(payment)
    registry = _load_processed_payment_charge_registry()
    if charge_id and processed_payment_charge_exists(registry, provider=provider, charge_id=charge_id):
        return PaymentApplication(False, grant, duplicate=True)

    invalid_reason = _payment_order_success_invalid_reason(order, user_id, delivery_chat_id, nonce, payment)
    if invalid_reason is not None:
        _record_orphan_successful_payment(user_id, payment, invalid_reason)
        return PaymentApplication(False, grant)

    entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements.get(user_id, Entitlement())
    entitlement.expire_if_needed()
    if order.product != "subscription_month" and not entitlement.is_subscription_active():
        entitlements[user_id] = entitlement
        save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
        _record_orphan_successful_payment(user_id, payment, "extra_without_active_subscription")
        return PaymentApplication(False, grant)

    if not charge_id:
        _record_orphan_successful_payment(user_id, payment, "missing_charge_id")
        return PaymentApplication(False, grant)

    if order.product == "subscription_month":
        result = apply_subscription_payment(
            entitlement,
            f"{provider}:{charge_id}",
            subscription_expiration_timestamp=getattr(payment, "subscription_expiration_date", None),
        )
    elif order.product == "extra_one_day":
        result = apply_extra_one_day_payment(entitlement, f"{provider}:{charge_id}")
    elif order.product == "extra_weekly_pdf":
        result = apply_extra_weekly_pdf_payment(entitlement, f"{provider}:{charge_id}")
    else:
        _record_orphan_successful_payment(user_id, payment, "unknown_order_product")
        return PaymentApplication(False)

    if result.processed:
        if not _remember_processed_payment_charge(
            registry,
            user_id=user_id,
            provider=provider,
            charge_id=charge_id,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            kind=grant,
        ):
            return PaymentApplication(False, grant, duplicate=True)
        save_processed_payment_charge_state(_processed_payment_charges_state_file(), registry)
        state.orders[order.order_id] = order.mark_paid()
        save_payment_order_state(PAYMENT_ORDERS_STATE_FILE, state)
        _record_file_successful_payment_event(
            user_id=user_id,
            provider=provider,
            charge_id=charge_id,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            product=order.product,
            amount=payment.total_amount,
            currency=payment.currency,
            raw_payload={
                **_payment_raw_payload(payment),
                "payment_order": order.to_dict(),
            },
        )
    entitlements[user_id] = entitlement
    save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
    if result.processed:
        _reconcile_file_pending_payment_events_for_charge(
            user_id=user_id,
            provider=provider,
            charge_id=charge_id,
        )
    return result


def _apply_legacy_successful_payment(user_id: int, payment: SuccessfulPayment) -> PaymentApplication:
    if not _is_legacy_monthly_successful_payment(payment):
        _record_orphan_successful_payment(user_id, payment, "missing_pending_order")
        return PaymentApplication(False)

    store = _postgres_store()
    if store is not None:
        return store.apply_payment(
            user_id,
            provider=_payment_provider_for_payment(payment),
            charge_id=_payment_charge_id(payment),
            telegram_charge_id=_payment_telegram_charge_id(payment),
            provider_charge_id=_payment_provider_charge_id(payment),
            grant="subscription",
            amount=payment.total_amount,
            currency=payment.currency,
            raw_payload={
                **_payment_raw_payload(payment),
                "legacy_payload": True,
            },
            subscription_expiration_timestamp=getattr(payment, "subscription_expiration_date", None),
        )

    with json_storage_transaction(*_json_storage_runtime_paths()):
        charge_id = _payment_charge_id(payment)
        telegram_charge_id = _payment_telegram_charge_id(payment)
        provider_charge_id = _payment_provider_charge_id(payment)
        if not charge_id:
            _record_orphan_successful_payment(user_id, payment, "missing_charge_id")
            return PaymentApplication(False, "subscription")
        provider = _payment_provider_for_payment(payment)
        provider_charge_id = f"{provider}:{charge_id}"
        registry = _load_processed_payment_charge_registry()
        if processed_payment_charge_exists(registry, provider=provider, charge_id=charge_id):
            return PaymentApplication(False, "subscription", duplicate=True)
        entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
        entitlement = entitlements.get(user_id, Entitlement())
        result = apply_subscription_payment(
            entitlement,
            provider_charge_id,
            subscription_expiration_timestamp=getattr(payment, "subscription_expiration_date", None),
        )
        if result.processed:
            if not _remember_processed_payment_charge(
                registry,
                user_id=user_id,
                provider=provider,
                charge_id=charge_id,
                telegram_charge_id=telegram_charge_id,
                provider_charge_id=provider_charge_id,
                kind="subscription",
            ):
                return PaymentApplication(False, "subscription", duplicate=True)
            save_processed_payment_charge_state(_processed_payment_charges_state_file(), registry)
            _record_file_successful_payment_event(
                user_id=user_id,
                provider=provider,
                charge_id=charge_id,
                telegram_charge_id=telegram_charge_id,
                provider_charge_id=provider_charge_id,
                product="subscription_month",
                amount=payment.total_amount,
                currency=payment.currency,
                raw_payload={
                    **_payment_raw_payload(payment),
                    "legacy_payload": True,
                },
            )

        entitlements[user_id] = entitlement
        save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
        if result.processed:
            _reconcile_file_pending_payment_events_for_charge(
                user_id=user_id,
                provider=provider,
                charge_id=charge_id,
            )
        return result


def _is_legacy_monthly_successful_payment(payment: SuccessfulPayment) -> bool:
    if not _legacy_payment_payloads_enabled():
        return False
    return _is_legacy_monthly_payment(
        payload=payment.invoice_payload,
        currency=payment.currency,
        amount=payment.total_amount,
    )


def _payment_grant_for_order_product(product: PaymentProduct) -> PaymentGrant:
    if product == "extra_one_day":
        return "extra_one_day"
    if product == "extra_weekly_pdf":
        return "extra_weekly_pdf"
    return "subscription"


def _payment_product_for_grant(grant: PaymentGrant | None) -> str | None:
    if grant == "subscription":
        return "subscription_month"
    if grant in {"extra_one_day", "extra_weekly_pdf"}:
        return grant
    return None


def _payment_order_success_invalid_reason(
    order: PaymentOrder,
    user_id: int,
    delivery_chat_id: int | None,
    nonce: str,
    payment: SuccessfulPayment,
) -> str | None:
    if order.nonce != nonce:
        return "nonce_mismatch"
    if order.user_id != user_id:
        return "user_mismatch"
    if (
        delivery_chat_id is not None
        and order.delivery_chat_id is not None
        and order.delivery_chat_id != delivery_chat_id
    ):
        return "chat_mismatch"
    if order.provider != _payment_provider_for_payment(payment):
        return "provider_mismatch"
    if order.amount != payment.total_amount:
        return "amount_mismatch"
    if order.currency != payment.currency:
        return "currency_mismatch"
    # Successful payments approved by pre_checkout are accepted even if the order TTL expires
    # before Telegram sends successful_payment. The smoke test
    # test_successful_payment_grants_when_order_expires_after_pre_checkout pins this.
    if order.status == "pending":
        return None
    if _order_accepts_recurring_successful_payment(order, payment):
        return None
    return "order_not_pending"


def _order_accepts_recurring_successful_payment(order: PaymentOrder, payment: SuccessfulPayment) -> bool:
    return (
        order.status == "paid"
        and order.is_recurring
        and order.product == "subscription_month"
        and order.provider == "telegram_stars"
        and bool(getattr(payment, "is_recurring", False))
        and not bool(getattr(payment, "is_first_recurring", False))
    )


def _record_orphan_successful_payment(user_id: int, payment: SuccessfulPayment, reason: str) -> None:
    raw_payload = {
        **_payment_raw_payload(payment),
        "orphan_reason": reason,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    provider = _payment_provider_for_payment(payment)
    charge_id = _payment_charge_id(payment)
    telegram_charge_id = _payment_telegram_charge_id(payment)
    provider_charge_id = _payment_provider_charge_id(payment)
    store = _postgres_store()
    if store is not None:
        store.record_orphan_payment(
            user_id,
            provider=provider,
            charge_id=charge_id,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            amount=payment.total_amount,
            currency=payment.currency,
            raw_payload=raw_payload,
            reason=reason,
        )
        return
    with json_storage_transaction(*_json_storage_runtime_paths()):
        _record_file_orphan_payment_event(
            user_id=user_id,
            provider=provider,
            charge_id=charge_id,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            amount=payment.total_amount,
            currency=payment.currency,
            reason=reason,
            raw_payload=raw_payload,
        )
        record_file_orphan_payment(
            PAYMENT_ORDERS_STATE_FILE,
            {
                "chat_hash": _log_identifier(user_id, prefix="chat"),
                "user_hash": _log_identifier(user_id, prefix="tg"),
                "provider": provider,
                "charge_id": charge_id,
                "telegram_charge_id": telegram_charge_id,
                "provider_charge_id": provider_charge_id,
                "amount": payment.total_amount,
                "currency": payment.currency,
                "reason": reason,
                "raw_payload": raw_payload,
            },
        )


def _payment_success_text(result: PaymentApplication) -> str:
    if result.grant == "subscription":
        return "Подписка активна. Лимиты на этот месяц обновлены."
    if result.grant == "extra_one_day":
        return "Готово: добавлена 1 попытка для дневного рациона."
    if result.grant == "extra_weekly_pdf":
        return "Готово: добавлена 1 попытка для недельного PDF."
    return "Платеж обработан."


def _payment_event_result_text(user_id: int, result: PaymentEventApplication) -> str:
    if result.duplicate:
        return (
            "Это платежное событие уже было обработано. Доступ и лимиты не изменились.\n\n"
            f"{_format_entitlement_status(user_id)}"
        )
    if result.processed and result.event_type == PAYMENT_EVENT_REFUND:
        return (
            "Возврат платежа обработан. Мы обновили доступ и списали связанные лимиты.\n\n"
            f"{_format_entitlement_status(user_id)}"
        )
    if result.processed and result.event_type == PAYMENT_EVENT_CHARGEBACK:
        return (
            "Банк сообщил об оспаривании платежа. Доступ и связанные лимиты обновлены.\n\n"
            f"{_format_entitlement_status(user_id)}"
        )
    if result.processed and result.event_type == PAYMENT_EVENT_CANCEL_SUBSCRIPTION:
        return (
            "Отмена подписки зафиксирована. Уже оплаченный период доступа сохранен до текущей даты окончания.\n\n"
            f"{_format_entitlement_status(user_id)}"
        )
    if result.reason == "extra_already_consumed":
        return (
            "Платежное событие получено, но связанный extra-лимит уже был использован. Доступ и лимиты не изменились.\n\n"
            f"{_format_entitlement_status(user_id)}"
        )
    if result.reason == "original_payment_not_found":
        return (
            "Получили платежное событие, но не нашли связанную покупку. Доступ не изменился; "
            "если это ошибка, напишите в поддержку."
        )
    return "Получили платежное событие, но оно не изменило доступ."


def _activate_promo_code_for_chat(chat_id: int, promo_code: str) -> PromoCodeActivation:
    store = _postgres_store()
    if store is not None:
        return store.activate_promo_code(chat_id, promo_code)

    with json_storage_transaction(*_json_storage_runtime_paths()):
        activation = activate_promo_code(PROMO_CODES_STATE_FILE, promo_code, chat_id)
        if not activation.activated:
            return activation

        entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
        entitlement = entitlements.get(chat_id, Entitlement())
        apply_subscription_payment(entitlement, f"promo:{activation.lookup_key or promo_code_lookup_key(activation.code)}")
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
    user = _effective_message_user(message)
    user_id = getattr(user, "id", None)
    return user_id if isinstance(user_id, int) else None


def _effective_message_user(message: Message) -> Any | None:
    return EFFECTIVE_INTERACTION_USER.get() or getattr(message, "from_user", None)


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
    store = _postgres_store()
    if store is not None:
        return store.grant_test_access_to_chat(chat_id, now=now)

    with json_storage_transaction(*_json_storage_runtime_paths()):
        entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
        entitlement = entitlements.get(chat_id, Entitlement())
        grant_test_access(entitlement, now=now)
        entitlements[chat_id] = entitlement
        save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
        return entitlement


def _revoke_test_access_for_chat(chat_id: int) -> Entitlement:
    store = _postgres_store()
    if store is not None:
        return store.revoke_test_access_for_chat(chat_id)

    with json_storage_transaction(*_json_storage_runtime_paths()):
        entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
        entitlement = entitlements.get(chat_id, Entitlement())
        revoke_test_access(entitlement)
        entitlements[chat_id] = entitlement
        save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
        return entitlement


def _set_test_access_mode(chat_id: int, enabled: bool) -> tuple[bool, Entitlement]:
    store = _postgres_store()
    if store is not None:
        return store.set_test_access_mode(chat_id, enabled)

    with json_storage_transaction(*_json_storage_runtime_paths()):
        entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
        entitlement = entitlements.get(chat_id, Entitlement())
        changed = set_test_access_enabled(entitlement, enabled)
        entitlements[chat_id] = entitlement
        save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)
        return changed, entitlement


def _has_test_access(chat_id: int, entitlement: Entitlement | None = None) -> bool:
    return _dev_tester_override_enabled(chat_id) or bool(entitlement and entitlement.is_test_access_active())


def _dev_tester_override_enabled(chat_id: int) -> bool:
    return chat_id in TESTER_CHAT_IDS and not _is_production_environment()


def _is_free_preview_mode(chat_id: int, entitlement: Entitlement | None = None) -> bool:
    if _dev_tester_override_enabled(chat_id):
        return False
    entitlement = entitlement or _entitlement_for_chat(chat_id)
    return entitlement.is_test_access_available() and not entitlement.test_access_enabled


def _has_active_paid_access(chat_id: int, entitlement: Entitlement | None = None) -> bool:
    entitlement = entitlement or _entitlement_for_chat(chat_id)
    if _is_free_preview_mode(chat_id, entitlement):
        return False
    return _has_test_access(chat_id, entitlement) or entitlement.is_subscription_active()


def _has_monthly_limits_remaining(entitlement: Entitlement) -> bool:
    return (
        entitlement.monthly_one_day_remaining > 0
        or entitlement.monthly_weekly_pdf_remaining > 0
    )


def _format_test_access_command_status(chat_id: int) -> str:
    command = _test_access_command_token()
    if _dev_tester_override_enabled(chat_id):
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
            + f"\nКоманда для бесплатного режима: {command} off"
        )
    return (
        "Тестовый режим выключен. Сейчас вы видите бесплатный сценарий."
        + until_text
        + f"\nКоманда для платного режима: {command} on"
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
    store = _postgres_store()
    if store is not None:
        return store.consume_generation_attempt(chat_id, ration_kind)

    if _dev_tester_override_enabled(chat_id):
        return AttemptConsumption(True, ration_kind, "test_access")

    with json_storage_transaction(*_json_storage_runtime_paths()):
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
    store = _postgres_store()
    if store is not None:
        store.refund_generation_attempt(chat_id, consumption)
        return

    with json_storage_transaction(*_json_storage_runtime_paths()):
        entitlements = load_entitlements(SUBSCRIPTIONS_STATE_FILE)
        entitlement = entitlements.get(chat_id, Entitlement())
        refund_attempt(entitlement, consumption)
        entitlements[chat_id] = entitlement
        save_entitlements(SUBSCRIPTIONS_STATE_FILE, entitlements)


def _heartbeat_generation_attempt(chat_id: int, consumption: AttemptConsumption) -> bool:
    store = _postgres_store()
    if store is not None:
        return store.heartbeat_generation_attempt(chat_id, consumption)
    return True


def _start_generation_delivery(chat_id: int, consumption: AttemptConsumption) -> bool:
    store = _postgres_store()
    if store is not None:
        return store.start_generation_delivery(chat_id, consumption)
    return True


def _complete_generation_attempt(
    chat_id: int,
    consumption: AttemptConsumption,
    *,
    telegram_message_id: int | None = None,
) -> None:
    store = _postgres_store()
    if store is not None:
        store.complete_generation_attempt(
            chat_id,
            consumption,
            telegram_message_id=telegram_message_id,
        )


def _entitlement_for_chat(chat_id: int) -> Entitlement:
    store = _postgres_store()
    if store is not None:
        return store.get_entitlement(chat_id)

    with json_storage_transaction(*_json_storage_runtime_paths()):
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
    owner_id = _message_owner_id(message)
    entitlement = await _run_storage_io(_entitlement_for_chat, owner_id)
    has_active_subscription = (
        entitlement.is_subscription_active()
        and not _is_free_preview_mode(owner_id, entitlement)
    )
    has_monthly_limits_remaining = _has_monthly_limits_remaining(entitlement)
    status_text = await _run_storage_io(_format_entitlement_status, owner_id)
    lines = [
        "Лимит для этого типа рациона закончился.",
        "",
        status_text,
    ]
    next_renewal = (
        None
        if _is_free_preview_mode(owner_id, entitlement)
        else _format_next_renewal_line(entitlement)
    )
    if next_renewal:
        lines.extend(["", next_renewal])
    if has_active_subscription:
        if has_monthly_limits_remaining:
            limit_text = "Можно дождаться следующего обновления подписки или купить разовую попытку."
            reply_markup = _paywall_keyboard(preferred=ration_kind)
        else:
            limit_text = "Лимиты текущего периода закончились. Можно купить разовую попытку или оформить следующий месяц."
            reply_markup = _paywall_keyboard(preferred=ration_kind, include_subscription=True)
        lines.extend(
            [
                "",
                limit_text,
            ],
        )
    else:
        lines.extend(
            [
                "",
                "Чтобы продолжить, оформите месячный доступ.",
            ],
        )
        reply_markup = _subscription_payment_keyboard()
    await _track_event_async(
        owner_id,
        "paywall_shown",
        {
            "source": "generation_denial",
            "ration_kind": ration_kind,
            "has_active_subscription": has_active_subscription,
            "has_monthly_limits_remaining": has_monthly_limits_remaining,
        },
    )
    await safe_answer(message, 
        "\n".join(lines),
        reply_markup=reply_markup,
    )


def _subscription_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button(text=PAY_WITH_RU_CARD_TEXT, callback_data=CALLBACK_PAY_RU_CARD, style=BUTTON_STYLE_SUCCESS)],
            [
                _inline_button(
                    text=PAY_WITH_TELEGRAM_STARS_TEXT,
                    callback_data=CALLBACK_PAY_TELEGRAM_STARS,
                    style=BUTTON_STYLE_SUCCESS,
                )
            ],
            *_payment_guardrail_keyboard_rows(),
        ],
    )


def _paywall_keyboard(*, preferred: str, include_subscription: bool = False) -> InlineKeyboardMarkup:
    extra_one_day_stars_button = _inline_button(
        text=BUY_EXTRA_ONE_DAY_TEXT,
        callback_data=CALLBACK_BUY_EXTRA_ONE_DAY,
        style=BUTTON_STYLE_SUCCESS,
    )
    extra_one_day_card_button = _inline_button(
        text=BUY_EXTRA_ONE_DAY_RU_CARD_TEXT,
        callback_data=CALLBACK_PAY_RU_EXTRA_ONE_DAY,
        style=BUTTON_STYLE_SUCCESS,
    )
    extra_weekly_pdf_stars_button = _inline_button(
        text=BUY_EXTRA_WEEKLY_PDF_TEXT,
        callback_data=CALLBACK_BUY_EXTRA_WEEKLY_PDF,
        style=BUTTON_STYLE_SUCCESS,
    )
    extra_weekly_pdf_card_button = _inline_button(
        text=BUY_EXTRA_WEEKLY_PDF_RU_CARD_TEXT,
        callback_data=CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF,
        style=BUTTON_STYLE_SUCCESS,
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
    inline_keyboard = [
        [extra_buttons[0]],
        [extra_buttons[1]],
        [extra_buttons[2]],
        [extra_buttons[3]],
    ]
    if include_subscription:
        inline_keyboard.extend(_subscription_payment_keyboard().inline_keyboard)
    else:
        inline_keyboard.extend(_payment_guardrail_keyboard_rows())
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def _trial_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button(text=SUBSCRIBE_CTA_TEXT, callback_data=CALLBACK_SUBSCRIBE, style=BUTTON_STYLE_SUCCESS)],
        ],
    )


def _after_plan_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    if chat_id is not None:
        entitlement = _entitlement_for_chat(chat_id)
        if _has_active_paid_access(chat_id, entitlement):
            return _subscriber_cabinet_keyboard(chat_id, entitlement=entitlement)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button(text=REPEAT_PLAN_TEXT, callback_data=CALLBACK_REPEAT, style=BUTTON_STYLE_PRIMARY)],
            [_inline_button(text=NEW_PROFILE_TEXT, callback_data=CALLBACK_NEW, style=BUTTON_STYLE_DANGER)],
            [_inline_button(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _plan_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button(text=ONE_DAY_PLAN_TEXT, callback_data=CALLBACK_ONE_DAY_PLAN, style=BUTTON_STYLE_PRIMARY)],
            [_inline_button(text=WEEK_PLAN_PDF_TEXT, callback_data=CALLBACK_WEEK_PLAN_PDF, style=BUTTON_STYLE_PRIMARY)],
            [_inline_button(text=CHANGE_PROFILE_TEXT, callback_data=CALLBACK_NEW, style=BUTTON_STYLE_DANGER)],
            [_inline_button(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _question_keyboard(session: QuestionnaireSession) -> InlineKeyboardMarkup | None:
    question = session.current_question
    if not question or not question.options:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=option,
                    callback_data=f"{CALLBACK_ANSWER_PREFIX}{session.session_id}:{question.key}:{index}",
                )
            ]
            for index, option in enumerate(question.options)
        ],
    )


async def _send_welcome_photo(message: Message) -> None:
    if not WELCOME_PHOTO_PATH.exists():
        return
    try:
        await safe_answer_photo(message, photo=FSInputFile(WELCOME_PHOTO_PATH))
    except TelegramAPIError:
        return


async def _send_meal_card(message: Message, meal: Meal) -> Message | None:
    text = format_meal_card(meal, include_photo_credit=bool(meal.image_attribution))
    photo = _photo_input(meal)
    if photo is None:
        return await _send_text_chunks(message, text)

    try:
        if len(text) <= 1024:
            return await safe_answer_photo(message, photo=photo, caption=text)
        sent_message = await safe_answer_photo(message, photo=photo)
    except TelegramAPIError:
        return await _send_text_chunks(message, text)

    return await _send_text_chunks(message, text) or sent_message


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
) -> Message | None:
    chunks = _telegram_chunks(text)
    sent_message = None
    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        sent_message = await safe_answer(message, chunk, reply_markup=markup)
    return sent_message


if __name__ == "__main__":
    main()
