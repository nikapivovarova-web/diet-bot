from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import diet_bot.chat_state_storage as chat_state_storage
import diet_bot.telegram_app as telegram_app
from diet_bot.chat_state_storage import ChatStateStorageError, JsonChatStateStore
from diet_bot.domain import (
    ActivityLevel,
    CookingTimePreference,
    Goal,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
)


def test_missing_state_file_loads_empty(tmp_path: Path) -> None:
    store = JsonChatStateStore(tmp_path / "history.json")

    assert store.load_all() == {}


def test_valid_state_roundtrips_profile_and_history(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    store = JsonChatStateStore(path)
    profile = {
        "age": 32,
        "sex": "female",
        "height_cm": 168,
        "weight_kg": 64,
        "goal": "maintain",
    }
    privacy_consent = {
        "accepted": True,
        "accepted_at": "2026-05-31T12:00:00+00:00",
        "text_sha256": "f" * 64,
        "policy_url": "https://foodbalance.example/privacy",
        "schema_version": 1,
    }

    store.save_chat_state(101, {"profile": profile})
    store.save_chat_state(101, {"privacy_consent": privacy_consent})
    store.save_chat_state(
        101,
        {"recipe_ids": ["r001", "r002"], "recipe_keys": ["breakfast:r001", "main:r002"]},
    )

    assert store.load_all() == {
        "101": {
            "profile": profile,
            "privacy_consent": privacy_consent,
            "recipe_ids": ["r001", "r002"],
            "recipe_keys": ["breakfast:r001", "main:r002"],
        },
    }
    assert json.loads(path.read_text(encoding="utf-8")) == store.load_all()


def test_save_writes_via_temp_replace_and_updates_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "history.json"
    store = JsonChatStateStore(path)
    replace_sources: list[Path] = []
    real_replace = chat_state_storage.os.replace

    def tracking_replace(source: str | bytes | Path, target: str | bytes | Path) -> None:
        replace_sources.append(Path(source))
        real_replace(source, target)

    monkeypatch.setattr(chat_state_storage.os, "replace", tracking_replace)

    store.save_all({"1": {"recipe_ids": ["old"], "recipe_keys": ["old-key"]}})
    first_payload = json.loads(path.read_text(encoding="utf-8"))
    assert _backup_path(path).exists()
    assert json.loads(_backup_path(path).read_text(encoding="utf-8")) == first_payload

    store.save_all({"1": {"recipe_ids": ["new"], "recipe_keys": ["new-key"]}})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "1": {"recipe_ids": ["new"], "recipe_keys": ["new-key"]},
    }
    assert json.loads(_backup_path(path).read_text(encoding="utf-8")) == {
        "1": {"recipe_ids": ["new"], "recipe_keys": ["new-key"]},
    }
    assert any(source.parent == path.parent and source.name.startswith(f".{path.name}.") for source in replace_sources)
    assert any(source.suffix == ".tmp" for source in replace_sources)


