from __future__ import annotations

import re

from diet_bot.log_redaction import redact_log_identifier, redact_log_kv


def test_redact_log_identifier_is_deterministic_for_same_value() -> None:
    first = redact_log_identifier("chat", 202)
    second = redact_log_identifier("chat", "202")

    assert first == second
    assert re.fullmatch(r"<redacted:[a-f0-9]{12}>", first)


def test_redact_log_identifier_separates_different_values() -> None:
    first = redact_log_identifier("chat", 202)
    second = redact_log_identifier("chat", 303)

    assert first != second


def test_redact_log_identifier_excludes_raw_value() -> None:
    raw = "tg-charge-sensitive-123"

    redacted = redact_log_identifier("telegram_payment_charge", raw)

    assert raw not in redacted
    assert redacted.startswith("<redacted:")


def test_redact_log_identifier_handles_missing_values_safely() -> None:
    assert redact_log_identifier("chat", None) == "<redacted:missing>"
    assert redact_log_identifier("chat", "   ") == "<redacted:missing>"


def test_redact_log_kv_labels_the_redacted_identifier() -> None:
    rendered = redact_log_kv("chat", 202)

    assert rendered.startswith("chat=<redacted:")
    assert "202" not in rendered
