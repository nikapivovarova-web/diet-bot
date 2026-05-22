from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from typing import Protocol

from .payments import (
    EVENT_SUCCESSFUL_PAYMENT_DUPLICATE,
    EVENT_SUCCESSFUL_PAYMENT_ORPHAN,
    EVENT_SUCCESSFUL_PAYMENT_RECEIVED,
    EVENT_SUCCESSFUL_PAYMENT_REJECTED,
    EVENT_SUCCESSFUL_PAYMENT_UNKNOWN_PAYLOAD,
    ORDER_STATUS_PENDING,
    PaymentCharge,
    PaymentEvent,
    PaymentHandlingResult,
    PaymentOrder,
    PaymentPayloadError,
    PaymentValidationResult,
    RecordedPaymentCharge,
    decode_payment_order_payload,
    expected_payment_price,
)


class PaymentRepository(Protocol):
    def create_order(self, order: PaymentOrder) -> PaymentOrder:
        ...

    def get_order(self, order_id: str) -> PaymentOrder | None:
        ...

    def record_event(self, event: PaymentEvent) -> PaymentEvent:
        ...

    def record_charge(self, charge: PaymentCharge) -> RecordedPaymentCharge:
        ...

    def mark_order_paid(self, order_id: str) -> PaymentOrder:
        ...

    def mark_order_granted(self, order_id: str) -> PaymentOrder:
        ...

    def mark_order_failed(self, order_id: str, reason: str | None = None) -> PaymentOrder:
        ...


GrantEntitlement = Callable[[PaymentOrder, PaymentCharge], None]


