from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from diet_bot import healthcheck


def test_strict_requires_database_url(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("DIET_BOT_ENV", "production")
    monkeypatch.setenv("DIET_BOT_SUPPORT_CHAT_ID", "-100555111222")
    monkeypatch.setenv("DIET_BOT_PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DIET_BOT_ALLOW_JSON_STORAGE", raising=False)

    assert healthcheck.main(["--strict"]) == 1

    captured = capsys.readouterr()
    assert "DIET_BOT_DATABASE_URL is required in strict mode." in captured.err


def test_non_strict_allows_local_json_storage(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DIET_BOT_ALLOW_JSON_STORAGE", "1")

    assert healthcheck.main([]) == 0

    captured = capsys.readouterr()
    assert "healthcheck: ok" in captured.out


def test_healthcheck_rejects_placeholder_database_url(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.setenv(
        "DIET_BOT_DATABASE_URL",
        "postgresql://diet_bot:YOUR_POSTGRES_PASSWORD@postgres:5432/diet_bot",
    )

    assert healthcheck.main(["--strict"]) == 1

    captured = capsys.readouterr()
    assert "DIET_BOT_DATABASE_URL contains an example placeholder" in captured.err


def test_healthcheck_rejects_placeholder_token(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:telegram-token")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DIET_BOT_ALLOW_JSON_STORAGE", "1")

    assert healthcheck.main([]) == 1

    captured = capsys.readouterr()
    assert "Telegram bot token looks like an example placeholder" in captured.err


def test_strict_checks_postgres_connection(monkeypatch, capsys) -> None:
    calls: list[tuple[str, int]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query: str) -> None:
            assert query == "SELECT 1"

        def fetchone(self) -> tuple[int]:
            return (1,)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    def connect(database_url: str, connect_timeout: int) -> FakeConnection:
        calls.append((database_url, connect_timeout))
        return FakeConnection()

    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.setenv("DIET_BOT_ENV", "production")
    monkeypatch.setenv("DIET_BOT_SUPPORT_CHAT_ID", "-100555111222")
    monkeypatch.setenv("DIET_BOT_PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")
    monkeypatch.setenv(
        "DIET_BOT_DATABASE_URL",
        "postgresql://diet_bot:secret@postgres:5432/diet_bot",
    )
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    monkeypatch.setattr(healthcheck, "_check_pre_payment_buttons", lambda: [])

    assert healthcheck.main(["--strict"]) == 0

    captured = capsys.readouterr()
    assert calls == [("postgresql://diet_bot:secret@postgres:5432/diet_bot", 5)]
    assert "healthcheck: ok" in captured.out


def test_package_data_check_passes_for_packaged_assets() -> None:
    assert healthcheck._check_package_data() == []


def test_package_data_only_skips_runtime_checks(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DIET_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)

    assert healthcheck.main(["--package-data-only"]) == 0

    captured = capsys.readouterr()
    assert "healthcheck: ok" in captured.out


def test_polling_liveness_accepts_fresh_local_heartbeat(monkeypatch, tmp_path, capsys) -> None:
    heartbeat_path = tmp_path / "polling_heartbeat.json"
    heartbeat_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "state": "polling",
                "updated_at": datetime.now(UTC).isoformat(),
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DIET_BOT_ALLOW_JSON_STORAGE", "1")
    monkeypatch.setenv("DIET_BOT_POLLING_HEARTBEAT_FILE", str(heartbeat_path))

    assert healthcheck.main(["--polling-liveness", "--polling-max-age-seconds", "60"]) == 0

    captured = capsys.readouterr()
    assert "healthcheck: ok" in captured.out


def test_polling_liveness_rejects_stale_heartbeat(monkeypatch, tmp_path, capsys) -> None:
    heartbeat_path = tmp_path / "polling_heartbeat.json"
    heartbeat_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "state": "polling",
                "updated_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DIET_BOT_ALLOW_JSON_STORAGE", "1")
    monkeypatch.setenv("DIET_BOT_POLLING_HEARTBEAT_FILE", str(heartbeat_path))

    assert healthcheck.main(["--polling-liveness", "--polling-max-age-seconds", "10"]) == 1

    captured = capsys.readouterr()
    assert "Polling heartbeat is stale" in captured.err


def test_strict_requires_production_environment(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.setenv("DIET_BOT_ENV", "development")
    monkeypatch.setenv("DIET_BOT_SUPPORT_CHAT_ID", "-100555111222")
    monkeypatch.setenv("DIET_BOT_PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://diet_bot:secret@postgres:5432/diet_bot")

    assert healthcheck.main(["--strict"]) == 1

    captured = capsys.readouterr()
    assert "DIET_BOT_ENV must be production" in captured.err


def test_strict_requires_support_chat_and_public_privacy(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.setenv("DIET_BOT_ENV", "production")
    monkeypatch.delenv("DIET_BOT_SUPPORT_CHAT_ID", raising=False)
    monkeypatch.setenv("DIET_BOT_PRIVACY_POLICY_URL", "http://localhost/privacy")
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)

    assert healthcheck.main(["--strict"]) == 1

    captured = capsys.readouterr()
    assert "DIET_BOT_SUPPORT_CHAT_ID is required in production" in captured.err
    assert "DIET_BOT_PRIVACY_POLICY_URL must be a public HTTPS URL in production" in captured.err


def test_strict_rejects_invalid_posthog_host_when_api_key_set(monkeypatch, capsys) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query: str) -> None:
            return None

        def fetchone(self) -> tuple[int]:
            return (1,)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.setenv("DIET_BOT_ENV", "production")
    monkeypatch.setenv("DIET_BOT_SUPPORT_CHAT_ID", "-100555111222")
    monkeypatch.setenv("DIET_BOT_PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://diet_bot:secret@postgres:5432/diet_bot")
    monkeypatch.setenv("POSTHOG_API_KEY", "ph-key")
    monkeypatch.setenv("POSTHOG_HOST", "http://localhost:8000")
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda *args, **kwargs: FakeConnection()))

    assert healthcheck.main(["--strict"]) == 1

    captured = capsys.readouterr()
    assert "POSTHOG_HOST must be a public HTTPS URL in production" in captured.err


