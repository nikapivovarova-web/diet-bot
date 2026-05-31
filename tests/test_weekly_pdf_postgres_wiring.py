from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.chat_state_storage import ChatStateStorageError
from diet_bot.domain import ActivityLevel, CookingTimePreference, Goal, Sex, UserProfile
from diet_bot.telegram_media_validation import TelegramMediaValidationError
from diet_bot.weekly_pdf_jobs import (
    AdmitJobResult,
    AdmitJobResultStatus,
    FinishJobResult,
    FinishJobResultStatus,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MarkDeliveredResult,
    MarkDeliveredResultStatus,
    MarkSendStartedResult,
    MarkSendStartedResultStatus,
    QueuedJobAdmissionResult,
    QueuedJobAdmissionResultStatus,
    REFUND_STATUS_NOT_REQUIRED,
    REFUND_STATUS_PENDING,
    REFUND_STATUS_REFUNDED,
    StartJobResult,
    StartJobResultStatus,
    WeeklyPdfJob,
)


@pytest.fixture(autouse=True)
def isolated_telegram_state(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_app, "STATE_FILE", tmp_path / "history.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", set())
    telegram_app._configure_weekly_pdf_concurrency(telegram_app.DEFAULT_WEEKLY_PDF_MAX_CONCURRENCY)
    yield
    telegram_app.PLAN_COUNT_BY_CHAT_ID.clear()
    telegram_app.PLAN_SEED_OFFSET_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID.clear()
    telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID.clear()
    telegram_app._configure_weekly_pdf_concurrency(telegram_app.DEFAULT_WEEKLY_PDF_MAX_CONCURRENCY)


def test_weekly_pdf_diag_redacts_chat_and_job_identifiers(caplog) -> None:
    chat_id = 201_014
    job_id = "7d0e1a90-37cc-4922-a6af-7f452ea92174"
    caplog.set_level(logging.WARNING, logger=telegram_app.logger.name)

    telegram_app._weekly_pdf_diag("marker_failed", chat_id=chat_id, job_id=job_id, status="failed")

    message = caplog.records[-1].getMessage()
    assert str(chat_id) not in message
    assert job_id not in message
    assert "chat_id=<redacted:" in message
    assert "job_id=<redacted:" in message
    assert "status=failed" in message


@pytest.mark.anyio
async def test_postgres_active_duplicate_returns_already_active_without_local_queue(monkeypatch) -> None:
    chat_id = 201_001
    message = FakeMessage(chat_id)
    runtime = FakeWeeklyPdfRuntime(admit_status=AdmitJobResultStatus.ACTIVE_DUPLICATE)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)

    def fail_submit(*_args, **_kwargs):
        raise AssertionError("Postgres duplicate must not enter the local queue")

    monkeypatch.setattr(telegram_app.WEEK_PDF_QUEUE_MANAGER, "submit", fail_submit)

    sent = await telegram_app._send_week_plan_with_access(
        message,
        profile_with(),
        idempotency_key="idem-active",
    )

    assert sent is False
    assert message.texts == [(telegram_app.WEEK_PDF_ALREADY_RUNNING_TEXT, None)]
    assert runtime.events == [
        ("cleanup", chat_id),
        ("admit_queued", chat_id, "idem-active", False),
    ]


def test_telegram_json_weekly_pdf_runtime_does_not_import_postgres_store(monkeypatch) -> None:
    imported: list[str] = []
    original_import = __import__

    def fail_postgres_import(name, *_args, **_kwargs):
        imported.append(name)
        if name.startswith(("diet_bot.postgres_weekly_pdf_job_store", "psycopg")):
            raise AssertionError(f"JSON weekly PDF runtime imported {name}")
        return original_import(name, *_args, **_kwargs)

    config = SimpleNamespace(storage_backend="json", database_url=None)
    monkeypatch.setattr(
        telegram_app,
        "_WEEKLY_PDF_JOB_RUNTIME",
        telegram_app._WEEKLY_PDF_JOB_RUNTIME_NOT_LOADED,
    )
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr("builtins.__import__", fail_postgres_import)

    runtime = telegram_app._weekly_pdf_job_runtime()

    assert runtime is None
    assert "diet_bot.postgres_weekly_pdf_job_store" not in imported


@pytest.mark.anyio
async def test_postgres_existing_idempotency_returns_already_active_without_local_queue(monkeypatch) -> None:
    chat_id = 201_002
    message = FakeMessage(chat_id)
    runtime = FakeWeeklyPdfRuntime(admit_status=AdmitJobResultStatus.EXISTING_IDEMPOTENCY)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)

    def fail_submit(*_args, **_kwargs):
        raise AssertionError("Existing idempotency must not enter the local queue")

    monkeypatch.setattr(telegram_app.WEEK_PDF_QUEUE_MANAGER, "submit", fail_submit)

    sent = await telegram_app._send_week_plan_with_access(
        message,
        profile_with(),
        idempotency_key="idem-existing",
    )

    assert sent is False
    assert message.texts == [(telegram_app.WEEK_PDF_ALREADY_RUNNING_TEXT, None)]
    assert runtime.events == [
        ("cleanup", chat_id),
        ("admit_queued", chat_id, "idem-existing", False),
    ]


