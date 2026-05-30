from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from .postgres_connection import DirectPostgresConnectionProvider, PostgresConnectionProvider
from .postgres_promo_migrations import MIGRATIONS, run_promo_schema_migrations
from .postgres_schema_validation import (
    SCHEMA_MIGRATIONS_COLUMNS,
    PostgresSchemaExpectation,
    validate_postgres_schema,
)
from .promo_codes import (
    PromoCodeDefinition,
    PromoCodeKind,
    PromoCodeRecord,
    normalize_promo_code,
    promo_code_grant_charge_id,
)


PROMO_IMPORT_LOCK_ID = 4_382_026_053_000_001
ACTIVE_REDEMPTION_STATUSES = ("reserved", "redeemed")

PromoClaimStatus = Literal[
    "redeemed",
    "reserved",
    "already_redeemed",
    "not_found",
    "disabled",
    "expired",
    "not_access_code",
    "already_used",
    "max_uses_reached",
    "idempotency_key_conflict",
]

PROMO_SCHEMA_EXPECTATION = PostgresSchemaExpectation(
    component="promo",
    migration_versions=tuple(migration.version for migration in MIGRATIONS),
    table_columns={
        "schema_migrations": SCHEMA_MIGRATIONS_COLUMNS,
        "promo_codes": (
            "code",
            "kind",
            "discount_type",
            "discount_percent",
            "discount_amount_minor",
            "duration_days",
            "monthly_duration_months",
            "max_uses",
            "per_user_limit",
            "expires_at",
            "active",
            "created_by",
            "created_at",
            "updated_at",
            "disabled_at",
            "disabled_by",
            "campaign_key",
            "metadata_json",
        ),
        "promo_code_redemptions": (
            "redemption_id",
            "code",
            "chat_id",
            "user_id",
            "status",
            "idempotency_key",
            "offered_at",
            "reserved_at",
            "redeemed_at",
            "released_at",
            "failed_at",
            "window_expires_at",
            "payment_order_id",
            "payment_provider",
            "payment_product",
            "currency",
            "original_amount_minor",
            "discount_amount_minor",
            "final_amount_minor",
            "entitlement_charge_id",
            "campaign_key",
            "campaign_step_key",
            "telegram_message_id",
            "failure_reason",
            "source",
            "metadata_json",
            "created_at",
            "updated_at",
        ),
        "promo_import_runs": (
            "migration_id",
            "source_fingerprint",
            "source_metadata_json",
            "result_json",
            "status",
            "started_at",
            "finished_at",
        ),
    },
    indexes=(
        "idx_promo_codes_active_kind",
        "idx_promo_codes_campaign_key",
        "idx_promo_codes_expires_at",
        "idx_promo_code_redemptions_idempotency_key_unique",
        "idx_promo_code_redemptions_payment_order_unique",
        "idx_promo_code_redemptions_entitlement_charge_unique",
        "idx_promo_code_redemptions_code_chat_active_unique",
        "idx_promo_code_redemptions_code_status",
        "idx_promo_code_redemptions_chat_status",
    ),
    constraints=(
        "promo_codes_pkey",
        "chk_promo_codes_code_non_empty",
        "chk_promo_codes_kind",
        "chk_promo_codes_discount_type",
        "chk_promo_codes_discount_shape",
        "chk_promo_codes_limits",
        "chk_promo_codes_duration_days",
        "promo_code_redemptions_pkey",
        "chk_promo_code_redemptions_status",
        "chk_promo_code_redemptions_idempotency_key_non_empty",
        "chk_promo_code_redemptions_source_non_empty",
        "chk_promo_code_redemptions_amounts",
        "chk_promo_code_redemptions_payment_provider",
        "chk_promo_code_redemptions_redeemed_at_shape",
        "chk_promo_import_runs_status",
    ),
    remediation="Run promo migrations before use.",
)


