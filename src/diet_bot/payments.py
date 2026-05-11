from __future__ import annotations

import json
import os
import secrets
import uuid
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from .json_storage import json_storage_transaction


PaymentProduct = Literal["subscription_month", "extra_one_day", "extra_weekly_pdf"]
PaymentOrderStatus = Literal["pending", "paid", "expired", "failed_invoice_creation"]
PaymentEventType = Literal[
    "successful_payment",
    "refund",
    "chargeback",
    "cancel_subscription",
    "unknown",
]
PaymentEventStatus = Literal[
    "processed",
    "pending_reconciliation",
    "ignored_non_terminal",
    "orphan_recoverable",
    "duplicate",
]

PAYMENT_ORDER_TTL_SECONDS = 60 * 60
PAYMENT_ORDER_PAYLOAD_PREFIX = "diet:order"
ORPHAN_PAYMENT_LIMIT = 500
PAYMENT_EVENT_LIMIT = 1_000
PAYMENT_EVENT_SUCCESSFUL = "successful_payment"
PAYMENT_EVENT_REFUND = "refund"
PAYMENT_EVENT_CHARGEBACK = "chargeback"
PAYMENT_EVENT_CANCEL_SUBSCRIPTION = "cancel_subscription"
PAYMENT_EVENT_UNKNOWN = "unknown"
PAYMENT_EVENT_NEGATIVE_TYPES = {
    PAYMENT_EVENT_REFUND,
    PAYMENT_EVENT_CHARGEBACK,
}
PAYMENT_EVENT_CANCEL_TYPES = {
    PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
}
PAYMENT_EVENT_REVERSAL_TYPES = PAYMENT_EVENT_NEGATIVE_TYPES | PAYMENT_EVENT_CANCEL_TYPES
PROCESSED_PAYMENT_CHARGE_LEGACY_PROVIDER = "legacy"
PAYMENT_EVENT_STATUS_PROCESSED = "processed"
PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION = "pending_reconciliation"
PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL = "ignored_non_terminal"
PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE = "orphan_recoverable"
PAYMENT_EVENT_STATUS_DUPLICATE = "duplicate"
PAYMENT_EVENT_TRANSITIONAL_STATUSES = {
    PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
    PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE,
    "ignored",
    "orphan",
}


