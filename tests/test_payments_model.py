from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from diet_bot.payments import (
    PROVIDER_CURRENCIES,
    PaymentCurrency,
    PaymentEvent,
    PaymentEventStatus,
    PaymentEventType,
    PaymentOrder,
    PaymentOrderStatus,
    PaymentPayloadError,
    PaymentProduct,
    PaymentProvider,
    ProcessedProviderCharge,
    decode_payment_order_payload,
    encode_payment_order_payload,
    redact_payment_payload,
)
from diet_bot.subscriptions import Entitlement


def test_payment_order_payload_round_trips_order_id_and_nonce() -> None:
    payload = encode_payment_order_payload("order_123", "nonce_456")

    assert payload == "diet:order:order_123:nonce_456"
    assert decode_payment_order_payload(payload) == ("order_123", "nonce_456")


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
