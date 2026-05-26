from __future__ import annotations

from .payment_recovery_spool import (
    PaymentRecoverySpoolUnavailable,
    validate_payment_recovery_spool_ready,
)
from .payment_service import PaymentService
from .runtime_config import RuntimeConfig, load_runtime_config


class PaymentLedgerUnavailable(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def create_payment_service(config: RuntimeConfig | None = None) -> PaymentService:
    return PaymentService(create_payment_store(config))


def validate_payment_runtime_for_startup(config: RuntimeConfig | None = None) -> None:
    runtime_config = load_runtime_config() if config is None else config
    if not runtime_config.payments_enabled:
        return

    if not runtime_config.payment_recovery_spool_configured:
        raise PaymentLedgerUnavailable(
            "payment_recovery_spool_unconfigured",
            "DIET_BOT_PAYMENT_RECOVERY_SPOOL is required when payments are enabled.",
        )
    try:
        validate_payment_recovery_spool_ready(runtime_config.payment_recovery_spool)
    except PaymentRecoverySpoolUnavailable as exc:
        raise PaymentLedgerUnavailable(
            "payment_recovery_spool_unavailable",
            "Payment recovery spool is not ready; configure an absolute writable fsync-able spool path.",
        ) from exc

    store = create_payment_store(runtime_config)
    validate_schema = getattr(store, "validate_schema", None)
    if not callable(validate_schema):
        raise PaymentLedgerUnavailable(
            "payment_ledger_schema_invalid",
            "Payment ledger schema is not ready; run payment migrations before startup.",
        )
    try:
        validate_schema()
    except PaymentLedgerUnavailable:
        raise
    except Exception as exc:
        raise PaymentLedgerUnavailable(
            "payment_ledger_schema_invalid",
            "Payment ledger schema is not ready; run payment migrations before startup.",
        ) from exc


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
