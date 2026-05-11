from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.payments import PaymentEvent, encode_payment_order_payload, record_payment_event
from diet_bot.promo_codes import PromoCodeRecord, save_promo_codes
from diet_bot.subscriptions import (
    MONTHLY_ONE_DAY_LIMIT,
    MONTHLY_WEEKLY_PDF_LIMIT,
    PROCESSED_CHARGE_ID_LIMIT,
    Entitlement,
    apply_subscription_payment,
    consume_one_day_attempt,
    save_entitlements,
)


class FakeInvoiceBot:
    def __init__(self) -> None:
        self.invoice_links: list[dict] = []

    async def create_invoice_link(self, **kwargs) -> str:
        self.invoice_links.append(kwargs)
        return f"https://t.me/invoice/{len(self.invoice_links)}"


class FakeMessage:
    def __init__(
        self,
        chat_id: int = 71_000,
        *,
        user_id: int | None = None,
        text: str = "",
        refunded_payment=None,
    ) -> None:
        self.chat = SimpleNamespace(id=chat_id, type="private")
        self.from_user = SimpleNamespace(id=user_id if user_id is not None else chat_id)
        self.bot = FakeInvoiceBot()
        self.text = text
        self.refunded_payment = refunded_payment
        self.texts: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None):
        self.texts.append((text, reply_markup))
        return SimpleNamespace(text=text, reply_markup=reply_markup)


@pytest.fixture(autouse=True)
def isolated_payment_state(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_app, "PAYMENT_ORDERS_STATE_FILE", tmp_path / "payment_orders.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", tmp_path / "promo_codes.json")
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "")
    monkeypatch.setattr(telegram_app, "_POSTGRES_STORE", None)
    monkeypatch.setattr(telegram_app, "TELEGRAM_PROVIDER_TOKEN", "provider-token")
    monkeypatch.setattr(telegram_app, "ALLOW_LEGACY_PAYMENT_PAYLOADS", False)
    monkeypatch.setattr(telegram_app, "ALLOW_LEGACY_PAYLOADS_UNTIL", datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.anyio
async def test_order_payloads_are_unique_across_products_and_tampered_payload_is_rejected() -> None:
    message = FakeMessage(71_101)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)

    first_payload = message.bot.invoice_links[0]["payload"]
    second_payload = message.bot.invoice_links[1]["payload"]
    first_order_id, first_nonce = telegram_app.decode_payment_order_payload(first_payload) or ("", "")
    bad_nonce_payload = encode_payment_order_payload(first_order_id, f"{first_nonce}-tampered")

    assert first_payload != second_payload
    assert telegram_app.decode_payment_order_payload(first_payload) is not None
    assert not telegram_app._is_valid_pre_checkout(
        SimpleNamespace(
            invoice_payload=bad_nonce_payload,
            currency="XTR",
            total_amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
            from_user=SimpleNamespace(id=message.from_user.id),
        )
    )
    assert not telegram_app._is_valid_pre_checkout(
        SimpleNamespace(
            invoice_payload="diet:stars:subscription_month",
            currency="XTR",
            total_amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
            from_user=SimpleNamespace(id=message.from_user.id),
        )
    )


@pytest.mark.anyio
async def test_repeated_payment_callback_reuses_active_invoice_order() -> None:
    message = FakeMessage(71_116)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)

    state = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE)
    pending_orders = [order for order in state.orders.values() if order.status == "pending"]

    assert len(message.bot.invoice_links) == 1
    assert len(pending_orders) == 1
    assert pending_orders[0].invoice_link == "https://t.me/invoice/1"
    assert message.texts[0][1].inline_keyboard[0][0].url == "https://t.me/invoice/1"
    assert message.texts[1][1].inline_keyboard[0][0].url == "https://t.me/invoice/1"


@pytest.mark.anyio
async def test_successful_payment_does_not_grant_twice_for_same_order() -> None:
    chat_id = 71_102
    _save_active_subscription(chat_id)
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id="charge-repeat-extra",
    )

    first = telegram_app._apply_successful_payment(chat_id, payment)
    second = telegram_app._apply_successful_payment(chat_id, payment)
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    state = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE)

    assert first.processed
    assert first.grant == "extra_one_day"
    assert not second.processed
    assert second.duplicate
    assert entitlement.extra_one_day_remaining == 1
    assert state.orphan_payments == []


