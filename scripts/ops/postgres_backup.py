from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

try:
    from scripts.ops.postgres_client_tools import resolve_required_postgres_tools
except ModuleNotFoundError:
    from postgres_client_tools import resolve_required_postgres_tools


DEFAULT_SOURCE_URL_ENV = "DIET_BOT_BACKUP_DATABASE_URL"
_QUERY_ENV_MAP = {
    "application_name": "PGAPPNAME",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "sslmode": "PGSSLMODE",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
}
_KEYWORD_ENV_MAP = {
    "host": "PGHOST",
    "port": "PGPORT",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "dbname": "PGDATABASE",
    **_QUERY_ENV_MAP,
}


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a sanitized PostgreSQL custom-format backup.")
    parser.add_argument("--source-url-env", default=DEFAULT_SOURCE_URL_ENV)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    source_env = dict(os.environ if env is None else env)
    source_url = _required_env(source_env, args.source_url_env)
    tools = resolve_required_postgres_tools(("pg_dump",), env=source_env)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / _backup_filename()

    started_at = _now().isoformat()
    command = [
        tools["pg_dump"],
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(output_file),
    ]
    child_env = dict(os.environ)
    child_env.pop(args.source_url_env, None)
    child_env.update(_connection_env_from_dsn(source_url))

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
    try:
        result = subprocess.run(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            f"{tool_name} executable was not found at run time; "
            "install PostgreSQL client tools or set the explicit executable path override.",
        ) from exc
    if result.returncode != 0:
        raise SystemExit(f"{tool_name} failed with exit code {result.returncode}; stderr redacted.")


def _connection_env_from_dsn(dsn: str) -> dict[str, str]:
    parsed = urlsplit(dsn)
    if parsed.scheme in {"postgres", "postgresql"}:
        connection_env: dict[str, str] = {}
        if parsed.hostname:
            connection_env["PGHOST"] = unquote(parsed.hostname)
        if parsed.port:
            connection_env["PGPORT"] = str(parsed.port)
        if parsed.username:
            connection_env["PGUSER"] = unquote(parsed.username)
        if parsed.password:
            connection_env["PGPASSWORD"] = unquote(parsed.password)
        dbname = _database_name_from_dsn(dsn)
        if dbname:
            connection_env["PGDATABASE"] = dbname
        query = parse_qs(parsed.query, keep_blank_values=True)
        for query_key, env_key in _QUERY_ENV_MAP.items():
            values = query.get(query_key)
            if values:
                connection_env[env_key] = values[-1]
        return connection_env

    keyword_params = _keyword_dsn_params(dsn)
    if keyword_params:
        return {
            env_key: value
            for key, value in keyword_params.items()
            if (env_key := _KEYWORD_ENV_MAP.get(key)) and value
        }

    return {"PGDATABASE": dsn}


def _database_name_from_dsn(dsn: str) -> str | None:
    parsed = urlsplit(dsn)
    if parsed.scheme in {"postgres", "postgresql"}:
        path = parsed.path.lstrip("/")
        if not path:
            return None
        return unquote(path.split("/", 1)[0])

    keyword_params = _keyword_dsn_params(dsn)
    if keyword_params:
        return keyword_params.get("dbname")
    return None


def _keyword_dsn_params(dsn: str) -> dict[str, str]:
    params: dict[str, str] = {}
    try:
        tokens = shlex.split(dsn)
    except ValueError:
        return {}
    for token in tokens:
        if "=" not in token:
            return {}
        key, value = token.split("=", 1)
        if not key:
            return {}
        params[key] = value
    return params


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
