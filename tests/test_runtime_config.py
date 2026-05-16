from __future__ import annotations

import pytest

from diet_bot.runtime_config import RuntimeConfigError, load_runtime_config


def test_runtime_config_prefers_diet_bot_token_over_legacy_alias() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "new-token",
            "TELEGRAM_BOT_TOKEN": "legacy-token",
            "DIET_BOT_ALLOW_JSON_STORAGE": "1",
        },
    )

    assert config.bot_token == "new-token"


def test_runtime_config_accepts_legacy_telegram_bot_token() -> None:
    config = load_runtime_config(
        {
            "TELEGRAM_BOT_TOKEN": "legacy-token",
            "DIET_BOT_ALLOW_JSON_STORAGE": "1",
        },
    )

    assert config.bot_token == "legacy-token"


def test_runtime_config_requires_token_for_startup() -> None:
    with pytest.raises(RuntimeConfigError, match="Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN."):
        load_runtime_config({})


def test_runtime_config_allows_local_mode_without_production_storage() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "local-token",
            "DIET_BOT_ENV": "development",
            "DIET_BOT_ALLOW_JSON_STORAGE": "1",
        },
    )

    assert config.environment == "development"
    assert config.database_url == ""
    assert config.local_json_storage_allowed is True
    assert config.state_file.name == "history.json"
    assert config.subscriptions_state_file.name == "subscriptions.json"
    assert config.promo_codes_state_file.name == "promo_codes.json"


def test_runtime_config_accepts_production_only_with_database_url() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "prod-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_DATABASE_URL": "postgresql://diet_bot@db.internal:5432/diet_bot",
        },
    )

    assert config.environment == "production"
    assert config.database_url == "postgresql://diet_bot@db.internal:5432/diet_bot"
    assert config.local_json_storage_allowed is False
    assert config.postgres_statement_timeout_ms == 5000
    assert config.postgres_lock_timeout_ms == 1000


def test_runtime_config_rejects_production_json_only() -> None:
    secret_token = "123456:VERY_SECRET_TOKEN"

    with pytest.raises(RuntimeConfigError) as exc_info:
        load_runtime_config(
            {
                "DIET_BOT_TOKEN": secret_token,
                "DIET_BOT_ENV": "production",
                "DIET_BOT_ALLOW_JSON_STORAGE": "1",
            },
        )

    message = str(exc_info.value)
    assert "DIET_BOT_DATABASE_URL" in message
    assert secret_token not in message


def test_runtime_config_requires_explicit_json_fallback_in_development() -> None:
    with pytest.raises(RuntimeConfigError) as exc_info:
        load_runtime_config(
            {
                "DIET_BOT_TOKEN": "local-token",
                "DIET_BOT_ENV": "development",
            },
        )

    assert "DIET_BOT_ALLOW_JSON_STORAGE=1" in str(exc_info.value)

    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "local-token",
            "DIET_BOT_ENV": "development",
            "DIET_BOT_ALLOW_JSON_STORAGE": "1",
        },
    )

    assert config.local_json_storage_allowed is True
    assert config.database_url == ""


def test_json_fallback_requires_explicit_development_opt_in() -> None:
    with pytest.raises(RuntimeConfigError) as exc_info:
        load_runtime_config(
            {
                "DIET_BOT_TOKEN": "local-token",
                "DIET_BOT_ENV": "development",
            },
        )

    assert "DIET_BOT_ALLOW_JSON_STORAGE=1" in str(exc_info.value)

    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "local-token",
            "DIET_BOT_ENV": "development",
            "DIET_BOT_ALLOW_JSON_STORAGE": "1",
        },
    )

    assert config.local_json_storage_allowed is True
    assert config.database_url == ""


