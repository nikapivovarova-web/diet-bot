from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from diet_bot.runtime_config import load_runtime_config, safe_summary
from diet_bot.sales_followup import (
    DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
    DEFAULT_SALES_FOLLOWUP_TRIGGER_KIND,
    SALES_FOLLOWUP_OPT_OUT_CALLBACK_DATA,
    SALES_FOLLOWUP_OPT_OUT_LABEL,
    SALES_FOLLOWUP_BUTTON_SET_KEY,
    SALES_FOLLOWUP_STEPS,
    SalesFollowupScheduleAdmissionStatus,
    build_sales_followup_job_drafts,
    build_sales_followup_trigger_idempotency_key,
    render_sales_followup_payload,
    schedule_sales_followup_after_free_trial_delivery,
)
from diet_bot.sales_followup_runtime import SalesFollowupJobRuntime


EXPECTED_STEP_KEYS = [
    "m01_two_hours",
    "m02_one_day",
    "m03_two_days",
    "m04_three_days_food20",
    "m05_one_week",
    "m06_two_weeks",
    "m07_one_month",
    "m08_six_weeks",
]

EXPECTED_OFFSETS = [
    timedelta(hours=2),
    timedelta(days=1),
    timedelta(days=2),
    timedelta(days=3),
    timedelta(days=7),
    timedelta(days=14),
    timedelta(days=30),
    timedelta(days=45),
]

EXPECTED_MESSAGE_TEXTS = [
    (
        "Как тебе рацион?\n\n"
        "Это был один день. Завтра снова вопрос что купить и что приготовить.\n\n"
        "С подпиской всё иначе. Получаешь красиво оформленный PDF с рационом на 7 дней. "
        "Один раз открыл список продуктов, один раз сходил в магазин и вся неделя расписана. "
        "Завтраки, обеды, ужины, рецепты, КБЖУ, витамины, минералы и таблица по каждому дню."
    ),
    (
        "Три причины почему люди откладывают подписку.\n\n"
        '"Рецепты наверное сложные." В анкете можно выбрать простые блюда до 30 минут. '
        "Паста, омлет, курица с гарниром, каши, салаты. Ничего экзотического.\n\n"
        '"Продукты дорогие или их не найти." Всё из обычного супермаркета. '
        "Крупы, овощи, мясо, рыба, яйца, творог, фрукты. Список продуктов на неделю "
        "в PDF помогает закупиться за один поход без лишнего.\n\n"
        '"Не смогу придерживаться." Если какое-то блюдо не понравилось, можно заменить '
        "на другое. Рацион подстраивается под тебя, а не наоборот."
    ),
    (
        "Вот что написала одна из пользователей после первой недели:\n\n"
        '"Я думала опять будет меню из гречки и грудки. А там нормальная еда которую '
        "реально готовишь дома. Самое удобное что список продуктов уже готов, "
        'пришла в магазин и взяла всё по списку."\n\n'
        "Именно в этом смысл PDF рациона на неделю. Не надо каждый день решать "
        "что купить и что приготовить. Один раз получил план и просто следуешь ему."
    ),
    (
        "Если рацион на один день понравился, неделя будет такой же. Только не надо "
        "каждый день заново думать что готовить.\n\n"
        "Для тех кто ещё думает, держи промокод на 20% скидку: FOOD20\n\n"
        "Действует 48 часов."
    ),
    (
        "Большинство людей которые следят за питанием недобирают магний, клетчатку "
        "и омега-3. Просто рацион однообразный и эти нутриенты в него не попадают.\n\n"
        "Многие пьют добавки не зная что именно им не хватает. В недельном рационе "
        "бот подбирает блюда под твои параметры и в таблице по каждому дню видно "
        "каких витаминов и минералов тебе достаточно из еды, а какие стоит получать "
        "дополнительно."
    ),
    (
        "Просто напомню что твои расчёты из анкеты сохранены.\n\n"
        "Рацион на неделю под твои параметры можно получить прямо сейчас."
    ),
    (
        "Три блюда которые легко готовить и которые хорошо покрывают дневную норму белка:\n\n"
        "Омлет с творогом и зеленью: 3 яйца, 100г творога. Белок около 35г, 15 минут.\n\n"
        "Запечённый лосось с рисом и овощами: 150г лосося, 80г риса, 100г овощей. "
        "Белок около 38г, 30 минут.\n\n"
        "Греческий йогурт с орехами и бананом: 200г йогурта, 20г орехов, 1 банан. "
        "Белок около 14г, 5 минут."
    ),
    (
        "За последнее время пользователи FoodBalance поделились результатами. "
        "Кто-то наконец разобрался с питанием под тренировки. Кто-то перестал "
        "каждый вечер думать что готовить. Кто-то просто стал есть вкуснее и осознаннее.\n\n"
        "Если ты ещё не попробовал неделю, твои расчёты сохранены. Рацион соберём за минуту."
    ),
]