@pytest.mark.anyio
async def test_successful_payment_dedupe_survives_entitlement_fifo_eviction() -> None:
    chat_id = 71_115
    charge_id = "charge-fifo-evicted-extra"
    _save_active_subscription(chat_id)
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    invoice_payload = message.bot.invoice_links[0]["payload"]
    payment = _successful_payment(
        invoice_payload,
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id=charge_id,
    )

    first = telegram_app._apply_successful_payment(chat_id, payment)

    order_id, _ = telegram_app.decode_payment_order_payload(invoice_payload) or ("", "")
    order_state = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE)
    order_state.orders[order_id] = replace(order_state.orders[order_id], status="pending", paid_at=None)
    telegram_app.save_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE, order_state)

    entitlements = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements[chat_id]
    provider_charge_id = f"telegram_stars:{charge_id}"
    entitlement.processed_payment_charge_ids = [
        f"synthetic-charge-{index}"
        for index in range(PROCESSED_CHARGE_ID_LIMIT)
    ]
    assert provider_charge_id not in entitlement.processed_payment_charge_ids
    telegram_app.save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, entitlements)

    second = telegram_app._apply_successful_payment(chat_id, payment)
    after = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert first.processed
    assert not second.processed
    assert second.duplicate
    assert after.extra_one_day_remaining == 1


@pytest.mark.anyio
async def test_successful_payment_registry_backfills_legacy_entitlement_charge_ids() -> None:
    chat_id = 71_116
    charge_id = "charge-legacy-entitlement"
    _save_active_subscription(chat_id)
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id=charge_id,
    )

    entitlements = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)
    entitlements[chat_id].processed_payment_charge_ids.append(f"telegram_stars:{charge_id}")
    telegram_app.save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, entitlements)

    result = telegram_app._apply_successful_payment(chat_id, payment)
    after = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert not result.processed
    assert result.duplicate
    assert after.extra_one_day_remaining == 0
    assert telegram_app._processed_payment_charges_state_file().exists()


@pytest.mark.anyio
async def test_successful_payment_grants_when_order_expires_after_pre_checkout() -> None:
    chat_id = 71_109
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    invoice_payload = message.bot.invoice_links[0]["payload"]
    pre_checkout_query = SimpleNamespace(
        invoice_payload=invoice_payload,
        currency="XTR",
        total_amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        from_user=SimpleNamespace(id=chat_id),
    )
    assert telegram_app._is_valid_pre_checkout(pre_checkout_query)

    order_id, _ = telegram_app.decode_payment_order_payload(invoice_payload) or ("", "")
    state = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE)
    # Product decision: after Telegram approves pre_checkout, do not reject successful_payment
    # solely because our local order TTL expires before the final payment update arrives.
    state.orders[order_id] = replace(
        state.orders[order_id],
        expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )
    telegram_app.save_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE, state)

    payment = _successful_payment(
        invoice_payload,
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="charge-expired-after-pre-checkout",
    )

    result = telegram_app._apply_successful_payment(chat_id, payment, delivery_chat_id=chat_id)
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    paid_order = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE).orders[order_id]

    assert result.processed
    assert result.grant == "subscription"
    assert entitlement.is_subscription_active()
    assert paid_order.status == "paid"


@pytest.mark.anyio
async def test_pre_checkout_rejects_expired_pending_order() -> None:
    chat_id = 71_114
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)

    invoice_payload = message.bot.invoice_links[0]["payload"]
    order_id, _ = telegram_app.decode_payment_order_payload(invoice_payload) or ("", "")
    state = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE)
    state.orders[order_id] = replace(
        state.orders[order_id],
        expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )
    telegram_app.save_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE, state)

    query = SimpleNamespace(
        invoice_payload=invoice_payload,
        currency="XTR",
        total_amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        from_user=SimpleNamespace(id=chat_id),
    )

    assert not telegram_app._is_valid_pre_checkout(query)
    expired_order = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE).orders[order_id]
    assert expired_order.status == "expired"


@pytest.mark.anyio
async def test_successful_payment_rejects_wrong_delivery_chat() -> None:
    user_id = 71_110
    chat_id = 71_111
    message = FakeMessage(chat_id, user_id=user_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="charge-wrong-delivery-chat",
    )

    result = telegram_app._apply_successful_payment(user_id, payment, delivery_chat_id=chat_id + 1)
    entitlements = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)
    state = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE)

    assert not result.processed
    assert user_id not in entitlements
    assert state.orphan_payments[-1]["reason"] == "chat_mismatch"


