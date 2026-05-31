import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import count
from threading import Lock
from types import SimpleNamespace

import pytest

from diet_bot.payment_service import PaymentService
from diet_bot.payments import (
    ORDER_STATUS_FAILED,
    ORDER_STATUS_PENDING,
    PRODUCT_EXTRA_ONE_DAY,
    PRODUCT_EXTRA_WEEKLY_PDF,
    PRODUCT_SUBSCRIPTION_MONTH,
    PROVIDER_TELEGRAM_STARS,
    PROVIDER_YOOKASSA,
    PaymentCharge,
    PaymentOrder,
    PaymentPayloadError,
    PaymentProductPrice,
    decode_payment_order_payload,
    encode_payment_order_payload,
    expected_payment_price,
)
from scripts.ops import apply_payment_reversal as payment_reversal_cli


def test_payment_order_payload_roundtrip() -> None:
    payload = encode_payment_order_payload("order_1234567890", "nonce_abcdef123456")

    decoded = decode_payment_order_payload(payload)

    assert decoded is not None
    assert decoded.order_id == "order_1234567890"
    assert decoded.nonce == "nonce_abcdef123456"
    assert len(payload) <= 128


@pytest.mark.parametrize(
    "payload",
    [
        "diet:stars:subscription_month",
        "diet:stars:extra_one_day",
        "diet:stars:extra_weekly_pdf",
        "diet:rub:subscription_month",
        "diet:rub:extra_one_day",
        "diet:rub:extra_weekly_pdf",
        "some-other-payload",
        "",
    ],
)
def test_static_or_non_order_payload_decodes_as_none(payload: str) -> None:
    assert decode_payment_order_payload(payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        "diet:order:v1",
        "diet:order:v2:order_12345678:nonce_12345678:checksum",
        "diet:order:v1:short:nonce_12345678:checksum",
        "diet:order:v1:order_12345678:short:checksum",
        "diet:order:v1:order_12345678:nonce_12345678:not-valid",
    ],
)
def test_malformed_order_payloads_are_rejected(payload: str) -> None:
    with pytest.raises(PaymentPayloadError):
        decode_payment_order_payload(payload)


def test_tampered_order_payload_checksum_is_rejected() -> None:
    payload = encode_payment_order_payload("order_1234567890", "nonce_abcdef123456")
    tampered = payload.replace("order_1234567890", "order_1234567899")

    with pytest.raises(PaymentPayloadError, match="checksum"):
        decode_payment_order_payload(tampered)


@pytest.mark.parametrize(
    ("provider", "product", "expected"),
    [
        (
            PROVIDER_TELEGRAM_STARS,
            PRODUCT_SUBSCRIPTION_MONTH,
            PaymentProductPrice(amount=450, currency="XTR"),
        ),
        (PROVIDER_TELEGRAM_STARS, PRODUCT_EXTRA_ONE_DAY, PaymentProductPrice(amount=29, currency="XTR")),
        (
            PROVIDER_TELEGRAM_STARS,
            PRODUCT_EXTRA_WEEKLY_PDF,
            PaymentProductPrice(amount=141, currency="XTR"),
        ),
        (PROVIDER_YOOKASSA, PRODUCT_SUBSCRIPTION_MONTH, PaymentProductPrice(amount=79_900, currency="RUB")),
        (PROVIDER_YOOKASSA, PRODUCT_EXTRA_ONE_DAY, PaymentProductPrice(amount=5_000, currency="RUB")),
        (PROVIDER_YOOKASSA, PRODUCT_EXTRA_WEEKLY_PDF, PaymentProductPrice(amount=25_000, currency="RUB")),
    ],
)
def test_expected_payment_price_matches_existing_static_products(
    provider: str,
    product: str,
    expected: PaymentProductPrice,
) -> None:
    assert expected_payment_price(provider, product) == expected


def test_create_order_reuses_active_pending_order_for_same_payment_key() -> None:
    repo = PendingReusePaymentRepository()
    service = _payment_service(repo)

    first = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    second = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )

    assert second.order_id == first.order_id
    assert second.nonce == first.nonce
    assert len(repo.orders) == 1


