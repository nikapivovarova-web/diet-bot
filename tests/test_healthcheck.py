from __future__ import annotations

import builtins
import sys
from pathlib import Path


def _production_postgres_env(**overrides: str) -> dict[str, str]:
    env = {
        "DIET_BOT_TOKEN": "fake-token",
        "DIET_BOT_ENV": "production",
        "DIET_BOT_STORAGE_BACKEND": "postgres",
        "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        "DIET_BOT_SUPPORT_CHAT_ID": "-100555111222",
        "DIET_BOT_PRIVACY_POLICY_URL": "https://foodbalance.example/privacy",
    }
    env.update(overrides)
    return env


def test_healthcheck_default_succeeds_with_fake_token_and_redacts(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main(
        [],
        env={
            "DIET_BOT_TOKEN": "bot-super-secret",
            "TELEGRAM_PROVIDER_TOKEN": "provider-super-secret",
            "DIET_BOT_DATABASE_URL": "postgresql://user:db-super-secret@example/db",
        },
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "mode=startup" in output
    assert "bot-super-secret" not in output
    assert "provider-super-secret" not in output
    assert "db-super-secret" not in output
    assert '"environment": "development"' in output
    assert '"storage_backend": "json"' in output
    assert '"database_url_present": true' in output


def test_healthcheck_default_fails_without_token(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main([], env={})

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN." in output


def test_healthcheck_production_startup_requires_support_and_privacy(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main(
        [],
        env={
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "mode=startup" in output
    assert "DIET_BOT_SUPPORT_CHAT_ID" in output
    assert "DIET_BOT_PRIVACY_POLICY_URL" in output
    assert "secret" not in output


def test_healthcheck_strict_mode_reports_production_issues(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main(["--strict-production"], env={"DIET_BOT_TOKEN": "fake-token"})

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "mode=strict-production" in output
    assert "DIET_BOT_DATABASE_URL" in output
    assert "DIET_BOT_SUPPORT_CHAT_ID" in output
    assert "DIET_BOT_PRIVACY_POLICY_URL" in output
    assert "non-JSON storage" in output


def test_healthcheck_strict_production_reports_missing_db_and_json_backend(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main(
        ["--strict-production"],
        env={
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_STORAGE_BACKEND": "json",
            "DIET_BOT_SUPPORT_CHAT_ID": "-100555111222",
            "DIET_BOT_PRIVACY_POLICY_URL": "https://foodbalance.example/privacy",
        },
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert '"environment": "production"' in output
    assert '"storage_backend": "json"' in output
    assert "DIET_BOT_DATABASE_URL is required in production" in output
    assert "JSON storage is not allowed in production" in output


def test_healthcheck_strict_production_requires_one_day_worker_for_postgres_queue(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main(
        ["--strict-production"],
        env=_production_postgres_env(DIET_BOT_WEEKLY_PDF_WORKER_ENABLED="1"),
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "DIET_BOT_ONE_DAY_WORKER_ENABLED" in output


def test_healthcheck_strict_production_requires_weekly_pdf_worker_for_postgres_queue(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main(
        ["--strict-production"],
        env=_production_postgres_env(DIET_BOT_ONE_DAY_WORKER_ENABLED="1"),
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "DIET_BOT_WEEKLY_PDF_WORKER_ENABLED" in output


def test_healthcheck_strict_production_accepts_postgres_workers_enabled(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main(
        ["--strict-production"],
        env=_production_postgres_env(
            DIET_BOT_ONE_DAY_WORKER_ENABLED="1",
            DIET_BOT_WEEKLY_PDF_WORKER_ENABLED="1",
        ),
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "issues: none" in output
    assert "DIET_BOT_ONE_DAY_WORKER_ENABLED" not in output
    assert "DIET_BOT_WEEKLY_PDF_WORKER_ENABLED" not in output


def test_healthcheck_local_json_does_not_require_postgres_workers(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main(
        [],
        env={
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_ENV": "development",
            "DIET_BOT_STORAGE_BACKEND": "json",
        },
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "issues: none" in output
    assert "DIET_BOT_ONE_DAY_WORKER_ENABLED" not in output
    assert "DIET_BOT_WEEKLY_PDF_WORKER_ENABLED" not in output


def test_healthcheck_env_can_select_strict_mode(capsys) -> None:
    from diet_bot.healthcheck import main

    exit_code = main(
        [],
        env={
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_HEALTHCHECK_STRICT": "1",
        },
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "mode=strict-production" in output


def test_healthcheck_does_not_import_telegram_or_touch_db_or_files(monkeypatch, capsys) -> None:
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        blocked_prefixes = ("aiogram", "asyncpg", "psycopg", "sqlite3")
        if name.startswith(blocked_prefixes):
            raise AssertionError(f"healthcheck imported blocked module {name}")
        return real_import(name, *args, **kwargs)

    def fail_write_text(self, *args, **kwargs):
        raise AssertionError(f"healthcheck wrote to {self}")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(Path, "write_text", fail_write_text)
    sys.modules.pop("diet_bot.healthcheck", None)

    from diet_bot.healthcheck import main

    exit_code = main(
        [],
        env={
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    assert exit_code == 0
    assert "runtime config healthcheck" in capsys.readouterr().out


def test_healthcheck_payment_spool_check_is_config_only_by_default(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("diet_bot.payment_recovery_spool"):
            raise AssertionError("healthcheck must not import payment recovery spool readiness")
        return real_import(name, *args, **kwargs)

    def fail_write_text(self, *args, **kwargs):
        raise AssertionError(f"healthcheck wrote to {self}")

    def fail_unlink(self, *args, **kwargs):
        raise AssertionError(f"healthcheck unlinked {self}")

    missing_parent_spool = tmp_path / "missing-parent" / "payments.jsonl"
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(Path, "write_text", fail_write_text)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    previous_healthcheck = sys.modules.pop("diet_bot.healthcheck", None)
    previous_spool = sys.modules.pop("diet_bot.payment_recovery_spool", None)
    try:
        from diet_bot.healthcheck import main

        exit_code = main(
            [],
            env={
                "DIET_BOT_TOKEN": "fake-token",
                "DIET_BOT_PAYMENTS_ENABLED": "1",
                "DIET_BOT_STORAGE_BACKEND": "postgres",
                "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
                "DIET_BOT_PAYMENT_RECOVERY_SPOOL": str(missing_parent_spool),
            },
        )
    finally:
        if previous_healthcheck is not None:
            sys.modules["diet_bot.healthcheck"] = previous_healthcheck
        else:
            sys.modules.pop("diet_bot.healthcheck", None)
        if previous_spool is not None:
            sys.modules["diet_bot.payment_recovery_spool"] = previous_spool
        else:
            sys.modules.pop("diet_bot.payment_recovery_spool", None)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "issues: none" in output
    assert not missing_parent_spool.exists()
