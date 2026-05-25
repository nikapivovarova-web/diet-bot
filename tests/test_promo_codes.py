from datetime import UTC, datetime

from diet_bot.promo_codes import (
    PromoCodeRecord,
    activate_promo_code,
    generate_promo_codes,
    load_promo_codes,
    normalize_promo_code,
    release_promo_code_activation,
    save_promo_codes,
)


def test_generate_promo_codes_creates_unique_monthly_codes() -> None:
    codes = generate_promo_codes(200)

    assert len(codes) == 200
    assert len(set(codes)) == 200
    assert all(code.startswith("FB-") for code in codes)
    assert all(len(code) == len("FB-AAAA-BBBB-CCCC") for code in codes)


def test_promo_code_activation_is_one_time(tmp_path) -> None:
    path = tmp_path / "promo_codes.json"
    save_promo_codes(path, {"FB-ABCD-EFGH-2345": PromoCodeRecord()})

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
