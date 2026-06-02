from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime

from .entitlement_storage import EntitlementStore
from .subscriptions import (
    AttemptConsumption,
    AutoRenewStatus,
    Entitlement,
    PaymentApplication,
    RationKind,
    SubscriptionSource,
    apply_extra_one_day_payment as apply_extra_one_day_payment_to_entitlement,
    apply_extra_weekly_pdf_payment as apply_extra_weekly_pdf_payment_to_entitlement,
    apply_subscription_payment as apply_subscription_payment_to_entitlement,
    consume_one_day_attempt,
    consume_weekly_pdf_attempt,
    grant_test_access as grant_test_access_to_entitlement,
    has_processed_charge_id,
    record_processed_charge_id,
    refund_attempt,
    revoke_test_access as revoke_test_access_from_entitlement,
    set_test_access_enabled as set_test_access_enabled_on_entitlement,
)


class EntitlementService:
    def __init__(self, store: EntitlementStore) -> None:
        self._store = store

    def _load_chat_entitlement(self, chat_id: int) -> Entitlement | None:
        load_chat_entitlement = getattr(self._store, "load_chat_entitlement", None)
        if callable(load_chat_entitlement):
            return load_chat_entitlement(int(chat_id))
        return self._store.load_all().get(int(chat_id))

    @contextmanager
    def _transact_chat_entitlement(self, chat_id: int) -> Iterator[Entitlement]:
        chat_id = int(chat_id)
        transact_chat_entitlement = getattr(self._store, "transact_chat_entitlement", None)
        if callable(transact_chat_entitlement):
            with transact_chat_entitlement(chat_id) as entitlement:
                yield entitlement
            return

        with self._store.transact() as entitlements:
            entitlement = entitlements.get(chat_id, Entitlement())
            yield entitlement
            entitlements[chat_id] = entitlement

    def get_entitlement(self, chat_id: int, *, now: datetime | None = None) -> Entitlement:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            entitlement.expire_if_needed(now)
            return _copy_entitlement(entitlement)

    def peek_entitlement(self, chat_id: int, *, now: datetime | None = None) -> Entitlement:
        entitlement = _copy_entitlement(self._load_chat_entitlement(chat_id) or Entitlement())
        entitlement.expire_if_needed(now)
        return entitlement

    def grant_test_access(
        self,
        chat_id: int,
        *,
        now: datetime | None = None,
        days: int | None = None,
    ) -> Entitlement:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            if days is None:
                grant_test_access_to_entitlement(entitlement, now=now)
            else:
                grant_test_access_to_entitlement(entitlement, now=now, days=days)
            return _copy_entitlement(entitlement)

    def revoke_test_access(self, chat_id: int) -> Entitlement:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            revoke_test_access_from_entitlement(entitlement)
            return _copy_entitlement(entitlement)

    def set_test_access_enabled(
        self,
        chat_id: int,
        enabled: bool,
        *,
        now: datetime | None = None,
    ) -> tuple[bool, Entitlement]:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            changed = set_test_access_enabled_on_entitlement(entitlement, enabled, now=now)
            return changed, _copy_entitlement(entitlement)

    def dry_run_ration(
        self,
        chat_id: int,
        ration_kind: RationKind,
        *,
        free_preview: bool = False,
        now: datetime | None = None,
    ) -> AttemptConsumption:
        entitlement = _copy_entitlement(self._load_chat_entitlement(chat_id) or Entitlement())
        if free_preview:
            entitlement = _free_preview_entitlement(entitlement)
        return _consume_entitlement(entitlement, ration_kind, now=now)

    def weekly_pdf_available(
        self,
        chat_id: int,
        *,
        free_preview: bool = False,
        now: datetime | None = None,
    ) -> bool:
        return self.dry_run_ration(chat_id, "weekly_pdf", free_preview=free_preview, now=now).allowed

    def consume_ration(
        self,
        chat_id: int,
        ration_kind: RationKind,
        *,
        free_preview: bool = False,
        now: datetime | None = None,
    ) -> AttemptConsumption:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            if free_preview:
                preview_entitlement = _free_preview_entitlement(entitlement)
                consumption = _consume_entitlement(preview_entitlement, ration_kind, now=now)
                entitlement.free_trial_used = preview_entitlement.free_trial_used
            else:
                consumption = _consume_entitlement(entitlement, ration_kind, now=now)
            return consumption

    def consume_weekly_pdf(
        self,
        chat_id: int,
        *,
        free_preview: bool = False,
        now: datetime | None = None,
    ) -> AttemptConsumption:
        return self.consume_ration(chat_id, "weekly_pdf", free_preview=free_preview, now=now)

    def refund_generation_attempt(self, chat_id: int, consumption: AttemptConsumption) -> Entitlement:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            refund_attempt(entitlement, consumption)
            return _copy_entitlement(entitlement)

    def refund_weekly_pdf(self, chat_id: int, consumption: AttemptConsumption) -> Entitlement:
        return self.refund_generation_attempt(chat_id, consumption)

    def mark_free_trial_used(self, chat_id: int) -> Entitlement:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            entitlement.free_trial_used = True
            return _copy_entitlement(entitlement)

    def apply_subscription_payment(
        self,
        chat_id: int,
        charge_id: str,
        *,
        now: datetime | None = None,
        subscription_expiration_timestamp: int | None = None,
        subscription_source: SubscriptionSource | None = None,
        auto_renew_status: AutoRenewStatus | None = None,
        stars_subscription_charge_id: str | None = None,
        last_subscription_payment_charge_id: str | None | object = None,
        current_period_payment_order_id: str | None = None,
    ) -> PaymentApplication:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            kwargs = {}
            if last_subscription_payment_charge_id is not None:
                kwargs["last_subscription_payment_charge_id"] = last_subscription_payment_charge_id
            result = apply_subscription_payment_to_entitlement(
                entitlement,
                charge_id,
                now=now,
                subscription_expiration_timestamp=subscription_expiration_timestamp,
                subscription_source=subscription_source,
                auto_renew_status=auto_renew_status,
                stars_subscription_charge_id=stars_subscription_charge_id,
                current_period_payment_order_id=current_period_payment_order_id,
                **kwargs,
            )
            return result

    def apply_extra_one_day_payment(self, chat_id: int, charge_id: str) -> PaymentApplication:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            result = apply_extra_one_day_payment_to_entitlement(entitlement, charge_id)
            return result

    def apply_extra_weekly_pdf_payment(self, chat_id: int, charge_id: str) -> PaymentApplication:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            result = apply_extra_weekly_pdf_payment_to_entitlement(entitlement, charge_id)
            return result

    def has_processed_charge_id(self, chat_id: int, charge_id: str) -> bool:
        entitlement = self._load_chat_entitlement(chat_id)
        return bool(entitlement and has_processed_charge_id(entitlement, charge_id))

    def record_processed_charge_id(self, chat_id: int, charge_id: str) -> bool:
        with self._transact_chat_entitlement(chat_id) as entitlement:
            recorded = record_processed_charge_id(entitlement, charge_id)
            return recorded


def _consume_entitlement(
    entitlement: Entitlement,
    ration_kind: RationKind,
    *,
    now: datetime | None = None,
) -> AttemptConsumption:
    if ration_kind == "weekly_pdf":
        return consume_weekly_pdf_attempt(entitlement, now)
    return consume_one_day_attempt(entitlement, now)


def _free_preview_entitlement(entitlement: Entitlement) -> Entitlement:
    return replace(
        entitlement,
        subscription_period_start=None,
        subscription_period_end=None,
        monthly_one_day_remaining=0,
        monthly_weekly_pdf_remaining=0,
        extra_one_day_remaining=0,
        extra_weekly_pdf_remaining=0,
        test_access_enabled=False,
        processed_payment_charge_ids=list(entitlement.processed_payment_charge_ids),
    )


def _copy_entitlement(entitlement: Entitlement) -> Entitlement:
    return replace(
        entitlement,
        processed_payment_charge_ids=list(entitlement.processed_payment_charge_ids),
    )