@pytest.mark.anyio
async def test_postgres_admission_returns_accepted_without_entering_local_queue_or_starting(monkeypatch) -> None:
    chat_id = 201_003
    message = FakeMessage(chat_id)
    runtime = FakeWeeklyPdfRuntime()
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)

    def fail_submit(*_args, **_kwargs):
        raise AssertionError("Durable weekly PDF admission must not enter the local queue")

    monkeypatch.setattr(telegram_app.WEEK_PDF_QUEUE_MANAGER, "submit", fail_submit)
    monkeypatch.setattr(telegram_app, "_send_week_plan_after_postgres_admission", _fail_async)

    sent = await telegram_app._send_week_plan_with_access(
        message,
        profile_with(),
        idempotency_key="idem-accepted",
    )

    assert sent is True
    old_duplicate_accepted_text = "Готовлю недельный PDF. Я пришлю его сюда, как только он будет готов."
    assert message.texts == []
    assert telegram_app.WEEK_PDF_ACCEPTED_TEXT == telegram_app.WEEK_PDF_STATUS_INITIAL_TEXT
    assert all(text != old_duplicate_accepted_text for text, _reply_markup in message.texts)
    assert ("start", runtime.job.job_id, False) not in runtime.events
    assert runtime.events == [
        ("cleanup", chat_id),
        ("admit_queued", chat_id, "idem-accepted", False),
    ]


@pytest.mark.anyio
async def test_postgres_no_quota_denied_by_durable_admission_without_local_queue_submit(monkeypatch) -> None:
    chat_id = 201_009
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(
        events=events,
        queued_admit_status=QueuedJobAdmissionResultStatus.DENIED,
    )
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)

    async def send_paywall(message: FakeMessage, ration_kind: str) -> None:
        events.append(("paywall", message.chat.id, ration_kind))

    def fail_submit(*_args, **_kwargs):
        raise AssertionError("No-quota Postgres admission must not enter the local queue")

    monkeypatch.setattr(telegram_app, "_send_limit_paywall", send_paywall)
    monkeypatch.setattr(telegram_app.WEEK_PDF_QUEUE_MANAGER, "submit", fail_submit)

    sent = await telegram_app._send_week_plan_with_access(
        FakeMessage(chat_id),
        profile_with(),
        idempotency_key="idem-no-quota",
    )

    assert sent is False
    assert events == [
        ("cleanup", chat_id),
        ("admit_queued", chat_id, "idem-no-quota", False),
        ("paywall", chat_id, "weekly_pdf"),
    ]


@pytest.mark.anyio
async def test_postgres_admission_error_returns_storage_error_without_local_queue(monkeypatch) -> None:
    chat_id = 201_010
    message = FakeMessage(chat_id)
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events, fail_admit_queued=True)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)

    def fail_submit(*_args, **_kwargs):
        raise AssertionError("Postgres admission error must not enter the local queue")

    monkeypatch.setattr(telegram_app.WEEK_PDF_QUEUE_MANAGER, "submit", fail_submit)

    sent = await telegram_app._send_week_plan_with_access(
        message,
        profile_with(),
        idempotency_key="idem-preflight-error",
    )

    assert sent is False
    assert message.texts == [(telegram_app.ENTITLEMENT_STORAGE_ERROR_TEXT, None)]
    assert events == [
        ("cleanup", chat_id),
        ("admit_queued", chat_id, "idem-preflight-error", False),
    ]


@pytest.mark.anyio
async def test_postgres_start_and_finish_success_wrap_successful_document_send(monkeypatch) -> None:
    chat_id = 201_004
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")

    def allow_weekly_pdf_preflight(preflight_chat_id: int) -> bool:
        events.append(("preflight", preflight_chat_id))
        return True

    monkeypatch.setattr(telegram_app, "_weekly_pdf_attempt_available", allow_weekly_pdf_preflight)

    async def fake_send_week_plan(*_args, **kwargs) -> bool:
        events.append(("send",))
        kwargs["on_document_send_started"]()
        kwargs["on_document_delivered"]()
        return True

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await _run_admitted_weekly_pdf(runtime, chat_id)

    assert sent is True
    assert events == [
        ("start", runtime.job.job_id, False),
        ("send",),
        ("send_started", runtime.job.job_id),
        ("delivered", runtime.job.job_id),
        ("success", runtime.job.job_id),
    ]


