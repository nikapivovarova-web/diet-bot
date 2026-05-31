from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

try:
    from scripts.ops.postgres_client_tools import resolve_required_postgres_tools
except ModuleNotFoundError:
    from postgres_client_tools import resolve_required_postgres_tools


DEFAULT_ADMIN_URL_ENV = "DIET_BOT_RESTORE_ADMIN_DATABASE_URL"
DEFAULT_COMPARE_SOURCE_URL_ENV = "DIET_BOT_BACKUP_DATABASE_URL"
RESTORE_DATABASE_PREFIX = "diet_bot_restore_drill_"
SCHEMA_TABLES = ("schema_migrations",)
ENTITLEMENT_TABLES = (
    "entitlements",
    "entitlement_processed_charge_ids",
    "entitlement_json_import_runs",
)
WEEKLY_PDF_JOB_TABLES = ("weekly_pdf_jobs",)
CHAT_STATE_TABLES = (
    "chat_profiles",
    "chat_recipe_history",
    "chat_privacy_consents",
    "chat_state_json_import_runs",
)
ONE_DAY_GENERATION_JOB_TABLES = (
    "one_day_generation_jobs",
    "one_day_generation_job_value_messages",
)
PAYMENT_LEDGER_TABLES = (
    "payment_orders",
    "payment_charges",
    "payment_events",
)
PROMO_TABLES = (
    "promo_codes",
    "promo_code_redemptions",
    "promo_import_runs",
)
REQUIRED_TABLES = (
    *SCHEMA_TABLES,
    *ENTITLEMENT_TABLES,
    *WEEKLY_PDF_JOB_TABLES,
    *CHAT_STATE_TABLES,
    *ONE_DAY_GENERATION_JOB_TABLES,
    *PAYMENT_LEDGER_TABLES,
    *PROMO_TABLES,
)
_DATABASE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_UNSAFE_DATABASE_NAMES = {
    "postgres",
    "template0",
    "template1",
    "production",
    "prod",
    "diet_bot",
    "diet_bot_prod",
}
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
    parser = argparse.ArgumentParser(description="Restore a PostgreSQL backup into a generated drill database.")
    parser.add_argument("--backup-file", required=True, type=Path)
    parser.add_argument("--admin-url-env", default=DEFAULT_ADMIN_URL_ENV)
    parser.add_argument("--compare-source-url-env")
    parser.add_argument(
        "--allow-row-count-mismatch",
        action="store_true",
        help=(
            "Allow source-to-restore required table row-count differences after comparison. "
            "Use only with a documented operator waiver."
        ),
    )
    parser.add_argument("--keep-restore-db", action="store_true")
    args = parser.parse_args(argv)
    if args.allow_row_count_mismatch and not args.compare_source_url_env:
        parser.error("--allow-row-count-mismatch requires --compare-source-url-env")

    source_env = dict(os.environ if env is None else env)
    backup_file = args.backup_file
    _require_existing_backup(backup_file)
    admin_url = _required_env(source_env, args.admin_url_env)
    restore_database = _generate_restore_database_name()
    _require_safe_restore_database_name(restore_database)
    _refuse_admin_database_as_restore_target(admin_url, restore_database)
    restore_url = _replace_database_in_dsn(admin_url, restore_database)

    compare_source_url: str | None = None
    if args.compare_source_url_env:
        compare_source_url = _required_env(source_env, args.compare_source_url_env)
        _refuse_same_database(compare_source_url, restore_url)

    required_tool_names = ("createdb", "pg_restore") if args.keep_restore_db else ("createdb", "pg_restore", "dropdb")
    tools = resolve_required_postgres_tools(required_tool_names, env=source_env)

    admin_env = _connection_env_from_dsn(admin_url)
    restore_env = _connection_env_from_dsn(admin_url, database=restore_database)
    started_at = _now().isoformat()
    created = False
    cleanup = {"dropdb": "not_needed", "kept_restore_db": bool(args.keep_restore_db)}
    verification: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None

    try:
        _run_tool([tools["createdb"], restore_database], env=admin_env, tool_name="createdb")
        created = True
        _run_tool(
            [
                tools["pg_restore"],
                "--no-owner",
                "--no-privileges",
                "--dbname",
                restore_database,
                str(backup_file),
            ],
            env=restore_env,
            tool_name="pg_restore",
        )
        verification = _verify_restored_database(restore_url)
        if compare_source_url is not None:
            comparison = _compare_source_and_restore_counts(
                compare_source_url,
                restore_url,
                allow_mismatch=args.allow_row_count_mismatch,
            )
            comparison = {
                "source_url_env": args.compare_source_url_env,
                "frozen_writes_required": True,
                **comparison,
            }
    finally:
        if created and not args.keep_restore_db:
            _run_tool([tools["dropdb"], "--if-exists", restore_database], env=admin_env, tool_name="dropdb")
            cleanup = {"dropdb": "ran", "kept_restore_db": False}
        elif created:
            cleanup = {"dropdb": "skipped", "kept_restore_db": True}

    payload = {
        "mode": "restore_drill",
        "backup_file": _file_metadata(backup_file),
        "admin_url_env": args.admin_url_env,
        "compare_source_url_env": args.compare_source_url_env,
        "restore_database": restore_database,
        "verification": verification,
        "comparison": comparison,
        "cleanup": cleanup,
        "started_at": started_at,
        "finished_at": _now().isoformat(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _required_env(env: dict[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise SystemExit(f"Set {name} to the Postgres URL required for the restore drill.")
    return value


def _require_existing_backup(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"backup file does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"backup path is not a file: {path}")


def _generate_restore_database_name() -> str:
    timestamp = _now().strftime("%Y%m%dT%H%M%SZ").lower()
    suffix = uuid.uuid4().hex[:8]
    return f"{RESTORE_DATABASE_PREFIX}{timestamp}_{suffix}"


def _require_safe_restore_database_name(database_name: str) -> None:
    if (
        not _DATABASE_NAME_RE.fullmatch(database_name)
        or not database_name.startswith(RESTORE_DATABASE_PREFIX)
        or "restore" not in database_name
        or "drill" not in database_name
        or database_name in _UNSAFE_DATABASE_NAMES
        or "production" in database_name
        or database_name.endswith("_prod")
    ):
        raise SystemExit(f"unsafe restore database name: {database_name!r}")


def _refuse_admin_database_as_restore_target(admin_url: str, restore_database: str) -> None:
    admin_database = _database_name_from_dsn(admin_url)
    if admin_database and admin_database == restore_database:
        raise SystemExit("refusing to use the admin database as the restore drill target.")


def _refuse_same_database(source_url: str, restore_url: str) -> None:
    source_identity = _database_identity_from_dsn(source_url)
    restore_identity = _database_identity_from_dsn(restore_url)
    if source_identity is not None and source_identity == restore_identity:
        raise SystemExit("refusing source==target database for restore comparison.")


def _run_tool(command: list[str], *, env: dict[str, str], tool_name: str) -> None:
    child_env = dict(os.environ)
    child_env.update(env)
    try:
        result = subprocess.run(
            command,
            env=child_env,
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


def _verify_restored_database(database_url: str) -> dict[str, Any]:
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            present_tables = _fetch_present_tables(cur, REQUIRED_TABLES)
            required_counts = _table_counts(cur, REQUIRED_TABLES, present_tables=present_tables)
            missing_required = [
                table_name
                for table_name, report in required_counts.items()
                if not report["present"]
            ]
            if missing_required:
                raise SystemExit(
                    "restored database is missing required tables: "
                    + ", ".join(sorted(missing_required)),
                )
    return {
        "required_tables": required_counts,
        "schema_tables": _select_table_counts(required_counts, SCHEMA_TABLES),
        "entitlement_tables": _select_table_counts(required_counts, ENTITLEMENT_TABLES),
        "weekly_pdf_job_tables": _select_table_counts(required_counts, WEEKLY_PDF_JOB_TABLES),
        "chat_state_tables": _select_table_counts(required_counts, CHAT_STATE_TABLES),
        "one_day_generation_job_tables": _select_table_counts(required_counts, ONE_DAY_GENERATION_JOB_TABLES),
        "payment_ledger_tables": _select_table_counts(required_counts, PAYMENT_LEDGER_TABLES),
        "promo_tables": _select_table_counts(required_counts, PROMO_TABLES),
    }


def _compare_source_and_restore_counts(
    source_url: str,
    restore_url: str,
    *,
    allow_mismatch: bool = False,
) -> dict[str, Any]:
    source_counts = _fetch_counts_for_tables(source_url, REQUIRED_TABLES)
    restore_counts = _fetch_counts_for_tables(restore_url, REQUIRED_TABLES)
    tables = {
        table_name: {
            "source_count": source_counts[table_name],
            "restored_count": restore_counts[table_name],
            "matches": source_counts[table_name] == restore_counts[table_name],
        }
        for table_name in REQUIRED_TABLES
    }
    mismatched_tables = sorted(table_name for table_name, report in tables.items() if not report["matches"])
    if mismatched_tables and not allow_mismatch:
        raise SystemExit(
            "restore drill row-count mismatch for required tables: "
            + ", ".join(mismatched_tables),
        )
    return {
        "tables": tables,
        "all_counts_match": not mismatched_tables,
        "row_count_mismatch_allowed": bool(allow_mismatch),
    }


def _fetch_counts_for_tables(database_url: str, table_names: tuple[str, ...]) -> dict[str, int]:
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            present_tables = _fetch_present_tables(cur, table_names)
            missing = sorted(set(table_names) - present_tables)
            if missing:
                raise SystemExit(
                    "database comparison is missing required tables: "
                    + ", ".join(missing),
                )
            counts = _table_counts(cur, table_names, present_tables=present_tables)
    return {table_name: int(report["row_count"]) for table_name, report in counts.items()}


def _fetch_present_tables(cur: Any, table_names: tuple[str, ...]) -> set[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        """,
        (list(table_names),),
    )
    return {str(row["table_name"]) for row in cur.fetchall()}


def _table_counts(
    cur: Any,
    table_names: tuple[str, ...],
    *,
    present_tables: set[str],
) -> dict[str, dict[str, int | bool | None]]:
    reports: dict[str, dict[str, int | bool | None]] = {}
    for table_name in table_names:
        if table_name not in present_tables:
            reports[table_name] = {"present": False, "row_count": None}
            continue
        cur.execute(f"SELECT count(*) AS row_count FROM {_quote_identifier(table_name)}")
        row = cur.fetchone()
        reports[table_name] = {"present": True, "row_count": int(row["row_count"])}
    return reports


def _select_table_counts(
    reports: dict[str, dict[str, int | bool | None]],
    table_names: tuple[str, ...],
) -> dict[str, dict[str, int | bool | None]]:
    return {table_name: reports[table_name] for table_name in table_names}


def _quote_identifier(identifier: str) -> str:
    if identifier not in REQUIRED_TABLES:
        raise ValueError(f"unexpected table identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def _connect(database_url: str) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(database_url, row_factory=dict_row)


def _connection_env_from_dsn(dsn: str, *, database: str | None = None) -> dict[str, str]:
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
        if database or dbname:
            connection_env["PGDATABASE"] = database or str(dbname)
        query = parse_qs(parsed.query, keep_blank_values=True)
        for query_key, env_key in _QUERY_ENV_MAP.items():
            values = query.get(query_key)
            if values:
                connection_env[env_key] = values[-1]
        return connection_env

    keyword_params = _keyword_dsn_params(dsn)
    if keyword_params:
        connection_env = {
            env_key: value
            for key, value in keyword_params.items()
            if (env_key := _KEYWORD_ENV_MAP.get(key)) and value
        }
        if database:
            connection_env["PGDATABASE"] = database
        return connection_env

    return {"PGDATABASE": database or dsn}


def _replace_database_in_dsn(dsn: str, database: str) -> str:
    parsed = urlsplit(dsn)
    if parsed.scheme in {"postgres", "postgresql"}:
        path = "/" + quote(database)
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

    keyword_params = _keyword_dsn_params(dsn)
    if keyword_params:
        keyword_params["dbname"] = database
        return " ".join(
            f"{key}={_conninfo_value(value)}"
            for key, value in keyword_params.items()
        )

    return database


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


def _database_identity_from_dsn(dsn: str) -> tuple[str | None, str | None, str | None, str | None] | None:
    parsed = urlsplit(dsn)
    if parsed.scheme in {"postgres", "postgresql"}:
        return (
            unquote(parsed.hostname or ""),
            str(parsed.port or ""),
            unquote(parsed.username or ""),
            _database_name_from_dsn(dsn),
        )

    keyword_params = _keyword_dsn_params(dsn)
    if keyword_params:
        return (
            keyword_params.get("host", ""),
            keyword_params.get("port", ""),
            keyword_params.get("user", ""),
            keyword_params.get("dbname", ""),
        )
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


def _conninfo_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.:/@-]+", value):
        return value
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _file_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def _now() -> datetime:
    return datetime.now(UTC)


if __name__ == "__main__":
    raise SystemExit(main())
