from __future__ import annotations

from contextlib import suppress
from typing import Final


POSTGRES_SINGLE_POLLER_LOCK_ID: Final = 894_823_691_245_117_031
_ALREADY_ACTIVE_ERROR = "another production poller is already active."
_STARTUP_GUARD_ERROR = "Could not acquire PostgreSQL single-poller startup guard."


class PostgresSinglePollerGuard:
    def __init__(self, database_url: str, *, lock_id: int = POSTGRES_SINGLE_POLLER_LOCK_ID) -> None:
        self._database_url = database_url
        self._lock_id = lock_id
        self._connection = None
        self._acquired = False

    def acquire(self) -> PostgresSinglePollerGuard:
        try:
            import psycopg
        except Exception:
            raise RuntimeError(_STARTUP_GUARD_ERROR) from None

        connection = None
        try:
            connection = psycopg.connect(self._database_url, autocommit=True)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (self._lock_id,))
                row = cursor.fetchone()
        except Exception:
            if connection is not None:
                with suppress(Exception):
                    connection.close()
            raise RuntimeError(_STARTUP_GUARD_ERROR) from None

        if not row or row[0] is not True:
            with suppress(Exception):
                connection.close()
            raise RuntimeError(_ALREADY_ACTIVE_ERROR)

        self._connection = connection
        self._acquired = True
        return self

    def close(self) -> None:
        connection = self._connection
        if connection is None:
            return

        self._connection = None
        acquired = self._acquired
        self._acquired = False
        try:
            if acquired:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (self._lock_id,))
        finally:
            connection.close()