@pytest.mark.anyio
async def test_postgres_history_save_failure_after_pdf_delivery_is_best_effort(monkeypatch) -> None:
    chat_id = 201_019
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events)
    store = FailingChatHistorySaveStore(ChatStateStorageError("history save failed"))
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    _allow_weekly_pdf_preflight(monkeypatch)

    async def fake_send_week_plan(*_args, **kwargs) -> bool:
        events.append(("send",))
        kwargs["on_document_send_started"]()
        kwargs["on_document_delivered"]()
        kwargs["recipe_history_entries"].append(
            telegram_app.RecipeHistoryItem(recipe_id="weekly-id", recipe_key="weekly:key")
        )
        return True

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await _run_admitted_weekly_pdf(runtime, chat_id)

    assert sent is True
    assert events == [
        ("start", runtime.job.job_id, False),
        ("send",),
        ("send_started", runtime.job.job_id),
        ("delivered", runtime.job.job_id),
        ("success", runtime.job.job_id),
    ]
    assert ("failure", runtime.job.job_id, "weekly_pdf_exception") not in events
    assert ("failure", runtime.job.job_id, "weekly_pdf_not_sent") not in events
    assert runtime.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert store.save_calls == 1
    assert chat_id not in telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID
    assert chat_id not in telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID


@pytest.mark.anyio
async def test_postgres_delivered_marker_failure_after_upload_finishes_non_refundable(monkeypatch, caplog) -> None:
    chat_id = 201_014
    events: list[tuple] = []
    diag_events: list[tuple[str, dict[str, object]]] = []
    runtime = FakeWeeklyPdfRuntime(events=events)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    monkeypatch.setattr(
        telegram_app,
        "_weekly_pdf_diag",
        lambda event, **fields: diag_events.append((event, fields)),
    )
    caplog.set_level(logging.ERROR, logger=telegram_app.logger.name)
    _allow_weekly_pdf_preflight(monkeypatch)

    def fail_mark_delivered(job_id):
        events.append(("delivered", job_id))
        raise RuntimeError("marker write failed")

    runtime.mark_delivered = fail_mark_delivered

    async def fake_send_week_plan(*_args, **kwargs) -> bool:
        events.append(("send",))
        kwargs["on_document_send_started"]()
        kwargs["on_document_delivered"]()
        events.append(("send_return",))
        return True

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await _run_admitted_weekly_pdf(runtime, chat_id)

    assert sent is True
    assert events == [
        ("start", runtime.job.job_id, False),
        ("send",),
        ("send_started", runtime.job.job_id),
        ("delivered", runtime.job.job_id),
        ("success", runtime.job.job_id),
        ("send_return",),
    ]
    assert ("failure", runtime.job.job_id, "weekly_pdf_not_sent") not in events
    assert ("failure", runtime.job.job_id, "weekly_pdf_exception") not in events
    assert runtime.job.status == JOB_STATUS_SUCCEEDED
    assert runtime.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert runtime.job.delivered_at is None
    assert (
        (
            "postgres_mark_delivered_failed_after_upload",
            {"chat_id": chat_id, "job_id": str(runtime.job.job_id), "error": "RuntimeError"},
        )
        in diag_events
    )
    error_messages = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert error_messages
    assert not any(str(chat_id) in message for message in error_messages)
    assert not any(str(runtime.job.job_id) in message for message in error_messages)
    assert any("<redacted:" in message for message in error_messages)


@pytest.mark.anyio
async def test_postgres_send_start_marker_failure_preserves_pre_upload_refund(monkeypatch) -> None:
    chat_id = 201_017
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    _allow_weekly_pdf_preflight(monkeypatch)

    def fail_mark_send_started(job_id):
        events.append(("send_started", job_id))
        raise RuntimeError("send-start marker failed")

    runtime.mark_send_started = fail_mark_send_started

    async def fake_send_week_plan(*_args, **kwargs) -> bool:
        events.append(("send",))
        try:
            kwargs["on_document_send_started"]()
        except RuntimeError:
            events.append(("upload_blocked",))
            return False
        events.append(("answer_document",))
        return True

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await _run_admitted_weekly_pdf(runtime, chat_id)

    assert sent is False
    assert events == [
        ("start", runtime.job.job_id, False),
        ("send",),
        ("send_started", runtime.job.job_id),
        ("upload_blocked",),
        ("failure", runtime.job.job_id, "weekly_pdf_not_sent"),
    ]
    assert ("answer_document",) not in events
    assert runtime.job.status == JOB_STATUS_FAILED
    assert runtime.job.refund_status == REFUND_STATUS_REFUNDED
    assert runtime.job.send_started_at is None
    assert runtime.job.delivered_at is None