EXPECTED_BUTTON_LABELS = [
    "Получить рацион на неделю",
    "Попробовать неделю",
    "Хочу свой план на неделю",
    "Оформить подписку",
    "Проверить свой рацион",
    "Получить рацион",
    "Собрать мой рацион",
    "Попробовать неделю",
]


def test_sales_followup_contract_preserves_exact_eight_step_schedule_and_payloads() -> None:
    triggered_at = datetime(2026, 5, 31, 12, 30, tzinfo=UTC)

    drafts = build_sales_followup_job_drafts(
        chat_id=4242,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        triggered_at=triggered_at,
    )

    assert [step.step_key for step in SALES_FOLLOWUP_STEPS] == EXPECTED_STEP_KEYS
    assert [step.offset for step in SALES_FOLLOWUP_STEPS] == EXPECTED_OFFSETS
    assert [draft.step_key for draft in drafts] == EXPECTED_STEP_KEYS
    assert [draft.step_index for draft in drafts] == list(range(1, 9))
    assert [draft.scheduled_at for draft in drafts] == [triggered_at + offset for offset in EXPECTED_OFFSETS]
    assert [draft.next_attempt_at for draft in drafts] == [triggered_at + offset for offset in EXPECTED_OFFSETS]
    assert [draft.button_set_key for draft in drafts] == [SALES_FOLLOWUP_BUTTON_SET_KEY] * 8
    assert [draft.payload["step_key"] for draft in drafts] == EXPECTED_STEP_KEYS
    assert [draft.payload["message_text"] for draft in drafts] == EXPECTED_MESSAGE_TEXTS
    assert [draft.payload["button_label"] for draft in drafts] == EXPECTED_BUTTON_LABELS


def test_sales_followup_button_targets_use_only_existing_safe_flows() -> None:
    drafts = build_sales_followup_job_drafts(
        chat_id=4242,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        triggered_at=datetime(2026, 5, 31, tzinfo=UTC),
    )
    payloads = {draft.step_key: draft.payload for draft in drafts}

    for step_key in (
        "m01_two_hours",
        "m02_one_day",
        "m03_two_days",
        "m05_one_week",
        "m06_two_weeks",
        "m07_one_month",
        "m08_six_weeks",
    ):
        assert payloads[step_key]["target_kind"] == "existing_weekly_pdf_flow"
        assert payloads[step_key]["target_callback_data"] == "diet:week_pdf"
        assert "CALLBACK_WEEK_PLAN_PDF" in payloads[step_key]["target_resolution_note"]

    food20_payload = payloads["m04_three_days_food20"]
    assert food20_payload["target_kind"] == "existing_subscription_flow"
    assert food20_payload["target_callback_data"] == "diet:subscribe_month"
    assert "CALLBACK_SUBSCRIBE" in food20_payload["target_resolution_note"]
    assert "FOOD20" not in food20_payload["target_callback_data"]
    assert food20_payload["target_kind"] != "existing_promo_flow"