@dataclass(frozen=True)
class PaymentOrder:
    order_id: str
    nonce: str
    user_id: int
    delivery_chat_id: int | None
    product: PaymentProduct
    provider: str
    amount: int
    currency: str
    status: PaymentOrderStatus = "pending"
    is_recurring: bool = False
    created_at: str = ""
    expires_at: str = ""
    paid_at: str | None = None
    invoice_link: str | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: int,
        delivery_chat_id: int | None = None,
        product: PaymentProduct,
        provider: str,
        amount: int,
        currency: str,
        is_recurring: bool = False,
        now: datetime | None = None,
        ttl_seconds: int = PAYMENT_ORDER_TTL_SECONDS,
    ) -> PaymentOrder:
        created_at = _normalize_now(now)
        return cls(
            order_id=secrets.token_urlsafe(12),
            nonce=secrets.token_urlsafe(12),
            user_id=user_id,
            delivery_chat_id=delivery_chat_id,
            product=product,
            provider=provider,
            amount=amount,
            currency=currency,
            status="pending",
            is_recurring=is_recurring,
            created_at=_format_datetime(created_at),
            expires_at=_format_datetime(created_at + timedelta(seconds=ttl_seconds)),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentOrder | None:
        try:
            product = str(data["product"])
            if product not in {"subscription_month", "extra_one_day", "extra_weekly_pdf"}:
                return None
            status = str(data.get("status", "pending"))
            if status not in {"pending", "paid", "expired", "failed_invoice_creation"}:
                return None
            order_id = str(data["order_id"]).strip()
            nonce = str(data["nonce"]).strip()
            if not order_id or not nonce:
                return None
            return cls(
                order_id=order_id,
                nonce=nonce,
                user_id=int(data["user_id"]),
                delivery_chat_id=_optional_int(data.get("delivery_chat_id")),
                product=product,  # type: ignore[arg-type]
                provider=str(data["provider"]),
                amount=int(data["amount"]),
                currency=str(data["currency"]),
                status=status,  # type: ignore[arg-type]
                is_recurring=bool(data.get("is_recurring", False)),
                created_at=_optional_datetime_text(data.get("created_at")) or "",
                expires_at=_optional_datetime_text(data.get("expires_at")) or "",
                paid_at=_optional_datetime_text(data.get("paid_at")),
                invoice_link=_optional_str(data.get("invoice_link")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def payload(self) -> str:
        return encode_payment_order_payload(self.order_id, self.nonce)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "nonce": self.nonce,
            "user_id": self.user_id,
            "delivery_chat_id": self.delivery_chat_id,
            "product": self.product,
            "provider": self.provider,
            "amount": self.amount,
            "currency": self.currency,
            "status": self.status,
            "is_recurring": self.is_recurring,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "paid_at": self.paid_at,
            "invoice_link": self.invoice_link,
        }

    def is_expired(self, now: datetime | None = None) -> bool:
        expires_at = _parse_datetime(self.expires_at)
        return bool(expires_at and expires_at <= _normalize_now(now))

    def mark_paid(self, now: datetime | None = None) -> PaymentOrder:
        return PaymentOrder(
            order_id=self.order_id,
            nonce=self.nonce,
            user_id=self.user_id,
            delivery_chat_id=self.delivery_chat_id,
            product=self.product,
            provider=self.provider,
            amount=self.amount,
            currency=self.currency,
            status="paid",
            is_recurring=self.is_recurring,
            created_at=self.created_at,
            expires_at=self.expires_at,
            paid_at=_format_datetime(_normalize_now(now)),
            invoice_link=self.invoice_link,
        )

    def mark_expired(self) -> PaymentOrder:
        return PaymentOrder(
            order_id=self.order_id,
            nonce=self.nonce,
            user_id=self.user_id,
            delivery_chat_id=self.delivery_chat_id,
            product=self.product,
            provider=self.provider,
            amount=self.amount,
            currency=self.currency,
            status="expired",
            is_recurring=self.is_recurring,
            created_at=self.created_at,
            expires_at=self.expires_at,
            paid_at=self.paid_at,
            invoice_link=self.invoice_link,
        )

    def mark_failed_invoice_creation(self) -> PaymentOrder:
        return PaymentOrder(
            order_id=self.order_id,
            nonce=self.nonce,
            user_id=self.user_id,
            delivery_chat_id=self.delivery_chat_id,
            product=self.product,
            provider=self.provider,
            amount=self.amount,
            currency=self.currency,
            status="failed_invoice_creation",
            is_recurring=self.is_recurring,
            created_at=self.created_at,
            expires_at=self.expires_at,
            paid_at=self.paid_at,
            invoice_link=self.invoice_link,
        )

    def with_invoice_link(self, invoice_link: str) -> PaymentOrder:
        return PaymentOrder(
            order_id=self.order_id,
            nonce=self.nonce,
            user_id=self.user_id,
            delivery_chat_id=self.delivery_chat_id,
            product=self.product,
            provider=self.provider,
            amount=self.amount,
            currency=self.currency,
            status=self.status,
            is_recurring=self.is_recurring,
            created_at=self.created_at,
            expires_at=self.expires_at,
            paid_at=self.paid_at,
            invoice_link=invoice_link,
        )


@dataclass
class PaymentOrderState:
    orders: dict[str, PaymentOrder] = field(default_factory=dict)
    orphan_payments: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "orders": {
                order_id: order.to_dict()
                for order_id, order in sorted(self.orders.items())
            },
            "orphan_payments": self.orphan_payments[-ORPHAN_PAYMENT_LIMIT:],
        }


@dataclass(frozen=True)
class PaymentEvent:
    event_id: str
    event_type: str
    provider: str
    charge_id: str
    telegram_charge_id: str | None = None
    provider_charge_id: str | None = None
    user_id: int | None = None
    product: str | None = None
    amount: int | None = None
    currency: str | None = None
    status: str = "processed"
    reason: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        provider: str,
        charge_id: str,
        event_id: str | None = None,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        user_id: int | None = None,
        product: str | None = None,
        amount: int | None = None,
        currency: str | None = None,
        status: str = "processed",
        reason: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> PaymentEvent:
        payload = raw_payload or {}
        return cls(
            event_id=event_id or _event_id_from_payload(payload) or f"evt_{uuid.uuid4().hex}",
            event_type=str(event_type),
            provider=str(provider),
            charge_id=str(charge_id),
            telegram_charge_id=_optional_str(telegram_charge_id)
            or _optional_str(payload.get("telegram_payment_charge_id")),
            provider_charge_id=_optional_str(provider_charge_id)
            or _optional_str(payload.get("provider_payment_charge_id")),
            user_id=user_id,
            product=product,
            amount=amount,
            currency=currency,
            status=_normalize_payment_event_status(status, reason),
            reason=reason,
            raw_payload=payload,
            created_at=_format_datetime(_normalize_now(now)),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentEvent | None:
        try:
            event_type = str(data["event_type"]).strip()
            provider = str(data["provider"]).strip()
            charge_id = str(data["charge_id"]).strip()
            if not event_type or not provider or not charge_id:
                return None
            raw_payload = data.get("raw_payload", {})
            raw_payload_dict = raw_payload if isinstance(raw_payload, dict) else {}
            reason = _optional_str(data.get("reason"))
            return cls(
                event_id=_optional_str(data.get("event_id")) or f"evt_{uuid.uuid4().hex}",
                event_type=event_type,
                provider=provider,
                charge_id=charge_id,
                telegram_charge_id=_optional_str(data.get("telegram_charge_id"))
                or _optional_str(data.get("telegram_payment_charge_id"))
                or _optional_str(raw_payload_dict.get("telegram_payment_charge_id")),
                provider_charge_id=_optional_str(data.get("provider_charge_id"))
                or _optional_str(data.get("provider_payment_charge_id"))
                or _optional_str(raw_payload_dict.get("provider_payment_charge_id")),
                user_id=_optional_int(data.get("user_id")),
                product=_optional_str(data.get("product")),
                amount=_optional_int(data.get("amount")),
                currency=_optional_str(data.get("currency")),
                status=_normalize_payment_event_status(
                    _optional_str(data.get("status")) or "processed",
                    reason,
                ),
                reason=reason,
                raw_payload=raw_payload_dict,
                created_at=_optional_datetime_text(data.get("created_at")) or "",
            )
        except (KeyError, TypeError, ValueError):
            return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "provider": self.provider,
            "charge_id": self.charge_id,
            "telegram_charge_id": self.telegram_charge_id,
            "provider_charge_id": self.provider_charge_id,
            "user_id": self.user_id,
            "product": self.product,
            "amount": self.amount,
            "currency": self.currency,
            "status": self.status,
            "reason": self.reason,
            "raw_payload": self.raw_payload,
            "created_at": self.created_at,
        }


@dataclass
class PaymentEventState:
    events: list[PaymentEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [
                event.to_dict()
                for event in self.events[-PAYMENT_EVENT_LIMIT:]
            ]
        }


@dataclass(frozen=True)
class ProcessedPaymentCharge:
    provider: str
    charge_id: str
    telegram_charge_id: str | None = None
    provider_charge_id: str | None = None
    user_id: int | None = None
    kind: str | None = None
    created_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        charge_id: str,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        user_id: int | None = None,
        kind: str | None = None,
        created_at: str | None = None,
        now: datetime | None = None,
    ) -> ProcessedPaymentCharge:
        return cls(
            provider=str(provider),
            charge_id=str(charge_id),
            telegram_charge_id=_optional_str(telegram_charge_id),
            provider_charge_id=_optional_str(provider_charge_id),
            user_id=user_id,
            kind=kind,
            created_at=created_at or _format_datetime(_normalize_now(now)),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessedPaymentCharge | None:
        try:
            provider = str(data["provider"]).strip()
            charge_id = str(data["charge_id"]).strip()
            if not provider or not charge_id:
                return None
            return cls(
                provider=provider,
                charge_id=charge_id,
                telegram_charge_id=_optional_str(data.get("telegram_charge_id"))
                or _optional_str(data.get("telegram_payment_charge_id")),
                provider_charge_id=_optional_str(data.get("provider_charge_id"))
                or _optional_str(data.get("provider_payment_charge_id")),
                user_id=_optional_int(data.get("user_id")),
                kind=_optional_str(data.get("kind")),
                created_at=_optional_datetime_text(data.get("created_at")) or "",
            )
        except (KeyError, TypeError, ValueError):
            return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "charge_id": self.charge_id,
            "telegram_charge_id": self.telegram_charge_id,
            "provider_charge_id": self.provider_charge_id,
            "user_id": self.user_id,
            "kind": self.kind,
            "created_at": self.created_at,
        }


