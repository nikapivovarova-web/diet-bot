from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from scripts.dev.recipe_importer.classifier import ClassificationResult
from scripts.dev.recipe_importer.ingredients import IngredientParseResult
from scripts.dev.recipe_importer.loader import LoadedInput, NormalizedRecipe
from scripts.dev.recipe_importer.mapping import IngredientMappingResult
from scripts.dev.recipe_importer.nutrition import NutritionResult
from scripts.dev.recipe_importer.photos import PhotoRecord
from scripts.dev.recipe_importer.production_rows import ProductionRows
from scripts.dev.recipe_importer.servings import ServingsResult


def write_audit_outputs(
    out_dir: Path,
    loaded: LoadedInput,
    photos: dict[str, PhotoRecord],
    classifications: list[ClassificationResult],
    *,
    ingredient_results: dict[str, IngredientParseResult],
    servings_results: dict[str, ServingsResult],
    mapping_results: dict[str, IngredientMappingResult],
    nutrition_results: dict[str, NutritionResult],
    input_dir: Path,
    photos_dir: Path,
    dry_run: bool,
    production_rows: ProductionRows | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_normalized(out_dir / "normalized_recipes.csv", loaded.recipes)
    _write_photo_manifest(out_dir / "photo_manifest.csv", photos)
    _write_structured_ingredients(out_dir / "structured_ingredients.csv", ingredient_results)
    _write_mapping_report(out_dir / "mapping_report.csv", mapping_results)
    _write_nutrition_rows(out_dir / "nutrition_rows.csv", nutrition_results)
    _write_classifications(out_dir / "classification.csv", classifications)
    _write_review_table(out_dir / "review_table.csv", classifications)
    _write_report(
        out_dir / "audit_report.md",
        loaded=loaded,
        photos=photos,
        classifications=classifications,
        ingredient_results=ingredient_results,
        servings_results=servings_results,
        mapping_results=mapping_results,
        nutrition_results=nutrition_results,
        input_dir=input_dir,
        photos_dir=photos_dir,
        dry_run=dry_run,
        production_rows=production_rows,
    )


def _write_normalized(path: Path, recipes: list[NormalizedRecipe]) -> None:
    fields = [
        "candidate_id",
        "title_ru",
        "meal_type",
        "duplicate_risk",
        "has_structured_ingredients",
        "has_raw_ingredient_text",
        "has_servings",
        "has_nutrition",
        "has_instructions",
        "time",
        "source",
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
                    "has_raw_ingredient_text": bool(recipe.raw_ingredient_text),
                    "has_servings": bool(recipe.servings),
                    "has_nutrition": bool(recipe.nutrition),
                    "has_instructions": bool(recipe.instructions),
                    "time": recipe.time,
                    "source": recipe.source,
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


def _write_structured_ingredients(
    path: Path,
    ingredient_results: dict[str, IngredientParseResult],
) -> None:
    fields = [
        "candidate_id",
        "ingredient_index",
        "name",
        "amount",
        "unit",
        "parse_status",
        "blocker_reason",
        "raw",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate_id in sorted(ingredient_results):
            result = ingredient_results[candidate_id]
            if not result.ingredients:
                writer.writerow(
                    {
                        "candidate_id": candidate_id,
                        "ingredient_index": "",
                        "name": "",
                        "amount": "",
                        "unit": "",
                        "parse_status": result.parse_status,
                        "blocker_reason": result.blocker_reason,
                        "raw": "",
                    }
                )
                continue
            for index, ingredient in enumerate(result.ingredients, start=1):
                writer.writerow(
                    {
                        "candidate_id": candidate_id,
                        "ingredient_index": index,
                        "name": ingredient.name,
                        "amount": ingredient.amount,
                        "unit": ingredient.unit,
                        "parse_status": result.parse_status,
                        "blocker_reason": result.blocker_reason,
                        "raw": ingredient.raw,
                    }
                )


def _write_mapping_report(
    path: Path,
    mapping_results: dict[str, IngredientMappingResult],
) -> None:
    fields = [
        "candidate_id",
        "ingredient_index",
        "ingredient_name",
        "normalized_alias",
        "food_id",
        "amount",
        "unit",
        "mapping_status",
        "blocker_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate_id in sorted(mapping_results):
            result = mapping_results[candidate_id]
            if not result.rows:
                writer.writerow(
                    {
                        "candidate_id": candidate_id,
                        "ingredient_index": "",
                        "ingredient_name": "",
                        "normalized_alias": "",
                        "food_id": "",
                        "amount": "",
                        "unit": "",
                        "mapping_status": result.status,
                        "blocker_reason": result.blocker_reason,
                    }
                )
                continue
            for index, row in enumerate(result.rows, start=1):
                writer.writerow(
                    {
                        "candidate_id": candidate_id,
                        "ingredient_index": index,
                        "ingredient_name": row.ingredient_name,
                        "normalized_alias": row.normalized_alias,
                        "food_id": row.food_id,
                        "amount": row.amount,
                        "unit": row.unit,
                        "mapping_status": row.mapping_status,
                        "blocker_reason": row.blocker_reason,
                    }
                )


def _write_nutrition_rows(
    path: Path,
    nutrition_results: dict[str, NutritionResult],
) -> None:
    fields = [
        "candidate_id",
        "calculation_status",
        "blocker_reason",
        "energy_kcal",
        "protein_g",
        "fat_g",
        "carbohydrate_g",
        "fiber_g",
        "sodium_mg",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate_id in sorted(nutrition_results):
            result = nutrition_results[candidate_id]
            writer.writerow(
                {
                    "candidate_id": result.candidate_id,
                    "calculation_status": result.calculation_status,
                    "blocker_reason": result.blocker_reason,
                    "energy_kcal": result.energy_kcal,
                    "protein_g": result.protein_g,
                    "fat_g": result.fat_g,
                    "carbohydrate_g": result.carbohydrate_g,
                    "fiber_g": result.fiber_g,
                    "sodium_mg": result.sodium_mg,
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
        "parse_status",
        "servings_status",
        "mapping_status",
        "nutrition_status",
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
        "parse_status": result.parse_status,
        "servings_status": result.servings_status,
        "mapping_status": result.mapping_status,
        "nutrition_status": result.nutrition_status,
    }


def _write_report(
    path: Path,
    *,
    loaded: LoadedInput,
    photos: dict[str, PhotoRecord],
    classifications: list[ClassificationResult],
    ingredient_results: dict[str, IngredientParseResult],
    servings_results: dict[str, ServingsResult],
    mapping_results: dict[str, IngredientMappingResult],
    nutrition_results: dict[str, NutritionResult],
    input_dir: Path,
    photos_dir: Path,
    dry_run: bool,
    production_rows: ProductionRows | None,
) -> None:
    class_counts = Counter(result.classification for result in classifications)
    photo_found = sum(1 for photo in photos.values() if photo.found)
    parsed = sum(1 for result in ingredient_results.values() if result.parse_status == "parsed")
    valid_servings = sum(1 for result in servings_results.values() if result.status == "valid")
    mapped = sum(1 for result in mapping_results.values() if result.status == "mapped")
    nutrition_ok = sum(
        1 for result in nutrition_results.values() if result.calculation_status == "ok"
    )
    lines = [
        "# Recipe Importer Phase 2C Audit",
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
        f"- parsed ingredients: {parsed}",
        f"- valid servings: {valid_servings}",
        f"- mapped ingredients: {mapped}",
        f"- nutrition calculated: {nutrition_ok}",
        f"- import_ready: {class_counts.get('import_ready', 0)}",
        f"- needs_review: {class_counts.get('needs_review', 0)}",
        f"- blocked: {class_counts.get('blocked', 0)}",
        f"- production curated_recipes rows: {len(production_rows.recipes) if production_rows else 0}",
        f"- production curated_recipe_ingredients rows: {len(production_rows.ingredients) if production_rows else 0}",
        f"- production curated_recipe_nutrition rows: {len(production_rows.nutrition) if production_rows else 0}",
        f"- production photo_manifest rows: {len(production_rows.photo_manifest) if production_rows else 0}",
        "",
        "## Policy",
        "",
        "- The importer audit is read-only and writes only audit artifacts.",
        "- Phase 2B adds read-only nutrition calculation from mapped ingredients.",
        "- Phase 2C writes production-shaped preview rows under the run output only.",
        "- Photo-ready status alone is not enough for import_ready.",
        "- import_ready requires parsed ingredients, valid servings, mapped ingredients, calculated nutrition with sodium, photo, and low duplicate risk.",
        "- No production data is imported by this audit.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
