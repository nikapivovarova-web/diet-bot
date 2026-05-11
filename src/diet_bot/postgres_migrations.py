from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PostgresMigration:
    version: str
    description: str
    statements: tuple[str, ...]


SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


LEGACY_SCHEMA_HARDENING_STATEMENTS = (
    """
    ALTER TABLE entitlement_events
        ADD COLUMN IF NOT EXISTS meal_plan_id BIGINT,
        ADD COLUMN IF NOT EXISTS source TEXT,
        ADD COLUMN IF NOT EXISTS amount INTEGER NOT NULL DEFAULT 1,
        ADD COLUMN IF NOT EXISTS related_event_id BIGINT REFERENCES entitlement_events(id) ON DELETE SET NULL
    """,
    """
    ALTER TABLE meal_plans
        ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS delivery_started_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT,
        ADD COLUMN IF NOT EXISTS delivery_attempts INTEGER NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE payment_orders
        ADD COLUMN IF NOT EXISTS delivery_chat_id BIGINT,
        ADD COLUMN IF NOT EXISTS invoice_link TEXT
    """,
    """
    ALTER TABLE payment_events
        ADD COLUMN IF NOT EXISTS event_id TEXT,
        ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
        ADD COLUMN IF NOT EXISTS event_type TEXT,
        ADD COLUMN IF NOT EXISTS provider TEXT,
        ADD COLUMN IF NOT EXISTS charge_id TEXT,
        ADD COLUMN IF NOT EXISTS telegram_charge_id TEXT,
        ADD COLUMN IF NOT EXISTS provider_charge_id TEXT,
        ADD COLUMN IF NOT EXISTS product TEXT,
        ADD COLUMN IF NOT EXISTS amount INTEGER,
        ADD COLUMN IF NOT EXISTS currency TEXT,
        ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'processed',
        ADD COLUMN IF NOT EXISTS reason TEXT,
        ADD COLUMN IF NOT EXISTS raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    """
    ALTER TABLE processed_payment_charges
        ADD COLUMN IF NOT EXISTS telegram_charge_id TEXT,
        ADD COLUMN IF NOT EXISTS provider_charge_id TEXT
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_entitlement_events_user_created_at
        ON entitlement_events(user_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_entitlement_events_meal_plan
        ON entitlement_events(meal_plan_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_consume_per_meal_plan
        ON entitlement_events(meal_plan_id, event_type)
        WHERE event_type = 'consume' AND meal_plan_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_refund_per_meal_plan
        ON entitlement_events(meal_plan_id, event_type)
        WHERE event_type = 'refund' AND meal_plan_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_refund_per_related_event
        ON entitlement_events(related_event_id)
        WHERE event_type = 'refund' AND related_event_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_meal_plans_user_created_at
        ON meal_plans(user_id, created_at DESC)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_meal_plan_per_user
        ON meal_plans(user_id)
        WHERE status IN ('generating', 'delivering')
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_meal_plans_active_heartbeat
        ON meal_plans(user_id, heartbeat_at)
        WHERE status IN ('generating', 'delivering')
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_payment_orders_user_status
        ON payment_orders(user_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_payment_events_user_created_at
        ON payment_events(user_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_payment_events_charge
        ON payment_events(provider, charge_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_payment_events_event_id
        ON payment_events(event_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_payment_events_provider_charge_type
        ON payment_events(provider, charge_id, event_type)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_analytics_events_name_created_at
        ON analytics_events(event_name, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_analytics_events_user_created_at
        ON analytics_events(user_id, created_at DESC)
    """,
)


IMPORT_RUNS_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS import_runs (
        id BIGSERIAL PRIMARY KEY,
        migration_id TEXT NOT NULL UNIQUE,
        source_fingerprint TEXT NOT NULL,
        source_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        status TEXT NOT NULL DEFAULT 'started',
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ,
        CHECK (status IN ('started', 'applied', 'failed'))
    )
    """,
)


def _add_check_constraint(table: str, name: str, expression: str) -> str:
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = '{table}'::regclass
              AND conname = '{name}'
        ) THEN
            ALTER TABLE {table}
                ADD CONSTRAINT {name}
                CHECK ({expression})
                NOT VALID;
        END IF;
    END;
    $$
    """


CHECK_CONSTRAINT_STATEMENTS = (
    _add_check_constraint(
        "entitlements",
        "chk_entitlements_plan_allowed",
        "plan IN ('free', 'monthly', 'test_access')",
    ),
    _add_check_constraint(
        "entitlements",
        "chk_entitlements_status_allowed",
        "status IN ('active', 'inactive')",
    ),
    _add_check_constraint(
        "entitlements",
        "chk_entitlements_counters_non_negative",
        """
        monthly_one_day_remaining >= 0
        AND monthly_weekly_pdf_remaining >= 0
        AND extra_one_day_remaining >= 0
        AND extra_weekly_pdf_remaining >= 0
        """,
    ),
    _add_check_constraint(
        "entitlement_events",
        "chk_entitlement_events_amount_non_negative",
        "amount >= 0",
    ),
    _add_check_constraint(
        "entitlement_events",
        "chk_entitlement_events_delta_reasonable",
        "delta_generations IS NULL OR delta_generations BETWEEN -1000 AND 1000",
    ),
    _add_check_constraint(
        "entitlement_events",
        "chk_entitlement_events_source_allowed",
        """
        source IS NULL OR source IN (
            'free_trial_one_day',
            'monthly_one_day',
            'monthly_weekly_pdf',
            'extra_one_day',
            'extra_weekly_pdf',
            'test_access'
        )
        """,
    ),
    _add_check_constraint(
        "processed_payment_charges",
        "chk_processed_payment_charges_provider_allowed",
        "provider IN ('telegram_stars', 'yookassa', 'telegram', 'legacy')",
    ),
    _add_check_constraint(
        "processed_payment_charges",
        "chk_processed_payment_charges_amount_non_negative",
        "amount IS NULL OR amount >= 0",
    ),
    _add_check_constraint(
        "processed_payment_charges",
        "chk_processed_payment_charges_status_allowed",
        """
        status IN (
            'processed',
            'pending_reconciliation',
            'ignored_non_terminal',
            'orphan_recoverable',
            'duplicate',
            'ignored',
            'orphan'
        )
        """,
    ),
    _add_check_constraint(
        "payment_events",
        "chk_payment_events_event_type_allowed",
        "event_type IN ('successful_payment', 'refund', 'chargeback', 'cancel_subscription', 'unknown')",
    ),
    _add_check_constraint(
        "payment_events",
        "chk_payment_events_provider_allowed",
        "provider IN ('telegram_stars', 'yookassa', 'telegram', 'legacy')",
    ),
    _add_check_constraint(
        "payment_events",
        "chk_payment_events_product_allowed",
        "product IS NULL OR product IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf')",
    ),
    _add_check_constraint(
        "payment_events",
        "chk_payment_events_amount_non_negative",
        "amount IS NULL OR amount >= 0",
    ),
    _add_check_constraint(
        "payment_events",
        "chk_payment_events_status_allowed",
        """
        status IN (
            'processed',
            'pending_reconciliation',
            'ignored_non_terminal',
            'orphan_recoverable',
            'duplicate',
            'ignored',
            'orphan'
        )
        """,
    ),
    _add_check_constraint(
        "payment_orders",
        "chk_payment_orders_product_allowed",
        "product IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf')",
    ),
    _add_check_constraint(
        "payment_orders",
        "chk_payment_orders_provider_allowed",
        "provider IN ('telegram_stars', 'yookassa')",
    ),
    _add_check_constraint(
        "payment_orders",
        "chk_payment_orders_amount_non_negative",
        "amount >= 0",
    ),
    _add_check_constraint(
        "payment_orders",
        "chk_payment_orders_status_allowed",
        "status IN ('pending', 'paid', 'expired', 'failed_invoice_creation')",
    ),
    _add_check_constraint(
        "promo_codes",
        "chk_promo_codes_kind_allowed",
        "kind IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf', 'test_access_days')",
    ),
    _add_check_constraint(
        "promo_codes",
        "chk_promo_codes_counters_non_negative",
        """
        value >= 1
        AND used_count >= 0
        AND (max_uses IS NULL OR max_uses >= 0)
        AND (max_uses IS NULL OR used_count <= max_uses)
        """,
    ),
    _add_check_constraint(
        "meal_plans",
        "chk_meal_plans_plan_type_allowed",
        "plan_type IN ('one_day', 'weekly_pdf')",
    ),
    _add_check_constraint(
        "meal_plans",
        "chk_meal_plans_status_allowed",
        "status IN ('generating', 'delivering', 'completed', 'failed', 'failed_timeout')",
    ),
    _add_check_constraint(
        "meal_plans",
        "chk_meal_plans_delivery_attempts_non_negative",
        "delivery_attempts >= 0",
    ),
)


MEAL_PLAN_LIFECYCLE_STATEMENTS = (
    """
    ALTER TABLE meal_plans
        ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS delivery_started_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT,
        ADD COLUMN IF NOT EXISTS delivery_attempts INTEGER NOT NULL DEFAULT 0
    """,
    """
    DROP INDEX IF EXISTS uniq_active_meal_plan_per_user
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_meal_plan_per_user
        ON meal_plans(user_id)
        WHERE status IN ('generating', 'delivering')
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_meal_plans_active_heartbeat
        ON meal_plans(user_id, heartbeat_at)
        WHERE status IN ('generating', 'delivering')
    """,
    """
    ALTER TABLE meal_plans
        DROP CONSTRAINT IF EXISTS chk_meal_plans_status_allowed
    """,
    _add_check_constraint(
        "meal_plans",
        "chk_meal_plans_status_allowed",
        "status IN ('generating', 'delivering', 'completed', 'failed', 'failed_timeout')",
    ),
    _add_check_constraint(
        "meal_plans",
        "chk_meal_plans_delivery_attempts_non_negative",
        "delivery_attempts >= 0",
    ),
)


MIGRATIONS = (
    PostgresMigration(
        version="202605110001",
        description="Backfill current schema columns and indexes",
        statements=LEGACY_SCHEMA_HARDENING_STATEMENTS,
    ),
    PostgresMigration(
        version="202605110002",
        description="Add JSON import run audit table",
        statements=IMPORT_RUNS_STATEMENTS,
    ),
    PostgresMigration(
        version="202605110003",
        description="Add storage integrity check constraints",
        statements=CHECK_CONSTRAINT_STATEMENTS,
    ),
    PostgresMigration(
        version="202605110004",
        description="Store reusable Telegram invoice links on payment orders",
        statements=(
            """
            ALTER TABLE payment_orders
                ADD COLUMN IF NOT EXISTS invoice_link TEXT
            """,
        ),
    ),
    PostgresMigration(
        version="202605110005",
        description="Add meal plan delivery lifecycle state",
        statements=MEAL_PLAN_LIFECYCLE_STATEMENTS,
    ),
)


def run_postgres_migrations(cur: Any) -> None:
    cur.execute(SCHEMA_MIGRATIONS_SQL)
    cur.execute("SELECT version FROM schema_migrations")
    applied_versions = {str(row["version"]) for row in cur.fetchall()}
    for migration in MIGRATIONS:
        if migration.version in applied_versions:
            continue
        for statement in migration.statements:
            statement = statement.strip()
            if statement:
                cur.execute(statement)
        cur.execute(
            """
            INSERT INTO schema_migrations (version, description)
            VALUES (%s, %s)
            ON CONFLICT (version) DO NOTHING
            """,
            (migration.version, migration.description),
        )
