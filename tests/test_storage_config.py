from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import diet_bot.telegram_app as telegram_app
from diet_bot.payments import encode_payment_order_payload
from diet_bot.subscriptions import Entitlement, apply_subscription_payment, load_entitlements, save_entitlements


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_app, "PAYMENT_ORDERS_STATE_FILE", tmp_path / "payment_orders.json")
    monkeypatch.setattr(telegram_app, "PAYMENT_EVENTS_STATE_FILE", tmp_path / "payment_events.json")
    monkeypatch.setattr(telegram_app, "SUBSCRIPTIONS_STATE_FILE", tmp_path / "subscriptions.json")
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "")
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "development")
    monkeypatch.setattr(telegram_app, "ALLOW_JSON_STORAGE", True)
    monkeypatch.setattr(telegram_app, "_POSTGRES_STORE", None)


@pytest.mark.anyio
async def test_production_without_database_url_does_not_start(monkeypatch) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")

    def fail_if_constructed(token: str):
        raise AssertionError("Bot should not be constructed without production storage.")

    monkeypatch.setattr(telegram_app, "Bot", fail_if_constructed)

    with pytest.raises(RuntimeError, match="DIET_BOT_DATABASE_URL is required in production"):
        await telegram_app.run_bot()


@pytest.mark.anyio
async def test_production_without_support_chat_id_does_not_start(monkeypatch) -> None:
    monkeypatch.setenv("DIET_BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "postgresql://diet_bot:secret@postgres:5432/diet_bot")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID_RAW", "")
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")

    def fail_if_constructed(token: str):
        raise AssertionError("Bot should not be constructed without production support config.")

    monkeypatch.setattr(telegram_app, "Bot", fail_if_constructed)

    with pytest.raises(RuntimeError, match="DIET_BOT_SUPPORT_CHAT_ID is required in production"):
        await telegram_app.run_bot()


def test_development_can_use_json_storage_fallback(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "development")
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "")
    monkeypatch.setattr(telegram_app, "ALLOW_JSON_STORAGE", True)

    assert telegram_app._postgres_store() is None


def test_development_tester_ids_can_use_json_best_effort_shortcut(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "development")
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "")
    monkeypatch.setattr(telegram_app, "ALLOW_JSON_STORAGE", True)
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", {91_004})

    consumption = telegram_app._consume_generation_attempt(91_004, "weekly_pdf")

    assert consumption.allowed
    assert consumption.source == "test_access"


def test_production_tester_ids_do_not_bypass_missing_postgres(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "")
    monkeypatch.setattr(telegram_app, "ALLOW_JSON_STORAGE", True)
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", {91_005})

    with pytest.raises(RuntimeError, match="DIET_BOT_DATABASE_URL is required in production"):
        telegram_app._consume_generation_attempt(91_005, "weekly_pdf")


def test_production_tester_ids_use_durable_store_result(monkeypatch) -> None:
    class FakeStore:
        def __init__(self) -> None:
            self.calls = []

        def consume_generation_attempt(self, chat_id, ration_kind):
            self.calls.append((chat_id, ration_kind))
            return telegram_app.AttemptConsumption(False, ration_kind, denial_reason="paywall")

    store = FakeStore()
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "postgresql://diet_bot:secret@postgres:5432/diet_bot")
    monkeypatch.setattr(telegram_app, "TESTER_CHAT_IDS", {91_006})
    monkeypatch.setattr(telegram_app, "_POSTGRES_STORE", store)

    consumption = telegram_app._consume_generation_attempt(91_006, "weekly_pdf")

    assert not consumption.allowed
    assert consumption.denial_reason == "paywall"
    assert store.calls == [(91_006, "weekly_pdf")]


def test_development_without_json_storage_flag_rejects_fallback(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "development")
    monkeypatch.setattr(telegram_app, "DIET_BOT_DATABASE_URL", "")
    monkeypatch.setattr(telegram_app, "ALLOW_JSON_STORAGE", False)

    with pytest.raises(RuntimeError, match="DIET_BOT_DATABASE_URL is required"):
        telegram_app._postgres_store()


def test_placeholder_database_url_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_app,
        "DIET_BOT_DATABASE_URL",
        "postgresql://diet_bot:YOUR_POSTGRES_PASSWORD@postgres:5432/diet_bot",
    )

    with pytest.raises(RuntimeError, match="DIET_BOT_DATABASE_URL contains an example placeholder"):
        telegram_app._postgres_store()