@dataclass(frozen=True)
class StoredPromoCode:
    code: str
    kind: PromoCodeKind | str
    active: bool
    max_redemptions: int
    per_user_limit: int
    expires_at: str | None
    discount_percent: int | None
    discount_amount: int | None
    monthly_duration_months: int
    duration_days: int | None
    created_by: int | None
    created_at: datetime | None
    updated_at: datetime | None
    disabled_at: datetime | None
    disabled_by: int | None
    campaign_key: str | None
    metadata: dict[str, Any]

    def to_definition(self) -> PromoCodeDefinition:
        return PromoCodeDefinition(
            code=self.code,
            kind=self.kind,
            active=self.active,
            max_redemptions=self.max_redemptions,
            per_user_limit=self.per_user_limit,
            expires_at=self.expires_at,
            discount_percent=self.discount_percent,
            discount_amount=self.discount_amount,
            monthly_duration_months=self.monthly_duration_months,
        )


@dataclass(frozen=True)
class PromoRedemption:
    redemption_id: int
    code: str
    chat_id: int
    user_id: int | None
    status: str
    idempotency_key: str
    offered_at: datetime | None
    reserved_at: datetime | None
    redeemed_at: datetime | None
    released_at: datetime | None
    failed_at: datetime | None
    window_expires_at: datetime | None
    payment_order_id: str | None
    payment_provider: str | None
    payment_product: str | None
    currency: str | None
    original_amount_minor: int | None
    discount_amount_minor: int | None
    final_amount_minor: int | None
    entitlement_charge_id: str | None
    campaign_key: str | None
    campaign_step_key: str | None
    telegram_message_id: int | None
    failure_reason: str | None
    source: str
    metadata: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class PromoRedemptionResult:
    status: PromoClaimStatus
    code: str
    chat_id: int | None = None
    redemption: PromoRedemption | None = None


