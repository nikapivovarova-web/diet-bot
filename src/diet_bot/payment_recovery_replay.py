from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

from .log_redaction import redact_optional_identifier
from .payment_recovery_spool import (
    ALLOWED_SERIALIZED_FIELDS,
    PaymentRecoveryRecord,
    PaymentRecoveryRecordError,
)
from .payments import (
    ORDER_STATUS_GRANTED,
    ORDER_STATUS_PENDING,
    PRODUCT_SUBSCRIPTION_MONTH,
    PaymentCharge,
    PaymentHandlingResult,
    PaymentOrder,
    PaymentPayloadError,
    decode_payment_order_payload,
)


STATUS_LISTED = "listed"
STATUS_REPLAYABLE_CANDIDATE = "replayable_candidate"
STATUS_ALREADY_RECOVERED = "already_recovered"
STATUS_BLOCKED = "blocked"
STATUS_DB_VALIDATION_UNAVAILABLE = "db_validation_unavailable"

APPLY_STATUS_RECOVERED = "recovered"
APPLY_STATUS_ALREADY_RECOVERED = "already_recovered"
APPLY_STATUS_BLOCKED = "blocked"
APPLY_STATUS_APPLY_FAILED = "apply_failed"

DEFAULT_DATABASE_URL_ENV = "DIET_BOT_DATABASE_URL"
_SAFE_REASON_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


class PaymentReplayUsageError(RuntimeError):
    """Raised when replay preflight input or CLI configuration is invalid."""


class PaymentReplayLookup(Protocol):
    def get_order(self, order_id: str) -> PaymentOrder | None:
        ...

    def find_charge_by_external_id(
        self,
        *,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
    ) -> PaymentCharge | None:
        ...


class PaymentReplayPaymentService(Protocol):
    def handle_successful_payment(
        self,
        *,
        payload: str,
        user_id: int,
        chat_id: int,
        provider: str,
        amount: int,
        currency: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None = None,
        raw_payload: dict[str, object] | None = None,
    ) -> PaymentHandlingResult:
        ...


