from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast


PROCESSED_CHARGE_ID_LIMIT = 200

SubscriptionSource = Literal["none", "telegram_stars", "yookassa", "promo", "admin", "legacy"]
AutoRenewStatus = Literal["not_applicable", "enabled", "canceled", "unknown"]

SUBSCRIPTION_SOURCES: frozenset[str] = frozenset(
    {"none", "telegram_stars", "yookassa", "promo", "admin", "legacy"}
)
AUTO_RENEW_STATUSES: frozenset[str] = frozenset(
    {"not_applicable", "enabled", "canceled", "unknown"}
)


@dataclass
class Entitlement:
    free_trial_used: bool = False
    subscription_period_start: str | None = None
    subscription_period_end: str | None = None
    subscription_source: SubscriptionSource = "none"
    auto_renew_status: AutoRenewStatus = "not_applicable"
    stars_subscription_charge_id: str | None = None
    last_subscription_payment_charge_id: str | None = None
    current_period_payment_order_id: str | None = None
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
            subscription_source=_subscription_source(data.get("subscription_source")),
            auto_renew_status=_auto_renew_status(data.get("auto_renew_status")),
            stars_subscription_charge_id=_optional_str(data.get("stars_subscription_charge_id")),
            last_subscription_payment_charge_id=_optional_str(
                data.get("last_subscription_payment_charge_id")
            ),
            current_period_payment_order_id=_optional_str(
                data.get("current_period_payment_order_id")
            ),
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
            "subscription_source": self.subscription_source,
            "auto_renew_status": self.auto_renew_status,
            "stars_subscription_charge_id": self.stars_subscription_charge_id,
            "last_subscription_payment_charge_id": self.last_subscription_payment_charge_id,
            "current_period_payment_order_id": self.current_period_payment_order_id,
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


def _subscription_source(value: Any) -> SubscriptionSource:
    text = str(value or "none").strip().lower()
    if text in SUBSCRIPTION_SOURCES:
        return cast(SubscriptionSource, text)
    return "legacy"


def _auto_renew_status(value: Any) -> AutoRenewStatus:
    text = str(value or "not_applicable").strip().lower()
    if text in AUTO_RENEW_STATUSES:
        return cast(AutoRenewStatus, text)
    return "unknown"


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
