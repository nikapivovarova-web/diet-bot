import pytest

from diet_bot.payments import (
    PRODUCT_EXTRA_ONE_DAY,
    PRODUCT_EXTRA_WEEKLY_PDF,
    PRODUCT_SUBSCRIPTION_MONTH,
    PROVIDER_TELEGRAM_STARS,
    PROVIDER_YOOKASSA,
    PaymentPayloadError,
    PaymentProductPrice,
    decode_payment_order_payload,
    encode_payment_order_payload,
    expected_payment_price,
)


def test_payment_order_payload_roundtrip() -> None:
    payload = encode_payment_order_payload("order_1234567890", "nonce_abcdef123456")

    decoded = decode_payment_order_payload(payload)

    assert decoded is not None
    assert decoded.order_id == "order_1234567890"
    assert decoded.nonce == "nonce_abcdef123456"
    assert len(payload) <= 128


@pytest.mark.parametrize(
    "payload",
    [
        "diet:stars:subscription_month",
        "diet:stars:extra_one_day",
        "diet:stars:extra_weekly_pdf",
        "diet:rub:subscription_month",
        "diet:rub:extra_one_day",
        "diet:rub:extra_weekly_pdf",
        "some-other-payload",
        "",
    ],
)
def test_static_or_non_order_payload_decodes_as_none(payload: str) -> None:
    assert decode_payment_order_payload(payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        "diet:order:v1",
        "diet:order:v2:order_12345678:nonce_12345678:checksum",
        "diet:order:v1:short:nonce_12345678:checksum",
        "diet:order:v1:order_12345678:short:checksum",
        "diet:order:v1:order_12345678:nonce_12345678:not-valid",
    ],
)
def test_malformed_order_payloads_are_rejected(payload: str) -> None:
    with pytest.raises(PaymentPayloadError):
        decode_payment_order_payload(payload)


def test_tampered_order_payload_checksum_is_rejected() -> None:
    payload = encode_payment_order_payload("order_1234567890", "nonce_abcdef123456")
    tampered = payload.replace("order_1234567890", "order_1234567899")

    with pytest.raises(PaymentPayloadError, match="checksum"):
        decode_payment_order_payload(tampered)


@pytest.mark.parametrize(
    ("provider", "product", "expected"),
    [
        (
            PROVIDER_TELEGRAM_STARS,
            PRODUCT_SUBSCRIPTION_MONTH,
            PaymentProductPrice(amount=450, currency="XTR"),
        ),
        (PROVIDER_TELEGRAM_STARS, PRODUCT_EXTRA_ONE_DAY, PaymentProductPrice(amount=29, currency="XTR")),
        (
            PROVIDER_TELEGRAM_STARS,
            PRODUCT_EXTRA_WEEKLY_PDF,
            PaymentProductPrice(amount=141, currency="XTR"),
        ),
        (PROVIDER_YOOKASSA, PRODUCT_SUBSCRIPTION_MONTH, PaymentProductPrice(amount=79_900, currency="RUB")),
        (PROVIDER_YOOKASSA, PRODUCT_EXTRA_ONE_DAY, PaymentProductPrice(amount=5_000, currency="RUB")),
        (PROVIDER_YOOKASSA, PRODUCT_EXTRA_WEEKLY_PDF, PaymentProductPrice(amount=25_000, currency="RUB")),
    ],
)
def test_expected_payment_price_matches_existing_static_products(
    provider: str,
    product: str,
    expected: PaymentProductPrice,
) -> None:
    assert expected_payment_price(provider, product) == expected
