from __future__ import annotations

import builtins
import sys
import types

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
