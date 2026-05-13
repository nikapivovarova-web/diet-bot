from __future__ import annotations

from collections import Counter
import re
from typing import Any


REQUIRED_TABLES = {
    "schema_migrations",
    "users",
    "chat_state",
    "profiles",
    "entitlements",
    "entitlement_events",
    "payment_orders",
    "payment_events",
    "processed_provider_charges",
    "generation_records",
    "promo_codes",
    "promo_redemptions",
    "promo_events",
    "support_state",
}

REQUIRED_INDEXES = {
    "idx_entitlement_events_user_created_at",
    "uniq_consume_per_generation",
    "uniq_refund_per_generation",
    "uniq_refund_per_related_event",
    "uniq_active_generation_per_user",
    "idx_generation_records_active_heartbeat",
    "idx_payment_orders_user_status",
    "idx_payment_events_order_created_at",
    "idx_payment_events_charge",
    "idx_payment_orders_promo_code",
    "idx_processed_provider_charges_order",
    "idx_promo_codes_active_expires",
    "idx_promo_redemptions_code_user",
    "idx_promo_redemptions_order",
    "idx_promo_redemptions_user",
    "idx_promo_events_code_created",
    "idx_support_state_status_updated",
}


class FakeCursor:
    def __init__(self) -> None:
        self.applied_versions: set[str] = set()
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self._fetchall_result: list[dict[str, str]] = []

    def execute(self, statement: str, params: tuple[Any, ...] | None = None) -> None:
        normalized = _normalize_sql(statement)
        self.executed.append((normalized, params))
        if normalized == "SELECT version FROM schema_migrations":
            self._fetchall_result = [
                {"version": version}
                for version in sorted(self.applied_versions)
            ]
        elif normalized.startswith("INSERT INTO schema_migrations"):
            assert params is not None
            self.applied_versions.add(str(params[0]))

    def fetchall(self) -> list[dict[str, str]]:
        return self._fetchall_result


def test_migrations_create_schema_migrations_first() -> None:
    from diet_bot import postgres_migrations

    cur = FakeCursor()

    postgres_migrations.run_postgres_migrations(cur)

    assert cur.executed
    first_statement = cur.executed[0][0]
    assert first_statement.startswith("CREATE TABLE IF NOT EXISTS schema_migrations")


def test_migrations_include_required_paid_storage_tables() -> None:
    from diet_bot import postgres_migrations

    sql = "\n".join(_all_statement_texts(postgres_migrations))

    for table in REQUIRED_TABLES:
        assert re.search(
            rf"\bCREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table}\b",
            sql,
            flags=re.IGNORECASE,
        ), table

    for index in REQUIRED_INDEXES:
        assert re.search(
            rf"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+{index}\b",
            sql,
            flags=re.IGNORECASE,
        ), index

    assert re.search(
        r"\bpre_checkout_approved_at\s+TIMESTAMPTZ\b",
        sql,
        flags=re.IGNORECASE,
    )
    for column_pattern in (
        r"\bexpires_at\s+TIMESTAMPTZ\b",
        r"\blist_amount\s+INTEGER\b",
        r"\bpromo_code_id\s+BIGINT\b",
        r"\border_id\s+TEXT\b",
        r"\bmax_redemptions\s+INTEGER\b",
        r"\bper_user_limit\s+INTEGER\b",
        r"\bdiscount_percent\s+INTEGER\b",
        r"\bdiscount_amount\s+INTEGER\b",
        r"\bmonthly_duration_months\s+INTEGER\b",
        r"\bmetadata_json\s+JSONB\s+NOT\s+NULL\s+DEFAULT\s+'\{\}'::jsonb\b",
    ):
        assert re.search(column_pattern, sql, flags=re.IGNORECASE), column_pattern


def test_migrations_use_idempotent_sql_shapes() -> None:
    from diet_bot import postgres_migrations

    for statement in _all_statement_texts(postgres_migrations):
        normalized = _normalize_sql(statement)
        upper = normalized.upper()
        assert not re.search(r"\bDROP\s+(TABLE|INDEX|SCHEMA|DATABASE)\b", upper)
        assert not re.search(r"\bCREATE\s+TABLE\b(?!\s+IF\s+NOT\s+EXISTS)", upper)
        assert not re.search(r"\bCREATE\s+INDEX\b(?!\s+IF\s+NOT\s+EXISTS)", upper)
        assert not re.search(r"\bCREATE\s+UNIQUE\s+INDEX\b(?!\s+IF\s+NOT\s+EXISTS)", upper)
        assert upper.startswith(
            (
                "CREATE TABLE IF NOT EXISTS",
                "CREATE INDEX IF NOT EXISTS",
                "CREATE UNIQUE INDEX IF NOT EXISTS",
                "ALTER TABLE",
                "DO $$",
            )
        ), normalized


def test_run_postgres_migrations_records_each_version_once() -> None:
    from diet_bot import postgres_migrations

    cur = FakeCursor()
    migrations = list(postgres_migrations.POSTGRES_MIGRATIONS)
    migration_versions = [migration.version for migration in migrations]

    postgres_migrations.run_postgres_migrations(cur)

    inserted_versions = [
        str(params[0])
        for statement, params in cur.executed
        if statement.startswith("INSERT INTO schema_migrations")
        and params is not None
    ]
    assert inserted_versions == migration_versions
    assert cur.applied_versions == set(migration_versions)

    first_run_counts = Counter(statement for statement, _params in cur.executed)
    postgres_migrations.run_postgres_migrations(cur)
    second_run_counts = Counter(statement for statement, _params in cur.executed)

    for statement in _migration_statement_texts(postgres_migrations):
        normalized = _normalize_sql(statement)
        assert second_run_counts[normalized] == first_run_counts[normalized]

    all_inserted_versions = [
        str(params[0])
        for statement, params in cur.executed
        if statement.startswith("INSERT INTO schema_migrations")
        and params is not None
    ]
    assert all_inserted_versions == migration_versions


def _all_statement_texts(postgres_migrations: Any) -> list[str]:
    return [
        postgres_migrations.SCHEMA_MIGRATIONS_SQL,
        *_migration_statement_texts(postgres_migrations),
    ]


def _migration_statement_texts(postgres_migrations: Any) -> list[str]:
    statements: list[str] = []
    for migration in postgres_migrations.POSTGRES_MIGRATIONS:
        statements.extend(migration.statements)
    return statements


def _normalize_sql(statement: str) -> str:
    return re.sub(r"\s+", " ", statement).strip().rstrip(";")