def test_production_rejects_json_fallback_even_when_flag_is_set() -> None:
    with pytest.raises(RuntimeConfigError) as exc_info:
        load_runtime_config(
            {
                "DIET_BOT_TOKEN": "prod-token",
                "DIET_BOT_ENV": "production",
                "DIET_BOT_ALLOW_JSON_STORAGE": "1",
            },
        )

    message = str(exc_info.value)
    assert "DIET_BOT_DATABASE_URL" in message
    assert "prod-token" not in message


def test_runtime_config_rejects_placeholder_database_url_without_leaking_secrets() -> None:
    placeholder_url = "postgresql://diet_bot:super-secret-db-password@example.com:5432/diet_bot"

    with pytest.raises(RuntimeConfigError) as exc_info:
        load_runtime_config(
            {
                "DIET_BOT_TOKEN": "prod-token",
                "DIET_BOT_ENV": "production",
                "DIET_BOT_DATABASE_URL": placeholder_url,
            },
        )

    message = str(exc_info.value)
    assert "DIET_BOT_DATABASE_URL" in message
    assert "placeholder" in message
    assert placeholder_url not in message
    assert "super-secret-db-password" not in message


def test_runtime_config_parses_admin_and_tester_ids_without_crashing_on_invalid_values() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "local-token",
            "DIET_BOT_ALLOW_JSON_STORAGE": "1",
            "DIET_BOT_ADMIN_USER_IDS": "100, not-an-int; -200",
            "DIET_BOT_TESTER_CHAT_IDS": "300 400 broken",
        },
    )

    assert config.admin_user_ids == frozenset({100, -200})
    assert config.tester_chat_ids == frozenset({300, 400})


def test_runtime_config_optional_provider_token_defaults_to_empty_string() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "local-token",
            "DIET_BOT_ALLOW_JSON_STORAGE": "1",
        },
    )

    assert config.telegram_provider_token == ""


def test_runtime_config_disables_public_payments_by_default() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "prod-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_DATABASE_URL": "postgresql://diet_bot@db.internal:5432/diet_bot",
            "TELEGRAM_PROVIDER_TOKEN": "provider-token",
        },
    )

    assert config.public_payments_enabled is False
    assert config.payment_test_prices_enabled is False


def test_runtime_config_enables_public_payments_only_with_explicit_flag() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "prod-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_DATABASE_URL": "postgresql://diet_bot@db.internal:5432/diet_bot",
            "DIET_BOT_PUBLIC_PAYMENTS_ENABLED": "1",
        },
    )

    assert config.public_payments_enabled is True


def test_runtime_config_enables_payment_test_prices_only_with_explicit_flag() -> None:
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "prod-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_DATABASE_URL": "postgresql://diet_bot@db.internal:5432/diet_bot",
            "DIET_BOT_PUBLIC_PAYMENTS_ENABLED": "1",
            "DIET_BOT_PAYMENT_TEST_PRICES_ENABLED": "1",
        },
    )

    assert config.payment_test_prices_enabled is True


def test_runtime_config_rejects_invalid_public_payments_flag() -> None:
    with pytest.raises(RuntimeConfigError, match="DIET_BOT_PUBLIC_PAYMENTS_ENABLED"):
        load_runtime_config(
            {
                "DIET_BOT_TOKEN": "local-token",
                "DIET_BOT_ALLOW_JSON_STORAGE": "1",
                "DIET_BOT_PUBLIC_PAYMENTS_ENABLED": "maybe",
            },
        )


def test_runtime_config_rejects_invalid_payment_test_prices_flag() -> None:
    with pytest.raises(RuntimeConfigError, match="DIET_BOT_PAYMENT_TEST_PRICES_ENABLED"):
        load_runtime_config(
            {
                "DIET_BOT_TOKEN": "local-token",
                "DIET_BOT_ALLOW_JSON_STORAGE": "1",
                "DIET_BOT_PAYMENT_TEST_PRICES_ENABLED": "maybe",
            },
        )


def test_runtime_config_uses_provided_mapping_instead_of_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "process-env-token")

    with pytest.raises(RuntimeConfigError, match="Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN."):
        load_runtime_config({})