@pytest.mark.anyio
async def test_refund_after_subscription_removes_access_and_tells_user() -> None:
    chat_id = 71_106
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="charge-refund-subscription",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    refund_message = FakeMessage(chat_id, refunded_payment=_refunded_payment(payment))
    await telegram_app.handle_refunded_payment(refund_message)
    duplicate = telegram_app._apply_payment_event(
        chat_id,
        event_type=telegram_app.PAYMENT_EVENT_REFUND,
        provider="telegram_stars",
        charge_id="charge-refund-subscription",
        amount=payment.total_amount,
        currency=payment.currency,
        raw_payload={"source": "duplicate-test"},
    )
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert payment_result.processed
    assert not entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == 0
    assert entitlement.monthly_weekly_pdf_remaining == 0
    assert duplicate.duplicate
    assert "Возврат платежа обработан" in refund_message.texts[-1][0]


@pytest.mark.anyio
async def test_refund_before_successful_payment_is_pending_then_reconciled() -> None:
    chat_id = 71_120
    charge_id = "refund-before-successful-payment"
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id=charge_id,
    )

    early_refund = telegram_app._apply_payment_event(
        chat_id,
        event_type=telegram_app.PAYMENT_EVENT_REFUND,
        provider="telegram_stars",
        charge_id=charge_id,
        amount=payment.total_amount,
        currency=payment.currency,
        raw_payload={"source": "provider-before-success"},
    )
    pending_events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events

    assert not early_refund.processed
    assert not early_refund.duplicate
    assert early_refund.status == telegram_app.PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION
    assert pending_events[-1].status == telegram_app.PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION

    payment_result = telegram_app._apply_successful_payment(chat_id, payment)
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events
    refund_events = [
        event
        for event in events
        if event.event_type == telegram_app.PAYMENT_EVENT_REFUND and event.charge_id == charge_id
    ]

    assert payment_result.processed
    assert refund_events[-1].status == telegram_app.PAYMENT_EVENT_STATUS_PROCESSED
    assert not entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == 0
    assert entitlement.monthly_weekly_pdf_remaining == 0


@pytest.mark.anyio
async def test_refund_subscription_keeps_separately_paid_extras() -> None:
    chat_id = 71_121
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    subscription_payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="refund-subscription-keeps-extras-sub",
    )
    subscription_result = telegram_app._apply_successful_payment(chat_id, subscription_payment)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    extra_payment = _successful_payment(
        message.bot.invoice_links[1]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id="refund-subscription-keeps-extras-extra",
    )
    extra_result = telegram_app._apply_successful_payment(chat_id, extra_payment)

    refund = telegram_app._apply_payment_event(
        chat_id,
        event_type=telegram_app.PAYMENT_EVENT_REFUND,
        provider="telegram_stars",
        charge_id="refund-subscription-keeps-extras-sub",
        amount=subscription_payment.total_amount,
        currency=subscription_payment.currency,
        raw_payload={"source": "subscription-refund"},
    )
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert subscription_result.processed
    assert extra_result.processed
    assert refund.processed
    assert not entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == 0
    assert entitlement.monthly_weekly_pdf_remaining == 0
    assert entitlement.extra_one_day_remaining == 1


@pytest.mark.anyio
async def test_refund_specific_extra_removes_only_that_extra() -> None:
    chat_id = 71_122
    _save_active_subscription(chat_id)
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    one_day_payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id="refund-specific-extra-one-day",
    )
    one_day_result = telegram_app._apply_successful_payment(chat_id, one_day_payment)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_WEEKLY_PDF)
    weekly_payment = _successful_payment(
        message.bot.invoice_links[1]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_WEEKLY_PDF],
        charge_id="refund-specific-extra-weekly",
    )
    weekly_result = telegram_app._apply_successful_payment(chat_id, weekly_payment)

    refund = telegram_app._apply_payment_event(
        chat_id,
        event_type=telegram_app.PAYMENT_EVENT_REFUND,
        provider="telegram_stars",
        charge_id="refund-specific-extra-one-day",
        amount=one_day_payment.total_amount,
        currency=one_day_payment.currency,
        raw_payload={"source": "extra-refund"},
    )
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert one_day_result.processed
    assert weekly_result.processed
    assert refund.processed
    assert entitlement.is_subscription_active()
    assert entitlement.extra_one_day_remaining == 0
    assert entitlement.extra_weekly_pdf_remaining == 1


