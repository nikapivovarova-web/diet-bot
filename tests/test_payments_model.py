from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from diet_bot.payments import (
    PAYMENT_ORDER_TTL_SECONDS,
    PAYMENT_TEST_SMOKE_PRICING_CONTEXT,
    PROVIDER_CURRENCIES,
    TELEGRAM_STARS_SUBSCRIPTION_PERIOD_SECONDS,
    PaymentCurrency,
    PaymentEvent,
    PaymentEventStatus,
    PaymentEventType,
    PaymentInvoiceMetadata,
    PaymentOrder,
    PaymentOrderCreationCode,
    PaymentOrderStatus,
    PaymentPayloadError,
    PaymentPreCheckoutCode,
    PaymentPreCheckoutValidation,
    PaymentProductInvoiceMetadata,
    PaymentProduct,
    PaymentProvider,
    PaymentReconciliationAction,
    PaymentReconciliationCode,
    PaymentReconciliationInput,
    PaymentReversalCode,
    PaymentReversalInput,
    PaymentSuccessfulPaymentCode,
    PaymentSuccessfulPaymentInput,
    ProcessedProviderCharge,
    apply_payment_reversal,
    apply_payment_reconciliation,
    apply_successful_payment,
    build_payment_invoice_metadata,
    build_payment_invoice_payload,
    create_or_reuse_pending_payment_order,
    decode_payment_order_payload,
    encode_payment_order_payload,
    get_payment_product_invoice_metadata,
    redact_payment_payload,
    validate_payment_pre_checkout,
    validate_payment_invoice_payload,
)
from diet_bot.subscriptions import Entitlement, consume_one_day_attempt


def test_payment_order_payload_round_trips_order_id_and_nonce() -> None:
    payload = encode_payment_order_payload("order_123", "nonce_456")

    assert payload == "diet:order:order_123:nonce_456"
    assert decode_payment_order_payload(payload) == ("order_123", "nonce_456")


def test_invoice_payload_helper_uses_order_id_and_nonce_for_each_order() -> None:
    orders = [
        _payment_order("order_sub1", "nonce_sub1", PaymentProduct.SUBSCRIPTION_MONTH),
        _payment_order("order_day1", "nonce_day1", PaymentProduct.EXTRA_ONE_DAY),
        _payment_order("order_pdf1", "nonce_pdf1", PaymentProduct.EXTRA_WEEKLY_PDF),
    ]

    payloads = [build_payment_invoice_payload(order) for order in orders]

    assert payloads == [
        "diet:order:order_sub1:nonce_sub1",
        "diet:order:order_day1:nonce_day1",
        "diet:order:order_pdf1:nonce_pdf1",
    ]
    assert [decode_payment_order_payload(payload) for payload in payloads] == [
        ("order_sub1", "nonce_sub1"),
        ("order_day1", "nonce_day1"),
        ("order_pdf1", "nonce_pdf1"),
    ]


def test_different_payment_orders_get_different_invoice_payloads() -> None:
    first = _payment_order("order_aaa1", "nonce_same", PaymentProduct.SUBSCRIPTION_MONTH)
    second = _payment_order("order_bbb1", "nonce_same", PaymentProduct.SUBSCRIPTION_MONTH)
    third = _payment_order("order_aaa1", "nonce_diff", PaymentProduct.SUBSCRIPTION_MONTH)

    assert len(
        {
            build_payment_invoice_payload(first),
            build_payment_invoice_payload(second),
            build_payment_invoice_payload(third),
        }
    ) == 3


@pytest.mark.parametrize(
    "payload",
    [
        "diet:order::nonce_456",
        "diet:order:order_123:",
        "diet:order:order_123:nonce_456:extra",
        "diet:order:order 123:nonce_456",
        "diet:order:order_123:nonce/456",
        "wrong:order:order_123:nonce_456",
    ],
)
def test_tampered_payment_order_payload_is_rejected(payload: str) -> None:
    with pytest.raises(PaymentPayloadError):
        decode_payment_order_payload(payload)


@pytest.mark.parametrize(
    "payload",
    [
        "subscription_month",
        "extra_one_day",
        "extra_weekly_pdf",
        "diet:stars:subscription_month",
        "diet:stars:extra_one_day",
        "diet:stars:extra_weekly_pdf",
        "diet:rub:subscription_month",
        "diet:rub:extra_one_day",
        "diet:rub:extra_weekly_pdf",
    ],
)
def test_static_legacy_payment_payload_is_rejected_by_default(payload: str) -> None:
    with pytest.raises(PaymentPayloadError):
        decode_payment_order_payload(payload)


def test_tampered_invoice_payload_nonce_is_rejected_against_order() -> None:
    order = _payment_order("order_123", "nonce_456", PaymentProduct.SUBSCRIPTION_MONTH)
    tampered_payload = "diet:order:order_123:nonce_999"

    assert validate_payment_invoice_payload(order, order.payload) == (order.order_id, order.nonce)
    with pytest.raises(PaymentPayloadError):
        validate_payment_invoice_payload(order, tampered_payload)


def test_pre_checkout_validation_approves_valid_pending_order_and_records_approval() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_123",
        "nonce_456",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentOrderRepository([order])

    result = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=order.currency,
        total_amount=order.amount,
        expected_provider=order.provider,
        expected_product=order.product,
        now=now,
    )

    assert isinstance(result, PaymentPreCheckoutValidation)
    assert result.approved is True
    assert result.code == PaymentPreCheckoutCode.APPROVED
    assert result.order is not None
    assert result.order.pre_checkout_approved_at == now
    assert repository.pre_checkout_approvals == [("order_123", now)]


def test_pre_checkout_validation_rejects_static_legacy_payload_without_recording_approval() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    repository = InMemoryPaymentOrderRepository()

    result = validate_payment_pre_checkout(
        repository,
        payload="subscription_month",
        user_id=1001,
        currency=PaymentCurrency.XTR,
        total_amount=400,
        now=now,
    )

    assert result.approved is False
    assert result.code == PaymentPreCheckoutCode.INVALID_PAYLOAD
    assert result.order is None
    assert repository.pre_checkout_approvals == []


def test_pre_checkout_validation_rejects_tampered_nonce_without_recording_approval() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_123",
        "nonce_456",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentOrderRepository([order])

    result = validate_payment_pre_checkout(
        repository,
        payload="diet:order:order_123:nonce_999",
        user_id=order.user_id,
        currency=order.currency,
        total_amount=order.amount,
        now=now,
    )

    assert result.approved is False
    assert result.code == PaymentPreCheckoutCode.NONCE_MISMATCH
    assert result.order == order
    assert repository.pre_checkout_approvals == []


def test_pre_checkout_validation_rejects_missing_order_without_recording_approval() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    repository = InMemoryPaymentOrderRepository()

    result = validate_payment_pre_checkout(
        repository,
        payload="diet:order:order_missing:nonce_456",
        user_id=1001,
        currency=PaymentCurrency.XTR,
        total_amount=400,
        now=now,
    )

    assert result.approved is False
    assert result.code == PaymentPreCheckoutCode.ORDER_NOT_FOUND
    assert result.order is None
    assert repository.pre_checkout_approvals == []


@pytest.mark.parametrize(
    "status",
    [
        PaymentOrderStatus.PAID,
        PaymentOrderStatus.EXPIRED,
        PaymentOrderStatus.FAILED_INVOICE_CREATION,
    ],
)
def test_pre_checkout_validation_rejects_non_pending_order_statuses(
    status: PaymentOrderStatus,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_123",
        "nonce_456",
        PaymentProduct.SUBSCRIPTION_MONTH,
        status=status,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentOrderRepository([order])

    result = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=order.currency,
        total_amount=order.amount,
        now=now,
    )

    assert result.approved is False
    assert result.code == PaymentPreCheckoutCode.ORDER_NOT_PENDING
    assert result.order == order
    assert repository.pre_checkout_approvals == []


def test_pre_checkout_validation_rejects_and_marks_expired_pending_order() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_123",
        "nonce_456",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now - timedelta(seconds=1),
    )
    repository = InMemoryPaymentOrderRepository([order])

    result = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=order.currency,
        total_amount=order.amount,
        now=now,
    )

    assert result.approved is False
    assert result.code == PaymentPreCheckoutCode.ORDER_EXPIRED
    assert repository.expired_order_ids == ["order_123"]
    assert repository.load_payment_order("order_123").status == PaymentOrderStatus.EXPIRED
    assert repository.pre_checkout_approvals == []


def test_pre_checkout_validation_rejects_wrong_user_without_recording_approval() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_123",
        "nonce_456",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentOrderRepository([order])

    result = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=9999,
        currency=order.currency,
        total_amount=order.amount,
        now=now,
    )

    assert result.approved is False
    assert result.code == PaymentPreCheckoutCode.USER_MISMATCH
    assert repository.pre_checkout_approvals == []


@pytest.mark.parametrize(
    ("currency", "total_amount", "expected_code"),
    [
        (PaymentCurrency.RUB, 400, PaymentPreCheckoutCode.CURRENCY_MISMATCH),
        (PaymentCurrency.XTR, 399, PaymentPreCheckoutCode.AMOUNT_MISMATCH),
    ],
)
def test_pre_checkout_validation_rejects_wrong_currency_or_amount(
    currency: PaymentCurrency,
    total_amount: int,
    expected_code: PaymentPreCheckoutCode,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_123",
        "nonce_456",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentOrderRepository([order])

    result = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=currency,
        total_amount=total_amount,
        now=now,
    )

    assert result.approved is False
    assert result.code == expected_code
    assert repository.pre_checkout_approvals == []


