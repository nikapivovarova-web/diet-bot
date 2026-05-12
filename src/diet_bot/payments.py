from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Callable, Protocol


PAYMENT_ORDER_PAYLOAD_PREFIX = "diet:order"
PAYMENT_ORDER_TTL_SECONDS = 15 * 60
TELEGRAM_STARS_SUBSCRIPTION_PERIOD_SECONDS = 30 * 24 * 60 * 60
REDACTED_PAYMENT_VALUE = "[REDACTED]"
TokenFactory = Callable[[], str]


class PaymentPayloadError(ValueError):
    """Raised when an invoice payload is not a current order nonce payload."""


class PaymentProvider(StrEnum):
    TELEGRAM_STARS = "telegram_stars"
    YOOKASSA = "yookassa"


class PaymentProduct(StrEnum):
    SUBSCRIPTION_MONTH = "subscription_month"
    EXTRA_ONE_DAY = "extra_one_day"
    EXTRA_WEEKLY_PDF = "extra_weekly_pdf"


class PaymentCurrency(StrEnum):
    XTR = "XTR"
    RUB = "RUB"


class PaymentOrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    EXPIRED = "expired"
    FAILED_INVOICE_CREATION = "failed_invoice_creation"


class PaymentEventType(StrEnum):
    SUCCESSFUL_PAYMENT = "successful_payment"
    REFUND = "refund"
    CHARGEBACK = "chargeback"
    CANCEL_SUBSCRIPTION = "cancel_subscription"
    UNKNOWN = "unknown"


class PaymentEventStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    PENDING_RECONCILIATION = "pending_reconciliation"
    ORPHAN_RECOVERABLE = "orphan_recoverable"
    IGNORED_NON_TERMINAL = "ignored_non_terminal"


PROVIDER_CURRENCIES: Mapping[PaymentProvider, PaymentCurrency] = {
    PaymentProvider.TELEGRAM_STARS: PaymentCurrency.XTR,
    PaymentProvider.YOOKASSA: PaymentCurrency.RUB,
}

PAYMENT_PRODUCTS = frozenset(product.value for product in PaymentProduct)

LEGACY_STATIC_PAYMENT_PAYLOADS = frozenset(
    {
        PaymentProduct.SUBSCRIPTION_MONTH.value,
        PaymentProduct.EXTRA_ONE_DAY.value,
        PaymentProduct.EXTRA_WEEKLY_PDF.value,
        "diet:stars:subscription_month",
        "diet:stars:extra_one_day",
        "diet:stars:extra_weekly_pdf",
        "diet:rub:subscription_month",
        "diet:rub:extra_one_day",
        "diet:rub:extra_weekly_pdf",
    }
)

_PAYMENT_PRODUCT_INVOICE_CATALOG: Mapping[
    tuple[PaymentProvider, PaymentProduct],
    tuple[PaymentCurrency, int, int | None],
] = {
    (
        PaymentProvider.TELEGRAM_STARS,
        PaymentProduct.SUBSCRIPTION_MONTH,
    ): (
        PaymentCurrency.XTR,
        400,
        TELEGRAM_STARS_SUBSCRIPTION_PERIOD_SECONDS,
    ),
    (PaymentProvider.TELEGRAM_STARS, PaymentProduct.EXTRA_ONE_DAY): (
        PaymentCurrency.XTR,
        35,
        None,
    ),
    (PaymentProvider.TELEGRAM_STARS, PaymentProduct.EXTRA_WEEKLY_PDF): (
        PaymentCurrency.XTR,
        170,
        None,
    ),
    (PaymentProvider.YOOKASSA, PaymentProduct.SUBSCRIPTION_MONTH): (
        PaymentCurrency.RUB,
        59_900,
        None,
    ),
    (PaymentProvider.YOOKASSA, PaymentProduct.EXTRA_ONE_DAY): (
        PaymentCurrency.RUB,
        5_000,
        None,
    ),
    (PaymentProvider.YOOKASSA, PaymentProduct.EXTRA_WEEKLY_PDF): (
        PaymentCurrency.RUB,
        25_000,
        None,
    ),
}

_PAYMENT_PRODUCT_RECEIPT_DESCRIPTIONS: Mapping[PaymentProduct, str] = {
    PaymentProduct.SUBSCRIPTION_MONTH: "FoodBalance monthly access",
    PaymentProduct.EXTRA_ONE_DAY: "FoodBalance one-day ration",
    PaymentProduct.EXTRA_WEEKLY_PDF: "FoodBalance weekly PDF",
}

