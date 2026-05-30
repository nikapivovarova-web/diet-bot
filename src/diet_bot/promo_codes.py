from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal


PROMO_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class PromoCodeKind(StrEnum):
    MONTHLY_ACCESS = "monthly_access"
    DISCOUNT = "discount"


PromoCodeActivationStatus = Literal[
    "activated",
    "not_found",
    "already_used",
    "not_access_code",
    "disabled",
    "expired",
]


@dataclass(frozen=True)
class PromoCodeDefinition:
    code: str
    kind: PromoCodeKind | str = PromoCodeKind.MONTHLY_ACCESS
    active: bool = True
    max_redemptions: int = 1
    per_user_limit: int = 1
    expires_at: str | datetime | None = None
    discount_percent: int | None = None
    discount_amount: int | None = None
    monthly_duration_months: int = 1

    def __post_init__(self) -> None:
        code = normalize_promo_code(self.code)
        if not code:
            raise ValueError("Promo code must not be empty")
        kind = _normalize_promo_kind(self.kind)
        max_redemptions = _positive_int(self.max_redemptions)
        per_user_limit = _positive_int(self.per_user_limit)
        monthly_duration_months = max(1, _positive_int(self.monthly_duration_months))
        discount_percent = _optional_positive_int(self.discount_percent)
        discount_amount = _optional_positive_int(self.discount_amount)
        expires_at = _optional_datetime_text(self.expires_at)

        if kind == PromoCodeKind.MONTHLY_ACCESS:
            if discount_percent is not None or discount_amount is not None:
                raise ValueError("Monthly access promo cannot define discount values")
        else:
            if discount_percent is None and discount_amount is None:
                raise ValueError("Discount promo must define discount_percent or discount_amount")
            if discount_percent is not None and discount_percent > 100:
                raise ValueError("Discount percent must be between 1 and 100")
            if discount_percent is not None and discount_amount is not None:
                raise ValueError("Discount promo must not define both percent and amount")

        object.__setattr__(self, "code", code)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "max_redemptions", max_redemptions)
        object.__setattr__(self, "per_user_limit", per_user_limit)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "discount_percent", discount_percent)
        object.__setattr__(self, "discount_amount", discount_amount)
        object.__setattr__(self, "monthly_duration_months", monthly_duration_months)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "kind": self.kind.value,
            "active": self.active,
            "max_redemptions": self.max_redemptions,
            "per_user_limit": self.per_user_limit,
            "expires_at": self.expires_at,
            "discount_percent": self.discount_percent,
            "discount_amount": self.discount_amount,
            "monthly_duration_months": self.monthly_duration_months,
        }


