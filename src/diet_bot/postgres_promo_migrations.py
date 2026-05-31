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
        version="202605300001",
        description="Create promo code tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                discount_type TEXT,
                discount_percent INTEGER,
                discount_amount_minor INTEGER,
                duration_days INTEGER,
                monthly_duration_months INTEGER NOT NULL DEFAULT 1,
                max_uses INTEGER NOT NULL DEFAULT 1,
                per_user_limit INTEGER NOT NULL DEFAULT 1,
                expires_at TIMESTAMPTZ,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_by BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                disabled_at TIMESTAMPTZ,
                disabled_by BIGINT,
                campaign_key TEXT,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                CONSTRAINT chk_promo_codes_code_non_empty CHECK (code <> ''),
                CONSTRAINT chk_promo_codes_kind CHECK (
                    kind IN ('monthly_access', 'discount', 'test_access')
                ),
                CONSTRAINT chk_promo_codes_discount_type CHECK (
                    discount_type IS NULL OR discount_type IN ('percent', 'amount')
                ),
                CONSTRAINT chk_promo_codes_discount_shape CHECK (
                    (
                        kind IN ('monthly_access', 'test_access')
                        AND discount_type IS NULL
                        AND discount_percent IS NULL
                        AND discount_amount_minor IS NULL
                        AND monthly_duration_months >= 1
                    )
                    OR (
                        kind = 'discount'
                        AND monthly_duration_months = 1
                        AND (
                            (
                                discount_type = 'percent'
                                AND discount_percent BETWEEN 1 AND 90
                                AND discount_amount_minor IS NULL
                            )
                            OR (
                                discount_type = 'amount'
                                AND discount_amount_minor > 0
                                AND discount_percent IS NULL
                            )
                        )
                    )
                ),
                CONSTRAINT chk_promo_codes_limits CHECK (
                    max_uses >= 1 AND per_user_limit >= 1
                ),
                CONSTRAINT chk_promo_codes_duration_days CHECK (
                    duration_days IS NULL OR duration_days >= 1
                )
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_promo_codes_active_kind
                ON promo_codes(kind, code)
                WHERE active
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_promo_codes_campaign_key
                ON promo_codes(campaign_key)
                WHERE campaign_key IS NOT NULL
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_promo_codes_expires_at
                ON promo_codes(expires_at)
                WHERE expires_at IS NOT NULL
            """,
            """
            CREATE TABLE IF NOT EXISTS promo_code_redemptions (
                redemption_id BIGSERIAL PRIMARY KEY,
                code TEXT NOT NULL REFERENCES promo_codes(code) ON DELETE RESTRICT,
                chat_id BIGINT NOT NULL,
                user_id BIGINT,
                status TEXT NOT NULL DEFAULT 'redeemed',
                idempotency_key TEXT NOT NULL,
                offered_at TIMESTAMPTZ,
                reserved_at TIMESTAMPTZ,
                redeemed_at TIMESTAMPTZ,
                released_at TIMESTAMPTZ,
                failed_at TIMESTAMPTZ,
                window_expires_at TIMESTAMPTZ,
                payment_order_id TEXT,
                payment_provider TEXT,
                payment_product TEXT,
                currency TEXT,
                original_amount_minor INTEGER,
                discount_amount_minor INTEGER,
                final_amount_minor INTEGER,
                entitlement_charge_id TEXT,
                campaign_key TEXT,
                campaign_step_key TEXT,
                telegram_message_id BIGINT,
                failure_reason TEXT,
                source TEXT NOT NULL DEFAULT 'runtime',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT chk_promo_code_redemptions_status CHECK (
                    status IN ('offered', 'reserved', 'redeemed', 'released', 'expired', 'failed')
                ),
                CONSTRAINT chk_promo_code_redemptions_idempotency_key_non_empty CHECK (
                    idempotency_key <> ''
                ),
                CONSTRAINT chk_promo_code_redemptions_source_non_empty CHECK (source <> ''),
                CONSTRAINT chk_promo_code_redemptions_amounts CHECK (
                    (
                        original_amount_minor IS NULL
                        AND discount_amount_minor IS NULL
                        AND final_amount_minor IS NULL
                    )
                    OR (
                        original_amount_minor > 0
                        AND discount_amount_minor > 0
                        AND final_amount_minor > 0
                        AND original_amount_minor = final_amount_minor + discount_amount_minor
                    )
                ),
                CONSTRAINT chk_promo_code_redemptions_payment_provider CHECK (
                    payment_provider IS NULL OR payment_provider IN ('telegram_stars', 'yookassa')
                ),
                CONSTRAINT chk_promo_code_redemptions_redeemed_at_shape CHECK (
                    status <> 'redeemed' OR redeemed_at IS NOT NULL
                )
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_code_redemptions_idempotency_key_unique
                ON promo_code_redemptions(idempotency_key)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_code_redemptions_payment_order_unique
                ON promo_code_redemptions(payment_order_id)
                WHERE payment_order_id IS NOT NULL
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_code_redemptions_entitlement_charge_unique
                ON promo_code_redemptions(entitlement_charge_id)
                WHERE entitlement_charge_id IS NOT NULL
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_code_redemptions_code_chat_active_unique
                ON promo_code_redemptions(code, chat_id)
                WHERE status IN ('reserved', 'redeemed')
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_promo_code_redemptions_code_status
                ON promo_code_redemptions(code, status, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_promo_code_redemptions_chat_status
                ON promo_code_redemptions(chat_id, status, created_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS promo_import_runs (
                migration_id TEXT PRIMARY KEY,
                source_fingerprint TEXT NOT NULL,
                source_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'started',
                started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ,
                CONSTRAINT chk_promo_import_runs_status CHECK (
                    status IN ('started', 'applied', 'failed')
                )
            )
            """,
        ),
    ),
    PostgresMigration(
        version="202605310002",
        description="Allow promo per-user limits above one",
        statements=(
            """
            DROP INDEX IF EXISTS idx_promo_code_redemptions_code_chat_active_unique
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_promo_code_redemptions_code_chat_status
                ON promo_code_redemptions(code, chat_id, status, created_at)
            """,
        ),
    ),
)


def run_promo_schema_migrations(cur: Any) -> None:
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