def test_concurrent_create_order_reuses_one_active_pending_order_for_same_payment_key() -> None:
    repo = PendingReusePaymentRepository()
    service = _payment_service(repo)

    def create_order() -> PaymentOrder:
        return service.create_order(
            user_id=101,
            chat_id=202,
            product=PRODUCT_SUBSCRIPTION_MONTH,
            provider=PROVIDER_TELEGRAM_STARS,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        orders = list(executor.map(lambda _index: create_order(), range(16)))

    assert {order.order_id for order in orders} == {orders[0].order_id}
    assert len(repo.orders) == 1


def test_create_order_allows_distinct_pending_orders_for_different_products() -> None:
    repo = PendingReusePaymentRepository()
    service = _payment_service(repo)

    subscription = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    extra_day = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_EXTRA_ONE_DAY,
        provider=PROVIDER_TELEGRAM_STARS,
    )

    assert extra_day.order_id != subscription.order_id
    assert {order.product for order in repo.orders.values()} == {
        PRODUCT_SUBSCRIPTION_MONTH,
        PRODUCT_EXTRA_ONE_DAY,
    }


def test_create_order_ignores_expired_or_failed_pending_order_for_same_payment_key() -> None:
    now = datetime(2026, 5, 31, 12, tzinfo=UTC)
    repo = PendingReusePaymentRepository()
    service = _payment_service(repo, now=now)
    first = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    repo.orders[first.order_id] = replace(first, created_at=now - timedelta(minutes=31))

    after_expired = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    repo.orders[after_expired.order_id] = replace(after_expired, status=ORDER_STATUS_FAILED)
    after_failed = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )

    assert after_expired.order_id != first.order_id
    assert after_failed.order_id != after_expired.order_id
    assert repo.orders[first.order_id].status == ORDER_STATUS_FAILED
    assert repo.orders[after_expired.order_id].status == ORDER_STATUS_FAILED
    assert repo.orders[after_failed.order_id].status == ORDER_STATUS_PENDING


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"provider": PROVIDER_YOOKASSA}, "provider_mismatch"),
        ({"amount": "mismatched"}, "amount_mismatch"),
        ({"currency": "RUB"}, "currency_mismatch"),
    ],
)
def test_reused_pending_order_keeps_original_amount_currency_provider_validation(
    override: dict[str, object],
    reason: str,
) -> None:
    repo = PendingReusePaymentRepository()
    service = _payment_service(repo)
    order = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )
    reused = service.create_order(
        user_id=101,
        chat_id=202,
        product=PRODUCT_SUBSCRIPTION_MONTH,
        provider=PROVIDER_TELEGRAM_STARS,
    )

    request = {
        "user_id": 101,
        "chat_id": 202,
        "provider": PROVIDER_TELEGRAM_STARS,
        "amount": order.amount,
        "currency": order.currency,
    }
    if override.get("amount") == "mismatched":
        override = {**override, "amount": order.amount + 1}
    request.update(override)

    validation = service.validate_order_payment(
        encode_payment_order_payload(reused.order_id, reused.nonce),
        **request,
    )

    assert reused.order_id == order.order_id
    assert not validation.valid
    assert validation.reason == reason


def test_payment_service_routes_provider_reversal_to_repository() -> None:
    repo = ReversalPaymentRepository()
    service = PaymentService(repo)
    assert hasattr(service, "handle_payment_reversal")

    result = service.handle_payment_reversal(
        provider=PROVIDER_TELEGRAM_STARS,
        telegram_payment_charge_id="tg-charge-refund",
        provider_payment_charge_id=None,
        reversal_status="refunded",
        amount=450,
        currency="XTR",
        raw_payload={"provider_status": "refunded"},
    )

    assert result.processed
    assert not result.manual_review_required
    assert repo.reversal_requests == [
        {
            "provider": PROVIDER_TELEGRAM_STARS,
            "telegram_payment_charge_id": "tg-charge-refund",
            "provider_payment_charge_id": None,
            "reversal_status": "refunded",
            "amount": 450,
            "currency": "XTR",
            "raw_payload": {"provider_status": "refunded"},
        }
    ]


