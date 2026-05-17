from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


ANALYTICS_EVENT_BOT_START = "bot_start"
ANALYTICS_EVENT_QUESTIONNAIRE_COMPLETED = "questionnaire_completed"
ANALYTICS_EVENT_PAYWALL_SHOWN = "paywall_shown"
ANALYTICS_EVENT_INVOICE_CREATED = "invoice_created"
ANALYTICS_EVENT_PAYMENT_SUCCESS = "payment_success"
ANALYTICS_EVENT_RATION_DELIVERED = "ration_delivered"
ANALYTICS_EVENT_WEEKLY_PDF_DELIVERED = "weekly_pdf_delivered"
ANALYTICS_EVENT_PROMO_APPLIED = "promo_applied"
ANALYTICS_EVENT_STARS_AUTO_RENEW_CANCELED = "stars_auto_renew_canceled"
ANALYTICS_EVENT_STARS_AUTO_RENEW_REENABLED = "stars_auto_renew_reenabled"

_MAX_CAMPAIGN_TEXT_LENGTH = 128
_MAX_PROPERTY_STRING_LENGTH = 500
_PAYLOAD_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.:-]+")
_ATTRIBUTION_SOURCE_SEPARATOR = re.compile(r"[_:.-]+")
_SENSITIVE_PROPERTY_KEY_FRAGMENTS = (
    "age",
    "allerg",
    "answer",
    "birth",
    "charge_id",
    "condition",
    "diagnos",
    "email",
    "height",
    "medical",
    "name",
    "payment_charge",
    "phone",
    "profile",
    "provider_charge",
    "questionnaire",
    "restriction",
    "secret",
    "telegram_charge",
    "telegram_payment",
    "token",
    "weight",
)


@dataclass(frozen=True)
class StartAttribution:
    source: str | None
    campaign: str
    referral: str


def parse_start_attribution(payload: object) -> StartAttribution | None:
    text = str(payload or "").strip()
    if not text:
        return None
    cleaned = _PAYLOAD_UNSAFE_CHARS.sub("_", text[:_MAX_CAMPAIGN_TEXT_LENGTH]).strip("._:-")
    if not cleaned:
        return None
    source = _ATTRIBUTION_SOURCE_SEPARATOR.split(cleaned, maxsplit=1)[0].strip() or None
    return StartAttribution(source=source, campaign=cleaned, referral=cleaned)


def sanitize_analytics_properties(properties: Mapping[str, Any] | None) -> dict[str, object]:
    if not properties:
        return {}
    sanitized: dict[str, object] = {}
    for key, value in properties.items():
        text_key = str(key)
        if _is_sensitive_property_key(text_key):
            continue
        sanitized_value = _sanitize_analytics_value(value)
        if sanitized_value is not _DROP_VALUE:
            sanitized[text_key] = sanitized_value
    return sanitized


def _is_sensitive_property_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_PROPERTY_KEY_FRAGMENTS)


_DROP_VALUE = object()


def _sanitize_analytics_value(value: Any) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Enum):
        return _sanitize_analytics_value(value.value)
    if isinstance(value, str):
        return value[:_MAX_PROPERTY_STRING_LENGTH]
    if isinstance(value, Mapping):
        return sanitize_analytics_properties(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [
            item
            for raw_item in value
            if (item := _sanitize_analytics_value(raw_item)) is not _DROP_VALUE
        ]
    if isinstance(value, bytes | bytearray):
        return _DROP_VALUE
    return str(value)[:_MAX_PROPERTY_STRING_LENGTH]
