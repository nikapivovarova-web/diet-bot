from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from diet_bot.payment_recovery_spool import PaymentRecoveryRecord
from diet_bot.payment_recovery_replay import (
    APPLY_STATUS_ALREADY_RECOVERED,
    APPLY_STATUS_APPLY_FAILED,
    APPLY_STATUS_BLOCKED,
    APPLY_STATUS_RECOVERED,
    STATUS_ALREADY_RECOVERED,
    STATUS_BLOCKED,
    STATUS_DB_VALIDATION_UNAVAILABLE,
    STATUS_REPLAYABLE_CANDIDATE,
    apply_spool,
    dry_run_spool,
    list_spool,
)
from diet_bot.payments import (
    ORDER_STATUS_GRANTED,
    ORDER_STATUS_PENDING,
    PRODUCT_EXTRA_WEEKLY_PDF,
    PRODUCT_SUBSCRIPTION_MONTH,
    PROVIDER_TELEGRAM_STARS,
    PROVIDER_YOOKASSA,
    PaymentCharge,
    PaymentHandlingResult,
    PaymentOrder,
    encode_payment_order_payload,
)
from scripts.ops import payment_recovery_replay


CREATED_AT = datetime(2026, 5, 25, 10, 30, tzinfo=UTC)
ORDER_ID = "order_12345678"
NONCE = "nonce_12345678"
INVOICE_PAYLOAD = encode_payment_order_payload(ORDER_ID, NONCE)


def test_list_parses_records_and_redacts_sensitive_identifiers(tmp_path: Path) -> None:
    spool = _write_spool(tmp_path, [_record()])

    report = list_spool(spool)

    assert report.counts["listed"] == 1
    payload = report.to_dict()
    rendered = json.dumps(payload, sort_keys=True)
    assert payload["records"][0]["status"] == "listed"
    assert payload["records"][0]["record_id"] == _record().record_id
    _assert_redacted(rendered)


def test_dry_run_without_database_validates_shape_only_and_reports_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spool = _write_spool(tmp_path, [_record()])

    def fail_if_store_is_built(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("dry-run without a DSN must not construct a Postgres store")

    monkeypatch.setattr(payment_recovery_replay.impl, "_build_postgres_lookup", fail_if_store_is_built)

    exit_code = payment_recovery_replay.main(["dry-run", "--spool", str(spool), "--json"], env={})

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["db_validation_available"] is False
    assert payload["records"][0]["status"] == STATUS_DB_VALIDATION_UNAVAILABLE
    assert payload["records"][0]["reason"] == "db_validation_unavailable"
    _assert_redacted(json.dumps(payload, sort_keys=True))


def test_pending_matching_order_becomes_replayable_candidate(tmp_path: Path) -> None:
    record = _record(
        product=PRODUCT_EXTRA_WEEKLY_PDF,
        provider=PROVIDER_TELEGRAM_STARS,
        total_amount=170,
        currency="XTR",
    )
    spool = _write_spool(tmp_path, [record])
    store = FakePaymentReplayLookup(
        orders=[
            _order(
                product=PRODUCT_EXTRA_WEEKLY_PDF,
                amount=170,
                currency="XTR",
                provider=PROVIDER_TELEGRAM_STARS,
            )
        ],
    )

    report = dry_run_spool(spool, lookup=store)

    assert report.records[0].status == STATUS_REPLAYABLE_CANDIDATE
    assert report.records[0].reason == "pending_order_matches_spool_record"
    assert store.write_calls == []


def test_exact_existing_same_charge_on_granted_order_is_already_recovered(tmp_path: Path) -> None:
    record = _record()
    order = _order(status=ORDER_STATUS_GRANTED)
    charge = _charge(order_id=order.order_id, amount=order.amount, currency=order.currency)
    spool = _write_spool(tmp_path, [record])

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup(orders=[order], charges=[charge]))

    assert report.records[0].status == STATUS_ALREADY_RECOVERED
    assert report.records[0].reason == "exact_charge_already_granted"


def test_granted_order_with_different_charge_is_blocked(tmp_path: Path) -> None:
    record = _record()
    spool = _write_spool(tmp_path, [record])

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup(orders=[_order(status=ORDER_STATUS_GRANTED)]))

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == "order_already_granted_with_different_charge"


