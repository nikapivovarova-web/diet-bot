from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


PRODUCT_SUBSCRIPTION_MONTH = "subscription_month"
PRODUCT_EXTRA_ONE_DAY = "extra_one_day"
PRODUCT_EXTRA_WEEKLY_PDF = "extra_weekly_pdf"
PAYMENT_PRODUCTS = (
    PRODUCT_SUBSCRIPTION_MONTH,
    PRODUCT_EXTRA_ONE_DAY,
    PRODUCT_EXTRA_WEEKLY_PDF,
)
PaymentProduct = Literal["subscription_month", "extra_one_day", "extra_weekly_pdf"]

PROVIDER_TELEGRAM_STARS = "telegram_stars"
PROVIDER_YOOKASSA = "yookassa"
PAYMENT_PROVIDERS = (PROVIDER_TELEGRAM_STARS, PROVIDER_YOOKASSA)
PaymentProvider = Literal["telegram_stars", "yookassa"]

ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_GRANTED = "granted"
ORDER_STATUS_FAILED = "failed"
PAYMENT_ORDER_STATUSES = (
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PAID,
    ORDER_STATUS_GRANTED,
    ORDER_STATUS_FAILED,
)
PaymentOrderStatus = Literal["pending", "paid", "granted", "failed"]

CHARGE_STATUS_SUCCEEDED = "succeeded"
CHARGE_STATUS_REFUNDED = "refunded"
CHARGE_STATUS_CANCELED = "canceled"
PAYMENT_CHARGE_STATUSES = (
    CHARGE_STATUS_SUCCEEDED,
    CHARGE_STATUS_REFUNDED,
    CHARGE_STATUS_CANCELED,
)
PaymentChargeStatus = Literal["succeeded", "refunded", "canceled"]

EVENT_SUCCESSFUL_PAYMENT_RECEIVED = "successful_payment_received"
EVENT_SUCCESSFUL_PAYMENT_DUPLICATE = "successful_payment_duplicate"
EVENT_SUCCESSFUL_PAYMENT_UNKNOWN_PAYLOAD = "successful_payment_unknown_payload"
EVENT_SUCCESSFUL_PAYMENT_ORPHAN = "successful_payment_orphan"
EVENT_SUCCESSFUL_PAYMENT_REJECTED = "successful_payment_rejected"
PAYMENT_EVENT_TYPES = (
    EVENT_SUCCESSFUL_PAYMENT_RECEIVED,
    EVENT_SUCCESSFUL_PAYMENT_DUPLICATE,
    EVENT_SUCCESSFUL_PAYMENT_UNKNOWN_PAYLOAD,
    EVENT_SUCCESSFUL_PAYMENT_ORPHAN,
    EVENT_SUCCESSFUL_PAYMENT_REJECTED,
)
PaymentEventType = Literal[
    "successful_payment_received",
    "successful_payment_duplicate",
    "successful_payment_unknown_payload",
    "successful_payment_orphan",
    "successful_payment_rejected",
]

ORDER_PAYLOAD_PREFIX = "diet:order:v1"
MAX_TELEGRAM_INVOICE_PAYLOAD_LENGTH = 128

_PAYLOAD_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_CHECKSUM_RE = re.compile(r"^[a-f0-9]{16}$")


class PaymentPayloadError(ValueError):
    """Raised when an order payment payload is malformed or fails checksum validation."""


@dataclass(frozen=True)
class PaymentProductPrice:
    amount: int
    currency: str


@dataclass(frozen=True)
class PaymentOrderPayload:
    order_id: str
    nonce: str


@dataclass(frozen=True)
class PaymentOrder:
    order_id: str
    user_id: int
    chat_id: int
    product: str
    provider: str
    amount: int
    currency: str
    nonce: str
    status: str = ORDER_STATUS_PENDING
    created_at: datetime | None = None
    updated_at: datetime | None = None
    paid_at: datetime | None = None
    granted_at: datetime | None = None
    failed_at: datetime | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class PaymentCharge:
    order_id: str | None
    provider: str
    telegram_payment_charge_id: str | None
    provider_payment_charge_id: str | None
    amount: int
    currency: str
    charge_id: int | None = None
    status: str = CHARGE_STATUS_SUCCEEDED
    raw_payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class RecordedPaymentCharge:
    charge: PaymentCharge
    inserted: bool
    reason: str | None = None


