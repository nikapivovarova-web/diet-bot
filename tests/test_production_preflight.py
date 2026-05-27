from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

import pytest

from diet_bot.runtime_config import load_runtime_config


def _valid_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = {
        "DIET_BOT_TOKEN": "bot-super-secret",
        "DIET_BOT_ENV": "production",
        "DIET_BOT_STORAGE_BACKEND": "postgres",
        "DIET_BOT_DATABASE_URL": "postgresql://user:db-super-secret@example.test/diet_bot_prod",
        "DIET_BOT_SUPPORT_CHAT_ID": "-100555111222",
        "DIET_BOT_PRIVACY_POLICY_URL": "https://foodbalance.example/privacy",
        "DIET_BOT_PAYMENT_RECOVERY_SPOOL": str(tmp_path / "payment-recovery.jsonl"),
    }
    env.update(overrides)
    return env


def _patch_successful_runtime_checks(monkeypatch: pytest.MonkeyPatch, preflight) -> list[str]:
    calls: list[str] = []

    class FakeStore:
        pass

    def record(name: str):
        def wrapped(*_args, **_kwargs) -> None:
            calls.append(name)

        return wrapped

    monkeypatch.setattr(preflight, "_validate_postgres_connectivity", record("postgres_connectivity"))
    monkeypatch.setattr(preflight, "validate_chat_state_store_for_startup", record("chat_state_schema"))
    monkeypatch.setattr(preflight, "create_entitlement_store", lambda _config: FakeStore())
    monkeypatch.setattr(preflight, "validate_entitlement_store_for_startup", record("entitlement_schema"))
    monkeypatch.setattr(preflight, "validate_weekly_pdf_job_runtime_for_startup", record("weekly_pdf_schema"))
    monkeypatch.setattr(
        preflight,
        "validate_one_day_generation_job_store_for_startup",
        record("one_day_schema"),
    )
    monkeypatch.setattr(preflight, "_validate_payment_ledger_schema", record("payment_ledger_schema"))
    monkeypatch.setattr(preflight, "validate_payment_recovery_spool_ready", record("payment_spool"))
    monkeypatch.setattr(preflight, "_validate_single_poller_guard", record("single_poller_guard"))
    return calls


