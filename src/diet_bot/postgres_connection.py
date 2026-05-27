from __future__ import annotations

import atexit
import re
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol


DEFAULT_POSTGRES_CONNECT_TIMEOUT = 5
DEFAULT_POSTGRES_CONNECT_ATTEMPTS = 3
DEFAULT_POSTGRES_RETRY_BASE_DELAY = 0.2
DEFAULT_POSTGRES_RETRY_MAX_DELAY = 1.0
DEFAULT_POSTGRES_POOL_MIN_SIZE = 1
DEFAULT_POSTGRES_POOL_MAX_SIZE = 4
DEFAULT_POSTGRES_POOL_TIMEOUT = 5.0

_URL_PASSWORD_RE = re.compile(
    r"(?P<scheme>postgres(?:ql)?://)(?P<user>[^:@/\s]+):(?P<password>[^@/\s]+)@",
    re.IGNORECASE,
)
_KEYWORD_PASSWORD_RE = re.compile(r"\b(?P<key>password|pass|sslpassword)=(?P<value>[^&\s]+)", re.IGNORECASE)


class PostgresConnectionError(RuntimeError):
    """Raised when a Postgres connection provider cannot lease a connection safely."""


class PostgresConnectionProvider(Protocol):
    dsn: str

    def connect(self) -> AbstractContextManager[Any]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class PostgresConnectionSettings:
    dsn: str
    connect_timeout: int = DEFAULT_POSTGRES_CONNECT_TIMEOUT
    connect_attempts: int = DEFAULT_POSTGRES_CONNECT_ATTEMPTS
    retry_base_delay: float = DEFAULT_POSTGRES_RETRY_BASE_DELAY
    retry_max_delay: float = DEFAULT_POSTGRES_RETRY_MAX_DELAY
    pool_enabled: bool = False
    pool_min_size: int = DEFAULT_POSTGRES_POOL_MIN_SIZE
    pool_max_size: int = DEFAULT_POSTGRES_POOL_MAX_SIZE
    pool_timeout: float = DEFAULT_POSTGRES_POOL_TIMEOUT


class DirectPostgresConnectionProvider:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = DEFAULT_POSTGRES_CONNECT_TIMEOUT,
        connect_attempts: int = DEFAULT_POSTGRES_CONNECT_ATTEMPTS,
        retry_base_delay: float = DEFAULT_POSTGRES_RETRY_BASE_DELAY,
        retry_max_delay: float = DEFAULT_POSTGRES_RETRY_MAX_DELAY,
    ) -> None:
        self.dsn = dsn
        self.connect_timeout = int(connect_timeout)
        self.connect_attempts = max(1, int(connect_attempts))
        self.retry_base_delay = float(retry_base_delay)
        self.retry_max_delay = float(retry_max_delay)

    @contextmanager
    def connect(self) -> Iterator[Any]:
        connection = self._open_connection()
        with connection as conn:
            yield conn

    def close(self) -> None:
        return None

    def _open_connection(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install PostgreSQL driver with `pip install psycopg[binary]`.") from exc

        last_error: Exception | None = None
        for attempt in range(1, self.connect_attempts + 1):
            try:
                return psycopg.connect(
                    self.dsn,
                    row_factory=dict_row,
                    connect_timeout=self.connect_timeout,
                )
            except psycopg.OperationalError as exc:
                last_error = exc
                if attempt >= self.connect_attempts:
                    break
                delay = min(self.retry_max_delay, self.retry_base_delay * (2 ** (attempt - 1)))
                time.sleep(delay)
        if last_error is not None:
            raise PostgresConnectionError(
                _connection_error_message(
                    "Could not connect to PostgreSQL",
                    dsn=self.dsn,
                    attempts=self.connect_attempts,
                    error=last_error,
                ),
            ) from None
        raise PostgresConnectionError("Could not connect to PostgreSQL.")


class PooledPostgresConnectionProvider:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int = DEFAULT_POSTGRES_CONNECT_TIMEOUT,
        pool_min_size: int = DEFAULT_POSTGRES_POOL_MIN_SIZE,
        pool_max_size: int = DEFAULT_POSTGRES_POOL_MAX_SIZE,
        pool_timeout: float = DEFAULT_POSTGRES_POOL_TIMEOUT,
        pool_factory: Callable[..., Any] | None = None,
        row_factory: Any | None = None,
    ) -> None:
        self.dsn = dsn
        self.connect_timeout = int(connect_timeout)
        self.pool_min_size = max(0, int(pool_min_size))
        self.pool_max_size = max(1, int(pool_max_size))
        if self.pool_max_size < self.pool_min_size:
            self.pool_max_size = self.pool_min_size or 1
        self.pool_timeout = float(pool_timeout)
        self._pool_factory = pool_factory
        self._row_factory = row_factory
        self._pool: Any | None = None
        self._closed = False
        self._lock = RLock()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        pool = self._ensure_pool()
        try:
            lease = pool.connection(timeout=self.pool_timeout)
            conn = lease.__enter__()
        except Exception as exc:
            raise PostgresConnectionError(
                _connection_error_message(
                    "Could not lease a PostgreSQL connection from the pool",
                    dsn=self.dsn,
                    attempts=1,
                    error=exc,
                ),
            ) from None

        try:
            yield conn
        except BaseException as exc:
            suppress = lease.__exit__(type(exc), exc, exc.__traceback__)
            if not suppress:
                raise
        else:
            lease.__exit__(None, None, None)

    def close(self) -> None:
        with self._lock:
            pool = self._pool
            self._pool = None
            already_closed = self._closed
            self._closed = True
        if pool is None or already_closed:
            return
        try:
            pool.close()
        except Exception as exc:
            raise PostgresConnectionError(
                _connection_error_message(
                    "Could not close PostgreSQL connection pool",
                    dsn=self.dsn,
                    attempts=1,
                    error=exc,
                ),
            ) from None

    def _ensure_pool(self) -> Any:
        with self._lock:
            if self._closed:
                raise PostgresConnectionError("PostgreSQL connection pool is closed.")
            if self._pool is not None:
                return self._pool

            pool_factory = self._pool_factory or _load_psycopg_pool_factory()
            row_factory = self._row_factory if self._row_factory is not None else _load_dict_row()
            try:
                pool = pool_factory(
                    conninfo=self.dsn,
                    kwargs={"row_factory": row_factory, "connect_timeout": self.connect_timeout},
                    min_size=self.pool_min_size,
                    max_size=self.pool_max_size,
                    open=False,
                )
                pool.open(wait=False)
            except Exception as exc:
                raise PostgresConnectionError(
                    _connection_error_message(
                        "Could not open PostgreSQL connection pool",
                        dsn=self.dsn,
                        attempts=1,
                        error=exc,
                    ),
                ) from None
            self._pool = pool
            return pool


