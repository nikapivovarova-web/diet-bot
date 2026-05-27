from __future__ import annotations

import argparse
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .chat_state_runtime import validate_chat_state_store_for_startup
from .entitlement_runtime import create_entitlement_store, validate_entitlement_store_for_startup
from .one_day_generation_job_runtime import validate_one_day_generation_job_store_for_startup
from .payment_recovery_spool import validate_payment_recovery_spool_ready
from .runtime_config import (
    RuntimeConfig,
    is_production_environment,
    load_runtime_config,
    validate_startup,
    validate_strict_production,
)
from .weekly_pdf_job_runtime import validate_weekly_pdf_job_runtime_for_startup


PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

_POSTGRES_DSN_RE = re.compile(r"\bpostgres(?:ql)?://[^\s\"'<>]+", flags=re.IGNORECASE)
_CONTROLLED_QA_ENVIRONMENTS = {
    "controlled-qa",
    "qa",
    "staging",
    "stage",
    "test",
    "testing",
    "local",
    "development",
    "dev",
    "sandbox",
}
_CONTROLLED_QA_BOT_TOKEN_MARKER_ENV = "DIET_BOT_CONTROLLED_QA_BOT_TOKEN_MARKER"
_CONTROLLED_QA_BOT_TOKEN_MARKERS = {"test", "sandbox"}
_CONTROLLED_QA_DATABASE_MARKER_ENV = "DIET_BOT_CONTROLLED_QA_DATABASE_MARKER"
_CONTROLLED_QA_DATABASE_MARKERS = {"local", "staging", "stage", "test", "testing", "throwaway", "sandbox"}
_PAYMENTS_DISABLED_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    messages: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return self.status == FAIL


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run safe readiness checks without starting the Telegram bot, "
            "poller, or Telegram API clients."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("production", "controlled-qa"),
        default="production",
        help="Readiness profile to run. The default preserves the production preflight behavior.",
    )
    args = parser.parse_args(argv)

    source = os.environ if env is None else env
    config = load_runtime_config(source)
    secrets = _secret_values(config, source)
    if args.mode == "controlled-qa":
        title = "controlled QA preflight"
        checks = run_controlled_qa_preflight(config, env=source, secrets=secrets)
    else:
        title = "production preflight"
        checks = run_preflight(config, secrets=secrets)

    print(title)
    print(f"environment={config.environment}")
    print(f"storage_backend={config.storage_backend}")
    if args.mode == "controlled-qa":
        print(f"bot_token_marker={_marker_status(source, _CONTROLLED_QA_BOT_TOKEN_MARKER_ENV)}")
        print(f"database_marker={_marker_status(source, _CONTROLLED_QA_DATABASE_MARKER_ENV)}")
        print(f"tester_chat_ids_count={len(config.tester_chat_ids)}")
    print("checks:")
    for check in checks:
        print(f"{check.status} {check.name}")
        for message in check.messages:
            print(f"  - {message}")

    failed = any(check.failed for check in checks)
    print(f"result: {FAIL if failed else PASS}")
    return 1 if failed else 0


def run_preflight(
    config: RuntimeConfig,
    *,
    secrets: frozenset[str] | None = None,
) -> tuple[PreflightCheck, ...]:
    redaction_values = secrets or frozenset()
    runtime_issues = _production_runtime_issues(config)
    if runtime_issues:
        return (
            PreflightCheck(
                "runtime config",
                FAIL,
                tuple(_redact_text(issue, redaction_values) for issue in runtime_issues),
            ),
        )

    checks: list[PreflightCheck] = [
        PreflightCheck("runtime config", PASS),
        _check("Postgres connectivity", lambda: _validate_postgres_connectivity(config), redaction_values),
        _check("chat state schema", lambda: validate_chat_state_store_for_startup(config), redaction_values),
        _check(
            "entitlement schema",
            lambda: validate_entitlement_store_for_startup(config, create_entitlement_store(config)),
            redaction_values,
        ),
        _check(
            "weekly PDF job schema",
            lambda: validate_weekly_pdf_job_runtime_for_startup(config),
            redaction_values,
        ),
        _check(
            "one-day generation job schema",
            lambda: validate_one_day_generation_job_store_for_startup(config),
            redaction_values,
        ),
        _check("payment ledger schema", lambda: _validate_payment_ledger_schema(config), redaction_values),
    ]

    if config.payments_enabled or config.payment_recovery_spool_configured:
        checks.append(
            _check(
                "payment recovery spool readiness",
                lambda: validate_payment_recovery_spool_ready(config.payment_recovery_spool),
                redaction_values,
            ),
        )
    else:
        checks.append(
            PreflightCheck(
                "payment recovery spool readiness",
                SKIP,
                (
                    "payments are disabled and DIET_BOT_PAYMENT_RECOVERY_SPOOL is not configured; "
                    "no recovery spool was probed.",
                ),
            ),
        )

    checks.append(
        _check(
            "single-poller guard acquire/release",
            lambda: _validate_single_poller_guard(config),
            redaction_values,
        ),
    )
    return tuple(checks)


