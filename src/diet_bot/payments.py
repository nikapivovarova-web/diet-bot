from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Callable, Protocol

from .subscriptions import (
    Entitlement,
    PaymentApplication,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_subscription_payment,
)


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


class PaymentOrderCreationCode(StrEnum):
    CREATED = "created"
    REUSED = "reused"
    ACTIVE_SUBSCRIPTION_REQUIRED = "active_subscription_required"
    PROMO_NOT_FOUND = "promo_not_found"
    PROMO_NOT_DISCOUNT = "promo_not_discount"
    PROMO_DISABLED = "promo_disabled"
    PROMO_EXPIRED = "promo_expired"
    PROMO_ALREADY_USED = "promo_already_used"
    PROMO_INVALID_DISCOUNT = "promo_invalid_discount"


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


class PaymentPreCheckoutCode(StrEnum):
    APPROVED = "approved"
    INVALID_PAYLOAD = "invalid_payload"
    ORDER_NOT_FOUND = "order_not_found"
    NONCE_MISMATCH = "nonce_mismatch"
    ORDER_NOT_PENDING = "order_not_pending"
    ORDER_EXPIRED = "order_expired"
    USER_MISMATCH = "user_mismatch"
    PROVIDER_MISMATCH = "provider_mismatch"
    PRODUCT_MISMATCH = "product_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    AMOUNT_MISMATCH = "amount_mismatch"
    ACTIVE_SUBSCRIPTION_REQUIRED = "active_subscription_required"


