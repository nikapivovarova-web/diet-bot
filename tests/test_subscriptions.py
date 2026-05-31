from datetime import UTC, datetime, timedelta

import pytest

from diet_bot.subscriptions import (
    MONTHLY_ONE_DAY_LIMIT,
    MONTHLY_WEEKLY_PDF_LIMIT,
    Entitlement,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_subscription_payment,
    consume_one_day_attempt,
    consume_weekly_pdf_attempt,
    grant_test_access,
    has_active_managed_stars_subscription,
    load_entitlements,
    refund_attempt,
    revoke_test_access,
    save_entitlements,
    set_test_access_enabled,
)
from diet_bot import subscriptions


def test_free_user_gets_one_lifetime_one_day_attempt() -> None:
    entitlement = Entitlement()

    first = consume_one_day_attempt(entitlement)
    second = consume_one_day_attempt(entitlement)

    assert first.allowed
    assert first.source == "free_trial"
    assert entitlement.free_trial_used
    assert not second.allowed


def test_free_user_cannot_generate_weekly_pdf() -> None:
    entitlement = Entitlement()

    consumption = consume_weekly_pdf_attempt(entitlement)

    assert not consumption.allowed


def test_subscription_payment_resets_monthly_limits_without_accumulation() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement()

    first = apply_subscription_payment(
        entitlement,
        "charge-1",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 2
    entitlement.monthly_weekly_pdf_remaining = 1
    second = apply_subscription_payment(
        entitlement,
        "charge-2",
        now=now + timedelta(days=30),
        subscription_expiration_timestamp=int((now + timedelta(days=60)).timestamp()),
    )

    assert first.processed
    assert second.processed
    assert entitlement.monthly_one_day_remaining == MONTHLY_ONE_DAY_LIMIT
    assert entitlement.monthly_weekly_pdf_remaining == MONTHLY_WEEKLY_PDF_LIMIT


def test_duplicate_payment_charge_does_not_grant_twice() -> None:
    entitlement = Entitlement()

    first = apply_extra_one_day_payment(entitlement, "charge-1")
    second = apply_extra_one_day_payment(entitlement, "charge-1")

    assert first.processed
    assert second.duplicate
    assert entitlement.extra_one_day_remaining == 1


def test_extra_attempts_are_consumed_after_monthly_attempts() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "charge-sub",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    apply_extra_one_day_payment(entitlement, "charge-extra-day")
    entitlement.monthly_one_day_remaining = 1

    monthly = consume_one_day_attempt(entitlement, now)
    extra = consume_one_day_attempt(entitlement, now)

    assert monthly.source == "monthly"
    assert extra.source == "extra"
    assert entitlement.monthly_one_day_remaining == 0
    assert entitlement.extra_one_day_remaining == 0


def test_refund_restores_consumed_attempt() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "charge-sub",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )

    consumption = consume_weekly_pdf_attempt(entitlement, now)
    refund_attempt(entitlement, consumption)

    assert consumption.source == "monthly"
    assert entitlement.monthly_weekly_pdf_remaining == MONTHLY_WEEKLY_PDF_LIMIT


def test_extra_weekly_purchase_grants_one_weekly_pdf_attempt() -> None:
    entitlement = Entitlement()

    result = apply_extra_weekly_pdf_payment(entitlement, "charge-week")

    assert result.processed
    assert entitlement.extra_weekly_pdf_remaining == 1


