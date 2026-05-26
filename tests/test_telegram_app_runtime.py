from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import types

import pytest


def test_telegram_app_import_does_not_import_postgres_or_psycopg_on_json_path() -> None:
    code = """
import builtins
import os
import sys

os.environ["DIET_BOT_STORAGE_BACKEND"] = "json"
os.environ.pop("DIET_BOT_DATABASE_URL", None)

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.startswith((
        "diet_bot.postgres_single_poller_guard",
        "diet_bot.postgres_entitlement_store",
        "diet_bot.postgres_weekly_pdf_job_store",
        "diet_bot.postgres_one_day_generation_job_store",
        "diet_bot.postgres_payment_store",
        "diet_bot.postgres_chat_state_store",
        "diet_bot.postgres_chat_state_migrations",
        "psycopg",
    )):
        raise AssertionError(f"telegram_app import touched postgres dependency {name}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import diet_bot.telegram_app
assert "diet_bot.postgres_single_poller_guard" not in sys.modules
assert "diet_bot.postgres_entitlement_store" not in sys.modules
assert "diet_bot.postgres_weekly_pdf_job_store" not in sys.modules
assert "diet_bot.postgres_one_day_generation_job_store" not in sys.modules
assert "diet_bot.postgres_payment_store" not in sys.modules
assert "diet_bot.postgres_chat_state_store" not in sys.modules
assert "diet_bot.postgres_chat_state_migrations" not in sys.modules
assert "psycopg" not in sys.modules
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_chat_state_runtime_json_path_does_not_import_postgres_or_psycopg(tmp_path) -> None:
    code = f"""
import builtins
import sys
from pathlib import Path

from diet_bot.runtime_config import load_runtime_config
from diet_bot.chat_state_runtime import create_chat_state_store, validate_chat_state_store_for_startup

state_path = Path({str(tmp_path / "history.json")!r})
state_path.write_text("{{}}", encoding="utf-8")
config = load_runtime_config({{
    "DIET_BOT_STORAGE_BACKEND": "json",
    "DIET_BOT_STATE_FILE": str(state_path),
}})

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.startswith((
        "diet_bot.postgres_chat_state_store",
        "diet_bot.postgres_chat_state_migrations",
        "psycopg",
    )):
        raise AssertionError(f"JSON chat state runtime imported postgres dependency {{name}}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
store = create_chat_state_store(config)
validate_chat_state_store_for_startup(config, store)
assert store.load_all() == {{}}
assert "diet_bot.postgres_chat_state_store" not in sys.modules
assert "diet_bot.postgres_chat_state_migrations" not in sys.modules
assert "psycopg" not in sys.modules
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_chat_state_runtime_postgres_validates_schema_without_initializing(monkeypatch) -> None:
    from diet_bot.chat_state_runtime import validate_chat_state_store_for_startup
    from diet_bot.runtime_config import load_runtime_config

    calls: list[tuple[str, str]] = []
    config = load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    class FakePostgresChatStateStore:
        def __init__(self, database_url: str) -> None:
            calls.append(("init", database_url))

        def initialize(self) -> None:
            calls.append(("initialize", "called"))

        def validate_schema(self) -> None:
            calls.append(("validate_schema", "called"))

    fake_module = types.ModuleType("diet_bot.postgres_chat_state_store")
    fake_module.PostgresChatStateStore = FakePostgresChatStateStore

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_chat_state_store", fake_module)

    validate_chat_state_store_for_startup(config)

    assert calls == [
        ("init", "postgresql://user:secret@example/db"),
        ("validate_schema", "called"),
    ]


def test_telegram_app_uses_postgres_chat_state_store_when_backend_is_postgres(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    calls: list[tuple[str, str]] = []
    config = load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    class FakePostgresChatStateStore:
        def __init__(self, database_url: str) -> None:
            calls.append(("init", database_url))

    fake_module = types.ModuleType("diet_bot.postgres_chat_state_store")
    fake_module.PostgresChatStateStore = FakePostgresChatStateStore

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_chat_state_store", fake_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "_CHAT_STATE_STORE", None)
    monkeypatch.setattr(telegram_app, "_CHAT_STATE_STORE_KEY", None, raising=False)

    store = telegram_app._chat_state_store()

    assert isinstance(store, FakePostgresChatStateStore)
    assert calls == [("init", "postgresql://user:secret@example/db")]


def test_run_bot_postgres_startup_acquires_guard_even_outside_production(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    fake_bot = object()
    events: list[str] = []
    polled: list[object] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            polled.append(bot)

    async def fake_set_commands(_bot) -> None:
        return None

    class FakeGuard:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://user:secret@example/db"
            events.append("guard_init")

        def acquire(self) -> FakeGuard:
            events.append("guard_acquire")
            return self

        def close(self) -> None:
            events.append("guard_close")

    def fake_validate_entitlement_storage(startup_config) -> None:
        assert startup_config is config
        events.append("validate_entitlement")

    def fake_validate_weekly_pdf_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_weekly_pdf")

    def fake_validate_one_day_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_one_day")

    def fake_validate_chat_state(startup_config) -> None:
        assert startup_config is config
        events.append("validate_chat_state")

    def fake_bot_factory(_token: str):
        events.append("bot")
        return fake_bot

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FakeGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", fake_validate_chat_state)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_one_day_generation_job_store_for_startup",
        fake_validate_one_day_jobs,
    )
    monkeypatch.setattr(telegram_app, "Bot", fake_bot_factory)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    asyncio.run(telegram_app.run_bot())

    assert polled == [fake_bot]
    assert events == [
        "validate_chat_state",
        "validate_entitlement",
        "validate_weekly_pdf",
        "validate_one_day",
        "guard_init",
        "guard_acquire",
        "bot",
        "guard_close",
    ]


def test_run_bot_payment_enabled_validates_payment_runtime_before_bot(monkeypatch, tmp_path) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    fake_bot = object()
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_PAYMENTS_ENABLED": "1",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
            "DIET_BOT_PAYMENT_RECOVERY_SPOOL": str(tmp_path / "payments.jsonl"),
        },
    )

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            assert bot is fake_bot
            events.append("start_polling")

    async def fake_set_commands(_bot) -> None:
        events.append("set_commands")

    def fake_bot_factory(_token: str):
        events.append("bot")
        return fake_bot

    def fake_validate_entitlement_storage(startup_config) -> None:
        assert startup_config is config
        events.append("validate_entitlement")

    def fake_validate_weekly_pdf_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_weekly_pdf")

    def fake_validate_one_day_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_one_day")

    def fake_validate_chat_state(startup_config) -> None:
        assert startup_config is config
        events.append("validate_chat_state")

    def fake_validate_payment(startup_config) -> None:
        assert startup_config is config
        events.append("validate_payment")

    class FakeGuard:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://user:secret@example/db"
            events.append("guard_init")

        def acquire(self) -> FakeGuard:
            events.append("guard_acquire")
            return self

        def close(self) -> None:
            events.append("guard_close")

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FakeGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", fake_validate_chat_state)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_one_day_generation_job_store_for_startup",
        fake_validate_one_day_jobs,
    )
    monkeypatch.setattr(telegram_app, "validate_payment_runtime_for_startup", fake_validate_payment)
    monkeypatch.setattr(telegram_app, "Bot", fake_bot_factory)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    asyncio.run(telegram_app.run_bot())

    assert events == [
        "validate_chat_state",
        "validate_entitlement",
        "validate_weekly_pdf",
        "validate_one_day",
        "validate_payment",
        "guard_init",
        "guard_acquire",
        "bot",
        "set_commands",
        "start_polling",
        "guard_close",
    ]