def test_production_preflight_success_reports_pass_and_uses_existing_validators(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from diet_bot import production_preflight as preflight

    calls = _patch_successful_runtime_checks(monkeypatch, preflight)

    exit_code = preflight.main([], env=_valid_env(tmp_path))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "production preflight" in output
    assert "result: PASS" in output
    assert "PASS runtime config" in output
    assert "PASS Postgres connectivity" in output
    assert "PASS entitlement schema" in output
    assert "PASS payment ledger schema" in output
    assert "PASS single-poller guard acquire/release" in output
    assert calls == [
        "postgres_connectivity",
        "chat_state_schema",
        "entitlement_schema",
        "weekly_pdf_schema",
        "one_day_schema",
        "payment_ledger_schema",
        "payment_spool",
        "single_poller_guard",
    ]
    assert "bot-super-secret" not in output
    assert "db-super-secret" not in output
    assert "postgresql://user:" not in output


def test_production_preflight_fails_closed_on_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from diet_bot import production_preflight as preflight

    monkeypatch.setattr(
        preflight,
        "_validate_postgres_connectivity",
        lambda _config: (_ for _ in ()).throw(AssertionError("DB checks must not run after invalid config")),
    )

    exit_code = preflight.main([], env={})

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "result: FAIL" in output
    assert "FAIL runtime config" in output
    assert "DIET_BOT_ENV must be production or prod" in output
    assert "Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN" in output


def test_production_preflight_reports_missing_schema_without_printing_dsn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from diet_bot import production_preflight as preflight

    _patch_successful_runtime_checks(monkeypatch, preflight)

    def fail_chat_state(_config) -> None:
        raise RuntimeError(
            "Postgres chat state storage is not ready; run chat state migrations before startup. "
            "dsn=postgresql://user:db-super-secret@example.test/diet_bot_prod",
        )

    monkeypatch.setattr(preflight, "validate_chat_state_store_for_startup", fail_chat_state)

    exit_code = preflight.main([], env=_valid_env(tmp_path))

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL chat state schema" in output
    assert "run chat state migrations before startup" in output
    assert "db-super-secret" not in output
    assert "postgresql://user:" not in output


def test_production_preflight_checks_configured_spool_even_when_payments_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from diet_bot import production_preflight as preflight

    _patch_successful_runtime_checks(monkeypatch, preflight)
    monkeypatch.setattr(
        preflight,
        "validate_payment_recovery_spool_ready",
        lambda _path: (_ for _ in ()).throw(RuntimeError("payment recovery spool parent directory does not exist")),
    )

    exit_code = preflight.main([], env=_valid_env(tmp_path))

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL payment recovery spool readiness" in output
    assert "payment recovery spool parent directory does not exist" in output


def test_production_preflight_payment_enabled_requires_provider_token_without_printing_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from diet_bot import production_preflight as preflight

    _patch_successful_runtime_checks(monkeypatch, preflight)
    env = _valid_env(tmp_path, DIET_BOT_PAYMENTS_ENABLED="1")

    exit_code = preflight.main([], env=env)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "TELEGRAM_PROVIDER_TOKEN is required when payments are enabled in production" in output
    assert "bot-super-secret" not in output
    assert "db-super-secret" not in output


def test_production_preflight_redacts_provider_token_and_dependency_error_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from diet_bot import production_preflight as preflight

    _patch_successful_runtime_checks(monkeypatch, preflight)

    def fail_connectivity(config) -> None:
        raise RuntimeError(
            "could not connect with "
            f"{config.database_url} {config.bot_token} {config.telegram_provider_token}"
        )

    monkeypatch.setattr(preflight, "_validate_postgres_connectivity", fail_connectivity)
    env = _valid_env(
        tmp_path,
        DIET_BOT_PAYMENTS_ENABLED="1",
        TELEGRAM_PROVIDER_TOKEN="provider-super-secret",
    )

    exit_code = preflight.main([], env=env)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL Postgres connectivity" in output
    assert "bot-super-secret" not in output
    assert "db-super-secret" not in output
    assert "provider-super-secret" not in output
    assert "postgresql://user:" not in output
    assert "<redacted>" in output


def test_single_poller_guard_probe_always_releases_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    from diet_bot import production_preflight as preflight

    events: list[str] = []

    class FakeGuard:
        def __init__(self, dsn: str) -> None:
            events.append(f"init:{dsn}")

        def acquire(self):
            events.append("acquire")
            return self

        def close(self) -> None:
            events.append("close")

    fake_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_module.PostgresSinglePollerGuard = FakeGuard
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_module)
    config = load_runtime_config(_valid_env(Path.cwd()))

    preflight._validate_single_poller_guard(config)

    assert events == [
        "init:postgresql://user:db-super-secret@example.test/diet_bot_prod",
        "acquire",
        "close",
    ]


def test_production_preflight_import_does_not_import_telegram_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del capsys
    import diet_bot

    previous_preflight = sys.modules.pop("diet_bot.production_preflight", None)
    had_preflight_attr = hasattr(diet_bot, "production_preflight")
    previous_preflight_attr = getattr(diet_bot, "production_preflight", None)
    if had_preflight_attr:
        delattr(diet_bot, "production_preflight")
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith(("aiogram", "diet_bot.telegram_app")):
            raise AssertionError(f"production preflight imported Telegram runtime {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    try:
        from diet_bot import production_preflight as preflight

        assert preflight is not None
    finally:
        if previous_preflight is not None:
            sys.modules["diet_bot.production_preflight"] = previous_preflight
        if had_preflight_attr:
            setattr(diet_bot, "production_preflight", previous_preflight_attr)


def test_runbook_documents_production_preflight_cli() -> None:
    runbook = Path("docs/production-runbook.md").read_text(encoding="utf-8")

    assert "python.exe -m scripts.ops.production_preflight" in runbook
    assert "never starts polling" in runbook
    assert "never calls Telegram API" in runbook
    assert "payment ledger schema/migration expectations" in runbook
    assert "single-poller advisory guard can be acquired and released" in runbook
    assert "must not contain full" in runbook
