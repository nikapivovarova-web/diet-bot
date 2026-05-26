from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ops import postgres_backup


BACKUP_DSN = "postgresql://backup_user:fake-password@db.example.invalid/diet_bot"


def test_backup_missing_env_fails_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(postgres_backup.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(SystemExit, match="DIET_BOT_BACKUP_DATABASE_URL"):
        postgres_backup.main(
            [
                "--source-url-env",
                "DIET_BOT_BACKUP_DATABASE_URL",
                "--output-dir",
                str(tmp_path),
            ],
            env={},
        )

    assert calls == []


def test_backup_does_not_fallback_to_runtime_database_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(postgres_backup.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(SystemExit, match="DIET_BOT_BACKUP_DATABASE_URL"):
        postgres_backup.main(
            [
                "--source-url-env",
                "DIET_BOT_BACKUP_DATABASE_URL",
                "--output-dir",
                str(tmp_path),
            ],
            env={"DIET_BOT_DATABASE_URL": "postgresql://user:runtime-secret@example.invalid/prod"},
        )

    assert calls == []


def test_backup_runs_pg_dump_without_secret_in_argv_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_dsn = (
        "postgresql://backup_user:fake-password@db.example.invalid:5433/"
        "diet_bot?sslmode=require&connect_timeout=10"
    )
    calls: list[dict[str, object]] = []
    pg_dump = _fake_tool(tmp_path, "pg_dump")
    monkeypatch.setenv("DIET_BOT_BACKUP_DATABASE_URL", fake_dsn)
    monkeypatch.setenv("DIET_BOT_PG_DUMP_PATH", str(pg_dump))

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": list(cmd), "env": dict(kwargs["env"])})
        output_path = Path(cmd[cmd.index("--file") + 1])
        output_path.write_bytes(b"fake custom dump")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(postgres_backup.subprocess, "run", fake_run)

    assert (
        postgres_backup.main(
            [
                "--source-url-env",
                "DIET_BOT_BACKUP_DATABASE_URL",
                "--output-dir",
                str(tmp_path),
            ],
        )
        == 0
    )

    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert isinstance(cmd, list)
    _assert_same_path(cmd[0], pg_dump)
    assert "--format=custom" in cmd
    assert "--no-owner" in cmd
    assert "--no-privileges" in cmd
    assert "--file" in cmd
    assert str(cmd[cmd.index("--file") + 1]).endswith(".dump")
    assert fake_dsn not in " ".join(str(part) for part in cmd)
    assert "fake-password" not in " ".join(str(part) for part in cmd)

    child_env = calls[0]["env"]
    assert isinstance(child_env, dict)
    assert child_env["PGHOST"] == "db.example.invalid"
    assert child_env["PGPORT"] == "5433"
    assert child_env["PGUSER"] == "backup_user"
    assert child_env["PGDATABASE"] == "diet_bot"
    assert child_env["PGPASSWORD"] == "fake-password"
    assert child_env["PGSSLMODE"] == "require"
    assert child_env["PGCONNECT_TIMEOUT"] == "10"
    assert child_env.get("DIET_BOT_BACKUP_DATABASE_URL") != fake_dsn

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "backup"
    assert payload["source_url_env"] == "DIET_BOT_BACKUP_DATABASE_URL"
    assert payload["output"]["bytes"] == len(b"fake custom dump")
    assert payload["output"]["path"].endswith(".dump")
    sanitized = json.dumps(payload, ensure_ascii=False)
    assert fake_dsn not in sanitized
    assert "fake-password" not in sanitized


def test_backup_missing_pg_dump_reports_actionable_error_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(postgres_backup.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(SystemExit) as excinfo:
        postgres_backup.main(
            [
                "--source-url-env",
                "DIET_BOT_BACKUP_DATABASE_URL",
                "--output-dir",
                str(tmp_path),
            ],
            env={"DIET_BOT_BACKUP_DATABASE_URL": BACKUP_DSN, "PATH": ""},
        )

    message = str(excinfo.value)
    assert "pg_dump" in message
    assert "DIET_BOT_PG_DUMP_PATH" in message
    assert "PostgreSQL client" in message
    assert "fake-password" not in message
    assert calls == []


def test_backup_uses_explicit_pg_dump_path_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pg_dump = _fake_tool(tmp_path, "pg_dump")
    calls: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": list(cmd), "env": dict(kwargs["env"])})
        output_path = Path(cmd[cmd.index("--file") + 1])
        output_path.write_bytes(b"fake custom dump")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(postgres_backup.subprocess, "run", fake_run)

    assert (
        postgres_backup.main(
            [
                "--source-url-env",
                "DIET_BOT_BACKUP_DATABASE_URL",
                "--output-dir",
                str(tmp_path / "backups"),
            ],
            env={
                "DIET_BOT_BACKUP_DATABASE_URL": BACKUP_DSN,
                "DIET_BOT_PG_DUMP_PATH": str(pg_dump),
                "PATH": "",
            },
        )
        == 0
    )

    _assert_same_path(calls[0]["cmd"][0], pg_dump)


def test_backup_discovers_pg_dump_from_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pg_dump = _fake_tool(bin_dir, "pg_dump")
    calls: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": list(cmd), "env": dict(kwargs["env"])})
        output_path = Path(cmd[cmd.index("--file") + 1])
        output_path.write_bytes(b"fake custom dump")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(postgres_backup.subprocess, "run", fake_run)

    assert (
        postgres_backup.main(
            [
                "--source-url-env",
                "DIET_BOT_BACKUP_DATABASE_URL",
                "--output-dir",
                str(tmp_path / "backups"),
            ],
            env={
                "DIET_BOT_BACKUP_DATABASE_URL": BACKUP_DSN,
                "PATH": str(bin_dir),
                "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
            },
        )
        == 0
    )

    _assert_same_path(calls[0]["cmd"][0], pg_dump)


def test_backup_script_help_runs_when_executed_directly() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/ops/postgres_backup.py", "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 0
    assert "Create a sanitized PostgreSQL custom-format backup." in result.stdout


def _fake_tool(directory: Path, name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    path = directory / f"{name}{suffix}"
    path.write_text("@echo off\r\nexit /b 0\r\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _assert_same_path(actual: object, expected: Path) -> None:
    actual_path = Path(str(actual))
    if os.name == "nt":
        assert actual_path.samefile(expected)
    else:
        assert actual_path == expected
