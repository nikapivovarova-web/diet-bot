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
