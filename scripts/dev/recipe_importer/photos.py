from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class PhotoRecord:
    candidate_id: str
    found: bool
    status: str
    relative_path: Path | None = None
    extension: str = ""
    size_bytes: int = 0


def build_photo_manifest(candidate_ids: list[str], photos_dir: Path) -> dict[str, PhotoRecord]:
    photos_dir = Path(photos_dir)
    indexed = _index_photos(photos_dir)
    manifest: dict[str, PhotoRecord] = {}

    for candidate_id in candidate_ids:
        photo_path = indexed.get(candidate_id.lower())
        if photo_path is None:
            manifest[candidate_id] = PhotoRecord(
                candidate_id=candidate_id,
                found=False,
                status="missing",
            )
            continue

        manifest[candidate_id] = PhotoRecord(
            candidate_id=candidate_id,
            found=True,
            status="found",
            relative_path=photo_path.relative_to(photos_dir),
            extension=photo_path.suffix.lower(),
            size_bytes=photo_path.stat().st_size,
        )
    return manifest


def _index_photos(photos_dir: Path) -> dict[str, Path]:
    if not photos_dir.exists():
        return {}

    indexed: dict[str, Path] = {}
    for path in sorted(photos_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in PHOTO_EXTENSIONS:
            continue
        indexed.setdefault(path.stem.lower(), path)
    return indexed
