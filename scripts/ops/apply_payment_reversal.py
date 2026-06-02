from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from diet_bot.log_redaction import redact_optional_identifier
from diet_bot.payment_service import PaymentService
from diet_bot.payments import (
    CHARGE_STATUS_CANCELED,
    CHARGE_STATUS_REFUNDED,
    PaymentCharge,
    PaymentReversalResult,
)


DEFAULT_DATABASE_URL_ENV = "DIET_BOT_DATABASE_URL"
MODE = "payment_reversal_operator_apply"

_KIND_TO_REVERSAL_STATUS = {
    "refund": "refunded",
    "refunded": "refunded",
    "cancel": "canceled",
    "canceled": "canceled",
    "reversal": "reversed",
    "reversed": "reversed",
    "chargeback": "chargeback",
}


class PaymentReversalOperatorStore(Protocol):
    def find_charge_by_external_id(
        self,
        *,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
    ) -> PaymentCharge | None:
        ...

    def find_charge_by_order_id(self, order_id: str) -> PaymentCharge | None:
        ...

    def record_payment_reversal(
        self,
        *,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
        reversal_status: str,
        amount: int | None = None,
        currency: str | None = None,
        raw_payload: dict[str, object] | None = None,
        now: datetime | None = None,
    ) -> PaymentReversalResult:
        ...


StoreFactory = Callable[[str], PaymentReversalOperatorStore]


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
        _validate_identifier_args(args, parser)
        event_time = _parse_event_timestamp(args.event_timestamp)
    except _ParserExit as exc:
        return exc.status
    except ValueError as exc:
        print(str(exc), file=stderr)
        return 2

    source_env = os.environ if env is None else env
    database_url = source_env.get(args.database_url_env)
    if not database_url:
        print(f"Set {args.database_url_env} to apply payment reversal events.", file=stderr)
        return 2

    factory = _default_store_factory if store_factory is None else store_factory
    reversal_status = _KIND_TO_REVERSAL_STATUS[args.kind]
    try:
        store = factory(database_url)
        charge = _resolve_charge(store, args)
        if charge is None:
            _write_payload(
                _base_payload(args, action=_action(args), reversal_status=reversal_status, event_time=event_time)
                | {"status": "not_found"},
                stdout,
            )
            return 1
        if charge.provider != args.provider:
            _write_payload(
                _base_payload(args, action=_action(args), reversal_status=reversal_status, event_time=event_time)
                | {
                    "status": "provider_mismatch",
                    "charge": _charge_payload(charge),
                },
                stdout,
            )
            return 1

        if not args.apply:
            _write_payload(
                _dry_run_payload(
                    args,
                    charge,
                    reversal_status=reversal_status,
                    event_time=event_time,
                ),
                stdout,
            )
            return 0

        service = PaymentService(store)
        result = service.handle_payment_reversal(
            provider=args.provider,
            telegram_payment_charge_id=charge.telegram_payment_charge_id,
            provider_payment_charge_id=charge.provider_payment_charge_id,
            reversal_status=reversal_status,
            amount=args.amount,
            currency=args.currency,
            raw_payload=_raw_audit_payload(args, event_time),
            now=event_time,
        )
        status = _apply_status(result)
        _write_payload(
            _base_payload(args, action="apply", reversal_status=reversal_status, event_time=event_time)
            | {
                "status": status,
                "charge": _charge_payload(charge),
                "result": _result_payload(result),
            },
            stdout,
        )
        return 0 if status in {"applied", "manual_review", "duplicate"} else 1
    except Exception:
        print("Failed to apply payment reversal; database details redacted.", file=stderr)
        return 2


def _default_store_factory(database_url: str) -> PaymentReversalOperatorStore:
    from diet_bot.postgres_payment_store import PostgresPaymentStore

    return PostgresPaymentStore(database_url)


def _build_parser(stderr: TextIO) -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description=(
            "Safely dry-run or apply a verified provider refund/cancel/reversal event "
            "to the local payment ledger and entitlement state. This command never calls "
            "a payment provider API."
        ),
        stderr=stderr,
    )
    parser.add_argument(
        "--database-url-env",
        default=DEFAULT_DATABASE_URL_ENV,
        help="Environment variable containing the Postgres DSN.",
    )
    parser.add_argument("--provider", required=True, type=_non_empty_text)
    parser.add_argument("--telegram-payment-charge-id", type=_optional_identifier)
    parser.add_argument(
        "--provider-payment-id",
        "--provider-payment-charge-id",
        dest="provider_payment_charge_id",
        type=_optional_identifier,
    )
    parser.add_argument("--order-id", type=_optional_identifier)
    parser.add_argument("--kind", required=True, choices=tuple(_KIND_TO_REVERSAL_STATUS))
    parser.add_argument("--event-timestamp", required=True, type=_non_empty_text)
    parser.add_argument("--amount", type=_non_negative_int)
    parser.add_argument("--currency", type=_optional_identifier)
    parser.add_argument("--reason", type=_non_empty_text)
    parser.add_argument("--operator", type=_non_empty_text)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview the local mutation without writing.")
    mode.add_argument("--apply", action="store_true", help="Apply the verified reversal to local state.")
    return parser


def _validate_identifier_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.telegram_payment_charge_id or args.provider_payment_charge_id or args.order_id:
        return
    parser.error(
        "identifier required: pass --telegram-payment-charge-id, --provider-payment-id, "
        "--provider-payment-charge-id, or --order-id"
    )