@pytest.mark.anyio
async def test_yookassa_refund_matches_provider_payment_charge_id() -> None:
    chat_id = 71_123
    message = FakeMessage(chat_id)

    await telegram_app._send_yookassa_invoice_link(message, telegram_app.PAYLOAD_RU_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="RUB",
        amount=telegram_app.RUB_PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_RU_SUBSCRIPTION_MONTH],
        charge_id="telegram-yookassa-charge",
        provider_charge_id="provider-yookassa-charge",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    refund = telegram_app._apply_payment_event(
        chat_id,
        event_type=telegram_app.PAYMENT_EVENT_REFUND,
        provider="yookassa",
        charge_id="provider-yookassa-charge",
        amount=payment.total_amount,
        currency=payment.currency,
        raw_payload={
            "source": "yookassa",
            "telegram_payment_charge_id": "telegram-yookassa-charge",
            "provider_payment_charge_id": "provider-yookassa-charge",
        },
    )
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events
    success_event = [
        event
        for event in events
        if event.event_type == telegram_app.PAYMENT_EVENT_SUCCESSFUL
        and event.provider == "yookassa"
    ][-1]

    assert payment_result.processed
    assert refund.processed
    assert success_event.charge_id == "provider-yookassa-charge"
    assert success_event.telegram_charge_id == "telegram-yookassa-charge"
    assert success_event.provider_charge_id == "provider-yookassa-charge"
    assert not entitlement.is_subscription_active()


@pytest.mark.anyio
async def test_chargeback_after_extra_removes_extra_attempt() -> None:
    chat_id = 71_107
    _save_active_subscription(chat_id)
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id="chargeback-extra-day",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    chargeback = telegram_app._apply_payment_event(
        chat_id,
        event_type=telegram_app.PAYMENT_EVENT_CHARGEBACK,
        provider="telegram_stars",
        charge_id="chargeback-extra-day",
        amount=payment.total_amount,
        currency=payment.currency,
        raw_payload={"source": "bank"},
    )
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert payment_result.processed
    assert chargeback.processed
    assert entitlement.extra_one_day_remaining == 0


@pytest.mark.anyio
async def test_refund_after_consumed_extra_is_ignored_with_precise_reason() -> None:
    chat_id = 71_119
    now = datetime.now(UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-refund-consumed-extra",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 1
    save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, {chat_id: entitlement})
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id="refund-consumed-extra-day",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)
    entitlements = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)
    entitlement = entitlements[chat_id]

    monthly = consume_one_day_attempt(entitlement, now)
    extra = consume_one_day_attempt(entitlement, now)
    telegram_app.save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, entitlements)

    refund = telegram_app._apply_payment_event(
        chat_id,
        event_type=telegram_app.PAYMENT_EVENT_REFUND,
        provider="telegram_stars",
        charge_id="refund-consumed-extra-day",
        amount=payment.total_amount,
        currency=payment.currency,
        raw_payload={"source": "refund"},
    )
    text = telegram_app._payment_event_result_text(chat_id, refund)
    updated = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events

    assert payment_result.processed
    assert monthly.source == "monthly"
    assert extra.source == "extra"
    assert not refund.processed
    assert refund.reason == "extra_already_consumed"
    assert updated.extra_one_day_remaining == 0
    assert events[-1].status == telegram_app.PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL
    assert events[-1].reason == "extra_already_consumed"
    assert "списали связанные лимиты" not in text
    assert "extra-лимит уже был использован" in text


@pytest.mark.anyio
async def test_admin_reconciliation_applies_orphan_successful_payment_once(monkeypatch) -> None:
    admin_id = 719_007
    chat_id = 71_124
    charge_id = "admin-reconcile-orphan-extra"
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id=charge_id,
    )
    orphan = telegram_app._apply_successful_payment(chat_id, payment)
    orphan_events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events

    _save_active_subscription(chat_id)

    command = FakeMessage(admin_id, user_id=admin_id, text=f"/payment_event reconcile {charge_id}")
    duplicate_command = FakeMessage(admin_id, user_id=admin_id, text=f"/payment_event reconcile {charge_id}")

    await telegram_app.payment_event_reconciliation_command(command)
    await telegram_app.payment_event_reconciliation_command(duplicate_command)

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events
    success_events = [
        event
        for event in events
        if event.event_type == telegram_app.PAYMENT_EVENT_SUCCESSFUL
        and event.charge_id == charge_id
    ]

    assert not orphan.processed
    assert orphan_events[-1].status == telegram_app.PAYMENT_EVENT_STATUS_ORPHAN_RECOVERABLE
    assert entitlement.extra_one_day_remaining == 1
    assert success_events[-1].status == telegram_app.PAYMENT_EVENT_STATUS_PROCESSED
    assert command.texts[-1][0].startswith("processed: reconciliation finished")
    assert duplicate_command.texts[-1][0].startswith("duplicate: reconciliation finished")


