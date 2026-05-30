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


MIGRATIONS = (
    PostgresMigration(
        version="202605220001",
        description="Create entitlement repository tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS entitlements (
                chat_id BIGINT PRIMARY KEY,
                free_trial_used BOOLEAN NOT NULL DEFAULT FALSE,
                subscription_period_start TEXT,
                subscription_period_end TEXT,
                test_access_until TEXT,
                test_access_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                monthly_one_day_remaining INTEGER NOT NULL DEFAULT 0,
                monthly_weekly_pdf_remaining INTEGER NOT NULL DEFAULT 0,
                extra_one_day_remaining INTEGER NOT NULL DEFAULT 0,
                extra_weekly_pdf_remaining INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                version BIGINT NOT NULL DEFAULT 1,
                CONSTRAINT chk_entitlements_counters_non_negative CHECK (
                    monthly_one_day_remaining >= 0
                    AND monthly_weekly_pdf_remaining >= 0
                    AND extra_one_day_remaining >= 0
                    AND extra_weekly_pdf_remaining >= 0
                ),
                CONSTRAINT chk_entitlements_version_positive CHECK (version >= 1)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS entitlement_processed_charge_ids (
                chat_id BIGINT NOT NULL REFERENCES entitlements(chat_id) ON DELETE CASCADE,
                charge_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (chat_id, charge_id),
                CONSTRAINT chk_entitlement_processed_charge_id_non_empty CHECK (charge_id <> ''),
                CONSTRAINT chk_entitlement_processed_charge_id_position CHECK (position >= 0)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_entitlement_processed_charge_ids_chat_position
                ON entitlement_processed_charge_ids(chat_id, position)
            """,
        ),
    ),
    PostgresMigration(
        version="202605220002",
        description="Create entitlement JSON import audit table",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS entitlement_json_import_runs (
                migration_id TEXT PRIMARY KEY,
                source_fingerprint TEXT NOT NULL,
                source_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'started',
                started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ,
                CONSTRAINT chk_entitlement_json_import_runs_status CHECK (
                    status IN ('started', 'applied', 'failed')
                )
            )
            """,
        ),
    ),
    PostgresMigration(
        version="202605290001",
        description="Add managed subscription metadata to entitlements",
        statements=(
            """
            ALTER TABLE entitlements
                ADD COLUMN IF NOT EXISTS subscription_source TEXT NOT NULL DEFAULT 'none'
            """,
            """
            ALTER TABLE entitlements
                ADD COLUMN IF NOT EXISTS auto_renew_status TEXT NOT NULL DEFAULT 'not_applicable'
            """,
            """
            ALTER TABLE entitlements
                ADD COLUMN IF NOT EXISTS stars_subscription_charge_id TEXT
            """,
            """
            ALTER TABLE entitlements
                ADD COLUMN IF NOT EXISTS last_subscription_payment_charge_id TEXT
            """,
            """
            ALTER TABLE entitlements
                ADD COLUMN IF NOT EXISTS current_period_payment_order_id TEXT
            """,
        ),
    ),
)


def run_entitlement_schema_migrations(cur: Any) -> None:
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