def _resolve_charge(store: PaymentReversalOperatorStore, args: argparse.Namespace) -> PaymentCharge | None:
    if args.telegram_payment_charge_id or args.provider_payment_charge_id:
        charge = store.find_charge_by_external_id(
            provider=args.provider,
            telegram_payment_charge_id=args.telegram_payment_charge_id,
            provider_payment_charge_id=args.provider_payment_charge_id,
        )
        if charge is not None:
            return charge
    if args.order_id:
        finder = getattr(store, "find_charge_by_order_id", None)
        if callable(finder):
            return finder(args.order_id)
    return None


def _dry_run_payload(
    args: argparse.Namespace,
    charge: PaymentCharge,
    *,
    reversal_status: str,
    event_time: datetime,
) -> dict[str, object]:
    charge_status = _ledger_charge_status_for_reversal(reversal_status)
    duplicate = charge.status == charge_status
    reason = _payment_reversal_context_mismatch_reason(charge, amount=args.amount, currency=args.currency)
    manual_review_required = reason is not None or charge.order_id is None
    if charge.order_id is None and reason is None:
        reason = "order_not_found"

    if duplicate:
        status = "duplicate"
        entitlement_reversal = "already_applied"
    elif manual_review_required:
        status = "would_manual_review"
        entitlement_reversal = "skipped_mismatch" if reason in {"partial_refund_manual_review", "currency_mismatch"} else "skipped"
    else:
        status = "would_apply"
        entitlement_reversal = "will_apply"

    return _base_payload(args, action="dry_run", reversal_status=reversal_status, event_time=event_time) | {
        "status": status,
        "charge": _charge_payload(charge),
        "would": {
            "charge_status": charge_status,
            "order_failure_reason": _payment_reversal_order_failure_reason(
                reversal_status,
                manual_review_required=manual_review_required,
            ),
            "manual_review_required": manual_review_required,
            "reason": reason or "",
            "entitlement_reversal": entitlement_reversal,
        },
    }


def _base_payload(
    args: argparse.Namespace,
    *,
    action: str,
    reversal_status: str,
    event_time: datetime,
) -> dict[str, object]:
    return {
        "mode": MODE,
        "action": action,
        "provider": args.provider,
        "provider_event_kind": args.kind,
        "reversal_status": reversal_status,
        "event_timestamp": _format_datetime(event_time),
        "identifiers": {
            "order_id": redact_optional_identifier("order", args.order_id),
            "telegram_payment_charge_id": redact_optional_identifier(
                "telegram_payment_charge",
                args.telegram_payment_charge_id,
            ),
            "provider_payment_charge_id": redact_optional_identifier(
                "provider_payment_charge",
                args.provider_payment_charge_id,
            ),
        },
    }


def _charge_payload(charge: PaymentCharge) -> dict[str, object]:
    return {
        "order_id": redact_optional_identifier("order", charge.order_id),
        "telegram_payment_charge_id": redact_optional_identifier(
            "telegram_payment_charge",
            charge.telegram_payment_charge_id,
        ),
        "provider_payment_charge_id": redact_optional_identifier(
            "provider_payment_charge",
            charge.provider_payment_charge_id,
        ),
        "amount": charge.amount,
        "currency": charge.currency,
        "current_status": charge.status,
    }


def _result_payload(result: Any) -> dict[str, object]:
    return {
        "processed": bool(getattr(result, "processed", False)),
        "duplicate": bool(getattr(result, "duplicate", False)),
        "manual_review_required": bool(getattr(result, "manual_review_required", False)),
        "reason": getattr(result, "reason", None) or "",
        "order_id": redact_optional_identifier("order", getattr(result, "order_id", None)),
        "charge_status": getattr(result, "charge_status", None) or "",
    }


def _raw_audit_payload(args: argparse.Namespace, event_time: datetime) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_timestamp": _format_datetime(event_time),
        "provider_event_kind": args.kind,
        "source": "operator_apply_payment_reversal",
    }
    if args.reason:
        payload["operator_reason"] = args.reason
    if args.operator:
        payload["operator"] = args.operator
    return payload


def _apply_status(result: Any) -> str:
    if bool(getattr(result, "duplicate", False)):
        return "duplicate"
    if bool(getattr(result, "processed", False)) and bool(getattr(result, "manual_review_required", False)):
        return "manual_review"
    if bool(getattr(result, "processed", False)):
        return "applied"
    if getattr(result, "reason", None) == "charge_not_found":
        return "not_found"
    return "rejected"


def _action(args: argparse.Namespace) -> str:
    return "apply" if args.apply else "dry_run"


def _parse_event_timestamp(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("event-timestamp must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _non_empty_text(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise argparse.ArgumentTypeError("value must not be empty")
    return text


def _optional_identifier(value: str) -> str:
    return _non_empty_text(value)


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("amount must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("amount must be a non-negative integer")
    return parsed


def _ledger_charge_status_for_reversal(status: str) -> str:
    if status == "canceled":
        return CHARGE_STATUS_CANCELED
    return CHARGE_STATUS_REFUNDED


def _payment_reversal_order_failure_reason(status: str, *, manual_review_required: bool) -> str:
    base = {
        "refunded": "payment_refunded",
        "canceled": "payment_canceled",
        "reversed": "payment_reversed",
        "chargeback": "payment_chargeback",
    }.get(status, "payment_reversed")
    if manual_review_required:
        return f"{base}_manual_review"
    return base


def _payment_reversal_context_mismatch_reason(
    charge: PaymentCharge,
    *,
    amount: int | None,
    currency: str | None,
) -> str | None:
    if amount is not None and int(amount) != int(charge.amount):
        return "partial_refund_manual_review"
    if currency is not None and str(currency) != charge.currency:
        return "currency_mismatch"
    return None


def _write_payload(payload: dict[str, object], stdout: TextIO) -> None:
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
