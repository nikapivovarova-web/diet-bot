from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
import math
import os
import random
import re
import secrets
import time
from collections import Counter, defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import RLock

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

from .builder import (
    CookingEffortConstraints,
    _RecipePlanCache,
    _cooking_effort_constraints,
    _finalize_recipe_meals,
    _food_by_id_cache_key,
    _meal_emoji,
    _meal_energy_slots,
    _meal_name,
    _passes_hard_nutrition_gates,
    _recipe_matches_cooking_effort_cached,
    _recipe_memory_key_cached,
    _recipe_scale,
    _recipe_slot_eligibility_cached,
    _recipe_title_uses_excluded_food,
    _resolve_recipe_ingredients,
    _scaled_recipe_portions,
    build_one_day_plan,
    filter_foods,
    recipe_plan_diagnostic_context,
)
from .catalog import built_in_foods
from .calculator import calculate_targets
from .chat_state_storage import ChatStateStorageError
from .chat_state_runtime import (
    ChatStateStore,
    create_chat_state_store,
    validate_chat_state_store_for_startup,
)
from .db_executor import DbExecutorBusy, run_db_call
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
    NutrientVector,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
    normalize_cooking_time_preference,
)
from .presentation import (
    format_calculation_summary,
    format_daily_totals,
    format_meal_card,
    format_plan_messages,
    format_week_shopping_list,
)
from .pdf_renderer import build_week_plan_pdf
from .curated_data import curated_recipes
from .recipe_catalog import RecipeTemplate, built_in_recipes
from .recipe_traits import RecipeTraits, infer_recipe_traits
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
    release_promo_code_activation,
    save_promo_codes,
)
from .questionnaire import QuestionnaireSession, start_session
from .runtime_config import (
    DEFAULT_PROMO_CODES_STATE_FILE,
    DEFAULT_STATE_FILE,
    DEFAULT_SUBSCRIPTIONS_STATE_FILE,
    load_runtime_config,
    parse_id_set as _parse_runtime_id_set,
    parse_optional_int as _parse_runtime_optional_int,
    validate_startup,
    weekly_selection_diagnostics_enabled,
)
from .sales_followup import (
    DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
    SALES_FOLLOWUP_OPT_OUT_CALLBACK_DATA,
    build_sales_followup_trigger_idempotency_key,
    render_sales_followup_payload,
    schedule_sales_followup_after_free_trial_delivery,
)
from .sales_followup_runtime import (
    SalesFollowupEligibility,
    SalesFollowupPermanentSendError,
    SalesFollowupSendRequest,
    SalesFollowupSendResult,
    SalesFollowupTransientSendError,
    SalesFollowupUnknownSendOutcome,
    SalesFollowupWorker,
    SalesFollowupWorkerSettings,
    SalesFollowupJobRuntime,
)
from .safety import evaluate_safety
from .entitlement_runtime import create_entitlement_store, validate_entitlement_store_for_startup
from .entitlement_service import EntitlementService
from .entitlement_storage import EntitlementStorageError
from .log_redaction import redact_identifier, redact_log_identifiers
from .payment_runtime import (
    PaymentLedgerUnavailable,
    create_payment_service,
    validate_payment_runtime_for_startup,
)
from .payment_recovery_spool import PaymentRecoveryRecord, append_payment_recovery_record
from .one_day_generation_job_runtime import (
    OneDayGenerationDelivery,
    OneDayGenerationJobRuntime,
    OneDayGenerationValueMessage,
    OneDayGenerationWorker,
    OneDayGenerationWorkerSettings,
    validate_one_day_generation_job_store_for_startup,
)
from .one_day_generation_jobs import (
    OneDayGenerationJob,
    OneDayGenerationRequestSnapshot,
    QueuedJobAdmissionResultStatus as OneDayQueuedJobAdmissionResultStatus,
)
from .payments import (
    PRODUCT_EXTRA_ONE_DAY,
    PRODUCT_EXTRA_WEEKLY_PDF,
    PRODUCT_SUBSCRIPTION_MONTH,
    PROVIDER_TELEGRAM_STARS,
    PROVIDER_YOOKASSA,
    PaymentHandlingResult,
    PaymentOrder,
    decode_payment_order_payload,
    encode_payment_order_payload,
)
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
from .telegram_send import TelegramSendError, TelegramSendFailureClass, safe_telegram_send
from .telegram_media_validation import (
    TELEGRAM_CAPTION_MAX_CHARS,
    TELEGRAM_DOCUMENT_MAX_BYTES,
    TELEGRAM_MESSAGE_CHUNK_MAX_CHARS,
    TelegramMediaValidationError,
    telegram_text_chunks,
    validate_local_pdf_document_path,
    validate_local_photo_path,
    validate_pdf_document_bytes,
    validate_telegram_caption,
)
from .validation import validate_plan
from .weekly_pdf_job_runtime import (
    WeeklyPdfDelivery,
    WeeklyPdfJobRuntime,
    WeeklyPdfWorker,
    WeeklyPdfWorkerSettings,
    validate_weekly_pdf_job_runtime_for_startup,
)
from .weekly_pdf_jobs import (
    AdmitJobResultStatus,
    FinishJobResultStatus,
    MarkSendStartedResultStatus,
    QueuedJobAdmissionResultStatus as WeeklyPdfQueuedJobAdmissionResultStatus,
    StartJobResultStatus,
    WeeklyPdfJob,
    WeeklyPdfRequestSnapshot,
)


SESSION_BY_CHAT_ID: dict[int, QuestionnaireSession] = {}
QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID: dict[int, str] = {}
_QUESTIONNAIRE_CALLBACK_LOCK_BY_CHAT_ID: dict[int, asyncio.Lock] = {}
PRIVACY_CONSENT_CHAT_IDS: set[int] = set()
TRIAL_CHAT_IDS: set[int] = set()
PROFILE_BY_CHAT_ID: dict[int, UserProfile] = {}
PLAN_COUNT_BY_CHAT_ID: dict[int, int] = {}
PLAN_SEED_OFFSET_BY_CHAT_ID: dict[int, int] = {}
RECENT_RECIPE_IDS_BY_CHAT_ID: dict[int, list[str]] = {}
RECENT_RECIPE_KEYS_BY_CHAT_ID: dict[int, list[str]] = {}
SUPPORT_REQUEST_CHAT_IDS: set[int] = set()
PROMO_CODE_REQUEST_CHAT_IDS: set[int] = set()
ADMIN_PROMO_ACTION_BY_CHAT_ID: dict[int, str] = {}
router = Router()
ADMIN_ACCESS_PROMO_CODE_RETRY_LIMIT = 20
ADMIN_PROMO_ACTION_CREATE_DISCOUNT = "create_discount"
ADMIN_PROMO_ACTION_DISABLE_DISCOUNT = "disable_discount"
RECENT_RECIPE_HISTORY_DAYS = 28
RECENT_RECIPE_HISTORY_LIMIT = 140
RECENT_RECIPE_REDUCED_DAYS = 14
RECENT_RECIPE_REDUCED_LIMIT = 70
logger = logging.getLogger(__name__)
ENTITLEMENT_STORAGE_ERROR_TEXT = "Не удалось проверить доступ. Попробуйте позже."
CHAT_PROFILE_STORAGE_ERROR_TEXT = "Не удалось сохранить анкету. Попробуйте позже."
CHAT_STATE_READ_ERROR_TEXT = "Не удалось загрузить данные чата. Попробуйте позже."
PRIVACY_CONSENT_STORAGE_ERROR_TEXT = "Не удалось сохранить согласие. Попробуйте позже."


def _entitlement_service() -> EntitlementService:
    config = replace(load_runtime_config(), subscriptions_state_file=SUBSCRIPTIONS_STATE_FILE)
    return EntitlementService(create_entitlement_store(config))


def _postgres_promo_store(config):
    if not config.database_url:
        raise EntitlementStorageError("Postgres promo store requires DIET_BOT_DATABASE_URL.")
    from .postgres_promo_store import PostgresPromoStore

    return PostgresPromoStore(
        config.database_url,
        connect_timeout=config.postgres_connect_timeout,
    )


def _payment_service():
    return create_payment_service(load_runtime_config())


_WEEKLY_PDF_JOB_RUNTIME_NOT_LOADED = object()
_WEEKLY_PDF_JOB_RUNTIME: WeeklyPdfJobRuntime | None | object = _WEEKLY_PDF_JOB_RUNTIME_NOT_LOADED


def _weekly_pdf_job_runtime() -> WeeklyPdfJobRuntime | None:
    global _WEEKLY_PDF_JOB_RUNTIME
    if _WEEKLY_PDF_JOB_RUNTIME is _WEEKLY_PDF_JOB_RUNTIME_NOT_LOADED:
        _WEEKLY_PDF_JOB_RUNTIME = WeeklyPdfJobRuntime.from_config(load_runtime_config())
    if _WEEKLY_PDF_JOB_RUNTIME is None:
        return None
    return _WEEKLY_PDF_JOB_RUNTIME  # type: ignore[return-value]


_ONE_DAY_GENERATION_JOB_RUNTIME_NOT_LOADED = object()
_ONE_DAY_GENERATION_JOB_RUNTIME: OneDayGenerationJobRuntime | None | object = (
    _ONE_DAY_GENERATION_JOB_RUNTIME_NOT_LOADED
)


def _one_day_generation_job_runtime() -> OneDayGenerationJobRuntime | None:
    global _ONE_DAY_GENERATION_JOB_RUNTIME
    if _ONE_DAY_GENERATION_JOB_RUNTIME is _ONE_DAY_GENERATION_JOB_RUNTIME_NOT_LOADED:
        _ONE_DAY_GENERATION_JOB_RUNTIME = OneDayGenerationJobRuntime.from_config(load_runtime_config())
    if _ONE_DAY_GENERATION_JOB_RUNTIME is None:
        return None
    return _ONE_DAY_GENERATION_JOB_RUNTIME  # type: ignore[return-value]


_SALES_FOLLOWUP_STORE_NOT_LOADED = object()
_SALES_FOLLOWUP_STORE: object | None = _SALES_FOLLOWUP_STORE_NOT_LOADED


def _sales_followup_runtime_enabled() -> bool:
    return bool(getattr(load_runtime_config(), "sales_followup_enabled", False))


def _sales_followup_store():
    global _SALES_FOLLOWUP_STORE
    config = load_runtime_config()
    if not getattr(config, "sales_followup_enabled", False):
        return None
    if getattr(config, "storage_backend", "json") != "postgres" or not getattr(config, "database_url", None):
        return None
    if _SALES_FOLLOWUP_STORE is _SALES_FOLLOWUP_STORE_NOT_LOADED:
        from .postgres_connection import get_shared_postgres_connection_provider
        from .postgres_sales_followup_store import PostgresSalesFollowupStore

        _SALES_FOLLOWUP_STORE = PostgresSalesFollowupStore(
            str(config.database_url),
            connect_timeout=int(getattr(config, "postgres_connect_timeout", 5)),
            connection_provider=get_shared_postgres_connection_provider(config),
        )
    return _SALES_FOLLOWUP_STORE


_SALES_FOLLOWUP_JOB_RUNTIME_NOT_LOADED = object()
_SALES_FOLLOWUP_JOB_RUNTIME: SalesFollowupJobRuntime | None | object = _SALES_FOLLOWUP_JOB_RUNTIME_NOT_LOADED


def _sales_followup_job_runtime() -> SalesFollowupJobRuntime | None:
    global _SALES_FOLLOWUP_JOB_RUNTIME
    if _SALES_FOLLOWUP_JOB_RUNTIME is _SALES_FOLLOWUP_JOB_RUNTIME_NOT_LOADED:
        _SALES_FOLLOWUP_JOB_RUNTIME = SalesFollowupJobRuntime.from_config(load_runtime_config())
    if _SALES_FOLLOWUP_JOB_RUNTIME is None:
        return None
    return _SALES_FOLLOWUP_JOB_RUNTIME  # type: ignore[return-value]


def _validate_entitlement_storage(config) -> None:
    store = create_entitlement_store(config)
    validate_entitlement_store_for_startup(config, store)


async def _send_entitlement_storage_error(message: Message) -> None:
    await message.answer(ENTITLEMENT_STORAGE_ERROR_TEXT)


async def _send_chat_profile_storage_error(message: Message) -> None:
    await message.answer(CHAT_PROFILE_STORAGE_ERROR_TEXT)


async def _send_chat_state_read_error(
    message: Message,
    *,
    status_message: Message | None = None,
) -> None:
    if status_message is not None:
        try:
            await status_message.edit_text(CHAT_STATE_READ_ERROR_TEXT)
            return
        except Exception:
            logger.exception(
                "Failed to edit chat state read error notice for chat_id=%s",
                _mask_chat_id(message.chat.id),
            )
    await message.answer(CHAT_STATE_READ_ERROR_TEXT)


async def _run_entitlement_db_call(func: Callable[..., object], /, *args: object, **kwargs: object) -> object:
    if not _should_dispatch_storage_db_calls():
        return func(*args, **kwargs)
    try:
        return await run_db_call(func, *args, **kwargs)
    except DbExecutorBusy as exc:
        logger.warning("DB executor is busy during entitlement operation: %s", getattr(func, "__name__", func))
        raise EntitlementStorageError("DB executor is busy.") from exc


async def _run_chat_state_db_call(func: Callable[..., object], /, *args: object, **kwargs: object) -> object:
    if not _should_dispatch_storage_db_calls():
        return func(*args, **kwargs)
    try:
        return await run_db_call(func, *args, **kwargs)
    except DbExecutorBusy as exc:
        logger.warning("DB executor is busy during chat state operation: %s", getattr(func, "__name__", func))
        raise ChatStateStorageError("DB executor is busy.") from exc


async def _run_sales_followup_db_call(func: Callable[..., object], /, *args: object, **kwargs: object) -> object:
    if not _should_dispatch_storage_db_calls():
        return func(*args, **kwargs)
    try:
        return await run_db_call(func, *args, **kwargs)
    except DbExecutorBusy as exc:
        logger.warning("DB executor is busy during sales follow-up operation: %s", getattr(func, "__name__", func))
        raise RuntimeError("Sales follow-up DB executor is busy.") from exc


def _cancel_sales_followup_after_access_grant(chat_id: int, *, reason: str) -> None:
    store = _sales_followup_store()
    if store is None:
        return
    cancel_jobs = getattr(store, "cancel_active_jobs_for_chat_campaign", None)
    if not callable(cancel_jobs):
        return
    try:
        cancel_jobs(
            chat_id=int(chat_id),
            campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
            reason=reason,
            chain_status="cancelled",
        )
    except Exception:
        logger.exception(
            "Failed to cancel sales follow-up jobs after access grant chat_id=%s reason=%s",
            _mask_chat_id(chat_id),
            reason,
        )


async def _cancel_sales_followup_after_access_grant_async(chat_id: int, *, reason: str) -> None:
    store = _sales_followup_store()
    if store is None:
        return
    cancel_jobs = getattr(store, "cancel_active_jobs_for_chat_campaign", None)
    if not callable(cancel_jobs):
        return
    try:
        await _run_sales_followup_db_call(
            cancel_jobs,
            chat_id=int(chat_id),
            campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
            reason=reason,
            chain_status="cancelled",
        )
    except Exception:
        logger.exception(
            "Failed to cancel sales follow-up jobs after access grant chat_id=%s reason=%s",
            _mask_chat_id(chat_id),
            reason,
        )


def _should_dispatch_storage_db_calls() -> bool:
    return load_runtime_config().storage_backend == "postgres"


async def _profile_for_chat_async(chat_id: int) -> UserProfile | None:
    return await _run_chat_state_db_call(_profile_for_chat, chat_id)  # type: ignore[return-value]


async def _load_chat_history_async(chat_id: int) -> None:
    await _run_chat_state_db_call(_load_chat_history, chat_id)


async def _save_chat_profile_async(chat_id: int, profile: UserProfile) -> None:
    await _run_chat_state_db_call(_save_chat_profile, chat_id, profile)


async def _has_privacy_consent_async(chat_id: int) -> bool:
    return await _run_chat_state_db_call(_has_privacy_consent, chat_id)  # type: ignore[return-value]


async def _save_privacy_consent_async(chat_id: int) -> None:
    await _run_chat_state_db_call(_save_privacy_consent, chat_id)


async def _load_recent_recipe_avoidance_async(chat_id: int) -> _RecentRecipeAvoidance:
    return await _run_chat_state_db_call(_load_recent_recipe_avoidance, chat_id)  # type: ignore[return-value]


async def _remember_recipe_history_items_best_effort_async(
    chat_id: int,
    entries: Sequence[RecipeHistoryItem],
    *,
    ration_kind: RationKind,
    context: str,
) -> None:
    try:
        await _run_chat_state_db_call(
            _remember_recipe_history_items_best_effort,
            chat_id,
            entries,
            ration_kind=ration_kind,
            context=context,
        )
    except ChatStateStorageError:
        logger.exception(
            "Failed to save recipe history in delivery context chat_id=%s ration_kind=%s context=%s entries=%d",
            _mask_chat_id(chat_id),
            ration_kind,
            context,
            len(entries),
        )


async def _record_successful_generation_history_async(
    chat_id: int,
    consumption: AttemptConsumption,
    entries: Sequence[RecipeHistoryItem],
) -> None:
    try:
        await _run_chat_state_db_call(_record_successful_generation_history, chat_id, consumption, entries)
    except ChatStateStorageError:
        logger.exception(
            "Failed to save successful generation history chat_id=%s ration_kind=%s entries=%d",
            _mask_chat_id(chat_id),
            consumption.ration_kind,
            len(entries),
        )


async def _format_entitlement_status_async(chat_id: int) -> str:
    return await _run_entitlement_db_call(_format_entitlement_status, chat_id)  # type: ignore[return-value]


async def _has_active_paid_access_async(chat_id: int) -> bool:
    return await _run_entitlement_db_call(_has_active_paid_access, chat_id)  # type: ignore[return-value]


async def _subscriber_cabinet_text_async(chat_id: int) -> str:
    return await _run_entitlement_db_call(_subscriber_cabinet_text, chat_id)  # type: ignore[return-value]


async def _subscriber_cabinet_keyboard_async(chat_id: int) -> InlineKeyboardMarkup:
    return await _run_entitlement_db_call(_subscriber_cabinet_keyboard, chat_id)  # type: ignore[return-value]


async def _main_menu_keyboard_async(chat_id: int) -> InlineKeyboardMarkup:
    return await _run_entitlement_db_call(_main_menu_keyboard, chat_id)  # type: ignore[return-value]


async def _ration_choice_keyboard_for_chat_async(chat_id: int) -> InlineKeyboardMarkup:
    return await _run_entitlement_db_call(_ration_choice_keyboard_for_chat, chat_id)  # type: ignore[return-value]


async def _payment_result_keyboard_async(chat_id: int, result: PaymentApplication) -> InlineKeyboardMarkup:
    return await _run_entitlement_db_call(_payment_result_keyboard, chat_id, result)  # type: ignore[return-value]


async def _weekly_pdf_attempt_available_async(chat_id: int) -> bool:
    return await _run_entitlement_db_call(_weekly_pdf_attempt_available, chat_id)  # type: ignore[return-value]


async def _consume_generation_attempt_async(chat_id: int, ration_kind: RationKind) -> AttemptConsumption:
    return await _run_entitlement_db_call(_consume_generation_attempt, chat_id, ration_kind)  # type: ignore[return-value]


async def _refund_generation_attempt_async(chat_id: int, consumption: AttemptConsumption) -> None:
    await _run_entitlement_db_call(_refund_generation_attempt, chat_id, consumption)


async def _is_valid_pre_checkout_async(pre_checkout_query: PreCheckoutQuery) -> bool:
    try:
        return await run_db_call(_is_valid_pre_checkout, pre_checkout_query)
    except DbExecutorBusy:
        logger.warning("DB executor is busy during pre_checkout validation")
        return False


async def _apply_successful_payment_async(
    chat_id: int,
    payment: SuccessfulPayment,
    *,
    user_id: int | None,
) -> PaymentApplication:
    try:
        return await run_db_call(_apply_successful_payment, chat_id, payment, user_id=user_id)
    except DbExecutorBusy as exc:
        logger.warning("DB executor is busy during successful_payment application")
        raise PaymentLedgerUnavailable("db_executor_busy", "Payment DB executor is busy.") from exc


async def _load_profile_for_message_or_notice(message: Message) -> tuple[bool, UserProfile | None]:
    try:
        return True, await _profile_for_chat_async(message.chat.id)
    except ChatStateStorageError:
        logger.exception("Failed to load chat profile for chat_id=%s", _mask_chat_id(message.chat.id))
        await _send_chat_state_read_error(message)
        return False, None


def _mask_chat_id(chat_id: int) -> str:
    return redact_identifier("chat", chat_id)


def _weekly_pdf_diag(
    event: str,
    *,
    chat_id: int | None = None,
    elapsed_s: float | None = None,
    **fields: object,
) -> None:
    safe_fields: dict[str, object] = {}
    if chat_id is not None:
        safe_fields["chat_id"] = _mask_chat_id(chat_id)
    if elapsed_s is not None:
        safe_fields["elapsed_s"] = f"{elapsed_s:.3f}"
    safe_fields.update(redact_log_identifiers(fields))
    details = " ".join(f"{key}={value}" for key, value in safe_fields.items())
    logger.warning("weekly_pdf_diag event=%s %s", event, details)


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
    repeat_fallback_used: bool = False
    repeat_recipe_count: int = 0
    repeat_note: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class _WeeklyRepeatFallbackContext:
    safety: object
    targets: object
    foods: tuple[Food, ...]
    food_by_id: dict[str, Food]
    food_cache_key: str
    recipes: tuple[RecipeTemplate, ...]
    recipe_cache: _RecipePlanCache


@dataclass(frozen=True)
class _WeeklyRepeatFallbackFastOption:
    recipe: RecipeTemplate
    estimated_protein_g: float
    estimated_energy_kcal: float


@dataclass(frozen=True)
class _WeeklyPhaseSlotFeasibility:
    slot: str
    weekly_required: int
    available_count: int
    strict_simple_count: int | None
    threshold: int


@dataclass(frozen=True)
class _WeeklyPhaseFeasibility:
    skipped: bool
    reason: str
    slot_counts: tuple[_WeeklyPhaseSlotFeasibility, ...]


class _WeeklySelectionTimeout(RuntimeError):
    def __init__(
        self,
        *,
        scope: str,
        phase: str,
        elapsed_s: float,
        timeout_s: float,
        day_index: int | None = None,
        candidate_index: int | None = None,
        stage: str = "selection",
    ) -> None:
        self.scope = scope
        self.phase = phase
        self.elapsed_s = elapsed_s
        self.timeout_s = timeout_s
        self.day_index = day_index
        self.candidate_index = candidate_index
        self.stage = stage
        super().__init__(
            f"weekly selection {scope} timeout after {elapsed_s:.3f}s "
            f"(limit {timeout_s:.3f}s, phase={phase}, day={day_index}, "
            f"candidate={candidate_index}, stage={stage})"
        )


@dataclass
class _WeeklySelectionGuard:
    total_started_at: float = field(default_factory=lambda: time.perf_counter())
    phase_started_at: float = field(default_factory=lambda: time.perf_counter())
    phase: str = "unknown"

    def begin_phase(self, phase: str) -> None:
        self.phase = phase
        self.phase_started_at = time.perf_counter()

    def check(
        self,
        *,
        stage: str,
        day_index: int | None = None,
        candidate_index: int | None = None,
    ) -> None:
        now = time.perf_counter()
        total_elapsed_s = now - self.total_started_at
        total_timeout_s = float(WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS)
        if total_timeout_s > 0 and total_elapsed_s > total_timeout_s:
            raise _WeeklySelectionTimeout(
                scope="total",
                phase=self.phase,
                elapsed_s=total_elapsed_s,
                timeout_s=total_timeout_s,
                day_index=day_index,
                candidate_index=candidate_index,
                stage=stage,
            )

        phase_elapsed_s = now - self.phase_started_at
        phase_timeout_s = _weekly_selection_phase_timeout(self.phase)
        if phase_timeout_s > 0 and phase_elapsed_s > phase_timeout_s:
            raise _WeeklySelectionTimeout(
                scope="phase",
                phase=self.phase,
                elapsed_s=phase_elapsed_s,
                timeout_s=phase_timeout_s,
                day_index=day_index,
                candidate_index=candidate_index,
                stage=stage,
            )


@dataclass
class _WeeklySelectionScopedGuard:
    guard: _WeeklySelectionGuard
    day_index: int | None
    candidate_index: int | None

    def check(
        self,
        *,
        stage: str,
        day_index: int | None = None,
        candidate_index: int | None = None,
    ) -> None:
        self.guard.check(
            stage=stage,
            day_index=self.day_index if day_index is None else day_index,
            candidate_index=self.candidate_index if candidate_index is None else candidate_index,
        )


def _weekly_selection_phase_timeout(phase: str) -> float:
    if phase == "no_recent":
        return float(WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS)
    return float(WEEKLY_SELECTION_RECENT_PHASE_TIMEOUT_SECONDS)


def _weekly_selection_diag_enabled() -> bool:
    return weekly_selection_diagnostics_enabled()


def _weekly_selection_phase_label(phase: str) -> str:
    if phase == "reduced_recent":
        return "relaxed_recent"
    return phase


def _weekly_selection_diag(event: str, *, always: bool = False, **fields: object) -> None:
    if not always and not _weekly_selection_diag_enabled():
        return
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.warning("weekly_selection_diag event=%s %s", event, details)


def _recipe_cache_diag_counts(recipe_cache: _RecipePlanCache) -> dict[str, int]:
    return {
        "cache_hits": sum(
            count for name, count in recipe_cache.stats.items() if name.endswith("_hits")
        ),
        "cache_misses": sum(
            count for name, count in recipe_cache.stats.items() if name.endswith("_misses")
        ),
    }


@dataclass
class _WeeklyPdfQueueJob:
    chat_id: int
    runner: Callable[[], Awaitable[bool]]
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[bool]
    ready_to_start: bool = False


@dataclass(frozen=True)
class _WeeklyPdfQueueAdmission:
    future: asyncio.Future[bool] | None
    duplicate: bool = False
    starts_immediately: bool = False
    ahead_count: int = 0


class _WeeklyPdfQueueManager:
    def __init__(self, max_concurrency: int) -> None:
        self.max_concurrency = max(1, int(max_concurrency))
        self._queue: deque[_WeeklyPdfQueueJob] = deque()
        self._queued_chat_ids: set[int] = set()
        self._active_chat_ids: set[int] = set()
        self._active_count = 0
        self._lock = RLock()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return self._active_count + len(self._queue)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, int]:
        queued_count = len(self._queue)
        return {
            "queue_active": self._active_count,
            "queue_queued": queued_count,
            "queue_pending": self._active_count + queued_count,
            "queue_max": self.max_concurrency,
        }

    def has_chat(self, chat_id: int) -> bool:
        with self._lock:
            return chat_id in self._queued_chat_ids or chat_id in self._active_chat_ids

    def submit(
        self,
        chat_id: int,
        runner: Callable[[], Awaitable[bool]],
    ) -> _WeeklyPdfQueueAdmission:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        job = _WeeklyPdfQueueJob(
            chat_id=chat_id,
            runner=runner,
            loop=loop,
            future=future,
        )

        with self._lock:
            if chat_id in self._queued_chat_ids or chat_id in self._active_chat_ids:
                _weekly_pdf_diag("queue_duplicate", chat_id=chat_id, **self._snapshot_locked())
                return _WeeklyPdfQueueAdmission(future=None, duplicate=True)

            ahead_count = self._active_count + len(self._queue)
            starts_immediately = not self._queue and self._active_count < self.max_concurrency
            job.ready_to_start = starts_immediately
            self._queue.append(job)
            self._queued_chat_ids.add(chat_id)
            jobs_to_start = self._dispatch_locked()

        self._start_jobs(jobs_to_start)
        _weekly_pdf_diag(
            "queue_admitted",
            chat_id=chat_id,
            starts_immediately=starts_immediately,
            ahead_count=0 if starts_immediately else ahead_count,
            **self.snapshot(),
        )
        return _WeeklyPdfQueueAdmission(
            future=future,
            starts_immediately=starts_immediately,
            ahead_count=0 if starts_immediately else ahead_count,
        )

    def _dispatch_locked(self) -> list[_WeeklyPdfQueueJob]:
        jobs_to_start: list[_WeeklyPdfQueueJob] = []
        while (
            self._queue
            and self._queue[0].ready_to_start
            and self._active_count < self.max_concurrency
        ):
            job = self._queue.popleft()
            self._queued_chat_ids.discard(job.chat_id)
            self._active_chat_ids.add(job.chat_id)
            self._active_count += 1
            jobs_to_start.append(job)
        return jobs_to_start

    def mark_ready(self, future: asyncio.Future[bool]) -> None:
        jobs_to_start: list[_WeeklyPdfQueueJob] = []
        ready_chat_id: int | None = None
        with self._lock:
            for job in self._queue:
                if job.future is future:
                    job.ready_to_start = True
                    ready_chat_id = job.chat_id
                    jobs_to_start = self._dispatch_locked()
                    break
        self._start_jobs(jobs_to_start)
        if ready_chat_id is not None:
            _weekly_pdf_diag("queue_ready", chat_id=ready_chat_id, **self.snapshot())

    def cancel(self, future: asyncio.Future[bool]) -> None:
        jobs_to_start: list[_WeeklyPdfQueueJob] = []
        with self._lock:
            remaining: deque[_WeeklyPdfQueueJob] = deque()
            removed_chat_id: int | None = None
            for job in self._queue:
                if job.future is future:
                    removed_chat_id = job.chat_id
                    continue
                remaining.append(job)
            if removed_chat_id is not None:
                self._queue = remaining
                self._queued_chat_ids.discard(removed_chat_id)
                if not future.done():
                    future.cancel()
                jobs_to_start = self._dispatch_locked()
        self._start_jobs(jobs_to_start)
        if removed_chat_id is not None:
            _weekly_pdf_diag("queue_cancelled", chat_id=removed_chat_id, **self.snapshot())

    def _start_jobs(self, jobs: Sequence[_WeeklyPdfQueueJob]) -> None:
        for job in jobs:
            job.loop.create_task(self._run_job(job))

    async def _run_job(self, job: _WeeklyPdfQueueJob) -> None:
        started_at = time.perf_counter()
        _weekly_pdf_diag("job_start", chat_id=job.chat_id, **self.snapshot())
        try:
            result = await job.runner()
        except Exception as exc:
            _weekly_pdf_diag(
                "job_fail",
                chat_id=job.chat_id,
                elapsed_s=time.perf_counter() - started_at,
                error=type(exc).__name__,
                **self.snapshot(),
            )
            if not job.future.done():
                job.future.set_exception(exc)
        else:
            _weekly_pdf_diag(
                "job_complete",
                chat_id=job.chat_id,
                elapsed_s=time.perf_counter() - started_at,
                result=result,
                **self.snapshot(),
            )
            if not job.future.done():
                job.future.set_result(result)
        finally:
            with self._lock:
                self._active_chat_ids.discard(job.chat_id)
                self._active_count = max(0, self._active_count - 1)
                jobs_to_start = self._dispatch_locked()
            self._start_jobs(jobs_to_start)
            _weekly_pdf_diag("job_released", chat_id=job.chat_id, **self.snapshot())


