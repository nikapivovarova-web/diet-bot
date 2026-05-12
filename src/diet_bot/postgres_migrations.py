from __future__ import annotations

from collections.abc import Mapping
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


BASE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        telegram_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_state (
        chat_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
        state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profiles (
        user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
        profile_json JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entitlements (
        user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
        plan TEXT NOT NULL DEFAULT 'free',
        status TEXT NOT NULL DEFAULT 'inactive',
        subscription_period_start TIMESTAMPTZ,
        subscription_period_end TIMESTAMPTZ,
        test_access_until TIMESTAMPTZ,
        test_access_enabled BOOLEAN NOT NULL DEFAULT false,
        free_trial_used BOOLEAN NOT NULL DEFAULT false,
        monthly_one_day_remaining INTEGER NOT NULL DEFAULT 0,
        monthly_weekly_pdf_remaining INTEGER NOT NULL DEFAULT 0,
        extra_one_day_remaining INTEGER NOT NULL DEFAULT 0,
        extra_weekly_pdf_remaining INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (plan IN ('free', 'monthly', 'test_access')),
        CHECK (status IN ('active', 'inactive')),
        CHECK (
            monthly_one_day_remaining >= 0
            AND monthly_weekly_pdf_remaining >= 0
            AND extra_one_day_remaining >= 0
            AND extra_weekly_pdf_remaining >= 0
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entitlement_events (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
        generation_id BIGINT,
        event_type TEXT NOT NULL,
        source TEXT,
        amount INTEGER NOT NULL DEFAULT 1,
        related_event_id BIGINT REFERENCES entitlement_events(id) ON DELETE SET NULL,
        reason TEXT,
        delta_generations INTEGER,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payment_orders (
        order_id TEXT PRIMARY KEY,
        nonce TEXT NOT NULL,
        user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
        delivery_chat_id BIGINT,
        product TEXT NOT NULL,
        provider TEXT NOT NULL,
        amount INTEGER NOT NULL,
        currency TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        invoice_link TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        paid_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (product IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf')),
        CHECK (provider IN ('telegram_stars', 'yookassa')),
        CHECK (status IN ('pending', 'paid', 'expired', 'failed_invoice_creation')),
        CHECK (amount >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generation_records (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
        ration_kind TEXT NOT NULL,
        status TEXT NOT NULL,
        entitlement_event_id BIGINT REFERENCES entitlement_events(id) ON DELETE SET NULL,
        pdf_path TEXT,
        error_message TEXT,
        heartbeat_at TIMESTAMPTZ,
        expires_at TIMESTAMPTZ,
        delivery_started_at TIMESTAMPTZ,
        delivered_at TIMESTAMPTZ,
        telegram_message_id BIGINT,
        delivery_attempts INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ,
        CHECK (ration_kind IN ('one_day', 'weekly_pdf')),
        CHECK (status IN ('generating', 'delivering', 'completed', 'failed', 'failed_timeout')),
        CHECK (delivery_attempts >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promo_codes (
        id BIGSERIAL PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL DEFAULT 'subscription_month',
        value INTEGER NOT NULL DEFAULT 1,
        max_uses INTEGER,
        used_count INTEGER NOT NULL DEFAULT 0,
        valid_from TIMESTAMPTZ,
        valid_until TIMESTAMPTZ,
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (kind IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf', 'test_access_days')),
        CHECK (value >= 1),
        CHECK (used_count >= 0),
        CHECK (max_uses IS NULL OR max_uses >= 0),
        CHECK (max_uses IS NULL OR used_count <= max_uses)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promo_redemptions (
        id BIGSERIAL PRIMARY KEY,
        promo_code_id BIGINT NOT NULL REFERENCES promo_codes(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
        redeemed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(promo_code_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS support_state (
        user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'idle',
        last_request_at TIMESTAMPTZ,
        last_admin_message_id BIGINT,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (status IN ('idle', 'open', 'answered', 'closed'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_entitlement_events_user_created_at
        ON entitlement_events(user_id, created_at DESC)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_consume_per_generation
        ON entitlement_events(generation_id, event_type)
        WHERE event_type = 'consume' AND generation_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_refund_per_generation
        ON entitlement_events(generation_id, event_type)
        WHERE event_type = 'refund' AND generation_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_refund_per_related_event
        ON entitlement_events(related_event_id)
        WHERE event_type = 'refund' AND related_event_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_generation_per_user
        ON generation_records(user_id)
        WHERE status IN ('generating', 'delivering')
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_generation_records_active_heartbeat
        ON generation_records(user_id, heartbeat_at)
        WHERE status IN ('generating', 'delivering')
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_payment_orders_user_status
        ON payment_orders(user_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_promo_redemptions_user
        ON promo_redemptions(user_id, redeemed_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_support_state_status_updated
        ON support_state(status, updated_at DESC)
    """,
)


BASE_SCHEMA_MIGRATION = PostgresMigration(
    version="202605120003",
    description="Create paid production storage schema",
    statements=BASE_SCHEMA_STATEMENTS,
)


POSTGRES_MIGRATIONS = (BASE_SCHEMA_MIGRATION,)


def run_postgres_migrations(cur: Any) -> None:
    cur.execute(SCHEMA_MIGRATIONS_SQL.strip())
    cur.execute("SELECT version FROM schema_migrations")
    applied_versions = _version_set(cur.fetchall())

    for migration in POSTGRES_MIGRATIONS:
        if migration.version in applied_versions:
            continue
        for statement in migration.statements:
            stripped_statement = statement.strip()
            if stripped_statement:
                cur.execute(stripped_statement)
        cur.execute(
            """
            INSERT INTO schema_migrations (version, description)
            VALUES (%s, %s)
            ON CONFLICT (version) DO NOTHING
            """.strip(),
            (migration.version, migration.description),
        )
        applied_versions.add(migration.version)


def _version_set(rows: Any) -> set[str]:
    versions: set[str] = set()
    for row in rows:
        if isinstance(row, Mapping):
            versions.add(str(row["version"]))
        else:
            versions.add(str(row[0]))
    return versions