class PostgresPromoStore:
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
                    run_promo_schema_migrations(cur)

    def validate_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                validate_postgres_schema(cur, PROMO_SCHEMA_EXPECTATION)

    def create_or_update_promo_code(
        self,
        definition: PromoCodeDefinition,
        *,
        created_by: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        duration_days: int | None = None,
        campaign_key: str | None = None,
    ) -> StoredPromoCode:
        normalized = PromoCodeDefinition(**definition.to_dict())
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._upsert_promo_code_cur(
                    cur,
                    normalized,
                    created_by=created_by,
                    metadata=metadata,
                    duration_days=duration_days,
                    campaign_key=campaign_key,
                )

    def update_promo_code(
        self,
        definition: PromoCodeDefinition,
        *,
        created_by: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        duration_days: int | None = None,
        campaign_key: str | None = None,
    ) -> StoredPromoCode:
        return self.create_or_update_promo_code(
            definition,
            created_by=created_by,
            metadata=metadata,
            duration_days=duration_days,
            campaign_key=campaign_key,
        )

    def get_promo_code(self, raw_code: str) -> StoredPromoCode | None:
        code = normalize_promo_code(raw_code)
        if not code:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM promo_codes WHERE code = %s", (code,))
                row = cur.fetchone()
        return _promo_from_row(row) if row is not None else None

    def list_active_promo_codes(self, *, now: datetime | None = None) -> list[StoredPromoCode]:
        cutoff = _normalize_now(now)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM promo_codes
                    WHERE active
                      AND (expires_at IS NULL OR expires_at > %s)
                    ORDER BY code
                    """,
                    (cutoff,),
                )
                return [_promo_from_row(row) for row in cur.fetchall()]

    def disable_promo_code(
        self,
        raw_code: str,
        *,
        disabled_by: int | None = None,
    ) -> StoredPromoCode | None:
        code = normalize_promo_code(raw_code)
        if not code:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE promo_codes
                    SET active = FALSE,
                        disabled_at = COALESCE(disabled_at, now()),
                        disabled_by = COALESCE(%s, disabled_by),
                        updated_at = now()
                    WHERE code = %s
                    RETURNING *
                    """,
                    (disabled_by, code),
                )
                row = cur.fetchone()
        return _promo_from_row(row) if row is not None else None

    def redeem_promo_code(
        self,
        raw_code: str,
        *,
        chat_id: int,
        user_id: int | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
        entitlement_charge_id: str | None = None,
        payment_order_id: str | None = None,
        kind: PromoCodeKind | str | None = None,
    ) -> PromoRedemptionResult:
        return self._claim_promo_code(
            raw_code,
            chat_id=chat_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            now=now,
            metadata=metadata,
            entitlement_charge_id=entitlement_charge_id,
            payment_order_id=payment_order_id,
            kind=kind,
            status="redeemed",
        )

    def reserve_promo_code(
        self,
        raw_code: str,
        *,
        chat_id: int,
        user_id: int | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
        payment_order_id: str | None = None,
        entitlement_charge_id: str | None = None,
        kind: PromoCodeKind | str | None = None,
    ) -> PromoRedemptionResult:
        return self._claim_promo_code(
            raw_code,
            chat_id=chat_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            now=now,
            metadata=metadata,
            entitlement_charge_id=entitlement_charge_id,
            payment_order_id=payment_order_id,
            kind=kind,
            status="reserved",
        )

    def finalize_promo_redemption(
        self,
        redemption_id: int,
        *,
        entitlement_charge_id: str | None = None,
        now: datetime | None = None,
    ) -> PromoRedemption | None:
        redeemed_at = _normalize_now(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE promo_code_redemptions
                        SET status = 'redeemed',
                            redeemed_at = COALESCE(redeemed_at, %s),
                            entitlement_charge_id = COALESCE(%s, entitlement_charge_id),
                            updated_at = now()
                        WHERE redemption_id = %s
                          AND status IN ('reserved', 'redeemed')
                        RETURNING *
                        """,
                        (redeemed_at, _optional_text(entitlement_charge_id), int(redemption_id)),
                    )
                    row = cur.fetchone()
        return _redemption_from_row(row) if row is not None else None

    def release_promo_redemption(
        self,
        redemption_id: int,
        *,
        failure_reason: str | None = None,
        now: datetime | None = None,
    ) -> PromoRedemption | None:
        released_at = _normalize_now(now)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE promo_code_redemptions
                        SET status = 'released',
                            released_at = COALESCE(released_at, %s),
                            failure_reason = COALESCE(%s, failure_reason),
                            updated_at = now()
                        WHERE redemption_id = %s
                          AND status = 'reserved'
                        RETURNING *
                        """,
                        (released_at, _optional_text(failure_reason), int(redemption_id)),
                    )
                    row = cur.fetchone()
        return _redemption_from_row(row) if row is not None else None

    def get_redemption_status(self, raw_code: str, chat_id: int) -> PromoRedemption | None:
        code = normalize_promo_code(raw_code)
        if not code:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._get_active_redemption_cur(cur, code, int(chat_id), for_update=False)

    def import_json_state(
        self,
        promo_codes: Mapping[str, PromoCodeRecord],
        *,
        migration_id: str | None = None,
        source_fingerprint: str | None = None,
        source_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, int]:
        normalized = _normalize_json_records(promo_codes)
        result = _json_import_result(normalized)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if migration_id is not None:
                        existing = self._begin_import_run_cur(
                            cur,
                            migration_id=migration_id,
                            source_fingerprint=source_fingerprint or "",
                            source_metadata=source_metadata or {},
                        )
                        if existing is not None:
                            return existing
                    inserted_redemptions = 0
                    for code, record in normalized.items():
                        self._upsert_promo_code_cur(
                            cur,
                            _definition_from_json_record(code, record),
                            created_by=None,
                            metadata={"source": "json_import"},
                            duration_days=None,
                            campaign_key=None,
                        )
                        if record.used_by_chat_id is not None:
                            inserted = self._insert_json_import_redemption_cur(cur, code, record)
                            if inserted is not None:
                                inserted_redemptions += 1
                    result["redemptions"] = inserted_redemptions
                    if migration_id is not None:
                        cur.execute(
                            """
                            UPDATE promo_import_runs
                            SET status = 'applied',
                                result_json = %s,
                                finished_at = now()
                            WHERE migration_id = %s
                            """,
                            (_jsonb(result), migration_id),
                        )
                    return result

    def _claim_promo_code(
        self,
        raw_code: str,
        *,
        chat_id: int,
        user_id: int | None,
        idempotency_key: str | None,
        now: datetime | None,
        metadata: Mapping[str, Any] | None,
        entitlement_charge_id: str | None = None,
        payment_order_id: str | None = None,
        kind: PromoCodeKind | str | None,
        status: Literal["reserved", "redeemed"],
    ) -> PromoRedemptionResult:
        code = normalize_promo_code(raw_code)
        if not code:
            return PromoRedemptionResult("not_found", "", int(chat_id))
        chat_id = int(chat_id)
        claimed_at = _normalize_now(now)
        idempotency_key = _optional_text(idempotency_key) or f"promo:{code}:chat:{chat_id}:{status}"
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    promo = self._get_promo_code_cur(cur, code, for_update=True)
                    if promo is None:
                        return PromoRedemptionResult("not_found", code, chat_id)
                    if not promo.active:
                        return PromoRedemptionResult("disabled", code, chat_id)
                    expires_at = _parse_datetime(promo.expires_at)
                    if expires_at is not None and expires_at <= claimed_at:
                        return PromoRedemptionResult("expired", code, chat_id)
                    if kind is not None and _kind_value(promo.kind) != _kind_value(kind):
                        return PromoRedemptionResult("not_access_code", code, chat_id)

                    existing = self._get_active_redemption_cur(cur, code, chat_id, for_update=True)
                    if existing is not None:
                        return PromoRedemptionResult("already_redeemed", code, chat_id, existing)

                    current_uses = self._active_redemption_count_cur(cur, code)
                    if current_uses >= promo.max_redemptions:
                        if promo.max_redemptions == 1:
                            return PromoRedemptionResult("already_used", code, chat_id)
                        return PromoRedemptionResult("max_uses_reached", code, chat_id)

                    redemption = self._insert_redemption_cur(
                        cur,
                        code=code,
                        chat_id=chat_id,
                        user_id=user_id,
                        idempotency_key=idempotency_key,
                        status=status,
                        claimed_at=claimed_at,
                        metadata=metadata,
                        entitlement_charge_id=entitlement_charge_id,
                        payment_order_id=payment_order_id,
                    )
                    if redemption is not None:
                        return PromoRedemptionResult(status, code, chat_id, redemption)

                    existing_by_key = self._get_redemption_by_idempotency_key_cur(cur, idempotency_key)
                    if (
                        existing_by_key is not None
                        and existing_by_key.code == code
                        and existing_by_key.chat_id == chat_id
                    ):
                        return PromoRedemptionResult("already_redeemed", code, chat_id, existing_by_key)
                    return PromoRedemptionResult("idempotency_key_conflict", code, chat_id)

    def _upsert_promo_code_cur(
        self,
        cur: Any,
        definition: PromoCodeDefinition,
        *,
        created_by: int | None,
        metadata: Mapping[str, Any] | None,
        duration_days: int | None,
        campaign_key: str | None,
    ) -> StoredPromoCode:
        discount_type = _discount_type(definition)
        cur.execute(
            """
            INSERT INTO promo_codes (
                code,
                kind,
                discount_type,
                discount_percent,
                discount_amount_minor,
                duration_days,
                monthly_duration_months,
                max_uses,
                per_user_limit,
                expires_at,
                active,
                created_by,
                campaign_key,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                kind = EXCLUDED.kind,
                discount_type = EXCLUDED.discount_type,
                discount_percent = EXCLUDED.discount_percent,
                discount_amount_minor = EXCLUDED.discount_amount_minor,
                duration_days = EXCLUDED.duration_days,
                monthly_duration_months = EXCLUDED.monthly_duration_months,
                max_uses = EXCLUDED.max_uses,
                per_user_limit = EXCLUDED.per_user_limit,
                expires_at = EXCLUDED.expires_at,
                active = EXCLUDED.active,
                campaign_key = EXCLUDED.campaign_key,
                metadata_json = EXCLUDED.metadata_json,
                disabled_at = CASE WHEN EXCLUDED.active THEN NULL ELSE promo_codes.disabled_at END,
                disabled_by = CASE WHEN EXCLUDED.active THEN NULL ELSE promo_codes.disabled_by END,
                updated_at = now()
            RETURNING *
            """,
            (
                definition.code,
                _kind_value(definition.kind),
                discount_type,
                definition.discount_percent,
                definition.discount_amount,
                duration_days,
                definition.monthly_duration_months,
                definition.max_redemptions,
                definition.per_user_limit,
                _parse_datetime(definition.expires_at),
                bool(definition.active),
                created_by,
                _optional_text(campaign_key),
                _jsonb(dict(metadata or {})),
            ),
        )
        return _promo_from_row(cur.fetchone())

    def _get_promo_code_cur(self, cur: Any, code: str, *, for_update: bool = False) -> StoredPromoCode | None:
        suffix = " FOR UPDATE" if for_update else ""
        cur.execute(f"SELECT * FROM promo_codes WHERE code = %s{suffix}", (code,))
        row = cur.fetchone()
        return _promo_from_row(row) if row is not None else None

    def _get_active_redemption_cur(
        self,
        cur: Any,
        code: str,
        chat_id: int,
        *,
        for_update: bool,
    ) -> PromoRedemption | None:
        suffix = " FOR UPDATE" if for_update else ""
        cur.execute(
            f"""
            SELECT *
            FROM promo_code_redemptions
            WHERE code = %s
              AND chat_id = %s
              AND status = ANY(%s)
            ORDER BY redemption_id
            LIMIT 1
            {suffix}
            """,
            (code, int(chat_id), list(ACTIVE_REDEMPTION_STATUSES)),
        )
        row = cur.fetchone()
        return _redemption_from_row(row) if row is not None else None

    def _active_redemption_count_cur(self, cur: Any, code: str) -> int:
        cur.execute(
            """
            SELECT count(*) AS count
            FROM promo_code_redemptions
            WHERE code = %s
              AND status = ANY(%s)
            """,
            (code, list(ACTIVE_REDEMPTION_STATUSES)),
        )
        return int(cur.fetchone()["count"])

    def _insert_redemption_cur(
        self,
        cur: Any,
        *,
        code: str,
        chat_id: int,
        user_id: int | None,
        idempotency_key: str,
        status: Literal["reserved", "redeemed"],
        claimed_at: datetime,
        metadata: Mapping[str, Any] | None,
        entitlement_charge_id: str | None,
        payment_order_id: str | None,
    ) -> PromoRedemption | None:
        cur.execute(
            """
            INSERT INTO promo_code_redemptions (
                code,
                chat_id,
                user_id,
                status,
                idempotency_key,
                reserved_at,
                redeemed_at,
                payment_order_id,
                entitlement_charge_id,
                source,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'runtime', %s)
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            (
                code,
                chat_id,
                user_id,
                status,
                idempotency_key,
                claimed_at if status == "reserved" else None,
                claimed_at if status == "redeemed" else None,
                _optional_text(payment_order_id),
                _optional_text(entitlement_charge_id),
                _jsonb(dict(metadata or {})),
            ),
        )
        row = cur.fetchone()
        return _redemption_from_row(row) if row is not None else None

    def _get_redemption_by_idempotency_key_cur(
        self,
        cur: Any,
        idempotency_key: str,
    ) -> PromoRedemption | None:
        cur.execute(
            """
            SELECT *
            FROM promo_code_redemptions
            WHERE idempotency_key = %s
            """,
            (idempotency_key,),
        )
        row = cur.fetchone()
        return _redemption_from_row(row) if row is not None else None

    def _insert_json_import_redemption_cur(
        self,
        cur: Any,
        code: str,
        record: PromoCodeRecord,
    ) -> PromoRedemption | None:
        chat_id = int(record.used_by_chat_id)
        redeemed_at = _parse_datetime(record.used_at) or _normalize_now(None)
        cur.execute(
            """
            INSERT INTO promo_code_redemptions (
                code,
                chat_id,
                status,
                idempotency_key,
                redeemed_at,
                entitlement_charge_id,
                source,
                metadata_json
            )
            VALUES (%s, %s, 'redeemed', %s, %s, %s, 'json_import', %s)
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            (
                code,
                chat_id,
                f"json_import:{code}:{chat_id}",
                redeemed_at,
                promo_code_grant_charge_id(code),
                _jsonb({"used_at": record.used_at}),
            ),
        )
        row = cur.fetchone()
        return _redemption_from_row(row) if row is not None else None

    def _begin_import_run_cur(
        self,
        cur: Any,
        *,
        migration_id: str,
        source_fingerprint: str,
        source_metadata: Mapping[str, Any],
    ) -> dict[str, int] | None:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (PROMO_IMPORT_LOCK_ID,))
        cur.execute(
            """
            SELECT migration_id, source_fingerprint, result_json, status
            FROM promo_import_runs
            WHERE migration_id = %s
            FOR UPDATE
            """,
            (migration_id,),
        )
        existing = cur.fetchone()
        if existing is not None:
            if str(existing["source_fingerprint"]) != source_fingerprint:
                raise RuntimeError(
                    f"Promo import migration_id {migration_id!r} has a different source fingerprint.",
                )
            if str(existing["status"]) != "applied":
                raise RuntimeError(
                    f"Promo import migration_id {migration_id!r} is recorded with status "
                    f"{existing['status']!r}.",
                )
            return {str(key): int(value) for key, value in dict(existing["result_json"]).items()}
        cur.execute(
            """
            INSERT INTO promo_import_runs (
                migration_id,
                source_fingerprint,
                source_metadata_json,
                result_json,
                status
            )
            VALUES (%s, %s, %s, '{}'::jsonb, 'started')
            """,
            (migration_id, source_fingerprint, _jsonb(dict(source_metadata))),
        )
        return None

    def _connect(self):
        return self._connection_provider.connect()

    def close(self) -> None:
        self._connection_provider.close()