@pytest.mark.parametrize(
    (
        "product",
        "charge_id",
        "grant_payment",
        "counter_attr",
        "consume_attempt",
        "reversal_status",
    ),
    [
        (
            "extra_one_day",
            "telegram_stars:tg-extra-day-refunded",
            apply_extra_one_day_payment,
            "extra_one_day_remaining",
            consume_one_day_attempt,
            "refunded",
        ),
        (
            "extra_weekly_pdf",
            "telegram_stars:tg-extra-pdf-canceled",
            apply_extra_weekly_pdf_payment,
            "extra_weekly_pdf_remaining",
            consume_weekly_pdf_attempt,
            "canceled",
        ),
        (
            "extra_weekly_pdf",
            "telegram_stars:tg-extra-pdf-reversed",
            apply_extra_weekly_pdf_payment,
            "extra_weekly_pdf_remaining",
            consume_weekly_pdf_attempt,
            "reversed",
        ),
    ],
)
def test_reversal_of_extra_purchase_revokes_unused_extra_access(
    product: str,
    charge_id: str,
    grant_payment,
    counter_attr: str,
    consume_attempt,
    reversal_status: str,
) -> None:
    apply_reversal = getattr(subscriptions, "apply_payment_reversal")
    now = datetime(2026, 5, 9, tzinfo=UTC)
    entitlement = Entitlement(free_trial_used=True)

    grant = grant_payment(entitlement, charge_id)

    assert grant.processed
    assert getattr(entitlement, counter_attr) == 1

    reversal = apply_reversal(
        entitlement,
        product,
        charge_id,
        order_id=f"order-{reversal_status}",
        reversal_status=reversal_status,
        now=now,
    )

    assert reversal.processed
    assert reversal.manual_review_required
    assert reversal.reason == "extra_entitlement_requires_manual_review"
    assert getattr(entitlement, counter_attr) == 0
    assert not consume_attempt(entitlement, now).allowed


def test_test_access_allows_generations_without_consuming_limits() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement()

    grant_test_access(entitlement, now=now)
    one_day = consume_one_day_attempt(entitlement, now)
    weekly_pdf = consume_weekly_pdf_attempt(entitlement, now)

    assert one_day.allowed
    assert one_day.source == "test_access"
    assert weekly_pdf.allowed
    assert weekly_pdf.source == "test_access"
    assert entitlement.test_access_enabled
    assert not entitlement.free_trial_used
    assert entitlement.monthly_one_day_remaining == 0
    assert entitlement.monthly_weekly_pdf_remaining == 0


def test_test_access_can_be_disabled_without_revoking_grant() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement()

    grant_test_access(entitlement, now=now)
    disabled = set_test_access_enabled(entitlement, False, now=now)
    consumption = consume_weekly_pdf_attempt(entitlement, now)

    assert disabled
    assert entitlement.test_access_until is not None
    assert not entitlement.test_access_enabled
    assert not consumption.allowed

    enabled = set_test_access_enabled(entitlement, True, now=now)

    assert enabled
    assert consume_weekly_pdf_attempt(entitlement, now).source == "test_access"


def test_test_access_can_be_revoked() -> None:
    entitlement = Entitlement()

    grant_test_access(entitlement)
    revoke_test_access(entitlement)

    assert entitlement.test_access_until is None
    assert not entitlement.test_access_enabled


def test_subscription_state_round_trips_json(tmp_path) -> None:
    path = tmp_path / "subscriptions.json"
    entitlement = Entitlement(
        free_trial_used=True,
        test_access_until="2027-05-08T00:00:00+00:00",
        test_access_enabled=True,
        extra_one_day_remaining=1,
        processed_payment_charge_ids=["charge-1"],
    )

    save_entitlements(path, {123: entitlement})
    loaded = load_entitlements(path)

    assert loaded[123].free_trial_used
    assert loaded[123].test_access_until == "2027-05-08T00:00:00+00:00"
    assert loaded[123].test_access_enabled
    assert loaded[123].extra_one_day_remaining == 1
    assert loaded[123].processed_payment_charge_ids == ["charge-1"]


def test_old_entitlement_json_defaults_managed_subscription_fields() -> None:
    entitlement = Entitlement.from_dict(
        {
            "subscription_period_start": "2026-05-01T00:00:00+00:00",
            "subscription_period_end": "2026-06-01T00:00:00+00:00",
            "monthly_one_day_remaining": 2,
            "processed_payment_charge_ids": ["old-charge"],
        }
    )

    assert entitlement.subscription_source == "none"
    assert entitlement.auto_renew_status == "not_applicable"
    assert entitlement.stars_subscription_charge_id is None
    assert entitlement.last_subscription_payment_charge_id is None
    assert entitlement.current_period_payment_order_id is None


