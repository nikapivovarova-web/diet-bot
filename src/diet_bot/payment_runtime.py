from __future__ import annotations

from .payment_service import PaymentService
from .runtime_config import RuntimeConfig, load_runtime_config


class PaymentLedgerUnavailable(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def create_payment_service(config: RuntimeConfig | None = None) -> PaymentService:
    return PaymentService(create_payment_store(config))


def create_payment_store(config: RuntimeConfig | None = None):
    runtime_config = load_runtime_config() if config is None else config
    if not runtime_config.payments_enabled:
        raise PaymentLedgerUnavailable("payments_disabled", "Payment ledger is disabled.")
    if runtime_config.storage_backend != "postgres":
        raise PaymentLedgerUnavailable(
            "payment_ledger_requires_postgres",
            "Payment ledger requires Postgres storage when payments are enabled.",
        )
    if not runtime_config.database_url:
        raise PaymentLedgerUnavailable(
            "payment_ledger_requires_database_url",
            "DIET_BOT_DATABASE_URL is required when payments are enabled.",
        )

    from .postgres_payment_store import PostgresPaymentStore

    return PostgresPaymentStore(runtime_config.database_url)