@dataclass(frozen=True)
class PaymentReplayRecordReport:
    line_number: int | None
    record_id: str | None
    status: str
    reason: str | None = None
    provider: str | None = None
    amount: int | None = None
    currency: str | None = None
    created_at: str | None = None
    chat_id: str | None = None
    user_id: str | None = None
    telegram_payment_charge_id: str | None = None
    provider_payment_charge_id: str | None = None
    has_subscription_expiration_date: bool | None = None
    detail: str | None = None

    @classmethod
    def from_record(
        cls,
        *,
        line_number: int,
        record: PaymentRecoveryRecord,
        status: str,
        reason: str | None,
    ) -> PaymentReplayRecordReport:
        return cls(
            line_number=line_number,
            record_id=record.record_id,
            status=status,
            reason=reason,
            provider=record.provider,
            amount=record.total_amount,
            currency=record.currency,
            created_at=record.created_at,
            chat_id=redact_optional_identifier("chat", record.chat_id),
            user_id=redact_optional_identifier("user", record.user_id),
            telegram_payment_charge_id=redact_optional_identifier(
                "telegram_payment_charge",
                record.telegram_payment_charge_id,
            ),
            provider_payment_charge_id=redact_optional_identifier(
                "provider_payment_charge",
                record.provider_payment_charge_id,
            ),
            has_subscription_expiration_date=record.subscription_expiration_date is not None,
        )

    @classmethod
    def malformed(cls, *, line_number: int, reason: str) -> PaymentReplayRecordReport:
        return cls(
            line_number=line_number,
            record_id=None,
            status=STATUS_BLOCKED,
            reason="malformed_spool_record",
            detail=reason,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "line_number": self.line_number,
            "record_id": self.record_id,
            "status": self.status,
            "reason": self.reason,
        }
        optional_fields = {
            "provider": self.provider,
            "amount": self.amount,
            "currency": self.currency,
            "created_at": self.created_at,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "telegram_payment_charge_id": self.telegram_payment_charge_id,
            "provider_payment_charge_id": self.provider_payment_charge_id,
            "has_subscription_expiration_date": self.has_subscription_expiration_date,
            "detail": self.detail,
        }
        for key, value in optional_fields.items():
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class PaymentReplayReport:
    mode: str
    spool_path: Path
    spool_fingerprint: str
    db_validation_available: bool
    records: tuple[PaymentReplayRecordReport, ...]
    started_at: str
    finished_at: str

    @property
    def counts(self) -> dict[str, int]:
        counts = {
            "total": len(self.records),
            STATUS_LISTED: 0,
            STATUS_REPLAYABLE_CANDIDATE: 0,
            STATUS_ALREADY_RECOVERED: 0,
            STATUS_DB_VALIDATION_UNAVAILABLE: 0,
            STATUS_BLOCKED: 0,
        }
        for item in self.records:
            if item.status in counts:
                counts[item.status] += 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "spool": {
                "path": str(self.spool_path),
                "exists": self.spool_path.exists(),
                "bytes": self.spool_path.stat().st_size if self.spool_path.exists() else 0,
                "fingerprint": self.spool_fingerprint,
            },
            "db_validation_available": self.db_validation_available,
            "counts": self.counts,
            "records": [record.to_dict() for record in self.records],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class PaymentReplayApplyRecordResult:
    line_number: int | None
    record_id: str | None
    preflight_status: str
    apply_status: str
    reason: str | None
    timestamp: str
    provider: str | None = None
    amount: int | None = None
    currency: str | None = None
    chat_id: str | None = None
    user_id: str | None = None
    telegram_payment_charge_id: str | None = None
    provider_payment_charge_id: str | None = None

    @classmethod
    def from_preflight(
        cls,
        preflight: PaymentReplayRecordReport,
        *,
        apply_status: str,
        reason: str | None,
        timestamp: str,
    ) -> PaymentReplayApplyRecordResult:
        return cls(
            line_number=preflight.line_number,
            record_id=preflight.record_id,
            preflight_status=preflight.status,
            apply_status=apply_status,
            reason=_safe_result_reason(reason),
            timestamp=timestamp,
            provider=preflight.provider,
            amount=preflight.amount,
            currency=preflight.currency,
            chat_id=preflight.chat_id,
            user_id=preflight.user_id,
            telegram_payment_charge_id=preflight.telegram_payment_charge_id,
            provider_payment_charge_id=preflight.provider_payment_charge_id,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "timestamp": self.timestamp,
            "line_number": self.line_number,
            "record_id": self.record_id,
            "preflight_status": self.preflight_status,
            "apply_status": self.apply_status,
            "reason": self.reason,
        }
        optional_fields = {
            "provider": self.provider,
            "amount": self.amount,
            "currency": self.currency,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "telegram_payment_charge_id": self.telegram_payment_charge_id,
            "provider_payment_charge_id": self.provider_payment_charge_id,
        }
        for key, value in optional_fields.items():
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class PaymentReplayApplyReport:
    mode: str
    spool_path: Path
    spool_fingerprint: str
    result_jsonl_path: Path
    db_validation_available: bool
    preflight: PaymentReplayReport
    results: tuple[PaymentReplayApplyRecordResult, ...]
    started_at: str
    finished_at: str

    @property
    def counts(self) -> dict[str, int]:
        counts = {
            "total": len(self.results),
            APPLY_STATUS_RECOVERED: 0,
            APPLY_STATUS_ALREADY_RECOVERED: 0,
            APPLY_STATUS_BLOCKED: 0,
            APPLY_STATUS_APPLY_FAILED: 0,
        }
        for result in self.results:
            if result.apply_status in counts:
                counts[result.apply_status] += 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "spool": {
                "path": str(self.spool_path),
                "exists": self.spool_path.exists(),
                "bytes": self.spool_path.stat().st_size if self.spool_path.exists() else 0,
                "fingerprint": self.spool_fingerprint,
            },
            "result_jsonl": {"path": str(self.result_jsonl_path)},
            "db_validation_available": self.db_validation_available,
            "counts": self.counts,
            "results": [result.to_dict() for result in self.results],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class _ParsedRecord:
    line_number: int
    record: PaymentRecoveryRecord


