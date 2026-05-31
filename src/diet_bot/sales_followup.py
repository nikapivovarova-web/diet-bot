from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal, Protocol
from uuid import UUID


DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY = "free_trial_v1"
DEFAULT_SALES_FOLLOWUP_TRIGGER_KIND = "free_one_day_delivery"
SALES_FOLLOWUP_CAMPAIGN_VERSION = "stage18b"
SALES_FOLLOWUP_BUTTON_SET_KEY = "sales_followup_default"
SALES_FOLLOWUP_OPT_OUT_LABEL = "Не напоминать"
SALES_FOLLOWUP_OPT_OUT_CALLBACK_DATA = "diet:sales_followup_opt_out"
TELEGRAM_CALLBACK_DATA_MAX_BYTES = 64

TARGET_EXISTING_SUBSCRIPTION_FLOW = "existing_subscription_flow"
TARGET_EXISTING_WEEKLY_PDF_FLOW = "existing_weekly_pdf_flow"
TARGET_EXISTING_PAYWALL_FLOW = "existing_paywall_flow"
TARGET_EXISTING_PROMO_FLOW = "existing_promo_flow"
TARGET_UNRESOLVED = "unresolved"

TargetKind = Literal[
    "existing_subscription_flow",
    "existing_weekly_pdf_flow",
    "existing_paywall_flow",
    "existing_promo_flow",
    "unresolved",
]


@dataclass(frozen=True)
class SalesFollowupTargetMapping:
    button_label: str
    target_kind: TargetKind
    target_callback_data: str | None
    target_resolution_note: str


@dataclass(frozen=True)
class SalesFollowupStep:
    step_key: str
    step_index: int
    offset: timedelta
    message_text: str
    target: SalesFollowupTargetMapping


@dataclass(frozen=True)
class SalesFollowupJobDraft:
    chat_id: int
    campaign_key: str
    step_key: str
    step_index: int
    scheduled_at: datetime
    next_attempt_at: datetime
    payload: dict[str, Any]
    button_set_key: str = SALES_FOLLOWUP_BUTTON_SET_KEY

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", dict(self.payload))


@dataclass(frozen=True)
class SalesFollowupRenderedMessage:
    message_text: str
    keyboard: tuple[tuple[tuple[str, str], ...], ...] = ()
    sendable: bool = True
    failure_reason: str | None = None


class SalesFollowupScheduleAdmissionStatus(str, Enum):
    SCHEDULED = "scheduled"
    EXISTING_IDEMPOTENCY = "existing_idempotency"
    ACTIVE_DUPLICATE = "active_duplicate"
    SKIPPED_FEATURE_DISABLED = "skipped_feature_disabled"
    SKIPPED_STORE_UNAVAILABLE = "skipped_store_unavailable"
    SKIPPED_NON_PRIVATE_CHAT = "skipped_non_private_chat"
    SKIPPED_DELIVERY_NOT_SUCCESSFUL = "skipped_delivery_not_successful"
    SKIPPED_WRONG_TRIGGER_KIND = "skipped_wrong_trigger_kind"
    SKIPPED_NOT_FREE_TRIAL = "skipped_not_free_trial"
    SKIPPED_NO_TRIAL_CTA = "skipped_no_trial_cta"
    SKIPPED_ACTIVE_PAID_ACCESS = "skipped_active_paid_access"
    SKIPPED_WEEKLY_PDF_ACCESS = "skipped_weekly_pdf_access"
    SKIPPED_OPTED_OUT = "skipped_opted_out"


@dataclass(frozen=True)
class SalesFollowupScheduleAdmission:
    status: SalesFollowupScheduleAdmissionStatus
    chain: object | None = None
    jobs: tuple[object, ...] = ()


class _SalesFollowupPreferenceStore(Protocol):
    def get_preference(self, chat_id: int) -> object | None: ...

    def create_chain(
        self,
        *,
        chat_id: int,
        campaign_key: str,
        trigger_kind: str,
        trigger_idempotency_key: str,
        triggered_at: datetime,
        trigger_job_id: UUID | str | None = None,
    ) -> object: ...


_WEEKLY_PDF_TARGET_NOTE = (
    "Mapped read-only to existing CALLBACK_WEEK_PLAN_PDF (diet:week_pdf) in telegram_app.py; "
    "Stage 18B adds no callback handler and does not send Telegram messages."
)

_SUBSCRIPTION_TARGET_NOTE = (
    "Mapped read-only to existing CALLBACK_SUBSCRIBE (diet:subscribe_month) in telegram_app.py; "
    "FOOD20 remains message text only with no promo seed, redemption, or payment discount wiring in Stage 18B."
)

_SAFE_TARGET_CALLBACK_DATA_BY_KIND = {
    TARGET_EXISTING_WEEKLY_PDF_FLOW: "diet:week_pdf",
    TARGET_EXISTING_SUBSCRIPTION_FLOW: "diet:subscribe_month",
}

