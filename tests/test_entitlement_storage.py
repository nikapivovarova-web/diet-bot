import json
import builtins
import sys
from pathlib import Path

import pytest

import diet_bot.entitlement_storage as entitlement_storage
from diet_bot.runtime_config import load_runtime_config
from diet_bot.entitlement_storage import (
    EntitlementStateCorrupt,
    EntitlementStorageError,
    JsonEntitlementStore,
)
from diet_bot.subscriptions import Entitlement


def test_missing_subscriptions_loads_empty(tmp_path: Path) -> None:
    store = JsonEntitlementStore(tmp_path / "subscriptions.json")

    assert store.load_all() == {}


@pytest.mark.parametrize("contents", ["", " \n\t "])
def test_zero_byte_or_whitespace_state_raises_and_does_not_save_empty(
    tmp_path: Path,
    contents: str,
) -> None:
    path = tmp_path / "subscriptions.json"
    path.write_text(contents, encoding="utf-8")
    store = JsonEntitlementStore(path)

    with pytest.raises(EntitlementStateCorrupt):
        store.load_all()

    with pytest.raises(EntitlementStateCorrupt):
        store.save_all({})

    assert path.read_text(encoding="utf-8") == contents
    assert not _backup_path(path).exists()


def test_corrupt_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(EntitlementStateCorrupt):
        JsonEntitlementStore(path).load_all()


@pytest.mark.parametrize("contents", ["[]", '"text"', "123", "null"])
def test_non_object_json_raises(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "subscriptions.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(EntitlementStateCorrupt):
        JsonEntitlementStore(path).load_all()


def test_atomic_write_preserves_previous_valid_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "subscriptions.json"
    _write_state(path, {123: Entitlement(monthly_weekly_pdf_remaining=1)})
    store = JsonEntitlementStore(path)

    def fail_replace(_source: str | bytes | Path, _target: str | bytes | Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(entitlement_storage.os, "replace", fail_replace)

    with pytest.raises(EntitlementStorageError):
        store.save_all({123: Entitlement(monthly_weekly_pdf_remaining=4)})

    assert store.load_all()[123].monthly_weekly_pdf_remaining == 1


def test_successful_save_creates_backup_from_previous_valid_primary(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.json"
    _write_state(path, {123: Entitlement(monthly_one_day_remaining=1)})
    store = JsonEntitlementStore(path)

    store.save_all({123: Entitlement(monthly_one_day_remaining=5)})

    assert store.load_all()[123].monthly_one_day_remaining == 5
    assert JsonEntitlementStore(_backup_path(path)).load_all()[123].monthly_one_day_remaining == 1


def test_backup_copy_storage_error_cleans_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "subscriptions.json"
    _write_state(path, {123: Entitlement(monthly_one_day_remaining=1)})
    store = JsonEntitlementStore(path)

    def fail_backup() -> None:
        raise EntitlementStorageError("backup failed")

    monkeypatch.setattr(store, "_copy_primary_to_backup", fail_backup)

    with pytest.raises(EntitlementStorageError):
        store.save_all({123: Entitlement(monthly_one_day_remaining=5)})

    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []
    assert store.load_all()[123].monthly_one_day_remaining == 1


def test_recover_from_backup_requires_valid_backup_and_restores(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.json"
    backup_path = _backup_path(path)
    store = JsonEntitlementStore(path)

    with pytest.raises(EntitlementStorageError):
        store.recover_from_backup()

    path.write_text("{corrupt", encoding="utf-8")
    backup_path.write_text("{corrupt-backup", encoding="utf-8")
    with pytest.raises(EntitlementStateCorrupt):
        store.recover_from_backup()

    _write_state(backup_path, {456: Entitlement(extra_weekly_pdf_remaining=2)})
    store.recover_from_backup()

    assert store.load_all()[456].extra_weekly_pdf_remaining == 2


def test_create_entitlement_store_defaults_to_json_without_postgres_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sys.modules.pop("diet_bot.postgres_entitlement_store", None)
    sys.modules.pop("psycopg", None)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith(("diet_bot.postgres_entitlement_store", "psycopg")):
            raise AssertionError(f"JSON runtime imported postgres dependency {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    from diet_bot.entitlement_runtime import create_entitlement_store

    path = tmp_path / "subscriptions.json"
    config = load_runtime_config({"DIET_BOT_SUBSCRIPTIONS_STATE_FILE": str(path)})

    store = create_entitlement_store(config)

    assert isinstance(store, JsonEntitlementStore)
    assert store.path == path


def test_create_entitlement_store_uses_postgres_when_requested() -> None:
    from diet_bot.entitlement_runtime import create_entitlement_store
    from diet_bot.postgres_entitlement_store import PostgresEntitlementStore

    database_url = "postgresql://user:secret@example/db"
    config = load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": database_url,
        },
    )

    store = create_entitlement_store(config)

    assert isinstance(store, PostgresEntitlementStore)
    assert store.dsn == database_url


def test_json_startup_validation_uses_existing_fail_closed_parser(tmp_path: Path) -> None:
    from diet_bot.entitlement_runtime import create_entitlement_store, validate_entitlement_store_for_startup

    path = tmp_path / "subscriptions.json"
    path.write_text("{not-json", encoding="utf-8")
    config = load_runtime_config({"DIET_BOT_SUBSCRIPTIONS_STATE_FILE": str(path)})
    store = create_entitlement_store(config)

    with pytest.raises(RuntimeError, match="Entitlement state is invalid"):
        validate_entitlement_store_for_startup(config, store)


def test_postgres_startup_validation_does_not_auto_migrate() -> None:
    from diet_bot.entitlement_runtime import validate_entitlement_store_for_startup

    class FakePostgresStore:
        def __init__(self) -> None:
            self.validated = False
            self.initialize_called = False

        def validate_schema(self) -> None:
            self.validated = True

        def initialize(self) -> None:
            self.initialize_called = True
            raise AssertionError("startup validation must not auto-migrate")

    store = FakePostgresStore()
    config = load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    validate_entitlement_store_for_startup(config, store)

    assert store.validated is True
    assert store.initialize_called is False


def _write_state(path: Path, entitlements: dict[int, Entitlement]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        str(chat_id): entitlement.to_dict()
        for chat_id, entitlement in sorted(entitlements.items())
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")
