from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import InitVar, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


PAYMENT_RECOVERY_SCHEMA_VERSION = 1

ALLOWED_SERIALIZED_FIELDS = frozenset(
    {
        "schema_version",
        "record_id",
        "provider",
        "chat_id",
        "user_id",
        "invoice_payload",
        "telegram_payment_charge_id",
        "provider_payment_charge_id",
        "currency",
        "total_amount",
        "subscription_expiration_date",
        "created_at",
    },
)

_REQUIRED_SERIALIZED_FIELDS = (
    "schema_version",
    "record_id",
    "provider",
    "chat_id",
    "user_id",
    "invoice_payload",
    "telegram_payment_charge_id",
    "provider_payment_charge_id",
    "currency",
    "total_amount",
    "created_at",
)
_MAX_SAFE_TEXT_LENGTH = 512
_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_CURRENCY_RE = re.compile(r"^[A-Z0-9]{3,12}$")
_SPOOL_READY_PROBE_BYTES = b"diet-bot-payment-recovery-spool-startup-probe\n"


class PaymentRecoveryRecordError(ValueError):
    """Raised when a payment recovery record fails validation."""


class PaymentRecoverySpoolUnavailable(RuntimeError):
    """Raised when the recovery spool cannot safely accept startup writes."""


@dataclass(frozen=True)
class PaymentRecoveryRecord:
    provider: str
    chat_id: int
    user_id: int
    invoice_payload: str
    telegram_payment_charge_id: str
    currency: str
    total_amount: int
    created_at: datetime | str
    provider_payment_charge_id: str | None = None
    subscription_expiration_date: int | None = None
    record_id: str | None = None
    schema_version: int = PAYMENT_RECOVERY_SCHEMA_VERSION
    extra: InitVar[Mapping[str, object] | None] = None

    def __post_init__(self, extra: Mapping[str, object] | None) -> None:
        del extra
        schema_version = _normalize_schema_version(self.schema_version)
        provider = _normalize_provider(self.provider)
        chat_id = _normalize_positive_int(self.chat_id, "chat_id")
        user_id = _normalize_positive_int(self.user_id, "user_id")
        invoice_payload = _required_text(self.invoice_payload, "invoice_payload")
        telegram_payment_charge_id = _required_text(
            self.telegram_payment_charge_id,
            "telegram_payment_charge_id",
        )
        provider_payment_charge_id = _optional_text(
            self.provider_payment_charge_id,
            "provider_payment_charge_id",
        )
        currency = _normalize_currency(self.currency)
        total_amount = _normalize_positive_int(self.total_amount, "total_amount")
        subscription_expiration_date = _normalize_optional_positive_int(
            self.subscription_expiration_date,
            "subscription_expiration_date",
        )
        created_at = _normalize_timestamp(self.created_at, "created_at")
        expected_record_id = _build_record_id(
            provider=provider,
            telegram_payment_charge_id=telegram_payment_charge_id,
            provider_payment_charge_id=provider_payment_charge_id,
            invoice_payload=invoice_payload,
        )
        if self.record_id is None:
            record_id = expected_record_id
        else:
            record_id = _required_text(self.record_id, "record_id")
            if record_id != expected_record_id:
                raise PaymentRecoveryRecordError("record_id does not match payment idempotency fields")

        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "chat_id", chat_id)
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "invoice_payload", invoice_payload)
        object.__setattr__(self, "telegram_payment_charge_id", telegram_payment_charge_id)
        object.__setattr__(self, "provider_payment_charge_id", provider_payment_charge_id)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "total_amount", total_amount)
        object.__setattr__(self, "subscription_expiration_date", subscription_expiration_date)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "record_id", record_id)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PaymentRecoveryRecord:
        if not isinstance(data, Mapping):
            raise PaymentRecoveryRecordError("record must be a JSON object")
        missing = [field for field in _REQUIRED_SERIALIZED_FIELDS if field not in data]
        if missing:
            raise PaymentRecoveryRecordError("record is missing required fields")
        return cls(
            schema_version=data["schema_version"],
            record_id=data["record_id"],
            provider=data["provider"],
            chat_id=data["chat_id"],
            user_id=data["user_id"],
            invoice_payload=data["invoice_payload"],
            telegram_payment_charge_id=data["telegram_payment_charge_id"],
            provider_payment_charge_id=data["provider_payment_charge_id"],
            currency=data["currency"],
            total_amount=data["total_amount"],
            subscription_expiration_date=data.get("subscription_expiration_date"),
            created_at=data["created_at"],
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "schema_version": self.schema_version,
            "record_id": self.record_id or "",
            "provider": self.provider,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "invoice_payload": self.invoice_payload,
            "telegram_payment_charge_id": self.telegram_payment_charge_id,
            "provider_payment_charge_id": self.provider_payment_charge_id,
            "currency": self.currency,
            "total_amount": self.total_amount,
            "created_at": self.created_at,
        }
        if self.subscription_expiration_date is not None:
            data["subscription_expiration_date"] = self.subscription_expiration_date
        return data

    def to_json_line(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"


@dataclass(frozen=True)
class PaymentRecoveryMalformedLine:
    line_number: int
    reason: str


@dataclass(frozen=True)
class PaymentRecoveryReadResult:
    records: tuple[PaymentRecoveryRecord, ...]
    malformed_lines: tuple[PaymentRecoveryMalformedLine, ...] = ()
    duplicates_skipped: int = 0


@dataclass(frozen=True)
class PaymentRecoverySpoolSummary:
    path: Path
    exists: bool
    bytes: int
    record_count: int
    malformed_line_count: int
    duplicate_record_count: int
    oldest_created_at: str | None
    newest_created_at: str | None
    oldest_age_seconds: int | None
    newest_age_seconds: int | None
    status: str
    reasons: tuple[str, ...]
    warn_after_seconds: int | None = None
    fail_after_seconds: int | None = None
    max_records: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "path": str(self.path),
            "exists": self.exists,
            "bytes": self.bytes,
            "record_count": self.record_count,
            "malformed_line_count": self.malformed_line_count,
            "duplicate_record_count": self.duplicate_record_count,
            "oldest_created_at": self.oldest_created_at,
            "newest_created_at": self.newest_created_at,
            "oldest_age_seconds": self.oldest_age_seconds,
            "newest_age_seconds": self.newest_age_seconds,
            "status": self.status,
            "reasons": list(self.reasons),
        }
        if self.warn_after_seconds is not None:
            payload["warn_after_seconds"] = self.warn_after_seconds
        if self.fail_after_seconds is not None:
            payload["fail_after_seconds"] = self.fail_after_seconds
        if self.max_records is not None:
            payload["max_records"] = self.max_records
        return payload


