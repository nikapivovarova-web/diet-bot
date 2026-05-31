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


def test_reconciliation_flags_same_order_different_telegram_charge_id_without_matching() -> None:
    provider_rows = [_provider_row("order_mismatch", "tg-provider-raw", "provider-match-raw")]
    ledger_rows = [
        _ledger_row(
            "order_mismatch",
            "tg-ledger-raw",
            "provider-match-raw",
            order_status="granted",
        )
    ]

    report = reconcile_payment_exports(provider_rows, ledger_rows)
    rendered = render_reconciliation_jsonl(report)
    [payload] = [json.loads(line) for line in rendered.splitlines()]

    assert report.counts["matched_paid_granted"] == 0
    assert payload["category"] == "charge_id_mismatch"
    assert payload["reason"] == "telegram_payment_charge_id_mismatch"
    assert payload["order_id"].startswith("<redacted:")
    assert payload["telegram_payment_charge_id"].startswith("<redacted:")
    assert payload["ledger_telegram_payment_charge_id"].startswith("<redacted:")
    assert payload["provider_payment_charge_id"].startswith("<redacted:")
    assert payload["ledger_provider_payment_charge_id"].startswith("<redacted:")
    assert payload["amount"] == 1000
    assert payload["ledger_amount"] == 1000
    assert payload["currency"] == "RUB"
    assert payload["ledger_currency"] == "RUB"
    assert payload["order_status"] == "succeeded"
    assert payload["ledger_order_status"] == "granted"
    for raw in ("order_mismatch", "tg-provider-raw", "tg-ledger-raw", "provider-match-raw"):
        assert raw not in rendered


def test_reconciliation_flags_same_order_different_provider_charge_id_without_matching() -> None:
    provider_rows = [_provider_row("order_mismatch", "tg-match-raw", "provider-provider-raw")]
    ledger_rows = [
        _ledger_row(
            "order_mismatch",
            "tg-match-raw",
            "provider-ledger-raw",
            order_status="granted",
        )
    ]

    report = reconcile_payment_exports(provider_rows, ledger_rows)
    rendered = render_reconciliation_jsonl(report)
    [payload] = [json.loads(line) for line in rendered.splitlines()]

    assert report.counts["matched_paid_granted"] == 0
    assert payload["category"] == "charge_id_mismatch"
    assert payload["reason"] == "provider_payment_charge_id_mismatch"
    assert payload["provider_payment_charge_id"].startswith("<redacted:")
    assert payload["ledger_provider_payment_charge_id"].startswith("<redacted:")
    for raw in ("order_mismatch", "tg-match-raw", "provider-provider-raw", "provider-ledger-raw"):
        assert raw not in rendered


def test_reconciliation_still_classifies_true_provider_ledger_matches() -> None:
    provider_rows = [_provider_row("order_match01", "tg-match-raw", "provider-match-raw")]
    ledger_rows = [_ledger_row("order_match01", "tg-match-raw", "provider-match-raw", order_status="granted")]

    report = reconcile_payment_exports(provider_rows, ledger_rows)

    assert [item.category for item in report.items] == ["matched_paid_granted"]


def test_reconciliation_flags_refunded_provider_charge_with_granted_ledger() -> None:
    provider_rows = [
        _provider_row(
            "order_refund01",
            "tg-refund-raw",
            "provider-refund-raw",
            status="refunded",
        )
    ]
    ledger_rows = [
        _ledger_row(
            "order_refund01",
            "tg-refund-raw",
            "provider-refund-raw",
            order_status="granted",
        )
    ]

    report = reconcile_payment_exports(provider_rows, ledger_rows)

    assert report.counts["matched_paid_granted"] == 0
    assert [item.category for item in report.items] == ["provider_refunded_but_granted"]
    assert report.items[0].reason == "provider_status_refunded"
    assert report.has_findings


def test_reconciliation_flags_canceled_or_reversed_provider_charge_with_granted_ledger() -> None:
    provider_rows = [
        _provider_row(
            "order_cancel01",
            "tg-cancel-raw",
            "provider-cancel-raw",
            status="canceled",
        ),
        _provider_row(
            "order_reverse01",
            "tg-reverse-raw",
            "provider-reverse-raw",
            status="reversed",
        ),
    ]
    ledger_rows = [
        _ledger_row(
            "order_cancel01",
            "tg-cancel-raw",
            "provider-cancel-raw",
            order_status="granted",
        ),
        _ledger_row(
            "order_reverse01",
            "tg-reverse-raw",
            "provider-reverse-raw",
            order_status="granted",
        ),
    ]

    report = reconcile_payment_exports(provider_rows, ledger_rows)

    assert report.counts["matched_paid_granted"] == 0
    assert [item.category for item in report.items] == [
        "provider_canceled_but_granted",
        "provider_reversed_but_granted",
    ]
    assert [item.reason for item in report.items] == [
        "provider_status_canceled",
        "provider_status_reversed",
    ]