@pytest.mark.parametrize(
    ("record_overrides", "order_overrides", "reason"),
    [
        ({}, {"provider": PROVIDER_TELEGRAM_STARS}, "provider_mismatch"),
        ({"total_amount": 60_000}, {}, "amount_mismatch"),
        ({"currency": "XTR"}, {}, "currency_mismatch"),
        ({"chat_id": 999}, {}, "chat_mismatch"),
        ({"user_id": 999}, {}, "user_mismatch"),
    ],
)
def test_context_mismatch_is_blocked(
    tmp_path: Path,
    record_overrides: dict[str, object],
    order_overrides: dict[str, object],
    reason: str,
) -> None:
    record = _record(**record_overrides)
    spool = _write_spool(tmp_path, [record])
    store = FakePaymentReplayLookup(orders=[_order(**order_overrides)])

    report = dry_run_spool(spool, lookup=store)

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == reason


def test_missing_order_is_blocked(tmp_path: Path) -> None:
    spool = _write_spool(tmp_path, [_record()])

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup())

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == "order_not_found"


def test_invalid_invoice_payload_is_blocked(tmp_path: Path) -> None:
    spool = _write_spool(tmp_path, [_record(invoice_payload="diet:stars:subscription_month")])

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup())

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == "invalid_invoice_payload"


def test_nonce_mismatch_is_blocked(tmp_path: Path) -> None:
    spool = _write_spool(tmp_path, [_record()])

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup(orders=[_order(nonce="nonce_wrong123456")]))

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == "nonce_mismatch"


def test_malformed_lines_are_blocked_without_echoing_raw_content(tmp_path: Path) -> None:
    spool = tmp_path / "payments.jsonl"
    spool.write_text("not-json-with-secret-token-and-tg-charge-raw\n", encoding="utf-8")

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup())
    rendered = json.dumps(report.to_dict(), sort_keys=True)

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == "malformed_spool_record"
    assert "secret-token" not in rendered
    assert "tg-charge-raw" not in rendered


def test_record_with_unsupported_raw_field_is_blocked_without_echoing_value(tmp_path: Path) -> None:
    payload = _record().to_dict()
    payload["raw_payload"] = {"token": "secret-token"}
    spool = tmp_path / "payments.jsonl"
    spool.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup(orders=[_order()]))
    rendered = json.dumps(report.to_dict(), sort_keys=True)

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == "malformed_spool_record"
    assert report.records[0].detail == "record contains unsupported fields"
    assert "secret-token" not in rendered


def test_conflicting_duplicate_record_id_is_blocked(tmp_path: Path) -> None:
    first = _record()
    second_payload = first.to_dict()
    second_payload["chat_id"] = 999
    spool = tmp_path / "payments.jsonl"
    spool.write_text(
        json.dumps(first.to_dict()) + "\n" + json.dumps(second_payload) + "\n",
        encoding="utf-8",
    )

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup(orders=[_order()]))

    assert [item.status for item in report.records] == [STATUS_BLOCKED, STATUS_BLOCKED]
    assert {item.reason for item in report.records} == {"duplicate_record_id_conflict"}


def test_output_redacts_payload_charge_chat_user_and_dsn_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _record(
        telegram_payment_charge_id="tg-charge-secret-raw",
        provider_payment_charge_id="provider-charge-secret-raw",
    )
    spool = _write_spool(tmp_path, [record])
    store = FakePaymentReplayLookup(orders=[_order()])

    def fake_lookup(dsn: str):
        assert dsn == "postgresql://user:secret-token@example.test/diet_bot"
        return store

    monkeypatch.setattr(payment_recovery_replay.impl, "_build_postgres_lookup", fake_lookup)

    exit_code = payment_recovery_replay.main(
        [
            "dry-run",
            "--spool",
            str(spool),
            "--database-url",
            "postgresql://user:secret-token@example.test/diet_bot",
            "--json",
        ],
        env={},
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    _assert_redacted(output)
    assert "secret-token" not in output
    assert "tg-charge-secret-raw" not in output
    assert "provider-charge-secret-raw" not in output


def test_subscription_replay_without_expiration_is_blocked(tmp_path: Path) -> None:
    record = _record(subscription_expiration_date=None)
    spool = _write_spool(tmp_path, [record])

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup(orders=[_order()]))

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == "subscription_replay_timing_unavailable"


