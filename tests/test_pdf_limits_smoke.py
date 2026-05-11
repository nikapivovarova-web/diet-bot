from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest

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
    monkeypatch.setattr(telegram_app, "_postgres_store", lambda: None)
    telegram_app.TELEGRAM_RATE_LIMITER.reset()
    telegram_app.INCOMING_THROTTLE.reset()
    monkeypatch.setattr(telegram_app.TELEGRAM_RATE_LIMITER, "per_chat_interval", 0.0)
    monkeypatch.setattr(telegram_app.TELEGRAM_RATE_LIMITER, "global_interval", 0.0)
    monkeypatch.setattr(telegram_app, "CALLBACK_THROTTLE_SECONDS", 0.0)
    yield
    telegram_app.TELEGRAM_RATE_LIMITER.reset()
    telegram_app.INCOMING_THROTTLE.reset()
    telegram_app.GENERATION_LOCKS_BY_CHAT_ID.clear()
    telegram_app.PLAN_COUNT_BY_CHAT_ID.clear()
    telegram_app.PLAN_SEED_OFFSET_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID.clear()


@pytest.mark.anyio
async def test_weekly_pdf_limit_is_consumed_after_successful_delivery(monkeypatch) -> None:
    chat_id = 101_001
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    calls = []

    async def fake_send_week_plan(message, profile, *, status_text=None, consumption=None):
        calls.append((message.chat.id, status_text))
        return True

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await telegram_app._send_week_plan_with_access(FakeMessage(chat_id), profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    assert sent
    assert calls == [(chat_id, telegram_app._format_entitlement_status(chat_id))]
    assert entitlement.monthly_weekly_pdf_remaining == 0


@pytest.mark.anyio
async def test_weekly_pdf_limit_is_refunded_when_generation_raises(monkeypatch) -> None:
    chat_id = 101_002
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)

    async def failing_send_week_plan(message, profile, *, status_text=None, consumption=None):
        raise RuntimeError("generation failed")

    monkeypatch.setattr(telegram_app, "_send_week_plan", failing_send_week_plan)

    with pytest.raises(RuntimeError, match="generation failed"):
        await telegram_app._send_week_plan_with_access(FakeMessage(chat_id), profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    assert entitlement.monthly_weekly_pdf_remaining == 1


@pytest.mark.anyio
async def test_weekly_pdf_limit_is_completed_when_pdf_renderer_falls_back_to_text(monkeypatch) -> None:
    chat_id = 101_006
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    plans = tuple(sample_meal_plan() for _ in range(7))

    monkeypatch.setattr(telegram_app, "_build_week_plans", lambda *_args: plans)
    monkeypatch.setattr(telegram_app, "build_week_plan_pdf", lambda *_args: (_ for _ in ()).throw(RuntimeError("pdf failed")))

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    sent_text = "\n".join(text for text, _ in message.texts)
    assert sent
    assert entitlement.monthly_weekly_pdf_remaining == 0
    assert message.documents == []
    assert "Smoke meal" in sent_text


@pytest.mark.anyio
async def test_one_day_invalid_plan_is_not_sent_and_limit_is_refunded(monkeypatch) -> None:
    chat_id = 101_007
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, one_day_remaining=1, weekly_pdf_remaining=0)

    monkeypatch.setattr(telegram_app, "build_one_day_plan", lambda *_args, **_kwargs: invalid_meal_plan())

    sent = await telegram_app._send_one_day_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    sent_text = "\n".join(text for text, _ in message.texts)
    assert not sent
    assert entitlement.monthly_one_day_remaining == 1
    assert message.photos == []
    assert message.documents == []
    assert "Invalid meal" not in sent_text


@pytest.mark.anyio
async def test_weekly_pdf_invalid_plan_is_not_sent_and_limit_is_refunded(monkeypatch) -> None:
    chat_id = 101_008
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    plans = tuple(invalid_meal_plan() for _ in range(7))

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("PDF renderer must not be called for invalid plans")

    monkeypatch.setattr(telegram_app, "_build_week_plans", lambda *_args: plans)
    monkeypatch.setattr(telegram_app, "build_week_plan_pdf", fail_if_called)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    sent_text = "\n".join(text for text, _ in message.texts)
    assert not sent
    assert entitlement.monthly_weekly_pdf_remaining == 1
    assert message.documents == []
    assert "Invalid meal" not in sent_text


@pytest.mark.anyio
async def test_weekly_pdf_too_large_uses_text_fallback_and_completes(monkeypatch) -> None:
    chat_id = 101_009
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    plans = tuple(sample_meal_plan() for _ in range(7))

    monkeypatch.setattr(telegram_app, "_build_week_plans", lambda *_args: plans)
    monkeypatch.setattr(telegram_app, "_build_week_pdf_payload", lambda *_args: (b"%PDF-1.4\n" + b"x" * 32, "large.pdf"))
    monkeypatch.setattr(telegram_app, "TELEGRAM_DOCUMENT_MAX_BYTES", 16)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    sent_text = "\n".join(text for text, _ in message.texts)
    assert sent
    assert entitlement.monthly_weekly_pdf_remaining == 0
    assert message.documents == []
    assert "Smoke meal" in sent_text