def run_controlled_qa_preflight(
    config: RuntimeConfig,
    *,
    env: Mapping[str, str],
    secrets: frozenset[str] | None = None,
) -> tuple[PreflightCheck, ...]:
    redaction_values = secrets or frozenset()
    runtime_issues = _controlled_qa_runtime_issues(config, env)
    if runtime_issues:
        return (
            PreflightCheck(
                "controlled QA runtime config",
                FAIL,
                tuple(_redact_text(issue, redaction_values) for issue in runtime_issues),
            ),
        )

    checks: list[PreflightCheck] = [
        PreflightCheck(
            "controlled QA runtime config",
            PASS,
            (
                "test bot token marker is present",
                "non-production database marker is present",
                "payments disabled and provider token absent",
                f"tester_chat_ids_count={len(config.tester_chat_ids)}",
            ),
        ),
        _check("Postgres connectivity", lambda: _validate_postgres_connectivity(config), redaction_values),
        _check("chat state schema", lambda: validate_chat_state_store_for_startup(config), redaction_values),
        _check(
            "entitlement schema",
            lambda: validate_entitlement_store_for_startup(config, create_entitlement_store(config)),
            redaction_values,
        ),
        _check(
            "weekly PDF job schema",
            lambda: validate_weekly_pdf_job_runtime_for_startup(config),
            redaction_values,
        ),
        _check(
            "one-day generation job schema",
            lambda: validate_one_day_generation_job_store_for_startup(config),
            redaction_values,
        ),
        _check("payment ledger schema", lambda: _validate_payment_ledger_schema(config), redaction_values),
        _check(
            "single-poller guard acquire/release",
            lambda: _validate_single_poller_guard(config),
            redaction_values,
        ),
    ]
    return tuple(checks)


def _production_runtime_issues(config: RuntimeConfig) -> tuple[str, ...]:
    issues: list[str] = []
    if not is_production_environment(config.environment):
        issues.append("DIET_BOT_ENV must be production or prod for production preflight.")
    issues.extend(validate_startup(config))
    issues.extend(validate_strict_production(config))
    if config.payments_enabled and not config.telegram_provider_token.strip():
        issues.append("TELEGRAM_PROVIDER_TOKEN is required when payments are enabled in production.")
    return _dedupe(issues)


def _controlled_qa_runtime_issues(config: RuntimeConfig, env: Mapping[str, str]) -> tuple[str, ...]:
    issues: list[str] = []
    raw_environment = _normalized_env_value(env, "DIET_BOT_ENV")
    if raw_environment is None:
        issues.append(
            "DIET_BOT_ENV must be set explicitly to controlled-qa, qa, staging, test, testing, "
            "local, or development for controlled QA.",
        )
    elif is_production_environment(config.environment):
        issues.append("DIET_BOT_ENV must not be production or prod for controlled QA.")
    elif config.environment not in _CONTROLLED_QA_ENVIRONMENTS:
        issues.append("DIET_BOT_ENV must identify a non-production QA environment for controlled QA.")

    issues.extend(validate_startup(config))

    if config.storage_backend != "postgres":
        issues.append(
            "Controlled QA requires DIET_BOT_STORAGE_BACKEND=postgres with an isolated non-production database.",
        )
    if not config.database_url:
        issues.append("DIET_BOT_DATABASE_URL is required for controlled QA Postgres storage.")

    payments_raw = _normalized_env_value(env, "DIET_BOT_PAYMENTS_ENABLED")
    if payments_raw is not None and payments_raw not in _PAYMENTS_DISABLED_VALUES:
        issues.append("DIET_BOT_PAYMENTS_ENABLED must be unset or disabled for controlled QA.")
    if config.telegram_provider_token.strip():
        issues.append("TELEGRAM_PROVIDER_TOKEN must be absent for controlled QA.")

    if _normalized_env_value(env, _CONTROLLED_QA_BOT_TOKEN_MARKER_ENV) not in _CONTROLLED_QA_BOT_TOKEN_MARKERS:
        issues.append(
            f"{_CONTROLLED_QA_BOT_TOKEN_MARKER_ENV} must be set to test or sandbox for controlled QA.",
        )
    if _normalized_env_value(env, _CONTROLLED_QA_DATABASE_MARKER_ENV) not in _CONTROLLED_QA_DATABASE_MARKERS:
        issues.append(
            f"{_CONTROLLED_QA_DATABASE_MARKER_ENV} must be set to local, staging, test, testing, "
            "throwaway, or sandbox for controlled QA.",
        )
    if not config.tester_chat_ids:
        issues.append("DIET_BOT_TESTER_CHAT_IDS must contain at least one tester chat ID for controlled QA.")
    return _dedupe(issues)