@dataclass(frozen=True)
class _MalformedRecord:
    line_number: int
    reason: str


def list_spool(path: str | Path) -> PaymentReplayReport:
    started_at = _now_iso()
    spool_path = _require_spool(path)
    parsed = _parse_spool(spool_path)
    reports = [
        PaymentReplayRecordReport.malformed(line_number=item.line_number, reason=item.reason)
        if isinstance(item, _MalformedRecord)
        else PaymentReplayRecordReport.from_record(
            line_number=item.line_number,
            record=item.record,
            status=STATUS_LISTED,
            reason=None,
        )
        for item in parsed
    ]
    return PaymentReplayReport(
        mode="list",
        spool_path=spool_path,
        spool_fingerprint=_spool_fingerprint(spool_path),
        db_validation_available=False,
        records=tuple(reports),
        started_at=started_at,
        finished_at=_now_iso(),
    )


def dry_run_spool(path: str | Path, *, lookup: PaymentReplayLookup | None = None) -> PaymentReplayReport:
    started_at = _now_iso()
    spool_path = _require_spool(path)
    parsed = _parse_spool(spool_path)
    conflict_ids = _conflicting_duplicate_record_ids(
        item for item in parsed if isinstance(item, _ParsedRecord)
    )
    reports: list[PaymentReplayRecordReport] = []
    for item in parsed:
        if isinstance(item, _MalformedRecord):
            reports.append(PaymentReplayRecordReport.malformed(line_number=item.line_number, reason=item.reason))
            continue
        record = item.record
        if record.record_id in conflict_ids:
            reports.append(
                PaymentReplayRecordReport.from_record(
                    line_number=item.line_number,
                    record=record,
                    status=STATUS_BLOCKED,
                    reason="duplicate_record_id_conflict",
                )
            )
            continue
        if lookup is None:
            reports.append(
                PaymentReplayRecordReport.from_record(
                    line_number=item.line_number,
                    record=record,
                    status=STATUS_DB_VALIDATION_UNAVAILABLE,
                    reason="db_validation_unavailable",
                )
            )
            continue
        status, reason = _validate_record_against_lookup(record, lookup)
        reports.append(
            PaymentReplayRecordReport.from_record(
                line_number=item.line_number,
                record=record,
                status=status,
                reason=reason,
            )
        )

    return PaymentReplayReport(
        mode="dry_run",
        spool_path=spool_path,
        spool_fingerprint=_spool_fingerprint(spool_path),
        db_validation_available=lookup is not None,
        records=tuple(reports),
        started_at=started_at,
        finished_at=_now_iso(),
    )


def apply_spool(
    path: str | Path,
    *,
    lookup: PaymentReplayLookup,
    payment_service: PaymentReplayPaymentService,
    expected_spool_fingerprint: str | None,
    result_jsonl: str | Path,
) -> PaymentReplayApplyReport:
    started_at = _now_iso()
    spool_path = _require_spool(path)
    spool_fingerprint = _spool_fingerprint(spool_path)
    _validate_expected_fingerprint_value(
        spool_fingerprint,
        expected_spool_fingerprint,
        required=True,
    )
    result_path = Path(result_jsonl)
    _validate_result_jsonl_path(spool_path, result_path)

    preflight = dry_run_spool(spool_path, lookup=lookup)
    parsed_by_record_id = _deduped_parsed_records_by_id(_parse_spool(spool_path))
    seen_keys: set[str] = set()
    results: list[PaymentReplayApplyRecordResult] = []
    for preflight_record in preflight.records:
        key = _preflight_result_key(preflight_record)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        timestamp = _now_iso()
        parsed = parsed_by_record_id.get(preflight_record.record_id or "")
        if preflight_record.status == STATUS_REPLAYABLE_CANDIDATE and parsed is not None:
            apply_status, reason = _apply_replayable_record(parsed.record, lookup, payment_service)
        elif preflight_record.status == STATUS_ALREADY_RECOVERED:
            apply_status = APPLY_STATUS_ALREADY_RECOVERED
            reason = preflight_record.reason
        else:
            apply_status = APPLY_STATUS_BLOCKED
            reason = preflight_record.reason or preflight_record.status
        results.append(
            PaymentReplayApplyRecordResult.from_preflight(
                preflight_record,
                apply_status=apply_status,
                reason=reason,
                timestamp=timestamp,
            )
        )

    _append_apply_results(result_path, results)
    return PaymentReplayApplyReport(
        mode="apply",
        spool_path=spool_path,
        spool_fingerprint=spool_fingerprint,
        result_jsonl_path=result_path,
        db_validation_available=True,
        preflight=preflight,
        results=tuple(results),
        started_at=started_at,
        finished_at=_now_iso(),
    )


