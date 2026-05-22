from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from .entitlement_storage import EntitlementStorageError
from .postgres_entitlement_migrations import run_entitlement_schema_migrations
from .subscriptions import Entitlement


ENTITLEMENT_MAP_LOCK_ID = 4_382_026_052_200_001
ENTITLEMENT_IMPORT_LOCK_ID = 4_382_026_052_200_002


class PostgresEntitlementStore:
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
                    run_entitlement_schema_migrations(cur)

    def validate_schema(self) -> None:
        expected_tables = {
            "schema_migrations",
            "entitlements",
            "entitlement_processed_charge_ids",
            "entitlement_json_import_runs",
        }
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
            raise EntitlementStorageError(
                "Postgres entitlement schema is missing tables: "
                f"{', '.join(missing_tables)}. Run entitlement migrations before startup.",
            )

    def load_all(self) -> dict[int, Entitlement]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._load_all_cur(cur)

    def save_all(self, entitlements: Mapping[int, Entitlement]) -> None:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._lock_entitlement_map_cur(cur)
                    self._replace_entitlements_cur(cur, entitlements)

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
            entitlements[chat_id] = Entitlement(
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

    def _replace_entitlements_cur(self, cur: Any, entitlements: Mapping[int, Entitlement]) -> None:
        normalized = _normalize_entitlements(entitlements)
        chat_ids = sorted(normalized)
        if chat_ids:
            cur.execute("DELETE FROM entitlements WHERE NOT (chat_id = ANY(%s))", (chat_ids,))
        else:
            cur.execute("DELETE FROM entitlements")

        for chat_id in chat_ids:
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