def test_production_runtime_requires_support_chat_id(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID_RAW", "")
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")

    with pytest.raises(RuntimeError, match="DIET_BOT_SUPPORT_CHAT_ID is required in production"):
        telegram_app.validate_runtime_config()


def test_production_runtime_rejects_invalid_support_chat_id(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID_RAW", "not-a-chat-id")
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")

    with pytest.raises(RuntimeError, match="DIET_BOT_SUPPORT_CHAT_ID must be an integer"):
        telegram_app.validate_runtime_config()


@pytest.mark.parametrize(
    "privacy_url",
    [
        "",
        "http://foodbalance.app/privacy",
        "https://localhost/privacy",
        "https://example.com/privacy",
        "https://foodbalance.local/privacy",
    ],
)
def test_production_runtime_requires_public_privacy_url(monkeypatch, privacy_url: str) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID_RAW", "-100555111222")
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", privacy_url)

    with pytest.raises(RuntimeError, match="DIET_BOT_PRIVACY_POLICY_URL"):
        telegram_app.validate_runtime_config()


def test_development_runtime_allows_missing_support_and_privacy(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "development")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID_RAW", "")
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", "")

    telegram_app.validate_runtime_config()


def test_production_runtime_accepts_support_and_public_privacy(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID_RAW", "-100555111222")
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")

    telegram_app.validate_runtime_config()


def test_production_runtime_rejects_invalid_posthog_host(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "DIET_BOT_ENV", "production")
    monkeypatch.setattr(telegram_app, "SUPPORT_CHAT_ID_RAW", "-100555111222")
    monkeypatch.setattr(telegram_app, "PRIVACY_POLICY_URL", "https://foodbalance.app/privacy")
    monkeypatch.setattr(telegram_app, "POSTHOG_API_KEY", "ph-key")
    monkeypatch.setattr(telegram_app, "POSTHOG_HOST", "http://localhost:8000")

    with pytest.raises(RuntimeError, match="POSTHOG_HOST must be a public HTTPS URL"):
        telegram_app.validate_runtime_config()


def test_corrupted_json_storage_does_not_grant_limit_access() -> None:
    telegram_app.SUBSCRIPTIONS_STATE_FILE.write_text("{broken", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Invalid entitlements state file"):
        telegram_app._consume_generation_attempt(91_001, "one_day")


def test_corrupted_payment_order_json_does_not_grant_payment_access() -> None:
    telegram_app.PAYMENT_ORDERS_STATE_FILE.write_text("{broken", encoding="utf-8")
    payment = _successful_payment(
        encode_payment_order_payload("order-1", "nonce-1"),
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_SUBSCRIPTION_MONTH],
        charge_id="charge-corrupt-order-json",
    )

    with pytest.raises(RuntimeError, match="Invalid payment order state file"):
        telegram_app._apply_successful_payment(91_002, payment)

    assert not telegram_app.SUBSCRIPTIONS_STATE_FILE.exists()


@pytest.mark.anyio
async def test_duplicate_payment_idempotency_survives_restart(monkeypatch) -> None:
    chat_id = 91_003
    message = FakeMessage(chat_id)
    _save_active_subscription(chat_id)

    await telegram_app._send_stars_invoice_link(message, telegram_app.PAYLOAD_EXTRA_ONE_DAY)
    payment = _successful_payment(
        message.bot.invoice_links[0]["payload"],
        currency="XTR",
        amount=telegram_app.PAYMENT_PAYLOAD_AMOUNTS[telegram_app.PAYLOAD_EXTRA_ONE_DAY],
        charge_id="charge-after-restart",
    )

    first = telegram_app._apply_successful_payment(chat_id, payment)
    before_restart = load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id].to_dict()
    monkeypatch.setattr(telegram_app, "_POSTGRES_STORE", None)

    second = telegram_app._apply_successful_payment(chat_id, payment)
    after_restart = load_entitlements(telegram_app.SUBSCRIPTIONS_STATE_FILE)[chat_id].to_dict()

    assert first.processed
    assert not second.processed
    assert second.duplicate
    assert before_restart == after_restart
    assert after_restart["extra_one_day_remaining"] == 1


class FakeInvoiceBot:
    def __init__(self) -> None:
        self.invoice_links: list[dict] = []

    async def create_invoice_link(self, **kwargs) -> str:
        self.invoice_links.append(kwargs)
        return f"https://t.me/invoice/{len(self.invoice_links)}"


class FakeMessage:
    def __init__(self, chat_id: int) -> None:
        self.chat = SimpleNamespace(id=chat_id, type="private")
        self.from_user = SimpleNamespace(id=chat_id)
        self.bot = FakeInvoiceBot()
        self.texts: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None):
        self.texts.append((text, reply_markup))
        return SimpleNamespace(text=text, reply_markup=reply_markup)


def _successful_payment(payload: str, *, currency: str, amount: int, charge_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        invoice_payload=payload,
        currency=currency,
        total_amount=amount,
        telegram_payment_charge_id=charge_id,
        provider_payment_charge_id="",
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
