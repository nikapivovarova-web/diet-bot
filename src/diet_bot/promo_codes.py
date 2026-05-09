from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


PROMO_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

PromoCodeActivationStatus = Literal["activated", "not_found", "already_used"]


@dataclass
class PromoCodeRecord:
    used_by_chat_id: int | None = None
    used_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromoCodeRecord:
        return cls(
            used_by_chat_id=_optional_int(data.get("used_by_chat_id")),
            used_at=_optional_str(data.get("used_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "used_by_chat_id": self.used_by_chat_id,
            "used_at": self.used_at,
        }

    def is_used(self) -> bool:
        return self.used_by_chat_id is not None


@dataclass(frozen=True)
class PromoCodeActivation:
    status: PromoCodeActivationStatus
    code: str
    used_by_chat_id: int | None = None

    @property
    def activated(self) -> bool:
        return self.status == "activated"


def normalize_promo_code(raw_code: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", raw_code.upper())
    if compact.startswith("FB") and len(compact) == 14:
        return f"FB-{compact[2:6]}-{compact[6:10]}-{compact[10:14]}"
    return compact


def load_promo_codes(path: Path) -> dict[str, PromoCodeRecord]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    data = raw.get("codes", raw) if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        return {}

    promo_codes: dict[str, PromoCodeRecord] = {}
    for code, record in data.items():
        normalized_code = normalize_promo_code(str(code))
        if not normalized_code:
            continue
        promo_codes[normalized_code] = (
            PromoCodeRecord.from_dict(record)
            if isinstance(record, dict)
            else PromoCodeRecord()
        )
    return promo_codes


def save_promo_codes(path: Path, promo_codes: dict[str, PromoCodeRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "codes": {
            code: record.to_dict()
            for code, record in sorted(promo_codes.items())
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def activate_promo_code(
    path: Path,
    raw_code: str,
    chat_id: int,
    *,
    now: datetime | None = None,
) -> PromoCodeActivation:
    code = normalize_promo_code(raw_code)
    if not code:
        return PromoCodeActivation("not_found", "")

    promo_codes = load_promo_codes(path)
    record = promo_codes.get(code)
    if record is None:
        return PromoCodeActivation("not_found", code)
    if record.is_used():
        return PromoCodeActivation("already_used", code, record.used_by_chat_id)

    record.used_by_chat_id = chat_id
    record.used_at = _format_datetime(_normalize_now(now))
    promo_codes[code] = record
    save_promo_codes(path, promo_codes)
    return PromoCodeActivation("activated", code, chat_id)


def generate_promo_codes(count: int, *, existing_codes: set[str] | None = None) -> list[str]:
    existing = {normalize_promo_code(code) for code in existing_codes or set()}
    generated: set[str] = set()
    while len(generated) < count:
        code = _new_promo_code()
        if code not in existing:
            generated.add(code)
    return sorted(generated)


def _new_promo_code() -> str:
    first = "".join(secrets.choice(PROMO_CODE_ALPHABET) for _ in range(4))
    second = "".join(secrets.choice(PROMO_CODE_ALPHABET) for _ in range(4))
    third = "".join(secrets.choice(PROMO_CODE_ALPHABET) for _ in range(4))
    return f"FB-{first}-{second}-{third}"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
