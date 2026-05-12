from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
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


PROVIDER_CURRENCIES: Mapping[PaymentProvider, PaymentCurrency] = {
    PaymentProvider.TELEGRAM_STARS: PaymentCurrency.XTR,
    PaymentProvider.YOOKASSA: PaymentCurrency.RUB,
}

PAYMENT_PRODUCTS = frozenset(product.value for product in PaymentProduct)

EXTRA_PAYMENT_PRODUCTS = frozenset(
    {
        PaymentProduct.EXTRA_ONE_DAY,
        PaymentProduct.EXTRA_WEEKLY_PDF,
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
    has_active_subscription: bool | None = None,
) -> PaymentOrderCreationResult:
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
    )
    if existing is not None:
        return PaymentOrderCreationResult(
            accepted=True,
            code=PaymentOrderCreationCode.REUSED,
            order=existing,
            requires_active_subscription=requires_active_subscription,
        )

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


def _load_existing_processed_charges(
    repository: PaymentSuccessfulPaymentRepository,
    provider: PaymentProvider,
    charge_aliases: tuple[str, ...],
) -> dict[str, ProcessedProviderCharge]:
    existing: dict[str, ProcessedProviderCharge] = {}
    for charge_alias in charge_aliases:
        processed = repository.find_processed_provider_charge(
            provider=provider,
            charge_id=charge_alias,
            event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
        )
        if processed is not None:
            existing[charge_alias] = processed
    return existing


def _validate_order_against_invoice_catalog(
    order: PaymentOrder,
) -> PaymentSuccessfulPaymentCode | None:
    try:
        metadata = get_payment_product_invoice_metadata(order.provider, order.product)
    except ValueError:
        return PaymentSuccessfulPaymentCode.PRODUCT_MISMATCH
    if order.currency != metadata.currency:
        return PaymentSuccessfulPaymentCode.CURRENCY_MISMATCH
    if order.amount != metadata.amount:
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
    return normalized in _SENSITIVE_KEY_NAMES or normalized.endswith("token")


def _redact_payment_text(value: str) -> str:
    redacted = _DATABASE_URL_RE.sub(REDACTED_PAYMENT_VALUE, value)
    redacted = _PROVIDER_TOKEN_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    redacted = _BOT_TOKEN_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    redacted = _EMAIL_RE.sub(REDACTED_PAYMENT_VALUE, redacted)
    return _PHONE_RE.sub(REDACTED_PAYMENT_VALUE, redacted)


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
    "PAYMENT_PRODUCTS",
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
    "PaymentSuccessfulPaymentCode",
    "PaymentSuccessfulPaymentInput",
    "PaymentSuccessfulPaymentRepository",
    "PaymentSuccessfulPaymentResult",
    "ProcessedProviderCharge",
    "REDACTED_PAYMENT_VALUE",
    "apply_successful_payment",
    "apply_successful_payment_entitlement",
    "build_payment_invoice_metadata",
    "build_payment_invoice_payload",
    "build_successful_payment_event",
    "create_or_reuse_pending_payment_order",
    "decode_payment_order_payload",
    "encode_payment_order_payload",
    "get_payment_product_invoice_metadata",
    "is_active_pending_payment_order",
    "redact_payment_payload",
    "successful_payment_canonical_charge_id",
    "successful_payment_charge_aliases",
    "validate_successful_payment_order",
    "validate_payment_pre_checkout",
    "validate_payment_invoice_payload",
]
