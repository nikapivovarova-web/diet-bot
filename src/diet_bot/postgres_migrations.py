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
        subscription_source TEXT NOT NULL DEFAULT 'none',
        auto_renew_status TEXT NOT NULL DEFAULT 'not_applicable',
        stars_subscription_charge_id TEXT,
        last_subscription_payment_charge_id TEXT,
        current_period_payment_order_id TEXT,
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
        CHECK (subscription_source IN ('none', 'telegram_stars', 'yookassa', 'promo', 'admin', 'legacy')),
        CHECK (auto_renew_status IN ('not_applicable', 'enabled', 'canceled', 'unknown')),
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
        list_amount INTEGER NOT NULL,
        discount_amount INTEGER NOT NULL DEFAULT 0,
        currency TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        invoice_link TEXT,
        pre_checkout_approved_at TIMESTAMPTZ,
        promo_code_id BIGINT,
        promo_redemption_id BIGINT,
        promo_code_hash TEXT,
        promo_code_suffix TEXT,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        paid_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (product IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf')),
        CHECK (provider IN ('telegram_stars', 'yookassa')),
        CHECK (status IN ('pending', 'paid', 'expired', 'failed_invoice_creation')),
        CHECK (amount > 0),
        CHECK (list_amount > 0),
        CHECK (discount_amount >= 0),
        CHECK (list_amount - discount_amount = amount)
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
        kind TEXT NOT NULL DEFAULT 'monthly_access',
        value INTEGER NOT NULL DEFAULT 1,
        max_uses INTEGER,
        max_redemptions INTEGER,
        per_user_limit INTEGER NOT NULL DEFAULT 1,
        used_count INTEGER NOT NULL DEFAULT 0,
        valid_from TIMESTAMPTZ,
        valid_until TIMESTAMPTZ,
        expires_at TIMESTAMPTZ,
        is_active BOOLEAN NOT NULL DEFAULT true,
        discount_percent INTEGER,
        discount_amount INTEGER,
        monthly_duration_months INTEGER NOT NULL DEFAULT 1,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (kind IN (
            'monthly_access',
            'discount',
            'subscription_month',
            'extra_one_day',
            'extra_weekly_pdf',
            'test_access_days'
        )),
        CHECK (value >= 1),
        CHECK (used_count >= 0),
        CHECK (max_uses IS NULL OR max_uses >= 0),
        CHECK (max_uses IS NULL OR used_count <= max_uses),
        CHECK (max_redemptions IS NULL OR max_redemptions >= 0),
        CHECK (max_redemptions IS NULL OR used_count <= max_redemptions),
        CHECK (per_user_limit >= 1),
        CHECK (discount_percent IS NULL OR discount_percent BETWEEN 1 AND 100),
        CHECK (discount_amount IS NULL OR discount_amount > 0),
        CHECK (monthly_duration_months >= 1)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promo_redemptions (
        id BIGSERIAL PRIMARY KEY,
        promo_code_id BIGINT NOT NULL REFERENCES promo_codes(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
        order_id TEXT REFERENCES payment_orders(order_id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'redeemed',
        kind TEXT,
        discount_amount INTEGER,
        entitlement_event_id BIGINT REFERENCES entitlement_events(id) ON DELETE SET NULL,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        redeemed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (status IN ('redeemed', 'reserved', 'released')),
        CHECK (
            kind IS NULL
            OR kind IN (
                'monthly_access',
                'discount',
                'subscription_month',
                'extra_one_day',
                'extra_weekly_pdf',
                'test_access_days'
            )
        ),
        CHECK (discount_amount IS NULL OR discount_amount >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promo_events (
        id BIGSERIAL PRIMARY KEY,
        promo_code_id BIGINT REFERENCES promo_codes(id) ON DELETE CASCADE,
        redemption_id BIGINT REFERENCES promo_redemptions(id) ON DELETE SET NULL,
        user_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
        event_type TEXT NOT NULL,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (event_type IN ('created', 'reserved', 'redeemed', 'released', 'rejected', 'disabled'))
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
    CREATE UNIQUE INDEX IF NOT EXISTS uniq_entitlements_stars_subscription_charge_id
        ON entitlements(stars_subscription_charge_id)
        WHERE stars_subscription_charge_id IS NOT NULL
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
    CREATE INDEX IF NOT EXISTS idx_promo_codes_active_expires
        ON promo_codes(is_active, expires_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_promo_redemptions_code_user
        ON promo_redemptions(promo_code_id, user_id, redeemed_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_promo_redemptions_user
        ON promo_redemptions(user_id, redeemed_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_promo_events_code_created
        ON promo_events(promo_code_id, created_at DESC)
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


PAYMENT_PRE_CHECKOUT_APPROVAL_MIGRATION = PostgresMigration(
    version="202605130001",
    description="Add payment order pre-checkout approval timestamp",
    statements=(
        """
        ALTER TABLE payment_orders
        ADD COLUMN IF NOT EXISTS pre_checkout_approved_at TIMESTAMPTZ
        """,
    ),
)


PAYMENT_SUCCESS_LEDGER_MIGRATION = PostgresMigration(
    version="202605130002",
    description="Add successful payment event and charge idempotency ledger",
    statements=(
        """
        CREATE TABLE IF NOT EXISTS payment_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            provider TEXT NOT NULL,
            order_id TEXT REFERENCES payment_orders(order_id) ON DELETE SET NULL,
            charge_id TEXT,
            telegram_charge_id TEXT,
            provider_charge_id TEXT,
            user_id BIGINT,
            delivery_chat_id BIGINT,
            product TEXT,
            amount INTEGER,
            currency TEXT,
            status TEXT NOT NULL,
            reason TEXT,
            is_recurring BOOLEAN NOT NULL DEFAULT false,
            is_first_recurring BOOLEAN NOT NULL DEFAULT false,
            subscription_expiration_at TIMESTAMPTZ,
            raw_payload_redacted JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ,
            CHECK (event_type IN (
                'successful_payment',
                'refund',
                'chargeback',
                'cancel_subscription',
                'unknown'
            )),
            CHECK (provider IN ('telegram_stars', 'yookassa')),
            CHECK (
                product IS NULL
                OR product IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf')
            ),
            CHECK (currency IS NULL OR currency IN ('XTR', 'RUB')),
            CHECK (status IN (
                'processed',
                'duplicate',
                'pending_reconciliation',
                'orphan_recoverable',
                'ignored_non_terminal'
            )),
            CHECK (amount IS NULL OR amount >= 0),
            CHECK (NOT is_first_recurring OR is_recurring)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS processed_provider_charges (
            provider TEXT NOT NULL,
            charge_id TEXT NOT NULL,
            telegram_charge_id TEXT,
            provider_charge_id TEXT,
            order_id TEXT REFERENCES payment_orders(order_id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            user_id BIGINT,
            product TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (provider, charge_id, event_type),
            CHECK (provider IN ('telegram_stars', 'yookassa')),
            CHECK (event_type IN (
                'successful_payment',
                'refund',
                'chargeback',
                'cancel_subscription',
                'unknown'
            )),
            CHECK (
                product IS NULL
                OR product IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf')
            )
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_payment_events_order_created_at
            ON payment_events(order_id, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_payment_events_charge
            ON payment_events(provider, charge_id, event_type)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_processed_provider_charges_order
            ON processed_provider_charges(order_id, created_at DESC)
        """,
    ),
)


PROMO_STORAGE_FOUNDATION_MIGRATION = PostgresMigration(
    version="202605130003",
    description="Add explicit promo storage definitions and audit events",
    statements=(
        """
        ALTER TABLE promo_codes
        ADD COLUMN IF NOT EXISTS max_redemptions INTEGER
        """,
        """
        ALTER TABLE promo_codes
        ADD COLUMN IF NOT EXISTS per_user_limit INTEGER NOT NULL DEFAULT 1
        """,
        """
        ALTER TABLE promo_codes
        ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ
        """,
        """
        ALTER TABLE promo_codes
        ADD COLUMN IF NOT EXISTS discount_percent INTEGER
        """,
        """
        ALTER TABLE promo_codes
        ADD COLUMN IF NOT EXISTS discount_amount INTEGER
        """,
        """
        ALTER TABLE promo_codes
        ADD COLUMN IF NOT EXISTS monthly_duration_months INTEGER NOT NULL DEFAULT 1
        """,
        """
        ALTER TABLE promo_codes
        ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
        """,
        """
        DO $$
        BEGIN
            UPDATE promo_codes
            SET expires_at = COALESCE(expires_at, valid_until),
                max_redemptions = COALESCE(max_redemptions, max_uses),
                monthly_duration_months = GREATEST(1, COALESCE(monthly_duration_months, value, 1))
            WHERE expires_at IS NULL
               OR max_redemptions IS NULL
               OR monthly_duration_months IS NULL;
        END $$;
        """,
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_codes'::regclass
                  AND conname = 'promo_codes_kind_check'
            ) THEN
                ALTER TABLE promo_codes DROP CONSTRAINT promo_codes_kind_check;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_codes'::regclass
                  AND conname = 'promo_codes_kind_supported_check'
            ) THEN
                ALTER TABLE promo_codes
                ADD CONSTRAINT promo_codes_kind_supported_check
                CHECK (kind IN (
                    'monthly_access',
                    'discount',
                    'subscription_month',
                    'extra_one_day',
                    'extra_weekly_pdf',
                    'test_access_days'
                ));
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_codes'::regclass
                  AND conname = 'promo_codes_max_redemptions_check'
            ) THEN
                ALTER TABLE promo_codes
                ADD CONSTRAINT promo_codes_max_redemptions_check
                CHECK (max_redemptions IS NULL OR max_redemptions >= 0);
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_codes'::regclass
                  AND conname = 'promo_codes_max_redemptions_used_check'
            ) THEN
                ALTER TABLE promo_codes
                ADD CONSTRAINT promo_codes_max_redemptions_used_check
                CHECK (max_redemptions IS NULL OR used_count <= max_redemptions);
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_codes'::regclass
                  AND conname = 'promo_codes_per_user_limit_check'
            ) THEN
                ALTER TABLE promo_codes
                ADD CONSTRAINT promo_codes_per_user_limit_check
                CHECK (per_user_limit >= 1);
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_codes'::regclass
                  AND conname = 'promo_codes_discount_percent_check'
            ) THEN
                ALTER TABLE promo_codes
                ADD CONSTRAINT promo_codes_discount_percent_check
                CHECK (discount_percent IS NULL OR discount_percent BETWEEN 1 AND 100);
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_codes'::regclass
                  AND conname = 'promo_codes_discount_amount_check'
            ) THEN
                ALTER TABLE promo_codes
                ADD CONSTRAINT promo_codes_discount_amount_check
                CHECK (discount_amount IS NULL OR discount_amount > 0);
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_codes'::regclass
                  AND conname = 'promo_codes_monthly_duration_check'
            ) THEN
                ALTER TABLE promo_codes
                ADD CONSTRAINT promo_codes_monthly_duration_check
                CHECK (monthly_duration_months >= 1);
            END IF;
        END $$;
        """,
        """
        ALTER TABLE promo_redemptions
        DROP CONSTRAINT IF EXISTS promo_redemptions_promo_code_id_user_id_key
        """,
        """
        ALTER TABLE promo_redemptions
        ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'redeemed'
        """,
        """
        ALTER TABLE promo_redemptions
        ADD COLUMN IF NOT EXISTS kind TEXT
        """,
        """
        ALTER TABLE promo_redemptions
        ADD COLUMN IF NOT EXISTS discount_amount INTEGER
        """,
        """
        ALTER TABLE promo_redemptions
        ADD COLUMN IF NOT EXISTS entitlement_event_id BIGINT REFERENCES entitlement_events(id) ON DELETE SET NULL
        """,
        """
        ALTER TABLE promo_redemptions
        ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_redemptions'::regclass
                  AND conname = 'promo_redemptions_status_supported_check'
            ) THEN
                ALTER TABLE promo_redemptions
                ADD CONSTRAINT promo_redemptions_status_supported_check
                CHECK (status IN ('redeemed', 'reserved', 'released'));
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_redemptions'::regclass
                  AND conname = 'promo_redemptions_kind_supported_check'
            ) THEN
                ALTER TABLE promo_redemptions
                ADD CONSTRAINT promo_redemptions_kind_supported_check
                CHECK (
                    kind IS NULL
                    OR kind IN (
                        'monthly_access',
                        'discount',
                        'subscription_month',
                        'extra_one_day',
                        'extra_weekly_pdf',
                        'test_access_days'
                    )
                );
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_redemptions'::regclass
                  AND conname = 'promo_redemptions_discount_amount_check'
            ) THEN
                ALTER TABLE promo_redemptions
                ADD CONSTRAINT promo_redemptions_discount_amount_check
                CHECK (discount_amount IS NULL OR discount_amount >= 0);
            END IF;
        END $$;
        """,
        """
        CREATE TABLE IF NOT EXISTS promo_events (
            id BIGSERIAL PRIMARY KEY,
            promo_code_id BIGINT REFERENCES promo_codes(id) ON DELETE CASCADE,
            redemption_id BIGINT REFERENCES promo_redemptions(id) ON DELETE SET NULL,
            user_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (event_type IN ('created', 'redeemed', 'rejected', 'disabled'))
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_promo_codes_active_expires
            ON promo_codes(is_active, expires_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_promo_redemptions_code_user
            ON promo_redemptions(promo_code_id, user_id, redeemed_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_promo_events_code_created
            ON promo_events(promo_code_id, created_at DESC)
        """,
    ),
)


PROMO_PAYMENT_DISCOUNT_MIGRATION = PostgresMigration(
    version="202605130004",
    description="Attach discount promo reservations to payment orders",
    statements=(
        """
        ALTER TABLE payment_orders
        ADD COLUMN IF NOT EXISTS list_amount INTEGER
        """,
        """
        ALTER TABLE payment_orders
        ADD COLUMN IF NOT EXISTS discount_amount INTEGER NOT NULL DEFAULT 0
        """,
        """
        ALTER TABLE payment_orders
        ADD COLUMN IF NOT EXISTS promo_code_id BIGINT
        """,
        """
        ALTER TABLE payment_orders
        ADD COLUMN IF NOT EXISTS promo_redemption_id BIGINT
        """,
        """
        ALTER TABLE payment_orders
        ADD COLUMN IF NOT EXISTS promo_code_hash TEXT
        """,
        """
        ALTER TABLE payment_orders
        ADD COLUMN IF NOT EXISTS promo_code_suffix TEXT
        """,
        """
        ALTER TABLE payment_orders
        ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
        """,
        """
        ALTER TABLE promo_redemptions
        ADD COLUMN IF NOT EXISTS order_id TEXT
        """,
        """
        DO $$
        BEGIN
            UPDATE payment_orders
            SET list_amount = COALESCE(list_amount, amount),
                discount_amount = COALESCE(discount_amount, 0),
                metadata_json = COALESCE(metadata_json, '{}'::jsonb)
            WHERE list_amount IS NULL
               OR discount_amount IS NULL
               OR metadata_json IS NULL;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'payment_orders'::regclass
                  AND conname = 'payment_orders_list_amount_check'
            ) THEN
                ALTER TABLE payment_orders
                ADD CONSTRAINT payment_orders_list_amount_check
                CHECK (list_amount > 0);
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'payment_orders'::regclass
                  AND conname = 'payment_orders_discount_amount_check'
            ) THEN
                ALTER TABLE payment_orders
                ADD CONSTRAINT payment_orders_discount_amount_check
                CHECK (discount_amount >= 0);
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'payment_orders'::regclass
                  AND conname = 'payment_orders_final_amount_check'
            ) THEN
                ALTER TABLE payment_orders
                ADD CONSTRAINT payment_orders_final_amount_check
                CHECK (amount > 0 AND list_amount - discount_amount = amount);
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'payment_orders'::regclass
                  AND conname = 'payment_orders_promo_code_id_fkey'
            ) THEN
                ALTER TABLE payment_orders
                ADD CONSTRAINT payment_orders_promo_code_id_fkey
                FOREIGN KEY (promo_code_id) REFERENCES promo_codes(id) ON DELETE SET NULL;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'payment_orders'::regclass
                  AND conname = 'payment_orders_promo_redemption_id_fkey'
            ) THEN
                ALTER TABLE payment_orders
                ADD CONSTRAINT payment_orders_promo_redemption_id_fkey
                FOREIGN KEY (promo_redemption_id) REFERENCES promo_redemptions(id) ON DELETE SET NULL;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_redemptions'::regclass
                  AND conname = 'promo_redemptions_order_id_fkey'
            ) THEN
                ALTER TABLE promo_redemptions
                ADD CONSTRAINT promo_redemptions_order_id_fkey
                FOREIGN KEY (order_id) REFERENCES payment_orders(order_id) ON DELETE SET NULL;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_events'::regclass
                  AND conname = 'promo_events_event_type_check'
            ) THEN
                ALTER TABLE promo_events DROP CONSTRAINT promo_events_event_type_check;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'promo_events'::regclass
                  AND conname = 'promo_events_event_type_supported_check'
            ) THEN
                ALTER TABLE promo_events
                ADD CONSTRAINT promo_events_event_type_supported_check
                CHECK (event_type IN ('created', 'reserved', 'redeemed', 'released', 'rejected', 'disabled'));
            END IF;
        END $$;
        """,
        """
        ALTER TABLE payment_orders
        ALTER COLUMN list_amount SET NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_payment_orders_promo_code
            ON payment_orders(promo_code_id, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_promo_redemptions_order
            ON promo_redemptions(order_id)
        """,
    ),
)


RECIPE_HISTORY_MIGRATION = PostgresMigration(
    version="202605140001",
    description="Add per-user recipe history ledger",
    statements=(
        """
        CREATE TABLE IF NOT EXISTS user_recipe_history (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
            generation_id BIGINT REFERENCES generation_records(id) ON DELETE SET NULL,
            ration_kind TEXT NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            day_index INTEGER,
            meal_index INTEGER NOT NULL,
            meal_slot TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            recipe_key TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (ration_kind IN ('one_day', 'weekly_pdf')),
            CHECK (meal_index >= 0),
            CHECK (day_index IS NULL OR day_index >= 0)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_user_recipe_history_recent
            ON user_recipe_history(user_id, generated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_user_recipe_history_recipe_id
            ON user_recipe_history(user_id, recipe_id, generated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_user_recipe_history_recipe_key
            ON user_recipe_history(user_id, recipe_key, generated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_user_recipe_history_generation
            ON user_recipe_history(generation_id)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_user_recipe_history_generation_slot
            ON user_recipe_history(
                generation_id,
                COALESCE(day_index, -1),
                meal_index,
                recipe_id
            )
            WHERE generation_id IS NOT NULL
        """,
    ),
)


MANAGED_SUBSCRIPTION_STATE_MIGRATION = PostgresMigration(
    version="202605160001",
    description="Add managed subscription state fields",
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
        """
        ALTER TABLE payment_events
        ADD COLUMN IF NOT EXISTS is_recurring BOOLEAN NOT NULL DEFAULT false
        """,
        """
        ALTER TABLE payment_events
        ADD COLUMN IF NOT EXISTS is_first_recurring BOOLEAN NOT NULL DEFAULT false
        """,
        """
        ALTER TABLE payment_events
        ADD COLUMN IF NOT EXISTS subscription_expiration_at TIMESTAMPTZ
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'entitlements'::regclass
                  AND conname = 'entitlements_subscription_source_supported_check'
            ) THEN
                ALTER TABLE entitlements
                ADD CONSTRAINT entitlements_subscription_source_supported_check
                CHECK (subscription_source IN ('none', 'telegram_stars', 'yookassa', 'promo', 'admin', 'legacy'));
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'entitlements'::regclass
                  AND conname = 'entitlements_auto_renew_status_supported_check'
            ) THEN
                ALTER TABLE entitlements
                ADD CONSTRAINT entitlements_auto_renew_status_supported_check
                CHECK (auto_renew_status IN ('not_applicable', 'enabled', 'canceled', 'unknown'));
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'entitlements'::regclass
                  AND conname = 'entitlements_current_period_payment_order_id_fkey'
            ) THEN
                ALTER TABLE entitlements
                ADD CONSTRAINT entitlements_current_period_payment_order_id_fkey
                FOREIGN KEY (current_period_payment_order_id)
                REFERENCES payment_orders(order_id)
                ON DELETE SET NULL;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'payment_events'::regclass
                  AND conname = 'payment_events_recurring_consistency_check'
            ) THEN
                ALTER TABLE payment_events
                ADD CONSTRAINT payment_events_recurring_consistency_check
                CHECK (NOT is_first_recurring OR is_recurring);
            END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
            UPDATE entitlements
            SET subscription_source = 'none',
                auto_renew_status = 'not_applicable',
                stars_subscription_charge_id = NULL,
                last_subscription_payment_charge_id = NULL,
                current_period_payment_order_id = NULL
            WHERE subscription_period_end IS NULL
               OR subscription_period_end <= now();
        END $$;
        """,
        """
        DO $$
        BEGIN
            WITH latest_paid_subscription AS (
                SELECT DISTINCT ON (orders.user_id)
                    orders.user_id,
                    orders.order_id,
                    orders.provider,
                    events.charge_id,
                    events.telegram_charge_id
                FROM payment_orders AS orders
                LEFT JOIN LATERAL (
                    SELECT charge_id, telegram_charge_id, created_at, event_id
                    FROM payment_events
                    WHERE order_id = orders.order_id
                      AND event_type = 'successful_payment'
                      AND status = 'processed'
                    ORDER BY created_at DESC NULLS LAST, event_id DESC
                    LIMIT 1
                ) AS events ON TRUE
                WHERE orders.product = 'subscription_month'
                  AND orders.status = 'paid'
                  AND orders.provider IN ('telegram_stars', 'yookassa')
                ORDER BY orders.user_id,
                         COALESCE(orders.paid_at, orders.updated_at, orders.created_at) DESC,
                         orders.order_id DESC
            )
            UPDATE entitlements AS entitlements
            SET subscription_source = latest_paid_subscription.provider,
                auto_renew_status = CASE
                    WHEN latest_paid_subscription.provider = 'telegram_stars' THEN 'enabled'
                    ELSE 'not_applicable'
                END,
                stars_subscription_charge_id = CASE
                    WHEN latest_paid_subscription.provider = 'telegram_stars'
                        THEN COALESCE(
                            latest_paid_subscription.telegram_charge_id,
                            latest_paid_subscription.charge_id,
                            entitlements.stars_subscription_charge_id
                        )
                    ELSE NULL
                END,
                last_subscription_payment_charge_id = latest_paid_subscription.charge_id,
                current_period_payment_order_id = latest_paid_subscription.order_id
            FROM latest_paid_subscription
            WHERE entitlements.user_id = latest_paid_subscription.user_id
              AND entitlements.subscription_period_end IS NOT NULL
              AND entitlements.subscription_period_end > now();
        END $$;
        """,
        """
        DO $$
        BEGIN
            WITH latest_subscription_grant AS (
                SELECT DISTINCT ON (user_id)
                    user_id,
                    source
                FROM entitlement_events
                WHERE event_type = 'grant'
                  AND (
                      (
                          source = 'promo'
                          AND metadata_json->>'promo_kind' IN ('monthly_access', 'subscription_month')
                      )
                      OR (
                          source = 'admin'
                          AND (
                              metadata_json->>'grant' = 'subscription_month'
                              OR metadata_json->>'subscription_source' = 'admin'
                          )
                      )
                  )
                ORDER BY user_id, id DESC
            )
            UPDATE entitlements AS entitlements
            SET subscription_source = latest_subscription_grant.source,
                auto_renew_status = 'not_applicable',
                stars_subscription_charge_id = NULL
            FROM latest_subscription_grant
            WHERE entitlements.user_id = latest_subscription_grant.user_id
              AND entitlements.subscription_source = 'none'
              AND entitlements.subscription_period_end IS NOT NULL
              AND entitlements.subscription_period_end > now();
        END $$;
        """,
        """
        DO $$
        BEGIN
            UPDATE entitlements
            SET subscription_source = 'legacy',
                auto_renew_status = 'unknown',
                stars_subscription_charge_id = NULL
            WHERE subscription_source = 'none'
              AND subscription_period_end IS NOT NULL
              AND subscription_period_end > now();
        END $$;
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_entitlements_stars_subscription_charge_id
            ON entitlements(stars_subscription_charge_id)
            WHERE stars_subscription_charge_id IS NOT NULL
        """,
    ),
)


PROMO_KIND_CONSTRAINT_COMPATIBILITY_MIGRATION = PostgresMigration(
    version="202605170001",
    description="Replace legacy promo kind constraint",
    statements=(
        """
        DO $$
        BEGIN
            ALTER TABLE promo_codes
            DROP CONSTRAINT IF EXISTS chk_promo_codes_kind_allowed;

            ALTER TABLE promo_codes
            DROP CONSTRAINT IF EXISTS promo_codes_kind_check;

            ALTER TABLE promo_codes
            DROP CONSTRAINT IF EXISTS promo_codes_kind_supported_check;

            ALTER TABLE promo_codes
            ADD CONSTRAINT promo_codes_kind_supported_check
            CHECK (kind IN (
                'monthly_access',
                'discount',
                'subscription_month',
                'extra_one_day',
                'extra_weekly_pdf',
                'test_access_days'
            ));
        END $$;
        """,
    ),
)


POSTGRES_LEGACY_LEDGER_COMPATIBILITY_MIGRATION = PostgresMigration(
    version="202605170002",
    description="Drop legacy ledger constraints",
    statements=(
        """
        ALTER TABLE entitlement_events
        DROP CONSTRAINT IF EXISTS chk_entitlement_events_source_allowed
        """,
        """
        DROP INDEX IF EXISTS uniq_payment_events_provider_charge_type
        """,
    ),
)


ANALYTICS_FOUNDATION_MIGRATION = PostgresMigration(
    version="202605170003",
    description="Add first-party analytics attribution and events",
    statements=(
        """
        CREATE TABLE IF NOT EXISTS user_attribution (
            user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
            source TEXT,
            campaign TEXT,
            referral TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS analytics_events (
            id BIGSERIAL PRIMARY KEY,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
            chat_id BIGINT,
            event_name TEXT NOT NULL,
            source TEXT,
            campaign TEXT,
            referral TEXT,
            properties_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            CHECK (event_name <> '')
        )
        """,
        """
        ALTER TABLE analytics_events
        ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        """,
        """
        ALTER TABLE analytics_events
        ADD COLUMN IF NOT EXISTS chat_id BIGINT
        """,
        """
        ALTER TABLE analytics_events
        ADD COLUMN IF NOT EXISTS source TEXT
        """,
        """
        ALTER TABLE analytics_events
        ADD COLUMN IF NOT EXISTS campaign TEXT
        """,
        """
        ALTER TABLE analytics_events
        ADD COLUMN IF NOT EXISTS referral TEXT
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_user_attribution_source_campaign
            ON user_attribution(source, campaign)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_analytics_events_user_occurred_at
            ON analytics_events(user_id, occurred_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_analytics_events_name_occurred_at
            ON analytics_events(event_name, occurred_at DESC)
        """,
    ),
)


ANALYTICS_CHAT_ID_COMPATIBILITY_MIGRATION = PostgresMigration(
    version="202605170004",
    description="Repair analytics events chat id column",
    statements=(
        """
        ALTER TABLE analytics_events
        ADD COLUMN IF NOT EXISTS chat_id BIGINT
        """,
    ),
)


ANALYTICS_WRITE_COLUMNS_COMPATIBILITY_MIGRATION = PostgresMigration(
    version="202605170005",
    description="Repair analytics events attribution columns",
    statements=(
        """
        ALTER TABLE analytics_events
        ADD COLUMN IF NOT EXISTS source TEXT
        """,
        """
        ALTER TABLE analytics_events
        ADD COLUMN IF NOT EXISTS campaign TEXT
        """,
        """
        ALTER TABLE analytics_events
        ADD COLUMN IF NOT EXISTS referral TEXT
        """,
    ),
)


POSTGRES_MIGRATIONS = (
    BASE_SCHEMA_MIGRATION,
    PAYMENT_PRE_CHECKOUT_APPROVAL_MIGRATION,
    PAYMENT_SUCCESS_LEDGER_MIGRATION,
    PROMO_STORAGE_FOUNDATION_MIGRATION,
    PROMO_PAYMENT_DISCOUNT_MIGRATION,
    RECIPE_HISTORY_MIGRATION,
    MANAGED_SUBSCRIPTION_STATE_MIGRATION,
    PROMO_KIND_CONSTRAINT_COMPATIBILITY_MIGRATION,
    POSTGRES_LEGACY_LEDGER_COMPATIBILITY_MIGRATION,
    ANALYTICS_FOUNDATION_MIGRATION,
    ANALYTICS_CHAT_ID_COMPATIBILITY_MIGRATION,
    ANALYTICS_WRITE_COLUMNS_COMPATIBILITY_MIGRATION,
)


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
