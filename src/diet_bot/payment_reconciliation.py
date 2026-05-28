from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .log_redaction import redact_optional_identifier
from .payment_recovery_spool import PaymentRecoveryRecord
from .payments import ORDER_STATUS_GRANTED, PaymentPayloadError, decode_payment_order_payload


CATEGORY_MATCHED_PAID_GRANTED = "matched_paid_granted"
CATEGORY_CHARGE_ID_MISMATCH = "charge_id_mismatch"
CATEGORY_CHARGED_BUT_NOT_GRANTED = "charged_but_not_granted"
CATEGORY_GRANTED_BUT_NO_PROVIDER_CHARGE = "granted_but_no_provider_charge"
CATEGORY_DUPLICATE_PROVIDER_CHARGE_ORDER = "duplicate_provider_charge_order"
CATEGORY_RECOVERY_SPOOL_CANDIDATE = "recovery_spool_candidate"

RECONCILIATION_CATEGORIES = (
    CATEGORY_MATCHED_PAID_GRANTED,
    CATEGORY_CHARGE_ID_MISMATCH,
    CATEGORY_CHARGED_BUT_NOT_GRANTED,
    CATEGORY_GRANTED_BUT_NO_PROVIDER_CHARGE,
    CATEGORY_DUPLICATE_PROVIDER_CHARGE_ORDER,
    CATEGORY_RECOVERY_SPOOL_CANDIDATE,
)


@dataclass(frozen=True)
class PaymentReconciliationItem:
    category: str
    provider: str | None = None
    reason: str | None = None
    order_id: str | None = None
    telegram_payment_charge_id: str | None = None
    provider_payment_charge_id: str | None = None
    amount: int | None = None
    currency: str | None = None
    order_status: str | None = None
    ledger_telegram_payment_charge_id: str | None = None
    ledger_provider_payment_charge_id: str | None = None
    ledger_amount: int | None = None
    ledger_currency: str | None = None
    ledger_order_status: str | None = None
    amount_matches: bool | None = None
    currency_matches: bool | None = None
    charge_id_mismatch_fields: tuple[str, ...] = ()
    provider_charge_count: int | None = None
    recovery_record_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"category": self.category}
        optional_fields: dict[str, object | None] = {
            "provider": self.provider,
            "reason": self.reason,
            "order_id": redact_optional_identifier("order", self.order_id),
            "telegram_payment_charge_id": redact_optional_identifier(
                "telegram_payment_charge",
                self.telegram_payment_charge_id,
            ),
            "provider_payment_charge_id": redact_optional_identifier(
                "provider_payment_charge",
                self.provider_payment_charge_id,
            ),
            "amount": self.amount,
            "currency": self.currency,
            "order_status": self.order_status,
            "ledger_telegram_payment_charge_id": redact_optional_identifier(
                "telegram_payment_charge",
                self.ledger_telegram_payment_charge_id,
            ),
            "ledger_provider_payment_charge_id": redact_optional_identifier(
                "provider_payment_charge",
                self.ledger_provider_payment_charge_id,
            ),
            "ledger_amount": self.ledger_amount,
            "ledger_currency": self.ledger_currency,
            "ledger_order_status": self.ledger_order_status,
            "amount_matches": self.amount_matches,
            "currency_matches": self.currency_matches,
            "provider_charge_count": self.provider_charge_count,
            "recovery_record_id": self.recovery_record_id,
        }
        for key, value in optional_fields.items():
            if value is not None:
                payload[key] = value
        if self.charge_id_mismatch_fields:
            payload["charge_id_mismatch_fields"] = list(self.charge_id_mismatch_fields)
        return payload