def test_sales_followup_renderer_preserves_exact_payloads_and_adds_opt_out_button() -> None:
    drafts = build_sales_followup_job_drafts(
        chat_id=4242,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        triggered_at=datetime(2026, 5, 31, tzinfo=UTC),
    )

    rendered_messages = [render_sales_followup_payload(draft.payload) for draft in drafts]

    assert [rendered.sendable for rendered in rendered_messages] == [True] * 8
    assert [rendered.message_text for rendered in rendered_messages] == EXPECTED_MESSAGE_TEXTS
    for rendered, expected_button_label, draft in zip(
        rendered_messages,
        EXPECTED_BUTTON_LABELS,
        drafts,
        strict=True,
    ):
        assert rendered.keyboard == (
            ((expected_button_label, draft.payload["target_callback_data"]),),
            ((SALES_FOLLOWUP_OPT_OUT_LABEL, SALES_FOLLOWUP_OPT_OUT_CALLBACK_DATA),),
        )


def test_sales_followup_renderer_fails_closed_for_unresolved_or_missing_callback_target() -> None:
    draft = build_sales_followup_job_drafts(
        chat_id=4242,
        campaign_key=DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
        triggered_at=datetime(2026, 5, 31, tzinfo=UTC),
    )[0]

    unresolved = render_sales_followup_payload(
        {
            **draft.payload,
            "target_kind": "unresolved",
            "target_callback_data": None,
        }
    )
    missing_callback = render_sales_followup_payload({**draft.payload, "target_callback_data": None})

    assert unresolved.sendable is False
    assert unresolved.failure_reason == "unresolved_target"
    assert unresolved.keyboard == ()
    assert missing_callback.sendable is False
    assert missing_callback.failure_reason == "missing_target_callback_data"
    assert missing_callback.keyboard == ()


def test_sales_followup_runtime_flag_is_disabled_by_default_and_requires_postgres() -> None:
    default_config = load_runtime_config({"DIET_BOT_TOKEN": "token"})

    assert default_config.sales_followup_enabled is False
    assert safe_summary(default_config)["sales_followup_enabled"] is False

    enabled_without_postgres = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "token",
            "DIET_BOT_SALES_FOLLOWUP_ENABLED": "1",
        },
    )

    assert enabled_without_postgres.sales_followup_enabled is True
    assert any(
        "DIET_BOT_SALES_FOLLOWUP_ENABLED requires postgres storage backend." in issue
        for issue in enabled_without_postgres.validate_startup()
    )

    enabled_with_postgres = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "token",
            "DIET_BOT_SALES_FOLLOWUP_ENABLED": "1",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/diet_bot_test",
        },
    )

    assert not any("DIET_BOT_SALES_FOLLOWUP_ENABLED" in issue for issue in enabled_with_postgres.validate_startup())


def test_sales_followup_worker_flag_defaults_disabled_and_does_not_start_runtime() -> None:
    default_config = load_runtime_config({"DIET_BOT_TOKEN": "token"})

    assert default_config.sales_followup_worker_enabled is False
    assert safe_summary(default_config)["sales_followup_worker_enabled"] is False
    assert SalesFollowupJobRuntime.from_config(default_config) is None

    worker_without_feature = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "token",
            "DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED": "1",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/diet_bot_test",
        },
    )

    assert any(
        "DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED requires DIET_BOT_SALES_FOLLOWUP_ENABLED=1." in issue
        for issue in worker_without_feature.validate_startup()
    )

    worker_without_postgres = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "token",
            "DIET_BOT_SALES_FOLLOWUP_ENABLED": "1",
            "DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED": "1",
        },
    )

    assert any(
        "DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED requires postgres storage backend." in issue
        for issue in worker_without_postgres.validate_startup()
    )


@dataclass
class _FakeCreateChainResult:
    status: object
    chain: object
    jobs: tuple[object, ...]