@pytest.mark.parametrize(
    ("expected_provider", "expected_product", "expected_code"),
    [
        (
            PaymentProvider.YOOKASSA,
            PaymentProduct.SUBSCRIPTION_MONTH,
            PaymentPreCheckoutCode.PROVIDER_MISMATCH,
        ),
        (
            PaymentProvider.TELEGRAM_STARS,
            PaymentProduct.EXTRA_ONE_DAY,
            PaymentPreCheckoutCode.PRODUCT_MISMATCH,
        ),
    ],
)
def test_pre_checkout_validation_rejects_wrong_provider_or_product_when_expected(
    expected_provider: PaymentProvider,
    expected_product: PaymentProduct,
    expected_code: PaymentPreCheckoutCode,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_123",
        "nonce_456",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentOrderRepository([order])

    result = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=order.currency,
        total_amount=order.amount,
        expected_provider=expected_provider,
        expected_product=expected_product,
        now=now,
    )

    assert result.approved is False
    assert result.code == expected_code
    assert repository.pre_checkout_approvals == []


@pytest.mark.parametrize(
    ("product", "amount"),
    [
        (PaymentProduct.EXTRA_ONE_DAY, 35),
        (PaymentProduct.EXTRA_WEEKLY_PDF, 170),
    ],
)
def test_pre_checkout_validation_requires_active_subscription_for_extras_without_mutating_entitlement(
    product: PaymentProduct,
    amount: int,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    entitlement = Entitlement(
        subscription_period_end=(now + timedelta(days=3)).isoformat(),
        monthly_one_day_remaining=2,
        monthly_weekly_pdf_remaining=1,
    )
    before = entitlement.to_dict()
    order = _payment_order(
        "order_123",
        "nonce_456",
        product,
        amount=amount,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentOrderRepository([order])

    rejected = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=order.currency,
        total_amount=order.amount,
        expected_provider=order.provider,
        expected_product=order.product,
        has_active_subscription=False,
        now=now,
    )
    approved = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=order.currency,
        total_amount=order.amount,
        expected_provider=order.provider,
        expected_product=order.product,
        has_active_subscription=entitlement.is_subscription_active(now),
        now=now,
    )

    assert rejected.approved is False
    assert rejected.code == PaymentPreCheckoutCode.ACTIVE_SUBSCRIPTION_REQUIRED
    assert rejected.requires_active_subscription is True
    assert approved.approved is True
    assert approved.code == PaymentPreCheckoutCode.APPROVED
    assert approved.requires_active_subscription is True
    assert repository.pre_checkout_approvals == [("order_123", now)]
    assert entitlement.to_dict() == before


def test_extra_pre_checkout_rejects_when_subscription_expired_after_order_creation() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_day1",
        "nonce_day1",
        PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentCheckoutRepository(
        [order],
        entitlements={
            order.user_id: Entitlement(
                subscription_period_start=(now - timedelta(days=30)).isoformat(),
                subscription_period_end=(now - timedelta(seconds=1)).isoformat(),
            ),
        },
    )

    result = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=order.currency,
        total_amount=order.amount,
        expected_provider=order.provider,
        expected_product=order.product,
        now=now,
    )

    assert result.approved is False
    assert result.code == PaymentPreCheckoutCode.ACTIVE_SUBSCRIPTION_REQUIRED
    assert result.requires_active_subscription is True
    assert repository.pre_checkout_approvals == []


def test_payment_enums_match_production_payment_plan() -> None:
    assert PaymentProvider.TELEGRAM_STARS.value == "telegram_stars"
    assert PaymentProvider.YOOKASSA.value == "yookassa"
    assert PaymentCurrency.XTR.value == "XTR"
    assert PaymentCurrency.RUB.value == "RUB"
    assert PaymentProduct.SUBSCRIPTION_MONTH.value == "subscription_month"
    assert PaymentProduct.EXTRA_ONE_DAY.value == "extra_one_day"
    assert PaymentProduct.EXTRA_WEEKLY_PDF.value == "extra_weekly_pdf"
    assert PROVIDER_CURRENCIES == {
        PaymentProvider.TELEGRAM_STARS: PaymentCurrency.XTR,
        PaymentProvider.YOOKASSA: PaymentCurrency.RUB,
    }


def test_payment_payload_redaction_masks_private_customer_and_secret_values() -> None:
    raw_payload = {
        "email": "buyer@example.com",
        "phone_number": "+37499123456",
        "order_info": {"email": "nested@example.com", "phone": "+79991234567"},
        "provider_token": "381764678:TEST:very-secret-provider-token",
        "bot_token": "123456789:ABCdefGhijKLMnopQRStuVWXyz",
        "database_url": "postgresql://diet_bot:secret@localhost:5432/foodbalance",
        "telegram_payment_charge_id": "tg-charge-sensitive-123456",
        "provider_payment_charge_id": "provider-charge-sensitive-123456",
        "charge_id": "charge-sensitive-abcdef",
        "invoice_payload": "diet:order:order_123:nonce_456",
        "nested": {
            "message": (
                "contact buyer@example.com or +79991234567, "
                "db postgresql://user:pass@example.com/db, "
                "bot 123456789:ABCdefGhijKLMnopQRStuVWXyz"
            )
        },
    }

    redacted = redact_payment_payload(raw_payload)
    serialized = json.dumps(redacted, sort_keys=True)

    for secret in (
        "buyer@example.com",
        "nested@example.com",
        "+37499123456",
        "+79991234567",
        "very-secret-provider-token",
        "123456789:ABCdefGhijKLMnopQRStuVWXyz",
        "postgresql://diet_bot:secret@localhost:5432/foodbalance",
        "postgresql://user:pass@example.com/db",
        "tg-charge-sensitive-123456",
        "provider-charge-sensitive-123456",
        "charge-sensitive-abcdef",
    ):
        assert secret not in serialized
    assert redacted["email"] == "[REDACTED]"
    assert redacted["phone_number"] == "[REDACTED]"
    assert redacted["order_info"] == "[REDACTED]"
    assert redacted["telegram_payment_charge_id"] == "[REDACTED]"
    assert redacted["provider_payment_charge_id"] == "[REDACTED]"
    assert redacted["charge_id"] == "[REDACTED]"
    assert redacted["invoice_payload"] == "diet:order:order_123:nonce_456"


def test_stars_subscription_invoice_metadata_contains_amount_and_subscription_period() -> None:
    order = _payment_order("order_sub1", "nonce_sub1", PaymentProduct.SUBSCRIPTION_MONTH)

    metadata = build_payment_invoice_metadata(order)

    assert isinstance(metadata, PaymentInvoiceMetadata)
    assert metadata.provider == PaymentProvider.TELEGRAM_STARS
    assert metadata.product == PaymentProduct.SUBSCRIPTION_MONTH
    assert metadata.payload == "diet:order:order_sub1:nonce_sub1"
    assert metadata.currency == PaymentCurrency.XTR
    assert metadata.amount == 400
    assert metadata.subscription_period == TELEGRAM_STARS_SUBSCRIPTION_PERIOD_SECONDS == 2_592_000
    assert metadata.need_email is False
    assert metadata.send_email_to_provider is False
    assert metadata.provider_data is None


def test_yookassa_subscription_invoice_metadata_contains_receipt_and_email_flags() -> None:
    order = _payment_order(
        "order_ru1",
        "nonce_ru1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        provider=PaymentProvider.YOOKASSA,
        amount=59_900,
        currency=PaymentCurrency.RUB,
    )

    metadata = build_payment_invoice_metadata(order)

    assert metadata.provider == PaymentProvider.YOOKASSA
    assert metadata.product == PaymentProduct.SUBSCRIPTION_MONTH
    assert metadata.payload == "diet:order:order_ru1:nonce_ru1"
    assert metadata.currency == PaymentCurrency.RUB
    assert metadata.amount == 59_900
    assert metadata.subscription_period is None
    assert metadata.need_email is True
    assert metadata.send_email_to_provider is True
    assert metadata.provider_data is not None
    item = metadata.provider_data["receipt"]["items"][0]
    assert item["amount"] == {"value": "599.00", "currency": "RUB"}
    assert item["quantity"] == "1.00"
    assert item["vat_code"] == 1
    assert item["payment_mode"] == "full_payment"
    assert item["payment_subject"] == "service"


def test_discounted_yookassa_invoice_uses_final_amount_and_redacted_promo_metadata() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_discount1",
        "nonce_discount1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        provider=PaymentProvider.YOOKASSA,
        amount=47_920,
        currency=PaymentCurrency.RUB,
        expires_at=now + timedelta(minutes=5),
        list_amount=59_900,
        discount_amount=11_980,
        promo_code_id=42,
        promo_redemption_id=77,
        promo_code_hash="a" * 64,
        promo_code_suffix="2026",
        metadata={
            "promo_code_id": 42,
            "promo_code_hash": "a" * 64,
            "promo_code_suffix": "2026",
            "discount_amount": 11_980,
            "final_amount": 47_920,
        },
    )
    repository = InMemoryPaymentLedgerRepository([order])

    metadata = build_payment_invoice_metadata(order)
    pre_checkout = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=order.currency,
        total_amount=47_920,
        expected_provider=order.provider,
        expected_product=order.product,
        now=now,
    )
    success = apply_successful_payment(
        repository,
        _successful_payment(
            order,
            telegram_charge_id="tg-charge-discount1",
            provider_charge_id="provider-charge-discount1",
            total_amount=47_920,
        ),
        now=now,
    )
    serialized_metadata = json.dumps(order.metadata, sort_keys=True)

    assert metadata.amount == 47_920
    assert metadata.provider_data is not None
    assert metadata.provider_data["receipt"]["items"][0]["amount"] == {
        "value": "479.20",
        "currency": "RUB",
    }
    assert pre_checkout.approved is True
    assert success.processed is True
    assert repository.get_entitlement(order.user_id).is_subscription_active(now)
    assert "FB-DISC-OUNT-2026" not in serialized_metadata
    assert order.promo_code_suffix == "2026"


