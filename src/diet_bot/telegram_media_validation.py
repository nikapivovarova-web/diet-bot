from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


# Conservative local preflight limits for Bot API uploads. Fallback/retry logic
# still handles Telegram-side failures, but these checks catch our own bad inputs.
TELEGRAM_CAPTION_MAX_CHARS = 1024
TELEGRAM_MESSAGE_MAX_CHARS = 4096
TELEGRAM_MESSAGE_CHUNK_MAX_CHARS = 3900
TELEGRAM_PHOTO_MAX_BYTES = 10 * 1024 * 1024
TELEGRAM_DOCUMENT_MAX_BYTES = 50 * 1024 * 1024
TELEGRAM_PDF_MAX_BYTES = TELEGRAM_DOCUMENT_MAX_BYTES

SUPPORTED_TELEGRAM_PHOTO_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
SUPPORTED_PDF_SUFFIXES = frozenset({".pdf"})


class TelegramMediaValidationError(ValueError):
    """Raised when local Telegram media/text preflight catches an invalid payload."""


def validate_local_photo_path(
    path: str | Path,
    *,
    label: str = "photo",
    max_bytes: int = TELEGRAM_PHOTO_MAX_BYTES,
) -> Path:
    return validate_local_media_file(
        path,
        label=label,
        max_bytes=max_bytes,
        allowed_suffixes=SUPPORTED_TELEGRAM_PHOTO_SUFFIXES,
    )


def validate_local_document_path(
    path: str | Path,
    *,
    label: str = "document",
    max_bytes: int = TELEGRAM_DOCUMENT_MAX_BYTES,
    allowed_suffixes: Iterable[str] | None = None,
) -> Path:
    return validate_local_media_file(
        path,
        label=label,
        max_bytes=max_bytes,
        allowed_suffixes=allowed_suffixes,
    )


def validate_local_pdf_document_path(
    path: str | Path,
    *,
    label: str = "PDF document",
    max_bytes: int = TELEGRAM_PDF_MAX_BYTES,
) -> Path:
    return validate_local_document_path(
        path,
        label=label,
        max_bytes=max_bytes,
        allowed_suffixes=SUPPORTED_PDF_SUFFIXES,
    )


def validate_local_media_file(
    path: str | Path,
    *,
    label: str,
    max_bytes: int,
    allowed_suffixes: Iterable[str] | None = None,
) -> Path:
    media_path = Path(path)
    safe_name = _safe_path_name(media_path)
    if not media_path.exists():
        raise TelegramMediaValidationError(f"{label} {safe_name} does not exist.")
    if not media_path.is_file():
        raise TelegramMediaValidationError(f"{label} {safe_name} is not a regular file.")

    normalized_suffixes = _normalize_suffixes(allowed_suffixes)
    if normalized_suffixes and media_path.suffix.lower() not in normalized_suffixes:
        supported = ", ".join(sorted(normalized_suffixes))
        raise TelegramMediaValidationError(
            f"{label} {safe_name} has unsupported extension {media_path.suffix.lower() or '<none>'}; "
            f"supported extensions: {supported}."
        )

    try:
        size = media_path.stat().st_size
    except OSError as exc:
        raise TelegramMediaValidationError(f"{label} {safe_name} could not be inspected.") from exc
    _validate_payload_size(size, label=label, safe_name=safe_name, max_bytes=max_bytes)
    return media_path


def validate_pdf_document_bytes(
    data: bytes,
    filename: str,
    *,
    max_bytes: int = TELEGRAM_PDF_MAX_BYTES,
) -> bytes:
    safe_name = _safe_filename(filename)
    if Path(filename).suffix.lower() not in SUPPORTED_PDF_SUFFIXES:
        raise TelegramMediaValidationError(f"weekly PDF {safe_name} has unsupported extension.")
    _validate_payload_size(len(data), label="weekly PDF", safe_name=safe_name, max_bytes=max_bytes)
    if not data.startswith(b"%PDF-"):
        raise TelegramMediaValidationError(f"weekly PDF {safe_name} is missing a PDF header.")
    return data


def validate_telegram_caption(
    caption: str,
    *,
    label: str = "caption",
    max_chars: int = TELEGRAM_CAPTION_MAX_CHARS,
) -> str:
    if len(caption) > max_chars:
        raise TelegramMediaValidationError(f"{label} is {len(caption)} chars; Telegram caption limit is {max_chars}.")
    return caption


def validate_telegram_message_text(
    text: str,
    *,
    label: str = "message text",
    max_chars: int = TELEGRAM_MESSAGE_MAX_CHARS,
) -> str:
    if len(text) > max_chars:
        raise TelegramMediaValidationError(f"{label} is {len(text)} chars; Telegram message limit is {max_chars}.")
    return text


def telegram_text_chunks(text: str, limit: int = TELEGRAM_MESSAGE_CHUNK_MAX_CHARS) -> list[str]:
    if limit <= 0:
        raise TelegramMediaValidationError("Telegram text chunk limit must be positive.")
    if limit > TELEGRAM_MESSAGE_MAX_CHARS:
        raise TelegramMediaValidationError(
            f"Telegram text chunk limit {limit} exceeds message limit {TELEGRAM_MESSAGE_MAX_CHARS}."
        )

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(validate_telegram_message_text(chunk, label="message chunk"))
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(validate_telegram_message_text(remaining, label="message chunk"))
    return chunks


def validate_local_telegram_media_assets(data_dir: str | Path | None = None) -> None:
    root = Path(data_dir) if data_dir is not None else Path(__file__).with_name("data")
    validate_local_photo_path(root / "welcome_foodbalance.png", label="welcome photo")

    recipes_path = root / "curated_recipes.json"
    if not recipes_path.is_file():
        raise TelegramMediaValidationError(f"recipe media manifest {_safe_path_name(recipes_path)} does not exist.")

    try:
        recipes = json.loads(recipes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TelegramMediaValidationError("recipe media manifest could not be read.") from exc

    if not isinstance(recipes, list):
        raise TelegramMediaValidationError("recipe media manifest must contain a list.")

    for index, row in enumerate(recipes, start=1):
        if not isinstance(row, dict):
            raise TelegramMediaValidationError(f"recipe media row {index} is not an object.")
        image_url = _string_value(row.get("image_url"))
        if not image_url or image_url.startswith(("http://", "https://")):
            continue
        label = f"recipe photo {row.get('recipe_no') or row.get('id') or index}"
        validate_local_photo_path(root / image_url, label=label)


def _validate_payload_size(size: int, *, label: str, safe_name: str, max_bytes: int) -> None:
    if size <= 0:
        raise TelegramMediaValidationError(f"{label} {safe_name} is empty.")
    if size > max_bytes:
        raise TelegramMediaValidationError(f"{label} {safe_name} is {size} bytes; exceeds limit {max_bytes} bytes.")


def _normalize_suffixes(suffixes: Iterable[str] | None) -> frozenset[str]:
    if suffixes is None:
        return frozenset()
    return frozenset(suffix.lower() for suffix in suffixes)


def _safe_path_name(path: Path) -> str:
    return repr(path.name or "<unnamed>")


def _safe_filename(filename: str) -> str:
    return repr(Path(filename).name or "<unnamed>")


def _string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""