def test_corrupt_primary_with_valid_backup_restores_and_loads_backup(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    backup_payload = {"44": {"recipe_ids": ["r044"], "recipe_keys": ["main:r044"]}}
    path.write_text("{not-json", encoding="utf-8")
    _backup_path(path).write_text(json.dumps(backup_payload, ensure_ascii=False), encoding="utf-8")

    store = JsonChatStateStore(path)

    assert store.load_all() == backup_payload
    assert json.loads(path.read_text(encoding="utf-8")) == backup_payload


@pytest.mark.parametrize("backup_contents", [None, "{backup-is-corrupt"])
def test_corrupt_primary_without_valid_backup_raises_and_does_not_overwrite(
    tmp_path: Path,
    backup_contents: str | None,
) -> None:
    path = tmp_path / "history.json"
    path.write_text("{primary-is-corrupt", encoding="utf-8")
    if backup_contents is not None:
        _backup_path(path).write_text(backup_contents, encoding="utf-8")
    store = JsonChatStateStore(path)

    with pytest.raises(ChatStateStorageError):
        store.load_all()
    with pytest.raises(ChatStateStorageError):
        store.save_chat_state(50, {"recipe_ids": ["must-not-write"], "recipe_keys": []})

    assert path.read_text(encoding="utf-8") == "{primary-is-corrupt"
    if backup_contents is not None:
        assert _backup_path(path).read_text(encoding="utf-8") == backup_contents


def test_two_chat_sequential_and_concurrent_saves_do_not_lose_either_chat(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    store = JsonChatStateStore(path)

    store.save_chat_state(1, {"recipe_ids": ["r001"], "recipe_keys": ["key-1"]})
    store.save_chat_state(2, {"recipe_ids": ["r002"], "recipe_keys": ["key-2"]})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(store.save_chat_state, 3, {"recipe_ids": ["r003"], "recipe_keys": ["key-3"]}),
            executor.submit(store.save_chat_state, 4, {"recipe_ids": ["r004"], "recipe_keys": ["key-4"]}),
        ]
        for future in futures:
            future.result()

    state = store.load_all()
    assert state["1"]["recipe_ids"] == ["r001"]
    assert state["2"]["recipe_ids"] == ["r002"]
    assert state["3"]["recipe_ids"] == ["r003"]
    assert state["4"]["recipe_ids"] == ["r004"]


def test_telegram_profile_save_read_uses_json_chat_state_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.json"
    chat_id = 9191
    profile = _profile()
    monkeypatch.setattr(telegram_app, "STATE_FILE", path)

    try:
        telegram_app._save_chat_profile(chat_id, profile)
        telegram_app.PROFILE_BY_CHAT_ID.pop(chat_id, None)

        restored = telegram_app._profile_for_chat(chat_id)

        assert restored == profile
        assert JsonChatStateStore(path).load_all()[str(chat_id)]["profile"] == telegram_app._profile_to_dict(profile)
    finally:
        telegram_app.PROFILE_BY_CHAT_ID.pop(chat_id, None)


def test_telegram_chat_state_reads_use_row_level_store_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_id = 8181
    profile = _profile()
    profile_payload = telegram_app._profile_to_dict(profile)
    store = _RowLevelOnlyChatStateStore(
        {
            str(chat_id): {
                "profile": profile_payload,
                "recipe_ids": ["r001", "r002"],
                "recipe_keys": ["breakfast:r001", "main:r002"],
            },
            "9999": {
                "recipe_ids": ["must-not-load-all"],
                "recipe_keys": ["must-not-load-all"],
            },
        },
    )
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)
    telegram_app.PROFILE_BY_CHAT_ID.pop(chat_id, None)
    telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
    telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)

    try:
        assert telegram_app._profile_for_chat(chat_id) == profile
        telegram_app._load_chat_history(chat_id)
        assert telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID[chat_id] == ["r001", "r002"]
        assert telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID[chat_id] == ["breakfast:r001", "main:r002"]
    finally:
        telegram_app.PROFILE_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.RECENT_RECIPE_IDS_BY_CHAT_ID.pop(chat_id, None)
        telegram_app.RECENT_RECIPE_KEYS_BY_CHAT_ID.pop(chat_id, None)

    assert store.load_chat_calls == [chat_id, chat_id]


def test_telegram_chat_state_writes_use_row_level_store_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_id = 8282
    profile = _profile()
    store = _RowLevelOnlyChatStateStore()
    monkeypatch.setattr(telegram_app, "_chat_state_store", lambda: store)

    telegram_app._save_chat_profile(chat_id, profile)
    telegram_app._save_chat_history(
        chat_id,
        recipe_ids=["r010", "r011"],
        recipe_keys=["main:r010", "main:r011"],
    )

    assert store.save_chat_calls == [
        (chat_id, {"profile": telegram_app._profile_to_dict(profile)}),
        (
            chat_id,
            {
                "recipe_ids": ["r010", "r011"],
                "recipe_keys": ["main:r010", "main:r011"],
            },
        ),
    ]


def _profile() -> UserProfile:
    return UserProfile(
        age=34,
        sex=Sex.FEMALE,
        height_cm=171,
        weight_kg=67,
        goal=Goal.MAINTAIN,
        activity=ActivityLevel.MODERATE,
        meal_count=4,
        cooking_time=CookingTimePreference.QUICK,
        restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "mushrooms"),),
    )


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


class _RowLevelOnlyChatStateStore:
    def __init__(self, state: dict[str, dict[str, object]] | None = None) -> None:
        self._state = state or {}
        self.load_chat_calls: list[int] = []
        self.save_chat_calls: list[tuple[int, dict[str, object]]] = []

    def load_chat_state(self, chat_id: int) -> dict[str, object]:
        self.load_chat_calls.append(int(chat_id))
        return dict(self._state.get(str(chat_id), {}))

    def save_chat_state(self, chat_id: int, chat_state) -> None:
        self.save_chat_calls.append((int(chat_id), dict(chat_state)))

    def load_all(self):
        raise AssertionError("hot chat-state path must not load all chat state")

    def save_all(self, state) -> None:
        raise AssertionError("hot chat-state path must not replace all chat state")