def _configure_weekly_pdf_concurrency(max_concurrency: int) -> None:
    global WEEKLY_PDF_MAX_CONCURRENCY
    global WEEK_PDF_QUEUE_MANAGER

    WEEKLY_PDF_MAX_CONCURRENCY = max(1, int(max_concurrency))
    WEEK_PDF_QUEUE_MANAGER = _WeeklyPdfQueueManager(WEEKLY_PDF_MAX_CONCURRENCY)


@dataclass
class _WeeklyRecipeTraitLookup:
    recipes_by_id: Mapping[str, RecipeTemplate] = field(default_factory=dict)
    precomputed_traits_by_id: Mapping[str, RecipeTraits] = field(default_factory=dict)
    traits_by_id: dict[str, RecipeTraits] = field(default_factory=dict)
    stats: Counter[str] = field(default_factory=Counter)

    @classmethod
    def from_recipes(cls, recipes: Sequence[RecipeTemplate]) -> "_WeeklyRecipeTraitLookup":
        return cls(recipes_by_id={recipe.id: recipe for recipe in recipes})

    @classmethod
    def from_traits(cls, traits_by_id: Mapping[str, RecipeTraits]) -> "_WeeklyRecipeTraitLookup":
        return cls(precomputed_traits_by_id=dict(traits_by_id))

    def get(self, recipe_id: str) -> RecipeTraits | None:
        if recipe_id in self.traits_by_id:
            self.stats["weekly_trait_lookup_hits"] += 1
            return self.traits_by_id[recipe_id]

        self.stats["weekly_trait_lookup_misses"] += 1
        traits = self.precomputed_traits_by_id.get(recipe_id)
        if traits is not None:
            self.stats["weekly_trait_lookup_precomputed"] += 1
            self.traits_by_id[recipe_id] = traits
            return traits

        recipe = self.recipes_by_id.get(recipe_id)
        if recipe is None:
            self.stats["weekly_trait_lookup_missing"] += 1
            return None

        self.stats["weekly_trait_lookup_inferred"] += 1
        traits = infer_recipe_traits(recipe)
        self.traits_by_id[recipe_id] = traits
        return traits


_RecipeTraitLookupSource = Mapping[str, RecipeTraits] | _WeeklyRecipeTraitLookup


@dataclass(frozen=True)
class RecipeHistoryItem:
    recipe_id: str | None = None
    recipe_key: str | None = None
    meal_slot: str | None = None
    ration_kind: RationKind | None = None
    day_index: int | None = None
    meal_index: int | None = None
    user_id: int | None = None
    generation_id: int | None = None
    generated_at: datetime | None = None



def _parse_id_set(raw: str | None) -> set[int]:
    return _parse_runtime_id_set(raw)


def _parse_optional_int(raw: str | None) -> int | None:
    return _parse_runtime_optional_int(raw)


def _payments_enabled_from_env() -> bool:
    config = load_runtime_config()
    return config.payments_enabled and config.public_payments_enabled


def _support_chat_id_from_env() -> int | None:
    return load_runtime_config().support_chat_id


def _privacy_policy_url_from_env() -> str | None:
    return load_runtime_config().privacy_policy_url


def _payments_enabled() -> bool:
    return PAYMENTS_ENABLED


def _is_support_chat(chat_id: int) -> bool:
    return SUPPORT_CHAT_ID is not None and chat_id == SUPPORT_CHAT_ID

START_PLAN_TEXT = "🥗 Составить план"
TRY_FREE_TEXT = "🥗 Попробовать бесплатно"
SUBSCRIPTION_PRICE_RUB = 799
EXTRA_ONE_DAY_PRICE_RUB = 50
EXTRA_WEEKLY_PDF_PRICE_RUB = 250
SUBSCRIPTION_STARS_AMOUNT = 450
EXTRA_ONE_DAY_STARS_AMOUNT = 29
EXTRA_WEEKLY_PDF_STARS_AMOUNT = 141
SUBSCRIBE_MONTH_TEXT = f"💳 Доступ на 30 дней - {SUBSCRIPTION_PRICE_RUB} ₽"
SUBSCRIBE_CTA_TEXT = "💳 Оформить месячный доступ"
SUBSCRIPTION_PAYMENT_TEXT = (
    "FoodBalance - цифровой сервис персональных рационов питания.\n\n"
    f"YooKassa: разовый доступ на 30 дней - {SUBSCRIPTION_PRICE_RUB} ₽.\n"
    f"Telegram Stars: автопродляемая подписка на месяц - {SUBSCRIPTION_STARS_AMOUNT} Stars.\n\n"
    "Включено:\n"
    f"• {MONTHLY_WEEKLY_PDF_LIMIT} недельных PDF-рациона\n"
    f"• {MONTHLY_ONE_DAY_LIMIT} рационов на 1 день\n"
    "• рецепты и список продуктов по анкете\n\n"
    "Сервис носит информационный характер и не является медицинской консультацией."
)
PAYMENTS_DISABLED_TEXT = (
    "Доступ по промокоду на этапе пилота.\n\n"
    "Публичная оплата картой, SberPay и Telegram Stars пока выключена. "
    "Введите промокод или обратитесь к администратору, если доступ уже согласован."
)
PAY_WITH_TELEGRAM_STARS_TEXT = f"⭐ Подписка с автопродлением - {SUBSCRIPTION_STARS_AMOUNT} Stars"
PAY_WITH_RU_CARD_TEXT = f"💳 Разовый доступ на 30 дней - {SUBSCRIPTION_PRICE_RUB} ₽"
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
    "• собираю PDF с меню, рецептами и списком продуктов\n"
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
PROMO_CODE_NOT_ACCESS_TEXT = (
    "Это промокод другого типа. Для активации доступа нужен промокод на месячный доступ."
)
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
WEEK_PLAN_RESCUE_CANDIDATE_COUNT = 4
WEEKLY_RECENT_FEASIBILITY_POOL_MULTIPLIER = 5
WEEKLY_REPEATS_FALLBACK_POOL_MULTIPLIER = 3
WEEKLY_REPEATS_FALLBACK_FAST_SLOT_OPTIONS = 8
WEEKLY_REPEATS_FALLBACK_FAST_COMBO_LIMIT = 50
WEEKLY_REPEATS_FALLBACK_DAY_POOL_SIZE = 6
WEEKLY_REPEATS_FALLBACK_BUILDER_ATTEMPTS = 7
WEEKLY_REPEATS_FALLBACK_NOTE = (
    "Из-за узких ограничений я повторил несколько блюд, "
    "чтобы сохранить рацион полноценным и не нарушать ваши исключения."
)
WEEKLY_SELECTION_RECENT_PHASE_TIMEOUT_SECONDS = 8.0
WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS = 60.0
WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS = 90.0
WEEKLY_EXACT_RECIPE_REPEAT_PENALTY = 1.0
WEEKLY_CANDIDATE_POOL_RECIPE_REPEAT_PENALTY = 0.15
WEEKLY_TRAIT_REPEAT_CAP = 3
WEEKLY_TRAIT_REPEAT_WEIGHTS = {
    "primary_protein": 0.018,
    "primary_carb": 0.012,
    "recipe_format": 0.014,
}
PDF_MONTH_NAMES_RU = {
    1: "\u044f\u043d\u0432\u0430\u0440\u044f",
    2: "\u0444\u0435\u0432\u0440\u0430\u043b\u044f",
    3: "\u043c\u0430\u0440\u0442\u0430",
    4: "\u0430\u043f\u0440\u0435\u043b\u044f",
    5: "\u043c\u0430\u044f",
    6: "\u0438\u044e\u043d\u044f",
    7: "\u0438\u044e\u043b\u044f",
    8: "\u0430\u0432\u0433\u0443\u0441\u0442\u0430",
    9: "\u0441\u0435\u043d\u0442\u044f\u0431\u0440\u044f",
    10: "\u043e\u043a\u0442\u044f\u0431\u0440\u044f",
    11: "\u043d\u043e\u044f\u0431\u0440\u044f",
    12: "\u0434\u0435\u043a\u0430\u0431\u0440\u044f",
}
WEEK_PDF_STATUS_UPDATE_SECONDS = 4.0
WEEK_PDF_STATUS_INITIAL_TEXT = (
    "Собираю ваш недельный PDF. Обычно это занимает 1-3 минуты. "
    "Можно закрыть Telegram — я пришлю файл сюда, когда он будет готов."
)
WEEK_PDF_STATUS_FRAMES = (
    "PDF собирается.\n\nПодбираю блюда под вашу анкету. Файл придет сюда автоматически.",
    "PDF собирается.\n\nПроверяю аллергии, ограничения и исключенные продукты.",
    "PDF собирается.\n\nСчитаю КБЖУ, витамины и минералы.",
    "PDF собирается.\n\nОформляю рецепты, список продуктов и сам файл.",
)
WEEK_PDF_UPLOAD_TEXT = "PDF собран. Загружаю файл в чат."
WEEK_PDF_DONE_TEXT = "Готово. PDF отправлен ниже."
WEEK_PDF_FALLBACK_TEXT = "PDF не удалось собрать. Отправляю рацион текстом."
WEEK_PDF_FAILURE_TEXT = "PDF \u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u0438\u0442\u044c \u0438\u043b\u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435."
WEEK_PDF_ACCEPTED_TEXT = WEEK_PDF_STATUS_INITIAL_TEXT
WEEK_PDF_ALREADY_RUNNING_TEXT = "Не переживайте, файл уже генерируется. Я пришлю PDF сюда, когда он будет готов."
ONE_DAY_PLAN_STATUS_TEXT = "\u0421\u0447\u0438\u0442\u0430\u044e \u0440\u0430\u0446\u0438\u043e\u043d \u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u044f\u044e \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f... \U0001f9ee"
ONE_DAY_PLAN_ACCEPTED_TEXT = "\u0413\u043e\u0442\u043e\u0432\u043b\u044e \u0440\u0430\u0446\u0438\u043e\u043d. \u042f \u043f\u0440\u0438\u0448\u043b\u044e \u0435\u0433\u043e \u0441\u044e\u0434\u0430, \u043a\u0430\u043a \u0442\u043e\u043b\u044c\u043a\u043e \u043e\u043d \u0431\u0443\u0434\u0435\u0442 \u0433\u043e\u0442\u043e\u0432."
ONE_DAY_PLAN_ALREADY_RUNNING_TEXT = "\u041d\u0435 \u043f\u0435\u0440\u0435\u0436\u0438\u0432\u0430\u0439\u0442\u0435, \u0440\u0430\u0446\u0438\u043e\u043d \u0443\u0436\u0435 \u0433\u043e\u0442\u043e\u0432\u0438\u0442\u0441\u044f. \u042f \u043f\u0440\u0438\u0448\u043b\u044e \u0435\u0433\u043e \u0441\u044e\u0434\u0430, \u043a\u043e\u0433\u0434\u0430 \u043e\u043d \u0431\u0443\u0434\u0435\u0442 \u0433\u043e\u0442\u043e\u0432."
ONE_DAY_PLAN_NO_PLAN_FOLLOW_UP_TEXT = "\u041d\u0435 \u0441\u043c\u043e\u0433 \u0441\u043e\u0431\u0440\u0430\u0442\u044c \u0440\u0430\u0446\u0438\u043e\u043d \u043f\u043e \u0442\u0435\u043a\u0443\u0449\u0438\u043c \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f\u043c. \u042f \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u043b \u044d\u0442\u043e \u043a\u0430\u043a \u043e\u0448\u0438\u0431\u043a\u0443 \u0438 \u043d\u0435 \u0431\u0443\u0434\u0443 \u0441\u043f\u0438\u0441\u044b\u0432\u0430\u0442\u044c \u043f\u043e\u043f\u044b\u0442\u043a\u0443."
WEEK_PDF_QUEUE_ESTIMATED_JOB_SECONDS = 90
DEFAULT_WEEKLY_PDF_MAX_CONCURRENCY = 5
WEEKLY_PDF_MAX_CONCURRENCY = DEFAULT_WEEKLY_PDF_MAX_CONCURRENCY
WEEK_PDF_QUEUE_MANAGER = _WeeklyPdfQueueManager(WEEKLY_PDF_MAX_CONCURRENCY)
_ONE_DAY_PLAN_IN_FLIGHT_CHAT_IDS: set[int] = set()
_ONE_DAY_PLAN_IN_FLIGHT_LOCK = RLock()
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
_RUNTIME_CONFIG = load_runtime_config()
STATE_FILE = _RUNTIME_CONFIG.state_file
SUBSCRIPTIONS_STATE_FILE = _RUNTIME_CONFIG.subscriptions_state_file
PROMO_CODES_STATE_FILE = _RUNTIME_CONFIG.promo_codes_state_file
_CHAT_STATE_STORE: ChatStateStore | None = None
_CHAT_STATE_STORE_KEY: tuple[str, str] | None = None
ADMIN_USER_IDS = set(_RUNTIME_CONFIG.admin_user_ids)
TESTER_CHAT_IDS = set(_RUNTIME_CONFIG.tester_chat_ids)
TELEGRAM_PROVIDER_TOKEN = _RUNTIME_CONFIG.telegram_provider_token
PUBLIC_PAYMENTS_ENABLED = _RUNTIME_CONFIG.public_payments_enabled
PAYMENT_TEST_PRICES_ENABLED = _RUNTIME_CONFIG.payment_test_prices_enabled
PAYMENTS_ENABLED = _RUNTIME_CONFIG.payments_enabled and _RUNTIME_CONFIG.public_payments_enabled
SUPPORT_CHAT_ID = _RUNTIME_CONFIG.support_chat_id
PRIVACY_POLICY_URL = _RUNTIME_CONFIG.privacy_policy_url
PRIVACY_POLICY_TEXT = "\u041f\u043e\u043b\u0438\u0442\u0438\u043a\u0430 \u043a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u0438"
PRIVACY_POLICY_BODY_TEXT = (
    "Политика конфиденциальности FoodBalance\n\n"
    "FoodBalance использует данные анкеты, сообщения в чате, технические данные Telegram и сведения об оплате "
    "только для расчета персонального рациона, проверки доступа, поддержки и улучшения сервиса.\n\n"
    "Мы не продаем персональные данные. Платежные данные обрабатываются платежными провайдерами; бот хранит только "
    "служебные статусы, идентификаторы операций и историю доступа, необходимые для восстановления и поддержки.\n\n"
    "Рекомендации FoodBalance носят информационный характер и не заменяют консультацию врача. Если нужно удалить "
    "данные или задать вопрос по обработке данных, напишите в техподдержку."
)
PRIVACY_CONSENT_TEXT = (
    "Перед началом нужно подтвердить согласие с политикой конфиденциальности FoodBalance. "
    "Мы используем данные анкеты только для расчета рациона, проверки доступа и поддержки."
)
PRIVACY_CONSENT_ACCEPT_TEXT = "✅ Принять и продолжить"
PRIVACY_CONSENT_SCHEMA_VERSION = 1
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
CALLBACK_PRIVACY_POLICY = "diet:privacy_policy"
CALLBACK_PRIVACY_CONSENT = "diet:privacy_consent"
CALLBACK_PRIVACY_CONSENT_TRIAL = "diet:privacy_consent:trial"
CALLBACK_SUPPORT = "diet:support"
CALLBACK_SALES_FOLLOWUP_OPT_OUT = SALES_FOLLOWUP_OPT_OUT_CALLBACK_DATA
SALES_FOLLOWUP_OPT_OUT_CONFIRMATION_TEXT = "Хорошо, больше не буду напоминать."
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
SELECTED_ANSWER_PREFIX = "✅ "
STALE_QUESTIONNAIRE_CALLBACK_TEXT = "Этот вопрос уже не активен. Продолжайте с последнего вопроса."
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
ADMIN_PROMO_STORAGE_ERROR_TEXT = "Promo storage is unavailable. Try again later."
PAYMENT_CALLBACKS = {
    CALLBACK_PAY_TELEGRAM_STARS,
    CALLBACK_PAY_RU_CARD,
    CALLBACK_PAY_RU_EXTRA_ONE_DAY,
    CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF,
    CALLBACK_BUY_EXTRA_ONE_DAY,
    CALLBACK_BUY_EXTRA_WEEKLY_PDF,
}


def _chat_state_store() -> ChatStateStore:
    global _CHAT_STATE_STORE, _CHAT_STATE_STORE_KEY

    config = load_runtime_config()
    if config.storage_backend == "json":
        config = replace(config, state_file=Path(STATE_FILE))
    key = _chat_state_store_key(config)
    if _CHAT_STATE_STORE is None or _CHAT_STATE_STORE_KEY != key:
        _CHAT_STATE_STORE = create_chat_state_store(config)
        _CHAT_STATE_STORE_KEY = key
    return _CHAT_STATE_STORE


def _chat_state_store_key(config) -> tuple[str, str]:
    if config.storage_backend == "postgres":
        return (config.storage_backend, str(config.database_url or ""))
    return (config.storage_backend, str(config.state_file))


PAYLOAD_SUBSCRIPTION_MONTH = "diet:stars:subscription_month"
PAYLOAD_EXTRA_ONE_DAY = "diet:stars:extra_one_day"
PAYLOAD_EXTRA_WEEKLY_PDF = "diet:stars:extra_weekly_pdf"
PAYLOAD_RU_SUBSCRIPTION_MONTH = "diet:rub:subscription_month"
PAYLOAD_RU_EXTRA_ONE_DAY = "diet:rub:extra_one_day"
PAYLOAD_RU_EXTRA_WEEKLY_PDF = "diet:rub:extra_weekly_pdf"
PAYMENT_LEDGER_UNAVAILABLE_TEXT = (
    "\u041e\u043f\u043b\u0430\u0442\u0430 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e "
    "\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430. "
    "\u0421\u0447\u0435\u0442 \u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u043d. "
    "\u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435 "
    "\u0438\u043b\u0438 \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0432 "
    "\u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443."
)
PAYMENT_ACTIVATION_DELAYED_TEXT = (
    "\u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u043e\u043b\u0443\u0447\u0435\u043d\u0430, "
    "\u043d\u043e \u0430\u043a\u0442\u0438\u0432\u0430\u0446\u0438\u044f "
    "\u0434\u043e\u0441\u0442\u0443\u043f\u0430 \u0437\u0430\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442\u0441\u044f. "
    "\u041d\u0435 \u043e\u043f\u043b\u0430\u0447\u0438\u0432\u0430\u0439\u0442\u0435 "
    "\u043f\u043e\u0432\u0442\u043e\u0440\u043d\u043e. "
    "\u041f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0430 "
    "\u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442 \u043f\u043b\u0430\u0442\u0435\u0436; "
    "\u043f\u043e\u0432\u0442\u043e\u0440\u043d\u0430\u044f "
    "\u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430 "
    "\u0432\u043a\u043b\u044e\u0447\u0438\u0442 \u0434\u043e\u0441\u0442\u0443\u043f."
)
PAYMENT_PENDING_INVOICE_ALREADY_OPEN_TEXT = (
    "\u0421\u0447\u0435\u0442 \u0443\u0436\u0435 \u0441\u043e\u0437\u0434\u0430\u043d. "
    "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 "
    "\u043f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0443\u044e "
    "\u0441\u0441\u044b\u043b\u043a\u0443 \u0434\u043b\u044f "
    "\u043e\u043f\u043b\u0430\u0442\u044b \u0438\u043b\u0438 "
    "\u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 "
    "\u043f\u043e\u0437\u0436\u0435."
)
PAYMENT_RECOVERY_SPOOL_ENV = "DIET_BOT_PAYMENT_RECOVERY_SPOOL"
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
    PAYLOAD_SUBSCRIPTION_MONTH: "FoodBalance: подписка на месяц с автопродлением",
    PAYLOAD_EXTRA_ONE_DAY: "FoodBalance: 1 дневной рацион",
    PAYLOAD_EXTRA_WEEKLY_PDF: "FoodBalance: 1 недельный PDF",
}
RUB_PAYMENT_PAYLOAD_TITLES = {
    PAYLOAD_RU_SUBSCRIPTION_MONTH: "FoodBalance: доступ на 30 дней",
    PAYLOAD_RU_EXTRA_ONE_DAY: "FoodBalance: 1 дневной рацион",
    PAYLOAD_RU_EXTRA_WEEKLY_PDF: "FoodBalance: 1 недельный PDF",
}
PAYMENT_PAYLOAD_DESCRIPTIONS = {
    PAYLOAD_SUBSCRIPTION_MONTH: "Автопродляемая подписка: 4 недельных PDF и 5 дневных рационов в месяц.",
    PAYLOAD_EXTRA_ONE_DAY: "Разовая дополнительная попытка для рациона на 1 день.",
    PAYLOAD_EXTRA_WEEKLY_PDF: "Разовая дополнительная попытка для недельного PDF-рациона.",
}
RUB_PAYMENT_PAYLOAD_DESCRIPTIONS = {
    PAYLOAD_RU_SUBSCRIPTION_MONTH: "Разовый доступ на 30 дней: 4 недельных PDF и 5 дневных рационов.",
    PAYLOAD_RU_EXTRA_ONE_DAY: "Разовая дополнительная попытка для рациона на 1 день.",
    PAYLOAD_RU_EXTRA_WEEKLY_PDF: "Разовая дополнительная попытка для недельного PDF-рациона.",
}
PAYMENT_PAYLOAD_PRODUCTS = {
    PAYLOAD_SUBSCRIPTION_MONTH: (PROVIDER_TELEGRAM_STARS, PRODUCT_SUBSCRIPTION_MONTH),
    PAYLOAD_EXTRA_ONE_DAY: (PROVIDER_TELEGRAM_STARS, PRODUCT_EXTRA_ONE_DAY),
    PAYLOAD_EXTRA_WEEKLY_PDF: (PROVIDER_TELEGRAM_STARS, PRODUCT_EXTRA_WEEKLY_PDF),
    PAYLOAD_RU_SUBSCRIPTION_MONTH: (PROVIDER_YOOKASSA, PRODUCT_SUBSCRIPTION_MONTH),
    PAYLOAD_RU_EXTRA_ONE_DAY: (PROVIDER_YOOKASSA, PRODUCT_EXTRA_ONE_DAY),
    PAYLOAD_RU_EXTRA_WEEKLY_PDF: (PROVIDER_YOOKASSA, PRODUCT_EXTRA_WEEKLY_PDF),
}
PAYMENT_PRODUCT_PAYLOADS = {value: key for key, value in PAYMENT_PAYLOAD_PRODUCTS.items()}
PAYMENT_CALLBACK_PRODUCTS = {
    CALLBACK_PAY_TELEGRAM_STARS: (PROVIDER_TELEGRAM_STARS, PRODUCT_SUBSCRIPTION_MONTH),
    CALLBACK_PAY_RU_CARD: (PROVIDER_YOOKASSA, PRODUCT_SUBSCRIPTION_MONTH),
    CALLBACK_PAY_RU_EXTRA_ONE_DAY: (PROVIDER_YOOKASSA, PRODUCT_EXTRA_ONE_DAY),
    CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF: (PROVIDER_YOOKASSA, PRODUCT_EXTRA_WEEKLY_PDF),
    CALLBACK_BUY_EXTRA_ONE_DAY: (PROVIDER_TELEGRAM_STARS, PRODUCT_EXTRA_ONE_DAY),
    CALLBACK_BUY_EXTRA_WEEKLY_PDF: (PROVIDER_TELEGRAM_STARS, PRODUCT_EXTRA_WEEKLY_PDF),
}
WELCOME_TEXT = (
    "Привет! Я FoodBalance — ваш персональный помощник по сбалансированному питанию 🥗\n\n"
    "Я подберу рецепты под ваши цели, рассчитаю КБЖУ, витамины и минералы, помогу собрать рацион так, "
    "чтобы питание было не только полезным, но и вкусным, удобным и реалистичным.\n\n"
    "Вы сможете получать блюда под свои предпочтения, режим, ограничения и нужную калорийность — "
    "без хаоса, ручных подсчётов и скучных однотипных меню.\n\n"
    "Начнём с короткой анкеты, чтобы я лучше понял, что вам подходит 👇"
)
PRIVATE_CHAT_REQUIRED_TEXT = "Пожалуйста, откройте бота в личном чате, чтобы продолжить. private chat"
PRIVATE_CHAT_CALLBACK_TEXT = "Откройте бота в личном чате, чтобы использовать эту кнопку. private chat"
PRIVATE_CHAT_ONLY_TEXT = PRIVATE_CHAT_REQUIRED_TEXT
TRIAL_SUBSCRIPTION_TEXT = (
    "Понравился рацион?\n\n"
    "На неделю вперёд я составлю тебе такое же меню: каждый день завтрак, обед, ужин и перекусы. "
    "Рецепты с граммовками, КБЖУ по каждому блюду и полная таблица витаминов и минералов за день.\n\n"
    "В конце недели будет список всех продуктов, которые нужно купить, чтобы всё это приготовить.\n\n"
    "Месячный доступ — это 4 недельных рациона плюс 5 дополнительных дней, "
    "если захочешь что-то поменять."
)
BOT_COMMANDS = (
    BotCommand(command="start", description="Открыть стартовое меню"),
    BotCommand(command="plan", description="Заполнить анкету для рациона"),
    BotCommand(command="promo", description="Ввести промокод"),
    BotCommand(command="privacy", description="Политика конфиденциальности"),
    BotCommand(command="cancel", description="Сбросить активную анкету"),
)


