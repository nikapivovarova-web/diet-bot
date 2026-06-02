from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from .payments import (
    CHARGE_STATUS_CANCELED,
    CHARGE_STATUS_REFUNDED,
    CHARGE_STATUS_SUCCEEDED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_GRANTED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING,
    PRODUCT_EXTRA_ONE_DAY,
    PRODUCT_EXTRA_WEEKLY_PDF,
    PRODUCT_SUBSCRIPTION_MONTH,
    PROVIDER_TELEGRAM_STARS,
    PaymentCharge,
    PaymentEvent,
    PaymentOrder,
    PaymentReversalResult,
    RecordedPaymentCharge,
)
from .postgres_entitlement_store import ENTITLEMENT_MAP_LOCK_ID
from .postgres_payment_migrations import MIGRATIONS, run_payment_schema_migrations
from .postgres_connection import DirectPostgresConnectionProvider, PostgresConnectionProvider
from .postgres_schema_validation import (
    SCHEMA_MIGRATIONS_COLUMNS,
    PostgresSchemaExpectation,
    validate_postgres_schema,
)
from .subscriptions import (
    Entitlement,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_payment_reversal,
    apply_subscription_payment,
)


GrantEntitlementInTransaction = Callable[[Any, PaymentOrder, PaymentCharge], None]

PAYMENT_SCHEMA_EXPECTATION = PostgresSchemaExpectation(
    component="payment",
    migration_versions=tuple(migration.version for migration in MIGRATIONS),
    table_columns={
        "schema_migrations": SCHEMA_MIGRATIONS_COLUMNS,
        "payment_orders": (
            "order_id",
            "user_id",
            "chat_id",
            "product",
            "provider",
            "amount",
            "currency",
            "nonce",
            "status",
            "failure_reason",
            "created_at",
            "updated_at",
            "paid_at",
            "granted_at",
            "failed_at",
        ),
        "payment_charges": (
            "charge_id",
            "order_id",
            "provider",
            "telegram_payment_charge_id",
            "provider_payment_charge_id",
            "amount",
            "currency",
            "status",
            "raw_payload_json",
            "created_at",
        ),
        "payment_events": (
            "event_id",
            "order_id",
            "event_type",
            "provider",
            "event_key",
            "telegram_payment_charge_id",
            "provider_payment_charge_id",
            "payload_json",
            "created_at",
        ),
    },
    indexes=(
        "idx_payment_charges_telegram_charge_id_unique",
        "idx_payment_charges_provider_charge_id_unique",
        "idx_payment_events_event_key_unique",
        "idx_payment_orders_user_chat_created",
        "idx_payment_events_order_created",
    ),
    remediation="Run payment migrations before use.",
)