class _FakeSalesFollowupStore:
    def __init__(
        self,
        *,
        create_status: str = "created",
        opted_out: bool = False,
    ) -> None:
        self.create_status = SimpleNamespace(value=create_status)
        self.preference = (
            SimpleNamespace(opted_out_at=datetime(2026, 5, 31, 8, 0, tzinfo=UTC))
            if opted_out
            else None
        )
        self.create_calls: list[dict[str, object]] = []

    def get_preference(self, chat_id: int):
        self.preference_chat_id = chat_id
        return self.preference

    def create_chain(self, **kwargs):
        self.create_calls.append(kwargs)
        return _FakeCreateChainResult(
            status=self.create_status,
            chain=SimpleNamespace(chain_id="chain-1"),
            jobs=tuple(SimpleNamespace(step_index=index) for index in range(1, 9)),
        )


def test_sales_followup_scheduler_admits_successful_free_trial_delivery_once() -> None:
    store = _FakeSalesFollowupStore()
    triggered_at = datetime(2026, 5, 31, 14, 30, tzinfo=UTC)
    trigger_key = build_sales_followup_trigger_idempotency_key(
        chat_id=4242,
        trigger_id="one-day-job-1",
    )

    result = schedule_sales_followup_after_free_trial_delivery(
        store=store,
        chat_id=4242,
        chat_is_private=True,
        feature_enabled=True,
        delivery_succeeded=True,
        source="free_trial",
        include_trial_subscription_cta=True,
        has_active_paid_access=False,
        has_weekly_pdf_access=False,
        trigger_idempotency_key=trigger_key,
        triggered_at=triggered_at,
        trigger_job_id=UUID("00000000-0000-0000-0000-000000000123"),
    )

    assert result.status == SalesFollowupScheduleAdmissionStatus.SCHEDULED
    assert len(result.jobs) == 8
    assert store.create_calls == [
        {
            "chat_id": 4242,
            "campaign_key": DEFAULT_SALES_FOLLOWUP_CAMPAIGN_KEY,
            "trigger_kind": DEFAULT_SALES_FOLLOWUP_TRIGGER_KIND,
            "trigger_idempotency_key": trigger_key,
            "triggered_at": triggered_at,
            "trigger_job_id": UUID("00000000-0000-0000-0000-000000000123"),
        }
    ]


def test_sales_followup_scheduler_treats_duplicate_trigger_as_admitted_without_new_jobs() -> None:
    store = _FakeSalesFollowupStore(create_status="existing_idempotency")

    result = schedule_sales_followup_after_free_trial_delivery(
        store=store,
        chat_id=4242,
        chat_is_private=True,
        feature_enabled=True,
        delivery_succeeded=True,
        source="free_trial",
        include_trial_subscription_cta=True,
        has_active_paid_access=False,
        has_weekly_pdf_access=False,
        trigger_idempotency_key="sales-followup:free_trial_v1:4242:job-1",
        triggered_at=datetime(2026, 5, 31, 14, 30, tzinfo=UTC),
    )

    assert result.status == SalesFollowupScheduleAdmissionStatus.EXISTING_IDEMPOTENCY
    assert len(store.create_calls) == 1


def test_sales_followup_trigger_idempotency_key_is_campaign_chat_and_delivery_specific() -> None:
    assert (
        build_sales_followup_trigger_idempotency_key(chat_id=101, trigger_id="job-1")
        == "sales-followup:free_trial_v1:101:job-1"
    )


def test_sales_followup_scheduler_skips_when_feature_disabled() -> None:
    store = _FakeSalesFollowupStore()

    result = schedule_sales_followup_after_free_trial_delivery(
        store=store,
        chat_id=4242,
        chat_is_private=True,
        feature_enabled=False,
        delivery_succeeded=True,
        source="free_trial",
        include_trial_subscription_cta=True,
        has_active_paid_access=False,
        has_weekly_pdf_access=False,
        trigger_idempotency_key="key",
        triggered_at=datetime(2026, 5, 31, 14, 30, tzinfo=UTC),
    )

    assert result.status == SalesFollowupScheduleAdmissionStatus.SKIPPED_FEATURE_DISABLED
    assert store.create_calls == []


