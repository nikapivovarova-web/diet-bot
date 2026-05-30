from datetime import UTC, datetime, timedelta

from diet_bot.promo_codes import (
    PromoCodeDefinition,
    PromoCodeKind,
    PromoCodeRecord,
    activate_promo_code,
    calculate_discount_amount,
    generate_promo_codes,
    load_promo_codes,
    normalize_promo_code,
    release_promo_code_activation,
    save_promo_codes,
)


def test_promo_definition_normalizes_code_and_validates_discount() -> None:
    promo = PromoCodeDefinition(
        code="fb abcd efgh 2345",
        kind=PromoCodeKind.DISCOUNT,
        max_redemptions=10,
        per_user_limit=2,
        discount_percent=25,
        expires_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )

    assert promo.code == "FB-ABCD-EFGH-2345"
    assert promo.kind == PromoCodeKind.DISCOUNT
    assert promo.expires_at == "2026-06-01T12:00:00+00:00"

    try:
        PromoCodeDefinition(code="FB-ABCD-EFGH-2345", kind=PromoCodeKind.DISCOUNT)
    except ValueError as exc:
        assert "discount" in str(exc)
    else:
        raise AssertionError("discount promo without discount amount must fail")


def test_monthly_access_promo_definition_defaults_to_one_time_month() -> None:
    promo = PromoCodeDefinition(code="FB-ABCD-EFGH-2345")

    assert promo.kind == PromoCodeKind.MONTHLY_ACCESS
    assert promo.max_redemptions == 1
    assert promo.per_user_limit == 1
    assert promo.monthly_duration_months == 1


def test_discount_amount_calculation_reduces_price_without_free_order() -> None:
    percent = PromoCodeDefinition(
        code="FB-DISC-OUNT-2026",
        kind=PromoCodeKind.DISCOUNT,
        max_redemptions=10,
        discount_percent=20,
    )
    fixed = PromoCodeDefinition(
        code="FB-FIXD-OUNT-2026",
        kind=PromoCodeKind.DISCOUNT,
        max_redemptions=10,
        discount_amount=1_500,
    )
    access = PromoCodeDefinition(code="FB-ACCE-SSSS-2026")
    free = PromoCodeDefinition(
        code="FB-FREE-EEEE-2026",
        kind=PromoCodeKind.DISCOUNT,
        max_redemptions=10,
        discount_percent=100,
    )

    assert calculate_discount_amount(percent, 79_900) == 15_980
    assert calculate_discount_amount(fixed, 79_900) == 1_500
    try:
        calculate_discount_amount(access, 79_900)
    except ValueError as exc:
        assert "discount" in str(exc)
    else:
        raise AssertionError("monthly access promo must not calculate a discount")
    try:
        calculate_discount_amount(free, 79_900)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("discount promo must not create a free order")


def test_generate_promo_codes_creates_unique_monthly_codes() -> None:
    codes = generate_promo_codes(200)

    assert len(codes) == 200
    assert len(set(codes)) == 200
    assert all(code.startswith("FB-") for code in codes)
    assert all(len(code) == len("FB-AAAA-BBBB-CCCC") for code in codes)


def test_promo_code_activation_is_one_time(tmp_path) -> None:
    path = tmp_path / "promo_codes.json"
    save_promo_codes(path, {"FB-ABCD-EFGH-2345": PromoCodeRecord.monthly_access()})

    first = activate_promo_code(
        path,
        "fb abcd efgh 2345",
        123,
        now=datetime(2026, 5, 9, 10, 0, tzinfo=UTC),
    )
    second = activate_promo_code(path, "FB-ABCD-EFGH-2345", 456)
    loaded = load_promo_codes(path)

    assert first.activated
    assert first.code == "FB-ABCD-EFGH-2345"
    assert second.status == "already_used"
    assert second.used_by_chat_id == 123
    assert loaded["FB-ABCD-EFGH-2345"].used_by_chat_id == 123
    assert loaded["FB-ABCD-EFGH-2345"].used_at == "2026-05-09T10:00:00+00:00"


def test_discount_promo_is_not_activated_as_monthly_access(tmp_path) -> None:
    path = tmp_path / "promo_codes.json"
    save_promo_codes(
        path,
        {
            "FB-DISC-OUNT-2026": PromoCodeRecord.from_definition(
                PromoCodeDefinition(
                    code="FB-DISC-OUNT-2026",
                    kind=PromoCodeKind.DISCOUNT,
                    max_redemptions=5,
                    per_user_limit=1,
                    discount_percent=15,
                )
            )
        },
    )

    result = activate_promo_code(path, "FB-DISC-OUNT-2026", 123)
    loaded = load_promo_codes(path)

    assert result.status == "not_access_code"
    assert loaded["FB-DISC-OUNT-2026"].used_by_chat_id is None


def test_disabled_and_expired_monthly_access_promo_is_not_activated(tmp_path) -> None:
    path = tmp_path / "promo_codes.json"
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    save_promo_codes(
        path,
        {
            "FB-DISA-BLED-2026": PromoCodeRecord(active=False),
            "FB-EXPI-REDX-2026": PromoCodeRecord(expires_at=(now - timedelta(seconds=1)).isoformat()),
        },
    )

    disabled = activate_promo_code(path, "FB-DISA-BLED-2026", 123, now=now)
    expired = activate_promo_code(path, "FB-EXPI-REDX-2026", 123, now=now)
    loaded = load_promo_codes(path)

    assert disabled.status == "disabled"
    assert expired.status == "expired"
    assert loaded["FB-DISA-BLED-2026"].used_by_chat_id is None
    assert loaded["FB-EXPI-REDX-2026"].used_by_chat_id is None


def test_release_promo_code_activation_clears_same_chat_claim(tmp_path) -> None:
    path = tmp_path / "promo_codes.json"
    save_promo_codes(
        path,
        {
            "FB-ABCD-EFGH-2345": PromoCodeRecord(
                used_by_chat_id=123,
                used_at="2026-05-09T10:00:00+00:00",
            ),
        },
    )

    release_promo_code_activation(path, "fb abcd efgh 2345", 123)

    loaded = load_promo_codes(path)
    assert loaded["FB-ABCD-EFGH-2345"].used_by_chat_id is None
    assert loaded["FB-ABCD-EFGH-2345"].used_at is None


def test_release_promo_code_activation_keeps_other_chat_claim(tmp_path) -> None:
    path = tmp_path / "promo_codes.json"
    save_promo_codes(
        path,
        {
            "FB-ABCD-EFGH-2345": PromoCodeRecord(
                used_by_chat_id=123,
                used_at="2026-05-09T10:00:00+00:00",
            ),
        },
    )

    release_promo_code_activation(path, "FB-ABCD-EFGH-2345", 456)

    loaded = load_promo_codes(path)
    assert loaded["FB-ABCD-EFGH-2345"].used_by_chat_id == 123
    assert loaded["FB-ABCD-EFGH-2345"].used_at == "2026-05-09T10:00:00+00:00"


def test_unknown_promo_code_is_not_found(tmp_path) -> None:
    result = activate_promo_code(tmp_path / "promo_codes.json", "unknown", 123)

    assert result.status == "not_found"


def test_normalize_promo_code_accepts_hyphenless_input() -> None:
    assert normalize_promo_code("fbabcdef123456") == "FB-ABCD-EF12-3456"