_PAYLOAD_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<![\w+])\+?\d[\d\s().-]{7,}\d(?!\w)")
_DATABASE_URL_RE = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://[^\s\"'<>]+",
    re.IGNORECASE,
)
_BOT_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
_PROVIDER_TOKEN_RE = re.compile(r"\b\d{6,}:(?:TEST|LIVE):[A-Za-z0-9_.:-]+\b", re.IGNORECASE)
_SENSITIVE_KEY_NAMES = frozenset(
    {
        "email",
        "phone",
        "phonenumber",
        "orderinfo",
        "providertoken",
        "bottoken",
        "databaseurl",
        "dburl",
        "postgresurl",
        "postgresdsn",
        "dsn",
        "receipt",
        "customer",
        "providerdata",
    }
)


@dataclass(frozen=True)
class PaymentProductInvoiceMetadata:
    provider: PaymentProvider | str
    product: PaymentProduct | str
    currency: PaymentCurrency | str
    amount: int
    subscription_period: int | None = None
    need_email: bool = False
    send_email_to_provider: bool = False
    provider_data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", PaymentProvider(self.provider))
        object.__setattr__(self, "product", PaymentProduct(self.product))
        object.__setattr__(self, "currency", PaymentCurrency(self.currency))
        if self.amount <= 0:
            raise ValueError("invoice amount must be positive")


@dataclass(frozen=True)
class PaymentInvoiceMetadata:
    provider: PaymentProvider | str
    product: PaymentProduct | str
    currency: PaymentCurrency | str
    amount: int
    payload: str
    subscription_period: int | None = None
    need_email: bool = False
    send_email_to_provider: bool = False
    provider_data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", PaymentProvider(self.provider))
        object.__setattr__(self, "product", PaymentProduct(self.product))
        object.__setattr__(self, "currency", PaymentCurrency(self.currency))
        if self.amount <= 0:
            raise ValueError("invoice amount must be positive")
        decode_payment_order_payload(self.payload)


@dataclass(frozen=True)
class PaymentOrder:
    order_id: str
    nonce: str
    user_id: int
    delivery_chat_id: int | None
    provider: PaymentProvider | str
    product: PaymentProduct | str
    amount: int
    currency: PaymentCurrency | str
    status: PaymentOrderStatus | str = PaymentOrderStatus.PENDING
    created_at: datetime | None = None
    expires_at: datetime | None = None
    paid_at: datetime | None = None
    updated_at: datetime | None = None
    invoice_link: str | None = None
    pre_checkout_approved_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", PaymentProvider(self.provider))
        object.__setattr__(self, "product", PaymentProduct(self.product))
        object.__setattr__(self, "currency", PaymentCurrency(self.currency))
        object.__setattr__(self, "status", PaymentOrderStatus(self.status))
        if self.amount < 0:
            raise ValueError("payment amount must be non-negative")
        encode_payment_order_payload(self.order_id, self.nonce)

    @property
    def payload(self) -> str:
        return encode_payment_order_payload(self.order_id, self.nonce)


class PaymentOrderRepository(Protocol):
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
    ) -> PaymentOrder | None: ...

    def insert_payment_order(self, order: PaymentOrder) -> PaymentOrder: ...


@dataclass(frozen=True)
class PaymentEvent:
    event_id: str
    event_type: PaymentEventType | str
    provider: PaymentProvider | str
    order_id: str | None
    charge_id: str | None
    telegram_charge_id: str | None = None
    provider_charge_id: str | None = None
    user_id: int | None = None
    delivery_chat_id: int | None = None
    product: PaymentProduct | str | None = None
    amount: int | None = None
    currency: PaymentCurrency | str | None = None
    status: PaymentEventStatus | str = PaymentEventStatus.PROCESSED
    reason: str | None = None
    raw_payload_redacted: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    processed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", PaymentEventType(self.event_type))
        object.__setattr__(self, "provider", PaymentProvider(self.provider))
        object.__setattr__(self, "status", PaymentEventStatus(self.status))
        if self.product is not None:
            object.__setattr__(self, "product", PaymentProduct(self.product))
        if self.currency is not None:
            object.__setattr__(self, "currency", PaymentCurrency(self.currency))
        if self.amount is not None and self.amount < 0:
            raise ValueError("payment event amount must be non-negative")


