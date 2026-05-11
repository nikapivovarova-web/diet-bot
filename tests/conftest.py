import os

import pytest


os.environ.setdefault("DIET_BOT_ALLOW_JSON_STORAGE", "1")


def pytest_addoption(parser):
    parser.addoption(
        "--require-postgres",
        action="store_true",
        default=False,
        help="Fail instead of skipping PostgreSQL integration tests when DIET_BOT_TEST_DATABASE_URL is missing.",
    )


def pytest_runtest_setup(item):
    if "postgres_integration" not in item.keywords:
        return
    if os.getenv("DIET_BOT_TEST_DATABASE_URL"):
        return
    if item.config.getoption("--require-postgres") or os.getenv("DIET_BOT_REQUIRE_POSTGRES_TESTS") == "1":
        pytest.fail(
            "DIET_BOT_TEST_DATABASE_URL is required for release-blocking PostgreSQL integration tests.",
            pytrace=False,
        )
    pytest.skip("Set DIET_BOT_TEST_DATABASE_URL to run PostgreSQL integration tests.")
