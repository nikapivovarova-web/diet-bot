from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.ops import postgres_restore_drill


ADMIN_DSN = "postgresql://restore_admin:fake-admin-password@db.example.invalid/postgres"


def test_restore_refuses_unsafe_generated_database_name_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_file = _write_backup(tmp_path)
    calls: list[object] = []
    monkeypatch.setattr(postgres_restore_drill, "_generate_restore_database_name", lambda: "production")
    monkeypatch.setattr(postgres_restore_drill.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(SystemExit, match="unsafe restore database name"):
        postgres_restore_drill.main(
            [
                "--backup-file",
                str(backup_file),
                "--admin-url-env",
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL",
            ],
            env={"DIET_BOT_RESTORE_ADMIN_DATABASE_URL": ADMIN_DSN},
        )

    assert calls == []


def test_restore_missing_client_tools_report_actionable_error_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_file = _write_backup(tmp_path)
    calls: list[object] = []
    monkeypatch.setattr(postgres_restore_drill, "_generate_restore_database_name", lambda: "diet_bot_restore_drill_unit_004")
    monkeypatch.setattr(postgres_restore_drill, "_verify_restored_database", lambda _url: _verification())
    monkeypatch.setattr(postgres_restore_drill.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(SystemExit) as excinfo:
        postgres_restore_drill.main(
            [
                "--backup-file",
                str(backup_file),
                "--admin-url-env",
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL",
            ],
            env={"DIET_BOT_RESTORE_ADMIN_DATABASE_URL": ADMIN_DSN, "PATH": ""},
        )

    message = str(excinfo.value)
    assert "createdb" in message
    assert "pg_restore" in message
    assert "dropdb" in message
    assert "DIET_BOT_CREATEDB_PATH" in message
    assert "DIET_BOT_PG_RESTORE_PATH" in message
    assert "DIET_BOT_DROPDB_PATH" in message
    assert "PostgreSQL client" in message
    assert "fake-admin-password" not in message
    assert calls == []


def test_restore_cleanup_runs_dropdb_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backup_file = _write_backup(tmp_path)
    tool_env, tools = _tool_env(tmp_path)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(postgres_restore_drill, "_generate_restore_database_name", lambda: "diet_bot_restore_drill_unit_001")
    monkeypatch.setattr(postgres_restore_drill, "_verify_restored_database", lambda _url: _verification())
    monkeypatch.setattr(postgres_restore_drill.subprocess, "run", _fake_runner(calls))

    assert (
        postgres_restore_drill.main(
            [
                "--backup-file",
                str(backup_file),
                "--admin-url-env",
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL",
            ],
            env={"DIET_BOT_RESTORE_ADMIN_DATABASE_URL": ADMIN_DSN, **tool_env},
        )
        == 0
    )

    _assert_tool_paths(calls, [tools["createdb"], tools["pg_restore"], tools["dropdb"]])
    assert "diet_bot_restore_drill_unit_001" in calls[-1]["cmd"]
    assert ADMIN_DSN not in _joined_commands(calls)
    assert "fake-admin-password" not in _joined_commands(calls)
    createdb_env = calls[0]["env"]
    pg_restore_env = calls[1]["env"]
    assert isinstance(createdb_env, dict)
    assert isinstance(pg_restore_env, dict)
    assert createdb_env["PGHOST"] == "db.example.invalid"
    assert createdb_env["PGUSER"] == "restore_admin"
    assert createdb_env["PGDATABASE"] == "postgres"
    assert createdb_env["PGPASSWORD"] == "fake-admin-password"
    assert pg_restore_env["PGHOST"] == "db.example.invalid"
    assert pg_restore_env["PGUSER"] == "restore_admin"
    assert pg_restore_env["PGDATABASE"] == "diet_bot_restore_drill_unit_001"
    assert pg_restore_env["PGPASSWORD"] == "fake-admin-password"

    payload = json.loads(capsys.readouterr().out)
    assert payload["cleanup"] == {"dropdb": "ran", "kept_restore_db": False}
    assert payload["restore_database"] == "diet_bot_restore_drill_unit_001"


def test_restore_uses_explicit_client_tool_path_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backup_file = _write_backup(tmp_path)
    createdb = _fake_tool(tmp_path, "createdb")
    pg_restore = _fake_tool(tmp_path, "pg_restore")
    dropdb = _fake_tool(tmp_path, "dropdb")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(postgres_restore_drill, "_generate_restore_database_name", lambda: "diet_bot_restore_drill_unit_005")
    monkeypatch.setattr(postgres_restore_drill, "_verify_restored_database", lambda _url: _verification())
    monkeypatch.setattr(postgres_restore_drill.subprocess, "run", _fake_runner(calls))

    assert (
        postgres_restore_drill.main(
            [
                "--backup-file",
                str(backup_file),
                "--admin-url-env",
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL",
            ],
            env={
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL": ADMIN_DSN,
                "DIET_BOT_CREATEDB_PATH": str(createdb),
                "DIET_BOT_PG_RESTORE_PATH": str(pg_restore),
                "DIET_BOT_DROPDB_PATH": str(dropdb),
                "PATH": "",
            },
        )
        == 0
    )

    _assert_tool_paths(calls, [createdb, pg_restore, dropdb])
    payload = json.loads(capsys.readouterr().out)
    assert payload["cleanup"] == {"dropdb": "ran", "kept_restore_db": False}


def test_restore_discovers_client_tools_from_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_file = _write_backup(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    createdb = _fake_tool(bin_dir, "createdb")
    pg_restore = _fake_tool(bin_dir, "pg_restore")
    dropdb = _fake_tool(bin_dir, "dropdb")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(postgres_restore_drill, "_generate_restore_database_name", lambda: "diet_bot_restore_drill_unit_006")
    monkeypatch.setattr(postgres_restore_drill, "_verify_restored_database", lambda _url: _verification())
    monkeypatch.setattr(postgres_restore_drill.subprocess, "run", _fake_runner(calls))

    assert (
        postgres_restore_drill.main(
            [
                "--backup-file",
                str(backup_file),
                "--admin-url-env",
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL",
            ],
            env={
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL": ADMIN_DSN,
                "PATH": str(bin_dir),
                "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
            },
        )
        == 0
    )

    _assert_tool_paths(calls, [createdb, pg_restore, dropdb])


def test_restore_script_help_runs_when_executed_directly() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/ops/postgres_restore_drill.py", "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 0
    assert "Restore a PostgreSQL backup into a generated drill database." in result.stdout


def test_restore_keep_flag_skips_dropdb_with_safe_generated_database_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backup_file = _write_backup(tmp_path)
    tool_env, tools = _tool_env(tmp_path, include_dropdb=False)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(postgres_restore_drill, "_generate_restore_database_name", lambda: "diet_bot_restore_drill_unit_002")
    monkeypatch.setattr(postgres_restore_drill, "_verify_restored_database", lambda _url: _verification())
    monkeypatch.setattr(postgres_restore_drill.subprocess, "run", _fake_runner(calls))

    assert (
        postgres_restore_drill.main(
            [
                "--backup-file",
                str(backup_file),
                "--admin-url-env",
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL",
                "--keep-restore-db",
            ],
            env={"DIET_BOT_RESTORE_ADMIN_DATABASE_URL": ADMIN_DSN, **tool_env},
        )
        == 0
    )

    _assert_tool_paths(calls, [tools["createdb"], tools["pg_restore"]])
    payload = json.loads(capsys.readouterr().out)
    assert payload["cleanup"] == {"dropdb": "skipped", "kept_restore_db": True}
    assert payload["restore_database"] == "diet_bot_restore_drill_unit_002"


def test_verify_restored_database_output_shape_includes_required_and_payment_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(
        present_tables={
            **{table: index for index, table in enumerate(postgres_restore_drill.REQUIRED_TABLES, start=1)},
            "payment_orders": 7,
            "payment_charges": 8,
        },
    )
    monkeypatch.setattr(postgres_restore_drill, "_connect", lambda _url: connection)

    report = postgres_restore_drill._verify_restored_database("postgresql://unused:secret@example.invalid/restore")

    assert set(report["required_tables"]) == set(postgres_restore_drill.REQUIRED_TABLES)
    assert report["required_tables"]["schema_migrations"] == {"present": True, "row_count": 1}
    assert report["required_tables"]["chat_profiles"]["row_count"] > 0
    assert report["payment_ledger_tables"]["payment_orders"] == {"present": True, "row_count": 7}
    assert report["payment_ledger_tables"]["payment_events"] == {"present": False, "row_count": None}


def test_restore_output_redacts_admin_and_compare_dsns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backup_file = _write_backup(tmp_path)
    compare_dsn = "postgresql://backup_user:fake-backup-password@db.example.invalid/diet_bot"
    tool_env, _tools = _tool_env(tmp_path)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(postgres_restore_drill, "_generate_restore_database_name", lambda: "diet_bot_restore_drill_unit_003")
    monkeypatch.setattr(postgres_restore_drill, "_verify_restored_database", lambda _url: _verification())
    monkeypatch.setattr(postgres_restore_drill, "_compare_source_and_restore_counts", lambda _source, _restore: _comparison())
    monkeypatch.setattr(postgres_restore_drill.subprocess, "run", _fake_runner(calls))

    assert (
        postgres_restore_drill.main(
            [
                "--backup-file",
                str(backup_file),
                "--admin-url-env",
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL",
                "--compare-source-url-env",
                "DIET_BOT_BACKUP_DATABASE_URL",
            ],
            env={
                "DIET_BOT_RESTORE_ADMIN_DATABASE_URL": ADMIN_DSN,
                "DIET_BOT_BACKUP_DATABASE_URL": compare_dsn,
                **tool_env,
            },
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert ADMIN_DSN not in serialized
    assert compare_dsn not in serialized
    assert "fake-admin-password" not in serialized
    assert "fake-backup-password" not in serialized
    assert payload["comparison"]["source_url_env"] == "DIET_BOT_BACKUP_DATABASE_URL"
    assert payload["comparison"]["frozen_writes_required"] is True


def test_runbook_documents_postgres_backup_restore_drill_env_vars() -> None:
    runbook = Path("docs/production-runbook.md").read_text(encoding="utf-8")

    assert "DIET_BOT_BACKUP_DATABASE_URL" in runbook
    assert "DIET_BOT_RESTORE_ADMIN_DATABASE_URL" in runbook
    assert "scripts\\ops\\postgres_backup.py" in runbook
    assert "scripts\\ops\\postgres_restore_drill.py" in runbook
    assert "DIET_BOT_PG_DUMP_PATH" in runbook
    assert "DIET_BOT_PG_RESTORE_PATH" in runbook
    assert "freeze writes" in runbook.lower()


def _write_backup(tmp_path: Path) -> Path:
    backup_file = tmp_path / "backup.dump"
    backup_file.write_bytes(b"fake dump")
    return backup_file


def _fake_runner(calls: list[dict[str, object]]):
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": list(cmd), "env": dict(kwargs["env"])})
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return fake_run


def _fake_tool(directory: Path, name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    path = directory / f"{name}{suffix}"
    path.write_text("@echo off\r\nexit /b 0\r\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _tool_env(tmp_path: Path, *, include_dropdb: bool = True) -> tuple[dict[str, str], dict[str, Path]]:
    tools = {
        "createdb": _fake_tool(tmp_path, "createdb"),
        "pg_restore": _fake_tool(tmp_path, "pg_restore"),
    }
    env = {
        "DIET_BOT_CREATEDB_PATH": str(tools["createdb"]),
        "DIET_BOT_PG_RESTORE_PATH": str(tools["pg_restore"]),
    }
    if include_dropdb:
        tools["dropdb"] = _fake_tool(tmp_path, "dropdb")
        env["DIET_BOT_DROPDB_PATH"] = str(tools["dropdb"])
    return env, tools


def _assert_tool_paths(calls: list[dict[str, object]], expected: list[Path]) -> None:
    actual = [Path(str(call["cmd"][0])) for call in calls]
    if os.name == "nt":
        for actual_path, expected_path in zip(actual, expected, strict=True):
            assert actual_path.samefile(expected_path)
    else:
        assert actual == expected


def _verification() -> dict[str, Any]:
    return {
        "required_tables": {
            table: {"present": True, "row_count": index}
            for index, table in enumerate(postgres_restore_drill.REQUIRED_TABLES, start=1)
        },
        "payment_ledger_tables": {
            table: {"present": False, "row_count": None}
            for table in postgres_restore_drill.PAYMENT_LEDGER_TABLES
        },
    }


def _comparison() -> dict[str, Any]:
    return {
        "tables": {
            table: {"source_count": index, "restored_count": index, "matches": True}
            for index, table in enumerate(postgres_restore_drill.REQUIRED_TABLES, start=1)
        },
        "all_counts_match": True,
    }


def _joined_commands(calls: list[dict[str, object]]) -> str:
    return " ".join(" ".join(str(part) for part in call["cmd"]) for call in calls)


class FakeConnection:
    def __init__(self, *, present_tables: dict[str, int]) -> None:
        self.present_tables = present_tables

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> "FakeCursor":
        return FakeCursor(self.present_tables)


class FakeCursor:
    def __init__(self, present_tables: dict[str, int]) -> None:
        self.present_tables = present_tables
        self.rows: list[dict[str, object]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: object, params: object | None = None) -> None:
        normalized = " ".join(str(query).split())
        if "FROM information_schema.tables" in normalized:
            requested = set(params[0]) if params else set()
            self.rows = [
                {"table_name": table}
                for table in sorted(requested)
                if table in self.present_tables
            ]
            return
        if normalized.startswith("SELECT count(*) AS row_count FROM"):
            table = normalized.rsplit(" ", 1)[-1].strip('"')
            self.rows = [{"row_count": self.present_tables[table]}]
            return
        raise AssertionError(f"unexpected query: {query}")

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.rows)

    def fetchone(self) -> dict[str, object]:
        return self.rows[0]