@dataclass(frozen=True)
class ProcessedProviderCharge:
    provider: PaymentProvider | str
    charge_id: str
    telegram_charge_id: str | None
    provider_charge_id: str | None
    order_id: str | None
    event_type: PaymentEventType | str
    user_id: int | None
    product: PaymentProduct | str | None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", PaymentProvider(self.provider))
        object.__setattr__(self, "event_type", PaymentEventType(self.event_type))
        if self.product is not None:
            object.__setattr__(self, "product", PaymentProduct(self.product))
        if not str(self.charge_id).strip():
            raise ValueError("processed provider charge requires a charge_id")


def encode_payment_order_payload(order_id: str, nonce: str) -> str:
    order_id = _validate_payload_token("order_id", order_id)
    nonce = _validate_payload_token("nonce", nonce)
    return f"{PAYMENT_ORDER_PAYLOAD_PREFIX}:{order_id}:{nonce}"


def build_payment_invoice_payload(order: PaymentOrder) -> str:
    return encode_payment_order_payload(order.order_id, order.nonce)


def validate_payment_invoice_payload(order: PaymentOrder, payload: str) -> tuple[str, str]:
    order_id, nonce = decode_payment_order_payload(payload)
    if order_id != order.order_id or nonce != order.nonce:
        raise PaymentPayloadError("payment payload does not match order nonce")
    return order_id, nonce


def get_payment_product_invoice_metadata(
    provider: PaymentProvider | str,
    product: PaymentProduct | str,
) -> PaymentProductInvoiceMetadata:
    provider_value = PaymentProvider(provider)
    product_value = PaymentProduct(product)
    try:
        currency, amount, subscription_period = _PAYMENT_PRODUCT_INVOICE_CATALOG[
            (provider_value, product_value)
        ]
    except KeyError as exc:
        raise ValueError("unsupported payment provider/product combination") from exc

    return PaymentProductInvoiceMetadata(
        provider=provider_value,
        product=product_value,
        currency=currency,
        amount=amount,
        subscription_period=subscription_period,
        need_email=provider_value == PaymentProvider.YOOKASSA,
        send_email_to_provider=provider_value == PaymentProvider.YOOKASSA,
        provider_data=(
            _build_yookassa_provider_data(product_value, amount)
            if provider_value == PaymentProvider.YOOKASSA
            else None
        ),
    )


def build_payment_invoice_metadata(order: PaymentOrder) -> PaymentInvoiceMetadata:
    product_metadata = get_payment_product_invoice_metadata(order.provider, order.product)
    if order.amount != product_metadata.amount or order.currency != product_metadata.currency:
        raise ValueError("payment order does not match production invoice metadata")

    return PaymentInvoiceMetadata(
        provider=product_metadata.provider,
        product=product_metadata.product,
        currency=product_metadata.currency,
        amount=product_metadata.amount,
        payload=build_payment_invoice_payload(order),
        subscription_period=product_metadata.subscription_period,
        need_email=product_metadata.need_email,
        send_email_to_provider=product_metadata.send_email_to_provider,
        provider_data=product_metadata.provider_data,
    )


def create_or_reuse_pending_payment_order(
    repository: PaymentOrderRepository,
    *,
    user_id: int,
    delivery_chat_id: int | None,
    provider: PaymentProvider | str,
    product: PaymentProduct | str,
    amount: int,
    currency: PaymentCurrency | str,
    now: datetime | None = None,
    ttl_seconds: int = PAYMENT_ORDER_TTL_SECONDS,
    order_id_factory: TokenFactory | None = None,
    nonce_factory: TokenFactory | None = None,
) -> PaymentOrder:
    provider_value = PaymentProvider(provider)
    product_value = PaymentProduct(product)
    currency_value = PaymentCurrency(currency)
    if PROVIDER_CURRENCIES[provider_value] != currency_value:
        raise ValueError("payment provider and currency do not match")
    if amount <= 0:
        raise ValueError("payment order amount must be positive")
    if ttl_seconds <= 0:
        raise ValueError("payment order ttl must be positive")

    current_time = _normalize_datetime(now)
    existing = repository.find_active_pending_payment_order(
        user_id=user_id,
        delivery_chat_id=delivery_chat_id,
        provider=provider_value,
        product=product_value,
        amount=amount,
        currency=currency_value,
        now=current_time,
    )
    if existing is not None:
        return existing

    order = PaymentOrder(
        order_id=(order_id_factory or _default_payment_token)(),
        nonce=(nonce_factory or _default_payment_token)(),
        user_id=user_id,
        delivery_chat_id=delivery_chat_id,
        provider=provider_value,
        product=product_value,
        amount=amount,
        currency=currency_value,
        status=PaymentOrderStatus.PENDING,
        created_at=current_time,
        expires_at=current_time + timedelta(seconds=ttl_seconds),
        updated_at=current_time,
    )
    return repository.insert_payment_order(order)


