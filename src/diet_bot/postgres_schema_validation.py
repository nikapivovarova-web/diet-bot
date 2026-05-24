from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


SCHEMA_MIGRATIONS_COLUMNS = ("version", "description", "applied_at")


@dataclass(frozen=True)
class PostgresSchemaExpectation:
    component: str
    migration_versions: tuple[str, ...]
    table_columns: Mapping[str, tuple[str, ...]]
    indexes: tuple[str, ...]
    remediation: str
    constraints: tuple[str, ...] = ()


def validate_postgres_schema(
    cur: Any,
    expectation: PostgresSchemaExpectation,
    *,
    error_cls: type[Exception] = RuntimeError,
) -> None:
    expected_tables = set(expectation.table_columns)
    found_tables = _fetch_tables(cur, expected_tables)
    missing_tables = sorted(expected_tables - found_tables)
    if missing_tables:
        _fail(
            expectation,
            f"missing tables: {', '.join(missing_tables)}",
            error_cls=error_cls,
        )

    found_migrations = _fetch_migration_versions(cur, set(expectation.migration_versions))
    missing_migrations = sorted(set(expectation.migration_versions) - found_migrations)
    if missing_migrations:
        _fail(
            expectation,
            f"missing migration versions: {', '.join(missing_migrations)}",
            error_cls=error_cls,
        )

    found_columns = _fetch_columns(cur, expected_tables)
    missing_columns = _missing_columns(expectation.table_columns, found_columns)
    if missing_columns:
        _fail(
            expectation,
            f"missing columns: {', '.join(missing_columns)}",
            error_cls=error_cls,
        )

    expected_indexes = set(expectation.indexes)
    if expected_indexes:
        found_indexes = _fetch_indexes(cur, expected_indexes)
        missing_indexes = sorted(expected_indexes - found_indexes)
        if missing_indexes:
            _fail(
                expectation,
                f"missing indexes: {', '.join(missing_indexes)}",
                error_cls=error_cls,
            )

    expected_constraints = set(expectation.constraints)
    if expected_constraints:
        found_constraints = _fetch_constraints(cur, expected_constraints)
        missing_constraints = sorted(expected_constraints - found_constraints)
        if missing_constraints:
            _fail(
                expectation,
                f"missing constraints: {', '.join(missing_constraints)}",
                error_cls=error_cls,
            )


def _fetch_tables(cur: Any, expected_tables: set[str]) -> set[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        """,
        (sorted(expected_tables),),
    )
    return {str(row["table_name"]) for row in cur.fetchall()}


def _fetch_migration_versions(cur: Any, expected_versions: set[str]) -> set[str]:
    cur.execute(
        """
        SELECT version
        FROM schema_migrations
        WHERE version = ANY(%s)
        """,
        (sorted(expected_versions),),
    )
    return {str(row["version"]) for row in cur.fetchall()}


def _fetch_columns(cur: Any, expected_tables: set[str]) -> dict[str, set[str]]:
    cur.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        """,
        (sorted(expected_tables),),
    )
    found: dict[str, set[str]] = {table: set() for table in expected_tables}
    for row in cur.fetchall():
        found.setdefault(str(row["table_name"]), set()).add(str(row["column_name"]))
    return found


def _fetch_indexes(cur: Any, expected_indexes: set[str]) -> set[str]:
    cur.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = current_schema()
          AND indexname = ANY(%s)
        """,
        (sorted(expected_indexes),),
    )
    return {str(row["indexname"]) for row in cur.fetchall()}


def _fetch_constraints(cur: Any, expected_constraints: set[str]) -> set[str]:
    cur.execute(
        """
        SELECT conname
        FROM pg_constraint
        WHERE connamespace = current_schema()::regnamespace
          AND conname = ANY(%s)
        """,
        (sorted(expected_constraints),),
    )
    return {str(row["conname"]) for row in cur.fetchall()}


def _missing_columns(
    expected_columns: Mapping[str, tuple[str, ...]],
    found_columns: Mapping[str, set[str]],
) -> list[str]:
    missing: list[str] = []
    for table_name, columns in sorted(expected_columns.items()):
        found = found_columns.get(table_name, set())
        missing.extend(
            f"{table_name}.{column_name}"
            for column_name in columns
            if column_name not in found
        )
    return missing


def _fail(
    expectation: PostgresSchemaExpectation,
    detail: str,
    *,
    error_cls: type[Exception],
) -> None:
    raise error_cls(
        f"Postgres {expectation.component} schema is invalid: {detail}. "
        f"{expectation.remediation}",
    )
