from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from diet_bot.payment_service import PaymentService
from diet_bot.payments import (
    ORDER_STATUS_FAILED,
    ORDER_STATUS_GRANTED,
    PRODUCT_EXTRA_ONE_DAY,
    PRODUCT_SUBSCRIPTION_MONTH,
    PROVIDER_TELEGRAM_STARS,
    PROVIDER_YOOKASSA,
    PaymentCharge,
    PaymentEvent,
    PaymentOrder,
    RecordedPaymentCharge,
    encode_payment_order_payload,
)


def test_create_and_validate_order() -> None:
    repo = FakePaymentRepository()
    service = PaymentService(
        repo,
        order_id_factory=lambda: "order_1234567890",
        nonce_factory=lambda: "nonce_abcdef123456",
    )

    order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    validation = service.validate_order_payment(
        encode_payment_order_payload(order.order_id, order.nonce),
        user_id=101,
        chat_id=202,
        provider=PROVIDER_TELEGRAM_STARS,
        amount=400,
        currency="XTR",
    )

    assert order.amount == 400
    assert order.currency == "XTR"
    assert validation.valid
    assert validation.order == order


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"user_id": 999}, "user_mismatch"),
        ({"chat_id": 999}, "chat_mismatch"),
        ({"provider": PROVIDER_YOOKASSA}, "provider_mismatch"),
        ({"amount": 401}, "amount_mismatch"),
        ({"currency": "RUB"}, "currency_mismatch"),
    ],
)
def test_validate_order_rejects_mismatched_payment_context(kwargs: dict[str, Any], reason: str) -> None:
    repo = FakePaymentRepository()
    service = PaymentService(
        repo,
        order_id_factory=lambda: "order_1234567890",
        nonce_factory=lambda: "nonce_abcdef123456",
    )
    order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    request = {
        "user_id": 101,
        "chat_id": 202,
        "provider": PROVIDER_TELEGRAM_STARS,
        "amount": 400,
        "currency": "XTR",
    }
    request.update(kwargs)

    validation = service.validate_order_payment(
        encode_payment_order_payload(order.order_id, order.nonce),
        **request,
    )

    assert not validation.valid
    assert validation.reason == reason


def test_validate_order_rejects_nonce_mismatch() -> None:
    repo = FakePaymentRepository()
    service = PaymentService(
        repo,
        order_id_factory=lambda: "order_1234567890",
        nonce_factory=lambda: "nonce_abcdef123456",
    )
    order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )

    validation = service.validate_order_payment(
        encode_payment_order_payload(order.order_id, "nonce_wrong123456"),
        user_id=101,
        chat_id=202,
        provider=PROVIDER_TELEGRAM_STARS,
        amount=400,
        currency="XTR",
    )

    assert not validation.valid
    assert validation.reason == "nonce_mismatch"


def test_duplicate_charge_does_not_grant_twice() -> None:
    repo = FakePaymentRepository()
    grants: list[tuple[PaymentOrder, PaymentCharge]] = []
    service = PaymentService(
        repo,
        order_id_factory=lambda: "order_1234567890",
        nonce_factory=lambda: "nonce_abcdef123456",
        grant_entitlement=lambda order, charge: grants.append((order, charge)),
    )
    order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    payload = encode_payment_order_payload(order.order_id, order.nonce)

    first = service.handle_successful_payment(
        payload=payload,
        user_id=101,
        chat_id=202,
        provider=PROVIDER_TELEGRAM_STARS,
        amount=400,
        currency="XTR",
        telegram_payment_charge_id="tg-charge-1",
    )
    second = service.handle_successful_payment(
        payload=payload,
        user_id=101,
        chat_id=202,
        provider=PROVIDER_TELEGRAM_STARS,
        amount=400,
        currency="XTR",
        telegram_payment_charge_id="tg-charge-1",
    )

    assert first.processed
    assert first.grant == PRODUCT_SUBSCRIPTION_MONTH
    assert second.duplicate
    assert not second.processed
    assert len(grants) == 1
    assert len(repo.charges) == 1
    assert repo.orders[order.order_id].status == ORDER_STATUS_GRANTED


def test_same_order_payload_with_new_charge_after_grant_is_ignored() -> None:
    repo = FakePaymentRepository()
    grants: list[tuple[PaymentOrder, PaymentCharge]] = []
    service = PaymentService(
        repo,
        order_id_factory=lambda: "order_1234567890",
        nonce_factory=lambda: "nonce_abcdef123456",
        grant_entitlement=lambda order, charge: grants.append((order, charge)),
    )
    order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    payload = encode_payment_order_payload(order.order_id, order.nonce)

    first = service.handle_successful_payment(
        payload=payload,
        user_id=101,
        chat_id=202,
        provider=PROVIDER_TELEGRAM_STARS,
        amount=400,
        currency="XTR",
        telegram_payment_charge_id="tg-charge-1",
    )
    second = service.handle_successful_payment(
        payload=payload,
        user_id=101,
        chat_id=202,
        provider=PROVIDER_TELEGRAM_STARS,
        amount=400,
        currency="XTR",
        telegram_payment_charge_id="tg-charge-2",
    )

    assert first.processed
    assert first.grant == PRODUCT_SUBSCRIPTION_MONTH
    assert not second.processed
    assert second.duplicate
    assert second.reason == "order_not_payable"
    assert len(grants) == 1
    assert len(repo.charges) == 1
    assert repo.orders[order.order_id].status == ORDER_STATUS_GRANTED
    assert repo.events[-1].event_type == "successful_payment_duplicate"
    assert repo.events[-1].payload["reason"] == "order_not_payable"
    assert repo.events[-1].payload["order_status"] == ORDER_STATUS_GRANTED