_WEEKLY_PDF_TARGETS = {
    "Получить рацион на неделю": SalesFollowupTargetMapping(
        button_label="Получить рацион на неделю",
        target_kind=TARGET_EXISTING_WEEKLY_PDF_FLOW,
        target_callback_data="diet:week_pdf",
        target_resolution_note=_WEEKLY_PDF_TARGET_NOTE,
    ),
    "Попробовать неделю": SalesFollowupTargetMapping(
        button_label="Попробовать неделю",
        target_kind=TARGET_EXISTING_WEEKLY_PDF_FLOW,
        target_callback_data="diet:week_pdf",
        target_resolution_note=_WEEKLY_PDF_TARGET_NOTE,
    ),
    "Хочу свой план на неделю": SalesFollowupTargetMapping(
        button_label="Хочу свой план на неделю",
        target_kind=TARGET_EXISTING_WEEKLY_PDF_FLOW,
        target_callback_data="diet:week_pdf",
        target_resolution_note=_WEEKLY_PDF_TARGET_NOTE,
    ),
    "Проверить свой рацион": SalesFollowupTargetMapping(
        button_label="Проверить свой рацион",
        target_kind=TARGET_EXISTING_WEEKLY_PDF_FLOW,
        target_callback_data="diet:week_pdf",
        target_resolution_note=_WEEKLY_PDF_TARGET_NOTE,
    ),
    "Получить рацион": SalesFollowupTargetMapping(
        button_label="Получить рацион",
        target_kind=TARGET_EXISTING_WEEKLY_PDF_FLOW,
        target_callback_data="diet:week_pdf",
        target_resolution_note=_WEEKLY_PDF_TARGET_NOTE,
    ),
    "Собрать мой рацион": SalesFollowupTargetMapping(
        button_label="Собрать мой рацион",
        target_kind=TARGET_EXISTING_WEEKLY_PDF_FLOW,
        target_callback_data="diet:week_pdf",
        target_resolution_note=_WEEKLY_PDF_TARGET_NOTE,
    ),
}


