from datetime import UTC, datetime, timedelta

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
    load_entitlements,
    refund_attempt,
    revoke_test_access,
    save_entitlements,
    set_test_access_enabled,
)


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