@pytest.mark.anyio
async def test_admin_reconciliation_applies_pending_refund_once(monkeypatch) -> None:
    admin_id = 719_008
    chat_id = 71_125
    charge_id = "admin-reconcile-pending-refund"
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})

    pending = telegram_app._apply_payment_event(
        chat_id,
        event_type=telegram_app.PAYMENT_EVENT_REFUND,
        provider="telegram_stars",
        charge_id=charge_id,
        amount=400,
        currency="XTR",
        raw_payload={"source": "early-refund"},
    )
    entitlement = Entitlement()
    now = datetime.now(UTC)
    apply_subscription_payment(
        entitlement,
        f"telegram_stars:{charge_id}",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, {chat_id: entitlement})
    record_payment_event(
        telegram_app._payment_events_state_file(),
        PaymentEvent.create(
            event_type=telegram_app.PAYMENT_EVENT_SUCCESSFUL,
            provider="telegram_stars",
            charge_id=charge_id,
            user_id=chat_id,
            product="subscription_month",
            amount=400,
            currency="XTR",
            status=telegram_app.PAYMENT_EVENT_STATUS_PROCESSED,
            raw_payload={"source": "manual-success-for-reconcile-test"},
        ),
    )

    command = FakeMessage(admin_id, user_id=admin_id, text=f"/payment_event reconcile {charge_id}")
    duplicate_command = FakeMessage(admin_id, user_id=admin_id, text=f"/payment_event reconcile {charge_id}")

    await telegram_app.payment_event_reconciliation_command(command)
    await telegram_app.payment_event_reconciliation_command(duplicate_command)

    updated = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events
    refund_events = [
        event
        for event in events
        if event.event_type == telegram_app.PAYMENT_EVENT_REFUND
        and event.charge_id == charge_id
    ]

    assert not pending.processed
    assert pending.status == telegram_app.PAYMENT_EVENT_STATUS_PENDING_RECONCILIATION
    assert refund_events[-1].status == telegram_app.PAYMENT_EVENT_STATUS_PROCESSED
    assert not updated.is_subscription_active()
    assert command.texts[-1][0].startswith("processed: reconciliation finished")
    assert duplicate_command.texts[-1][0].startswith("duplicate: reconciliation finished")


@pytest.mark.anyio
async def test_admin_payment_event_command_applies_chargeback_and_is_idempotent(monkeypatch) -> None:
    admin_id = 719_001
    chat_id = 71_113
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    _save_active_subscription(chat_id)
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id="admin-chargeback-extra-day",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    command = FakeMessage(
        admin_id,
        user_id=admin_id,
        text="/payment_event chargeback telegram_stars admin-chargeback-extra-day",
    )
    duplicate_command = FakeMessage(
        admin_id,
        user_id=admin_id,
        text="/payment_event chargeback telegram_stars admin-chargeback-extra-day",
    )

    await telegram_app.payment_event_reconciliation_command(command)
    await telegram_app.payment_event_reconciliation_command(duplicate_command)

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events
    chargeback_event = [
        event
        for event in events
        if event.event_type == telegram_app.PAYMENT_EVENT_CHARGEBACK
        and event.charge_id == "admin-chargeback-extra-day"
    ][-1]

    assert payment_result.processed
    assert entitlement.extra_one_day_remaining == 0
    assert command.texts[-1][0].startswith("processed: event applied")
    assert duplicate_command.texts[-1][0].startswith("already_processed: event already applied")
    assert chargeback_event.raw_payload["source"] == "admin_reconciliation_command"
    assert chargeback_event.raw_payload["admin_hash"] != str(admin_id)
    assert "admin_id" not in chargeback_event.raw_payload
    assert "user_id" not in chargeback_event.raw_payload


