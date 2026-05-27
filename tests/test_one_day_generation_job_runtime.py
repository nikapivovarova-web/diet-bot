from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

from diet_bot.one_day_generation_job_runtime import (
    OneDayGenerationJobRuntime,
    validate_one_day_generation_job_store_for_startup,
)


def test_json_startup_validation_does_not_import_postgres_store(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    imported: list[str] = []

    def fail_import(name, *_args, **_kwargs):
        imported.append(name)
        if name.startswith(("diet_bot.postgres_one_day_generation_job_store", "psycopg")):
            raise AssertionError("JSON backend must not import Postgres one-day generation job store")
        return original_import(name, *_args, **_kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    validate_one_day_generation_job_store_for_startup(
        type("Config", (), {"storage_backend": "json", "database_url": None})(),
    )

    assert "diet_bot.postgres_one_day_generation_job_store" not in imported
    assert "diet_bot.postgres_one_day_generation_job_store" not in sys.modules
    assert "psycopg" not in sys.modules


def test_json_runtime_from_config_does_not_import_postgres_store(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    imported: list[str] = []

    def fail_import(name, *_args, **_kwargs):
        imported.append(name)
        if name.startswith(("diet_bot.postgres_one_day_generation_job_store", "psycopg")):
            raise AssertionError("JSON backend must not import Postgres one-day generation job store")
        return original_import(name, *_args, **_kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    runtime = OneDayGenerationJobRuntime.from_config(
        type("Config", (), {"storage_backend": "json", "database_url": None})(),
    )

    assert runtime is None
    assert "diet_bot.postgres_one_day_generation_job_store" not in imported
    assert "diet_bot.postgres_one_day_generation_job_store" not in sys.modules
    assert "psycopg" not in sys.modules


def test_postgres_runtime_from_config_constructs_store(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    fake_module = types.ModuleType("diet_bot.postgres_one_day_generation_job_store")

    class FakePostgresOneDayGenerationJobStore:
        def __init__(self, dsn: str, **_kwargs) -> None:
            calls.append(("construct", dsn))

    fake_module.PostgresOneDayGenerationJobStore = FakePostgresOneDayGenerationJobStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", fake_module)

    runtime = OneDayGenerationJobRuntime.from_config(
        type(
            "Config",
            (),
            {
                "storage_backend": "postgres",
                "database_url": "postgresql://user:secret@example/db",
            },
        )(),
    )

    assert isinstance(runtime, OneDayGenerationJobRuntime)
    assert calls == [("construct", "postgresql://user:secret@example/db")]


def test_runtime_wrapper_methods_delegate_timestamps_and_stale_settings() -> None:
    now = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
    returns = {
        "admit_job": object(),
        "start_job_and_consume": object(),
        "set_expected_value_messages": object(),
        "mark_send_started": object(),
        "mark_value_message_delivered": object(),
        "finish_success": object(),
        "finish_failure_and_refund_once": object(),
        "cancel_queued": object(),
        "cleanup_stale": object(),
    }
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeStore:
        def admit_job(self, **kwargs):
            calls.append(("admit_job", kwargs))
            return returns["admit_job"]

        def start_job_and_consume(self, job_id, **kwargs):
            calls.append(("start_job_and_consume", {"job_id": job_id, **kwargs}))
            return returns["start_job_and_consume"]

        def set_expected_value_messages(self, job_id, expected_count, **kwargs):
            calls.append(
                (
                    "set_expected_value_messages",
                    {"job_id": job_id, "expected_count": expected_count, **kwargs},
                )
            )
            return returns["set_expected_value_messages"]

        def mark_send_started(self, job_id, **kwargs):
            calls.append(("mark_send_started", {"job_id": job_id, **kwargs}))
            return returns["mark_send_started"]

        def mark_value_message_delivered(self, job_id, **kwargs):
            calls.append(("mark_value_message_delivered", {"job_id": job_id, **kwargs}))
            return returns["mark_value_message_delivered"]

        def finish_success(self, job_id, **kwargs):
            calls.append(("finish_success", {"job_id": job_id, **kwargs}))
            return returns["finish_success"]

        def finish_failure_and_refund_once(self, job_id, **kwargs):
            calls.append(("finish_failure_and_refund_once", {"job_id": job_id, **kwargs}))
            return returns["finish_failure_and_refund_once"]

        def cancel_queued(self, job_id, **kwargs):
            calls.append(("cancel_queued", {"job_id": job_id, **kwargs}))
            return returns["cancel_queued"]

        def cleanup_stale(self, **kwargs):
            calls.append(("cleanup_stale", kwargs))
            return returns["cleanup_stale"]

    runtime = OneDayGenerationJobRuntime(
        FakeStore(),
        now=lambda: now,
        stale_after_seconds=90,
        cleanup_limit=4,
    )

    assert runtime.admit(chat_id=123, idempotency_key="event-1", metadata={"source": "test"}) is returns["admit_job"]
    assert runtime.start_job_and_consume("job-1", test_access=True) is returns["start_job_and_consume"]
    assert runtime.set_expected_value_messages("job-1", 6) is returns["set_expected_value_messages"]
    assert runtime.mark_send_started("job-1") is returns["mark_send_started"]
    assert (
        runtime.mark_value_message_delivered("job-1", value_message_key="meal:00:r1")
        is returns["mark_value_message_delivered"]
    )
    assert runtime.finish_success("job-1") is returns["finish_success"]
    assert (
        runtime.finish_failure_and_refund_once("job-1", reason="one_day_failed")
        is returns["finish_failure_and_refund_once"]
    )
    assert runtime.cancel_admitted_job("job-1", reason="local_queue_full") is returns["cancel_queued"]
    assert runtime.cleanup_stale(chat_id=123) is returns["cleanup_stale"]

    assert calls == [
        (
            "admit_job",
            {
                "chat_id": 123,
                "idempotency_key": "event-1",
                "stale_after": now + timedelta(seconds=90),
                "metadata": {"source": "test"},
            },
        ),
        (
            "start_job_and_consume",
            {
                "job_id": "job-1",
                "now": now,
                "stale_after": now + timedelta(seconds=90),
                "test_access": True,
            },
        ),
        ("set_expected_value_messages", {"job_id": "job-1", "expected_count": 6, "now": now}),
        ("mark_send_started", {"job_id": "job-1", "now": now}),
        (
            "mark_value_message_delivered",
            {"job_id": "job-1", "value_message_key": "meal:00:r1", "now": now},
        ),
        ("finish_success", {"job_id": "job-1", "now": now}),
        ("finish_failure_and_refund_once", {"job_id": "job-1", "reason": "one_day_failed", "now": now}),
        ("cancel_queued", {"job_id": "job-1", "reason": "local_queue_full", "now": now}),
        ("cleanup_stale", {"chat_id": 123, "now": now, "limit": 4}),
    ]


def test_postgres_startup_validation_validates_schema_without_initializing(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    fake_module = types.ModuleType("diet_bot.postgres_one_day_generation_job_store")

    class FakePostgresOneDayGenerationJobStore:
        def __init__(self, dsn: str, **_kwargs) -> None:
            calls.append(("construct", dsn))

        def initialize(self) -> None:
            calls.append(("initialize", None))
            raise AssertionError("startup validation must not auto-migrate")

        def validate_schema(self) -> None:
            calls.append(("validate_schema", None))

    fake_module.PostgresOneDayGenerationJobStore = FakePostgresOneDayGenerationJobStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", fake_module)

    validate_one_day_generation_job_store_for_startup(
        type(
            "Config",
            (),
            {
                "storage_backend": "postgres",
                "database_url": "postgresql://user:secret@example/db",
            },
        )(),
    )

    assert calls == [
        ("construct", "postgresql://user:secret@example/db"),
        ("validate_schema", None),
    ]


def test_postgres_startup_validation_wraps_schema_failure(monkeypatch) -> None:
    fake_module = types.ModuleType("diet_bot.postgres_one_day_generation_job_store")

    class FakePostgresOneDayGenerationJobStore:
        def __init__(self, _dsn: str, **_kwargs) -> None:
            pass

        def initialize(self) -> None:
            raise AssertionError("startup validation must not auto-migrate")

        def validate_schema(self) -> None:
            raise RuntimeError("missing one_day_generation_jobs")

    fake_module.PostgresOneDayGenerationJobStore = FakePostgresOneDayGenerationJobStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", fake_module)

    with pytest.raises(RuntimeError, match="run one-day generation job migrations before startup"):
        validate_one_day_generation_job_store_for_startup(
            type(
                "Config",
                (),
                {
                    "storage_backend": "postgres",
                    "database_url": "postgresql://user:secret@example/db",
                },
            )(),
        )