@pytest.mark.anyio
async def test_postgres_upload_failure_after_send_start_is_non_refundable(monkeypatch) -> None:
    chat_id = 201_018
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    _allow_weekly_pdf_preflight(monkeypatch)

    async def fake_send_week_plan(*_args, **kwargs) -> bool:
        events.append(("send",))
        kwargs["on_document_send_started"]()
        events.append(("answer_document",))
        return False

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await _run_admitted_weekly_pdf(runtime, chat_id)

    assert sent is False
    assert events == [
        ("start", runtime.job.job_id, False),
        ("send",),
        ("send_started", runtime.job.job_id),
        ("answer_document",),
        ("failure", runtime.job.job_id, "weekly_pdf_not_sent"),
    ]
    assert ("delivered", runtime.job.job_id) not in events
    assert runtime.job.status == JOB_STATUS_SUCCEEDED
    assert runtime.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert runtime.job.send_started_at is not None
    assert runtime.job.delivered_at is None
    assert runtime.job.finalization_error == "weekly_pdf_not_sent"


@pytest.mark.anyio
async def test_postgres_marker_failure_then_status_edit_error_does_not_refund_or_resend(monkeypatch) -> None:
    chat_id = 201_015
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    _allow_weekly_pdf_preflight(monkeypatch)

    def fail_mark_delivered(job_id):
        events.append(("delivered", job_id))
        raise RuntimeError("marker write failed")

    runtime.mark_delivered = fail_mark_delivered

    async def fake_send_week_plan(*_args, **kwargs) -> bool:
        events.append(("send",))
        kwargs["on_document_delivered"]()
        raise RuntimeError("status edit failed")

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    with pytest.raises(RuntimeError, match="status edit failed"):
        await _run_admitted_weekly_pdf(runtime, chat_id)

    assert events == [
        ("start", runtime.job.job_id, False),
        ("send",),
        ("delivered", runtime.job.job_id),
        ("success", runtime.job.job_id),
    ]
    assert events.count(("send",)) == 1
    assert ("failure", runtime.job.job_id, "weekly_pdf_exception") not in events
    assert runtime.job.status == JOB_STATUS_SUCCEEDED
    assert runtime.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert runtime.job.delivered_at is None


@pytest.mark.anyio
async def test_postgres_marker_failure_stale_cleanup_before_normal_success_does_not_refund(monkeypatch) -> None:
    chat_id = 201_016
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    _allow_weekly_pdf_preflight(monkeypatch)

    def fail_mark_delivered(job_id):
        events.append(("delivered", job_id))
        raise RuntimeError("marker write failed")

    runtime.mark_delivered = fail_mark_delivered

    async def fake_send_week_plan(*_args, **kwargs) -> bool:
        events.append(("send",))
        kwargs["on_document_delivered"]()
        runtime.cleanup_stale(chat_id=chat_id)
        events.append(("send_return",))
        return True

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await _run_admitted_weekly_pdf(runtime, chat_id)

    assert sent is True
    assert events == [
        ("start", runtime.job.job_id, False),
        ("send",),
        ("delivered", runtime.job.job_id),
        ("success", runtime.job.job_id),
        ("cleanup", chat_id),
        ("send_return",),
    ]
    assert ("stale_refund", runtime.job.job_id) not in events
    assert runtime.job.status == JOB_STATUS_SUCCEEDED
    assert runtime.job.refund_status == REFUND_STATUS_NOT_REQUIRED
    assert runtime.job.delivered_at is None


@pytest.mark.anyio
async def test_postgres_generation_failure_uses_store_refund_path_not_json_refund(monkeypatch) -> None:
    chat_id = 201_005
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    _allow_weekly_pdf_preflight(monkeypatch)

    def fail_json_refund(*_args, **_kwargs):
        raise AssertionError("Postgres path must not use JSON entitlement refund")

    monkeypatch.setattr(telegram_app, "_refund_generation_attempt", fail_json_refund)

    async def fake_send_week_plan(*_args, **_kwargs) -> bool:
        events.append(("send",))
        return False

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await _run_admitted_weekly_pdf(runtime, chat_id)

    assert sent is False
    assert events == [
        ("start", runtime.job.job_id, False),
        ("send",),
        ("failure", runtime.job.job_id, "weekly_pdf_not_sent"),
    ]
    assert runtime.job.status == JOB_STATUS_FAILED
    assert runtime.job.refund_status == REFUND_STATUS_REFUNDED


@pytest.mark.anyio
async def test_postgres_post_delivery_failure_marks_delivered_before_failure(monkeypatch) -> None:
    chat_id = 201_011
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events)
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    _allow_weekly_pdf_preflight(monkeypatch)

    async def fake_send_week_plan(*_args, **kwargs) -> bool:
        events.append(("send",))
        kwargs["on_document_delivered"]()
        raise RuntimeError("status edit failed")

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    with pytest.raises(RuntimeError, match="status edit failed"):
        await _run_admitted_weekly_pdf(runtime, chat_id)

    assert events == [
        ("start", runtime.job.job_id, False),
        ("send",),
        ("delivered", runtime.job.job_id),
        ("failure", runtime.job.job_id, "weekly_pdf_exception"),
    ]


