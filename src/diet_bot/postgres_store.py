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
    PaymentReconciliationInput,
    PaymentReconciliationResult,
    PaymentReversalCode,
    PaymentReversalInput,
    PaymentReversalResult,
    PaymentSuccessfulPaymentCode,
    PaymentSuccessfulPaymentInput,
    PaymentSuccessfulPaymentResult,
    ProcessedProviderCharge,
    apply_payment_reversal as apply_payment_reversal_core,
    apply_payment_reversal_entitlement,
    apply_payment_reconciliation as apply_payment_reconciliation_core,
    apply_successful_payment as apply_successful_payment_core,
    apply_successful_payment_entitlement,
    build_payment_reversal_event,
    build_successful_payment_event,
    successful_payment_canonical_charge_id,
    successful_payment_charge_aliases,
    validate_payment_reversal_order,
    validate_successful_payment_order,
)
from .postgres_migrations import run_postgres_migrations
from .promo_codes import (
    PromoCodeActivation,
    PromoCodeDefinition,
    PromoCodeKind,
    PromoCodeRecord,
    PromoRedemptionResult,
    PromoRedemptionStatus,
    calculate_discount_amount,
    normalize_promo_code,
    promo_code_audit_metadata,
    promo_code_grant_charge_id,
)
from .subscriptions import (
    AttemptConsumption,
    Entitlement,
    RationKind,
    apply_extra_one_day_payment,
    apply_extra_weekly_pdf_payment,
    apply_monthly_access_promo_grant,
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
LEDGER_EVENT_PROMO_GRANT = "grant"
PROMO_ACCESS_KINDS = frozenset({"monthly_access", "subscription_month"})


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
                    INSERT INTO promo_codes (
                        code,
                        kind,
                        value,
                        max_uses,
                        max_redemptions,
                        per_user_limit,
                        used_count,
                        is_active,
                        monthly_duration_months
                    )
                    VALUES (%s, 'monthly_access', 1, 1, 1, 1, %s, true, 1)
                    ON CONFLICT (code) DO UPDATE
                    SET used_count = GREATEST(promo_codes.used_count, EXCLUDED.used_count),
                        kind = 'monthly_access',
                        value = 1,
                        max_uses = 1,
                        max_redemptions = 1,
                        per_user_limit = 1,
                        is_active = true,
                        monthly_duration_months = 1
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
                    SELECT 1
                    FROM promo_redemptions
                    WHERE promo_code_id = %s
                      AND user_id = %s
                    LIMIT 1
                    """,
                    (int(row["id"]), used_by_chat_id),
                )
                if cur.fetchone() is not None:
                    return
                cur.execute(
                    """
                    INSERT INTO promo_redemptions (
                        promo_code_id,
                        user_id,
                        status,
                        kind,
                        metadata_json,
                        redeemed_at
                    )
                    VALUES (%s, %s, 'redeemed', 'monthly_access', %s, COALESCE(%s, now()))
                    """,
                    (
                        int(row["id"]),
                        used_by_chat_id,
                        _jsonb({"legacy_json_import": True}),
                        used_at,
                    ),
                )

    def create_promo_code(self, promo: PromoCodeDefinition) -> PromoCodeDefinition:
        definition = PromoCodeDefinition(**promo.to_dict())
        with self._connect() as conn:
            with conn.cursor() as cur:
                row = self._upsert_promo_definition_cur(cur, definition)
                metadata = definition.to_dict()
                metadata.pop("code", None)
                self._insert_promo_event_cur(
                    cur,
                    int(row["id"]),
                    "created",
                    metadata=promo_code_audit_metadata(definition.code, **metadata),
                )
        return _row_to_promo_definition(row)

    def get_promo_code(
        self,
        raw_code: str,
        *,
        active_only: bool = False,
        now: datetime | None = None,
    ) -> PromoCodeDefinition | None:
        code = normalize_promo_code(raw_code)
        if not code:
            return None

        current_time = _normalize_datetime(now)
        clauses = ["code = %s"]
        params: list[Any] = [code]
        if active_only:
            clauses.append("is_active = true")
            clauses.append(
                "(COALESCE(expires_at, valid_until) IS NULL OR COALESCE(expires_at, valid_until) > %s)"
            )
            params.append(current_time)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM promo_codes
                    WHERE {' AND '.join(clauses)}
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
        if row is None:
            return None
        try:
            return _row_to_promo_definition(row)
        except ValueError:
            return None

    def redeem_promo_code(
        self,
        user_id: int,
        raw_code: str,
        *,
        now: datetime | None = None,
    ) -> PromoRedemptionResult:
        code = normalize_promo_code(raw_code)
        if not code:
            return PromoRedemptionResult(PromoRedemptionStatus.NOT_FOUND, "")

        current_time = _normalize_datetime(now)
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(user_id))
                promo = self._select_promo_for_update_cur(cur, code)
                if promo is None:
                    self._insert_promo_event_cur(
                        cur,
                        None,
                        "rejected",
                        user_id=user_id,
                        metadata=promo_code_audit_metadata(code, status="not_found"),
                    )
                    return PromoRedemptionResult(PromoRedemptionStatus.NOT_FOUND, code)

                try:
                    promo_kind = _promo_definition_kind(promo)
                except ValueError:
                    self._insert_promo_event_cur(
                        cur,
                        int(promo["id"]),
                        "rejected",
                        user_id=user_id,
                        metadata=promo_code_audit_metadata(code, status="not_found"),
                    )
                    return PromoRedemptionResult(PromoRedemptionStatus.NOT_FOUND, code)

                validation = self._validate_promo_redemption_cur(
                    cur,
                    promo,
                    user_id,
                    current_time,
                )
                if validation is not None:
                    self._insert_promo_event_cur(
                        cur,
                        int(promo["id"]),
                        "rejected",
                        user_id=user_id,
                        metadata=promo_code_audit_metadata(
                            code,
                            status=str(validation.status),
                        ),
                    )
                    return validation

                redemption_id = self._insert_promo_redemption_cur(
                    cur,
                    promo,
                    user_id,
                    current_time,
                )
                entitlement_event_id: int | None = None
                if promo_kind == PromoCodeKind.MONTHLY_ACCESS:
                    entitlement = self._select_entitlement_for_update_cur(cur, user_id)
                    entitlement_event_id = self._apply_promo_grant_cur(
                        cur,
                        user_id,
                        entitlement,
                        promo,
                        code,
                        current_time,
                    )
                    self._update_entitlement_cur(cur, user_id, entitlement)
                    self._insert_entitlement_snapshot_cur(cur, user_id, entitlement)
                    self._link_promo_redemption_entitlement_event_cur(
                        cur,
                        redemption_id,
                        entitlement_event_id,
                    )

                self._increment_promo_used_count_cur(cur, int(promo["id"]))
                self._insert_promo_event_cur(
                    cur,
                    int(promo["id"]),
                    "redeemed",
                    user_id=user_id,
                    redemption_id=redemption_id,
                    metadata=promo_code_audit_metadata(
                        code,
                        kind=promo_kind.value,
                        entitlement_event_id=entitlement_event_id,
                    ),
                )
                return PromoRedemptionResult(
                    PromoRedemptionStatus.REDEEMED,
                    code,
                    promo=_row_to_promo_definition(promo),
                    redemption_id=redemption_id,
                    used_by_chat_id=user_id,
                )

    def activate_promo_code(self, user_id: int, raw_code: str) -> PromoCodeActivation:
        code = normalize_promo_code(raw_code)
        if not code:
            return PromoCodeActivation("not_found", "")

        current_time = datetime.now(UTC)
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._remember_user_cur(cur, UserIdentity(user_id))
                promo = self._select_promo_for_update_cur(cur, code)
                if promo is None:
                    self._insert_promo_event_cur(
                        cur,
                        None,
                        "rejected",
                        user_id=user_id,
                        metadata=promo_code_audit_metadata(code, status="not_found"),
                    )
                    return PromoCodeActivation("not_found", code)

                promo_kind = _promo_kind_value(promo)
                if promo_kind not in PROMO_ACCESS_KINDS:
                    self._insert_promo_event_cur(
                        cur,
                        int(promo["id"]),
                        "rejected",
                        user_id=user_id,
                        metadata=promo_code_audit_metadata(
                            code,
                            status="not_access_code",
                            kind=promo_kind,
                        ),
                    )
                    return PromoCodeActivation("not_access_code", code)

                validation = self._validate_promo_redemption_cur(
                    cur,
                    promo,
                    user_id,
                    current_time,
                )
                if validation is not None:
                    self._insert_promo_event_cur(
                        cur,
                        int(promo["id"]),
                        "rejected",
                        user_id=user_id,
                        metadata=promo_code_audit_metadata(
                            code,
                            status=str(validation.status),
                        ),
                    )
                    return PromoCodeActivation(
                        str(validation.status),
                        code,
                        validation.used_by_chat_id,
                    )

                existing_redeemer = self._first_promo_redeemer_cur(cur, int(promo["id"]))
                already_redeemed = (
                    existing_redeemer is not None
                    or _non_negative_int(promo.get("used_count")) >= 1
                )
                if already_redeemed:
                    self._insert_promo_event_cur(
                        cur,
                        int(promo["id"]),
                        "rejected",
                        user_id=user_id,
                        metadata=promo_code_audit_metadata(code, status="already_used"),
                    )
                    return PromoCodeActivation("already_used", code, existing_redeemer)

                entitlement = self._select_entitlement_for_update_cur(cur, user_id)
                redemption_id = self._insert_promo_redemption_cur(
                    cur,
                    promo,
                    user_id,
                    current_time,
                )
                entitlement_event_id = self._apply_promo_grant_cur(
                    cur,
                    user_id,
                    entitlement,
                    promo,
                    code,
                    current_time,
                )
                self._link_promo_redemption_entitlement_event_cur(
                    cur,
                    redemption_id,
                    entitlement_event_id,
                )
                self._increment_promo_used_count_cur(cur, int(promo["id"]))
                self._update_entitlement_cur(cur, user_id, entitlement)
                self._insert_entitlement_snapshot_cur(cur, user_id, entitlement)
                self._insert_promo_event_cur(
                    cur,
                    int(promo["id"]),
                    "redeemed",
                    user_id=user_id,
                    redemption_id=redemption_id,
                    metadata=promo_code_audit_metadata(
                        code,
                        kind=promo_kind,
                        entitlement_event_id=entitlement_event_id,
                    ),
                )
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
        list_amount: int | None = None,
        discount_amount: int = 0,
        promo_code_id: int | None = None,
        promo_redemption_id: int | None = None,
        promo_code_hash: str | None = None,
        promo_code_suffix: str | None = None,
        metadata: dict[str, object] | None = None,
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
            list_amount=list_amount,
            discount_amount=discount_amount,
            promo_code_id=promo_code_id,
            promo_redemption_id=promo_redemption_id,
            promo_code_hash=promo_code_hash,
            promo_code_suffix=promo_code_suffix,
            metadata=metadata or {},
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
        promo_code: str | None = None,
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
        normalized_promo_code = normalize_promo_code(promo_code) if promo_code else None
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
                list_amount = amount
                final_amount = amount
                discount_amount = 0
                promo: dict[str, Any] | None = None
                promo_id: int | None = None
                promo_metadata: dict[str, object] = {}
                promo_code_hash: str | None = None
                promo_code_suffix: str | None = None
                if normalized_promo_code is not None:
                    promo = self._select_promo_for_update_cur(cur, normalized_promo_code)
                    rejected = self._discount_promo_order_rejection_cur(
                        cur,
                        promo,
                        user_id=user_id,
                        code=normalized_promo_code,
                        now=current_time,
                        validate_limits=False,
                    )
                    if rejected is not None:
                        return rejected
                    assert promo is not None
                    promo_id = int(promo["id"])
                    try:
                        discount_amount = calculate_discount_amount(
                            _row_to_promo_definition(promo),
                            list_amount,
                        )
                    except ValueError:
                        self._insert_promo_event_cur(
                            cur,
                            promo_id,
                            "rejected",
                            user_id=user_id,
                            metadata=promo_code_audit_metadata(
                                normalized_promo_code,
                                status=PaymentOrderCreationCode.PROMO_INVALID_DISCOUNT.value,
                                list_amount=list_amount,
                            ),
                        )
                        return PaymentOrderCreationResult(
                            accepted=False,
                            code=PaymentOrderCreationCode.PROMO_INVALID_DISCOUNT,
                            message="Promo discount cannot be applied to this order.",
                        )
                    final_amount = list_amount - discount_amount
                    self._release_expired_discount_reservations_cur(
                        cur,
                        promo_id,
                        now=current_time,
                    )
                    promo = self._select_promo_by_id_for_update_cur(cur, promo_id) or promo
                    promo_metadata = promo_code_audit_metadata(
                        normalized_promo_code,
                        promo_code_id=promo_id,
                        discount_amount=discount_amount,
                        list_amount=list_amount,
                        final_amount=final_amount,
                    )
                    promo_code_hash = str(promo_metadata["code_hash"])
                    promo_code_suffix = str(promo_metadata["code_suffix"])
                existing = self._find_active_pending_payment_order_cur(
                    cur,
                    user_id=user_id,
                    delivery_chat_id=delivery_chat_id,
                    provider=provider_value,
                    product=product_value,
                    amount=final_amount,
                    currency=currency_value,
                    now=current_time,
                    promo_code_id=promo_id,
                )
                if existing is not None:
                    return PaymentOrderCreationResult(
                        accepted=True,
                        code=PaymentOrderCreationCode.REUSED,
                        order=existing,
                        requires_active_subscription=requires_active_subscription,
                    )
                if normalized_promo_code is not None:
                    rejected = self._discount_promo_order_rejection_cur(
                        cur,
                        promo,
                        user_id=user_id,
                        code=normalized_promo_code,
                        now=current_time,
                        validate_limits=True,
                    )
                    if rejected is not None:
                        return rejected
                order = PaymentOrder(
                    order_id=_payment_token(),
                    nonce=_payment_token(),
                    user_id=user_id,
                    delivery_chat_id=delivery_chat_id,
                    product=product_value,
                    provider=provider_value,
                    amount=final_amount,
                    currency=currency_value,
                    status=PaymentOrderStatus.PENDING,
                    created_at=current_time,
                    expires_at=current_time + timedelta(seconds=ttl_seconds),
                    updated_at=current_time,
                    list_amount=list_amount,
                    discount_amount=discount_amount,
                    promo_code_id=promo_id,
                    promo_code_hash=promo_code_hash,
                    promo_code_suffix=promo_code_suffix,
                    metadata=promo_metadata,
                )
                inserted = self._insert_payment_order_cur(cur, order)
                if promo is not None and normalized_promo_code is not None:
                    redemption_id = self._reserve_discount_promo_redemption_cur(
                        cur,
                        promo,
                        user_id=user_id,
                        order_id=inserted.order_id,
                        discount_amount=discount_amount,
                        metadata=promo_metadata,
                        reserved_at=current_time,
                    )
                    self._increment_promo_used_count_cur(cur, int(promo["id"]))
                    inserted = self._set_payment_order_promo_redemption_cur(
                        cur,
                        inserted.order_id,
                        redemption_id,
                    ) or inserted
                    self._insert_promo_event_cur(
                        cur,
                        int(promo["id"]),
                        "reserved",
                        user_id=user_id,
                        redemption_id=redemption_id,
                        metadata=promo_metadata,
                    )
                return PaymentOrderCreationResult(
                    accepted=True,
                    code=PaymentOrderCreationCode.CREATED,
                    order=inserted,
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
        promo_code_id: int | None = None,
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
                    promo_code_id=promo_code_id,
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
                self._release_discount_promo_reservation_for_order_cur(
                    cur,
                    order_id,
                    reason="order_expired",
                )
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
                self._release_discount_promo_reservation_for_order_cur(
                    cur,
                    order_id,
                    reason="invoice_creation_failed",
                )
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

    def apply_payment_reversal(
        self,
        reversal: PaymentReversalInput,
        *,
        now: datetime | None = None,
    ) -> PaymentReversalResult:
        return apply_payment_reversal_core(self, reversal, now=now)

    def apply_payment_reconciliation(
        self,
        reconciliation: PaymentReconciliationInput,
        *,
        now: datetime | None = None,
    ) -> PaymentReconciliationResult:
        return apply_payment_reconciliation_core(self, reconciliation, now=now)

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

    def apply_payment_reversal_transaction(
        self,
        reversal: PaymentReversalInput,
        *,
        charge_aliases: tuple[str, ...],
        now: datetime,
    ) -> PaymentReversalResult:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._apply_payment_reversal_transaction_cur(
                    cur,
                    reversal,
                    charge_aliases=charge_aliases,
                    now=now,
                )

    def insert_payment_event(self, event: PaymentEvent) -> PaymentEvent:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._insert_payment_event_cur(cur, event)

    def load_payment_event(self, event_id: str) -> PaymentEvent | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM payment_events WHERE event_id = %s",
                    (event_id,),
                )
                row = cur.fetchone()
        return _row_to_payment_event(row) if row is not None else None

    def update_payment_event(self, event: PaymentEvent) -> PaymentEvent:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._update_payment_event_cur(cur, event)

    def find_payment_event(
        self,
        *,
        provider: PaymentProvider,
        charge_id: str,
        event_type: PaymentEventType | None = None,
        statuses: tuple[PaymentEventStatus, ...] = (),
    ) -> PaymentEvent | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                filters = [
                    "provider = %s",
                    "(charge_id = %s OR telegram_charge_id = %s OR provider_charge_id = %s)",
                ]
                params: list[Any] = [
                    provider.value,
                    charge_id,
                    charge_id,
                    charge_id,
                ]
                if event_type is not None:
                    filters.append("event_type = %s")
                    params.append(event_type.value)
                if statuses:
                    filters.append("status = ANY(%s)")
                    params.append([status.value for status in statuses])
                cur.execute(
                    f"""
                    SELECT *
                    FROM payment_events
                    WHERE {' AND '.join(filters)}
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT 1
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
        return _row_to_payment_event(row) if row is not None else None

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
        self._redeem_discount_promo_reservation_cur(cur, paid_order, redeemed_at=now)
        return PaymentSuccessfulPaymentResult(
            processed=True,
            code=PaymentSuccessfulPaymentCode.PROCESSED,
            order=paid_order,
            event=event,
            charge_aliases=charge_aliases,
        )

    def _apply_payment_reversal_transaction_cur(
        self,
        cur: Any,
        reversal: PaymentReversalInput,
        *,
        charge_aliases: tuple[str, ...],
        now: datetime,
    ) -> PaymentReversalResult:
        duplicate_charges = self._load_processed_provider_charges_cur(
            cur,
            provider=reversal.provider,
            charge_aliases=charge_aliases,
            event_type=reversal.event_type,
        )
        duplicate_charge = next(iter(duplicate_charges.values()), None)
        if duplicate_charge is not None:
            order = self._select_payment_order_for_update_cur(cur, duplicate_charge.order_id)
            event = build_payment_reversal_event(
                reversal,
                code=PaymentReversalCode.DUPLICATE,
                event_status=PaymentEventStatus.DUPLICATE,
                order=order,
                original_charge=duplicate_charge,
                now=now,
            )
            self._insert_payment_event_cur(cur, event)
            return PaymentReversalResult(
                processed=False,
                code=PaymentReversalCode.DUPLICATE,
                order=order,
                event=event,
                duplicate=True,
                charge_aliases=charge_aliases,
            )

        original_charges = self._load_processed_provider_charges_cur(
            cur,
            provider=reversal.provider,
            charge_aliases=charge_aliases,
            event_type=PaymentEventType.SUCCESSFUL_PAYMENT,
        )
        original_charge = next(iter(original_charges.values()), None)
        if original_charge is None:
            event = build_payment_reversal_event(
                reversal,
                code=PaymentReversalCode.ORIGINAL_PAYMENT_NOT_FOUND,
                event_status=PaymentEventStatus.PENDING_RECONCILIATION,
                reason=PaymentReversalCode.ORIGINAL_PAYMENT_NOT_FOUND.value,
                now=now,
            )
            self._insert_payment_event_cur(cur, event)
            return PaymentReversalResult(
                processed=False,
                code=PaymentReversalCode.ORIGINAL_PAYMENT_NOT_FOUND,
                event=event,
                charge_aliases=charge_aliases,
                message="Original successful payment was not found.",
            )

        order = self._select_payment_order_for_update_cur(cur, original_charge.order_id)
        if order is None:
            event = build_payment_reversal_event(
                reversal,
                code=PaymentReversalCode.ORIGINAL_ORDER_NOT_FOUND,
                event_status=PaymentEventStatus.PENDING_RECONCILIATION,
                original_charge=original_charge,
                reason=PaymentReversalCode.ORIGINAL_ORDER_NOT_FOUND.value,
                now=now,
            )
            self._insert_payment_event_cur(cur, event)
            return PaymentReversalResult(
                processed=False,
                code=PaymentReversalCode.ORIGINAL_ORDER_NOT_FOUND,
                event=event,
                charge_aliases=charge_aliases,
                message="Original payment order was not found.",
            )

        validation_code = validate_payment_reversal_order(reversal, order)
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
            self._insert_payment_event_cur(cur, event)
            return PaymentReversalResult(
                processed=False,
                code=validation_code,
                order=order,
                event=event,
                charge_aliases=charge_aliases,
                message="Payment reversal did not match the original order.",
            )

        reserved, duplicate_charge = self._reserve_reversal_processed_charges_cur(
            cur,
            reversal,
            order,
            charge_aliases=charge_aliases,
            now=now,
        )
        if duplicate_charge is not None:
            self._delete_reserved_processed_charges_cur(cur, reserved, order.order_id)
            event = build_payment_reversal_event(
                reversal,
                code=PaymentReversalCode.DUPLICATE,
                event_status=PaymentEventStatus.DUPLICATE,
                order=order,
                original_charge=duplicate_charge,
                now=now,
            )
            self._insert_payment_event_cur(cur, event)
            return PaymentReversalResult(
                processed=False,
                code=PaymentReversalCode.DUPLICATE,
                order=order,
                event=event,
                duplicate=True,
                charge_aliases=charge_aliases,
            )

        entitlement = self._select_entitlement_for_update_cur(cur, order.user_id)
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
        self._insert_payment_event_cur(cur, event)
        if application.save_entitlement:
            self._update_entitlement_cur(cur, order.user_id, entitlement)
            self._insert_entitlement_snapshot_cur(cur, order.user_id, entitlement)
        return PaymentReversalResult(
            processed=application.processed,
            code=application.code,
            order=order,
            event=event,
            charge_aliases=charge_aliases,
            message=None if application.processed else application.reason,
        )

    def _load_processed_provider_charges_cur(
        self,
        cur: Any,
        *,
        provider: PaymentProvider,
        charge_aliases: tuple[str, ...],
        event_type: PaymentEventType = PaymentEventType.SUCCESSFUL_PAYMENT,
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
                event_type.value,
                list(charge_aliases),
            ),
        )
        return {
            str(row["charge_id"]): _row_to_processed_provider_charge(row)
            for row in cur.fetchall()
        }

    def _select_payment_order_for_update_cur(
        self,
        cur: Any,
        order_id: str | None,
    ) -> PaymentOrder | None:
        if order_id is None:
            return None
        cur.execute(
            "SELECT * FROM payment_orders WHERE order_id = %s FOR UPDATE",
            (order_id,),
        )
        row = cur.fetchone()
        return _row_to_payment_order(row) if row is not None else None

    def _reserve_reversal_processed_charges_cur(
        self,
        cur: Any,
        reversal: PaymentReversalInput,
        order: PaymentOrder,
        *,
        charge_aliases: tuple[str, ...],
        now: datetime,
    ) -> tuple[list[ProcessedProviderCharge], ProcessedProviderCharge | None]:
        reserved: list[ProcessedProviderCharge] = []
        for charge_alias in charge_aliases:
            charge = ProcessedProviderCharge(
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
            stored_charge, inserted = self._insert_processed_provider_charge_cur(cur, charge)
            if inserted:
                reserved.append(stored_charge)
                continue
            return reserved, stored_charge
        return reserved, None

    def _delete_reserved_processed_charges_cur(
        self,
        cur: Any,
        reserved: list[ProcessedProviderCharge],
        order_id: str,
    ) -> None:
        for charge in reserved:
            cur.execute(
                """
                DELETE FROM processed_provider_charges
                WHERE provider = %s
                  AND charge_id = %s
                  AND event_type = %s
                  AND order_id = %s
                """,
                (
                    charge.provider.value,
                    charge.charge_id,
                    charge.event_type.value,
                    order_id,
                ),
            )

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

    def _update_payment_event_cur(self, cur: Any, event: PaymentEvent) -> PaymentEvent:
        cur.execute(
            """
            UPDATE payment_events
            SET order_id = %s,
                charge_id = %s,
                telegram_charge_id = %s,
                provider_charge_id = %s,
                user_id = %s,
                delivery_chat_id = %s,
                product = %s,
                amount = %s,
                currency = %s,
                status = %s,
                reason = %s,
                raw_payload_redacted = %s,
                processed_at = %s
            WHERE event_id = %s
            RETURNING *
            """,
            (
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
                (
                    _normalize_datetime(event.processed_at)
                    if event.processed_at is not None
                    else None
                ),
                event.event_id,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Could not update payment event.")
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
        promo_code_id: int | None = None,
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
              AND promo_code_id IS NOT DISTINCT FROM %s
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
                promo_code_id,
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
                list_amount,
                discount_amount,
                currency,
                status,
                invoice_link,
                pre_checkout_approved_at,
                promo_code_id,
                promo_redemption_id,
                promo_code_hash,
                promo_code_suffix,
                metadata_json,
                created_at,
                expires_at,
                paid_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                order.list_amount,
                order.discount_amount,
                order.currency.value,
                order.status.value,
                order.invoice_link,
                (
                    _normalize_datetime(order.pre_checkout_approved_at)
                    if order.pre_checkout_approved_at is not None
                    else None
                ),
                order.promo_code_id,
                order.promo_redemption_id,
                order.promo_code_hash,
                order.promo_code_suffix,
                _jsonb(order.metadata),
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

    def _upsert_promo_definition_cur(
        self,
        cur: Any,
        definition: PromoCodeDefinition,
    ) -> dict[str, Any]:
        cur.execute(
            """
            INSERT INTO promo_codes (
                code,
                kind,
                value,
                max_uses,
                max_redemptions,
                per_user_limit,
                used_count,
                valid_until,
                expires_at,
                is_active,
                discount_percent,
                discount_amount,
                monthly_duration_months,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE
            SET kind = EXCLUDED.kind,
                value = EXCLUDED.value,
                max_uses = EXCLUDED.max_uses,
                max_redemptions = EXCLUDED.max_redemptions,
                per_user_limit = EXCLUDED.per_user_limit,
                used_count = GREATEST(promo_codes.used_count, EXCLUDED.used_count),
                valid_until = EXCLUDED.valid_until,
                expires_at = EXCLUDED.expires_at,
                is_active = EXCLUDED.is_active,
                discount_percent = EXCLUDED.discount_percent,
                discount_amount = EXCLUDED.discount_amount,
                monthly_duration_months = EXCLUDED.monthly_duration_months,
                metadata_json = EXCLUDED.metadata_json
            RETURNING *
            """,
            (
                definition.code,
                definition.kind.value,
                _promo_definition_value(definition),
                definition.max_redemptions,
                definition.max_redemptions,
                definition.per_user_limit or 1,
                definition.used_count,
                _parse_datetime(definition.expires_at),
                _parse_datetime(definition.expires_at),
                definition.active,
                definition.discount_percent,
                definition.discount_amount,
                definition.monthly_duration_months,
                _jsonb(definition.metadata),
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Could not create promo code.")
        return dict(row)

    def _select_promo_for_update_cur(self, cur: Any, code: str) -> dict[str, Any] | None:
        cur.execute(
            """
            SELECT *
            FROM promo_codes
            WHERE code = %s
            FOR UPDATE
            """,
            (code,),
        )
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def _select_promo_by_id_for_update_cur(
        self,
        cur: Any,
        promo_id: int,
    ) -> dict[str, Any] | None:
        cur.execute(
            """
            SELECT *
            FROM promo_codes
            WHERE id = %s
            FOR UPDATE
            """,
            (promo_id,),
        )
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def _validate_promo_redemption_cur(
        self,
        cur: Any,
        promo: dict[str, Any],
        user_id: int,
        now: datetime,
    ) -> PromoRedemptionResult | None:
        code = str(promo["code"])
        promo_id = int(promo["id"])
        if not bool(promo.get("is_active", True)):
            return PromoRedemptionResult(PromoRedemptionStatus.DISABLED, code)

        valid_from = _parse_datetime(promo.get("valid_from"))
        if valid_from is not None and valid_from > now:
            return PromoRedemptionResult(PromoRedemptionStatus.NOT_FOUND, code)

        expires_at = _promo_expires_at(promo)
        if expires_at is not None and expires_at <= now:
            return PromoRedemptionResult(PromoRedemptionStatus.EXPIRED, code)

        cur.execute(
            """
            SELECT count(*) AS redemption_count
            FROM promo_redemptions
            WHERE promo_code_id = %s
              AND user_id = %s
              AND status IN ('reserved', 'redeemed')
            """,
            (promo_id, user_id),
        )
        user_redemption_count = int(cur.fetchone()["redemption_count"])
        if user_redemption_count >= _promo_per_user_limit(promo):
            return PromoRedemptionResult(
                PromoRedemptionStatus.ALREADY_USED,
                code,
                used_by_chat_id=user_id,
            )

        max_redemptions = _promo_max_redemptions(promo)
        if (
            max_redemptions is not None
            and _non_negative_int(promo.get("used_count")) >= max_redemptions
        ):
            return PromoRedemptionResult(
                PromoRedemptionStatus.ALREADY_USED,
                code,
                used_by_chat_id=self._first_promo_redeemer_cur(cur, promo_id),
            )
        return None

    def _discount_promo_order_rejection_cur(
        self,
        cur: Any,
        promo: dict[str, Any] | None,
        *,
        user_id: int,
        code: str,
        now: datetime,
        validate_limits: bool,
    ) -> PaymentOrderCreationResult | None:
        if promo is None:
            self._insert_promo_event_cur(
                cur,
                None,
                "rejected",
                user_id=user_id,
                metadata=promo_code_audit_metadata(
                    code,
                    status=PaymentOrderCreationCode.PROMO_NOT_FOUND.value,
                ),
            )
            return PaymentOrderCreationResult(
                accepted=False,
                code=PaymentOrderCreationCode.PROMO_NOT_FOUND,
                message="Promo code was not found.",
            )

        promo_id = int(promo["id"])
        try:
            promo_kind = _promo_definition_kind(promo)
        except ValueError:
            self._insert_promo_event_cur(
                cur,
                promo_id,
                "rejected",
                user_id=user_id,
                metadata=promo_code_audit_metadata(
                    code,
                    status=PaymentOrderCreationCode.PROMO_NOT_FOUND.value,
                ),
            )
            return PaymentOrderCreationResult(
                accepted=False,
                code=PaymentOrderCreationCode.PROMO_NOT_FOUND,
                message="Promo code was not found.",
            )

        if promo_kind != PromoCodeKind.DISCOUNT:
            self._insert_promo_event_cur(
                cur,
                promo_id,
                "rejected",
                user_id=user_id,
                metadata=promo_code_audit_metadata(
                    code,
                    status=PaymentOrderCreationCode.PROMO_NOT_DISCOUNT.value,
                    kind=promo_kind.value,
                ),
            )
            return PaymentOrderCreationResult(
                accepted=False,
                code=PaymentOrderCreationCode.PROMO_NOT_DISCOUNT,
                message="Promo code is not a payment discount.",
            )

        if not bool(promo.get("is_active", True)):
            self._insert_promo_event_cur(
                cur,
                promo_id,
                "rejected",
                user_id=user_id,
                metadata=promo_code_audit_metadata(
                    code,
                    status=PaymentOrderCreationCode.PROMO_DISABLED.value,
                ),
            )
            return PaymentOrderCreationResult(
                accepted=False,
                code=PaymentOrderCreationCode.PROMO_DISABLED,
                message="Promo code is disabled.",
            )

        valid_from = _parse_datetime(promo.get("valid_from"))
        if valid_from is not None and valid_from > now:
            self._insert_promo_event_cur(
                cur,
                promo_id,
                "rejected",
                user_id=user_id,
                metadata=promo_code_audit_metadata(
                    code,
                    status=PaymentOrderCreationCode.PROMO_NOT_FOUND.value,
                ),
            )
            return PaymentOrderCreationResult(
                accepted=False,
                code=PaymentOrderCreationCode.PROMO_NOT_FOUND,
                message="Promo code was not found.",
            )

        expires_at = _promo_expires_at(promo)
        if expires_at is not None and expires_at <= now:
            self._insert_promo_event_cur(
                cur,
                promo_id,
                "rejected",
                user_id=user_id,
                metadata=promo_code_audit_metadata(
                    code,
                    status=PaymentOrderCreationCode.PROMO_EXPIRED.value,
                ),
            )
            return PaymentOrderCreationResult(
                accepted=False,
                code=PaymentOrderCreationCode.PROMO_EXPIRED,
                message="Promo code is expired.",
            )

        if not validate_limits:
            return None

        cur.execute(
            """
            SELECT count(*) AS redemption_count
            FROM promo_redemptions
            WHERE promo_code_id = %s
              AND user_id = %s
              AND status IN ('reserved', 'redeemed')
            """,
            (promo_id, user_id),
        )
        user_redemption_count = int(cur.fetchone()["redemption_count"])
        if user_redemption_count >= _promo_per_user_limit(promo):
            self._insert_promo_event_cur(
                cur,
                promo_id,
                "rejected",
                user_id=user_id,
                metadata=promo_code_audit_metadata(
                    code,
                    status=PaymentOrderCreationCode.PROMO_ALREADY_USED.value,
                ),
            )
            return PaymentOrderCreationResult(
                accepted=False,
                code=PaymentOrderCreationCode.PROMO_ALREADY_USED,
                message="Promo code has already been used.",
            )

        max_redemptions = _promo_max_redemptions(promo)
        if (
            max_redemptions is not None
            and _non_negative_int(promo.get("used_count")) >= max_redemptions
        ):
            self._insert_promo_event_cur(
                cur,
                promo_id,
                "rejected",
                user_id=user_id,
                metadata=promo_code_audit_metadata(
                    code,
                    status=PaymentOrderCreationCode.PROMO_ALREADY_USED.value,
                ),
            )
            return PaymentOrderCreationResult(
                accepted=False,
                code=PaymentOrderCreationCode.PROMO_ALREADY_USED,
                message="Promo code has already been used.",
            )
        return None

    def _insert_promo_redemption_cur(
        self,
        cur: Any,
        promo: dict[str, Any],
        user_id: int,
        redeemed_at: datetime,
    ) -> int:
        kind = _promo_kind_value(promo)
        cur.execute(
            """
            INSERT INTO promo_redemptions (
                promo_code_id,
                user_id,
                status,
                kind,
                discount_amount,
                metadata_json,
                redeemed_at
            )
            VALUES (%s, %s, 'redeemed', %s, %s, %s, %s)
            RETURNING id
            """,
            (
                int(promo["id"]),
                user_id,
                kind,
                (
                    _non_negative_int(promo.get("discount_amount"))
                    if promo.get("discount_amount") is not None
                    else None
                ),
                _jsonb(
                    promo_code_audit_metadata(
                        str(promo["code"]),
                        kind=kind,
                        discount_percent=promo.get("discount_percent"),
                        discount_amount=promo.get("discount_amount"),
                        monthly_duration_months=_promo_monthly_duration(promo),
                    )
                ),
                redeemed_at,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Could not create promo redemption.")
        return int(row["id"])

    def _reserve_discount_promo_redemption_cur(
        self,
        cur: Any,
        promo: dict[str, Any],
        *,
        user_id: int,
        order_id: str,
        discount_amount: int,
        metadata: dict[str, object],
        reserved_at: datetime,
    ) -> int:
        cur.execute(
            """
            INSERT INTO promo_redemptions (
                promo_code_id,
                user_id,
                order_id,
                status,
                kind,
                discount_amount,
                metadata_json,
                redeemed_at
            )
            VALUES (%s, %s, %s, 'reserved', 'discount', %s, %s, %s)
            RETURNING id
            """,
            (
                int(promo["id"]),
                user_id,
                order_id,
                discount_amount,
                _jsonb(metadata),
                reserved_at,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Could not reserve promo discount.")
        return int(row["id"])

    def _set_payment_order_promo_redemption_cur(
        self,
        cur: Any,
        order_id: str,
        redemption_id: int,
    ) -> PaymentOrder | None:
        cur.execute(
            """
            UPDATE payment_orders
            SET promo_redemption_id = %s,
                updated_at = now()
            WHERE order_id = %s
            RETURNING *
            """,
            (redemption_id, order_id),
        )
        row = cur.fetchone()
        return _row_to_payment_order(row) if row is not None else None

    def _redeem_discount_promo_reservation_cur(
        self,
        cur: Any,
        order: PaymentOrder,
        *,
        redeemed_at: datetime,
    ) -> None:
        if order.promo_redemption_id is None:
            return
        cur.execute(
            """
            UPDATE promo_redemptions
            SET status = 'redeemed',
                redeemed_at = %s,
                metadata_json = metadata_json || %s
            WHERE id = %s
              AND status = 'reserved'
            RETURNING promo_code_id, user_id, metadata_json
            """,
            (
                _normalize_datetime(redeemed_at),
                _jsonb({"finalized_by": "successful_payment"}),
                order.promo_redemption_id,
            ),
        )
        row = cur.fetchone()
        if row is None:
            return
        metadata = dict(row["metadata_json"]) if isinstance(row.get("metadata_json"), dict) else {}
        metadata["finalized_by"] = "successful_payment"
        self._insert_promo_event_cur(
            cur,
            int(row["promo_code_id"]),
            "redeemed",
            user_id=int(row["user_id"]),
            redemption_id=order.promo_redemption_id,
            metadata=metadata,
        )

    def _release_discount_promo_reservation_for_order_cur(
        self,
        cur: Any,
        order_id: str,
        *,
        reason: str,
    ) -> None:
        cur.execute(
            """
            SELECT *
            FROM payment_orders
            WHERE order_id = %s
            FOR UPDATE
            """,
            (order_id,),
        )
        order_row = cur.fetchone()
        if order_row is None or order_row.get("promo_redemption_id") is None:
            return
        redemption_id = int(order_row["promo_redemption_id"])
        cur.execute(
            """
            UPDATE promo_redemptions
            SET status = 'released',
                metadata_json = metadata_json || %s
            WHERE id = %s
              AND status = 'reserved'
            RETURNING promo_code_id, user_id, metadata_json
            """,
            (_jsonb({"release_reason": reason}), redemption_id),
        )
        redemption_row = cur.fetchone()
        if redemption_row is None:
            return
        promo_id = int(redemption_row["promo_code_id"])
        cur.execute(
            """
            UPDATE promo_codes
            SET used_count = GREATEST(used_count - 1, 0)
            WHERE id = %s
            """,
            (promo_id,),
        )
        metadata = (
            dict(redemption_row["metadata_json"])
            if isinstance(redemption_row.get("metadata_json"), dict)
            else {}
        )
        metadata["release_reason"] = reason
        self._insert_promo_event_cur(
            cur,
            promo_id,
            "released",
            user_id=int(redemption_row["user_id"]),
            redemption_id=redemption_id,
            metadata=metadata,
        )

    def _release_expired_discount_reservations_cur(
        self,
        cur: Any,
        promo_id: int,
        *,
        now: datetime,
    ) -> None:
        cur.execute(
            """
            SELECT order_id
            FROM payment_orders
            WHERE promo_code_id = %s
              AND status = 'pending'
              AND expires_at <= %s
            FOR UPDATE
            """,
            (promo_id, _normalize_datetime(now)),
        )
        order_ids = [str(row["order_id"]) for row in cur.fetchall()]
        for order_id in order_ids:
            self._release_discount_promo_reservation_for_order_cur(
                cur,
                order_id,
                reason="order_expired",
            )
            cur.execute(
                """
                UPDATE payment_orders
                SET status = 'expired',
                    updated_at = now()
                WHERE order_id = %s
                  AND status = 'pending'
                """,
                (order_id,),
            )

    def _increment_promo_used_count_cur(self, cur: Any, promo_id: int) -> None:
        cur.execute(
            """
            UPDATE promo_codes
            SET used_count = used_count + 1
            WHERE id = %s
            """,
            (promo_id,),
        )

    def _link_promo_redemption_entitlement_event_cur(
        self,
        cur: Any,
        redemption_id: int,
        entitlement_event_id: int | None,
    ) -> None:
        if entitlement_event_id is None:
            return
        cur.execute(
            """
            UPDATE promo_redemptions
            SET entitlement_event_id = %s
            WHERE id = %s
            """,
            (entitlement_event_id, redemption_id),
        )

    def _insert_promo_event_cur(
        self,
        cur: Any,
        promo_id: int | None,
        event_type: str,
        *,
        user_id: int | None = None,
        redemption_id: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        cur.execute(
            """
            INSERT INTO promo_events (
                promo_code_id,
                redemption_id,
                user_id,
                event_type,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (promo_id, redemption_id, user_id, event_type, _jsonb(metadata or {})),
        )

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
    ) -> int:
        kind = _promo_kind_value(promo)
        value = _promo_monthly_duration(promo) if kind in PROMO_ACCESS_KINDS else max(
            1,
            _non_negative_int(promo.get("value")),
        )
        charge_id = promo_code_grant_charge_id(code)

        if kind in PROMO_ACCESS_KINDS:
            apply_monthly_access_promo_grant(
                entitlement,
                charge_id,
                now=now,
                months=value,
            )
        elif kind == "extra_one_day":
            for index in range(value):
                apply_extra_one_day_payment(entitlement, f"{charge_id}:extra_one_day:{index}")
        elif kind == "extra_weekly_pdf":
            for index in range(value):
                apply_extra_weekly_pdf_payment(entitlement, f"{charge_id}:extra_weekly_pdf:{index}")
        elif kind == "test_access_days":
            grant_test_access(entitlement, now=now, days=value)

        return self._insert_entitlement_event_cur(
            cur,
            user_id,
            LEDGER_EVENT_PROMO_GRANT,
            source="promo",
            amount=value,
            delta_generations=0,
            metadata=promo_code_audit_metadata(
                code,
                promo_code_id=int(promo["id"]),
                promo_kind=kind,
                monthly_duration_months=value if kind in PROMO_ACCESS_KINDS else None,
            ),
        )


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


def _row_to_promo_definition(row: dict[str, Any]) -> PromoCodeDefinition:
    metadata = row.get("metadata_json")
    return PromoCodeDefinition(
        code=str(row["code"]),
        kind=_promo_definition_kind(row),
        active=bool(row.get("is_active", True)),
        expires_at=_format_datetime(_promo_expires_at(row)),
        max_redemptions=_promo_max_redemptions(row),
        per_user_limit=_promo_per_user_limit(row),
        discount_percent=(
            _non_negative_int(row.get("discount_percent"))
            if row.get("discount_percent") is not None
            else None
        ),
        discount_amount=(
            _non_negative_int(row.get("discount_amount"))
            if row.get("discount_amount") is not None
            else None
        ),
        monthly_duration_months=_promo_monthly_duration(row),
        used_count=_non_negative_int(row.get("used_count")),
        created_at=_format_datetime(row.get("created_at")),
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
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
        list_amount=(
            int(row["list_amount"]) if row.get("list_amount") is not None else None
        ),
        discount_amount=_non_negative_int(row.get("discount_amount")),
        promo_code_id=(
            int(row["promo_code_id"]) if row.get("promo_code_id") is not None else None
        ),
        promo_redemption_id=(
            int(row["promo_redemption_id"])
            if row.get("promo_redemption_id") is not None
            else None
        ),
        promo_code_hash=(
            str(row["promo_code_hash"]) if row.get("promo_code_hash") is not None else None
        ),
        promo_code_suffix=(
            str(row["promo_code_suffix"])
            if row.get("promo_code_suffix") is not None
            else None
        ),
        metadata=(
            dict(row["metadata_json"]) if isinstance(row.get("metadata_json"), dict) else {}
        ),
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


def _promo_definition_value(definition: PromoCodeDefinition) -> int:
    if definition.kind == PromoCodeKind.MONTHLY_ACCESS:
        return definition.monthly_duration_months
    return definition.discount_percent or definition.discount_amount or 1


def _promo_kind_value(row: dict[str, Any]) -> str:
    return str(row.get("kind") or PromoCodeKind.MONTHLY_ACCESS.value)


def _promo_definition_kind(row: dict[str, Any]) -> PromoCodeKind:
    kind = _promo_kind_value(row)
    if kind in PROMO_ACCESS_KINDS:
        return PromoCodeKind.MONTHLY_ACCESS
    if kind == PromoCodeKind.DISCOUNT.value:
        return PromoCodeKind.DISCOUNT
    raise ValueError(f"Unsupported promo definition kind: {kind}")


def _promo_expires_at(row: dict[str, Any]) -> datetime | None:
    return _parse_datetime(row.get("expires_at") or row.get("valid_until"))


def _promo_max_redemptions(row: dict[str, Any]) -> int | None:
    value = row.get("max_redemptions")
    if value is None:
        value = row.get("max_uses")
    if value is None:
        return None
    return _non_negative_int(value)


def _promo_per_user_limit(row: dict[str, Any]) -> int:
    return max(1, _non_negative_int(row.get("per_user_limit") or 1))


def _promo_monthly_duration(row: dict[str, Any]) -> int:
    value = row.get("monthly_duration_months")
    if value is None:
        value = row.get("value")
    return max(1, _non_negative_int(value))


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