@dataclass
class ProcessedPaymentChargeState:
    charges: dict[str, ProcessedPaymentCharge] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            key: charge.to_dict()
            for key, charge in sorted(self.charges.items())
        }


@dataclass(frozen=True)
class PaymentEventApplication:
    processed: bool
    event_type: str
    product: str | None = None
    duplicate: bool = False
    reason: str | None = None
    status: str | None = None


def encode_payment_order_payload(order_id: str, nonce: str) -> str:
    return f"{PAYMENT_ORDER_PAYLOAD_PREFIX}:{order_id}:{nonce}"


def decode_payment_order_payload(payload: str) -> tuple[str, str] | None:
    parts = payload.split(":")
    if len(parts) != 4 or parts[0] != "diet" or parts[1] != "order":
        return None
    order_id, nonce = parts[2].strip(), parts[3].strip()
    if not order_id or not nonce:
        return None
    return order_id, nonce


def load_payment_order_state(path: Path) -> PaymentOrderState:
    if not path.exists():
        return PaymentOrderState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not read payment order state file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid payment order state file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Invalid payment order state file {path}: expected a JSON object.")

    raw_orders = raw.get("orders", {})
    orders: dict[str, PaymentOrder] = {}
    if isinstance(raw_orders, dict):
        for order_id, order_data in raw_orders.items():
            if not isinstance(order_data, dict):
                continue
            order = PaymentOrder.from_dict(order_data)
            if order is not None:
                orders[str(order_id)] = order

    raw_orphans = raw.get("orphan_payments", [])
    orphan_payments = [
        item
        for item in raw_orphans
        if isinstance(item, dict)
    ][-ORPHAN_PAYMENT_LIMIT:]
    return PaymentOrderState(orders=orders, orphan_payments=orphan_payments)