def append_payment_recovery_record(path: str | Path, record: PaymentRecoveryRecord) -> None:
    if not isinstance(record, PaymentRecoveryRecord):
        raise TypeError("record must be a PaymentRecoveryRecord")

    spool_path = Path(path)
    spool_path.parent.mkdir(parents=True, exist_ok=True)
    line = record.to_json_line()

    fd, created_spool = _open_spool_for_append(spool_path)
    try:
        _restrict_file_permissions(spool_path)
        with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as spool:
            fd = None
            spool.write(line)
            spool.flush()
            os.fsync(spool.fileno())
    finally:
        if fd is not None:
            os.close(fd)
    if created_spool:
        _fsync_directory_if_supported(spool_path.parent)


def read_payment_recovery_records(path: str | Path, *, dedupe: bool = True) -> PaymentRecoveryReadResult:
    spool_path = Path(path)
    if not spool_path.exists():
        return PaymentRecoveryReadResult(records=())

    records: list[PaymentRecoveryRecord] = []
    malformed_lines: list[PaymentRecoveryMalformedLine] = []
    seen_record_ids: set[str] = set()
    duplicates_skipped = 0
    with spool_path.open("r", encoding="utf-8") as spool:
        for line_number, line in enumerate(spool, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                record = PaymentRecoveryRecord.from_dict(payload)
            except (json.JSONDecodeError, PaymentRecoveryRecordError, TypeError, ValueError) as exc:
                malformed_lines.append(PaymentRecoveryMalformedLine(line_number, _safe_malformed_reason(exc)))
                continue
            if dedupe and record.record_id in seen_record_ids:
                duplicates_skipped += 1
                continue
            seen_record_ids.add(record.record_id or "")
            records.append(record)
    return PaymentRecoveryReadResult(
        records=tuple(records),
        malformed_lines=tuple(malformed_lines),
        duplicates_skipped=duplicates_skipped,
    )


def summarize_payment_recovery_spool(
    path: str | Path,
    *,
    now: datetime | None = None,
    warn_after: timedelta | None = None,
    fail_after: timedelta | None = None,
    max_records: int | None = None,
) -> PaymentRecoverySpoolSummary:
    spool_path = Path(path)
    current_time = _normalize_summary_now(now)
    if not spool_path.exists():
        return PaymentRecoverySpoolSummary(
            path=spool_path,
            exists=False,
            bytes=0,
            record_count=0,
            malformed_line_count=0,
            duplicate_record_count=0,
            oldest_created_at=None,
            newest_created_at=None,
            oldest_age_seconds=None,
            newest_age_seconds=None,
            status="ok",
            reasons=("spool_missing",),
            warn_after_seconds=_timedelta_seconds(warn_after),
            fail_after_seconds=_timedelta_seconds(fail_after),
            max_records=max_records,
        )

    all_records = read_payment_recovery_records(spool_path, dedupe=False)
    deduped_records = read_payment_recovery_records(spool_path, dedupe=True)
    created_times = tuple(_summary_timestamp(record.created_at) for record in all_records.records)
    oldest = min(created_times) if created_times else None
    newest = max(created_times) if created_times else None
    oldest_age = _age_seconds(current_time, oldest)
    newest_age = _age_seconds(current_time, newest)
    record_count = len(all_records.records)
    duplicate_count = max(0, record_count - len(deduped_records.records))
    malformed_count = len(all_records.malformed_lines)

    reasons: list[str] = []
    status = "ok"
    if malformed_count:
        status = "fail"
        reasons.append("malformed_spool_records")
    if max_records is not None and record_count > max_records:
        status = "fail"
        reasons.append("record_count_exceeds_max")
    fail_after_seconds = _timedelta_seconds(fail_after)
    warn_after_seconds = _timedelta_seconds(warn_after)
    if oldest_age is not None and fail_after_seconds is not None and oldest_age > fail_after_seconds:
        status = "fail"
        reasons.append("oldest_record_exceeds_fail_threshold")
    elif oldest_age is not None and warn_after_seconds is not None and oldest_age > warn_after_seconds:
        if status != "fail":
            status = "warn"
        reasons.append("oldest_record_exceeds_warn_threshold")
    if record_count and not reasons:
        reasons.append("spool_non_empty")
    if not record_count and not reasons:
        reasons.append("spool_empty")

    return PaymentRecoverySpoolSummary(
        path=spool_path,
        exists=True,
        bytes=spool_path.stat().st_size,
        record_count=record_count,
        malformed_line_count=malformed_count,
        duplicate_record_count=duplicate_count,
        oldest_created_at=oldest.isoformat(timespec="seconds") if oldest is not None else None,
        newest_created_at=newest.isoformat(timespec="seconds") if newest is not None else None,
        oldest_age_seconds=oldest_age,
        newest_age_seconds=newest_age,
        status=status,
        reasons=tuple(reasons),
        warn_after_seconds=warn_after_seconds,
        fail_after_seconds=fail_after_seconds,
        max_records=max_records,
    )


def validate_payment_recovery_spool_ready(path: str | Path) -> None:
    spool_path = Path(path)
    if not spool_path.is_absolute():
        raise PaymentRecoverySpoolUnavailable("payment recovery spool path must be absolute")

    parent = spool_path.parent
    if not parent.exists():
        raise PaymentRecoverySpoolUnavailable("payment recovery spool parent directory does not exist")
    if not parent.is_dir():
        raise PaymentRecoverySpoolUnavailable("payment recovery spool parent path is not a directory")
    if spool_path.is_dir():
        raise PaymentRecoverySpoolUnavailable("payment recovery spool target path is a directory")

    if spool_path.exists():
        _validate_existing_spool_ready(spool_path)
        _probe_spool_directory(parent, spool_path.name)
    else:
        _probe_spool_directory(parent, spool_path.name)
        _create_empty_spool_file_durably(spool_path)


def _validate_existing_spool_ready(path: Path) -> None:
    flags = os.O_APPEND | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    fd: int | None = None
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as spool:
            fd = None
            spool.flush()
            os.fsync(spool.fileno())
    except OSError as exc:
        raise PaymentRecoverySpoolUnavailable("existing spool is not append/fsync ready") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _open_spool_for_append(path: Path) -> tuple[int, bool]:
    flags = os.O_APPEND | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    create_flags = flags | os.O_CREAT | os.O_EXCL
    try:
        return os.open(path, create_flags, stat.S_IRUSR | stat.S_IWUSR), True
    except FileExistsError:
        return os.open(path, flags), False


def _create_empty_spool_file_durably(path: Path) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    fd: int | None = None
    created_spool = False
    failure: OSError | None = None
    try:
        fd = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
        created_spool = True
        _restrict_file_permissions(path)
        os.fsync(fd)
    except FileExistsError:
        _validate_existing_spool_ready(path)
    except OSError as exc:
        failure = exc
    finally:
        if fd is not None:
            os.close(fd)

    if failure is not None:
        if created_spool:
            _remove_created_empty_spool(path)
        raise PaymentRecoverySpoolUnavailable("payment recovery spool file creation failed") from failure

    if not created_spool:
        return

    try:
        _fsync_directory_if_supported(path.parent)
    except OSError as exc:
        _remove_created_empty_spool(path)
        raise PaymentRecoverySpoolUnavailable("payment recovery spool parent directory is not fsync ready") from exc


def _remove_created_empty_spool(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _fsync_directory_if_supported(path: Path) -> bool:
    """Fsync a directory when the platform exposes a safe directory handle.

    Windows does not provide a reliable directory fsync path through Python's
    os.open/os.fsync APIs, so callers get best-available file fsync behavior
    there and this helper returns False.
    """
    if os.name == "nt":
        return False

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY

    fd: int | None = None
    try:
        fd = os.open(path, flags)
        os.fsync(fd)
        return True
    finally:
        if fd is not None:
            os.close(fd)


def _probe_spool_directory(parent: Path, target_name: str) -> None:
    fd: int | None = None
    probe_path: Path | None = None
    failure: OSError | None = None
    try:
        fd, raw_probe_path = tempfile.mkstemp(
            prefix=f".{_safe_probe_filename(target_name)}.startup-",
            suffix=".tmp",
            dir=parent,
        )
        probe_path = Path(raw_probe_path)
        with os.fdopen(fd, "wb") as probe:
            fd = None
            probe.write(_SPOOL_READY_PROBE_BYTES)
            probe.flush()
            os.fsync(probe.fileno())
    except OSError as exc:
        failure = exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError as exc:
                if failure is None:
                    failure = exc
        if probe_path is not None:
            try:
                probe_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                if failure is None:
                    failure = exc

    if failure is not None:
        raise PaymentRecoverySpoolUnavailable("payment recovery spool directory probe failed") from failure


def _safe_probe_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return safe or "payment-recovery-spool"


def _build_record_id(
    *,
    provider: str,
    telegram_payment_charge_id: str,
    provider_payment_charge_id: str | None,
    invoice_payload: str,
) -> str:
    idempotency_fields = [
        PAYMENT_RECOVERY_SCHEMA_VERSION,
        provider,
        telegram_payment_charge_id,
        provider_payment_charge_id or "",
        invoice_payload,
    ]
    digest = hashlib.sha256(
        json.dumps(idempotency_fields, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
    ).hexdigest()
    return f"payment_recovery_v1_{digest[:32]}"


def _normalize_schema_version(value: object) -> int:
    version = _normalize_positive_int(value, "schema_version")
    if version != PAYMENT_RECOVERY_SCHEMA_VERSION:
        raise PaymentRecoveryRecordError("unsupported payment recovery schema version")
    return version


def _normalize_provider(value: object) -> str:
    provider = _required_text(value, "provider").lower()
    if not _PROVIDER_RE.fullmatch(provider):
        raise PaymentRecoveryRecordError("provider is not a safe identifier")
    return provider


def _normalize_currency(value: object) -> str:
    currency = _required_text(value, "currency").upper()
    if not _CURRENCY_RE.fullmatch(currency):
        raise PaymentRecoveryRecordError("currency is not a safe identifier")
    return currency


def _normalize_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise PaymentRecoveryRecordError(f"{field_name} must be an integer")
    try:
        integer = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise PaymentRecoveryRecordError(f"{field_name} must be an integer") from exc
    if integer <= 0:
        raise PaymentRecoveryRecordError(f"{field_name} must be positive")
    return integer


def _normalize_optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _normalize_positive_int(value, field_name)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise PaymentRecoveryRecordError(f"{field_name} must be text")
    text = value.strip()
    if not text:
        raise PaymentRecoveryRecordError(f"{field_name} is required")
    if len(text) > _MAX_SAFE_TEXT_LENGTH:
        raise PaymentRecoveryRecordError(f"{field_name} is too long")
    if any(ord(char) < 32 for char in text):
        raise PaymentRecoveryRecordError(f"{field_name} contains control characters")
    return text


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PaymentRecoveryRecordError(f"{field_name} must be text")
    text = value.strip()
    if not text:
        return None
    if len(text) > _MAX_SAFE_TEXT_LENGTH:
        raise PaymentRecoveryRecordError(f"{field_name} is too long")
    if any(ord(char) < 32 for char in text):
        raise PaymentRecoveryRecordError(f"{field_name} contains control characters")
    return text


def _normalize_timestamp(value: object, field_name: str) -> str:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise PaymentRecoveryRecordError(f"{field_name} is required")
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            timestamp = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise PaymentRecoveryRecordError(f"{field_name} must be an ISO timestamp") from exc
    else:
        raise PaymentRecoveryRecordError(f"{field_name} must be an ISO timestamp")

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat(timespec="seconds")


def _normalize_summary_now(value: datetime | None) -> datetime:
    timestamp = datetime.now(UTC) if value is None else value
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _summary_timestamp(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    timestamp = datetime.fromisoformat(raw)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _age_seconds(now: datetime, timestamp: datetime | None) -> int | None:
    if timestamp is None:
        return None
    return max(0, int((now - timestamp).total_seconds()))


def _timedelta_seconds(value: timedelta | None) -> int | None:
    if value is None:
        return None
    return max(0, int(value.total_seconds()))


def _restrict_file_permissions(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _safe_malformed_reason(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "invalid JSON"
    if isinstance(exc, PaymentRecoveryRecordError):
        return str(exc)
    return "invalid payment recovery record"