@dataclass(frozen=True)
class PaymentEvent:
    event_id: str
    event_type: str
    order_id: str | None = None
    provider: str | None = None
    event_key: str | None = None
    telegram_payment_charge_id: str | None = None
    provider_payment_charge_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class PaymentValidationResult:
    valid: bool
    order: PaymentOrder | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PaymentHandlingResult:
    processed: bool
    grant: str | None = None
    duplicate: bool = False
    reason: str | None = None


PRODUCT_PRICES: dict[str, dict[str, PaymentProductPrice]] = {
    PROVIDER_TELEGRAM_STARS: {
        PRODUCT_SUBSCRIPTION_MONTH: PaymentProductPrice(amount=400, currency="XTR"),
        PRODUCT_EXTRA_ONE_DAY: PaymentProductPrice(amount=35, currency="XTR"),
        PRODUCT_EXTRA_WEEKLY_PDF: PaymentProductPrice(amount=170, currency="XTR"),
    },
    PROVIDER_YOOKASSA: {
        PRODUCT_SUBSCRIPTION_MONTH: PaymentProductPrice(amount=59_900, currency="RUB"),
        PRODUCT_EXTRA_ONE_DAY: PaymentProductPrice(amount=5_000, currency="RUB"),
        PRODUCT_EXTRA_WEEKLY_PDF: PaymentProductPrice(amount=25_000, currency="RUB"),
    },
}


def expected_payment_price(provider: str, product: str) -> PaymentProductPrice:
    try:
        return PRODUCT_PRICES[provider][product]
    except KeyError as exc:
        raise ValueError(f"Unsupported payment provider/product: {provider!r}/{product!r}") from exc


def encode_payment_order_payload(order_id: str, nonce: str) -> str:
    _validate_payload_token(order_id, "order_id")
    _validate_payload_token(nonce, "nonce")
    checksum = _payload_checksum(order_id, nonce)
    payload = f"{ORDER_PAYLOAD_PREFIX}:{order_id}:{nonce}:{checksum}"
    if len(payload) > MAX_TELEGRAM_INVOICE_PAYLOAD_LENGTH:
        raise PaymentPayloadError("Payment order payload is too long for Telegram invoice payload.")
    return payload


def decode_payment_order_payload(payload: str) -> PaymentOrderPayload | None:
    if not payload or not payload.startswith("diet:order:"):
        return None

    parts = payload.split(":")
    if len(parts) != 6 or ":".join(parts[:3]) != ORDER_PAYLOAD_PREFIX:
        raise PaymentPayloadError("Malformed payment order payload.")

    _prefix, _order, _version, order_id, nonce, checksum = parts
    _validate_payload_token(order_id, "order_id")
    _validate_payload_token(nonce, "nonce")
    if not _CHECKSUM_RE.fullmatch(checksum):
        raise PaymentPayloadError("Malformed payment order payload checksum.")
    expected_checksum = _payload_checksum(order_id, nonce)
    if checksum != expected_checksum:
        raise PaymentPayloadError("Payment order payload checksum mismatch.")
    return PaymentOrderPayload(order_id=order_id, nonce=nonce)


def _validate_payload_token(value: str, field_name: str) -> None:
    if not _PAYLOAD_TOKEN_RE.fullmatch(str(value)):
        raise PaymentPayloadError(f"Invalid payment order payload {field_name}.")


def _payload_checksum(order_id: str, nonce: str) -> str:
    digest = hashlib.sha256(f"{ORDER_PAYLOAD_PREFIX}:{order_id}:{nonce}".encode("utf-8")).hexdigest()
    return digest[:16]