SALES_FOLLOWUP_STEPS = (
    SalesFollowupStep(
        step_key="m01_two_hours",
        step_index=1,
        offset=timedelta(hours=2),
        message_text=(
            "Как тебе рацион?\n\n"
            "Это был один день. Завтра снова вопрос что купить и что приготовить.\n\n"
            "С подпиской всё иначе. Получаешь красиво оформленный PDF с рационом на 7 дней. "
            "Один раз открыл список продуктов, один раз сходил в магазин и вся неделя расписана. "
            "Завтраки, обеды, ужины, рецепты, КБЖУ, витамины, минералы и таблица по каждому дню."
        ),
        target=_WEEKLY_PDF_TARGETS["Получить рацион на неделю"],
    ),
    SalesFollowupStep(
        step_key="m02_one_day",
        step_index=2,
        offset=timedelta(days=1),
        message_text=(
            "Три причины почему люди откладывают подписку.\n\n"
            '"Рецепты наверное сложные." В анкете можно выбрать простые блюда до 30 минут. '
            "Паста, омлет, курица с гарниром, каши, салаты. Ничего экзотического.\n\n"
            '"Продукты дорогие или их не найти." Всё из обычного супермаркета. '
            "Крупы, овощи, мясо, рыба, яйца, творог, фрукты. Список продуктов на неделю "
            "в PDF помогает закупиться за один поход без лишнего.\n\n"
            '"Не смогу придерживаться." Если какое-то блюдо не понравилось, можно заменить '
            "на другое. Рацион подстраивается под тебя, а не наоборот."
        ),
        target=_WEEKLY_PDF_TARGETS["Попробовать неделю"],
    ),
    SalesFollowupStep(
        step_key="m03_two_days",
        step_index=3,
        offset=timedelta(days=2),
        message_text=(
            "Вот что написала одна из пользователей после первой недели:\n\n"
            '"Я думала опять будет меню из гречки и грудки. А там нормальная еда которую '
            "реально готовишь дома. Самое удобное что список продуктов уже готов, "
            'пришла в магазин и взяла всё по списку."\n\n'
            "Именно в этом смысл PDF рациона на неделю. Не надо каждый день решать "
            "что купить и что приготовить. Один раз получил план и просто следуешь ему."
        ),
        target=_WEEKLY_PDF_TARGETS["Хочу свой план на неделю"],
    ),
    SalesFollowupStep(
        step_key="m04_three_days_food20",
        step_index=4,
        offset=timedelta(days=3),
        message_text=(
            "Если рацион на один день понравился, неделя будет такой же. Только не надо "
            "каждый день заново думать что готовить.\n\n"
            "Для тех кто ещё думает, держи промокод на 20% скидку: FOOD20\n\n"
            "Действует 48 часов."
        ),
        target=SalesFollowupTargetMapping(
            button_label="Оформить подписку",
            target_kind=TARGET_EXISTING_SUBSCRIPTION_FLOW,
            target_callback_data="diet:subscribe_month",
            target_resolution_note=_SUBSCRIPTION_TARGET_NOTE,
        ),
    ),
    SalesFollowupStep(
        step_key="m05_one_week",
        step_index=5,
        offset=timedelta(days=7),
        message_text=(
            "Большинство людей которые следят за питанием недобирают магний, клетчатку "
            "и омега-3. Просто рацион однообразный и эти нутриенты в него не попадают.\n\n"
            "Многие пьют добавки не зная что именно им не хватает. В недельном рационе "
            "бот подбирает блюда под твои параметры и в таблице по каждому дню видно "
            "каких витаминов и минералов тебе достаточно из еды, а какие стоит получать "
            "дополнительно."
        ),
        target=_WEEKLY_PDF_TARGETS["Проверить свой рацион"],
    ),
    SalesFollowupStep(
        step_key="m06_two_weeks",
        step_index=6,
        offset=timedelta(days=14),
        message_text=(
            "Просто напомню что твои расчёты из анкеты сохранены.\n\n"
            "Рацион на неделю под твои параметры можно получить прямо сейчас."
        ),
        target=_WEEKLY_PDF_TARGETS["Получить рацион"],
    ),
    SalesFollowupStep(
        step_key="m07_one_month",
        step_index=7,
        offset=timedelta(days=30),
        message_text=(
            "Три блюда которые легко готовить и которые хорошо покрывают дневную норму белка:\n\n"
            "Омлет с творогом и зеленью: 3 яйца, 100г творога. Белок около 35г, 15 минут.\n\n"
            "Запечённый лосось с рисом и овощами: 150г лосося, 80г риса, 100г овощей. "
            "Белок около 38г, 30 минут.\n\n"
            "Греческий йогурт с орехами и бананом: 200г йогурта, 20г орехов, 1 банан. "
            "Белок около 14г, 5 минут."
        ),
        target=_WEEKLY_PDF_TARGETS["Собрать мой рацион"],
    ),
    SalesFollowupStep(
        step_key="m08_six_weeks",
        step_index=8,
        offset=timedelta(days=45),
        message_text=(
            "За последнее время пользователи FoodBalance поделились результатами. "
            "Кто-то наконец разобрался с питанием под тренировки. Кто-то перестал "
            "каждый вечер думать что готовить. Кто-то просто стал есть вкуснее и осознаннее.\n\n"
            "Если ты ещё не попробовал неделю, твои расчёты сохранены. Рацион соберём за минуту."
        ),
        target=_WEEKLY_PDF_TARGETS["Попробовать неделю"],
    ),
)


def build_sales_followup_job_drafts(
    *,
    chat_id: int,
    campaign_key: str,
    triggered_at: datetime,
) -> tuple[SalesFollowupJobDraft, ...]:
    base_time = _normalize_datetime(triggered_at)
    normalized_campaign_key = _required_text(campaign_key, "campaign_key")
    drafts: list[SalesFollowupJobDraft] = []
    for step in SALES_FOLLOWUP_STEPS:
        scheduled_at = base_time + step.offset
        target = step.target
        drafts.append(
            SalesFollowupJobDraft(
                chat_id=int(chat_id),
                campaign_key=normalized_campaign_key,
                step_key=step.step_key,
                step_index=step.step_index,
                scheduled_at=scheduled_at,
                next_attempt_at=scheduled_at,
                payload={
                    "step_key": step.step_key,
                    "message_text": step.message_text,
                    "button_label": target.button_label,
                    "target_kind": target.target_kind,
                    "target_callback_data": target.target_callback_data,
                    "target_resolution_note": target.target_resolution_note,
                },
            ),
        )
    return tuple(drafts)


