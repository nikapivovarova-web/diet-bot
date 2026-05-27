from __future__ import annotations

from diet_bot.log_redaction import (
    redact_identifier,
    redact_log_identifiers,
    redact_optional_identifier,
)


def test_redacted_identifier_is_deterministic_for_same_value() -> None:
    first = redact_identifier("chat", 202_123_456)
    second = redact_identifier("chat", "202123456")

    assert first == second
    assert first.startswith("<redacted:")
    assert first.endswith(">")


def test_redacted_identifier_differs_for_different_values() -> None:
    assert redact_identifier("chat", 202_123_456) != redact_identifier("chat", 202_123_457)


def test_redacted_identifier_does_not_include_raw_value() -> None:
    raw_value = "tg-charge-secret-raw"

    redacted = redact_identifier("telegram_payment_charge", raw_value)

    assert raw_value not in redacted
    assert "secret" not in redacted


def test_missing_identifiers_are_handled_safely() -> None:
    assert redact_identifier("chat", None) == "<redacted:missing>"
    assert redact_identifier("chat", "  ") == "<redacted:missing>"
    assert redact_optional_identifier("provider_payment_charge", None) is None
    assert redact_optional_identifier("provider_payment_charge", "  ") is None


def test_log_identifier_mapping_redacts_known_identifier_fields() -> None:
    fields = {
        "chat_id": 202_123_456,
        "user_id": 101_000,
        "order_id": "order_12345678",
        "telegram_payment_charge_id": "tg-charge-secret-raw",
        "provider_payment_charge_id": "provider-charge-secret-raw",
        "job_id": "7d0e1a90-37cc-4922-a6af-7f452ea92174",
        "status": "failed",
    }

    redacted = redact_log_identifiers(fields)

    assert redacted["status"] == "failed"
    assert all(str(value).startswith("<redacted:") for key, value in redacted.items() if key != "status")
    rendered = repr(redacted)
    for raw in (
        "202123456",
        "101000",
        "order_12345678",
        "tg-charge-secret-raw",
        "provider-charge-secret-raw",
        "7d0e1a90-37cc-4922-a6af-7f452ea92174",
    ):
        assert raw not in rendered
