from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ops import postgres_backup


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
    fake_dsn = "postgresql://backup_user:fake-password@db.example.invalid/diet_bot"
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
                str(tmp_path),
            ],
            env={"DIET_BOT_BACKUP_DATABASE_URL": fake_dsn},
        )
        == 0
    )

    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:1] == ["pg_dump"]
    assert "--format=custom" in cmd
    assert "--no-owner" in cmd
    assert "--no-privileges" in cmd
    assert "--file" in cmd
    assert str(cmd[cmd.index("--file") + 1]).endswith(".dump")
    assert fake_dsn not in " ".join(str(part) for part in cmd)
    assert "fake-password" not in " ".join(str(part) for part in cmd)

    child_env = calls[0]["env"]
    assert isinstance(child_env, dict)
    assert child_env["PGDATABASE"] == fake_dsn

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "backup"
    assert payload["source_url_env"] == "DIET_BOT_BACKUP_DATABASE_URL"
    assert payload["output"]["bytes"] == len(b"fake custom dump")
    assert payload["output"]["path"].endswith(".dump")
    sanitized = json.dumps(payload, ensure_ascii=False)
    assert fake_dsn not in sanitized
    assert "fake-password" not in sanitized
