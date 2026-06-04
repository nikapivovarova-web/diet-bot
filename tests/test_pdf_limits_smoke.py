from __future__ import annotations

import asyncio
import threading
from datetime import UTC, date, datetime, timedelta
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
    monkeypatch.setenv("DIET_BOT_STORAGE_BACKEND", "json")
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "WEEK_PDF_STATUS_UPDATE_SECONDS", 60.0)
    monkeypatch.setattr(telegram_app, "_WEEKLY_PDF_JOB_RUNTIME", None, raising=False)
    monkeypatch.setattr(telegram_app, "_RUNTIME_CONFIG_APPLIED", True, raising=False)
    monkeypatch.setattr(telegram_app, "PUBLIC_PAYMENTS_ENABLED", False, raising=False)
    monkeypatch.setattr(telegram_app, "PAYMENT_TEST_PRICES_ENABLED", False, raising=False)
    telegram_app._configure_weekly_pdf_concurrency(telegram_app.DEFAULT_WEEKLY_PDF_MAX_CONCURRENCY)
    yield
    telegram_app.PLAN_COUNT_BY_CHAT_ID.clear()
    telegram_app.PLAN_SEED_OFFSET_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID.clear()
    telegram_app._configure_weekly_pdf_concurrency(telegram_app.DEFAULT_WEEKLY_PDF_MAX_CONCURRENCY)


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


def test_weekly_pdf_preview_does_not_save_or_spend_json_entitlement(monkeypatch) -> None:
    chat_id = 101_016
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    before = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id].to_dict()

    def fail_save_entitlements(*_args, **_kwargs) -> None:
        raise AssertionError("weekly PDF preview must not save entitlements")

    monkeypatch.setattr(telegram_app, "save_entitlements", fail_save_entitlements)

    assert telegram_app._weekly_pdf_attempt_available(chat_id) is True

    after = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id].to_dict()
    assert after == before


@pytest.mark.anyio
async def test_weekly_pdf_free_preview_with_extra_limit_shows_paywall_without_queue(monkeypatch) -> None:
    chat_id = 101_017
    message = FakeMessage(chat_id)
    entitlement = Entitlement(extra_weekly_pdf_remaining=1)
    telegram_app.grant_test_access(entitlement, now=datetime(2026, 5, 10, tzinfo=UTC))
    telegram_app.set_test_access_enabled(entitlement, False)
    telegram_app.save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, {chat_id: entitlement})

    def fail_queue_submit(*_args, **_kwargs):
        raise AssertionError("free-preview weekly PDF must not enter the queue")

    monkeypatch.setattr(telegram_app.WEEK_PDF_QUEUE_MANAGER, "submit", fail_queue_submit)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    saved = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    assert sent is False
    assert message.texts
    assert message.documents == []
    assert saved.extra_weekly_pdf_remaining == 1
    assert telegram_app.WEEK_PDF_QUEUE_MANAGER.pending_count == 0


@pytest.mark.anyio
async def test_weekly_pdf_storage_error_shows_notice_without_queue(monkeypatch) -> None:
    chat_id = 101_018
    message = FakeMessage(chat_id)
    telegram_app.SUBSCRIPTIONS_STATE_FILE.write_text("{corrupt", encoding="utf-8")

    def fail_queue_submit(*_args, **_kwargs):
        raise AssertionError("weekly PDF must not enter the queue when entitlement state is corrupt")

    monkeypatch.setattr(telegram_app.WEEK_PDF_QUEUE_MANAGER, "submit", fail_queue_submit)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    assert sent is False
    assert message.documents == []
    assert message.texts[-1] == (telegram_app.ENTITLEMENT_STORAGE_ERROR_TEXT, None)


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
async def test_weekly_pdf_missing_rendered_file_refunds_before_upload(monkeypatch, tmp_path) -> None:
    chat_id = 101_019
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    plans = tuple(sample_meal_plan() for _ in range(7))
    missing_pdf_path = tmp_path / "missing.pdf"

    monkeypatch.setattr(
        telegram_app,
        "_build_week_plans_with_recent_fallback",
        lambda *_args: _week_plan_build_result(plans),
    )
    monkeypatch.setattr(telegram_app, "build_week_plan_pdf", lambda *_args: missing_pdf_path)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    assert not sent
    assert entitlement.monthly_weekly_pdf_remaining == 1
    assert message.documents == []