def test_telegram_check_is_manual_and_optional(monkeypatch) -> None:
    seen_tokens: list[str] = []

    class FakeSession:
        async def close(self) -> None:
            return None

    class FakeBot:
        def __init__(self, token: str) -> None:
            seen_tokens.append(token)
            self.session = FakeSession()

        async def get_me(self) -> None:
            return None

    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DIET_BOT_ALLOW_JSON_STORAGE", "1")
    monkeypatch.setattr(healthcheck, "Bot", FakeBot)

    assert healthcheck.main([]) == 0
    assert seen_tokens == []

    assert healthcheck.main(["--telegram"]) == 0
    assert seen_tokens == ["123456:abcdef"]


def test_strict_telegram_check_verifies_support_chat(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query: str) -> None:
            return None

        def fetchone(self) -> tuple[int]:
            return (1,)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    class FakeSession:
        async def close(self) -> None:
            return None

    class FakeBot:
        def __init__(self, token: str) -> None:
            calls.append(("bot", token))
            self.session = FakeSession()

        async def get_me(self) -> None:
            calls.append(("get_me", None))

        async def get_chat(self, chat_id: int) -> None:
            calls.append(("get_chat", chat_id))

    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:abcdef")
    monkeypatch.setenv("DIET_BOT_ENV", "production")
    monkeypatch.setenv("DIET_BOT_SUPPORT_CHAT_ID", "-100555111222")
    monkeypatch.setenv("DIET_BOT_PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://diet_bot:secret@postgres:5432/diet_bot")
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda *args, **kwargs: FakeConnection()))
    monkeypatch.setattr(healthcheck, "Bot", FakeBot)
    monkeypatch.setattr(healthcheck, "_check_pre_payment_buttons", lambda: [])

    assert healthcheck.main(["--strict", "--telegram"]) == 0

    assert calls == [
        ("bot", "123456:abcdef"),
        ("get_me", None),
        ("get_chat", -100555111222),
    ]
