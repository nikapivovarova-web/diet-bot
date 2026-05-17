from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.domain import (
    ActivityLevel,
    CookingTimePreference,
    Food,
    Goal,
    Meal,
    MealPlan,
    NutrientVector,
    NutritionTargets,
    SafetyResult,
    Sex,
    UserProfile,
)
from diet_bot.subscriptions import Entitlement


@pytest.fixture(autouse=True)
def isolated_telegram_state(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "WEEK_PDF_STATUS_UPDATE_SECONDS", 60.0)
    yield
    telegram_app.PLAN_COUNT_BY_CHAT_ID.clear()
    telegram_app.PLAN_SEED_OFFSET_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID.clear()


@pytest.mark.anyio
async def test_weekly_pdf_limit_is_consumed_after_successful_delivery(monkeypatch) -> None:
    chat_id = 101_001
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    plans = tuple(sample_meal_plan() for _ in range(7))

    monkeypatch.setattr(
        telegram_app,
        "_build_week_plans_with_recent_fallback",
        lambda *_args: _week_plan_build_result(plans),
    )
    monkeypatch.setattr(telegram_app, "_build_week_pdf_payload", lambda *_args: (b"%PDF-1.4\n%test", "week.pdf"))

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    assert sent
    assert entitlement.monthly_weekly_pdf_remaining == 0
    assert len(message.documents) == 1


@pytest.mark.anyio
async def test_weekly_pdf_render_failure_does_not_consume_limit_or_send_text_fallback(monkeypatch) -> None:
    chat_id = 101_002
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    plans = tuple(sample_meal_plan() for _ in range(7))

    monkeypatch.setattr(
        telegram_app,
        "_build_week_plans_with_recent_fallback",
        lambda *_args: _week_plan_build_result(plans),
    )
    monkeypatch.setattr(
        telegram_app,
        "_build_week_pdf_payload",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("pdf failed")),
    )

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    sent_text = "\n".join(text for text, _ in message.texts)
    assert not sent
    assert entitlement.monthly_weekly_pdf_remaining == 1
    assert message.documents == []
    assert message.edits
    assert "PDF" in message.edits[-1][0]
    assert "Smoke meal" not in sent_text
    assert "Smoke food" not in sent_text
    assert "PDF на неделю: 0" not in sent_text


@pytest.mark.anyio
async def test_weekly_pdf_size_guard_does_not_consume_limit_or_send_text_fallback(monkeypatch) -> None:
    chat_id = 101_003
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    plans = tuple(sample_meal_plan() for _ in range(7))

    monkeypatch.setattr(
        telegram_app,
        "_build_week_plans_with_recent_fallback",
        lambda *_args: _week_plan_build_result(plans),
    )
    monkeypatch.setattr(telegram_app, "_build_week_pdf_payload", lambda *_args: (b"%PDF-1.4\n" + b"x" * 32, "large.pdf"))
    monkeypatch.setattr(telegram_app, "TELEGRAM_DOCUMENT_MAX_BYTES", 16, raising=False)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    sent_text = "\n".join(text for text, _ in message.texts)
    assert not sent
    assert entitlement.monthly_weekly_pdf_remaining == 1
    assert message.documents == []
    assert message.edits
    assert "PDF" in message.edits[-1][0]
    assert "Smoke meal" not in sent_text
    assert "Smoke food" not in sent_text
    assert "PDF на неделю: 0" not in sent_text


@pytest.mark.anyio
async def test_weekly_pdf_payload_generation_is_capped_by_semaphore(monkeypatch) -> None:
    plans = tuple(sample_meal_plan() for _ in range(7))
    max_active = 0
    active = 0
    lock = threading.Lock()

    async def fake_animate_week_pdf_status(*_args, **_kwargs) -> None:
        return None

    def slow_build_week_pdf_payload(*_args):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return b"%PDF-1.4\n%test", "week.pdf"
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(telegram_app, "_WEEKLY_PDF_SEMAPHORE", asyncio.Semaphore(2))
    monkeypatch.setattr(telegram_app, "_animate_week_pdf_status", fake_animate_week_pdf_status)
    monkeypatch.setattr(
        telegram_app,
        "_build_week_plans_with_recent_fallback",
        lambda *_args: _week_plan_build_result(plans),
    )
    monkeypatch.setattr(telegram_app, "_build_week_pdf_payload", slow_build_week_pdf_payload)

    results = await asyncio.gather(
        *(
            telegram_app._send_week_plan(FakeMessage(102_000 + index), profile_with())
            for index in range(6)
        )
    )

    assert results == [True] * 6
    assert max_active <= 2


@pytest.mark.anyio
async def test_busy_weekly_pdf_slots_fail_fast_without_consuming_limit(monkeypatch) -> None:
    chat_id = 101_004
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    busy_semaphore = asyncio.Semaphore(1)
    await busy_semaphore.acquire()

    monkeypatch.setattr(telegram_app, "_WEEKLY_PDF_SEMAPHORE", busy_semaphore)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    assert not sent
    assert entitlement.monthly_weekly_pdf_remaining == 1
    assert message.documents == []
    assert [text for text, _ in message.texts] == [telegram_app.WEEK_PDF_BUSY_TEXT]


class FakeMessage:
    def __init__(self, chat_id: int) -> None:
        self.chat = SimpleNamespace(id=chat_id, type="private")
        self.from_user = SimpleNamespace(id=chat_id, username=None, first_name=None, last_name=None, full_name="")
        self.bot = FakeBot()
        self.photos = []
        self.texts = []
        self.documents = []
        self.edits = []

    async def answer(self, text, reply_markup=None):
        self.texts.append((text, reply_markup))
        return FakeSentMessage(self)

    async def answer_photo(self, **kwargs) -> None:
        self.photos.append(kwargs)

    async def answer_document(self, **kwargs) -> None:
        self.documents.append(kwargs)


class FakeSentMessage:
    def __init__(self, source: FakeMessage) -> None:
        self.source = source

    async def edit_text(self, text, **kwargs) -> None:
        self.source.edits.append((text, kwargs))


class FakeBot:
    def __init__(self) -> None:
        self.chat_actions = []

    async def send_chat_action(self, **kwargs) -> None:
        self.chat_actions.append(kwargs)


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


def _save_active_subscription(chat_id: int, *, weekly_pdf_remaining: int) -> Entitlement:
    entitlement = Entitlement()
    telegram_app.apply_subscription_payment(
        entitlement,
        f"charge-{chat_id}",
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )
    entitlement.monthly_weekly_pdf_remaining = weekly_pdf_remaining
    telegram_app.save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, {chat_id: entitlement})
    return entitlement


def sample_meal_plan() -> MealPlan:
    meals = tuple(sample_meal() for _ in range(4))
    targets = NutritionTargets(
        bmi=22.0,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=meals[0].nutrients,
        calorie_bounds=(1400, 2200),
        macro_bounds={},
    )
    return MealPlan(meals, targets, SafetyResult(can_generate_plan=True))


def _week_plan_build_result(plans: tuple[MealPlan, ...]) -> telegram_app._WeekPlanBuildResult:
    return telegram_app._WeekPlanBuildResult(plans=plans, avoidance_phase="full_recent")


def sample_meal() -> Meal:
    food = Food(
        id="smoke_food",
        name="Smoke food",
        category="test",
        nutrients_per_100g=NutrientVector(
            {
                "kcal": 120,
                "protein_g": 8,
                "fat_g": 4,
                "carbs_g": 12,
                "fiber_g": 2,
            },
        ),
    )
    return Meal(
        name="Smoke meal",
        portions=(food.portion(150),),
        recipe="Cook and serve.",
    )
