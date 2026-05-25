from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_URL_ENV = "DIET_BOT_BACKUP_DATABASE_URL"


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a sanitized PostgreSQL custom-format backup.")
    parser.add_argument("--source-url-env", default=DEFAULT_SOURCE_URL_ENV)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    source_env = dict(os.environ if env is None else env)
    source_url = _required_env(source_env, args.source_url_env)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / _backup_filename()

    started_at = _now().isoformat()
    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(output_file),
    ]
    child_env = dict(os.environ)
    child_env["PGDATABASE"] = source_url

    _run_tool(command, env=child_env, tool_name="pg_dump")
    _require_backup_file(output_file)

    payload = {
        "mode": "backup",
        "source_url_env": args.source_url_env,
        "tool": "pg_dump",
        "output": _file_metadata(output_file),
        "started_at": started_at,
        "finished_at": _now().isoformat(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _required_env(env: dict[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise SystemExit(f"Set {name} to the Postgres URL to back up.")
    return value


def _backup_filename() -> str:
    return f"diet-bot-postgres-backup-{_now().strftime('%Y%m%dT%H%M%SZ')}.dump"


def _now() -> datetime:
    return datetime.now(UTC)


def _run_tool(command: list[str], *, env: dict[str, str], tool_name: str) -> None:
    result = subprocess.run(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"{tool_name} failed with exit code {result.returncode}; stderr redacted.")


def _require_backup_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise SystemExit("pg_dump completed without creating the expected backup file.")
    if path.stat().st_size <= 0:
        raise SystemExit("pg_dump created an empty backup file.")


def _file_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
