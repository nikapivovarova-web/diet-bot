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
        version="202605220003",
        description="Create dormant payment ledger tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS payment_orders (
                order_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                product TEXT NOT NULL,
                provider TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                nonce TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                failure_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                paid_at TIMESTAMPTZ,
                granted_at TIMESTAMPTZ,
                failed_at TIMESTAMPTZ,
                CONSTRAINT chk_payment_orders_product CHECK (
                    product IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf')
                ),
                CONSTRAINT chk_payment_orders_provider CHECK (
                    provider IN ('telegram_stars', 'yookassa')
                ),
                CONSTRAINT chk_payment_orders_status CHECK (
                    status IN ('pending', 'paid', 'granted', 'failed')
                ),
                CONSTRAINT chk_payment_orders_amount_positive CHECK (amount > 0),
                CONSTRAINT chk_payment_orders_currency CHECK (currency IN ('XTR', 'RUB')),
                CONSTRAINT chk_payment_orders_nonce_non_empty CHECK (nonce <> ''),
                CONSTRAINT chk_payment_orders_provider_currency CHECK (
                    (provider = 'telegram_stars' AND currency = 'XTR')
                    OR (provider = 'yookassa' AND currency = 'RUB')
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS payment_charges (
                charge_id BIGSERIAL PRIMARY KEY,
                order_id TEXT REFERENCES payment_orders(order_id) ON DELETE RESTRICT,
                provider TEXT NOT NULL,
                telegram_payment_charge_id TEXT,
                provider_payment_charge_id TEXT,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'succeeded',
                raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT chk_payment_charges_provider CHECK (
                    provider IN ('telegram_stars', 'yookassa')
                ),
                CONSTRAINT chk_payment_charges_status CHECK (
                    status IN ('succeeded', 'refunded', 'canceled')
                ),
                CONSTRAINT chk_payment_charges_amount_positive CHECK (amount > 0),
                CONSTRAINT chk_payment_charges_currency CHECK (currency IN ('XTR', 'RUB')),
                CONSTRAINT chk_payment_charges_provider_currency CHECK (
                    (provider = 'telegram_stars' AND currency = 'XTR')
                    OR (provider = 'yookassa' AND currency = 'RUB')
                ),
                CONSTRAINT chk_payment_charges_external_id_present CHECK (
                    COALESCE(NULLIF(telegram_payment_charge_id, ''), NULLIF(provider_payment_charge_id, '')) IS NOT NULL
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS payment_events (
                event_id TEXT PRIMARY KEY,
                order_id TEXT REFERENCES payment_orders(order_id) ON DELETE SET NULL,
                event_type TEXT NOT NULL,
                provider TEXT,
                event_key TEXT,
                telegram_payment_charge_id TEXT,
                provider_payment_charge_id TEXT,
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT chk_payment_events_type CHECK (
                    event_type IN (
                        'successful_payment_received',
                        'successful_payment_duplicate',
                        'successful_payment_unknown_payload',
                        'successful_payment_orphan',
                        'successful_payment_rejected'
                    )
                ),
                CONSTRAINT chk_payment_events_provider CHECK (
                    provider IS NULL OR provider IN ('telegram_stars', 'yookassa')
                )
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_charges_telegram_charge_id_unique
                ON payment_charges(provider, telegram_payment_charge_id)
                WHERE telegram_payment_charge_id IS NOT NULL AND telegram_payment_charge_id <> ''
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_charges_provider_charge_id_unique
                ON payment_charges(provider, provider_payment_charge_id)
                WHERE provider_payment_charge_id IS NOT NULL AND provider_payment_charge_id <> ''
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_events_event_key_unique
                ON payment_events(event_key)
                WHERE event_key IS NOT NULL AND event_key <> ''
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_payment_orders_user_chat_created
                ON payment_orders(user_id, chat_id, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_payment_events_order_created
                ON payment_events(order_id, created_at)
            """,
        ),
    ),
)


def run_payment_schema_migrations(cur: Any) -> None:
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