@pytest.mark.anyio
async def test_postgres_tester_chat_id_starts_lifecycle_as_test_access_without_json_mutation(monkeypatch) -> None:
    chat_id = 201_006
    events: list[tuple] = []
    runtime = FakeWeeklyPdfRuntime(events=events, start_source="test_access")
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", {chat_id})
    monkeypatch.setattr(telegram_app, "_weekly_pdf_job_runtime", lambda: runtime)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")
    _allow_weekly_pdf_preflight(monkeypatch)

    def fail_json_consume_or_refund(*_args, **_kwargs):
        raise AssertionError("TESTER_CHAT_IDS Postgres path must not mutate JSON entitlements")

    monkeypatch.setattr(telegram_app, "_consume_generation_attempt", fail_json_consume_or_refund)
    monkeypatch.setattr(telegram_app, "_refund_generation_attempt", fail_json_consume_or_refund)

    async def fake_send_week_plan(*_args, **kwargs) -> bool:
        events.append(("send",))
        kwargs["on_document_delivered"]()
        return True

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await _run_admitted_weekly_pdf(runtime, chat_id)

    assert sent is True
    assert events == [
        ("start", runtime.job.job_id, True),
        ("send",),
        ("delivered", runtime.job.job_id),
        ("success", runtime.job.job_id),
    ]


@pytest.mark.anyio
async def test_send_week_pdf_document_marks_delivery_after_answer_document_success() -> None:
    events: list[str] = []

    class DocumentMessage(FakeMessage):
        async def answer_document(self, **_kwargs) -> None:
            events.append("answer_document")

    await telegram_app._send_week_pdf_document(
        DocumentMessage(201_012),
        b"%PDF-1.4\n%test",
        "week.pdf",
        on_document_send_started=lambda: events.append("send_started"),
        on_document_delivered=lambda: events.append("delivered"),
    )

    assert events == ["send_started", "answer_document", "delivered"]


@pytest.mark.anyio
async def test_send_week_pdf_document_rejects_empty_pdf_before_send_start() -> None:
    events: list[str] = []

    class DocumentMessage(FakeMessage):
        async def answer_document(self, **_kwargs) -> None:
            events.append("answer_document")

    with pytest.raises(TelegramMediaValidationError, match="empty"):
        await telegram_app._send_week_pdf_document(
            DocumentMessage(201_022),
            b"",
            "week.pdf",
            on_document_send_started=lambda: events.append("send_started"),
            on_document_delivered=lambda: events.append("delivered"),
        )

    assert events == []


