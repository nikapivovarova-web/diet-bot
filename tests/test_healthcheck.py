from __future__ import annotations

import sys

from diet_bot import healthcheck
from diet_bot.runtime_config import RuntimeConfigError


def test_package_import_healthcheck_ok() -> None:
    assert healthcheck.check_package_import() == []


def test_package_data_healthcheck_ok_without_external_services() -> None:
    assert healthcheck.check_package_data() == []


def test_healthcheck_reports_missing_required_package_data() -> None:
    errors = healthcheck.check_package_data(["missing-healthcheck-test-file.json"])

    assert errors == ["Package data file missing: data/missing-healthcheck-test-file.json."]


def test_healthcheck_cli_package_data_only_exits_zero(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DIET_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    assert healthcheck.main(["--package-data-only"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "healthcheck: ok\n"
    assert captured.err == ""


def test_healthcheck_cli_default_reuses_runtime_config_guard(monkeypatch, capsys) -> None:
    seen_environ: list[dict[str, str]] = []

    def load_runtime_config(environ: dict[str, str]) -> object:
        seen_environ.append(environ)
        raise RuntimeConfigError("runtime config failed")

    monkeypatch.delenv("DIET_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(healthcheck, "load_runtime_config", load_runtime_config)

    assert healthcheck.main([]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "healthcheck: runtime config failed\n"
    assert seen_environ
    assert seen_environ[0]["DIET_BOT_TOKEN"] == "healthcheck-local-token"


def test_healthcheck_cli_failure_message_starts_with_healthcheck_prefix(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DIET_BOT_ENV", "production")

    assert healthcheck.main([]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("healthcheck: ")


def test_healthcheck_does_not_print_secret_values(monkeypatch, capsys) -> None:
    secret_token = "123456:VERY_SECRET_TOKEN"
    monkeypatch.setenv("DIET_BOT_TOKEN", secret_token)
    monkeypatch.setenv("DIET_BOT_ENV", "production")

    assert healthcheck.main([]) == 1

    captured = capsys.readouterr()
    assert secret_token not in captured.out
    assert secret_token not in captured.err


def test_healthcheck_does_not_import_telegram_or_postgres(monkeypatch) -> None:
    sys.modules.pop("aiogram", None)
    sys.modules.pop("psycopg", None)

    assert healthcheck.run_healthcheck(environ={}) == []
    assert "aiogram" not in sys.modules
    assert "psycopg" not in sys.modules
