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
        version="202605230001",
        description="Create weekly PDF job tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS weekly_pdf_jobs (
                job_id UUID PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                refund_status TEXT NOT NULL DEFAULT 'not_required',
                consumption_source TEXT,
                stale_after TIMESTAMPTZ NOT NULL,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                failure_reason TEXT,
                send_started_at TIMESTAMPTZ,
                delivered_at TIMESTAMPTZ,
                finalization_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                started_at TIMESTAMPTZ,
                heartbeat_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                CONSTRAINT chk_weekly_pdf_jobs_idempotency_key_non_empty CHECK (idempotency_key <> ''),
                CONSTRAINT chk_weekly_pdf_jobs_status CHECK (
                    status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
                ),
                CONSTRAINT chk_weekly_pdf_jobs_refund_status CHECK (
                    refund_status IN ('not_required', 'pending', 'refunded')
                ),
                CONSTRAINT chk_weekly_pdf_jobs_consumption_source CHECK (
                    consumption_source IS NULL
                    OR consumption_source IN ('monthly', 'extra', 'free_trial', 'test_access')
                )
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly_pdf_jobs_active_chat_unique
                ON weekly_pdf_jobs(chat_id)
                WHERE status IN ('queued', 'running')
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly_pdf_jobs_idempotency_key_unique
                ON weekly_pdf_jobs(idempotency_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_weekly_pdf_jobs_stale
                ON weekly_pdf_jobs(stale_after)
                WHERE status IN ('queued', 'running')
            """,
        ),
    ),
    PostgresMigration(
        version="202605250001",
        description="Track delivered weekly PDF jobs",
        statements=(
            """
            ALTER TABLE weekly_pdf_jobs
            ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ
            """,
            """
            ALTER TABLE weekly_pdf_jobs
            ADD COLUMN IF NOT EXISTS finalization_error TEXT
            """,
        ),
    ),
    PostgresMigration(
        version="202605250002",
        description="Track weekly PDF send starts",
        statements=(
            """
            ALTER TABLE weekly_pdf_jobs
            ADD COLUMN IF NOT EXISTS send_started_at TIMESTAMPTZ
            """,
        ),
    ),
    PostgresMigration(
        version="202605260001",
        description="Track weekly PDF delivery review state",
        statements=(
            """
            ALTER TABLE weekly_pdf_jobs
            ADD COLUMN IF NOT EXISTS delivery_status TEXT
            """,
            """
            ALTER TABLE weekly_pdf_jobs
            ADD COLUMN IF NOT EXISTS requires_manual_review BOOLEAN NOT NULL DEFAULT false
            """,
            """
            ALTER TABLE weekly_pdf_jobs
            ADD COLUMN IF NOT EXISTS manual_review_reason TEXT
            """,
            """
            ALTER TABLE weekly_pdf_jobs
            ADD COLUMN IF NOT EXISTS manual_reviewed_at TIMESTAMPTZ
            """,
            """
            ALTER TABLE weekly_pdf_jobs
            ADD COLUMN IF NOT EXISTS manual_review_resolution TEXT
            """,
            """
            UPDATE weekly_pdf_jobs
            SET delivery_status = 'delivered',
                requires_manual_review = false,
                manual_review_reason = NULL,
                manual_reviewed_at = NULL,
                manual_review_resolution = NULL
            WHERE delivered_at IS NOT NULL
            """,
            """
            UPDATE weekly_pdf_jobs
            SET delivery_status = 'unknown',
                requires_manual_review = true,
                manual_review_reason = COALESCE(NULLIF(finalization_error, ''), 'send_started_without_delivery_confirmation')
            WHERE send_started_at IS NOT NULL
              AND delivered_at IS NULL
              AND status = 'succeeded'
              AND finalization_error IS NOT NULL
            """,
            """
            UPDATE weekly_pdf_jobs
            SET delivery_status = 'send_started',
                requires_manual_review = false,
                manual_review_reason = NULL
            WHERE delivery_status IS NULL
              AND send_started_at IS NOT NULL
              AND delivered_at IS NULL
              AND status IN ('queued', 'running')
            """,
            """
            UPDATE weekly_pdf_jobs
            SET delivery_status = 'not_started',
                requires_manual_review = false,
                manual_review_reason = NULL
            WHERE delivery_status IS NULL
            """,
            """
            ALTER TABLE weekly_pdf_jobs
            ALTER COLUMN delivery_status SET DEFAULT 'not_started'
            """,
            """
            ALTER TABLE weekly_pdf_jobs
            ALTER COLUMN delivery_status SET NOT NULL
            """,
            """
            DO $$
            BEGIN
                ALTER TABLE weekly_pdf_jobs
                ADD CONSTRAINT chk_weekly_pdf_jobs_delivery_status CHECK (
                    delivery_status IN ('not_started', 'send_started', 'delivered', 'unknown')
                );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """,
            """
            DO $$
            BEGIN
                ALTER TABLE weekly_pdf_jobs
                ADD CONSTRAINT chk_weekly_pdf_jobs_manual_review_reason CHECK (
                    requires_manual_review = false OR manual_review_reason IS NOT NULL
                );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """,
            """
            DO $$
            BEGIN
                ALTER TABLE weekly_pdf_jobs
                ADD CONSTRAINT chk_weekly_pdf_jobs_unknown_requires_review CHECK (
                    delivery_status <> 'unknown' OR requires_manual_review = true
                );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """,
            """
            DO $$
            BEGIN
                ALTER TABLE weekly_pdf_jobs
                ADD CONSTRAINT chk_weekly_pdf_jobs_delivered_without_review CHECK (
                    delivery_status <> 'delivered' OR requires_manual_review = false
                );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """,
        ),
    ),
)


def run_weekly_pdf_job_schema_migrations(cur: Any) -> None:
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
