from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, TextIO
from uuid import UUID

from diet_bot.log_redaction import stable_identifier_hash
from diet_bot.ops.manual_review_text import redact_manual_review_text


DEFAULT_DATABASE_URL_ENV = "DIET_BOT_DATABASE_URL"
JOB_TYPE_WEEKLY = "weekly-pdf"
JOB_TYPE_ONE_DAY = "one-day"


class ManualReviewResolutionStore(Protocol):
    def get_job(self, job_id: UUID | str) -> Any | None:
        ...

    def resolve_manual_review(
        self,
        job_id: UUID | str,
        *,
        resolved_by: str,
        resolution: str,
        note: str,
        now: datetime | None = None,
        allow_non_manual_review: bool = False,
    ) -> Any:
        ...


StoreFactory = Callable[[str, str], ManualReviewResolutionStore]
NowFactory = Callable[[], datetime]


def main(
    argv: list[str] | None = None,
    env: Mapping[str, str] | None = None,
    *,
    store_factory: StoreFactory | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    now: NowFactory | None = None,
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
        print(f"Set {args.database_url_env} to resolve manual-review jobs.", file=stderr)
        return 2

    factory = _default_store_factory if store_factory is None else store_factory
    current_time = _normalize_now(now)
    try:
        store = factory(args.job_type, database_url)
        job_id = UUID(str(args.job_id))
        if args.dry_run:
            return _dry_run(args, store, job_id, stdout=stdout)
        return _apply(args, store, job_id, current_time, stdout=stdout)
    except ValueError as exc:
        print(str(exc), file=stderr)
        return 2
    except Exception:
        print("Failed to resolve manual-review job; database details redacted.", file=stderr)
        return 2


def _dry_run(args: argparse.Namespace, store: ManualReviewResolutionStore, job_id: UUID, *, stdout: TextIO) -> int:
    job = store.get_job(job_id)
    if job is None:
        _write_payload(
            {
                "mode": "manual_review_resolution",
                "action": "dry_run",
                "job_type": args.job_type,
                "job_id": str(job_id),
                "status": "not_found",
            },
            stdout,
        )
        return 1
    status = _dry_run_status(job, allow_non_manual_review=args.allow_non_manual_review)
    _write_payload(
        {
            "mode": "manual_review_resolution",
            "action": "dry_run",
            "job_type": args.job_type,
            "status": status,
            "operator": args.operator,
            "requested_resolution": args.resolution,
            "requested_note": redact_manual_review_text(args.note),
            "job": _job_payload(job, job_type=args.job_type),
        },
        stdout,
    )
    return 0 if status in {"would_resolve", "already_resolved"} else 1


def _apply(
    args: argparse.Namespace,
    store: ManualReviewResolutionStore,
    job_id: UUID,
    current_time: datetime,
    *,
    stdout: TextIO,
) -> int:
    result = store.resolve_manual_review(
        job_id,
        resolved_by=args.operator,
        resolution=args.resolution,
        note=args.note,
        now=current_time,
        allow_non_manual_review=args.allow_non_manual_review,
    )
    status = _status_value(result.status)
    _write_payload(
        {
            "mode": "manual_review_resolution",
            "action": "apply",
            "job_type": args.job_type,
            "status": status,
            "operator": args.operator,
            "requested_resolution": args.resolution,
            "requested_note": redact_manual_review_text(args.note),
            "job": _job_payload(result.job, job_type=args.job_type) if result.job is not None else None,
        },
        stdout,
    )
    return 0 if status in {"resolved", "already_resolved"} else 1


def _default_store_factory(job_type: str, database_url: str) -> ManualReviewResolutionStore:
    if job_type == JOB_TYPE_WEEKLY:
        from diet_bot.postgres_weekly_pdf_job_store import PostgresWeeklyPdfJobStore

        return PostgresWeeklyPdfJobStore(database_url)
    if job_type == JOB_TYPE_ONE_DAY:
        from diet_bot.postgres_one_day_generation_job_store import PostgresOneDayGenerationJobStore

        return PostgresOneDayGenerationJobStore(database_url)
    raise ValueError(f"Unsupported job type: {job_type}")


def _build_parser(stderr: TextIO) -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description="Resolve a weekly PDF or one-day manual-review job with operator audit metadata.",
        stderr=stderr,
    )
    parser.add_argument(
        "--database-url-env",
        default=DEFAULT_DATABASE_URL_ENV,
        help="Environment variable containing the Postgres DSN.",
    )
    parser.add_argument("--job-type", required=True, choices=(JOB_TYPE_WEEKLY, JOB_TYPE_ONE_DAY))
    parser.add_argument("--job-id", required=True, type=_uuid_value)
    parser.add_argument("--operator", required=True, type=_non_empty_text)
    parser.add_argument("--resolution", required=True, type=_non_empty_text)
    parser.add_argument("--note", required=True, type=_non_empty_text)
    parser.add_argument(
        "--allow-non-manual-review",
        action="store_true",
        help="Audit-resolve a row that is not currently flagged for manual review.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Preview the resolution without mutating the job.")
    mode.add_argument("--apply", action="store_true", help="Write resolution audit fields to the job.")
    return parser


def _uuid_value(value: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("job-id must be a UUID") from exc


def _non_empty_text(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise argparse.ArgumentTypeError("value must not be empty")
    return text


def _normalize_now(now: NowFactory | None) -> datetime:
    value = datetime.now(UTC) if now is None else now()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dry_run_status(job: Any, *, allow_non_manual_review: bool) -> str:
    if getattr(job, "manual_reviewed_at", None) is not None:
        return "already_resolved"
    if not bool(getattr(job, "requires_manual_review", False)) and not allow_non_manual_review:
        return "not_manual_review"
    return "would_resolve"


def _job_payload(job: Any, *, job_type: str) -> dict[str, Any]:
    payload = {
        "job_id": str(job.job_id),
        "job_type": job_type,
        "status": job.status,
        "delivery_status": job.delivery_status,
        "refund_status": job.refund_status,
        "consumption_source": getattr(job, "consumption_source", None) or "",
        "requires_manual_review": bool(getattr(job, "requires_manual_review", False)),
        "chat_id_hash": stable_identifier_hash("chat", int(job.chat_id)),
        "created_at": _format_datetime(getattr(job, "created_at", None)),
        "updated_at": _format_datetime(getattr(job, "updated_at", None)),
        "finished_at": _format_datetime(getattr(job, "finished_at", None)),
        "failure_reason": getattr(job, "failure_reason", None) or "",
        "finalization_error": getattr(job, "finalization_error", None) or "",
        "manual_reviewed_at": _format_datetime(getattr(job, "manual_reviewed_at", None)),
        "manual_reviewed_by": getattr(job, "manual_reviewed_by", None) or "",
        "manual_review_resolution": getattr(job, "manual_review_resolution", None) or "",
        "manual_review_note": redact_manual_review_text(getattr(job, "manual_review_note", None)),
    }
    if hasattr(job, "manual_review_reason"):
        payload["manual_review_reason"] = getattr(job, "manual_review_reason", None) or ""
    if hasattr(job, "expected_value_messages"):
        payload["expected_value_messages"] = int(getattr(job, "expected_value_messages", 0))
        payload["delivered_value_messages"] = int(getattr(job, "delivered_value_messages", 0))
    return payload


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _status_value(status: Any) -> str:
    return str(getattr(status, "value", status))


def _write_payload(payload: dict[str, Any], stdout: TextIO) -> None:
    json.dump(payload, stdout, ensure_ascii=False, indent=2, sort_keys=True)
    stdout.write("\n")


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
