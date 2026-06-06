from pathlib import Path

from scripts.dev.recipe_importer.photos import build_photo_manifest


def test_build_photo_manifest_finds_candidate_photos_recursively(tmp_path: Path) -> None:
    photos_dir = tmp_path / "photo-work"
    batch_dir = photos_dir / "batch_01"
    batch_dir.mkdir(parents=True)
    photo_path = batch_dir / "c001.png"
    photo_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    manifest = build_photo_manifest(["c001", "c002"], photos_dir)

    assert manifest["c001"].found is True
    assert manifest["c001"].relative_path == Path("batch_01") / "c001.png"
    assert manifest["c001"].extension == ".png"
    assert manifest["c002"].found is False
    assert manifest["c002"].status == "missing"