@router.message(Command("start"))
async def start(message: Message) -> None:
    if await _reject_non_private_message(message):
        return
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
    _clear_questionnaire_session(message.chat.id)
    TRIAL_CHAT_IDS.discard(message.chat.id)
    if _is_support_chat(message.chat.id):
        return
    await _send_welcome_photo(message)
    try:
        has_paid_access = await _has_active_paid_access_async(message.chat.id)
    except EntitlementStorageError:
        logger.exception("Failed to check active access due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return
    if has_paid_access:
        try:
            subscriber_text = await _subscriber_cabinet_text_async(message.chat.id)
            subscriber_keyboard = await _subscriber_cabinet_keyboard_async(message.chat.id)
        except EntitlementStorageError:
            logger.exception("Failed to render subscriber cabinet due to entitlement storage error")
            await _send_entitlement_storage_error(message)
            return
        except ChatStateStorageError:
            logger.exception("Failed to render subscriber cabinet due to chat state storage error")
            await _send_chat_state_read_error(message)
            return
        await message.answer(
            subscriber_text,
            reply_markup=subscriber_keyboard,
        )
        return
    try:
        profile = await _profile_for_chat_async(message.chat.id)
    except ChatStateStorageError:
        logger.exception("Failed to load chat profile for chat_id=%s", _mask_chat_id(message.chat.id))
        await _send_chat_state_read_error(message)
        return
    if profile is not None:
        try:
            reply_markup = await _main_menu_keyboard_async(message.chat.id)
        except EntitlementStorageError:
            logger.exception("Failed to render main menu due to entitlement storage error")
            await _send_entitlement_storage_error(message)
            return
        except ChatStateStorageError:
            logger.exception("Failed to render main menu due to chat state storage error")
            await _send_chat_state_read_error(message)
            return
        await message.answer(
            "Анкета уже сохранена. Можно сразу составить рацион или изменить анкету.",
            reply_markup=reply_markup,
        )
        return
    await message.answer(WELCOME_TEXT, reply_markup=_start_keyboard())


@router.message(Command("plan"))
async def plan(message: Message) -> None:
    if await _reject_non_private_message(message):
        return
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
    if _is_support_chat(message.chat.id):
        return
    profile_loaded, profile = await _load_profile_for_message_or_notice(message)
    if not profile_loaded:
        return
    if profile is not None:
        await _send_calculation_options(message, profile)
        return
    await _start_questionnaire_with_privacy_consent(message)


@router.message(Command("promo"))
async def promo(message: Message) -> None:
    if await _reject_non_private_message(message):
        return
    if _is_support_chat(message.chat.id):
        return
    ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
    await _start_promo_code_request(message)


@router.message(Command("privacy"))
async def privacy(message: Message) -> None:
    if await _reject_non_private_message(message):
        return
    if _is_support_chat(message.chat.id):
        return
    await _send_privacy_policy(message)


@router.message(Command("cancel"))
async def cancel(message: Message) -> None:
    if await _reject_non_private_message(message):
        return
    _clear_questionnaire_session(message.chat.id)
    TRIAL_CHAT_IDS.discard(message.chat.id)
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
    ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
    if _is_support_chat(message.chat.id):
        return
    await message.answer("Анкета сброшена ✅", reply_markup=_main_menu_keyboard(message.chat.id))


@router.message(Command("myid"))
async def myid(message: Message) -> None:
    if await _reject_non_private_message(message):
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
    await message.answer("\n".join(lines))


@router.message(Command("330366"))
async def secret_access_command(message: Message) -> None:
    if await _reject_non_private_message(message):
        return
    if _is_admin_panel_command_text(message.text or ""):
        if not _is_admin_message(message):
            await message.answer("Command is available only to admins.")
            return
        await _send_admin_promo_panel(message)
        return

    action, target_chat_id = _parse_test_access_command(message.text or "")
    if target_chat_id is not None:
        if not _is_admin_message(message):
            await message.answer("Команда для выдачи доступа доступна только администратору.")
            return
        if action == "revoke":
            try:
                _revoke_test_access_for_chat(target_chat_id)
            except EntitlementStorageError:
                logger.exception("Failed to revoke test access due to entitlement storage error")
                await _send_entitlement_storage_error(message)
                return
            await message.answer(f"Тестовый доступ отключен для chat_id {target_chat_id}.")
            return
        try:
            entitlement = _grant_test_access_to_chat(target_chat_id)
        except EntitlementStorageError:
            logger.exception("Failed to grant test access due to entitlement storage error")
            await _send_entitlement_storage_error(message)
            return
        test_access_end = entitlement.test_access_end_datetime()
        until_text = f" до {test_access_end:%d.%m.%Y}" if test_access_end else ""
        await message.answer(
            f"Тестовый доступ выдан для chat_id {target_chat_id}{until_text}.",
        )
        return

    if action == "enable":
        try:
            enabled, _ = _set_test_access_mode(message.chat.id, True)
        except EntitlementStorageError:
            logger.exception("Failed to enable test access due to entitlement storage error")
            await _send_entitlement_storage_error(message)
            return
        if enabled:
            await message.answer("Тестовый платный режим включен.")
        else:
            await message.answer("Тестовый доступ для вашего chat_id не выдан или уже истек.")
        return

    if action == "disable":
        try:
            disabled, _ = _set_test_access_mode(message.chat.id, False)
        except EntitlementStorageError:
            logger.exception("Failed to disable test access due to entitlement storage error")
            await _send_entitlement_storage_error(message)
            return
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

    try:
        status_text = _format_test_access_command_status(message.chat.id)
    except EntitlementStorageError:
        logger.exception("Failed to read test access status due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return
    await message.answer(status_text)


@router.callback_query()
async def handle_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer()
        return

    if await _reject_non_private_callback(callback, message):
        return

    if _is_support_chat(message.chat.id):
        await callback.answer()
        return

    if data != CALLBACK_SUPPORT:
        SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    if data != CALLBACK_PROMO_CODE:
        PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
    if data not in ADMIN_PROMO_CALLBACKS:
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)

    if data == CALLBACK_SALES_FOLLOWUP_OPT_OUT:
        await _handle_sales_followup_opt_out_callback(callback, message)
        return

    if data == CALLBACK_ADMIN_CREATE_MONTHLY_ACCESS_CODE:
        if not _is_admin_callback(callback):
            await callback.answer("Command is available only to admins.")
            return
        await callback.answer()
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
        await _send_admin_monthly_access_code(message, admin_user_id=_callback_user_id(callback))
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

    if data in PAYMENT_CALLBACKS and not _payments_enabled():
        await callback.answer()
        await _send_payments_disabled_notice(message)
        return

    if data == CALLBACK_SUPPORT:
        await callback.answer()
        await _start_support_request(message)
        return

    if data == CALLBACK_START:
        await callback.answer()
        await _start_questionnaire_with_privacy_consent(message, is_trial=True)
        return

    if data == CALLBACK_NEW:
        await callback.answer()
        await _start_questionnaire_with_privacy_consent(message)
        return

    if data in {CALLBACK_PRIVACY_CONSENT, CALLBACK_PRIVACY_CONSENT_TRIAL}:
        await callback.answer()
        try:
            await _save_privacy_consent_async(message.chat.id)
        except ChatStateStorageError:
            await message.answer(PRIVACY_CONSENT_STORAGE_ERROR_TEXT)
            return
        await _start_questionnaire(message, is_trial=data == CALLBACK_PRIVACY_CONSENT_TRIAL)
        return

    if data == CALLBACK_SUBSCRIBE:
        await callback.answer()
        await _send_subscription_payment_options(message)
        return

    if data == CALLBACK_PAY_TELEGRAM_STARS:
        await callback.answer()
        if await _send_active_subscription_notice_if_needed(message):
            return
        await _send_payment_invoice_link(message, *PAYMENT_CALLBACK_PRODUCTS[data], payer_user_id=_callback_user_id(callback))
        return

    if data == CALLBACK_PAY_RU_CARD:
        await callback.answer()
        if await _send_active_subscription_notice_if_needed(message):
            return
        await _send_payment_invoice_link(message, *PAYMENT_CALLBACK_PRODUCTS[data], payer_user_id=_callback_user_id(callback))
        return

    if data == CALLBACK_PAY_RU_EXTRA_ONE_DAY:
        await callback.answer()
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_payment_invoice_link(message, *PAYMENT_CALLBACK_PRODUCTS[data], payer_user_id=_callback_user_id(callback))
        return

    if data == CALLBACK_PAY_RU_EXTRA_WEEKLY_PDF:
        await callback.answer()
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_payment_invoice_link(message, *PAYMENT_CALLBACK_PRODUCTS[data], payer_user_id=_callback_user_id(callback))
        return

    if data == CALLBACK_BUY_EXTRA_ONE_DAY:
        await callback.answer()
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_payment_invoice_link(message, *PAYMENT_CALLBACK_PRODUCTS[data], payer_user_id=_callback_user_id(callback))
        return

    if data == CALLBACK_BUY_EXTRA_WEEKLY_PDF:
        await callback.answer()
        if await _send_extra_purchase_subscription_notice_if_needed(message):
            return
        await _send_payment_invoice_link(message, *PAYMENT_CALLBACK_PRODUCTS[data], payer_user_id=_callback_user_id(callback))
        return

    if data == CALLBACK_FEATURES:
        await callback.answer()
        await message.answer(FEATURES_MESSAGE, reply_markup=_main_menu_keyboard(message.chat.id))
        return

    if data == CALLBACK_PROMO_CODE:
        await callback.answer()
        await _start_promo_code_request(message)
        return

    if data == CALLBACK_PRIVACY_POLICY:
        await callback.answer()
        await _send_privacy_policy(message)
        return

    if data == CALLBACK_REPEAT:
        await callback.answer()
        await _repeat_plan(message, idempotency_key=_one_day_callback_idempotency_key(callback))
        return

    if data == CALLBACK_ONE_DAY_PLAN:
        await callback.answer()
        profile_loaded, profile = await _load_profile_for_message_or_notice(message)
        if not profile_loaded:
            return
        if profile is None:
            await _start_questionnaire_with_privacy_consent(message)
            return
        await _send_one_day_plan_with_access(
            message,
            profile,
            idempotency_key=_one_day_callback_idempotency_key(callback),
        )
        return

    if data == CALLBACK_WEEK_PLAN_PDF:
        await callback.answer()
        profile_loaded, profile = await _load_profile_for_message_or_notice(message)
        if not profile_loaded:
            return
        if profile is None:
            await _start_questionnaire_with_privacy_consent(message)
            return
        await _send_week_plan_with_access(
            message,
            profile,
            idempotency_key=_weekly_pdf_callback_idempotency_key(callback),
        )
        return

    if data.startswith(CALLBACK_ANSWER_PREFIX):
        async with _questionnaire_callback_lock(message.chat.id):
            session = SESSION_BY_CHAT_ID.get(message.chat.id)
            if session is None or session.current_question is None:
                await callback.answer("Анкета уже не активна")
                await message.answer(
                    "Нажмите кнопку, чтобы составить рацион 👇",
                    reply_markup=_main_menu_keyboard(message.chat.id),
                )
                return

            payload = _parse_questionnaire_answer_callback(data)
            if payload is None:
                await _answer_stale_questionnaire_callback(callback, message, session)
                return
            callback_token, callback_step_index, option_index = payload
            expected_token = QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.get(message.chat.id)
            if expected_token is None or callback_token != expected_token or callback_step_index != session.step_index:
                await _answer_stale_questionnaire_callback(callback, message, session)
                return

            try:
                answer = session.current_question.options[option_index]
            except IndexError:
                await _answer_stale_questionnaire_callback(callback, message, session)
                return

            await _mark_questionnaire_answer_selected(
                message,
                session.current_question,
                option_index,
                chat_id=message.chat.id,
                step_index=session.step_index,
            )
            await callback.answer(answer)
            await _handle_questionnaire_answer(message, answer)
        return

    await callback.answer()


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    if await _is_valid_pre_checkout_async(pre_checkout_query):
        await pre_checkout_query.answer(ok=True)
        return
    await pre_checkout_query.answer(
        ok=False,
        error_message="Не удалось проверить платеж. Попробуйте создать счет заново.",
    )


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    if await _reject_non_private_message(message):
        return
    payment = message.successful_payment
    if payment is None:
        return

    try:
        result = await _apply_successful_payment_async(
            message.chat.id,
            payment,
            user_id=_message_user_id(message),
        )
    except PaymentLedgerUnavailable as exc:
        _spool_failed_successful_payment(message, payment, exc)
        await _send_payment_activation_delayed_notice(message)
        return
    except EntitlementStorageError:
        logger.exception("Failed to apply payment due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return
    if result.duplicate:
        try:
            duplicate_status_text = await _format_entitlement_status_async(message.chat.id)
            reply_markup = await _payment_result_keyboard_async(message.chat.id, result)
        except EntitlementStorageError:
            logger.exception("Failed to render duplicate payment status due to entitlement storage error")
            await _send_entitlement_storage_error(message)
            return
        await message.answer(
            "Этот платеж уже был обработан. Текущие остатки:\n\n"
            f"{duplicate_status_text}",
            reply_markup=reply_markup,
        )
        return
    if not result.processed:
        await message.answer(
            "Платеж получен, но я не смог распознать его назначение. Напишите в поддержку, чтобы мы проверили оплату.",
            reply_markup=_subscription_payment_keyboard(),
        )
        return

    try:
        status_text = (
            await _subscriber_cabinet_text_async(message.chat.id)
            if result.grant == "subscription" or await _has_active_paid_access_async(message.chat.id)
            else await _format_entitlement_status_async(message.chat.id)
        )
        reply_markup = await _payment_result_keyboard_async(message.chat.id, result)
    except EntitlementStorageError:
        logger.exception("Failed to render payment status due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return
    await message.answer(
        _payment_success_text(result) + "\n\n" + status_text,
        reply_markup=reply_markup,
    )


@router.message()
async def handle_answer(message: Message) -> None:
    chat_id = message.chat.id
    if await _reject_non_private_message(message):
        return
    text = (message.text or "").strip()
    normalized_command = _normalize_command_text(text)
    if normalized_command == "myid":
        await myid(message)
        return
    if normalized_command == "privacy":
        await privacy(message)
        return
    if _is_support_chat(chat_id):
        SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
        PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(chat_id, None)
        return
    if normalized_command == "330366":
        await secret_access_command(message)
        return
    if text == SUPPORT_TEXT:
        await _start_support_request(message)
        return
    if chat_id in SUPPORT_REQUEST_CHAT_IDS and normalized_command is None:
        await _handle_support_request(message, text)
        return
    if chat_id in ADMIN_PROMO_ACTION_BY_CHAT_ID and normalized_command is None:
        await _handle_admin_promo_action_input(message, text)
        return
    if text == PROMO_CODE_TEXT:
        await _start_promo_code_request(message)
        return
    if text == PRIVACY_POLICY_TEXT:
        await _send_privacy_policy(message)
        return
    if chat_id in PROMO_CODE_REQUEST_CHAT_IDS and normalized_command is None:
        await _handle_promo_code_request(message, text)
        return
    if text == TRY_FREE_TEXT:
        await _start_questionnaire_with_privacy_consent(message, is_trial=True)
        return
    if text in {START_PLAN_TEXT, NEW_PROFILE_TEXT, CHANGE_PROFILE_TEXT}:
        await _start_questionnaire_with_privacy_consent(message)
        return
    if text == SUBSCRIBE_MONTH_TEXT:
        await _send_subscription_payment_options(message)
        return
    if text == FEATURES_TEXT:
        await message.answer(FEATURES_MESSAGE, reply_markup=_main_menu_keyboard(chat_id))
        return
    if text == REPEAT_PLAN_TEXT:
        await _repeat_plan(
            message,
            idempotency_key=_one_day_request_idempotency_key(message, None, event="repeat"),
        )
        return
    if text == ONE_DAY_PLAN_TEXT or text.startswith(SUBSCRIBER_ONE_DAY_PLAN_TEXT):
        profile_loaded, profile = await _load_profile_for_message_or_notice(message)
        if not profile_loaded:
            return
        if profile is None:
            await _start_questionnaire_with_privacy_consent(message)
            return
        await _send_one_day_plan_with_access(
            message,
            profile,
            idempotency_key=_one_day_request_idempotency_key(message, None, event="one_day"),
        )
        return
    if text == WEEK_PLAN_PDF_TEXT or text.startswith(SUBSCRIBER_WEEK_PLAN_PDF_TEXT):
        profile_loaded, profile = await _load_profile_for_message_or_notice(message)
        if not profile_loaded:
            return
        if profile is None:
            await _start_questionnaire_with_privacy_consent(message)
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
            reply_markup=_question_keyboard_for_session(chat_id, session),
        )
        return

    early_stop = next_session.should_stop_after_answer()
    if early_stop:
        _clear_questionnaire_session(chat_id)
        TRIAL_CHAT_IDS.discard(chat_id)
        await message.answer(early_stop, reply_markup=_main_menu_keyboard(chat_id))
        return

    if not next_session.is_complete:
        SESSION_BY_CHAT_ID[chat_id] = next_session
        await message.answer(
            next_session.current_question.prompt,
            reply_markup=_question_keyboard_for_session(chat_id, next_session),
        )
        return

    profile = next_session.build_profile()
    is_trial = chat_id in TRIAL_CHAT_IDS
    trial_session_token = QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.get(chat_id) if is_trial else None
    try:
        await _save_chat_profile_async(chat_id, profile)
    except ChatStateStorageError:
        logger.exception("Failed to save questionnaire profile for chat_id=%s", _mask_chat_id(chat_id))
        await _send_chat_profile_storage_error(message)
        return

    SESSION_BY_CHAT_ID[chat_id] = next_session
    PROFILE_BY_CHAT_ID[chat_id] = profile
    PLAN_COUNT_BY_CHAT_ID[chat_id] = 0
    PLAN_SEED_OFFSET_BY_CHAT_ID[chat_id] = random.SystemRandom().randrange(1, 1_000_000_000)
    try:
        await _load_chat_history_async(chat_id)
    except ChatStateStorageError:
        logger.exception("Failed to load chat history for chat_id=%s", _mask_chat_id(chat_id))
        await _send_chat_state_read_error(message)
        return
    trial_idempotency_key = _trial_plan_idempotency_key(chat_id, trial_session_token, profile) if is_trial else None
    _clear_questionnaire_session(chat_id)
    TRIAL_CHAT_IDS.discard(chat_id)
    if is_trial:
        await _send_trial_plan(message, profile, idempotency_key=trial_idempotency_key)
        return
    await _send_calculation_options(message, profile)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_bot() -> None:
    config = load_runtime_config()
    startup_issues = validate_startup(config)
    if startup_issues:
        raise RuntimeError("; ".join(startup_issues))
    assert config.bot_token is not None
    validate_chat_state_store_for_startup(config)
    _validate_entitlement_storage(config)
    validate_weekly_pdf_job_runtime_for_startup(config)
    validate_one_day_generation_job_store_for_startup(config)
    validate_payment_runtime_for_startup(config)
    single_poller_guard = _acquire_postgres_single_poller_guard(config)
    one_day_worker_task: asyncio.Task | None = None
    weekly_pdf_worker_task: asyncio.Task | None = None
    sales_followup_worker_task: asyncio.Task | None = None
    try:
        bot = Bot(config.bot_token)
        await _set_bot_commands(bot)
        dispatcher = create_dispatcher()
        weekly_pdf_worker_task = _start_weekly_pdf_worker_if_configured(config, bot)
        one_day_worker_task = _start_one_day_generation_worker_if_configured(config, bot)
        sales_followup_worker_task = _start_sales_followup_worker_if_configured(config, bot)
        worker_tasks = [
            task
            for task in (weekly_pdf_worker_task, one_day_worker_task, sales_followup_worker_task)
            if task is not None
        ]
        polling_task = asyncio.create_task(dispatcher.start_polling(bot), name="telegram-polling")
        try:
            await _run_polling_with_worker_supervision(polling_task, worker_tasks)
        finally:
            await _cancel_background_task(polling_task)
            for worker_task in worker_tasks:
                await _cancel_background_task(worker_task)
    finally:
        if single_poller_guard is not None:
            single_poller_guard.close()


async def _run_polling_with_worker_supervision(
    polling_task: asyncio.Task,
    worker_tasks: Sequence[asyncio.Task],
) -> None:
    if not worker_tasks:
        await polling_task
        return

    pending: set[asyncio.Task] = {polling_task, *worker_tasks}
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not polling_task:
                await _cancel_background_task(polling_task)
                _raise_worker_task_stopped(task)
        if polling_task in done:
            await polling_task
            return


def _raise_worker_task_stopped(task: asyncio.Task) -> None:
    label = _worker_task_label(task)
    if not task.cancelled():
        with suppress(Exception):
            task.exception()
    raise RuntimeError(f"{label} stopped unexpectedly")


def _worker_task_label(task: asyncio.Task) -> str:
    task_name = task.get_name()
    if task_name == "one-day-generation-worker":
        return "One-day worker"
    if task_name == "weekly-pdf-worker":
        return "Weekly PDF worker"
    if task_name == "sales-followup-worker":
        return "Sales follow-up worker"
    return "Worker"


async def _cancel_background_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
    except Exception:
        return


def _start_weekly_pdf_worker_if_configured(config, bot: Bot) -> asyncio.Task | None:
    if not getattr(config, "weekly_pdf_worker_enabled", False):
        return None
    runtime = _weekly_pdf_job_runtime()
    if runtime is None:
        logger.warning("Weekly PDF worker enabled but Postgres job runtime is unavailable")
        return None
    settings = WeeklyPdfWorkerSettings.from_config(config)
    worker = WeeklyPdfWorker(runtime, _TelegramWeeklyPdfJobProcessor(bot), settings)
    task = asyncio.create_task(worker.run_forever(), name="weekly-pdf-worker")
    _observe_worker_task(task, "Weekly PDF worker")
    return task


def _start_one_day_generation_worker_if_configured(config, bot: Bot) -> asyncio.Task | None:
    if not getattr(config, "one_day_worker_enabled", False):
        return None
    runtime = _one_day_generation_job_runtime()
    if runtime is None:
        logger.warning("One-day worker enabled but Postgres job runtime is unavailable")
        return None
    settings = OneDayGenerationWorkerSettings.from_config(config)
    worker = OneDayGenerationWorker(runtime, _TelegramOneDayGenerationJobProcessor(bot), settings)
    task = asyncio.create_task(worker.run_forever(), name="one-day-generation-worker")
    _observe_worker_task(task, "One-day worker")
    return task


def _start_sales_followup_worker_if_configured(config, bot: Bot) -> asyncio.Task | None:
    if not getattr(config, "sales_followup_worker_enabled", False):
        return None
    runtime = _sales_followup_job_runtime()
    if runtime is None:
        logger.warning("Sales follow-up worker enabled but Postgres job runtime is unavailable")
        return None
    settings = SalesFollowupWorkerSettings.from_config(config)
    worker = SalesFollowupWorker(
        runtime,
        _TelegramSalesFollowupSender(bot),
        eligibility_checker=_sales_followup_production_eligibility,
        settings=settings,
    )
    task = asyncio.create_task(worker.run_forever(), name="sales-followup-worker")
    _observe_worker_task(task, "Sales follow-up worker")
    return task


def _observe_worker_task(task: asyncio.Task, label: str) -> None:
    def log_unexpected_stop(done_task: asyncio.Task) -> None:
        if done_task.cancelled():
            return
        try:
            exc = done_task.exception()
        except asyncio.CancelledError:
            return
        if exc is None:
            return
        logger.error(
            "%s task stopped unexpectedly; task_name=%s error_type=%s",
            label,
            done_task.get_name(),
            type(exc).__name__,
        )

    task.add_done_callback(log_unexpected_stop)


def _acquire_postgres_single_poller_guard(config):
    if config.storage_backend != "postgres":
        return None
    assert config.database_url is not None
    from .postgres_single_poller_guard import PostgresSinglePollerGuard

    return PostgresSinglePollerGuard(config.database_url).acquire()


def main() -> None:
    asyncio.run(run_bot())


def _telegram_chunks(text: str, limit: int = TELEGRAM_MESSAGE_CHUNK_MAX_CHARS) -> list[str]:
    return telegram_text_chunks(text, limit=limit)


async def _set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)


def _is_private_chat_message(message: Message) -> bool:
    chat_type = getattr(getattr(message, "chat", None), "type", None)
    if chat_type is None:
        return True
    return str(getattr(chat_type, "value", chat_type)).lower() == "private"


def _message_chat_type(message: Message) -> str | None:
    chat_type = getattr(getattr(message, "chat", None), "type", None)
    if chat_type is None:
        return None
    return str(getattr(chat_type, "value", chat_type)).lower()


def _chat_type_is_private(chat_type: object) -> bool:
    if chat_type is None:
        return False
    return str(getattr(chat_type, "value", chat_type)).lower() == "private"


def _sales_followup_production_eligibility(job: object) -> SalesFollowupEligibility:
    chat_type = _sales_followup_job_chat_type(job)
    if chat_type is not None and not _chat_type_is_private(chat_type):
        return SalesFollowupEligibility.blocked("non_private_chat")

    chat_id = int(getattr(job, "chat_id"))
    if _has_active_paid_access(chat_id):
        return SalesFollowupEligibility.blocked("active_paid_access")
    if _weekly_pdf_attempt_available(chat_id):
        return SalesFollowupEligibility.blocked("weekly_pdf_access")
    return SalesFollowupEligibility.allowed()


def _sales_followup_job_chat_type(job: object) -> object | None:
    chat_type = getattr(job, "chat_type", None)
    if chat_type is not None:
        return chat_type
    payload = getattr(job, "payload", None)
    if isinstance(payload, Mapping):
        return payload.get("chat_type")
    return None


async def _reject_non_private_message(message: Message) -> bool:
    if _is_private_chat_message(message):
        return False
    await message.answer(PRIVATE_CHAT_REQUIRED_TEXT)
    return True


async def _reject_non_private_callback(callback: CallbackQuery, message: Message) -> bool:
    if _is_private_chat_message(message):
        return False
    with suppress(TypeError):
        await callback.answer(PRIVATE_CHAT_CALLBACK_TEXT, show_alert=True)
        return True
    await callback.answer(PRIVATE_CHAT_CALLBACK_TEXT)
    return True


async def _handle_sales_followup_opt_out_callback(callback: CallbackQuery, message: Message) -> None:
    store = _sales_followup_store()
    if store is not None:
        try:
            await _run_sales_followup_db_call(
                store.set_opt_out,
                message.chat.id,
                opt_out_source="telegram_callback",
            )
            cancel_jobs = getattr(store, "cancel_active_jobs_for_chat_campaign", None)
            if callable(cancel_jobs):
                await _run_sales_followup_db_call(
                    cancel_jobs,
                    chat_id=message.chat.id,
                    campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
                    reason="opted_out",
                    chain_status="opted_out",
                )
        except Exception:
            logger.exception(
                "Failed to persist sales follow-up opt-out for chat_id=%s",
                _mask_chat_id(message.chat.id),
            )
            await callback.answer("Не удалось сохранить настройку. Попробуйте позже.")
            return

    await callback.answer()
    await _confirm_sales_followup_opt_out(message)


async def _confirm_sales_followup_opt_out(message: Message) -> None:
    edit_text = getattr(message, "edit_text", None)
    if callable(edit_text):
        try:
            await edit_text(SALES_FOLLOWUP_OPT_OUT_CONFIRMATION_TEXT, reply_markup=None)
            return
        except Exception:
            logger.exception(
                "Failed to edit sales follow-up opt-out confirmation for chat_id=%s",
                _mask_chat_id(message.chat.id),
            )
    await message.answer(SALES_FOLLOWUP_OPT_OUT_CONFIRMATION_TEXT)


async def _start_support_request(message: Message) -> None:
    PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)
    ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
    SUPPORT_REQUEST_CHAT_IDS.add(message.chat.id)
    await message.answer(SUPPORT_PROMPT_TEXT)


async def _start_promo_code_request(message: Message) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
    _clear_questionnaire_session(message.chat.id)
    TRIAL_CHAT_IDS.discard(message.chat.id)
    PROMO_CODE_REQUEST_CHAT_IDS.add(message.chat.id)
    await message.answer(PROMO_CODE_PROMPT_TEXT)


async def _handle_promo_code_request(message: Message, text: str) -> None:
    if not text:
        await message.answer(PROMO_CODE_EMPTY_TEXT)
        return

    try:
        activation = _activate_promo_code_for_chat(message.chat.id, text)
    except EntitlementStorageError:
        logger.exception("Failed to activate promo entitlement due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return
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
    if activation.status == "disabled":
        await message.answer(PROMO_CODE_DISABLED_TEXT)
        return
    if activation.status == "expired":
        await message.answer(PROMO_CODE_EXPIRED_TEXT)
        return
    if activation.status == "not_access_code":
        await message.answer(PROMO_CODE_NOT_ACCESS_TEXT)
        return
    await message.answer(PROMO_CODE_NOT_FOUND_TEXT)


async def _send_privacy_policy(message: Message) -> None:
    text = PRIVACY_POLICY_BODY_TEXT
    if PRIVACY_POLICY_URL:
        text = f"{text}\n\nПолная версия: {PRIVACY_POLICY_URL}"
    await message.answer(text, reply_markup=_privacy_policy_actions_keyboard())


def _privacy_policy_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


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


def _clear_questionnaire_session(chat_id: int) -> None:
    SESSION_BY_CHAT_ID.pop(chat_id, None)
    QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.pop(chat_id, None)


def _questionnaire_callback_lock(chat_id: int) -> asyncio.Lock:
    lock = _QUESTIONNAIRE_CALLBACK_LOCK_BY_CHAT_ID.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _QUESTIONNAIRE_CALLBACK_LOCK_BY_CHAT_ID[chat_id] = lock
    return lock


def _parse_questionnaire_answer_callback(data: str) -> tuple[str, int, int] | None:
    parts = data.removeprefix(CALLBACK_ANSWER_PREFIX).split(":")
    if len(parts) != 3:
        return None
    token, step_index_text, option_index_text = parts
    if not token:
        return None
    try:
        return token, int(step_index_text), int(option_index_text)
    except ValueError:
        return None


async def _answer_stale_questionnaire_callback(
    callback: CallbackQuery,
    message: Message,
    session: QuestionnaireSession,
) -> None:
    await callback.answer(STALE_QUESTIONNAIRE_CALLBACK_TEXT)
    if session.current_question is None:
        await message.answer(
            "Нажмите кнопку, чтобы составить рацион 👇",
            reply_markup=_main_menu_keyboard(message.chat.id),
        )
        return
    await message.answer(
        session.current_question.prompt,
        reply_markup=_question_keyboard_for_session(message.chat.id, session),
    )


async def _start_questionnaire(message: Message, *, is_trial: bool = False) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    session = start_session()
    SESSION_BY_CHAT_ID[message.chat.id] = session
    QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID[message.chat.id] = secrets.token_urlsafe(6)
    if is_trial:
        TRIAL_CHAT_IDS.add(message.chat.id)
    else:
        TRIAL_CHAT_IDS.discard(message.chat.id)
    await message.answer(
        session.current_question.prompt,
        reply_markup=_question_keyboard_for_session(message.chat.id, session),
    )


async def _start_questionnaire_with_privacy_consent(message: Message, *, is_trial: bool = False) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)
    try:
        has_consent = await _has_privacy_consent_async(message.chat.id)
    except ChatStateStorageError:
        await _send_chat_state_read_error(message)
        return
    if has_consent:
        await _start_questionnaire(message, is_trial=is_trial)
        return
    await message.answer(
        PRIVACY_CONSENT_TEXT,
        reply_markup=_privacy_consent_keyboard(is_trial=is_trial),
    )