def test_discounted_order_rejects_catalog_amount_at_pre_checkout_and_success() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_discount1",
        "nonce_discount1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        amount=300,
        expires_at=now + timedelta(minutes=5),
        list_amount=400,
        discount_amount=100,
        promo_code_id=42,
        promo_code_hash="b" * 64,
        promo_code_suffix="2026",
    )
    repository = InMemoryPaymentLedgerRepository([order])

    pre_checkout = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=order.currency,
        total_amount=400,
        now=now,
    )
    success = apply_successful_payment(
        repository,
        _successful_payment(
            order,
            telegram_charge_id="tg-charge-discount1",
            total_amount=400,
        ),
        now=now,
    )

    assert pre_checkout.approved is False
    assert pre_checkout.code == PaymentPreCheckoutCode.AMOUNT_MISMATCH
    assert success.processed is False
    assert success.code == PaymentSuccessfulPaymentCode.AMOUNT_MISMATCH
    assert repository.get_entitlement(order.user_id) == Entitlement()


@pytest.mark.parametrize(
    ("provider", "product", "currency", "amount"),
    [
        (PaymentProvider.TELEGRAM_STARS, PaymentProduct.SUBSCRIPTION_MONTH, PaymentCurrency.XTR, 400),
        (PaymentProvider.TELEGRAM_STARS, PaymentProduct.EXTRA_ONE_DAY, PaymentCurrency.XTR, 35),
        (PaymentProvider.TELEGRAM_STARS, PaymentProduct.EXTRA_WEEKLY_PDF, PaymentCurrency.XTR, 170),
        (PaymentProvider.YOOKASSA, PaymentProduct.SUBSCRIPTION_MONTH, PaymentCurrency.RUB, 59_900),
        (PaymentProvider.YOOKASSA, PaymentProduct.EXTRA_ONE_DAY, PaymentCurrency.RUB, 5_000),
        (PaymentProvider.YOOKASSA, PaymentProduct.EXTRA_WEEKLY_PDF, PaymentCurrency.RUB, 25_000),
    ],
)
def test_product_invoice_metadata_contains_provider_product_currency_and_amount(
    provider: PaymentProvider,
    product: PaymentProduct,
    currency: PaymentCurrency,
    amount: int,
) -> None:
    metadata = get_payment_product_invoice_metadata(provider, product)

    assert isinstance(metadata, PaymentProductInvoiceMetadata)
    assert metadata.provider == provider
    assert metadata.product == product
    assert metadata.currency == currency
    assert metadata.amount == amount
    if provider == PaymentProvider.YOOKASSA:
        assert metadata.need_email is True
        assert metadata.send_email_to_provider is True
        assert metadata.provider_data is not None
    else:
        assert metadata.need_email is False
        assert metadata.send_email_to_provider is False
        assert metadata.provider_data is None


def test_product_invoice_metadata_uses_production_prices_by_default() -> None:
    stars = get_payment_product_invoice_metadata(
        PaymentProvider.TELEGRAM_STARS,
        PaymentProduct.SUBSCRIPTION_MONTH,
    )
    yookassa = get_payment_product_invoice_metadata(
        PaymentProvider.YOOKASSA,
        PaymentProduct.SUBSCRIPTION_MONTH,
    )

    assert stars.amount == 400
    assert yookassa.amount == 59_900
    assert yookassa.provider_data is not None
    assert yookassa.provider_data["receipt"]["items"][0]["amount"] == {
        "value": "599.00",
        "currency": "RUB",
    }


@pytest.mark.parametrize(
    ("provider", "currency", "amount"),
    [
        (PaymentProvider.TELEGRAM_STARS, PaymentCurrency.XTR, 1),
        (PaymentProvider.YOOKASSA, PaymentCurrency.RUB, 10_000),
    ],
)
def test_test_smoke_subscription_invoice_metadata_uses_minimum_provider_amount(
    provider: PaymentProvider,
    currency: PaymentCurrency,
    amount: int,
) -> None:
    metadata = get_payment_product_invoice_metadata(
        provider,
        PaymentProduct.SUBSCRIPTION_MONTH,
        pricing_context=PAYMENT_TEST_SMOKE_PRICING_CONTEXT,
    )

    assert metadata.currency == currency
    assert metadata.amount == amount
    if provider == PaymentProvider.YOOKASSA:
        assert metadata.provider_data is not None
        assert metadata.provider_data["receipt"]["items"][0]["amount"] == {
            "value": "100.00",
            "currency": "RUB",
        }


def test_test_smoke_payment_order_and_invoice_metadata_use_overridden_amount() -> None:
    repository = InMemoryPaymentOrderRepository()
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    product_metadata = get_payment_product_invoice_metadata(
        PaymentProvider.YOOKASSA,
        PaymentProduct.SUBSCRIPTION_MONTH,
        pricing_context=PAYMENT_TEST_SMOKE_PRICING_CONTEXT,
    )

    result = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=product_metadata.provider,
        product=product_metadata.product,
        amount=product_metadata.amount,
        currency=product_metadata.currency,
        pricing_context=PAYMENT_TEST_SMOKE_PRICING_CONTEXT,
        now=now,
        order_id_factory=_sequence_factory("order_smoke1"),
        nonce_factory=_sequence_factory("nonce_smoke1"),
    )

    assert result.accepted is True
    order = result.order
    assert order is not None
    assert order.amount == 10_000
    assert order.list_amount == 10_000
    assert order.discount_amount == 0
    assert order.metadata["pricing_context"] == PAYMENT_TEST_SMOKE_PRICING_CONTEXT

    invoice_metadata = build_payment_invoice_metadata(order)
    pre_checkout = validate_payment_pre_checkout(
        repository,
        payload=order.payload,
        user_id=order.user_id,
        currency=PaymentCurrency.RUB,
        total_amount=10_000,
        expected_provider=PaymentProvider.YOOKASSA,
        expected_product=PaymentProduct.SUBSCRIPTION_MONTH,
        now=now,
    )

    assert invoice_metadata.amount == 10_000
    assert invoice_metadata.provider_data is not None
    assert invoice_metadata.provider_data["receipt"]["items"][0]["amount"] == {
        "value": "100.00",
        "currency": "RUB",
    }
    assert pre_checkout.approved is True


def test_invoice_metadata_helper_does_not_require_telegram_bot_api() -> None:
    order = _payment_order("order_sub1", "nonce_sub1", PaymentProduct.SUBSCRIPTION_MONTH)

    metadata = build_payment_invoice_metadata(order)

    assert metadata.payload == "diet:order:order_sub1:nonce_sub1"
    assert not hasattr(metadata, "bot")
    assert not hasattr(metadata, "create_invoice_link")


def test_payment_dataclasses_represent_order_event_and_processed_charge_without_entitlements() -> None:
    now = datetime(2026, 5, 12, 10, 0, tzinfo=UTC)
    entitlement = Entitlement()
    entitlement_before = entitlement.to_dict()

    order = PaymentOrder(
        order_id="order_123",
        nonce="nonce_456",
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.TELEGRAM_STARS,
        product=PaymentProduct.SUBSCRIPTION_MONTH,
        amount=400,
        currency=PaymentCurrency.XTR,
        status=PaymentOrderStatus.PENDING,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    event = PaymentEvent(
        event_id="evt_123",
        event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
        provider=PaymentProvider.TELEGRAM_STARS,
        order_id=order.order_id,
        charge_id="tg-charge-123",
        telegram_charge_id="tg-charge-123",
        provider_charge_id=None,
        user_id=order.user_id,
        delivery_chat_id=order.delivery_chat_id,
        product=order.product,
        amount=order.amount,
        currency=order.currency,
        status=PaymentEventStatus.PROCESSED,
        raw_payload_redacted=redact_payment_payload({"email": "buyer@example.com"}),
        created_at=now,
        processed_at=now,
    )
    processed = ProcessedProviderCharge(
        provider=PaymentProvider.TELEGRAM_STARS,
        charge_id=event.charge_id,
        telegram_charge_id=event.telegram_charge_id,
        provider_charge_id=event.provider_charge_id,
        order_id=order.order_id,
        event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
        user_id=order.user_id,
        product=order.product,
        created_at=now,
    )

    assert order.payload == "diet:order:order_123:nonce_456"
    assert order.status == PaymentOrderStatus.PENDING
    assert event.event_type == PaymentEventType.SUCCESSFUL_PAYMENT
    assert event.raw_payload_redacted == {"email": "[REDACTED]"}
    assert processed.event_type == PaymentEventType.SUCCESSFUL_PAYMENT
    assert entitlement.to_dict() == entitlement_before


def test_create_or_reuse_pending_payment_order_creates_new_pending_order() -> None:
    repository = InMemoryPaymentOrderRepository()
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)

    result = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.TELEGRAM_STARS,
        product=PaymentProduct.SUBSCRIPTION_MONTH,
        amount=400,
        currency=PaymentCurrency.XTR,
        now=now,
        order_id_factory=_sequence_factory("order_new1"),
        nonce_factory=_sequence_factory("nonce_new1"),
    )

    assert result.accepted is True
    assert result.code == PaymentOrderCreationCode.CREATED
    order = result.order
    assert order is not None
    assert order.order_id == "order_new1"
    assert order.nonce == "nonce_new1"
    assert order.user_id == 1001
    assert order.delivery_chat_id == 2002
    assert order.provider == PaymentProvider.TELEGRAM_STARS
    assert order.product == PaymentProduct.SUBSCRIPTION_MONTH
    assert order.amount == 400
    assert order.currency == PaymentCurrency.XTR
    assert order.status == PaymentOrderStatus.PENDING
    assert order.created_at == now
    assert order.expires_at == now + timedelta(seconds=PAYMENT_ORDER_TTL_SECONDS)
    assert order.invoice_link is None
    assert order.payload == "diet:order:order_new1:nonce_new1"
    assert repository.orders == [order]