class PostgresPaymentStore:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = 5,
        connect_attempts: int = 3,
        retry_base_delay: float = 0.2,
        retry_max_delay: float = 1.0,
        connection_provider: PostgresConnectionProvider | None = None,
    ) -> None:
        self.dsn = dsn
        self.connect_timeout = connect_timeout
        self.connect_attempts = max(1, connect_attempts)
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self._connection_provider = connection_provider or DirectPostgresConnectionProvider(
            dsn,
            connect_timeout=connect_timeout,
            connect_attempts=self.connect_attempts,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
        )

    def initialize(self) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    run_payment_schema_migrations(cur)

    def validate_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                validate_postgres_schema(cur, PAYMENT_SCHEMA_EXPECTATION)

    def create_order(self, order: PaymentOrder) -> PaymentOrder:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._create_order_cur(cur, order)

    def create_or_reuse_pending_order(
        self,
        order: PaymentOrder,
        *,
        pending_ttl: timedelta | None = timedelta(minutes=30),
        now: datetime | None = None,
    ) -> PaymentOrder:
        current_time = now or datetime.now(UTC)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _lock_pending_order_key_cur(cur, order)
                    reusable = self._find_reusable_pending_order_cur(
                        cur,
                        order,
                        pending_ttl=pending_ttl,
                        now=current_time,
                    )
                    if reusable is not None:
                        return reusable
                    return self._create_order_cur(cur, order)

    def get_order(self, order_id: str) -> PaymentOrder | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM payment_orders WHERE order_id = %s", (order_id,))
                row = cur.fetchone()
        return _order_from_row(row) if row is not None else None

    def find_charge_by_external_id(
        self,
        *,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
    ) -> PaymentCharge | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._find_charge_by_external_id_cur(
                    cur,
                    provider=provider,
                    telegram_payment_charge_id=telegram_payment_charge_id,
                    provider_payment_charge_id=provider_payment_charge_id,
                    for_update=False,
                )

    def find_charge_by_order_id(self, order_id: str) -> PaymentCharge | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM payment_charges
                    WHERE order_id = %s
                    ORDER BY charge_id DESC
                    LIMIT 1
                    """,
                    (order_id,),
                )
                row = cur.fetchone()
        return _charge_from_row(row) if row is not None else None

    def record_event(self, event: PaymentEvent) -> PaymentEvent:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._record_event_cur(cur, event)

    def record_charge(self, charge: PaymentCharge) -> RecordedPaymentCharge:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    return self._record_charge_cur(cur, charge)

    def mark_order_paid(self, order_id: str) -> PaymentOrder:
        return self._mark_order(order_id, ORDER_STATUS_PAID)

    def mark_order_granted(self, order_id: str) -> PaymentOrder:
        return self._mark_order(order_id, ORDER_STATUS_GRANTED)

    def mark_order_failed(self, order_id: str, reason: str | None = None) -> PaymentOrder:
        return self._mark_order(order_id, ORDER_STATUS_FAILED, reason=reason)

    def record_successful_payment_and_grant_entitlement(
        self,
        *,
        order_id: str,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
        amount: int,
        currency: str,
        product: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        now: datetime | None = None,
        subscription_expiration_timestamp: int | None = None,
        grant_entitlement: GrantEntitlementInTransaction | None = None,
        event: PaymentEvent | None = None,
        duplicate_event: PaymentEvent | None = None,
        rejected_event: PaymentEvent | None = None,
    ) -> RecordedPaymentCharge:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    order = self._get_order_cur(cur, order_id, for_update=True)
                    if order is None:
                        raise RuntimeError(f"Payment order not found: {order_id}")
                    charge = PaymentCharge(
                        order_id=order.order_id,
                        provider=provider,
                        telegram_payment_charge_id=_optional_text(telegram_payment_charge_id),
                        provider_payment_charge_id=_optional_text(provider_payment_charge_id),
                        amount=int(amount),
                        currency=currency,
                        status=CHARGE_STATUS_SUCCEEDED,
                        raw_payload=dict(raw_payload or {}),
                    )
                    if order.status != ORDER_STATUS_PENDING:
                        existing = self._find_existing_charge_cur(cur, charge)
                        if existing is not None:
                            if duplicate_event is not None:
                                self._record_event_cur(cur, duplicate_event)
                            return RecordedPaymentCharge(existing, inserted=False, reason="duplicate_charge")
                        if duplicate_event is not None:
                            self._record_event_cur(cur, duplicate_event)
                        return RecordedPaymentCharge(charge, inserted=False, reason="order_not_payable")
                    mismatch = _payment_context_mismatch_reason(
                        order,
                        provider=provider,
                        product=product,
                        amount=amount,
                        currency=currency,
                    )
                    if mismatch is not None:
                        self._mark_order_cur(cur, order.order_id, ORDER_STATUS_FAILED, reason=mismatch)
                        if rejected_event is not None:
                            self._record_event_cur(cur, rejected_event)
                        return RecordedPaymentCharge(charge, inserted=False, reason=mismatch)
                    recorded = self._record_charge_cur(cur, charge)
                    if not recorded.inserted:
                        if duplicate_event is not None:
                            self._record_event_cur(cur, duplicate_event)
                        return RecordedPaymentCharge(
                            recorded.charge,
                            inserted=False,
                            reason=recorded.reason or "duplicate_charge",
                        )
                    if event is not None:
                        self._record_event_cur(cur, event)
                    order = self._mark_order_cur(cur, order.order_id, ORDER_STATUS_PAID)
                    grant = grant_entitlement or (
                        lambda callback_cur, callback_order, callback_charge: _grant_entitlement_cur(
                            callback_cur,
                            callback_order,
                            callback_charge,
                            now=now,
                            subscription_expiration_timestamp=subscription_expiration_timestamp,
                        )
                    )
                    grant(cur, order, recorded.charge)
                    self._mark_order_cur(cur, order.order_id, ORDER_STATUS_GRANTED)
                    return recorded

    def record_payment_reversal(
        self,
        *,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
        reversal_status: str,
        amount: int | None = None,
        currency: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> PaymentReversalResult:
        normalized_status = _payment_reversal_status(reversal_status)
        ledger_status = _ledger_charge_status_for_reversal(normalized_status)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    charge = self._find_charge_by_external_id_cur(
                        cur,
                        provider=provider,
                        telegram_payment_charge_id=telegram_payment_charge_id,
                        provider_payment_charge_id=provider_payment_charge_id,
                        for_update=True,
                    )
                    if charge is None:
                        return PaymentReversalResult(False, reason="charge_not_found")
                    order = (
                        self._get_order_cur(cur, charge.order_id, for_update=True)
                        if charge.order_id is not None
                        else None
                    )
                    if charge.status == ledger_status:
                        return PaymentReversalResult(
                            False,
                            order.product if order is not None else None,
                            duplicate=True,
                            reason="duplicate_reversal",
                            order_id=order.order_id if order is not None else charge.order_id,
                            charge_status=charge.status,
                        )

                    payload = dict(raw_payload or {})
                    payload.setdefault("reversal_status", normalized_status)
                    payload.setdefault("ledger_charge_status", ledger_status)
                    if amount is not None:
                        payload.setdefault("reversal_amount", int(amount))
                    if currency is not None:
                        payload.setdefault("reversal_currency", str(currency))
                    updated_charge = self._update_charge_reversal_cur(cur, charge, ledger_status, payload)

                    manual_review_required = False
                    reason = _payment_reversal_context_mismatch_reason(
                        charge,
                        amount=amount,
                        currency=currency,
                    )
                    if reason is not None:
                        manual_review_required = True
                    elif order is None:
                        manual_review_required = True
                        reason = "order_not_found"
                    else:
                        reversal = _apply_payment_reversal_entitlement_cur(
                            cur,
                            order,
                            updated_charge,
                            reversal_status=normalized_status,
                            now=now,
                        )
                        manual_review_required = reversal.manual_review_required
                        reason = reversal.reason

                    if order is not None:
                        self._mark_order_cur(
                            cur,
                            order.order_id,
                            ORDER_STATUS_FAILED,
                            reason=_payment_reversal_order_failure_reason(
                                normalized_status,
                                manual_review_required=manual_review_required,
                            ),
                        )
                    return PaymentReversalResult(
                        True,
                        order.product if order is not None else None,
                        manual_review_required=manual_review_required,
                        reason=reason,
                        order_id=order.order_id if order is not None else charge.order_id,
                        charge_status=updated_charge.status,
                    )

    def _create_order_cur(self, cur: Any, order: PaymentOrder) -> PaymentOrder:
        cur.execute(
            """
            INSERT INTO payment_orders (
                order_id,
                user_id,
                chat_id,
                product,
                provider,
                amount,
                currency,
                nonce,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                order.order_id,
                order.user_id,
                order.chat_id,
                order.product,
                order.provider,
                order.amount,
                order.currency,
                order.nonce,
                order.status,
            ),
        )
        return _order_from_row(cur.fetchone())

    def _find_reusable_pending_order_cur(
        self,
        cur: Any,
        order: PaymentOrder,
        *,
        pending_ttl: timedelta | None,
        now: datetime,
    ) -> PaymentOrder | None:
        cur.execute(
            """
            SELECT *
            FROM payment_orders
            WHERE chat_id = %s
              AND product = %s
              AND provider = %s
              AND amount = %s
              AND currency = %s
              AND status = %s
            ORDER BY created_at, order_id
            FOR UPDATE
            """,
            (
                order.chat_id,
                order.product,
                order.provider,
                order.amount,
                order.currency,
                ORDER_STATUS_PENDING,
            ),
        )
        for row in cur.fetchall():
            existing = _order_from_row(row)
            if _pending_order_expired(existing, pending_ttl=pending_ttl, now=now):
                self._mark_order_cur(cur, existing.order_id, ORDER_STATUS_FAILED, reason="order_expired")
                continue
            return replace(existing, reused_pending=True)
        return None

    def _record_event_cur(self, cur: Any, event: PaymentEvent) -> PaymentEvent:
        cur.execute(
            """
            INSERT INTO payment_events (
                event_id,
                order_id,
                event_type,
                provider,
                event_key,
                telegram_payment_charge_id,
                provider_payment_charge_id,
                payload_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            (
                event.event_id,
                event.order_id,
                event.event_type,
                event.provider,
                _optional_text(event.event_key),
                _optional_text(event.telegram_payment_charge_id),
                _optional_text(event.provider_payment_charge_id),
                _jsonb(event.payload),
            ),
        )
        row = cur.fetchone()
        if row is not None:
            return _event_from_row(row)
        existing = self._find_existing_event_cur(cur, event)
        if existing is None:
            raise RuntimeError("Payment event insert conflicted but no existing row was found.")
        return existing

    def _record_charge_cur(self, cur: Any, charge: PaymentCharge) -> RecordedPaymentCharge:
        cur.execute(
            """
            INSERT INTO payment_charges (
                order_id,
                provider,
                telegram_payment_charge_id,
                provider_payment_charge_id,
                amount,
                currency,
                status,
                raw_payload_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            (
                charge.order_id,
                charge.provider,
                _optional_text(charge.telegram_payment_charge_id),
                _optional_text(charge.provider_payment_charge_id),
                charge.amount,
                charge.currency,
                charge.status,
                _jsonb(charge.raw_payload),
            ),
        )
        row = cur.fetchone()
        if row is not None:
            return RecordedPaymentCharge(_charge_from_row(row), inserted=True)
        existing = self._find_existing_charge_cur(cur, charge)
        if existing is None:
            raise RuntimeError("Payment charge insert conflicted but no existing row was found.")
        return RecordedPaymentCharge(existing, inserted=False)

    def _update_charge_reversal_cur(
        self,
        cur: Any,
        charge: PaymentCharge,
        status: str,
        payload: dict[str, Any],
    ) -> PaymentCharge:
        cur.execute(
            """
            UPDATE payment_charges
            SET status = %s,
                raw_payload_json = raw_payload_json || %s
            WHERE charge_id = %s
            RETURNING *
            """,
            (status, _jsonb(payload), charge.charge_id),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Payment charge not found: {charge.charge_id}")
        return _charge_from_row(row)

    def _find_existing_event_cur(self, cur: Any, event: PaymentEvent) -> PaymentEvent | None:
        clauses = ["event_id = %s"]
        params: list[Any] = [event.event_id]
        if _optional_text(event.event_key):
            clauses.append("event_key = %s")
            params.append(_optional_text(event.event_key))
        cur.execute(
            f"""
            SELECT *
            FROM payment_events
            WHERE {" OR ".join(clauses)}
            ORDER BY created_at, event_id
            LIMIT 1
            """,
            tuple(params),
        )
        row = cur.fetchone()
        return _event_from_row(row) if row is not None else None

    def _find_existing_charge_cur(self, cur: Any, charge: PaymentCharge) -> PaymentCharge | None:
        return self._find_charge_by_external_id_cur(
            cur,
            provider=charge.provider,
            telegram_payment_charge_id=charge.telegram_payment_charge_id,
            provider_payment_charge_id=charge.provider_payment_charge_id,
            for_update=True,
        )

    def _find_charge_by_external_id_cur(
        self,
        cur: Any,
        *,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
        for_update: bool,
    ) -> PaymentCharge | None:
        clauses: list[str] = []
        params: list[Any] = [provider]
        if _optional_text(telegram_payment_charge_id):
            clauses.append("telegram_payment_charge_id = %s")
            params.append(_optional_text(telegram_payment_charge_id))
        if _optional_text(provider_payment_charge_id):
            clauses.append("provider_payment_charge_id = %s")
            params.append(_optional_text(provider_payment_charge_id))
        if not clauses:
            return None
        lock_suffix = " FOR UPDATE" if for_update else ""
        cur.execute(
            f"""
            SELECT *
            FROM payment_charges
            WHERE provider = %s
              AND ({" OR ".join(clauses)})
            ORDER BY charge_id
            LIMIT 1
            {lock_suffix}
            """,
            tuple(params),
        )
        row = cur.fetchone()
        return _charge_from_row(row) if row is not None else None

    def _get_order_cur(self, cur: Any, order_id: str, *, for_update: bool = False) -> PaymentOrder | None:
        suffix = " FOR UPDATE" if for_update else ""
        cur.execute(f"SELECT * FROM payment_orders WHERE order_id = %s{suffix}", (order_id,))
        row = cur.fetchone()
        return _order_from_row(row) if row is not None else None

    def _mark_order(self, order_id: str, status: str, *, reason: str | None = None) -> PaymentOrder:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._mark_order_cur(cur, order_id, status, reason=reason)

    def _mark_order_cur(
        self,
        cur: Any,
        order_id: str,
        status: str,
        *,
        reason: str | None = None,
    ) -> PaymentOrder:
        cur.execute(
            """
            UPDATE payment_orders
            SET status = %s,
                failure_reason = CASE WHEN %s = 'failed' THEN %s ELSE failure_reason END,
                updated_at = now(),
                paid_at = CASE WHEN %s = 'paid' THEN COALESCE(paid_at, now()) ELSE paid_at END,
                granted_at = CASE WHEN %s = 'granted' THEN COALESCE(granted_at, now()) ELSE granted_at END,
                failed_at = CASE WHEN %s = 'failed' THEN COALESCE(failed_at, now()) ELSE failed_at END
            WHERE order_id = %s
            RETURNING *
            """,
            (status, status, reason, status, status, status, order_id),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Payment order not found: {order_id}")
        return _order_from_row(row)

    def _connect(self):
        return self._connection_provider.connect()

    def close(self) -> None:
        self._connection_provider.close()


def _grant_entitlement_cur(
    cur: Any,
    order: PaymentOrder,
    charge: PaymentCharge,
    *,
    now: datetime | None,
    subscription_expiration_timestamp: int | None,
) -> None:
    _lock_entitlement_map_cur(cur)
    entitlement = _load_entitlement_cur(cur, order.chat_id)
    charge_key = _entitlement_charge_key(order, charge)
    if order.product == PRODUCT_SUBSCRIPTION_MONTH:
        is_stars_subscription = order.provider == PROVIDER_TELEGRAM_STARS
        apply_subscription_payment(
            entitlement,
            charge_key,
            now=now,
            subscription_expiration_timestamp=subscription_expiration_timestamp,
            subscription_source="telegram_stars" if is_stars_subscription else "yookassa",
            auto_renew_status="enabled" if is_stars_subscription else "not_applicable",
            stars_subscription_charge_id=charge_key if is_stars_subscription else None,
            last_subscription_payment_charge_id=charge_key,
            current_period_payment_order_id=order.order_id,
        )
    elif order.product == PRODUCT_EXTRA_ONE_DAY:
        apply_extra_one_day_payment(entitlement, charge_key)
    elif order.product == PRODUCT_EXTRA_WEEKLY_PDF:
        apply_extra_weekly_pdf_payment(entitlement, charge_key)
    else:
        raise RuntimeError(f"Unsupported payment product for entitlement grant: {order.product!r}")
    _upsert_entitlement_cur(cur, order.chat_id, entitlement)


def _apply_payment_reversal_entitlement_cur(
    cur: Any,
    order: PaymentOrder,
    charge: PaymentCharge,
    *,
    reversal_status: str,
    now: datetime | None,
):
    _lock_entitlement_map_cur(cur)
    entitlement = _load_entitlement_cur(cur, order.chat_id)
    result = apply_payment_reversal(
        entitlement,
        order.product,
        _entitlement_charge_key(order, charge),
        order_id=order.order_id,
        reversal_status=reversal_status,
        now=now,
    )
    _upsert_entitlement_cur(cur, order.chat_id, entitlement)
    return result


def _lock_entitlement_map_cur(cur: Any) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (ENTITLEMENT_MAP_LOCK_ID,))


def _payment_reversal_status(value: str) -> str:
    normalized = str(value or "refunded").strip().lower()
    if normalized == "cancelled":
        normalized = "canceled"
    if normalized == "refund":
        normalized = "refunded"
    if normalized in {"refunded", "canceled", "reversed", "chargeback"}:
        return normalized
    return "reversed"


def _ledger_charge_status_for_reversal(status: str) -> str:
    if status == "canceled":
        return CHARGE_STATUS_CANCELED
    return CHARGE_STATUS_REFUNDED


def _payment_reversal_order_failure_reason(
    status: str,
    *,
    manual_review_required: bool,
) -> str:
    base = {
        "refunded": "payment_refunded",
        "canceled": "payment_canceled",
        "reversed": "payment_reversed",
        "chargeback": "payment_chargeback",
    }.get(status, "payment_reversed")
    if manual_review_required:
        return f"{base}_manual_review"
    return base


def _payment_reversal_context_mismatch_reason(
    charge: PaymentCharge,
    *,
    amount: int | None,
    currency: str | None,
) -> str | None:
    if amount is not None and int(amount) != int(charge.amount):
        return "partial_refund_manual_review"
    if currency is not None and str(currency) != charge.currency:
        return "currency_mismatch"
    return None


def _payment_context_mismatch_reason(
    order: PaymentOrder,
    *,
    provider: str,
    product: str | None,
    amount: int,
    currency: str,
) -> str | None:
    if order.provider != provider:
        return "provider_mismatch"
    if product is not None and order.product != product:
        return "product_mismatch"
    if int(order.amount) != int(amount):
        return "amount_mismatch"
    if order.currency != currency:
        return "currency_mismatch"
    return None


def _lock_pending_order_key_cur(cur: Any, order: PaymentOrder) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (_pending_order_lock_id(order),))


def _pending_order_lock_id(order: PaymentOrder) -> int:
    key = ":".join(
        (
            "payment_pending_order_v1",
            str(int(order.chat_id)),
            str(order.product),
            str(order.provider),
            str(int(order.amount)),
            str(order.currency),
        )
    )
    value = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big", signed=False)
    if value >= 2**63:
        value -= 2**64
    return value


def _pending_order_expired(
    order: PaymentOrder,
    *,
    pending_ttl: timedelta | None,
    now: datetime,
) -> bool:
    if pending_ttl is None:
        return False
    created_at = order.created_at or order.updated_at
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    return created_at + pending_ttl < now


def _load_entitlement_cur(cur: Any, chat_id: int) -> Entitlement:
    cur.execute(
        """
        INSERT INTO entitlements (chat_id)
        VALUES (%s)
        ON CONFLICT (chat_id) DO NOTHING
        """,
        (chat_id,),
    )
    cur.execute(
        """
        SELECT
            chat_id,
            free_trial_used,
            subscription_period_start,
            subscription_period_end,
            subscription_source,
            auto_renew_status,
            stars_subscription_charge_id,
            last_subscription_payment_charge_id,
            current_period_payment_order_id,
            test_access_until,
            test_access_enabled,
            monthly_one_day_remaining,
            monthly_weekly_pdf_remaining,
            extra_one_day_remaining,
            extra_weekly_pdf_remaining
        FROM entitlements
        WHERE chat_id = %s
        FOR UPDATE
        """,
        (chat_id,),
    )
    row = cur.fetchone()
    if row is None:
        return Entitlement()
    entitlement = Entitlement(
        free_trial_used=bool(row["free_trial_used"]),
        subscription_period_start=_optional_text(row["subscription_period_start"]),
        subscription_period_end=_optional_text(row["subscription_period_end"]),
        subscription_source=_optional_text(row["subscription_source"]) or "none",
        auto_renew_status=_optional_text(row["auto_renew_status"]) or "not_applicable",
        stars_subscription_charge_id=_optional_text(row["stars_subscription_charge_id"]),
        last_subscription_payment_charge_id=_optional_text(row["last_subscription_payment_charge_id"]),
        current_period_payment_order_id=_optional_text(row["current_period_payment_order_id"]),
        test_access_until=_optional_text(row["test_access_until"]),
        test_access_enabled=bool(row["test_access_enabled"]),
        monthly_one_day_remaining=int(row["monthly_one_day_remaining"]),
        monthly_weekly_pdf_remaining=int(row["monthly_weekly_pdf_remaining"]),
        extra_one_day_remaining=int(row["extra_one_day_remaining"]),
        extra_weekly_pdf_remaining=int(row["extra_weekly_pdf_remaining"]),
        processed_payment_charge_ids=[],
    )
    cur.execute(
        """
        SELECT charge_id
        FROM entitlement_processed_charge_ids
        WHERE chat_id = %s
        ORDER BY position, recorded_at, charge_id
        """,
        (chat_id,),
    )
    entitlement.processed_payment_charge_ids = [str(item["charge_id"]) for item in cur.fetchall()]
    return entitlement


def _upsert_entitlement_cur(cur: Any, chat_id: int, entitlement: Entitlement) -> None:
    cur.execute(
        """
        INSERT INTO entitlements (
            chat_id,
            free_trial_used,
            subscription_period_start,
            subscription_period_end,
            subscription_source,
            auto_renew_status,
            stars_subscription_charge_id,
            last_subscription_payment_charge_id,
            current_period_payment_order_id,
            test_access_until,
            test_access_enabled,
            monthly_one_day_remaining,
            monthly_weekly_pdf_remaining,
            extra_one_day_remaining,
            extra_weekly_pdf_remaining
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chat_id) DO UPDATE SET
            free_trial_used = EXCLUDED.free_trial_used,
            subscription_period_start = EXCLUDED.subscription_period_start,
            subscription_period_end = EXCLUDED.subscription_period_end,
            subscription_source = EXCLUDED.subscription_source,
            auto_renew_status = EXCLUDED.auto_renew_status,
            stars_subscription_charge_id = EXCLUDED.stars_subscription_charge_id,
            last_subscription_payment_charge_id = EXCLUDED.last_subscription_payment_charge_id,
            current_period_payment_order_id = EXCLUDED.current_period_payment_order_id,
            test_access_until = EXCLUDED.test_access_until,
            test_access_enabled = EXCLUDED.test_access_enabled,
            monthly_one_day_remaining = EXCLUDED.monthly_one_day_remaining,
            monthly_weekly_pdf_remaining = EXCLUDED.monthly_weekly_pdf_remaining,
            extra_one_day_remaining = EXCLUDED.extra_one_day_remaining,
            extra_weekly_pdf_remaining = EXCLUDED.extra_weekly_pdf_remaining,
            updated_at = now(),
            version = entitlements.version + 1
        """,
        (
            chat_id,
            entitlement.free_trial_used,
            entitlement.subscription_period_start,
            entitlement.subscription_period_end,
            entitlement.subscription_source,
            entitlement.auto_renew_status,
            entitlement.stars_subscription_charge_id,
            entitlement.last_subscription_payment_charge_id,
            entitlement.current_period_payment_order_id,
            entitlement.test_access_until,
            entitlement.test_access_enabled,
            entitlement.monthly_one_day_remaining,
            entitlement.monthly_weekly_pdf_remaining,
            entitlement.extra_one_day_remaining,
            entitlement.extra_weekly_pdf_remaining,
        ),
    )
    cur.execute("DELETE FROM entitlement_processed_charge_ids WHERE chat_id = %s", (chat_id,))
    for position, charge_id in enumerate(_unique_charge_ids(entitlement.processed_payment_charge_ids)):
        cur.execute(
            """
            INSERT INTO entitlement_processed_charge_ids (chat_id, charge_id, position)
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id, charge_id) DO UPDATE SET
                position = EXCLUDED.position
            """,
            (chat_id, charge_id, position),
        )


def _unique_charge_ids(charge_ids: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for charge_id in charge_ids:
        text = str(charge_id).strip()
        if not text or text in seen:
            continue
        unique.append(text)
        seen.add(text)
    return unique


def _entitlement_charge_key(order: PaymentOrder, charge: PaymentCharge) -> str:
    external_id = (
        _optional_text(charge.telegram_payment_charge_id)
        or _optional_text(charge.provider_payment_charge_id)
        or str(charge.charge_id or "")
    )
    if not external_id:
        raise RuntimeError("Cannot grant entitlement without a payment charge id.")
    return f"{order.provider}:{external_id}"


def _order_from_row(row: Any) -> PaymentOrder:
    return PaymentOrder(
        order_id=str(row["order_id"]),
        user_id=int(row["user_id"]),
        chat_id=int(row["chat_id"]),
        product=str(row["product"]),
        provider=str(row["provider"]),
        amount=int(row["amount"]),
        currency=str(row["currency"]),
        nonce=str(row["nonce"]),
        status=str(row["status"]),
        failure_reason=_optional_text(row["failure_reason"]),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
        paid_at=_datetime_or_none(row["paid_at"]),
        granted_at=_datetime_or_none(row["granted_at"]),
        failed_at=_datetime_or_none(row["failed_at"]),
    )


def _charge_from_row(row: Any) -> PaymentCharge:
    return PaymentCharge(
        charge_id=int(row["charge_id"]),
        order_id=_optional_text(row["order_id"]),
        provider=str(row["provider"]),
        telegram_payment_charge_id=_optional_text(row["telegram_payment_charge_id"]),
        provider_payment_charge_id=_optional_text(row["provider_payment_charge_id"]),
        amount=int(row["amount"]),
        currency=str(row["currency"]),
        status=str(row["status"]),
        raw_payload=dict(row["raw_payload_json"]),
        created_at=_datetime_or_none(row["created_at"]),
    )


def _event_from_row(row: Any) -> PaymentEvent:
    return PaymentEvent(
        event_id=str(row["event_id"]),
        order_id=_optional_text(row["order_id"]),
        event_type=str(row["event_type"]),
        provider=_optional_text(row["provider"]),
        event_key=_optional_text(row["event_key"]),
        telegram_payment_charge_id=_optional_text(row["telegram_payment_charge_id"]),
        provider_payment_charge_id=_optional_text(row["provider_payment_charge_id"]),
        payload=dict(row["payload_json"]),
        created_at=_datetime_or_none(row["created_at"]),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return None


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)