async def _repeat_plan(message: Message, *, idempotency_key: str | None = None) -> None:
    profile_loaded, profile = await _load_profile_for_message_or_notice(message)
    if not profile_loaded:
        return
    if profile is None:
        await _start_questionnaire_with_privacy_consent(message)
        return
    await _send_one_day_plan_with_access(
        message,
        profile,
        idempotency_key=idempotency_key or _one_day_request_idempotency_key(message, None, event="repeat"),
    )


async def _send_calculation_options(message: Message, profile: UserProfile) -> None:
    await _send_calculation_report(
        message,
        profile,
        reply_markup=await _ration_choice_keyboard_for_chat_async(message.chat.id),
    )


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


async def _send_trial_plan(
    message: Message,
    profile: UserProfile,
    *,
    idempotency_key: str | None = None,
) -> None:
    trial_idempotency_key = idempotency_key or _trial_plan_idempotency_key(
        message.chat.id,
        QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.get(message.chat.id),
        profile,
    )
    runtime = _one_day_generation_job_runtime()
    if runtime is not None:
        await _send_trial_plan_with_postgres_job(
            message,
            profile,
            runtime=runtime,
            idempotency_key=trial_idempotency_key,
        )
        return

    try:
        consumption = await _consume_generation_attempt_async(message.chat.id, "one_day")
    except EntitlementStorageError:
        logger.exception("Failed to consume trial entitlement due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return
    if not consumption.allowed:
        await _send_limit_paywall(message, "one_day")
        return

    try:
        await _send_calculation_report(message, profile)
        sent = await _send_plan(message, profile, include_default_after_plan_keyboard=False)
    except Exception:
        await _refund_generation_attempt_async(message.chat.id, consumption)
        raise

    if not sent:
        await _refund_generation_attempt_async(message.chat.id, consumption)
        return

    if sent:
        await _send_trial_subscription_cta(message)
        await _schedule_sales_followup_after_trial_success(
            chat_id=message.chat.id,
            chat_type=_message_chat_type(message),
            source=consumption.source,
            include_trial_subscription_cta=True,
            trigger_id=trial_idempotency_key,
        )


def _trial_plan_idempotency_key(chat_id: int, session_token: str | None, profile: UserProfile) -> str:
    if session_token:
        return f"telegram_trial_session:{chat_id}:{session_token}:one_day"

    profile_payload = {
        "age": profile.age,
        "sex": profile.sex.value,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "goal": profile.goal.value,
        "activity": profile.activity.value,
        "meal_count": profile.meal_count,
        "cooking_time": profile.cooking_time.value,
        "restrictions": [
            {"type": restriction.type.value, "value": restriction.value, "severity": restriction.severity}
            for restriction in profile.restrictions
        ],
        "conditions": [str(condition) for condition in profile.conditions],
        "allow_lactose_free_dairy": profile.allow_lactose_free_dairy,
        "allow_gluten_free_oats": profile.allow_gluten_free_oats,
    }
    digest = hashlib.sha256(
        json.dumps(profile_payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"telegram_trial_profile:{chat_id}:{digest}:one_day"


async def _send_trial_subscription_cta(message: Message) -> None:
    await message.answer(
        TRIAL_SUBSCRIPTION_TEXT + "\n\n" + await _format_entitlement_status_async(message.chat.id),
        reply_markup=_trial_subscription_keyboard(),
    )


async def _schedule_sales_followup_after_trial_success(
    *,
    chat_id: int,
    chat_type: object,
    source: str | None,
    include_trial_subscription_cta: bool,
    trigger_id: object,
    trigger_job_id: object | None = None,
) -> None:
    feature_enabled = _sales_followup_runtime_enabled()
    store = _sales_followup_store() if feature_enabled else None
    has_active_paid_access = False
    has_weekly_pdf_access = False
    if feature_enabled and store is not None:
        try:
            has_active_paid_access = await _has_active_paid_access_async(chat_id)
            has_weekly_pdf_access = await _weekly_pdf_attempt_available_async(chat_id)
        except Exception:
            logger.exception(
                "Sales follow-up eligibility check failed for chat_id=%s; skipping schedule",
                _mask_chat_id(chat_id),
            )
            return

    try:
        result = schedule_sales_followup_after_free_trial_delivery(
            store=store,
            chat_id=chat_id,
            chat_is_private=_chat_type_is_private(chat_type),
            feature_enabled=feature_enabled,
            delivery_succeeded=True,
            source=source,
            include_trial_subscription_cta=include_trial_subscription_cta,
            has_active_paid_access=has_active_paid_access,
            has_weekly_pdf_access=has_weekly_pdf_access,
            trigger_idempotency_key=build_sales_followup_trigger_idempotency_key(
                chat_id=chat_id,
                trigger_id=trigger_id,
            ),
            triggered_at=datetime.now(UTC),
            trigger_job_id=trigger_job_id,
        )
    except Exception:
        logger.exception(
            "Sales follow-up schedule admission failed for chat_id=%s",
            _mask_chat_id(chat_id),
        )
        return

    logger.info(
        "Sales follow-up schedule admission result for chat_id=%s status=%s",
        _mask_chat_id(chat_id),
        result.status.value,
    )


async def _send_trial_plan_with_postgres_job(
    message: Message,
    profile: UserProfile,
    *,
    runtime: OneDayGenerationJobRuntime,
    idempotency_key: str,
) -> bool:
    chat_id = message.chat.id
    try:
        runtime.cleanup_stale(chat_id=chat_id)
    except Exception:
        logger.exception("Failed to cleanup stale trial one-day generation jobs")

    try:
        await _load_chat_history_async(chat_id)
    except ChatStateStorageError:
        logger.exception("Failed to load chat history for queued trial one-day job chat_id=%s", _mask_chat_id(chat_id))
        status_message = await message.answer(ONE_DAY_PLAN_STATUS_TEXT, reply_markup=ReplyKeyboardRemove())
        await _send_chat_state_read_error(message, status_message=status_message)
        return False

    try:
        job_admission = runtime.admit_queued(
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            request_snapshot=_one_day_request_snapshot(
                chat_id,
                profile,
                request_kind="telegram_trial",
                request_payload={
                    "source": "telegram_trial",
                    "chat_type": _message_chat_type(message),
                    "include_calculation_report": True,
                    "include_default_after_plan_keyboard": False,
                    "include_entitlement_status": False,
                    "include_trial_subscription_cta": True,
                },
            ),
            metadata={"source": "telegram_trial"},
            test_access=False,
        )
    except Exception:
        logger.exception("Failed to admit trial one-day generation Postgres job")
        await _send_entitlement_storage_error(message)
        return False

    if job_admission.status in {
        OneDayQueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE,
        OneDayQueuedJobAdmissionResultStatus.EXISTING_IDEMPOTENCY,
    }:
        await message.answer(ONE_DAY_PLAN_ALREADY_RUNNING_TEXT)
        return False

    if job_admission.status == OneDayQueuedJobAdmissionResultStatus.DENIED:
        await _send_limit_paywall(message, "one_day")
        return False

    if job_admission.status != OneDayQueuedJobAdmissionResultStatus.ADMITTED or job_admission.job is None:
        await _send_entitlement_storage_error(message)
        return False

    _mark_one_day_generation_seed_admitted(chat_id)
    await message.answer(ONE_DAY_PLAN_ACCEPTED_TEXT)
    return True


def _try_enter_one_day_plan_generation(chat_id: int) -> bool:
    with _ONE_DAY_PLAN_IN_FLIGHT_LOCK:
        if chat_id in _ONE_DAY_PLAN_IN_FLIGHT_CHAT_IDS:
            return False
        _ONE_DAY_PLAN_IN_FLIGHT_CHAT_IDS.add(chat_id)
        return True


def _release_one_day_plan_generation(chat_id: int) -> None:
    with _ONE_DAY_PLAN_IN_FLIGHT_LOCK:
        _ONE_DAY_PLAN_IN_FLIGHT_CHAT_IDS.discard(chat_id)


async def _send_one_day_plan_with_access(
    message: Message,
    profile: UserProfile,
    *,
    idempotency_key: str | None = None,
) -> bool:
    chat_id = message.chat.id
    runtime = _one_day_generation_job_runtime()
    if runtime is not None:
        return await _send_one_day_plan_with_postgres_job(
            message,
            profile,
            runtime=runtime,
            idempotency_key=_one_day_request_idempotency_key(message, idempotency_key, event="one_day"),
        )

    if not _try_enter_one_day_plan_generation(chat_id):
        await message.answer(ONE_DAY_PLAN_ALREADY_RUNNING_TEXT)
        return False

    try:
        try:
            consumption = await _consume_generation_attempt_async(chat_id, "one_day")
        except EntitlementStorageError:
            logger.exception("Failed to consume one-day entitlement due to entitlement storage error")
            await _send_entitlement_storage_error(message)
            return False
        if not consumption.allowed:
            await _send_limit_paywall(message, "one_day")
            return False

        try:
            sent = await _send_plan(
                message,
                profile,
                status_text=await _format_entitlement_status_async(chat_id),
            )
        except Exception:
            await _refund_generation_attempt_async(chat_id, consumption)
            raise

        if not sent:
            await _refund_generation_attempt_async(chat_id, consumption)
        return sent
    finally:
        _release_one_day_plan_generation(chat_id)


async def _send_one_day_plan_with_postgres_job(
    message: Message,
    profile: UserProfile,
    *,
    runtime: OneDayGenerationJobRuntime,
    idempotency_key: str,
) -> bool:
    chat_id = message.chat.id
    try:
        runtime.cleanup_stale(chat_id=chat_id)
    except Exception:
        logger.exception("Failed to cleanup stale one-day generation jobs")

    try:
        await _load_chat_history_async(chat_id)
    except ChatStateStorageError:
        logger.exception("Failed to load chat history for queued one-day job chat_id=%s", _mask_chat_id(chat_id))
        status_message = await message.answer(ONE_DAY_PLAN_STATUS_TEXT, reply_markup=ReplyKeyboardRemove())
        await _send_chat_state_read_error(message, status_message=status_message)
        return False

    try:
        job_admission = runtime.admit_queued(
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            request_snapshot=_one_day_request_snapshot(
                chat_id,
                profile,
                request_kind="telegram_one_day",
                request_payload={
                    "source": "telegram_one_day",
                    "include_calculation_report": False,
                    "include_default_after_plan_keyboard": True,
                    "include_entitlement_status": True,
                    "include_trial_subscription_cta": False,
                },
            ),
            metadata={"source": "telegram_one_day"},
            test_access=chat_id in TESTER_CHAT_IDS,
        )
    except Exception:
        logger.exception("Failed to admit one-day generation Postgres job")
        await _send_entitlement_storage_error(message)
        return False

    if job_admission.status in {
        OneDayQueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE,
        OneDayQueuedJobAdmissionResultStatus.EXISTING_IDEMPOTENCY,
    }:
        await message.answer(ONE_DAY_PLAN_ALREADY_RUNNING_TEXT)
        return False

    if job_admission.status == OneDayQueuedJobAdmissionResultStatus.DENIED:
        await _send_limit_paywall(message, "one_day")
        return False

    if job_admission.status != OneDayQueuedJobAdmissionResultStatus.ADMITTED or job_admission.job is None:
        await _send_entitlement_storage_error(message)
        return False

    _mark_one_day_generation_seed_admitted(chat_id)
    await message.answer(ONE_DAY_PLAN_ACCEPTED_TEXT)
    return True


def _finish_one_day_postgres_job_failure(
    runtime: OneDayGenerationJobRuntime,
    job_id: object,
    *,
    chat_id: int,
    reason: str,
) -> None:
    try:
        runtime.finish_failure_and_refund_once(job_id, reason=reason)
    except Exception:
        logger.exception(
            "Failed to finalize failed one-day generation Postgres job for chat_id=%s",
            _mask_chat_id(chat_id),
        )


def _one_day_request_snapshot(
    chat_id: int,
    profile: UserProfile,
    *,
    request_kind: str,
    request_payload: Mapping[str, object] | None = None,
) -> OneDayGenerationRequestSnapshot:
    payload = dict(request_payload or {})
    payload["recent_recipe_keys"] = list(RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, ()))
    seed = _one_day_generation_seed_candidate(chat_id)
    return OneDayGenerationRequestSnapshot(
        request_kind=request_kind,
        request_payload=payload,
        profile=_profile_to_dict(profile),
        recent_recipe_ids=tuple(RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, ())),
        generation_seed=str(seed),
    )


def _one_day_generation_seed_candidate(chat_id: int) -> int:
    count = PLAN_COUNT_BY_CHAT_ID.get(chat_id, 0)
    seed_offset = PLAN_SEED_OFFSET_BY_CHAT_ID.setdefault(
        chat_id,
        random.SystemRandom().randrange(1, 1_000_000_000),
    )
    return seed_offset + count


def _mark_one_day_generation_seed_admitted(chat_id: int) -> None:
    PLAN_COUNT_BY_CHAT_ID[chat_id] = PLAN_COUNT_BY_CHAT_ID.get(chat_id, 0) + 1


def _one_day_callback_idempotency_key(callback: CallbackQuery) -> str | None:
    callback_id = getattr(callback, "id", None)
    data = getattr(callback, "data", None)
    if callback_id and data:
        return f"telegram_callback:{callback_id}:{data}"
    if callback_id:
        return f"telegram_callback:{callback_id}"
    message = getattr(callback, "message", None)
    message_id = getattr(message, "message_id", None)
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    if data and chat_id is not None and message_id is not None:
        return f"telegram_callback_data:{chat_id}:{message_id}:{data}"
    return None


def _one_day_request_idempotency_key(message: Message, idempotency_key: str | None, *, event: str) -> str:
    if idempotency_key:
        return idempotency_key
    message_id = getattr(message, "message_id", None)
    if message_id is not None:
        return f"telegram_message:{message.chat.id}:{message_id}:{event}"
    return f"telegram_request:{message.chat.id}:{event}:{time.time_ns()}"


def _weekly_pdf_callback_idempotency_key(callback: CallbackQuery) -> str | None:
    callback_id = getattr(callback, "id", None)
    if not callback_id:
        return None
    return f"telegram_callback:{callback_id}"


def _weekly_pdf_request_idempotency_key(message: Message, idempotency_key: str | None) -> str:
    if idempotency_key:
        return idempotency_key
    message_id = getattr(message, "message_id", None)
    if message_id is not None:
        return f"telegram_message:{message.chat.id}:{message_id}"
    return f"telegram_request:{message.chat.id}:{time.time_ns()}"


def _weekly_pdf_request_snapshot(chat_id: int, profile: UserProfile) -> WeeklyPdfRequestSnapshot:
    payload = {
        "source": "telegram_weekly_pdf",
        "recent_recipe_keys": list(RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, ())),
    }
    return WeeklyPdfRequestSnapshot(
        request_payload=payload,
        profile=_profile_to_dict(profile),
        recent_recipe_ids=tuple(RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, ())),
        generation_seed=str(_weekly_pdf_generation_seed_candidate(chat_id)),
    )


def _weekly_pdf_generation_seed_candidate(chat_id: int) -> int:
    count = PLAN_COUNT_BY_CHAT_ID.get(chat_id, 0)
    seed_offset = PLAN_SEED_OFFSET_BY_CHAT_ID.setdefault(
        chat_id,
        random.SystemRandom().randrange(1, 1_000_000_000),
    )
    return seed_offset + count


def _mark_weekly_pdf_generation_seed_admitted(chat_id: int) -> None:
    PLAN_COUNT_BY_CHAT_ID[chat_id] = PLAN_COUNT_BY_CHAT_ID.get(chat_id, 0) + WEEK_PLAN_DAYS * WEEK_PLAN_CANDIDATE_COUNT


async def _send_week_plan_with_access(
    message: Message,
    profile: UserProfile,
    *,
    idempotency_key: str | None = None,
) -> bool:
    chat_id = message.chat.id
    weekly_pdf_job_runtime = _weekly_pdf_job_runtime()
    if weekly_pdf_job_runtime is not None:
        return await _send_week_plan_with_postgres_jobs(
            message,
            profile,
            runtime=weekly_pdf_job_runtime,
            idempotency_key=_weekly_pdf_request_idempotency_key(message, idempotency_key),
        )

    if WEEK_PDF_QUEUE_MANAGER.has_chat(chat_id):
        _weekly_pdf_diag("queue_duplicate_precheck", chat_id=chat_id, **WEEK_PDF_QUEUE_MANAGER.snapshot())
        await message.answer(WEEK_PDF_ALREADY_RUNNING_TEXT)
        return False

    try:
        weekly_pdf_available = await _weekly_pdf_attempt_available_async(chat_id)
    except EntitlementStorageError:
        logger.exception("Failed to check weekly PDF entitlement due to entitlement storage error")
        _weekly_pdf_diag("access_error_entitlement_storage", chat_id=chat_id)
        await _send_entitlement_storage_error(message)
        return False

    if not weekly_pdf_available:
        _weekly_pdf_diag("access_denied_no_weekly_pdf_attempt", chat_id=chat_id)
        await _send_limit_paywall(message, "weekly_pdf")
        return False

    queued_status_message: Message | None = None

    async def run_weekly_pdf_job() -> bool:
        return await _send_week_plan_after_queue_admission(
            message,
            profile,
            initial_status_message=queued_status_message,
        )

    admission = WEEK_PDF_QUEUE_MANAGER.submit(chat_id, run_weekly_pdf_job)
    if admission.duplicate:
        await message.answer(WEEK_PDF_ALREADY_RUNNING_TEXT)
        return False

    if admission.future is None:
        return False

    if not admission.starts_immediately:
        try:
            queued_status_message = await message.answer(
                _week_pdf_queue_status_text(admission.ahead_count),
                reply_markup=ReplyKeyboardRemove(),
            )
        except asyncio.CancelledError:
            WEEK_PDF_QUEUE_MANAGER.cancel(admission.future)
            raise
        except Exception:
            WEEK_PDF_QUEUE_MANAGER.cancel(admission.future)
            raise
        WEEK_PDF_QUEUE_MANAGER.mark_ready(admission.future)

    try:
        return await admission.future
    except asyncio.CancelledError:
        _weekly_pdf_diag("queue_wait_cancelled", chat_id=chat_id, **WEEK_PDF_QUEUE_MANAGER.snapshot())
        WEEK_PDF_QUEUE_MANAGER.cancel(admission.future)
        raise


async def _send_week_plan_with_postgres_jobs(
    message: Message,
    profile: UserProfile,
    *,
    runtime: WeeklyPdfJobRuntime,
    idempotency_key: str,
) -> bool:
    chat_id = message.chat.id
    try:
        runtime.cleanup_stale(chat_id=chat_id)
    except Exception:
        logger.exception("Failed to cleanup stale weekly PDF jobs")
        _weekly_pdf_diag("postgres_cleanup_stale_failed", chat_id=chat_id)

    try:
        await _load_chat_history_async(chat_id)
    except ChatStateStorageError:
        logger.exception("Failed to load chat history for queued weekly PDF job chat_id=%s", _mask_chat_id(chat_id))
        await _send_chat_state_read_error(message)
        return False

    try:
        job_admission = runtime.admit_queued(
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            request_snapshot=_weekly_pdf_request_snapshot(chat_id, profile),
            metadata={"source": "telegram_weekly_pdf"},
            test_access=chat_id in TESTER_CHAT_IDS,
        )
    except Exception:
        logger.exception("Failed to admit weekly PDF Postgres job")
        _weekly_pdf_diag("postgres_admit_failed", chat_id=chat_id)
        await _send_entitlement_storage_error(message)
        return False

    if job_admission.status in {
        WeeklyPdfQueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE,
        WeeklyPdfQueuedJobAdmissionResultStatus.EXISTING_IDEMPOTENCY,
    }:
        _weekly_pdf_diag("postgres_admit_duplicate", chat_id=chat_id, status=job_admission.status.value)
        await message.answer(WEEK_PDF_ALREADY_RUNNING_TEXT)
        return False

    if job_admission.status == WeeklyPdfQueuedJobAdmissionResultStatus.DENIED:
        _weekly_pdf_diag("postgres_access_denied_no_weekly_pdf_attempt", chat_id=chat_id)
        await _send_limit_paywall(message, "weekly_pdf")
        return False

    if job_admission.status != WeeklyPdfQueuedJobAdmissionResultStatus.ADMITTED or job_admission.job is None:
        await _send_entitlement_storage_error(message)
        return False

    _mark_weekly_pdf_generation_seed_admitted(chat_id)
    return True


def _cancel_postgres_admitted_job(
    runtime: WeeklyPdfJobRuntime,
    job: WeeklyPdfJob,
    *,
    chat_id: int,
    reason: str,
) -> None:
    try:
        runtime.cancel_admitted_job(job.job_id, reason=reason)
    except Exception:
        logger.exception("Failed to cancel admitted weekly PDF Postgres job")
        _weekly_pdf_diag("postgres_cancel_admitted_failed", chat_id=chat_id, reason=reason)


async def _send_week_plan_after_postgres_admission(
    message: Message,
    profile: UserProfile,
    *,
    runtime: WeeklyPdfJobRuntime,
    job: WeeklyPdfJob,
    initial_status_message: Message | None = None,
) -> bool:
    chat_id = message.chat.id
    try:
        start_result = runtime.start_job_and_consume(
            job.job_id,
            test_access=chat_id in TESTER_CHAT_IDS,
        )
    except Exception:
        logger.exception("Failed to start weekly PDF Postgres job")
        _weekly_pdf_diag("postgres_start_failed", chat_id=chat_id)
        await _send_entitlement_storage_error(message)
        return False

    if start_result.status == StartJobResultStatus.DENIED:
        await _send_limit_paywall(message, "weekly_pdf")
        return False

    if start_result.status != StartJobResultStatus.STARTED or start_result.job is None:
        _weekly_pdf_diag("postgres_start_not_started", chat_id=chat_id, status=start_result.status.value)
        await message.answer(
            WEEK_PDF_ALREADY_RUNNING_TEXT
            if start_result.status == StartJobResultStatus.ALREADY_RUNNING
            else WEEK_PDF_FAILURE_TEXT
        )
        return False

    consumption = AttemptConsumption(True, "weekly_pdf", start_result.job.consumption_source)
    recipe_history_entries: list[RecipeHistoryItem] = []
    post_upload_finalized = False

    def mark_document_send_started() -> None:
        try:
            result = runtime.mark_send_started(job.job_id)
        except Exception as exc:
            logger.exception(
                "Failed to mark weekly PDF job send-start before Telegram upload chat_id=%s job_id=%s",
                _mask_chat_id(chat_id),
                redact_identifier("job", job.job_id),
            )
            _weekly_pdf_diag(
                "postgres_mark_send_started_failed_before_upload",
                chat_id=chat_id,
                job_id=str(job.job_id),
                error=type(exc).__name__,
            )
            raise

        if result.status not in {
            MarkSendStartedResultStatus.SEND_STARTED,
            MarkSendStartedResultStatus.ALREADY_SEND_STARTED,
        }:
            _weekly_pdf_diag(
                "postgres_mark_send_started_rejected_before_upload",
                chat_id=chat_id,
                job_id=str(job.job_id),
                status=result.status.value,
            )
            raise RuntimeError(f"Weekly PDF send-start marker was not persisted: {result.status.value}")

    def mark_document_delivered() -> None:
        nonlocal post_upload_finalized
        try:
            runtime.mark_delivered(job.job_id)
        except Exception as exc:
            marker_error = type(exc).__name__
            logger.exception(
                "Failed to mark weekly PDF job delivered after Telegram upload chat_id=%s job_id=%s",
                _mask_chat_id(chat_id),
                redact_identifier("job", job.job_id),
            )
            _weekly_pdf_diag(
                "postgres_mark_delivered_failed_after_upload",
                chat_id=chat_id,
                job_id=str(job.job_id),
                error=marker_error,
            )
            try:
                finish_result = runtime.finish_success(job.job_id)
            except Exception as finish_exc:
                logger.exception(
                    "Failed to finalize weekly PDF job as succeeded after delivered marker failure "
                    "chat_id=%s job_id=%s",
                    _mask_chat_id(chat_id),
                    redact_identifier("job", job.job_id),
                )
                _weekly_pdf_diag(
                    "postgres_finish_success_failed_after_mark_delivered_failed",
                    chat_id=chat_id,
                    job_id=str(job.job_id),
                    marker_error=marker_error,
                    error=type(finish_exc).__name__,
                )
                return
            post_upload_finalized = finish_result.status in {
                FinishJobResultStatus.SUCCEEDED,
                FinishJobResultStatus.ALREADY_TERMINAL,
            }
            _weekly_pdf_diag(
                "postgres_finish_success_after_mark_delivered_failed",
                chat_id=chat_id,
                job_id=str(job.job_id),
                marker_error=marker_error,
                status=finish_result.status.value,
            )

    try:
        sent = await _send_week_plan(
            message,
            profile,
            status_text=await _format_entitlement_status_async(chat_id),
            recipe_history_entries=recipe_history_entries,
            pdf_slot_acquired=True,
            initial_status_message=initial_status_message,
            on_document_send_started=mark_document_send_started,
            on_document_delivered=mark_document_delivered,
        )
    except Exception:
        if not post_upload_finalized:
            _finish_postgres_job_failure(
                runtime,
                job,
                chat_id=chat_id,
                reason="weekly_pdf_exception",
            )
        raise

    if not sent:
        if not post_upload_finalized:
            _finish_postgres_job_failure(
                runtime,
                job,
                chat_id=chat_id,
                reason="weekly_pdf_not_sent",
            )
        return False

    if not post_upload_finalized:
        runtime.finish_success(job.job_id)
    await _record_successful_generation_history_async(chat_id, consumption, recipe_history_entries)
    return True


def _finish_postgres_job_failure(
    runtime: WeeklyPdfJobRuntime,
    job: WeeklyPdfJob,
    *,
    chat_id: int,
    reason: str,
) -> None:
    try:
        runtime.finish_failure_and_refund_once(job.job_id, reason=reason)
    except Exception:
        logger.exception("Failed to finalize failed weekly PDF Postgres job")
        _weekly_pdf_diag("postgres_finish_failure_failed", chat_id=chat_id, reason=reason)


async def _send_week_plan_after_queue_admission(
    message: Message,
    profile: UserProfile,
    *,
    initial_status_message: Message | None = None,
) -> bool:
    consumption: AttemptConsumption | None = None
    try:
        consume_started_at = time.perf_counter()
        _weekly_pdf_diag("consume_attempt_start", chat_id=message.chat.id)
        try:
            consumption = await _consume_generation_attempt_async(message.chat.id, "weekly_pdf")
        except EntitlementStorageError:
            logger.exception("Failed to consume weekly PDF entitlement due to entitlement storage error")
            await _send_entitlement_storage_error(message)
            return False
        _weekly_pdf_diag(
            "consume_attempt_end",
            chat_id=message.chat.id,
            elapsed_s=time.perf_counter() - consume_started_at,
            allowed=consumption.allowed,
            source=consumption.source,
        )
        if not consumption.allowed:
            await _send_limit_paywall(message, "weekly_pdf")
            return False

        recipe_history_entries: list[RecipeHistoryItem] = []
        sent = await _send_week_plan(
            message,
            profile,
            status_text=await _format_entitlement_status_async(message.chat.id),
            recipe_history_entries=recipe_history_entries,
            pdf_slot_acquired=True,
            initial_status_message=initial_status_message,
        )
    except Exception:
        if consumption is not None and consumption.allowed:
            await _refund_generation_attempt_async(message.chat.id, consumption)
        raise

    if not sent:
        await _refund_generation_attempt_async(message.chat.id, consumption)
    else:
        _complete_generation_attempt(message.chat.id, consumption)
        await _record_successful_generation_history_async(
            message.chat.id,
            consumption,
            recipe_history_entries,
        )
    return sent

def _weekly_pdf_attempt_available(chat_id: int) -> bool:
    return _dry_run_generation_attempt(chat_id, "weekly_pdf").allowed

