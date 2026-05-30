from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = PROJECT_ROOT / ".diet_bot_state" / "history.json"
DEFAULT_SUBSCRIPTIONS_STATE_FILE = DEFAULT_STATE_FILE.with_name("subscriptions.json")
DEFAULT_PROMO_CODES_STATE_FILE = DEFAULT_STATE_FILE.with_name("promo_codes.json")
DEFAULT_PAYMENT_RECOVERY_SPOOL = DEFAULT_SUBSCRIPTIONS_STATE_FILE.with_name("payment_recovery.jsonl")
DEFAULT_ONE_DAY_WORKER_CONCURRENCY = 1
DEFAULT_ONE_DAY_WORKER_LEASE_SECONDS = 300
DEFAULT_ONE_DAY_WORKER_HEARTBEAT_SECONDS = 60
DEFAULT_ONE_DAY_WORKER_RETRY_DELAY_SECONDS = 30
DEFAULT_ONE_DAY_WORKER_MAX_ATTEMPTS = 3
DEFAULT_ONE_DAY_WORKER_IDLE_SLEEP_SECONDS = 1.0
DEFAULT_WEEKLY_PDF_WORKER_CONCURRENCY = 1
DEFAULT_WEEKLY_PDF_WORKER_LEASE_SECONDS = 300
DEFAULT_WEEKLY_PDF_WORKER_HEARTBEAT_SECONDS = 60
DEFAULT_WEEKLY_PDF_WORKER_RETRY_DELAY_SECONDS = 30
DEFAULT_WEEKLY_PDF_WORKER_MAX_ATTEMPTS = 3
DEFAULT_WEEKLY_PDF_WORKER_IDLE_SLEEP_SECONDS = 1.0

MISSING_BOT_TOKEN_ERROR = "Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN."
PAYMENT_RECOVERY_SPOOL_ENV = "DIET_BOT_PAYMENT_RECOVERY_SPOOL"

_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_VALID_STORAGE_BACKENDS = {"json", "postgres"}
_PRODUCTION_ENVIRONMENTS = {"production", "prod"}


