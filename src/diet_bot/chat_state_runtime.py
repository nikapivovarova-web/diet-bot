from __future__ import annotations

from typing import Protocol

from .chat_state_storage import ChatStateByChatId, ChatStateStorageError, JsonChatStateStore
from .runtime_config import RuntimeConfig


class ChatStateStore(Protocol):
    def load_all(self) -> ChatStateByChatId: ...

    def load_chat_state(self, chat_id: int): ...

    def save_all(self, state) -> None: ...

    def save_chat_state(self, chat_id: int, chat_state) -> None: ...


def create_chat_state_store(config: RuntimeConfig) -> ChatStateStore:
    if config.storage_backend == "json":
        return JsonChatStateStore(config.state_file)

    if config.storage_backend == "postgres":
        if not config.database_url:
            raise RuntimeError("DIET_BOT_DATABASE_URL is required for postgres storage.")
        from .postgres_chat_state_store import PostgresChatStateStore

        return PostgresChatStateStore(config.database_url)

    raise RuntimeError(f"Unsupported chat state storage backend: {config.storage_backend!r}.")


def validate_chat_state_store_for_startup(
    config: RuntimeConfig,
    store: ChatStateStore | None = None,
) -> None:
    if config.storage_backend == "json":
        json_store = store if store is not None else create_chat_state_store(config)
        try:
            json_store.load_all()
        except ChatStateStorageError as exc:
            raise RuntimeError(f"Chat state is invalid at {config.state_file}: {exc}") from exc
        return

    if config.storage_backend == "postgres":
        postgres_store = store if store is not None else create_chat_state_store(config)
        validate_schema = getattr(postgres_store, "validate_schema", None)
        try:
            if callable(validate_schema):
                validate_schema()
            else:
                postgres_store.load_all()
        except Exception as exc:
            raise RuntimeError(
                "Postgres chat state storage is not ready; run chat state migrations before startup.",
            ) from exc
        return

    raise RuntimeError(f"Unsupported chat state storage backend: {config.storage_backend!r}.")
