from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"

REQUIRED_SECTIONS = (
    "Telegram",
    "Storage/Postgres",
    "Workers/Queues",
    "Payments",
    "Promo/Admin",
    "Privacy/Support",
    "Monitoring/Ops",
    "Local/dev only",
)

REQUIRED_PRODUCTION_ENV_VARS = {
    "DIET_BOT_ENV",
    "DIET_BOT_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "DIET_BOT_STORAGE_BACKEND",
    "DIET_BOT_ALLOW_JSON_STORAGE",
    "DIET_BOT_DATABASE_URL",
    "DIET_BOT_ONE_DAY_WORKER_ENABLED",
    "DIET_BOT_WEEKLY_PDF_WORKER_ENABLED",
    "DIET_BOT_SUPPORT_CHAT_ID",
    "DIET_BOT_PRIVACY_POLICY_URL",
    "DIET_BOT_PAYMENTS_ENABLED",
    "DIET_BOT_PUBLIC_PAYMENTS_ENABLED",
    "DIET_BOT_PAYMENT_TEST_PRICES_ENABLED",
    "TELEGRAM_PROVIDER_TOKEN",
    "DIET_BOT_PAYMENT_RECOVERY_SPOOL",
}

SECRET_VALUE_PATTERNS = (
    re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$"),
    re.compile(r"^postgres(?:ql)?://[^:\s]+:[^@\s]+@", flags=re.IGNORECASE),
    re.compile(r"^(?:live|test)_[A-Za-z0-9_-]{16,}$", flags=re.IGNORECASE),
)


def _env_text() -> str:
    return ENV_EXAMPLE.read_text(encoding="utf-8")


def _assignments(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file()


def test_env_example_documents_required_production_vars() -> None:
    values = _assignments(_env_text())

    missing = sorted(REQUIRED_PRODUCTION_ENV_VARS - values.keys())

    assert missing == []
    assert values["DIET_BOT_STORAGE_BACKEND"] == "postgres"
    assert values["DIET_BOT_ALLOW_JSON_STORAGE"] == "0"
    assert values["DIET_BOT_ONE_DAY_WORKER_ENABLED"] == "1"
    assert values["DIET_BOT_WEEKLY_PDF_WORKER_ENABLED"] == "1"


def test_env_example_keeps_expected_operator_sections() -> None:
    text = _env_text()

    for section in REQUIRED_SECTIONS:
        assert f"# {section}" in text


def test_env_example_documents_promo_postgres_requirement() -> None:
    text = _env_text()

    assert "Postgres promo store" in text
    assert "JSON promo state" in text
    assert "import seed/local fallback" in text


def test_env_example_does_not_contain_real_looking_secret_values() -> None:
    values = _assignments(_env_text())
    real_looking = {
        key: value
        for key, value in values.items()
        if value and any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS)
    }

    assert real_looking == {}
