from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest


def test_pyproject_declares_postgres_integration_marker() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    markers = data["tool"]["pytest"]["ini_options"]["markers"]
    assert any(marker.startswith("postgres_integration:") for marker in markers)


def test_conftest_registers_require_postgres_option() -> None:
    text = Path("tests/conftest.py").read_text(encoding="utf-8")
    assert "--require-postgres" in text
    assert "postgres_integration" in text
    assert "DIET_BOT_TEST_DATABASE_URL" in text
    assert "UsageError" in text


@pytest.mark.postgres_integration
def test_postgres_integration_lane_requires_database_url() -> None:
    assert os.getenv("DIET_BOT_TEST_DATABASE_URL"), (
        "DIET_BOT_TEST_DATABASE_URL must be set when running PostgreSQL integration tests"
    )
