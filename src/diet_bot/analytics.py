from __future__ import annotations

import json
import logging
import os
import urllib.request
from hashlib import sha256
import hmac
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from .runtime_config import is_production_environment, is_public_https_url


logger = logging.getLogger(__name__)

DEFAULT_POSTHOG_HOST = "https://app.posthog.com"
DEFAULT_POSTHOG_TIMEOUT_SECONDS = 2.0
DEFAULT_ANALYTICS_ID_SALT = "diet-bot-analytics-v1"
MAX_EVENT_NAME_LENGTH = 100
MAX_PROPERTY_KEY_LENGTH = 80
MAX_STRING_VALUE_LENGTH = 300
MAX_COLLECTION_ITEMS = 25
MAX_NESTING_DEPTH = 3

SENSITIVE_KEY_MARKERS = (
    "answer",
    "card",
    "charge_id",
    "email",
    "first_name",
    "full_name",
    "health",
    "last_name",
    "medical",
    "message",
    "order_id",
    "password",
    "payload",
    "phone",
    "profile",
    "raw",
    "secret",
    "telegram_id",
    "text",
    "token",
    "user_id",
    "username",
)


class AnalyticsStore(Protocol):
    def record_analytics_event(
        self,
        user_id: int | None,
        event_name: str,
        properties: dict[str, object],
    ) -> None:
        ...


@dataclass(frozen=True)
class AnalyticsConfig:
    enabled: bool
    posthog_api_key: str = ""
    posthog_host: str = DEFAULT_POSTHOG_HOST
    timeout_seconds: float = DEFAULT_POSTHOG_TIMEOUT_SECONDS
    distinct_id_salt: str = DEFAULT_ANALYTICS_ID_SALT

    @classmethod
    def from_env(cls) -> AnalyticsConfig:
        posthog_api_key = os.getenv("POSTHOG_API_KEY", "").strip()
        posthog_host = os.getenv("POSTHOG_HOST", DEFAULT_POSTHOG_HOST).strip() or DEFAULT_POSTHOG_HOST
        distinct_id_salt = os.getenv("DIET_BOT_ANALYTICS_ID_SALT", "").strip() or DEFAULT_ANALYTICS_ID_SALT
        if posthog_api_key and _production_posthog_host_invalid(posthog_host):
            logger.error("Invalid POSTHOG_HOST; PostHog analytics will be skipped.")
            posthog_api_key = ""
        return cls(
            enabled=_env_bool("DIET_BOT_ANALYTICS_ENABLED", default=False),
            posthog_api_key=posthog_api_key,
            posthog_host=posthog_host,
            distinct_id_salt=distinct_id_salt,
        )


@dataclass(frozen=True)
class PreparedAnalyticsEvent:
    name: str
    properties: dict[str, object]


def track_event(
    user_id: int | None,
    event_name: str,
    properties: dict[str, object] | None = None,
    *,
    store: AnalyticsStore | None = None,
    config: AnalyticsConfig | None = None,
) -> None:
    active_config = config or AnalyticsConfig.from_env()
    if not active_config.enabled:
        return

    prepared_event = prepare_analytics_event(event_name, properties)
    if prepared_event is None:
        return

    if store is not None:
        record_event_in_store(store, user_id, prepared_event)

    send_event_to_posthog(active_config, user_id, prepared_event)


def prepare_analytics_event(
    event_name: str,
    properties: dict[str, object] | None = None,
) -> PreparedAnalyticsEvent | None:
    normalized_event_name = _normalize_event_name(event_name)
    if not normalized_event_name:
        return None
    return PreparedAnalyticsEvent(normalized_event_name, sanitize_properties(properties or {}))


def record_event_in_store(
    store: AnalyticsStore,
    user_id: int | None,
    event: PreparedAnalyticsEvent,
) -> None:
    try:
        store.record_analytics_event(user_id, event.name, event.properties)
    except Exception:
        logger.exception("Could not record analytics event in PostgreSQL.", extra={"event_name": event.name})


def send_event_to_posthog(
    config: AnalyticsConfig,
    user_id: int | None,
    event: PreparedAnalyticsEvent,
) -> None:
    if not config.posthog_api_key:
        return
    if _production_posthog_host_invalid(config.posthog_host):
        logger.error("Invalid POSTHOG_HOST; PostHog analytics will be skipped.", extra={"event_name": event.name})
        return
    try:
        _send_posthog_event(config, user_id, event.name, event.properties)
    except Exception:
        logger.exception("Could not send analytics event to PostHog.", extra={"event_name": event.name})


def sanitize_properties(properties: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for raw_key, raw_value in properties.items():
        key = str(raw_key).strip()
        if not key or _is_sensitive_key(key):
            continue
        sanitized = _sanitize_value(raw_value, depth=0)
        if sanitized is not None:
            safe[key[:MAX_PROPERTY_KEY_LENGTH]] = sanitized
    return safe


def pseudonymous_identifier(
    value: object | None,
    *,
    salt: str = DEFAULT_ANALYTICS_ID_SALT,
    prefix: str = "id",
) -> str:
    if value is None:
        return f"{prefix}_anonymous"
    normalized_salt = str(salt or DEFAULT_ANALYTICS_ID_SALT).encode("utf-8")
    normalized_value = str(value).encode("utf-8")
    digest = hmac.new(normalized_salt, normalized_value, sha256).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _send_posthog_event(
    config: AnalyticsConfig,
    user_id: int | None,
    event_name: str,
    properties: dict[str, object],
) -> None:
    endpoint = f"{config.posthog_host.rstrip('/')}/capture/"
    payload = {
        "api_key": config.posthog_api_key,
        "event": event_name,
        "distinct_id": pseudonymous_identifier(user_id, salt=config.distinct_id_salt, prefix="tg"),
        "properties": properties,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
        response.read()


def _normalize_event_name(event_name: str) -> str:
    return str(event_name).strip()[:MAX_EVENT_NAME_LENGTH]


def _sanitize_value(value: object, *, depth: int) -> object | None:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        return text[:MAX_STRING_VALUE_LENGTH] if text else None
    if depth >= MAX_NESTING_DEPTH:
        return None
    if isinstance(value, dict):
        nested: dict[str, object] = {}
        for raw_key, raw_value in list(value.items())[:MAX_COLLECTION_ITEMS]:
            key = str(raw_key).strip()
            if not key or _is_sensitive_key(key):
                continue
            sanitized = _sanitize_value(raw_value, depth=depth + 1)
            if sanitized is not None:
                nested[key[:MAX_PROPERTY_KEY_LENGTH]] = sanitized
        return nested or None
    if isinstance(value, list | tuple):
        nested_values = [
            sanitized
            for item in value[:MAX_COLLECTION_ITEMS]
            if (sanitized := _sanitize_value(item, depth=depth + 1)) is not None
        ]
        return nested_values or None
    return str(value)[:MAX_STRING_VALUE_LENGTH]


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _runtime_environment() -> str:
    return os.getenv("DIET_BOT_ENV", os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")))


def _production_posthog_host_invalid(posthog_host: str) -> bool:
    return is_production_environment(_runtime_environment()) and not is_public_https_url(posthog_host)