def test_apply_payment_reversal_cli_defaults_to_dry_run_without_mutating() -> None:
    charge = PaymentCharge(
        order_id="order_cli_dry_run",
        provider=PROVIDER_TELEGRAM_STARS,
        telegram_payment_charge_id="tg-charge-cli-dry-run",
        provider_payment_charge_id="provider-charge-cli-dry-run",
        amount=450,
        currency="XTR",
    )
    store = OperatorReversalStore(charge=charge)
    stdout = io.StringIO()
    stderr = io.StringIO()
    secret_dsn = "postgresql://user:secret-token@localhost/diet_bot_test"

    exit_code = payment_reversal_cli.main(
        [
            "--provider",
            PROVIDER_TELEGRAM_STARS,
            "--telegram-payment-charge-id",
            "tg-charge-cli-dry-run",
            "--kind",
            "refund",
            "--event-timestamp",
            "2026-05-31T12:00:00Z",
            "--amount",
            "450",
            "--currency",
            "XTR",
            "--reason",
            "provider refund event",
        ],
        env={"DIET_BOT_DATABASE_URL": secret_dsn},
        store_factory=lambda _dsn: store,
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    combined_output = stdout.getvalue() + stderr.getvalue()
    assert exit_code == 0
    assert payload["action"] == "dry_run"
    assert payload["status"] == "would_apply"
    assert payload["would"]["charge_status"] == "refunded"
    assert payload["would"]["order_failure_reason"] == "payment_refunded"
    assert payload["would"]["entitlement_reversal"] == "will_apply"
    assert store.reversal_requests == []
    assert secret_dsn not in combined_output
    assert "secret-token" not in combined_output
    assert "tg-charge-cli-dry-run" not in combined_output
    assert "provider-charge-cli-dry-run" not in combined_output
    assert "order_cli_dry_run" not in combined_output


def test_apply_payment_reversal_cli_apply_routes_to_service_with_audit_payload() -> None:
    charge = PaymentCharge(
        order_id="order_cli_apply",
        provider=PROVIDER_TELEGRAM_STARS,
        telegram_payment_charge_id="tg-charge-cli-apply",
        provider_payment_charge_id="provider-charge-cli-apply",
        amount=450,
        currency="XTR",
    )
    store = OperatorReversalStore(charge=charge)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = payment_reversal_cli.main(
        [
            "--provider",
            PROVIDER_TELEGRAM_STARS,
            "--provider-payment-id",
            "provider-charge-cli-apply",
            "--kind",
            "cancel",
            "--event-timestamp",
            "2026-05-31T13:14:15Z",
            "--amount",
            "450",
            "--currency",
            "XTR",
            "--reason",
            "operator verified provider cancel",
            "--operator",
            "ops-user",
            "--apply",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret-token@localhost/diet_bot_test"},
        store_factory=lambda _dsn: store,
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["action"] == "apply"
    assert payload["status"] == "applied"
    assert len(store.reversal_requests) == 1
    request = store.reversal_requests[0]
    assert request["provider"] == PROVIDER_TELEGRAM_STARS
    assert request["telegram_payment_charge_id"] == "tg-charge-cli-apply"
    assert request["provider_payment_charge_id"] == "provider-charge-cli-apply"
    assert request["reversal_status"] == "canceled"
    assert request["amount"] == 450
    assert request["currency"] == "XTR"
    assert request["now"] == datetime(2026, 5, 31, 13, 14, 15, tzinfo=UTC)
    assert request["raw_payload"] == {
        "event_timestamp": "2026-05-31T13:14:15Z",
        "operator": "ops-user",
        "operator_reason": "operator verified provider cancel",
        "provider_event_kind": "cancel",
        "source": "operator_apply_payment_reversal",
    }


def test_apply_payment_reversal_cli_resolves_order_identifier_before_apply() -> None:
    charge = PaymentCharge(
        order_id="order_cli_lookup",
        provider=PROVIDER_TELEGRAM_STARS,
        telegram_payment_charge_id="tg-charge-cli-lookup",
        provider_payment_charge_id=None,
        amount=29,
        currency="XTR",
    )
    store = OperatorReversalStore(charge=charge)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = payment_reversal_cli.main(
        [
            "--provider",
            PROVIDER_TELEGRAM_STARS,
            "--order-id",
            "order_cli_lookup",
            "--kind",
            "reversal",
            "--event-timestamp",
            "2026-05-31T14:00:00Z",
            "--apply",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret-token@localhost/diet_bot_test"},
        store_factory=lambda _dsn: store,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert store.order_id_lookups == ["order_cli_lookup"]
    assert store.reversal_requests[0]["telegram_payment_charge_id"] == "tg-charge-cli-lookup"
    assert store.reversal_requests[0]["provider_payment_charge_id"] is None
    assert store.reversal_requests[0]["reversal_status"] == "reversed"


@pytest.mark.parametrize(
    ("amount", "currency", "reason"),
    [
        (451, "XTR", "partial_refund_manual_review"),
        (450, "RUB", "currency_mismatch"),
    ],
)
def test_apply_payment_reversal_cli_dry_run_mismatch_goes_to_manual_review_without_apply(
    amount: int,
    currency: str,
    reason: str,
) -> None:
    charge = PaymentCharge(
        order_id="order_cli_mismatch",
        provider=PROVIDER_TELEGRAM_STARS,
        telegram_payment_charge_id="tg-charge-cli-mismatch",
        provider_payment_charge_id=None,
        amount=450,
        currency="XTR",
    )
    store = OperatorReversalStore(charge=charge)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = payment_reversal_cli.main(
        [
            "--provider",
            PROVIDER_TELEGRAM_STARS,
            "--telegram-payment-charge-id",
            "tg-charge-cli-mismatch",
            "--kind",
            "refund",
            "--event-timestamp",
            "2026-05-31T15:00:00Z",
            "--amount",
            str(amount),
            "--currency",
            currency,
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret-token@localhost/diet_bot_test"},
        store_factory=lambda _dsn: store,
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["status"] == "would_manual_review"
    assert payload["would"]["manual_review_required"]
    assert payload["would"]["reason"] == reason
    assert payload["would"]["entitlement_reversal"] == "skipped_mismatch"
    assert store.reversal_requests == []


def test_apply_payment_reversal_cli_rejects_missing_required_identifier() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = payment_reversal_cli.main(
        [
            "--provider",
            PROVIDER_TELEGRAM_STARS,
            "--kind",
            "refund",
            "--event-timestamp",
            "2026-05-31T12:00:00Z",
        ],
        env={"DIET_BOT_DATABASE_URL": "postgresql://user:secret-token@localhost/diet_bot_test"},
        store_factory=lambda _dsn: OperatorReversalStore(),
        stdout=stdout,
        stderr=stderr,
    )

    combined_output = stdout.getvalue() + stderr.getvalue()
    assert exit_code == 2
    assert "identifier" in stderr.getvalue()
    assert "secret-token" not in combined_output
    assert stdout.getvalue() == ""


def test_apply_payment_reversal_cli_redacts_database_url_on_store_failure() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    secret_dsn = "postgresql://user:secret-token@localhost/diet_bot_test"

    exit_code = payment_reversal_cli.main(
        [
            "--provider",
            PROVIDER_TELEGRAM_STARS,
            "--telegram-payment-charge-id",
            "tg-charge-cli-error",
            "--kind",
            "refund",
            "--event-timestamp",
            "2026-05-31T12:00:00Z",
        ],
        env={"DIET_BOT_DATABASE_URL": secret_dsn},
        store_factory=lambda _dsn: (_ for _ in ()).throw(RuntimeError("boom with secret-token")),
        stdout=stdout,
        stderr=stderr,
    )

    combined_output = stdout.getvalue() + stderr.getvalue()
    assert exit_code == 2
    assert "database details redacted" in stderr.getvalue()
    assert secret_dsn not in combined_output
    assert "secret-token" not in combined_output
    assert stdout.getvalue() == ""


def _payment_service(repo: "PendingReusePaymentRepository", *, now: datetime | None = None) -> PaymentService:
    sequence = count(1)

    def next_token(prefix: str) -> str:
        with repo.factory_lock:
            return f"{prefix}_{next(sequence):08d}"

    return PaymentService(
        repo,
        order_id_factory=lambda: next_token("order"),
        nonce_factory=lambda: next_token("nonce"),
        now_factory=lambda: now or datetime(2026, 5, 31, 12, tzinfo=UTC),
    )


class PendingReusePaymentRepository:
    def __init__(self) -> None:
        self.orders: dict[str, PaymentOrder] = {}
        self.lock = Lock()
        self.factory_lock = Lock()

    def create_order(self, order: PaymentOrder) -> PaymentOrder:
        with self.lock:
            self.orders[order.order_id] = order
            return order

    def create_or_reuse_pending_order(
        self,
        order: PaymentOrder,
        *,
        pending_ttl: timedelta | None,
        now: datetime,
    ) -> PaymentOrder:
        with self.lock:
            for existing in list(self.orders.values()):
                if not _same_pending_key(existing, order):
                    continue
                if existing.status != ORDER_STATUS_PENDING:
                    continue
                if _is_expired(existing, pending_ttl, now):
                    self.orders[existing.order_id] = replace(
                        existing,
                        status=ORDER_STATUS_FAILED,
                        failure_reason="order_expired",
                    )
                    continue
                return replace(existing, reused_pending=True)
            self.orders[order.order_id] = order
            return order

    def get_order(self, order_id: str) -> PaymentOrder | None:
        return self.orders.get(order_id)

    def record_event(self, _event):
        raise NotImplementedError

    def record_charge(self, _charge):
        raise NotImplementedError

    def mark_order_paid(self, order_id: str) -> PaymentOrder:
        return self._mark(order_id, "paid")

    def mark_order_granted(self, order_id: str) -> PaymentOrder:
        return self._mark(order_id, "granted")

    def mark_order_failed(self, order_id: str, reason: str | None = None) -> PaymentOrder:
        order = replace(self.orders[order_id], status=ORDER_STATUS_FAILED, failure_reason=reason)
        self.orders[order_id] = order
        return order

    def _mark(self, order_id: str, status: str) -> PaymentOrder:
        order = replace(self.orders[order_id], status=status)
        self.orders[order_id] = order
        return order


class ReversalPaymentRepository:
    def __init__(self) -> None:
        self.reversal_requests: list[dict[str, object]] = []

    def record_payment_reversal(self, **kwargs: object):
        self.reversal_requests.append(dict(kwargs))
        return SimpleNamespace(
            processed=True,
            manual_review_required=False,
            duplicate=False,
            reason=None,
        )


class OperatorReversalStore:
    def __init__(
        self,
        *,
        charge: PaymentCharge | None = None,
        result: object | None = None,
    ) -> None:
        self.charge = charge
        self.result = result or SimpleNamespace(
            processed=True,
            manual_review_required=False,
            duplicate=False,
            reason=None,
            order_id=charge.order_id if charge is not None else None,
            charge_status="refunded",
        )
        self.reversal_requests: list[dict[str, object]] = []
        self.external_id_lookups: list[dict[str, object]] = []
        self.order_id_lookups: list[str] = []

    def find_charge_by_external_id(
        self,
        *,
        provider: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
    ) -> PaymentCharge | None:
        self.external_id_lookups.append(
            {
                "provider": provider,
                "telegram_payment_charge_id": telegram_payment_charge_id,
                "provider_payment_charge_id": provider_payment_charge_id,
            }
        )
        if self.charge is None:
            return None
        if self.charge.provider != provider:
            return None
        if telegram_payment_charge_id and self.charge.telegram_payment_charge_id == telegram_payment_charge_id:
            return self.charge
        if provider_payment_charge_id and self.charge.provider_payment_charge_id == provider_payment_charge_id:
            return self.charge
        return None

    def find_charge_by_order_id(self, order_id: str) -> PaymentCharge | None:
        self.order_id_lookups.append(order_id)
        if self.charge is not None and self.charge.order_id == order_id:
            return self.charge
        return None

    def record_payment_reversal(self, **kwargs: object):
        self.reversal_requests.append(dict(kwargs))
        return self.result


def _same_pending_key(left: PaymentOrder, right: PaymentOrder) -> bool:
    return (
        int(left.chat_id) == int(right.chat_id)
        and left.product == right.product
        and left.provider == right.provider
        and int(left.amount) == int(right.amount)
        and left.currency == right.currency
    )


def _is_expired(order: PaymentOrder, pending_ttl: timedelta | None, now: datetime) -> bool:
    if pending_ttl is None or order.created_at is None:
        return False
    created_at = order.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at + pending_ttl < now