def save_payment_order_state(path: Path, state: PaymentOrderState) -> None:
    _write_json_atomic(path, state.to_dict())


def load_payment_event_state(path: Path) -> PaymentEventState:
    if not path.exists():
        return PaymentEventState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not read payment event state file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid payment event state file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Invalid payment event state file {path}: expected a JSON object.")
    raw_events = raw.get("events", [])
    events = []
    if isinstance(raw_events, list):
        for event_data in raw_events:
            if not isinstance(event_data, dict):
                continue
            event = PaymentEvent.from_dict(event_data)
            if event is not None:
                events.append(event)
    return PaymentEventState(events=events[-PAYMENT_EVENT_LIMIT:])


def save_payment_event_state(path: Path, state: PaymentEventState) -> None:
    _write_json_atomic(path, state.to_dict())


def processed_payment_charge_key(provider: str, charge_id: str) -> str:
    return f"{provider}:{charge_id}"


def load_processed_payment_charge_state(path: Path) -> ProcessedPaymentChargeState:
    if not path.exists():
        return ProcessedPaymentChargeState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not read processed payment charge registry file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid processed payment charge registry file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Invalid processed payment charge registry file {path}: expected a JSON object.")

    raw_charges = raw.get("processed_charges", raw)
    if not isinstance(raw_charges, dict):
        raise RuntimeError(f"Invalid processed payment charge registry file {path}: expected charge entries.")

    charges: dict[str, ProcessedPaymentCharge] = {}
    for item in raw_charges.values():
        if not isinstance(item, dict):
            continue
        charge = ProcessedPaymentCharge.from_dict(item)
        if charge is None:
            continue
        charges[processed_payment_charge_key(charge.provider, charge.charge_id)] = charge
    return ProcessedPaymentChargeState(charges=charges)