@dataclass(frozen=True)
class PaymentReconciliationReport:
    items: tuple[PaymentReconciliationItem, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts = {category: 0 for category in RECONCILIATION_CATEGORIES}
        counts["total"] = len(self.items)
        for item in self.items:
            counts[item.category] = counts.get(item.category, 0) + 1
        return counts

    @property
    def has_findings(self) -> bool:
        return any(item.category != CATEGORY_MATCHED_PAID_GRANTED for item in self.items)


@dataclass(frozen=True)
class _PaymentExportRow:
    provider: str | None
    order_id: str | None
    telegram_payment_charge_id: str | None
    provider_payment_charge_id: str | None
    amount: int | None
    currency: str | None
    status: str | None

    @property
    def external_key(self) -> tuple[str, str, str] | None:
        if self.provider and self.telegram_payment_charge_id:
            return (self.provider, "telegram", self.telegram_payment_charge_id)
        if self.provider and self.provider_payment_charge_id:
            return (self.provider, "provider", self.provider_payment_charge_id)
        return None

    @property
    def order_key(self) -> tuple[str, str] | None:
        if self.provider and self.order_id:
            return (self.provider, self.order_id)
        return None


def reconcile_payment_exports(
    provider_rows: Sequence[Mapping[str, object]],
    ledger_rows: Sequence[Mapping[str, object]],
    *,
    recovery_records: Sequence[PaymentRecoveryRecord] = (),
) -> PaymentReconciliationReport:
    provider_charges = [_provider_row(row) for row in provider_rows]
    ledger_entries = [_ledger_row(row) for row in ledger_rows]
    ledger_by_external = _rows_by_external_key(ledger_entries)
    ledger_by_order = _rows_by_order_key(ledger_entries)
    provider_by_external = _rows_by_external_key(provider_charges)
    provider_by_order = _rows_by_order_key(provider_charges)

    items: list[PaymentReconciliationItem] = []
    items.extend(_duplicate_provider_items(provider_by_external, provider_by_order))
    for charge in provider_charges:
        matches = _matching_rows(charge, ledger_by_external, ledger_by_order)
        exact_granted = [ledger for ledger in matches if _is_exact_granted_match(charge, ledger)]
        if exact_granted:
            items.append(_item(CATEGORY_MATCHED_PAID_GRANTED, charge, reason="provider_charge_matches_grant"))
        elif charge_id_mismatch := _first_charge_id_mismatch(charge, matches):
            ledger, mismatch_fields = charge_id_mismatch
            items.append(_charge_id_mismatch_item(charge, ledger, mismatch_fields))
        else:
            reason = "provider_charge_missing_ledger" if not matches else _not_granted_reason(matches)
            items.append(_item(CATEGORY_CHARGED_BUT_NOT_GRANTED, charge, reason=reason))

    for ledger in ledger_entries:
        if ledger.status != ORDER_STATUS_GRANTED:
            continue
        if _matching_rows(ledger, provider_by_external, provider_by_order):
            continue
        items.append(_item(CATEGORY_GRANTED_BUT_NO_PROVIDER_CHARGE, ledger, reason="ledger_grant_missing_provider_charge"))

    for record in recovery_records:
        spool_row = _spool_row(record)
        matches = _matching_rows(spool_row, ledger_by_external, ledger_by_order)
        if any(_is_exact_granted_match(spool_row, ledger) for ledger in matches):
            continue
        items.append(
            _item(
                CATEGORY_RECOVERY_SPOOL_CANDIDATE,
                spool_row,
                reason="spool_record_not_granted",
                recovery_record_id=record.record_id,
            )
        )

    return PaymentReconciliationReport(items=tuple(items))


def load_reconciliation_rows(path: str | Path) -> list[dict[str, object]]:
    source = Path(path)
    if source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    payload = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(_require_mapping(row)) for row in payload]
    if isinstance(payload, Mapping):
        for key in ("rows", "charges", "provider_charges", "ledger", "ledger_rows"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(_require_mapping(row)) for row in rows]
    raise ValueError("reconciliation export must be a JSON array, known JSON object, or CSV file")


def render_reconciliation_jsonl(report: PaymentReconciliationReport) -> str:
    return "".join(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) + "\n" for item in report.items)


def render_reconciliation_table(report: PaymentReconciliationReport) -> str:
    fields = (
        "category",
        "provider",
        "order_id",
        "telegram_payment_charge_id",
        "provider_payment_charge_id",
        "ledger_telegram_payment_charge_id",
        "ledger_provider_payment_charge_id",
        "amount",
        "ledger_amount",
        "currency",
        "ledger_currency",
        "order_status",
        "ledger_order_status",
        "reason",
    )
    lines = [" ".join(fields)]
    for item in report.items:
        payload = item.to_dict()
        lines.append(" ".join(str(payload.get(key, "-")) for key in fields))
    return "\n".join(lines) + "\n"