def test_charge_id_collision_with_mismatched_context_is_blocked(tmp_path: Path) -> None:
    record = _record()
    order = _order()
    collision_order = _order(order_id="order_collision", user_id=303, chat_id=404)
    collision = _charge(order_id=collision_order.order_id)
    spool = _write_spool(tmp_path, [record])

    report = dry_run_spool(
        spool,
        lookup=FakePaymentReplayLookup(orders=[order, collision_order], charges=[collision]),
    )

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == "charge_id_collision_context_mismatch"


def test_charge_id_collision_with_mismatched_secondary_charge_id_is_blocked(tmp_path: Path) -> None:
    record = _record()
    order = _order()
    collision = _charge(order_id=order.order_id, provider_payment_charge_id="provider-charge-other")
    spool = _write_spool(tmp_path, [record])

    report = dry_run_spool(spool, lookup=FakePaymentReplayLookup(orders=[order], charges=[collision]))

    assert report.records[0].status == STATUS_BLOCKED
    assert report.records[0].reason == "charge_id_collision_context_mismatch"


def test_dry_run_does_not_call_apply_or_write_methods(tmp_path: Path) -> None:
    spool = _write_spool(tmp_path, [_record()])

    report = dry_run_spool(spool, lookup=ExplodingWritesLookup(orders=[_order()]))

    assert report.records[0].status == STATUS_REPLAYABLE_CANDIDATE


