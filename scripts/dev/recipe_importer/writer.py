from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from scripts.dev.recipe_importer.classifier import ClassificationResult
from scripts.dev.recipe_importer.loader import LoadedInput, NormalizedRecipe
from scripts.dev.recipe_importer.photos import PhotoRecord


def write_audit_outputs(
    out_dir: Path,
    loaded: LoadedInput,
    photos: dict[str, PhotoRecord],
    classifications: list[ClassificationResult],
    *,
    input_dir: Path,
    photos_dir: Path,
    dry_run: bool,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_normalized(out_dir / "normalized_recipes.csv", loaded.recipes)
    _write_photo_manifest(out_dir / "photo_manifest.csv", photos)
    _write_classifications(out_dir / "classification.csv", classifications)
    _write_review_table(out_dir / "review_table.csv", classifications)
    _write_report(
        out_dir / "audit_report.md",
        loaded=loaded,
        photos=photos,
        classifications=classifications,
        input_dir=input_dir,
        photos_dir=photos_dir,
        dry_run=dry_run,
    )


def _write_normalized(path: Path, recipes: list[NormalizedRecipe]) -> None:
    fields = [
        "candidate_id",
        "title_ru",
        "meal_type",
        "duplicate_risk",
        "has_structured_ingredients",
        "has_servings",
        "has_nutrition",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for recipe in recipes:
            writer.writerow(
                {
                    "candidate_id": recipe.candidate_id,
                    "title_ru": recipe.title_ru,
                    "meal_type": recipe.meal_type,
                    "duplicate_risk": recipe.duplicate_risk,
                    "has_structured_ingredients": bool(recipe.structured_ingredients),
                    "has_servings": bool(recipe.servings),
                    "has_nutrition": bool(recipe.nutrition),
                }
            )


def _write_photo_manifest(path: Path, photos: dict[str, PhotoRecord]) -> None:
    fields = [
        "candidate_id",
        "photo_found",
        "photo_status",
        "photo_path",
        "photo_ext",
        "photo_size_bytes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate_id in sorted(photos):
            photo = photos[candidate_id]
            writer.writerow(
                {
                    "candidate_id": candidate_id,
                    "photo_found": photo.found,
                    "photo_status": photo.status,
                    "photo_path": str(photo.relative_path or ""),
                    "photo_ext": photo.extension,
                    "photo_size_bytes": photo.size_bytes,
                }
            )


def _write_classifications(path: Path, classifications: list[ClassificationResult]) -> None:
    fields = [
        "candidate_id",
        "title_ru",
        "classification",
        "blockers",
        "review_reasons",
        "duplicate_risk",
        "photo_status",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in classifications:
            writer.writerow(_classification_row(result))


def _write_review_table(path: Path, classifications: list[ClassificationResult]) -> None:
    fields = [
        "candidate_id",
        "title_ru",
        "classification",
        "review_priority",
        "review_reasons",
        "blockers",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in classifications:
            if result.classification == "import_ready":
                continue
            writer.writerow(
                {
                    "candidate_id": result.candidate_id,
                    "title_ru": result.title_ru,
                    "classification": result.classification,
                    "review_priority": "high" if result.classification == "blocked" else "normal",
                    "review_reasons": ";".join(result.review_reasons),
                    "blockers": ";".join(result.blockers),
                }
            )


def _classification_row(result: ClassificationResult) -> dict[str, str]:
    return {
        "candidate_id": result.candidate_id,
        "title_ru": result.title_ru,
        "classification": result.classification,
        "blockers": ";".join(result.blockers),
        "review_reasons": ";".join(result.review_reasons),
        "duplicate_risk": result.duplicate_risk,
        "photo_status": result.photo_status,
    }


def _write_report(
    path: Path,
    *,
    loaded: LoadedInput,
    photos: dict[str, PhotoRecord],
    classifications: list[ClassificationResult],
    input_dir: Path,
    photos_dir: Path,
    dry_run: bool,
) -> None:
    class_counts = Counter(result.classification for result in classifications)
    photo_found = sum(1 for photo in photos.values() if photo.found)
    lines = [
        "# Recipe Importer Phase 1 Audit",
        "",
        f"input_dir: {input_dir}",
        f"photos_dir: {photos_dir}",
        f"dry_run: {str(dry_run).lower()}",
        "",
        "## Counts",
        "",
        f"- photo_ready rows: {loaded.source_counts.get('photo_ready', 0)}",
        f"- duplicate risk rows: {loaded.source_counts.get('duplicate_risk', 0)}",
        f"- photos found: {photo_found}",
        f"- photos missing: {len(photos) - photo_found}",
        f"- import_ready: {class_counts.get('import_ready', 0)}",
        f"- needs_review: {class_counts.get('needs_review', 0)}",
        f"- blocked: {class_counts.get('blocked', 0)}",
        "",
        "## Policy",
        "",
        "- Phase 1 is read-only and writes only audit artifacts.",
        "- Photo-ready status alone is not enough for import_ready.",
        "- Missing structured ingredients, servings, or nutrition stays needs_review or blocked.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