def _provider_row(row: Mapping[str, object]) -> _PaymentExportRow:
    return _PaymentExportRow(
        provider=_optional_text(row.get("provider")),
        order_id=_optional_text(row.get("order_id")),
        telegram_payment_charge_id=_optional_text(row.get("telegram_payment_charge_id")),
        provider_payment_charge_id=_optional_text(row.get("provider_payment_charge_id")),
        amount=_optional_int(row.get("amount")),
        currency=_optional_text(row.get("currency")),
        status=_optional_text(row.get("status")),
    )


def _ledger_row(row: Mapping[str, object]) -> _PaymentExportRow:
    return _PaymentExportRow(
        provider=_optional_text(row.get("provider")),
        order_id=_optional_text(row.get("order_id")),
        telegram_payment_charge_id=_optional_text(row.get("telegram_payment_charge_id")),
        provider_payment_charge_id=_optional_text(row.get("provider_payment_charge_id")),
        amount=_optional_int(row.get("amount")),
        currency=_optional_text(row.get("currency")),
        status=_optional_text(row.get("order_status") or row.get("status")),
    )


def _spool_row(record: PaymentRecoveryRecord) -> _PaymentExportRow:
    order_id: str | None = None
    try:
        decoded = decode_payment_order_payload(record.invoice_payload)
    except PaymentPayloadError:
        decoded = None
    if decoded is not None:
        order_id = decoded.order_id
    return _PaymentExportRow(
        provider=record.provider,
        order_id=order_id,
        telegram_payment_charge_id=record.telegram_payment_charge_id,
        provider_payment_charge_id=record.provider_payment_charge_id,
        amount=record.total_amount,
        currency=record.currency,
        status=None,
    )


def _rows_by_external_key(rows: Sequence[_PaymentExportRow]) -> dict[tuple[str, str, str], list[_PaymentExportRow]]:
    groups: dict[tuple[str, str, str], list[_PaymentExportRow]] = defaultdict(list)
    for row in rows:
        if row.external_key is not None:
            groups[row.external_key].append(row)
    return groups


def _rows_by_order_key(rows: Sequence[_PaymentExportRow]) -> dict[tuple[str, str], list[_PaymentExportRow]]:
    groups: dict[tuple[str, str], list[_PaymentExportRow]] = defaultdict(list)
    for row in rows:
        if row.order_key is not None:
            groups[row.order_key].append(row)
    return groups


def _duplicate_provider_items(
    by_external: Mapping[tuple[str, str, str], list[_PaymentExportRow]],
    by_order: Mapping[tuple[str, str], list[_PaymentExportRow]],
) -> tuple[PaymentReconciliationItem, ...]:
    items: list[PaymentReconciliationItem] = []
    for rows in by_external.values():
        if len(rows) > 1:
            items.append(
                _item(
                    CATEGORY_DUPLICATE_PROVIDER_CHARGE_ORDER,
                    rows[0],
                    reason="duplicate_provider_charge_id",
                    provider_charge_count=len(rows),
                )
            )
    for rows in by_order.values():
        if len(rows) > 1:
            items.append(
                _item(
                    CATEGORY_DUPLICATE_PROVIDER_CHARGE_ORDER,
                    rows[0],
                    reason="duplicate_provider_order_id",
                    provider_charge_count=len(rows),
                )
            )
    return tuple(items)


def _matching_rows(
    row: _PaymentExportRow,
    by_external: Mapping[tuple[str, str, str], list[_PaymentExportRow]],
    by_order: Mapping[tuple[str, str], list[_PaymentExportRow]],
) -> tuple[_PaymentExportRow, ...]:
    if row.external_key is not None and row.external_key in by_external:
        return tuple(by_external[row.external_key])
    if row.order_key is not None and row.order_key in by_order:
        return tuple(by_order[row.order_key])
    return ()


