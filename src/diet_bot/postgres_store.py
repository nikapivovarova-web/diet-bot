from __future__ import annotations

import uuid
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from .payments import (
    PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
    PAYMENT_EVENT_CHARGEBACK,
    PAYMENT_EVENT_NEGATIVE_TYPES,
    PAYMENT_EVENT_REFUND,
    PAYMENT_EVENT_STATUS_DUPLICATE,
    PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
    PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE,
    PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
    PAYMENT_EVENT_STATUS_PROCESSED,
    PAYMENT_EVENT_TRANSITIONAL_STATUSES,
    PAYMENT_EVENT_SUCCESSFUL,
    PaymentEvent,
    PaymentEventApplication,
    PaymentOrder,
    PaymentProduct,
)
from .postgres_migrations import run_postgres_migrations
from .promo_codes import PromoCodeActivation, PromoCodeRecord, normalize_promo_code, promo_code_lookup_key
from .subscriptions import (
    AttemptConsumption,
    Entitlement,
    LEDGER_EVENT_CONSUME,
    LEDGER_EVENT_REFUND,
    LEDGER_SOURCE_EXTRA_ONE_DAY,
    LEDGER_SOURCE_EXTRA_WEEKLY_PDF,
    LEDGER_SOURCE_FREE_TRIAL_ONE_DAY,
    LEDGER_SOURCE_MONTHLY_ONE_DAY,
    LEDGER_SOURCE_MONTHLY_WEEKLY_PDF,
    LEDGER_SOURCE_TEST_ACCESS,
    LedgerSource,
    MONTHLY_ONE_DAY_LIMIT,
    MONTHLY_WEEKLY_PDF_LIMIT,
    PaymentApplication,
    PaymentGrant,
    RationKind,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_payment_reversal,
    apply_subscription_payment,
    consume_one_day_attempt,
    consume_weekly_pdf_attempt,
    grant_test_access,
    revoke_test_access,
    set_test_access_enabled,
)


PromoGrantKind = Literal[
    "subscription_month",
    "extra_one_day",
    "extra_weekly_pdf",
    "test_access_days",
]

GENERATION_STALE_TIMEOUT = timedelta(minutes=30)
ACTIVE_MEAL_PLAN_STATUSES = ("generating", "delivering")
JSON_IMPORT_LOCK_ID = 4_829_479_171_217_297_001