@pytest.mark.parametrize(
    ("product", "amount"),
    [
        (PaymentProduct.EXTRA_ONE_DAY, 35),
        (PaymentProduct.EXTRA_WEEKLY_PDF, 170),
    ],
)
def test_create_pending_extra_payment_order_requires_active_subscription(
    product: PaymentProduct,
    amount: int,
) -> None:
    repository = InMemoryPaymentOrderRepository()

    result = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.TELEGRAM_STARS,
        product=product,
        amount=amount,
        currency=PaymentCurrency.XTR,
        now=datetime(2026, 5, 13, 10, 0, tzinfo=UTC),
        order_id_factory=_sequence_factory("order_new1"),
        nonce_factory=_sequence_factory("nonce_new1"),
    )

    assert result.accepted is False
    assert result.code == PaymentOrderCreationCode.ACTIVE_SUBSCRIPTION_REQUIRED
    assert result.order is None
    assert result.requires_active_subscription is True
    assert repository.orders == []


def test_create_subscription_month_payment_order_allows_inactive_user() -> None:
    repository = InMemoryPaymentOrderRepository()

    result = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.TELEGRAM_STARS,
        product=PaymentProduct.SUBSCRIPTION_MONTH,
        amount=400,
        currency=PaymentCurrency.XTR,
        now=datetime(2026, 5, 13, 10, 0, tzinfo=UTC),
        order_id_factory=_sequence_factory("order_sub1"),
        nonce_factory=_sequence_factory("nonce_sub1"),
    )

    assert result.accepted is True
    assert result.code == PaymentOrderCreationCode.CREATED
    assert result.order is not None
    assert result.order.product == PaymentProduct.SUBSCRIPTION_MONTH


def test_repeated_payment_order_creation_reuses_active_pending_order() -> None:
    repository = InMemoryPaymentOrderRepository()
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)

    first_result = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.YOOKASSA,
        product=PaymentProduct.EXTRA_WEEKLY_PDF,
        amount=25000,
        currency=PaymentCurrency.RUB,
        now=now,
        has_active_subscription=True,
        order_id_factory=_sequence_factory("order_new1"),
        nonce_factory=_sequence_factory("nonce_new1"),
    )
    second_result = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.YOOKASSA,
        product=PaymentProduct.EXTRA_WEEKLY_PDF,
        amount=25000,
        currency=PaymentCurrency.RUB,
        now=now + timedelta(minutes=1),
        has_active_subscription=True,
        order_id_factory=_sequence_factory("order_new2"),
        nonce_factory=_sequence_factory("nonce_new2"),
    )

    first = first_result.order
    second = second_result.order
    assert first_result.code == PaymentOrderCreationCode.CREATED
    assert second_result.code == PaymentOrderCreationCode.REUSED
    assert second == first
    assert len(repository.orders) == 1


def test_expired_pending_payment_order_is_not_reused() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    expired = PaymentOrder(
        order_id="order_old1",
        nonce="nonce_old1",
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.TELEGRAM_STARS,
        product=PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
        currency=PaymentCurrency.XTR,
        status=PaymentOrderStatus.PENDING,
        created_at=now - timedelta(hours=1),
        expires_at=now - timedelta(minutes=1),
    )
    repository = InMemoryPaymentOrderRepository([expired])

    result = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.TELEGRAM_STARS,
        product=PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
        currency=PaymentCurrency.XTR,
        now=now,
        has_active_subscription=True,
        order_id_factory=_sequence_factory("order_new1"),
        nonce_factory=_sequence_factory("nonce_new1"),
    )

    assert result.accepted is True
    order = result.order
    assert order is not None
    assert order.order_id == "order_new1"
    assert order.payload == "diet:order:order_new1:nonce_new1"
    assert repository.orders == [expired, order]


def test_payment_order_creation_does_not_mutate_entitlement() -> None:
    repository = InMemoryPaymentOrderRepository()
    entitlement = Entitlement(
        free_trial_used=True,
        monthly_one_day_remaining=2,
        monthly_weekly_pdf_remaining=1,
        extra_one_day_remaining=3,
        extra_weekly_pdf_remaining=4,
        processed_payment_charge_ids=["charge-existing"],
    )
    before = entitlement.to_dict()

    result = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.YOOKASSA,
        product=PaymentProduct.SUBSCRIPTION_MONTH,
        amount=59900,
        currency=PaymentCurrency.RUB,
        now=datetime(2026, 5, 13, 10, 0, tzinfo=UTC),
        order_id_factory=_sequence_factory("order_new1"),
        nonce_factory=_sequence_factory("nonce_new1"),
    )

    assert result.accepted is True
    assert entitlement.to_dict() == before


def test_successful_subscription_payment_marks_order_paid_and_grants_subscription_once() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])

    result = apply_successful_payment(
        repository,
        _successful_payment(order, telegram_charge_id="tg-charge-sub1"),
        now=now,
    )

    entitlement = repository.get_entitlement(order.user_id)
    paid_order = repository.load_payment_order(order.order_id)
    assert result.processed is True
    assert result.code == PaymentSuccessfulPaymentCode.PROCESSED
    assert result.duplicate is False
    assert paid_order is not None
    assert paid_order.status == PaymentOrderStatus.PAID
    assert paid_order.paid_at == now
    assert entitlement.is_subscription_active(now)
    assert entitlement.monthly_one_day_remaining == 5
    assert entitlement.monthly_weekly_pdf_remaining == 4
    assert repository.processed_charge_ids() == ["tg-charge-sub1"]
    assert [event.status for event in repository.payment_events] == [
        PaymentEventStatus.PROCESSED
    ]


def test_duplicate_same_successful_payment_does_not_grant_twice() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_day1",
        "nonce_day1",
        PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])
    repository.entitlements[order.user_id] = _active_entitlement(now)
    payment = _successful_payment(
        order,
        telegram_charge_id="tg-charge-day1",
        provider_charge_id="provider-charge-day1",
    )

    first = apply_successful_payment(repository, payment, now=now)
    repository.entitlements[order.user_id].extra_one_day_remaining = 0
    duplicate = apply_successful_payment(repository, payment, now=now + timedelta(seconds=10))

    assert first.processed is True
    assert duplicate.processed is False
    assert duplicate.duplicate is True
    assert duplicate.code == PaymentSuccessfulPaymentCode.DUPLICATE
    assert repository.entitlements[order.user_id].extra_one_day_remaining == 0
    assert repository.processed_charge_ids() == [
        "tg-charge-day1",
        "provider-charge-day1",
    ]
    assert [event.status for event in repository.payment_events] == [
        PaymentEventStatus.PROCESSED,
        PaymentEventStatus.DUPLICATE,
    ]


def test_successful_payment_wrong_nonce_is_rejected_without_grant() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])

    result = apply_successful_payment(
        repository,
        _successful_payment(
            order,
            payload="diet:order:order_sub1:nonce_bad1",
            telegram_charge_id="tg-charge-sub1",
        ),
        now=now,
    )

    assert result.processed is False
    assert result.code == PaymentSuccessfulPaymentCode.NONCE_MISMATCH
    assert repository.load_payment_order(order.order_id) == order
    assert repository.get_entitlement(order.user_id) == Entitlement()
    assert repository.processed_charge_ids() == []


def test_successful_payment_missing_order_is_recorded_as_orphan_without_grant() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    repository = InMemoryPaymentLedgerRepository()

    result = apply_successful_payment(
        repository,
        PaymentSuccessfulPaymentInput(
            payload="diet:order:order_missing1:nonce_456",
            provider=PaymentProvider.TELEGRAM_STARS,
            telegram_charge_id="tg-charge-orphan",
            user_id=1001,
            delivery_chat_id=2002,
            currency=PaymentCurrency.XTR,
            total_amount=400,
        ),
        now=now,
    )

    assert result.processed is False
    assert result.code == PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND
    assert result.order is None
    assert result.event is not None
    assert result.event.status == PaymentEventStatus.ORPHAN_RECOVERABLE
    assert result.event.reason == PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND.value
    assert repository.entitlements == {}
    assert repository.processed_charge_ids() == []


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"user_id": 9999}, PaymentSuccessfulPaymentCode.USER_MISMATCH),
        ({"delivery_chat_id": 9999}, PaymentSuccessfulPaymentCode.DELIVERY_CHAT_MISMATCH),
    ],
)
def test_successful_payment_rejects_wrong_user_or_delivery_chat(
    overrides: dict[str, object],
    expected_code: PaymentSuccessfulPaymentCode,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])

    result = apply_successful_payment(
        repository,
        _successful_payment(order, telegram_charge_id="tg-charge-sub1", **overrides),
        now=now,
    )

    assert result.processed is False
    assert result.code == expected_code
    assert repository.get_entitlement(order.user_id) == Entitlement()
    assert repository.processed_charge_ids() == []


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"provider": PaymentProvider.YOOKASSA}, PaymentSuccessfulPaymentCode.PROVIDER_MISMATCH),
        (
            {"expected_product": PaymentProduct.EXTRA_ONE_DAY},
            PaymentSuccessfulPaymentCode.PRODUCT_MISMATCH,
        ),
        ({"currency": PaymentCurrency.RUB}, PaymentSuccessfulPaymentCode.CURRENCY_MISMATCH),
        ({"total_amount": 399}, PaymentSuccessfulPaymentCode.AMOUNT_MISMATCH),
    ],
)
def test_successful_payment_rejects_wrong_provider_product_currency_or_amount(
    overrides: dict[str, object],
    expected_code: PaymentSuccessfulPaymentCode,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])

    result = apply_successful_payment(
        repository,
        _successful_payment(order, telegram_charge_id="tg-charge-sub1", **overrides),
        now=now,
    )

    assert result.processed is False
    assert result.code == expected_code
    assert repository.get_entitlement(order.user_id) == Entitlement()
    assert repository.processed_charge_ids() == []


