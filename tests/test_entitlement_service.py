from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from diet_bot.entitlement_service import EntitlementService
from diet_bot.entitlement_storage import JsonEntitlementStore
from diet_bot.subscriptions import Entitlement


def test_service_consumes_and_refunds_weekly_pdf(tmp_path: Path) -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    service = _service(tmp_path)
    chat_id = 123
    service.apply_subscription_payment(
        chat_id,
        "charge-subscription",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )

    consumption = service.consume_weekly_pdf(chat_id, now=now)
    after_consume = service.get_entitlement(chat_id, now=now)

    assert consumption.allowed
    assert consumption.source == "monthly"
    assert after_consume.monthly_weekly_pdf_remaining == 3

    service.refund_weekly_pdf(chat_id, consumption)

    assert service.get_entitlement(chat_id, now=now).monthly_weekly_pdf_remaining == 4


def test_service_grants_revokes_and_toggles_test_access(tmp_path: Path) -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    service = _service(tmp_path)
    chat_id = 456

    granted = service.grant_test_access(chat_id, now=now)
    disabled, disabled_entitlement = service.set_test_access_enabled(chat_id, False, now=now)
    enabled, enabled_entitlement = service.set_test_access_enabled(chat_id, True, now=now)
    revoked = service.revoke_test_access(chat_id)

    assert granted.is_test_access_active(now)
    assert disabled
    assert not disabled_entitlement.test_access_enabled
    assert enabled
    assert enabled_entitlement.is_test_access_active(now)
    assert revoked.test_access_until is None
    assert not revoked.test_access_enabled


def test_service_records_and_checks_processed_charge_ids(tmp_path: Path) -> None:
    service = _service(tmp_path)
    chat_id = 789

    assert not service.has_processed_charge_id(chat_id, "charge-1")
    assert service.record_processed_charge_id(chat_id, "charge-1")
    assert service.has_processed_charge_id(chat_id, "charge-1")
    assert not service.record_processed_charge_id(chat_id, "charge-1")


def test_service_status_and_grant_use_row_level_store_methods() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    chat_id = 2468
    store = _RowLevelOnlyEntitlementStore()
    service = EntitlementService(store)

    entitlement = service.get_entitlement(chat_id, now=now)
    granted = service.grant_test_access(chat_id, now=now)

    assert entitlement == Entitlement()
    assert granted.is_test_access_active(now)
    assert store.load_chat_calls == []
    assert store.transact_chat_calls == [chat_id, chat_id]


def test_service_payment_and_charge_checks_use_row_level_store_methods() -> None:
    now = datetime(2026, 5, 8, tzinfo=UTC)
    chat_id = 1357
    store = _RowLevelOnlyEntitlementStore()
    service = EntitlementService(store)

    result = service.apply_subscription_payment(
        chat_id,
        "charge-subscription",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )

    assert result.processed
    assert service.has_processed_charge_id(chat_id, "charge-subscription")
    assert not service.record_processed_charge_id(chat_id, "charge-subscription")
    assert store.load_chat_calls == [chat_id]
    assert store.transact_chat_calls == [chat_id, chat_id]


def _service(tmp_path: Path) -> EntitlementService:
    return EntitlementService(JsonEntitlementStore(tmp_path / "subscriptions.json"))


class _RowLevelOnlyEntitlementStore:
    def __init__(self) -> None:
        self._entitlements: dict[int, Entitlement] = {}
        self.load_chat_calls: list[int] = []
        self.transact_chat_calls: list[int] = []

    def load_chat_entitlement(self, chat_id: int) -> Entitlement | None:
        self.load_chat_calls.append(int(chat_id))
        entitlement = self._entitlements.get(int(chat_id))
        if entitlement is None:
            return None
        return Entitlement.from_dict(entitlement.to_dict())

    @contextmanager
    def transact_chat_entitlement(self, chat_id: int):
        chat_id = int(chat_id)
        self.transact_chat_calls.append(chat_id)
        current = self._entitlements.get(chat_id)
        entitlement = Entitlement.from_dict(current.to_dict()) if current is not None else Entitlement()
        yield entitlement
        self._entitlements[chat_id] = Entitlement.from_dict(entitlement.to_dict())

    def load_all(self):
        raise AssertionError("hot entitlement path must not load all entitlements")

    def save_all(self, entitlements):
        raise AssertionError("hot entitlement path must not replace all entitlements")

    @contextmanager
    def transact(self):
        raise AssertionError("hot entitlement path must not transact over all entitlements")