def test_managed_stars_subscription_fields_round_trip_json_and_duplicate_guard() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement(
        subscription_period_start=now.isoformat(),
        subscription_period_end=(now + timedelta(days=30)).isoformat(),
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
        stars_subscription_charge_id="stars-sub-1",
        last_subscription_payment_charge_id="payment-charge-1",
        current_period_payment_order_id="order-1",
    )

    loaded = Entitlement.from_dict(entitlement.to_dict())

    assert loaded.subscription_source == "telegram_stars"
    assert loaded.auto_renew_status == "enabled"
    assert loaded.stars_subscription_charge_id == "stars-sub-1"
    assert loaded.last_subscription_payment_charge_id == "payment-charge-1"
    assert loaded.current_period_payment_order_id == "order-1"
    assert has_active_managed_stars_subscription(loaded, now)


def test_subscription_payment_can_mark_managed_stars_subscription() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement()

    result = apply_subscription_payment(
        entitlement,
        "telegram_stars:tg-charge-1",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
        stars_subscription_charge_id="stars-sub-1",
        last_subscription_payment_charge_id="tg-charge-1",
        current_period_payment_order_id="order-1",
    )

    assert result.processed
    assert entitlement.subscription_source == "telegram_stars"
    assert entitlement.auto_renew_status == "enabled"
    assert entitlement.stars_subscription_charge_id == "stars-sub-1"
    assert entitlement.last_subscription_payment_charge_id == "tg-charge-1"
    assert entitlement.current_period_payment_order_id == "order-1"


def test_extra_payments_do_not_mutate_managed_subscription_fields() -> None:
    entitlement = Entitlement(
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
        stars_subscription_charge_id="stars-sub-1",
        last_subscription_payment_charge_id="payment-charge-1",
        current_period_payment_order_id="order-1",
    )

    apply_extra_one_day_payment(entitlement, "extra-day-1")
    apply_extra_weekly_pdf_payment(entitlement, "extra-week-1")

    assert entitlement.subscription_source == "telegram_stars"
    assert entitlement.auto_renew_status == "enabled"
    assert entitlement.stars_subscription_charge_id == "stars-sub-1"
    assert entitlement.last_subscription_payment_charge_id == "payment-charge-1"
    assert entitlement.current_period_payment_order_id == "order-1"


def test_refunded_current_subscription_revokes_paid_entitlement() -> None:
    apply_reversal = getattr(subscriptions, "apply_payment_reversal")
    paid_at = datetime(2026, 5, 8, tzinfo=UTC)
    refunded_at = paid_at + timedelta(days=3)
    charge_id = "telegram_stars:tg-charge-refund"
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        charge_id,
        now=paid_at,
        subscription_expiration_timestamp=int((paid_at + timedelta(days=30)).timestamp()),
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
        stars_subscription_charge_id=charge_id,
        last_subscription_payment_charge_id=charge_id,
        current_period_payment_order_id="order-refund",
    )

    result = apply_reversal(
        entitlement,
        "subscription_month",
        charge_id,
        order_id="order-refund",
        reversal_status="refunded",
        now=refunded_at,
    )

    assert result.processed
    assert not result.manual_review_required
    assert not entitlement.is_subscription_active(refunded_at)
    assert entitlement.subscription_period_end == refunded_at.isoformat()
    assert entitlement.monthly_one_day_remaining == 0
    assert entitlement.monthly_weekly_pdf_remaining == 0
    assert entitlement.auto_renew_status == "canceled"
    assert f"reversal:refunded:{charge_id}" in entitlement.processed_payment_charge_ids


def test_repeated_refund_reversal_is_idempotent() -> None:
    apply_reversal = getattr(subscriptions, "apply_payment_reversal")
    now = datetime(2026, 5, 8, tzinfo=UTC)
    charge_id = "telegram_stars:tg-charge-repeat"
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        charge_id,
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
        last_subscription_payment_charge_id=charge_id,
        current_period_payment_order_id="order-repeat",
    )

    first = apply_reversal(
        entitlement,
        "subscription_month",
        charge_id,
        order_id="order-repeat",
        reversal_status="refunded",
        now=now + timedelta(days=1),
    )
    second = apply_reversal(
        entitlement,
        "subscription_month",
        charge_id,
        order_id="order-repeat",
        reversal_status="refunded",
        now=now + timedelta(days=2),
    )

    assert first.processed
    assert not second.processed
    assert second.duplicate
    assert entitlement.processed_payment_charge_ids.count(f"reversal:refunded:{charge_id}") == 1
    assert entitlement.subscription_period_end == (now + timedelta(days=1)).isoformat()