def create_postgres_connection_provider(
    settings: PostgresConnectionSettings,
) -> PostgresConnectionProvider:
    if settings.pool_enabled:
        return PooledPostgresConnectionProvider(
            settings.dsn,
            connect_timeout=settings.connect_timeout,
            pool_min_size=settings.pool_min_size,
            pool_max_size=settings.pool_max_size,
            pool_timeout=settings.pool_timeout,
        )
    return DirectPostgresConnectionProvider(
        settings.dsn,
        connect_timeout=settings.connect_timeout,
        connect_attempts=settings.connect_attempts,
        retry_base_delay=settings.retry_base_delay,
        retry_max_delay=settings.retry_max_delay,
    )


def postgres_connection_settings_from_config(config: object) -> PostgresConnectionSettings:
    database_url = getattr(config, "database_url", None)
    if not database_url:
        raise RuntimeError("DIET_BOT_DATABASE_URL is required for postgres storage.")
    return PostgresConnectionSettings(
        dsn=str(database_url),
        connect_timeout=int(getattr(config, "postgres_connect_timeout", DEFAULT_POSTGRES_CONNECT_TIMEOUT)),
        pool_enabled=bool(getattr(config, "postgres_pool_enabled", False)),
        pool_min_size=int(getattr(config, "postgres_pool_min_size", DEFAULT_POSTGRES_POOL_MIN_SIZE)),
        pool_max_size=int(getattr(config, "postgres_pool_max_size", DEFAULT_POSTGRES_POOL_MAX_SIZE)),
        pool_timeout=float(getattr(config, "postgres_pool_timeout", DEFAULT_POSTGRES_POOL_TIMEOUT)),
    )


_SHARED_PROVIDER_LOCK = RLock()
_SHARED_PROVIDER: PostgresConnectionProvider | None = None
_SHARED_PROVIDER_SETTINGS: PostgresConnectionSettings | None = None


def get_shared_postgres_connection_provider(config: object) -> PostgresConnectionProvider:
    global _SHARED_PROVIDER, _SHARED_PROVIDER_SETTINGS
    settings = postgres_connection_settings_from_config(config)
    with _SHARED_PROVIDER_LOCK:
        if _SHARED_PROVIDER is not None and _SHARED_PROVIDER_SETTINGS == settings:
            return _SHARED_PROVIDER
        old_provider = _SHARED_PROVIDER
        provider = create_postgres_connection_provider(settings)
        _SHARED_PROVIDER = provider
        _SHARED_PROVIDER_SETTINGS = settings
    if old_provider is not None:
        old_provider.close()
    return provider


def close_shared_postgres_connection_provider() -> None:
    global _SHARED_PROVIDER, _SHARED_PROVIDER_SETTINGS
    with _SHARED_PROVIDER_LOCK:
        provider = _SHARED_PROVIDER
        _SHARED_PROVIDER = None
        _SHARED_PROVIDER_SETTINGS = None
    if provider is not None:
        provider.close()


def redact_postgres_dsn(dsn: str) -> str:
    return redact_postgres_text(str(dsn))


def redact_postgres_text(text: str, dsn: str | None = None) -> str:
    redacted = str(text)
    if dsn:
        redacted = redacted.replace(str(dsn), _redact_inline(str(dsn)))
    return _redact_inline(redacted)


def _redact_inline(text: str) -> str:
    redacted = _URL_PASSWORD_RE.sub(r"\g<scheme>\g<user>:***@", text)
    return _KEYWORD_PASSWORD_RE.sub(lambda match: f"{match.group('key')}=***", redacted)


def _connection_error_message(
    prefix: str,
    *,
    dsn: str,
    attempts: int,
    error: Exception,
) -> str:
    safe_error = redact_postgres_text(str(error), dsn=dsn)
    details = error.__class__.__name__
    if safe_error:
        details = f"{details}: {safe_error}"
    attempt_text = "attempt" if attempts == 1 else "attempts"
    return f"{prefix} using DSN {redact_postgres_dsn(dsn)} after {attempts} {attempt_text}: {details}"


def _load_psycopg_pool_factory() -> Callable[..., Any]:
    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "Install PostgreSQL pool support with `pip install 'psycopg[pool]'`.",
        ) from exc
    return ConnectionPool


def _load_dict_row() -> Any:
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Install PostgreSQL driver with `pip install psycopg[binary]`.") from exc
    return dict_row


atexit.register(close_shared_postgres_connection_provider)
