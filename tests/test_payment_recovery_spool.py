from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

import diet_bot.payment_recovery_spool as payment_recovery_spool
from diet_bot.payment_recovery_spool import (
    ALLOWED_SERIALIZED_FIELDS,
    PaymentRecoveryRecord,
    PaymentRecoveryRecordError,
    PaymentRecoverySpoolUnavailable,
    append_payment_recovery_record,
    read_payment_recovery_records,
    validate_payment_recovery_spool_ready,
)


CREATED_AT = datetime(2026, 5, 25, 10, 30, tzinfo=UTC)


def make_record(**overrides: object) -> PaymentRecoveryRecord:
    values: dict[str, object] = {
        "provider": " YooKassa ",
        "chat_id": 202,
        "user_id": 101,
        "invoice_payload": "diet:order:v1:order_12345678:nonce_12345678:54f63baa9f54e967",
        "telegram_payment_charge_id": "tg-charge-1",
        "provider_payment_charge_id": "provider-charge-1",
        "currency": " rub ",
        "total_amount": 79_900,
        "subscription_expiration_date": 1_781_234_567,
        "created_at": CREATED_AT,
    }
    values.update(overrides)
    return PaymentRecoveryRecord(**values)


def test_valid_record_serializes_minimal_allowed_fields() -> None:
    record = make_record()

    serialized = record.to_dict()

    assert serialized == {
        "schema_version": 1,
        "record_id": record.record_id,
        "provider": "yookassa",
        "chat_id": 202,
        "user_id": 101,
        "invoice_payload": "diet:order:v1:order_12345678:nonce_12345678:54f63baa9f54e967",
        "telegram_payment_charge_id": "tg-charge-1",
        "provider_payment_charge_id": "provider-charge-1",
        "currency": "RUB",
        "total_amount": 79_900,
        "subscription_expiration_date": 1_781_234_567,
        "created_at": "2026-05-25T10:30:00+00:00",
    }
    assert set(serialized).issubset(ALLOWED_SERIALIZED_FIELDS)


def test_record_id_is_stable_for_same_charge_and_payload() -> None:
    first = make_record(created_at=datetime(2026, 5, 25, 10, 30, tzinfo=UTC))
    second = make_record(created_at=datetime(2026, 5, 26, 10, 30, tzinfo=UTC), total_amount=60_000)
    different_charge = make_record(telegram_payment_charge_id="tg-charge-2")

    assert first.record_id == second.record_id
    assert first.record_id != different_charge.record_id


def test_optional_provider_charge_id_can_be_absent() -> None:
    record = make_record(provider_payment_charge_id="  ")

    assert record.provider_payment_charge_id is None
    assert record.to_dict()["provider_payment_charge_id"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": ""},
        {"provider": "bad provider"},
        {"chat_id": 0},
        {"user_id": 0},
        {"invoice_payload": ""},
        {"telegram_payment_charge_id": ""},
        {"currency": ""},
        {"currency": "rub usd"},
        {"total_amount": 0},
        {"subscription_expiration_date": 0},
        {"created_at": "not-a-timestamp"},
    ],
)
def test_invalid_records_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(PaymentRecoveryRecordError):
        make_record(**overrides)


def test_serialization_excludes_forbidden_raw_or_private_fields() -> None:
    record = make_record(
        extra={
            "bot_token": "bot-token-secret",
            "provider_token": "provider-token-secret",
            "database_url": "postgres://user:password@example/db",
            "raw_update": {"message": {"text": "private message"}},
            "username": "private-user",
            "first_name": "Private",
            "last_name": "Person",
            "email": "private@example.test",
            "phone_number": "+10000000000",
            "shipping_address": {"street_line1": "Private"},
            "order_info": {"email": "private@example.test"},
            "invoice_link": "https://pay.example/secret",
            "receipt": {"opaque": "provider-secret"},
            "provider_data": {"card": "secret"},
            "card": {"last4": "4242"},
            "message_text": "private message",
        },
    )

    serialized = record.to_dict()
    serialized_json = json.dumps(serialized, sort_keys=True)

    assert set(serialized).issubset(ALLOWED_SERIALIZED_FIELDS)
    assert "secret" not in serialized_json
    assert "private@example.test" not in serialized_json
    assert "private message" not in serialized_json
    assert "bot_token" not in serialized
    assert "raw_update" not in serialized
    assert "order_info" not in serialized


