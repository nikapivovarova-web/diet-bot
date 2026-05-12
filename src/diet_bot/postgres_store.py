from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from .payments import (
    EXTRA_PAYMENT_PRODUCTS,
    PAYMENT_ORDER_TTL_SECONDS,
    PROVIDER_CURRENCIES,
    PaymentEvent,
    PaymentEventStatus,
    PaymentEventType,
    PaymentCurrency,
    PaymentOrder,
    PaymentOrderCreationCode,
    PaymentOrderCreationResult,
    PaymentOrderStatus,
    PaymentProduct,
    PaymentProvider,
    PaymentSuccessfulPaymentCode,
    PaymentSuccessfulPaymentInput,
    PaymentSuccessfulPaymentResult,
    ProcessedProviderCharge,
    apply_successful_payment as apply_successful_payment_core,
    apply_successful_payment_entitlement,
    build_successful_payment_event,
    successful_payment_canonical_charge_id,
    successful_payment_charge_aliases,
    validate_successful_payment_order,
)
from .postgres_migrations import run_postgres_migrations
from .promo_codes import PromoCodeActivation, PromoCodeRecord, normalize_promo_code
from .subscriptions import (
    AttemptConsumption,
    Entitlement,
    RationKind,
    SUBSCRIPTION_PERIOD_SECONDS,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_subscription_payment,
    consume_one_day_attempt,
    consume_weekly_pdf_attempt,
    grant_test_access,
    refund_attempt,
)
from .storage import SupportState, UserIdentity


GENERATION_STALE_TIMEOUT = timedelta(minutes=30)
ACTIVE_GENERATION_STATUSES = ("generating", "delivering")
LEDGER_EVENT_CONSUME = "consume"
LEDGER_EVENT_REFUND = "refund"
LEDGER_EVENT_ENTITLEMENT_SNAPSHOT = "entitlement_snapshot"