def test_unknown_and_orphan_successful_payments_record_event_without_grant() -> None:
    repo = FakePaymentRepository()
    grants: list[tuple[PaymentOrder, PaymentCharge]] = []
    service = PaymentService(repo, grant_entitlement=lambda order, charge: grants.append((order, charge)))

    unknown = service.handle_successful_payment(
        payload="diet:stars:subscription_month",
        user_id=101,
        chat_id=202,
        provider=PROVIDER_TELEGRAM_STARS,
        amount=400,
        currency="XTR",
        telegram_payment_charge_id="tg-charge-unknown",
    )
    orphan = service.handle_successful_payment(
        payload=encode_payment_order_payload("order_missing123", "nonce_missing123"),
        user_id=101,
        chat_id=202,
        provider=PROVIDER_TELEGRAM_STARS,
        amount=400,
        currency="XTR",
        telegram_payment_charge_id="tg-charge-orphan",
    )

    assert not unknown.processed
    assert unknown.reason == "non_order_payload"
    assert not orphan.processed
    assert orphan.reason == "order_not_found"
    assert grants == []
    assert [event.event_type for event in repo.events] == [
        "successful_payment_unknown_payload",
        "successful_payment_orphan",
    ]


def test_grant_failure_marks_order_failed_and_reraises() -> None:
    repo = FakePaymentRepository()

    def fail_grant(_order: PaymentOrder, _charge: PaymentCharge) -> None:
        raise RuntimeError("entitlement down")

    service = PaymentService(
        repo,
        order_id_factory=lambda: "order_1234567890",
        nonce_factory=lambda: "nonce_abcdef123456",
        grant_entitlement=fail_grant,
    )
    order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_EXTRA_ONE_DAY,
        provider=PROVIDER_TELEGRAM_STARS,
    )

    with pytest.raises(RuntimeError, match="entitlement down"):
        service.handle_successful_payment(
            payload=encode_payment_order_payload(order.order_id, order.nonce),
            user_id=101,
            chat_id=202,
            provider=PROVIDER_TELEGRAM_STARS,
            amount=35,
            currency="XTR",
            telegram_payment_charge_id="tg-charge-fails",
        )

    assert repo.orders[order.order_id].status == ORDER_STATUS_FAILED


class FakePaymentRepository:
    def __init__(self) -> None:
        self.orders: dict[str, PaymentOrder] = {}
        self.charges: list[PaymentCharge] = []
        self.events: list[PaymentEvent] = []

    def create_order(self, order: PaymentOrder) -> PaymentOrder:
        self.orders[order.order_id] = order
        return order

    def get_order(self, order_id: str) -> PaymentOrder | None:
        return self.orders.get(order_id)

    def record_event(self, event: PaymentEvent) -> PaymentEvent:
        if event.event_key:
            for existing in self.events:
                if existing.event_key == event.event_key:
                    return existing
        self.events.append(event)
        return event

    def record_charge(self, charge: PaymentCharge) -> RecordedPaymentCharge:
        for existing in self.charges:
            if (
                charge.provider == existing.provider
                and charge.telegram_payment_charge_id
                and charge.telegram_payment_charge_id == existing.telegram_payment_charge_id
            ):
                return RecordedPaymentCharge(existing, inserted=False)
            if (
                charge.provider == existing.provider
                and charge.provider_payment_charge_id
                and charge.provider_payment_charge_id == existing.provider_payment_charge_id
            ):
                return RecordedPaymentCharge(existing, inserted=False)
        saved = replace(charge, charge_id=len(self.charges) + 1)
        self.charges.append(saved)
        return RecordedPaymentCharge(saved, inserted=True)

    def mark_order_paid(self, order_id: str) -> PaymentOrder:
        return self._mark(order_id, "paid")

    def mark_order_granted(self, order_id: str) -> PaymentOrder:
        return self._mark(order_id, "granted")

    def mark_order_failed(self, order_id: str, reason: str | None = None) -> PaymentOrder:
        order = self._mark(order_id, "failed")
        return replace(order, failure_reason=reason)

    def _mark(self, order_id: str, status: str) -> PaymentOrder:
        order = replace(self.orders[order_id], status=status)
        self.orders[order_id] = order
        return order