def test_apply_requires_expected_fingerprint_before_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spool = _write_spool(tmp_path, [_record()])
    result_jsonl = tmp_path / "apply-results.jsonl"

    def fail_if_store_is_built(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("apply fingerprint guard must run before Postgres is touched")

    monkeypatch.setattr(payment_recovery_replay.impl, "_build_postgres_lookup", fail_if_store_is_built)

    exit_code = payment_recovery_replay.main(
        [
            "apply",
            "--spool",
            str(spool),
            "--database-url",
            "postgresql://user:secret-token@example.test/diet_bot",
            "--result-jsonl",
            str(result_jsonl),
        ],
        env={},
    )

    assert exit_code == 2
    assert "expected spool fingerprint is required" in capsys.readouterr().err
    assert not result_jsonl.exists()


def test_apply_fingerprint_mismatch_blocks_before_database_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = _write_spool(tmp_path, [_record()])
    result_jsonl = tmp_path / "apply-results.jsonl"

    def fail_if_store_is_built(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("fingerprint mismatch must fail before Postgres is touched")

    monkeypatch.setattr(payment_recovery_replay.impl, "_build_postgres_lookup", fail_if_store_is_built)

    exit_code = payment_recovery_replay.main(
        [
            "apply",
            "--spool",
            str(spool),
            "--database-url",
            "postgresql://user:secret-token@example.test/diet_bot",
            "--expected-spool-fingerprint",
            "sha256:not-the-current-fingerprint",
            "--result-jsonl",
            str(result_jsonl),
        ],
        env={},
    )

    assert exit_code == 2
    assert not result_jsonl.exists()


def test_apply_replayable_candidate_calls_payment_service_once_and_writes_redacted_result_jsonl(
    tmp_path: Path,
) -> None:
    record = _record()
    spool = _write_spool(tmp_path, [record])
    original_spool = spool.read_text(encoding="utf-8")
    result_jsonl = tmp_path / "apply-results.jsonl"
    lookup = FakePaymentReplayLookup(orders=[_order()])
    service = FakePaymentService(PaymentHandlingResult(True, PRODUCT_SUBSCRIPTION_MONTH))

    report = apply_spool(
        spool,
        lookup=lookup,
        payment_service=service,
        expected_spool_fingerprint=list_spool(spool).spool_fingerprint,
        result_jsonl=result_jsonl,
    )

    assert report.results[0].preflight_status == STATUS_REPLAYABLE_CANDIDATE
    assert report.results[0].apply_status == APPLY_STATUS_RECOVERED
    assert len(service.calls) == 1
    assert service.calls[0]["payload"] == record.invoice_payload
    assert service.calls[0]["user_id"] == record.user_id
    assert service.calls[0]["chat_id"] == record.chat_id
    assert service.calls[0]["provider"] == record.provider
    assert service.calls[0]["amount"] == record.total_amount
    assert service.calls[0]["currency"] == record.currency
    assert service.calls[0]["telegram_payment_charge_id"] == record.telegram_payment_charge_id
    assert service.calls[0]["provider_payment_charge_id"] == record.provider_payment_charge_id
    assert spool.read_text(encoding="utf-8") == original_spool
    lines = _read_jsonl(result_jsonl)
    assert lines == [report.results[0].to_dict()]
    rendered = result_jsonl.read_text(encoding="utf-8")
    _assert_redacted(rendered)


def test_apply_already_recovered_does_not_call_payment_service_and_writes_noop_success(
    tmp_path: Path,
) -> None:
    record = _record()
    order = _order(status=ORDER_STATUS_GRANTED)
    charge = _charge(order_id=order.order_id, amount=order.amount, currency=order.currency)
    spool = _write_spool(tmp_path, [record])
    result_jsonl = tmp_path / "apply-results.jsonl"
    service = ExplodingPaymentService()

    report = apply_spool(
        spool,
        lookup=FakePaymentReplayLookup(orders=[order], charges=[charge]),
        payment_service=service,
        expected_spool_fingerprint=list_spool(spool).spool_fingerprint,
        result_jsonl=result_jsonl,
    )

    assert report.results[0].preflight_status == STATUS_ALREADY_RECOVERED
    assert report.results[0].apply_status == APPLY_STATUS_ALREADY_RECOVERED
    assert _read_jsonl(result_jsonl)[0]["apply_status"] == APPLY_STATUS_ALREADY_RECOVERED


def test_apply_blocked_record_does_not_call_payment_service(tmp_path: Path) -> None:
    spool = _write_spool(tmp_path, [_record()])
    result_jsonl = tmp_path / "apply-results.jsonl"

    report = apply_spool(
        spool,
        lookup=FakePaymentReplayLookup(),
        payment_service=ExplodingPaymentService(),
        expected_spool_fingerprint=list_spool(spool).spool_fingerprint,
        result_jsonl=result_jsonl,
    )

    assert report.results[0].preflight_status == STATUS_BLOCKED
    assert report.results[0].apply_status == APPLY_STATUS_BLOCKED
    assert report.results[0].reason == "order_not_found"


def test_apply_duplicate_payment_service_result_is_recovered_only_after_exact_preflight(
    tmp_path: Path,
) -> None:
    record = _record()
    order = _order()
    lookup = FakePaymentReplayLookup(orders=[order])
    spool = _write_spool(tmp_path, [record])
    result_jsonl = tmp_path / "apply-results.jsonl"

    def record_exact_recovery(_kwargs: dict[str, object]) -> None:
        lookup.orders[order.order_id] = replace(order, status=ORDER_STATUS_GRANTED)
        lookup.charges.append(_charge(order_id=order.order_id, amount=order.amount, currency=order.currency))

    service = FakePaymentService(
        PaymentHandlingResult(False, PRODUCT_SUBSCRIPTION_MONTH, duplicate=True, reason="duplicate_charge"),
        side_effect=record_exact_recovery,
    )

    report = apply_spool(
        spool,
        lookup=lookup,
        payment_service=service,
        expected_spool_fingerprint=list_spool(spool).spool_fingerprint,
        result_jsonl=result_jsonl,
    )

    assert report.results[0].preflight_status == STATUS_REPLAYABLE_CANDIDATE
    assert report.results[0].apply_status == APPLY_STATUS_RECOVERED
    assert report.results[0].reason == "exact_charge_already_granted"


def test_apply_payment_service_mismatch_result_becomes_apply_failed(tmp_path: Path) -> None:
    spool = _write_spool(tmp_path, [_record()])
    result_jsonl = tmp_path / "apply-results.jsonl"
    service = FakePaymentService(PaymentHandlingResult(False, reason="amount_mismatch"))

    report = apply_spool(
        spool,
        lookup=FakePaymentReplayLookup(orders=[_order()]),
        payment_service=service,
        expected_spool_fingerprint=list_spool(spool).spool_fingerprint,
        result_jsonl=result_jsonl,
    )

    assert report.results[0].preflight_status == STATUS_REPLAYABLE_CANDIDATE
    assert report.results[0].apply_status == APPLY_STATUS_APPLY_FAILED
    assert report.results[0].reason == "amount_mismatch"


def test_apply_cli_exit_codes_success_blocker_fingerprint_and_runtime_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = _write_spool(tmp_path, [_record()])
    fingerprint = list_spool(spool).spool_fingerprint
    result_jsonl = tmp_path / "apply-results.jsonl"

    store = FakePaymentReplayLookup(orders=[_order()])
    service = FakePaymentService(PaymentHandlingResult(True, PRODUCT_SUBSCRIPTION_MONTH))
    _patch_apply_builders(monkeypatch, store, service)

    assert _run_apply_cli(spool, result_jsonl, fingerprint) == 0

    blocker_jsonl = tmp_path / "apply-blocked.jsonl"
    _patch_apply_builders(monkeypatch, FakePaymentReplayLookup(), ExplodingPaymentService())
    assert _run_apply_cli(spool, blocker_jsonl, fingerprint) == 1

    mismatch_jsonl = tmp_path / "apply-mismatch.jsonl"
    assert _run_apply_cli(spool, mismatch_jsonl, "sha256:not-current") == 2

    runtime_jsonl = tmp_path / "apply-runtime.jsonl"

    def fail_build(_database_url: str) -> object:
        raise RuntimeError("database unavailable with secret-token")

    monkeypatch.setattr(payment_recovery_replay.impl, "_build_postgres_lookup", fail_build)
    assert _run_apply_cli(spool, runtime_jsonl, fingerprint) == 3


def test_apply_dedupes_exact_duplicate_records_before_calling_payment_service(tmp_path: Path) -> None:
    record = _record()
    spool = tmp_path / "payments.jsonl"
    spool.write_text(record.to_json_line() + record.to_json_line(), encoding="utf-8")
    result_jsonl = tmp_path / "apply-results.jsonl"
    service = FakePaymentService(PaymentHandlingResult(True, PRODUCT_SUBSCRIPTION_MONTH))

    report = apply_spool(
        spool,
        lookup=FakePaymentReplayLookup(orders=[_order()]),
        payment_service=service,
        expected_spool_fingerprint=list_spool(spool).spool_fingerprint,
        result_jsonl=result_jsonl,
    )

    assert len(service.calls) == 1
    assert len(report.results) == 1
    assert len(_read_jsonl(result_jsonl)) == 1


def _record(**overrides: object) -> PaymentRecoveryRecord:
    product = str(overrides.pop("product", PRODUCT_SUBSCRIPTION_MONTH))
    provider = str(overrides.get("provider", PROVIDER_YOOKASSA))
    amount = int(overrides.get("total_amount", 59_900 if provider == PROVIDER_YOOKASSA else 400))
    currency = str(overrides.get("currency", "RUB" if provider == PROVIDER_YOOKASSA else "XTR"))
    values: dict[str, object] = {
        "provider": provider,
        "chat_id": 202,
        "user_id": 101,
        "invoice_payload": INVOICE_PAYLOAD if product == PRODUCT_SUBSCRIPTION_MONTH else encode_payment_order_payload(
            ORDER_ID,
            NONCE,
        ),
        "telegram_payment_charge_id": "tg-charge-1",
        "provider_payment_charge_id": "provider-charge-1",
        "currency": currency,
        "total_amount": amount,
        "subscription_expiration_date": 1_781_234_567,
        "created_at": CREATED_AT,
    }
    values.update(overrides)
    return PaymentRecoveryRecord(**values)


def _order(
    *,
    order_id: str = ORDER_ID,
    user_id: int = 101,
    chat_id: int = 202,
    product: str = PRODUCT_SUBSCRIPTION_MONTH,
    provider: str = PROVIDER_YOOKASSA,
    amount: int = 59_900,
    currency: str = "RUB",
    nonce: str = NONCE,
    status: str = ORDER_STATUS_PENDING,
) -> PaymentOrder:
    return PaymentOrder(
        order_id=order_id,
        user_id=user_id,
        chat_id=chat_id,
        product=product,
        provider=provider,
        amount=amount,
        currency=currency,
        nonce=nonce,
        status=status,
    )


def _charge(
    *,
    order_id: str = ORDER_ID,
    provider: str = PROVIDER_YOOKASSA,
    telegram_payment_charge_id: str = "tg-charge-1",
    provider_payment_charge_id: str = "provider-charge-1",
    amount: int = 59_900,
    currency: str = "RUB",
) -> PaymentCharge:
    return PaymentCharge(
        order_id=order_id,
        provider=provider,
        telegram_payment_charge_id=telegram_payment_charge_id,
        provider_payment_charge_id=provider_payment_charge_id,
        amount=amount,
        currency=currency,
    )


def _write_spool(tmp_path: Path, records: list[PaymentRecoveryRecord]) -> Path:
    spool = tmp_path / "payments.jsonl"
    spool.write_text("".join(record.to_json_line() for record in records), encoding="utf-8")
    return spool


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _patch_apply_builders(
    monkeypatch: pytest.MonkeyPatch,
    store: FakePaymentReplayLookup,
    service: object,
) -> None:
    monkeypatch.setattr(payment_recovery_replay.impl, "_build_postgres_lookup", lambda _database_url: store)
    monkeypatch.setattr(payment_recovery_replay.impl, "_build_payment_service", lambda _repository: service)


def _run_apply_cli(spool: Path, result_jsonl: Path, fingerprint: str) -> int:
    return payment_recovery_replay.main(
        [
            "apply",
            "--spool",
            str(spool),
            "--database-url",
            "postgresql://user:secret-token@example.test/diet_bot",
            "--expected-spool-fingerprint",
            fingerprint,
            "--result-jsonl",
            str(result_jsonl),
        ],
        env={},
    )


def _assert_redacted(output: str) -> None:
    assert INVOICE_PAYLOAD not in output
    assert "tg-charge-1" not in output
    assert "provider-charge-1" not in output
    assert '"chat_id": 202' not in output
    assert '"user_id": 101' not in output


class FakePaymentReplayLookup:
    def __init__(
        self,
        *,
        orders: list[PaymentOrder] | None = None,
        charges: list[PaymentCharge] | None = None,
    ) -> None:
        self.orders = {order.order_id: order for order in orders or []}
        self.charges = list(charges or [])
        self.write_calls: list[str] = []

    def get_order(self, order_id: str) -> PaymentOrder | None:
        return self.orders.get(order_id)

    def find_charge_by_external_id(
        self,
        *,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
    ) -> PaymentCharge | None:
        for charge in self.charges:
            if charge.provider != provider:
                continue
            if telegram_payment_charge_id and charge.telegram_payment_charge_id == telegram_payment_charge_id:
                return charge
            if provider_payment_charge_id and charge.provider_payment_charge_id == provider_payment_charge_id:
                return charge
        return None

    def create_order(self, order: PaymentOrder) -> PaymentOrder:
        self.write_calls.append("create_order")
        return order

    def record_charge(self, charge: PaymentCharge) -> object:
        self.write_calls.append("record_charge")
        return replace(charge)

    def record_event(self, *args: object, **kwargs: object) -> object:
        self.write_calls.append("record_event")
        return object()

    def mark_order_paid(self, order_id: str) -> PaymentOrder:
        self.write_calls.append("mark_order_paid")
        return self.orders[order_id]

    def mark_order_granted(self, order_id: str) -> PaymentOrder:
        self.write_calls.append("mark_order_granted")
        return self.orders[order_id]

    def mark_order_failed(self, order_id: str, reason: str | None = None) -> PaymentOrder:
        self.write_calls.append("mark_order_failed")
        return self.orders[order_id]


class ExplodingWritesLookup(FakePaymentReplayLookup):
    def create_order(self, order: PaymentOrder) -> PaymentOrder:
        raise AssertionError("dry-run must not create orders")

    def record_charge(self, charge: PaymentCharge) -> object:
        raise AssertionError("dry-run must not record charges")

    def record_event(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("dry-run must not record events")

    def mark_order_paid(self, order_id: str) -> PaymentOrder:
        raise AssertionError("dry-run must not mark orders paid")

    def mark_order_granted(self, order_id: str) -> PaymentOrder:
        raise AssertionError("dry-run must not mark orders granted")

    def mark_order_failed(self, order_id: str, reason: str | None = None) -> PaymentOrder:
        raise AssertionError("dry-run must not mark orders failed")


class FakePaymentService:
    def __init__(
        self,
        result: PaymentHandlingResult,
        *,
        side_effect: object | None = None,
    ) -> None:
        self.result = result
        self.side_effect = side_effect
        self.calls: list[dict[str, object]] = []

    def handle_successful_payment(self, **kwargs: object) -> PaymentHandlingResult:
        self.calls.append(dict(kwargs))
        if callable(self.side_effect):
            self.side_effect(kwargs)
        return self.result


class ExplodingPaymentService:
    def handle_successful_payment(self, **_kwargs: object) -> PaymentHandlingResult:
        raise AssertionError("blocked or already recovered records must not be applied")
