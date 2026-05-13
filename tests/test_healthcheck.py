from __future__ import annotations

import sys

from diet_bot import healthcheck
from diet_bot.runtime_config import RuntimeConfigError


PDF_BRANDING_ASSETS = {
    "foodbalance_pdf_logo.png",
    "foodbalance_pdf_qr.png",
}


def test_package_import_healthcheck_ok() -> None:
    assert healthcheck.check_package_import() == []


def test_package_data_healthcheck_ok_without_external_services() -> None:
    assert healthcheck.check_package_data() == []


def test_pdf_branding_assets_are_required_package_data() -> None:
    assert PDF_BRANDING_ASSETS <= set(healthcheck.REQUIRED_DATA_FILES)


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


def test_healthcheck_strict_requires_postgres_in_production(monkeypatch) -> None:
    checked: list[tuple[str, int, int]] = []

    class FakePostgresStore:
        def __init__(
            self,
            dsn: str,
            *,
            statement_timeout_ms: int,
            lock_timeout_ms: int,
            **_kwargs: object,
        ) -> None:
            checked.append((dsn, statement_timeout_ms, lock_timeout_ms))

        def healthcheck(self) -> None:
            checked.append(("healthcheck", 0, 0))

    monkeypatch.setattr(healthcheck, "PostgresDietBotStore", FakePostgresStore)

    missing_errors = healthcheck.run_healthcheck(
        strict=True,
        environ={
            "DIET_BOT_ENV": "production",
            "DIET_BOT_TOKEN": "prod-token",
        },
    )
    assert any("DIET_BOT_DATABASE_URL" in error for error in missing_errors)

    errors = healthcheck.run_healthcheck(
        strict=True,
        environ={
            "DIET_BOT_ENV": "production",
            "DIET_BOT_TOKEN": "prod-token",
            "DIET_BOT_DATABASE_URL": "postgresql://diet_bot@localhost:5432/diet_bot",
        },
    )

    assert errors == []
    assert checked == [
        ("postgresql://diet_bot@localhost:5432/diet_bot", 5000, 1000),
        ("healthcheck", 0, 0),
    ]
