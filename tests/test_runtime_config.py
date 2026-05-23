from __future__ import annotations

import json
from pathlib import Path

from diet_bot.runtime_config import (
    DEFAULT_PROMO_CODES_STATE_FILE,
    DEFAULT_STATE_FILE,
    DEFAULT_SUBSCRIPTIONS_STATE_FILE,
    load_runtime_config,
    validate_startup,
    validate_strict_production,
)


def _production_env() -> dict[str, str]:
    return {
        "DIET_BOT_TOKEN": "fake-token",
        "DIET_BOT_ENV": "production",
        "DIET_BOT_STORAGE_BACKEND": "postgres",
        "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        "DIET_BOT_SUPPORT_CHAT_ID": "-100555111222",
        "DIET_BOT_PRIVACY_POLICY_URL": "https://foodbalance.example/privacy",
    }


def test_bot_token_prefers_diet_bot_token() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "diet-token",
            "TELEGRAM_BOT_TOKEN": "telegram-token",
        },
    )

    assert config.bot_token == "diet-token"
    assert config.bot_token_source == "DIET_BOT_TOKEN"


def test_bot_token_falls_back_to_telegram_bot_token() -> None:
    config = load_runtime_config({"TELEGRAM_BOT_TOKEN": "telegram-token"})

    assert config.bot_token == "telegram-token"
    assert config.bot_token_source == "TELEGRAM_BOT_TOKEN"


def test_missing_token_is_startup_error() -> None:
    config = load_runtime_config({})

    assert validate_startup(config) == ("Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN.",)


def test_payments_enabled_only_by_one() -> None:
    assert load_runtime_config({"DIET_BOT_PAYMENTS_ENABLED": "1"}).payments_enabled is True

    for raw in ("", "0", "true", "yes", "on", "2"):
        assert load_runtime_config({"DIET_BOT_PAYMENTS_ENABLED": raw}).payments_enabled is False


def test_provider_token_alone_does_not_enable_payments() -> None:
    config = load_runtime_config({"TELEGRAM_PROVIDER_TOKEN": "provider-secret"})

    assert config.telegram_provider_token == "provider-secret"
    assert config.payments_enabled is False


def test_storage_backend_defaults_to_json_outside_production() -> None:
    assert load_runtime_config({}).storage_backend == "json"
    assert load_runtime_config({"DIET_BOT_ENV": "local"}).storage_backend == "json"
    assert load_runtime_config({"DIET_BOT_ENV": "development"}).storage_backend == "json"


def test_storage_backend_accepts_explicit_json_and_postgres() -> None:
    json_config = load_runtime_config({"DIET_BOT_STORAGE_BACKEND": "json"})
    postgres_config = load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    assert json_config.storage_backend == "json"
    assert postgres_config.storage_backend == "postgres"
    assert validate_startup(postgres_config) == ("Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN.",)


def test_invalid_storage_backend_is_startup_config_error() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_STORAGE_BACKEND": "sqlite",
        },
    )

    issues = validate_startup(config)

    assert any("DIET_BOT_STORAGE_BACKEND" in issue for issue in issues)
    assert any("json" in issue and "postgres" in issue for issue in issues)


def test_production_defaults_to_postgres_backend_when_unset() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
            "DIET_BOT_SUPPORT_CHAT_ID": "-100555111222",
            "DIET_BOT_PRIVACY_POLICY_URL": "https://foodbalance.example/privacy",
        },
    )

    assert config.environment == "production"
    assert config.storage_backend == "postgres"
    assert validate_startup(config) == ()


def test_production_startup_accepts_required_postgres_support_and_privacy() -> None:
    config = load_runtime_config(_production_env())

    assert validate_startup(config) == ()


def test_production_requires_support_chat_id() -> None:
    env = _production_env()
    env.pop("DIET_BOT_SUPPORT_CHAT_ID")
    config = load_runtime_config(env)

    issues = validate_startup(config)

    assert any("DIET_BOT_SUPPORT_CHAT_ID" in issue for issue in issues)


def test_production_rejects_invalid_support_chat_id() -> None:
    config = load_runtime_config(
        {
            **_production_env(),
            "DIET_BOT_SUPPORT_CHAT_ID": "not-a-chat-id",
        },
    )

    issues = validate_startup(config)

    assert any("DIET_BOT_SUPPORT_CHAT_ID" in issue for issue in issues)