def render_sales_followup_payload(payload: Mapping[str, Any]) -> SalesFollowupRenderedMessage:
    raw_payload = dict(payload or {})
    message_text = raw_payload.get("message_text")
    if not isinstance(message_text, str) or not message_text.strip():
        return _not_sendable("missing_message_text")

    button_label = raw_payload.get("button_label")
    if not isinstance(button_label, str) or not button_label.strip():
        return _not_sendable("missing_button_label", message_text=message_text)

    target_kind = str(raw_payload.get("target_kind") or "").strip()
    if target_kind == TARGET_UNRESOLVED:
        return _not_sendable("unresolved_target", message_text=message_text)

    expected_callback_data = _SAFE_TARGET_CALLBACK_DATA_BY_KIND.get(target_kind)
    if expected_callback_data is None:
        return _not_sendable("unsupported_target_kind", message_text=message_text)

    target_callback_data = _optional_text(raw_payload.get("target_callback_data"))
    if target_callback_data is None:
        return _not_sendable("missing_target_callback_data", message_text=message_text)
    if target_callback_data != expected_callback_data:
        return _not_sendable("unsafe_target_callback_data", message_text=message_text)
    if not _telegram_callback_data_fits(target_callback_data):
        return _not_sendable("target_callback_data_too_long", message_text=message_text)
    if not _telegram_callback_data_fits(SALES_FOLLOWUP_OPT_OUT_CALLBACK_DATA):
        return _not_sendable("opt_out_callback_data_too_long", message_text=message_text)

    return SalesFollowupRenderedMessage(
        message_text=message_text,
        keyboard=(
            ((button_label, target_callback_data),),
            ((SALES_FOLLOWUP_OPT_OUT_LABEL, SALES_FOLLOWUP_OPT_OUT_CALLBACK_DATA),),
        ),
        sendable=True,
    )


def build_sales_followup_trigger_idempotency_key(
    *,
    chat_id: int,
    trigger_id: UUID | str,
    campaign_key: str = DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
) -> str:
    normalized_campaign_key = _required_text(campaign_key, "campaign_key")
    normalized_trigger_id = _required_text(str(trigger_id), "trigger_id")
    return f"sales-followup:{normalized_campaign_key}:{int(chat_id)}:{normalized_trigger_id}"


def schedule_sales_followup_after_free_trial_delivery(
    *,
    store: _SalesFollowupPreferenceStore | None,
    chat_id: int,
    chat_is_private: bool,
    feature_enabled: bool,
    delivery_succeeded: bool,
    source: str | None,
    include_trial_subscription_cta: bool,
    has_active_paid_access: bool,
    has_weekly_pdf_access: bool,
    trigger_idempotency_key: str,
    triggered_at: datetime,
    trigger_job_id: UUID | str | None = None,
    campaign_key: str = DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
    trigger_kind: str = DEFAULT_SALES_FOLLOWUP_TRIGGER_KIND,
) -> SalesFollowupScheduleAdmission:
    if not feature_enabled:
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_FEATURE_DISABLED)
    if store is None:
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_STORE_UNAVAILABLE)
    if not chat_is_private:
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_NON_PRIVATE_CHAT)
    if not delivery_succeeded:
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_DELIVERY_NOT_SUCCESSFUL)
    if trigger_kind != DEFAULT_SALES_FOLLOWUP_TRIGGER_KIND:
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_WRONG_TRIGGER_KIND)
    if str(source or "").strip() != "free_trial":
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_NOT_FREE_TRIAL)
    if not include_trial_subscription_cta:
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_NO_TRIAL_CTA)
    if has_active_paid_access:
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_ACTIVE_PAID_ACCESS)
    if has_weekly_pdf_access:
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_WEEKLY_PDF_ACCESS)

    preference = store.get_preference(int(chat_id))
    if getattr(preference, "opted_out_at", None) is not None:
        return SalesFollowupScheduleAdmission(SalesFollowupScheduleAdmissionStatus.SKIPPED_OPTED_OUT)

    result = store.create_chain(
        chat_id=int(chat_id),
        campaign_key=_required_text(campaign_key, "campaign_key"),
        trigger_kind=DEFAULT_SALES_FOLLOWUP_TRIGGER_KIND,
        trigger_idempotency_key=_required_text(trigger_idempotency_key, "trigger_idempotency_key"),
        triggered_at=_normalize_datetime(triggered_at),
        trigger_job_id=trigger_job_id,
    )
    status = _create_chain_status_value(getattr(result, "status", None))
    if status == "created":
        admission_status = SalesFollowupScheduleAdmissionStatus.SCHEDULED
    elif status == "existing_idempotency":
        admission_status = SalesFollowupScheduleAdmissionStatus.EXISTING_IDEMPOTENCY
    elif status == "active_duplicate":
        admission_status = SalesFollowupScheduleAdmissionStatus.ACTIVE_DUPLICATE
    else:
        raise RuntimeError(f"Unexpected sales follow-up create_chain status: {status}")
    return SalesFollowupScheduleAdmission(
        admission_status,
        getattr(result, "chain", None),
        tuple(getattr(result, "jobs", ())),
    )


def _create_chain_status_value(status: object) -> str:
    return str(getattr(status, "value", status))


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_text(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _telegram_callback_data_fits(value: str) -> bool:
    size = len(value.encode("utf-8"))
    return 1 <= size <= TELEGRAM_CALLBACK_DATA_MAX_BYTES


def _not_sendable(
    failure_reason: str,
    *,
    message_text: str = "",
) -> SalesFollowupRenderedMessage:
    return SalesFollowupRenderedMessage(
        message_text=message_text,
        keyboard=(),
        sendable=False,
        failure_reason=failure_reason,
    )
