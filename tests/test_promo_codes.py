from datetime import UTC, datetime

from diet_bot.promo_codes import (
    PromoCodeRecord,
    activate_promo_code,
    generate_promo_codes,
    load_promo_codes,
    normalize_promo_code,
    promo_code_lookup_key,
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
    lookup_key = promo_code_lookup_key("FB-ABCD-EFGH-2345")

    assert first.activated
    assert first.code == "FB-ABCD-EFGH-2345"
    assert first.lookup_key == lookup_key
    assert second.status == "already_used"
    assert second.used_by_chat_id == 123
    assert loaded[lookup_key].used_by_chat_id == 123
    assert loaded[lookup_key].used_at == "2026-05-09T10:00:00+00:00"
    assert "FB-ABCD-EFGH-2345" not in path.read_text(encoding="utf-8")


def test_unknown_promo_code_is_not_found(tmp_path) -> None:
    result = activate_promo_code(tmp_path / "promo_codes.json", "unknown", 123)

    assert result.status == "not_found"


def test_normalize_promo_code_accepts_hyphenless_input() -> None:
    assert normalize_promo_code("fbabcdef123456") == "FB-ABCD-EF12-3456"


def test_promo_code_lookup_key_is_stable_for_normalized_forms() -> None:
    assert promo_code_lookup_key("fb abcd efgh 2345") == promo_code_lookup_key("FB-ABCD-EFGH-2345")
    assert promo_code_lookup_key("FB-ABCD-EFGH-2345").startswith("sha256:")


def test_corrupt_promo_code_state_raises_instead_of_returning_empty(tmp_path) -> None:
    path = tmp_path / "promo_codes.json"
    path.write_text("{broken", encoding="utf-8")

    try:
        load_promo_codes(path)
    except RuntimeError as exc:
        assert "Invalid promo code state file" in str(exc)
    else:
        raise AssertionError("Expected corrupt promo JSON to raise")
