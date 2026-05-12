from __future__ import annotations

from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.runtime_config import load_runtime_config


@pytest.mark.anyio
async def test_production_without_database_url_does_not_construct_bot(monkeypatch) -> None:
    created_tokens: list[str] = []

    class UnexpectedBot:
        def __init__(self, token: str) -> None:
            created_tokens.append(token)
            raise AssertionError("Bot must not be constructed without production storage")

    monkeypatch.setenv("DIET_BOT_ENV", "production")
    monkeypatch.setenv("DIET_BOT_TOKEN", "prod-token")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DIET_BOT_ALLOW_JSON_STORAGE", raising=False)
    monkeypatch.setattr(telegram_app, "Bot", UnexpectedBot)

    with pytest.raises(RuntimeError, match="DIET_BOT_DATABASE_URL"):
        await telegram_app.run_bot()

    assert created_tokens == []


@pytest.mark.anyio
async def test_production_with_database_url_initializes_postgres_store_before_polling(
    monkeypatch,
) -> None:
    events: list[str] = []

    class FakeStore:
        def __init__(self, dsn: str, **kwargs: object) -> None:
            events.append(f"store:{dsn}")
            assert kwargs["statement_timeout_ms"] == 5000
            assert kwargs["lock_timeout_ms"] == 1000

        def initialize(self) -> None:
            events.append("store.initialize")

    class FakeBot:
        def __init__(self, token: str) -> None:
            events.append(f"bot:{token}")

    class FakeDispatcher:
        async def start_polling(self, bot: FakeBot) -> None:
            events.append("polling")

    async def fake_set_bot_commands(bot: FakeBot) -> None:
        events.append("commands")

    monkeypatch.setenv("DIET_BOT_ENV", "production")
    monkeypatch.setenv("DIET_BOT_TOKEN", "prod-token")
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://diet_bot@localhost:5432/diet_bot")
    monkeypatch.delenv("DIET_BOT_ALLOW_JSON_STORAGE", raising=False)
    monkeypatch.setattr(telegram_app, "PostgresDietBotStore", FakeStore)
    monkeypatch.setattr(telegram_app, "Bot", FakeBot)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_bot_commands)

    await telegram_app.run_bot()

    assert events == [
        "store:postgresql://diet_bot@localhost:5432/diet_bot",
        "store.initialize",
        "bot:prod-token",
        "commands",
        "polling",
    ]


def test_development_can_use_json_storage_fallback_when_flag_is_set() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_ENV": "development",
            "DIET_BOT_TOKEN": "local-token",
            "DIET_BOT_ALLOW_JSON_STORAGE": "1",
        },
    )

    assert telegram_app._storage_backend_mode(config) == "json"
    assert telegram_app._build_store_from_runtime_config(config) is None


@pytest.mark.anyio
async def test_development_without_json_storage_flag_rejects_fallback(monkeypatch) -> None:
    created: list[object] = []

    class UnexpectedBot:
        def __init__(self, token: str) -> None:
            created.append(SimpleNamespace(token=token))
            raise AssertionError("Bot must not be constructed without storage")

    monkeypatch.setenv("DIET_BOT_ENV", "development")
    monkeypatch.setenv("DIET_BOT_TOKEN", "local-token")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DIET_BOT_ALLOW_JSON_STORAGE", raising=False)
    monkeypatch.setattr(telegram_app, "Bot", UnexpectedBot)

    with pytest.raises(RuntimeError, match="DIET_BOT_ALLOW_JSON_STORAGE=1"):
        await telegram_app.run_bot()

    assert created == []
