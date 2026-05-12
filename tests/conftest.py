from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-postgres",
        action="store_true",
        default=False,
        help="Run PostgreSQL integration tests instead of skip-marking them.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    postgres_items = [item for item in items if "postgres_integration" in item.keywords]
    if not postgres_items:
        return

    if config.getoption("--require-postgres"):
        if not os.getenv("DIET_BOT_TEST_DATABASE_URL"):
            raise pytest.UsageError(
                "--require-postgres requires DIET_BOT_TEST_DATABASE_URL to point at a test database"
            )
        return

    skip_postgres = pytest.mark.skip(
        reason="requires --require-postgres and DIET_BOT_TEST_DATABASE_URL"
    )
    for item in postgres_items:
        item.add_marker(skip_postgres)