def test_reconciliation_still_classifies_provider_without_ledger() -> None:
    report = reconcile_payment_exports([_provider_row("order_missing", "tg-missing-raw", "provider-missing-raw")], [])

    assert [item.category for item in report.items] == ["charged_but_not_granted"]


def test_reconciliation_still_classifies_ledger_without_provider() -> None:
    ledger_rows = [_ledger_row("order_orphan1", "tg-orphan-raw", "provider-orphan-raw", order_status="granted")]

    report = reconcile_payment_exports([], ledger_rows)

    assert [item.category for item in report.items] == ["granted_but_no_provider_charge"]


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


def test_reconciliation_cli_says_report_is_read_only_and_points_to_apply_command(
    tmp_path: Path,
    capsys,
) -> None:
    provider_json, ledger_json = _write_reconciliation_inputs(tmp_path)

    exit_code = payment_reconciliation_report.main(
        [
            "--provider-export",
            str(provider_json),
            "--ledger-export",
            str(ledger_json),
            "--format",
            "jsonl",
        ],
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "reconciliation is read-only" in captured.err
    assert "scripts.ops.apply_payment_reversal" in captured.err
    assert "--dry-run" in captured.err
    assert "--apply" in captured.err
    assert "tg-paid-raw" not in captured.err
    assert "provider-paid-raw" not in captured.err
    assert "order_paid01" not in captured.err


def test_reconciliation_cli_fails_when_explicit_recovery_spool_is_missing(
    tmp_path: Path,
    capsys,
) -> None:
    provider_json, ledger_json = _write_reconciliation_inputs(tmp_path)
    missing_spool = tmp_path / "missing-secret-spool.jsonl"

    exit_code = payment_reconciliation_report.main(
        [
            "--provider-export",
            str(provider_json),
            "--ledger-export",
            str(ledger_json),
            "--recovery-spool",
            str(missing_spool),
            "--format",
            "jsonl",
        ],
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "recovery spool does not exist" in captured.err
    assert "<redacted:" in captured.err
    assert str(missing_spool) not in captured.err
    assert captured.out == ""


def test_reconciliation_cli_fails_on_malformed_recovery_spool_by_default(
    tmp_path: Path,
    capsys,
) -> None:
    provider_json, ledger_json = _write_reconciliation_inputs(tmp_path)
    spool = tmp_path / "spool.jsonl"
    spool.write_text("not-json-with-secret-token\n", encoding="utf-8")

    exit_code = payment_reconciliation_report.main(
        [
            "--provider-export",
            str(provider_json),
            "--ledger-export",
            str(ledger_json),
            "--recovery-spool",
            str(spool),
        ],
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "malformed recovery spool lines" in captured.err
    assert "malformed_line_count=1" in captured.err
    assert "secret-token" not in captured.err
    assert str(spool) not in captured.err
    assert captured.out == ""


def test_reconciliation_cli_allow_malformed_spool_continues_and_reports_count(
    tmp_path: Path,
    capsys,
) -> None:
    provider_json, ledger_json = _write_reconciliation_inputs(tmp_path)
    spool = tmp_path / "spool.jsonl"
    spool.write_text(
        "not-json-with-secret-token\n"
        + _spool_record("order_paid01", "nonce_paid01", "tg-paid-raw", "provider-paid-raw").to_json_line(),
        encoding="utf-8",
    )

    exit_code = payment_reconciliation_report.main(
        [
            "--provider-export",
            str(provider_json),
            "--ledger-export",
            str(ledger_json),
            "--recovery-spool",
            str(spool),
            "--allow-malformed-spool",
            "--format",
            "jsonl",
        ],
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "recovery_spool_candidate" in captured.out
    assert "malformed recovery spool lines ignored" in captured.err
    assert "malformed_line_count=1" in captured.err
    assert "secret-token" not in captured.err
    assert str(spool) not in captured.err


def _provider_row(
    order_id: str,
    telegram_charge_id: str,
    provider_charge_id: str,
    *,
    status: str = "succeeded",
) -> dict[str, object]:
    return {
        "provider": "fake_provider",
        "order_id": order_id,
        "telegram_payment_charge_id": telegram_charge_id,
        "provider_payment_charge_id": provider_charge_id,
        "amount": 1000,
        "currency": "RUB",
        "status": status,
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


def _write_reconciliation_inputs(tmp_path: Path) -> tuple[Path, Path]:
    provider_json = tmp_path / "provider.json"
    ledger_json = tmp_path / "ledger.json"
    provider_json.write_text(
        json.dumps([_provider_row("order_paid01", "tg-paid-raw", "provider-paid-raw")]),
        encoding="utf-8",
    )
    ledger_json.write_text(
        json.dumps([_ledger_row("order_paid01", "tg-paid-raw", "provider-paid-raw", order_status="paid")]),
        encoding="utf-8",
    )
    return provider_json, ledger_json