@dataclass
class PromoCodeRecord:
    kind: PromoCodeKind | str = PromoCodeKind.MONTHLY_ACCESS
    active: bool = True
    max_redemptions: int = 1
    per_user_limit: int = 1
    expires_at: str | None = None
    discount_percent: int | None = None
    discount_amount: int | None = None
    monthly_duration_months: int = 1
    used_by_chat_id: int | None = None
    used_at: str | None = None

    @classmethod
    def monthly_access(cls) -> PromoCodeRecord:
        return cls(kind=PromoCodeKind.MONTHLY_ACCESS)

    @classmethod
    def from_definition(cls, definition: PromoCodeDefinition) -> PromoCodeRecord:
        return cls(
            kind=definition.kind,
            active=definition.active,
            max_redemptions=definition.max_redemptions,
            per_user_limit=definition.per_user_limit,
            expires_at=definition.expires_at,
            discount_percent=definition.discount_percent,
            discount_amount=definition.discount_amount,
            monthly_duration_months=definition.monthly_duration_months,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromoCodeRecord:
        return cls(
            kind=_normalize_promo_kind(data.get("kind", PromoCodeKind.MONTHLY_ACCESS)),
            active=bool(data.get("active", True)),
            max_redemptions=_positive_int(data.get("max_redemptions", 1)),
            per_user_limit=_positive_int(data.get("per_user_limit", 1)),
            expires_at=_optional_str(data.get("expires_at")),
            discount_percent=_optional_positive_int(data.get("discount_percent")),
            discount_amount=_optional_positive_int(data.get("discount_amount")),
            monthly_duration_months=max(1, _positive_int(data.get("monthly_duration_months", 1))),
            used_by_chat_id=_optional_int(data.get("used_by_chat_id")),
            used_at=_optional_str(data.get("used_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": _normalize_promo_kind(self.kind).value,
            "active": self.active,
            "max_redemptions": self.max_redemptions,
            "per_user_limit": self.per_user_limit,
            "expires_at": self.expires_at,
            "discount_percent": self.discount_percent,
            "discount_amount": self.discount_amount,
            "monthly_duration_months": self.monthly_duration_months,
            "used_by_chat_id": self.used_by_chat_id,
            "used_at": self.used_at,
        }

    def is_used(self) -> bool:
        return self.used_by_chat_id is not None

    def is_monthly_access(self) -> bool:
        return _normalize_promo_kind(self.kind) == PromoCodeKind.MONTHLY_ACCESS

    def is_expired(self, now: datetime | None = None) -> bool:
        expires_at = _parse_datetime(self.expires_at)
        return bool(expires_at and expires_at <= _normalize_now(now))


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


def promo_code_grant_charge_id(raw_code: str) -> str:
    code = normalize_promo_code(raw_code)
    return f"promo:{code}" if code else "promo:"


def calculate_discount_amount(promo: PromoCodeDefinition, list_amount: int) -> int:
    if int(list_amount) <= 0:
        raise ValueError("Discount requires a positive list amount")
    definition = PromoCodeDefinition(**promo.to_dict())
    if definition.kind != PromoCodeKind.DISCOUNT:
        raise ValueError("Promo code is not a discount")
    if definition.discount_percent is not None:
        discount_amount = (int(list_amount) * definition.discount_percent) // 100
    else:
        discount_amount = definition.discount_amount or 0
    final_amount = int(list_amount) - discount_amount
    if discount_amount <= 0 or final_amount <= 0:
        raise ValueError("Discount must leave a positive final amount")
    return discount_amount


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
    if not record.is_monthly_access():
        return PromoCodeActivation("not_access_code", code)
    if not record.active:
        return PromoCodeActivation("disabled", code)
    if record.is_expired(now):
        return PromoCodeActivation("expired", code)
    if record.is_used():
        return PromoCodeActivation("already_used", code, record.used_by_chat_id)

    record.used_by_chat_id = chat_id
    record.used_at = _format_datetime(_normalize_now(now))
    promo_codes[code] = record
    save_promo_codes(path, promo_codes)
    return PromoCodeActivation("activated", code, chat_id)


def release_promo_code_activation(path: Path, raw_code: str, chat_id: int) -> bool:
    code = normalize_promo_code(raw_code)
    if not code:
        return False

    promo_codes = load_promo_codes(path)
    record = promo_codes.get(code)
    if record is None or record.used_by_chat_id != chat_id:
        return False

    record.used_by_chat_id = None
    record.used_at = None
    promo_codes[code] = record
    save_promo_codes(path, promo_codes)
    return True


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


def _positive_int(value: Any) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_datetime_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _format_datetime(value)
    text = str(value).strip()
    return text or None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _normalize_now(parsed)


def _normalize_promo_kind(value: Any) -> PromoCodeKind:
    text = str(value or PromoCodeKind.MONTHLY_ACCESS.value).strip().lower()
    if text == str(PromoCodeKind.MONTHLY_ACCESS).lower():
        return PromoCodeKind.MONTHLY_ACCESS
    if text in {kind.value for kind in PromoCodeKind}:
        return PromoCodeKind(text)
    raise ValueError(f"Unsupported promo code kind: {value}")


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
