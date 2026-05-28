from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from diet_bot.payment_reconciliation import reconcile_payment_exports, render_reconciliation_jsonl
from diet_bot.payment_recovery_spool import PaymentRecoveryRecord
from diet_bot.payments import encode_payment_order_payload
from scripts.ops import payment_reconciliation_report


def test_reconciliation_categorizes_fake_provider_ledger_and_spool_without_raw_ids() -> None:
    provider_rows = [
        _provider_row("order_match01", "tg-match-raw", "provider-match-raw"),
        _provider_row("order_paid01", "tg-paid-raw", "provider-paid-raw"),
        _provider_row("order_missing", "tg-missing-raw", "provider-missing-raw"),
        _provider_row("order_dupe01", "tg-dupe-a-raw", "provider-dupe-a-raw"),
        _provider_row("order_dupe01", "tg-dupe-b-raw", "provider-dupe-b-raw"),
    ]
    ledger_rows = [
        _ledger_row("order_match01", "tg-match-raw", "provider-match-raw", order_status="granted"),
        _ledger_row("order_paid01", "tg-paid-raw", "provider-paid-raw", order_status="paid"),
        _ledger_row(
            "order_orphan1",
            "tg-orphan-ledger-raw",
            "provider-orphan-ledger-raw",
            order_status="granted",
        ),
    ]
    spool_record = _spool_record("order_paid01", "nonce_paid01", "tg-paid-raw", "provider-paid-raw")

    report = reconcile_payment_exports(provider_rows, ledger_rows, recovery_records=[spool_record])
    categories = [item.category for item in report.items]

    assert "matched_paid_granted" in categories
    assert "charged_but_not_granted" in categories
    assert "granted_but_no_provider_charge" in categories
    assert "duplicate_provider_charge_order" in categories
    assert "recovery_spool_candidate" in categories
    assert report.counts["matched_paid_granted"] == 1
    assert report.counts["charged_but_not_granted"] == 4
    assert report.counts["granted_but_no_provider_charge"] == 1
    assert report.counts["duplicate_provider_charge_order"] == 1
    assert report.counts["recovery_spool_candidate"] == 1

    rendered = render_reconciliation_jsonl(report)
    for raw in (
        "order_match01",
        "order_paid01",
        "tg-match-raw",
        "provider-match-raw",
        "tg-paid-raw",
        "provider-paid-raw",
        "707070",
        "808080",
        encode_payment_order_payload("order_paid01", "nonce_paid01"),
    ):
        assert raw not in rendered


def test_reconciliation_cli_accepts_csv_json_spool_and_outputs_redacted_jsonl(
    tmp_path: Path,
    capsys,
) -> None:
    provider_csv = tmp_path / "provider.csv"
    ledger_json = tmp_path / "ledger.json"
    spool = tmp_path / "spool.jsonl"

    with provider_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "provider",
                "order_id",
                "telegram_payment_charge_id",
                "provider_payment_charge_id",
                "amount",
                "currency",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerow(_provider_row("order_paid01", "tg-paid-raw", "provider-paid-raw"))
    ledger_json.write_text(
        json.dumps([_ledger_row("order_paid01", "tg-paid-raw", "provider-paid-raw", order_status="paid")]),
        encoding="utf-8",
    )
    spool.write_text(_spool_record("order_paid01", "nonce_paid01", "tg-paid-raw", "provider-paid-raw").to_json_line())

    exit_code = payment_reconciliation_report.main(
        [
            "--provider-export",
            str(provider_csv),
            "--ledger-export",
            str(ledger_json),
            "--recovery-spool",
            str(spool),
            "--format",
            "jsonl",
        ],
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "charged_but_not_granted" in output
    assert "recovery_spool_candidate" in output
    assert "tg-paid-raw" not in output
    assert "provider-paid-raw" not in output
    assert "order_paid01" not in output


def _provider_row(order_id: str, telegram_charge_id: str, provider_charge_id: str) -> dict[str, object]:
    return {
        "provider": "fake_provider",
        "order_id": order_id,
        "telegram_payment_charge_id": telegram_charge_id,
        "provider_payment_charge_id": provider_charge_id,
        "amount": 1000,
        "currency": "RUB",
        "status": "succeeded",
    }


def _ledger_row(
    order_id: str,
    telegram_charge_id: str,
    provider_charge_id: str,
    *,
    order_status: str,
) -> dict[str, object]:
    return {
        "provider": "fake_provider",
        "order_id": order_id,
        "telegram_payment_charge_id": telegram_charge_id,
        "provider_payment_charge_id": provider_charge_id,
        "amount": 1000,
        "currency": "RUB",
        "order_status": order_status,
    }


def _spool_record(
    order_id: str,
    nonce: str,
    telegram_charge_id: str,
    provider_charge_id: str,
) -> PaymentRecoveryRecord:
    return PaymentRecoveryRecord(
        provider="fake_provider",
        chat_id=707070,
        user_id=808080,
        invoice_payload=encode_payment_order_payload(order_id, nonce),
        telegram_payment_charge_id=telegram_charge_id,
        provider_payment_charge_id=provider_charge_id,
        currency="RUB",
        total_amount=1000,
        created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
    )