@pytest.mark.anyio
async def test_admin_cancel_subscription_command_keeps_paid_period(monkeypatch) -> None:
    admin_id = 719_002
    chat_id = 71_114
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="admin-cancel-subscription",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    command = FakeMessage(
        admin_id,
        user_id=admin_id,
        text="/payment_event cancel_subscription telegram_stars admin-cancel-subscription",
    )
    refund_command = FakeMessage(
        admin_id,
        user_id=admin_id,
        text="/payment_event refund telegram_stars admin-cancel-subscription",
    )

    await telegram_app.payment_event_reconciliation_command(command)

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events
    cancel_event = [
        event
        for event in events
        if event.event_type == telegram_app.PAYMENT_EVENT_CANCEL_SUBSCRIPTION
        and event.charge_id == "admin-cancel-subscription"
    ][-1]

    assert payment_result.processed
    assert entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == MONTHLY_ONE_DAY_LIMIT
    assert entitlement.monthly_weekly_pdf_remaining == MONTHLY_WEEKLY_PDF_LIMIT
    assert command.texts[-1][0].startswith("processed: event applied")
    assert cancel_event.raw_payload["admin_hash"] != str(admin_id)
    assert "admin_id" not in cancel_event.raw_payload
    assert "user_id" not in cancel_event.raw_payload

    await telegram_app.payment_event_reconciliation_command(refund_command)
    entitlement_after_refund = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert not entitlement_after_refund.is_subscription_active()
    assert refund_command.texts[-1][0].startswith("processed: event applied")


@pytest.mark.anyio
async def test_admin_cancel_subscription_after_refund_is_recorded_separately(monkeypatch) -> None:
    admin_id = 719_006
    chat_id = 71_118
    charge_id = "admin-refund-before-cancel"
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id=charge_id,
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    refund_command = FakeMessage(
        admin_id,
        user_id=admin_id,
        text=f"/payment_event refund telegram_stars {charge_id}",
    )
    cancel_command = FakeMessage(
        admin_id,
        user_id=admin_id,
        text=f"/payment_event cancel_subscription telegram_stars {charge_id}",
    )

    await telegram_app.payment_event_reconciliation_command(refund_command)
    await telegram_app.payment_event_reconciliation_command(cancel_command)

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events
    cancel_events = [
        event
        for event in events
        if event.event_type == telegram_app.PAYMENT_EVENT_CANCEL_SUBSCRIPTION
        and event.charge_id == charge_id
    ]
    cancel_response = cancel_command.texts[-1][0]

    assert payment_result.processed
    assert not entitlement.is_subscription_active()
    assert refund_command.texts[-1][0].startswith("processed: event applied")
    assert not cancel_response.startswith("already_processed: event already applied")
    assert "reason: duplicate_event" not in cancel_response
    assert cancel_events
    assert cancel_events[-1].raw_payload["admin_hash"] != str(admin_id)
    assert "admin_id" not in cancel_events[-1].raw_payload
    assert "user_id" not in cancel_events[-1].raw_payload


@pytest.mark.anyio
async def test_admin_refund_command_can_use_explicit_user_id(monkeypatch) -> None:
    admin_id = 719_004
    chat_id = 71_116
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="admin-refund-subscription",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    command = FakeMessage(
        admin_id,
        user_id=admin_id,
        text=f"/payment_event refund telegram_stars admin-refund-subscription {chat_id}",
    )

    await telegram_app.payment_event_reconciliation_command(command)

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert payment_result.processed
    assert not entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == 0
    assert entitlement.monthly_weekly_pdf_remaining == 0
    assert command.texts[-1][0].startswith("processed: event applied")


@pytest.mark.anyio
async def test_admin_payment_event_command_requires_admin(monkeypatch) -> None:
    admin_id = 719_003
    chat_id = 71_115
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    _save_active_subscription(chat_id)
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id="admin-only-chargeback",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    command = FakeMessage(
        719_999,
        user_id=719_999,
        text="/payment_event chargeback telegram_stars admin-only-chargeback",
    )

    await telegram_app.payment_event_reconciliation_command(command)

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert payment_result.processed
    assert entitlement.extra_one_day_remaining == 1
    assert "only to admins" in command.texts[-1][0]


