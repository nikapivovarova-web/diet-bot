from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest


class FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((query, params))


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1


class FakeConnectionContext:
    def __init__(self, pool: "FakeConnectionPool") -> None:
        self.pool = pool
        self.conn = FakeConnection()

    def __enter__(self) -> FakeConnection:
        self.pool.checked_out += 1
        return self.conn

    def __exit__(self, *_args: object) -> None:
        self.pool.returned += 1
        return None


class FakeConnectionPool:
    instances: list["FakeConnectionPool"] = []

    def __init__(
        self,
        conninfo: str,
        *,
        min_size: int,
        max_size: int,
        kwargs: dict[str, object],
        configure: Any,
        open: bool,
    ) -> None:
        self.conninfo = conninfo
        self.min_size = min_size
        self.max_size = max_size
        self.kwargs = kwargs
        self.configure = configure
        self.open_arg = open
        self.open_calls = 0
        self.closed = False
        self.checked_out = 0
        self.returned = 0
        FakeConnectionPool.instances.append(self)

    def open(self, *, wait: bool, timeout: float) -> None:
        self.open_calls += 1
        self.open_wait = wait
        self.open_timeout = timeout
        conn = FakeConnection()
        self.configure(conn)
        self.configured_connection = conn

    def connection(self) -> FakeConnectionContext:
        return FakeConnectionContext(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_pool(monkeypatch: pytest.MonkeyPatch) -> type[FakeConnectionPool]:
    FakeConnectionPool.instances = []
    monkeypatch.setitem(
        sys.modules,
        "psycopg_pool",
        SimpleNamespace(ConnectionPool=FakeConnectionPool),
    )
    return FakeConnectionPool


def test_postgres_store_initializes_pool_once_for_repeated_initialize(
    monkeypatch: pytest.MonkeyPatch,
    fake_pool: type[FakeConnectionPool],
) -> None:
    from diet_bot import postgres_store

    migrations: list[FakeCursor] = []
    monkeypatch.setattr(postgres_store, "run_postgres_migrations", migrations.append)

    store = postgres_store.PostgresDietBotStore(
        "postgresql://unit-test",
        pool_max_size=7,
        statement_timeout_ms=1234,
        lock_timeout_ms=234,
    )

    store.initialize()
    store.initialize()

    assert len(fake_pool.instances) == 1
    pool = fake_pool.instances[0]
    assert pool.conninfo == "postgresql://unit-test"
    assert pool.min_size == 1
    assert pool.max_size == 7
    assert pool.open_arg is False
    assert pool.open_calls == 1
    assert pool.open_wait is True
    assert pool.kwargs["connect_timeout"] == 5
    assert "row_factory" in pool.kwargs
    assert len(migrations) == 2
    assert pool.configured_connection.commits == 1
    assert pool.configured_connection.cursor_obj.executed == [
        ("SELECT set_config('statement_timeout', %s, false)", ("1234ms",)),
        ("SELECT set_config('lock_timeout', %s, false)", ("234ms",)),
    ]


def test_postgres_store_connect_checks_out_from_pool(
    monkeypatch: pytest.MonkeyPatch,
    fake_pool: type[FakeConnectionPool],
) -> None:
    from diet_bot import postgres_store

    monkeypatch.setattr(postgres_store, "run_postgres_migrations", lambda _cur: None)
    store = postgres_store.PostgresDietBotStore("postgresql://unit-test")
    store.initialize()

    with store._connect() as conn:
        assert isinstance(conn, FakeConnection)

    pool = fake_pool.instances[0]
    assert pool.checked_out == 2
    assert pool.returned == 2


def test_postgres_store_close_closes_pool(
    monkeypatch: pytest.MonkeyPatch,
    fake_pool: type[FakeConnectionPool],
) -> None:
    from diet_bot import postgres_store

    monkeypatch.setattr(postgres_store, "run_postgres_migrations", lambda _cur: None)
    store = postgres_store.PostgresDietBotStore("postgresql://unit-test")
    store.initialize()

    store.close()
    store.close()

    assert fake_pool.instances[0].closed is True


def test_postgres_store_closes_new_pool_when_initialize_fails(
    monkeypatch: pytest.MonkeyPatch,
    fake_pool: type[FakeConnectionPool],
) -> None:
    from diet_bot import postgres_store

    def fail_migration(_cur: FakeCursor) -> None:
        raise RuntimeError("migration failed")

    monkeypatch.setattr(postgres_store, "run_postgres_migrations", fail_migration)
    store = postgres_store.PostgresDietBotStore("postgresql://unit-test")

    with pytest.raises(RuntimeError, match="migration failed"):
        store.initialize()

    assert fake_pool.instances[0].closed is True