def _week_pdf_queue_status_text(ahead_count: int) -> str:
    normalized_ahead_count = max(0, int(ahead_count))
    wait_minutes = _week_pdf_queue_wait_minutes(normalized_ahead_count)
    return (
        "Не переживайте, файл генерируется.\n\n"
        f"Сейчас перед вами {_ru_plural(normalized_ahead_count, 'человек', 'человека', 'человек')}, "
        f"примерное ожидание {_ru_plural(wait_minutes, 'минута', 'минуты', 'минут')}."
    )

def _week_pdf_queue_wait_minutes(ahead_count: int) -> int:
    concurrency = max(1, WEEKLY_PDF_MAX_CONCURRENCY)
    batches_before_start = max(1, math.ceil(max(1, ahead_count) / concurrency))
    return max(1, math.ceil((batches_before_start * WEEK_PDF_QUEUE_ESTIMATED_JOB_SECONDS) / 60))

def _ru_plural(value: int, one: str, few: str, many: str) -> str:
    absolute = abs(value)
    if 11 <= absolute % 100 <= 14:
        word = many
    elif absolute % 10 == 1:
        word = one
    elif 2 <= absolute % 10 <= 4:
        word = few
    else:
        word = many
    return f"{value} {word}"

async def _send_plan(
    message: Message,
    profile: UserProfile,
    *,
    final_reply_markup: InlineKeyboardMarkup | None = None,
    include_default_after_plan_keyboard: bool = True,
    status_text: str | None = None,
    on_expected_value_messages: Callable[[int], None] | None = None,
    on_value_send_start: Callable[[], None] | None = None,
    on_value_message_delivered: Callable[[str], None] | None = None,
) -> bool:
    chat_id = message.chat.id
    count = PLAN_COUNT_BY_CHAT_ID.get(chat_id, 0)
    seed_offset = PLAN_SEED_OFFSET_BY_CHAT_ID.setdefault(
        chat_id,
        random.SystemRandom().randrange(1, 1_000_000_000),
    )
    seed = seed_offset + count
    PLAN_COUNT_BY_CHAT_ID[chat_id] = count + 1
    status_message = await message.answer(ONE_DAY_PLAN_STATUS_TEXT, reply_markup=ReplyKeyboardRemove())
    try:
        await _load_chat_history_async(chat_id)
    except ChatStateStorageError:
        logger.exception("Failed to load chat history for chat_id=%s", _mask_chat_id(chat_id))
        await _send_chat_state_read_error(message, status_message=status_message)
        return False
    recent_recipe_ids = set(RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, []))
    recent_recipe_keys = set(RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, []))
    plan_result = await asyncio.to_thread(
        build_one_day_plan,
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
    if on_expected_value_messages is not None:
        on_expected_value_messages(len(plan_result.meals) + 2)
    if on_value_send_start is not None:
        on_value_send_start()
    for meal_index, meal in enumerate(plan_result.meals):
        await _send_meal_card(message, meal)
        if on_value_message_delivered is not None:
            on_value_message_delivered(_one_day_meal_value_message_key(meal_index, meal))
    await _remember_recipe_history_items_best_effort_async(
        chat_id,
        _recipe_history_items_from_plan(plan_result, "one_day"),
        ration_kind="one_day",
        context="after_one_day_meal_delivery",
    )
    plan_reply_markup = final_reply_markup
    if plan_reply_markup is None and include_default_after_plan_keyboard:
        plan_reply_markup = _after_plan_keyboard(message.chat.id)
    summary_keys = ("summary:daily_totals", "summary:shopping")
    summary_messages = messages[2:]
    for index, response in enumerate(summary_messages):
        markup = plan_reply_markup if index == len(summary_messages) - 1 else None
        await _send_text_chunks(message, response, markup)
        if on_value_message_delivered is not None and index < len(summary_keys):
            on_value_message_delivered(summary_keys[index])
    return True


def _one_day_meal_value_message_key(index: int, meal: Meal) -> str:
    recipe_key = meal.recipe_id or meal.recipe_key
    if not recipe_key:
        name_hash = hashlib.sha256(meal.name.encode("utf-8")).hexdigest()[:16]
        recipe_key = f"name_hash:{name_hash}"
    return f"meal:{index:02d}:{recipe_key}"


class _TelegramOneDayGenerationJobProcessor:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def prepare_delivery(self, job: OneDayGenerationJob) -> OneDayGenerationDelivery:
        return await _prepare_one_day_generation_delivery(job, self.bot)


class _TelegramSalesFollowupSender:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, request: SalesFollowupSendRequest) -> SalesFollowupSendResult:
        payload = dict(request.payload or {})
        payload.setdefault("message_text", request.message_text)
        if request.button_label is not None:
            payload.setdefault("button_label", request.button_label)
        if request.target_callback_data is not None:
            payload.setdefault("target_callback_data", request.target_callback_data)
        rendered = render_sales_followup_payload(payload)
        if not rendered.sendable:
            raise SalesFollowupPermanentSendError(rendered.failure_reason or "sales_followup_not_sendable")

        try:
            sent = await safe_telegram_send(
                lambda: self.bot.send_message(
                    chat_id=request.chat_id,
                    text=rendered.message_text,
                    reply_markup=_sales_followup_inline_keyboard(rendered.keyboard),
                ),
                operation_name="sales_followup_worker_send_message",
            )
        except TelegramSendError as exc:
            if exc.result.classification == TelegramSendFailureClass.RETRYABLE:
                raise SalesFollowupTransientSendError(str(exc)) from exc
            if exc.result.classification == TelegramSendFailureClass.PERMANENT:
                raise SalesFollowupPermanentSendError(str(exc)) from exc
            raise SalesFollowupUnknownSendOutcome(str(exc)) from exc
        return SalesFollowupSendResult(telegram_message_id=getattr(sent, "message_id", None))


def _sales_followup_inline_keyboard(
    rows: tuple[tuple[tuple[str, str], ...], ...],
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=callback_data) for text, callback_data in row]
            for row in rows
        ],
    )


class _OneDayJobChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.type = "private"