def test_run_bot_json_startup_does_not_import_postgres_or_psycopg(monkeypatch, tmp_path) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    subscriptions_path = tmp_path / "subscriptions.json"
    subscriptions_path.write_text("{}", encoding="utf-8")
    fake_bot = object()
    polled: list[object] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_SUBSCRIPTIONS_STATE_FILE": str(subscriptions_path),
        },
    )
    imported: list[str] = []

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            polled.append(bot)

    async def fake_set_commands(_bot) -> None:
        return None

    original_import = __import__

    def guarded_import(name, *args, **kwargs):
        imported.append(name)
        if name.startswith((
            "diet_bot.postgres_single_poller_guard",
            "diet_bot.postgres_entitlement_store",
            "diet_bot.postgres_weekly_pdf_job_store",
            "diet_bot.postgres_one_day_generation_job_store",
            "diet_bot.postgres_payment_store",
            "diet_bot.postgres_chat_state_store",
            "diet_bot.postgres_chat_state_migrations",
            "psycopg",
        )):
            raise AssertionError(f"JSON startup touched postgres dependency {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "diet_bot.postgres_single_poller_guard", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_entitlement_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_weekly_pdf_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_payment_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_chat_state_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_chat_state_migrations", raising=False)
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    monkeypatch.setattr("builtins.__import__", guarded_import)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "Bot", lambda _token: fake_bot)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    asyncio.run(telegram_app.run_bot())

    assert polled == [fake_bot]
    assert "diet_bot.postgres_single_poller_guard" not in imported
    assert "diet_bot.postgres_entitlement_store" not in imported
    assert "diet_bot.postgres_weekly_pdf_job_store" not in imported
    assert "diet_bot.postgres_one_day_generation_job_store" not in imported
    assert "diet_bot.postgres_payment_store" not in imported
    assert "diet_bot.postgres_chat_state_store" not in imported
    assert "diet_bot.postgres_chat_state_migrations" not in imported
    assert "diet_bot.postgres_single_poller_guard" not in sys.modules
    assert "diet_bot.postgres_entitlement_store" not in sys.modules
    assert "diet_bot.postgres_weekly_pdf_job_store" not in sys.modules
    assert "diet_bot.postgres_one_day_generation_job_store" not in sys.modules
    assert "diet_bot.postgres_payment_store" not in sys.modules
    assert "diet_bot.postgres_chat_state_store" not in sys.modules
    assert "diet_bot.postgres_chat_state_migrations" not in sys.modules
    assert "psycopg" not in sys.modules


