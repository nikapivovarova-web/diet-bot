from __future__ import annotations

from pathlib import Path

import pytest

from diet_bot.telegram_media_validation import (
    TELEGRAM_CAPTION_MAX_CHARS,
    TELEGRAM_MESSAGE_CHUNK_MAX_CHARS,
    TelegramMediaValidationError,
    telegram_text_chunks,
    validate_local_document_path,
    validate_local_photo_path,
    validate_pdf_document_bytes,
    validate_telegram_caption,
)


def test_validate_local_photo_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TelegramMediaValidationError, match="does not exist"):
        validate_local_photo_path(tmp_path / "missing.jpg", label="meal photo")


def test_validate_local_photo_rejects_directory_path(tmp_path: Path) -> None:
    with pytest.raises(TelegramMediaValidationError, match="regular file"):
        validate_local_photo_path(tmp_path, label="meal photo")


def test_validate_local_photo_rejects_empty_file(tmp_path: Path) -> None:
    photo = tmp_path / "empty.jpg"
    photo.write_bytes(b"")

    with pytest.raises(TelegramMediaValidationError, match="empty"):
        validate_local_photo_path(photo, label="meal photo")


def test_validate_local_photo_rejects_unsupported_extension(tmp_path: Path) -> None:
    photo = tmp_path / "photo.bmp"
    photo.write_bytes(b"not-empty")

    with pytest.raises(TelegramMediaValidationError, match="unsupported"):
        validate_local_photo_path(photo, label="meal photo")


def test_validate_local_photo_rejects_oversized_file(tmp_path: Path) -> None:
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"12345")

    with pytest.raises(TelegramMediaValidationError, match="exceeds"):
        validate_local_photo_path(photo, label="meal photo", max_bytes=4)


def test_validate_local_document_rejects_oversized_pdf(tmp_path: Path) -> None:
    document = tmp_path / "week.pdf"
    document.write_bytes(b"12345")

    with pytest.raises(TelegramMediaValidationError, match="exceeds"):
        validate_local_document_path(document, label="weekly PDF", max_bytes=4, allowed_suffixes={".pdf"})


def test_validate_pdf_document_bytes_rejects_empty_oversized_and_non_pdf_payloads() -> None:
    with pytest.raises(TelegramMediaValidationError, match="empty"):
        validate_pdf_document_bytes(b"", "week.pdf")
    with pytest.raises(TelegramMediaValidationError, match="exceeds"):
        validate_pdf_document_bytes(b"%PDF-1.4\nxxxxx", "week.pdf", max_bytes=8)
    with pytest.raises(TelegramMediaValidationError, match="PDF header"):
        validate_pdf_document_bytes(b"not a pdf", "week.pdf")


def test_validate_telegram_caption_rejects_too_long_caption() -> None:
    with pytest.raises(TelegramMediaValidationError, match="caption"):
        validate_telegram_caption("x" * (TELEGRAM_CAPTION_MAX_CHARS + 1), label="meal caption")


def test_valid_media_and_text_chunks_pass(tmp_path: Path) -> None:
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"not-empty")

    assert validate_local_photo_path(photo, label="meal photo") == photo
    assert validate_pdf_document_bytes(b"%PDF-1.4\nbody", "week.pdf") == b"%PDF-1.4\nbody"
    assert validate_telegram_caption("short caption", label="meal caption") == "short caption"

    chunks = telegram_text_chunks("a" * (TELEGRAM_MESSAGE_CHUNK_MAX_CHARS + 50))
    assert len(chunks) == 2
    assert all(0 < len(chunk) <= TELEGRAM_MESSAGE_CHUNK_MAX_CHARS for chunk in chunks)