BASE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_state (
    chat_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
    state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
    profile_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entitlements (
    user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'inactive',
    subscription_started_at TIMESTAMPTZ,
    subscription_expires_at TIMESTAMPTZ,
    monthly_one_day_remaining INTEGER NOT NULL DEFAULT 0,
    monthly_weekly_pdf_remaining INTEGER NOT NULL DEFAULT 0,
    extra_one_day_remaining INTEGER NOT NULL DEFAULT 0,
    extra_weekly_pdf_remaining INTEGER NOT NULL DEFAULT 0,
    trial_used BOOLEAN NOT NULL DEFAULT false,
    trial_started_at TIMESTAMPTZ,
    trial_ends_at TIMESTAMPTZ,
    test_access_enabled BOOLEAN NOT NULL DEFAULT false,
    test_access_until TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entitlement_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    meal_plan_id BIGINT,
    event_type TEXT NOT NULL,
    source TEXT,
    amount INTEGER NOT NULL DEFAULT 1,
    related_event_id BIGINT REFERENCES entitlement_events(id) ON DELETE SET NULL,
    reason TEXT,
    delta_generations INTEGER,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed_payment_charges (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    charge_id TEXT NOT NULL,
    telegram_charge_id TEXT,
    provider_charge_id TEXT,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    amount INTEGER,
    currency TEXT,
    status TEXT NOT NULL DEFAULT 'processed',
    raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(provider, charge_id)
);

CREATE TABLE IF NOT EXISTS payment_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    charge_id TEXT NOT NULL,
    telegram_charge_id TEXT,
    provider_charge_id TEXT,
    product TEXT,
    amount INTEGER,
    currency TEXT,
    status TEXT NOT NULL DEFAULT 'processed',
    reason TEXT,
    raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(provider, charge_id, event_type)
);

CREATE TABLE IF NOT EXISTS payment_orders (
    order_id TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    delivery_chat_id BIGINT,
    product TEXT NOT NULL,
    provider TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    is_recurring BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    paid_at TIMESTAMPTZ,
    invoice_link TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analytics_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
    event_name TEXT NOT NULL,
    properties_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS promo_codes (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'subscription_month',
    value INTEGER NOT NULL DEFAULT 1,
    max_uses INTEGER,
    used_count INTEGER NOT NULL DEFAULT 0,
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS promo_redemptions (
    id BIGSERIAL PRIMARY KEY,
    promo_code_id BIGINT NOT NULL REFERENCES promo_codes(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(promo_code_id, user_id)
);

CREATE TABLE IF NOT EXISTS meal_plans (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    plan_type TEXT NOT NULL,
    status TEXT NOT NULL,
    pdf_path TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    delivery_started_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    telegram_message_id BIGINT,
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    finished_at TIMESTAMPTZ
);
"""


class PostgresDietBotStore:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = 5,
        connect_attempts: int = 3,
        retry_base_delay: float = 0.2,
        retry_max_delay: float = 1.0,
    ) -> None:
        self.dsn = dsn
        self.connect_timeout = connect_timeout
        self.connect_attempts = max(1, connect_attempts)
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay

    def initialize(self) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    for statement in BASE_SCHEMA_SQL.split(";"):
                        statement = statement.strip()
                        if statement:
                            cur.execute(statement)
                    run_postgres_migrations(cur)

    def upsert_user(
        self,
        user_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_user_cur(cur, user_id, username=username, first_name=first_name)

    def load_chat_state(self, chat_id: int) -> dict[str, object]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cs.state_json, up.profile_json
                    FROM users u
                    LEFT JOIN chat_state cs ON cs.chat_id = u.telegram_id
                    LEFT JOIN user_profiles up ON up.user_id = u.telegram_id
                    WHERE u.telegram_id = %s
                    """,
                    (chat_id,),
                )
                row = cur.fetchone()
        if not row:
            return {}
        state = dict(row.get("state_json") or {})
        profile = row.get("profile_json")
        if isinstance(profile, dict):
            state["profile"] = profile
        return state

    def save_chat_history(
        self,
        chat_id: int,
        *,
        recipe_ids: list[str],
        recipe_keys: list[str],
    ) -> None:
        state = {
            "recipe_ids": list(recipe_ids),
            "recipe_keys": list(recipe_keys),
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_user_cur(cur, chat_id)
                cur.execute(
                    """
                    INSERT INTO chat_state (chat_id, state_json)
                    VALUES (%s, %s)
                    ON CONFLICT (chat_id) DO UPDATE
                    SET state_json = chat_state.state_json || EXCLUDED.state_json,
                        updated_at = now()
                    """,
                    (chat_id, _jsonb(state)),
                )

    def load_profile_data(self, user_id: int) -> dict[str, object] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT profile_json FROM user_profiles WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
        profile = row.get("profile_json") if row else None
        return dict(profile) if isinstance(profile, dict) else None

    def save_profile_data(self, user_id: int, profile_data: dict[str, object]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_user_cur(cur, user_id)
                cur.execute(
                    """
                    INSERT INTO user_profiles (user_id, profile_json)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET profile_json = EXCLUDED.profile_json,
                        updated_at = now()
                    """,
                    (user_id, _jsonb(profile_data)),
                )

    def get_entitlement(self, user_id: int) -> Entitlement:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    entitlement = self._select_entitlement_for_update(cur, user_id)
                    before = entitlement.to_dict()
                    entitlement.expire_if_needed()
                    if entitlement.to_dict() != before:
                        self._update_entitlement_cur(cur, user_id, entitlement)
                        self._insert_event_cur(
                            cur,
                            user_id,
                            "entitlement_expired",
                            reason="read_expire",
                            metadata={"before": before, "after": entitlement.to_dict()},
                        )
                    return entitlement

    def save_entitlement(self, user_id: int, entitlement: Entitlement) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._select_entitlement_for_update(cur, user_id)
                    self._update_entitlement_cur(cur, user_id, entitlement)

    def grant_test_access_to_chat(
        self,
        user_id: int,
        *,
        now: datetime | None = None,
    ) -> Entitlement:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    entitlement = self._select_entitlement_for_update(cur, user_id)
                    grant_test_access(entitlement, now=now)
                    self._update_entitlement_cur(cur, user_id, entitlement)
                    self._insert_event_cur(
                        cur,
                        user_id,
                        "test_access_granted",
                        reason="admin_command",
                        metadata={"test_access_until": entitlement.test_access_until},
                    )
                    return entitlement

    def revoke_test_access_for_chat(self, user_id: int) -> Entitlement:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    entitlement = self._select_entitlement_for_update(cur, user_id)
                    revoke_test_access(entitlement)
                    self._update_entitlement_cur(cur, user_id, entitlement)
                    self._insert_event_cur(cur, user_id, "test_access_revoked", reason="admin_command")
                    return entitlement

    def set_test_access_mode(self, user_id: int, enabled: bool) -> tuple[bool, Entitlement]:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    entitlement = self._select_entitlement_for_update(cur, user_id)
                    changed = set_test_access_enabled(entitlement, enabled)
                    self._update_entitlement_cur(cur, user_id, entitlement)
                    self._insert_event_cur(
                        cur,
                        user_id,
                        "test_access_mode_changed",
                        reason="user_command",
                        metadata={"enabled": enabled, "changed": changed},
                    )
                    return changed, entitlement

    def create_payment_order(self, order: PaymentOrder) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._upsert_user_cur(cur, order.user_id)
                    cur.execute(
                        """
                        INSERT INTO payment_orders (
                            order_id,
                            nonce,
                            user_id,
                            delivery_chat_id,
                            product,
                            provider,
                            amount,
                            currency,
                            status,
                            is_recurring,
                            created_at,
                            expires_at,
                            paid_at,
                            invoice_link
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (order_id) DO UPDATE
                        SET nonce = EXCLUDED.nonce,
                            user_id = EXCLUDED.user_id,
                            delivery_chat_id = EXCLUDED.delivery_chat_id,
                            product = EXCLUDED.product,
                            provider = EXCLUDED.provider,
                            amount = EXCLUDED.amount,
                            currency = EXCLUDED.currency,
                            status = EXCLUDED.status,
                            is_recurring = EXCLUDED.is_recurring,
                            created_at = EXCLUDED.created_at,
                            expires_at = EXCLUDED.expires_at,
                            paid_at = EXCLUDED.paid_at,
                            invoice_link = EXCLUDED.invoice_link,
                            updated_at = now()
                        """,
                        (
                            order.order_id,
                            order.nonce,
                            order.user_id,
                            order.delivery_chat_id,
                            order.product,
                            order.provider,
                            order.amount,
                            order.currency,
                            order.status,
                            order.is_recurring,
                            _parse_datetime(order.created_at),
                            _parse_datetime(order.expires_at),
                            _parse_datetime(order.paid_at),
                            order.invoice_link,
                        ),
                    )

    def import_processed_payment_charge(
        self,
        user_id: int,
        *,
        provider: str,
        charge_id: str,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        amount: int | None = None,
        currency: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        status: str = "processed",
    ) -> bool:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._upsert_user_cur(cur, user_id)
                    return self._insert_processed_charge_cur(
                        cur,
                        user_id,
                        provider=provider,
                        charge_id=charge_id,
                        telegram_charge_id=telegram_charge_id,
                        provider_charge_id=provider_charge_id,
                        amount=amount,
                        currency=currency,
                        raw_payload=raw_payload or {},
                        status=status,
                    )

    def get_payment_order(self, order_id: str) -> PaymentOrder | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM payment_orders WHERE order_id = %s",
                    (order_id,),
                )
                row = cur.fetchone()
        return _row_to_payment_order(row) if row else None

    def find_active_payment_order(
        self,
        *,
        user_id: int,
        delivery_chat_id: int | None,
        product: PaymentProduct,
        provider: str,
        amount: int,
        currency: str,
        is_recurring: bool,
    ) -> PaymentOrder | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM payment_orders
                    WHERE user_id = %s
                      AND delivery_chat_id IS NOT DISTINCT FROM %s
                      AND product = %s
                      AND provider = %s
                      AND amount = %s
                      AND currency = %s
                      AND is_recurring = %s
                      AND status = 'pending'
                      AND expires_at > now()
                      AND invoice_link IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (
                        user_id,
                        delivery_chat_id,
                        product,
                        provider,
                        amount,
                        currency,
                        is_recurring,
                    ),
                )
                row = cur.fetchone()
        return _row_to_payment_order(row) if row else None

    def set_payment_order_invoice_link(self, order_id: str, invoice_link: str) -> PaymentOrder | None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE payment_orders
                        SET invoice_link = %s,
                            updated_at = now()
                        WHERE order_id = %s
                          AND status = 'pending'
                        RETURNING *
                        """,
                        (invoice_link, order_id),
                    )
                    row = cur.fetchone()
        return _row_to_payment_order(row) if row else None

    def mark_payment_order_failed_invoice_creation(self, order_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payment_orders
                    SET status = 'failed_invoice_creation',
                        updated_at = now()
                    WHERE order_id = %s AND status = 'pending'
                    """,
                    (order_id,),
                )

    def mark_payment_order_expired(self, order_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payment_orders
                    SET status = 'expired',
                        updated_at = now()
                    WHERE order_id = %s AND status = 'pending'
                    """,
                    (order_id,),
                )

    def record_analytics_event(
        self,
        user_id: int | None,
        event_name: str,
        properties: dict[str, object],
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                if user_id is not None:
                    self._upsert_user_cur(cur, user_id)
                cur.execute(
                    """
                    INSERT INTO analytics_events (user_id, event_name, properties_json)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, event_name, _jsonb(properties)),
                )

    def record_orphan_payment(
        self,
        user_id: int,
        *,
        provider: str,
        charge_id: str,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        amount: int | None,
        currency: str | None,
        raw_payload: dict[str, Any],
        reason: str,
    ) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._upsert_user_cur(cur, user_id)
                    self._insert_orphan_payment_cur(
                        cur,
                        user_id,
                        provider=provider,
                        charge_id=charge_id,
                        telegram_charge_id=telegram_charge_id,
                        provider_charge_id=provider_charge_id,
                        amount=amount,
                        currency=currency,
                        raw_payload=raw_payload,
                        reason=reason,
                    )

    def apply_order_payment(
        self,
        user_id: int,
        *,
        order_id: str,
        nonce: str,
        delivery_chat_id: int | None = None,
        provider: str,
        charge_id: str,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        amount: int | None,
        currency: str | None,
        raw_payload: dict[str, Any],
        is_recurring_payment: bool = False,
        is_first_recurring_payment: bool = False,
        subscription_expiration_timestamp: int | None = None,
    ) -> PaymentApplication:
        if not charge_id:
            return PaymentApplication(False)

        current_time = datetime.now(UTC)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._upsert_user_cur(cur, user_id)
                    cur.execute(
                        "SELECT * FROM payment_orders WHERE order_id = %s FOR UPDATE",
                        (order_id,),
                    )
                    order_row = cur.fetchone()
                    order = _row_to_payment_order(order_row) if order_row else None
                    if order is None:
                        self._insert_orphan_payment_cur(
                            cur,
                            user_id,
                            provider=provider,
                            charge_id=charge_id,
                            telegram_charge_id=telegram_charge_id,
                            provider_charge_id=provider_charge_id,
                            amount=amount,
                            currency=currency,
                            raw_payload=raw_payload,
                            reason="order_not_found",
                        )
                        return PaymentApplication(False)

                    grant = _payment_grant_for_order_product(order.product)
                    if self._payment_charge_exists_cur(cur, provider=provider, charge_id=charge_id):
                        return PaymentApplication(False, grant, duplicate=True)
                    invalid_reason = _payment_order_invalid_reason(
                        order,
                        user_id=user_id,
                        nonce=nonce,
                        delivery_chat_id=delivery_chat_id,
                        provider=provider,
                        amount=amount,
                        currency=currency,
                        is_recurring_payment=is_recurring_payment,
                        is_first_recurring_payment=is_first_recurring_payment,
                    )
                    if invalid_reason is not None:
                        self._insert_orphan_payment_cur(
                            cur,
                            user_id,
                            provider=provider,
                            charge_id=charge_id,
                            telegram_charge_id=telegram_charge_id,
                            provider_charge_id=provider_charge_id,
                            amount=amount,
                            currency=currency,
                            raw_payload=raw_payload,
                            reason=invalid_reason,
                        )
                        return PaymentApplication(False, grant)

                    entitlement = self._select_entitlement_for_update(cur, user_id)
                    entitlement.expire_if_needed(current_time)
                    if order.product != "subscription_month" and not entitlement.is_subscription_active(current_time):
                        self._insert_orphan_payment_cur(
                            cur,
                            user_id,
                            provider=provider,
                            charge_id=charge_id,
                            telegram_charge_id=telegram_charge_id,
                            provider_charge_id=provider_charge_id,
                            amount=amount,
                            currency=currency,
                            raw_payload=raw_payload,
                            reason="extra_without_active_subscription",
                        )
                        return PaymentApplication(False, grant)

                    inserted = self._insert_processed_charge_cur(
                        cur,
                        user_id,
                        provider=provider,
                        charge_id=charge_id,
                        telegram_charge_id=telegram_charge_id,
                        provider_charge_id=provider_charge_id,
                        amount=amount,
                        currency=currency,
                        raw_payload={
                            **raw_payload,
                            "payment_order": order.to_dict(),
                        },
                        status="processed",
                    )
                    if not inserted:
                        return PaymentApplication(False, grant, duplicate=True)
                    event_inserted = self._insert_payment_event_cur(
                        cur,
                        user_id,
                        event_type=PAYMENT_EVENT_SUCCESSFUL,
                        provider=provider,
                        charge_id=charge_id,
                        telegram_charge_id=telegram_charge_id,
                        provider_charge_id=provider_charge_id,
                        product=order.product,
                        amount=amount,
                        currency=currency,
                        status=PAYMENT_EVENT_STATUS_PROCESSED,
                        raw_payload={
                            **raw_payload,
                            "payment_order": order.to_dict(),
                        },
                    )
                    if not event_inserted:
                        return PaymentApplication(False, grant, duplicate=True)

                    result = self._apply_payment_grant(
                        entitlement,
                        grant,
                        f"{provider}:{charge_id}",
                        subscription_expiration_timestamp=subscription_expiration_timestamp,
                    )
                    self._update_entitlement_cur(cur, user_id, entitlement)
                    if result.processed:
                        cur.execute(
                            """
                            UPDATE payment_orders
                            SET status = 'paid',
                                paid_at = COALESCE(paid_at, %s),
                                updated_at = now()
                            WHERE order_id = %s
                            """,
                            (current_time, order.order_id),
                        )
                    self._insert_event_cur(
                        cur,
                        user_id,
                        "payment_order_applied",
                        reason=f"payment_order:{provider}",
                        metadata={
                            "provider": provider,
                            "charge_id": charge_id,
                            "order_id": order.order_id,
                            "product": order.product,
                            "amount": amount,
                            "currency": currency,
                            "processed": result.processed,
                            "duplicate": result.duplicate,
                        },
                    )
                    if result.processed:
                        self._reconcile_pending_payment_events_for_charge_cur(
                            cur,
                            user_id=user_id,
                            provider=provider,
                            charge_id=charge_id,
                            current_time=current_time,
                        )
                    return result

    def apply_payment(
        self,
        user_id: int,
        *,
        provider: str,
        charge_id: str,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        grant: PaymentGrant,
        amount: int | None,
        currency: str | None,
        raw_payload: dict[str, Any],
        subscription_expiration_timestamp: int | None = None,
    ) -> PaymentApplication:
        if not charge_id:
            return PaymentApplication(False, grant)

        current_time = datetime.now(UTC)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._upsert_user_cur(cur, user_id)

                    if self._payment_charge_exists_cur(cur, provider=provider, charge_id=charge_id):
                        return PaymentApplication(False, grant, duplicate=True)

                    entitlement = self._select_entitlement_for_update(cur, user_id)
                    entitlement.expire_if_needed(current_time)
                    if grant != "subscription" and not entitlement.is_subscription_active(current_time):
                        self._update_entitlement_cur(cur, user_id, entitlement)
                        self._insert_orphan_payment_cur(
                            cur,
                            user_id,
                            provider=provider,
                            charge_id=charge_id,
                            telegram_charge_id=telegram_charge_id,
                            provider_charge_id=provider_charge_id,
                            amount=amount,
                            currency=currency,
                            raw_payload=raw_payload,
                            reason="extra_without_active_subscription",
                        )
                        return PaymentApplication(False, grant)

                    inserted = self._insert_processed_charge_cur(
                        cur,
                        user_id,
                        provider=provider,
                        charge_id=charge_id,
                        telegram_charge_id=telegram_charge_id,
                        provider_charge_id=provider_charge_id,
                        amount=amount,
                        currency=currency,
                        raw_payload=raw_payload,
                        status="processed",
                    )
                    if not inserted:
                        return PaymentApplication(False, grant, duplicate=True)
                    event_inserted = self._insert_payment_event_cur(
                        cur,
                        user_id,
                        event_type=PAYMENT_EVENT_SUCCESSFUL,
                        provider=provider,
                        charge_id=charge_id,
                        telegram_charge_id=telegram_charge_id,
                        provider_charge_id=provider_charge_id,
                        product=_payment_product_for_grant(grant),
                        amount=amount,
                        currency=currency,
                        status=PAYMENT_EVENT_STATUS_PROCESSED,
                        raw_payload=raw_payload,
                    )
                    if not event_inserted:
                        return PaymentApplication(False, grant, duplicate=True)

                    result = self._apply_payment_grant(
                        entitlement,
                        grant,
                        f"{provider}:{charge_id}",
                        subscription_expiration_timestamp=subscription_expiration_timestamp,
                    )
                    self._update_entitlement_cur(cur, user_id, entitlement)
                    self._insert_event_cur(
                        cur,
                        user_id,
                        "payment_applied",
                        reason=f"payment:{provider}",
                        metadata={
                            "provider": provider,
                            "charge_id": charge_id,
                            "grant": grant,
                            "amount": amount,
                            "currency": currency,
                        },
                    )
                    if result.processed:
                        self._reconcile_pending_payment_events_for_charge_cur(
                            cur,
                            user_id=user_id,
                            provider=provider,
                            charge_id=charge_id,
                            current_time=current_time,
                        )
                    return result

    def apply_payment_event(
        self,
        user_id: int,
        *,
        event_type: str,
        provider: str,
        charge_id: str,
        amount: int | None = None,
        currency: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> PaymentEventApplication:
        normalized_event_type = _normalize_payment_event_type(event_type)
        if not charge_id:
            return PaymentEventApplication(
                False,
                normalized_event_type,
                reason="missing_charge_id",
                status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
            )

        current_time = datetime.now(UTC)
        payload = raw_payload or {}
        telegram_charge_id = _payload_text(payload, "telegram_payment_charge_id")
        provider_charge_id = _payload_text(payload, "provider_payment_charge_id")
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._upsert_user_cur(cur, user_id)

                    if normalized_event_type == "unknown":
                        inserted = self._insert_payment_event_cur(
                            cur,
                            user_id,
                            event_type=normalized_event_type,
                            provider=provider,
                            charge_id=charge_id,
                            telegram_charge_id=telegram_charge_id,
                            provider_charge_id=provider_charge_id,
                            amount=amount,
                            currency=currency,
                            status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
                            reason="unknown_event_type",
                            raw_payload=payload,
                        )
                        self._insert_event_cur(
                            cur,
                            user_id,
                            "payment_event_ignored",
                            reason="unknown_event_type",
                            metadata={
                                "event_type": event_type,
                                "provider": provider,
                                "charge_id": charge_id,
                            },
                        )
                        return PaymentEventApplication(
                            False,
                            normalized_event_type,
                            duplicate=False,
                            reason="unknown_event_type",
                            status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
                        )

                    if normalized_event_type == PAYMENT_EVENT_SUCCESSFUL:
                        return PaymentEventApplication(
                            False,
                            normalized_event_type,
                            reason="successful_payment_uses_specific_handler",
                            status=PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL,
                        )

                    self._lock_processed_charge_cur(cur, provider=provider, charge_id=charge_id)
                    product = self._find_successful_payment_product_cur(cur, provider=provider, charge_id=charge_id)
                    if product is None:
                        inserted = self._insert_payment_event_cur(
                            cur,
                            user_id,
                            event_type=normalized_event_type,
                            provider=provider,
                            charge_id=charge_id,
                            telegram_charge_id=telegram_charge_id,
                            provider_charge_id=provider_charge_id,
                            amount=amount,
                            currency=currency,
                            status=PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
                            reason="original_payment_not_found",
                            raw_payload=payload,
                        )
                        self._insert_event_cur(
                            cur,
                            user_id,
                            "payment_event_ignored",
                            reason="original_payment_not_found",
                            metadata={
                                "event_type": normalized_event_type,
                                "provider": provider,
                                "charge_id": charge_id,
                            },
                        )
                        return PaymentEventApplication(
                            False,
                            normalized_event_type,
                            duplicate=False,
                            reason="original_payment_not_found" if inserted else "pending_reconciliation_exists",
                            status=PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
                        )

                    if self._terminal_payment_adjustment_exists_cur(
                        cur,
                        event_type=normalized_event_type,
                        provider=provider,
                        charge_id=charge_id,
                    ):
                        self._insert_payment_event_cur(
                            cur,
                            user_id,
                            event_type=normalized_event_type,
                            provider=provider,
                            charge_id=charge_id,
                            telegram_charge_id=telegram_charge_id,
                            provider_charge_id=provider_charge_id,
                            product=product,
                            amount=amount,
                            currency=currency,
                            status=PAYMENT_EVENT_STATUS_DUPLICATE,
                            reason="duplicate_event",
                            raw_payload=payload,
                        )
                        return PaymentEventApplication(
                            False,
                            normalized_event_type,
                            product=product,
                            duplicate=True,
                            reason="duplicate_event",
                            status=PAYMENT_EVENT_STATUS_DUPLICATE,
                        )

                    entitlement = self._select_entitlement_for_update(cur, user_id)
                    before = entitlement.to_dict()
                    reversal = apply_payment_reversal(
                        entitlement,
                        product,
                        normalized_event_type,  # type: ignore[arg-type]
                        now=current_time,
                    )
                    status = (
                        PAYMENT_EVENT_STATUS_PROCESSED
                        if reversal.processed
                        else PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL
                    )
                    reason = reversal.reason
                    inserted = self._insert_payment_event_cur(
                        cur,
                        user_id,
                        event_type=normalized_event_type,
                        provider=provider,
                        charge_id=charge_id,
                        telegram_charge_id=telegram_charge_id,
                        provider_charge_id=provider_charge_id,
                        product=product,
                        amount=amount,
                        currency=currency,
                        status=status,
                        reason=reason,
                        raw_payload=payload,
                    )
                    if not inserted:
                        return PaymentEventApplication(
                            False,
                            normalized_event_type,
                            product=product,
                            duplicate=True,
                            reason="duplicate_event",
                            status=PAYMENT_EVENT_STATUS_DUPLICATE,
                        )
                    self._update_entitlement_cur(cur, user_id, entitlement)
                    self._insert_event_cur(
                        cur,
                        user_id,
                        _payment_event_audit_type(normalized_event_type),
                        reason=f"payment_event:{provider}",
                        metadata={
                            "event_type": normalized_event_type,
                            "provider": provider,
                            "charge_id": charge_id,
                            "product": product,
                            "amount": amount,
                            "currency": currency,
                            "processed": reversal.processed,
                            "before": before,
                            "after": entitlement.to_dict(),
                        },
                    )
                    return PaymentEventApplication(
                        reversal.processed,
                        normalized_event_type,
                        product=product,
                        reason=reason,
                        status=status,
                    )

    def _reconcile_pending_payment_events_for_charge_cur(
        self,
        cur,
        *,
        user_id: int,
        provider: str,
        charge_id: str,
        current_time: datetime,
    ) -> None:
        cur.execute(
            """
            SELECT *
            FROM payment_events
            WHERE user_id = %s
              AND provider = %s
              AND status = %s
              AND event_type IN (%s, %s, %s)
              AND (
                charge_id = %s
                OR telegram_charge_id = %s
                OR provider_charge_id = %s
              )
            ORDER BY id
            FOR UPDATE
            """,
            (
                user_id,
                provider,
                PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
                PAYMENT_EVENT_REFUND,
                PAYMENT_EVENT_CHARGEBACK,
                PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
                charge_id,
                charge_id,
                charge_id,
            ),
        )
        rows = cur.fetchall()
        if not rows:
            return
        product = self._find_successful_payment_product_cur(cur, provider=provider, charge_id=charge_id)
        if product is None:
            return
        entitlement = self._select_entitlement_for_update(cur, user_id)
        before = entitlement.to_dict()
        for row in rows:
            event_type = str(row["event_type"])
            reversal = apply_payment_reversal(
                entitlement,
                product,
                event_type,  # type: ignore[arg-type]
                now=current_time,
            )
            status = (
                PAYMENT_EVENT_STATUS_PROCESSED
                if reversal.processed
                else PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL
            )
            raw_payload = row.get("raw_payload_json") or {}
            cur.execute(
                """
                UPDATE payment_events
                SET product = %s,
                    status = %s,
                    reason = %s,
                    raw_payload_json = raw_payload_json || %s
                WHERE id = %s
                """,
                (
                    product,
                    status,
                    reversal.reason,
                    _jsonb(
                        {
                            **raw_payload,
                            "source": "automatic_pending_reconciliation",
                            "successful_charge_id": charge_id,
                        }
                    ),
                    row["id"],
                ),
            )
            self._insert_event_cur(
                cur,
                user_id,
                _payment_event_audit_type(event_type),
                reason=f"payment_event:{provider}",
                metadata={
                    "event_type": event_type,
                    "provider": provider,
                    "charge_id": charge_id,
                    "product": product,
                    "status": status,
                    "processed": reversal.processed,
                    "before": before,
                    "after": entitlement.to_dict(),
                    "source": "automatic_pending_reconciliation",
                },
            )
        self._update_entitlement_cur(cur, user_id, entitlement)

    def find_successful_payment_user_id(self, *, provider: str, charge_id: str) -> int | None:
        if not charge_id:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id
                    FROM payment_events
                    WHERE provider = %s
                      AND (
                        charge_id = %s
                        OR telegram_charge_id = %s
                        OR provider_charge_id = %s
                      )
                      AND event_type = %s
                      AND status = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (
                        provider,
                        charge_id,
                        charge_id,
                        charge_id,
                        PAYMENT_EVENT_SUCCESSFUL,
                        PAYMENT_EVENT_STATUS_PROCESSED,
                    ),
                )
                row = cur.fetchone()
                if row is not None:
                    return int(row["user_id"])

                cur.execute(
                    """
                    SELECT user_id
                    FROM processed_payment_charges
                    WHERE provider = %s
                      AND (
                        charge_id = %s
                        OR telegram_charge_id = %s
                        OR provider_charge_id = %s
                      )
                      AND status = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (
                        provider,
                        charge_id,
                        charge_id,
                        charge_id,
                        PAYMENT_EVENT_STATUS_PROCESSED,
                    ),
                )
                row = cur.fetchone()
                if row is not None:
                    return int(row["user_id"])
        return None

    def find_payment_event_for_reconciliation(
        self,
        lookup_id: str,
        *,
        statuses: set[str] | None = None,
    ) -> PaymentEvent | None:
        lookup_id = str(lookup_id).strip()
        if not lookup_id:
            return None
        statuses = statuses or {
            PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
            PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE,
            "ignored",
            "orphan",
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM payment_events
                    WHERE status = ANY(%s)
                      AND (
                        event_id = %s
                        OR charge_id = %s
                        OR telegram_charge_id = %s
                        OR provider_charge_id = %s
                      )
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (list(statuses), lookup_id, lookup_id, lookup_id, lookup_id),
                )
                row = cur.fetchone()
        return _row_to_payment_event(row) if row else None

    def activate_promo_code(
        self,
        user_id: int,
        raw_code: str,
        *,
        now: datetime | None = None,
    ) -> PromoCodeActivation:
        code = normalize_promo_code(raw_code)
        if not code:
            return PromoCodeActivation("not_found", "")
        lookup_key = promo_code_lookup_key(code)
        current_time = _normalize_now(now)

        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._upsert_user_cur(cur, user_id)
                    cur.execute(
                        """
                        SELECT *
                        FROM promo_codes
                        WHERE code = %s
                        FOR UPDATE
                        """,
                        (lookup_key,),
                    )
                    promo = cur.fetchone()
                    if not promo or not _promo_is_active_in_window(promo, current_time):
                        return PromoCodeActivation("not_found", code, lookup_key=lookup_key)

                    cur.execute(
                        """
                        SELECT user_id
                        FROM promo_redemptions
                        WHERE promo_code_id = %s AND user_id = %s
                        """,
                        (promo["id"], user_id),
                    )
                    if cur.fetchone() is not None:
                        return PromoCodeActivation("already_used", code, user_id, lookup_key)
                    if _promo_is_exhausted(promo):
                        return PromoCodeActivation("not_found", code, lookup_key=lookup_key)

                    cur.execute(
                        """
                        INSERT INTO promo_redemptions (promo_code_id, user_id, redeemed_at)
                        VALUES (%s, %s, %s)
                        """,
                        (promo["id"], user_id, current_time),
                    )
                    cur.execute(
                        "UPDATE promo_codes SET used_count = used_count + 1 WHERE id = %s",
                        (promo["id"],),
                    )
                    entitlement = self._select_entitlement_for_update(cur, user_id)
                    self._apply_promo_grant(entitlement, promo, lookup_key, current_time)
                    self._update_entitlement_cur(cur, user_id, entitlement)
                    self._insert_event_cur(
                        cur,
                        user_id,
                        "promo_redeemed",
                        reason=f"promo:{lookup_key}",
                        metadata={
                            "promo_code_id": promo["id"],
                            "promo_code_lookup_key": lookup_key,
                            "kind": promo["kind"],
                            "value": promo["value"],
                        },
                    )
                    return PromoCodeActivation("activated", code, user_id, lookup_key)

    def consume_generation_attempt(
        self,
        user_id: int,
        ration_kind: RationKind,
    ) -> AttemptConsumption:
        current_time = datetime.now(UTC)
        try:
            with self._connect() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        entitlement = self._select_entitlement_for_update(cur, user_id)
                        self._fail_stale_generations_cur(cur, user_id, entitlement, current_time)

                        if self._active_generation_exists_cur(cur, user_id):
                            self._update_entitlement_cur(cur, user_id, entitlement)
                            return AttemptConsumption(
                                False,
                                ration_kind,
                                denial_reason="already_generating",
                            )

                        consumption = self._consume_entitlement_for_ration(entitlement, ration_kind, current_time)
                        if not consumption.allowed:
                            self._update_entitlement_cur(cur, user_id, entitlement)
                            self._insert_event_cur(
                                cur,
                                user_id,
                                "generation_attempt_denied",
                                reason=f"generation:{ration_kind}",
                                metadata={
                                    "ration_kind": ration_kind,
                                    "denial_reason": "paywall",
                                },
                            )
                            return AttemptConsumption(False, ration_kind, denial_reason="paywall")

                        self._update_entitlement_cur(cur, user_id, entitlement)
                        meal_plan_id = self._insert_meal_plan_cur(cur, user_id, ration_kind, current_time)
                        ledger_source = _ledger_source_for_consumption(consumption)
                        ledger_event_id = self._insert_event_cur(
                            cur,
                            user_id,
                            LEDGER_EVENT_CONSUME,
                            reason=f"generation:{ration_kind}",
                            delta_generations=_consumption_delta(consumption),
                            meal_plan_id=meal_plan_id,
                            source=ledger_source,
                            amount=_ledger_amount_for_source(ledger_source),
                            metadata={
                                "ration_kind": ration_kind,
                                "attempt_source": consumption.source,
                            },
                        )
                        return AttemptConsumption(
                            True,
                            consumption.ration_kind,
                            consumption.source,
                            meal_plan_id,
                            ledger_event_id=ledger_event_id,
                        )
        except Exception as exc:
            if _is_unique_violation(exc):
                return AttemptConsumption(False, ration_kind, denial_reason="already_generating")
            raise

    def refund_generation_attempt(
        self,
        user_id: int,
        consumption: AttemptConsumption,
        *,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    entitlement = self._select_entitlement_for_update(cur, user_id)
                    if consumption.meal_plan_id is not None:
                        failed = self._update_meal_plan_status_cur(
                            cur,
                            user_id,
                            consumption.meal_plan_id,
                            "failed",
                            error_message=error_message or "generation_failed",
                        )
                        refunded = (
                            self._refund_meal_plan_from_ledger_cur(
                                cur,
                                user_id,
                                entitlement,
                                consumption.meal_plan_id,
                                reason=error_message or "generation_failed",
                            )
                            if failed
                            else False
                        )
                    else:
                        refunded = False
                    self._update_entitlement_cur(cur, user_id, entitlement)
                    if not refunded:
                        self._insert_event_cur(
                            cur,
                            user_id,
                            "generation_refund_skipped",
                            reason=error_message or "generation_failed",
                            metadata={
                                "ration_kind": consumption.ration_kind,
                                "source": consumption.source,
                                "meal_plan_id": consumption.meal_plan_id,
                            },
                        )

    def heartbeat_generation_attempt(
        self,
        user_id: int,
        consumption: AttemptConsumption,
    ) -> bool:
        if consumption.meal_plan_id is None:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE meal_plans
                    SET heartbeat_at = now(),
                        expires_at = now() + %s::interval,
                        updated_at = now()
                    WHERE id = %s
                      AND user_id = %s
                      AND status = ANY(%s)
                    RETURNING id
                    """,
                    (
                        _interval_from_timedelta(GENERATION_STALE_TIMEOUT),
                        consumption.meal_plan_id,
                        user_id,
                        list(ACTIVE_MEAL_PLAN_STATUSES),
                    ),
                )
                return cur.fetchone() is not None

    def start_generation_delivery(
        self,
        user_id: int,
        consumption: AttemptConsumption,
    ) -> bool:
        if consumption.meal_plan_id is None:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE meal_plans
                    SET status = 'delivering',
                        delivery_started_at = COALESCE(delivery_started_at, now()),
                        delivery_attempts = delivery_attempts + 1,
                        heartbeat_at = now(),
                        expires_at = now() + %s::interval,
                        updated_at = now()
                    WHERE id = %s
                      AND user_id = %s
                      AND status = ANY(%s)
                    RETURNING id
                    """,
                    (
                        _interval_from_timedelta(GENERATION_STALE_TIMEOUT),
                        consumption.meal_plan_id,
                        user_id,
                        list(ACTIVE_MEAL_PLAN_STATUSES),
                    ),
                )
                return cur.fetchone() is not None

    def complete_generation_attempt(
        self,
        user_id: int,
        consumption: AttemptConsumption,
        *,
        pdf_path: str | None = None,
        telegram_message_id: int | None = None,
    ) -> None:
        if consumption.meal_plan_id is None:
            return
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE meal_plans
                        SET status = 'completed',
                            pdf_path = COALESCE(%s, pdf_path),
                            telegram_message_id = COALESCE(%s, telegram_message_id),
                            error_message = NULL,
                            delivered_at = COALESCE(delivered_at, now()),
                            finished_at = now(),
                            heartbeat_at = now(),
                            updated_at = now()
                        WHERE id = %s
                          AND user_id = %s
                          AND status = ANY(%s)
                        """,
                        (
                            pdf_path,
                            telegram_message_id,
                            consumption.meal_plan_id,
                            user_id,
                            list(ACTIVE_MEAL_PLAN_STATUSES),
                        ),
                    )

    def cleanup_stale_generations(self, now: datetime | None = None) -> int:
        current_time = _normalize_now(now)
        stale_before = current_time - GENERATION_STALE_TIMEOUT
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT user_id
                    FROM meal_plans
                    WHERE status = ANY(%s)
                      AND (
                          (heartbeat_at IS NOT NULL AND heartbeat_at < %s)
                          OR (
                              heartbeat_at IS NULL
                              AND (
                                  updated_at < %s
                                  OR (expires_at IS NOT NULL AND expires_at <= %s)
                              )
                          )
                      )
                    """,
                    (list(ACTIVE_MEAL_PLAN_STATUSES), stale_before, stale_before, current_time),
                )
                user_ids = [int(row["user_id"]) for row in cur.fetchall()]

        cleaned = 0
        for user_id in user_ids:
            with self._connect() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        entitlement = self._select_entitlement_for_update(cur, user_id)
                        cleaned += self._fail_stale_generations_cur(cur, user_id, entitlement, current_time)
                        self._update_entitlement_cur(cur, user_id, entitlement)
        return cleaned

    def upsert_promo_code(
        self,
        code: str,
        *,
        kind: PromoGrantKind = "subscription_month",
        value: int = 1,
        max_uses: int | None = 1,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        is_active: bool = True,
    ) -> int:
        lookup_key = promo_code_lookup_key(code)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO promo_codes (
                        code,
                        kind,
                        value,
                        max_uses,
                        valid_from,
                        valid_until,
                        is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO UPDATE
                    SET kind = EXCLUDED.kind,
                        value = EXCLUDED.value,
                        max_uses = EXCLUDED.max_uses,
                        valid_from = EXCLUDED.valid_from,
                        valid_until = EXCLUDED.valid_until,
                        is_active = EXCLUDED.is_active
                    RETURNING id
                    """,
                    (
                        lookup_key,
                        kind,
                        value,
                        max_uses,
                        valid_from,
                        valid_until,
                        is_active,
                    ),
                )
                return int(cur.fetchone()["id"])

    def import_promo_record(self, code: str, record: PromoCodeRecord) -> None:
        lookup_key = promo_code_lookup_key(code)
        used_at = _parse_datetime(record.used_at)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO promo_codes (code, kind, value, max_uses, used_count, is_active)
                        VALUES (%s, 'subscription_month', 1, 1, 0, true)
                        ON CONFLICT (code) DO UPDATE
                        SET kind = EXCLUDED.kind,
                            value = EXCLUDED.value,
                            max_uses = EXCLUDED.max_uses,
                            is_active = EXCLUDED.is_active
                        RETURNING id
                        """,
                        (lookup_key,),
                    )
                    promo_id = int(cur.fetchone()["id"])
                    if record.used_by_chat_id is None:
                        return
                    self._upsert_user_cur(cur, record.used_by_chat_id)
                    cur.execute(
                        """
                        INSERT INTO promo_redemptions (promo_code_id, user_id, redeemed_at)
                        VALUES (%s, %s, COALESCE(%s, now()))
                        ON CONFLICT (promo_code_id, user_id) DO NOTHING
                        """,
                        (promo_id, record.used_by_chat_id, used_at),
                    )
                    cur.execute(
                        """
                        UPDATE promo_codes
                        SET used_count = (
                            SELECT count(*)
                            FROM promo_redemptions
                            WHERE promo_code_id = %s
                        )
                        WHERE id = %s
                        """,
                        (promo_id, promo_id),
                    )

    def chat_state_exists(self, chat_id: int) -> bool:
        return self._row_exists("chat_state", "chat_id", chat_id)

    def profile_exists(self, user_id: int) -> bool:
        return self._row_exists("user_profiles", "user_id", user_id)

    def entitlement_exists(self, user_id: int) -> bool:
        return self._row_exists("entitlements", "user_id", user_id)

    def payment_order_exists(self, order_id: str) -> bool:
        return self._row_exists("payment_orders", "order_id", order_id)

    def promo_code_exists(self, code: str) -> bool:
        lookup_key = promo_code_lookup_key(code)
        if not lookup_key:
            return False
        return self._row_exists("promo_codes", "code", lookup_key)

    def processed_payment_charge_exists(self, *, provider: str, charge_id: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._payment_charge_exists_cur(cur, provider=provider, charge_id=charge_id)

    def begin_json_import_run(
        self,
        *,
        migration_id: str,
        source_fingerprint: str,
        source_summary: dict[str, Any],
    ) -> int:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT migration_id
                        FROM import_runs
                        WHERE status = 'applied'
                        ORDER BY id
                        LIMIT 1
                        """
                    )
                    applied = cur.fetchone()
                    if applied is not None:
                        raise RuntimeError(
                            "JSON import has already been applied "
                            f"with migration_id {applied['migration_id']!r}."
                        )
                    cur.execute(
                        "SELECT id, status FROM import_runs WHERE migration_id = %s FOR UPDATE",
                        (migration_id,),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        raise RuntimeError(
                            "JSON import migration_id already recorded "
                            f"with status {existing['status']!r}: {migration_id}"
                        )
                    cur.execute(
                        """
                        INSERT INTO import_runs (
                            migration_id,
                            source_fingerprint,
                            source_summary_json,
                            status
                        )
                        VALUES (%s, %s, %s, 'started')
                        RETURNING id
                        """,
                        (migration_id, source_fingerprint, _jsonb(source_summary)),
                    )
                    return int(cur.fetchone()["id"])

    def finish_json_import_run(self, run_id: int, *, status: str, result: dict[str, Any]) -> None:
        if status not in {"applied", "failed"}:
            raise ValueError(f"Unsupported JSON import run status: {status}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE import_runs
                    SET status = %s,
                        result_json = %s,
                        finished_at = now()
                    WHERE id = %s
                    """,
                    (status, _jsonb(result), run_id),
                )

    @contextmanager
    def json_import_lock(self) -> Iterator[None]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", (JSON_IMPORT_LOCK_ID,))
                row = cur.fetchone()
                if not row or not row["locked"]:
                    raise RuntimeError("Another JSON import is already running.")
            conn.commit()
            try:
                yield
            finally:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (JSON_IMPORT_LOCK_ID,))
                conn.commit()

    def _row_exists(self, table: str, column: str, value: object) -> bool:
        if table not in {
            "chat_state",
            "user_profiles",
            "entitlements",
            "payment_orders",
            "promo_codes",
        }:
            raise ValueError(f"Unsupported existence check table: {table}")
        if column not in {"chat_id", "user_id", "order_id", "code"}:
            raise ValueError(f"Unsupported existence check column: {column}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {column} = %s) AS exists",
                    (value,),
                )
                row = cur.fetchone()
                return bool(row and row["exists"])

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install PostgreSQL driver with `pip install psycopg[binary]`.") from exc
        last_error: Exception | None = None
        for attempt in range(1, self.connect_attempts + 1):
            try:
                return psycopg.connect(
                    self.dsn,
                    row_factory=dict_row,
                    connect_timeout=self.connect_timeout,
                )
            except psycopg.OperationalError as exc:
                last_error = exc
                if attempt >= self.connect_attempts:
                    break
                delay = min(self.retry_max_delay, self.retry_base_delay * (2 ** (attempt - 1)))
                time.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Could not connect to PostgreSQL.")

    def _upsert_user_cur(
        self,
        cur,
        user_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
    ) -> None:
        cur.execute(
            """
            INSERT INTO users (telegram_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE
            SET username = COALESCE(EXCLUDED.username, users.username),
                first_name = COALESCE(EXCLUDED.first_name, users.first_name),
                last_seen_at = now()
            """,
            (user_id, username, first_name),
        )

    def _select_entitlement_for_update(self, cur, user_id: int) -> Entitlement:
        self._upsert_user_cur(cur, user_id)
        cur.execute(
            "INSERT INTO entitlements (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
            (user_id,),
        )
        cur.execute(
            "SELECT * FROM entitlements WHERE user_id = %s FOR UPDATE",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Could not load entitlement row for user {user_id}.")
        return _row_to_entitlement(row)

    def _update_entitlement_cur(self, cur, user_id: int, entitlement: Entitlement) -> None:
        plan, status = _plan_and_status(entitlement)
        cur.execute(
            """
            UPDATE entitlements
            SET plan = %s,
                status = %s,
                subscription_started_at = %s,
                subscription_expires_at = %s,
                monthly_one_day_remaining = %s,
                monthly_weekly_pdf_remaining = %s,
                extra_one_day_remaining = %s,
                extra_weekly_pdf_remaining = %s,
                trial_used = %s,
                trial_started_at = CASE
                    WHEN %s AND trial_started_at IS NULL THEN now()
                    WHEN NOT %s THEN NULL
                    ELSE trial_started_at
                END,
                test_access_enabled = %s,
                test_access_until = %s,
                updated_at = now()
            WHERE user_id = %s
            """,
            (
                plan,
                status,
                _parse_datetime(entitlement.subscription_period_start),
                _parse_datetime(entitlement.subscription_period_end),
                entitlement.monthly_one_day_remaining,
                entitlement.monthly_weekly_pdf_remaining,
                entitlement.extra_one_day_remaining,
                entitlement.extra_weekly_pdf_remaining,
                entitlement.free_trial_used,
                entitlement.free_trial_used,
                entitlement.free_trial_used,
                entitlement.test_access_enabled,
                _parse_datetime(entitlement.test_access_until),
                user_id,
            ),
        )

    def _consume_entitlement_for_ration(
        self,
        entitlement: Entitlement,
        ration_kind: RationKind,
        now: datetime,
    ) -> AttemptConsumption:
        if entitlement.is_test_access_available(now) and not entitlement.test_access_enabled:
            preview_entitlement = replace(
                entitlement,
                subscription_period_start=None,
                subscription_period_end=None,
                monthly_one_day_remaining=0,
                monthly_weekly_pdf_remaining=0,
                extra_one_day_remaining=0,
                extra_weekly_pdf_remaining=0,
                test_access_enabled=False,
            )
            consumption = (
                consume_weekly_pdf_attempt(preview_entitlement, now)
                if ration_kind == "weekly_pdf"
                else consume_one_day_attempt(preview_entitlement, now)
            )
            entitlement.free_trial_used = preview_entitlement.free_trial_used
            return consumption

        return (
            consume_weekly_pdf_attempt(entitlement, now)
            if ration_kind == "weekly_pdf"
            else consume_one_day_attempt(entitlement, now)
        )

    def _active_generation_exists_cur(self, cur, user_id: int) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM meal_plans
            WHERE user_id = %s AND status = ANY(%s)
            LIMIT 1
            """,
            (user_id, list(ACTIVE_MEAL_PLAN_STATUSES)),
        )
        return cur.fetchone() is not None

    def _fail_stale_generations_cur(
        self,
        cur,
        user_id: int,
        entitlement: Entitlement,
        now: datetime,
    ) -> int:
        stale_before = now - GENERATION_STALE_TIMEOUT
        cur.execute(
            """
            SELECT id
            FROM meal_plans
            WHERE user_id = %s
              AND status = ANY(%s)
              AND (
                  (heartbeat_at IS NOT NULL AND heartbeat_at < %s)
                  OR (
                      heartbeat_at IS NULL
                      AND (
                          updated_at < %s
                          OR (expires_at IS NOT NULL AND expires_at <= %s)
                      )
                  )
              )
            FOR UPDATE
            """,
            (user_id, list(ACTIVE_MEAL_PLAN_STATUSES), stale_before, stale_before, now),
        )
        stale_plan_ids = [int(row["id"]) for row in cur.fetchall()]
        cleaned = 0
        for meal_plan_id in stale_plan_ids:
            timed_out = self._update_stale_meal_plan_timeout_cur(
                cur,
                user_id,
                meal_plan_id,
                now,
            )
            if not timed_out:
                continue
            cleaned += 1
            refunded = (
                self._refund_meal_plan_from_ledger_cur(
                    cur,
                    user_id,
                    entitlement,
                    meal_plan_id,
                    reason="generation_timeout",
                )
                if timed_out
                else False
            )
            if not refunded:
                self._insert_event_cur(
                    cur,
                    user_id,
                    "stale_generation_closed_without_ledger_refund",
                    reason="generation_timeout",
                    meal_plan_id=meal_plan_id,
                    metadata={"meal_plan_id": meal_plan_id},
                )
        return cleaned

    def _refund_meal_plan_from_ledger_cur(
        self,
        cur,
        user_id: int,
        entitlement: Entitlement,
        meal_plan_id: int,
        *,
        reason: str,
    ) -> bool:
        cur.execute(
            """
            SELECT *
            FROM entitlement_events
            WHERE meal_plan_id = %s
              AND event_type = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (meal_plan_id, LEDGER_EVENT_CONSUME),
        )
        consume_event = cur.fetchone()
        if not consume_event or consume_event.get("event_type") != LEDGER_EVENT_CONSUME:
            return False

        source = _valid_ledger_source(consume_event.get("source"))
        if source is None:
            return False

        refund_event_id = self._insert_refund_event_cur(
            cur,
            user_id,
            meal_plan_id=meal_plan_id,
            source=source,
            related_event_id=int(consume_event["id"]),
            reason=reason,
        )
        if refund_event_id is None:
            return False

        _refund_entitlement_for_ledger_source(entitlement, source)
        return True

    def _insert_refund_event_cur(
        self,
        cur,
        user_id: int,
        *,
        meal_plan_id: int,
        source: LedgerSource,
        related_event_id: int,
        reason: str,
    ) -> int | None:
        cur.execute(
            """
            INSERT INTO entitlement_events (
                user_id,
                meal_plan_id,
                event_type,
                source,
                amount,
                related_event_id,
                reason,
                delta_generations,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                user_id,
                meal_plan_id,
                LEDGER_EVENT_REFUND,
                source,
                _ledger_amount_for_source(source),
                related_event_id,
                reason,
                _ledger_refund_delta_for_source(source),
                _jsonb({"related_event_id": related_event_id}),
            ),
        )
        row = cur.fetchone()
        return int(row["id"]) if row else None

    def _insert_processed_charge_cur(
        self,
        cur,
        user_id: int,
        *,
        provider: str,
        charge_id: str,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        amount: int | None,
        currency: str | None,
        raw_payload: dict[str, Any],
        status: str,
    ) -> bool:
        if not charge_id:
            return False
        cur.execute(
            """
            INSERT INTO processed_payment_charges (
                provider,
                charge_id,
                telegram_charge_id,
                provider_charge_id,
                user_id,
                amount,
                currency,
                status,
                raw_payload_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider, charge_id) DO UPDATE
            SET telegram_charge_id = COALESCE(EXCLUDED.telegram_charge_id, processed_payment_charges.telegram_charge_id),
                provider_charge_id = COALESCE(EXCLUDED.provider_charge_id, processed_payment_charges.provider_charge_id),
                user_id = EXCLUDED.user_id,
                amount = COALESCE(EXCLUDED.amount, processed_payment_charges.amount),
                currency = COALESCE(EXCLUDED.currency, processed_payment_charges.currency),
                status = EXCLUDED.status,
                raw_payload_json = processed_payment_charges.raw_payload_json || EXCLUDED.raw_payload_json,
                processed_at = now()
            WHERE processed_payment_charges.status <> %s
            RETURNING id
            """,
            (
                provider,
                charge_id,
                telegram_charge_id,
                provider_charge_id,
                user_id,
                amount,
                currency,
                status,
                _jsonb(raw_payload),
                PAYMENT_EVENT_STATUS_PROCESSED,
            ),
        )
        return cur.fetchone() is not None

    def _payment_charge_exists_cur(
        self,
        cur,
        *,
        provider: str,
        charge_id: str,
    ) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM processed_payment_charges
            WHERE provider = %s
              AND status = %s
              AND (
                charge_id = %s
                OR telegram_charge_id = %s
                OR provider_charge_id = %s
              )
            """,
            (provider, PAYMENT_EVENT_STATUS_PROCESSED, charge_id, charge_id, charge_id),
        )
        return cur.fetchone() is not None

    def _lock_processed_charge_cur(
        self,
        cur,
        *,
        provider: str,
        charge_id: str,
    ) -> None:
        cur.execute(
            """
            SELECT id
            FROM processed_payment_charges
            WHERE provider = %s
              AND (
                charge_id = %s
                OR telegram_charge_id = %s
                OR provider_charge_id = %s
              )
            FOR UPDATE
            """,
            (provider, charge_id, charge_id, charge_id),
        )
        cur.fetchone()

    def _insert_payment_event_cur(
        self,
        cur,
        user_id: int,
        *,
        event_type: str,
        provider: str,
        charge_id: str,
        event_id: str | None = None,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        product: str | None = None,
        amount: int | None = None,
        currency: str | None = None,
        status: str,
        reason: str | None = None,
        raw_payload: dict[str, Any],
    ) -> bool:
        if not charge_id:
            return False
        event_id = event_id or _payload_text(raw_payload, "event_id") or f"evt_{uuid.uuid4().hex}"
        telegram_charge_id = telegram_charge_id or _payload_text(raw_payload, "telegram_payment_charge_id")
        provider_charge_id = provider_charge_id or _payload_text(raw_payload, "provider_payment_charge_id")
        cur.execute(
            """
            INSERT INTO payment_events (
                event_id,
                user_id,
                event_type,
                provider,
                charge_id,
                telegram_charge_id,
                provider_charge_id,
                product,
                amount,
                currency,
                status,
                reason,
                raw_payload_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider, charge_id, event_type) DO UPDATE
            SET event_id = COALESCE(payment_events.event_id, EXCLUDED.event_id),
                user_id = EXCLUDED.user_id,
                telegram_charge_id = COALESCE(EXCLUDED.telegram_charge_id, payment_events.telegram_charge_id),
                provider_charge_id = COALESCE(EXCLUDED.provider_charge_id, payment_events.provider_charge_id),
                product = COALESCE(EXCLUDED.product, payment_events.product),
                amount = COALESCE(EXCLUDED.amount, payment_events.amount),
                currency = COALESCE(EXCLUDED.currency, payment_events.currency),
                status = EXCLUDED.status,
                reason = EXCLUDED.reason,
                raw_payload_json = payment_events.raw_payload_json || EXCLUDED.raw_payload_json
            WHERE payment_events.status IN (%s, %s, 'ignored', 'orphan')
            RETURNING id
            """,
            (
                event_id,
                user_id,
                event_type,
                provider,
                charge_id,
                telegram_charge_id,
                provider_charge_id,
                product,
                amount,
                currency,
                status,
                reason,
                _jsonb(raw_payload),
                PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION,
                PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE,
            ),
        )
        return cur.fetchone() is not None

    def _terminal_payment_adjustment_exists_cur(
        self,
        cur,
        *,
        event_type: str,
        provider: str,
        charge_id: str,
    ) -> bool:
        if event_type not in PAYMENT_EVENT_NEGATIVE_TYPES:
            return False
        cur.execute(
            """
            SELECT 1
            FROM payment_events
            WHERE provider = %s
              AND (
                charge_id = %s
                OR telegram_charge_id = %s
                OR provider_charge_id = %s
              )
              AND event_type IN (%s, %s)
              AND status = %s
            LIMIT 1
            """,
            (
                provider,
                charge_id,
                charge_id,
                charge_id,
                PAYMENT_EVENT_REFUND,
                PAYMENT_EVENT_CHARGEBACK,
                PAYMENT_EVENT_STATUS_PROCESSED,
            ),
        )
        return cur.fetchone() is not None

    def _find_successful_payment_product_cur(
        self,
        cur,
        *,
        provider: str,
        charge_id: str,
    ) -> str | None:
        cur.execute(
            """
            SELECT product
            FROM payment_events
            WHERE provider = %s
              AND (
                charge_id = %s
                OR telegram_charge_id = %s
                OR provider_charge_id = %s
              )
              AND event_type = %s
              AND status = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                provider,
                charge_id,
                charge_id,
                charge_id,
                PAYMENT_EVENT_SUCCESSFUL,
                PAYMENT_EVENT_STATUS_PROCESSED,
            ),
        )
        row = cur.fetchone()
        product = _valid_payment_product(row.get("product") if row else None)
        if product is not None:
            return product

        cur.execute(
            """
            SELECT raw_payload_json
            FROM processed_payment_charges
            WHERE provider = %s
              AND (
                charge_id = %s
                OR telegram_charge_id = %s
                OR provider_charge_id = %s
              )
              AND status = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                provider,
                charge_id,
                charge_id,
                charge_id,
                PAYMENT_EVENT_STATUS_PROCESSED,
            ),
        )
        row = cur.fetchone()
        raw_payload = row.get("raw_payload_json") if row else None
        product = _product_from_payment_raw_payload(raw_payload)
        if product is not None:
            return product

        cur.execute(
            """
            SELECT metadata_json
            FROM entitlement_events
            WHERE event_type IN ('payment_applied', 'payment_order_applied')
              AND metadata_json ->> 'provider' = %s
              AND metadata_json ->> 'charge_id' = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (provider, charge_id),
        )
        row = cur.fetchone()
        metadata = row.get("metadata_json") if row else None
        return _product_from_payment_event_metadata(metadata)

    def _insert_orphan_payment_cur(
        self,
        cur,
        user_id: int,
        *,
        provider: str,
        charge_id: str,
        telegram_charge_id: str | None = None,
        provider_charge_id: str | None = None,
        amount: int | None,
        currency: str | None,
        raw_payload: dict[str, Any],
        reason: str,
    ) -> None:
        self._insert_processed_charge_cur(
            cur,
            user_id,
            provider=provider,
            charge_id=charge_id,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            amount=amount,
            currency=currency,
            raw_payload={
                **raw_payload,
                "orphan_reason": reason,
            },
            status=PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE,
        )
        self._insert_payment_event_cur(
            cur,
            user_id,
            event_type=PAYMENT_EVENT_SUCCESSFUL,
            provider=provider,
            charge_id=charge_id,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            amount=amount,
            currency=currency,
            status=PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE,
            reason=reason,
            raw_payload=raw_payload,
        )
        self._insert_event_cur(
            cur,
            user_id,
            "orphan_payment",
            reason=reason,
            metadata={
                "provider": provider,
                "charge_id": charge_id,
                "telegram_charge_id": telegram_charge_id,
                "provider_charge_id": provider_charge_id,
                "amount": amount,
                "currency": currency,
            },
        )

    def _insert_event_cur(
        self,
        cur,
        user_id: int,
        event_type: str,
        *,
        reason: str | None = None,
        delta_generations: int | None = None,
        meal_plan_id: int | None = None,
        source: str | None = None,
        amount: int = 0,
        related_event_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cur.execute(
            """
            INSERT INTO entitlement_events (
                user_id,
                meal_plan_id,
                event_type,
                source,
                amount,
                related_event_id,
                reason,
                delta_generations,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id,
                meal_plan_id,
                event_type,
                source,
                amount,
                related_event_id,
                reason,
                delta_generations,
                _jsonb(metadata or {}),
            ),
        )
        return int(cur.fetchone()["id"])

    def _insert_meal_plan_cur(
        self,
        cur,
        user_id: int,
        ration_kind: RationKind,
        now: datetime,
    ) -> int:
        cur.execute(
            """
            INSERT INTO meal_plans (user_id, plan_type, status, heartbeat_at, expires_at)
            VALUES (%s, %s, 'generating', %s, %s)
            RETURNING id
            """,
            (user_id, ration_kind, now, now + GENERATION_STALE_TIMEOUT),
        )
        return int(cur.fetchone()["id"])

    def _update_meal_plan_status_cur(
        self,
        cur,
        user_id: int,
        meal_plan_id: int,
        status: str,
        *,
        pdf_path: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        cur.execute(
            """
            UPDATE meal_plans
            SET status = %s,
                pdf_path = COALESCE(%s, pdf_path),
                error_message = %s,
                finished_at = CASE
                    WHEN %s <> 'generating' THEN COALESCE(finished_at, now())
                    ELSE finished_at
                END,
                updated_at = now()
            WHERE id = %s AND user_id = %s
              AND status = ANY(%s)
            RETURNING id
            """,
            (
                status,
                pdf_path,
                error_message,
                status,
                meal_plan_id,
                user_id,
                list(ACTIVE_MEAL_PLAN_STATUSES),
            ),
        )
        return cur.fetchone() is not None

    def _update_stale_meal_plan_timeout_cur(
        self,
        cur,
        user_id: int,
        meal_plan_id: int,
        now: datetime,
    ) -> bool:
        stale_before = now - GENERATION_STALE_TIMEOUT
        cur.execute(
            """
            UPDATE meal_plans
            SET status = 'failed_timeout',
                error_message = 'generation timed out',
                finished_at = COALESCE(finished_at, now()),
                updated_at = now()
            WHERE id = %s
              AND user_id = %s
              AND status = ANY(%s)
              AND (
                  (heartbeat_at IS NOT NULL AND heartbeat_at < %s)
                  OR (
                      heartbeat_at IS NULL
                      AND (
                          updated_at < %s
                          OR (expires_at IS NOT NULL AND expires_at <= %s)
                      )
                  )
              )
            RETURNING id
            """,
            (
                meal_plan_id,
                user_id,
                list(ACTIVE_MEAL_PLAN_STATUSES),
                stale_before,
                stale_before,
                now,
            ),
        )
        return cur.fetchone() is not None

    def _apply_payment_grant(
        self,
        entitlement: Entitlement,
        grant: PaymentGrant,
        charge_id: str,
        *,
        subscription_expiration_timestamp: int | None = None,
    ) -> PaymentApplication:
        if grant == "subscription":
            return apply_subscription_payment(
                entitlement,
                charge_id,
                subscription_expiration_timestamp=subscription_expiration_timestamp,
            )
        if grant == "extra_one_day":
            return apply_extra_one_day_payment(entitlement, charge_id)
        if grant == "extra_weekly_pdf":
            return apply_extra_weekly_pdf_payment(entitlement, charge_id)
        return PaymentApplication(False)

    def _apply_promo_grant(
        self,
        entitlement: Entitlement,
        promo: dict[str, Any],
        promo_reference: str,
        now: datetime,
    ) -> None:
        kind = str(promo["kind"])
        value = _positive_int(promo.get("value"), default=1)
        if kind == "extra_one_day":
            apply_extra_one_day_payment(entitlement, f"promo:{promo_reference}")
        elif kind == "extra_weekly_pdf":
            apply_extra_weekly_pdf_payment(entitlement, f"promo:{promo_reference}")
        elif kind == "test_access_days":
            grant_test_access(entitlement, now=now, days=value)
        else:
            apply_subscription_payment(entitlement, f"promo:{promo_reference}", now=now)


def _ledger_source_for_consumption(consumption: AttemptConsumption) -> LedgerSource:
    if consumption.source == "test_access":
        return LEDGER_SOURCE_TEST_ACCESS
    if consumption.source == "free_trial" and consumption.ration_kind == "one_day":
        return LEDGER_SOURCE_FREE_TRIAL_ONE_DAY
    if consumption.source == "monthly" and consumption.ration_kind == "one_day":
        return LEDGER_SOURCE_MONTHLY_ONE_DAY
    if consumption.source == "monthly" and consumption.ration_kind == "weekly_pdf":
        return LEDGER_SOURCE_MONTHLY_WEEKLY_PDF
    if consumption.source == "extra" and consumption.ration_kind == "one_day":
        return LEDGER_SOURCE_EXTRA_ONE_DAY
    if consumption.source == "extra" and consumption.ration_kind == "weekly_pdf":
        return LEDGER_SOURCE_EXTRA_WEEKLY_PDF
    raise ValueError(f"Unsupported consumption source for ledger: {consumption!r}")


def _valid_ledger_source(value: Any) -> LedgerSource | None:
    if value in {
        LEDGER_SOURCE_FREE_TRIAL_ONE_DAY,
        LEDGER_SOURCE_MONTHLY_ONE_DAY,
        LEDGER_SOURCE_MONTHLY_WEEKLY_PDF,
        LEDGER_SOURCE_EXTRA_ONE_DAY,
        LEDGER_SOURCE_EXTRA_WEEKLY_PDF,
        LEDGER_SOURCE_TEST_ACCESS,
    }:
        return value
    return None


def _ledger_amount_for_source(source: LedgerSource) -> int:
    return 0 if source == LEDGER_SOURCE_TEST_ACCESS else 1


def _ledger_refund_delta_for_source(source: LedgerSource) -> int:
    return 0 if source == LEDGER_SOURCE_TEST_ACCESS else 1


def _refund_entitlement_for_ledger_source(entitlement: Entitlement, source: LedgerSource) -> None:
    if source == LEDGER_SOURCE_MONTHLY_ONE_DAY:
        entitlement.monthly_one_day_remaining = min(
            MONTHLY_ONE_DAY_LIMIT,
            entitlement.monthly_one_day_remaining + 1,
        )
    elif source == LEDGER_SOURCE_MONTHLY_WEEKLY_PDF:
        entitlement.monthly_weekly_pdf_remaining = min(
            MONTHLY_WEEKLY_PDF_LIMIT,
            entitlement.monthly_weekly_pdf_remaining + 1,
        )
    elif source == LEDGER_SOURCE_EXTRA_ONE_DAY:
        entitlement.extra_one_day_remaining += 1
    elif source == LEDGER_SOURCE_EXTRA_WEEKLY_PDF:
        entitlement.extra_weekly_pdf_remaining += 1
    elif source == LEDGER_SOURCE_FREE_TRIAL_ONE_DAY:
        entitlement.free_trial_used = False


def _is_unique_violation(exc: Exception) -> bool:
    try:
        import psycopg
    except ImportError:
        return False
    return isinstance(exc, psycopg.errors.UniqueViolation)


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _interval_from_timedelta(value: timedelta) -> str:
    seconds = max(0, int(value.total_seconds()))
    return f"{seconds} seconds"


def _payload_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row_to_entitlement(row: dict[str, Any]) -> Entitlement:
    return Entitlement(
        free_trial_used=bool(row.get("trial_used", False)),
        subscription_period_start=_format_datetime(row.get("subscription_started_at")),
        subscription_period_end=_format_datetime(row.get("subscription_expires_at")),
        test_access_until=_format_datetime(row.get("test_access_until")),
        test_access_enabled=bool(row.get("test_access_enabled", False)),
        monthly_one_day_remaining=_non_negative_int(row.get("monthly_one_day_remaining")),
        monthly_weekly_pdf_remaining=_non_negative_int(row.get("monthly_weekly_pdf_remaining")),
        extra_one_day_remaining=_non_negative_int(row.get("extra_one_day_remaining")),
        extra_weekly_pdf_remaining=_non_negative_int(row.get("extra_weekly_pdf_remaining")),
    )


def _row_to_payment_order(row: dict[str, Any]) -> PaymentOrder | None:
    return PaymentOrder.from_dict(
        {
            "order_id": row.get("order_id"),
            "nonce": row.get("nonce"),
            "user_id": row.get("user_id"),
            "delivery_chat_id": row.get("delivery_chat_id"),
            "product": row.get("product"),
            "provider": row.get("provider"),
            "amount": row.get("amount"),
            "currency": row.get("currency"),
            "status": row.get("status"),
            "is_recurring": row.get("is_recurring"),
            "created_at": _format_datetime(row.get("created_at")),
            "expires_at": _format_datetime(row.get("expires_at")),
            "paid_at": _format_datetime(row.get("paid_at")),
            "invoice_link": row.get("invoice_link"),
        }
    )


def _row_to_payment_event(row: dict[str, Any]) -> PaymentEvent | None:
    return PaymentEvent.from_dict(
        {
            "event_id": row.get("event_id"),
            "event_type": row.get("event_type"),
            "provider": row.get("provider"),
            "charge_id": row.get("charge_id"),
            "telegram_charge_id": row.get("telegram_charge_id"),
            "provider_charge_id": row.get("provider_charge_id"),
            "user_id": row.get("user_id"),
            "product": row.get("product"),
            "amount": row.get("amount"),
            "currency": row.get("currency"),
            "status": row.get("status"),
            "reason": row.get("reason"),
            "raw_payload": row.get("raw_payload_json") or {},
            "created_at": _format_datetime(row.get("created_at")),
        }
    )


def _payment_grant_for_order_product(product: str) -> PaymentGrant:
    if product == "extra_one_day":
        return "extra_one_day"
    if product == "extra_weekly_pdf":
        return "extra_weekly_pdf"
    return "subscription"


def _payment_product_for_grant(grant: PaymentGrant) -> str:
    if grant == "extra_one_day":
        return "extra_one_day"
    if grant == "extra_weekly_pdf":
        return "extra_weekly_pdf"
    return "subscription_month"


def _normalize_payment_event_type(event_type: str) -> str:
    normalized = str(event_type).strip().lower().replace("-", "_")
    if normalized in {
        PAYMENT_EVENT_SUCCESSFUL,
        PAYMENT_EVENT_REFUND,
        PAYMENT_EVENT_CHARGEBACK,
        PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
    }:
        return normalized
    return "unknown"


def _valid_payment_product(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in {"subscription_month", "extra_one_day", "extra_weekly_pdf"}:
        return text
    return None


def _product_from_payment_raw_payload(raw_payload: Any) -> str | None:
    if not isinstance(raw_payload, dict):
        return None
    raw_order = raw_payload.get("payment_order")
    if isinstance(raw_order, dict):
        product = _valid_payment_product(raw_order.get("product"))
        if product is not None:
            return product
    return _valid_payment_product(raw_payload.get("product"))


def _product_from_payment_event_metadata(metadata: Any) -> str | None:
    if not isinstance(metadata, dict):
        return None
    product = _valid_payment_product(metadata.get("product"))
    if product is not None:
        return product
    grant = str(metadata.get("grant") or "").strip()
    if grant in {"subscription", "extra_one_day", "extra_weekly_pdf"}:
        return _payment_product_for_grant(grant)  # type: ignore[arg-type]
    return None


def _payment_event_audit_type(event_type: str) -> str:
    if event_type == PAYMENT_EVENT_REFUND:
        return "payment_refund_applied"
    if event_type == PAYMENT_EVENT_CHARGEBACK:
        return "payment_chargeback_applied"
    if event_type == PAYMENT_EVENT_CANCEL_SUBSCRIPTION:
        return "payment_subscription_cancelled"
    return "payment_event_ignored"


def _payment_order_invalid_reason(
    order: PaymentOrder,
    *,
    user_id: int,
    nonce: str,
    delivery_chat_id: int | None,
    provider: str,
    amount: int | None,
    currency: str | None,
    is_recurring_payment: bool,
    is_first_recurring_payment: bool,
) -> str | None:
    if order.nonce != nonce:
        return "nonce_mismatch"
    if order.user_id != user_id:
        return "user_mismatch"
    if (
        delivery_chat_id is not None
        and order.delivery_chat_id is not None
        and order.delivery_chat_id != delivery_chat_id
    ):
        return "chat_mismatch"
    if order.provider != provider:
        return "provider_mismatch"
    if order.amount != amount:
        return "amount_mismatch"
    if order.currency != currency:
        return "currency_mismatch"
    # Successful payments approved by pre_checkout are accepted even if the order TTL expires
    # before Telegram sends successful_payment. The smoke test
    # test_successful_payment_grants_when_order_expires_after_pre_checkout pins this.
    if order.status == "pending":
        return None
    if _order_accepts_recurring_payment(
        order,
        is_recurring_payment=is_recurring_payment,
        is_first_recurring_payment=is_first_recurring_payment,
    ):
        return None
    return "order_not_pending"


def _order_accepts_recurring_payment(
    order: PaymentOrder,
    *,
    is_recurring_payment: bool,
    is_first_recurring_payment: bool,
) -> bool:
    return (
        order.status == "paid"
        and order.is_recurring
        and order.product == "subscription_month"
        and order.provider == "telegram_stars"
        and is_recurring_payment
        and not is_first_recurring_payment
    )


def _format_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    text = str(value).strip()
    return text or None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_now(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return _normalize_now(datetime.fromisoformat(text))
    except ValueError:
        return None


def _normalize_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _plan_and_status(entitlement: Entitlement) -> tuple[str, str]:
    now = datetime.now(UTC)
    if entitlement.is_subscription_active(now):
        return "monthly", "active"
    if entitlement.is_test_access_active(now):
        return "test_access", "active"
    if entitlement.subscription_period_end:
        return "monthly", "inactive"
    return "free", "inactive"


def _promo_is_active_in_window(promo: dict[str, Any], now: datetime) -> bool:
    if not promo.get("is_active", False):
        return False
    valid_from = _parse_datetime(promo.get("valid_from"))
    valid_until = _parse_datetime(promo.get("valid_until"))
    if valid_from is not None and valid_from > now:
        return False
    if valid_until is not None and valid_until <= now:
        return False
    return True


def _promo_is_exhausted(promo: dict[str, Any]) -> bool:
    max_uses = promo.get("max_uses")
    return max_uses is not None and int(promo.get("used_count") or 0) >= int(max_uses)


def _consumption_delta(consumption: AttemptConsumption) -> int:
    if not consumption.allowed:
        return 0
    if consumption.source in {"monthly", "extra", "free_trial"}:
        return -1
    return 0


def _refund_delta(consumption: AttemptConsumption) -> int:
    if not consumption.allowed:
        return 0
    if consumption.source in {"monthly", "extra", "free_trial"}:
        return 1
    return 0