def save_processed_payment_charge_state(path: Path, state: ProcessedPaymentChargeState) -> None:
    _write_json_atomic(path, state.to_dict())


def processed_payment_charge_exists(
    state: ProcessedPaymentChargeState,
    *,
    provider: str,
    charge_id: str,
) -> bool:
    if not provider or not charge_id:
        return False
    if (
        processed_payment_charge_key(provider, charge_id) in state.charges
        or processed_payment_charge_key(PROCESSED_PAYMENT_CHARGE_LEGACY_PROVIDER, charge_id) in state.charges
    ):
        return True
    return any(
        charge.provider == provider
        and charge_id in _charge_aliases(
            charge.charge_id,
            telegram_charge_id=charge.telegram_charge_id,
            provider_charge_id=charge.provider_charge_id,
            raw_payload=None,
        )
        for charge in state.charges.values()
    )


def add_processed_payment_charge(
    state: ProcessedPaymentChargeState,
    charge: ProcessedPaymentCharge,
) -> bool:
    if not charge.provider or not charge.charge_id:
        return False
    key = processed_payment_charge_key(charge.provider, charge.charge_id)
    if key in state.charges:
        return False
    state.charges[key] = charge
    return True


def record_payment_event(path: Path, event: PaymentEvent) -> bool:
    with json_storage_transaction(path):
        state = load_payment_event_state(path)
        existing_index = find_payment_event_index(
            state,
            provider=event.provider,
            charge_id=event.charge_id,
            event_type=event.event_type,
        )
        if existing_index is not None:
            existing = state.events[existing_index]
            if existing.status not in PAYMENT_EVENT_TRANSITIONAL_STATUSES:
                return False
            merged_raw_payload = {
                **existing.raw_payload,
                **event.raw_payload,
                "reconciled_from_event_id": existing.event_id,
            }
            state.events[existing_index] = replace(
                event,
                event_id=existing.event_id,
                created_at=existing.created_at or event.created_at,
                raw_payload=merged_raw_payload,
            )
            save_payment_event_state(path, state)
            return True
        if not event.created_at:
            event = replace(event, created_at=_format_datetime(_normalize_now(None)))
        state.events.append(event)
        state.events = state.events[-PAYMENT_EVENT_LIMIT:]
        save_payment_event_state(path, state)
        return True


def payment_event_exists(
    state: PaymentEventState,
    *,
    provider: str,
    charge_id: str,
    event_type: str,
) -> bool:
    return find_payment_event_index(
        state,
        provider=provider,
        charge_id=charge_id,
        event_type=event_type,
    ) is not None


def find_payment_event_index(
    state: PaymentEventState,
    *,
    provider: str | None = None,
    charge_id: str | None = None,
    event_type: str | None = None,
    event_id: str | None = None,
    statuses: set[str] | None = None,
) -> int | None:
    for index in range(len(state.events) - 1, -1, -1):
        event = state.events[index]
        if not payment_event_matches(
            event,
            provider=provider,
            charge_id=charge_id,
            event_type=event_type,
            event_id=event_id,
            statuses=statuses,
        ):
            continue
        return index
    return None


def find_payment_event(
    state: PaymentEventState,
    *,
    provider: str | None = None,
    charge_id: str | None = None,
    event_type: str | None = None,
    event_id: str | None = None,
    statuses: set[str] | None = None,
) -> PaymentEvent | None:
    index = find_payment_event_index(
        state,
        provider=provider,
        charge_id=charge_id,
        event_type=event_type,
        event_id=event_id,
        statuses=statuses,
    )
    return state.events[index] if index is not None else None


