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
        "diet_bot.postgres_payment_store",
        "psycopg",
    )):
        raise AssertionError(f"telegram_app import touched postgres dependency {name}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import diet_bot.telegram_app
assert "diet_bot.postgres_single_poller_guard" not in sys.modules
assert "diet_bot.postgres_entitlement_store" not in sys.modules
assert "diet_bot.postgres_weekly_pdf_job_store" not in sys.modules
assert "diet_bot.postgres_payment_store" not in sys.modules
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


def test_run_bot_startup_invokes_weekly_pdf_schema_validation_for_postgres(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    fake_bot = object()
    calls: list[tuple[str, str]] = []
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

    original_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith(("diet_bot.postgres_single_poller_guard", "psycopg")):
            raise AssertionError(f"non-production startup touched single-poller guard {name}")
        return original_import(name, *args, **kwargs)

    def fake_validate_entitlement_storage(startup_config) -> None:
        calls.append(("entitlement", startup_config.storage_backend))

    def fake_validate_weekly_pdf_jobs(startup_config) -> None:
        calls.append(("weekly_pdf", startup_config.storage_backend))

    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(telegram_app, "Bot", lambda _token: fake_bot)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())
    monkeypatch.setattr("builtins.__import__", guarded_import)

    asyncio.run(telegram_app.run_bot())

    assert calls == [("entitlement", "postgres"), ("weekly_pdf", "postgres")]
    assert polled == [fake_bot]


def test_run_bot_payment_enabled_validates_payment_schema_before_bot(monkeypatch) -> None:
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

    def fake_validate_payment(startup_config) -> None:
        assert startup_config is config
        events.append("validate_payment")

    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(telegram_app, "validate_payment_runtime_for_startup", fake_validate_payment)
    monkeypatch.setattr(telegram_app, "Bot", fake_bot_factory)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    asyncio.run(telegram_app.run_bot())

    assert events == [
        "validate_entitlement",
        "validate_weekly_pdf",
        "validate_payment",
        "bot",
        "set_commands",
        "start_polling",
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
            "diet_bot.postgres_payment_store",
            "psycopg",
        )):
            raise AssertionError(f"JSON startup touched postgres dependency {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "diet_bot.postgres_single_poller_guard", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_entitlement_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_weekly_pdf_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_payment_store", raising=False)
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
    assert "diet_bot.postgres_payment_store" not in imported
    assert "diet_bot.postgres_single_poller_guard" not in sys.modules
    assert "diet_bot.postgres_entitlement_store" not in sys.modules
    assert "diet_bot.postgres_weekly_pdf_job_store" not in sys.modules
    assert "diet_bot.postgres_payment_store" not in sys.modules
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

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FakeGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(telegram_app, "Bot", fake_bot_factory)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    asyncio.run(telegram_app.run_bot())

    assert events == [
        "validate_entitlement",
        "validate_weekly_pdf",
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
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_weekly_pdf_job_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "Bot", fail_bot)

    with pytest.raises(RuntimeError, match="another production poller is already active"):
        asyncio.run(telegram_app.run_bot())

    assert events == ["guard_init", "guard_acquire"]
