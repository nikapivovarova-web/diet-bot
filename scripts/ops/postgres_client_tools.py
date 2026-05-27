from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path


POSTGRES_TOOL_ENV_VARS = {
    "pg_dump": "DIET_BOT_PG_DUMP_PATH",
    "pg_restore": "DIET_BOT_PG_RESTORE_PATH",
    "createdb": "DIET_BOT_CREATEDB_PATH",
    "dropdb": "DIET_BOT_DROPDB_PATH",
}


def resolve_required_postgres_tools(
    tool_names: tuple[str, ...],
    *,
    env: Mapping[str, str],
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    missing: list[tuple[str, str]] = []
    for tool_name in tool_names:
        env_var = POSTGRES_TOOL_ENV_VARS[tool_name]
        path = _resolve_postgres_tool(tool_name, env_var=env_var, env=env)
        if path is None:
            missing.append((tool_name, env_var))
            continue
        resolved[tool_name] = path
    if missing:
        raise SystemExit(_missing_tools_message(missing))
    return resolved


def _resolve_postgres_tool(
    tool_name: str,
    *,
    env_var: str,
    env: Mapping[str, str],
) -> str | None:
    override = env.get(env_var)
    if override:
        override = override.strip()
        if _looks_like_path(override):
            return _resolve_explicit_path(override)
        return _which(override, env=env)
    return _which(tool_name, env=env)


def _resolve_explicit_path(value: str) -> str | None:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return str(candidate)
    return None


def _looks_like_path(value: str) -> bool:
    path = Path(value)
    return path.is_absolute() or os.sep in value or (os.altsep is not None and os.altsep in value)


def _which(command: str, *, env: Mapping[str, str]) -> str | None:
    path = shutil.which(command, path=env.get("PATH"))
    if path is not None:
        return path
    if os.name != "nt":
        return None
    return _which_windows_with_env_pathext(command, env=env)


def _which_windows_with_env_pathext(command: str, *, env: Mapping[str, str]) -> str | None:
    command_path = Path(command)
    if command_path.parent != Path("."):
        candidate = Path(command)
        if candidate.is_file():
            return str(candidate)
        return None

    path_value = env.get("PATH")
    if path_value is None:
        path_dirs = os.get_exec_path()
    else:
        path_dirs = path_value.split(os.pathsep)
    extensions = _windows_extensions(command, env=env)
    for directory in path_dirs:
        search_dir = Path(directory or ".")
        for extension in extensions:
            candidate = search_dir / f"{command}{extension}"
            if candidate.is_file():
                return str(candidate)
    return None


def _windows_extensions(command: str, *, env: Mapping[str, str]) -> tuple[str, ...]:
    if Path(command).suffix:
        return ("",)
    pathext = env.get("PATHEXT") or os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    return tuple(extension for extension in pathext.split(os.pathsep) if extension)


def _missing_tools_message(missing: list[tuple[str, str]]) -> str:
    names = ", ".join(tool_name for tool_name, _env_var in missing)
    overrides = ", ".join(f"{env_var} for {tool_name}" for tool_name, env_var in missing)
    return (
        f"Missing required PostgreSQL client executable(s): {names}. "
        "Install the PostgreSQL client tools and ensure they are on PATH, "
        f"or set explicit executable path override(s): {overrides}."
    )
