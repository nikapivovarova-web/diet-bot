from __future__ import annotations

from diet_bot.ops.manual_review_text import redact_manual_review_text


def test_redacts_dsn_credentials_and_preserves_host_context() -> None:
    output = redact_manual_review_text("checked postgresql://ops:super-secret@example.invalid/prod")

    assert "ops" not in output
    assert "super-secret" not in output
    assert output == "checked postgresql://<redacted:credentials>@example.invalid/prod"


def test_redacts_secret_assignments_and_preserves_surrounding_note() -> None:
    output = redact_manual_review_text(
        "Ticket MR-44 checked password=super-secret token=abc123 api_key='key-456' secret: top-secret"
    )

    assert "Ticket MR-44 checked" in output
    assert "password=<redacted:secret>" in output
    assert "token=<redacted:secret>" in output
    assert "api_key=<redacted:secret>" in output
    assert "secret: <redacted:secret>" in output
    assert "super-secret" not in output
    assert "abc123" not in output
    assert "key-456" not in output
    assert "top-secret" not in output


def test_redacts_double_quoted_json_style_secret_assignments() -> None:
    output = redact_manual_review_text(
        '{"password":"cleartext","api_key":"key-456","token":"abc123","note":"ordinary quoted text"}'
    )

    assert '"password":"<redacted:secret>"' in output
    assert '"api_key":"<redacted:secret>"' in output
    assert '"token":"<redacted:secret>"' in output
    assert '"note":"ordinary quoted text"' in output
    assert "cleartext" not in output
    assert "key-456" not in output
    assert "abc123" not in output


def test_redacts_single_quoted_dict_style_secret_assignments() -> None:
    output = redact_manual_review_text(
        "{'password':'cleartext','api_key':'key-456','token':'abc123','note':'ordinary quoted text'}"
    )

    assert "'password':'<redacted:secret>'" in output
    assert "'api_key':'<redacted:secret>'" in output
    assert "'token':'<redacted:secret>'" in output
    assert "'note':'ordinary quoted text'" in output
    assert "cleartext" not in output
    assert "key-456" not in output
    assert "abc123" not in output


def test_redacts_quoted_database_url_and_dsn_assignments() -> None:
    output = redact_manual_review_text(
        '{"database_url":"postgresql://ops:secret@example.invalid/prod",'
        '"dsn":"postgresql://ops:secret@example.invalid/report"}'
    )

    assert '"database_url":"<redacted:secret>"' in output
    assert '"dsn":"<redacted:secret>"' in output
    assert "postgresql://" not in output
    assert "ops:secret" not in output


def test_preserves_ordinary_quoted_note_text() -> None:
    output = redact_manual_review_text('{"note":"password rotation discussed without values"}')

    assert output == '{"note":"password rotation discussed without values"}'


def test_redacts_long_numeric_ids_and_preserves_ordinary_note_text() -> None:
    output = redact_manual_review_text("Ticket MR-44 checked chat 987654321 and provider export.")

    assert output == "Ticket MR-44 checked chat <redacted:number> and provider export."


def test_redacts_telegram_and_provider_token_shaped_strings() -> None:
    telegram_token = "123456789:AAH9qS8MZ0PsY7N8l1x2y3z4-provider_Token"
    provider_token = "pk_live_51Nx1wA9zY8xV7uT6sR5qP4oN3mL2kJ1h"

    output = redact_manual_review_text(f"checked tokens {telegram_token} and {provider_token}")

    assert telegram_token not in output
    assert provider_token not in output
    assert output == "checked tokens <redacted:token> and <redacted:token>"