@pytest.mark.anyio
async def test_admin_payment_event_command_rejects_user_id_mismatch(monkeypatch) -> None:
    admin_id = 719_005
    chat_id = 71_117
    wrong_user_id = 71_118
    monkeypatch.setattr(telegram_app, "ADMIN_USER_IDS", {admin_id})
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="admin-refund-mismatch",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    command = FakeMessage(
        admin_id,
        user_id=admin_id,
        text=f"/payment_event refund telegram_stars admin-refund-mismatch {wrong_user_id}",
    )

    await telegram_app.payment_event_reconciliation_command(command)

    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]
    wrong_entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE).get(wrong_user_id)

    assert payment_result.processed
    assert entitlement.is_subscription_active()
    assert wrong_entitlement is None
    assert command.texts[-1][0].startswith("ignored: user_id_mismatch")


def test_unknown_payment_event_is_ignored_without_breaking_access() -> None:
    chat_id = 71_108

    result = telegram_app._apply_payment_event(
        chat_id,
        event_type="provider-surprise",
        provider="yookassa",
        charge_id="unknown-provider-event",
        amount=1_000,
        currency="RUB",
        raw_payload={"kind": "provider-surprise"},
    )
    entitlements = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)
    events = telegram_app.load_payment_event_state(telegram_app._payment_events_state_file()).events

    assert not result.processed
    assert result.reason == "unknown_event_type"
    assert chat_id not in entitlements
    assert events[-1].event_type == "unknown"
    assert events[-1].status == telegram_app.PAYMENT_EVENT_STATUS_IGNORED_NON_TERMINAL


@pytest.mark.anyio
async def test_cancel_subscription_event_records_cancel_without_revoking_paid_period() -> None:
    chat_id = 71_112
    message = FakeMessage(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="charge-cancel-subscription",
    )
    payment_result = telegram_app._apply_successful_payment(chat_id, payment)

    cancellation = telegram_app._apply_payment_event(
        chat_id,
        event_type=telegram_app.PAYMENT_EVENT_CANCEL_SUBSCRIPTION,
        provider="telegram_stars",
        charge_id="charge-cancel-subscription",
        amount=payment.total_amount,
        currency=payment.currency,
        raw_payload={"source": "telegram"},
    )
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert payment_result.processed
    assert cancellation.processed
    assert entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == MONTHLY_ONE_DAY_LIMIT
    assert entitlement.monthly_weekly_pdf_remaining == MONTHLY_WEEKLY_PDF_LIMIT


def test_payment_raw_payload_is_redacted_to_safe_fields() -> None:
    class PaymentWithSensitiveDump:
        invoice_payload = "payload"
        currency = "RUB"
        total_amount = 12_900
        telegram_payment_charge_id = "tg-charge"
        provider_payment_charge_id = "provider-charge"
        order_info = {"email": "person@example.com", "phone_number": "+79990000000"}

        def model_dump(self, *, mode: str):
            return {
                "invoice_payload": self.invoice_payload,
                "currency": self.currency,
                "total_amount": self.total_amount,
                "order_info": self.order_info,
            }

    raw_payload = telegram_app._payment_raw_payload(PaymentWithSensitiveDump())

    assert raw_payload["invoice_payload"] == "payload"
    assert raw_payload["provider_payment_charge_id"] == "provider-charge"
    assert "order_info" not in raw_payload
    assert "email" not in raw_payload


def test_legacy_payloads_are_disabled_by_default_even_before_deadline(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "ALLOW_LEGACY_PAYMENT_PAYLOADS", False)
    monkeypatch.setattr(telegram_app, "ALLOW_LEGACY_PAYLOADS_UNTIL", datetime(2099, 5, 17, tzinfo=UTC))
    query = SimpleNamespace(
        invoice_payload=telegram_app.PAYLOAD_SUBSCRIPTION_MONTH,
        currency="XTR",
        total_amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
    )
    payment = _successful_payment(
        telegram_app.PAYLOAD_SUBSCRIPTION_MONTH,
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="legacy-default-off",
    )

    pre_checkout_valid = telegram_app._is_valid_pre_checkout(query)
    result = telegram_app._apply_successful_payment(71_113, payment)

    assert not pre_checkout_valid
    assert not result.processed


@pytest.mark.anyio
async def test_successful_payment_from_other_user_id_is_rejected() -> None:
    buyer_id = 71_103
    other_user_id = 71_104
    message = FakeMessage(buyer_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="charge-wrong-user",
    )

    result = telegram_app._apply_successful_payment(other_user_id, payment)
    entitlements = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)
    state = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE)

    assert not result.processed
    assert result.grant == "subscription"
    assert other_user_id not in entitlements
    assert state.orphan_payments[-1]["reason"] == "user_mismatch"