def test_sales_followup_scheduler_skips_when_store_is_unavailable() -> None:
    result = schedule_sales_followup_after_free_trial_delivery(
        store=None,
        chat_id=4242,
        chat_is_private=True,
        feature_enabled=True,
        delivery_succeeded=True,
        source="free_trial",
        include_trial_subscription_cta=True,
        has_active_paid_access=False,
        has_weekly_pdf_access=False,
        trigger_idempotency_key="key",
        triggered_at=datetime(2026, 5, 31, 14, 30, tzinfo=UTC),
    )

    assert result.status == SalesFollowupScheduleAdmissionStatus.SKIPPED_STORE_UNAVAILABLE


def test_sales_followup_scheduler_skips_opted_out_chat() -> None:
    store = _FakeSalesFollowupStore(opted_out=True)

    result = schedule_sales_followup_after_free_trial_delivery(
        store=store,
        chat_id=4242,
        chat_is_private=True,
        feature_enabled=True,
        delivery_succeeded=True,
        source="free_trial",
        include_trial_subscription_cta=True,
        has_active_paid_access=False,
        has_weekly_pdf_access=False,
        trigger_idempotency_key="key",
        triggered_at=datetime(2026, 5, 31, 14, 30, tzinfo=UTC),
    )

    assert result.status == SalesFollowupScheduleAdmissionStatus.SKIPPED_OPTED_OUT
    assert store.create_calls == []


def test_sales_followup_scheduler_skip_matrix_blocks_non_eligible_triggers() -> None:
    base = {
        "store": _FakeSalesFollowupStore(),
        "chat_id": 4242,
        "chat_is_private": True,
        "feature_enabled": True,
        "delivery_succeeded": True,
        "source": "free_trial",
        "include_trial_subscription_cta": True,
        "has_active_paid_access": False,
        "has_weekly_pdf_access": False,
        "trigger_idempotency_key": "key",
        "triggered_at": datetime(2026, 5, 31, 14, 30, tzinfo=UTC),
    }
    cases = [
        ({"chat_is_private": False}, SalesFollowupScheduleAdmissionStatus.SKIPPED_NON_PRIVATE_CHAT),
        ({"delivery_succeeded": False}, SalesFollowupScheduleAdmissionStatus.SKIPPED_DELIVERY_NOT_SUCCESSFUL),
        ({"source": "monthly"}, SalesFollowupScheduleAdmissionStatus.SKIPPED_NOT_FREE_TRIAL),
        ({"source": "extra"}, SalesFollowupScheduleAdmissionStatus.SKIPPED_NOT_FREE_TRIAL),
        ({"source": "test_access"}, SalesFollowupScheduleAdmissionStatus.SKIPPED_NOT_FREE_TRIAL),
        ({"trigger_kind": "weekly_pdf_delivery"}, SalesFollowupScheduleAdmissionStatus.SKIPPED_WRONG_TRIGGER_KIND),
        ({"include_trial_subscription_cta": False}, SalesFollowupScheduleAdmissionStatus.SKIPPED_NO_TRIAL_CTA),
        ({"has_active_paid_access": True}, SalesFollowupScheduleAdmissionStatus.SKIPPED_ACTIVE_PAID_ACCESS),
        ({"has_weekly_pdf_access": True}, SalesFollowupScheduleAdmissionStatus.SKIPPED_WEEKLY_PDF_ACCESS),
    ]

    for overrides, expected in cases:
        store = _FakeSalesFollowupStore()
        result = schedule_sales_followup_after_free_trial_delivery(**{**base, "store": store, **overrides})

        assert result.status == expected
        assert store.create_calls == []
