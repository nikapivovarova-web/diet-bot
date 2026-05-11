from datetime import UTC, datetime, timedelta

from diet_bot.subscriptions import (
    MONTHLY_ONE_DAY_LIMIT,
    MONTHLY_WEEKLY_PDF_LIMIT,
    Entitlement,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_payment_reversal,
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


def test_subscription_payment_extends_active_period_from_current_end() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement()
    first_end = now + timedelta(days=30)
    second_payment_time = now + timedelta(days=10)

    apply_subscription_payment(
        entitlement,
        "charge-1",
        now=now,
        subscription_expiration_timestamp=int(first_end.timestamp()),
    )
    apply_subscription_payment(
        entitlement,
        "charge-2",
        now=second_payment_time,
        subscription_expiration_timestamp=int((second_payment_time + timedelta(days=30)).timestamp()),
    )

    subscription_end = datetime.fromisoformat(entitlement.subscription_period_end or "")

    assert subscription_end == first_end + timedelta(days=30)
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


def test_extra_attempts_require_active_subscription_to_consume() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement(
        free_trial_used=True,
        subscription_period_start=(now - timedelta(days=31)).isoformat(),
        subscription_period_end=(now - timedelta(days=1)).isoformat(),
        extra_one_day_remaining=1,
        extra_weekly_pdf_remaining=1,
    )

    one_day = consume_one_day_attempt(entitlement, now)
    weekly_pdf = consume_weekly_pdf_attempt(entitlement, now)

    assert not one_day.allowed
    assert not weekly_pdf.allowed
    assert entitlement.extra_one_day_remaining == 1
    assert entitlement.extra_weekly_pdf_remaining == 1


def test_extra_attempts_unlock_after_subscription_renewal() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    entitlement = Entitlement(
        free_trial_used=True,
        extra_one_day_remaining=1,
        extra_weekly_pdf_remaining=1,
    )
    assert not consume_one_day_attempt(entitlement, now).allowed
    assert not consume_weekly_pdf_attempt(entitlement, now).allowed

    apply_subscription_payment(
        entitlement,
        "charge-sub",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 0
    entitlement.monthly_weekly_pdf_remaining = 0

    one_day = consume_one_day_attempt(entitlement, now)
    weekly_pdf = consume_weekly_pdf_attempt(entitlement, now)

    assert one_day.source == "extra"
    assert weekly_pdf.source == "extra"
    assert entitlement.extra_one_day_remaining == 0
    assert entitlement.extra_weekly_pdf_remaining == 0


def test_extra_reversal_reports_already_consumed_when_no_remaining_quota() -> None:
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

    consume_one_day_attempt(entitlement, now)
    extra = consume_one_day_attempt(entitlement, now)
    result = apply_payment_reversal(entitlement, "extra_one_day", "refund", now=now)

    assert extra.source == "extra"
    assert not result.processed
    assert result.reason == "extra_already_consumed"
    assert entitlement.extra_one_day_remaining == 0

    weekly_entitlement = Entitlement(extra_weekly_pdf_remaining=0)
    weekly_result = apply_payment_reversal(weekly_entitlement, "extra_weekly_pdf", "refund", now=now)

    assert not weekly_result.processed
    assert weekly_result.reason == "extra_already_consumed"
    assert weekly_entitlement.extra_weekly_pdf_remaining == 0


def test_extra_reversal_decrements_available_weekly_pdf_quota() -> None:
    entitlement = Entitlement(extra_weekly_pdf_remaining=1)

    result = apply_payment_reversal(entitlement, "extra_weekly_pdf", "refund")

    assert result.processed
    assert result.reason is None
    assert entitlement.extra_weekly_pdf_remaining == 0


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


def test_corrupt_subscription_state_raises_instead_of_returning_empty(tmp_path) -> None:
    path = tmp_path / "subscriptions.json"
    path.write_text("{broken", encoding="utf-8")

    try:
        load_entitlements(path)
    except RuntimeError as exc:
        assert "Invalid entitlements state file" in str(exc)
    else:
        raise AssertionError("Expected corrupt subscription JSON to raise")