class PostgresDietBotStore:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = 5,
        statement_timeout_ms: int = 5000,
        lock_timeout_ms: int = 1000,
        connect_attempts: int = 1,
    ) -> None:
        self.dsn = dsn
        self.connect_timeout = _positive_int(connect_timeout, name="connect_timeout")
        self.statement_timeout_ms = _positive_int(
            statement_timeout_ms,
            name="statement_timeout_ms",
        )
        self.lock_timeout_ms = _positive_int(lock_timeout_ms, name="lock_timeout_ms")
        self.connect_attempts = _positive_int(connect_attempts, name="connect_attempts")

    def initialize(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                run_postgres_migrations(cur)

    def healthcheck(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
        if row is None or int(row["ok"]) != 1:
            raise RuntimeError("PostgreSQL healthcheck failed")

    def remember_user(self, user: UserIdentity) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, user)

    def load_profile_data(self, user_id: int) -> dict[str, object] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT profile_json FROM profiles WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        profile = row["profile_json"]
        return dict(profile) if isinstance(profile, dict) else None

    def save_profile_data(self, user_id: int, profile_data: dict[str, object]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(user_id))
                cur.execute(
                    """
                    INSERT INTO profiles (user_id, profile_json)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET profile_json = EXCLUDED.profile_json,
                        updated_at = now()
                    """,
                    (user_id, _jsonb(profile_data)),
                )

    def load_chat_state(self, chat_id: int) -> dict[str, object]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state_json FROM chat_state WHERE chat_id = %s",
                    (chat_id,),
                )
                row = cur.fetchone()
        if row is None:
            return {}
        state = row["state_json"]
        return dict(state) if isinstance(state, dict) else {}

    def save_chat_state(self, chat_id: int, state: dict[str, object]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(chat_id))
                cur.execute(
                    """
                    INSERT INTO chat_state (chat_id, state_json)
                    VALUES (%s, %s)
                    ON CONFLICT (chat_id) DO UPDATE
                    SET state_json = EXCLUDED.state_json,
                        updated_at = now()
                    """,
                    (chat_id, _jsonb(state)),
                )

    def get_entitlement(self, user_id: int) -> Entitlement:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM entitlements WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                processed_charge_ids = self._load_processed_charge_ids_cur(cur, user_id)
        if row is None:
            return Entitlement()
        entitlement = _row_to_entitlement(row)
        entitlement.processed_payment_charge_ids = processed_charge_ids
        return entitlement

    def save_entitlement(self, user_id: int, entitlement: Entitlement) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(user_id))
                self._upsert_entitlement_cur(cur, user_id, entitlement)
                self._insert_entitlement_snapshot_cur(cur, user_id, entitlement)

    def consume_generation_attempt(
        self,
        user_id: int,
        ration_kind: RationKind,
    ) -> AttemptConsumption:
        current_time = datetime.now(UTC)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    entitlement = self._select_entitlement_for_update_cur(cur, user_id)
                    self._fail_stale_generations_cur(cur, user_id, entitlement, current_time)

                    if self._active_generation_exists_cur(cur, user_id):
                        self._update_entitlement_cur(cur, user_id, entitlement)
                        return AttemptConsumption(False, ration_kind)

                    consumption = _consume_entitlement_for_ration(
                        entitlement,
                        ration_kind,
                        current_time,
                    )
                    if not consumption.allowed:
                        self._update_entitlement_cur(cur, user_id, entitlement)
                        return consumption

                    self._update_entitlement_cur(cur, user_id, entitlement)
                    generation_id = self._insert_generation_cur(
                        cur,
                        user_id,
                        ration_kind,
                        current_time,
                    )
                    event_id = self._insert_entitlement_event_cur(
                        cur,
                        user_id,
                        LEDGER_EVENT_CONSUME,
                        generation_id=generation_id,
                        source=consumption.source,
                        amount=_event_amount(consumption),
                        delta_generations=_consume_delta(consumption),
                        metadata={
                            "ration_kind": ration_kind,
                            "attempt_source": consumption.source,
                        },
                    )
                    cur.execute(
                        """
                        UPDATE generation_records
                        SET entitlement_event_id = %s,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (event_id, generation_id),
                    )
                    return _with_generation_metadata(consumption, generation_id, event_id)
        except Exception as exc:
            if _is_unique_violation(exc):
                return AttemptConsumption(False, ration_kind)
            raise

    def heartbeat_generation_attempt(
        self,
        user_id: int,
        consumption: AttemptConsumption,
    ) -> bool:
        if not consumption.allowed:
            return False
        generation_id = _generation_id_from_consumption(consumption)
        with self._connect() as conn:
            with conn.cursor() as cur:
                generation = self._select_generation_for_consumption_cur(
                    cur,
                    user_id,
                    consumption,
                    generation_id=generation_id,
                    active_only=True,
                )
                if generation is None:
                    return False
                cur.execute(
                    """
                    UPDATE generation_records
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
                        generation["id"],
                        user_id,
                        list(ACTIVE_GENERATION_STATUSES),
                    ),
                )
                return cur.fetchone() is not None

    def start_generation_delivery(
        self,
        user_id: int,
        consumption: AttemptConsumption,
    ) -> bool:
        if not consumption.allowed:
            return False
        generation_id = _generation_id_from_consumption(consumption)
        with self._connect() as conn:
            with conn.cursor() as cur:
                generation = self._select_generation_for_consumption_cur(
                    cur,
                    user_id,
                    consumption,
                    generation_id=generation_id,
                    active_only=True,
                )
                if generation is None:
                    return False
                cur.execute(
                    """
                    UPDATE generation_records
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
                        generation["id"],
                        user_id,
                        list(ACTIVE_GENERATION_STATUSES),
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
        if not consumption.allowed:
            return
        generation_id = _generation_id_from_consumption(consumption)
        with self._connect() as conn:
            with conn.cursor() as cur:
                generation = self._select_generation_for_consumption_cur(
                    cur,
                    user_id,
                    consumption,
                    generation_id=generation_id,
                    active_only=True,
                )
                if generation is None:
                    return
                cur.execute(
                    """
                    UPDATE generation_records
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
                        generation["id"],
                        user_id,
                        list(ACTIVE_GENERATION_STATUSES),
                    ),
                )

    def refund_generation_attempt(
        self,
        user_id: int,
        consumption: AttemptConsumption,
        *,
        error_message: str | None = None,
    ) -> None:
        if not consumption.allowed:
            return
        generation_id = _generation_id_from_consumption(consumption)
        with self._connect() as conn:
            with conn.cursor() as cur:
                entitlement = self._select_entitlement_for_update_cur(cur, user_id)
                generation = self._select_generation_for_consumption_cur(
                    cur,
                    user_id,
                    consumption,
                    generation_id=generation_id,
                    active_only=False,
                )
                if generation is None or generation["status"] not in ACTIVE_GENERATION_STATUSES:
                    return
                cur.execute(
                    """
                    UPDATE generation_records
                    SET status = 'failed',
                        error_message = %s,
                        finished_at = now(),
                        updated_at = now()
                    WHERE id = %s
                      AND user_id = %s
                      AND status = ANY(%s)
                    RETURNING id
                    """,
                    (
                        error_message or "generation_failed",
                        generation["id"],
                        user_id,
                        list(ACTIVE_GENERATION_STATUSES),
                    ),
                )
                if cur.fetchone() is None:
                    return
                self._refund_generation_from_event_cur(
                    cur,
                    user_id,
                    entitlement,
                    int(generation["id"]),
                    reason=error_message or "generation_failed",
                )
                self._update_entitlement_cur(cur, user_id, entitlement)

    def cleanup_stale_generations(self, now: datetime | None = None) -> int:
        current_time = _normalize_datetime(now)
        stale_before = current_time - GENERATION_STALE_TIMEOUT
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT user_id
                    FROM generation_records
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
                    (
                        list(ACTIVE_GENERATION_STATUSES),
                        stale_before,
                        stale_before,
                        current_time,
                    ),
                )
                user_ids = [int(row["user_id"]) for row in cur.fetchall()]

        cleaned = 0
        for stale_user_id in user_ids:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    entitlement = self._select_entitlement_for_update_cur(cur, stale_user_id)
                    cleaned += self._fail_stale_generations_cur(
                        cur,
                        stale_user_id,
                        entitlement,
                        current_time,
                    )
                    self._update_entitlement_cur(cur, stale_user_id, entitlement)
        return cleaned

    def upsert_promo_code(self, code: str, record: PromoCodeRecord) -> None:
        normalized_code = normalize_promo_code(code)
        if not normalized_code:
            raise ValueError("Promo code must not be empty")

        used_by_chat_id = record.used_by_chat_id if record.is_used() else None
        used_at = _parse_datetime(record.used_at)
        with self._connect() as conn:
            with conn.cursor() as cur:
                if used_by_chat_id is not None:
                    self._remember_user_cur(cur, UserIdentity(used_by_chat_id))
                cur.execute(
                    """
                    INSERT INTO promo_codes (code, kind, value, max_uses, used_count, is_active)
                    VALUES (%s, 'subscription_month', 1, 1, %s, true)
                    ON CONFLICT (code) DO UPDATE
                    SET used_count = GREATEST(promo_codes.used_count, EXCLUDED.used_count),
                        is_active = true
                    RETURNING id
                    """,
                    (normalized_code, 1 if used_by_chat_id is not None else 0),
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("Could not upsert promo code.")
                if used_by_chat_id is None:
                    return
                cur.execute(
                    """
                    INSERT INTO promo_redemptions (promo_code_id, user_id, redeemed_at)
                    VALUES (%s, %s, COALESCE(%s, now()))
                    ON CONFLICT (promo_code_id, user_id) DO NOTHING
                    """,
                    (int(row["id"]), used_by_chat_id, used_at),
                )

    def activate_promo_code(self, user_id: int, raw_code: str) -> PromoCodeActivation:
        code = normalize_promo_code(raw_code)
        if not code:
            return PromoCodeActivation("not_found", "")

        current_time = datetime.now(UTC)
        with self._connect() as conn:
            with conn.cursor() as cur:
                entitlement = self._select_entitlement_for_update_cur(cur, user_id)
                cur.execute(
                    """
                    SELECT *
                    FROM promo_codes
                    WHERE code = %s
                      AND is_active = true
                      AND (valid_from IS NULL OR valid_from <= %s)
                      AND (valid_until IS NULL OR valid_until > %s)
                    FOR UPDATE
                    """,
                    (code, current_time, current_time),
                )
                promo = cur.fetchone()
                if promo is None:
                    return PromoCodeActivation("not_found", code)

                promo_id = int(promo["id"])
                cur.execute(
                    """
                    SELECT 1
                    FROM promo_redemptions
                    WHERE promo_code_id = %s
                      AND user_id = %s
                    LIMIT 1
                    """,
                    (promo_id, user_id),
                )
                if cur.fetchone() is not None:
                    return PromoCodeActivation("already_used", code, user_id)

                used_count = _non_negative_int(promo.get("used_count"))
                max_uses = promo.get("max_uses")
                if max_uses is not None and used_count >= _non_negative_int(max_uses):
                    return PromoCodeActivation(
                        "already_used",
                        code,
                        self._first_promo_redeemer_cur(cur, promo_id),
                    )

                cur.execute(
                    """
                    INSERT INTO promo_redemptions (promo_code_id, user_id)
                    VALUES (%s, %s)
                    """,
                    (promo_id, user_id),
                )
                cur.execute(
                    """
                    UPDATE promo_codes
                    SET used_count = used_count + 1
                    WHERE id = %s
                    """,
                    (promo_id,),
                )
                self._apply_promo_grant_cur(cur, user_id, entitlement, promo, code, current_time)
                self._update_entitlement_cur(cur, user_id, entitlement)
                self._insert_entitlement_snapshot_cur(cur, user_id, entitlement)
                return PromoCodeActivation("activated", code, user_id)

    def record_support_state(self, state: SupportState) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(state.user_id))
                cur.execute(
                    """
                    INSERT INTO support_state (
                        user_id,
                        status,
                        last_request_at,
                        last_admin_message_id,
                        metadata_json
                    )
                    VALUES (%s, %s, %s, %s, '{}'::jsonb)
                    ON CONFLICT (user_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        last_request_at = EXCLUDED.last_request_at,
                        last_admin_message_id = EXCLUDED.last_admin_message_id,
                        metadata_json = '{}'::jsonb,
                        updated_at = now()
                    """,
                    (
                        state.user_id,
                        state.status,
                        _parse_datetime(state.last_request_at),
                        state.last_admin_message_id,
                    ),
                )

    def load_support_state(self, user_id: int) -> SupportState | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, status, last_request_at, last_admin_message_id
                    FROM support_state
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return SupportState(
            user_id=int(row["user_id"]),
            status=str(row["status"]),
            last_request_at=_normalize_datetime(row["last_request_at"]) if row["last_request_at"] else None,
            last_admin_message_id=(
                int(row["last_admin_message_id"])
                if row["last_admin_message_id"] is not None
                else None
            ),
        )

    def create_payment_order(
        self,
        *,
        order_id: str,
        nonce: str,
        user_id: int,
        delivery_chat_id: int | None,
        product: str,
        provider: str,
        amount: int,
        currency: str,
        expires_at: datetime,
    ) -> PaymentOrder:
        created_at = datetime.now(UTC)
        order = PaymentOrder(
            order_id=order_id,
            nonce=nonce,
            user_id=user_id,
            delivery_chat_id=delivery_chat_id,
            product=product,
            provider=provider,
            amount=amount,
            currency=currency,
            status=PaymentOrderStatus.PENDING,
            created_at=created_at,
            expires_at=_normalize_datetime(expires_at),
            updated_at=created_at,
        )
        return self.insert_payment_order(order)

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
        ttl_seconds: int = PAYMENT_ORDER_TTL_SECONDS,
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(user_id))
                cur.execute("SELECT 1 FROM users WHERE telegram_id = %s FOR UPDATE", (user_id,))
                if requires_active_subscription:
                    entitlement = self._select_entitlement_for_update_cur(cur, user_id)
                    if not entitlement.is_subscription_active(current_time):
                        return PaymentOrderCreationResult(
                            accepted=False,
                            code=PaymentOrderCreationCode.ACTIVE_SUBSCRIPTION_REQUIRED,
                            message="Active subscription is required for this extra.",
                            requires_active_subscription=True,
                        )
                existing = self._find_active_pending_payment_order_cur(
                    cur,
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
                    order_id=_payment_token(),
                    nonce=_payment_token(),
                    user_id=user_id,
                    delivery_chat_id=delivery_chat_id,
                    product=product_value,
                    provider=provider_value,
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
                    order=self._insert_payment_order_cur(cur, order),
                    requires_active_subscription=requires_active_subscription,
                )

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
    ) -> PaymentOrder | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._find_active_pending_payment_order_cur(
                    cur,
                    user_id=user_id,
                    delivery_chat_id=delivery_chat_id,
                    provider=provider,
                    product=product,
                    amount=amount,
                    currency=currency,
                    now=now,
                )

    def insert_payment_order(self, order: PaymentOrder) -> PaymentOrder:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(order.user_id))
                return self._insert_payment_order_cur(cur, order)

    def load_payment_order(self, order_id: str) -> PaymentOrder | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM payment_orders WHERE order_id = %s", (order_id,))
                row = cur.fetchone()
        return _row_to_payment_order(row) if row is not None else None

    def mark_payment_order_invoice_link(self, order_id: str, invoice_link: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payment_orders
                    SET invoice_link = %s,
                        updated_at = now()
                    WHERE order_id = %s
                    """,
                    (invoice_link, order_id),
                )

    def record_payment_order_pre_checkout_approved(
        self,
        order_id: str,
        approved_at: datetime | None = None,
    ) -> PaymentOrder | None:
        approved_at_value = _normalize_datetime(approved_at)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payment_orders
                    SET pre_checkout_approved_at = COALESCE(pre_checkout_approved_at, %s),
                        updated_at = now()
                    WHERE order_id = %s
                      AND status = 'pending'
                    RETURNING *
                    """,
                    (approved_at_value, order_id),
                )
                row = cur.fetchone()
        return _row_to_payment_order(row) if row is not None else None

    def mark_payment_order_expired(self, order_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payment_orders
                    SET status = 'expired',
                        updated_at = now()
                    WHERE order_id = %s
                    """,
                    (order_id,),
                )

    def mark_payment_order_invoice_creation_failed(self, order_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payment_orders
                    SET status = 'failed_invoice_creation',
                        updated_at = now()
                    WHERE order_id = %s
                    """,
                    (order_id,),
                )

    def apply_successful_payment(
        self,
        successful_payment: PaymentSuccessfulPaymentInput,
        *,
        now: datetime | None = None,
    ) -> PaymentSuccessfulPaymentResult:
        return apply_successful_payment_core(self, successful_payment, now=now)

    def apply_successful_payment_transaction(
        self,
        successful_payment: PaymentSuccessfulPaymentInput,
        *,
        order_id: str,
        nonce: str,
        now: datetime,
    ) -> PaymentSuccessfulPaymentResult:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._apply_successful_payment_transaction_cur(
                    cur,
                    successful_payment,
                    order_id=order_id,
                    nonce=nonce,
                    now=now,
                )

    def insert_payment_event(self, event: PaymentEvent) -> PaymentEvent:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._insert_payment_event_cur(cur, event)

    def _apply_successful_payment_transaction_cur(
        self,
        cur: Any,
        successful_payment: PaymentSuccessfulPaymentInput,
        *,
        order_id: str,
        nonce: str,
        now: datetime,
    ) -> PaymentSuccessfulPaymentResult:
        charge_aliases = successful_payment_charge_aliases(successful_payment)
        cur.execute(
            "SELECT * FROM payment_orders WHERE order_id = %s FOR UPDATE",
            (order_id,),
        )
        order_row = cur.fetchone()
        if order_row is None:
            event = build_successful_payment_event(
                successful_payment,
                code=PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND,
                event_status=PaymentEventStatus.ORPHAN_RECOVERABLE,
                order_id=order_id,
                reason=PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND.value,
                now=now,
            )
            self._insert_payment_event_cur(cur, event)
            return PaymentSuccessfulPaymentResult(
                processed=False,
                code=PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND,
                event=event,
                charge_aliases=charge_aliases,
                message="Payment order was not found.",
            )

        order = _row_to_payment_order(order_row)
        existing_processed_charges = self._load_processed_provider_charges_cur(
            cur,
            provider=successful_payment.provider,
            charge_aliases=charge_aliases,
        )
        entitlement = self._select_entitlement_for_update_cur(cur, order.user_id)
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
                return self._process_successful_payment_cur(
                    cur,
                    successful_payment,
                    order,
                    entitlement,
                    charge_aliases=charge_aliases,
                    canonical_charge_id=canonical_charge_id,
                    now=now,
                )

        event = build_successful_payment_event(
            successful_payment,
            code=code,
            event_status=_payment_event_status_for_successful_payment_code(code),
            order=order,
            reason=None if code == PaymentSuccessfulPaymentCode.DUPLICATE else code.value,
            now=now,
        )
        self._insert_payment_event_cur(cur, event)
        return PaymentSuccessfulPaymentResult(
            processed=False,
            code=code,
            order=order,
            event=event,
            duplicate=code == PaymentSuccessfulPaymentCode.DUPLICATE,
            charge_aliases=charge_aliases,
            message=None if code == PaymentSuccessfulPaymentCode.DUPLICATE else "Payment was rejected.",
        )

    def _process_successful_payment_cur(
        self,
        cur: Any,
        successful_payment: PaymentSuccessfulPaymentInput,
        order: PaymentOrder,
        entitlement: Entitlement,
        *,
        charge_aliases: tuple[str, ...],
        canonical_charge_id: str,
        now: datetime,
    ) -> PaymentSuccessfulPaymentResult:
        reserved_charges: list[ProcessedProviderCharge] = []
        for charge_alias in charge_aliases:
            charge = ProcessedProviderCharge(
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
            stored_charge, inserted = self._insert_processed_provider_charge_cur(cur, charge)
            if inserted:
                reserved_charges.append(stored_charge)
                continue

            for reserved in reserved_charges:
                cur.execute(
                    """
                    DELETE FROM processed_provider_charges
                    WHERE provider = %s
                      AND charge_id = %s
                      AND event_type = %s
                      AND order_id = %s
                    """,
                    (
                        reserved.provider.value,
                        reserved.charge_id,
                        reserved.event_type.value,
                        order.order_id,
                    ),
                )

            duplicate = (
                stored_charge.order_id == order.order_id
                and stored_charge.provider == order.provider
                and stored_charge.event_type == PaymentEventType.SUCCESSFUL_PAYMENT
            )
            code = (
                PaymentSuccessfulPaymentCode.DUPLICATE
                if duplicate
                else PaymentSuccessfulPaymentCode.CHARGE_ALIAS_CONFLICT
            )
            event = build_successful_payment_event(
                successful_payment,
                code=code,
                event_status=_payment_event_status_for_successful_payment_code(code),
                order=order,
                reason=None if duplicate else code.value,
                now=now,
            )
            self._insert_payment_event_cur(cur, event)
            return PaymentSuccessfulPaymentResult(
                processed=False,
                code=code,
                order=order,
                event=event,
                duplicate=duplicate,
                charge_aliases=charge_aliases,
                message=None if duplicate else "Payment was rejected.",
            )

        application = apply_successful_payment_entitlement(
            entitlement,
            order,
            successful_payment,
            charge_id=canonical_charge_id,
            now=now,
        )
        if not application.processed:
            event = build_successful_payment_event(
                successful_payment,
                code=PaymentSuccessfulPaymentCode.DUPLICATE,
                event_status=PaymentEventStatus.DUPLICATE,
                order=order,
                now=now,
            )
            self._insert_payment_event_cur(cur, event)
            return PaymentSuccessfulPaymentResult(
                processed=False,
                code=PaymentSuccessfulPaymentCode.DUPLICATE,
                order=order,
                event=event,
                duplicate=True,
                charge_aliases=charge_aliases,
            )

        event = build_successful_payment_event(
            successful_payment,
            code=PaymentSuccessfulPaymentCode.PROCESSED,
            event_status=PaymentEventStatus.PROCESSED,
            order=order,
            now=now,
        )
        self._insert_payment_event_cur(cur, event)
        self._update_entitlement_cur(cur, order.user_id, entitlement)
        self._insert_entitlement_snapshot_cur(cur, order.user_id, entitlement)
        paid_order = self._mark_payment_order_paid_cur(cur, order.order_id, now) or order
        return PaymentSuccessfulPaymentResult(
            processed=True,
            code=PaymentSuccessfulPaymentCode.PROCESSED,
            order=paid_order,
            event=event,
            charge_aliases=charge_aliases,
        )

    def _load_processed_provider_charges_cur(
        self,
        cur: Any,
        *,
        provider: PaymentProvider,
        charge_aliases: tuple[str, ...],
    ) -> dict[str, ProcessedProviderCharge]:
        if not charge_aliases:
            return {}
        cur.execute(
            """
            SELECT *
            FROM processed_provider_charges
            WHERE provider = %s
              AND event_type = %s
              AND charge_id = ANY(%s)
            FOR UPDATE
            """,
            (
                provider.value,
                PaymentEventType.SUCCESSFUL_PAYMENT.value,
                list(charge_aliases),
            ),
        )
        return {
            str(row["charge_id"]): _row_to_processed_provider_charge(row)
            for row in cur.fetchall()
        }

    def _insert_payment_event_cur(self, cur: Any, event: PaymentEvent) -> PaymentEvent:
        cur.execute(
            """
            INSERT INTO payment_events (
                event_id,
                event_type,
                provider,
                order_id,
                charge_id,
                telegram_charge_id,
                provider_charge_id,
                user_id,
                delivery_chat_id,
                product,
                amount,
                currency,
                status,
                reason,
                raw_payload_redacted,
                created_at,
                processed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                event.event_id,
                event.event_type.value,
                event.provider.value,
                event.order_id,
                event.charge_id,
                event.telegram_charge_id,
                event.provider_charge_id,
                event.user_id,
                event.delivery_chat_id,
                event.product.value if event.product is not None else None,
                event.amount,
                event.currency.value if event.currency is not None else None,
                event.status.value,
                event.reason,
                _jsonb(event.raw_payload_redacted),
                _normalize_datetime(event.created_at),
                (
                    _normalize_datetime(event.processed_at)
                    if event.processed_at is not None
                    else None
                ),
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Could not create payment event.")
        return _row_to_payment_event(row)

    def _insert_processed_provider_charge_cur(
        self,
        cur: Any,
        charge: ProcessedProviderCharge,
    ) -> tuple[ProcessedProviderCharge, bool]:
        cur.execute(
            """
            INSERT INTO processed_provider_charges (
                provider,
                charge_id,
                telegram_charge_id,
                provider_charge_id,
                order_id,
                event_type,
                user_id,
                product,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider, charge_id, event_type) DO NOTHING
            RETURNING *
            """,
            (
                charge.provider.value,
                charge.charge_id,
                charge.telegram_charge_id,
                charge.provider_charge_id,
                charge.order_id,
                charge.event_type.value,
                charge.user_id,
                charge.product.value if charge.product is not None else None,
                _normalize_datetime(charge.created_at),
            ),
        )
        row = cur.fetchone()
        if row is not None:
            return _row_to_processed_provider_charge(row), True

        cur.execute(
            """
            SELECT *
            FROM processed_provider_charges
            WHERE provider = %s
              AND charge_id = %s
              AND event_type = %s
            FOR UPDATE
            """,
            (charge.provider.value, charge.charge_id, charge.event_type.value),
        )
        existing = cur.fetchone()
        if existing is None:
            raise RuntimeError("Could not read processed provider charge conflict.")
        return _row_to_processed_provider_charge(existing), False

    def _mark_payment_order_paid_cur(
        self,
        cur: Any,
        order_id: str,
        paid_at: datetime,
    ) -> PaymentOrder | None:
        cur.execute(
            """
            UPDATE payment_orders
            SET status = 'paid',
                paid_at = COALESCE(paid_at, %s),
                updated_at = now()
            WHERE order_id = %s
              AND status = 'pending'
            RETURNING *
            """,
            (_normalize_datetime(paid_at), order_id),
        )
        row = cur.fetchone()
        return _row_to_payment_order(row) if row is not None else None

    def _find_active_pending_payment_order_cur(
        self,
        cur: Any,
        *,
        user_id: int,
        delivery_chat_id: int | None,
        provider: PaymentProvider,
        product: PaymentProduct,
        amount: int,
        currency: PaymentCurrency,
        now: datetime,
    ) -> PaymentOrder | None:
        cur.execute(
            """
            SELECT *
            FROM payment_orders
            WHERE user_id = %s
              AND delivery_chat_id IS NOT DISTINCT FROM %s
              AND provider = %s
              AND product = %s
              AND amount = %s
              AND currency = %s
              AND status = 'pending'
              AND expires_at > %s
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (
                user_id,
                delivery_chat_id,
                provider.value,
                product.value,
                amount,
                currency.value,
                _normalize_datetime(now),
            ),
        )
        row = cur.fetchone()
        return _row_to_payment_order(row) if row is not None else None

    def _insert_payment_order_cur(self, cur: Any, order: PaymentOrder) -> PaymentOrder:
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
                invoice_link,
                pre_checkout_approved_at,
                created_at,
                expires_at,
                paid_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                order.order_id,
                order.nonce,
                order.user_id,
                order.delivery_chat_id,
                order.product.value,
                order.provider.value,
                order.amount,
                order.currency.value,
                order.status.value,
                order.invoice_link,
                (
                    _normalize_datetime(order.pre_checkout_approved_at)
                    if order.pre_checkout_approved_at is not None
                    else None
                ),
                _normalize_datetime(order.created_at),
                _normalize_datetime(order.expires_at),
                _normalize_datetime(order.paid_at) if order.paid_at is not None else None,
                _normalize_datetime(order.updated_at),
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Could not create payment order.")
        return _row_to_payment_order(row)

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        last_error: Exception | None = None
        for _attempt in range(self.connect_attempts):
            try:
                conn = psycopg.connect(
                    self.dsn,
                    connect_timeout=self.connect_timeout,
                    row_factory=dict_row,
                )
                self._configure_connection(conn)
                return conn
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise RuntimeError("PostgreSQL connection was not attempted")

    def _configure_connection(self, conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (f"{self.statement_timeout_ms}ms",),
            )
            cur.execute(
                "SELECT set_config('lock_timeout', %s, false)",
                (f"{self.lock_timeout_ms}ms",),
            )

    def _remember_user_cur(self, cur: Any, user: UserIdentity) -> None:
        cur.execute(
            """
            INSERT INTO users (telegram_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_seen_at = now()
            """,
            (user.telegram_id, user.username, user.first_name),
        )

    def _select_entitlement_for_update_cur(self, cur: Any, user_id: int) -> Entitlement:
        self._remember_user_cur(cur, UserIdentity(user_id))
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

    def _upsert_entitlement_cur(
        self,
        cur: Any,
        user_id: int,
        entitlement: Entitlement,
    ) -> None:
        plan, status = _plan_and_status(entitlement)
        cur.execute(
            """
            INSERT INTO entitlements (
                user_id,
                plan,
                status,
                subscription_period_start,
                subscription_period_end,
                test_access_until,
                test_access_enabled,
                free_trial_used,
                monthly_one_day_remaining,
                monthly_weekly_pdf_remaining,
                extra_one_day_remaining,
                extra_weekly_pdf_remaining
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
            SET plan = EXCLUDED.plan,
                status = EXCLUDED.status,
                subscription_period_start = EXCLUDED.subscription_period_start,
                subscription_period_end = EXCLUDED.subscription_period_end,
                test_access_until = EXCLUDED.test_access_until,
                test_access_enabled = EXCLUDED.test_access_enabled,
                free_trial_used = EXCLUDED.free_trial_used,
                monthly_one_day_remaining = EXCLUDED.monthly_one_day_remaining,
                monthly_weekly_pdf_remaining = EXCLUDED.monthly_weekly_pdf_remaining,
                extra_one_day_remaining = EXCLUDED.extra_one_day_remaining,
                extra_weekly_pdf_remaining = EXCLUDED.extra_weekly_pdf_remaining,
                updated_at = now()
            """,
            (
                user_id,
                plan,
                status,
                _parse_datetime(entitlement.subscription_period_start),
                _parse_datetime(entitlement.subscription_period_end),
                _parse_datetime(entitlement.test_access_until),
                entitlement.test_access_enabled,
                entitlement.free_trial_used,
                entitlement.monthly_one_day_remaining,
                entitlement.monthly_weekly_pdf_remaining,
                entitlement.extra_one_day_remaining,
                entitlement.extra_weekly_pdf_remaining,
            ),
        )

    def _update_entitlement_cur(self, cur: Any, user_id: int, entitlement: Entitlement) -> None:
        self._upsert_entitlement_cur(cur, user_id, entitlement)

    def _active_generation_exists_cur(self, cur: Any, user_id: int) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM generation_records
            WHERE user_id = %s
              AND status = ANY(%s)
            LIMIT 1
            """,
            (user_id, list(ACTIVE_GENERATION_STATUSES)),
        )
        return cur.fetchone() is not None

    def _insert_generation_cur(
        self,
        cur: Any,
        user_id: int,
        ration_kind: RationKind,
        now: datetime,
    ) -> int:
        cur.execute(
            """
            INSERT INTO generation_records (
                user_id,
                ration_kind,
                status,
                heartbeat_at,
                expires_at
            )
            VALUES (%s, %s, 'generating', %s, %s)
            RETURNING id
            """,
            (user_id, ration_kind, now, now + GENERATION_STALE_TIMEOUT),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Could not create generation record.")
        return int(row["id"])

    def _insert_entitlement_event_cur(
        self,
        cur: Any,
        user_id: int,
        event_type: str,
        *,
        generation_id: int | None = None,
        source: str | None = None,
        amount: int = 1,
        related_event_id: int | None = None,
        reason: str | None = None,
        delta_generations: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> int:
        cur.execute(
            """
            INSERT INTO entitlement_events (
                user_id,
                generation_id,
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
                generation_id,
                event_type,
                source,
                amount,
                related_event_id,
                reason,
                delta_generations,
                _jsonb(metadata or {}),
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Could not create entitlement event.")
        return int(row["id"])

    def _insert_entitlement_snapshot_cur(
        self,
        cur: Any,
        user_id: int,
        entitlement: Entitlement,
    ) -> None:
        self._insert_entitlement_event_cur(
            cur,
            user_id,
            LEDGER_EVENT_ENTITLEMENT_SNAPSHOT,
            source="save_entitlement",
            amount=0,
            delta_generations=0,
            metadata={
                "processed_payment_charge_ids": entitlement.processed_payment_charge_ids,
            },
        )

    def _load_processed_charge_ids_cur(self, cur: Any, user_id: int) -> list[str]:
        cur.execute(
            """
            SELECT metadata_json
            FROM entitlement_events
            WHERE user_id = %s
              AND event_type = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, LEDGER_EVENT_ENTITLEMENT_SNAPSHOT),
        )
        row = cur.fetchone()
        if row is None or not isinstance(row.get("metadata_json"), dict):
            return []
        parsed = Entitlement.from_dict(row["metadata_json"])
        return parsed.processed_payment_charge_ids

    def _select_generation_for_consumption_cur(
        self,
        cur: Any,
        user_id: int,
        consumption: AttemptConsumption,
        *,
        generation_id: int | None,
        active_only: bool,
    ) -> dict[str, Any] | None:
        if generation_id is not None:
            cur.execute(
                """
                SELECT *
                FROM generation_records
                WHERE id = %s
                  AND user_id = %s
                FOR UPDATE
                """,
                (generation_id, user_id),
            )
        elif active_only:
            cur.execute(
                """
                SELECT *
                FROM generation_records
                WHERE user_id = %s
                  AND ration_kind = %s
                  AND status = ANY(%s)
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
                """,
                (user_id, consumption.ration_kind, list(ACTIVE_GENERATION_STATUSES)),
            )
        else:
            cur.execute(
                """
                SELECT *
                FROM generation_records
                WHERE user_id = %s
                  AND ration_kind = %s
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
                """,
                (user_id, consumption.ration_kind),
            )
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def _fail_stale_generations_cur(
        self,
        cur: Any,
        user_id: int,
        entitlement: Entitlement,
        now: datetime,
    ) -> int:
        stale_before = now - GENERATION_STALE_TIMEOUT
        cur.execute(
            """
            SELECT id
            FROM generation_records
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
            (
                user_id,
                list(ACTIVE_GENERATION_STATUSES),
                stale_before,
                stale_before,
                now,
            ),
        )
        generation_ids = [int(row["id"]) for row in cur.fetchall()]
        cleaned = 0
        for generation_id in generation_ids:
            cur.execute(
                """
                UPDATE generation_records
                SET status = 'failed_timeout',
                    error_message = 'generation timed out',
                    finished_at = COALESCE(finished_at, now()),
                    updated_at = now()
                WHERE id = %s
                  AND user_id = %s
                  AND status = ANY(%s)
                RETURNING id
                """,
                (generation_id, user_id, list(ACTIVE_GENERATION_STATUSES)),
            )
            if cur.fetchone() is None:
                continue
            cleaned += 1
            self._refund_generation_from_event_cur(
                cur,
                user_id,
                entitlement,
                generation_id,
                reason="generation_timeout",
            )
        return cleaned

    def _refund_generation_from_event_cur(
        self,
        cur: Any,
        user_id: int,
        entitlement: Entitlement,
        generation_id: int,
        *,
        reason: str,
    ) -> bool:
        cur.execute(
            """
            SELECT *
            FROM entitlement_events
            WHERE generation_id = %s
              AND event_type = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (generation_id, LEDGER_EVENT_CONSUME),
        )
        consume_event = cur.fetchone()
        if consume_event is None:
            return False

        cur.execute(
            """
            SELECT 1
            FROM entitlement_events
            WHERE generation_id = %s
              AND event_type = %s
            LIMIT 1
            """,
            (generation_id, LEDGER_EVENT_REFUND),
        )
        if cur.fetchone() is not None:
            return False

        consumed = _consumption_from_event(consume_event)
        if consumed is None:
            return False

        refund_attempt(entitlement, consumed)
        self._insert_entitlement_event_cur(
            cur,
            user_id,
            LEDGER_EVENT_REFUND,
            generation_id=generation_id,
            source=consumed.source,
            amount=_event_amount(consumed),
            related_event_id=int(consume_event["id"]),
            reason=reason,
            delta_generations=_refund_delta(consumed),
            metadata={
                "ration_kind": consumed.ration_kind,
                "attempt_source": consumed.source,
            },
        )
        return True

    def _first_promo_redeemer_cur(self, cur: Any, promo_id: int) -> int | None:
        cur.execute(
            """
            SELECT user_id
            FROM promo_redemptions
            WHERE promo_code_id = %s
            ORDER BY id
            LIMIT 1
            """,
            (promo_id,),
        )
        row = cur.fetchone()
        return int(row["user_id"]) if row is not None else None

    def _apply_promo_grant_cur(
        self,
        cur: Any,
        user_id: int,
        entitlement: Entitlement,
        promo: dict[str, Any],
        code: str,
        now: datetime,
    ) -> None:
        kind = str(promo["kind"])
        value = max(1, _non_negative_int(promo.get("value")))
        charge_id = f"promo:{code}"

        if kind == "subscription_month":
            apply_subscription_payment(
                entitlement,
                charge_id,
                now=now,
                subscription_expiration_timestamp=int(
                    (now + timedelta(seconds=SUBSCRIPTION_PERIOD_SECONDS * value)).timestamp()
                ),
            )
        elif kind == "extra_one_day":
            for index in range(value):
                apply_extra_one_day_payment(entitlement, f"{charge_id}:extra_one_day:{index}")
        elif kind == "extra_weekly_pdf":
            for index in range(value):
                apply_extra_weekly_pdf_payment(entitlement, f"{charge_id}:extra_weekly_pdf:{index}")
        elif kind == "test_access_days":
            grant_test_access(entitlement, now=now, days=value)


def _consume_entitlement_for_ration(
    entitlement: Entitlement,
    ration_kind: RationKind,
    now: datetime,
) -> AttemptConsumption:
    if ration_kind == "weekly_pdf":
        return consume_weekly_pdf_attempt(entitlement, now)
    return consume_one_day_attempt(entitlement, now)


def _row_to_entitlement(row: dict[str, Any]) -> Entitlement:
    return Entitlement(
        free_trial_used=bool(row.get("free_trial_used", False)),
        subscription_period_start=_format_datetime(row.get("subscription_period_start")),
        subscription_period_end=_format_datetime(row.get("subscription_period_end")),
        test_access_until=_format_datetime(row.get("test_access_until")),
        test_access_enabled=bool(row.get("test_access_enabled", False)),
        monthly_one_day_remaining=_non_negative_int(row.get("monthly_one_day_remaining")),
        monthly_weekly_pdf_remaining=_non_negative_int(row.get("monthly_weekly_pdf_remaining")),
        extra_one_day_remaining=_non_negative_int(row.get("extra_one_day_remaining")),
        extra_weekly_pdf_remaining=_non_negative_int(row.get("extra_weekly_pdf_remaining")),
    )


def _row_to_payment_order(row: dict[str, Any]) -> PaymentOrder:
    return PaymentOrder(
        order_id=str(row["order_id"]),
        nonce=str(row["nonce"]),
        user_id=int(row["user_id"]),
        delivery_chat_id=(
            int(row["delivery_chat_id"]) if row["delivery_chat_id"] is not None else None
        ),
        product=str(row["product"]),
        provider=str(row["provider"]),
        amount=int(row["amount"]),
        currency=str(row["currency"]),
        status=str(row["status"]),
        invoice_link=(
            str(row["invoice_link"]) if row["invoice_link"] is not None else None
        ),
        pre_checkout_approved_at=(
            _normalize_datetime(row["pre_checkout_approved_at"])
            if row.get("pre_checkout_approved_at") is not None
            else None
        ),
        created_at=_normalize_datetime(row["created_at"]),
        expires_at=_normalize_datetime(row["expires_at"]),
        paid_at=(
            _normalize_datetime(row["paid_at"]) if row["paid_at"] is not None else None
        ),
        updated_at=_normalize_datetime(row["updated_at"]),
    )


def _row_to_payment_event(row: dict[str, Any]) -> PaymentEvent:
    return PaymentEvent(
        event_id=str(row["event_id"]),
        event_type=str(row["event_type"]),
        provider=str(row["provider"]),
        order_id=str(row["order_id"]) if row.get("order_id") is not None else None,
        charge_id=str(row["charge_id"]) if row.get("charge_id") is not None else None,
        telegram_charge_id=(
            str(row["telegram_charge_id"])
            if row.get("telegram_charge_id") is not None
            else None
        ),
        provider_charge_id=(
            str(row["provider_charge_id"])
            if row.get("provider_charge_id") is not None
            else None
        ),
        user_id=int(row["user_id"]) if row.get("user_id") is not None else None,
        delivery_chat_id=(
            int(row["delivery_chat_id"])
            if row.get("delivery_chat_id") is not None
            else None
        ),
        product=str(row["product"]) if row.get("product") is not None else None,
        amount=int(row["amount"]) if row.get("amount") is not None else None,
        currency=str(row["currency"]) if row.get("currency") is not None else None,
        status=str(row["status"]),
        reason=str(row["reason"]) if row.get("reason") is not None else None,
        raw_payload_redacted=(
            dict(row["raw_payload_redacted"])
            if isinstance(row.get("raw_payload_redacted"), dict)
            else {}
        ),
        created_at=_normalize_datetime(row["created_at"]),
        processed_at=(
            _normalize_datetime(row["processed_at"])
            if row.get("processed_at") is not None
            else None
        ),
    )


def _row_to_processed_provider_charge(row: dict[str, Any]) -> ProcessedProviderCharge:
    return ProcessedProviderCharge(
        provider=str(row["provider"]),
        charge_id=str(row["charge_id"]),
        telegram_charge_id=(
            str(row["telegram_charge_id"])
            if row.get("telegram_charge_id") is not None
            else None
        ),
        provider_charge_id=(
            str(row["provider_charge_id"])
            if row.get("provider_charge_id") is not None
            else None
        ),
        order_id=str(row["order_id"]) if row.get("order_id") is not None else None,
        event_type=str(row["event_type"]),
        user_id=int(row["user_id"]) if row.get("user_id") is not None else None,
        product=str(row["product"]) if row.get("product") is not None else None,
        created_at=_normalize_datetime(row["created_at"]),
    )


def _payment_event_status_for_successful_payment_code(
    code: PaymentSuccessfulPaymentCode,
) -> PaymentEventStatus:
    if code == PaymentSuccessfulPaymentCode.PROCESSED:
        return PaymentEventStatus.PROCESSED
    if code == PaymentSuccessfulPaymentCode.DUPLICATE:
        return PaymentEventStatus.DUPLICATE
    if code == PaymentSuccessfulPaymentCode.ORDER_NOT_FOUND:
        return PaymentEventStatus.ORPHAN_RECOVERABLE
    return PaymentEventStatus.IGNORED_NON_TERMINAL


def _plan_and_status(entitlement: Entitlement) -> tuple[str, str]:
    now = datetime.now(UTC)
    if entitlement.is_subscription_active(now):
        return "monthly", "active"
    if entitlement.is_test_access_active(now):
        return "test_access", "active"
    if entitlement.subscription_period_end:
        return "monthly", "inactive"
    return "free", "inactive"


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
        return _normalize_datetime(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return _normalize_datetime(datetime.fromisoformat(text))
    except ValueError:
        return None


def _normalize_datetime(value: datetime | None) -> datetime:
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


def _with_generation_metadata(
    consumption: AttemptConsumption,
    generation_id: int,
    entitlement_event_id: int,
) -> AttemptConsumption:
    object.__setattr__(consumption, "_postgres_generation_id", generation_id)
    object.__setattr__(consumption, "_postgres_entitlement_event_id", entitlement_event_id)
    return consumption


def _generation_id_from_consumption(consumption: AttemptConsumption) -> int | None:
    generation_id = getattr(consumption, "_postgres_generation_id", None)
    if generation_id is None:
        return None
    try:
        return int(generation_id)
    except (TypeError, ValueError):
        return None


def _consumption_from_event(row: dict[str, Any]) -> AttemptConsumption | None:
    metadata = row.get("metadata_json")
    if not isinstance(metadata, dict):
        metadata = {}
    ration_kind = metadata.get("ration_kind")
    source = row.get("source") or metadata.get("attempt_source")
    if ration_kind not in {"one_day", "weekly_pdf"}:
        return None
    if source not in {"monthly", "extra", "free_trial", "test_access"}:
        return None
    return AttemptConsumption(True, ration_kind, source)  # type: ignore[arg-type]


def _event_amount(consumption: AttemptConsumption) -> int:
    return 0 if consumption.source == "test_access" else 1


def _consume_delta(consumption: AttemptConsumption) -> int:
    if not consumption.allowed:
        return 0
    return 0 if consumption.source == "test_access" else -1


def _refund_delta(consumption: AttemptConsumption) -> int:
    if not consumption.allowed:
        return 0
    return 0 if consumption.source == "test_access" else 1


def _interval_from_timedelta(value: timedelta) -> str:
    seconds = max(0, int(value.total_seconds()))
    return f"{seconds} seconds"


def _is_unique_violation(exc: Exception) -> bool:
    try:
        import psycopg
    except ImportError:
        return False
    return isinstance(exc, psycopg.errors.UniqueViolation)


def _jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _positive_int(value: int, *, name: str) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _payment_token() -> str:
    return secrets.token_urlsafe(18)