def _check(
    name: str,
    validator: Callable[[], None],
    secrets: frozenset[str],
) -> PreflightCheck:
    try:
        validator()
    except Exception as exc:
        message = _redact_text(str(exc) or exc.__class__.__name__, secrets)
        return PreflightCheck(name, FAIL, (message,))
    return PreflightCheck(name, PASS)


def _validate_postgres_connectivity(config: RuntimeConfig) -> None:
    if config.storage_backend != "postgres":
        raise RuntimeError("Production preflight requires DIET_BOT_STORAGE_BACKEND=postgres.")
    if not config.database_url:
        raise RuntimeError("DIET_BOT_DATABASE_URL is required for Postgres connectivity preflight.")

    try:
        import psycopg
        from psycopg.conninfo import make_conninfo
    except Exception as exc:
        raise RuntimeError("psycopg is required for Postgres connectivity preflight.") from exc

    try:
        database_url = make_conninfo(config.database_url, connect_timeout="5")
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                row = cur.fetchone()
        if row is None or row[0] != 1:
            raise RuntimeError("Postgres connectivity probe returned an unexpected result.")
    except Exception as exc:
        raise RuntimeError(
            "Could not connect to Postgres using DIET_BOT_DATABASE_URL; "
            "verify network access, credentials, database name, and search_path.",
        ) from exc


def _validate_payment_ledger_schema(config: RuntimeConfig) -> None:
    if config.storage_backend != "postgres":
        raise RuntimeError("Payment ledger schema preflight requires Postgres storage.")
    if not config.database_url:
        raise RuntimeError("DIET_BOT_DATABASE_URL is required for payment ledger schema preflight.")

    from .postgres_payment_store import PostgresPaymentStore

    PostgresPaymentStore(config.database_url).validate_schema()


def _validate_single_poller_guard(config: RuntimeConfig) -> None:
    if config.storage_backend != "postgres":
        raise RuntimeError("Single-poller guard preflight requires Postgres storage.")
    if not config.database_url:
        raise RuntimeError("DIET_BOT_DATABASE_URL is required for single-poller guard preflight.")

    from .postgres_single_poller_guard import PostgresSinglePollerGuard

    guard = PostgresSinglePollerGuard(config.database_url).acquire()
    try:
        pass
    finally:
        guard.close()


def _secret_values(config: RuntimeConfig, env: Mapping[str, str]) -> frozenset[str]:
    candidates = {
        config.bot_token,
        config.database_url,
        config.telegram_provider_token,
        env.get("DIET_BOT_TOKEN"),
        env.get("TELEGRAM_BOT_TOKEN"),
        env.get("DIET_BOT_DATABASE_URL"),
        env.get("TELEGRAM_PROVIDER_TOKEN"),
    }
    return frozenset(value for value in candidates if value and len(value) >= 4)


def _normalized_env_value(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _marker_status(env: Mapping[str, str], key: str) -> str:
    return "set" if _normalized_env_value(env, key) else "missing"


def _redact_text(text: str, secrets: frozenset[str]) -> str:
    redacted = text
    for secret in sorted(secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, "<redacted>")
    return _POSTGRES_DSN_RE.sub("postgresql://<redacted>", redacted)


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)
