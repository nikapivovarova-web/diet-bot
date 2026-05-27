from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from typing import Any

import pytest

from diet_bot.postgres_chat_state_store import PostgresChatStateStore
from diet_bot.postgres_entitlement_store import PostgresEntitlementStore
from diet_bot.postgres_one_day_generation_job_store import PostgresOneDayGenerationJobStore
from diet_bot.postgres_payment_store import PostgresPaymentStore
from diet_bot.postgres_weekly_pdf_job_store import PostgresWeeklyPdfJobStore
from diet_bot.runtime_config import load_runtime_config


SECRET_DSN = "postgresql://db_user:super-secret-password@db.example.com:5432/diet_bot"


def test_direct_provider_opens_psycopg_connection_with_redacted_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diet_bot.postgres_connection import (
        DirectPostgresConnectionProvider,
        PostgresConnectionError,
    )

    class FakeOperationalError(Exception):
        pass

    fake_psycopg = types.ModuleType("psycopg")
    fake_rows = types.ModuleType("psycopg.rows")
    fake_rows.dict_row = object()

    def fail_connect(*args: Any, **kwargs: Any) -> Any:
        raise FakeOperationalError(f"could not connect with {SECRET_DSN}")

    fake_psycopg.connect = fail_connect
    fake_psycopg.OperationalError = FakeOperationalError
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", fake_rows)

    provider = DirectPostgresConnectionProvider(
        SECRET_DSN,
        connect_timeout=1,
        connect_attempts=1,
    )

    with pytest.raises(PostgresConnectionError) as exc_info:
        with provider.connect():
            pass

    message = str(exc_info.value)
    assert "super-secret-password" not in message
    assert SECRET_DSN not in message
    assert "postgresql://db_user:***@db.example.com:5432/diet_bot" in message


def test_direct_provider_leases_direct_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from diet_bot.postgres_connection import DirectPostgresConnectionProvider

    calls: list[dict[str, Any]] = []
    fake_connection = FakeConnection()
    fake_psycopg = types.ModuleType("psycopg")
    fake_rows = types.ModuleType("psycopg.rows")
    fake_rows.dict_row = object()

    class FakeOperationalError(Exception):
        pass

    def connect(dsn: str, **kwargs: Any) -> FakeConnection:
        calls.append({"dsn": dsn, **kwargs})
        return fake_connection

    fake_psycopg.connect = connect
    fake_psycopg.OperationalError = FakeOperationalError
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", fake_rows)

    provider = DirectPostgresConnectionProvider(
        SECRET_DSN,
        connect_timeout=7,
        connect_attempts=1,
    )

    with provider.connect() as connection:
        assert connection is fake_connection

    assert calls == [
        {
            "dsn": SECRET_DSN,
            "row_factory": fake_rows.dict_row,
            "connect_timeout": 7,
        },
    ]
    assert fake_connection.enter_count == 1
    assert fake_connection.exit_count == 1


def test_pooled_provider_leases_and_returns_connections_through_fake_pool() -> None:
    from diet_bot.postgres_connection import PooledPostgresConnectionProvider

    fake_pool = FakePool(leased_connection=FakeConnection())
    created: list[dict[str, Any]] = []

    def pool_factory(**kwargs: Any) -> FakePool:
        created.append(kwargs)
        return fake_pool

    provider = PooledPostgresConnectionProvider(
        SECRET_DSN,
        connect_timeout=3,
        pool_min_size=1,
        pool_max_size=4,
        pool_timeout=2.5,
        pool_factory=pool_factory,
        row_factory="dict-row",
    )

    with provider.connect() as connection:
        assert connection is fake_pool.leased_connection
        assert fake_pool.checked_out == 1

    assert fake_pool.checked_out == 0
    assert fake_pool.open_calls == 1
    assert fake_pool.connection_timeouts == [2.5]
    assert created == [
        {
            "conninfo": SECRET_DSN,
            "kwargs": {"row_factory": "dict-row", "connect_timeout": 3},
            "min_size": 1,
            "max_size": 4,
            "open": False,
        },
    ]