class PaymentSuccessfulPaymentCode(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    INVALID_PAYLOAD = "invalid_payload"
    ORDER_NOT_FOUND = "order_not_found"
    NONCE_MISMATCH = "nonce_mismatch"
    ORDER_NOT_PENDING = "order_not_pending"
    ORDER_EXPIRED = "order_expired"
    USER_MISMATCH = "user_mismatch"
    DELIVERY_CHAT_MISMATCH = "delivery_chat_mismatch"
    PROVIDER_MISMATCH = "provider_mismatch"
    PRODUCT_MISMATCH = "product_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    AMOUNT_MISMATCH = "amount_mismatch"
    ACTIVE_SUBSCRIPTION_REQUIRED = "active_subscription_required"
    CHARGE_ID_MISSING = "charge_id_missing"
    CHARGE_ALIAS_CONFLICT = "charge_alias_conflict"


class PaymentReversalCode(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    CHARGE_ID_MISSING = "charge_id_missing"
    ORIGINAL_PAYMENT_NOT_FOUND = "original_payment_not_found"
    ORIGINAL_ORDER_NOT_FOUND = "original_order_not_found"
    AMOUNT_MISMATCH = "amount_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    EXTRA_ALREADY_CONSUMED = "extra_already_consumed"
    UNSUPPORTED_PRODUCT_FOR_EVENT = "unsupported_product_for_event"


class PaymentReconciliationAction(StrEnum):
    RECONCILE_ORPHAN_SUCCESS = "reconcile_orphan_success"
    RECONCILE_PENDING_REVERSAL = "reconcile_pending_reversal"
    IGNORE_EVENT = "ignore_event"


class PaymentReconciliationCode(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"
    EVENT_NOT_FOUND = "event_not_found"
    EVENT_NOT_RECONCILABLE = "event_not_reconcilable"
    TARGET_REQUIRED = "target_required"
    REASON_REQUIRED = "reason_required"
    ORDER_NOT_FOUND = "order_not_found"
    ORDER_NOT_PENDING = "order_not_pending"
    ORDER_EXPIRED = "order_expired"
    USER_MISMATCH = "user_mismatch"
    DELIVERY_CHAT_MISMATCH = "delivery_chat_mismatch"
    PROVIDER_MISMATCH = "provider_mismatch"
    PRODUCT_MISMATCH = "product_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    AMOUNT_MISMATCH = "amount_mismatch"
    ACTIVE_SUBSCRIPTION_REQUIRED = "active_subscription_required"
    CHARGE_ID_MISSING = "charge_id_missing"
    CHARGE_ALIAS_CONFLICT = "charge_alias_conflict"
    ORIGINAL_PAYMENT_NOT_FOUND = "original_payment_not_found"
    ORIGINAL_ORDER_NOT_FOUND = "original_order_not_found"
    EXTRA_ALREADY_CONSUMED = "extra_already_consumed"
    UNSUPPORTED_PRODUCT_FOR_EVENT = "unsupported_product_for_event"


PROVIDER_CURRENCIES: Mapping[PaymentProvider, PaymentCurrency] = {
    PaymentProvider.TELEGRAM_STARS: PaymentCurrency.XTR,
    PaymentProvider.YOOKASSA: PaymentCurrency.RUB,
}
PAYMENT_PRICING_CONTEXT_METADATA_KEY = "pricing_context"
PAYMENT_TEST_SMOKE_PRICING_CONTEXT = "test_smoke"

PAYMENT_PRODUCTS = frozenset(product.value for product in PaymentProduct)

EXTRA_PAYMENT_PRODUCTS = frozenset(
    {
        PaymentProduct.EXTRA_ONE_DAY,
        PaymentProduct.EXTRA_WEEKLY_PDF,
    }
)

PAYMENT_REVERSAL_EVENT_TYPES = frozenset(
    {
        PaymentEventType.REFUND,
        PaymentEventType.CHARGEBACK,
        PaymentEventType.CANCEL_SUBSCRIPTION,
    }
)

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

_PAYMENT_TEST_SMOKE_INVOICE_AMOUNTS: Mapping[
    tuple[PaymentProvider, PaymentProduct],
    int,
] = {
    (PaymentProvider.TELEGRAM_STARS, PaymentProduct.SUBSCRIPTION_MONTH): 1,
    (PaymentProvider.YOOKASSA, PaymentProduct.SUBSCRIPTION_MONTH): 100,
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
_PAYMENT_CHARGE_LABEL_RE = re.compile(
    r"\b(?:[a-z]+_)*charge_?id\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_SENSITIVE_TEXT_WORD_RE = re.compile(
    r"\b(?:order_info|provider_data|receipt|customer)\b",
    re.IGNORECASE,
)
_SENSITIVE_KEY_NAMES = frozenset(
    {
        "chargeid",
        "email",
        "phone",
        "phonenumber",
        "orderinfo",
        "paymentchargeid",
        "providerchargeid",
        "providerpaymentchargeid",
        "providertoken",
        "bottoken",
        "telegramchargeid",
        "telegrampaymentchargeid",
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
    list_amount: int | None = None
    discount_amount: int = 0
    promo_code_id: int | None = None
    promo_redemption_id: int | None = None
    promo_code_hash: str | None = None
    promo_code_suffix: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", PaymentProvider(self.provider))
        object.__setattr__(self, "product", PaymentProduct(self.product))
        object.__setattr__(self, "currency", PaymentCurrency(self.currency))
        object.__setattr__(self, "status", PaymentOrderStatus(self.status))
        list_amount = self.amount if self.list_amount is None else int(self.list_amount)
        discount_amount = int(self.discount_amount)
        if self.amount <= 0:
            raise ValueError("payment amount must be positive")
        if list_amount <= 0:
            raise ValueError("payment list amount must be positive")
        if discount_amount < 0:
            raise ValueError("payment discount amount must be non-negative")
        if list_amount - discount_amount != self.amount:
            raise ValueError("payment discount metadata must match final amount")
        if discount_amount > 0 and (
            self.promo_code_id is None
            or not str(self.promo_code_hash or "").strip()
            or not str(self.promo_code_suffix or "").strip()
        ):
            raise ValueError("discounted payment orders require promo metadata")
        if self.promo_code_hash is not None:
            object.__setattr__(self, "promo_code_hash", str(self.promo_code_hash).strip() or None)
        if self.promo_code_suffix is not None:
            object.__setattr__(self, "promo_code_suffix", str(self.promo_code_suffix).strip() or None)
        object.__setattr__(self, "list_amount", list_amount)
        object.__setattr__(self, "discount_amount", discount_amount)
        object.__setattr__(self, "metadata", dict(self.metadata))
        encode_payment_order_payload(self.order_id, self.nonce)

    @property
    def payload(self) -> str:
        return encode_payment_order_payload(self.order_id, self.nonce)


@dataclass(frozen=True)
class PaymentOrderCreationResult:
    accepted: bool
    code: PaymentOrderCreationCode | str
    order: PaymentOrder | None = None
    message: str | None = None
    requires_active_subscription: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", PaymentOrderCreationCode(self.code))


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
        promo_code_id: int | None = None,
    ) -> PaymentOrder | None: ...

    def insert_payment_order(self, order: PaymentOrder) -> PaymentOrder: ...


class PaymentPreCheckoutOrderRepository(Protocol):
    def load_payment_order(self, order_id: str) -> PaymentOrder | None: ...


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


@dataclass(frozen=True)
class PaymentPreCheckoutValidation:
    approved: bool
    code: PaymentPreCheckoutCode | str
    order: PaymentOrder | None = None
    message: str | None = None
    requires_active_subscription: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", PaymentPreCheckoutCode(self.code))


@dataclass(frozen=True)
class PaymentSuccessfulPaymentInput:
    payload: str
    provider: PaymentProvider | str
    telegram_charge_id: str
    user_id: int
    delivery_chat_id: int | None
    currency: PaymentCurrency | str
    total_amount: int
    provider_charge_id: str | None = None
    expected_product: PaymentProduct | str | None = None
    raw_payload: Mapping[str, Any] | None = None
    subscription_expiration_timestamp: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", PaymentProvider(self.provider))
        object.__setattr__(self, "currency", PaymentCurrency(self.currency))
        if self.expected_product is not None:
            object.__setattr__(self, "expected_product", PaymentProduct(self.expected_product))
        if self.total_amount < 0:
            raise ValueError("successful payment amount must be non-negative")
        if self.provider_charge_id is not None:
            text_provider_charge_id = str(self.provider_charge_id).strip()
            object.__setattr__(
                self,
                "provider_charge_id",
                text_provider_charge_id or None,
            )
        object.__setattr__(self, "telegram_charge_id", str(self.telegram_charge_id).strip())


@dataclass(frozen=True)
class PaymentSuccessfulPaymentResult:
    processed: bool
    code: PaymentSuccessfulPaymentCode | str
    order: PaymentOrder | None = None
    event: PaymentEvent | None = None
    duplicate: bool = False
    charge_aliases: tuple[str, ...] = ()
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", PaymentSuccessfulPaymentCode(self.code))


@dataclass(frozen=True)
class PaymentReversalInput:
    event_type: PaymentEventType | str
    provider: PaymentProvider | str
    telegram_charge_id: str | None = None
    provider_charge_id: str | None = None
    amount: int | None = None
    currency: PaymentCurrency | str | None = None
    reason: str | None = None
    status: str | None = None
    raw_payload: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        event_type = PaymentEventType(self.event_type)
        if event_type not in PAYMENT_REVERSAL_EVENT_TYPES:
            raise ValueError("payment reversal event type must be refund, chargeback, or cancel_subscription")
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "provider", PaymentProvider(self.provider))
        if self.currency is not None:
            object.__setattr__(self, "currency", PaymentCurrency(self.currency))
        if self.amount is not None and self.amount < 0:
            raise ValueError("payment reversal amount must be non-negative")
        for field_name in ("telegram_charge_id", "provider_charge_id"):
            charge_id = getattr(self, field_name)
            if charge_id is None:
                continue
            text_charge_id = str(charge_id).strip()
            object.__setattr__(self, field_name, text_charge_id or None)


@dataclass(frozen=True)
class PaymentReversalResult:
    processed: bool
    code: PaymentReversalCode | str
    order: PaymentOrder | None = None
    event: PaymentEvent | None = None
    duplicate: bool = False
    charge_aliases: tuple[str, ...] = ()
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", PaymentReversalCode(self.code))


@dataclass(frozen=True)
class PaymentReconciliationInput:
    action: PaymentReconciliationAction | str
    target_event_id: str | None = None
    target_order_id: str | None = None
    target_charge_id: str | None = None
    provider: PaymentProvider | str | None = None
    admin_actor: Mapping[str, Any] | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", PaymentReconciliationAction(self.action))
        if self.provider is not None:
            object.__setattr__(self, "provider", PaymentProvider(self.provider))
        for field_name in ("target_event_id", "target_order_id", "target_charge_id", "reason"):
            value = getattr(self, field_name)
            if value is None:
                continue
            text = str(value).strip()
            object.__setattr__(self, field_name, text or None)
        if self.admin_actor is not None:
            object.__setattr__(self, "admin_actor", dict(self.admin_actor))


@dataclass(frozen=True)
class PaymentReconciliationResult:
    processed: bool
    code: PaymentReconciliationCode | str
    action: PaymentReconciliationAction | str
    target_event: PaymentEvent | None = None
    order: PaymentOrder | None = None
    audit_event: PaymentEvent | None = None
    successful_payment_result: PaymentSuccessfulPaymentResult | None = None
    reversal_result: PaymentReversalResult | None = None
    duplicate: bool = False
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", PaymentReconciliationCode(self.code))
        object.__setattr__(self, "action", PaymentReconciliationAction(self.action))


class PaymentSuccessfulPaymentRepository(Protocol):
    def load_payment_order(self, order_id: str) -> PaymentOrder | None: ...
    def get_entitlement(self, user_id: int) -> Entitlement: ...
    def save_entitlement(self, user_id: int, entitlement: Entitlement) -> None: ...
    def insert_payment_event(self, event: PaymentEvent) -> PaymentEvent: ...

    def find_processed_provider_charge(
        self,
        *,
        provider: PaymentProvider,
        charge_id: str,
        event_type: PaymentEventType,
    ) -> ProcessedProviderCharge | None: ...

    def insert_processed_provider_charge(
        self,
        charge: ProcessedProviderCharge,
    ) -> ProcessedProviderCharge: ...

    def mark_payment_order_paid(
        self,
        order_id: str,
        paid_at: datetime,
    ) -> PaymentOrder | None: ...


class PaymentReversalRepository(Protocol):
    def load_payment_order(self, order_id: str) -> PaymentOrder | None: ...
    def get_entitlement(self, user_id: int) -> Entitlement: ...
    def save_entitlement(self, user_id: int, entitlement: Entitlement) -> None: ...
    def insert_payment_event(self, event: PaymentEvent) -> PaymentEvent: ...

    def find_processed_provider_charge(
        self,
        *,
        provider: PaymentProvider,
        charge_id: str,
        event_type: PaymentEventType,
    ) -> ProcessedProviderCharge | None: ...

    def insert_processed_provider_charge(
        self,
        charge: ProcessedProviderCharge,
    ) -> ProcessedProviderCharge: ...


class PaymentReconciliationRepository(PaymentSuccessfulPaymentRepository, PaymentReversalRepository, Protocol):
    def load_payment_event(self, event_id: str) -> PaymentEvent | None: ...
    def update_payment_event(self, event: PaymentEvent) -> PaymentEvent: ...

    def find_payment_event(
        self,
        *,
        provider: PaymentProvider,
        charge_id: str,
        event_type: PaymentEventType | None = None,
        statuses: tuple[PaymentEventStatus, ...] = (),
    ) -> PaymentEvent | None: ...


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


def validate_payment_pre_checkout(
    repository: PaymentPreCheckoutOrderRepository,
    *,
    payload: str,
    user_id: int,
    currency: PaymentCurrency | str,
    total_amount: int,
    expected_provider: PaymentProvider | str | None = None,
    expected_product: PaymentProduct | str | None = None,
    has_active_subscription: bool | None = None,
    now: datetime | None = None,
) -> PaymentPreCheckoutValidation:
    current_time = _normalize_datetime(now)
    try:
        order_id, nonce = decode_payment_order_payload(payload)
    except PaymentPayloadError:
        return _pre_checkout_rejection(
            PaymentPreCheckoutCode.INVALID_PAYLOAD,
            message="Payment could not be verified. Please create a new invoice.",
        )

    order = repository.load_payment_order(order_id)
    if order is None:
        return _pre_checkout_rejection(
            PaymentPreCheckoutCode.ORDER_NOT_FOUND,
            message="Payment could not be verified. Please create a new invoice.",
        )
    if order.nonce != nonce:
        return _pre_checkout_rejection(
            PaymentPreCheckoutCode.NONCE_MISMATCH,
            order=order,
            message="Payment could not be verified. Please create a new invoice.",
        )
    if order.status != PaymentOrderStatus.PENDING:
        return _pre_checkout_rejection(
            PaymentPreCheckoutCode.ORDER_NOT_PENDING,
            order=order,
            message="Payment is no longer pending. Please create a new invoice.",
        )
    if order.expires_at is None or _normalize_datetime(order.expires_at) <= current_time:
        _mark_pre_checkout_order_expired(repository, order.order_id)
        refreshed_order = repository.load_payment_order(order.order_id) or order
        return _pre_checkout_rejection(
            PaymentPreCheckoutCode.ORDER_EXPIRED,
            order=refreshed_order,
            message="Payment invoice expired. Please create a new invoice.",
        )
    if order.user_id != user_id:
        return _pre_checkout_rejection(
            PaymentPreCheckoutCode.USER_MISMATCH,
            order=order,
            message="Payment could not be verified. Please create a new invoice.",
        )

    if expected_provider is not None:
        try:
            expected_provider_value = PaymentProvider(expected_provider)
        except ValueError:
            expected_provider_value = None
        if expected_provider_value != order.provider:
            return _pre_checkout_rejection(
                PaymentPreCheckoutCode.PROVIDER_MISMATCH,
                order=order,
                message="Payment could not be verified. Please create a new invoice.",
            )

    if expected_product is not None:
        try:
            expected_product_value = PaymentProduct(expected_product)
        except ValueError:
            expected_product_value = None
        if expected_product_value != order.product:
            return _pre_checkout_rejection(
                PaymentPreCheckoutCode.PRODUCT_MISMATCH,
                order=order,
                message="Payment could not be verified. Please create a new invoice.",
            )

    try:
        currency_value = PaymentCurrency(currency)
    except ValueError:
        currency_value = None
    if currency_value != order.currency:
        return _pre_checkout_rejection(
            PaymentPreCheckoutCode.CURRENCY_MISMATCH,
            order=order,
            message="Payment currency changed. Please create a new invoice.",
        )
    if total_amount != order.amount:
        return _pre_checkout_rejection(
            PaymentPreCheckoutCode.AMOUNT_MISMATCH,
            order=order,
            message="Payment amount changed. Please create a new invoice.",
        )

    requires_active_subscription = order.product in EXTRA_PAYMENT_PRODUCTS
    active_subscription = _repository_has_active_subscription(
        repository,
        user_id=order.user_id,
        now=current_time,
        provided=has_active_subscription,
    )
    if requires_active_subscription and not active_subscription:
        return _pre_checkout_rejection(
            PaymentPreCheckoutCode.ACTIVE_SUBSCRIPTION_REQUIRED,
            order=order,
            message="Active subscription is required for this extra.",
            requires_active_subscription=True,
        )

    approved_order = _record_pre_checkout_approval(repository, order, current_time)
    return PaymentPreCheckoutValidation(
        approved=True,
        code=PaymentPreCheckoutCode.APPROVED,
        order=approved_order,
        requires_active_subscription=requires_active_subscription,
    )


def apply_successful_payment(
    repository: PaymentSuccessfulPaymentRepository,
    successful_payment: PaymentSuccessfulPaymentInput,
    *,
    now: datetime | None = None,
) -> PaymentSuccessfulPaymentResult:
    current_time = _normalize_datetime(now)
    try:
        order_id, nonce = decode_payment_order_payload(successful_payment.payload)
    except PaymentPayloadError:
        event = build_successful_payment_event(
            successful_payment,
            code=PaymentSuccessfulPaymentCode.INVALID_PAYLOAD,
            event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            reason=PaymentSuccessfulPaymentCode.INVALID_PAYLOAD.value,
            now=current_time,
        )
        _insert_payment_event_if_supported(repository, event)
        return PaymentSuccessfulPaymentResult(
            processed=False,
            code=PaymentSuccessfulPaymentCode.INVALID_PAYLOAD,
            event=event,
            message="Payment payload could not be verified.",
        )

    transactional_applier = getattr(repository, "apply_successful_payment_transaction", None)
    if callable(transactional_applier):
        return transactional_applier(
            successful_payment,
            order_id=order_id,
            nonce=nonce,
            now=current_time,
        )

    return _apply_successful_payment_generic(
        repository,
        successful_payment,
        order_id=order_id,
        nonce=nonce,
        now=current_time,
    )


def validate_successful_payment_order(
    successful_payment: PaymentSuccessfulPaymentInput,
    order: PaymentOrder,
    *,
    nonce: str,
    now: datetime,
    existing_processed_charges: Mapping[str, ProcessedProviderCharge] | None = None,
    has_active_subscription: bool | None = None,
) -> PaymentSuccessfulPaymentCode:
    charge_aliases = successful_payment_charge_aliases(successful_payment)
    if not charge_aliases:
        return PaymentSuccessfulPaymentCode.CHARGE_ID_MISSING
    if order.nonce != nonce:
        return PaymentSuccessfulPaymentCode.NONCE_MISMATCH
    if order.status not in {PaymentOrderStatus.PENDING, PaymentOrderStatus.PAID}:
        return PaymentSuccessfulPaymentCode.ORDER_NOT_PENDING
    if order.user_id != successful_payment.user_id:
        return PaymentSuccessfulPaymentCode.USER_MISMATCH
    if order.delivery_chat_id != successful_payment.delivery_chat_id:
        return PaymentSuccessfulPaymentCode.DELIVERY_CHAT_MISMATCH
    if order.provider != successful_payment.provider:
        return PaymentSuccessfulPaymentCode.PROVIDER_MISMATCH
    if (
        successful_payment.expected_product is not None
        and order.product != successful_payment.expected_product
    ):
        return PaymentSuccessfulPaymentCode.PRODUCT_MISMATCH
    if order.currency != successful_payment.currency:
        return PaymentSuccessfulPaymentCode.CURRENCY_MISMATCH
    if order.amount != successful_payment.total_amount:
        return PaymentSuccessfulPaymentCode.AMOUNT_MISMATCH

    catalog_code = _validate_order_against_invoice_catalog(order)
    if catalog_code is not None:
        return catalog_code

    existing = existing_processed_charges or {}
    matching_alias = _matching_processed_charge(order, existing.values())
    if _conflicting_processed_charge(order, existing.values()) is not None:
        return PaymentSuccessfulPaymentCode.CHARGE_ALIAS_CONFLICT
    if order.status == PaymentOrderStatus.PAID:
        return (
            PaymentSuccessfulPaymentCode.DUPLICATE
            if matching_alias is not None
            else PaymentSuccessfulPaymentCode.ORDER_NOT_PENDING
        )
    if matching_alias is not None:
        return PaymentSuccessfulPaymentCode.DUPLICATE

    if _successful_payment_order_is_expired_without_approval(order, now):
        return PaymentSuccessfulPaymentCode.ORDER_EXPIRED
    if (
        order.product in EXTRA_PAYMENT_PRODUCTS
        and has_active_subscription is not True
    ):
        return PaymentSuccessfulPaymentCode.ACTIVE_SUBSCRIPTION_REQUIRED
    return PaymentSuccessfulPaymentCode.PROCESSED


def successful_payment_charge_aliases(
    successful_payment: PaymentSuccessfulPaymentInput,
) -> tuple[str, ...]:
    aliases: list[str] = []
    for charge_id in (
        successful_payment.telegram_charge_id,
        successful_payment.provider_charge_id,
    ):
        text = str(charge_id or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    return tuple(aliases)


def successful_payment_canonical_charge_id(
    successful_payment: PaymentSuccessfulPaymentInput,
) -> str | None:
    aliases = successful_payment_charge_aliases(successful_payment)
    return aliases[0] if aliases else None


def build_successful_payment_event(
    successful_payment: PaymentSuccessfulPaymentInput,
    *,
    code: PaymentSuccessfulPaymentCode,
    event_status: PaymentEventStatus,
    now: datetime,
    order: PaymentOrder | None = None,
    order_id: str | None = None,
    reason: str | None = None,
) -> PaymentEvent:
    return PaymentEvent(
        event_id=_payment_event_id(),
        event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
        provider=successful_payment.provider,
        order_id=order.order_id if order is not None else order_id,
        charge_id=successful_payment_canonical_charge_id(successful_payment),
        telegram_charge_id=successful_payment.telegram_charge_id or None,
        provider_charge_id=successful_payment.provider_charge_id,
        user_id=successful_payment.user_id,
        delivery_chat_id=successful_payment.delivery_chat_id,
        product=order.product if order is not None else None,
        amount=successful_payment.total_amount,
        currency=successful_payment.currency,
        status=event_status,
        reason=reason,
        raw_payload_redacted=_successful_payment_redacted_payload(
            successful_payment,
            code=code,
            order_id=order.order_id if order is not None else order_id,
        ),
        created_at=now,
        processed_at=now if event_status in {
            PaymentEventStatus.PROCESSED,
            PaymentEventStatus.DUPLICATE,
        } else None,
    )


def apply_successful_payment_entitlement(
    entitlement: Entitlement,
    order: PaymentOrder,
    successful_payment: PaymentSuccessfulPaymentInput,
    *,
    charge_id: str,
    now: datetime,
) -> PaymentApplication:
    if order.product == PaymentProduct.SUBSCRIPTION_MONTH:
        return apply_subscription_payment(
            entitlement,
            charge_id,
            now=now,
            subscription_expiration_timestamp=(
                successful_payment.subscription_expiration_timestamp
            ),
        )
    if order.product == PaymentProduct.EXTRA_ONE_DAY:
        return apply_extra_one_day_payment(entitlement, charge_id)
    if order.product == PaymentProduct.EXTRA_WEEKLY_PDF:
        return apply_extra_weekly_pdf_payment(entitlement, charge_id)
    raise ValueError("unsupported successful payment product")


def apply_payment_reversal(
    repository: PaymentReversalRepository,
    reversal: PaymentReversalInput,
    *,
    now: datetime | None = None,
) -> PaymentReversalResult:
    current_time = _normalize_datetime(now)
    charge_aliases = payment_reversal_charge_aliases(reversal)
    if not charge_aliases:
        event = build_payment_reversal_event(
            reversal,
            code=PaymentReversalCode.CHARGE_ID_MISSING,
            event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            reason=PaymentReversalCode.CHARGE_ID_MISSING.value,
            now=current_time,
        )
        _insert_payment_event_if_supported(repository, event)
        return PaymentReversalResult(
            processed=False,
            code=PaymentReversalCode.CHARGE_ID_MISSING,
            event=event,
            message="Payment reversal charge id is missing.",
        )

    transactional_applier = getattr(repository, "apply_payment_reversal_transaction", None)
    if callable(transactional_applier):
        return transactional_applier(
            reversal,
            charge_aliases=charge_aliases,
            now=current_time,
        )

    return _apply_payment_reversal_generic(
        repository,
        reversal,
        charge_aliases=charge_aliases,
        now=current_time,
    )


def payment_reversal_charge_aliases(reversal: PaymentReversalInput) -> tuple[str, ...]:
    aliases: list[str] = []
    for charge_id in (reversal.telegram_charge_id, reversal.provider_charge_id):
        text = str(charge_id or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    return tuple(aliases)


def payment_reversal_canonical_charge_id(reversal: PaymentReversalInput) -> str | None:
    aliases = payment_reversal_charge_aliases(reversal)
    return aliases[0] if aliases else None


def build_payment_reversal_event(
    reversal: PaymentReversalInput,
    *,
    code: PaymentReversalCode,
    event_status: PaymentEventStatus,
    now: datetime,
    order: PaymentOrder | None = None,
    order_id: str | None = None,
    original_charge: ProcessedProviderCharge | None = None,
    reason: str | None = None,
) -> PaymentEvent:
    event_order_id = order.order_id if order is not None else order_id
    if event_order_id is None and original_charge is not None:
        event_order_id = original_charge.order_id
    event_product = order.product if order is not None else None
    if event_product is None and original_charge is not None:
        event_product = original_charge.product
    event_user_id = order.user_id if order is not None else None
    if event_user_id is None and original_charge is not None:
        event_user_id = original_charge.user_id
    return PaymentEvent(
        event_id=_payment_event_id(),
        event_type=reversal.event_type,
        provider=reversal.provider,
        order_id=event_order_id,
        charge_id=payment_reversal_canonical_charge_id(reversal),
        telegram_charge_id=reversal.telegram_charge_id,
        provider_charge_id=reversal.provider_charge_id,
        user_id=event_user_id,
        delivery_chat_id=order.delivery_chat_id if order is not None else None,
        product=event_product,
        amount=reversal.amount if reversal.amount is not None else (
            order.amount if order is not None else None
        ),
        currency=reversal.currency if reversal.currency is not None else (
            order.currency if order is not None else None
        ),
        status=event_status,
        reason=reason,
        raw_payload_redacted=_payment_reversal_redacted_payload(
            reversal,
            code=code,
            order_id=event_order_id,
        ),
        created_at=now,
        processed_at=now if event_status in {
            PaymentEventStatus.PROCESSED,
            PaymentEventStatus.DUPLICATE,
            PaymentEventStatus.IGNORED_NON_TERMINAL,
        } else None,
    )


def apply_payment_reconciliation(
    repository: PaymentReconciliationRepository,
    reconciliation: PaymentReconciliationInput,
    *,
    now: datetime | None = None,
) -> PaymentReconciliationResult:
    current_time = _normalize_datetime(now)
    if reconciliation.action == PaymentReconciliationAction.RECONCILE_ORPHAN_SUCCESS:
        return _reconcile_orphan_success(
            repository,
            reconciliation,
            now=current_time,
        )
    if reconciliation.action == PaymentReconciliationAction.RECONCILE_PENDING_REVERSAL:
        return _reconcile_pending_reversal(
            repository,
            reconciliation,
            now=current_time,
        )
    if reconciliation.action == PaymentReconciliationAction.IGNORE_EVENT:
        return _ignore_reconciliation_event(
            repository,
            reconciliation,
            now=current_time,
        )
    raise ValueError("unsupported payment reconciliation action")


def build_payment_reconciliation_audit_event(
    reconciliation: PaymentReconciliationInput,
    *,
    code: PaymentReconciliationCode,
    event_status: PaymentEventStatus,
    now: datetime,
    target_event: PaymentEvent | None = None,
    order: PaymentOrder | None = None,
    reason: str | None = None,
) -> PaymentEvent:
    provider = (
        target_event.provider
        if target_event is not None
        else PaymentProvider(reconciliation.provider)
    )
    return PaymentEvent(
        event_id=_payment_event_id(),
        event_type=PaymentEventType.UNKNOWN,
        provider=provider,
        order_id=order.order_id if order is not None else (
            target_event.order_id if target_event is not None else reconciliation.target_order_id
        ),
        charge_id=(
            target_event.charge_id
            if target_event is not None
            else reconciliation.target_charge_id
        ),
        telegram_charge_id=target_event.telegram_charge_id if target_event is not None else None,
        provider_charge_id=target_event.provider_charge_id if target_event is not None else None,
        product=order.product if order is not None else (
            target_event.product if target_event is not None else None
        ),
        amount=target_event.amount if target_event is not None else None,
        currency=target_event.currency if target_event is not None else None,
        status=event_status,
        reason=reason,
        raw_payload_redacted=_payment_reconciliation_redacted_payload(
            reconciliation,
            code=code,
            target_event=target_event,
            order=order,
            reason=reason,
        ),
        created_at=now,
        processed_at=now,
    )


def _normalize_payment_pricing_context(pricing_context: str | None) -> str | None:
    if pricing_context is None:
        return None
    normalized = str(pricing_context).strip()
    if not normalized:
        return None
    if normalized == PAYMENT_TEST_SMOKE_PRICING_CONTEXT:
        return normalized
    raise ValueError("unsupported payment pricing context")


def _payment_invoice_amount(
    provider: PaymentProvider,
    product: PaymentProduct,
    production_amount: int,
    *,
    pricing_context: str | None,
) -> int:
    if pricing_context == PAYMENT_TEST_SMOKE_PRICING_CONTEXT:
        return _PAYMENT_TEST_SMOKE_INVOICE_AMOUNTS.get(
            (provider, product),
            production_amount,
        )
    return production_amount


def _payment_order_pricing_context(order: PaymentOrder) -> str | None:
    return _normalize_payment_pricing_context(
        order.metadata.get(PAYMENT_PRICING_CONTEXT_METADATA_KEY),
    )


def get_payment_product_invoice_metadata(
    provider: PaymentProvider | str,
    product: PaymentProduct | str,
    *,
    pricing_context: str | None = None,
) -> PaymentProductInvoiceMetadata:
    provider_value = PaymentProvider(provider)
    product_value = PaymentProduct(product)
    pricing_context_value = _normalize_payment_pricing_context(pricing_context)
    try:
        currency, amount, subscription_period = _PAYMENT_PRODUCT_INVOICE_CATALOG[
            (provider_value, product_value)
        ]
    except KeyError as exc:
        raise ValueError("unsupported payment provider/product combination") from exc
    invoice_amount = _payment_invoice_amount(
        provider_value,
        product_value,
        amount,
        pricing_context=pricing_context_value,
    )

    return PaymentProductInvoiceMetadata(
        provider=provider_value,
        product=product_value,
        currency=currency,
        amount=invoice_amount,
        subscription_period=subscription_period,
        need_email=provider_value == PaymentProvider.YOOKASSA,
        send_email_to_provider=provider_value == PaymentProvider.YOOKASSA,
        provider_data=(
            _build_yookassa_provider_data(product_value, invoice_amount)
            if provider_value == PaymentProvider.YOOKASSA
            else None
        ),
    )


def build_payment_invoice_metadata(order: PaymentOrder) -> PaymentInvoiceMetadata:
    product_metadata = get_payment_product_invoice_metadata(
        order.provider,
        order.product,
        pricing_context=_payment_order_pricing_context(order),
    )
    if (
        order.list_amount != product_metadata.amount
        or order.currency != product_metadata.currency
        or order.discount_amount != order.list_amount - order.amount
    ):
        raise ValueError("payment order does not match production invoice metadata")

    return PaymentInvoiceMetadata(
        provider=product_metadata.provider,
        product=product_metadata.product,
        currency=product_metadata.currency,
        amount=order.amount,
        payload=build_payment_invoice_payload(order),
        subscription_period=product_metadata.subscription_period,
        need_email=product_metadata.need_email,
        send_email_to_provider=product_metadata.send_email_to_provider,
        provider_data=(
            _build_yookassa_provider_data(order.product, order.amount)
            if order.provider == PaymentProvider.YOOKASSA
            else product_metadata.provider_data
        ),
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
    has_active_subscription: bool | None = None,
    promo_code_id: int | None = None,
    promo_redemption_id: int | None = None,
    list_amount: int | None = None,
    discount_amount: int = 0,
    promo_code_hash: str | None = None,
    promo_code_suffix: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    pricing_context: str | None = None,
) -> PaymentOrderCreationResult:
    provider_value = PaymentProvider(provider)
    product_value = PaymentProduct(product)
    currency_value = PaymentCurrency(currency)
    pricing_context_value = _normalize_payment_pricing_context(pricing_context)
    if PROVIDER_CURRENCIES[provider_value] != currency_value:
        raise ValueError("payment provider and currency do not match")
    if amount <= 0:
        raise ValueError("payment order amount must be positive")
    if ttl_seconds <= 0:
        raise ValueError("payment order ttl must be positive")

    current_time = _normalize_datetime(now)
    requires_active_subscription = product_value in EXTRA_PAYMENT_PRODUCTS
    if requires_active_subscription and not _repository_has_active_subscription(
        repository,
        user_id=user_id,
        now=current_time,
        provided=has_active_subscription,
    ):
        return PaymentOrderCreationResult(
            accepted=False,
            code=PaymentOrderCreationCode.ACTIVE_SUBSCRIPTION_REQUIRED,
            message="Active subscription is required for this extra.",
            requires_active_subscription=True,
        )

    existing = repository.find_active_pending_payment_order(
        user_id=user_id,
        delivery_chat_id=delivery_chat_id,
        provider=provider_value,
        product=product_value,
        amount=amount,
        currency=currency_value,
        now=current_time,
        promo_code_id=promo_code_id,
    )
    if existing is not None:
        return PaymentOrderCreationResult(
            accepted=True,
            code=PaymentOrderCreationCode.REUSED,
            order=existing,
            requires_active_subscription=requires_active_subscription,
        )

    order_metadata = dict(metadata or {})
    if pricing_context_value is not None:
        order_metadata[PAYMENT_PRICING_CONTEXT_METADATA_KEY] = pricing_context_value

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
        list_amount=list_amount,
        discount_amount=discount_amount,
        promo_code_id=promo_code_id,
        promo_redemption_id=promo_redemption_id,
        promo_code_hash=promo_code_hash,
        promo_code_suffix=promo_code_suffix,
        metadata=order_metadata,
    )
    return PaymentOrderCreationResult(
        accepted=True,
        code=PaymentOrderCreationCode.CREATED,
        order=repository.insert_payment_order(order),
        requires_active_subscription=requires_active_subscription,
    )


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


def redact_admin_actor_metadata(actor: Mapping[str, Any] | None) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in dict(actor or {}).items():
        text_key = str(key)
        normalized_key = re.sub(r"[^a-z0-9]", "", text_key.lower())
        if _admin_actor_key_requires_hash(normalized_key):
            redacted[f"{text_key}_hash"] = _hash_reconciliation_value(text_key, value)
        else:
            redacted[text_key] = redact_payment_payload(value)
    return redacted


def _reconcile_orphan_success(
    repository: PaymentReconciliationRepository,
    reconciliation: PaymentReconciliationInput,
    *,
    now: datetime,
) -> PaymentReconciliationResult:
    target_event = _load_reconciliation_target_event(
        repository,
        reconciliation,
        event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
        statuses=(
            PaymentEventStatus.ORPHAN_RECOVERABLE,
            PaymentEventStatus.PROCESSED,
        ),
    )
    if target_event is None:
        return PaymentReconciliationResult(
            processed=False,
            code=PaymentReconciliationCode.EVENT_NOT_FOUND,
            action=reconciliation.action,
            message="Payment event was not found.",
        )
    if reconciliation.target_order_id is None:
        audit = _insert_reconciliation_audit_event(
            repository,
            reconciliation,
            code=PaymentReconciliationCode.TARGET_REQUIRED,
            event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            target_event=target_event,
            reason=PaymentReconciliationCode.TARGET_REQUIRED.value,
            now=now,
        )
        return PaymentReconciliationResult(
            processed=False,
            code=PaymentReconciliationCode.TARGET_REQUIRED,
            action=reconciliation.action,
            target_event=target_event,
            audit_event=audit,
            message="A target payment order is required.",
        )

    order = repository.load_payment_order(reconciliation.target_order_id)
    if order is None:
        audit = _insert_reconciliation_audit_event(
            repository,
            reconciliation,
            code=PaymentReconciliationCode.ORDER_NOT_FOUND,
            event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            target_event=target_event,
            reason=PaymentReconciliationCode.ORDER_NOT_FOUND.value,
            now=now,
        )
        return PaymentReconciliationResult(
            processed=False,
            code=PaymentReconciliationCode.ORDER_NOT_FOUND,
            action=reconciliation.action,
            target_event=target_event,
            audit_event=audit,
            message="Target payment order was not found.",
        )

    validation_code = _validate_orphan_success_reconciliation(
        target_event,
        order,
        reconciliation,
    )
    if validation_code != PaymentReconciliationCode.PROCESSED:
        audit = _insert_reconciliation_audit_event(
            repository,
            reconciliation,
            code=validation_code,
            event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            target_event=target_event,
            order=order,
            reason=validation_code.value,
            now=now,
        )
        return PaymentReconciliationResult(
            processed=False,
            code=validation_code,
            action=reconciliation.action,
            target_event=target_event,
            order=order,
            audit_event=audit,
            message="Orphan successful payment does not match target order.",
        )

    successful_payment = _successful_payment_input_from_event(target_event, order)
    successful_result = apply_successful_payment(repository, successful_payment, now=now)
    code = _reconciliation_code_from_successful_payment(successful_result.code)
    processed = successful_result.processed
    duplicate = successful_result.duplicate
    event_status = (
        PaymentEventStatus.PROCESSED
        if processed
        else PaymentEventStatus.DUPLICATE if duplicate else PaymentEventStatus.IGNORED_NON_TERMINAL
    )
    reason = (
        _safe_reconciliation_reason(reconciliation.reason)
        if processed
        else None if duplicate else code.value
    )
    updated_target = target_event
    if processed or duplicate:
        updated_target = _update_payment_event_if_supported(
            repository,
            _reconciled_payment_event(
                target_event,
                order=successful_result.order or order,
                status=PaymentEventStatus.PROCESSED,
                reason=reason or "reconciled_orphan_success",
                processed_at=now,
            ),
        )
    audit = _insert_reconciliation_audit_event(
        repository,
        reconciliation,
        code=code,
        event_status=event_status,
        target_event=updated_target,
        order=successful_result.order or order,
        reason=reason,
        now=now,
    )
    return PaymentReconciliationResult(
        processed=processed,
        code=code,
        action=reconciliation.action,
        target_event=updated_target,
        order=successful_result.order or order,
        audit_event=audit,
        successful_payment_result=successful_result,
        duplicate=duplicate,
        message=successful_result.message,
    )


def _reconcile_pending_reversal(
    repository: PaymentReconciliationRepository,
    reconciliation: PaymentReconciliationInput,
    *,
    now: datetime,
) -> PaymentReconciliationResult:
    target_event = _load_reconciliation_target_event(
        repository,
        reconciliation,
        statuses=(
            PaymentEventStatus.PENDING_RECONCILIATION,
            PaymentEventStatus.PROCESSED,
        ),
    )
    if target_event is None:
        return PaymentReconciliationResult(
            processed=False,
            code=PaymentReconciliationCode.EVENT_NOT_FOUND,
            action=reconciliation.action,
            message="Payment event was not found.",
        )
    if target_event.event_type not in PAYMENT_REVERSAL_EVENT_TYPES:
        audit = _insert_reconciliation_audit_event(
            repository,
            reconciliation,
            code=PaymentReconciliationCode.EVENT_NOT_RECONCILABLE,
            event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            target_event=target_event,
            reason=PaymentReconciliationCode.EVENT_NOT_RECONCILABLE.value,
            now=now,
        )
        return PaymentReconciliationResult(
            processed=False,
            code=PaymentReconciliationCode.EVENT_NOT_RECONCILABLE,
            action=reconciliation.action,
            target_event=target_event,
            audit_event=audit,
            message="Payment event is not a pending reversal.",
        )

    reversal = _payment_reversal_input_from_event(target_event)
    if reversal is None:
        audit = _insert_reconciliation_audit_event(
            repository,
            reconciliation,
            code=PaymentReconciliationCode.CHARGE_ID_MISSING,
            event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            target_event=target_event,
            reason=PaymentReconciliationCode.CHARGE_ID_MISSING.value,
            now=now,
        )
        return PaymentReconciliationResult(
            processed=False,
            code=PaymentReconciliationCode.CHARGE_ID_MISSING,
            action=reconciliation.action,
            target_event=target_event,
            audit_event=audit,
            message="Pending reversal charge id is missing.",
        )

    reversal_result = apply_payment_reversal(repository, reversal, now=now)
    code = _reconciliation_code_from_reversal(reversal_result.code)
    processed = reversal_result.processed
    duplicate = reversal_result.duplicate
    event_status = (
        PaymentEventStatus.PROCESSED
        if processed
        else PaymentEventStatus.DUPLICATE if duplicate else PaymentEventStatus.IGNORED_NON_TERMINAL
    )
    reason = (
        _safe_reconciliation_reason(reconciliation.reason)
        if processed
        else None if duplicate else code.value
    )
    updated_target = target_event
    if processed or duplicate:
        source_event = reversal_result.event
        updated_target = _update_payment_event_if_supported(
            repository,
            replace(
                target_event,
                order_id=(
                    reversal_result.order.order_id
                    if reversal_result.order is not None
                    else source_event.order_id if source_event is not None else target_event.order_id
                ),
                user_id=(
                    reversal_result.order.user_id
                    if reversal_result.order is not None
                    else source_event.user_id if source_event is not None else target_event.user_id
                ),
                delivery_chat_id=(
                    reversal_result.order.delivery_chat_id
                    if reversal_result.order is not None
                    else (
                        source_event.delivery_chat_id
                        if source_event is not None
                        else target_event.delivery_chat_id
                    )
                ),
                product=(
                    reversal_result.order.product
                    if reversal_result.order is not None
                    else source_event.product if source_event is not None else target_event.product
                ),
                status=PaymentEventStatus.PROCESSED,
                reason=reason or "reconciled_pending_reversal",
                processed_at=now,
            ),
        )
    audit = _insert_reconciliation_audit_event(
        repository,
        reconciliation,
        code=code,
        event_status=event_status,
        target_event=updated_target,
        order=reversal_result.order,
        reason=reason,
        now=now,
    )
    return PaymentReconciliationResult(
        processed=processed,
        code=code,
        action=reconciliation.action,
        target_event=updated_target,
        order=reversal_result.order,
        audit_event=audit,
        reversal_result=reversal_result,
        duplicate=duplicate,
        message=reversal_result.message,
    )


def _ignore_reconciliation_event(
    repository: PaymentReconciliationRepository,
    reconciliation: PaymentReconciliationInput,
    *,
    now: datetime,
) -> PaymentReconciliationResult:
    target_event = _load_reconciliation_target_event(repository, reconciliation)
    if target_event is None:
        return PaymentReconciliationResult(
            processed=False,
            code=PaymentReconciliationCode.EVENT_NOT_FOUND,
            action=reconciliation.action,
            message="Payment event was not found.",
        )
    reason = _safe_reconciliation_reason(reconciliation.reason)
    if reason is None:
        audit = _insert_reconciliation_audit_event(
            repository,
            reconciliation,
            code=PaymentReconciliationCode.REASON_REQUIRED,
            event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            target_event=target_event,
            reason=PaymentReconciliationCode.REASON_REQUIRED.value,
            now=now,
        )
        return PaymentReconciliationResult(
            processed=False,
            code=PaymentReconciliationCode.REASON_REQUIRED,
            action=reconciliation.action,
            target_event=target_event,
            audit_event=audit,
            message="Ignoring a payment event requires a reason.",
        )
    if target_event.status == PaymentEventStatus.IGNORED_NON_TERMINAL:
        audit = _insert_reconciliation_audit_event(
            repository,
            reconciliation,
            code=PaymentReconciliationCode.DUPLICATE,
            event_status=PaymentEventStatus.DUPLICATE,
            target_event=target_event,
            reason=reason,
            now=now,
        )
        return PaymentReconciliationResult(
            processed=False,
            code=PaymentReconciliationCode.DUPLICATE,
            action=reconciliation.action,
            target_event=target_event,
            audit_event=audit,
            duplicate=True,
        )

    ignored = _update_payment_event_if_supported(
        repository,
        replace(
            target_event,
            status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            reason=reason,
            processed_at=now,
        ),
    )
    audit = _insert_reconciliation_audit_event(
        repository,
        reconciliation,
        code=PaymentReconciliationCode.IGNORED,
        event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
        target_event=ignored,
        reason=reason,
        now=now,
    )
    return PaymentReconciliationResult(
        processed=True,
        code=PaymentReconciliationCode.IGNORED,
        action=reconciliation.action,
        target_event=ignored,
        audit_event=audit,
    )


def _load_reconciliation_target_event(
    repository: PaymentReconciliationRepository,
    reconciliation: PaymentReconciliationInput,
    *,
    event_type: PaymentEventType | None = None,
    statuses: tuple[PaymentEventStatus, ...] = (),
) -> PaymentEvent | None:
    if reconciliation.target_event_id:
        return repository.load_payment_event(reconciliation.target_event_id)
    if reconciliation.target_charge_id and reconciliation.provider is not None:
        finder = getattr(repository, "find_payment_event", None)
        if callable(finder):
            return finder(
                provider=reconciliation.provider,
                charge_id=reconciliation.target_charge_id,
                event_type=event_type,
                statuses=statuses,
            )
    return None


def _validate_orphan_success_reconciliation(
    event: PaymentEvent,
    order: PaymentOrder,
    reconciliation: PaymentReconciliationInput,
) -> PaymentReconciliationCode:
    if event.event_type != PaymentEventType.SUCCESSFUL_PAYMENT:
        return PaymentReconciliationCode.EVENT_NOT_RECONCILABLE
    if event.status not in {
        PaymentEventStatus.ORPHAN_RECOVERABLE,
        PaymentEventStatus.PROCESSED,
    }:
        return PaymentReconciliationCode.EVENT_NOT_RECONCILABLE
    charge_aliases = _payment_event_charge_aliases(event)
    if not charge_aliases:
        return PaymentReconciliationCode.CHARGE_ID_MISSING
    if (
        reconciliation.target_charge_id is not None
        and reconciliation.target_charge_id not in charge_aliases
    ):
        return PaymentReconciliationCode.CHARGE_ID_MISSING
    if order.status not in {PaymentOrderStatus.PENDING, PaymentOrderStatus.PAID}:
        return PaymentReconciliationCode.ORDER_NOT_PENDING
    if event.provider != order.provider:
        return PaymentReconciliationCode.PROVIDER_MISMATCH
    if event.product is not None and event.product != order.product:
        return PaymentReconciliationCode.PRODUCT_MISMATCH
    if event.user_id != order.user_id:
        return PaymentReconciliationCode.USER_MISMATCH
    if event.delivery_chat_id != order.delivery_chat_id:
        return PaymentReconciliationCode.DELIVERY_CHAT_MISMATCH
    if event.currency != order.currency:
        return PaymentReconciliationCode.CURRENCY_MISMATCH
    if event.amount != order.amount:
        return PaymentReconciliationCode.AMOUNT_MISMATCH
    return PaymentReconciliationCode.PROCESSED


def _successful_payment_input_from_event(
    event: PaymentEvent,
    order: PaymentOrder,
) -> PaymentSuccessfulPaymentInput:
    return PaymentSuccessfulPaymentInput(
        payload=order.payload,
        provider=event.provider,
        telegram_charge_id=event.telegram_charge_id or event.charge_id or "",
        provider_charge_id=event.provider_charge_id,
        user_id=event.user_id if event.user_id is not None else order.user_id,
        delivery_chat_id=event.delivery_chat_id,
        currency=event.currency if event.currency is not None else order.currency,
        total_amount=event.amount if event.amount is not None else order.amount,
        expected_product=order.product,
        raw_payload={
            "reconciliation_target_event_id": event.event_id,
            "reconciliation_action": PaymentReconciliationAction.RECONCILE_ORPHAN_SUCCESS.value,
        },
    )


def _payment_reversal_input_from_event(event: PaymentEvent) -> PaymentReversalInput | None:
    if not _payment_event_charge_aliases(event):
        return None
    return PaymentReversalInput(
        event_type=event.event_type,
        provider=event.provider,
        telegram_charge_id=event.telegram_charge_id,
        provider_charge_id=event.provider_charge_id,
        amount=event.amount,
        currency=event.currency,
        reason=event.reason,
        raw_payload={
            "reconciliation_target_event_id": event.event_id,
            "reconciliation_action": PaymentReconciliationAction.RECONCILE_PENDING_REVERSAL.value,
        },
    )


def _reconciled_payment_event(
    event: PaymentEvent,
    *,
    order: PaymentOrder,
    status: PaymentEventStatus,
    reason: str,
    processed_at: datetime,
) -> PaymentEvent:
    return replace(
        event,
        order_id=order.order_id,
        user_id=order.user_id,
        delivery_chat_id=order.delivery_chat_id,
        product=order.product,
        amount=event.amount if event.amount is not None else order.amount,
        currency=event.currency if event.currency is not None else order.currency,
        status=status,
        reason=reason,
        processed_at=processed_at,
    )


def _insert_reconciliation_audit_event(
    repository: PaymentReconciliationRepository,
    reconciliation: PaymentReconciliationInput,
    *,
    code: PaymentReconciliationCode,
    event_status: PaymentEventStatus,
    now: datetime,
    target_event: PaymentEvent | None = None,
    order: PaymentOrder | None = None,
    reason: str | None = None,
) -> PaymentEvent | None:
    if target_event is None and reconciliation.provider is None:
        return None
    event = build_payment_reconciliation_audit_event(
        reconciliation,
        code=code,
        event_status=event_status,
        target_event=target_event,
        order=order,
        reason=reason,
        now=now,
    )
    return repository.insert_payment_event(event)


def _update_payment_event_if_supported(
    repository: PaymentReconciliationRepository,
    event: PaymentEvent,
) -> PaymentEvent:
    updater = getattr(repository, "update_payment_event", None)
    if not callable(updater):
        return event
    updated = updater(event)
    return updated if isinstance(updated, PaymentEvent) else event


def _payment_event_charge_aliases(event: PaymentEvent) -> tuple[str, ...]:
    aliases: list[str] = []
    for charge_id in (event.charge_id, event.telegram_charge_id, event.provider_charge_id):
        text = str(charge_id or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    return tuple(aliases)


def _reconciliation_code_from_successful_payment(
    code: PaymentSuccessfulPaymentCode | str,
) -> PaymentReconciliationCode:
    value = PaymentSuccessfulPaymentCode(code).value
    return _reconciliation_code_from_value(value)


def _reconciliation_code_from_reversal(
    code: PaymentReversalCode | str,
) -> PaymentReconciliationCode:
    value = PaymentReversalCode(code).value
    return _reconciliation_code_from_value(value)


def _reconciliation_code_from_value(value: str) -> PaymentReconciliationCode:
    try:
        return PaymentReconciliationCode(value)
    except ValueError:
        return PaymentReconciliationCode.EVENT_NOT_RECONCILABLE


def _payment_reconciliation_redacted_payload(
    reconciliation: PaymentReconciliationInput,
    *,
    code: PaymentReconciliationCode,
    target_event: PaymentEvent | None,
    order: PaymentOrder | None,
    reason: str | None,
) -> dict[str, Any]:
    charge_id = (
        target_event.charge_id
        if target_event is not None
        else reconciliation.target_charge_id
    )
    return {
        "event_type": "payment_reconciliation",
        "action": reconciliation.action.value,
        "status_code": code.value,
        "target_event_id": target_event.event_id if target_event is not None else (
            reconciliation.target_event_id
        ),
        "target_order_id": order.order_id if order is not None else reconciliation.target_order_id,
        "target_charge_id_hash": (
            _hash_reconciliation_value("charge_id", charge_id)
            if charge_id
            else None
        ),
        "admin_actor": redact_admin_actor_metadata(reconciliation.admin_actor),
        "reason": reason,
    }


def _safe_reconciliation_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    text = str(redact_payment_payload(str(reason).strip())).strip()
    return text or None


def _admin_actor_key_requires_hash(normalized_key: str) -> bool:
    return (
        normalized_key in {"id", "adminid", "userid", "telegramid", "email"}
        or normalized_key.endswith("id")
        or normalized_key.endswith("email")
        or _is_sensitive_key(normalized_key)
    )


def _hash_reconciliation_value(key: str, value: Any) -> str:
    normalized = f"foodbalance:payments:admin:{key}:{value}".encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _apply_successful_payment_generic(
    repository: PaymentSuccessfulPaymentRepository,
    successful_payment: PaymentSuccessfulPaymentInput,
    *,
    order_id: str,
    nonce: str,
    now: datetime,
) -> PaymentSuccessfulPaymentResult:
    order = repository.load_payment_order(order_id)
    charge_aliases = successful_payment_charge_aliases(successful_payment)
    if order is None:
        event = build_successful_payment_event(
            successful_payment,
            code=PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND,
            event_status=PaymentEventStatus.ORPHAN_RECOVERABLE,
            order_id=order_id,
            reason=PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND.value,
            now=now,
        )
        repository.insert_payment_event(event)
        return PaymentSuccessfulPaymentResult(
            processed=False,
            code=PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND,
            event=event,
            charge_aliases=charge_aliases,
            message="Payment order was not found.",
        )

    existing_processed_charges = _load_existing_processed_charges(
        repository,
        successful_payment.provider,
        charge_aliases,
    )
    entitlement = repository.get_entitlement(order.user_id)
    code = validate_successful_payment_order(
        successful_payment,
        order,
        nonce=nonce,
        now=now,
        existing_processed_charges=existing_processed_charges,
        has_active_subscription=entitlement.is_subscription_active(now),
    )
    if code == PaymentSuccessfulPaymentCode.PROCESSED:
        canonical_charge_id = successful_payment_canonical_charge_id(successful_payment)
        if canonical_charge_id is None:
            code = PaymentSuccessfulPaymentCode.CHARGE_ID_MISSING
        else:
            return _process_successful_payment_generic(
                repository,
                successful_payment,
                order,
                entitlement,
                charge_aliases=charge_aliases,
                canonical_charge_id=canonical_charge_id,
                now=now,
            )

    event_status = _event_status_for_successful_payment_code(code)
    event = build_successful_payment_event(
        successful_payment,
        code=code,
        event_status=event_status,
        order=order,
        reason=None if code == PaymentSuccessfulPaymentCode.DUPLICATE else code.value,
        now=now,
    )
    repository.insert_payment_event(event)
    return PaymentSuccessfulPaymentResult(
        processed=False,
        code=code,
        order=order,
        event=event,
        duplicate=code == PaymentSuccessfulPaymentCode.DUPLICATE,
        charge_aliases=charge_aliases,
        message=None if code == PaymentSuccessfulPaymentCode.DUPLICATE else "Payment was rejected.",
    )


def _process_successful_payment_generic(
    repository: PaymentSuccessfulPaymentRepository,
    successful_payment: PaymentSuccessfulPaymentInput,
    order: PaymentOrder,
    entitlement: Entitlement,
    *,
    charge_aliases: tuple[str, ...],
    canonical_charge_id: str,
    now: datetime,
) -> PaymentSuccessfulPaymentResult:
    event = build_successful_payment_event(
        successful_payment,
        code=PaymentSuccessfulPaymentCode.PROCESSED,
        event_status=PaymentEventStatus.PROCESSED,
        order=order,
        now=now,
    )
    repository.insert_payment_event(event)
    for charge_alias in charge_aliases:
        repository.insert_processed_provider_charge(
            ProcessedProviderCharge(
                provider=successful_payment.provider,
                charge_id=charge_alias,
                telegram_charge_id=successful_payment.telegram_charge_id or None,
                provider_charge_id=successful_payment.provider_charge_id,
                order_id=order.order_id,
                event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
                user_id=order.user_id,
                product=order.product,
                created_at=now,
            )
        )
    application = apply_successful_payment_entitlement(
        entitlement,
        order,
        successful_payment,
        charge_id=canonical_charge_id,
        now=now,
    )
    if not application.processed:
        duplicate_event = build_successful_payment_event(
            successful_payment,
            code=PaymentSuccessfulPaymentCode.DUPLICATE,
            event_status=PaymentEventStatus.DUPLICATE,
            order=order,
            now=now,
        )
        repository.insert_payment_event(duplicate_event)
        return PaymentSuccessfulPaymentResult(
            processed=False,
            code=PaymentSuccessfulPaymentCode.DUPLICATE,
            order=order,
            event=duplicate_event,
            duplicate=True,
            charge_aliases=charge_aliases,
        )
    repository.save_entitlement(order.user_id, entitlement)
    paid_order = repository.mark_payment_order_paid(order.order_id, now) or order
    return PaymentSuccessfulPaymentResult(
        processed=True,
        code=PaymentSuccessfulPaymentCode.PROCESSED,
        order=paid_order,
        event=event,
        charge_aliases=charge_aliases,
    )


def _apply_payment_reversal_generic(
    repository: PaymentReversalRepository,
    reversal: PaymentReversalInput,
    *,
    charge_aliases: tuple[str, ...],
    now: datetime,
) -> PaymentReversalResult:
    duplicate_charge = _first_processed_charge(
        _load_processed_charges(
            repository,
            reversal.provider,
            charge_aliases,
            reversal.event_type,
        ).values()
    )
    if duplicate_charge is not None:
        order = (
            repository.load_payment_order(duplicate_charge.order_id)
            if duplicate_charge.order_id is not None
            else None
        )
        event = build_payment_reversal_event(
            reversal,
            code=PaymentReversalCode.DUPLICATE,
            event_status=PaymentEventStatus.DUPLICATE,
            order=order,
            original_charge=duplicate_charge,
            now=now,
        )
        repository.insert_payment_event(event)
        return PaymentReversalResult(
            processed=False,
            code=PaymentReversalCode.DUPLICATE,
            order=order,
            event=event,
            duplicate=True,
            charge_aliases=charge_aliases,
        )

    original_charge = _first_processed_charge(
        _load_processed_charges(
            repository,
            reversal.provider,
            charge_aliases,
            PaymentEventType.SUCCESSFUL_PAYMENT,
        ).values()
    )
    if original_charge is None:
        event = build_payment_reversal_event(
            reversal,
            code=PaymentReversalCode.ORIGINAL_PAYMENT_NOT_FOUND,
            event_status=PaymentEventStatus.PENDING_RECONCILIATION,
            reason=PaymentReversalCode.ORIGINAL_PAYMENT_NOT_FOUND.value,
            now=now,
        )
        repository.insert_payment_event(event)
        return PaymentReversalResult(
            processed=False,
            code=PaymentReversalCode.ORIGINAL_PAYMENT_NOT_FOUND,
            event=event,
            charge_aliases=charge_aliases,
            message="Original successful payment was not found.",
        )

    order = (
        repository.load_payment_order(original_charge.order_id)
        if original_charge.order_id is not None
        else None
    )
    if order is None:
        event = build_payment_reversal_event(
            reversal,
            code=PaymentReversalCode.ORIGINAL_ORDER_NOT_FOUND,
            event_status=PaymentEventStatus.PENDING_RECONCILIATION,
            original_charge=original_charge,
            reason=PaymentReversalCode.ORIGINAL_ORDER_NOT_FOUND.value,
            now=now,
        )
        repository.insert_payment_event(event)
        return PaymentReversalResult(
            processed=False,
            code=PaymentReversalCode.ORIGINAL_ORDER_NOT_FOUND,
            event=event,
            charge_aliases=charge_aliases,
            message="Original payment order was not found.",
        )

    validation_code = _validate_reversal_against_order(reversal, order)
    if validation_code is not None:
        event = build_payment_reversal_event(
            reversal,
            code=validation_code,
            event_status=PaymentEventStatus.IGNORED_NON_TERMINAL,
            order=order,
            original_charge=original_charge,
            reason=validation_code.value,
            now=now,
        )
        repository.insert_payment_event(event)
        return PaymentReversalResult(
            processed=False,
            code=validation_code,
            order=order,
            event=event,
            charge_aliases=charge_aliases,
            message="Payment reversal did not match the original order.",
        )

    entitlement = repository.get_entitlement(order.user_id)
    application = apply_payment_reversal_entitlement(
        entitlement,
        order,
        reversal,
        now=now,
    )
    event_status = (
        PaymentEventStatus.PROCESSED
        if application.processed
        else PaymentEventStatus.IGNORED_NON_TERMINAL
    )
    event = build_payment_reversal_event(
        reversal,
        code=application.code,
        event_status=event_status,
        order=order,
        original_charge=original_charge,
        reason=application.reason,
        now=now,
    )
    repository.insert_payment_event(event)
    _insert_reversal_processed_charges(
        repository,
        reversal,
        order,
        charge_aliases=charge_aliases,
        now=now,
    )
    if application.save_entitlement:
        repository.save_entitlement(order.user_id, entitlement)
    return PaymentReversalResult(
        processed=application.processed,
        code=application.code,
        order=order,
        event=event,
        charge_aliases=charge_aliases,
        message=None if application.processed else application.reason,
    )


@dataclass(frozen=True)
class _PaymentReversalEntitlementApplication:
    processed: bool
    code: PaymentReversalCode
    reason: str | None = None
    save_entitlement: bool = False


def apply_payment_reversal_entitlement(
    entitlement: Entitlement,
    order: PaymentOrder,
    reversal: PaymentReversalInput,
    *,
    now: datetime,
) -> _PaymentReversalEntitlementApplication:
    entitlement.expire_if_needed(now)
    if reversal.event_type == PaymentEventType.CANCEL_SUBSCRIPTION:
        if order.product == PaymentProduct.SUBSCRIPTION_MONTH:
            return _PaymentReversalEntitlementApplication(
                True,
                PaymentReversalCode.PROCESSED,
            )
        return _PaymentReversalEntitlementApplication(
            False,
            PaymentReversalCode.UNSUPPORTED_PRODUCT_FOR_EVENT,
            PaymentReversalCode.UNSUPPORTED_PRODUCT_FOR_EVENT.value,
        )

    if order.product == PaymentProduct.SUBSCRIPTION_MONTH:
        return _apply_subscription_payment_reversal_entitlement(
            entitlement,
            order,
            now=now,
        )
    if order.product == PaymentProduct.EXTRA_ONE_DAY:
        if entitlement.extra_one_day_remaining <= 0:
            return _PaymentReversalEntitlementApplication(
                False,
                PaymentReversalCode.EXTRA_ALREADY_CONSUMED,
                PaymentReversalCode.EXTRA_ALREADY_CONSUMED.value,
            )
        entitlement.extra_one_day_remaining -= 1
        return _PaymentReversalEntitlementApplication(
            True,
            PaymentReversalCode.PROCESSED,
            save_entitlement=True,
        )
    if order.product == PaymentProduct.EXTRA_WEEKLY_PDF:
        if entitlement.extra_weekly_pdf_remaining <= 0:
            return _PaymentReversalEntitlementApplication(
                False,
                PaymentReversalCode.EXTRA_ALREADY_CONSUMED,
                PaymentReversalCode.EXTRA_ALREADY_CONSUMED.value,
            )
        entitlement.extra_weekly_pdf_remaining -= 1
        return _PaymentReversalEntitlementApplication(
            True,
            PaymentReversalCode.PROCESSED,
            save_entitlement=True,
        )
    return _PaymentReversalEntitlementApplication(
        False,
        PaymentReversalCode.UNSUPPORTED_PRODUCT_FOR_EVENT,
        PaymentReversalCode.UNSUPPORTED_PRODUCT_FOR_EVENT.value,
    )


def _apply_subscription_payment_reversal_entitlement(
    entitlement: Entitlement,
    order: PaymentOrder,
    *,
    now: datetime,
) -> _PaymentReversalEntitlementApplication:
    original_period_start = _normalize_datetime(order.paid_at or order.created_at)
    current_period_start = _parse_payment_datetime(entitlement.subscription_period_start)
    if (
        current_period_start is None
        or abs((current_period_start - original_period_start).total_seconds()) > 1
    ):
        return _PaymentReversalEntitlementApplication(
            True,
            PaymentReversalCode.PROCESSED,
            "paid_period_not_current",
        )

    entitlement.subscription_period_end = _format_payment_datetime(now)
    entitlement.monthly_one_day_remaining = 0
    entitlement.monthly_weekly_pdf_remaining = 0
    return _PaymentReversalEntitlementApplication(
        True,
        PaymentReversalCode.PROCESSED,
        save_entitlement=True,
    )


def _load_existing_processed_charges(
    repository: PaymentSuccessfulPaymentRepository,
    provider: PaymentProvider,
    charge_aliases: tuple[str, ...],
) -> dict[str, ProcessedProviderCharge]:
    return _load_processed_charges(
        repository,
        provider,
        charge_aliases,
        PaymentEventType.SUCCESSFUL_PAYMENT,
    )


def _load_processed_charges(
    repository: PaymentSuccessfulPaymentRepository | PaymentReversalRepository,
    provider: PaymentProvider,
    charge_aliases: tuple[str, ...],
    event_type: PaymentEventType,
) -> dict[str, ProcessedProviderCharge]:
    existing: dict[str, ProcessedProviderCharge] = {}
    for charge_alias in charge_aliases:
        processed = repository.find_processed_provider_charge(
            provider=provider,
            charge_id=charge_alias,
            event_type=event_type,
        )
        if processed is not None:
            existing[charge_alias] = processed
    return existing


def _first_processed_charge(
    processed_charges: object,
) -> ProcessedProviderCharge | None:
    for processed in processed_charges:
        if isinstance(processed, ProcessedProviderCharge):
            return processed
    return None


def _validate_reversal_against_order(
    reversal: PaymentReversalInput,
    order: PaymentOrder,
) -> PaymentReversalCode | None:
    return validate_payment_reversal_order(reversal, order)


def validate_payment_reversal_order(
    reversal: PaymentReversalInput,
    order: PaymentOrder,
) -> PaymentReversalCode | None:
    if reversal.amount is not None and reversal.amount != order.amount:
        return PaymentReversalCode.AMOUNT_MISMATCH
    if reversal.currency is not None and reversal.currency != order.currency:
        return PaymentReversalCode.CURRENCY_MISMATCH
    return None


def _insert_reversal_processed_charges(
    repository: PaymentReversalRepository,
    reversal: PaymentReversalInput,
    order: PaymentOrder,
    *,
    charge_aliases: tuple[str, ...],
    now: datetime,
) -> None:
    for charge_alias in charge_aliases:
        repository.insert_processed_provider_charge(
            ProcessedProviderCharge(
                provider=reversal.provider,
                charge_id=charge_alias,
                telegram_charge_id=reversal.telegram_charge_id,
                provider_charge_id=reversal.provider_charge_id,
                order_id=order.order_id,
                event_type=reversal.event_type,
                user_id=order.user_id,
                product=order.product,
                created_at=now,
            )
        )


def _validate_order_against_invoice_catalog(
    order: PaymentOrder,
) -> PaymentSuccessfulPaymentCode | None:
    try:
        metadata = get_payment_product_invoice_metadata(
            order.provider,
            order.product,
            pricing_context=_payment_order_pricing_context(order),
        )
    except ValueError:
        return PaymentSuccessfulPaymentCode.PRODUCT_MISMATCH
    if order.currency != metadata.currency:
        return PaymentSuccessfulPaymentCode.CURRENCY_MISMATCH
    if (
        order.list_amount != metadata.amount
        or order.discount_amount != order.list_amount - order.amount
        or (
            order.discount_amount > 0
            and (
                order.promo_code_id is None
                or not order.promo_code_hash
                or not order.promo_code_suffix
            )
        )
        or order.amount <= 0
    ):
        return PaymentSuccessfulPaymentCode.AMOUNT_MISMATCH
    return None


def _matching_processed_charge(
    order: PaymentOrder,
    processed_charges: object,
) -> ProcessedProviderCharge | None:
    for processed in processed_charges:
        if not isinstance(processed, ProcessedProviderCharge):
            continue
        if (
            processed.order_id == order.order_id
            and processed.event_type == PaymentEventType.SUCCESSFUL_PAYMENT
            and processed.provider == order.provider
        ):
            return processed
    return None


def _conflicting_processed_charge(
    order: PaymentOrder,
    processed_charges: object,
) -> ProcessedProviderCharge | None:
    for processed in processed_charges:
        if not isinstance(processed, ProcessedProviderCharge):
            continue
        if (
            processed.event_type == PaymentEventType.SUCCESSFUL_PAYMENT
            and (
                processed.provider != order.provider
                or processed.order_id != order.order_id
            )
        ):
            return processed
    return None


def _successful_payment_order_is_expired_without_approval(
    order: PaymentOrder,
    now: datetime,
) -> bool:
    if order.expires_at is None:
        return True
    expires_at = _normalize_datetime(order.expires_at)
    if expires_at > _normalize_datetime(now):
        return False
    approved_at = order.pre_checkout_approved_at
    if approved_at is None:
        return True
    return _normalize_datetime(approved_at) > expires_at


def _event_status_for_successful_payment_code(
    code: PaymentSuccessfulPaymentCode,
) -> PaymentEventStatus:
    if code == PaymentSuccessfulPaymentCode.DUPLICATE:
        return PaymentEventStatus.DUPLICATE
    if code == PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND:
        return PaymentEventStatus.ORPHAN_RECOVERABLE
    if code == PaymentSuccessfulPaymentCode.PROCESSED:
        return PaymentEventStatus.PROCESSED
    return PaymentEventStatus.IGNORED_NON_TERMINAL


def _successful_payment_redacted_payload(
    successful_payment: PaymentSuccessfulPaymentInput,
    *,
    code: PaymentSuccessfulPaymentCode,
    order_id: str | None,
) -> dict[str, Any]:
    return {
        "event_type": PaymentEventType.SUCCESSFUL_PAYMENT.value,
        "status_code": code.value,
        "order_id": order_id,
        "invoice_payload": successful_payment.payload,
        "provider": successful_payment.provider.value,
        "currency": successful_payment.currency.value,
        "total_amount": successful_payment.total_amount,
        "has_telegram_charge_id": bool(successful_payment.telegram_charge_id),
        "has_provider_charge_id": bool(successful_payment.provider_charge_id),
        "raw_payload": redact_payment_payload(dict(successful_payment.raw_payload or {})),
    }


def _payment_reversal_redacted_payload(
    reversal: PaymentReversalInput,
    *,
    code: PaymentReversalCode,
    order_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_type": reversal.event_type.value,
        "status_code": code.value,
        "order_id": order_id,
        "provider": reversal.provider.value,
        "amount": reversal.amount,
        "currency": reversal.currency.value if reversal.currency is not None else None,
        "has_telegram_charge_id": bool(reversal.telegram_charge_id),
        "has_provider_charge_id": bool(reversal.provider_charge_id),
        "raw_payload": redact_payment_payload(dict(reversal.raw_payload or {})),
    }
    if reversal.reason is not None:
        payload["reason"] = redact_payment_payload(reversal.reason)
    if reversal.status is not None:
        payload["provider_status"] = redact_payment_payload(reversal.status)
    return payload


def _insert_payment_event_if_supported(
    repository: object,
    event: PaymentEvent,
) -> None:
    inserter = getattr(repository, "insert_payment_event", None)
    if callable(inserter):
        inserter(event)


def _repository_has_active_subscription(
    repository: object,
    *,
    user_id: int,
    now: datetime,
    provided: bool | None,
) -> bool:
    loader = getattr(repository, "get_entitlement", None)
    if callable(loader):
        entitlement = loader(user_id)
        checker = getattr(entitlement, "is_subscription_active", None)
        if callable(checker):
            return bool(checker(now))
    return provided is True


def _validate_payload_token(name: str, value: str) -> str:
    text = str(value).strip()
    if not _PAYLOAD_TOKEN_RE.fullmatch(text):
        raise PaymentPayloadError(
            f"{name} must be 4-128 chars of letters, numbers, underscore, or hyphen"
        )
    return text


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return (
        normalized in _SENSITIVE_KEY_NAMES
        or normalized.endswith("chargeid")
        or normalized.endswith("token")
    )


def _redact_payment_text(value: str) -> str:
    redacted = _DATABASE_URL_RE.sub(REDACTED_PAYMENT_VALUE, value)
    redacted = _PROVIDER_TOKEN_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    redacted = _BOT_TOKEN_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    redacted = _EMAIL_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    redacted = _PHONE_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    redacted = _PAYMENT_CHARGE_LABEL_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    return _SENSITIVE_TEXT_WORD_RE.sub(REDACTED_PAYMENT_VALUE, redacted)


def _pre_checkout_rejection(
    code: PaymentPreCheckoutCode,
    *,
    order: PaymentOrder | None = None,
    message: str | None = None,
    requires_active_subscription: bool = False,
) -> PaymentPreCheckoutValidation:
    return PaymentPreCheckoutValidation(
        approved=False,
        code=code,
        order=order,
        message=message,
        requires_active_subscription=requires_active_subscription,
    )


def _record_pre_checkout_approval(
    repository: PaymentPreCheckoutOrderRepository,
    order: PaymentOrder,
    approved_at: datetime,
) -> PaymentOrder:
    recorder = getattr(repository, "record_payment_order_pre_checkout_approved", None)
    if not callable(recorder):
        return order
    recorded = recorder(order.order_id, approved_at)
    return recorded if isinstance(recorded, PaymentOrder) else order


def _mark_pre_checkout_order_expired(
    repository: PaymentPreCheckoutOrderRepository,
    order_id: str,
) -> None:
    marker = getattr(repository, "mark_payment_order_expired", None)
    if callable(marker):
        marker(order_id)


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


def _format_payment_datetime(value: datetime) -> str:
    return _normalize_datetime(value).isoformat()


def _parse_payment_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _normalize_datetime(datetime.fromisoformat(value))
    except ValueError:
        return None


def _normalize_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _default_payment_token() -> str:
    return secrets.token_urlsafe(18)


def _payment_event_id() -> str:
    return f"evt_{secrets.token_urlsafe(18)}"


__all__ = [
    "LEGACY_STATIC_PAYMENT_PAYLOADS",
    "PAYMENT_ORDER_PAYLOAD_PREFIX",
    "PAYMENT_ORDER_TTL_SECONDS",
    "PAYMENT_PRICING_CONTEXT_METADATA_KEY",
    "PAYMENT_PRODUCTS",
    "PAYMENT_REVERSAL_EVENT_TYPES",
    "PAYMENT_TEST_SMOKE_PRICING_CONTEXT",
    "PROVIDER_CURRENCIES",
    "TELEGRAM_STARS_SUBSCRIPTION_PERIOD_SECONDS",
    "PaymentCurrency",
    "PaymentEvent",
    "PaymentEventStatus",
    "PaymentEventType",
    "PaymentInvoiceMetadata",
    "PaymentOrder",
    "PaymentOrderCreationCode",
    "PaymentOrderCreationResult",
    "PaymentOrderRepository",
    "PaymentOrderStatus",
    "PaymentPayloadError",
    "PaymentPreCheckoutCode",
    "PaymentPreCheckoutOrderRepository",
    "PaymentPreCheckoutValidation",
    "PaymentProduct",
    "PaymentProductInvoiceMetadata",
    "PaymentProvider",
    "PaymentReconciliationAction",
    "PaymentReconciliationCode",
    "PaymentReconciliationInput",
    "PaymentReconciliationRepository",
    "PaymentReconciliationResult",
    "PaymentReversalCode",
    "PaymentReversalInput",
    "PaymentReversalRepository",
    "PaymentReversalResult",
    "PaymentSuccessfulPaymentCode",
    "PaymentSuccessfulPaymentInput",
    "PaymentSuccessfulPaymentRepository",
    "PaymentSuccessfulPaymentResult",
    "ProcessedProviderCharge",
    "REDACTED_PAYMENT_VALUE",
    "apply_payment_reversal",
    "apply_payment_reversal_entitlement",
    "apply_payment_reconciliation",
    "apply_successful_payment",
    "apply_successful_payment_entitlement",
    "build_payment_invoice_metadata",
    "build_payment_invoice_payload",
    "build_payment_reconciliation_audit_event",
    "build_payment_reversal_event",
    "build_successful_payment_event",
    "create_or_reuse_pending_payment_order",
    "decode_payment_order_payload",
    "encode_payment_order_payload",
    "get_payment_product_invoice_metadata",
    "is_active_pending_payment_order",
    "redact_payment_payload",
    "redact_admin_actor_metadata",
    "payment_reversal_canonical_charge_id",
    "payment_reversal_charge_aliases",
    "successful_payment_canonical_charge_id",
    "successful_payment_charge_aliases",
    "validate_successful_payment_order",
    "validate_payment_reversal_order",
    "validate_payment_pre_checkout",
    "validate_payment_invoice_payload",
]
