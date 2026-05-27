from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from .entitlement_storage import EntitlementStorageError
from .postgres_connection import DirectPostgresConnectionProvider, PostgresConnectionProvider
from .postgres_entitlement_migrations import MIGRATIONS, run_entitlement_schema_migrations
from .postgres_schema_validation import (
    SCHEMA_MIGRATIONS_COLUMNS,
    PostgresSchemaExpectation,
    validate_postgres_schema,
)
from .subscriptions import Entitlement


ENTITLEMENT_MAP_LOCK_ID = 4_382_026_052_200_001
ENTITLEMENT_IMPORT_LOCK_ID = 4_382_026_052_200_002

ENTITLEMENT_SCHEMA_EXPECTATION = PostgresSchemaExpectation(
    component="entitlement",
    migration_versions=tuple(migration.version for migration in MIGRATIONS),
    table_columns={
        "schema_migrations": SCHEMA_MIGRATIONS_COLUMNS,
        "entitlements": (
            "chat_id",
            "free_trial_used",
            "subscription_period_start",
            "subscription_period_end",
            "test_access_until",
            "test_access_enabled",
            "monthly_one_day_remaining",
            "monthly_weekly_pdf_remaining",
            "extra_one_day_remaining",
            "extra_weekly_pdf_remaining",
            "created_at",
            "updated_at",
            "version",
        ),
        "entitlement_processed_charge_ids": (
            "chat_id",
            "charge_id",
            "position",
            "recorded_at",
        ),
        "entitlement_json_import_runs": (
            "migration_id",
            "source_fingerprint",
            "source_metadata_json",
            "result_json",
            "status",
            "started_at",
            "finished_at",
        ),
    },
    indexes=("idx_entitlement_processed_charge_ids_chat_position",),
    remediation="Run entitlement migrations before startup.",
)