@pytest.mark.anyio
async def test_weekly_pdf_empty_payload_refunds_before_upload(monkeypatch) -> None:
    chat_id = 101_020
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id, weekly_pdf_remaining=1)
    plans = tuple(sample_meal_plan() for _ in range(7))

    monkeypatch.setattr(
        telegram_app,
        "_build_week_plans_with_recent_fallback",
        lambda *_args: _week_plan_build_result(plans),
    )
    monkeypatch.setattr(telegram_app, "_build_week_pdf_payload", lambda *_args: (b"", "week.pdf"))

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    assert not sent
    assert entitlement.monthly_weekly_pdf_remaining == 1
    assert message.documents == []


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
async def test_weekly_pdf_queue_uses_configured_worker_concurrency(monkeypatch) -> None:
    max_active = 0
    active = 0
    lock = threading.Lock()

    async def slow_send_week_plan(*_args, **_kwargs) -> bool:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.05)
            return True
        finally:
            with lock:
                active -= 1

    telegram_app._configure_weekly_pdf_concurrency(2)
    monkeypatch.setattr(telegram_app, "_send_week_plan", slow_send_week_plan)
    for index in range(6):
        _save_active_subscription(102_000 + index, weekly_pdf_remaining=1)

    results = await asyncio.gather(
        *(
            telegram_app._send_week_plan_with_access(FakeMessage(102_000 + index), profile_with())
            for index in range(6)
        )
    )

    assert results == [True] * 6
    assert max_active <= 2


@pytest.mark.anyio
async def test_weekly_pdf_starts_immediately_when_worker_slot_is_free(monkeypatch) -> None:
    first_chat_id = 101_011
    second_chat_id = 101_012
    first_message = FakeMessage(first_chat_id)
    second_message = FakeMessage(second_chat_id)
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_jobs = asyncio.Event()

    async def controlled_send_week_plan(message, *_args, **_kwargs) -> bool:
        if message.chat.id == first_chat_id:
            first_started.set()
        if message.chat.id == second_chat_id:
            second_started.set()
        await release_jobs.wait()
        return True

    telegram_app._configure_weekly_pdf_concurrency(2)
    monkeypatch.setattr(telegram_app, "_send_week_plan", controlled_send_week_plan)
    _save_active_subscription(first_chat_id, weekly_pdf_remaining=1)
    _save_active_subscription(second_chat_id, weekly_pdf_remaining=1)

    first_task = asyncio.create_task(telegram_app._send_week_plan_with_access(first_message, profile_with()))
    await asyncio.wait_for(first_started.wait(), timeout=1)

    second_task = asyncio.create_task(telegram_app._send_week_plan_with_access(second_message, profile_with()))
    await asyncio.wait_for(second_started.wait(), timeout=1)

    assert second_message.texts == []

    release_jobs.set()
    assert await first_task is True
    assert await second_task is True