def render_human(report: PaymentReplayReport) -> str:
    counts = report.counts
    lines = [
        (
            f"mode={report.mode} records={counts['total']} blocked={counts[STATUS_BLOCKED]} "
            f"replayable_candidate={counts[STATUS_REPLAYABLE_CANDIDATE]} "
            f"already_recovered={counts[STATUS_ALREADY_RECOVERED]} "
            f"db_validation_available={str(report.db_validation_available).lower()}"
        )
    ]
    for item in report.records:
        fields = [
            f"line={item.line_number}",
            f"record_id={item.record_id or 'unavailable'}",
            f"status={item.status}",
        ]
        if item.reason:
            fields.append(f"reason={item.reason}")
        if item.provider:
            fields.append(f"provider={item.provider}")
        if item.amount is not None:
            fields.append(f"amount={item.amount}")
        if item.currency:
            fields.append(f"currency={item.currency}")
        if item.chat_id:
            fields.append(f"chat_id={item.chat_id}")
        if item.user_id:
            fields.append(f"user_id={item.user_id}")
        if item.telegram_payment_charge_id:
            fields.append(f"telegram_payment_charge_id={item.telegram_payment_charge_id}")
        if item.provider_payment_charge_id:
            fields.append(f"provider_payment_charge_id={item.provider_payment_charge_id}")
        lines.append(" ".join(fields))
    return "\n".join(lines) + "\n"