def test_week_pdf_payload_is_non_empty_pdf() -> None:
    pdf_data, filename = telegram_app._build_week_pdf_payload(
        (sample_meal_plan(),),
        (date(2026, 5, 10),),
    )

    assert filename.endswith(".pdf")
    assert pdf_data.startswith(b"%PDF")
    assert len(pdf_data) > 1_000


@pytest.mark.anyio
async def test_weekly_pdf_double_click_does_not_start_parallel_generation(monkeypatch) -> None:
    chat_id = 101_003
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def slow_locked_send(message, profile):
        calls.append(message.chat.id)
        started.set()
        await release.wait()
        return True

    monkeypatch.setattr(telegram_app, "_send_week_plan_with_access_locked", slow_locked_send)

    first_task = asyncio.create_task(
        telegram_app._send_week_plan_with_access(FakeMessage(chat_id), profile_with()),
    )
    await started.wait()
    second_message = FakeMessage(chat_id)
    second_result = await telegram_app._send_week_plan_with_access(second_message, profile_with())
    release.set()
    first_result = await first_task

    assert first_result
    assert not second_result
    assert calls == [chat_id]
    assert second_message.texts == [(telegram_app.GENERATION_ALREADY_RUNNING_TEXT, None)]


@pytest.mark.anyio
async def test_meal_photo_failure_falls_back_to_text(monkeypatch) -> None:
    message = FakeMessage(101_004)
    meal = sample_meal(image_url="https://example.test/meal.jpg")

    async def failing_photo(_message, **_kwargs):
        raise TelegramBadRequest(SimpleNamespace(), "photo failed")

    monkeypatch.setattr(telegram_app, "safe_answer_photo", failing_photo)

    await telegram_app._send_meal_card(message, meal)

    assert message.photos == []
    assert len(message.texts) == 1
    assert "Smoke meal" in message.texts[0][0]
    assert "Cook and serve" in message.texts[0][0]


@pytest.mark.anyio
async def test_week_plan_pdf_failure_sends_text_ration_and_reports_pdf_not_delivered(monkeypatch) -> None:
    chat_id = 101_005
    message = FakeMessage(chat_id)
    plans = tuple(sample_meal_plan() for _ in range(7))

    monkeypatch.setattr(telegram_app, "_build_week_plans", lambda *_args: plans)
    monkeypatch.setattr(telegram_app, "build_week_plan_pdf", lambda *_args: (_ for _ in ()).throw(RuntimeError("pdf failed")))

    sent = await telegram_app._send_week_plan(message, profile_with(), status_text="limits: smoke")

    sent_text = "\n".join(text for text, _ in message.texts)
    assert sent
    assert message.documents == []
    assert "PDF" in sent_text
    assert "Smoke meal" in sent_text
    assert "limits: smoke" not in sent_text


class FakeMessage:
    def __init__(self, chat_id: int = 12345) -> None:
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


def _save_active_subscription(
    chat_id: int,
    *,
    weekly_pdf_remaining: int,
    one_day_remaining: int = 0,
) -> Entitlement:
    entitlement = Entitlement()
    telegram_app.apply_subscription_payment(
        entitlement,
        f"charge-{chat_id}",
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )
    entitlement.monthly_one_day_remaining = one_day_remaining
    entitlement.monthly_weekly_pdf_remaining = weekly_pdf_remaining
    telegram_app.save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, {chat_id: entitlement})
    return entitlement


def sample_meal_plan() -> MealPlan:
    meal = sample_meal()
    targets = NutritionTargets(
        bmi=22.0,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=meal.nutrients,
        calorie_bounds=(1400, 2200),
        macro_bounds={},
    )
    return MealPlan((meal,), targets, SafetyResult(can_generate_plan=True))


def invalid_meal_plan() -> MealPlan:
    invalid_food = Food(
        id="invalid_food",
        name="Invalid food",
        category="test",
        nutrients_per_100g=NutrientVector(
            {
                "energy_kcal": 120,
                "protein_g": 8,
                "fat_g": 4,
                "carbohydrate_g": 12,
                "fiber_g": 2,
            },
        ),
        max_per_meal_g=50,
    )
    meal = Meal(
        name="Invalid meal",
        portions=(invalid_food.portion(150),),
        recipe="Cook and serve.",
    )
    targets = NutritionTargets(
        bmi=22.0,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=meal.nutrients,
        calorie_bounds=(0, 10_000),
        macro_bounds={},
    )
    return MealPlan((meal,), targets, SafetyResult(can_generate_plan=True))


def sample_meal(*, image_url: str | None = None) -> Meal:
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
        image_url=image_url,
    )
