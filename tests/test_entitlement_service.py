from datetime import UTC, datetime, timedelta
from pathlib import Path

from diet_bot.entitlement_service import EntitlementService
from diet_bot.entitlement_storage import JsonEntitlementStore


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


def _service(tmp_path: Path) -> EntitlementService:
    return EntitlementService(JsonEntitlementStore(tmp_path / "subscriptions.json"))