@dataclass(frozen=True)
class RuntimeConfig:
    bot_token: str | None
    bot_token_source: str | None
    environment: str
    payments_enabled: bool
    public_payments_enabled: bool
    payment_test_prices_enabled: bool
    telegram_provider_token: str
    database_url: str | None
    postgres_pool_enabled: bool
    postgres_connect_timeout: int
    postgres_pool_min_size: int
    postgres_pool_max_size: int
    postgres_pool_timeout: float
    state_file: Path
    subscriptions_state_file: Path
    promo_codes_state_file: Path
    payment_recovery_spool: Path
    payment_recovery_spool_configured: bool
    support_chat_id: int | None
    admin_user_ids: frozenset[int]
    tester_chat_ids: frozenset[int]
    weekly_selection_diagnostics_enabled: bool
    privacy_policy_url: str | None
    one_day_worker_enabled: bool = False
    one_day_worker_concurrency: int = DEFAULT_ONE_DAY_WORKER_CONCURRENCY
    one_day_worker_lease_seconds: int = DEFAULT_ONE_DAY_WORKER_LEASE_SECONDS
    one_day_worker_heartbeat_seconds: int = DEFAULT_ONE_DAY_WORKER_HEARTBEAT_SECONDS
    one_day_worker_retry_delay_seconds: int = DEFAULT_ONE_DAY_WORKER_RETRY_DELAY_SECONDS
    one_day_worker_max_attempts: int = DEFAULT_ONE_DAY_WORKER_MAX_ATTEMPTS
    one_day_worker_idle_sleep_seconds: float = DEFAULT_ONE_DAY_WORKER_IDLE_SLEEP_SECONDS
    weekly_pdf_worker_enabled: bool = False
    weekly_pdf_worker_concurrency: int = DEFAULT_WEEKLY_PDF_WORKER_CONCURRENCY
    weekly_pdf_worker_lease_seconds: int = DEFAULT_WEEKLY_PDF_WORKER_LEASE_SECONDS
    weekly_pdf_worker_heartbeat_seconds: int = DEFAULT_WEEKLY_PDF_WORKER_HEARTBEAT_SECONDS
    weekly_pdf_worker_retry_delay_seconds: int = DEFAULT_WEEKLY_PDF_WORKER_RETRY_DELAY_SECONDS
    weekly_pdf_worker_max_attempts: int = DEFAULT_WEEKLY_PDF_WORKER_MAX_ATTEMPTS
    weekly_pdf_worker_idle_sleep_seconds: float = DEFAULT_WEEKLY_PDF_WORKER_IDLE_SLEEP_SECONDS
    storage_backend: str = "json"
    config_errors: tuple[str, ...] = ()

    def safe_summary(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "bot_token": "set" if self.bot_token else "missing",
            "bot_token_source": self.bot_token_source if self.bot_token else None,
            "payments_enabled": self.payments_enabled,
            "public_payments_enabled": self.public_payments_enabled,
            "payment_test_prices_enabled": self.payment_test_prices_enabled,
            "telegram_provider_token": "set" if self.telegram_provider_token else "missing",
            "database_url": "set" if self.database_url else "missing",
            "database_url_present": bool(self.database_url),
            "postgres_pool_enabled": self.postgres_pool_enabled,
            "postgres_connect_timeout": self.postgres_connect_timeout,
            "postgres_pool_min_size": self.postgres_pool_min_size,
            "postgres_pool_max_size": self.postgres_pool_max_size,
            "postgres_pool_timeout": self.postgres_pool_timeout,
            "state_file": str(self.state_file),
            "subscriptions_state_file": str(self.subscriptions_state_file),
            "promo_codes_state_file": str(self.promo_codes_state_file),
            "payment_recovery_spool": str(self.payment_recovery_spool),
            "payment_recovery_spool_configured": self.payment_recovery_spool_configured,
            "support_chat_id": "set" if self.support_chat_id is not None else "missing",
            "admin_user_ids_count": len(self.admin_user_ids),
            "tester_chat_ids_count": len(self.tester_chat_ids),
            "weekly_selection_diagnostics_enabled": self.weekly_selection_diagnostics_enabled,
            "privacy_policy_url": "set" if self.privacy_policy_url else "missing",
            "one_day_worker_enabled": self.one_day_worker_enabled,
            "one_day_worker_concurrency": self.one_day_worker_concurrency,
            "one_day_worker_lease_seconds": self.one_day_worker_lease_seconds,
            "one_day_worker_heartbeat_seconds": self.one_day_worker_heartbeat_seconds,
            "one_day_worker_retry_delay_seconds": self.one_day_worker_retry_delay_seconds,
            "one_day_worker_max_attempts": self.one_day_worker_max_attempts,
            "one_day_worker_idle_sleep_seconds": self.one_day_worker_idle_sleep_seconds,
            "weekly_pdf_worker_enabled": self.weekly_pdf_worker_enabled,
            "weekly_pdf_worker_concurrency": self.weekly_pdf_worker_concurrency,
            "weekly_pdf_worker_lease_seconds": self.weekly_pdf_worker_lease_seconds,
            "weekly_pdf_worker_heartbeat_seconds": self.weekly_pdf_worker_heartbeat_seconds,
            "weekly_pdf_worker_retry_delay_seconds": self.weekly_pdf_worker_retry_delay_seconds,
            "weekly_pdf_worker_max_attempts": self.weekly_pdf_worker_max_attempts,
            "weekly_pdf_worker_idle_sleep_seconds": self.weekly_pdf_worker_idle_sleep_seconds,
            "storage_backend": self.storage_backend,
        }

    def validate_startup(self) -> tuple[str, ...]:
        issues = list(self.config_errors)
        if self.one_day_worker_enabled and self.storage_backend != "postgres":
            issues.append("DIET_BOT_ONE_DAY_WORKER_ENABLED requires postgres storage backend.")
        if self.storage_backend == "postgres" and not self.database_url:
            issues.append("DIET_BOT_DATABASE_URL is required for postgres storage.")
        if self.one_day_worker_enabled and not self.database_url:
            issues.append("DIET_BOT_DATABASE_URL is required when the one-day worker is enabled.")
        if self.weekly_pdf_worker_enabled and self.storage_backend != "postgres":
            issues.append("DIET_BOT_WEEKLY_PDF_WORKER_ENABLED requires postgres storage backend.")
        if self.weekly_pdf_worker_enabled and not self.database_url:
            issues.append("DIET_BOT_DATABASE_URL is required when the weekly PDF worker is enabled.")
        if self.payments_enabled:
            if self.storage_backend != "postgres":
                issues.append("Payments require Postgres storage backend.")
            if not self.database_url:
                issues.append("DIET_BOT_DATABASE_URL is required when payments are enabled.")
            if not self.payment_recovery_spool_configured:
                issues.append("DIET_BOT_PAYMENT_RECOVERY_SPOOL is required when payments are enabled.")
            elif not self.payment_recovery_spool.is_absolute():
                issues.append("DIET_BOT_PAYMENT_RECOVERY_SPOOL must be an absolute path when payments are enabled.")
        if self.public_payments_enabled and not self.payments_enabled:
            issues.append("DIET_BOT_PUBLIC_PAYMENTS_ENABLED requires DIET_BOT_PAYMENTS_ENABLED=1.")
        if is_production_environment(self.environment):
            if self.payment_test_prices_enabled:
                issues.append("DIET_BOT_PAYMENT_TEST_PRICES_ENABLED is not allowed in production.")
            if not self.database_url:
                issues.append("DIET_BOT_DATABASE_URL is required in production.")
            if self.storage_backend == "json":
                issues.append("JSON storage is not allowed in production.")
            if self.storage_backend == "postgres":
                if not self.one_day_worker_enabled:
                    issues.append(
                        "Production Postgres one-day generation uses durable jobs; "
                        "set DIET_BOT_ONE_DAY_WORKER_ENABLED=1 so queued one-day jobs are processed.",
                    )
                if not self.weekly_pdf_worker_enabled:
                    issues.append(
                        "Production Postgres weekly PDF generation uses durable jobs; "
                        "set DIET_BOT_WEEKLY_PDF_WORKER_ENABLED=1 so queued weekly PDF jobs are processed.",
                    )
            if self.support_chat_id is None:
                issues.append("DIET_BOT_SUPPORT_CHAT_ID is required and must be a valid integer in production.")
            if not _is_valid_http_url(self.privacy_policy_url):
                issues.append("DIET_BOT_PRIVACY_POLICY_URL is required and must be a valid HTTP(S) URL in production.")
        if not self.bot_token:
            issues.append(MISSING_BOT_TOKEN_ERROR)
        return tuple(issues)

    def validate_strict_production(self) -> tuple[str, ...]:
        issues: list[str] = []
        if not self.database_url:
            issues.append("DIET_BOT_DATABASE_URL is required for strict production.")
        if self.support_chat_id is None:
            issues.append("DIET_BOT_SUPPORT_CHAT_ID is required for strict production.")
        if not self.privacy_policy_url:
            issues.append("DIET_BOT_PRIVACY_POLICY_URL is required for strict production.")
        if self.storage_backend == "json":
            issues.append(
                "Strict production requires non-JSON storage; JSON storage is not allowed in production.",
            )
        return tuple(issues)


