from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from .entitlement_model import (
    AUTO_RENEW_STATUSES as AUTO_RENEW_STATUSES,
    PROCESSED_CHARGE_ID_LIMIT,
    SUBSCRIPTION_SOURCES as SUBSCRIPTION_SOURCES,
    AutoRenewStatus,
    Entitlement,
    SubscriptionSource,
    _format_datetime,
    _normalize_now,
)


MONTHLY_ONE_DAY_LIMIT = 5
MONTHLY_WEEKLY_PDF_LIMIT = 4
SUBSCRIPTION_PERIOD_SECONDS = 2_592_000
TEST_ACCESS_PERIOD_DAYS = 365

RationKind = Literal["one_day", "weekly_pdf"]
AttemptSource = Literal["monthly", "extra", "free_trial", "test_access"]
PaymentGrant = Literal["subscription", "extra_one_day", "extra_weekly_pdf"]
PaymentReversalStatus = Literal["refunded", "canceled", "reversed", "chargeback"]

STARS_DUPLICATE_GUARD_AUTO_RENEW_STATUSES: frozenset[str] = frozenset(
    {"enabled", "unknown", "canceled"}
)
_UNSET = object()


@dataclass(frozen=True)
class AttemptConsumption:
    allowed: bool
    ration_kind: RationKind
    source: AttemptSource | None = None


@dataclass(frozen=True)
class PaymentApplication:
    processed: bool
    grant: PaymentGrant | None = None
    duplicate: bool = False


@dataclass(frozen=True)
class PaymentReversalApplication:
    processed: bool
    grant: PaymentGrant | None = None
    duplicate: bool = False
    manual_review_required: bool = False
    reason: str | None = None


def load_entitlements(path: Path) -> dict[int, Entitlement]:
    from .entitlement_storage import JsonEntitlementStore

    return JsonEntitlementStore(path).load_all()


def save_entitlements(path: Path, entitlements: dict[int, Entitlement]) -> None:
    from .entitlement_storage import JsonEntitlementStore

    JsonEntitlementStore(path).save_all(entitlements)


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
    if entitlement.extra_one_day_remaining > 0:
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
    if entitlement.extra_weekly_pdf_remaining > 0:
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


def has_active_managed_stars_subscription(
    entitlement: Entitlement,
    now: datetime | None = None,
) -> bool:
    return (
        entitlement.subscription_source == "telegram_stars"
        and entitlement.auto_renew_status in STARS_DUPLICATE_GUARD_AUTO_RENEW_STATUSES
        and entitlement.is_subscription_active(now)
    )


def apply_subscription_payment(
    entitlement: Entitlement,
    charge_id: str,
    *,
    now: datetime | None = None,
    subscription_expiration_timestamp: int | None = None,
    subscription_source: SubscriptionSource | None = None,
    auto_renew_status: AutoRenewStatus | None = None,
    stars_subscription_charge_id: str | None = None,
    last_subscription_payment_charge_id: str | None | object = _UNSET,
    current_period_payment_order_id: str | None = None,
) -> PaymentApplication:
    if has_processed_charge_id(entitlement, charge_id):
        return PaymentApplication(False, "subscription", duplicate=True)

    start = _normalize_now(now)
    end = (
        datetime.fromtimestamp(subscription_expiration_timestamp, UTC)
        if subscription_expiration_timestamp
        else start + timedelta(seconds=SUBSCRIPTION_PERIOD_SECONDS)
    )
    entitlement.subscription_period_start = _format_datetime(start)
    entitlement.subscription_period_end = _format_datetime(end)
    entitlement.monthly_one_day_remaining = MONTHLY_ONE_DAY_LIMIT
    entitlement.monthly_weekly_pdf_remaining = MONTHLY_WEEKLY_PDF_LIMIT
    if subscription_source is not None:
        entitlement.subscription_source = subscription_source
        if subscription_source != "telegram_stars":
            entitlement.stars_subscription_charge_id = None
    if auto_renew_status is not None:
        entitlement.auto_renew_status = auto_renew_status
    if stars_subscription_charge_id is not None:
        entitlement.stars_subscription_charge_id = stars_subscription_charge_id
    elif subscription_source == "telegram_stars":
        entitlement.stars_subscription_charge_id = charge_id
    if last_subscription_payment_charge_id is not _UNSET:
        entitlement.last_subscription_payment_charge_id = cast(str | None, last_subscription_payment_charge_id)
    elif subscription_source is not None:
        entitlement.last_subscription_payment_charge_id = charge_id
    if current_period_payment_order_id is not None:
        entitlement.current_period_payment_order_id = current_period_payment_order_id
    record_processed_charge_id(entitlement, charge_id)
    return PaymentApplication(True, "subscription")


def apply_monthly_access_promo_grant(
    entitlement: Entitlement,
    charge_id: str,
    *,
    now: datetime | None = None,
    months: int = 1,
) -> PaymentApplication:
    current_time = _normalize_now(now)
    current_end = entitlement.subscription_end_datetime()
    extension_base = current_end if current_end and current_end > current_time else current_time
    duration = max(1, int(months)) * SUBSCRIPTION_PERIOD_SECONDS
    return apply_subscription_payment(
        entitlement,
        charge_id,
        now=current_time,
        subscription_expiration_timestamp=int((extension_base + timedelta(seconds=duration)).timestamp()),
        subscription_source="promo",
        auto_renew_status="not_applicable",
        last_subscription_payment_charge_id=charge_id,
    )