class PaymentService:
    def __init__(
        self,
        repository: PaymentRepository,
        *,
        order_id_factory: Callable[[], str] | None = None,
        nonce_factory: Callable[[], str] | None = None,
        event_id_factory: Callable[[], str] | None = None,
        grant_entitlement: GrantEntitlement | None = None,
    ) -> None:
        self._repository = repository
        self._order_id_factory = order_id_factory or (lambda: f"order_{uuid.uuid4().hex}")
        self._nonce_factory = nonce_factory or (lambda: f"nonce_{secrets.token_urlsafe(12)}")
        self._event_id_factory = event_id_factory or (lambda: f"event_{uuid.uuid4().hex}")
        self._grant_entitlement = grant_entitlement

    def create_order(
        self,
        *,
        user_id: int,
        chat_id: int,
        product: str,
        provider: str,
        amount: int | None = None,
        currency: str | None = None,
    ) -> PaymentOrder:
        expected = expected_payment_price(provider, product)
        order = PaymentOrder(
            order_id=self._order_id_factory(),
            user_id=int(user_id),
            chat_id=int(chat_id),
            product=product,
            provider=provider,
            amount=expected.amount if amount is None else int(amount),
            currency=expected.currency if currency is None else str(currency),
            nonce=self._nonce_factory(),
        )
        return self._repository.create_order(order)

    def validate_order_payment(
        self,
        payload: str,
        *,
        user_id: int,
        chat_id: int,
        provider: str,
        amount: int,
        currency: str,
        require_pending: bool = True,
    ) -> PaymentValidationResult:
        try:
            decoded = decode_payment_order_payload(payload)
        except PaymentPayloadError as exc:
            return PaymentValidationResult(False, reason=str(exc))
        if decoded is None:
            return PaymentValidationResult(False, reason="non_order_payload")

        order = self._repository.get_order(decoded.order_id)
        if order is None:
            return PaymentValidationResult(False, reason="order_not_found")
        if order.nonce != decoded.nonce:
            return PaymentValidationResult(False, order, "nonce_mismatch")
        if int(order.user_id) != int(user_id):
            return PaymentValidationResult(False, order, "user_mismatch")
        if int(order.chat_id) != int(chat_id):
            return PaymentValidationResult(False, order, "chat_mismatch")
        if order.provider != provider:
            return PaymentValidationResult(False, order, "provider_mismatch")
        if int(order.amount) != int(amount):
            return PaymentValidationResult(False, order, "amount_mismatch")
        if order.currency != currency:
            return PaymentValidationResult(False, order, "currency_mismatch")
        if require_pending and order.status != ORDER_STATUS_PENDING:
            return PaymentValidationResult(False, order, "order_not_pending")
        return PaymentValidationResult(True, order)

    def handle_successful_payment(
        self,
        *,
        payload: str,
        user_id: int,
        chat_id: int,
        provider: str,
        amount: int,
        currency: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None = None,
        raw_payload: dict[str, object] | None = None,
    ) -> PaymentHandlingResult:
        validation = self.validate_order_payment(
            payload,
            user_id=user_id,
            chat_id=chat_id,
            provider=provider,
            amount=amount,
            currency=currency,
            require_pending=False,
        )
        event_payload = dict(raw_payload or {})
        event_payload.setdefault("invoice_payload", payload)
        event_payload.setdefault("reason", validation.reason)
        if not validation.valid:
            event_type = (
                EVENT_SUCCESSFUL_PAYMENT_UNKNOWN_PAYLOAD
                if validation.reason == "non_order_payload"
                else EVENT_SUCCESSFUL_PAYMENT_ORPHAN
                if validation.reason == "order_not_found"
                else EVENT_SUCCESSFUL_PAYMENT_REJECTED
            )
            self._repository.record_event(
                self._event(
                    event_type=event_type,
                    order_id=validation.order.order_id if validation.order else None,
                    provider=provider,
                    telegram_payment_charge_id=telegram_payment_charge_id,
                    provider_payment_charge_id=provider_payment_charge_id,
                    payload=event_payload,
                )
            )
            return PaymentHandlingResult(False, reason=validation.reason)

        order = validation.order
        assert order is not None
        if order.status != ORDER_STATUS_PENDING:
            event_payload["reason"] = "order_not_payable"
            event_payload["order_status"] = order.status
            self._repository.record_event(
                self._event(
                    event_type=EVENT_SUCCESSFUL_PAYMENT_DUPLICATE,
                    order_id=order.order_id,
                    provider=provider,
                    telegram_payment_charge_id=telegram_payment_charge_id,
                    provider_payment_charge_id=provider_payment_charge_id,
                    payload=event_payload,
                )
            )
            return PaymentHandlingResult(False, order.product, duplicate=True, reason="order_not_payable")

        charge = PaymentCharge(
            order_id=order.order_id,
            provider=provider,
            telegram_payment_charge_id=_optional_text(telegram_payment_charge_id),
            provider_payment_charge_id=_optional_text(provider_payment_charge_id),
            amount=int(amount),
            currency=currency,
            raw_payload=event_payload,
        )
        recorded = self._repository.record_charge(charge)
        if not recorded.inserted:
            self._repository.record_event(
                self._event(
                    event_type=EVENT_SUCCESSFUL_PAYMENT_DUPLICATE,
                    order_id=order.order_id,
                    provider=provider,
                    telegram_payment_charge_id=telegram_payment_charge_id,
                    provider_payment_charge_id=provider_payment_charge_id,
                    payload=event_payload,
                )
            )
            return PaymentHandlingResult(False, order.product, duplicate=True, reason="duplicate_charge")

        self._repository.record_event(
            self._event(
                event_type=EVENT_SUCCESSFUL_PAYMENT_RECEIVED,
                order_id=order.order_id,
                provider=provider,
                telegram_payment_charge_id=telegram_payment_charge_id,
                provider_payment_charge_id=provider_payment_charge_id,
                payload=event_payload,
            )
        )
        self._repository.mark_order_paid(order.order_id)
        try:
            if self._grant_entitlement is not None:
                self._grant_entitlement(order, recorded.charge)
        except Exception:
            self._repository.mark_order_failed(order.order_id, "grant_failed")
            raise
        self._repository.mark_order_granted(order.order_id)
        return PaymentHandlingResult(True, order.product)

    def _event(
        self,
        *,
        event_type: str,
        order_id: str | None,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
        payload: dict[str, object],
    ) -> PaymentEvent:
        return PaymentEvent(
            event_id=self._event_id_factory(),
            event_type=event_type,
            order_id=order_id,
            provider=provider,
            event_key=_event_key(provider, telegram_payment_charge_id, provider_payment_charge_id, event_type),
            telegram_payment_charge_id=_optional_text(telegram_payment_charge_id),
            provider_payment_charge_id=_optional_text(provider_payment_charge_id),
            payload=dict(payload),
        )


def _event_key(
    provider: str,
    telegram_payment_charge_id: str | None,
    provider_payment_charge_id: str | None,
    event_type: str,
) -> str | None:
    charge_id = _optional_text(telegram_payment_charge_id) or _optional_text(provider_payment_charge_id)
    if not charge_id:
        return None
    return f"{provider}:{charge_id}:{event_type}"


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
