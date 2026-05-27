from __future__ import annotations

from .entitlement_storage import EntitlementStorageError, EntitlementStore, JsonEntitlementStore
from .runtime_config import RuntimeConfig


def create_entitlement_store(config: RuntimeConfig) -> EntitlementStore:
    if config.storage_backend == "json":
        return JsonEntitlementStore(config.subscriptions_state_file)

    if config.storage_backend == "postgres":
        if not config.database_url:
            raise RuntimeError("DIET_BOT_DATABASE_URL is required for postgres storage.")
        from .postgres_connection import get_shared_postgres_connection_provider
        from .postgres_entitlement_store import PostgresEntitlementStore

        return PostgresEntitlementStore(
            config.database_url,
            connection_provider=get_shared_postgres_connection_provider(config),
        )

    raise RuntimeError(f"Unsupported entitlement storage backend: {config.storage_backend!r}.")


def validate_entitlement_store_for_startup(config: RuntimeConfig, store: EntitlementStore) -> None:
    if config.storage_backend == "json":
        try:
            store.load_all()
        except EntitlementStorageError as exc:
            raise RuntimeError(
                f"Entitlement state is invalid at {config.subscriptions_state_file}: {exc}",
            ) from exc
        return

    if config.storage_backend == "postgres":
        validate_schema = getattr(store, "validate_schema", None)
        try:
            if callable(validate_schema):
                validate_schema()
            else:
                store.load_all()
        except Exception as exc:
            raise RuntimeError(
                "Postgres entitlement storage is not ready; run entitlement migrations before startup.",
            ) from exc
        return

    raise RuntimeError(f"Unsupported entitlement storage backend: {config.storage_backend!r}.")
