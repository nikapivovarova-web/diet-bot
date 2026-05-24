import json
from pathlib import Path

import pytest

from diet_bot.subscriptions import Entitlement
from scripts import migrate_entitlements_json_to_postgres as migration


def test_dry_run_reports_counts_and_does_not_connect_to_postgres(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "subscriptions.json"
    _write_source(
        source,
        {
            101: Entitlement(
                free_trial_used=True,
                monthly_one_day_remaining=2,
                processed_payment_charge_ids=["charge-1", "charge-2"],
            ),
            202: Entitlement(extra_weekly_pdf_remaining=1),
        },
    )

    def fail_if_connected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("dry-run must not construct a Postgres store")

    monkeypatch.setattr(migration, "PostgresEntitlementStore", fail_if_connected)

    assert migration.main(["--source", str(source), "--migration-id", "dry-run-1"], env={}) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry_run"
    assert payload["migration_id"] == "dry-run-1"
    assert payload["report"] == {
        "entitlements": 2,
        "processed_charge_ids": 2,
    }
    assert payload["source"]["exists"] is True
    assert payload["source"]["bytes"] > 0
    assert payload["source_fingerprint"]
    assert "database" not in json.dumps(payload).lower()
    assert "postgres" not in json.dumps(payload).lower()


def test_dry_run_requires_existing_source(tmp_path: Path) -> None:
    missing_source = tmp_path / "missing-subscriptions.json"

    with pytest.raises(SystemExit, match="source JSON does not exist"):
        migration.main(
            ["--source", str(missing_source), "--migration-id", "missing-source-dry-run"],
            env={},
        )


def test_apply_requires_existing_source_before_postgres_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_source = tmp_path / "missing-subscriptions.json"

    def fail_if_connected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("missing source must fail before Postgres is touched")

    monkeypatch.setattr(migration, "PostgresEntitlementStore", fail_if_connected)

    with pytest.raises(SystemExit, match="source JSON does not exist"):
        migration.main(
            [
                "--source",
                str(missing_source),
                "--migration-id",
                "missing-source-apply",
                "--apply",
                "--database-url",
                "postgresql://example.invalid/diet_bot_test",
            ],
            env={},
        )


@pytest.mark.parametrize("contents", ["", " \n\t ", "{not-json", "[]", '"text"', "123", "null"])
def test_corrupt_empty_or_non_object_source_fails_before_postgres_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contents: str,
) -> None:
    source = tmp_path / "subscriptions.json"
    source.write_text(contents, encoding="utf-8")

    def fail_if_connected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("invalid JSON source must fail before Postgres is touched")

    monkeypatch.setattr(migration, "PostgresEntitlementStore", fail_if_connected)

    with pytest.raises(Exception):
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


def test_apply_requires_database_url_after_source_is_valid(tmp_path: Path) -> None:
    source = tmp_path / "subscriptions.json"
    _write_source(source, {303: Entitlement(monthly_weekly_pdf_remaining=3)})

    with pytest.raises(SystemExit, match="--database-url"):
        migration.main(["--source", str(source), "--migration-id", "apply-without-dsn", "--apply"], env={})


def test_expected_source_fingerprint_mismatch_fails_before_postgres_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "subscriptions.json"
    _write_source(source, {404: Entitlement(monthly_one_day_remaining=1)})

    def fail_if_connected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected source fingerprint guard must fail before Postgres is touched")

    monkeypatch.setattr(migration, "PostgresEntitlementStore", fail_if_connected)

    with pytest.raises(SystemExit, match="source fingerprint"):
        migration.main(
            [
                "--source",
                str(source),
                "--migration-id",
                "fingerprint-mismatch",
                "--expected-source-fingerprint",
                "not-the-current-fingerprint",
                "--apply",
                "--database-url",
                "postgresql://example.invalid/db",
            ],
            env={},
        )


def test_expected_entitlement_count_mismatch_fails_before_postgres_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "subscriptions.json"
    _write_source(
        source,
        {
            505: Entitlement(monthly_one_day_remaining=1, processed_payment_charge_ids=["charge-1"]),
            606: Entitlement(monthly_weekly_pdf_remaining=1),
        },
    )

    def fail_if_connected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected count guard must fail before Postgres is touched")

    monkeypatch.setattr(migration, "PostgresEntitlementStore", fail_if_connected)

    with pytest.raises(SystemExit, match="entitlement count"):
        migration.main(
            [
                "--source",
                str(source),
                "--migration-id",
                "entitlement-count-mismatch",
                "--expected-entitlement-count",
                "1",
                "--apply",
                "--database-url",
                "postgresql://example.invalid/db",
            ],
            env={},
        )


def test_expected_processed_charge_count_mismatch_fails_before_postgres_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "subscriptions.json"
    _write_source(
        source,
        {
            707: Entitlement(processed_payment_charge_ids=["charge-1", "charge-2"]),
        },
    )

    def fail_if_connected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected processed charge count guard must fail before Postgres is touched")

    monkeypatch.setattr(migration, "PostgresEntitlementStore", fail_if_connected)

    with pytest.raises(SystemExit, match="processed charge count"):
        migration.main(
            [
                "--source",
                str(source),
                "--migration-id",
                "processed-charge-count-mismatch",
                "--expected-processed-charge-count",
                "1",
                "--apply",
                "--database-url",
                "postgresql://example.invalid/db",
            ],
            env={},
        )


def _write_source(path: Path, entitlements: dict[int, Entitlement]) -> None:
    path.write_text(
        json.dumps(
            {str(chat_id): entitlement.to_dict() for chat_id, entitlement in entitlements.items()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
