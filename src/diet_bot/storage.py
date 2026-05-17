from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .payments import (
    PaymentCurrency,
    PaymentOrder,
    PaymentOrderCreationResult,
    PaymentProduct,
    PaymentProvider,
    PaymentReconciliationInput,
    PaymentReconciliationResult,
    PaymentReversalInput,
    PaymentReversalResult,
    PaymentSuccessfulPaymentInput,
    PaymentSuccessfulPaymentResult,
)
from .promo_codes import (
    PromoCodeActivation,
    PromoCodeDefinition,
    PromoCodeKind,
    PromoCodeRecord,
    PromoRedemptionResult,
)
from .subscriptions import AttemptConsumption, Entitlement, RationKind


@dataclass(frozen=True)
class UserIdentity:
    telegram_id: int
    username: str | None = None
    first_name: str | None = None


@dataclass(frozen=True)
class SupportState:
    user_id: int
    status: str
    last_request_at: datetime | None
    last_admin_message_id: int | None = None


@dataclass(frozen=True)
class RecipeHistoryItem:
    recipe_id: str
    recipe_key: str
    meal_slot: str
    ration_kind: RationKind
    generation_id: int | None = None
    generated_at: datetime | None = None
    day_index: int | None = None
    meal_index: int = 0
    user_id: int | None = None


@dataclass(frozen=True)
class UserAttribution:
    user_id: int
    source: str | None = None
    campaign: str | None = None
    referral: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class AnalyticsEventRecord:
    id: int
    occurred_at: datetime
    event_name: str
    user_id: int | None = None
    chat_id: int | None = None
    source: str | None = None
    campaign: str | None = None
    referral: str | None = None
    properties_json: dict[str, object] | None = None


class DietBotStore(Protocol):
    def initialize(self) -> None: ...
    def healthcheck(self) -> None: ...
    def remember_user(self, user: UserIdentity) -> None: ...
    def load_chat_state(self, chat_id: int) -> dict[str, object]: ...
    def save_chat_state(self, chat_id: int, state: dict[str, object]) -> None: ...
    def load_profile_data(self, user_id: int) -> dict[str, object] | None: ...
    def save_profile_data(self, user_id: int, profile_data: dict[str, object]) -> None: ...
    def get_entitlement(self, user_id: int) -> Entitlement: ...
    def save_entitlement(self, user_id: int, entitlement: Entitlement) -> None: ...
    def consume_generation_attempt(self, user_id: int, ration_kind: RationKind) -> AttemptConsumption: ...
    def heartbeat_generation_attempt(self, user_id: int, consumption: AttemptConsumption) -> bool: ...
    def start_generation_delivery(self, user_id: int, consumption: AttemptConsumption) -> bool: ...

    def complete_generation_attempt(
        self,
        user_id: int,
        consumption: AttemptConsumption,
        *,
        pdf_path: str | None = None,
        telegram_message_id: int | None = None,
    ) -> None: ...

    def refund_generation_attempt(
        self,
        user_id: int,
        consumption: AttemptConsumption,
        *,
        error_message: str | None = None,
    ) -> None: ...

    def record_recipe_history(
        self,
        user_id: int,
        entries: Sequence[RecipeHistoryItem],
    ) -> None: ...

    def load_recent_recipe_history(
        self,
        user_id: int,
        *,
        since: datetime | None = None,
        limit: int = 400,
    ) -> list[RecipeHistoryItem]: ...

    def get_user_attribution(self, user_id: int) -> UserAttribution | None: ...

    def set_user_attribution(
        self,
        user_id: int,
        *,
        source: str | None = None,
        campaign: str | None = None,
        referral: str | None = None,
    ) -> UserAttribution: ...

    def record_analytics_event(
        self,
        *,
        event_name: str,
        user_id: int | None = None,
        chat_id: int | None = None,
        source: str | None = None,
        campaign: str | None = None,
        referral: str | None = None,
        properties_json: dict[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> AnalyticsEventRecord: ...

    def cleanup_stale_generations(self, now: datetime | None = None) -> int: ...
    def upsert_promo_code(self, code: str, record: PromoCodeRecord) -> None: ...
    def create_promo_code(self, promo: PromoCodeDefinition) -> PromoCodeDefinition: ...
    def list_promo_codes(
        self,
        *,
        kind: PromoCodeKind | str | None = None,
        active_only: bool = False,
        now: datetime | None = None,
    ) -> list[PromoCodeDefinition]: ...
    def get_promo_code(
        self,
        raw_code: str,
        *,
        active_only: bool = False,
        now: datetime | None = None,
    ) -> PromoCodeDefinition | None: ...
    def disable_promo_code(
        self,
        raw_code: str,
        *,
        kind: PromoCodeKind | str | None = None,
    ) -> PromoCodeDefinition | None: ...
    def redeem_promo_code(
        self,
        user_id: int,
        raw_code: str,
        *,
        now: datetime | None = None,
    ) -> PromoRedemptionResult: ...
    def activate_promo_code(self, user_id: int, raw_code: str) -> PromoCodeActivation: ...
    def create_or_reuse_pending_payment_order(
        self,
        *,
        user_id: int,
        delivery_chat_id: int | None,
        provider: PaymentProvider | str,
        product: PaymentProduct | str,
        amount: int,
        currency: PaymentCurrency | str,
        now: datetime | None = None,
        ttl_seconds: int = 900,
        promo_code: str | None = None,
        pricing_context: str | None = None,
    ) -> PaymentOrderCreationResult: ...
    def load_payment_order(self, order_id: str) -> PaymentOrder | None: ...
    def mark_payment_order_invoice_link(self, order_id: str, invoice_link: str) -> None: ...
    def mark_payment_order_invoice_creation_failed(self, order_id: str) -> None: ...
    def record_payment_order_pre_checkout_approved(
        self,
        order_id: str,
        approved_at: datetime | None = None,
    ) -> PaymentOrder | None: ...
    def apply_successful_payment(
        self,
        successful_payment: PaymentSuccessfulPaymentInput,
        *,
        now: datetime | None = None,
    ) -> PaymentSuccessfulPaymentResult: ...
    def apply_payment_reversal(
        self,
        reversal: PaymentReversalInput,
        *,
        now: datetime | None = None,
    ) -> PaymentReversalResult: ...
    def apply_payment_reconciliation(
        self,
        reconciliation: PaymentReconciliationInput,
        *,
        now: datetime | None = None,
    ) -> PaymentReconciliationResult: ...
    def record_support_state(self, state: SupportState) -> None: ...
    def load_support_state(self, user_id: int) -> SupportState | None: ...
