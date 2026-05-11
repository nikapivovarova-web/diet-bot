from __future__ import annotations

import asyncio

import pytest

from diet_bot import telegram_app


def test_run_bot_removes_heartbeat_and_closes_session_on_shutdown(monkeypatch, tmp_path) -> None:
    heartbeat_path = tmp_path / "polling_heartbeat.json"
    closed_sessions: list[bool] = []

    class FakeSession:
        async def close(self) -> None:
            closed_sessions.append(True)

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token
            self.session = FakeSession()

    class FakeDispatcher:
        async def start_polling(self, bot: FakeBot) -> None:
            assert bot.token == "123456:abcdef"
            assert heartbeat_path.is_file()
            raise RuntimeError("stop polling")

    async def no_op(*args, **kwargs) -> None:
        return None

    async def fake_run_storage_io(*args, **kwargs) -> None:
        return None

    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.setenv("DIET_BOT_POLLING_HEARTBEAT_FILE", str(heartbeat_path))
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "")
    monkeypatch.setattr(telegram_app, "ALLOW_JSON_STORAGE", True)
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "development")
    monkeypatch.setattr(telegram_app, "Bot", FakeBot)
    monkeypatch.setattr(telegram_app, "_prepare_polling_webhook_state", no_op)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", no_op)
    monkeypatch.setattr(telegram_app, "_run_storage_io", fake_run_storage_io)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    with pytest.raises(RuntimeError, match="stop polling"):
        asyncio.run(telegram_app.run_bot())

    assert closed_sessions == [True]
    assert not heartbeat_path.exists()