class PostgresEntitlementStore:
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
                    run_entitlement_schema_migrations(cur)

    def validate_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                validate_postgres_schema(
                    cur,
                    ENTITLEMENT_SCHEMA_EXPECTATION,
                    error_cls=EntitlementStorageError,
                )

    def load_all(self) -> dict[int, Entitlement]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._load_all_cur(cur)

    def load_chat_entitlement(self, chat_id: int) -> Entitlement | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._load_chat_entitlement_cur(cur, int(chat_id))

    def save_chat_entitlement(self, chat_id: int, entitlement: Entitlement) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._upsert_entitlement_cur(cur, int(chat_id), entitlement)

    def save_all(self, entitlements: Mapping[int, Entitlement]) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._lock_entitlement_map_cur(cur)
                    self._replace_entitlements_cur(cur, entitlements)

    @contextmanager
    def transact_chat_entitlement(self, chat_id: int) -> Iterator[Entitlement]:
        chat_id = int(chat_id)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO entitlements (chat_id) VALUES (%s) ON CONFLICT (chat_id) DO NOTHING",
                        (chat_id,),
                    )
                    entitlement = self._load_chat_entitlement_cur(cur, chat_id, for_update=True)
                    if entitlement is None:
                        entitlement = Entitlement()
                    yield entitlement
                    self._upsert_entitlement_cur(cur, chat_id, entitlement)

    @contextmanager
    def transact(self) -> Iterator[dict[int, Entitlement]]:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._lock_entitlement_map_cur(cur)
                    entitlements = self._load_all_cur(cur)
                    yield entitlements
                    self._replace_entitlements_cur(cur, entitlements)

    def apply_json_import(
        self,
        *,
        migration_id: str,
        source_fingerprint: str,
        source_metadata: Mapping[str, Any],
        entitlements: Mapping[int, Entitlement],
        result_payload: Mapping[str, Any],
        allow_non_empty_target: bool = False,
    ) -> dict[str, Any]:
        normalized = _normalize_entitlements(entitlements)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._lock_import_cur(cur)
                    cur.execute(
                        """
                        SELECT migration_id, source_fingerprint, result_json, status
                        FROM entitlement_json_import_runs
                        WHERE migration_id = %s
                        FOR UPDATE
                        """,
                        (migration_id,),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        if str(existing["source_fingerprint"]) != source_fingerprint:
                            raise EntitlementStorageError(
                                f"JSON import migration_id {migration_id!r} has a different source fingerprint.",
                            )
                        if str(existing["status"]) != "applied":
                            raise EntitlementStorageError(
                                f"JSON import migration_id {migration_id!r} is recorded with status "
                                f"{existing['status']!r}.",
                            )
                        return dict(existing["result_json"])
                    if not allow_non_empty_target:
                        self._require_empty_json_import_target_cur(cur)

                    cur.execute(
                        """
                        INSERT INTO entitlement_json_import_runs (
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
                    self._lock_entitlement_map_cur(cur)
                    self._replace_entitlements_cur(cur, normalized)
                    loaded = self._load_all_cur(cur)
                    if loaded != normalized:
                        raise EntitlementStorageError(
                            "Postgres entitlement parity check failed after JSON import.",
                        )
                    payload = dict(result_payload)
                    cur.execute(
                        """
                        UPDATE entitlement_json_import_runs
                        SET status = 'applied',
                            result_json = %s,
                            finished_at = now()
                        WHERE migration_id = %s
                        """,
                        (_jsonb(payload), migration_id),
                    )
                    return payload

    def _load_all_cur(self, cur: Any) -> dict[int, Entitlement]:
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
            ORDER BY chat_id
            """
        )
        entitlements: dict[int, Entitlement] = {}
        for row in cur.fetchall():
            chat_id = int(row["chat_id"])
            entitlements[chat_id] = _entitlement_from_row(row)

        if not entitlements:
            return {}

        cur.execute(
            """
            SELECT chat_id, charge_id
            FROM entitlement_processed_charge_ids
            WHERE chat_id = ANY(%s)
            ORDER BY chat_id, position, recorded_at, charge_id
            """,
            (list(entitlements),),
        )
        for row in cur.fetchall():
            entitlements[int(row["chat_id"])].processed_payment_charge_ids.append(str(row["charge_id"]))
        return entitlements

    def _load_chat_entitlement_cur(
        self,
        cur: Any,
        chat_id: int,
        *,
        for_update: bool = False,
    ) -> Entitlement | None:
        suffix = " FOR UPDATE" if for_update else ""
        cur.execute(
            f"""
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
            WHERE chat_id = %s{suffix}
            """,
            (int(chat_id),),
        )
        row = cur.fetchone()
        if row is None:
            return None

        entitlement = _entitlement_from_row(row)
        cur.execute(
            """
            SELECT charge_id
            FROM entitlement_processed_charge_ids
            WHERE chat_id = %s
            ORDER BY position, recorded_at, charge_id
            """,
            (int(chat_id),),
        )
        entitlement.processed_payment_charge_ids = [str(charge["charge_id"]) for charge in cur.fetchall()]
        return entitlement

    def _replace_entitlements_cur(self, cur: Any, entitlements: Mapping[int, Entitlement]) -> None:
        normalized = _normalize_entitlements(entitlements)
        chat_ids = sorted(normalized)
        if chat_ids:
            cur.execute("DELETE FROM entitlements WHERE NOT (chat_id = ANY(%s))", (chat_ids,))
        else:
            cur.execute("DELETE FROM entitlements")

        for chat_id in chat_ids:
            self._upsert_entitlement_cur(cur, chat_id, normalized[chat_id])

    def _upsert_entitlement_cur(self, cur: Any, chat_id: int, entitlement: Entitlement) -> None:
        normalized = _normalize_entitlements({int(chat_id): entitlement})
        chat_id = next(iter(normalized))
        entitlement = normalized[chat_id]
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
        cur.execute(
            "DELETE FROM entitlement_processed_charge_ids WHERE chat_id = %s",
            (chat_id,),
        )
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

    def _lock_entitlement_map_cur(self, cur: Any) -> None:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (ENTITLEMENT_MAP_LOCK_ID,))

    def _lock_import_cur(self, cur: Any) -> None:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (ENTITLEMENT_IMPORT_LOCK_ID,))

    def _require_empty_json_import_target_cur(self, cur: Any) -> None:
        counts = self._json_import_target_counts_cur(cur)
        if not any(counts.values()):
            return
        formatted_counts = ", ".join(f"{name}={count}" for name, count in counts.items())
        raise EntitlementStorageError(
            "Refusing JSON entitlement import into non-empty Postgres target "
            f"({formatted_counts}). Pass --allow-non-empty-target only after verifying "
            "the overwrite is intentional.",
        )

    def _json_import_target_counts_cur(self, cur: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table_name in (
            "entitlements",
            "entitlement_processed_charge_ids",
            "entitlement_json_import_runs",
        ):
            cur.execute(f"SELECT count(*) AS count FROM {table_name}")
            counts[table_name] = int(cur.fetchone()["count"])
        return counts

    def _connect(self):
        return self._connection_provider.connect()

    def close(self) -> None:
        self._connection_provider.close()


def _entitlement_from_row(row: Mapping[str, Any]) -> Entitlement:
    return Entitlement(
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


def _normalize_entitlements(entitlements: Mapping[int, Entitlement]) -> dict[int, Entitlement]:
    normalized: dict[int, Entitlement] = {}
    for raw_chat_id, entitlement in entitlements.items():
        try:
            chat_id = int(raw_chat_id)
        except (TypeError, ValueError) as exc:
            raise EntitlementStorageError(f"Invalid entitlement chat id: {raw_chat_id!r}") from exc
        if not isinstance(entitlement, Entitlement):
            raise EntitlementStorageError(f"Invalid entitlement value for chat_id {chat_id}")
        normalized[chat_id] = Entitlement.from_dict(entitlement.to_dict())
    return normalized


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


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)