def test_append_creates_parent_and_writes_one_jsonl_line(tmp_path: Path) -> None:
    path = tmp_path / "spool" / "payments.jsonl"
    record = make_record()

    append_payment_recovery_record(path, record)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == record.to_dict()


def test_append_flushes_and_fsyncs_existing_spool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fake_fsync(fd: int) -> None:
        calls.append(fd)

    def fail_parent_fsync(_path: Path) -> bool:
        raise AssertionError("existing spool append must not fsync the parent directory")

    monkeypatch.setattr("diet_bot.payment_recovery_spool.os.fsync", fake_fsync)
    monkeypatch.setattr(
        "diet_bot.payment_recovery_spool._fsync_directory_if_supported",
        fail_parent_fsync,
    )
    path = tmp_path / "payments.jsonl"
    path.write_text("", encoding="utf-8")

    append_payment_recovery_record(path, make_record())

    assert calls


def test_append_to_missing_spool_fsyncs_parent_directory_after_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    def fake_fsync(_fd: int) -> None:
        events.append("file")

    def fake_fsync_directory(path: Path) -> bool:
        events.append(("parent", path))
        return True

    monkeypatch.setattr("diet_bot.payment_recovery_spool.os.fsync", fake_fsync)
    monkeypatch.setattr(
        "diet_bot.payment_recovery_spool._fsync_directory_if_supported",
        fake_fsync_directory,
    )

    append_payment_recovery_record(tmp_path / "payments.jsonl", make_record())

    assert events == ["file", ("parent", tmp_path)]


