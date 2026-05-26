from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, TextIO

from diet_bot.weekly_pdf_jobs import WeeklyPdfJob


DEFAULT_DATABASE_URL_ENV = "DIET_BOT_DATABASE_URL"
DEFAULT_LIMIT = 100


class ManualReviewJobStore(Protocol):
    def get_unresolved_manual_review_jobs(self, *, limit: int) -> list[WeeklyPdfJob]:
        ...

    def get_manual_review_jobs(self, *, limit: int, include_reviewed: bool) -> list[WeeklyPdfJob]:
        ...


StoreFactory = Callable[[str], ManualReviewJobStore]


def main(
    argv: list[str] | None = None,
    env: Mapping[str, str] | None = None,
    *,
    store_factory: StoreFactory | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = _build_parser(stderr)
    try:
        args = parser.parse_args(argv)
    except _ParserExit as exc:
        return exc.status

    source_env = os.environ if env is None else env
    database_url = source_env.get(args.database_url_env)
    if not database_url:
        print(
            f"Set {args.database_url_env} to read weekly PDF manual-review jobs.",
            file=stderr,
        )
        return 2

    factory = _default_store_factory if store_factory is None else store_factory
    try:
        store = factory(database_url)
        if args.include_reviewed:
            jobs = store.get_manual_review_jobs(limit=args.limit, include_reviewed=True)
        else:
            jobs = store.get_unresolved_manual_review_jobs(limit=args.limit)
    except Exception:
        print(
            "Failed to read weekly PDF manual-review jobs; database details redacted.",
            file=stderr,
        )
        return 2

    if args.json:
        _write_json_report(jobs, include_reviewed=args.include_reviewed, limit=args.limit, stdout=stdout)
    else:
        stdout.write(_render_table(jobs, include_reviewed=args.include_reviewed))
    return 0


def report_rows(jobs: list[WeeklyPdfJob]) -> list[dict[str, Any]]:
    return [_report_row(job) for job in jobs]


def _default_store_factory(database_url: str) -> ManualReviewJobStore:
    from diet_bot.postgres_weekly_pdf_job_store import PostgresWeeklyPdfJobStore

    return PostgresWeeklyPdfJobStore(database_url)


def _build_parser(stderr: TextIO) -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description="List weekly PDF jobs that need operator manual review.",
        stderr=stderr,
    )
    parser.add_argument(
        "--database-url-env",
        default=DEFAULT_DATABASE_URL_ENV,
        help="Environment variable containing the Postgres DSN.",
    )
    parser.add_argument(
        "--limit",
        default=DEFAULT_LIMIT,
        type=_positive_int,
        help="Maximum number of jobs to list.",
    )
    parser.add_argument("--json", action="store_true", help="Write a JSON report instead of a table.")
    parser.add_argument(
        "--include-reviewed",
        action="store_true",
        help="Include manual-review rows that already have manual_reviewed_at set.",
    )
    return parser


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be positive") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("limit must be positive")
    return parsed


def _write_json_report(
    jobs: list[WeeklyPdfJob],
    *,
    include_reviewed: bool,
    limit: int,
    stdout: TextIO,
) -> None:
    payload = {
        "mode": "weekly_pdf_manual_review",
        "include_reviewed": include_reviewed,
        "limit": limit,
        "count": len(jobs),
        "jobs": report_rows(jobs),
    }
    json.dump(payload, stdout, ensure_ascii=False, indent=2, sort_keys=True)
    stdout.write("\n")


def _render_table(jobs: list[WeeklyPdfJob], *, include_reviewed: bool) -> str:
    if not jobs:
        scope = "manual-review" if include_reviewed else "unresolved manual-review"
        return f"No weekly PDF {scope} jobs found.\n"

    rows = report_rows(jobs)
    columns = [
        ("job_id", "job_id"),
        ("created_at", "created_at"),
        ("updated_at", "updated_at"),
        ("status", "status"),
        ("delivery_status", "delivery"),
        ("refund_status", "refund"),
        ("consumption_source", "source"),
        ("chat_id_hash", "chat"),
        ("manual_review_reason", "manual_review_reason"),
        ("finalization_error", "finalization_error"),
        ("manual_reviewed_at", "reviewed_at"),
        ("manual_review_resolution", "resolution"),
    ]
    widths = {
        key: max(len(label), *(len(str(row[key])) for row in rows))
        for key, label in columns
    }
    lines = [
        "  ".join(label.ljust(widths[key]) for key, label in columns),
        "  ".join("-" * widths[key] for key, _label in columns),
    ]
    for row in rows:
        lines.append("  ".join(str(row[key]).ljust(widths[key]) for key, _label in columns))
    return "\n".join(lines) + "\n"


def _report_row(job: WeeklyPdfJob) -> dict[str, Any]:
    return {
        "job_id": str(job.job_id),
        "created_at": _format_datetime(job.created_at),
        "updated_at": _format_datetime(job.updated_at),
        "status": job.status,
        "delivery_status": job.delivery_status,
        "manual_review_reason": job.manual_review_reason or "",
        "finalization_error": job.finalization_error or "",
        "refund_status": job.refund_status,
        "consumption_source": job.consumption_source or "",
        "chat_id_hash": _chat_id_hash(job.chat_id),
        "manual_reviewed_at": _format_datetime(job.manual_reviewed_at),
        "manual_review_resolution": job.manual_review_resolution or "",
    }


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _chat_id_hash(chat_id: int) -> str:
    digest = hashlib.sha256(str(int(chat_id)).encode("utf-8")).hexdigest()[:16]
    return f"chat:sha256:{digest}"


class _ParserExit(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class _ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, stderr: TextIO, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._stderr = stderr

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if message:
            self._stderr.write(message)
        raise _ParserExit(status)

    def error(self, message: str) -> None:
        self.print_usage(self._stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