def test_refund_of_old_payment_does_not_revoke_later_valid_subscription() -> None:
    apply_reversal = getattr(subscriptions, "apply_payment_reversal")
    first_paid_at = datetime(2026, 5, 8, tzinfo=UTC)
    second_paid_at = first_paid_at + timedelta(days=7)
    first_charge_id = "telegram_stars:tg-charge-old"
    second_charge_id = "telegram_stars:tg-charge-current"
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        first_charge_id,
        now=first_paid_at,
        subscription_expiration_timestamp=int((first_paid_at + timedelta(days=30)).timestamp()),
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
        last_subscription_payment_charge_id=first_charge_id,
        current_period_payment_order_id="order-old",
    )
    apply_subscription_payment(
        entitlement,
        second_charge_id,
        now=second_paid_at,
        subscription_expiration_timestamp=int((second_paid_at + timedelta(days=30)).timestamp()),
        subscription_source="telegram_stars",
        auto_renew_status="enabled",
        last_subscription_payment_charge_id=second_charge_id,
        current_period_payment_order_id="order-current",
    )

    result = apply_reversal(
        entitlement,
        "subscription_month",
        first_charge_id,
        order_id="order-old",
        reversal_status="refunded",
        now=second_paid_at + timedelta(days=1),
    )

    assert result.processed
    assert result.manual_review_required
    assert result.reason == "subscription_charge_not_current"
    assert entitlement.is_subscription_active(second_paid_at + timedelta(days=1))
    assert entitlement.last_subscription_payment_charge_id == second_charge_id
    assert entitlement.current_period_payment_order_id == "order-current"


def test_refund_of_extra_purchase_revokes_one_extra_unit_without_removing_test_access() -> None:
    apply_reversal = getattr(subscriptions, "apply_payment_reversal")
    entitlement = Entitlement()
    apply_extra_weekly_pdf_payment(entitlement, "telegram_stars:tg-extra-refunded")
    apply_extra_weekly_pdf_payment(entitlement, "telegram_stars:tg-extra-current")
    grant_test_access(entitlement, now=datetime(2026, 5, 8, tzinfo=UTC))

    result = apply_reversal(
        entitlement,
        "extra_weekly_pdf",
        "telegram_stars:tg-extra-refunded",
        order_id="order-extra-refunded",
        reversal_status="refunded",
        now=datetime(2026, 5, 9, tzinfo=UTC),
    )

    assert result.processed
    assert result.manual_review_required
    assert result.reason == "extra_entitlement_requires_manual_review"
    assert entitlement.extra_weekly_pdf_remaining == 1
    assert entitlement.is_test_access_active(datetime(2026, 5, 9, tzinfo=UTC))


def test_refund_of_extra_purchase_without_active_counter_stays_manual_review_only() -> None:
    apply_reversal = getattr(subscriptions, "apply_payment_reversal")
    now = datetime(2026, 5, 9, tzinfo=UTC)
    charge_id = "telegram_stars:tg-extra-consumed"
    entitlement = Entitlement(free_trial_used=True)
    apply_extra_one_day_payment(entitlement, charge_id)
    consumption = consume_one_day_attempt(entitlement, now)

    result = apply_reversal(
        entitlement,
        "extra_one_day",
        charge_id,
        order_id="order-extra-consumed",
        reversal_status="refunded",
        now=now,
    )

    assert consumption.allowed
    assert consumption.source == "extra"
    assert result.processed
    assert result.manual_review_required
    assert result.reason == "extra_entitlement_requires_manual_review"
    assert entitlement.extra_one_day_remaining == 0
    assert f"reversal:refunded:{charge_id}" in entitlement.processed_payment_charge_ids
