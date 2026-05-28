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
from diet_bot.payment_recovery_spool import read_payment_recovery_records


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
    parser.add_argument("--format", choices=("table", "jsonl"), default="table")
    parser.add_argument("--fail-on-findings", action="store_true")
    args = parser.parse_args(argv)

    provider_rows = load_reconciliation_rows(args.provider_export)
    ledger_rows = load_reconciliation_rows(args.ledger_export)
    recovery_records = ()
    if args.recovery_spool is not None:
        recovery_records = read_payment_recovery_records(args.recovery_spool).records
    report = reconcile_payment_exports(provider_rows, ledger_rows, recovery_records=recovery_records)

    if args.format == "jsonl":
        print(render_reconciliation_jsonl(report), end="")
    else:
        print(render_reconciliation_table(report), end="")
    if args.fail_on_findings and report.has_findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
