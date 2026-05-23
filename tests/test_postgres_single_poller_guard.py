from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[int, ...]) -> None:
        if self.connection.execute_error is not None:
            raise self.connection.execute_error
        self.connection.statements.append((sql, params))

    def fetchone(self) -> tuple[bool] | None:
        return self.connection.rows.pop(0) if self.connection.rows else None


class FakeConnection:
    def __init__(
        self,
        *,
        try_result: bool = True,
        execute_error: Exception | None = None,
    ) -> None:
        self.rows = [(try_result,)]
        self.execute_error = execute_error
        self.statements: list[tuple[str, tuple[int, ...]]] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _install_fake_psycopg(monkeypatch: pytest.MonkeyPatch, connection: FakeConnection) -> list[str]:
    connected_urls: list[str] = []

    def connect(database_url: str, **_kwargs: object) -> FakeConnection:
        connected_urls.append(database_url)
        return connection

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    return connected_urls


def test_acquire_success_calls_pg_try_advisory_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    from diet_bot.postgres_single_poller_guard import (
        POSTGRES_SINGLE_POLLER_LOCK_ID,
        PostgresSinglePollerGuard,
    )

    connection = FakeConnection(try_result=True)
    connected_urls = _install_fake_psycopg(monkeypatch, connection)

    guard = PostgresSinglePollerGuard("postgresql://user:secret@example/db").acquire()

    assert connected_urls == ["postgresql://user:secret@example/db"]
    assert connection.statements == [
        ("SELECT pg_try_advisory_lock(%s)", (POSTGRES_SINGLE_POLLER_LOCK_ID,)),
    ]
    assert connection.closed is False

    guard.close()


def test_unavailable_lock_raises_sanitized_already_active_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diet_bot.postgres_single_poller_guard import PostgresSinglePollerGuard

    connection = FakeConnection(try_result=False)
    _install_fake_psycopg(monkeypatch, connection)

    with pytest.raises(RuntimeError) as excinfo:
        PostgresSinglePollerGuard("postgresql://user:secret@example/db").acquire()

    message = str(excinfo.value)
    assert "another production poller is already active" in message
    assert "postgresql://" not in message
    assert "secret" not in message
    assert connection.closed is True


def test_close_releases_lock_and_closes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from diet_bot.postgres_single_poller_guard import (
        POSTGRES_SINGLE_POLLER_LOCK_ID,
        PostgresSinglePollerGuard,
    )

    connection = FakeConnection(try_result=True)
    _install_fake_psycopg(monkeypatch, connection)

    guard = PostgresSinglePollerGuard("postgresql://user:secret@example/db").acquire()
    guard.close()

    assert connection.statements == [
        ("SELECT pg_try_advisory_lock(%s)", (POSTGRES_SINGLE_POLLER_LOCK_ID,)),
        ("SELECT pg_advisory_unlock(%s)", (POSTGRES_SINGLE_POLLER_LOCK_ID,)),
    ]
    assert connection.closed is True


def test_database_exception_is_sanitized_without_dsn_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diet_bot.postgres_single_poller_guard import PostgresSinglePollerGuard

    secret_dsn = "postgresql://user:super-secret@example/db"

    def connect(_database_url: str, **_kwargs: object) -> FakeConnection:
        raise RuntimeError(f"could not connect to {secret_dsn}")

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))

    with pytest.raises(RuntimeError) as excinfo:
        PostgresSinglePollerGuard(secret_dsn).acquire()

    message = str(excinfo.value)
    assert "Could not acquire PostgreSQL single-poller startup guard" in message
    assert "postgresql://" not in message
    assert "super-secret" not in message
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
