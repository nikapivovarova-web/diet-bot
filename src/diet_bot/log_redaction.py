from __future__ import annotations

import hashlib
from collections.abc import Mapping


DEFAULT_REDACTION_LENGTH = 12
DEFAULT_HASH_LENGTH = 16
MISSING_REDACTION = "<redacted:missing>"

_LOG_IDENTIFIER_LABELS = {
    "chat_id": "chat",
    "user_id": "user",
    "order_id": "order",
    "telegram_payment_charge_id": "telegram_payment_charge",
    "provider_payment_charge_id": "provider_payment_charge",
    "job_id": "job",
}


def redact_identifier(label: str, value: object | None, *, length: int = DEFAULT_REDACTION_LENGTH) -> str:
    fingerprint = identifier_fingerprint(label, value, length=length)
    if fingerprint is None:
        return MISSING_REDACTION
    return f"<redacted:{fingerprint}>"


def redact_optional_identifier(
    label: str,
    value: object | None,
    *,
    length: int = DEFAULT_REDACTION_LENGTH,
) -> str | None:
    fingerprint = identifier_fingerprint(label, value, length=length)
    if fingerprint is None:
        return None
    return f"<redacted:{fingerprint}>"


def stable_identifier_hash(label: str, value: object | None, *, length: int = DEFAULT_HASH_LENGTH) -> str:
    fingerprint = identifier_fingerprint(label, value, length=length)
    if fingerprint is None:
        return f"{label}:sha256:missing"
    return f"{label}:sha256:{fingerprint}"


def redact_log_identifiers(
    fields: Mapping[str, object],
    *,
    labels_by_key: Mapping[str, str] | None = None,
) -> dict[str, object]:
    labels = dict(_LOG_IDENTIFIER_LABELS)
    if labels_by_key:
        labels.update(labels_by_key)
    return {
        key: redact_identifier(labels[key], value) if key in labels else value
        for key, value in fields.items()
    }


def identifier_fingerprint(
    label: str,
    value: object | None,
    *,
    length: int = DEFAULT_REDACTION_LENGTH,
) -> str | None:
    if length < 1:
        raise ValueError("fingerprint length must be positive")
    text = _identifier_text(value)
    if text is None:
        return None
    digest = hashlib.sha256(f"{label}:{text}".encode("utf-8")).hexdigest()
    return digest[:length]


def _identifier_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