@pytest.mark.anyio
async def test_busy_weekly_pdf_slots_enqueue_next_user_without_consuming_waiting_limit(monkeypatch) -> None:
    first_chat_id = 101_004
    second_chat_id = 101_005
    first_message = FakeMessage(first_chat_id)
    second_message = FakeMessage(second_chat_id)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    started_chat_ids: list[int] = []

    async def controlled_send_week_plan(message, *_args, **_kwargs) -> bool:
        started_chat_ids.append(message.chat.id)
        if message.chat.id == first_chat_id:
            first_started.set()
            await release_first.wait()
        if message.chat.id == second_chat_id:
            second_started.set()
        return True

    telegram_app._configure_weekly_pdf_concurrency(1)
    monkeypatch.setattr(telegram_app, "_send_week_plan", controlled_send_week_plan)
    _save_active_subscription(first_chat_id, weekly_pdf_remaining=1)
    _save_active_subscription(second_chat_id, weekly_pdf_remaining=1)

    first_task = asyncio.create_task(telegram_app._send_week_plan_with_access(first_message, profile_with()))
    await asyncio.wait_for(first_started.wait(), timeout=1)

    second_task = asyncio.create_task(telegram_app._send_week_plan_with_access(second_message, profile_with()))
    await _wait_for_message_text(second_message)

    waiting_entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[second_chat_id]
    assert waiting_entitlement.monthly_weekly_pdf_remaining == 1
    assert second_message.documents == []
    assert second_message.texts
    assert "Не переживайте, файл генерируется." in second_message.texts[-1][0]
    assert "перед вами 1 человек" in second_message.texts[-1][0]
    assert not second_started.is_set()

    release_first.set()
    assert await first_task is True
    assert await second_task is True
    assert started_chat_ids == [first_chat_id, second_chat_id]
    delivered_entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[second_chat_id]
    assert delivered_entitlement.monthly_weekly_pdf_remaining == 0


@pytest.mark.anyio
async def test_queued_weekly_pdf_waits_until_queue_status_message_is_sent(monkeypatch) -> None:
    first_chat_id = 101_009
    second_chat_id = 101_010
    first_message = FakeMessage(first_chat_id)
    second_message = SlowQueueStatusMessage(second_chat_id)
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()

    async def controlled_send_week_plan(message, *_args, **_kwargs) -> bool:
        if message.chat.id == first_chat_id:
            first_started.set()
            await release_first.wait()
        if message.chat.id == second_chat_id:
            second_started.set()
        return True

    telegram_app._configure_weekly_pdf_concurrency(1)
    monkeypatch.setattr(telegram_app, "_send_week_plan", controlled_send_week_plan)
    _save_active_subscription(first_chat_id, weekly_pdf_remaining=1)
    _save_active_subscription(second_chat_id, weekly_pdf_remaining=1)

    first_task = asyncio.create_task(telegram_app._send_week_plan_with_access(first_message, profile_with()))
    await asyncio.wait_for(first_started.wait(), timeout=1)

    second_task = asyncio.create_task(telegram_app._send_week_plan_with_access(second_message, profile_with()))
    await asyncio.wait_for(second_message.queue_status_answer_started.wait(), timeout=1)

    release_first.set()
    assert await first_task is True
    await asyncio.sleep(0.02)
    assert not second_started.is_set()

    second_message.allow_queue_status_answer.set()
    assert await second_task is True
    assert second_started.is_set()


