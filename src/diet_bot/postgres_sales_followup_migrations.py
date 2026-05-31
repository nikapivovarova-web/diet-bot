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
        version="202605310001",
        description="Create sales follow-up storage tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS sales_followup_chains (
                chain_id UUID PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                campaign_key TEXT NOT NULL,
                trigger_kind TEXT NOT NULL,
                trigger_job_id UUID,
                trigger_idempotency_key TEXT NOT NULL,
                triggered_at TIMESTAMPTZ NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                cancel_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                cancelled_at TIMESTAMPTZ,
                CONSTRAINT chk_sales_followup_chains_campaign_key_non_empty CHECK (campaign_key <> ''),
                CONSTRAINT chk_sales_followup_chains_trigger_kind_non_empty CHECK (trigger_kind <> ''),
                CONSTRAINT chk_sales_followup_chains_trigger_idempotency_key_non_empty CHECK (
                    trigger_idempotency_key <> ''
                ),
                CONSTRAINT chk_sales_followup_chains_status CHECK (
                    status IN ('active', 'completed', 'cancelled', 'opted_out', 'suppressed')
                )
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_followup_chains_trigger_idempotency_key_unique
                ON sales_followup_chains(trigger_idempotency_key)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_followup_chains_active_chat_campaign_unique
                ON sales_followup_chains(chat_id, campaign_key)
                WHERE status = 'active'
            """,
            """
            CREATE TABLE IF NOT EXISTS sales_followup_jobs (
                job_id UUID PRIMARY KEY,
                chain_id UUID NOT NULL REFERENCES sales_followup_chains(chain_id) ON DELETE CASCADE,
                chat_id BIGINT NOT NULL,
                campaign_key TEXT NOT NULL,
                step_key TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                scheduled_at TIMESTAMPTZ NOT NULL,
                next_attempt_at TIMESTAMPTZ NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                button_set_key TEXT NOT NULL DEFAULT 'sales_followup_default',
                send_started_at TIMESTAMPTZ,
                sent_at TIMESTAMPTZ,
                telegram_message_id BIGINT,
                skipped_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                skip_reason TEXT,
                failure_reason TEXT,
                last_error TEXT,
                worker_id TEXT,
                leased_until TIMESTAMPTZ,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                heartbeat_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT chk_sales_followup_jobs_campaign_key_non_empty CHECK (campaign_key <> ''),
                CONSTRAINT chk_sales_followup_jobs_step_key_non_empty CHECK (step_key <> ''),
                CONSTRAINT chk_sales_followup_jobs_step_index_positive CHECK (step_index >= 1),
                CONSTRAINT chk_sales_followup_jobs_status CHECK (
                    status IN ('queued', 'running', 'sent', 'skipped', 'cancelled', 'failed', 'unknown')
                ),
                CONSTRAINT chk_sales_followup_jobs_payload_object CHECK (jsonb_typeof(payload_json) = 'object'),
                CONSTRAINT chk_sales_followup_jobs_button_set_key_non_empty CHECK (button_set_key <> ''),
                CONSTRAINT chk_sales_followup_jobs_worker_id_non_empty CHECK (worker_id IS NULL OR worker_id <> ''),
                CONSTRAINT chk_sales_followup_jobs_attempt_count_non_negative CHECK (attempt_count >= 0)
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_followup_jobs_chain_step_unique
                ON sales_followup_jobs(chain_id, step_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_sales_followup_jobs_queue_claim
                ON sales_followup_jobs(next_attempt_at, scheduled_at, job_id)
                WHERE status = 'queued'
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_sales_followup_jobs_lease_reclaim
                ON sales_followup_jobs(leased_until, job_id)
                WHERE status = 'running'
                  AND leased_until IS NOT NULL
            """,
            """
            CREATE TABLE IF NOT EXISTS sales_followup_preferences (
                chat_id BIGINT PRIMARY KEY,
                opted_out_at TIMESTAMPTZ,
                opt_out_source TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT chk_sales_followup_preferences_opt_out_source_non_empty CHECK (
                    opt_out_source IS NULL OR opt_out_source <> ''
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sales_followup_campaigns (
                campaign_key TEXT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT false,
                version TEXT NOT NULL,
                disabled_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT chk_sales_followup_campaigns_campaign_key_non_empty CHECK (campaign_key <> ''),
                CONSTRAINT chk_sales_followup_campaigns_version_non_empty CHECK (version <> ''),
                CONSTRAINT chk_sales_followup_campaigns_disabled_reason_non_empty CHECK (
                    disabled_reason IS NULL OR disabled_reason <> ''
                )
            )
            """,
        ),
    ),
)


def run_sales_followup_schema_migrations(cur: Any) -> None:
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
