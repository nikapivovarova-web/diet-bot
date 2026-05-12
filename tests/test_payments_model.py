from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from diet_bot.payments import (
    PAYMENT_ORDER_TTL_SECONDS,
    PROVIDER_CURRENCIES,
    TELEGRAM_STARS_SUBSCRIPTION_PERIOD_SECONDS,
    PaymentCurrency,
    PaymentEvent,
    PaymentEventStatus,
    PaymentEventType,
    PaymentInvoiceMetadata,
    PaymentOrder,
    PaymentOrderStatus,
    PaymentPayloadError,
    PaymentProductInvoiceMetadata,
    PaymentProduct,
    PaymentProvider,
    ProcessedProviderCharge,
    build_payment_invoice_metadata,
    build_payment_invoice_payload,
    create_or_reuse_pending_payment_order,
    decode_payment_order_payload,
    encode_payment_order_payload,
    get_payment_product_invoice_metadata,
    redact_payment_payload,
    validate_payment_invoice_payload,
)
from diet_bot.subscriptions import Entitlement


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
    ):
        assert secret not in serialized
    assert redacted["email"] == "[REDACTED]"
    assert redacted["phone_number"] == "[REDACTED]"
    assert redacted["order_info"] == "[REDACTED]"
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

    order = create_or_reuse_pending_payment_order(
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


def test_repeated_payment_order_creation_reuses_active_pending_order() -> None:
    repository = InMemoryPaymentOrderRepository()
    now = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)

    first = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.YOOKASSA,
        product=PaymentProduct.EXTRA_WEEKLY_PDF,
        amount=25000,
        currency=PaymentCurrency.RUB,
        now=now,
        order_id_factory=_sequence_factory("order_new1"),
        nonce_factory=_sequence_factory("nonce_new1"),
    )
    second = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.YOOKASSA,
        product=PaymentProduct.EXTRA_WEEKLY_PDF,
        amount=25000,
        currency=PaymentCurrency.RUB,
        now=now + timedelta(minutes=1),
        order_id_factory=_sequence_factory("order_new2"),
        nonce_factory=_sequence_factory("nonce_new2"),
    )

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

    order = create_or_reuse_pending_payment_order(
        repository,
        user_id=1001,
        delivery_chat_id=2002,
        provider=PaymentProvider.TELEGRAM_STARS,
        product=PaymentProduct.EXTRA_ONE_DAY,
        amount=35,
        currency=PaymentCurrency.XTR,
        now=now,
        order_id_factory=_sequence_factory("order_new1"),
        nonce_factory=_sequence_factory("nonce_new1"),
    )

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

    create_or_reuse_pending_payment_order(
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

    assert entitlement.to_dict() == before


class InMemoryPaymentOrderRepository:
    def __init__(self, orders: list[PaymentOrder] | None = None) -> None:
        self.orders = list(orders or [])

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
    ) -> PaymentOrder | None:
        for order in reversed(self.orders):
            if (
                order.user_id == user_id
                and order.delivery_chat_id == delivery_chat_id
                and order.provider == provider
                and order.product == product
                and order.amount == amount
                and order.currency == currency
                and order.status == PaymentOrderStatus.PENDING
                and order.expires_at is not None
                and order.expires_at > now
            ):
                return order
        return None

    def insert_payment_order(self, order: PaymentOrder) -> PaymentOrder:
        self.orders.append(order)
        return order


def _payment_order(
    order_id: str,
    nonce: str,
    product: PaymentProduct,
    *,
    provider: PaymentProvider = PaymentProvider.TELEGRAM_STARS,
    amount: int = 400,
    currency: PaymentCurrency = PaymentCurrency.XTR,
) -> PaymentOrder:
    return PaymentOrder(
        order_id=order_id,
        nonce=nonce,
        user_id=1001,
        delivery_chat_id=2002,
        provider=provider,
        product=product,
        amount=amount,
        currency=currency,
        status=PaymentOrderStatus.PENDING,
    )


def _sequence_factory(*values: str):
    remaining = iter(values)

    def factory() -> str:
        return next(remaining)

    return factory
