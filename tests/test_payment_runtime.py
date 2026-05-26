from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

import pytest

from diet_bot.runtime_config import load_runtime_config


def test_disabled_payments_do_not_create_payment_service_or_import_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    from diet_bot.payment_runtime import PaymentLedgerUnavailable, create_payment_service

    sys.modules.pop("diet_bot.postgres_payment_store", None)
    sys.modules.pop("psycopg", None)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith(("diet_bot.postgres_payment_store", "psycopg")):
            raise AssertionError(f"disabled payment runtime imported {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    config = load_runtime_config({})

    with pytest.raises(PaymentLedgerUnavailable, match="disabled"):
        create_payment_service(config)


def test_enabled_payments_require_postgres_backend_and_database_url() -> None:
    from diet_bot.payment_runtime import PaymentLedgerUnavailable, create_payment_service

    config = load_runtime_config({"DIET_BOT_PAYMENTS_ENABLED": "1"})

    with pytest.raises(PaymentLedgerUnavailable, match="Postgres"):
        create_payment_service(config)


def test_enabled_postgres_payment_runtime_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    from diet_bot.payment_runtime import create_payment_service

    created: list[tuple[str, int, int]] = []

    class FakePostgresPaymentStore:
        def __init__(self, dsn: str, *, connect_timeout: int = 5, connect_attempts: int = 3) -> None:
            created.append((dsn, connect_timeout, connect_attempts))

        def create_order(self, order):
            return order

    module = types.ModuleType("diet_bot.postgres_payment_store")
    module.PostgresPaymentStore = FakePostgresPaymentStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_payment_store", module)
    config = load_runtime_config(
        {
            "DIET_BOT_PAYMENTS_ENABLED": "1",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/test",
        },
    )

    service = create_payment_service(config)

    assert service is not None
    assert created == [("postgresql://user:secret@example/test", 5, 3)]


def test_disabled_payment_startup_validation_does_not_import_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diet_bot.payment_runtime import validate_payment_runtime_for_startup

    sys.modules.pop("diet_bot.postgres_payment_store", None)
    sys.modules.pop("psycopg", None)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith(("diet_bot.postgres_payment_store", "psycopg")):
            raise AssertionError(f"disabled payment startup validation imported {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    validate_payment_runtime_for_startup(load_runtime_config({}))


def test_enabled_payment_startup_validation_checks_postgres_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from diet_bot.payment_runtime import validate_payment_runtime_for_startup

    calls: list[tuple[str, str]] = []

    class FakePostgresPaymentStore:
        def __init__(self, dsn: str) -> None:
            calls.append(("init", dsn))

        def validate_schema(self) -> None:
            calls.append(("validate_schema", "called"))

    module = types.ModuleType("diet_bot.postgres_payment_store")
    module.PostgresPaymentStore = FakePostgresPaymentStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_payment_store", module)
    config = load_runtime_config(
        {
            "DIET_BOT_PAYMENTS_ENABLED": "1",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/test",
            "DIET_BOT_PAYMENT_RECOVERY_SPOOL": str(tmp_path / "payments.jsonl"),
        },
    )

    validate_payment_runtime_for_startup(config)

    assert calls == [
        ("init", "postgresql://user:secret@example/test"),
        ("validate_schema", "called"),
    ]


def test_enabled_payment_startup_validation_checks_spool_before_postgres(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import diet_bot.payment_runtime as payment_runtime
    from diet_bot.payment_runtime import validate_payment_runtime_for_startup

    calls: list[tuple[str, str]] = []

    def fake_validate_spool(path: Path) -> None:
        calls.append(("validate_spool", str(path)))

    class FakePostgresPaymentStore:
        def __init__(self, dsn: str) -> None:
            calls.append(("init", dsn))

        def validate_schema(self) -> None:
            calls.append(("validate_schema", "called"))

    module = types.ModuleType("diet_bot.postgres_payment_store")
    module.PostgresPaymentStore = FakePostgresPaymentStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_payment_store", module)
    monkeypatch.setattr(payment_runtime, "validate_payment_recovery_spool_ready", fake_validate_spool)
    config = load_runtime_config(
        {
            "DIET_BOT_PAYMENTS_ENABLED": "1",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/test",
            "DIET_BOT_PAYMENT_RECOVERY_SPOOL": str(tmp_path / "payments.jsonl"),
        },
    )

    validate_payment_runtime_for_startup(config)

    assert calls == [
        ("validate_spool", str(tmp_path / "payments.jsonl")),
        ("init", "postgresql://user:secret@example/test"),
        ("validate_schema", "called"),
    ]


def test_enabled_payment_startup_validation_accepts_absolute_spool_when_probe_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from diet_bot.payment_runtime import validate_payment_runtime_for_startup

    class FakePostgresPaymentStore:
        def __init__(self, _dsn: str) -> None:
            pass

        def validate_schema(self) -> None:
            pass

    module = types.ModuleType("diet_bot.postgres_payment_store")
    module.PostgresPaymentStore = FakePostgresPaymentStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_payment_store", module)
    spool_path = tmp_path / "payments.jsonl"
    config = load_runtime_config(
        {
            "DIET_BOT_PAYMENTS_ENABLED": "1",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/test",
            "DIET_BOT_PAYMENT_RECOVERY_SPOOL": str(spool_path),
        },
    )

    validate_payment_runtime_for_startup(config)

    assert not spool_path.exists()


def test_enabled_payment_startup_validation_wraps_schema_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from diet_bot.payment_runtime import PaymentLedgerUnavailable, validate_payment_runtime_for_startup

    class FakePostgresPaymentStore:
        def __init__(self, _dsn: str) -> None:
            pass

        def validate_schema(self) -> None:
            raise RuntimeError("missing payment_orders")

    module = types.ModuleType("diet_bot.postgres_payment_store")
    module.PostgresPaymentStore = FakePostgresPaymentStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_payment_store", module)
    config = load_runtime_config(
        {
            "DIET_BOT_PAYMENTS_ENABLED": "1",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/test",
            "DIET_BOT_PAYMENT_RECOVERY_SPOOL": str(tmp_path / "payments.jsonl"),
        },
    )

    with pytest.raises(PaymentLedgerUnavailable, match="Payment ledger schema is not ready") as exc_info:
        validate_payment_runtime_for_startup(config)

    assert exc_info.value.reason == "payment_ledger_schema_invalid"