@pytest.mark.anyio
async def test_queued_weekly_pdf_cancelled_during_queue_status_message_cleans_queue(monkeypatch) -> None:
    first_chat_id = 101_013
    second_chat_id = 101_014
    third_chat_id = 101_015
    first_message = FakeMessage(first_chat_id)
    second_message = SlowQueueStatusMessage(second_chat_id)
    third_message = FakeMessage(third_chat_id)
    first_started = asyncio.Event()
    third_started = asyncio.Event()
    release_first = asyncio.Event()
    started_chat_ids: list[int] = []

    async def controlled_send_week_plan(message, *_args, **_kwargs) -> bool:
        started_chat_ids.append(message.chat.id)
        if message.chat.id == first_chat_id:
            first_started.set()
            await release_first.wait()
        if message.chat.id == third_chat_id:
            third_started.set()
        return True

    telegram_app._configure_weekly_pdf_concurrency(1)
    monkeypatch.setattr(telegram_app, "_send_week_plan", controlled_send_week_plan)
    _save_active_subscription(first_chat_id, weekly_pdf_remaining=1)
    _save_active_subscription(second_chat_id, weekly_pdf_remaining=1)
    _save_active_subscription(third_chat_id, weekly_pdf_remaining=1)

    first_task = asyncio.create_task(telegram_app._send_week_plan_with_access(first_message, profile_with()))
    second_task = None
    third_task = None
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1)

        second_task = asyncio.create_task(telegram_app._send_week_plan_with_access(second_message, profile_with()))
        await asyncio.wait_for(second_message.queue_status_answer_started.wait(), timeout=1)

        second_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second_task

        assert not telegram_app.WEEK_PDF_QUEUE_MANAGER.has_chat(second_chat_id)
        assert telegram_app.WEEK_PDF_QUEUE_MANAGER.pending_count == 1

        release_first.set()
        assert await first_task is True
        assert telegram_app.WEEK_PDF_QUEUE_MANAGER.pending_count == 0

        third_task = asyncio.create_task(telegram_app._send_week_plan_with_access(third_message, profile_with()))
        await asyncio.wait_for(third_started.wait(), timeout=1)
        assert await third_task is True
        assert third_message.texts == []
        assert started_chat_ids == [first_chat_id, third_chat_id]
    finally:
        release_first.set()
        cleanup_tasks = [first_task]
        if second_task is not None:
            cleanup_tasks.append(second_task)
        if third_task is not None:
            cleanup_tasks.append(third_task)
        for task in cleanup_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)


@pytest.mark.anyio
async def test_second_weekly_pdf_request_from_same_chat_does_not_start_second_job(monkeypatch) -> None:
    chat_id = 101_006
    first_message = FakeMessage(chat_id)
    second_message = FakeMessage(chat_id)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    started_chat_ids: list[int] = []

    async def controlled_send_week_plan(message, *_args, **_kwargs) -> bool:
        started_chat_ids.append(message.chat.id)
        first_started.set()
        await release_first.wait()
        return True

    telegram_app._configure_weekly_pdf_concurrency(1)
    monkeypatch.setattr(telegram_app, "_send_week_plan", controlled_send_week_plan)
    _save_active_subscription(chat_id, weekly_pdf_remaining=2)

    first_task = asyncio.create_task(telegram_app._send_week_plan_with_access(first_message, profile_with()))
    await asyncio.wait_for(first_started.wait(), timeout=1)

    duplicate_sent = await telegram_app._send_week_plan_with_access(second_message, profile_with())
    entitlement_after_duplicate = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert duplicate_sent is False
    assert entitlement_after_duplicate.monthly_weekly_pdf_remaining == 1
    assert len(started_chat_ids) == 1
    assert second_message.texts == [(telegram_app.WEEK_PDF_ALREADY_RUNNING_TEXT, None)]

    release_first.set()
    assert await first_task is True
    assert started_chat_ids == [chat_id]


@pytest.mark.anyio
async def test_weekly_pdf_without_limit_shows_paywall_and_does_not_enter_queue(monkeypatch) -> None:
    chat_id = 101_007
    message = FakeMessage(chat_id)
    calls = 0

    async def fake_send_week_plan(*_args, **_kwargs) -> bool:
        nonlocal calls
        calls += 1
        return True

    telegram_app._configure_weekly_pdf_concurrency(1)
    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)
    _save_active_subscription(chat_id, weekly_pdf_remaining=0)

    sent = await telegram_app._send_week_plan_with_access(message, profile_with())

    assert sent is False
    assert calls == 0
    assert message.texts
    assert telegram_app.WEEK_PDF_QUEUE_MANAGER.pending_count == 0


@pytest.mark.anyio
async def test_weekly_pdf_send_failure_refunds_consumed_limit(monkeypatch) -> None:
    chat_id = 101_008
    message = FailingDocumentMessage(chat_id)
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
    assert sent is False
    assert entitlement.monthly_weekly_pdf_remaining == 1
    assert len(message.document_attempts) == 1