def is_active_pending_payment_order(order: PaymentOrder, *, now: datetime | None = None) -> bool:
    return (
        order.status == PaymentOrderStatus.PENDING
        and order.expires_at is not None
        and order.expires_at > _normalize_datetime(now)
    )


def decode_payment_order_payload(payload: str) -> tuple[str, str]:
    if not isinstance(payload, str):
        raise PaymentPayloadError("payment payload must be a string")
    payload = payload.strip()
    if payload in LEGACY_STATIC_PAYMENT_PAYLOADS:
        raise PaymentPayloadError("legacy static payment payloads are disabled")
    parts = payload.split(":")
    if len(parts) != 4 or parts[0] != "diet" or parts[1] != "order":
        raise PaymentPayloadError("payment payload must use diet:order:<order_id>:<nonce>")
    return (
        _validate_payload_token("order_id", parts[2]),
        _validate_payload_token("nonce", parts[3]),
    )


def redact_payment_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            redacted[text_key] = (
                REDACTED_PAYMENT_VALUE
                if _is_sensitive_key(text_key)
                else redact_payment_payload(item)
            )
        return redacted
    if isinstance(value, list):
        return [redact_payment_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payment_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_payment_text(value)
    return value


def _validate_payload_token(name: str, value: str) -> str:
    text = str(value).strip()
    if not _PAYLOAD_TOKEN_RE.fullmatch(text):
        raise PaymentPayloadError(
            f"{name} must be 4-128 chars of letters, numbers, underscore, or hyphen"
        )
    return text


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in _SENSITIVE_KEY_NAMES or normalized.endswith("token")


def _redact_payment_text(value: str) -> str:
    redacted = _DATABASE_URL_RE.sub(REDACTED_PAYMENT_VALUE, value)
    redacted = _PROVIDER_TOKEN_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    redacted = _BOT_TOKEN_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    redacted = _EMAIL_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    return _PHONE_RE.sub(REDACTED_PAYMENT_VALUE, redacted)


def _build_yookassa_provider_data(product: PaymentProduct, amount: int) -> dict[str, Any]:
    return {
        "receipt": {
            "items": [
                {
                    "description": _PAYMENT_PRODUCT_RECEIPT_DESCRIPTIONS[product],
                    "quantity": "1.00",
                    "amount": {
                        "value": _format_kopecks_as_rub(amount),
                        "currency": PaymentCurrency.RUB.value,
                    },
                    "vat_code": 1,
                    "payment_mode": "full_payment",
                    "payment_subject": "service",
                },
            ],
        },
    }


def _format_kopecks_as_rub(amount: int) -> str:
    return f"{amount / 100:.2f}"


def _normalize_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _default_payment_token() -> str:
    return secrets.token_urlsafe(18)


__all__ = [
    "LEGACY_STATIC_PAYMENT_PAYLOADS",
    "PAYMENT_ORDER_PAYLOAD_PREFIX",
    "PAYMENT_ORDER_TTL_SECONDS",
    "PAYMENT_PRODUCTS",
    "PROVIDER_CURRENCIES",
    "TELEGRAM_STARS_SUBSCRIPTION_PERIOD_SECONDS",
    "PaymentCurrency",
    "PaymentEvent",
    "PaymentEventStatus",
    "PaymentEventType",
    "PaymentInvoiceMetadata",
    "PaymentOrder",
    "PaymentOrderRepository",
    "PaymentOrderStatus",
    "PaymentPayloadError",
    "PaymentProduct",
    "PaymentProductInvoiceMetadata",
    "PaymentProvider",
    "ProcessedProviderCharge",
    "REDACTED_PAYMENT_VALUE",
    "build_payment_invoice_metadata",
    "build_payment_invoice_payload",
    "create_or_reuse_pending_payment_order",
    "decode_payment_order_payload",
    "encode_payment_order_payload",
    "get_payment_product_invoice_metadata",
    "is_active_pending_payment_order",
    "redact_payment_payload",
    "validate_payment_invoice_payload",
]
