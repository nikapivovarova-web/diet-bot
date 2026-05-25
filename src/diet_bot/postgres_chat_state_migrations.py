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
        version="202605250003",
        description="Create chat state tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS chat_profiles (
                chat_id BIGINT PRIMARY KEY,
                profile_json JSONB NOT NULL,
                profile_format_version INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                version BIGINT NOT NULL DEFAULT 1,
                CONSTRAINT chk_chat_profiles_profile_json_object CHECK (
                    jsonb_typeof(profile_json) = 'object'
                ),
                CONSTRAINT chk_chat_profiles_profile_format_version_positive CHECK (
                    profile_format_version >= 1
                ),
                CONSTRAINT chk_chat_profiles_version_positive CHECK (version >= 1)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_recipe_history (
                chat_id BIGINT PRIMARY KEY,
                recipe_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                recipe_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                version BIGINT NOT NULL DEFAULT 1,
                CONSTRAINT chk_chat_recipe_history_recipe_ids_array CHECK (
                    jsonb_typeof(recipe_ids) = 'array'
                ),
                CONSTRAINT chk_chat_recipe_history_recipe_keys_array CHECK (
                    jsonb_typeof(recipe_keys) = 'array'
                ),
                CONSTRAINT chk_chat_recipe_history_version_positive CHECK (version >= 1)
            )
            """,
        ),
    ),
    PostgresMigration(
        version="202605250004",
        description="Create chat state JSON import audit table",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS chat_state_json_import_runs (
                migration_id TEXT PRIMARY KEY,
                source_fingerprint TEXT NOT NULL,
                source_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'started',
                started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ,
                CONSTRAINT chk_chat_state_json_import_runs_status CHECK (
                    status IN ('started', 'applied', 'failed')
                )
            )
            """,
        ),
    ),
)


def run_chat_state_schema_migrations(cur: Any) -> None:
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
