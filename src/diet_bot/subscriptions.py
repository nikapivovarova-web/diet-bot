from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from .json_storage import json_storage_transaction


MONTHLY_ONE_DAY_LIMIT = 5
MONTHLY_WEEKLY_PDF_LIMIT = 4
SUBSCRIPTION_PERIOD_SECONDS = 2_592_000
TEST_ACCESS_PERIOD_DAYS = 365
PROCESSED_CHARGE_ID_LIMIT = 200

RationKind = Literal["one_day", "weekly_pdf"]
AttemptSource = Literal["monthly", "extra", "free_trial", "test_access"]
AttemptDenialReason = Literal["paywall", "already_generating"]
PaymentGrant = Literal["subscription", "extra_one_day", "extra_weekly_pdf"]
PaymentReversalType = Literal["refund", "chargeback", "cancel_subscription"]
PaymentReversalReason = Literal["extra_already_consumed", "unsupported_product_for_event"]
LedgerSource = Literal[
    "free_trial_one_day",
    "monthly_one_day",
    "monthly_weekly_pdf",
    "extra_one_day",
    "extra_weekly_pdf",
    "test_access",
]

LEDGER_EVENT_CONSUME = "consume"
LEDGER_EVENT_REFUND = "refund"
LEDGER_EVENT_TYPES = {LEDGER_EVENT_CONSUME, LEDGER_EVENT_REFUND}
LEDGER_SOURCE_FREE_TRIAL_ONE_DAY = "free_trial_one_day"
LEDGER_SOURCE_MONTHLY_ONE_DAY = "monthly_one_day"
LEDGER_SOURCE_MONTHLY_WEEKLY_PDF = "monthly_weekly_pdf"
LEDGER_SOURCE_EXTRA_ONE_DAY = "extra_one_day"
LEDGER_SOURCE_EXTRA_WEEKLY_PDF = "extra_weekly_pdf"
LEDGER_SOURCE_TEST_ACCESS = "test_access"


@dataclass
class Entitlement:
    free_trial_used: bool = False
    subscription_period_start: str | None = None
    subscription_period_end: str | None = None
    test_access_until: str | None = None
    test_access_enabled: bool = False
    monthly_one_day_remaining: int = 0
    monthly_weekly_pdf_remaining: int = 0
    extra_one_day_remaining: int = 0
    extra_weekly_pdf_remaining: int = 0
    processed_payment_charge_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entitlement:
        return cls(
            free_trial_used=bool(data.get("free_trial_used", False)),
            subscription_period_start=_optional_str(data.get("subscription_period_start")),
            subscription_period_end=_optional_str(data.get("subscription_period_end")),
            test_access_until=_optional_str(data.get("test_access_until")),
            test_access_enabled=bool(data.get("test_access_enabled", bool(data.get("test_access_until")))),
            monthly_one_day_remaining=_non_negative_int(data.get("monthly_one_day_remaining")),
            monthly_weekly_pdf_remaining=_non_negative_int(data.get("monthly_weekly_pdf_remaining")),
            extra_one_day_remaining=_non_negative_int(data.get("extra_one_day_remaining")),
            extra_weekly_pdf_remaining=_non_negative_int(data.get("extra_weekly_pdf_remaining")),
            processed_payment_charge_ids=[
                str(charge_id)
                for charge_id in data.get("processed_payment_charge_ids", [])
                if str(charge_id)
            ][-PROCESSED_CHARGE_ID_LIMIT:],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "free_trial_used": self.free_trial_used,
            "subscription_period_start": self.subscription_period_start,
            "subscription_period_end": self.subscription_period_end,
            "test_access_until": self.test_access_until,
            "test_access_enabled": self.test_access_enabled,
            "monthly_one_day_remaining": self.monthly_one_day_remaining,
            "monthly_weekly_pdf_remaining": self.monthly_weekly_pdf_remaining,
            "extra_one_day_remaining": self.extra_one_day_remaining,
            "extra_weekly_pdf_remaining": self.extra_weekly_pdf_remaining,
            "processed_payment_charge_ids": self.processed_payment_charge_ids[-PROCESSED_CHARGE_ID_LIMIT:],
        }

    def subscription_end_datetime(self) -> datetime | None:
        return _parse_datetime(self.subscription_period_end)

    def test_access_end_datetime(self) -> datetime | None:
        return _parse_datetime(self.test_access_until)

    def is_subscription_active(self, now: datetime | None = None) -> bool:
        end = self.subscription_end_datetime()
        return bool(end and end > _normalize_now(now))

    def is_test_access_available(self, now: datetime | None = None) -> bool:
        end = self.test_access_end_datetime()
        return bool(end and end > _normalize_now(now))

    def is_test_access_active(self, now: datetime | None = None) -> bool:
        return self.test_access_enabled and self.is_test_access_available(now)

    def expire_if_needed(self, now: datetime | None = None) -> None:
        if self.subscription_period_end and not self.is_subscription_active(now):
            self.monthly_one_day_remaining = 0
            self.monthly_weekly_pdf_remaining = 0
        if self.test_access_until and not self.is_test_access_available(now):
            self.test_access_until = None
            self.test_access_enabled = False


