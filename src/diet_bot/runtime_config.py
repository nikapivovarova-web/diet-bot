from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PRODUCTION_ENV_NAMES = frozenset({"prod", "production"})
POSTGRES_URL_SCHEMES = frozenset({"postgres", "postgresql"})
PLACEHOLDER_DATABASE_URL_PARTS = (
    "<",
    ">",
    "change-me",
    "changeme",
    "example",
    "placeholder",
    "your-",
    "your_",
)
HEALTHCHECK_LOCAL_TOKEN = "healthcheck-local-token"


class RuntimeConfigError(RuntimeError):
    """Raised when startup configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    bot_token: str
    telegram_provider_token: str
    support_chat_id: int | None
    admin_user_ids: frozenset[int]
    tester_chat_ids: frozenset[int]
    state_file: Path
    subscriptions_state_file: Path
    promo_codes_state_file: Path
    database_url: str
    local_json_storage_allowed: bool
    postgres_statement_timeout_ms: int
    postgres_lock_timeout_ms: int
    public_payments_enabled: bool
    payment_test_prices_enabled: bool


def load_runtime_config(environ: Mapping[str, str] | None = None) -> RuntimeConfig:
    env = os.environ if environ is None else environ
    environment = _env_value(env, "DIET_BOT_ENV") or "development"
    bot_token = _first_non_blank(env, "DIET_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise RuntimeConfigError("Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN.")

    database_url = _env_value(env, "DIET_BOT_DATABASE_URL")
    if database_url:
        _validate_database_url(database_url)

    local_json_storage_allowed = _env_value(env, "DIET_BOT_ALLOW_JSON_STORAGE") == "1"
    production_environment = is_production_environment(environment)
    if production_environment:
        if not database_url:
            raise RuntimeConfigError("Set DIET_BOT_DATABASE_URL for production durable storage.")
        local_json_storage_allowed = False
    elif (
        not database_url
        and not local_json_storage_allowed
        and not _is_local_healthcheck_probe(environment, bot_token)
    ):
        raise RuntimeConfigError(
            "Set DIET_BOT_DATABASE_URL or DIET_BOT_ALLOW_JSON_STORAGE=1 for local JSON storage."
        )

    postgres_statement_timeout_ms = _parse_positive_int(
        _env_value(env, "DIET_BOT_POSTGRES_STATEMENT_TIMEOUT_MS"),
        default=5000,
        name="DIET_BOT_POSTGRES_STATEMENT_TIMEOUT_MS",
    )
    postgres_lock_timeout_ms = _parse_positive_int(
        _env_value(env, "DIET_BOT_POSTGRES_LOCK_TIMEOUT_MS"),
        default=1000,
        name="DIET_BOT_POSTGRES_LOCK_TIMEOUT_MS",
    )
    public_payments_enabled = _parse_bool_flag(
        _env_value(env, "DIET_BOT_PUBLIC_PAYMENTS_ENABLED"),
        default=False,
        name="DIET_BOT_PUBLIC_PAYMENTS_ENABLED",
    )
    payment_test_prices_enabled = _parse_bool_flag(
        _env_value(env, "DIET_BOT_PAYMENT_TEST_PRICES_ENABLED"),
        default=False,
        name="DIET_BOT_PAYMENT_TEST_PRICES_ENABLED",
    )

    default_state_file = Path(__file__).resolve().parents[2] / ".diet_bot_state" / "history.json"
    state_file = _path_from_env(env, "DIET_BOT_STATE_FILE", default_state_file)
    subscriptions_state_file = _path_from_env(
        env,
        "DIET_BOT_SUBSCRIPTIONS_STATE_FILE",
        state_file.with_name("subscriptions.json"),
    )
    promo_codes_state_file = _path_from_env(
        env,
        "DIET_BOT_PROMO_CODES_STATE_FILE",
        state_file.with_name("promo_codes.json"),
    )

    return RuntimeConfig(
        environment=environment.strip(),
        bot_token=bot_token,
        telegram_provider_token=_env_value(env, "TELEGRAM_PROVIDER_TOKEN"),
        support_chat_id=_parse_optional_int(_env_value(env, "DIET_BOT_SUPPORT_CHAT_ID")),
        admin_user_ids=_parse_id_set(_env_value(env, "DIET_BOT_ADMIN_USER_IDS")),
        tester_chat_ids=_parse_id_set(_env_value(env, "DIET_BOT_TESTER_CHAT_IDS")),
        state_file=state_file,
        subscriptions_state_file=subscriptions_state_file,
        promo_codes_state_file=promo_codes_state_file,
        database_url=database_url,
        local_json_storage_allowed=local_json_storage_allowed,
        postgres_statement_timeout_ms=postgres_statement_timeout_ms,
        postgres_lock_timeout_ms=postgres_lock_timeout_ms,
        public_payments_enabled=public_payments_enabled,
        payment_test_prices_enabled=payment_test_prices_enabled,
    )


def is_production_environment(environment: str | None) -> bool:
    return (environment or "").strip().lower() in PRODUCTION_ENV_NAMES


def _first_non_blank(env: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = _env_value(env, name)
        if value:
            return value
    return ""


def _env_value(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _path_from_env(env: Mapping[str, str], name: str, default: Path) -> Path:
    value = _env_value(env, name)
    if not value:
        return default
    return Path(value)


def _validate_database_url(database_url: str) -> None:
    parsed = urlparse(database_url)
    if parsed.scheme.lower() not in POSTGRES_URL_SCHEMES or not parsed.netloc:
        raise RuntimeConfigError("DIET_BOT_DATABASE_URL must be a PostgreSQL URL.")
    if _is_placeholder_database_url(database_url):
        raise RuntimeConfigError("DIET_BOT_DATABASE_URL contains a placeholder value.")


def _is_placeholder_database_url(database_url: str) -> bool:
    lowered_url = database_url.strip().lower()
    if any(part in lowered_url for part in PLACEHOLDER_DATABASE_URL_PARTS):
        return True

    parsed = urlparse(database_url)
    placeholder_credentials = {"password", "changeme", "change-me", "secret", "your-password"}
    if (parsed.password or "").strip().lower() in placeholder_credentials:
        return True
    return False


def _is_local_healthcheck_probe(environment: str, bot_token: str) -> bool:
    return (
        not is_production_environment(environment)
        and bot_token == HEALTHCHECK_LOCAL_TOKEN
    )


def _parse_positive_int(raw: str, *, default: int, name: str) -> int:
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeConfigError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise RuntimeConfigError(f"{name} must be a positive integer.")
    return value


def _parse_bool_flag(raw: str, *, default: bool, name: str) -> bool:
    if not raw:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeConfigError(
        f"{name} must be one of: 1, 0, true, false, yes, no, on, off."
    )


def _parse_id_set(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for item in re.split(r"[\s,;]+", raw):
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            continue
    return frozenset(ids)


def _parse_optional_int(raw: str) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
