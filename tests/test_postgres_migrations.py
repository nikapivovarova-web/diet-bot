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
    "user_recipe_history",
    "promo_codes",
    "promo_redemptions",
    "promo_events",
    "support_state",
    "user_attribution",
    "analytics_events",
}

REQUIRED_INDEXES = {
    "idx_entitlement_events_user_created_at",
    "uniq_consume_per_generation",
    "uniq_refund_per_generation",
    "uniq_refund_per_related_event",
    "uniq_active_generation_per_user",
    "idx_generation_records_active_heartbeat",
    "idx_user_recipe_history_recent",
    "idx_user_recipe_history_recipe_id",
    "idx_user_recipe_history_recipe_key",
    "idx_user_recipe_history_generation",
    "uniq_user_recipe_history_generation_slot",
    "idx_payment_orders_user_status",
    "idx_payment_events_order_created_at",
    "idx_payment_events_charge",
    "uniq_entitlements_stars_subscription_charge_id",
    "idx_payment_orders_promo_code",
    "idx_processed_provider_charges_order",
    "idx_promo_codes_active_expires",
    "idx_promo_redemptions_code_user",
    "idx_promo_redemptions_order",
    "idx_promo_redemptions_user",
    "idx_promo_events_code_created",
    "idx_support_state_status_updated",
    "idx_user_attribution_source_campaign",
    "idx_analytics_events_user_occurred_at",
    "idx_analytics_events_name_occurred_at",
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
        r"\bsubscription_source\s+TEXT\s+NOT\s+NULL\s+DEFAULT\s+'none'",
        r"\bauto_renew_status\s+TEXT\s+NOT\s+NULL\s+DEFAULT\s+'not_applicable'",
        r"\bstars_subscription_charge_id\s+TEXT\b",
        r"\blast_subscription_payment_charge_id\s+TEXT\b",
        r"\bcurrent_period_payment_order_id\s+TEXT\b",
        r"\bis_recurring\s+BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+false\b",
        r"\bis_first_recurring\s+BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+false\b",
        r"\bsubscription_expiration_at\s+TIMESTAMPTZ\b",
        r"\bgeneration_id\s+BIGINT\s+REFERENCES\s+generation_records\(id\)\s+ON\s+DELETE\s+SET\s+NULL\b",
        r"\bgenerated_at\s+TIMESTAMPTZ\s+NOT\s+NULL\s+DEFAULT\s+now\(\)",
        r"\bmeal_slot\s+TEXT\s+NOT\s+NULL\b",
        r"\brecipe_id\s+TEXT\s+NOT\s+NULL\b",
        r"\brecipe_key\s+TEXT\s+NOT\s+NULL\b",
        r"\bsource\s+TEXT\b",
        r"\bcampaign\s+TEXT\b",
        r"\breferral\s+TEXT\b",
        r"\bchat_id\s+BIGINT\b",
        r"\bevent_name\s+TEXT\s+NOT\s+NULL\b",
        r"\bproperties_json\s+JSONB\s+NOT\s+NULL\s+DEFAULT\s+'\{\}'::jsonb\b",
        r"\boccurred_at\s+TIMESTAMPTZ\s+NOT\s+NULL\s+DEFAULT\s+now\(\)",
    ):
        assert re.search(column_pattern, sql, flags=re.IGNORECASE), column_pattern
    assert "subscription_source IN ('none', 'telegram_stars', 'yookassa', 'promo', 'admin', 'legacy')" in sql
    assert "auto_renew_status IN ('not_applicable', 'enabled', 'canceled', 'unknown')" in sql
    assert re.search(
        r"CREATE\s+UNIQUE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+"
        r"uniq_entitlements_stars_subscription_charge_id\s+"
        r"ON\s+entitlements\(stars_subscription_charge_id\)\s+"
        r"WHERE\s+stars_subscription_charge_id\s+IS\s+NOT\s+NULL",
        sql,
        flags=re.IGNORECASE,
    )
    assert re.search(
        r"CHECK\s+\(\s*NOT\s+is_first_recurring\s+OR\s+is_recurring\s*\)",
        sql,
        flags=re.IGNORECASE,
    )


def test_migrations_use_idempotent_sql_shapes() -> None:
    from diet_bot import postgres_migrations

    for statement in _all_statement_texts(postgres_migrations):
        normalized = _normalize_sql(statement)
        upper = normalized.upper()
        assert not re.search(r"\bDROP\s+(TABLE|SCHEMA|DATABASE)\b", upper)
        assert not re.search(
            r"\bDROP\s+INDEX\b(?!\s+IF\s+EXISTS\s+UNIQ_PAYMENT_EVENTS_PROVIDER_CHARGE_TYPE\b)",
            upper,
        )
        assert not re.search(r"\bCREATE\s+TABLE\b(?!\s+IF\s+NOT\s+EXISTS)", upper)
        assert not re.search(r"\bCREATE\s+INDEX\b(?!\s+IF\s+NOT\s+EXISTS)", upper)
        assert not re.search(r"\bCREATE\s+UNIQUE\s+INDEX\b(?!\s+IF\s+NOT\s+EXISTS)", upper)
        assert upper.startswith(
            (
                "CREATE TABLE IF NOT EXISTS",
                "CREATE INDEX IF NOT EXISTS",
                "CREATE UNIQUE INDEX IF NOT EXISTS",
                "ALTER TABLE",
                "DROP INDEX IF EXISTS UNIQ_PAYMENT_EVENTS_PROVIDER_CHARGE_TYPE",
                "DO $$",
            )
        ), normalized


def test_migrations_replace_legacy_promo_kind_constraint() -> None:
    from diet_bot import postgres_migrations

    sql = "\n".join(_migration_statement_texts(postgres_migrations))

    assert "DROP CONSTRAINT IF EXISTS chk_promo_codes_kind_allowed" in sql
    assert "DROP CONSTRAINT IF EXISTS chk_entitlement_events_source_allowed" in sql
    assert "DROP INDEX IF EXISTS uniq_payment_events_provider_charge_type" in sql
    assert "DROP CONSTRAINT IF EXISTS promo_codes_kind_supported_check" in sql
    assert "ADD CONSTRAINT promo_codes_kind_supported_check" in sql
    assert "kind IN (\n                    'monthly_access',\n                    'discount'," in sql


def test_analytics_migration_repairs_existing_events_table_before_indexes() -> None:
    from diet_bot import postgres_migrations

    migration = next(
        migration
        for migration in postgres_migrations.POSTGRES_MIGRATIONS
        if migration.version == "202605170003"
    )
    statements = [_normalize_sql(statement) for statement in migration.statements]
    repair_statement = (
        "ALTER TABLE analytics_events "
        "ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()"
    )

    assert repair_statement in statements
    repair_index = statements.index(repair_statement)
    index_indexes = [
        index
        for index, statement in enumerate(statements)
        if statement.startswith("CREATE INDEX IF NOT EXISTS idx_analytics_events_")
    ]
    assert index_indexes
    assert repair_index < min(index_indexes)


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
