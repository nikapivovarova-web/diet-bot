from __future__ import annotations

import pytest

from diet_bot.postgres_schema_validation import (
    PostgresSchemaExpectation,
    validate_postgres_schema,
)


def test_validate_postgres_schema_accepts_complete_schema() -> None:
    cursor = SchemaCursor(
        tables={"schema_migrations", "orders"},
        columns={
            "schema_migrations": {"version", "description", "applied_at"},
            "orders": {"order_id", "amount"},
        },
        indexes={"idx_orders_amount"},
        migrations={"202605240001"},
    )

    validate_postgres_schema(cursor, _expectation())


def test_validate_postgres_schema_rejects_missing_migration_version() -> None:
    cursor = SchemaCursor(
        tables={"schema_migrations", "orders"},
        columns={
            "schema_migrations": {"version", "description", "applied_at"},
            "orders": {"order_id", "amount"},
        },
        indexes={"idx_orders_amount"},
        migrations=set(),
    )

    with pytest.raises(RuntimeError, match="missing migration versions.*202605240001"):
        validate_postgres_schema(cursor, _expectation())


def test_validate_postgres_schema_rejects_missing_column() -> None:
    cursor = SchemaCursor(
        tables={"schema_migrations", "orders"},
        columns={
            "schema_migrations": {"version", "description", "applied_at"},
            "orders": {"order_id"},
        },
        indexes={"idx_orders_amount"},
        migrations={"202605240001"},
    )

    with pytest.raises(RuntimeError, match=r"missing columns.*orders\.amount"):
        validate_postgres_schema(cursor, _expectation())


def test_validate_postgres_schema_rejects_missing_index() -> None:
    cursor = SchemaCursor(
        tables={"schema_migrations", "orders"},
        columns={
            "schema_migrations": {"version", "description", "applied_at"},
            "orders": {"order_id", "amount"},
        },
        indexes=set(),
        migrations={"202605240001"},
    )

    with pytest.raises(RuntimeError, match="missing indexes.*idx_orders_amount"):
        validate_postgres_schema(cursor, _expectation())


def _expectation() -> PostgresSchemaExpectation:
    return PostgresSchemaExpectation(
        component="test schema",
        migration_versions=("202605240001",),
        table_columns={
            "schema_migrations": ("version", "description", "applied_at"),
            "orders": ("order_id", "amount"),
        },
        indexes=("idx_orders_amount",),
        remediation="run test migrations",
    )


class SchemaCursor:
    def __init__(
        self,
        *,
        tables: set[str],
        columns: dict[str, set[str]],
        indexes: set[str],
        migrations: set[str],
    ) -> None:
        self.tables = tables
        self.columns = columns
        self.indexes = indexes
        self.migrations = migrations
        self._rows: list[dict[str, str]] = []

    def execute(self, query: object, params: object | None = None) -> None:
        normalized = " ".join(str(query).split())
        values = set(params[0]) if params else set()
        if "FROM information_schema.tables" in normalized:
            self._rows = [{"table_name": table} for table in sorted(self.tables & values)]
            return
        if "FROM schema_migrations" in normalized:
            self._rows = [{"version": version} for version in sorted(self.migrations & values)]
            return
        if "FROM information_schema.columns" in normalized:
            rows: list[dict[str, str]] = []
            for table in sorted(values):
                rows.extend(
                    {"table_name": table, "column_name": column}
                    for column in sorted(self.columns.get(table, set()))
                )
            self._rows = rows
            return
        if "FROM pg_indexes" in normalized:
            self._rows = [{"indexname": index} for index in sorted(self.indexes & values)]
            return
        raise AssertionError(f"unexpected query: {query}")

    def fetchall(self) -> list[dict[str, str]]:
        return list(self._rows)