def payment_event_matches(
    event: PaymentEvent,
    *,
    provider: str | None = None,
    charge_id: str | None = None,
    event_type: str | None = None,
    event_id: str | None = None,
    statuses: set[str] | None = None,
) -> bool:
    if event_id and event.event_id != event_id:
        return False
    if event_type and event.event_type != event_type:
        return False
    if provider and event.provider != provider:
        return False
    if statuses is not None and event.status not in statuses:
        return False
    if charge_id and charge_id not in payment_event_charge_aliases(event):
        return False
    return True


def payment_event_charge_aliases(event: PaymentEvent) -> set[str]:
    return _charge_aliases(
        event.charge_id,
        telegram_charge_id=event.telegram_charge_id,
        provider_charge_id=event.provider_charge_id,
        raw_payload=event.raw_payload,
    )


def terminal_payment_adjustment_exists(
    state: PaymentEventState,
    *,
    event_type: str,
    provider: str,
    charge_id: str,
) -> bool:
    if event_type not in PAYMENT_EVENT_NEGATIVE_TYPES:
        return False
    return any(
        event.provider == provider
        and charge_id in payment_event_charge_aliases(event)
        and event.event_type in PAYMENT_EVENT_NEGATIVE_TYPES
        and event.status == PAYMENT_EVENT_STATUS_PROCESSED
        for event in state.events
    )


def find_successful_payment_event(
    state: PaymentEventState,
    *,
    provider: str,
    charge_id: str,
) -> PaymentEvent | None:
    for event in reversed(state.events):
        if (
            event.provider == provider
            and charge_id in payment_event_charge_aliases(event)
            and event.event_type == PAYMENT_EVENT_SUCCESSFUL
            and event.status == PAYMENT_EVENT_STATUS_PROCESSED
        ):
            return event
    return None


def remember_payment_order(path: Path, order: PaymentOrder) -> None:
    with json_storage_transaction(path):
        state = load_payment_order_state(path)
        state.orders[order.order_id] = order
        save_payment_order_state(path, state)


def record_orphan_payment(path: Path, payment: dict[str, Any]) -> None:
    with json_storage_transaction(path):
        state = load_payment_order_state(path)
        state.orphan_payments.append(payment)
        state.orphan_payments = state.orphan_payments[-ORPHAN_PAYMENT_LIMIT:]
        save_payment_order_state(path, state)


def _normalize_payment_event_status(status: str | None, reason: str | None = None) -> str:
    text = str(status or "").strip() or PAYMENT_EVENT_STATUS_PROCESSED
    if text in {
        PAYMENT_EVENT_STATUS_PROCESSED,
        PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
        PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
        PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE,
        PAYMENT_EVENT_STATUS_DUPLICATE,
    }:
        return text
    if text == "orphan":
        return PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE
    if text == "ignored":
        if reason == "original_payment_not_found":
            return PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION
        return PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL
    return PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL


def _event_id_from_payload(raw_payload: dict[str, Any]) -> str | None:
    for key in ("event_id", "payment_event_id", "id"):
        value = _optional_str(raw_payload.get(key))
        if value:
            return value
    return None


def _charge_aliases(
    charge_id: str | None,
    *,
    telegram_charge_id: str | None,
    provider_charge_id: str | None,
    raw_payload: dict[str, Any] | None,
) -> set[str]:
    aliases = {
        value
        for value in (
            _optional_str(charge_id),
            _optional_str(telegram_charge_id),
            _optional_str(provider_charge_id),
        )
        if value
    }
    if isinstance(raw_payload, dict):
        for key in ("telegram_payment_charge_id", "provider_payment_charge_id"):
            value = _optional_str(raw_payload.get(key))
            if value:
                aliases.add(value)
    return aliases


def _normalize_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _optional_datetime_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _format_datetime(value)
    text = str(value).strip()
    return text or None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _normalize_now(datetime.fromisoformat(value))
    except ValueError:
        return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with json_storage_transaction(path):
        try:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        finally:
            with suppress(OSError):
                tmp_path.unlink()