@pytest.mark.anyio
async def test_stars_and_yookassa_orders_preserve_product_type_and_provider() -> None:
    expected = [
        (telegram_app._send_stars_invoice_link, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH, "subscription_month", "telegram_stars", "XTR", True),
        (telegram_app._send_stars_invoice_link, telegram_app.PAYLOAD_EXTRA_ONE_DAY, "extra_one_day", "telegram_stars", "XTR", False),
        (telegram_app._send_stars_invoice_link, telegram_app.PAYLOAD_EXTRA_WEEKLY_PDF, "extra_weekly_pdf", "telegram_stars", "XTR", False),
        (telegram_app._send_yookassa_invoice_link, telegram_app.PAYLOAD_RU_SUBSCRIPTION_MONTH, "subscription_month", "yookassa", "RUB", False),
        (telegram_app._send_yookassa_invoice_link, telegram_app.PAYLOAD_RU_EXTRA_ONE_DAY, "extra_one_day", "yookassa", "RUB", False),
        (telegram_app._send_yookassa_invoice_link, telegram_app.PAYLOAD_RU_EXTRA_WEEKLY_PDF, "extra_weekly_pdf", "yookassa", "RUB", False),
    ]

    for index, (send_invoice, payload, product, provider, currency, is_recurring) in enumerate(expected):
        message = FakeMessage(71_200 + index)

        await send_invoice(message, payload)

        invoice = message.bot.invoice_links[0]
        order_id, _ = telegram_app.decode_payment_order_payload(invoice["payload"]) or ("", "")
        order = telegram_app.load_payment_order_state(telegram_app.PAYMENT_ORDERS_STATE_FILE).orders[order_id]
        assert order.product == product
        assert order.provider == provider
        assert order.currency == currency
        assert order.is_recurring is is_recurring


@pytest.mark.anyio
async def test_invoice_creation_tracks_checkout_and_invoice_events(monkeypatch) -> None:
    events: list[tuple[int | None, str, dict[str, object] | None]] = []

    async def fake_track_event(user_id, event_name, properties=None):
        events.append((user_id, event_name, properties))

    monkeypatch.setattr(telegram_app, "_track_event_async", fake_track_event)
    message = FakeMessage(71_115)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_SUBSCRIPTION_MONTH)

    assert [(event_name, (properties or {})["product"]) for _, event_name, properties in events] == [
        ("checkout_started", "subscription_month"),
        ("invoice_created", "subscription_month"),
    ]
    assert all(user_id == 71_115 for user_id, _, _ in events)


def test_promo_code_grants_subscription_access_and_cannot_be_reused() -> None:
    chat_id = 71_105
    promo_code = "FB-ABCD-EFGH-2345"
    save_promo_codes(telegram_app.PROMO_CODES_STATE_FILE, {promo_code: PromoCodeRecord()})

    first = telegram_app._activate_promo_code_for_chat(chat_id, "fb abcd efgh 2345")
    second = telegram_app._activate_promo_code_for_chat(chat_id, promo_code)
    entitlement = telegram_app.load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id]

    assert first.activated
    assert second.status == "already_used"
    assert entitlement.is_subscription_active()
    assert entitlement.monthly_one_day_remaining == MONTHLY_ONE_DAY_LIMIT
    assert entitlement.monthly_weekly_pdf_remaining == MONTHLY_WEEKLY_PDF_LIMIT


def _successful_payment(
    payload: str,
    *,
    currency: str,
    amount: int,
    charge_id: str,
    provider_charge_id: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        invoice_payload=payload,
        currency=currency,
        total_amount=amount,
        telegram_payment_charge_id=charge_id,
        provider_payment_charge_id=provider_charge_id,
    )


def _refunded_payment(payment: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        invoice_payload=payment.invoice_payload,
        currency=payment.currency,
        total_amount=payment.total_amount,
        telegram_payment_charge_id=payment.telegram_payment_charge_id,
        provider_payment_charge_id=payment.provider_payment_charge_id,
    )


def _save_active_subscription(chat_id: int) -> None:
    now = datetime(2026, 5, 10, tzinfo=UTC)
    entitlement = Entitlement()
    apply_subscription_payment(
        entitlement,
        "seed-subscription",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )
    entitlement.monthly_one_day_remaining = 1
    entitlement.monthly_weekly_pdf_remaining = 1
    save_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE, {chat_id: entitlement})
