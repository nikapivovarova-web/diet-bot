from __future__ import annotations

from collections import Counter

from diet_bot import (
    postgres_chat_state_migrations,
    postgres_entitlement_migrations,
    postgres_payment_migrations,
    postgres_weekly_pdf_job_migrations,
)


POSTGRES_MIGRATION_MODULES = (
    postgres_entitlement_migrations,
    postgres_payment_migrations,
    postgres_weekly_pdf_job_migrations,
    postgres_chat_state_migrations,
)


def test_postgres_migration_versions_are_globally_unique_and_ordered() -> None:
    migrations_by_module = {
        module.__name__: module.MIGRATIONS
        for module in POSTGRES_MIGRATION_MODULES
    }
    versions = [
        migration.version
        for migrations in migrations_by_module.values()
        for migration in migrations
    ]
    duplicate_versions = sorted(
        version
        for version, count in Counter(versions).items()
        if count > 1
    )

    assert duplicate_versions == []
    for module_name, migrations in migrations_by_module.items():
        module_versions = [migration.version for migration in migrations]
        assert module_versions == sorted(module_versions), module_name