@pytest.mark.parametrize(
    ("product", "amount", "field_name"),
    [
        (PaymentProduct.EXTRA_ONE_DAY, 35, "extra_one_day_remaining"),
        (PaymentProduct.EXTRA_WEEKLY_PDF, 170, "extra_weekly_pdf_remaining"),
    ],
)
def test_successful_payment_extras_require_active_subscription_at_success_time(
    product: PaymentProduct,
    amount: int,
    field_name: str,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    inactive_order = _payment_order(
        f"order_{product.value}_inactive",
        "nonce_inactive",
        product,
        amount=amount,
        expires_at=now + timedelta(minutes=5),
    )
    active_order = _payment_order(
        f"order_{product.value}_active",
        "nonce_active",
        product,
        amount=amount,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([inactive_order, active_order])

    rejected = apply_successful_payment(
        repository,
        _successful_payment(inactive_order, telegram_charge_id=f"tg-{product.value}-inactive"),
        now=now,
    )
    repository.entitlements[active_order.user_id] = _active_entitlement(now)
    accepted = apply_successful_payment(
        repository,
        _successful_payment(active_order, telegram_charge_id=f"tg-{product.value}-active"),
        now=now,
    )

    assert rejected.processed is False
    assert rejected.code == PaymentSuccessfulPaymentCode.ACTIVE_SUBSCRIPTION_REQUIRED
    assert accepted.processed is True
    assert getattr(repository.entitlements[active_order.user_id], field_name) == 1


def test_extra_successful_payment_rejects_when_subscription_expired_after_pre_checkout() -> None:
    pre_checkout_at = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    success_at = pre_checkout_at + timedelta(minutes=2)
    order = _payment_order(
        "order_day1",
        "nonce_day1",
        PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
        expires_at=success_at + timedelta(minutes=5),
        pre_checkout_approved_at=pre_checkout_at,
    )
    repository = InMemoryPaymentLedgerRepository([order])
    repository.entitlements[order.user_id] = Entitlement(
        subscription_period_start=(pre_checkout_at - timedelta(days=3)).isoformat(),
        subscription_period_end=(pre_checkout_at + timedelta(minutes=1)).isoformat(),
    )

    result = apply_successful_payment(
        repository,
        _successful_payment(order, telegram_charge_id="tg-charge-day1"),
        now=success_at,
    )

    entitlement = repository.get_entitlement(order.user_id)
    assert result.processed is False
    assert result.code == PaymentSuccessfulPaymentCode.ACTIVE_SUBSCRIPTION_REQUIRED
    assert entitlement.extra_one_day_remaining == 0
    assert repository.processed_charge_ids() == []
    pending_order = repository.load_payment_order(order.order_id)
    assert pending_order is not None
    assert pending_order.status == PaymentOrderStatus.PENDING
    assert [event.status for event in repository.payment_events] == [
        PaymentEventStatus.IGNORED_NON_TERMINAL
    ]
    assert repository.payment_events[0].reason == "active_subscription_required"


def test_expired_successful_payment_without_prior_pre_checkout_approval_is_rejected() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_expired1",
        "nonce_expired1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now - timedelta(seconds=1),
    )
    repository = InMemoryPaymentLedgerRepository([order])

    result = apply_successful_payment(
        repository,
        _successful_payment(order, telegram_charge_id="tg-charge-expired1"),
        now=now,
    )

    assert result.processed is False
    assert result.code == PaymentSuccessfulPaymentCode.ORDER_EXPIRED
    assert repository.get_entitlement(order.user_id) == Entitlement()


def test_expired_successful_payment_with_prior_pre_checkout_approval_is_accepted() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    expires_at = now - timedelta(seconds=1)
    approved_at = expires_at - timedelta(seconds=10)
    order = _payment_order(
        "order_expired1",
        "nonce_expired1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=expires_at,
        pre_checkout_approved_at=approved_at,
    )
    repository = InMemoryPaymentLedgerRepository([order])

    result = apply_successful_payment(
        repository,
        _successful_payment(order, telegram_charge_id="tg-charge-expired1"),
        now=now,
    )

    assert result.processed is True
    assert result.code == PaymentSuccessfulPaymentCode.PROCESSED
    assert repository.load_payment_order(order.order_id).status == PaymentOrderStatus.PAID
    assert repository.get_entitlement(order.user_id).is_subscription_active(now)


def test_successful_payment_records_telegram_and_provider_charge_aliases() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_ru1",
        "nonce_ru1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        provider=PaymentProvider.YOOKASSA,
        amount=59_900,
        currency=PaymentCurrency.RUB,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])

    result = apply_successful_payment(
        repository,
        _successful_payment(
            order,
            telegram_charge_id="tg-charge-ru1",
            provider_charge_id="provider-charge-ru1",
        ),
        now=now,
    )

    assert result.processed is True
    assert result.charge_aliases == ("tg-charge-ru1", "provider-charge-ru1")
    assert repository.processed_charge_ids() == [
        "tg-charge-ru1",
        "provider-charge-ru1",
    ]


def test_successful_payment_event_raw_payload_is_redacted() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])

    result = apply_successful_payment(
        repository,
        _successful_payment(
            order,
            telegram_charge_id="tg-charge-sub1",
            raw_payload={
                "email": "buyer@example.com",
                "phone_number": "+37499123456",
                "order_info": {"email": "nested@example.com"},
                "provider_token": "381764678:TEST:very-secret-provider-token",
                "database_url": "postgresql://diet_bot:secret@localhost:5432/foodbalance",
                "telegram_payment_charge_id": "tg-charge-raw-secret",
                "provider_payment_charge_id": "provider-charge-raw-secret",
                "invoice_payload": order.payload,
            },
        ),
        now=now,
    )

    assert result.event is not None
    serialized = json.dumps(result.event.raw_payload_redacted, sort_keys=True)
    assert "buyer@example.com" not in serialized
    assert "nested@example.com" not in serialized
    assert "+37499123456" not in serialized
    assert "very-secret-provider-token" not in serialized
    assert "postgresql://diet_bot:secret@localhost:5432/foodbalance" not in serialized
    assert "tg-charge-raw-secret" not in serialized
    assert "provider-charge-raw-secret" not in serialized
    assert result.event.raw_payload_redacted["raw_payload"]["email"] == "[REDACTED]"
    assert result.event.raw_payload_redacted["raw_payload"]["order_info"] == "[REDACTED]"
    assert result.event.raw_payload_redacted["raw_payload"]["telegram_payment_charge_id"] == "[REDACTED]"
    assert result.event.raw_payload_redacted["raw_payload"]["provider_payment_charge_id"] == "[REDACTED]"


def test_refund_subscription_revokes_matching_paid_period() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])
    _pay_order(repository, order, now=now, telegram_charge_id="tg-charge-sub1")

    result = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.REFUND,
            order,
            telegram_charge_id="tg-charge-sub1",
        ),
        now=now + timedelta(hours=1),
    )

    entitlement = repository.get_entitlement(order.user_id)
    assert result.processed is True
    assert result.code == PaymentReversalCode.PROCESSED
    assert result.event is not None
    assert result.event.status == PaymentEventStatus.PROCESSED
    assert not entitlement.is_subscription_active(now + timedelta(hours=1))
    assert entitlement.monthly_one_day_remaining == 0
    assert entitlement.monthly_weekly_pdf_remaining == 0


def test_refund_old_subscription_does_not_revoke_newer_active_subscription() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    renewal_at = now + timedelta(days=1)
    old_order = _payment_order(
        "order_old1",
        "nonce_old1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    new_order = _payment_order(
        "order_new1",
        "nonce_new1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=renewal_at + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([old_order, new_order])
    _pay_order(repository, old_order, now=now, telegram_charge_id="tg-charge-old1")
    _pay_order(repository, new_order, now=renewal_at, telegram_charge_id="tg-charge-new1")
    before = repository.get_entitlement(old_order.user_id).to_dict()

    result = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.REFUND,
            old_order,
            telegram_charge_id="tg-charge-old1",
        ),
        now=renewal_at + timedelta(hours=1),
    )

    after = repository.get_entitlement(old_order.user_id)
    assert result.processed is True
    assert result.code == PaymentReversalCode.PROCESSED
    assert result.event is not None
    assert result.event.status == PaymentEventStatus.PROCESSED
    assert result.event.reason == "paid_period_not_current"
    assert after.to_dict() == before
    assert after.is_subscription_active(renewal_at + timedelta(hours=1))


def test_chargeback_subscription_behaves_as_terminal_matching_reversal() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])
    _pay_order(repository, order, now=now, telegram_charge_id="tg-charge-sub1")

    result = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.CHARGEBACK,
            order,
            telegram_charge_id="tg-charge-sub1",
        ),
        now=now + timedelta(hours=1),
    )

    entitlement = repository.get_entitlement(order.user_id)
    assert result.processed is True
    assert result.code == PaymentReversalCode.PROCESSED
    assert result.event is not None
    assert result.event.event_type == PaymentEventType.CHARGEBACK
    assert result.event.status == PaymentEventStatus.PROCESSED
    assert not entitlement.is_subscription_active(now + timedelta(hours=1))
    assert repository.processed_charge_ids(PaymentEventType.CHARGEBACK) == ["tg-charge-sub1"]


def test_cancel_subscription_records_event_and_keeps_paid_period_active() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])
    _pay_order(repository, order, now=now, telegram_charge_id="tg-charge-sub1")
    before = repository.get_entitlement(order.user_id).to_dict()

    result = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.CANCEL_SUBSCRIPTION,
            order,
            telegram_charge_id="tg-charge-sub1",
        ),
        now=now + timedelta(hours=1),
    )

    entitlement = repository.get_entitlement(order.user_id)
    assert result.processed is True
    assert result.code == PaymentReversalCode.PROCESSED
    assert result.event is not None
    assert result.event.event_type == PaymentEventType.CANCEL_SUBSCRIPTION
    assert result.event.status == PaymentEventStatus.PROCESSED
    assert entitlement.to_dict() == before
    assert entitlement.is_subscription_active(now + timedelta(hours=1))


