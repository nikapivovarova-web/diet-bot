from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .payments import (
    CHARGE_STATUS_SUCCEEDED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_GRANTED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING,
    PRODUCT_EXTRA_ONE_DAY,
    PRODUCT_EXTRA_WEEKLY_PDF,
    PRODUCT_SUBSCRIPTION_MONTH,
    PaymentCharge,
    PaymentEvent,
    PaymentOrder,
    RecordedPaymentCharge,
)
from .postgres_payment_migrations import run_payment_schema_migrations
from .subscriptions import (
    Entitlement,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_subscription_payment,
)


GrantEntitlementInTransaction = Callable[[Any, PaymentOrder, PaymentCharge], None]


class PostgresPaymentStore:
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
                    run_payment_schema_migrations(cur)

    def validate_schema(self) -> None:
        expected_tables = {"schema_migrations", "payment_orders", "payment_charges", "payment_events"}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = ANY(%s)
                    """,
                    (sorted(expected_tables),),
                )
                found_tables = {str(row["table_name"]) for row in cur.fetchall()}
        missing_tables = sorted(expected_tables - found_tables)
        if missing_tables:
            raise RuntimeError(
                "Postgres payment schema is missing tables: "
                f"{', '.join(missing_tables)}. Run payment migrations before use.",
            )

    def create_order(self, order: PaymentOrder) -> PaymentOrder:
        with self._connect() as conn:
            with conn.cursor() as cur:
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

    def get_order(self, order_id: str) -> PaymentOrder | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM payment_orders WHERE order_id = %s", (order_id,))
                row = cur.fetchone()
        return _order_from_row(row) if row is not None else None

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
                            return RecordedPaymentCharge(existing, inserted=False, reason="duplicate_charge")
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
                        return RecordedPaymentCharge(charge, inserted=False, reason=mismatch)
                    recorded = self._record_charge_cur(cur, charge)
                    if not recorded.inserted:
                        return recorded
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
        clauses: list[str] = []
        params: list[Any] = [charge.provider]
        if _optional_text(charge.telegram_payment_charge_id):
            clauses.append("telegram_payment_charge_id = %s")
            params.append(_optional_text(charge.telegram_payment_charge_id))
        if _optional_text(charge.provider_payment_charge_id):
            clauses.append("provider_payment_charge_id = %s")
            params.append(_optional_text(charge.provider_payment_charge_id))
        if not clauses:
            return None
        cur.execute(
            f"""
            SELECT *
            FROM payment_charges
            WHERE provider = %s
              AND ({" OR ".join(clauses)})
            ORDER BY charge_id
            LIMIT 1
            FOR UPDATE
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


def _grant_entitlement_cur(
    cur: Any,
    order: PaymentOrder,
    charge: PaymentCharge,
    *,
    now: datetime | None,
    subscription_expiration_timestamp: int | None,
) -> None:
    entitlement = _load_entitlement_cur(cur, order.chat_id)
    charge_key = _entitlement_charge_key(order, charge)
    if order.product == PRODUCT_SUBSCRIPTION_MONTH:
        apply_subscription_payment(
            entitlement,
            charge_key,
            now=now,
            subscription_expiration_timestamp=subscription_expiration_timestamp,
        )
    elif order.product == PRODUCT_EXTRA_ONE_DAY:
        apply_extra_one_day_payment(entitlement, charge_key)
    elif order.product == PRODUCT_EXTRA_WEEKLY_PDF:
        apply_extra_weekly_pdf_payment(entitlement, charge_key)
    else:
        raise RuntimeError(f"Unsupported payment product for entitlement grant: {order.product!r}")
    _upsert_entitlement_cur(cur, order.chat_id, entitlement)


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


def _load_entitlement_cur(cur: Any, chat_id: int) -> Entitlement:
    cur.execute(
        """
        SELECT
            chat_id,
            free_trial_used,
            subscription_period_start,
            subscription_period_end,
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
            test_access_until,
            test_access_enabled,
            monthly_one_day_remaining,
            monthly_weekly_pdf_remaining,
            extra_one_day_remaining,
            extra_weekly_pdf_remaining
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chat_id) DO UPDATE SET
            free_trial_used = EXCLUDED.free_trial_used,
            subscription_period_start = EXCLUDED.subscription_period_start,
            subscription_period_end = EXCLUDED.subscription_period_end,
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
