from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from diet_bot.payment_recovery_spool import PaymentRecoveryRecord, summarize_payment_recovery_spool
from diet_bot.payments import encode_payment_order_payload
from scripts.ops import payment_recovery_replay


def test_spool_summary_reports_count_age_and_thresholds_without_raw_identifiers(tmp_path: Path) -> None:
    now = datetime(2026, 5, 28, 12, tzinfo=UTC)
    spool = tmp_path / "payments.jsonl"
    spool.write_text(
        _record("order_old001", "nonce_old001", "tg-old-raw", "provider-old-raw", now - timedelta(hours=5))
        .to_json_line()
        + _record("order_new001", "nonce_new001", "tg-new-raw", "provider-new-raw", now - timedelta(minutes=30))
        .to_json_line(),
        encoding="utf-8",
    )

    summary = summarize_payment_recovery_spool(
        spool,
        now=now,
        warn_after=timedelta(hours=2),
        fail_after=timedelta(hours=8),
        max_records=10,
    )

    payload = summary.to_dict()
    rendered = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "warn"
    assert payload["record_count"] == 2
    assert payload["oldest_age_seconds"] == 18_000
    assert payload["newest_age_seconds"] == 1_800
    assert payload["oldest_created_at"] == "2026-05-28T07:00:00+00:00"
    assert payload["newest_created_at"] == "2026-05-28T11:30:00+00:00"
    assert "tg-old-raw" not in rendered
    assert "provider-old-raw" not in rendered
    assert "order_old001" not in rendered


def test_spool_status_cli_fails_when_fail_threshold_is_exceeded(
    tmp_path: Path,
    capsys,
) -> None:
    now = datetime(2026, 5, 28, 12, tzinfo=UTC)
    spool = tmp_path / "payments.jsonl"
    spool.write_text(
        _record("order_old001", "nonce_old001", "tg-old-raw", "provider-old-raw", now - timedelta(hours=3))
        .to_json_line(),
        encoding="utf-8",
    )

    exit_code = payment_recovery_replay.main(
        [
            "status",
            "--spool",
            str(spool),
            "--fail-after-hours",
            "1",
            "--now",
            "2026-05-28T12:00:00+00:00",
            "--json",
        ],
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["status"] == "fail"
    assert payload["record_count"] == 1
    assert payload["oldest_age_seconds"] == 10_800
    assert "tg-old-raw" not in output
    assert "provider-old-raw" not in output


def _record(
    order_id: str,
    nonce: str,
    telegram_charge_id: str,
    provider_charge_id: str,
    created_at: datetime,
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
        created_at=created_at,
    )