def test_duplicate_refund_does_not_revoke_newer_subscription() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    renewal_at = now + timedelta(hours=2)
    refunded_order = _payment_order(
        "order_refund1",
        "nonce_refund1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    new_order = _payment_order(
        "order_new1",
        "nonce_new1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=renewal_at + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([refunded_order, new_order])
    _pay_order(repository, refunded_order, now=now, telegram_charge_id="tg-charge-refund1")
    first = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.REFUND,
            refunded_order,
            telegram_charge_id="tg-charge-refund1",
        ),
        now=now + timedelta(hours=1),
    )
    _pay_order(repository, new_order, now=renewal_at, telegram_charge_id="tg-charge-new1")
    before_duplicate = repository.get_entitlement(refunded_order.user_id).to_dict()

    duplicate = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.REFUND,
            refunded_order,
            telegram_charge_id="tg-charge-refund1",
        ),
        now=renewal_at + timedelta(hours=1),
    )

    entitlement = repository.get_entitlement(refunded_order.user_id)
    assert first.processed is True
    assert duplicate.processed is False
    assert duplicate.duplicate is True
    assert duplicate.code == PaymentReversalCode.DUPLICATE
    assert duplicate.event is not None
    assert duplicate.event.status == PaymentEventStatus.DUPLICATE
    assert entitlement.to_dict() == before_duplicate
    assert entitlement.is_subscription_active(renewal_at + timedelta(hours=1))


def test_duplicate_chargeback_does_not_revoke_newer_subscription() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    renewal_at = now + timedelta(hours=2)
    charged_back_order = _payment_order(
        "order_chargeback1",
        "nonce_chargeback1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    new_order = _payment_order(
        "order_new1",
        "nonce_new1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=renewal_at + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([charged_back_order, new_order])
    _pay_order(
        repository,
        charged_back_order,
        now=now,
        telegram_charge_id="tg-charge-chargeback1",
    )
    first = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.CHARGEBACK,
            charged_back_order,
            telegram_charge_id="tg-charge-chargeback1",
        ),
        now=now + timedelta(hours=1),
    )
    _pay_order(repository, new_order, now=renewal_at, telegram_charge_id="tg-charge-new1")
    before_duplicate = repository.get_entitlement(charged_back_order.user_id).to_dict()

    duplicate = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.CHARGEBACK,
            charged_back_order,
            telegram_charge_id="tg-charge-chargeback1",
        ),
        now=renewal_at + timedelta(hours=1),
    )

    entitlement = repository.get_entitlement(charged_back_order.user_id)
    assert first.processed is True
    assert duplicate.processed is False
    assert duplicate.duplicate is True
    assert duplicate.code == PaymentReversalCode.DUPLICATE
    assert entitlement.to_dict() == before_duplicate
    assert entitlement.is_subscription_active(renewal_at + timedelta(hours=1))


@pytest.mark.parametrize(
    ("product", "amount", "target_field", "other_field"),
    [
        (
            PaymentProduct.EXTRA_ONE_DAY,
            35,
            "extra_one_day_remaining",
            "extra_weekly_pdf_remaining",
        ),
        (
            PaymentProduct.EXTRA_WEEKLY_PDF,
            170,
            "extra_weekly_pdf_remaining",
            "extra_one_day_remaining",
        ),
    ],
)
def test_refund_extra_removes_only_matching_unused_extra(
    product: PaymentProduct,
    amount: int,
    target_field: str,
    other_field: str,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        f"order_{product.value}",
        "nonce_extra1",
        product,
        amount=amount,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])
    repository.entitlements[order.user_id] = _active_entitlement(now)
    _pay_order(repository, order, now=now, telegram_charge_id=f"tg-charge-{product.value}")
    setattr(repository.entitlements[order.user_id], other_field, 2)

    result = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.REFUND,
            order,
            telegram_charge_id=f"tg-charge-{product.value}",
        ),
        now=now + timedelta(hours=1),
    )

    entitlement = repository.get_entitlement(order.user_id)
    assert result.processed is True
    assert result.code == PaymentReversalCode.PROCESSED
    assert getattr(entitlement, target_field) == 0
    assert getattr(entitlement, other_field) == 2
    assert entitlement.is_subscription_active(now + timedelta(hours=1))


def test_refund_consumed_extra_records_ignored_reason_without_wrong_quota_change() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_day1",
        "nonce_day1",
        PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])
    repository.entitlements[order.user_id] = _active_entitlement(now)
    repository.entitlements[order.user_id].monthly_one_day_remaining = 1
    _pay_order(repository, order, now=now, telegram_charge_id="tg-charge-day1")

    entitlement = repository.get_entitlement(order.user_id)
    monthly = consume_one_day_attempt(entitlement, now)
    extra = consume_one_day_attempt(entitlement, now)
    repository.save_entitlement(order.user_id, entitlement)
    before_refund = entitlement.to_dict()

    result = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.REFUND,
            order,
            telegram_charge_id="tg-charge-day1",
        ),
        now=now + timedelta(hours=1),
    )

    updated = repository.get_entitlement(order.user_id)
    assert monthly.source == "monthly"
    assert extra.source == "extra"
    assert result.processed is False
    assert result.code == PaymentReversalCode.EXTRA_ALREADY_CONSUMED
    assert result.event is not None
    assert result.event.status == PaymentEventStatus.IGNORED_NON_TERMINAL
    assert result.event.reason == "extra_already_consumed"
    assert updated.to_dict() == before_refund
    assert updated.monthly_one_day_remaining == 0
    assert updated.extra_one_day_remaining == 0


@pytest.mark.parametrize("event_type", [PaymentEventType.REFUND, PaymentEventType.CHARGEBACK])
def test_unknown_negative_reversal_is_pending_reconciliation_without_entitlement_change(
    event_type: PaymentEventType,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    repository = InMemoryPaymentLedgerRepository()
    repository.entitlements[1001] = _active_entitlement(now)
    before = repository.entitlements[1001].to_dict()

    result = apply_payment_reversal(
        repository,
        PaymentReversalInput(
            event_type=event_type,
            provider=PaymentProvider.TELEGRAM_STARS,
            telegram_charge_id="tg-charge-missing",
            amount=400,
            currency=PaymentCurrency.XTR,
            raw_payload={"email": "buyer@example.com"},
        ),
        now=now,
    )

    assert result.processed is False
    assert result.code == PaymentReversalCode.ORIGINAL_PAYMENT_NOT_FOUND
    assert result.event is not None
    assert result.event.status == PaymentEventStatus.PENDING_RECONCILIATION
    assert result.event.reason == "original_payment_not_found"
    assert repository.entitlements[1001].to_dict() == before
    assert repository.processed_charge_ids(event_type) == []


def test_refund_matches_original_payment_by_provider_charge_alias() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_ru1",
        "nonce_ru1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        provider=PaymentProvider.YOOKASSA,
        amount=59_900,
        currency=PaymentCurrency.RUB,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])
    _pay_order(
        repository,
        order,
        now=now,
        telegram_charge_id="tg-charge-ru1",
        provider_charge_id="provider-charge-ru1",
    )

    result = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.REFUND,
            order,
            telegram_charge_id=None,
            provider_charge_id="provider-charge-ru1",
        ),
        now=now + timedelta(hours=1),
    )

    assert result.processed is True
    assert result.order is not None
    assert result.order.order_id == order.order_id
    assert not repository.get_entitlement(order.user_id).is_subscription_active(
        now + timedelta(hours=1)
    )


def test_reversal_event_raw_metadata_is_redacted() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])
    _pay_order(repository, order, now=now, telegram_charge_id="tg-charge-sub1")

    result = apply_payment_reversal(
        repository,
        _payment_reversal(
            PaymentEventType.REFUND,
            order,
            telegram_charge_id="tg-charge-sub1",
            raw_payload={
                "email": "buyer@example.com",
                "phone_number": "+37499123456",
                "order_info": {"email": "nested@example.com"},
                "provider_token": "381764678:TEST:very-secret-provider-token",
                "database_url": "postgresql://diet_bot:secret@localhost:5432/foodbalance",
                "telegram_payment_charge_id": "tg-charge-reversal-secret",
                "provider_payment_charge_id": "provider-charge-reversal-secret",
            },
        ),
        now=now + timedelta(hours=1),
    )

    assert result.event is not None
    serialized = json.dumps(result.event.raw_payload_redacted, sort_keys=True)
    assert "buyer@example.com" not in serialized
    assert "nested@example.com" not in serialized
    assert "+37499123456" not in serialized
    assert "very-secret-provider-token" not in serialized
    assert "postgresql://diet_bot:secret@localhost:5432/foodbalance" not in serialized
    assert "tg-charge-reversal-secret" not in serialized
    assert "provider-charge-reversal-secret" not in serialized
    assert result.event.raw_payload_redacted["raw_payload"]["email"] == "[REDACTED]"
    assert result.event.raw_payload_redacted["raw_payload"]["order_info"] == "[REDACTED]"
    assert result.event.raw_payload_redacted["raw_payload"]["telegram_payment_charge_id"] == "[REDACTED]"
    assert result.event.raw_payload_redacted["raw_payload"]["provider_payment_charge_id"] == "[REDACTED]"