@dataclass(frozen=True)
class AttemptConsumption:
    allowed: bool
    ration_kind: RationKind
    source: AttemptSource | None = None
    meal_plan_id: int | None = None
    denial_reason: AttemptDenialReason | None = None
    ledger_event_id: int | None = None


@dataclass(frozen=True)
class PaymentApplication:
    processed: bool
    grant: PaymentGrant | None = None
    duplicate: bool = False
    reason: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class PaymentReversalApplication:
    processed: bool
    reason: PaymentReversalReason | None = None


def load_entitlements(path: Path) -> dict[int, Entitlement]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not read entitlements state file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid entitlements state file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Invalid entitlements state file {path}: expected a JSON object.")
    entitlements: dict[int, Entitlement] = {}
    for chat_id, data in raw.items():
        if not isinstance(data, dict):
            continue
        try:
            parsed_chat_id = int(chat_id)
        except (TypeError, ValueError):
            continue
        entitlements[parsed_chat_id] = Entitlement.from_dict(data)
    return entitlements


def save_entitlements(path: Path, entitlements: dict[int, Entitlement]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        str(chat_id): entitlement.to_dict()
        for chat_id, entitlement in sorted(entitlements.items())
    }
    _write_json_atomic(path, payload)


def consume_one_day_attempt(
    entitlement: Entitlement,
    now: datetime | None = None,
) -> AttemptConsumption:
    entitlement.expire_if_needed(now)
    if entitlement.is_test_access_active(now):
        return AttemptConsumption(True, "one_day", "test_access")
    if entitlement.is_subscription_active(now) and entitlement.monthly_one_day_remaining > 0:
        entitlement.monthly_one_day_remaining -= 1
        return AttemptConsumption(True, "one_day", "monthly")
    if entitlement.is_subscription_active(now) and entitlement.extra_one_day_remaining > 0:
        entitlement.extra_one_day_remaining -= 1
        return AttemptConsumption(True, "one_day", "extra")
    if not entitlement.free_trial_used:
        entitlement.free_trial_used = True
        return AttemptConsumption(True, "one_day", "free_trial")
    return AttemptConsumption(False, "one_day")


def consume_weekly_pdf_attempt(
    entitlement: Entitlement,
    now: datetime | None = None,
) -> AttemptConsumption:
    entitlement.expire_if_needed(now)
    if entitlement.is_test_access_active(now):
        return AttemptConsumption(True, "weekly_pdf", "test_access")
    if entitlement.is_subscription_active(now) and entitlement.monthly_weekly_pdf_remaining > 0:
        entitlement.monthly_weekly_pdf_remaining -= 1
        return AttemptConsumption(True, "weekly_pdf", "monthly")
    if entitlement.is_subscription_active(now) and entitlement.extra_weekly_pdf_remaining > 0:
        entitlement.extra_weekly_pdf_remaining -= 1
        return AttemptConsumption(True, "weekly_pdf", "extra")
    return AttemptConsumption(False, "weekly_pdf")


def refund_attempt(entitlement: Entitlement, consumption: AttemptConsumption) -> None:
    if not consumption.allowed or not consumption.source:
        return
    if consumption.ration_kind == "one_day" and consumption.source == "monthly":
        entitlement.monthly_one_day_remaining = min(
            MONTHLY_ONE_DAY_LIMIT,
            entitlement.monthly_one_day_remaining + 1,
        )
    elif consumption.ration_kind == "weekly_pdf" and consumption.source == "monthly":
        entitlement.monthly_weekly_pdf_remaining = min(
            MONTHLY_WEEKLY_PDF_LIMIT,
            entitlement.monthly_weekly_pdf_remaining + 1,
        )
    elif consumption.ration_kind == "one_day" and consumption.source == "extra":
        entitlement.extra_one_day_remaining += 1
    elif consumption.ration_kind == "weekly_pdf" and consumption.source == "extra":
        entitlement.extra_weekly_pdf_remaining += 1
    elif consumption.ration_kind == "one_day" and consumption.source == "free_trial":
        entitlement.free_trial_used = False