@pytest.mark.anyio
async def test_send_week_pdf_document_rejects_oversized_pdf_before_send_start(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(telegram_app, "TELEGRAM_DOCUMENT_MAX_BYTES", 8, raising=False)

    class DocumentMessage(FakeMessage):
        async def answer_document(self, **_kwargs) -> None:
            events.append("answer_document")

    with pytest.raises(TelegramMediaValidationError, match="exceeds"):
        await telegram_app._send_week_pdf_document(
            DocumentMessage(201_023),
            b"%PDF-1.4\nlarge",
            "week.pdf",
            on_document_send_started=lambda: events.append("send_started"),
            on_document_delivered=lambda: events.append("delivered"),
        )

    assert events == []


@pytest.mark.anyio
async def test_send_week_pdf_document_rejects_long_caption_before_send_start() -> None:
    events: list[str] = []

    class DocumentMessage(FakeMessage):
        async def answer_document(self, **_kwargs) -> None:
            events.append("answer_document")

    with pytest.raises(TelegramMediaValidationError, match="caption"):
        await telegram_app._send_week_pdf_document(
            DocumentMessage(201_024),
            b"%PDF-1.4\n%test",
            "week.pdf",
            status_text="x" * 2_000,
            on_document_send_started=lambda: events.append("send_started"),
            on_document_delivered=lambda: events.append("delivered"),
        )

    assert events == []


@pytest.mark.anyio
async def test_send_week_pdf_document_blocks_upload_when_send_start_marker_fails() -> None:
    events: list[str] = []

    class DocumentMessage(FakeMessage):
        async def answer_document(self, **_kwargs) -> None:
            events.append("answer_document")

    def fail_send_started() -> None:
        events.append("send_started")
        raise RuntimeError("marker write failed")

    with pytest.raises(RuntimeError, match="marker write failed"):
        await telegram_app._send_week_pdf_document(
            DocumentMessage(201_019),
            b"%PDF-1.4\n%test",
            "week.pdf",
            on_document_send_started=fail_send_started,
            on_document_delivered=lambda: events.append("delivered"),
        )

    assert events == ["send_started"]


@pytest.mark.anyio
async def test_send_week_pdf_document_does_not_mark_delivery_before_upload_success() -> None:
    events: list[str] = []

    class FailingDocumentMessage(FakeMessage):
        async def answer_document(self, **_kwargs) -> None:
            events.append("answer_document")
            raise RuntimeError("upload failed")

    with pytest.raises(RuntimeError, match="upload failed"):
        await telegram_app._send_week_pdf_document(
            FailingDocumentMessage(201_013),
            b"%PDF-1.4\n%test",
            "week.pdf",
            on_document_send_started=lambda: events.append("send_started"),
            on_document_delivered=lambda: events.append("delivered"),
        )

    assert events == ["send_started", "answer_document"]


@pytest.mark.anyio
async def test_json_history_save_failure_after_pdf_delivery_returns_success_without_refund_or_notice(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 201_020
    subscriptions_path = tmp_path / "subscriptions.json"
    store = FailingChatHistorySaveStore(ChatStateStorageError("history save failed"))
    message = FakeMessage(chat_id)
    events: list[tuple] = []
    entitlement = telegram_app.Entitlement()
    telegram_app.apply_subscription_payment(
        entitlement,
        f"charge-{chat_id}",
        now=datetime(2026, 5, 23, tzinfo=UTC),
    )
    entitlement.monthly_weekly_pdf_remaining = 1
    telegram_app.save_entitlements(subscriptions_path, {chat_id: entitlement})
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")

    async def fake_send_week_plan(_message, *_args, **kwargs) -> bool:
        events.append(("send",))
        kwargs["recipe_history_entries"].append(
            telegram_app.RecipeHistoryItem(recipe_id="weekly-id", recipe_key="weekly:key")
        )
        return True

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await telegram_app._send_week_plan_after_queue_admission(message, profile_with())

    saved_entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
    assert sent is True
    assert events == [("send",)]
    assert saved_entitlement.monthly_weekly_pdf_remaining == 0
    assert message.texts == []
    assert store.save_calls == 1
    assert chat_id not in telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID
    assert chat_id not in telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID


@pytest.mark.anyio
async def test_json_weekly_generation_failure_refunds_consumed_weekly_attempt(
    monkeypatch,
    tmp_path,
) -> None:
    chat_id = 201_021
    subscriptions_path = tmp_path / "subscriptions.json"
    message = FakeMessage(chat_id)
    events: list[tuple] = []
    entitlement = telegram_app.Entitlement()
    telegram_app.apply_subscription_payment(
        entitlement,
        f"charge-{chat_id}",
        now=datetime(2026, 5, 23, tzinfo=UTC),
    )
    entitlement.monthly_weekly_pdf_remaining = 1
    telegram_app.save_entitlements(subscriptions_path, {chat_id: entitlement})
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", subscriptions_path)
    monkeypatch.setattr(telegram_app, "_format_entitlement_status", lambda _chat_id: "status")

    async def fake_send_week_plan(_message, *_args, **_kwargs) -> bool:
        events.append(("send_failed",))
        return False

    monkeypatch.setattr(telegram_app, "_send_week_plan", fake_send_week_plan)

    sent = await telegram_app._send_week_plan_after_queue_admission(message, profile_with())

    saved_entitlement = telegram_app.load_entitlements(subscriptions_path)[chat_id]
    assert sent is False
    assert events == [("send_failed",)]
    assert saved_entitlement.monthly_weekly_pdf_remaining == 1
    assert saved_entitlement.extra_weekly_pdf_remaining == 0


class FailingChatHistorySaveStore:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.save_calls = 0

    def load_all(self):
        return {}

    def save_chat_state(self, chat_id: int, chat_state) -> None:
        self.save_calls += 1
        raise self.exc


class FakeWeeklyPdfRuntime:
    def __init__(
        self,
        *,
        events: list[tuple] | None = None,
        admit_status: AdmitJobResultStatus = AdmitJobResultStatus.ADMITTED,
        queued_admit_status: QueuedJobAdmissionResultStatus | None = None,
        fail_admit_queued: bool = False,
        start_status: StartJobResultStatus = StartJobResultStatus.STARTED,
        start_source: str | None = "monthly",
    ) -> None:
        self.events = events if events is not None else []
        self.admit_status = admit_status
        self.queued_admit_status = queued_admit_status
        self.fail_admit_queued = fail_admit_queued
        self.start_status = start_status
        self.start_source = start_source
        self.job = _job(status=JOB_STATUS_QUEUED, chat_id=0)

    def cleanup_stale(self, *, chat_id: int):
        self.events.append(("cleanup", chat_id))
        if self.job.chat_id != chat_id or self.job.status not in {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING}:
            return
        if self.job.status == JOB_STATUS_QUEUED:
            self.job = _job(
                status=JOB_STATUS_CANCELLED,
                chat_id=self.job.chat_id,
                job_id=self.job.job_id,
                source=self.job.consumption_source,
                refund_status=REFUND_STATUS_NOT_REQUIRED,
            )
            return
        if self.job.delivered_at is not None:
            self.job = _job(
                status=JOB_STATUS_SUCCEEDED,
                chat_id=self.job.chat_id,
                job_id=self.job.job_id,
                source=self.job.consumption_source,
                send_started_at=self.job.send_started_at,
                delivered_at=self.job.delivered_at,
                refund_status=REFUND_STATUS_NOT_REQUIRED,
                finalization_error="stale_after_delivery",
            )
            return
        if self.job.send_started_at is not None:
            self.job = _job(
                status=JOB_STATUS_SUCCEEDED,
                chat_id=self.job.chat_id,
                job_id=self.job.job_id,
                source=self.job.consumption_source,
                send_started_at=self.job.send_started_at,
                refund_status=REFUND_STATUS_NOT_REQUIRED,
                finalization_error="stale_after_send_attempt_unconfirmed",
            )
            return
        refund_status = self.job.refund_status
        if self.job.refund_status == REFUND_STATUS_PENDING and self.job.consumption_source in {"monthly", "extra"}:
            refund_status = REFUND_STATUS_REFUNDED
            self.events.append(("stale_refund", self.job.job_id))
        self.job = _job(
            status=JOB_STATUS_FAILED,
            chat_id=self.job.chat_id,
            job_id=self.job.job_id,
            source=self.job.consumption_source,
            refund_status=refund_status,
        )

    def admit(self, *, chat_id: int, idempotency_key: str, metadata=None):
        del metadata
        status = JOB_STATUS_RUNNING if self.admit_status == AdmitJobResultStatus.ACTIVE_DUPLICATE else JOB_STATUS_QUEUED
        self.job = _job(status=status, chat_id=chat_id)
        self.events.append(("admit", chat_id, idempotency_key))
        return AdmitJobResult(self.admit_status, self.job)

    def admit_queued(
        self,
        *,
        chat_id: int,
        idempotency_key: str,
        request_snapshot,
        metadata=None,
        test_access: bool = False,
    ):
        del request_snapshot, metadata
        self.events.append(("admit_queued", chat_id, idempotency_key, test_access))
        if self.fail_admit_queued:
            raise RuntimeError("admission failed")
        queued_status = self.queued_admit_status
        if queued_status is None:
            queued_status = QueuedJobAdmissionResultStatus(self.admit_status.value)
        if queued_status == QueuedJobAdmissionResultStatus.DENIED:
            return QueuedJobAdmissionResult(
                QueuedJobAdmissionResultStatus.DENIED,
                None,
                "weekly_pdf_entitlement_unavailable",
            )
        status = JOB_STATUS_RUNNING if queued_status == QueuedJobAdmissionResultStatus.ACTIVE_DUPLICATE else JOB_STATUS_QUEUED
        refund_status = REFUND_STATUS_NOT_REQUIRED if test_access else REFUND_STATUS_PENDING
        source = "test_access" if test_access else "monthly"
        self.job = _job(status=status, chat_id=chat_id, source=source, refund_status=refund_status)
        return QueuedJobAdmissionResult(queued_status, self.job)

    def start_job_and_consume(self, job_id, *, test_access: bool = False):
        self.events.append(("start", job_id, test_access))
        if self.start_status != StartJobResultStatus.STARTED:
            return StartJobResult(self.start_status, self.job)
        refund_status = (
            REFUND_STATUS_PENDING if self.start_source in {"monthly", "extra"} else REFUND_STATUS_NOT_REQUIRED
        )
        self.job = _job(
            status=JOB_STATUS_RUNNING,
            chat_id=self.job.chat_id,
            job_id=job_id,
            source=self.start_source,
            refund_status=refund_status,
        )
        return StartJobResult(StartJobResultStatus.STARTED, self.job)

    def finish_success(self, job_id):
        self.events.append(("success", job_id))
        if self.job.status in {JOB_STATUS_CANCELLED, JOB_STATUS_FAILED, JOB_STATUS_SUCCEEDED}:
            return FinishJobResult(FinishJobResultStatus.ALREADY_TERMINAL, self.job)
        self.job = _job(
            status=JOB_STATUS_SUCCEEDED,
            chat_id=self.job.chat_id,
            job_id=job_id,
            source=self.start_source,
            send_started_at=self.job.send_started_at,
            delivered_at=self.job.delivered_at,
            refund_status=REFUND_STATUS_NOT_REQUIRED,
        )
        return FinishJobResult(
            FinishJobResultStatus.SUCCEEDED,
            self.job,
        )

    def mark_send_started(self, job_id):
        self.events.append(("send_started", job_id))
        self.job = _job(
            status=JOB_STATUS_RUNNING,
            chat_id=self.job.chat_id,
            job_id=job_id,
            source=self.start_source,
            send_started_at=datetime(2026, 5, 23, 0, 0, 4, tzinfo=UTC),
            delivered_at=self.job.delivered_at,
            refund_status=self.job.refund_status,
        )
        return MarkSendStartedResult(MarkSendStartedResultStatus.SEND_STARTED, self.job)

    def mark_delivered(self, job_id):
        self.events.append(("delivered", job_id))
        self.job = _job(
            status=JOB_STATUS_RUNNING,
            chat_id=self.job.chat_id,
            job_id=job_id,
            source=self.start_source,
            send_started_at=self.job.send_started_at,
            delivered_at=datetime(2026, 5, 23, 0, 0, 5, tzinfo=UTC),
            refund_status=self.job.refund_status,
        )
        return MarkDeliveredResult(MarkDeliveredResultStatus.DELIVERED, self.job)

    def finish_failure_and_refund_once(self, job_id, *, reason: str | None = None):
        self.events.append(("failure", job_id, reason))
        if self.job.delivered_at is not None:
            self.job = _job(
                status=JOB_STATUS_SUCCEEDED,
                chat_id=self.job.chat_id,
                job_id=job_id,
                source=self.start_source,
                send_started_at=self.job.send_started_at,
                delivered_at=self.job.delivered_at,
                refund_status=REFUND_STATUS_NOT_REQUIRED,
                finalization_error=reason,
            )
            return FinishJobResult(FinishJobResultStatus.SUCCEEDED, self.job)
        if self.job.send_started_at is not None:
            self.job = _job(
                status=JOB_STATUS_SUCCEEDED,
                chat_id=self.job.chat_id,
                job_id=job_id,
                source=self.start_source,
                send_started_at=self.job.send_started_at,
                refund_status=REFUND_STATUS_NOT_REQUIRED,
                finalization_error=reason,
            )
            return FinishJobResult(FinishJobResultStatus.SUCCEEDED, self.job)
        refund_status = self.job.refund_status
        if self.job.refund_status == REFUND_STATUS_PENDING and self.job.consumption_source in {"monthly", "extra"}:
            refund_status = REFUND_STATUS_REFUNDED
        elif self.job.refund_status != REFUND_STATUS_REFUNDED:
            refund_status = REFUND_STATUS_NOT_REQUIRED
        self.job = _job(
            status=JOB_STATUS_FAILED,
            chat_id=self.job.chat_id,
            job_id=job_id,
            source=self.start_source,
            refund_status=refund_status,
        )
        return FinishJobResult(
            FinishJobResultStatus.FAILED,
            self.job,
        )

    def cancel_admitted_job(self, job_id, *, reason: str | None = None):
        self.events.append(("cancel", job_id, reason))
        return FinishJobResult(
            FinishJobResultStatus.CANCELLED,
            _job(status=JOB_STATUS_CANCELLED, chat_id=self.job.chat_id, job_id=job_id),
        )


class FakeMessage:
    def __init__(self, chat_id: int) -> None:
        self.chat = SimpleNamespace(id=chat_id, type="private")
        self.from_user = SimpleNamespace(id=chat_id)
        self.texts: list[tuple[str, object]] = []

    async def answer(self, text, reply_markup=None):
        self.texts.append((text, reply_markup))
        return SimpleNamespace(edit_text=_fake_edit_text)


async def _fake_edit_text(*_args, **_kwargs) -> None:
    return None


async def _run_admitted_weekly_pdf(runtime: FakeWeeklyPdfRuntime, chat_id: int) -> bool:
    runtime.job = _job(status=JOB_STATUS_QUEUED, chat_id=chat_id)
    return await telegram_app._send_week_plan_after_postgres_admission(
        FakeMessage(chat_id),
        profile_with(),
        runtime=runtime,
        job=runtime.job,
    )


async def _fail_async(*_args, **_kwargs):
    raise AssertionError("unexpected async call")


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


def _allow_weekly_pdf_preflight(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "_weekly_pdf_attempt_available", lambda _chat_id: True)


def _job(
    *,
    status: str,
    chat_id: int,
    job_id=None,
    source: str | None = None,
    send_started_at: datetime | None = None,
    delivered_at: datetime | None = None,
    finalization_error: str | None = None,
    refund_status: str = REFUND_STATUS_NOT_REQUIRED,
) -> WeeklyPdfJob:
    return WeeklyPdfJob(
        job_id=job_id or uuid4(),
        chat_id=chat_id,
        idempotency_key=f"idem-{chat_id}",
        status=status,
        refund_status=refund_status,
        consumption_source=source,
        stale_after=datetime(2026, 5, 23, tzinfo=UTC) + timedelta(minutes=30),
        send_started_at=send_started_at,
        delivered_at=delivered_at,
        finalization_error=finalization_error,
    )