def test_run_bot_production_postgres_acquires_guard_before_bot_and_releases(
    monkeypatch,
) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    fake_bot = object()
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
            "DIET_BOT_SUPPORT_CHAT_ID": "1001",
            "DIET_BOT_PRIVACY_POLICY_URL": "https://example.com/privacy",
        },
    )

    class FakeGuard:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://user:secret@example/db"
            events.append("guard_init")

        def acquire(self) -> FakeGuard:
            events.append("guard_acquire")
            return self

        def close(self) -> None:
            events.append("guard_close")

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            assert bot is fake_bot
            events.append("start_polling")

    async def fake_set_commands(bot) -> None:
        assert bot is fake_bot
        events.append("set_commands")

    def fake_bot_factory(_token: str):
        events.append("bot")
        return fake_bot

    def fake_validate_entitlement_storage(startup_config) -> None:
        assert startup_config is config
        events.append("validate_entitlement")

    def fake_validate_weekly_pdf_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_weekly_pdf")

    def fake_validate_one_day_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_one_day")

    def fake_validate_chat_state(startup_config) -> None:
        assert startup_config is config
        events.append("validate_chat_state")

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FakeGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", fake_validate_chat_state)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_one_day_generation_job_store_for_startup",
        fake_validate_one_day_jobs,
    )
    monkeypatch.setattr(telegram_app, "Bot", fake_bot_factory)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    asyncio.run(telegram_app.run_bot())

    assert events == [
        "validate_chat_state",
        "validate_entitlement",
        "validate_weekly_pdf",
        "validate_one_day",
        "guard_init",
        "guard_acquire",
        "bot",
        "set_commands",
        "start_polling",
        "guard_close",
    ]


def test_run_bot_guard_failure_exits_before_bot_or_telegram_path(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
            "DIET_BOT_SUPPORT_CHAT_ID": "1001",
            "DIET_BOT_PRIVACY_POLICY_URL": "https://example.com/privacy",
        },
    )

    class FailingGuard:
        def __init__(self, _database_url: str) -> None:
            events.append("guard_init")

        def acquire(self) -> FailingGuard:
            events.append("guard_acquire")
            raise RuntimeError("another production poller is already active.")

    def fail_bot(_token: str):
        raise AssertionError("Bot must not be constructed when single-poller guard fails")

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FailingGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_weekly_pdf_job_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_one_day_generation_job_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "Bot", fail_bot)

    with pytest.raises(RuntimeError, match="another production poller is already active"):
        asyncio.run(telegram_app.run_bot())

    assert events == ["guard_init", "guard_acquire"]


def test_run_bot_unknown_env_postgres_guard_failure_exits_before_bot(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_ENV": "staging",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    class FailingGuard:
        def __init__(self, _database_url: str) -> None:
            events.append("guard_init")

        def acquire(self) -> FailingGuard:
            events.append("guard_acquire")
            raise RuntimeError("single-poller guard unavailable")

    def fail_bot(_token: str):
        raise AssertionError("Bot must not be constructed when Postgres guard fails")

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FailingGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_weekly_pdf_job_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_one_day_generation_job_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_payment_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "Bot", fail_bot)

    with pytest.raises(RuntimeError, match="single-poller guard unavailable"):
        asyncio.run(telegram_app.run_bot())

    assert events == ["guard_init", "guard_acquire"]


def test_run_bot_one_day_startup_validation_failure_exits_before_bot(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    def fake_validate_chat_state(startup_config) -> None:
        assert startup_config is config
        events.append("validate_chat_state")

    def fake_validate_entitlement_storage(startup_config) -> None:
        assert startup_config is config
        events.append("validate_entitlement")

    def fake_validate_weekly_pdf_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_weekly_pdf")

    def fail_validate_one_day_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_one_day")
        raise RuntimeError("one-day generation job schema missing")

    def fail_payment(_config) -> None:
        raise AssertionError("payment validation must not run after one-day startup validation fails")

    def fail_bot(_token: str):
        raise AssertionError("Bot must not be constructed when one-day validation fails")

    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", fake_validate_chat_state)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_one_day_generation_job_store_for_startup",
        fail_validate_one_day_jobs,
    )
    monkeypatch.setattr(telegram_app, "validate_payment_runtime_for_startup", fail_payment)
    monkeypatch.setattr(telegram_app, "Bot", fail_bot)

    with pytest.raises(RuntimeError, match="one-day generation job schema missing"):
        asyncio.run(telegram_app.run_bot())

    assert events == [
        "validate_chat_state",
        "validate_entitlement",
        "validate_weekly_pdf",
        "validate_one_day",
    ]