def load_runtime_config(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    source = os.environ if env is None else env
    bot_token, bot_token_source = _bot_token_from_env(source)
    environment = _environment_from_env(source)
    storage_backend, storage_config_errors = _storage_backend_from_env(source, environment)
    postgres_connect_timeout, connect_timeout_errors = _int_from_env(
        source,
        "DIET_BOT_POSTGRES_CONNECT_TIMEOUT_SECONDS",
        5,
        minimum=1,
    )
    postgres_pool_min_size, pool_min_errors = _int_from_env(
        source,
        "DIET_BOT_POSTGRES_POOL_MIN_SIZE",
        1,
        minimum=0,
    )
    postgres_pool_max_size, pool_max_errors = _int_from_env(
        source,
        "DIET_BOT_POSTGRES_POOL_MAX_SIZE",
        4,
        minimum=1,
    )
    postgres_pool_timeout, pool_timeout_errors = _float_from_env(
        source,
        "DIET_BOT_POSTGRES_POOL_TIMEOUT_SECONDS",
        5.0,
        minimum=0.1,
    )
    postgres_config_errors = (
        storage_config_errors
        + connect_timeout_errors
        + pool_min_errors
        + pool_max_errors
        + pool_timeout_errors
    )
    if postgres_pool_max_size < postgres_pool_min_size:
        postgres_config_errors += (
            "DIET_BOT_POSTGRES_POOL_MAX_SIZE must be greater than or equal to "
            "DIET_BOT_POSTGRES_POOL_MIN_SIZE.",
        )
    state_file = _path_from_env(source, "DIET_BOT_STATE_FILE", DEFAULT_STATE_FILE)
    subscriptions_state_file = _path_from_env(
        source,
        "DIET_BOT_SUBSCRIPTIONS_STATE_FILE",
        DEFAULT_SUBSCRIPTIONS_STATE_FILE,
    )
    promo_codes_state_file = _path_from_env(
        source,
        "DIET_BOT_PROMO_CODES_STATE_FILE",
        DEFAULT_PROMO_CODES_STATE_FILE,
    )
    payment_recovery_spool, payment_recovery_spool_configured = _path_from_env_with_configured(
        source,
        PAYMENT_RECOVERY_SPOOL_ENV,
        subscriptions_state_file.with_name("payment_recovery.jsonl"),
    )
    one_day_worker_concurrency, worker_concurrency_errors = _int_from_env(
        source,
        "DIET_BOT_ONE_DAY_WORKER_CONCURRENCY",
        DEFAULT_ONE_DAY_WORKER_CONCURRENCY,
        minimum=1,
    )
    one_day_worker_lease_seconds, worker_lease_errors = _int_from_env(
        source,
        "DIET_BOT_ONE_DAY_WORKER_LEASE_SECONDS",
        DEFAULT_ONE_DAY_WORKER_LEASE_SECONDS,
        minimum=1,
    )
    one_day_worker_heartbeat_seconds, worker_heartbeat_errors = _int_from_env(
        source,
        "DIET_BOT_ONE_DAY_WORKER_HEARTBEAT_SECONDS",
        DEFAULT_ONE_DAY_WORKER_HEARTBEAT_SECONDS,
        minimum=1,
    )
    one_day_worker_retry_delay_seconds, worker_retry_errors = _int_from_env(
        source,
        "DIET_BOT_ONE_DAY_WORKER_RETRY_DELAY_SECONDS",
        DEFAULT_ONE_DAY_WORKER_RETRY_DELAY_SECONDS,
        minimum=0,
    )
    one_day_worker_max_attempts, worker_attempts_errors = _int_from_env(
        source,
        "DIET_BOT_ONE_DAY_WORKER_MAX_ATTEMPTS",
        DEFAULT_ONE_DAY_WORKER_MAX_ATTEMPTS,
        minimum=1,
    )
    one_day_worker_idle_sleep_seconds, worker_idle_errors = _float_from_env(
        source,
        "DIET_BOT_ONE_DAY_WORKER_IDLE_SLEEP_SECONDS",
        DEFAULT_ONE_DAY_WORKER_IDLE_SLEEP_SECONDS,
        minimum=0.1,
    )
    worker_config_errors = (
        worker_concurrency_errors
        + worker_lease_errors
        + worker_heartbeat_errors
        + worker_retry_errors
        + worker_attempts_errors
        + worker_idle_errors
    )
    weekly_pdf_worker_concurrency, weekly_pdf_worker_concurrency_errors = _int_from_env(
        source,
        "DIET_BOT_WEEKLY_PDF_WORKER_CONCURRENCY",
        DEFAULT_WEEKLY_PDF_WORKER_CONCURRENCY,
        minimum=1,
    )
    weekly_pdf_worker_lease_seconds, weekly_pdf_worker_lease_errors = _int_from_env(
        source,
        "DIET_BOT_WEEKLY_PDF_WORKER_LEASE_SECONDS",
        DEFAULT_WEEKLY_PDF_WORKER_LEASE_SECONDS,
        minimum=1,
    )
    weekly_pdf_worker_heartbeat_seconds, weekly_pdf_worker_heartbeat_errors = _int_from_env(
        source,
        "DIET_BOT_WEEKLY_PDF_WORKER_HEARTBEAT_SECONDS",
        DEFAULT_WEEKLY_PDF_WORKER_HEARTBEAT_SECONDS,
        minimum=1,
    )
    weekly_pdf_worker_retry_delay_seconds, weekly_pdf_worker_retry_errors = _int_from_env(
        source,
        "DIET_BOT_WEEKLY_PDF_WORKER_RETRY_DELAY_SECONDS",
        DEFAULT_WEEKLY_PDF_WORKER_RETRY_DELAY_SECONDS,
        minimum=0,
    )
    weekly_pdf_worker_max_attempts, weekly_pdf_worker_attempts_errors = _int_from_env(
        source,
        "DIET_BOT_WEEKLY_PDF_WORKER_MAX_ATTEMPTS",
        DEFAULT_WEEKLY_PDF_WORKER_MAX_ATTEMPTS,
        minimum=1,
    )
    weekly_pdf_worker_idle_sleep_seconds, weekly_pdf_worker_idle_errors = _float_from_env(
        source,
        "DIET_BOT_WEEKLY_PDF_WORKER_IDLE_SLEEP_SECONDS",
        DEFAULT_WEEKLY_PDF_WORKER_IDLE_SLEEP_SECONDS,
        minimum=0.1,
    )
    weekly_pdf_worker_config_errors = (
        weekly_pdf_worker_concurrency_errors
        + weekly_pdf_worker_lease_errors
        + weekly_pdf_worker_heartbeat_errors
        + weekly_pdf_worker_retry_errors
        + weekly_pdf_worker_attempts_errors
        + weekly_pdf_worker_idle_errors
    )

    return RuntimeConfig(
        bot_token=bot_token,
        bot_token_source=bot_token_source,
        environment=environment,
        payments_enabled=_text_from_env(source, "DIET_BOT_PAYMENTS_ENABLED") == "1",
        public_payments_enabled=_public_payments_enabled_from_env(source),
        payment_test_prices_enabled=_bool_from_env(source, "DIET_BOT_PAYMENT_TEST_PRICES_ENABLED"),
        telegram_provider_token=_text_from_env(source, "TELEGRAM_PROVIDER_TOKEN") or "",
        database_url=_text_from_env(source, "DIET_BOT_DATABASE_URL"),
        postgres_pool_enabled=_bool_from_env(source, "DIET_BOT_POSTGRES_POOL_ENABLED"),
        postgres_connect_timeout=postgres_connect_timeout,
        postgres_pool_min_size=postgres_pool_min_size,
        postgres_pool_max_size=postgres_pool_max_size,
        postgres_pool_timeout=postgres_pool_timeout,
        state_file=state_file,
        subscriptions_state_file=subscriptions_state_file,
        promo_codes_state_file=promo_codes_state_file,
        payment_recovery_spool=payment_recovery_spool,
        payment_recovery_spool_configured=payment_recovery_spool_configured,
        support_chat_id=_optional_int_from_env(source, "DIET_BOT_SUPPORT_CHAT_ID"),
        admin_user_ids=frozenset(_parse_id_set(source.get("DIET_BOT_ADMIN_USER_IDS"))),
        tester_chat_ids=frozenset(_parse_id_set(source.get("DIET_BOT_TESTER_CHAT_IDS"))),
        weekly_selection_diagnostics_enabled=weekly_selection_diagnostics_enabled(source),
        privacy_policy_url=_text_from_env(source, "DIET_BOT_PRIVACY_POLICY_URL"),
        one_day_worker_enabled=_bool_from_env(source, "DIET_BOT_ONE_DAY_WORKER_ENABLED"),
        one_day_worker_concurrency=one_day_worker_concurrency,
        one_day_worker_lease_seconds=one_day_worker_lease_seconds,
        one_day_worker_heartbeat_seconds=one_day_worker_heartbeat_seconds,
        one_day_worker_retry_delay_seconds=one_day_worker_retry_delay_seconds,
        one_day_worker_max_attempts=one_day_worker_max_attempts,
        one_day_worker_idle_sleep_seconds=one_day_worker_idle_sleep_seconds,
        weekly_pdf_worker_enabled=_bool_from_env(source, "DIET_BOT_WEEKLY_PDF_WORKER_ENABLED"),
        weekly_pdf_worker_concurrency=weekly_pdf_worker_concurrency,
        weekly_pdf_worker_lease_seconds=weekly_pdf_worker_lease_seconds,
        weekly_pdf_worker_heartbeat_seconds=weekly_pdf_worker_heartbeat_seconds,
        weekly_pdf_worker_retry_delay_seconds=weekly_pdf_worker_retry_delay_seconds,
        weekly_pdf_worker_max_attempts=weekly_pdf_worker_max_attempts,
        weekly_pdf_worker_idle_sleep_seconds=weekly_pdf_worker_idle_sleep_seconds,
        storage_backend=storage_backend,
        config_errors=postgres_config_errors + worker_config_errors + weekly_pdf_worker_config_errors,
    )


def validate_startup(config: RuntimeConfig) -> tuple[str, ...]:
    return config.validate_startup()


def validate_strict_production(config: RuntimeConfig) -> tuple[str, ...]:
    return config.validate_strict_production()


def safe_summary(config: RuntimeConfig) -> dict[str, object]:
    return config.safe_summary()


def weekly_selection_diagnostics_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    raw = _text_from_env(source, "DIET_BOT_WEEKLY_SELECTION_DIAG")
    return bool(raw and raw.lower() in _TRUTHY_VALUES)


def _public_payments_enabled_from_env(env: Mapping[str, str]) -> bool:
    raw = _text_from_env(env, "DIET_BOT_PUBLIC_PAYMENTS_ENABLED")
    if raw is None:
        return _text_from_env(env, "DIET_BOT_PAYMENTS_ENABLED") == "1"
    return raw.lower() in _TRUTHY_VALUES


def _bool_from_env(env: Mapping[str, str], key: str) -> bool:
    raw = _text_from_env(env, key)
    return bool(raw and raw.lower() in _TRUTHY_VALUES)


def _int_from_env(
    env: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int,
) -> tuple[int, tuple[str, ...]]:
    raw = _text_from_env(env, key)
    if raw is None:
        return default, ()
    try:
        value = int(raw)
    except ValueError:
        return default, (f"{key} must be an integer greater than or equal to {minimum}.",)
    if value < minimum:
        return default, (f"{key} must be an integer greater than or equal to {minimum}.",)
    return value, ()


def _float_from_env(
    env: Mapping[str, str],
    key: str,
    default: float,
    *,
    minimum: float,
) -> tuple[float, tuple[str, ...]]:
    raw = _text_from_env(env, key)
    if raw is None:
        return default, ()
    try:
        value = float(raw)
    except ValueError:
        return default, (f"{key} must be greater than or equal to {minimum:g}.",)
    if value < minimum:
        return default, (f"{key} must be greater than or equal to {minimum:g}.",)
    return value, ()


def parse_id_set(raw: str | None) -> set[int]:
    return _parse_id_set(raw)


def parse_optional_int(raw: str | None) -> int | None:
    return _parse_optional_int(raw)


def is_production_environment(environment: str | None) -> bool:
    return (environment or "").strip().lower() in _PRODUCTION_ENVIRONMENTS


def _bot_token_from_env(env: Mapping[str, str]) -> tuple[str | None, str | None]:
    diet_bot_token = _text_from_env(env, "DIET_BOT_TOKEN")
    if diet_bot_token:
        return diet_bot_token, "DIET_BOT_TOKEN"

    telegram_bot_token = _text_from_env(env, "TELEGRAM_BOT_TOKEN")
    if telegram_bot_token:
        return telegram_bot_token, "TELEGRAM_BOT_TOKEN"

    return None, None


def _environment_from_env(env: Mapping[str, str]) -> str:
    return (_text_from_env(env, "DIET_BOT_ENV") or "development").lower()


def _storage_backend_from_env(env: Mapping[str, str], environment: str) -> tuple[str, tuple[str, ...]]:
    raw = _text_from_env(env, "DIET_BOT_STORAGE_BACKEND")
    if raw is None:
        return ("postgres" if is_production_environment(environment) else "json"), ()

    backend = raw.lower()
    if backend in _VALID_STORAGE_BACKENDS:
        return backend, ()
    return backend, ("DIET_BOT_STORAGE_BACKEND must be 'json' or 'postgres'.",)


def _text_from_env(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _path_from_env(env: Mapping[str, str], key: str, default: Path) -> Path:
    value = _text_from_env(env, key)
    return Path(value) if value is not None else default


def _path_from_env_with_configured(env: Mapping[str, str], key: str, default: Path) -> tuple[Path, bool]:
    value = _text_from_env(env, key)
    if value is None:
        return default, False
    return Path(value), True


def _optional_int_from_env(env: Mapping[str, str], key: str) -> int | None:
    return _parse_optional_int(env.get(key))


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _is_valid_http_url(raw: str | None) -> bool:
    if raw is None:
        return False
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _parse_id_set(raw: str | None) -> set[int]:
    ids: set[int] = set()
    for item in re.split(r"[\s,;]+", raw or ""):
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            continue
    return ids