def test_weekly_pdf_payload_uses_human_readable_download_filename(monkeypatch, tmp_path) -> None:
    internal_pdf_path = tmp_path / "foodbalance-week-2026-05-20-ab12cd34.pdf"
    internal_pdf_path.write_bytes(b"%PDF-1.4\n%test")
    plan_dates = tuple(date(2026, 5, 20) + timedelta(days=offset) for offset in range(7))

    monkeypatch.setattr(telegram_app, "build_week_plan_pdf", lambda *_args: internal_pdf_path)

    pdf_data, filename = telegram_app._build_week_pdf_payload(
        tuple(sample_meal_plan() for _ in range(7)),
        plan_dates,
    )

    assert pdf_data == b"%PDF-1.4\n%test"
    assert filename == "FoodBalance_рацион_на_неделю_20-26_мая_2026.pdf"
    assert not internal_pdf_path.exists()


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


async def _wait_for_message_text(message: FakeMessage, *, timeout: float = 1.0) -> None:
    async def wait_until_text() -> None:
        while not message.texts:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_until_text(), timeout=timeout)


class FailingDocumentMessage(FakeMessage):
    def __init__(self, chat_id: int) -> None:
        super().__init__(chat_id)
        self.document_attempts = []

    async def answer_document(self, **kwargs) -> None:
        self.document_attempts.append(kwargs)
        raise RuntimeError("telegram send failed")


class SlowQueueStatusMessage(FakeMessage):
    def __init__(self, chat_id: int) -> None:
        super().__init__(chat_id)
        self.queue_status_answer_started = asyncio.Event()
        self.allow_queue_status_answer = asyncio.Event()

    async def answer(self, text, reply_markup=None):
        if text.startswith("Не переживайте, файл генерируется."):
            self.queue_status_answer_started.set()
            await self.allow_queue_status_answer.wait()
        return await super().answer(text, reply_markup=reply_markup)


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
    entitlement = _active_subscription_entitlement(
        charge_id=f"charge-{chat_id}",
        weekly_pdf_remaining=weekly_pdf_remaining,
    )
    entitlements = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)
    entitlements[chat_id] = entitlement
    telegram_app.save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, entitlements)
    return entitlement


def _active_subscription_entitlement(
    *,
    charge_id: str = "charge-active",
    weekly_pdf_remaining: int,
) -> Entitlement:
    entitlement = Entitlement()
    telegram_app.apply_subscription_payment(
        entitlement,
        charge_id,
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )
    entitlement.monthly_weekly_pdf_remaining = weekly_pdf_remaining
    return entitlement


def sample_meal_plan() -> MealPlan:
    meals = tuple(sample_meal(index) for index in range(4))
    targets = NutritionTargets(
        bmi=22.0,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector(
            {
                "energy_kcal": 2000,
                "protein_g": 120,
                "fat_g": 56,
                "carbohydrate_g": 240,
            }
        ),
        calorie_bounds=(1400, 2200),
        macro_bounds={},
    )
    return MealPlan(meals, targets, SafetyResult(can_generate_plan=True))


def _week_plan_build_result(plans: tuple[MealPlan, ...]) -> telegram_app._WeekPlanBuildResult:
    return telegram_app._WeekPlanBuildResult(plans=plans, avoidance_phase="full_recent")


def sample_meal(index: int) -> Meal:
    food = Food(
        id=f"smoke_food_{index}",
        name=f"Smoke food {index + 1}",
        category="test",
        nutrients_per_100g=NutrientVector(
            {
                "energy_kcal": 333.3333333333,
                "protein_g": 20,
                "fat_g": 9.3333333333,
                "carbohydrate_g": 40,
            },
        ),
    )
    return Meal(
        name="Smoke meal",
        portions=(food.portion(150),),
        recipe="Cook and serve.",
    )