def test_orphan_successful_payment_can_be_reconciled_to_matching_pending_order_once() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    repository = InMemoryPaymentLedgerRepository()
    orphan = apply_successful_payment(
        repository,
        PaymentSuccessfulPaymentInput(
            payload="diet:order:order_missing1:nonce_missing1",
            provider=PaymentProvider.TELEGRAM_STARS,
            telegram_charge_id="tg-charge-orphan1",
            provider_charge_id="provider-charge-orphan1",
            user_id=1001,
            delivery_chat_id=2002,
            currency=PaymentCurrency.XTR,
            total_amount=400,
        ),
        now=now,
    )
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository.orders.append(order)

    result = apply_payment_reconciliation(
        repository,
        PaymentReconciliationInput(
            action=PaymentReconciliationAction.RECONCILE_ORPHAN_SUCCESS,
            target_event_id=orphan.event.event_id if orphan.event is not None else None,
            target_order_id=order.order_id,
            admin_actor={"admin_id": "admin-42"},
            reason="matched Telegram support receipt",
        ),
        now=now + timedelta(minutes=1),
    )

    entitlement = repository.get_entitlement(order.user_id)
    paid_order = repository.load_payment_order(order.order_id)
    reconciled_event = repository.load_payment_event(orphan.event.event_id)
    assert result.processed is True
    assert result.code == PaymentReconciliationCode.PROCESSED
    assert result.successful_payment_result is not None
    assert result.successful_payment_result.processed is True
    assert paid_order is not None
    assert paid_order.status == PaymentOrderStatus.PAID
    assert entitlement.is_subscription_active(now + timedelta(minutes=1))
    assert repository.processed_charge_ids() == [
        "tg-charge-orphan1",
        "provider-charge-orphan1",
    ]
    assert reconciled_event is not None
    assert reconciled_event.status == PaymentEventStatus.PROCESSED
    assert reconciled_event.order_id == order.order_id
    assert reconciled_event.product == order.product
    assert result.audit_event is not None
    assert result.audit_event.event_type == PaymentEventType.UNKNOWN


@pytest.mark.parametrize(
    ("event_overrides", "order_overrides", "expected_code"),
    [
        ({"user_id": 9999}, {}, PaymentReconciliationCode.USER_MISMATCH),
        (
            {"delivery_chat_id": 9999},
            {},
            PaymentReconciliationCode.DELIVERY_CHAT_MISMATCH,
        ),
        ({"provider": PaymentProvider.YOOKASSA}, {}, PaymentReconciliationCode.PROVIDER_MISMATCH),
        (
            {"product": PaymentProduct.EXTRA_ONE_DAY},
            {},
            PaymentReconciliationCode.PRODUCT_MISMATCH,
        ),
        ({"amount": 399}, {}, PaymentReconciliationCode.AMOUNT_MISMATCH),
        ({"currency": PaymentCurrency.RUB}, {}, PaymentReconciliationCode.CURRENCY_MISMATCH),
    ],
)
def test_orphan_success_reconciliation_rejects_mismatched_order_fields(
    event_overrides: dict[str, object],
    order_overrides: dict[str, object],
    expected_code: PaymentReconciliationCode,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    event = _orphan_success_event(**event_overrides)
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
        **order_overrides,
    )
    repository = InMemoryPaymentLedgerRepository([order])
    repository.insert_payment_event(event)

    result = apply_payment_reconciliation(
        repository,
        PaymentReconciliationInput(
            action=PaymentReconciliationAction.RECONCILE_ORPHAN_SUCCESS,
            target_event_id=event.event_id,
            target_order_id=order.order_id,
            admin_actor={"admin_id": "admin-42"},
            reason="manual mismatch check",
        ),
        now=now,
    )

    assert result.processed is False
    assert result.code == expected_code
    assert repository.load_payment_order(order.order_id) == order
    assert repository.get_entitlement(order.user_id) == Entitlement()
    assert repository.processed_charge_ids() == []
    assert repository.load_payment_event(event.event_id) == event


def test_duplicate_orphan_reconciliation_does_not_grant_twice() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    event = _orphan_success_event(
        event_id="evt_orphan_extra1",
        product=PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
    )
    order = _payment_order(
        "order_day1",
        "nonce_day1",
        PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
        expires_at=now + timedelta(minutes=5),
    )
    repository = InMemoryPaymentLedgerRepository([order])
    repository.entitlements[order.user_id] = _active_entitlement(now)
    repository.insert_payment_event(event)

    first = apply_payment_reconciliation(
        repository,
        PaymentReconciliationInput(
            action=PaymentReconciliationAction.RECONCILE_ORPHAN_SUCCESS,
            target_event_id=event.event_id,
            target_order_id=order.order_id,
            admin_actor={"admin_id": "admin-42"},
            reason="matched Telegram support receipt",
        ),
        now=now,
    )
    repository.entitlements[order.user_id].extra_one_day_remaining = 0
    duplicate = apply_payment_reconciliation(
        repository,
        PaymentReconciliationInput(
            action=PaymentReconciliationAction.RECONCILE_ORPHAN_SUCCESS,
            target_event_id=event.event_id,
            target_order_id=order.order_id,
            admin_actor={"admin_id": "admin-42"},
            reason="retry after operator refresh",
        ),
        now=now + timedelta(seconds=10),
    )

    assert first.processed is True
    assert duplicate.processed is False
    assert duplicate.duplicate is True
    assert duplicate.code == PaymentReconciliationCode.DUPLICATE
    assert repository.entitlements[order.user_id].extra_one_day_remaining == 0
    assert repository.processed_charge_ids() == ["tg-charge-orphan1"]


@pytest.mark.parametrize("event_type", [PaymentEventType.REFUND, PaymentEventType.CHARGEBACK])
def test_pending_terminal_reversal_reconciles_after_matching_success_and_revokes_access(
    event_type: PaymentEventType,
) -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    repository = InMemoryPaymentLedgerRepository()
    pending = apply_payment_reversal(
        repository,
        PaymentReversalInput(
            event_type=event_type,
            provider=PaymentProvider.TELEGRAM_STARS,
            telegram_charge_id="tg-charge-pending1",
            amount=400,
            currency=PaymentCurrency.XTR,
        ),
        now=now,
    )
    order = _payment_order(
        "order_sub1",
        "nonce_sub1",
        PaymentProduct.SUBSCRIPTION_MONTH,
        expires_at=now + timedelta(minutes=5),
    )
    repository.orders.append(order)
    _pay_order(repository, order, now=now + timedelta(minutes=1), telegram_charge_id="tg-charge-pending1")

    result = apply_payment_reconciliation(
        repository,
        PaymentReconciliationInput(
            action=PaymentReconciliationAction.RECONCILE_PENDING_REVERSAL,
            target_event_id=pending.event.event_id if pending.event is not None else None,
            admin_actor={"admin_id": "admin-42"},
            reason="provider sent terminal event before success update",
        ),
        now=now + timedelta(minutes=2),
    )

    entitlement = repository.get_entitlement(order.user_id)
    reconciled_event = repository.load_payment_event(pending.event.event_id)
    assert result.processed is True
    assert result.code == PaymentReconciliationCode.PROCESSED
    assert result.reversal_result is not None
    assert result.reversal_result.processed is True
    assert not entitlement.is_subscription_active(now + timedelta(minutes=2))
    assert repository.processed_charge_ids(event_type) == ["tg-charge-pending1"]
    assert reconciled_event is not None
    assert reconciled_event.status == PaymentEventStatus.PROCESSED
    assert reconciled_event.order_id == order.order_id


def test_ignored_orphan_event_records_reason_without_mutating_entitlement() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    event = _orphan_success_event(event_id="evt_ignore1")
    repository = InMemoryPaymentLedgerRepository()
    repository.entitlements[1001] = _active_entitlement(now)
    before = repository.entitlements[1001].to_dict()
    repository.insert_payment_event(event)

    result = apply_payment_reconciliation(
        repository,
        PaymentReconciliationInput(
            action=PaymentReconciliationAction.IGNORE_EVENT,
            target_event_id=event.event_id,
            admin_actor={"admin_id": "admin-42"},
            reason="provider support confirmed no matching payment",
        ),
        now=now,
    )

    ignored = repository.load_payment_event(event.event_id)
    assert result.processed is True
    assert result.code == PaymentReconciliationCode.IGNORED
    assert ignored is not None
    assert ignored.status == PaymentEventStatus.IGNORED_NON_TERMINAL
    assert ignored.reason == "provider support confirmed no matching payment"
    assert repository.entitlements[1001].to_dict() == before
    assert repository.processed_charge_ids() == []


def test_reconciliation_admin_metadata_is_hashed_or_redacted() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    event = _orphan_success_event(event_id="evt_admin_redaction1")
    repository = InMemoryPaymentLedgerRepository()
    repository.insert_payment_event(event)

    result = apply_payment_reconciliation(
        repository,
        PaymentReconciliationInput(
            action=PaymentReconciliationAction.IGNORE_EVENT,
            target_event_id=event.event_id,
            admin_actor={
                "admin_id": "admin-777",
                "email": "ops@example.com",
                "provider_token": "381764678:TEST:very-secret-provider-token",
                "note": "contact ops@example.com",
            },
            reason="manual close",
        ),
        now=now,
    )

    assert result.audit_event is not None
    actor = result.audit_event.raw_payload_redacted["admin_actor"]
    serialized = json.dumps(
        [event.raw_payload_redacted for event in repository.payment_events],
        sort_keys=True,
    )
    assert "admin-777" not in serialized
    assert "ops@example.com" not in serialized
    assert "very-secret-provider-token" not in serialized
    assert actor["admin_id_hash"] != "admin-777"
    assert actor["email_hash"] != "ops@example.com"
    assert actor["provider_token_hash"] != "381764678:TEST:very-secret-provider-token"
    assert len(actor["admin_id_hash"]) == 64