def _promo_from_row(row: Mapping[str, Any]) -> StoredPromoCode:
    return StoredPromoCode(
        code=str(row["code"]),
        kind=_kind_from_text(str(row["kind"])),
        active=bool(row["active"]),
        max_redemptions=int(row["max_uses"]),
        per_user_limit=int(row["per_user_limit"]),
        expires_at=_datetime_text(row["expires_at"]),
        discount_percent=_optional_int(row["discount_percent"]),
        discount_amount=_optional_int(row["discount_amount_minor"]),
        monthly_duration_months=int(row["monthly_duration_months"]),
        duration_days=_optional_int(row["duration_days"]),
        created_by=_optional_int(row["created_by"]),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
        disabled_at=_datetime_or_none(row["disabled_at"]),
        disabled_by=_optional_int(row["disabled_by"]),
        campaign_key=_optional_text(row["campaign_key"]),
        metadata=dict(row["metadata_json"] or {}),
    )


def _redemption_from_row(row: Mapping[str, Any]) -> PromoRedemption:
    return PromoRedemption(
        redemption_id=int(row["redemption_id"]),
        code=str(row["code"]),
        chat_id=int(row["chat_id"]),
        user_id=_optional_int(row["user_id"]),
        status=str(row["status"]),
        idempotency_key=str(row["idempotency_key"]),
        offered_at=_datetime_or_none(row["offered_at"]),
        reserved_at=_datetime_or_none(row["reserved_at"]),
        redeemed_at=_datetime_or_none(row["redeemed_at"]),
        released_at=_datetime_or_none(row["released_at"]),
        failed_at=_datetime_or_none(row["failed_at"]),
        window_expires_at=_datetime_or_none(row["window_expires_at"]),
        payment_order_id=_optional_text(row["payment_order_id"]),
        payment_provider=_optional_text(row["payment_provider"]),
        payment_product=_optional_text(row["payment_product"]),
        currency=_optional_text(row["currency"]),
        original_amount_minor=_optional_int(row["original_amount_minor"]),
        discount_amount_minor=_optional_int(row["discount_amount_minor"]),
        final_amount_minor=_optional_int(row["final_amount_minor"]),
        entitlement_charge_id=_optional_text(row["entitlement_charge_id"]),
        campaign_key=_optional_text(row["campaign_key"]),
        campaign_step_key=_optional_text(row["campaign_step_key"]),
        telegram_message_id=_optional_int(row["telegram_message_id"]),
        failure_reason=_optional_text(row["failure_reason"]),
        source=str(row["source"]),
        metadata=dict(row["metadata_json"] or {}),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
    )


