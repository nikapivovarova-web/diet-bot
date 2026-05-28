from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from diet_bot.payment_reconciliation import (
    load_reconciliation_rows,
    reconcile_payment_exports,
    render_reconciliation_jsonl,
    render_reconciliation_table,
)
from diet_bot.log_redaction import redact_identifier
from diet_bot.payment_recovery_spool import PaymentRecoveryRecord, read_payment_recovery_records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a local fake/synthetic provider export with a local payment ledger export. "
            "This tool reads files only and never calls a payment provider API."
        ),
    )
    parser.add_argument("--provider-export", required=True, type=Path)
    parser.add_argument("--ledger-export", required=True, type=Path)
    parser.add_argument("--recovery-spool", type=Path)
    parser.add_argument("--allow-malformed-spool", action="store_true")
    parser.add_argument("--format", choices=("table", "jsonl"), default="table")
    parser.add_argument("--fail-on-findings", action="store_true")
    args = parser.parse_args(argv)

    provider_rows = load_reconciliation_rows(args.provider_export)
    ledger_rows = load_reconciliation_rows(args.ledger_export)
    recovery_records = ()
    if args.recovery_spool is not None:
        recovery_read = _read_explicit_recovery_spool(
            args.recovery_spool,
            allow_malformed=args.allow_malformed_spool,
        )
        if isinstance(recovery_read, int):
            return recovery_read
        recovery_records = recovery_read
    report = reconcile_payment_exports(provider_rows, ledger_rows, recovery_records=recovery_records)

    if args.format == "jsonl":
        print(render_reconciliation_jsonl(report), end="")
    else:
        print(render_reconciliation_table(report), end="")
    if args.fail_on_findings and report.has_findings:
        return 1
    return 0


def _read_explicit_recovery_spool(path: Path, *, allow_malformed: bool) -> tuple[PaymentRecoveryRecord, ...] | int:
    redacted_path = _redacted_path(path)
    if not path.exists():
        print(
            f"error: recovery spool does not exist; path={redacted_path}; "
            "verify the explicit --recovery-spool path before reconciling.",
            file=sys.stderr,
        )
        return 2
    if not path.is_file():
        print(
            f"error: recovery spool is not a file; path={redacted_path}; "
            "pass a JSONL recovery spool file.",
            file=sys.stderr,
        )
        return 2

    result = read_payment_recovery_records(path)
    malformed_count = len(result.malformed_lines)
    if malformed_count and not allow_malformed:
        print(
            f"error: malformed recovery spool lines; malformed_line_count={malformed_count}; "
            f"path={redacted_path}; rerun with --allow-malformed-spool only after operator review.",
            file=sys.stderr,
        )
        return 2
    if malformed_count:
        print(
            f"warning: malformed recovery spool lines ignored; malformed_line_count={malformed_count}; "
            f"path={redacted_path}",
            file=sys.stderr,
        )
    return result.records


def _redacted_path(path: Path) -> str:
    return redact_identifier("path", str(path))


if __name__ == "__main__":
    raise SystemExit(main())