def test_read_parses_records_and_dedupes_by_record_id(tmp_path: Path) -> None:
    path = tmp_path / "payments.jsonl"
    first = make_record()
    duplicate = make_record(created_at=datetime(2026, 5, 26, 10, 30, tzinfo=UTC))
    second = make_record(telegram_payment_charge_id="tg-charge-2")
    path.write_text(
        "\n".join(
            [
                json.dumps(first.to_dict()),
                json.dumps(duplicate.to_dict()),
                json.dumps(second.to_dict()),
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    result = read_payment_recovery_records(path)

    assert result.records == (first, second)
    assert result.duplicates_skipped == 1
    assert result.malformed_lines == ()


def test_read_reports_malformed_lines_without_raw_content(tmp_path: Path) -> None:
    path = tmp_path / "payments.jsonl"
    valid = make_record()
    path.write_text(
        "not-json-with-secret-token\n"
        "{}\n"
        f"{json.dumps(valid.to_dict())}\n",
        encoding="utf-8",
    )

    result = read_payment_recovery_records(path)

    assert result.records == (valid,)
    assert len(result.malformed_lines) == 2
    assert result.malformed_lines[0].line_number == 1
    assert "secret-token" not in result.malformed_lines[0].reason


def test_append_uses_restrictive_permissions_where_supported(tmp_path: Path) -> None:
    path = tmp_path / "payments.jsonl"

    append_payment_recovery_record(path, make_record())

    if os.name == "nt":
        assert path.exists()
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def test_spool_readiness_creates_missing_target_and_fsyncs_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_fsyncs: list[Path] = []

    def fake_fsync_directory(path: Path) -> bool:
        parent_fsyncs.append(path)
        return True

    monkeypatch.setattr(
        "diet_bot.payment_recovery_spool._fsync_directory_if_supported",
        fake_fsync_directory,
    )
    path = tmp_path / "payments.jsonl"

    validate_payment_recovery_spool_ready(path)

    assert path.is_file()
    assert path.read_text(encoding="utf-8") == ""
    assert parent_fsyncs == [tmp_path]
    assert sorted(child.name for child in tmp_path.iterdir()) == ["payments.jsonl"]


def test_spool_readiness_preserves_existing_target_contents(tmp_path: Path) -> None:
    path = tmp_path / "payments.jsonl"
    existing = '{"existing":true}\n'
    path.write_text(existing, encoding="utf-8")

    validate_payment_recovery_spool_ready(path)

    assert path.read_text(encoding="utf-8") == existing


def test_spool_readiness_rejects_relative_path() -> None:
    with pytest.raises(PaymentRecoverySpoolUnavailable, match="absolute"):
        validate_payment_recovery_spool_ready(Path("payments.jsonl"))


def test_spool_readiness_rejects_missing_parent(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "payments.jsonl"

    with pytest.raises(PaymentRecoverySpoolUnavailable, match="parent directory does not exist"):
        validate_payment_recovery_spool_ready(path)

    assert not path.parent.exists()


def test_spool_readiness_rejects_parent_that_is_file(tmp_path: Path) -> None:
    parent = tmp_path / "not-a-directory"
    parent.write_text("not a directory", encoding="utf-8")

    with pytest.raises(PaymentRecoverySpoolUnavailable, match="parent path is not a directory"):
        validate_payment_recovery_spool_ready(parent / "payments.jsonl")


def test_spool_readiness_rejects_target_directory(tmp_path: Path) -> None:
    path = tmp_path / "payments.jsonl"
    path.mkdir()

    with pytest.raises(PaymentRecoverySpoolUnavailable, match="target path is a directory"):
        validate_payment_recovery_spool_ready(path)


def test_spool_readiness_fails_when_existing_target_cannot_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "payments.jsonl"
    path.write_text("", encoding="utf-8")

    def fail_fsync(_fd: int) -> None:
        raise OSError("fsync blocked")

    monkeypatch.setattr("diet_bot.payment_recovery_spool.os.fsync", fail_fsync)

    with pytest.raises(PaymentRecoverySpoolUnavailable, match="existing spool is not append/fsync ready"):
        validate_payment_recovery_spool_ready(path)


def test_spool_readiness_fails_when_temp_probe_cannot_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "payments.jsonl"

    def fail_fsync(_fd: int) -> None:
        raise OSError("fsync blocked")

    monkeypatch.setattr("diet_bot.payment_recovery_spool.os.fsync", fail_fsync)

    with pytest.raises(PaymentRecoverySpoolUnavailable, match="directory probe failed"):
        validate_payment_recovery_spool_ready(path)

    assert not any(tmp_path.iterdir())


def test_spool_readiness_fails_when_created_target_parent_cannot_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "payments.jsonl"

    def fail_fsync_directory(_path: Path) -> bool:
        raise OSError("parent fsync blocked")

    monkeypatch.setattr(
        "diet_bot.payment_recovery_spool._fsync_directory_if_supported",
        fail_fsync_directory,
    )

    with pytest.raises(PaymentRecoverySpoolUnavailable, match="parent directory is not fsync ready"):
        validate_payment_recovery_spool_ready(path)

    assert not path.exists()


def test_spool_readiness_temp_probe_writes_only_non_sensitive_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[bytes] = []
    flushes: list[str] = []
    real_fdopen = os.fdopen

    class TrackingFile:
        def __init__(self, wrapped) -> None:
            self._wrapped = wrapped

        def __enter__(self):
            self._wrapped.__enter__()
            return self

        def __exit__(self, exc_type, exc, traceback):
            return self._wrapped.__exit__(exc_type, exc, traceback)

        def write(self, data: bytes) -> int:
            written.append(data)
            return self._wrapped.write(data)

        def flush(self) -> None:
            flushes.append("flush")
            self._wrapped.flush()

        def fileno(self) -> int:
            return self._wrapped.fileno()

    def tracking_fdopen(*args, **kwargs):
        return TrackingFile(real_fdopen(*args, **kwargs))

    monkeypatch.setattr("diet_bot.payment_recovery_spool.os.fdopen", tracking_fdopen)

    path = tmp_path / "payments.jsonl"

    validate_payment_recovery_spool_ready(path)

    assert written == [b"diet-bot-payment-recovery-spool-startup-probe\n"]
    assert flushes == ["flush"]
    assert b"secret" not in b"".join(written).lower()
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == ""


def test_directory_fsync_is_explicit_best_effort_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_open(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("Windows directory fsync fallback should not open the directory")

    monkeypatch.setattr(payment_recovery_spool.os, "name", "nt")
    monkeypatch.setattr(payment_recovery_spool.os, "open", fail_open)

    assert payment_recovery_spool._fsync_directory_if_supported(tmp_path) is False
