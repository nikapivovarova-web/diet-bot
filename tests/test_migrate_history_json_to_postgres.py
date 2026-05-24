import json
from pathlib import Path

import pytest

from scripts import migrate_history_json_to_postgres as migration


def test_dry_run_reports_counts_and_does_not_connect_to_postgres(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "history.json"
    _write_raw_source(
        source,
        {
            "1111111111": {
                "profile": {"marker": "secret-profile-marker"},
                "recipe_ids": ["recipe-secret-id", 42],
                "recipe_keys": ["recipe-secret-key"],
            },
            "2222222222": {"recipe_keys": ["second-secret-key"]},
            "3333333333": {"profile": {"ok": True}},
            "4444444444": ["invalid"],
            "not-a-chat-id": {"recipe_ids": ["skipped-secret-id"]},
        },
    )

    def fail_if_connected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("dry-run must not construct a Postgres store")

    monkeypatch.setattr(migration, "PostgresChatStateStore", fail_if_connected)

    assert migration.main(["--source", str(source), "--migration-id", "dry-run-1"], env={}) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry_run"
    assert payload["migration_id"] == "dry-run-1"
    assert payload["report"] == {
        "total_chats": 3,
        "profiles": 2,
        "chats_with_recipe_ids": 1,
        "chats_with_recipe_keys": 2,
        "recipe_history_chats": 2,
        "invalid_skipped_records": 2,
    }
    assert payload["source"]["exists"] is True
    assert payload["source"]["bytes"] > 0
    assert payload["source_fingerprint"]
    output = json.dumps(payload, ensure_ascii=False)
    for forbidden in (
        "1111111111",
        "2222222222",
        "secret-profile-marker",
        "recipe-secret-id",
        "recipe-secret-key",
        "second-secret-key",
        "skipped-secret-id",
    ):
        assert forbidden not in output


def test_apply_requires_database_url_after_source_is_valid(tmp_path: Path) -> None:
    source = tmp_path / "history.json"
    _write_raw_source(source, {"1111111111": {"recipe_ids": ["r001"]}})

    with pytest.raises(SystemExit, match="--database-url"):
        migration.main(["--source", str(source), "--migration-id", "apply-without-dsn", "--apply"], env={})


@pytest.mark.parametrize(
    ("guard_args", "match"),
    [
        (["--expected-source-fingerprint", "not-the-current-fingerprint"], "source fingerprint"),
        (["--expected-chat-count", "999"], "chat count"),
        (["--expected-profile-count", "999"], "profile count"),
        (["--expected-recipe-history-chat-count", "999"], "recipe history chat count"),
    ],
)
def test_expected_guard_mismatch_fails_before_postgres_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    guard_args: list[str],
    match: str,
) -> None:
    source = tmp_path / "history.json"
    _write_raw_source(
        source,
        {
            "1111111111": {"profile": {"ok": True}, "recipe_ids": ["r001"]},
            "2222222222": {"recipe_keys": ["main:r002"]},
        },
    )

    def fail_if_connected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected source guard must fail before Postgres is touched")

    monkeypatch.setattr(migration, "PostgresChatStateStore", fail_if_connected)

    with pytest.raises(SystemExit, match=match):
        migration.main(
            [
                "--source",
                str(source),
                "--migration-id",
                "guard-mismatch",
                *guard_args,
                "--apply",
                "--database-url",
                "postgresql://example.invalid/db",
            ],
            env={},
        )


@pytest.mark.parametrize("contents", ["", " \n\t ", "{not-json", "[]", '"text"', "123", "null"])
def test_invalid_json_empty_or_non_object_source_fails_before_postgres_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contents: str,
) -> None:
    source = tmp_path / "history.json"
    source.write_text(contents, encoding="utf-8")

    def fail_if_connected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("invalid JSON source must fail before Postgres is touched")

    monkeypatch.setattr(migration, "PostgresChatStateStore", fail_if_connected)

    with pytest.raises(SystemExit):
        migration.main(
            [
                "--source",
                str(source),
                "--migration-id",
                "invalid-source",
                "--apply",
                "--database-url",
                "postgresql://example.invalid/db",
            ],
            env={},
        )


def test_apply_passes_normalized_state_to_store_without_printing_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "history.json"
    _write_raw_source(
        source,
        {
            "1111111111": {
                "profile": {"marker": "secret-profile-marker"},
                "recipe_ids": ["recipe-secret-id"],
                "recipe_keys": ["recipe-secret-key"],
            },
            "bad-chat": {"profile": {"marker": "skipped-secret-profile"}},
        },
    )
    calls: list[dict[str, object]] = []

    class FakeStore:
        def __init__(self, dsn: str) -> None:
            calls.append({"dsn": dsn})

        def initialize(self) -> None:
            calls.append({"initialize": True})

        def apply_json_import(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return dict(kwargs["result_payload"])  # type: ignore[index]

    monkeypatch.setattr(migration, "PostgresChatStateStore", FakeStore)

    assert migration.main(
        [
            "--source",
            str(source),
            "--migration-id",
            "apply-fake",
            "--apply",
            "--database-url",
            "postgresql://example.invalid/db",
        ],
        env={},
    ) == 0

    apply_call = calls[-1]
    assert apply_call["chat_state"] == {
        "1111111111": {
            "profile": {"marker": "secret-profile-marker"},
            "recipe_ids": ["recipe-secret-id"],
            "recipe_keys": ["recipe-secret-key"],
        },
    }
    payload = json.loads(capsys.readouterr().out)
    output = json.dumps(payload, ensure_ascii=False)
    for forbidden in (
        "1111111111",
        "secret-profile-marker",
        "recipe-secret-id",
        "recipe-secret-key",
        "skipped-secret-profile",
    ):
        assert forbidden not in output


def _write_raw_source(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