def apply_extra_one_day_payment(entitlement: Entitlement, charge_id: str) -> PaymentApplication:
    if has_processed_charge_id(entitlement, charge_id):
        return PaymentApplication(False, "extra_one_day", duplicate=True)
    entitlement.extra_one_day_remaining += 1
    record_processed_charge_id(entitlement, charge_id)
    return PaymentApplication(True, "extra_one_day")


def apply_extra_weekly_pdf_payment(entitlement: Entitlement, charge_id: str) -> PaymentApplication:
    if has_processed_charge_id(entitlement, charge_id):
        return PaymentApplication(False, "extra_weekly_pdf", duplicate=True)
    entitlement.extra_weekly_pdf_remaining += 1
    record_processed_charge_id(entitlement, charge_id)
    return PaymentApplication(True, "extra_weekly_pdf")


def apply_payment_reversal(
    entitlement: Entitlement,
    product: str,
    charge_id: str,
    *,
    order_id: str | None = None,
    reversal_status: str = "refunded",
    now: datetime | None = None,
) -> PaymentReversalApplication:
    grant = _payment_grant_for_product(product)
    normalized_status = _payment_reversal_status(reversal_status)
    marker = _payment_reversal_marker(normalized_status, charge_id)
    if has_processed_charge_id(entitlement, marker):
        return PaymentReversalApplication(False, grant, duplicate=True)

    record_processed_charge_id(entitlement, marker)
    if not has_processed_charge_id(entitlement, charge_id):
        return PaymentReversalApplication(
            True,
            grant,
            manual_review_required=True,
            reason="payment_charge_not_granted",
        )
    if product == "subscription_month":
        return _apply_subscription_payment_reversal(
            entitlement,
            charge_id,
            order_id=order_id,
            reversal_status=normalized_status,
            now=now,
        )
    if product in {"extra_one_day", "extra_weekly_pdf"}:
        _apply_extra_payment_reversal(entitlement, product)
        return PaymentReversalApplication(
            True,
            grant,
            manual_review_required=True,
            reason="extra_entitlement_requires_manual_review",
        )
    return PaymentReversalApplication(
        True,
        grant,
        manual_review_required=True,
        reason="unsupported_payment_product",
    )


def has_processed_charge_id(entitlement: Entitlement, charge_id: str) -> bool:
    return bool(charge_id and charge_id in entitlement.processed_payment_charge_ids)


def record_processed_charge_id(entitlement: Entitlement, charge_id: str) -> bool:
    if not charge_id or has_processed_charge_id(entitlement, charge_id):
        return False
    entitlement.processed_payment_charge_ids.append(charge_id)
    entitlement.processed_payment_charge_ids = entitlement.processed_payment_charge_ids[-PROCESSED_CHARGE_ID_LIMIT:]
    return True


def _apply_subscription_payment_reversal(
    entitlement: Entitlement,
    charge_id: str,
    *,
    order_id: str | None,
    reversal_status: PaymentReversalStatus,
    now: datetime | None,
) -> PaymentReversalApplication:
    if not _subscription_reversal_matches_current(entitlement, charge_id, order_id):
        return PaymentReversalApplication(
            True,
            "subscription",
            manual_review_required=True,
            reason="subscription_charge_not_current",
        )
    reversed_at = _normalize_now(now)
    entitlement.subscription_period_end = _format_datetime(reversed_at)
    entitlement.monthly_one_day_remaining = 0
    entitlement.monthly_weekly_pdf_remaining = 0
    if entitlement.subscription_source == "telegram_stars" or reversal_status in {"canceled", "reversed", "chargeback"}:
        entitlement.auto_renew_status = "canceled"
    return PaymentReversalApplication(True, "subscription")


def _apply_extra_payment_reversal(entitlement: Entitlement, product: str) -> None:
    if product == "extra_one_day" and entitlement.extra_one_day_remaining > 0:
        entitlement.extra_one_day_remaining -= 1
    elif product == "extra_weekly_pdf" and entitlement.extra_weekly_pdf_remaining > 0:
        entitlement.extra_weekly_pdf_remaining -= 1


def _subscription_reversal_matches_current(
    entitlement: Entitlement,
    charge_id: str,
    order_id: str | None,
) -> bool:
    charge_matches = charge_id in {
        entitlement.last_subscription_payment_charge_id,
        entitlement.stars_subscription_charge_id,
    }
    if not charge_matches:
        return False
    return (
        order_id is None
        or entitlement.current_period_payment_order_id is None
        or entitlement.current_period_payment_order_id == order_id
    )


def _payment_reversal_status(value: str) -> PaymentReversalStatus:
    normalized = str(value or "refunded").strip().lower()
    if normalized == "cancelled":
        normalized = "canceled"
    if normalized == "refund":
        normalized = "refunded"
    if normalized in {"refunded", "canceled", "reversed", "chargeback"}:
        return cast(PaymentReversalStatus, normalized)
    return "reversed"


def _payment_reversal_marker(status: PaymentReversalStatus, charge_id: str) -> str:
    return f"reversal:{status}:{charge_id}"


def _payment_grant_for_product(product: str) -> PaymentGrant | None:
    if product == "subscription_month":
        return "subscription"
    if product == "extra_one_day":
        return "extra_one_day"
    if product == "extra_weekly_pdf":
        return "extra_weekly_pdf"
    return None