class _OneDayJobMessage:
    def __init__(self, *, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat = _OneDayJobChat(chat_id)
        self.message_id = None

    async def answer(self, text: str, reply_markup=None):
        return await safe_telegram_send(
            lambda: self.bot.send_message(chat_id=self.chat.id, text=text, reply_markup=reply_markup),
            operation_name="one_day_worker_send_message",
        )

    async def answer_photo(self, **kwargs):
        return await safe_telegram_send(
            lambda: self.bot.send_photo(chat_id=self.chat.id, **kwargs),
            operation_name="one_day_worker_send_photo",
        )


async def _prepare_one_day_generation_delivery(job: OneDayGenerationJob, bot: Bot) -> OneDayGenerationDelivery:
    snapshot = job.request_snapshot
    if snapshot is None:
        raise RuntimeError("one-day job snapshot is missing")
    profile = _profile_from_dict(snapshot.profile)
    if profile is None:
        raise RuntimeError("one-day job profile snapshot is invalid")

    request_payload = dict(snapshot.request_payload)
    message = _OneDayJobMessage(bot=bot, chat_id=job.chat_id)
    plan_result = await asyncio.to_thread(
        build_one_day_plan,
        profile,
        variety_seed=_generation_seed_from_snapshot(snapshot),
        avoided_recipe_ids=set(snapshot.recent_recipe_ids),
        avoided_recipe_keys=set(_recent_recipe_keys_from_snapshot(snapshot)),
        recipe_source="curated_only",
    )
    plan_result = _annotate_batch_prep(plan_result)
    if not plan_result.safety.can_generate_plan or not plan_result.meals:
        async def failure_follow_up() -> None:
            reply_markup = None
            if request_payload.get("include_default_after_plan_keyboard", True):
                reply_markup = _after_plan_keyboard(job.chat_id)
            await message.answer(ONE_DAY_PLAN_NO_PLAN_FOLLOW_UP_TEXT, reply_markup=reply_markup)

        return OneDayGenerationDelivery(value_messages=(), failure_follow_up=failure_follow_up)

    validation = validate_plan(plan_result)
    messages = list(format_plan_messages(plan_result, validation))
    if request_payload.get("include_entitlement_status") and len(messages) > 2:
        messages[-1] = f"{messages[-1]}\n\n{await _format_entitlement_status_async(job.chat_id)}"

    async def before_value_messages() -> None:
        if request_payload.get("include_calculation_report"):
            await _send_calculation_report(message, profile)

    plan_reply_markup = None
    if request_payload.get("include_default_after_plan_keyboard", True):
        plan_reply_markup = _after_plan_keyboard(job.chat_id)

    value_messages: list[OneDayGenerationValueMessage] = []
    for meal_index, meal in enumerate(plan_result.meals):
        value_messages.append(
            OneDayGenerationValueMessage(
                value_message_key=_one_day_meal_value_message_key(meal_index, meal),
                send=lambda meal=meal: _send_meal_card(message, meal),
            )
        )

    summary_keys = ("summary:daily_totals", "summary:shopping")
    summary_messages = messages[2:]
    for index, response in enumerate(summary_messages):
        markup = plan_reply_markup if index == len(summary_messages) - 1 else None
        value_key = summary_keys[index] if index < len(summary_keys) else f"summary:{index}"
        value_messages.append(
            OneDayGenerationValueMessage(
                value_message_key=value_key,
                send=lambda response=response, markup=markup: _send_text_chunks(message, response, markup),
            )
        )

    async def after_success() -> None:
        await _remember_recipe_history_items_best_effort_async(
            job.chat_id,
            _recipe_history_items_from_plan(plan_result, "one_day"),
            ration_kind="one_day",
            context="one_day_worker_success",
        )
        if request_payload.get("include_trial_subscription_cta"):
            await _send_trial_subscription_cta(message)
            await _schedule_sales_followup_after_trial_success(
                chat_id=job.chat_id,
                chat_type=request_payload.get("chat_type"),
                source=job.consumption_source,
                include_trial_subscription_cta=True,
                trigger_id=job.job_id,
                trigger_job_id=job.job_id,
            )

    return OneDayGenerationDelivery(
        value_messages=tuple(value_messages),
        before_value_messages=before_value_messages,
        after_success=after_success,
    )


def _generation_seed_from_snapshot(snapshot: OneDayGenerationRequestSnapshot) -> int:
    if snapshot.generation_seed:
        try:
            return int(snapshot.generation_seed)
        except ValueError:
            pass
    digest = hashlib.sha256(
        json.dumps(
            {
                "request_kind": snapshot.request_kind,
                "request_payload": snapshot.request_payload,
                "profile": snapshot.profile,
                "recent_recipe_ids": list(snapshot.recent_recipe_ids),
            },
            sort_keys=True,
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return int(digest[:12], 16)


def _recent_recipe_keys_from_snapshot(snapshot: OneDayGenerationRequestSnapshot) -> tuple[str, ...]:
    raw_keys = snapshot.request_payload.get("recent_recipe_keys", ())
    if not isinstance(raw_keys, Sequence) or isinstance(raw_keys, (str, bytes)):
        return ()
    return tuple(str(key).strip() for key in raw_keys if str(key).strip())


class _TelegramWeeklyPdfJobProcessor:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def prepare_delivery(self, job: WeeklyPdfJob) -> WeeklyPdfDelivery:
        return await _prepare_weekly_pdf_delivery(job, self.bot)


class _WeeklyPdfJobChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.type = "private"


class _WeeklyPdfJobMessage:
    def __init__(self, *, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat = _WeeklyPdfJobChat(chat_id)
        self.message_id = None

    async def answer(self, text: str, reply_markup=None):
        return await safe_telegram_send(
            lambda: self.bot.send_message(chat_id=self.chat.id, text=text, reply_markup=reply_markup),
            operation_name="weekly_pdf_worker_send_message",
        )

    async def answer_document(self, **kwargs):
        return await safe_telegram_send(
            lambda: self.bot.send_document(chat_id=self.chat.id, **kwargs),
            operation_name="weekly_pdf_worker_send_document",
        )


async def _prepare_weekly_pdf_delivery(job: WeeklyPdfJob, bot: Bot) -> WeeklyPdfDelivery:
    snapshot = job.request_snapshot
    if snapshot is None:
        raise RuntimeError("weekly PDF job snapshot is missing")
    profile = _profile_from_dict(snapshot.profile)
    if profile is None:
        raise RuntimeError("weekly PDF job profile snapshot is invalid")

    message = _WeeklyPdfJobMessage(bot=bot, chat_id=job.chat_id)
    recipe_history_entries: list[RecipeHistoryItem] = []

    async def send(on_send_started, on_delivered) -> bool:
        return await _send_week_plan(
            message,
            profile,
            status_text=await _format_entitlement_status_async(job.chat_id),
            recipe_history_entries=recipe_history_entries,
            pdf_slot_acquired=True,
            generation_seed=_weekly_generation_seed_from_snapshot(snapshot),
            recent_avoidance=_weekly_recent_avoidance_from_snapshot(snapshot),
            on_document_send_started=on_send_started,
            on_document_delivered=on_delivered,
        )

    async def after_success() -> None:
        await _remember_recipe_history_items_best_effort_async(
            job.chat_id,
            recipe_history_entries,
            ration_kind="weekly_pdf",
            context="weekly_pdf_worker_success",
        )
        await _cancel_sales_followup_after_access_grant_async(job.chat_id, reason="weekly_pdf_delivered")

    return WeeklyPdfDelivery(send=send, after_success=after_success)


def _weekly_generation_seed_from_snapshot(snapshot: WeeklyPdfRequestSnapshot) -> int:
    if snapshot.generation_seed:
        try:
            return int(snapshot.generation_seed)
        except ValueError:
            pass
    digest = hashlib.sha256(
        json.dumps(
            {
                "request_payload": snapshot.request_payload,
                "profile": snapshot.profile,
                "recent_recipe_ids": list(snapshot.recent_recipe_ids),
            },
            sort_keys=True,
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return int(digest[:12], 16)


def _weekly_recent_avoidance_from_snapshot(snapshot: WeeklyPdfRequestSnapshot) -> _RecentRecipeAvoidance:
    recent_ids = _bounded_recent_strings(snapshot.recent_recipe_ids, RECENT_RECIPE_HISTORY_LIMIT)
    recent_keys = _bounded_recent_strings(_weekly_recent_recipe_keys_from_snapshot(snapshot), RECENT_RECIPE_HISTORY_LIMIT)
    reduced_ids = _bounded_recent_strings(recent_ids, RECENT_RECIPE_REDUCED_LIMIT)
    reduced_keys = _bounded_recent_strings(recent_keys, RECENT_RECIPE_REDUCED_LIMIT)
    return _RecentRecipeAvoidance(
        full_recipe_ids=frozenset(recent_ids),
        full_recipe_keys=frozenset(recent_keys),
        reduced_recipe_ids=frozenset(reduced_ids),
        reduced_recipe_keys=frozenset(reduced_keys),
    )


def _weekly_recent_recipe_keys_from_snapshot(snapshot: WeeklyPdfRequestSnapshot) -> tuple[str, ...]:
    raw_keys = snapshot.request_payload.get("recent_recipe_keys", ())
    if not isinstance(raw_keys, Sequence) or isinstance(raw_keys, (str, bytes)):
        return ()
    return tuple(str(key).strip() for key in raw_keys if str(key).strip())


async def _send_week_plan(
    message: Message,
    profile: UserProfile,
    *,
    status_text: str | None = None,
    recipe_history_entries: list[RecipeHistoryItem] | None = None,
    pdf_slot_acquired: bool = False,
    initial_status_message: Message | None = None,
    generation_seed: int | None = None,
    recent_avoidance: _RecentRecipeAvoidance | None = None,
    on_document_send_started: Callable[[], None] | None = None,
    on_document_delivered: Callable[[], None] | None = None,
) -> bool:
    chat_id = message.chat.id
    if generation_seed is None:
        seed = _weekly_pdf_generation_seed_candidate(chat_id)
        _mark_weekly_pdf_generation_seed_admitted(chat_id)
    else:
        seed = int(generation_seed)
    if initial_status_message is None:
        status_message = await message.answer(
            WEEK_PDF_STATUS_INITIAL_TEXT,
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        status_message = initial_status_message
        await _edit_week_pdf_status(status_message, WEEK_PDF_STATUS_INITIAL_TEXT)
    status_task = asyncio.create_task(_animate_week_pdf_status(message, status_message))
    try:
        if recent_avoidance is None:
            try:
                recent_avoidance = await _load_recent_recipe_avoidance_async(chat_id)
            except ChatStateStorageError:
                logger.exception("Failed to load weekly PDF chat history for chat_id=%s", _mask_chat_id(chat_id))
                await _stop_week_pdf_status(status_task)
                await _edit_week_pdf_status(status_message, CHAT_STATE_READ_ERROR_TEXT)
                return False
        _weekly_pdf_diag(
            "recent_avoidance_loaded",
            chat_id=chat_id,
            full_ids=len(recent_avoidance.full_recipe_ids),
            full_keys=len(recent_avoidance.full_recipe_keys),
            reduced_ids=len(recent_avoidance.reduced_recipe_ids),
            reduced_keys=len(recent_avoidance.reduced_recipe_keys),
        )
        selection_started_at = time.perf_counter()
        _weekly_pdf_diag("selection_start", chat_id=chat_id, seed=seed)
        build_result = await asyncio.to_thread(
            _build_week_plans_with_recent_fallback,
            profile,
            seed,
            recent_avoidance,
        )
        _weekly_pdf_diag(
            "selection_end",
            chat_id=chat_id,
            elapsed_s=time.perf_counter() - selection_started_at,
            phase=build_result.avoidance_phase,
            days=len(build_result.plans),
            meals=sum(len(plan.meals) for plan in build_result.plans),
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
            pdf_data, pdf_filename = await asyncio.to_thread(
                _build_week_pdf_payload,
                plans,
                plan_dates,
                chat_id,
            )
            _validate_week_pdf_payload_size(pdf_data, pdf_filename)
            await _stop_week_pdf_status(status_task)
            await _edit_week_pdf_status(status_message, WEEK_PDF_UPLOAD_TEXT)
            await _send_week_pdf_document(
                message,
                pdf_data,
                pdf_filename,
                status_text=status_text,
                on_document_send_started=on_document_send_started,
                on_document_delivered=on_document_delivered,
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
    on_document_send_started: Callable[[], None] | None = None,
    on_document_delivered: Callable[[], None] | None = None,
) -> None:
    caption = "Готово - ваш рацион на неделю в PDF."
    if status_text:
        caption = f"{caption}\n\n{status_text}"
    _validate_week_pdf_payload_size(pdf_data, pdf_filename)
    validate_telegram_caption(caption, label="weekly PDF caption")
    document = BufferedInputFile(pdf_data, filename=pdf_filename)
    reply_markup = _after_plan_keyboard(message.chat.id)
    upload_started_at = time.perf_counter()
    _weekly_pdf_diag(
        "telegram_upload_start",
        chat_id=message.chat.id,
        bytes=len(pdf_data),
        filename=pdf_filename,
    )
    if on_document_send_started is not None:
        on_document_send_started()
    try:
        await message.answer_document(
            document=document,
            caption=caption,
            reply_markup=reply_markup,
        )
    except Exception as exc:
        _weekly_pdf_diag(
            "telegram_upload_fail",
            chat_id=message.chat.id,
            elapsed_s=time.perf_counter() - upload_started_at,
            error=type(exc).__name__,
        )
        raise
    if on_document_delivered is not None:
        on_document_delivered()
    _weekly_pdf_diag(
        "telegram_upload_end",
        chat_id=message.chat.id,
        elapsed_s=time.perf_counter() - upload_started_at,
    )


def _build_week_pdf_payload(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    chat_id: int | None = None,
) -> tuple[bytes, str]:
    render_started_at = time.perf_counter()
    _weekly_pdf_diag("render_start", chat_id=chat_id, days=len(plans))
    try:
        pdf_path = Path(build_week_plan_pdf(plans, plan_dates))
    except Exception as exc:
        _weekly_pdf_diag(
            "render_fail",
            chat_id=chat_id,
            elapsed_s=time.perf_counter() - render_started_at,
            error=type(exc).__name__,
        )
        raise
    _weekly_pdf_diag(
        "render_end",
        chat_id=chat_id,
        elapsed_s=time.perf_counter() - render_started_at,
        temp_pdf=pdf_path.name,
    )
    read_started_at = time.perf_counter()
    _weekly_pdf_diag("temp_pdf_read_start", chat_id=chat_id, temp_pdf=pdf_path.name)
    try:
        validate_local_pdf_document_path(
            pdf_path,
            label="weekly PDF temp file",
            max_bytes=TELEGRAM_DOCUMENT_MAX_BYTES,
        )
        pdf_data = pdf_path.read_bytes()
        _weekly_pdf_diag(
            "temp_pdf_read_end",
            chat_id=chat_id,
            elapsed_s=time.perf_counter() - read_started_at,
            bytes=len(pdf_data),
        )
        return pdf_data, _week_pdf_download_filename(plan_dates)
    except Exception as exc:
        _weekly_pdf_diag(
            "temp_pdf_read_fail",
            chat_id=chat_id,
            elapsed_s=time.perf_counter() - read_started_at,
            error=type(exc).__name__,
        )
        raise
    finally:
        delete_started_at = time.perf_counter()
        _weekly_pdf_diag("temp_pdf_delete_start", chat_id=chat_id, temp_pdf=pdf_path.name)
        with suppress(OSError):
            pdf_path.unlink()
        _weekly_pdf_diag(
            "temp_pdf_delete_end",
            chat_id=chat_id,
            elapsed_s=time.perf_counter() - delete_started_at,
            exists=pdf_path.exists(),
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


async def _send_week_plan_as_text(
    message: Message,
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    *,
    status_text: str | None = None,
) -> None:
    for day_index, (plan_result, plan_date) in enumerate(zip(plans, plan_dates), start=1):
        await _send_text_chunks(message, _format_week_day_header(day_index, plan_date))
        for meal in plan_result.meals:
            await _send_meal_card(message, meal)
        await _send_text_chunks(message, format_daily_totals(plan_result))
        _remember_recipes(message.chat.id, plan_result)

    shopping_list = format_week_shopping_list(plans)
    if status_text:
        shopping_list = f"{shopping_list}\n\n{status_text}"
    await _send_text_chunks(message, shopping_list, _after_plan_keyboard(message.chat.id))


def _week_pdf_download_filename(plan_dates: Sequence[date]) -> str:
    if not plan_dates:
        return "FoodBalance_рацион_на_неделю.pdf"
    return f"FoodBalance_рацион_на_неделю_{_week_pdf_date_range(plan_dates)}.pdf"

def _week_pdf_date_range(plan_dates: Sequence[date]) -> str:
    first_date = plan_dates[0]
    last_date = plan_dates[-1]
    first_month = PDF_MONTH_NAMES_RU[first_date.month]
    last_month = PDF_MONTH_NAMES_RU[last_date.month]
    if first_date.year == last_date.year and first_date.month == last_date.month:
        return f"{first_date:%d}-{last_date:%d}_{first_month}_{first_date:%Y}"
    if first_date.year == last_date.year:
        return f"{first_date:%d}_{first_month}-{last_date:%d}_{last_month}_{first_date:%Y}"
    return f"{first_date:%d}_{first_month}_{first_date:%Y}-{last_date:%d}_{last_month}_{last_date:%Y}"

def _validate_week_pdf_payload_size(pdf_data: bytes, pdf_filename: str) -> None:
    validate_pdf_document_bytes(pdf_data, pdf_filename, max_bytes=TELEGRAM_DOCUMENT_MAX_BYTES)

def _weekly_phase_feasibility(
    profile: UserProfile,
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
    *,
    phase: str,
    recipe_cache: _RecipePlanCache,
) -> _WeeklyPhaseFeasibility:
    phase_label = _weekly_selection_phase_label(phase)
    _weekly_selection_diag(
        "phase_feasibility_start",
        phase=phase_label,
        raw_phase=phase,
        avoided_ids=len(avoided_recipe_ids),
        avoided_keys=len(avoided_recipe_keys),
    )
    if phase == "no_recent":
        result = _WeeklyPhaseFeasibility(
            skipped=False,
            reason="no_recent_not_gated",
            slot_counts=(),
        )
        _weekly_selection_diag(
            "phase_feasibility_end",
            phase=phase_label,
            raw_phase=phase,
            skipped=result.skipped,
            reason=result.reason,
            slot_counts="",
        )
        return result

    safety = evaluate_safety(profile)
    if not safety.can_generate_plan:
        result = _WeeklyPhaseFeasibility(
            skipped=True,
            reason="safety_cannot_generate",
            slot_counts=(),
        )
        _weekly_selection_diag(
            "phase_feasibility_end",
            phase=phase_label,
            raw_phase=phase,
            skipped=result.skipped,
            reason=result.reason,
            slot_counts="",
        )
        return result

    targets = calculate_targets(profile)
    candidate_foods = filter_foods(built_in_foods(), safety)
    if not candidate_foods:
        result = _WeeklyPhaseFeasibility(
            skipped=True,
            reason="no_safe_foods",
            slot_counts=(),
        )
        _weekly_selection_diag(
            "phase_feasibility_end",
            phase=phase_label,
            raw_phase=phase,
            skipped=result.skipped,
            reason=result.reason,
            slot_counts="",
        )
        return result

    food_by_id = {food.id: food for food in candidate_foods}
    food_cache_key = _food_by_id_cache_key(food_by_id)
    base_recipes = _weekly_phase_feasible_base_recipes(
        food_by_id,
        food_cache_key,
        avoided_recipe_ids,
        avoided_recipe_keys,
        safety.excluded_food_names,
        recipe_cache,
    )
    slots = _meal_energy_slots(profile.meal_count)
    slot_counts_by_name = Counter(slot.slot for slot in slots)
    strict_simple_constraints = None
    if normalize_cooking_time_preference(profile.cooking_time) == CookingTimePreference.SIMPLE:
        strict_simple_constraints = _cooking_effort_constraints(CookingTimePreference.SIMPLE)

    total_energy = targets.targets.get("energy_kcal")
    feasibility_counts: list[_WeeklyPhaseSlotFeasibility] = []
    for slot_name in slot_counts_by_name:
        matching_slots = [slot for slot in slots if slot.slot == slot_name]
        available_counts: list[int] = []
        strict_counts: list[int] = []
        for energy_slot in matching_slots:
            available_count, strict_count = _weekly_phase_slot_candidate_counts(
                base_recipes,
                slot=energy_slot.slot,
                slot_energy_target=total_energy * energy_slot.target_ratio,
                target=targets.targets,
                food_by_id=food_by_id,
                food_cache_key=food_cache_key,
                avoided_recipe_keys=avoided_recipe_keys,
                strict_simple_constraints=strict_simple_constraints,
                recipe_cache=recipe_cache,
            )
            available_counts.append(available_count)
            if strict_simple_constraints is not None:
                strict_counts.append(strict_count)

        weekly_required = slot_counts_by_name[slot_name] * WEEK_PLAN_DAYS
        if strict_simple_constraints is not None:
            threshold = (
                weekly_required
                * WEEKLY_RECENT_FEASIBILITY_POOL_MULTIPLIER
            )
            strict_simple_count: int | None = min(strict_counts) if strict_counts else 0
        else:
            threshold = weekly_required
            strict_simple_count = None

        feasibility_counts.append(
            _WeeklyPhaseSlotFeasibility(
                slot=slot_name,
                weekly_required=weekly_required,
                available_count=min(available_counts) if available_counts else 0,
                strict_simple_count=strict_simple_count,
                threshold=threshold,
            )
        )

    skipped_count = next(
        (
            count
            for count in feasibility_counts
            if _weekly_phase_slot_gating_count(count) < count.threshold
        ),
        None,
    )
    if skipped_count is None:
        result = _WeeklyPhaseFeasibility(
            skipped=False,
            reason="feasible",
            slot_counts=tuple(feasibility_counts),
        )
    else:
        result = _WeeklyPhaseFeasibility(
            skipped=True,
            reason=(
                "slot_pool_below_threshold:"
                f"{skipped_count.slot}:"
                f"{_weekly_phase_slot_gating_count(skipped_count)}"
                f"<{skipped_count.threshold}"
            ),
            slot_counts=tuple(feasibility_counts),
        )

    _weekly_selection_diag(
        "phase_feasibility_end",
        phase=phase_label,
        raw_phase=phase,
        skipped=result.skipped,
        reason=result.reason,
        slot_counts=_weekly_phase_feasibility_counts_summary(result.slot_counts),
    )
    return result

def _weekly_phase_feasible_base_recipes(
    food_by_id: dict[str, Food],
    food_cache_key: str,
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
    excluded_food_names: frozenset[str],
    recipe_cache: _RecipePlanCache,
) -> tuple[RecipeTemplate, ...]:
    recipes: list[RecipeTemplate] = []
    for recipe in built_in_recipes():
        if "curated" not in recipe.tags:
            continue
        if recipe.id in avoided_recipe_ids:
            continue
        if _recipe_memory_key_cached(recipe, recipe_cache=recipe_cache) in avoided_recipe_keys:
            continue
        if _recipe_title_uses_excluded_food(recipe, excluded_food_names):
            continue
        if (
            _resolve_recipe_ingredients(
                recipe,
                food_by_id,
                recipe_cache=recipe_cache,
                food_cache_key=food_cache_key,
            )
            is None
        ):
            continue
        recipes.append(recipe)
    return tuple(recipes)

def _weekly_phase_slot_candidate_counts(
    recipes: tuple[RecipeTemplate, ...],
    *,
    slot: str,
    slot_energy_target: float,
    target: NutrientVector,
    food_by_id: dict[str, Food],
    food_cache_key: str,
    avoided_recipe_keys: set[str],
    strict_simple_constraints: CookingEffortConstraints | None,
    recipe_cache: _RecipePlanCache,
) -> tuple[int, int]:
    available_count = 0
    strict_simple_count = 0
    for recipe in recipes:
        if _recipe_memory_key_cached(recipe, slot, recipe_cache=recipe_cache) in avoided_recipe_keys:
            continue
        eligibility = _recipe_slot_eligibility_cached(
            recipe,
            slot,
            food_by_id,
            slot_energy_target,
            target,
            recipe_cache=recipe_cache,
            food_cache_key=food_cache_key,
        )
        if not eligibility.eligible:
            continue
        available_count += 1
        if strict_simple_constraints is not None and _recipe_matches_cooking_effort_cached(
            recipe,
            strict_simple_constraints,
            recipe_cache,
        ):
            strict_simple_count += 1
    return available_count, strict_simple_count

def _weekly_phase_slot_gating_count(count: _WeeklyPhaseSlotFeasibility) -> int:
    if count.strict_simple_count is not None:
        return count.strict_simple_count
    return count.available_count

def _weekly_phase_feasibility_counts_summary(
    counts: Sequence[_WeeklyPhaseSlotFeasibility],
) -> str:
    return ";".join(
        (
            f"{count.slot}:required={count.weekly_required},"
            f"available={count.available_count},"
            f"strict_simple={count.strict_simple_count},"
            f"threshold={count.threshold}"
        )
        for count in counts
    )

def _recent_avoidance_is_empty(recent_avoidance: _RecentRecipeAvoidance) -> bool:
    return not (
        recent_avoidance.full_recipe_ids
        or recent_avoidance.full_recipe_keys
        or recent_avoidance.reduced_recipe_ids
        or recent_avoidance.reduced_recipe_keys
    )


def _weekly_no_recent_repeat_fallback_reason(
    profile: UserProfile,
    *,
    recipe_cache: _RecipePlanCache,
) -> str | None:
    feasibility = _weekly_phase_feasibility(
        profile,
        set(),
        set(),
        phase="full_recent",
        recipe_cache=recipe_cache,
    )
    if feasibility.reason in {"safety_cannot_generate", "no_safe_foods"}:
        return feasibility.reason

    for count in feasibility.slot_counts:
        threshold = count.weekly_required * WEEKLY_REPEATS_FALLBACK_POOL_MULTIPLIER
        available = _weekly_phase_slot_gating_count(count)
        if available < threshold:
            return f"repeat_fallback_slot_pool_below_threshold:{count.slot}:{available}<{threshold}"
    return None


def _build_week_plans_with_repeats_fallback(
    profile: UserProfile,
    seed: int,
    *,
    recipe_cache: _RecipePlanCache,
    failure_reason: str | None = None,
) -> _WeekPlanBuildResult:
    safety = evaluate_safety(profile)
    if not safety.can_generate_plan:
        return _WeekPlanBuildResult(
            plans=(),
            avoidance_phase="failed",
            failure_reason="safety_cannot_generate",
        )

    if not filter_foods(built_in_foods(), safety):
        return _WeekPlanBuildResult(
            plans=(),
            avoidance_phase="failed",
            repeat_fallback_used=True,
            failure_reason="no_safe_foods",
        )

    day_pool = _build_weekly_repeat_fallback_day_pool(
        profile,
        seed,
        recipe_cache=recipe_cache,
    )
    if not day_pool:
        return _WeekPlanBuildResult(
            plans=(),
            avoidance_phase="failed",
            repeat_fallback_used=True,
            failure_reason="repeats_fallback_no_valid_day_pool",
        )

    scheduled_plans = _schedule_weekly_repeat_fallback_pool(day_pool, profile)
    repeat_count = _weekly_repeated_recipe_count(scheduled_plans)
    if not _week_plans_are_complete(scheduled_plans, profile):
        return _WeekPlanBuildResult(
            plans=(),
            avoidance_phase="failed",
            repeat_fallback_used=True,
            failure_reason="repeats_fallback_incomplete_week",
        )
    return _WeekPlanBuildResult(
        plans=scheduled_plans,
        avoidance_phase="repeats_fallback",
        repeat_fallback_used=True,
        repeat_recipe_count=repeat_count,
        repeat_note=WEEKLY_REPEATS_FALLBACK_NOTE if repeat_count else None,
    )


def _build_weekly_repeat_fallback_day_pool(
    profile: UserProfile,
    seed: int,
    *,
    recipe_cache: _RecipePlanCache,
) -> tuple[MealPlan, ...]:
    safety = evaluate_safety(profile)
    if "dairy" in safety.excluded_food_names:
        builders = (_build_weekly_repeat_fallback_day_pool_from_slots,)
    else:
        builders = (
            _build_weekly_repeat_fallback_day_pool_from_builder,
            _build_weekly_repeat_fallback_day_pool_from_slots,
        )

    for build_pool in builders:
        day_pool = build_pool(profile, seed, recipe_cache=recipe_cache)
        if day_pool:
            return day_pool
    return ()


def _build_weekly_repeat_fallback_day_pool_from_builder(
    profile: UserProfile,
    seed: int,
    *,
    recipe_cache: _RecipePlanCache,
) -> tuple[MealPlan, ...]:
    plans: list[MealPlan] = []
    seen_signatures: set[tuple[str, ...]] = set()
    generated_by_offset: dict[int, MealPlan] = {}

    for offset in range(WEEKLY_REPEATS_FALLBACK_BUILDER_ATTEMPTS):
        if len(plans) >= WEEKLY_REPEATS_FALLBACK_DAY_POOL_SIZE:
            break

        plan = generated_by_offset.get(offset)
        if plan is None:
            plan = build_one_day_plan(
                profile,
                variety_seed=seed + offset,
                recipe_source="curated_only",
                recipe_cache=recipe_cache,
            )
            generated_by_offset[offset] = plan

        if not _week_day_plan_is_complete(plan, profile):
            continue

        signature = _plan_recipe_ids(plan)
        if not signature or signature in seen_signatures:
            continue

        seen_signatures.add(signature)
        plans.append(plan)

    return tuple(plans)


def _build_weekly_repeat_fallback_day_pool_from_slots(
    profile: UserProfile,
    seed: int,
    *,
    recipe_cache: _RecipePlanCache,
) -> tuple[MealPlan, ...]:
    context, _context_failure_reason = _weekly_repeat_fallback_context(profile, recipe_cache)
    if context is None:
        return ()

    target = context.targets.targets
    total_energy = target.get("energy_kcal")
    slots = _meal_energy_slots(profile.meal_count)
    slot_options = tuple(
        _weekly_repeat_fallback_fast_slot_options(
            context.recipes,
            energy_slot.slot,
            meal_index,
            context,
            target,
            total_energy * energy_slot.target_ratio,
            Counter(),
            frozenset(),
        )
        for meal_index, energy_slot in enumerate(slots)
    )
    if any(not options for options in slot_options):
        return ()

    plans: list[MealPlan] = []
    seen_signatures: set[tuple[str, ...]] = set()

    ranked_combinations = _weekly_repeat_fallback_ranked_combinations(
        slot_options,
        slots,
        target,
        Counter(),
        frozenset(),
    )
    for offset, recipes_for_day in enumerate(
        ranked_combinations[:WEEKLY_REPEATS_FALLBACK_FAST_COMBO_LIMIT]
    ):
        if len(plans) >= WEEKLY_REPEATS_FALLBACK_DAY_POOL_SIZE:
            break

        signature = tuple(recipe.id for recipe in recipes_for_day)
        if signature in seen_signatures:
            continue

        meals = _weekly_repeat_fallback_build_combo_meals(
            recipes_for_day,
            slots,
            context,
            target,
            total_energy,
            seed + offset,
        )
        if len(meals) != len(slots):
            continue
        if not _passes_hard_nutrition_gates(
            meals,
            target,
            enforce_sodium=bool(context.safety.excluded_food_names),
        ):
            continue

        plan = MealPlan(meals=tuple(meals), targets=context.targets, safety=context.safety)
        if not _week_day_plan_is_complete(plan, profile):
            continue
        seen_signatures.add(signature)
        plans.append(plan)

    return tuple(plans)


def _weekly_repeat_fallback_context(
    profile: UserProfile,
    recipe_cache: _RecipePlanCache,
) -> tuple[_WeeklyRepeatFallbackContext | None, str | None]:
    safety = evaluate_safety(profile)
    targets = calculate_targets(profile)
    if not safety.can_generate_plan:
        return None, "safety_cannot_generate"

    foods = tuple(filter_foods(built_in_foods(), safety))
    if not foods:
        return None, "no_safe_foods"

    food_by_id = {food.id: food for food in foods}
    food_cache_key = _food_by_id_cache_key(food_by_id)
    recipes = _weekly_phase_feasible_base_recipes(
        food_by_id,
        food_cache_key,
        set(),
        set(),
        safety.excluded_food_names,
        recipe_cache,
    )
    if not recipes:
        return None, "no_safe_recipes"

    return (
        _WeeklyRepeatFallbackContext(
            safety=safety,
            targets=targets,
            foods=foods,
            food_by_id=food_by_id,
            food_cache_key=food_cache_key,
            recipes=recipes,
            recipe_cache=recipe_cache,
        ),
        None,
    )


def _weekly_repeat_fallback_fast_slot_options(
    recipes: tuple[RecipeTemplate, ...],
    slot: str,
    meal_index: int,
    context: _WeeklyRepeatFallbackContext,
    target: NutrientVector,
    slot_energy_target: float,
    week_recipe_counts: Counter[str],
    previous_day_recipe_ids: frozenset[str],
) -> tuple[_WeeklyRepeatFallbackFastOption, ...]:
    del meal_index
    options: list[tuple[tuple[float, float, float, float, str], _WeeklyRepeatFallbackFastOption]] = []
    empty_used_grams: defaultdict[str, float] = defaultdict(float)
    empty_total = NutrientVector()
    for recipe in recipes:
        eligibility = _recipe_slot_eligibility_cached(
            recipe,
            slot,
            context.food_by_id,
            slot_energy_target,
            target,
            recipe_cache=context.recipe_cache,
            food_cache_key=context.food_cache_key,
        )
        if not eligibility.eligible:
            continue
        resolved = _resolve_recipe_ingredients(
            recipe,
            context.food_by_id,
            recipe_cache=context.recipe_cache,
            food_cache_key=context.food_cache_key,
        )
        if resolved is None:
            continue
        base_energy = NutrientVector.sum(
            food.portion(grams).nutrients for food, grams in resolved
        ).get("energy_kcal")
        portions = _scaled_recipe_portions(
            resolved,
            _recipe_scale(slot_energy_target, base_energy),
            empty_used_grams,
            empty_total,
            target,
            meal_slot=slot,
        )
        if not portions:
            continue
        nutrients = NutrientVector.sum(portion.nutrients for portion in portions)
        repeat_weight = 2.0 if slot == "main" else 1.0
        sort_key = (
            -float(recipe.id in previous_day_recipe_ids),
            -(week_recipe_counts[recipe.id] * repeat_weight),
            nutrients.get("protein_g"),
            -abs(nutrients.get("energy_kcal") - slot_energy_target),
            recipe.id,
        )
        options.append(
            (
                sort_key,
                _WeeklyRepeatFallbackFastOption(
                    recipe=recipe,
                    estimated_protein_g=nutrients.get("protein_g"),
                    estimated_energy_kcal=nutrients.get("energy_kcal"),
                ),
            )
        )

    return tuple(
        option
        for _, option in sorted(options, key=lambda item: item[0], reverse=True)[
            :WEEKLY_REPEATS_FALLBACK_FAST_SLOT_OPTIONS
        ]
    )


def _weekly_repeat_fallback_ranked_combinations(
    slot_options: tuple[tuple[_WeeklyRepeatFallbackFastOption, ...], ...],
    slots,
    target: NutrientVector,
    week_recipe_counts: Counter[str],
    previous_day_recipe_ids: frozenset[str],
) -> tuple[tuple[RecipeTemplate, ...], ...]:
    ranked: list[tuple[tuple[float, float, float, float, float, tuple[str, ...]], tuple[RecipeTemplate, ...]]] = []
    for combination in itertools.product(*slot_options):
        recipe_ids = tuple(option.recipe.id for option in combination)
        if len(set(recipe_ids)) != len(recipe_ids):
            continue
        adjacent_count = len(set(recipe_ids) & previous_day_recipe_ids)
        repeat_pressure = sum(week_recipe_counts[recipe_id] for recipe_id in recipe_ids)
        main_repeat_pressure = sum(
            week_recipe_counts[recipe_ids[index]]
            for index, energy_slot in enumerate(slots)
            if energy_slot.slot == "main"
        )
        estimated_protein = sum(option.estimated_protein_g for option in combination)
        estimated_energy = sum(option.estimated_energy_kcal for option in combination)
        score = (
            -float(adjacent_count),
            -abs(estimated_protein - target.get("protein_g")),
            -abs(estimated_energy - target.get("energy_kcal")),
            -float(main_repeat_pressure),
            -float(repeat_pressure),
            recipe_ids,
        )
        ranked.append((score, tuple(option.recipe for option in combination)))
    return tuple(
        recipes
        for _, recipes in sorted(ranked, key=lambda item: item[0], reverse=True)
    )


def _weekly_repeat_fallback_build_combo_meals(
    recipes_for_day: tuple[RecipeTemplate, ...],
    slots,
    context: _WeeklyRepeatFallbackContext,
    target: NutrientVector,
    total_energy: float,
    seed: int,
) -> list[Meal]:
    meals: list[Meal] = []
    used_grams: defaultdict[str, float] = defaultdict(float)
    current_total = NutrientVector()
    for meal_index, (recipe, energy_slot) in enumerate(zip(recipes_for_day, slots)):
        resolved = _resolve_recipe_ingredients(
            recipe,
            context.food_by_id,
            recipe_cache=context.recipe_cache,
            food_cache_key=context.food_cache_key,
        )
        if resolved is None:
            return []
        base_energy = NutrientVector.sum(
            food.portion(grams).nutrients for food, grams in resolved
        ).get("energy_kcal")
        portions = _scaled_recipe_portions(
            resolved,
            _recipe_scale(total_energy * energy_slot.target_ratio, base_energy),
            used_grams,
            current_total,
            target,
            meal_slot=energy_slot.slot,
        )
        if not portions:
            return []
        for portion in portions:
            used_grams[portion.food.id] += portion.grams
        meal = Meal(
            name=f"{_meal_emoji(energy_slot.slot, meal_index)} {_meal_name(energy_slot.slot, meal_index)}: {recipe.title}",
            portions=tuple(portions),
            recipe=recipe.instructions,
            image_url=recipe.image_url,
            image_attribution=recipe.image_attribution,
            source_url=recipe.source_url,
            recipe_id=recipe.id,
            recipe_key=_recipe_memory_key_cached(
                recipe,
                energy_slot.slot,
                recipe_cache=context.recipe_cache,
            ),
        )
        meals.append(meal)
        current_total = current_total.plus(meal.nutrients)

    if current_total.get("protein_g") + 0.01 < target.get("protein_g") * 0.85:
        return []
    return _finalize_recipe_meals(meals, list(context.foods), target, seed)


def _plan_recipe_ids(plan: MealPlan) -> tuple[str, ...]:
    return tuple(meal.recipe_id for meal in plan.meals if meal.recipe_id)


def _weekly_repeated_recipe_count(plans: Sequence[MealPlan]) -> int:
    counts: Counter[str] = Counter(
        recipe_id
        for plan in plans
        for recipe_id in _plan_recipe_ids(plan)
    )
    return sum(count - 1 for count in counts.values() if count > 1)


def _schedule_weekly_repeat_fallback_pool(
    day_pool: tuple[MealPlan, ...],
    profile: UserProfile,
) -> tuple[MealPlan, ...]:
    if not day_pool:
        return ()

    scheduled: list[MealPlan] = []
    recipe_counts: Counter[str] = Counter()
    previous_day_recipe_ids: frozenset[str] = frozenset()

    for day_index in range(WEEK_PLAN_DAYS):
        candidates = list(day_pool)
        non_adjacent_candidates = [
            plan
            for plan in candidates
            if not (set(_plan_recipe_ids(plan)) & previous_day_recipe_ids)
        ]
        if non_adjacent_candidates:
            candidates = non_adjacent_candidates
        selected = max(
            enumerate(candidates),
            key=lambda item: _weekly_repeat_fallback_pool_score(
                item[1],
                recipe_counts,
                previous_day_recipe_ids,
                profile,
                pool_index=item[0],
            ),
        )[1]
        scheduled.append(selected)
        previous_day_recipe_ids = frozenset(_plan_recipe_ids(selected))
        recipe_counts.update(previous_day_recipe_ids)
    return tuple(scheduled)


def _weekly_repeat_fallback_pool_score(
    plan: MealPlan,
    recipe_counts: Counter[str],
    previous_day_recipe_ids: frozenset[str],
    profile: UserProfile,
    *,
    pool_index: int,
) -> tuple[float, float, float, float, float, float, int]:
    recipe_ids = _plan_recipe_ids(plan)
    adjacent_count = len(set(recipe_ids) & previous_day_recipe_ids)
    repeated_recipe_additions = sum(1 for recipe_id in recipe_ids if recipe_counts[recipe_id] > 0)
    repeat_pressure = sum(recipe_counts[recipe_id] for recipe_id in recipe_ids)
    max_after = max((recipe_counts[recipe_id] + 1 for recipe_id in recipe_ids), default=0)
    main_repeat_pressure = sum(
        recipe_counts[meal.recipe_id]
        for meal in plan.meals
        if meal.recipe_id and _meal_slot(meal) == "main"
    )
    new_recipe_count = sum(1 for recipe_id in recipe_ids if recipe_counts[recipe_id] == 0)
    protein_gap = _relative_gap(plan.totals, plan.targets.targets, "protein_g")
    return (
        -float(repeated_recipe_additions),
        -float(adjacent_count),
        -float(repeat_pressure),
        -float(main_repeat_pressure),
        -float(max_after),
        float(new_recipe_count),
        -protein_gap,
        -pool_index,
    )


def _load_recent_recipe_avoidance(
    chat_id: int,
    *,
    now: datetime | None = None,
) -> _RecentRecipeAvoidance:
    del now
    _load_chat_history(chat_id)
    return _recent_recipe_avoidance_from_legacy_chat_history(chat_id)

def _build_week_plans_with_recent_fallback(
    profile: UserProfile,
    seed: int,
    recent_avoidance: _RecentRecipeAvoidance,
) -> _WeekPlanBuildResult:
    guard = _WeeklySelectionGuard()
    recipe_cache = _RecipePlanCache()
    timed_out = False
    repeat_fallback_reason: str | None = None
    if _recent_avoidance_is_empty(recent_avoidance):
        repeat_fallback_reason = _weekly_no_recent_repeat_fallback_reason(
            profile,
            recipe_cache=recipe_cache,
        )
        if repeat_fallback_reason in {"safety_cannot_generate", "no_safe_foods"}:
            return _WeekPlanBuildResult(
                plans=(),
                avoidance_phase="failed",
                failure_reason=repeat_fallback_reason,
            )
        if repeat_fallback_reason is not None:
            _weekly_selection_diag(
                "repeats_fallback_start",
                phase="repeats_fallback",
                seed=seed,
                reason=repeat_fallback_reason,
            )
            return _build_week_plans_with_repeats_fallback(
                profile,
                seed,
                recipe_cache=recipe_cache,
                failure_reason=repeat_fallback_reason,
            )

    for phase, avoided_recipe_ids, avoided_recipe_keys in _weekly_recent_avoidance_phases(
        recent_avoidance
    ):
        guard.begin_phase(phase)
        _weekly_selection_diag(
            "phase_start",
            phase=_weekly_selection_phase_label(phase),
            raw_phase=phase,
            seed=seed,
            avoided_ids=len(avoided_recipe_ids),
            avoided_keys=len(avoided_recipe_keys),
        )
        avoided_recipe_id_set = set(avoided_recipe_ids)
        avoided_recipe_key_set = set(avoided_recipe_keys)
        feasibility = _weekly_phase_feasibility(
            profile,
            avoided_recipe_id_set,
            avoided_recipe_key_set,
            phase=phase,
            recipe_cache=recipe_cache,
        )
        if feasibility.skipped:
            _weekly_selection_diag(
                "phase_end",
                phase=_weekly_selection_phase_label(phase),
                raw_phase=phase,
                complete=False,
                days=0,
                meals=0,
                skipped=True,
                reason=feasibility.reason,
                **_recipe_cache_diag_counts(recipe_cache),
            )
            continue
        try:
            plans = _build_week_plans(
                profile,
                seed,
                avoided_recipe_id_set,
                avoided_recipe_key_set,
                selection_phase=phase,
                selection_guard=guard,
                recipe_cache=recipe_cache,
            )
        except _WeeklySelectionTimeout as exc:
            timed_out = True
            _weekly_selection_diag(
                "timeout",
                always=True,
                scope=exc.scope,
                phase=_weekly_selection_phase_label(exc.phase),
                raw_phase=exc.phase,
                elapsed_s=f"{exc.elapsed_s:.3f}",
                timeout_s=f"{exc.timeout_s:.3f}",
                day_index=exc.day_index,
                candidate_index=exc.candidate_index,
                stage=exc.stage,
                **_recipe_cache_diag_counts(recipe_cache),
            )
            if exc.scope == "total":
                return _WeekPlanBuildResult(plans=(), avoidance_phase="timeout")
            continue
        _weekly_selection_diag(
            "phase_end",
            phase=_weekly_selection_phase_label(phase),
            raw_phase=phase,
            complete=_week_plans_are_complete(plans, profile),
            days=len(plans),
            meals=sum(len(plan.meals) for plan in plans),
            **_recipe_cache_diag_counts(recipe_cache),
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

    total_timeout_s = float(WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS)
    if timed_out or (
        total_timeout_s > 0 and time.perf_counter() - guard.total_started_at > total_timeout_s
    ):
        if _recent_avoidance_is_empty(recent_avoidance) and not (
            total_timeout_s > 0 and time.perf_counter() - guard.total_started_at > total_timeout_s
        ):
            return _build_week_plans_with_repeats_fallback(
                profile,
                seed,
                recipe_cache=recipe_cache,
                failure_reason="strict_weekly_selection_timeout",
            )
        return _WeekPlanBuildResult(plans=(), avoidance_phase="timeout")
    if _recent_avoidance_is_empty(recent_avoidance):
        return _build_week_plans_with_repeats_fallback(
            profile,
            seed,
            recipe_cache=recipe_cache,
            failure_reason=repeat_fallback_reason or "strict_weekly_selection_failed",
        )
    return _WeekPlanBuildResult(plans=(), avoidance_phase="failed", failure_reason="strict_weekly_selection_failed")

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

def _week_plans_are_complete(plans: Sequence[MealPlan], profile: UserProfile) -> bool:
    return len(plans) == WEEK_PLAN_DAYS and all(_week_day_plan_is_complete(plan, profile) for plan in plans)

def _week_day_plan_is_complete(plan: MealPlan, profile: UserProfile) -> bool:
    return plan.safety.can_generate_plan and len(plan.meals) == _expected_meal_count(profile)


def _expected_meal_count(profile: UserProfile) -> int:
    return min(5, max(3, profile.meal_count))


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

def _macro_balance_gap(plan: MealPlan) -> float:
    total = plan.totals
    target = plan.targets.targets
    return (
        _relative_gap(total, target, "protein_g")
        + _relative_gap(total, target, "fat_g")
        + _relative_gap(total, target, "carbohydrate_g")
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


def _relative_gap(total: NutrientVector, target: NutrientVector, nutrient: str) -> float:
    target_value = target.get(nutrient)
    if target_value <= 0:
        return 0.0
    return abs(total.get(nutrient) - target_value) / target_value


def _weekly_day_selection_score(
    plan: MealPlan,
    week_food_ids: set[str],
    candidate_index: int,
    *,
    week_recipe_ids_for_diversity: set[str] | None = None,
    candidate_recipe_counts: Counter[str] | None = None,
    recipe_trait_lookup: _RecipeTraitLookupSource | None = None,
) -> tuple[float, float, float, int]:
    in_calorie_band, calorie_gap = _calorie_fit(plan)
    macro_gap = _macro_balance_gap(plan)
    diversity_penalty = _weekly_completed_day_diversity_penalty(
        plan,
        week_recipe_ids_for_diversity or set(),
        recipe_trait_lookup=recipe_trait_lookup,
    )
    candidate_pool_penalty = _completed_candidate_pool_recipe_penalty(plan, candidate_recipe_counts or Counter())
    return (
        1.0 if in_calorie_band else 0.0,
        -(calorie_gap + macro_gap * 0.04 + diversity_penalty + candidate_pool_penalty),
        _ingredient_reuse_score(plan, week_food_ids),
        -candidate_index,
    )

def _candidate_recipe_counts(plans: Sequence[MealPlan]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for plan in plans:
        counts.update(meal.recipe_id for meal in plan.meals if meal.recipe_id)
    return counts

def _completed_candidate_pool_recipe_penalty(plan: MealPlan, candidate_recipe_counts: Counter[str]) -> float:
    if not candidate_recipe_counts:
        return 0.0
    penalty = 0.0
    for meal in plan.meals:
        if not meal.recipe_id:
            continue
        penalty += max(0, candidate_recipe_counts[meal.recipe_id] - 1) * WEEKLY_CANDIDATE_POOL_RECIPE_REPEAT_PENALTY
    return penalty

def _weekly_completed_day_diversity_penalty(
    plan: MealPlan,
    week_recipe_ids: set[str],
    *,
    recipe_trait_lookup: _RecipeTraitLookupSource | None = None,
) -> float:
    if not plan.meals or not week_recipe_ids:
        return 0.0

    traits_by_id = recipe_trait_lookup or _recipe_traits_by_id()
    week_trait_counts = _week_trait_counts(week_recipe_ids, traits_by_id)
    penalty = 0.0
    for meal in plan.meals:
        recipe_id = meal.recipe_id
        if not recipe_id:
            continue
        if recipe_id in week_recipe_ids:
            penalty += WEEKLY_EXACT_RECIPE_REPEAT_PENALTY
        traits = _recipe_traits_for_id(recipe_id, traits_by_id)
        if traits is None:
            continue
        for trait_name, weight in WEEKLY_TRAIT_REPEAT_WEIGHTS.items():
            value = getattr(traits, trait_name)
            if not value:
                continue
            repeated = min(week_trait_counts[(trait_name, value)], WEEKLY_TRAIT_REPEAT_CAP)
            penalty += repeated * weight
    return penalty

def _week_trait_counts(
    recipe_ids: set[str],
    traits_by_id: _RecipeTraitLookupSource,
) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for recipe_id in recipe_ids:
        traits = _recipe_traits_for_id(recipe_id, traits_by_id)
        if traits is None:
            continue
        for trait_name in WEEKLY_TRAIT_REPEAT_WEIGHTS:
            value = getattr(traits, trait_name)
            if value:
                counts[(trait_name, value)] += 1
    return counts

def _recipe_traits_for_id(
    recipe_id: str,
    traits_by_id: _RecipeTraitLookupSource,
) -> RecipeTraits | None:
    return traits_by_id.get(recipe_id)

def _recipe_traits_by_id() -> dict[str, RecipeTraits]:
    return {recipe.id: infer_recipe_traits(recipe) for recipe in built_in_recipes()}

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

def _remember_recipe_history_items(
    chat_id: int,
    entries: Sequence[RecipeHistoryItem],
) -> None:
    if not entries:
        return
    id_history = [
        *RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, []),
        *(entry.recipe_id for entry in entries if entry.recipe_id),
    ][-RECENT_RECIPE_LIMIT:]
    key_history = [
        *RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, []),
        *(entry.recipe_key for entry in entries if entry.recipe_key),
    ][-RECENT_RECIPE_LIMIT:]
    _save_chat_history(chat_id, recipe_ids=id_history, recipe_keys=key_history)
    RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = id_history
    RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = key_history


def _remember_recipe_history_items_best_effort(
    chat_id: int,
    entries: Sequence[RecipeHistoryItem],
    *,
    ration_kind: RationKind,
    context: str,
) -> None:
    try:
        _remember_recipe_history_items(chat_id, entries)
    except ChatStateStorageError:
        logger.exception(
            "Failed to save recipe history in delivery context chat_id=%s ration_kind=%s context=%s entries=%d",
            _mask_chat_id(chat_id),
            ration_kind,
            context,
            len(entries),
        )


def _history_generation_id(consumption: AttemptConsumption) -> int | None:
    del consumption
    return None

def _build_week_plans(
    profile: UserProfile,
    seed: int,
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
    *,
    recipe_trait_lookup: _RecipeTraitLookupSource | None = None,
    selection_phase: str = "unknown",
    selection_guard: _WeeklySelectionGuard | None = None,
    recipe_cache: _RecipePlanCache | None = None,
) -> tuple[MealPlan, ...]:
    plans: list[MealPlan] = []
    week_recipe_ids = set(avoided_recipe_ids)
    week_recipe_keys = set(avoided_recipe_keys)
    selected_week_recipe_ids: set[str] = set()
    carryovers: dict[str, _BatchCarryover] = {}
    if recipe_cache is None:
        recipe_cache = _RecipePlanCache()
    if recipe_trait_lookup is None:
        recipe_trait_lookup = _WeeklyRecipeTraitLookup.from_recipes(curated_recipes())
    for day_index in range(WEEK_PLAN_DAYS):
        if selection_guard is not None:
            selection_guard.check(stage="before_day", day_index=day_index)
        week_food_ids = _week_food_ids(plans)
        day_seed = seed + day_index * WEEK_PLAN_CANDIDATE_COUNT
        day_started_at = time.perf_counter()
        _weekly_selection_diag(
            "day_start",
            phase=_weekly_selection_phase_label(selection_phase),
            raw_phase=selection_phase,
            day_index=day_index,
            seed=day_seed,
            avoided_ids=len(week_recipe_ids),
            avoided_keys=len(week_recipe_keys),
        )
        plan, carryovers = _select_week_day_plan(
            profile,
            day_seed,
            week_recipe_ids,
            week_recipe_keys,
            week_food_ids,
            carryovers,
            has_future_week_days=day_index < WEEK_PLAN_DAYS - 1,
            week_recipe_ids_for_diversity=selected_week_recipe_ids,
            recipe_cache=recipe_cache,
            recipe_trait_lookup=recipe_trait_lookup,
            selection_phase=selection_phase,
            day_index=day_index,
            selection_guard=selection_guard,
        )
        _weekly_selection_diag(
            "day_end",
            phase=_weekly_selection_phase_label(selection_phase),
            raw_phase=selection_phase,
            day_index=day_index,
            elapsed_s=f"{time.perf_counter() - day_started_at:.3f}",
            complete=_week_day_plan_is_complete(plan, profile),
            meals=len(plan.meals),
        )
        if not _week_day_plan_is_complete(plan, profile):
            return ()
        plans.append(plan)
        selected_ids = {meal.recipe_id for meal in plan.meals if meal.recipe_id}
        week_recipe_ids.update(selected_ids)
        selected_week_recipe_ids.update(selected_ids)
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
    week_recipe_ids_for_diversity: set[str] | None = None,
    recipe_cache: _RecipePlanCache | None = None,
    recipe_trait_lookup: _RecipeTraitLookupSource | None = None,
    selection_phase: str = "unknown",
    day_index: int | None = None,
    selection_guard: _WeeklySelectionGuard | None = None,
) -> tuple[MealPlan, dict[str, "_BatchCarryover"]]:
    candidate_options: list[tuple[MealPlan, dict[str, _BatchCarryover], int]] = []
    rejected_plan: MealPlan | None = None

    def add_selectable_candidates(candidate_indexes: range) -> None:
        nonlocal rejected_plan
        for candidate_index in candidate_indexes:
            if selection_guard is not None:
                selection_guard.check(
                    stage="before_candidate",
                    day_index=day_index,
                    candidate_index=candidate_index,
                )
            candidate_seed = seed + candidate_index
            candidate_phase = (
                "rescue"
                if candidate_index >= WEEK_PLAN_CANDIDATE_COUNT
                else _weekly_selection_phase_label(selection_phase)
            )
            candidate_started_at = time.perf_counter()
            _weekly_selection_diag(
                "candidate_start",
                phase=candidate_phase,
                recent_phase=_weekly_selection_phase_label(selection_phase),
                raw_phase=selection_phase,
                day_index=day_index,
                candidate_index=candidate_index,
                seed=candidate_seed,
                avoided_ids=len(avoided_recipe_ids),
                avoided_keys=len(avoided_recipe_keys),
            )
            with recipe_plan_diagnostic_context(
                phase=candidate_phase,
                recent_phase=_weekly_selection_phase_label(selection_phase),
                raw_phase=selection_phase,
                day_index=day_index,
                candidate_index=candidate_index,
                seed=candidate_seed,
            ):
                candidate_selection_guard = (
                    _WeeklySelectionScopedGuard(selection_guard, day_index, candidate_index)
                    if selection_guard is not None
                    else None
                )
                plan = build_one_day_plan(
                    profile,
                    variety_seed=candidate_seed,
                    avoided_recipe_ids=avoided_recipe_ids,
                    avoided_recipe_keys=avoided_recipe_keys,
                    recipe_source="curated_only",
                    allow_avoided_recipe_relaxation=False,
                    recipe_cache=recipe_cache,
                    selection_guard=candidate_selection_guard,
                )
            candidate_carryovers = _copy_carryovers(carryovers)
            plan = _apply_batch_carryovers(plan, candidate_carryovers)
            complete = _week_day_plan_is_complete(plan, profile)
            used_avoided = _plan_uses_avoided_recipes(plan, avoided_recipe_ids, avoided_recipe_keys)
            _weekly_selection_diag(
                "candidate_end",
                phase=candidate_phase,
                recent_phase=_weekly_selection_phase_label(selection_phase),
                raw_phase=selection_phase,
                day_index=day_index,
                candidate_index=candidate_index,
                seed=candidate_seed,
                elapsed_s=f"{time.perf_counter() - candidate_started_at:.3f}",
                complete=complete,
                meals=len(plan.meals),
                recipe_count=len({meal.recipe_id for meal in plan.meals if meal.recipe_id}),
                used_avoided=used_avoided,
            )
            if selection_guard is not None:
                selection_guard.check(
                    stage="after_candidate",
                    day_index=day_index,
                    candidate_index=candidate_index,
                )
            if not complete:
                rejected_plan = rejected_plan or plan
                continue
            if used_avoided:
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
            candidate_options.append((plan, candidate_carryovers, candidate_index))

    add_selectable_candidates(range(WEEK_PLAN_CANDIDATE_COUNT))
    if not candidate_options:
        rescue_start = WEEK_PLAN_CANDIDATE_COUNT
        rescue_stop = rescue_start + WEEK_PLAN_RESCUE_CANDIDATE_COUNT
        add_selectable_candidates(range(rescue_start, rescue_stop))

    if candidate_options:
        candidate_recipe_counts = _candidate_recipe_counts(tuple(option[0] for option in candidate_options))
        best_plan, best_carryovers, _ = max(
            candidate_options,
            key=lambda option: _weekly_day_selection_score(
                option[0],
                week_food_ids,
                option[2],
                week_recipe_ids_for_diversity=week_recipe_ids_for_diversity,
                candidate_recipe_counts=candidate_recipe_counts,
                recipe_trait_lookup=recipe_trait_lookup,
            ),
        )
        return best_plan, best_carryovers

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
            recipe_cache=recipe_cache,
            selection_guard=(
                _WeeklySelectionScopedGuard(selection_guard, day_index, None)
                if selection_guard is not None
                else None
            ),
        ),
        carryovers,
    )


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
    _remember_recipe_history_items(
        chat_id,
        _recipe_history_items_from_plan(plan_result, "one_day"),
    )


def _load_chat_history(chat_id: int) -> None:
    chat_state = _load_chat_state(chat_id)
    RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_ids", []))[-RECENT_RECIPE_LIMIT:]
    RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] = list(chat_state.get("recipe_keys", []))[-RECENT_RECIPE_LIMIT:]


def _save_chat_history(
    chat_id: int,
    *,
    recipe_ids: Sequence[str] | None = None,
    recipe_keys: Sequence[str] | None = None,
) -> None:
    stored_recipe_ids = (
        RECENT_RECIPE_IDS_BY_CHAT_ID.get(chat_id, [])
        if recipe_ids is None
        else recipe_ids
    )
    stored_recipe_keys = (
        RECENT_RECIPE_KEYS_BY_CHAT_ID.get(chat_id, [])
        if recipe_keys is None
        else recipe_keys
    )
    try:
        _chat_state_store().save_chat_state(
            chat_id,
            {
                "recipe_ids": list(stored_recipe_ids)[-RECENT_RECIPE_LIMIT:],
                "recipe_keys": list(stored_recipe_keys)[-RECENT_RECIPE_LIMIT:],
            },
        )
    except ChatStateStorageError:
        raise
    except Exception as exc:
        raise ChatStateStorageError("Could not save chat history") from exc


def _profile_for_chat(chat_id: int) -> UserProfile | None:
    profile = PROFILE_BY_CHAT_ID.get(chat_id)
    if profile is not None:
        return profile

    chat_state = _load_chat_state(chat_id)
    raw_profile = chat_state.get("profile")
    if not isinstance(raw_profile, dict):
        return None

    profile = _profile_from_dict(raw_profile)
    if profile is None:
        return None
    PROFILE_BY_CHAT_ID[chat_id] = profile
    return profile


def _save_chat_profile(chat_id: int, profile: UserProfile) -> None:
    try:
        _chat_state_store().save_chat_state(chat_id, {"profile": _profile_to_dict(profile)})
    except ChatStateStorageError:
        raise
    except Exception as exc:
        raise ChatStateStorageError("Could not save chat profile") from exc


def _has_privacy_consent(chat_id: int) -> bool:
    if chat_id in PRIVACY_CONSENT_CHAT_IDS:
        return True
    chat_state = _load_chat_state(chat_id)
    if not _is_privacy_consent_record(chat_state.get("privacy_consent")):
        return False
    PRIVACY_CONSENT_CHAT_IDS.add(chat_id)
    return True


def _save_privacy_consent(chat_id: int) -> None:
    try:
        _chat_state_store().save_chat_state(chat_id, {"privacy_consent": _privacy_consent_record()})
    except ChatStateStorageError:
        raise
    except Exception as exc:
        raise ChatStateStorageError("Could not save privacy consent") from exc
    PRIVACY_CONSENT_CHAT_IDS.add(chat_id)


def _privacy_consent_record(now: datetime | None = None) -> dict[str, object]:
    record: dict[str, object] = {
        "accepted": True,
        "accepted_at": (now or datetime.now(UTC)).replace(microsecond=0).isoformat(),
        "text_sha256": hashlib.sha256(PRIVACY_CONSENT_TEXT.encode("utf-8")).hexdigest(),
        "schema_version": PRIVACY_CONSENT_SCHEMA_VERSION,
    }
    if PRIVACY_POLICY_URL:
        record["policy_url"] = PRIVACY_POLICY_URL
    return record


def _is_privacy_consent_record(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    accepted_at = value.get("accepted_at")
    return value.get("accepted") is True and isinstance(accepted_at, str) and bool(accepted_at.strip())


def _load_chat_state(chat_id: int) -> dict[str, object]:
    try:
        store = _chat_state_store()
        load_chat_state = getattr(store, "load_chat_state", None)
        if callable(load_chat_state):
            return dict(load_chat_state(chat_id) or {})
        return dict(store.load_all().get(str(chat_id), {}))
    except ChatStateStorageError:
        raise
    except Exception as exc:
        logger.exception("Unexpected chat state load failure")
        raise ChatStateStorageError("Could not load chat state") from exc


def _load_state() -> dict[str, dict[str, object]]:
    try:
        return _chat_state_store().load_all()
    except ChatStateStorageError:
        raise
    except Exception as exc:
        logger.exception("Unexpected chat state load failure")
        raise ChatStateStorageError("Could not load chat state") from exc


def _save_state(state: dict[str, dict[str, object]]) -> None:
    _chat_state_store().save_all(state)


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


def _privacy_policy_button() -> InlineKeyboardButton | None:
    if PRIVACY_POLICY_URL:
        return InlineKeyboardButton(text=PRIVACY_POLICY_TEXT, url=PRIVACY_POLICY_URL)
    return InlineKeyboardButton(text=PRIVACY_POLICY_TEXT, callback_data=CALLBACK_PRIVACY_POLICY)


def _rows_with_privacy_policy(
    rows: Sequence[Sequence[InlineKeyboardButton]],
) -> list[list[InlineKeyboardButton]]:
    keyboard_rows = [list(row) for row in rows]
    privacy_button = _privacy_policy_button()
    if privacy_button is not None:
        keyboard_rows.append([privacy_button])
    return keyboard_rows


def _keyboard_with_privacy_policy(rows: Sequence[Sequence[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_rows_with_privacy_policy(rows))


def _optional_keyboard_with_privacy_policy(
    rows: Sequence[Sequence[InlineKeyboardButton]],
) -> InlineKeyboardMarkup | None:
    keyboard_rows = _rows_with_privacy_policy(rows)
    if not keyboard_rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def _start_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=TRY_FREE_TEXT, callback_data=CALLBACK_START)],
    ]
    if _payments_enabled():
        rows.append([InlineKeyboardButton(text=SUBSCRIBE_MONTH_TEXT, callback_data=CALLBACK_SUBSCRIBE)])
    rows.extend(
        [
            [InlineKeyboardButton(text=FEATURES_TEXT, callback_data=CALLBACK_FEATURES)],
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )
    return _keyboard_with_privacy_policy(rows)


def _privacy_consent_keyboard(*, is_trial: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=PRIVACY_CONSENT_ACCEPT_TEXT,
                callback_data=CALLBACK_PRIVACY_CONSENT_TRIAL if is_trial else CALLBACK_PRIVACY_CONSENT,
            ),
        ],
    ]
    privacy_button = _privacy_policy_button()
    if privacy_button is not None:
        rows.append([privacy_button])
    rows.append([InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    return _keyboard_with_privacy_policy(
        [
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
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
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
    if not _payments_enabled():
        await _send_payments_disabled_notice(message)
        return
    if await _send_active_subscription_notice_if_needed(message):
        return
    await message.answer(SUBSCRIPTION_PAYMENT_TEXT, reply_markup=_subscription_payment_keyboard())


async def _send_payments_disabled_notice(message: Message) -> None:
    await message.answer(PAYMENTS_DISABLED_TEXT, reply_markup=_payments_disabled_keyboard())


async def _send_payment_ledger_unavailable_notice(message: Message) -> None:
    await message.answer(PAYMENT_LEDGER_UNAVAILABLE_TEXT, reply_markup=_payments_disabled_keyboard())


async def _send_payment_activation_delayed_notice(message: Message) -> None:
    await message.answer(PAYMENT_ACTIVATION_DELAYED_TEXT, reply_markup=_payments_disabled_keyboard())


async def _send_active_subscription_notice_if_needed(message: Message) -> bool:
    try:
        entitlement = await _run_entitlement_db_call(_entitlement_for_chat, message.chat.id)  # type: ignore[assignment]
    except EntitlementStorageError:
        logger.exception("Failed to check active subscription due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return True
    if not entitlement.is_subscription_active():
        return False
    try:
        reply_markup = await _run_entitlement_db_call(
            _subscriber_cabinet_keyboard,
            message.chat.id,
            entitlement=entitlement,
        )
    except EntitlementStorageError:
        logger.exception("Failed to render active subscription keyboard due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return True
    await message.answer(
        _active_subscription_notice_text(entitlement),
        reply_markup=reply_markup,
    )
    return True


async def _send_extra_purchase_subscription_notice_if_needed(message: Message) -> bool:
    try:
        entitlement = await _run_entitlement_db_call(_entitlement_for_chat, message.chat.id)  # type: ignore[assignment]
    except EntitlementStorageError:
        logger.exception("Failed to check extra purchase subscription due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return True
    if entitlement.is_subscription_active() and not _is_free_preview_mode(message.chat.id, entitlement):
        return False
    await message.answer(
        "Разовые покупки доступны только при активном месячном доступе.\n\n"
        "Чтобы продолжить, оформите месячный доступ или введите промокод.",
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


async def _send_payment_invoice_link(
    message: Message,
    provider: str,
    product: str,
    *,
    payer_user_id: int | None = None,
) -> None:
    payload = PAYMENT_PRODUCT_PAYLOADS[(provider, product)]
    if provider == PROVIDER_TELEGRAM_STARS:
        await _send_stars_invoice_link(message, payload, payer_user_id=payer_user_id)
        return
    await _send_yookassa_invoice_link(message, payload, payer_user_id=payer_user_id)


async def _send_stars_invoice_link(message: Message, payload: str, *, payer_user_id: int | None = None) -> None:
    if not _payments_enabled():
        await _send_payments_disabled_notice(message)
        return

    provider, product = _payment_product_for_legacy_payload(payload)
    if provider != PROVIDER_TELEGRAM_STARS:
        raise ValueError(f"Unsupported Stars payment payload: {payload!r}")
    amount = PAYMENT_PAYLOAD_AMOUNTS[payload]
    title = PAYMENT_PAYLOAD_TITLES[payload]
    description = PAYMENT_PAYLOAD_DESCRIPTIONS[payload]
    subscription_period = SUBSCRIPTION_PERIOD_SECONDS if payload == PAYLOAD_SUBSCRIPTION_MONTH else None
    try:
        service, order, invoice_payload = _create_payment_order_payload(
            message,
            provider,
            product,
            payer_user_id=payer_user_id,
        )
    except PaymentLedgerUnavailable as exc:
        logger.warning("Payment ledger is unavailable for Stars invoice: %s", exc.reason)
        await _send_payment_ledger_unavailable_notice(message)
        return
    except Exception:
        logger.exception("Failed to create payment ledger order for Stars invoice")
        await _send_payment_ledger_unavailable_notice(message)
        return
    if getattr(order, "reused_pending", False):
        await message.answer(PAYMENT_PENDING_INVOICE_ALREADY_OPEN_TEXT)
        return

    try:
        invoice_link = await message.bot.create_invoice_link(
            title=title,
            description=description,
            payload=invoice_payload,
            currency="XTR",
            prices=[LabeledPrice(label=title, amount=amount)],
            provider_token="",
            subscription_period=subscription_period,
        )
    except TelegramAPIError:
        _mark_payment_order_failed(service, order.order_id, "invoice_creation_failed")
        await message.answer("Не удалось создать счет для оплаты. Попробуйте позже.")
        return
    await message.answer(
        f"{title}\n\nСтоимость: {amount} Stars.",
        reply_markup=_keyboard_with_privacy_policy(
            [
                [InlineKeyboardButton(text="Оплатить в Telegram", url=invoice_link)],
            ],
        ),
    )


async def _send_yookassa_invoice_link(message: Message, payload: str, *, payer_user_id: int | None = None) -> None:
    if not _payments_enabled():
        await _send_payments_disabled_notice(message)
        return

    provider, product = _payment_product_for_legacy_payload(payload)
    if provider != PROVIDER_YOOKASSA:
        raise ValueError(f"Unsupported YooKassa payment payload: {payload!r}")
    provider_token = TELEGRAM_PROVIDER_TOKEN.strip()
    if not provider_token:
        await message.answer(_ru_card_payment_unavailable_text(payload))
        return

    amount = RUB_PAYMENT_PAYLOAD_AMOUNTS[payload]
    title = RUB_PAYMENT_PAYLOAD_TITLES[payload]
    description = RUB_PAYMENT_PAYLOAD_DESCRIPTIONS[payload]
    try:
        service, order, invoice_payload = _create_payment_order_payload(
            message,
            provider,
            product,
            payer_user_id=payer_user_id,
        )
    except PaymentLedgerUnavailable as exc:
        logger.warning("Payment ledger is unavailable for YooKassa invoice: %s", exc.reason)
        await _send_payment_ledger_unavailable_notice(message)
        return
    except Exception:
        logger.exception("Failed to create payment ledger order for YooKassa invoice")
        await _send_payment_ledger_unavailable_notice(message)
        return
    if getattr(order, "reused_pending", False):
        await message.answer(PAYMENT_PENDING_INVOICE_ALREADY_OPEN_TEXT)
        return

    try:
        invoice_link = await message.bot.create_invoice_link(
            title=title,
            description=description,
            payload=invoice_payload,
            currency="RUB",
            prices=[LabeledPrice(label=title, amount=amount)],
            provider_token=provider_token,
            need_email=True,
            send_email_to_provider=True,
            provider_data=json.dumps(_yookassa_provider_data(payload), ensure_ascii=False),
        )
    except TelegramAPIError:
        _mark_payment_order_failed(service, order.order_id, "invoice_creation_failed")
        await message.answer("Не удалось создать счет для оплаты. Попробуйте позже.")
        return

    await message.answer(
        f"{title}\n\nСтоимость: {_format_kopecks_for_display(amount)} ₽.",
        reply_markup=_keyboard_with_privacy_policy(
            [
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


def _payment_product_for_legacy_payload(payload: str) -> tuple[str, str]:
    try:
        return PAYMENT_PAYLOAD_PRODUCTS[payload]
    except KeyError as exc:
        raise ValueError(f"Unsupported payment payload: {payload!r}") from exc


def _create_payment_order_payload(
    message: Message,
    provider: str,
    product: str,
    *,
    payer_user_id: int | None = None,
) -> tuple[object, PaymentOrder, str]:
    service = _payment_service()
    order = service.create_order(
        user_id=_message_user_id(message) if payer_user_id is None else int(payer_user_id),
        chat_id=message.chat.id,
        product=product,
        provider=provider,
    )
    return service, order, encode_payment_order_payload(order.order_id, order.nonce)


def _mark_payment_order_failed(service: object, order_id: str, reason: str) -> None:
    mark_order_failed = getattr(service, "mark_order_failed", None)
    if callable(mark_order_failed):
        mark_order_failed(order_id, reason)


def _message_user_id(message: Message) -> int:
    from_user = getattr(message, "from_user", None)
    user_id = getattr(from_user, "id", None)
    return int(message.chat.id if user_id is None else user_id)


def _callback_user_id(callback: CallbackQuery) -> int:
    from_user = getattr(callback, "from_user", None)
    user_id = getattr(from_user, "id", None)
    if user_id is None:
        raise ValueError("CallbackQuery.from_user.id is required for payment invoice creation.")
    return int(user_id)


def _pre_checkout_user_id(pre_checkout_query: PreCheckoutQuery) -> int | None:
    from_user = getattr(pre_checkout_query, "from_user", None)
    user_id = getattr(from_user, "id", None)
    return int(user_id) if user_id is not None else None


def _payment_provider_for_currency(currency: str) -> str | None:
    if currency == "XTR":
        return PROVIDER_TELEGRAM_STARS
    if currency == "RUB":
        return PROVIDER_YOOKASSA
    return None


def _payment_provider_for_payment(payment: SuccessfulPayment) -> str | None:
    provider = _payment_provider_for_currency(payment.currency)
    if provider is not None:
        return provider
    legacy_mapping = PAYMENT_PAYLOAD_PRODUCTS.get(payment.invoice_payload)
    return legacy_mapping[0] if legacy_mapping else None


def _payment_raw_payload(payment: SuccessfulPayment) -> dict[str, object]:
    raw = {
        "invoice_payload": payment.invoice_payload,
        "currency": payment.currency,
        "total_amount": payment.total_amount,
        "telegram_payment_charge_id": getattr(payment, "telegram_payment_charge_id", None),
        "provider_payment_charge_id": getattr(payment, "provider_payment_charge_id", None),
    }
    subscription_expiration = getattr(payment, "subscription_expiration_date", None)
    if subscription_expiration is not None:
        raw["subscription_expiration_date"] = subscription_expiration
    return raw


def _spool_failed_successful_payment(
    message: Message,
    payment: SuccessfulPayment,
    exc: PaymentLedgerUnavailable,
) -> None:
    record: PaymentRecoveryRecord | None = None
    try:
        record = _payment_recovery_record_from_message(message, payment)
        append_payment_recovery_record(_payment_recovery_spool_path(), record)
    except Exception:
        logger.critical(
            "Failed to spool payment recovery record after successful_payment grant failure",
            exc_info=True,
            extra=_payment_recovery_log_extra(message, payment, exc, record),
        )
        return

    logger.critical(
        "Spooled payment recovery record after successful_payment grant failure",
        extra=_payment_recovery_log_extra(message, payment, exc, record),
    )


def _payment_recovery_record_from_message(
    message: Message,
    payment: SuccessfulPayment,
) -> PaymentRecoveryRecord:
    provider = _payment_provider_for_payment(payment)
    if provider is None:
        raise ValueError("Cannot determine payment provider for successful_payment recovery record.")
    return PaymentRecoveryRecord(
        provider=provider,
        chat_id=int(message.chat.id),
        user_id=_message_user_id(message),
        invoice_payload=str(payment.invoice_payload),
        telegram_payment_charge_id=getattr(payment, "telegram_payment_charge_id", None),
        provider_payment_charge_id=getattr(payment, "provider_payment_charge_id", None),
        currency=str(payment.currency),
        total_amount=int(payment.total_amount),
        subscription_expiration_date=getattr(payment, "subscription_expiration_date", None),
        created_at=datetime.now(UTC),
    )


def _payment_recovery_spool_path() -> Path:
    configured_path = os.environ.get(PAYMENT_RECOVERY_SPOOL_ENV, "").strip()
    if configured_path:
        return Path(configured_path)
    return Path(SUBSCRIPTIONS_STATE_FILE).with_name("payment_recovery.jsonl")


def _payment_recovery_log_extra(
    message: Message,
    payment: SuccessfulPayment,
    exc: PaymentLedgerUnavailable,
    record: PaymentRecoveryRecord | None,
) -> dict[str, object]:
    return redact_log_identifiers({
        "record_id": record.record_id if record is not None else None,
        "payment_provider": record.provider if record is not None else _payment_provider_for_payment(payment),
        "chat_id": int(message.chat.id),
        "user_id": _message_user_id(message),
        "order_id": _payment_order_id_for_log(getattr(payment, "invoice_payload", None)),
        "telegram_payment_charge_id": getattr(payment, "telegram_payment_charge_id", None),
        "provider_payment_charge_id": getattr(payment, "provider_payment_charge_id", None),
        "ledger_failure_reason": exc.reason,
    })


def _payment_order_id_for_log(invoice_payload: object) -> str | None:
    if not isinstance(invoice_payload, str):
        return None
    try:
        decoded = decode_payment_order_payload(invoice_payload)
    except Exception:
        return None
    return decoded.order_id if decoded is not None else None


def _payment_application_from_handling_result(result: PaymentHandlingResult) -> PaymentApplication:
    grants = {
        PRODUCT_SUBSCRIPTION_MONTH: "subscription",
        PRODUCT_EXTRA_ONE_DAY: "extra_one_day",
        PRODUCT_EXTRA_WEEKLY_PDF: "extra_weekly_pdf",
    }
    return PaymentApplication(result.processed, grants.get(result.grant), result.duplicate)


def _is_valid_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> bool:
    if not _payments_enabled():
        return False

    payload = str(pre_checkout_query.invoice_payload or "")
    if not payload.startswith("diet:order:"):
        return False

    provider = _payment_provider_for_currency(pre_checkout_query.currency)
    if provider is None:
        return False
    if provider == PROVIDER_YOOKASSA and not TELEGRAM_PROVIDER_TOKEN.strip():
        return False
    user_id = _pre_checkout_user_id(pre_checkout_query)
    if user_id is None:
        return False

    try:
        validation = _payment_service().validate_order_payment(
            payload,
            user_id=user_id,
            chat_id=None,
            provider=provider,
            amount=pre_checkout_query.total_amount,
            currency=pre_checkout_query.currency,
        )
    except PaymentLedgerUnavailable as exc:
        logger.warning("Payment ledger is unavailable during pre_checkout: %s", exc.reason)
        return False
    except Exception:
        logger.exception("Failed to validate pre_checkout against payment ledger")
        return False
    return validation.valid


def _apply_successful_payment(
    chat_id: int,
    payment: SuccessfulPayment,
    *,
    user_id: int | None = None,
) -> PaymentApplication:
    provider = _payment_provider_for_payment(payment)
    if provider is None:
        return PaymentApplication(False)
    try:
        result = _payment_service().handle_successful_payment(
            payload=payment.invoice_payload,
            user_id=chat_id if user_id is None else user_id,
            chat_id=chat_id,
            provider=provider,
            amount=payment.total_amount,
            currency=payment.currency,
            telegram_payment_charge_id=getattr(payment, "telegram_payment_charge_id", None),
            provider_payment_charge_id=getattr(payment, "provider_payment_charge_id", None),
            raw_payload=_payment_raw_payload(payment),
        )
    except PaymentLedgerUnavailable:
        raise
    except Exception as exc:
        raise PaymentLedgerUnavailable("payment_ledger_unavailable", "Payment ledger is unavailable.") from exc
    application = _payment_application_from_handling_result(result)
    _cancel_sales_followup_after_payment_grant(chat_id, application)
    return application


def _cancel_sales_followup_after_payment_grant(chat_id: int, result: PaymentApplication) -> None:
    if not result.processed:
        return
    if result.grant == "subscription":
        _cancel_sales_followup_after_access_grant(chat_id, reason="subscription_granted")
        return
    if result.grant == "extra_weekly_pdf":
        _cancel_sales_followup_after_access_grant(chat_id, reason="weekly_pdf_access_granted")


def _payment_success_text(result: PaymentApplication) -> str:
    if result.grant == "subscription":
        return "Месячный доступ активен. Лимиты на этот период обновлены."
    if result.grant == "extra_one_day":
        return "Готово: добавлена 1 попытка для дневного рациона."
    if result.grant == "extra_weekly_pdf":
        return "Готово: добавлена 1 попытка для недельного PDF."
    return "Платеж обработан."


def _activate_promo_code_for_chat(chat_id: int, promo_code: str) -> PromoCodeActivation:
    config = load_runtime_config()
    if config.storage_backend == "postgres":
        return _activate_postgres_promo_code_for_chat(config, chat_id, promo_code)

    activation = activate_promo_code(PROMO_CODES_STATE_FILE, promo_code, chat_id)
    if not activation.activated:
        return activation

    try:
        grant_result = _entitlement_service().apply_subscription_payment(
            chat_id,
            promo_code_grant_charge_id(activation.code),
            subscription_source="promo",
            auto_renew_status="not_applicable",
            last_subscription_payment_charge_id=promo_code_grant_charge_id(activation.code),
        )
    except Exception:
        try:
            release_promo_code_activation(PROMO_CODES_STATE_FILE, activation.code, chat_id)
        except Exception:
            logger.exception("Failed to roll back promo activation after entitlement grant failure")
        raise
    if getattr(grant_result, "processed", True):
        _cancel_sales_followup_after_access_grant(chat_id, reason="monthly_access_promo_granted")
    return activation


def _activate_postgres_promo_code_for_chat(config, chat_id: int, promo_code: str) -> PromoCodeActivation:
    code = normalize_promo_code(promo_code)
    if not code:
        return PromoCodeActivation("not_found", "")

    charge_id = promo_code_grant_charge_id(code)
    store = _postgres_promo_store(config)
    try:
        reserve_result = store.reserve_promo_code(
            promo_code,
            chat_id=chat_id,
            idempotency_key=f"promo:{code}:chat:{int(chat_id)}:activation",
            kind=PromoCodeKind.MONTHLY_ACCESS,
            entitlement_charge_id=charge_id,
        )
    except EntitlementStorageError:
        raise
    except Exception as exc:
        logger.exception("Failed to reserve promo code through Postgres promo store")
        raise EntitlementStorageError("Postgres promo store is unavailable.") from exc

    activation = _promo_activation_from_store_result(reserve_result, fallback_code=code, chat_id=chat_id)
    if not activation.activated:
        return activation

    redemption_id = _promo_redemption_id_from_store_result(reserve_result)
    try:
        grant_result = _entitlement_service().apply_subscription_payment(
            chat_id,
            charge_id,
            subscription_source="promo",
            auto_renew_status="not_applicable",
            last_subscription_payment_charge_id=charge_id,
        )
    except Exception:
        try:
            store.release_promo_redemption(redemption_id, failure_reason="entitlement_grant_failed")
        except Exception:
            logger.exception("Failed to release Postgres promo reservation after entitlement grant failure")
        raise

    if getattr(grant_result, "processed", True):
        _cancel_sales_followup_after_access_grant(chat_id, reason="monthly_access_promo_granted")

    try:
        store.finalize_promo_redemption(redemption_id, entitlement_charge_id=charge_id)
    except Exception as exc:
        logger.exception("Failed to finalize Postgres promo redemption after entitlement grant")
        raise EntitlementStorageError("Postgres promo redemption finalization failed.") from exc

    return activation


def _promo_activation_from_store_result(
    result,
    *,
    fallback_code: str,
    chat_id: int,
) -> PromoCodeActivation:
    status = str(getattr(result, "status", "not_found"))
    result_code = normalize_promo_code(str(getattr(result, "code", fallback_code))) or fallback_code
    result_chat_id = getattr(result, "chat_id", None)
    used_by_chat_id = int(result_chat_id) if result_chat_id is not None else None
    if status in {"reserved", "redeemed"}:
        return PromoCodeActivation("activated", result_code, int(chat_id))
    if status in {"already_redeemed", "already_used", "max_uses_reached"}:
        return PromoCodeActivation("already_used", result_code, used_by_chat_id)
    if status in {"not_found", "disabled", "expired", "not_access_code"}:
        return PromoCodeActivation(status, result_code, used_by_chat_id)
    raise EntitlementStorageError(f"Unexpected promo store activation status: {status}")


def _promo_redemption_id_from_store_result(result) -> int:
    redemption = getattr(result, "redemption", None)
    redemption_id = getattr(redemption, "redemption_id", None)
    if redemption_id is None:
        raise EntitlementStorageError("Postgres promo store did not return a reservation id.")
    return int(redemption_id)


def _promo_code_success_text(chat_id: int) -> str:
    return (
        "Поздравляем! Промокод активирован.\n\n"
        "У вас активировался месячный доступ. Теперь вы можете сгенерировать "
        f"{MONTHLY_WEEKLY_PDF_LIMIT} недельных PDF-рациона и "
        f"{MONTHLY_ONE_DAY_LIMIT} дневных рационов.\n\n"
        f"{_format_entitlement_status(chat_id)}"
    )


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
    await message.answer(ADMIN_PROMO_PANEL_TEXT, reply_markup=_admin_promo_panel_keyboard())


@dataclass(frozen=True)
class _AdminDiscountPromoInput:
    code: str
    percent: int


def _set_admin_promo_action(chat_id: int, action: str) -> None:
    SUPPORT_REQUEST_CHAT_IDS.discard(chat_id)
    PROMO_CODE_REQUEST_CHAT_IDS.discard(chat_id)
    _clear_questionnaire_session(chat_id)
    ADMIN_PROMO_ACTION_BY_CHAT_ID[chat_id] = action


async def _start_admin_discount_promo_create(message: Message) -> None:
    _set_admin_promo_action(message.chat.id, ADMIN_PROMO_ACTION_CREATE_DISCOUNT)
    await message.answer(ADMIN_DISCOUNT_PROMO_INPUT_TEXT)


async def _start_admin_discount_promo_disable(message: Message) -> None:
    _set_admin_promo_action(message.chat.id, ADMIN_PROMO_ACTION_DISABLE_DISCOUNT)
    await message.answer(ADMIN_DISABLE_DISCOUNT_PROMO_INPUT_TEXT)


async def _handle_admin_promo_action_input(message: Message, text: str) -> None:
    if not _is_admin_message(message):
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
        await message.answer("Command is available only to admins.")
        return

    action = ADMIN_PROMO_ACTION_BY_CHAT_ID.get(message.chat.id)
    if action == ADMIN_PROMO_ACTION_CREATE_DISCOUNT:
        parsed, error = _parse_admin_discount_promo_input(text)
        if error is not None or parsed is None:
            await message.answer(error or ADMIN_DISCOUNT_PROMO_INPUT_TEXT)
            return
        promo, error = _create_or_update_admin_discount_promo(
            parsed,
            admin_user_id=_message_user_id(message),
        )
        if error is not None or promo is None:
            await message.answer(error or "Не удалось сохранить discount promo.")
            return
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
        await message.answer(f"Скидка активна: {promo.code}\nРазмер скидки: {promo.discount_percent}%.")
        return

    if action == ADMIN_PROMO_ACTION_DISABLE_DISCOUNT:
        code, error = _parse_admin_discount_code_input(text)
        if error is not None or code is None:
            await message.answer(error or ADMIN_DISABLE_DISCOUNT_PROMO_INPUT_TEXT)
            return
        promo, error = _disable_admin_discount_promo(code, admin_user_id=_message_user_id(message))
        if error is not None or promo is None:
            await message.answer(error or f"Discount promo code {code} не найден.")
            return
        ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)
        await message.answer(f"Скидка отключена: {promo.code}.")
        return

    ADMIN_PROMO_ACTION_BY_CHAT_ID.pop(message.chat.id, None)


def _parse_admin_discount_promo_input(text: str) -> tuple[_AdminDiscountPromoInput | None, str | None]:
    parts = text.strip().split()
    if len(parts) != 2:
        return None, "Отправьте код и процент скидки в формате CODE PERCENT."

    code = normalize_promo_code(parts[0])
    if not code:
        return None, "Код не должен быть пустым."
    try:
        percent = int(parts[1])
    except ValueError:
        return None, "Процент скидки должен быть числом."
    if percent < 1 or percent > 90:
        return None, "Процент скидки должен быть от 1 до 90."
    return _AdminDiscountPromoInput(code=code, percent=percent), None


def _parse_admin_discount_code_input(text: str) -> tuple[str | None, str | None]:
    parts = text.strip().split()
    if len(parts) != 1:
        return None, "Код скидки должен быть без пробелов."
    code = normalize_promo_code(parts[0])
    if not code:
        return None, "Код не должен быть пустым."
    return code, None


def _create_or_update_admin_discount_promo(
    parsed: _AdminDiscountPromoInput,
    *,
    admin_user_id: int | None = None,
) -> tuple[PromoCodeDefinition | None, str | None]:
    config = load_runtime_config()
    if config.storage_backend == "postgres":
        return _create_or_update_postgres_admin_discount_promo(
            config,
            parsed,
            admin_user_id=admin_user_id,
        )

    promo_codes = load_promo_codes(PROMO_CODES_STATE_FILE)
    existing = promo_codes.get(parsed.code)
    if existing is not None and not _promo_record_is_kind(existing, PromoCodeKind.DISCOUNT):
        return None, f"Код {parsed.code} уже существует как {existing.kind}. Через discount flow его не меняю."

    definition = PromoCodeDefinition(
        code=parsed.code,
        kind=PromoCodeKind.DISCOUNT,
        active=True,
        max_redemptions=existing.max_redemptions if existing is not None else 1,
        per_user_limit=existing.per_user_limit if existing is not None else 1,
        expires_at=existing.expires_at if existing is not None else None,
        discount_percent=parsed.percent,
    )
    promo_codes[definition.code] = PromoCodeRecord.from_definition(definition)
    save_promo_codes(PROMO_CODES_STATE_FILE, promo_codes)
    return definition, None


async def _send_admin_discount_promo_list(message: Message) -> None:
    try:
        promos = _list_admin_discount_promos()
    except EntitlementStorageError:
        logger.exception("Failed to list admin discount promos due to promo storage error")
        await message.answer(ADMIN_PROMO_STORAGE_ERROR_TEXT)
        return
    await message.answer(_format_admin_discount_promo_list(promos))


def _list_admin_discount_promos() -> list[PromoCodeDefinition]:
    config = load_runtime_config()
    if config.storage_backend == "postgres":
        return _list_postgres_admin_discount_promos(config)

    promos: list[PromoCodeDefinition] = []
    for code, record in load_promo_codes(PROMO_CODES_STATE_FILE).items():
        if not record.active or record.is_expired() or not _promo_record_is_kind(record, PromoCodeKind.DISCOUNT):
            continue
        promos.append(
            PromoCodeDefinition(
                code=code,
                kind=PromoCodeKind.DISCOUNT,
                active=record.active,
                max_redemptions=record.max_redemptions,
                per_user_limit=record.per_user_limit,
                expires_at=record.expires_at,
                discount_percent=record.discount_percent,
                discount_amount=record.discount_amount,
            )
        )
    return sorted(promos, key=lambda item: item.code)


def _format_admin_discount_promo_list(promos: Sequence[PromoCodeDefinition]) -> str:
    if not promos:
        return "Активных discount promo codes нет."

    lines = ["Активные discount promo codes:"]
    for promo in promos:
        discount = (
            f"{promo.discount_percent}%"
            if promo.discount_percent is not None
            else f"{promo.discount_amount} minor units"
        )
        lines.append(f"{promo.code} — {discount}")
    return "\n".join(lines)


def _disable_admin_discount_promo(
    code: str,
    *,
    admin_user_id: int | None = None,
) -> tuple[PromoCodeDefinition | None, str | None]:
    code = normalize_promo_code(code)
    if not code:
        return None, "Код не должен быть пустым."

    config = load_runtime_config()
    if config.storage_backend == "postgres":
        return _disable_postgres_admin_discount_promo(
            config,
            code,
            admin_user_id=admin_user_id,
        )

    promo_codes = load_promo_codes(PROMO_CODES_STATE_FILE)
    existing = promo_codes.get(code)
    if existing is None:
        return None, f"Discount promo code {code} не найден."
    if not _promo_record_is_kind(existing, PromoCodeKind.DISCOUNT):
        return None, f"Код {code} имеет тип {existing.kind}. Через discount flow отключаются только discount promo."

    disabled = PromoCodeDefinition(
        code=code,
        kind=PromoCodeKind.DISCOUNT,
        active=False,
        max_redemptions=existing.max_redemptions,
        per_user_limit=existing.per_user_limit,
        expires_at=existing.expires_at,
        discount_percent=existing.discount_percent,
        discount_amount=existing.discount_amount,
    )
    promo_codes[disabled.code] = PromoCodeRecord.from_definition(disabled)
    save_promo_codes(PROMO_CODES_STATE_FILE, promo_codes)
    return disabled, None


async def _send_admin_monthly_access_code(message: Message, *, admin_user_id: int | None = None) -> None:
    try:
        promo = _create_admin_monthly_access_promo_code(admin_user_id=admin_user_id)
    except EntitlementStorageError:
        logger.exception("Failed to create admin monthly access promo due to promo storage error")
        await message.answer(ADMIN_PROMO_STORAGE_ERROR_TEXT)
        return
    await message.answer("\n".join(["Created promo code:", promo.code, "Access: 1 month."]))


def _create_admin_monthly_access_promo_code(
    *,
    admin_user_id: int | None = None,
) -> PromoCodeDefinition:
    config = load_runtime_config()
    if config.storage_backend == "postgres":
        return _create_postgres_admin_monthly_access_promo_code(
            config,
            admin_user_id=admin_user_id,
        )

    promo_codes = load_promo_codes(PROMO_CODES_STATE_FILE)
    for _attempt in range(ADMIN_ACCESS_PROMO_CODE_RETRY_LIMIT):
        code = generate_promo_codes(1, existing_codes=set(promo_codes))[0]
        if code in promo_codes:
            continue
        definition = PromoCodeDefinition(
            code=code,
            kind=PromoCodeKind.MONTHLY_ACCESS,
            active=True,
            max_redemptions=1,
            per_user_limit=1,
            monthly_duration_months=1,
        )
        promo_codes[definition.code] = PromoCodeRecord.from_definition(definition)
        save_promo_codes(PROMO_CODES_STATE_FILE, promo_codes)
        return definition
    raise RuntimeError("Could not generate a unique monthly access promo code.")


def _create_postgres_admin_monthly_access_promo_code(
    config,
    *,
    admin_user_id: int | None = None,
) -> PromoCodeDefinition:
    store = _postgres_promo_store(config)
    for _attempt in range(ADMIN_ACCESS_PROMO_CODE_RETRY_LIMIT):
        code = generate_promo_codes(1)[0]
        try:
            if store.get_promo_code(code) is not None:
                continue
            definition = PromoCodeDefinition(
                code=code,
                kind=PromoCodeKind.MONTHLY_ACCESS,
                active=True,
                max_redemptions=1,
                per_user_limit=1,
                monthly_duration_months=1,
            )
            stored = store.create_or_update_promo_code(
                definition,
                created_by=admin_user_id,
                metadata=_admin_promo_metadata("create_monthly_access"),
            )
        except EntitlementStorageError:
            raise
        except Exception as exc:
            raise EntitlementStorageError("Postgres promo store is unavailable.") from exc
        return _promo_definition_from_store_promo(stored)
    raise RuntimeError("Could not generate a unique monthly access promo code.")


def _create_or_update_postgres_admin_discount_promo(
    config,
    parsed: _AdminDiscountPromoInput,
    *,
    admin_user_id: int | None = None,
) -> tuple[PromoCodeDefinition | None, str | None]:
    try:
        store = _postgres_promo_store(config)
        existing = store.get_promo_code(parsed.code)
        existing_definition = _promo_definition_from_store_promo(existing) if existing is not None else None
        if existing_definition is not None and existing_definition.kind != PromoCodeKind.DISCOUNT:
            return (
                None,
                f"Код {parsed.code} уже существует как {existing_definition.kind}. Через discount flow его не меняю.",
            )
        definition = PromoCodeDefinition(
            code=parsed.code,
            kind=PromoCodeKind.DISCOUNT,
            active=True,
            max_redemptions=existing_definition.max_redemptions if existing_definition is not None else 1,
            per_user_limit=existing_definition.per_user_limit if existing_definition is not None else 1,
            expires_at=existing_definition.expires_at if existing_definition is not None else None,
            discount_percent=parsed.percent,
        )
        stored = store.create_or_update_promo_code(
            definition,
            created_by=admin_user_id,
            metadata=_admin_promo_metadata("create_discount"),
        )
    except EntitlementStorageError:
        logger.exception("Failed to create or update admin discount promo due to promo storage error")
        return None, ADMIN_PROMO_STORAGE_ERROR_TEXT
    except Exception:
        logger.exception("Failed to create or update admin discount promo through Postgres promo store")
        return None, ADMIN_PROMO_STORAGE_ERROR_TEXT
    return _promo_definition_from_store_promo(stored), None


def _list_postgres_admin_discount_promos(config) -> list[PromoCodeDefinition]:
    try:
        store = _postgres_promo_store(config)
        promos = [
            _promo_definition_from_store_promo(promo)
            for promo in store.list_active_promo_codes()
            if _promo_store_promo_is_kind(promo, PromoCodeKind.DISCOUNT)
        ]
    except EntitlementStorageError:
        logger.exception("Failed to list admin discount promos due to promo storage error")
        raise
    except Exception as exc:
        raise EntitlementStorageError("Postgres promo store is unavailable.") from exc
    return sorted(promos, key=lambda item: item.code)


def _disable_postgres_admin_discount_promo(
    config,
    code: str,
    *,
    admin_user_id: int | None = None,
) -> tuple[PromoCodeDefinition | None, str | None]:
    try:
        store = _postgres_promo_store(config)
        existing = store.get_promo_code(code)
        if existing is None:
            return None, f"Discount promo code {code} не найден."
        if not _promo_store_promo_is_kind(existing, PromoCodeKind.DISCOUNT):
            existing_kind = getattr(existing, "kind", None)
            return None, f"Код {code} имеет тип {existing_kind}. Через discount flow отключаются только discount promo."
        disabled = store.disable_promo_code(code, disabled_by=admin_user_id)
        if disabled is None:
            return None, f"Discount promo code {code} не найден."
    except EntitlementStorageError:
        logger.exception("Failed to disable admin discount promo due to promo storage error")
        return None, ADMIN_PROMO_STORAGE_ERROR_TEXT
    except Exception:
        logger.exception("Failed to disable admin discount promo through Postgres promo store")
        return None, ADMIN_PROMO_STORAGE_ERROR_TEXT
    return _promo_definition_from_store_promo(disabled), None


def _promo_definition_from_store_promo(promo) -> PromoCodeDefinition:
    to_definition = getattr(promo, "to_definition", None)
    if callable(to_definition):
        definition = to_definition()
        return PromoCodeDefinition(**definition.to_dict())
    return PromoCodeDefinition(
        code=getattr(promo, "code"),
        kind=getattr(promo, "kind", PromoCodeKind.MONTHLY_ACCESS),
        active=bool(getattr(promo, "active", True)),
        max_redemptions=int(getattr(promo, "max_redemptions", 1)),
        per_user_limit=int(getattr(promo, "per_user_limit", 1)),
        expires_at=getattr(promo, "expires_at", None),
        discount_percent=getattr(promo, "discount_percent", None),
        discount_amount=getattr(promo, "discount_amount", None),
        monthly_duration_months=int(getattr(promo, "monthly_duration_months", 1)),
    )


def _promo_store_promo_is_kind(promo, kind: PromoCodeKind) -> bool:
    return _promo_kind_matches(getattr(promo, "kind", None), kind)


def _promo_kind_matches(value, kind: PromoCodeKind) -> bool:
    return value == kind or str(value) == kind.value


def _admin_promo_metadata(action: str) -> dict[str, str]:
    return {"source": "telegram_admin_menu", "action": action}


def _promo_record_is_kind(record: PromoCodeRecord, kind: PromoCodeKind) -> bool:
    return str(record.kind) == kind.value or record.kind == kind


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
    from_user = getattr(callback, "from_user", None)
    user_id = getattr(from_user, "id", None)
    return bool(user_id is not None and int(user_id) in ADMIN_USER_IDS)


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
    return _entitlement_service().grant_test_access(chat_id, now=now)


def _revoke_test_access_for_chat(chat_id: int) -> Entitlement:
    return _entitlement_service().revoke_test_access(chat_id)


def _set_test_access_mode(chat_id: int, enabled: bool) -> tuple[bool, Entitlement]:
    return _entitlement_service().set_test_access_enabled(chat_id, enabled)


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


def _dry_run_generation_attempt(chat_id: int, ration_kind: RationKind) -> AttemptConsumption:
    if chat_id in TESTER_CHAT_IDS:
        return AttemptConsumption(True, ration_kind, "test_access")
    service = _entitlement_service()
    entitlement = service.peek_entitlement(chat_id)
    return service.dry_run_ration(
        chat_id,
        ration_kind,
        free_preview=_is_free_preview_mode(chat_id, entitlement),
    )


def _copy_entitlement_for_dry_run(entitlement: Entitlement) -> Entitlement:
    return replace(entitlement, processed_payment_charge_ids=list(entitlement.processed_payment_charge_ids))


def _free_preview_entitlement(entitlement: Entitlement) -> Entitlement:
    return replace(
        entitlement,
        subscription_period_start=None,
        subscription_period_end=None,
        monthly_one_day_remaining=0,
        monthly_weekly_pdf_remaining=0,
        extra_one_day_remaining=0,
        extra_weekly_pdf_remaining=0,
        test_access_enabled=False,
    )


def _consume_entitlement_for_ration(entitlement: Entitlement, ration_kind: RationKind) -> AttemptConsumption:
    if ration_kind == "weekly_pdf":
        return consume_weekly_pdf_attempt(entitlement)
    return consume_one_day_attempt(entitlement)

def _consume_generation_attempt(chat_id: int, ration_kind: RationKind) -> AttemptConsumption:
    if chat_id in TESTER_CHAT_IDS:
        return AttemptConsumption(True, ration_kind, "test_access")

    service = _entitlement_service()
    entitlement = service.peek_entitlement(chat_id)
    return service.consume_ration(
        chat_id,
        ration_kind,
        free_preview=_is_free_preview_mode(chat_id, entitlement),
    )


def _refund_generation_attempt(chat_id: int, consumption: AttemptConsumption) -> None:
    _entitlement_service().refund_generation_attempt(chat_id, consumption)


def _record_successful_generation_history(
    chat_id: int,
    consumption: AttemptConsumption,
    entries: Sequence[RecipeHistoryItem],
) -> None:
    if consumption.allowed:
        _remember_recipe_history_items_best_effort(
            chat_id,
            entries,
            ration_kind=consumption.ration_kind,
            context="after_successful_generation_delivery",
        )
        if consumption.ration_kind == "weekly_pdf":
            _cancel_sales_followup_after_access_grant(chat_id, reason="weekly_pdf_delivered")

def _complete_generation_attempt(chat_id: int, consumption: AttemptConsumption) -> None:
    del chat_id, consumption

def _entitlement_for_chat(chat_id: int) -> Entitlement:
    return _entitlement_service().get_entitlement(chat_id)


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
    try:
        entitlement = await _run_entitlement_db_call(_entitlement_for_chat, message.chat.id)  # type: ignore[assignment]
        status_text = await _format_entitlement_status_async(message.chat.id)
    except EntitlementStorageError:
        logger.exception("Failed to render limit paywall due to entitlement storage error")
        await _send_entitlement_storage_error(message)
        return
    has_active_subscription = (
        entitlement.is_subscription_active()
        and not _is_free_preview_mode(message.chat.id, entitlement)
    )
    lines = [
        "Лимит для этого типа рациона закончился.",
        "",
        status_text,
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
    if not _payments_enabled():
        return _payments_disabled_keyboard()
    return _keyboard_with_privacy_policy(
        [
            [InlineKeyboardButton(text=PAY_WITH_RU_CARD_TEXT, callback_data=CALLBACK_PAY_RU_CARD)],
            [InlineKeyboardButton(text=PAY_WITH_TELEGRAM_STARS_TEXT, callback_data=CALLBACK_PAY_TELEGRAM_STARS)],
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _paywall_keyboard(*, preferred: str) -> InlineKeyboardMarkup:
    if not _payments_enabled():
        return _payments_disabled_keyboard()

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
    return _keyboard_with_privacy_policy(
        [
            [extra_buttons[0]],
            [extra_buttons[1]],
            [extra_buttons[2]],
            [extra_buttons[3]],
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _trial_subscription_keyboard() -> InlineKeyboardMarkup:
    if not _payments_enabled():
        return _payments_disabled_keyboard()
    return _keyboard_with_privacy_policy(
        [
            [InlineKeyboardButton(text=SUBSCRIBE_CTA_TEXT, callback_data=CALLBACK_SUBSCRIBE)],
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _payments_disabled_keyboard() -> InlineKeyboardMarkup:
    return _keyboard_with_privacy_policy(
        [
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _after_plan_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    if chat_id is not None:
        entitlement = _entitlement_for_chat(chat_id)
        if _has_active_paid_access(chat_id, entitlement):
            return _subscriber_cabinet_keyboard(chat_id, entitlement=entitlement)
    return _keyboard_with_privacy_policy(
        [
            [InlineKeyboardButton(text=REPEAT_PLAN_TEXT, callback_data=CALLBACK_REPEAT)],
            [InlineKeyboardButton(text=NEW_PROFILE_TEXT, callback_data=CALLBACK_NEW)],
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _plan_choice_keyboard() -> InlineKeyboardMarkup:
    return _keyboard_with_privacy_policy(
        [
            [InlineKeyboardButton(text=ONE_DAY_PLAN_TEXT, callback_data=CALLBACK_ONE_DAY_PLAN)],
            [InlineKeyboardButton(text=WEEK_PLAN_PDF_TEXT, callback_data=CALLBACK_WEEK_PLAN_PDF)],
            [InlineKeyboardButton(text=CHANGE_PROFILE_TEXT, callback_data=CALLBACK_NEW)],
            [InlineKeyboardButton(text=PROMO_CODE_TEXT, callback_data=CALLBACK_PROMO_CODE)],
            [InlineKeyboardButton(text=SUPPORT_TEXT, callback_data=CALLBACK_SUPPORT)],
        ],
    )


def _question_keyboard_for_session(chat_id: int, session: QuestionnaireSession) -> InlineKeyboardMarkup | None:
    return _question_keyboard(session.current_question, chat_id=chat_id, step_index=session.step_index)


def _question_answer_callback_data(
    option_index: int,
    *,
    chat_id: int | None = None,
    step_index: int | None = None,
) -> str:
    token = QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID.get(chat_id) if chat_id is not None else None
    if token is not None and step_index is not None:
        return f"{CALLBACK_ANSWER_PREFIX}{token}:{step_index}:{option_index}"
    return f"{CALLBACK_ANSWER_PREFIX}{option_index}"


def _question_keyboard(
    question,
    *,
    selected_index: int | None = None,
    chat_id: int | None = None,
    step_index: int | None = None,
) -> InlineKeyboardMarkup | None:
    if not question:
        return None
    rows = [
        [
            InlineKeyboardButton(
                text=f"{SELECTED_ANSWER_PREFIX}{option}" if index == selected_index else option,
                callback_data=_question_answer_callback_data(index, chat_id=chat_id, step_index=step_index),
            )
        ]
        for index, option in enumerate(question.options)
    ]
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _mark_questionnaire_answer_selected(
    message: Message,
    question,
    option_index: int,
    *,
    chat_id: int,
    step_index: int,
) -> None:
    with suppress(TelegramAPIError, AttributeError, TypeError):
        await message.edit_reply_markup(
            reply_markup=_question_keyboard(
                question,
                selected_index=option_index,
                chat_id=chat_id,
                step_index=step_index,
            )
        )


async def _send_welcome_photo(message: Message) -> None:
    try:
        photo_path = validate_local_photo_path(WELCOME_PHOTO_PATH, label="welcome photo")
    except TelegramMediaValidationError as exc:
        logger.warning("Skipping welcome photo before Telegram send: %s", exc)
        return
    try:
        await message.answer_photo(photo=FSInputFile(photo_path))
    except TelegramAPIError:
        return


async def _send_meal_card(message: Message, meal: Meal) -> None:
    text = format_meal_card(meal, include_photo_credit=bool(meal.image_attribution))
    try:
        photo = _photo_input(meal)
    except TelegramMediaValidationError as exc:
        logger.warning("Skipping meal photo before Telegram send: %s", exc)
        photo = None
    if photo is None:
        await _send_text_chunks(message, text)
        return

    try:
        if len(text) <= TELEGRAM_CAPTION_MAX_CHARS:
            validate_telegram_caption(text, label="meal photo caption")
            await message.answer_photo(photo=photo, caption=text)
            return
        await message.answer_photo(photo=photo)
    except (TelegramAPIError, TelegramSendError):
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

    return FSInputFile(validate_local_photo_path(path, label="meal photo"))


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