def _definition_from_json_record(code: str, record: PromoCodeRecord) -> PromoCodeDefinition:
    return PromoCodeDefinition(
        code=code,
        kind=record.kind,
        active=record.active,
        max_redemptions=record.max_redemptions,
        per_user_limit=record.per_user_limit,
        expires_at=record.expires_at,
        discount_percent=record.discount_percent,
        discount_amount=record.discount_amount,
        monthly_duration_months=record.monthly_duration_months,
    )


def _normalize_json_records(promo_codes: Mapping[str, PromoCodeRecord]) -> dict[str, PromoCodeRecord]:
    normalized: dict[str, PromoCodeRecord] = {}
    for raw_code, record in promo_codes.items():
        code = normalize_promo_code(str(raw_code))
        if not code:
            continue
        if not isinstance(record, PromoCodeRecord):
            raise TypeError(f"Invalid promo record for code {raw_code!r}")
        normalized[code] = PromoCodeRecord.from_dict(record.to_dict())
    return dict(sorted(normalized.items()))


def _json_import_result(promo_codes: Mapping[str, PromoCodeRecord]) -> dict[str, int]:
    active = 0
    disabled = 0
    discounts = 0
    monthly_access = 0
    redemptions = 0
    for record in promo_codes.values():
        if record.active:
            active += 1
        else:
            disabled += 1
        if _kind_value(record.kind) == PromoCodeKind.DISCOUNT.value:
            discounts += 1
        else:
            monthly_access += 1
        if record.used_by_chat_id is not None:
            redemptions += 1
    return {
        "promo_codes": len(promo_codes),
        "redemptions": redemptions,
        "active": active,
        "disabled": disabled,
        "discount": discounts,
        "monthly_access": monthly_access,
    }


def _discount_type(definition: PromoCodeDefinition) -> str | None:
    if definition.kind != PromoCodeKind.DISCOUNT:
        return None
    if definition.discount_percent is not None:
        return "percent"
    if definition.discount_amount is not None:
        return "amount"
    return None


def _kind_from_text(value: str) -> PromoCodeKind | str:
    try:
        return PromoCodeKind(value)
    except ValueError:
        return value


def _kind_value(value: PromoCodeKind | str) -> str:
    if isinstance(value, PromoCodeKind):
        return value.value
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_now(value)
    text = str(value).strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    return _normalize_now(parsed)


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_now(value)
    return _parse_datetime(value)


def _datetime_text(value: Any) -> str | None:
    parsed = _datetime_or_none(value)
    return parsed.isoformat() if parsed is not None else None


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)
