from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping


REDACTED_MISSING = "<redacted:missing>"
_FINGERPRINT_LENGTH = 12
_LABEL_RE = re.compile(r"[^a-z0-9_.-]+")

SENSITIVE_LOG_IDENTIFIER_LABELS: dict[str, str] = {
    "chat": "chat",
    "chat_id": "chat",
    "user": "user",
    "user_id": "user",
    "order": "order",
    "order_id": "order",
    "job": "job",
    "job_id": "job",
    "telegram_payment_charge": "telegram_payment_charge",
    "telegram_payment_charge_id": "telegram_payment_charge",
    "provider_payment_charge": "provider_payment_charge",
    "provider_payment_charge_id": "provider_payment_charge",
    "payment_charge": "payment_charge",
    "payment_charge_id": "payment_charge",
}


def redact_log_identifier(label: str, value: object | None) -> str:
    text = _normalize_identifier_value(value)
    if text is None:
        return REDACTED_MISSING
    digest = hashlib.sha256(f"{_normalize_label(label)}:{text}".encode("utf-8")).hexdigest()
    return f"<redacted:{digest[:_FINGERPRINT_LENGTH]}>"


def redact_log_kv(label: str, value: object | None) -> str:
    safe_label = _normalize_label(label)
    return f"{safe_label}={redact_log_identifier(safe_label, value)}"


def redact_log_fields(fields: Mapping[str, object]) -> dict[str, object]:
    safe_fields: dict[str, object] = {}
    for key, value in fields.items():
        key_text = str(key)
        redaction_label = SENSITIVE_LOG_IDENTIFIER_LABELS.get(key_text)
        safe_fields[key_text] = redact_log_identifier(redaction_label, value) if redaction_label else value
    return safe_fields


def _normalize_identifier_value(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_label(label: str) -> str:
    normalized = _LABEL_RE.sub("_", str(label).strip().lower()).strip("._-")
    return normalized or "id"
