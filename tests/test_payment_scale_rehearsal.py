from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.payment_recovery_replay import (
    APPLY_STATUS_ALREADY_RECOVERED,
    APPLY_STATUS_RECOVERED,
    STATUS_REPLAYABLE_CANDIDATE,
    apply_spool,
    dry_run_spool,
    list_spool,
)
from diet_bot.payment_recovery_spool import read_payment_recovery_records
from diet_bot.payment_runtime import PaymentLedgerUnavailable
from diet_bot.payment_service import PaymentService
from diet_bot.payments import (
    ORDER_STATUS_GRANTED,
    ORDER_STATUS_PENDING,
    PRODUCT_EXTRA_WEEKLY_PDF,
    PRODUCT_SUBSCRIPTION_MONTH,
    PROVIDER_YOOKASSA,
    PaymentCharge,
    PaymentEvent,
    PaymentOrder,
    RecordedPaymentCharge,
    encode_payment_order_payload,
)


def test_synthetic_successful_payment_rehearsal_spool_replay_and_repeat_idempotency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = RehearsalPaymentRepository()
    grants: list[tuple[str, str | None]] = []
    service = PaymentService(
        repo,
        order_id_factory=_sequence("order_scale01", "order_replay1"),
        nonce_factory=_sequence("nonce_scale01", "nonce_replay1"),
        grant_entitlement=lambda order, charge: grants.append((order.order_id, charge.telegram_payment_charge_id)),
    )

    paid_order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_YOOKASSA,
    )
    paid_payload = encode_payment_order_payload(paid_order.order_id, paid_order.nonce)

    first = service.handle_successful_payment(
        payload=paid_payload,
        user_id=101,
        chat_id=202,
        provider=PROVIDER_YOOKASSA,
        amount=79_900,
        currency="RUB",
        telegram_payment_charge_id="tg-scale-duplicate-raw",
        provider_payment_charge_id="provider-scale-duplicate-raw",
    )
    duplicate = service.handle_successful_payment(
        payload=paid_payload,
        user_id=101,
        chat_id=202,
        provider=PROVIDER_YOOKASSA,
        amount=79_900,
        currency="RUB",
        telegram_payment_charge_id="tg-scale-duplicate-raw",
        provider_payment_charge_id="provider-scale-duplicate-raw",
    )

    assert first.processed
    assert duplicate.duplicate
    assert len(grants) == 1
    assert repo.orders[paid_order.order_id].status == ORDER_STATUS_GRANTED

    replay_order = service.create_order(
        user_id=303,
        chat_id=404,
        product=PRODUCT_EXTRA_WEEKLY_PDF,
        provider=PROVIDER_YOOKASSA,
    )
    replay_payload = encode_payment_order_payload(replay_order.order_id, replay_order.nonce)
    spool = tmp_path / "payment-recovery.jsonl"
    monkeypatch.setattr(telegram_app, "_payment_recovery_spool_path", lambda: spool)

    telegram_app._spool_failed_successful_payment(
        SimpleNamespace(chat=SimpleNamespace(id=404), from_user=SimpleNamespace(id=303)),
        SimpleNamespace(
            invoice_payload=replay_payload,
            currency="RUB",
            total_amount=25_000,
            telegram_payment_charge_id="tg-recovery-raw",
            provider_payment_charge_id="provider-recovery-raw",
        ),
        PaymentLedgerUnavailable("payment_ledger_unavailable", "synthetic ledger outage"),
    )

    read_result = read_payment_recovery_records(spool)
    assert len(read_result.records) == 1
    assert read_result.records[0].invoice_payload == replay_payload
    assert repo.orders[replay_order.order_id].status == ORDER_STATUS_PENDING

    dry_run = dry_run_spool(spool, lookup=repo)
    assert dry_run.records[0].status == STATUS_REPLAYABLE_CANDIDATE

    apply_result = apply_spool(
        spool,
        lookup=repo,
        payment_service=service,
        expected_spool_fingerprint=list_spool(spool).spool_fingerprint,
        result_jsonl=tmp_path / "apply-results.jsonl",
    )

    assert apply_result.results[0].apply_status == APPLY_STATUS_RECOVERED
    assert grants == [
        ("order_scale01", "tg-scale-duplicate-raw"),
        ("order_replay1", "tg-recovery-raw"),
    ]
    assert repo.orders[replay_order.order_id].status == ORDER_STATUS_GRANTED

    repeat_result = apply_spool(
        spool,
        lookup=repo,
        payment_service=service,
        expected_spool_fingerprint=list_spool(spool).spool_fingerprint,
        result_jsonl=tmp_path / "repeat-apply-results.jsonl",
    )

    assert repeat_result.results[0].apply_status == APPLY_STATUS_ALREADY_RECOVERED
    assert grants == [
        ("order_scale01", "tg-scale-duplicate-raw"),
        ("order_replay1", "tg-recovery-raw"),
    ]


def _sequence(*values: str):
    iterator: Iterator[str] = iter(values)
    return lambda: next(iterator)


class RehearsalPaymentRepository:
    def __init__(self) -> None:
        self.orders: dict[str, PaymentOrder] = {}
        self.charges: list[PaymentCharge] = []
        self.events: list[PaymentEvent] = []

    def create_order(self, order: PaymentOrder) -> PaymentOrder:
        self.orders[order.order_id] = order
        return order

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

    def record_event(self, event: PaymentEvent) -> PaymentEvent:
        if event.event_key:
            for existing in self.events:
                if existing.event_key == event.event_key:
                    return existing
        self.events.append(event)
        return event

    def record_charge(self, charge: PaymentCharge) -> RecordedPaymentCharge:
        existing = self.find_charge_by_external_id(
            provider=charge.provider,
            telegram_payment_charge_id=charge.telegram_payment_charge_id,
            provider_payment_charge_id=charge.provider_payment_charge_id,
        )
        if existing is not None:
            return RecordedPaymentCharge(existing, inserted=False)
        saved = replace(charge, charge_id=len(self.charges) + 1)
        self.charges.append(saved)
        return RecordedPaymentCharge(saved, inserted=True)

    def mark_order_paid(self, order_id: str) -> PaymentOrder:
        return self._mark(order_id, "paid")

    def mark_order_granted(self, order_id: str) -> PaymentOrder:
        return self._mark(order_id, "granted")

    def mark_order_failed(self, order_id: str, reason: str | None = None) -> PaymentOrder:
        order = replace(self.orders[order_id], status="failed", failure_reason=reason)
        self.orders[order_id] = order
        return order

    def _mark(self, order_id: str, status: str) -> PaymentOrder:
        order = replace(self.orders[order_id], status=status)
        self.orders[order_id] = order
        return order
