from __future__ import annotations

from urllib.parse import urlparse


_PLACEHOLDER_MARKERS = (
    "YOUR_",
    "CHANGE_ME",
    "CHANGEME",
    "REPLACE_ME",
    "REPLACEME",
    "TODO",
    "PASSWORD_HERE",
    "TOKEN_HERE",
)

_BOT_TOKEN_EXAMPLE_MARKERS = (
    "TELEGRAM-TOKEN",
    "BOT-TOKEN",
)

PRODUCTION_ENV_NAMES = {"prod", "production"}

_FORBIDDEN_PUBLIC_URL_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "example.com",
    "example.org",
}


def _contains_placeholder(value: str, markers: tuple[str, ...]) -> bool:
    normalized = value.strip().upper()
    return any(marker in normalized for marker in markers)


def is_production_environment(environment: str | None) -> bool:
    return (environment or "").strip().lower() in PRODUCTION_ENV_NAMES


def parse_support_chat_id(value: str | None) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        chat_id = int(text)
    except ValueError:
        return None
    if chat_id == 0:
        return None
    return chat_id


def is_public_https_url(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False

    parsed = urlparse(text)
    if parsed.scheme != "https":
        return False
    if not parsed.netloc:
        return False

    hostname = (parsed.hostname or "").lower()
    if hostname in _FORBIDDEN_PUBLIC_URL_HOSTS:
        return False
    if hostname.endswith(".local"):
        return False
    return True


def validate_database_url(database_url: str) -> list[str]:
    if not database_url.strip():
        return []
    if _contains_placeholder(database_url, _PLACEHOLDER_MARKERS):
        return [
            "DIET_BOT_DATABASE_URL contains an example placeholder. "
            "Replace it with the real PostgreSQL connection string."
        ]
    return []


def validate_bot_token(token: str) -> list[str]:
    if not token.strip():
        return ["Telegram bot token is missing. Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN."]
    if _contains_placeholder(token, _PLACEHOLDER_MARKERS + _BOT_TOKEN_EXAMPLE_MARKERS):
        return [
            "Telegram bot token looks like an example placeholder. "
            "Set a real DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN."
        ]
    return []


def validate_support_chat_id(value: str | None, *, required: bool = False) -> list[str]:
    text = (value or "").strip()
    if not text:
        if required:
            return ["DIET_BOT_SUPPORT_CHAT_ID is required in production."]
        return []
    try:
        chat_id = int(text)
    except ValueError:
        return ["DIET_BOT_SUPPORT_CHAT_ID must be an integer."]
    if chat_id == 0:
        return ["DIET_BOT_SUPPORT_CHAT_ID cannot be 0."]
    return []


def validate_privacy_policy_url(value: str | None, *, required: bool = False) -> list[str]:
    text = (value or "").strip()
    if not text:
        if required:
            return ["DIET_BOT_PRIVACY_POLICY_URL is required in production."]
        return []
    if not is_public_https_url(text):
        return ["DIET_BOT_PRIVACY_POLICY_URL must be a public HTTPS URL in production."]
    return []


def validate_posthog_host(value: str | None, *, required: bool = False) -> list[str]:
    text = (value or "").strip()
    if not text:
        if required:
            return ["POSTHOG_HOST is required in production when POSTHOG_API_KEY is set."]
        return []
    if not is_public_https_url(text):
        return ["POSTHOG_HOST must be a public HTTPS URL in production."]
    return []


def validate_production_runtime_config(
    *,
    environment: str | None,
    support_chat_id: str | None,
    privacy_policy_url: str | None,
    posthog_api_key: str | None = None,
    posthog_host: str | None = None,
) -> list[str]:
    if not is_production_environment(environment):
        return []

    errors: list[str] = []
    errors.extend(validate_support_chat_id(support_chat_id, required=True))
    errors.extend(validate_privacy_policy_url(privacy_policy_url, required=True))
    if (posthog_api_key or "").strip():
        errors.extend(validate_posthog_host(posthog_host, required=True))
    return errors
