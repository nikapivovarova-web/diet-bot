from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest


def test_json_recipe_history_records_and_loads_newest_first_with_window(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from diet_bot.json_storage import (
        load_recent_recipe_history_from_json,
        record_recipe_history_in_json,
    )
    from diet_bot.storage import RecipeHistoryItem

    path = tmp_path / "history.json"
    user_id = 12345
    old_at = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    middle_at = datetime(2026, 5, 8, 8, 0, tzinfo=UTC)
    new_at = datetime(2026, 5, 14, 8, 0, tzinfo=UTC)

    record_recipe_history_in_json(
        path,
        user_id,
        [
            RecipeHistoryItem("old", "breakfast:old", "breakfast", "one_day", generated_at=old_at),
            RecipeHistoryItem(
                "middle",
                "lunch:middle",
                "lunch",
                "weekly_pdf",
                generated_at=middle_at,
            ),
            RecipeHistoryItem("new", "dinner:new", "dinner", "weekly_pdf", generated_at=new_at),
        ],
    )

    recent = load_recent_recipe_history_from_json(
        path,
        user_id,
        since=middle_at,
        limit=2,
    )

    assert [item.recipe_id for item in recent] == ["new", "middle"]
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored[str(user_id)]["recipe_ids"] == ["old", "middle", "new"]
    assert stored[str(user_id)]["recipe_keys"] == [
        "breakfast:old",
        "lunch:middle",
        "dinner:new",
    ]


def test_json_recipe_history_is_idempotent_for_generation_slots(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from diet_bot.json_storage import (
        load_recent_recipe_history_from_json,
        record_recipe_history_in_json,
    )
    from diet_bot.storage import RecipeHistoryItem

    path = tmp_path / "history.json"
    user_id = 54321
    entry = RecipeHistoryItem(
        "recipe-1",
        "breakfast:recipe-1",
        "breakfast",
        "weekly_pdf",
        generation_id=99,
        generated_at=datetime(2026, 5, 14, 9, 0, tzinfo=UTC),
        day_index=0,
        meal_index=0,
    )

    record_recipe_history_in_json(path, user_id, [entry])
    record_recipe_history_in_json(path, user_id, [entry])

    recent = load_recent_recipe_history_from_json(path, user_id)
    stored = json.loads(path.read_text(encoding="utf-8"))

    assert [item.recipe_id for item in recent] == ["recipe-1"]
    assert stored[str(user_id)]["recipe_ids"] == ["recipe-1"]


def test_json_storage_transaction_is_reentrant(tmp_path: Path) -> None:
    from diet_bot.json_storage import atomic_write_json, json_storage_transaction

    path = tmp_path / "state.json"

    with json_storage_transaction(path, timeout_seconds=0.2):
        with json_storage_transaction(path, timeout_seconds=0.2):
            atomic_write_json(path, {"status": "ok"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "ok"}


def test_json_storage_lock_timeout_raises_clear_error(tmp_path: Path) -> None:
    from diet_bot.json_storage import JsonStorageLockError, json_storage_transaction

    path = tmp_path / "state.json"
    entered = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with json_storage_transaction(path, timeout_seconds=1.0):
            entered.set()
            release.wait(timeout=1.0)

    thread = threading.Thread(target=hold_lock)
    thread.start()
    assert entered.wait(timeout=1.0)

    started_at = time.monotonic()
    try:
        with pytest.raises(JsonStorageLockError) as exc_info:
            with json_storage_transaction(path, timeout_seconds=0.05):
                pass
    finally:
        release.set()
        thread.join(timeout=1.0)

    elapsed = time.monotonic() - started_at
    message = str(exc_info.value)
    assert elapsed < 0.5
    assert "state.json.lock" in message
    assert "0.05" in message


def test_json_storage_atomic_write_uses_temp_file_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import diet_bot.json_storage as json_storage

    path = tmp_path / "nested" / "state.json"
    replace_calls: list[tuple[Path, Path, str]] = []
    real_replace = os.replace

    def recording_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        source_path = Path(source)
        target_path = Path(target)
        replace_calls.append((source_path, target_path, source_path.read_text(encoding="utf-8")))
        real_replace(source, target)

    monkeypatch.setattr(json_storage.os, "replace", recording_replace)

    json_storage.atomic_write_json(path, {"value": 42})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 42}
    assert len(replace_calls) == 1
    source_path, target_path, temp_payload = replace_calls[0]
    assert source_path.parent == path.parent
    assert source_path != path
    assert source_path.name.endswith(".tmp")
    assert target_path == path
    assert json.loads(temp_payload) == {"value": 42}
    assert not source_path.exists()