class InMemoryPaymentOrderRepository:
    def __init__(self, orders: list[PaymentOrder] | None = None) -> None:
        self.orders = list(orders or [])
        self.pre_checkout_approvals: list[tuple[str, datetime]] = []
        self.expired_order_ids: list[str] = []

    def find_active_pending_payment_order(
        self,
        *,
        user_id: int,
        delivery_chat_id: int | None,
        provider: PaymentProvider,
        product: PaymentProduct,
        amount: int,
        currency: PaymentCurrency,
        now: datetime,
        promo_code_id: int | None = None,
    ) -> PaymentOrder | None:
        for order in reversed(self.orders):
            if (
                order.user_id == user_id
                and order.delivery_chat_id == delivery_chat_id
                and order.provider == provider
                and order.product == product
                and order.amount == amount
                and order.currency == currency
                and order.promo_code_id == promo_code_id
                and order.status == PaymentOrderStatus.PENDING
                and order.expires_at is not None
                and order.expires_at > now
            ):
                return order
        return None

    def insert_payment_order(self, order: PaymentOrder) -> PaymentOrder:
        self.orders.append(order)
        return order

    def load_payment_order(self, order_id: str) -> PaymentOrder | None:
        for order in self.orders:
            if order.order_id == order_id:
                return order
        return None

    def record_payment_order_pre_checkout_approved(
        self,
        order_id: str,
        approved_at: datetime,
    ) -> PaymentOrder | None:
        for index, order in enumerate(self.orders):
            if order.order_id != order_id:
                continue
            updated = replace(
                order,
                pre_checkout_approved_at=approved_at,
                updated_at=approved_at,
            )
            self.orders[index] = updated
            self.pre_checkout_approvals.append((order_id, approved_at))
            return updated
        return None

    def mark_payment_order_expired(self, order_id: str) -> None:
        for index, order in enumerate(self.orders):
            if order.order_id != order_id:
                continue
            self.orders[index] = replace(order, status=PaymentOrderStatus.EXPIRED)
            self.expired_order_ids.append(order_id)
            return


class InMemoryPaymentCheckoutRepository(InMemoryPaymentOrderRepository):
    def __init__(
        self,
        orders: list[PaymentOrder] | None = None,
        *,
        entitlements: dict[int, Entitlement] | None = None,
    ) -> None:
        super().__init__(orders)
        self.entitlements = dict(entitlements or {})

    def get_entitlement(self, user_id: int) -> Entitlement:
        return self.entitlements.setdefault(user_id, Entitlement())


class InMemoryPaymentLedgerRepository(InMemoryPaymentOrderRepository):
    def __init__(self, orders: list[PaymentOrder] | None = None) -> None:
        super().__init__(orders)
        self.entitlements: dict[int, Entitlement] = {}
        self.payment_events: list[PaymentEvent] = []
        self.processed_provider_charges: list[ProcessedProviderCharge] = []

    def get_entitlement(self, user_id: int) -> Entitlement:
        return self.entitlements.setdefault(user_id, Entitlement())

    def save_entitlement(self, user_id: int, entitlement: Entitlement) -> None:
        self.entitlements[user_id] = entitlement

    def insert_payment_event(self, event: PaymentEvent) -> PaymentEvent:
        self.payment_events.append(event)
        return event

    def load_payment_event(self, event_id: str) -> PaymentEvent | None:
        for event in self.payment_events:
            if event.event_id == event_id:
                return event
        return None

    def update_payment_event(self, event: PaymentEvent) -> PaymentEvent:
        for index, existing in enumerate(self.payment_events):
            if existing.event_id != event.event_id:
                continue
            self.payment_events[index] = event
            return event
        self.payment_events.append(event)
        return event

    def find_payment_event(
        self,
        *,
        provider: PaymentProvider,
        charge_id: str,
        event_type: PaymentEventType | None = None,
        statuses: tuple[PaymentEventStatus, ...] = (),
    ) -> PaymentEvent | None:
        for event in reversed(self.payment_events):
            if event.provider != provider:
                continue
            if event_type is not None and event.event_type != event_type:
                continue
            if statuses and event.status not in statuses:
                continue
            if charge_id in {
                event.charge_id,
                event.telegram_charge_id,
                event.provider_charge_id,
            }:
                return event
        return None

    def find_processed_provider_charge(
        self,
        *,
        provider: PaymentProvider,
        charge_id: str,
        event_type: PaymentEventType,
    ) -> ProcessedProviderCharge | None:
        for processed in self.processed_provider_charges:
            if (
                processed.provider == provider
                and processed.charge_id == charge_id
                and processed.event_type == event_type
            ):
                return processed
        return None

    def insert_processed_provider_charge(
        self,
        charge: ProcessedProviderCharge,
    ) -> ProcessedProviderCharge:
        existing = self.find_processed_provider_charge(
            provider=charge.provider,
            charge_id=charge.charge_id,
            event_type=charge.event_type,
        )
        if existing is not None:
            return existing
        self.processed_provider_charges.append(charge)
        return charge

    def mark_payment_order_paid(
        self,
        order_id: str,
        paid_at: datetime,
    ) -> PaymentOrder | None:
        for index, order in enumerate(self.orders):
            if order.order_id != order_id:
                continue
            updated = replace(
                order,
                status=PaymentOrderStatus.PAID,
                paid_at=paid_at,
                updated_at=paid_at,
            )
            self.orders[index] = updated
            return updated
        return None

    def processed_charge_ids(
        self,
        event_type: PaymentEventType = PaymentEventType.SUCCESSFUL_PAYMENT,
    ) -> list[str]:
        return [
            charge.charge_id
            for charge in self.processed_provider_charges
            if charge.event_type == event_type
        ]


def _payment_order(
    order_id: str,
    nonce: str,
    product: PaymentProduct,
    *,
    provider: PaymentProvider = PaymentProvider.TELEGRAM_STARS,
    amount: int = 400,
    currency: PaymentCurrency = PaymentCurrency.XTR,
    status: PaymentOrderStatus = PaymentOrderStatus.PENDING,
    user_id: int = 1001,
    delivery_chat_id: int | None = 2002,
    expires_at: datetime | None = None,
    pre_checkout_approved_at: datetime | None = None,
    list_amount: int | None = None,
    discount_amount: int = 0,
    promo_code_id: int | None = None,
    promo_redemption_id: int | None = None,
    promo_code_hash: str | None = None,
    promo_code_suffix: str | None = None,
    metadata: dict[str, object] | None = None,
) -> PaymentOrder:
    return PaymentOrder(
        order_id=order_id,
        nonce=nonce,
        user_id=user_id,
        delivery_chat_id=delivery_chat_id,
        provider=provider,
        product=product,
        amount=amount,
        currency=currency,
        status=status,
        expires_at=expires_at,
        pre_checkout_approved_at=pre_checkout_approved_at,
        list_amount=list_amount,
        discount_amount=discount_amount,
        promo_code_id=promo_code_id,
        promo_redemption_id=promo_redemption_id,
        promo_code_hash=promo_code_hash,
        promo_code_suffix=promo_code_suffix,
        metadata=metadata or {},
    )


def _successful_payment(
    order: PaymentOrder,
    *,
    payload: str | None = None,
    provider: PaymentProvider | str | None = None,
    telegram_charge_id: str = "tg-charge-1",
    provider_charge_id: str | None = None,
    user_id: int | None = None,
    delivery_chat_id: int | None = None,
    currency: PaymentCurrency | str | None = None,
    total_amount: int | None = None,
    expected_product: PaymentProduct | str | None = None,
    raw_payload: dict[str, object] | None = None,
) -> PaymentSuccessfulPaymentInput:
    return PaymentSuccessfulPaymentInput(
        payload=payload or order.payload,
        provider=provider or order.provider,
        telegram_charge_id=telegram_charge_id,
        provider_charge_id=provider_charge_id,
        user_id=order.user_id if user_id is None else user_id,
        delivery_chat_id=order.delivery_chat_id if delivery_chat_id is None else delivery_chat_id,
        currency=currency or order.currency,
        total_amount=order.amount if total_amount is None else total_amount,
        expected_product=expected_product,
        raw_payload=raw_payload,
    )


def _payment_reversal(
    event_type: PaymentEventType,
    order: PaymentOrder,
    *,
    telegram_charge_id: str | None,
    provider_charge_id: str | None = None,
    amount: int | None = None,
    currency: PaymentCurrency | str | None = None,
    raw_payload: dict[str, object] | None = None,
) -> PaymentReversalInput:
    return PaymentReversalInput(
        event_type=event_type,
        provider=order.provider,
        telegram_charge_id=telegram_charge_id,
        provider_charge_id=provider_charge_id,
        amount=order.amount if amount is None else amount,
        currency=order.currency if currency is None else currency,
        raw_payload=raw_payload,
    )


def _orphan_success_event(
    *,
    event_id: str = "evt_orphan1",
    provider: PaymentProvider = PaymentProvider.TELEGRAM_STARS,
    product: PaymentProduct | None = PaymentProduct.SUBSCRIPTION_MONTH,
    user_id: int = 1001,
    delivery_chat_id: int | None = 2002,
    amount: int = 400,
    currency: PaymentCurrency = PaymentCurrency.XTR,
    telegram_charge_id: str = "tg-charge-orphan1",
    provider_charge_id: str | None = None,
) -> PaymentEvent:
    return PaymentEvent(
        event_id=event_id,
        event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
        provider=provider,
        order_id="order_missing1",
        charge_id=telegram_charge_id,
        telegram_charge_id=telegram_charge_id,
        provider_charge_id=provider_charge_id,
        user_id=user_id,
        delivery_chat_id=delivery_chat_id,
        product=product,
        amount=amount,
        currency=currency,
        status=PaymentEventStatus.ORPHAN_RECOVERABLE,
        reason=PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND.value,
        raw_payload_redacted={"invoice_payload": "diet:order:order_missing1:nonce_missing1"},
    )


def _pay_order(
    repository: InMemoryPaymentLedgerRepository,
    order: PaymentOrder,
    *,
    now: datetime,
    telegram_charge_id: str,
    provider_charge_id: str | None = None,
) -> None:
    result = apply_successful_payment(
        repository,
        _successful_payment(
            order,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
        ),
        now=now,
    )
    assert result.processed is True


def _active_entitlement(now: datetime) -> Entitlement:
    return Entitlement(
        subscription_period_start=now.isoformat(),
        subscription_period_end=(now + timedelta(days=3)).isoformat(),
        monthly_one_day_remaining=2,
        monthly_weekly_pdf_remaining=1,
    )


def _sequence_factory(*values: str):
    remaining = iter(values)

    def factory() -> str:
        return next(remaining)

    return factory
