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
        version="202605260002",
        description="Create one-day generation job tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS one_day_generation_jobs (
                job_id UUID PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                consumption_source TEXT,
                refund_status TEXT NOT NULL DEFAULT 'not_required',
                delivery_status TEXT NOT NULL DEFAULT 'not_started',
                expected_value_messages INTEGER NOT NULL DEFAULT 0,
                delivered_value_messages INTEGER NOT NULL DEFAULT 0,
                send_started_at TIMESTAMPTZ,
                first_value_delivered_at TIMESTAMPTZ,
                delivered_at TIMESTAMPTZ,
                stale_after TIMESTAMPTZ NOT NULL,
                failure_reason TEXT,
                finalization_error TEXT,
                requires_manual_review BOOLEAN NOT NULL DEFAULT false,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                started_at TIMESTAMPTZ,
                heartbeat_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                CONSTRAINT chk_one_day_generation_jobs_idempotency_key_non_empty CHECK (idempotency_key <> ''),
                CONSTRAINT chk_one_day_generation_jobs_status CHECK (
                    status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
                ),
                CONSTRAINT chk_one_day_generation_jobs_consumption_source CHECK (
                    consumption_source IS NULL
                    OR consumption_source IN ('monthly', 'extra', 'free_trial', 'test_access')
                ),
                CONSTRAINT chk_one_day_generation_jobs_refund_status CHECK (
                    refund_status IN ('not_required', 'pending', 'refunded')
                ),
                CONSTRAINT chk_one_day_generation_jobs_delivery_status CHECK (
                    delivery_status IN ('not_started', 'send_started', 'partial', 'delivered', 'unknown')
                ),
                CONSTRAINT chk_one_day_generation_jobs_value_message_counts CHECK (
                    expected_value_messages >= 0
                    AND delivered_value_messages >= 0
                    AND delivered_value_messages <= expected_value_messages
                ),
                CONSTRAINT chk_one_day_generation_jobs_metadata_object CHECK (
                    jsonb_typeof(metadata_json) = 'object'
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS one_day_generation_job_value_messages (
                job_id UUID NOT NULL REFERENCES one_day_generation_jobs(job_id) ON DELETE CASCADE,
                value_message_key TEXT NOT NULL,
                delivered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (job_id, value_message_key),
                CONSTRAINT chk_one_day_generation_job_value_key_non_empty CHECK (value_message_key <> '')
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_day_generation_jobs_active_chat_unique
                ON one_day_generation_jobs(chat_id)
                WHERE status IN ('queued', 'running')
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_day_generation_jobs_idempotency_key_unique
                ON one_day_generation_jobs(idempotency_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_one_day_generation_jobs_stale
                ON one_day_generation_jobs(stale_after)
                WHERE status IN ('queued', 'running')
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_one_day_generation_job_value_messages_job
                ON one_day_generation_job_value_messages(job_id, delivered_at)
            """,
        ),
    ),
    PostgresMigration(
        version="202605270001",
        description="Add durable one-day queue request snapshot and lease fields",
        statements=(
            """
            ALTER TABLE one_day_generation_jobs
                ADD COLUMN IF NOT EXISTS request_payload_json JSONB,
                ADD COLUMN IF NOT EXISTS request_kind TEXT,
                ADD COLUMN IF NOT EXISTS profile_json JSONB,
                ADD COLUMN IF NOT EXISTS recent_recipe_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                ADD COLUMN IF NOT EXISTS generation_seed TEXT,
                ADD COLUMN IF NOT EXISTS worker_id TEXT,
                ADD COLUMN IF NOT EXISTS leased_until TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS last_error TEXT
            """,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'chk_one_day_generation_jobs_request_kind_non_empty'
                      AND conrelid = 'one_day_generation_jobs'::regclass
                ) THEN
                    ALTER TABLE one_day_generation_jobs
                        ADD CONSTRAINT chk_one_day_generation_jobs_request_kind_non_empty
                        CHECK (request_kind IS NULL OR request_kind <> '');
                END IF;
            END $$;
            """,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'chk_one_day_generation_jobs_request_payload_object'
                      AND conrelid = 'one_day_generation_jobs'::regclass
                ) THEN
                    ALTER TABLE one_day_generation_jobs
                        ADD CONSTRAINT chk_one_day_generation_jobs_request_payload_object
                        CHECK (
                            request_payload_json IS NULL
                            OR jsonb_typeof(request_payload_json) = 'object'
                        );
                END IF;
            END $$;
            """,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'chk_one_day_generation_jobs_profile_object'
                      AND conrelid = 'one_day_generation_jobs'::regclass
                ) THEN
                    ALTER TABLE one_day_generation_jobs
                        ADD CONSTRAINT chk_one_day_generation_jobs_profile_object
                        CHECK (profile_json IS NULL OR jsonb_typeof(profile_json) = 'object');
                END IF;
            END $$;
            """,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'chk_one_day_generation_jobs_recent_recipe_ids_array'
                      AND conrelid = 'one_day_generation_jobs'::regclass
                ) THEN
                    ALTER TABLE one_day_generation_jobs
                        ADD CONSTRAINT chk_one_day_generation_jobs_recent_recipe_ids_array
                        CHECK (jsonb_typeof(recent_recipe_ids_json) = 'array');
                END IF;
            END $$;
            """,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'chk_one_day_generation_jobs_worker_id_non_empty'
                      AND conrelid = 'one_day_generation_jobs'::regclass
                ) THEN
                    ALTER TABLE one_day_generation_jobs
                        ADD CONSTRAINT chk_one_day_generation_jobs_worker_id_non_empty
                        CHECK (worker_id IS NULL OR worker_id <> '');
                END IF;
            END $$;
            """,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'chk_one_day_generation_jobs_attempt_count_non_negative'
                      AND conrelid = 'one_day_generation_jobs'::regclass
                ) THEN
                    ALTER TABLE one_day_generation_jobs
                        ADD CONSTRAINT chk_one_day_generation_jobs_attempt_count_non_negative
                        CHECK (attempt_count >= 0);
                END IF;
            END $$;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_one_day_generation_jobs_queue_claim
                ON one_day_generation_jobs (
                    COALESCE(next_attempt_at, created_at),
                    created_at,
                    job_id
                )
                WHERE status = 'queued'
                  AND request_kind IS NOT NULL
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_one_day_generation_jobs_lease_reclaim
                ON one_day_generation_jobs(leased_until, created_at, job_id)
                WHERE status = 'running'
                  AND leased_until IS NOT NULL
                  AND request_kind IS NOT NULL
            """,
        ),
    ),
)


def run_one_day_generation_job_schema_migrations(cur: Any) -> None:
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