def grant_test_access(
    entitlement: Entitlement,
    *,
    now: datetime | None = None,
    days: int = TEST_ACCESS_PERIOD_DAYS,
) -> None:
    start = _normalize_now(now)
    entitlement.test_access_until = _format_datetime(start + timedelta(days=max(1, days)))
    entitlement.test_access_enabled = True


def revoke_test_access(entitlement: Entitlement) -> None:
    entitlement.test_access_until = None
    entitlement.test_access_enabled = False


def set_test_access_enabled(
    entitlement: Entitlement,
    enabled: bool,
    *,
    now: datetime | None = None,
) -> bool:
    entitlement.expire_if_needed(now)
    if not entitlement.is_test_access_available(now):
        return False
    entitlement.test_access_enabled = enabled
    return True


def apply_subscription_payment(
    entitlement: Entitlement,
    charge_id: str,
    *,
    now: datetime | None = None,
    subscription_expiration_timestamp: int | None = None,
) -> PaymentApplication:
    if _is_duplicate_charge(entitlement, charge_id):
        return PaymentApplication(False, "subscription", duplicate=True)

    start = _normalize_now(now)
    entitlement.expire_if_needed(start)
    current_end = entitlement.subscription_end_datetime()
    extension_base = current_end if current_end and current_end > start else start
    provider_end = (
        datetime.fromtimestamp(subscription_expiration_timestamp, UTC)
        if subscription_expiration_timestamp
        else None
    )
    extended_end = extension_base + timedelta(seconds=SUBSCRIPTION_PERIOD_SECONDS)
    end = max(extended_end, provider_end) if provider_end else extended_end
    entitlement.subscription_period_start = _format_datetime(start)
    entitlement.subscription_period_end = _format_datetime(end)
    entitlement.monthly_one_day_remaining = MONTHLY_ONE_DAY_LIMIT
    entitlement.monthly_weekly_pdf_remaining = MONTHLY_WEEKLY_PDF_LIMIT
    _remember_charge_id(entitlement, charge_id)
    return PaymentApplication(True, "subscription")


def apply_extra_one_day_payment(entitlement: Entitlement, charge_id: str) -> PaymentApplication:
    if _is_duplicate_charge(entitlement, charge_id):
        return PaymentApplication(False, "extra_one_day", duplicate=True)
    entitlement.extra_one_day_remaining += 1
    _remember_charge_id(entitlement, charge_id)
    return PaymentApplication(True, "extra_one_day")


def apply_extra_weekly_pdf_payment(entitlement: Entitlement, charge_id: str) -> PaymentApplication:
    if _is_duplicate_charge(entitlement, charge_id):
        return PaymentApplication(False, "extra_weekly_pdf", duplicate=True)
    entitlement.extra_weekly_pdf_remaining += 1
    _remember_charge_id(entitlement, charge_id)
    return PaymentApplication(True, "extra_weekly_pdf")


def apply_payment_reversal(
    entitlement: Entitlement,
    product: str,
    event_type: PaymentReversalType,
    *,
    now: datetime | None = None,
) -> PaymentReversalApplication:
    entitlement.expire_if_needed(now)
    if product == "subscription_month":
        if event_type == "cancel_subscription":
            return PaymentReversalApplication(True)
        entitlement.subscription_period_end = _format_datetime(_normalize_now(now))
        entitlement.monthly_one_day_remaining = 0
        entitlement.monthly_weekly_pdf_remaining = 0
        return PaymentReversalApplication(True)
    if event_type == "cancel_subscription":
        return PaymentReversalApplication(False, "unsupported_product_for_event")
    if product == "extra_one_day":
        if entitlement.extra_one_day_remaining <= 0:
            return PaymentReversalApplication(False, "extra_already_consumed")
        entitlement.extra_one_day_remaining -= 1
        return PaymentReversalApplication(True)
    if product == "extra_weekly_pdf":
        if entitlement.extra_weekly_pdf_remaining <= 0:
            return PaymentReversalApplication(False, "extra_already_consumed")
        entitlement.extra_weekly_pdf_remaining -= 1
        return PaymentReversalApplication(True)
    return PaymentReversalApplication(False, "unsupported_product_for_event")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _normalize_now(parsed)


def _is_duplicate_charge(entitlement: Entitlement, charge_id: str) -> bool:
    return bool(charge_id and charge_id in entitlement.processed_payment_charge_ids)


def _remember_charge_id(entitlement: Entitlement, charge_id: str) -> None:
    if not charge_id:
        return
    entitlement.processed_payment_charge_ids.append(charge_id)
    entitlement.processed_payment_charge_ids = entitlement.processed_payment_charge_ids[-PROCESSED_CHARGE_ID_LIMIT:]


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with json_storage_transaction(path):
        try:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        finally:
            with suppress(OSError):
                tmp_path.unlink()