def test_pooled_provider_close_is_idempotent() -> None:
    from diet_bot.postgres_connection import PooledPostgresConnectionProvider

    fake_pool = FakePool(leased_connection=FakeConnection())
    provider = PooledPostgresConnectionProvider(
        SECRET_DSN,
        pool_factory=lambda **_: fake_pool,
        row_factory="dict-row",
    )

    with provider.connect():
        pass

    provider.close()
    provider.close()

    assert fake_pool.close_calls == 1


def test_pooled_provider_redacts_full_dsn_from_pool_errors() -> None:
    from diet_bot.postgres_connection import (
        PooledPostgresConnectionProvider,
        PostgresConnectionError,
    )

    fake_pool = FakePool(leased_connection=FakeConnection(), failure=RuntimeError(f"failed {SECRET_DSN}"))
    provider = PooledPostgresConnectionProvider(
        SECRET_DSN,
        pool_factory=lambda **_: fake_pool,
        row_factory="dict-row",
    )

    with pytest.raises(PostgresConnectionError) as exc_info:
        with provider.connect():
            pass

    message = str(exc_info.value)
    assert "super-secret-password" not in message
    assert SECRET_DSN not in message
    assert "postgresql://db_user:***@db.example.com:5432/diet_bot" in message


@pytest.mark.parametrize(
    "store_cls",
    [
        PostgresPaymentStore,
        PostgresChatStateStore,
        PostgresEntitlementStore,
        PostgresWeeklyPdfJobStore,
        PostgresOneDayGenerationJobStore,
    ],
)
def test_runtime_stores_use_injected_connection_provider(store_cls: type[Any]) -> None:
    provider = FakeProvider(FakeConnection())
    store = store_cls(SECRET_DSN, connection_provider=provider)

    with store._connect() as connection:
        assert connection is provider.connection

    assert provider.connect_calls == 1


def test_runtime_factories_wire_stores_to_shared_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import diet_bot.postgres_connection as postgres_connection
    from diet_bot.chat_state_runtime import create_chat_state_store
    from diet_bot.entitlement_runtime import create_entitlement_store
    from diet_bot.one_day_generation_job_runtime import _create_postgres_one_day_generation_job_store
    from diet_bot.payment_runtime import create_payment_store
    from diet_bot.weekly_pdf_job_runtime import _create_postgres_weekly_pdf_job_store

    provider = FakeProvider(FakeConnection())
    monkeypatch.setattr(
        postgres_connection,
        "get_shared_postgres_connection_provider",
        lambda _config: provider,
    )
    config = load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": SECRET_DSN,
            "DIET_BOT_PAYMENTS_ENABLED": "1",
        },
    )

    stores = [
        create_chat_state_store(config),
        create_entitlement_store(config),
        _create_postgres_weekly_pdf_job_store(config),
        _create_postgres_one_day_generation_job_store(config),
        create_payment_store(config),
    ]

    assert all(getattr(store, "_connection_provider") is provider for store in stores)


class FakeProvider:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.connect_calls = 0

    @contextmanager
    def connect(self):
        self.connect_calls += 1
        yield self.connection

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0

    def __enter__(self) -> "FakeConnection":
        self.enter_count += 1
        return self

    def __exit__(self, *args: Any) -> None:
        self.exit_count += 1


class FakePool:
    def __init__(self, *, leased_connection: FakeConnection, failure: Exception | None = None) -> None:
        self.leased_connection = leased_connection
        self.failure = failure
        self.open_calls = 0
        self.close_calls = 0
        self.checked_out = 0
        self.connection_timeouts: list[float | None] = []

    def open(self, *, wait: bool = False) -> None:
        assert wait is False
        self.open_calls += 1

    def connection(self, *, timeout: float | None = None):
        self.connection_timeouts.append(timeout)
        return FakePoolLease(self)

    def close(self) -> None:
        self.close_calls += 1


class FakePoolLease:
    def __init__(self, pool: FakePool) -> None:
        self.pool = pool

    def __enter__(self) -> FakeConnection:
        if self.pool.failure is not None:
            raise self.pool.failure
        self.pool.checked_out += 1
        return self.pool.leased_connection

    def __exit__(self, *args: Any) -> None:
        self.pool.checked_out -= 1
