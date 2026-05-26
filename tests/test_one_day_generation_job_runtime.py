from __future__ import annotations

import sys
import types

import pytest

from diet_bot.one_day_generation_job_runtime import validate_one_day_generation_job_store_for_startup


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


def test_postgres_startup_validation_validates_schema_without_initializing(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    fake_module = types.ModuleType("diet_bot.postgres_one_day_generation_job_store")

    class FakePostgresOneDayGenerationJobStore:
        def __init__(self, dsn: str) -> None:
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
        def __init__(self, _dsn: str) -> None:
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