def test_production_requires_privacy_policy_url() -> None:
    env = _production_env()
    env.pop("DIET_BOT_PRIVACY_POLICY_URL")
    config = load_runtime_config(env)

    issues = validate_startup(config)

    assert any("DIET_BOT_PRIVACY_POLICY_URL" in issue for issue in issues)


def test_production_rejects_invalid_privacy_policy_url() -> None:
    config = load_runtime_config(
        {
            **_production_env(),
            "DIET_BOT_PRIVACY_POLICY_URL": "foodbalance.example/privacy",
        },
    )

    issues = validate_startup(config)

    assert any("DIET_BOT_PRIVACY_POLICY_URL" in issue for issue in issues)


def test_production_explicit_json_backend_is_rejected() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_STORAGE_BACKEND": "json",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
            "DIET_BOT_SUPPORT_CHAT_ID": "-100555111222",
            "DIET_BOT_PRIVACY_POLICY_URL": "https://foodbalance.example/privacy",
        },
    )

    issues = validate_startup(config)

    assert config.storage_backend == "json"
    assert any("JSON storage is not allowed in production" in issue for issue in issues)


def test_postgres_backend_requires_database_url() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
        },
    )

    assert any("DIET_BOT_DATABASE_URL is required for postgres storage" in issue for issue in validate_startup(config))


def test_production_requires_database_url() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "fake-token",
            "DIET_BOT_ENV": "production",
        },
    )

    assert config.storage_backend == "postgres"
    assert any("DIET_BOT_DATABASE_URL is required in production" in issue for issue in validate_startup(config))


def test_support_admin_and_tester_ids_are_parsed() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_SUPPORT_CHAT_ID": "-100555111",
            "DIET_BOT_ADMIN_USER_IDS": "1, 2;bad\n-3",
            "DIET_BOT_TESTER_CHAT_IDS": "4; nope,5 6",
        },
    )

    assert config.support_chat_id == -100555111
    assert config.admin_user_ids == frozenset({1, 2, -3})
    assert config.tester_chat_ids == frozenset({4, 5, 6})


def test_state_paths_use_existing_defaults_and_overrides() -> None:
    default_config = load_runtime_config({})

    assert default_config.state_file == DEFAULT_STATE_FILE
    assert default_config.subscriptions_state_file == DEFAULT_SUBSCRIPTIONS_STATE_FILE
    assert default_config.promo_codes_state_file == DEFAULT_PROMO_CODES_STATE_FILE

    override_config = load_runtime_config(
        {
            "DIET_BOT_STATE_FILE": "state/history.json",
            "DIET_BOT_SUBSCRIPTIONS_STATE_FILE": "state/subscriptions.json",
            "DIET_BOT_PROMO_CODES_STATE_FILE": "state/promo_codes.json",
        },
    )

    assert override_config.state_file == Path("state/history.json")
    assert override_config.subscriptions_state_file == Path("state/subscriptions.json")
    assert override_config.promo_codes_state_file == Path("state/promo_codes.json")


def test_safe_summary_redacts_secrets() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "bot-super-secret",
            "TELEGRAM_PROVIDER_TOKEN": "provider-super-secret",
            "DIET_BOT_DATABASE_URL": "postgresql://user:db-super-secret@example/db",
            "DIET_BOT_SUPPORT_CHAT_ID": "123456",
            "DIET_BOT_ADMIN_USER_IDS": "1,2",
            "DIET_BOT_TESTER_CHAT_IDS": "3",
        },
    )

    summary = config.safe_summary()
    encoded = json.dumps(summary, sort_keys=True)

    assert summary["bot_token"] == "set"
    assert summary["telegram_provider_token"] == "set"
    assert summary["database_url"] == "set"
    assert summary["database_url_present"] is True
    assert summary["environment"] == "development"
    assert summary["storage_backend"] == "json"
    assert summary["admin_user_ids_count"] == 2
    assert summary["tester_chat_ids_count"] == 1
    assert "bot-super-secret" not in encoded
    assert "provider-super-secret" not in encoded
    assert "db-super-secret" not in encoded
    assert "123456" not in encoded


def test_strict_production_reports_missing_db_support_privacy_and_non_json_storage() -> None:
    config = load_runtime_config({"DIET_BOT_TOKEN": "fake-token"})

    issues = validate_strict_production(config)

    assert any("DIET_BOT_DATABASE_URL" in issue for issue in issues)
    assert any("DIET_BOT_SUPPORT_CHAT_ID" in issue for issue in issues)
    assert any("DIET_BOT_PRIVACY_POLICY_URL" in issue for issue in issues)
    assert any("non-JSON storage" in issue for issue in issues)