def render_apply_human(report: PaymentReplayApplyReport) -> str:
    counts = report.counts
    lines = [
        (
            f"mode={report.mode} records={counts['total']} "
            f"recovered={counts[APPLY_STATUS_RECOVERED]} "
            f"already_recovered={counts[APPLY_STATUS_ALREADY_RECOVERED]} "
            f"blocked={counts[APPLY_STATUS_BLOCKED]} "
            f"apply_failed={counts[APPLY_STATUS_APPLY_FAILED]} "
            f"db_validation_available={str(report.db_validation_available).lower()}"
        )
    ]
    for item in report.results:
        fields = [
            f"line={item.line_number}",
            f"record_id={item.record_id or 'unavailable'}",
            f"preflight_status={item.preflight_status}",
            f"apply_status={item.apply_status}",
        ]
        if item.reason:
            fields.append(f"reason={item.reason}")
        if item.provider:
            fields.append(f"provider={item.provider}")
        if item.amount is not None:
            fields.append(f"amount={item.amount}")
        if item.currency:
            fields.append(f"currency={item.currency}")
        if item.chat_id:
            fields.append(f"chat_id={item.chat_id}")
        if item.user_id:
            fields.append(f"user_id={item.user_id}")
        if item.telegram_payment_charge_id:
            fields.append(f"telegram_payment_charge_id={item.telegram_payment_charge_id}")
        if item.provider_payment_charge_id:
            fields.append(f"provider_payment_charge_id={item.provider_payment_charge_id}")
        lines.append(" ".join(fields))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or apply payment recovery spool records.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("list", "dry-run"):
        subparser = subparsers.add_parser(mode)
        subparser.add_argument("--spool", required=True, type=Path)
        subparser.add_argument("--expected-spool-fingerprint")
        subparser.add_argument("--json", action="store_true", dest="json_output")
        if mode == "dry-run":
            subparser.add_argument("--database-url")
            subparser.add_argument("--database-url-env", default=DEFAULT_DATABASE_URL_ENV)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--spool", required=True, type=Path)
    apply_parser.add_argument("--database-url")
    apply_parser.add_argument("--database-url-env", default=DEFAULT_DATABASE_URL_ENV)
    apply_parser.add_argument("--expected-spool-fingerprint")
    apply_parser.add_argument("--result-jsonl", type=Path)
    apply_parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    source_env = dict(os.environ if env is None else env)

    try:
        if args.mode == "list":
            report = list_spool(args.spool)
            _validate_expected_fingerprint(report, args.expected_spool_fingerprint)
            if args.json_output:
                print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_human(report), end="")
            return _exit_code(report)
        if args.mode == "dry-run":
            database_url = args.database_url or source_env.get(args.database_url_env)
            lookup = _build_postgres_lookup(database_url) if database_url else None
            report = dry_run_spool(args.spool, lookup=lookup)
            _validate_expected_fingerprint(report, args.expected_spool_fingerprint)
            if args.json_output:
                print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_human(report), end="")
            return _exit_code(report)

        result_path = _require_result_jsonl_arg(args.result_jsonl)
        spool_path = _require_spool(args.spool)
        spool_fingerprint = _spool_fingerprint(spool_path)
        _validate_expected_fingerprint_value(
            spool_fingerprint,
            args.expected_spool_fingerprint,
            required=True,
        )
        database_url = args.database_url or source_env.get(args.database_url_env)
        if not database_url:
            raise PaymentReplayUsageError(
                f"database URL is required for apply; pass --database-url or set {args.database_url_env}",
            )
        lookup = _build_postgres_lookup(database_url)
        payment_service = _build_payment_service(lookup)
        apply_report = apply_spool(
            spool_path,
            lookup=lookup,
            payment_service=payment_service,
            expected_spool_fingerprint=spool_fingerprint,
            result_jsonl=result_path,
        )
    except PaymentReplayUsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print("payment recovery replay failed; details redacted.", file=sys.stderr)
        return 3

    if args.json_output:
        print(json.dumps(apply_report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_apply_human(apply_report), end="")
    return _exit_code(apply_report)


def _build_postgres_lookup(database_url: str) -> PaymentReplayLookup:
    from .postgres_payment_store import PostgresPaymentStore

    return PostgresPaymentStore(database_url)


def _build_payment_service(repository: PaymentReplayLookup) -> PaymentReplayPaymentService:
    from .payment_service import PaymentService

    return PaymentService(repository)  # type: ignore[arg-type]


def _validate_record_against_lookup(
    record: PaymentRecoveryRecord,
    lookup: PaymentReplayLookup,
) -> tuple[str, str]:
    try:
        decoded = decode_payment_order_payload(record.invoice_payload)
    except PaymentPayloadError:
        return STATUS_BLOCKED, "invalid_invoice_payload"
    if decoded is None:
        return STATUS_BLOCKED, "invalid_invoice_payload"

    order = lookup.get_order(decoded.order_id)
    if order is None:
        return STATUS_BLOCKED, "order_not_found"
    mismatch = _record_order_mismatch(record, order, decoded_nonce=decoded.nonce)
    if mismatch is not None:
        return STATUS_BLOCKED, mismatch

    existing_charge = lookup.find_charge_by_external_id(
        provider=record.provider,
        telegram_payment_charge_id=record.telegram_payment_charge_id,
        provider_payment_charge_id=record.provider_payment_charge_id,
    )
    if existing_charge is not None:
        if not _charge_matches_record_and_order(existing_charge, record, order):
            return STATUS_BLOCKED, "charge_id_collision_context_mismatch"
        if order.status == ORDER_STATUS_GRANTED:
            return STATUS_ALREADY_RECOVERED, "exact_charge_already_granted"
        return STATUS_BLOCKED, "charge_already_recorded_without_grant"

    if order.status == ORDER_STATUS_PENDING:
        if order.product == PRODUCT_SUBSCRIPTION_MONTH and record.subscription_expiration_date is None:
            return STATUS_BLOCKED, "subscription_replay_timing_unavailable"
        return STATUS_REPLAYABLE_CANDIDATE, "pending_order_matches_spool_record"
    if order.status == ORDER_STATUS_GRANTED:
        return STATUS_BLOCKED, "order_already_granted_with_different_charge"
    return STATUS_BLOCKED, "order_not_pending"


def _apply_replayable_record(
    record: PaymentRecoveryRecord,
    lookup: PaymentReplayLookup,
    payment_service: PaymentReplayPaymentService,
) -> tuple[str, str]:
    result = payment_service.handle_successful_payment(
        payload=record.invoice_payload,
        user_id=record.user_id,
        chat_id=record.chat_id,
        provider=record.provider,
        amount=record.total_amount,
        currency=record.currency,
        telegram_payment_charge_id=record.telegram_payment_charge_id,
        provider_payment_charge_id=record.provider_payment_charge_id,
        raw_payload=_apply_raw_payload(record),
    )
    if result.processed:
        return APPLY_STATUS_RECOVERED, "processed_successfully"
    if result.duplicate:
        post_status, post_reason = _validate_record_against_lookup(record, lookup)
        if post_status == STATUS_ALREADY_RECOVERED:
            return APPLY_STATUS_RECOVERED, post_reason
        return APPLY_STATUS_APPLY_FAILED, result.reason or post_reason or "duplicate_not_exactly_recovered"
    return APPLY_STATUS_APPLY_FAILED, result.reason or "payment_service_rejected"


def _apply_raw_payload(record: PaymentRecoveryRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "payment_recovery_replay": True,
        "payment_recovery_record_id": record.record_id or "",
        "payment_recovery_record_created_at": record.created_at,
    }
    if record.subscription_expiration_date is not None:
        payload["subscription_expiration_date"] = record.subscription_expiration_date
    return payload


def _record_order_mismatch(
    record: PaymentRecoveryRecord,
    order: PaymentOrder,
    *,
    decoded_nonce: str,
) -> str | None:
    if order.nonce != decoded_nonce:
        return "nonce_mismatch"
    if int(order.user_id) != int(record.user_id):
        return "user_mismatch"
    if int(order.chat_id) != int(record.chat_id):
        return "chat_mismatch"
    if order.provider != record.provider:
        return "provider_mismatch"
    if int(order.amount) != int(record.total_amount):
        return "amount_mismatch"
    if order.currency != record.currency:
        return "currency_mismatch"
    return None


def _charge_matches_record_and_order(
    charge: PaymentCharge,
    record: PaymentRecoveryRecord,
    order: PaymentOrder,
) -> bool:
    if record.telegram_payment_charge_id and charge.telegram_payment_charge_id != record.telegram_payment_charge_id:
        return False
    if record.provider_payment_charge_id and charge.provider_payment_charge_id != record.provider_payment_charge_id:
        return False
    return (
        charge.order_id == order.order_id
        and charge.provider == record.provider
        and int(charge.amount) == int(record.total_amount)
        and charge.currency == record.currency
    )


def _conflicting_duplicate_record_ids(records: Any) -> set[str]:
    contexts_by_id: dict[str, set[tuple[object, ...]]] = {}
    for parsed in records:
        record = parsed.record
        if record.record_id is None:
            continue
        contexts_by_id.setdefault(record.record_id, set()).add(_record_context(record))
    return {record_id for record_id, contexts in contexts_by_id.items() if len(contexts) > 1}


def _deduped_parsed_records_by_id(
    parsed: tuple[_ParsedRecord | _MalformedRecord, ...],
) -> dict[str, _ParsedRecord]:
    records: dict[str, _ParsedRecord] = {}
    for item in parsed:
        if isinstance(item, _MalformedRecord):
            continue
        record_id = item.record.record_id or ""
        if record_id and record_id not in records:
            records[record_id] = item
    return records


def _record_context(record: PaymentRecoveryRecord) -> tuple[object, ...]:
    return (
        record.provider,
        record.chat_id,
        record.user_id,
        record.invoice_payload,
        record.telegram_payment_charge_id,
        record.provider_payment_charge_id,
        record.currency,
        record.total_amount,
        record.subscription_expiration_date,
    )


def _parse_spool(path: Path) -> tuple[_ParsedRecord | _MalformedRecord, ...]:
    parsed: list[_ParsedRecord | _MalformedRecord] = []
    with path.open("r", encoding="utf-8") as spool:
        for line_number, line in enumerate(spool, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                _reject_unexpected_fields(payload)
                record = PaymentRecoveryRecord.from_dict(payload)
            except (json.JSONDecodeError, PaymentRecoveryRecordError, TypeError, ValueError) as exc:
                parsed.append(_MalformedRecord(line_number, _safe_malformed_reason(exc)))
                continue
            parsed.append(_ParsedRecord(line_number, record))
    return tuple(parsed)


def _reject_unexpected_fields(payload: object) -> None:
    if not isinstance(payload, Mapping):
        return
    if not set(payload).issubset(ALLOWED_SERIALIZED_FIELDS):
        raise PaymentRecoveryRecordError("record contains unsupported fields")


def _safe_malformed_reason(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "invalid JSON"
    if isinstance(exc, PaymentRecoveryRecordError):
        return str(exc)
    return "invalid payment recovery record"


def _require_spool(path: str | Path) -> Path:
    spool_path = Path(path)
    if not spool_path.exists():
        raise PaymentReplayUsageError(f"spool does not exist: {spool_path}")
    if not spool_path.is_file():
        raise PaymentReplayUsageError(f"spool is not a file: {spool_path}")
    return spool_path


def _require_result_jsonl_arg(path: Path | None) -> Path:
    if path is None:
        raise PaymentReplayUsageError("result JSONL path is required for apply")
    return path


def _validate_result_jsonl_path(spool_path: Path, result_path: Path) -> None:
    try:
        if spool_path.resolve() == result_path.resolve():
            raise PaymentReplayUsageError("result JSONL path must be different from spool path")
    except OSError as exc:
        raise PaymentReplayUsageError("could not validate result JSONL path") from exc


def _append_apply_results(
    result_path: Path,
    results: list[PaymentReplayApplyRecordResult],
) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with result_path.open("a", encoding="utf-8", newline="\n") as output:
        for result in results:
            output.write(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def _spool_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"payment-recovery-spool-v1\0")
    digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def _validate_expected_fingerprint(report: PaymentReplayReport, expected: str | None) -> None:
    _validate_expected_fingerprint_value(report.spool_fingerprint, expected, required=False)


def _validate_expected_fingerprint_value(actual: str, expected: str | None, *, required: bool) -> None:
    if expected is None or not expected.strip():
        if required:
            raise PaymentReplayUsageError("expected spool fingerprint is required for apply")
        return
    if _normalize_spool_fingerprint(expected) != actual.lower():
        raise PaymentReplayUsageError("spool fingerprint mismatch")


def _normalize_spool_fingerprint(value: str) -> str:
    text = value.strip().lower()
    if text.startswith("sha256:"):
        return text
    if re.fullmatch(r"[a-f0-9]{64}", text):
        return f"sha256:{text}"
    return text


def _safe_result_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    text = str(reason).strip()
    if not text:
        return None
    if _SAFE_REASON_RE.fullmatch(text):
        return text
    return "redacted_error"


def _preflight_result_key(record: PaymentReplayRecordReport) -> str:
    if record.record_id:
        return f"record:{record.record_id}"
    return f"line:{record.line_number}"


def _exit_code(report: PaymentReplayReport | PaymentReplayApplyReport) -> int:
    if isinstance(report, PaymentReplayApplyReport):
        if report.counts[APPLY_STATUS_BLOCKED] or report.counts[APPLY_STATUS_APPLY_FAILED]:
            return 1
        return 0
    if report.counts[STATUS_BLOCKED]:
        return 1
    return 0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