def _is_exact_granted_match(left: _PaymentExportRow, right: _PaymentExportRow) -> bool:
    return (
        right.status == ORDER_STATUS_GRANTED
        and left.provider == right.provider
        and _same_optional_int(left.amount, right.amount)
        and _same_optional_text(left.currency, right.currency)
        and _charge_ids_compatible(left, right)
    )


def _first_charge_id_mismatch(
    row: _PaymentExportRow,
    matches: Sequence[_PaymentExportRow],
) -> tuple[_PaymentExportRow, tuple[str, ...]] | None:
    for match in matches:
        mismatch_fields = _charge_id_mismatch_fields(row, match)
        if mismatch_fields:
            return match, mismatch_fields
    return None


def _charge_id_mismatch_fields(left: _PaymentExportRow, right: _PaymentExportRow) -> tuple[str, ...]:
    fields: list[str] = []
    if (
        left.telegram_payment_charge_id
        and right.telegram_payment_charge_id
        and left.telegram_payment_charge_id != right.telegram_payment_charge_id
    ):
        fields.append("telegram_payment_charge_id")
    if (
        left.provider_payment_charge_id
        and right.provider_payment_charge_id
        and left.provider_payment_charge_id != right.provider_payment_charge_id
    ):
        fields.append("provider_payment_charge_id")
    return tuple(fields)


def _charge_ids_compatible(left: _PaymentExportRow, right: _PaymentExportRow) -> bool:
    return not _charge_id_mismatch_fields(left, right)


def _charge_id_mismatch_reason(fields: Sequence[str]) -> str:
    if len(fields) == 1:
        return f"{fields[0]}_mismatch"
    return "multiple_charge_id_mismatches"


def _not_granted_reason(matches: Sequence[_PaymentExportRow]) -> str:
    statuses = Counter(row.status or "missing_status" for row in matches)
    if ORDER_STATUS_GRANTED in statuses:
        return "ledger_context_mismatch"
    if len(statuses) == 1:
        return f"ledger_order_{next(iter(statuses))}"
    return "ledger_order_not_granted"


def _item(
    category: str,
    row: _PaymentExportRow,
    *,
    reason: str,
    provider_charge_count: int | None = None,
    recovery_record_id: str | None = None,
) -> PaymentReconciliationItem:
    return PaymentReconciliationItem(
        category=category,
        provider=row.provider,
        reason=reason,
        order_id=row.order_id,
        telegram_payment_charge_id=row.telegram_payment_charge_id,
        provider_payment_charge_id=row.provider_payment_charge_id,
        amount=row.amount,
        currency=row.currency,
        order_status=row.status,
        provider_charge_count=provider_charge_count,
        recovery_record_id=recovery_record_id,
    )


def _charge_id_mismatch_item(
    provider_row: _PaymentExportRow,
    ledger_row: _PaymentExportRow,
    mismatch_fields: Sequence[str],
) -> PaymentReconciliationItem:
    return PaymentReconciliationItem(
        category=CATEGORY_CHARGE_ID_MISMATCH,
        provider=provider_row.provider,
        reason=_charge_id_mismatch_reason(mismatch_fields),
        order_id=provider_row.order_id,
        telegram_payment_charge_id=provider_row.telegram_payment_charge_id,
        provider_payment_charge_id=provider_row.provider_payment_charge_id,
        amount=provider_row.amount,
        currency=provider_row.currency,
        order_status=provider_row.status,
        ledger_telegram_payment_charge_id=ledger_row.telegram_payment_charge_id,
        ledger_provider_payment_charge_id=ledger_row.provider_payment_charge_id,
        ledger_amount=ledger_row.amount,
        ledger_currency=ledger_row.currency,
        ledger_order_status=ledger_row.status,
        amount_matches=_same_optional_int(provider_row.amount, ledger_row.amount),
        currency_matches=_same_optional_text(provider_row.currency, ledger_row.currency),
        charge_id_mismatch_fields=tuple(mismatch_fields),
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _same_optional_int(left: int | None, right: int | None) -> bool:
    return left is None or right is None or left == right


def _same_optional_text(left: str | None, right: str | None) -> bool:
    return left is None or right is None or left == right


def _require_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("reconciliation rows must be objects")
    return value
