import csv
import json
from pathlib import Path

import pytest

from scripts.dev.recipe_importer.classifier import ClassificationResult
from scripts.dev.recipe_importer.ingredients import IngredientParseResult, ParsedIngredient
from scripts.dev.recipe_importer.loader import LoadedInput, NormalizedRecipe
from scripts.dev.recipe_importer.mapping import IngredientMappingResult, IngredientMappingRow
from scripts.dev.recipe_importer.nutrition import NutritionResult
from scripts.dev.recipe_importer.photos import PhotoRecord
from scripts.dev.recipe_importer.production_rows import generate_production_rows
from scripts.dev.recipe_importer.servings import ServingsResult


def test_generate_production_rows_uses_deterministic_ids_and_recipe_keys() -> None:
    rows = _generate(recipe_no_start=711, recipe_key_prefix="import202606_")

    assert [row["recipe_no"] for row in rows.recipes] == [711, 712]
    assert [row["recipe_id"] for row in rows.recipes] == [
        "r711_alpha_bowl",
        "r712_beta_bowl",
    ]
    assert [row["recipe_key"] for row in rows.recipes] == [
        "import202606_001",
        "import202606_002",
    ]
    assert rows.recipes[0]["import_metadata"] == {
        "candidate_id": "c001",
        "source": "https://example.test/alpha",
    }


def test_generate_production_rows_sets_ingredient_line_index() -> None:
    rows = _generate(recipe_no_start=711, recipe_key_prefix="import202606_")

    alpha_ingredients = [
        row for row in rows.ingredients if row["recipe_key"] == "import202606_001"
    ]
    assert [row["line_index"] for row in alpha_ingredients] == [1, 2]
    assert alpha_ingredients[0]["recipe_no"] == 711
    assert alpha_ingredients[0]["recipe_id"] == "r711_alpha_bowl"


def test_generate_production_rows_sets_nutrition_status_ok() -> None:
    rows = _generate(recipe_no_start=711, recipe_key_prefix="import202606_")

    assert rows.nutrition[0]["calculation_status"] == "ok"
    assert rows.nutrition[0]["ingredient_count"] == 2
    assert rows.nutrition[0]["unmatched_ingredient_count"] == 0
    assert rows.nutrition[0]["calculation_notes"] == "recipe importer dry-run preview"


def test_generate_production_rows_photo_manifest_uses_target_photo_path() -> None:
    rows = _generate(recipe_no_start=711, recipe_key_prefix="import202606_")

    assert rows.photo_manifest[0]["source_photo_path"] == "batch_01/c001.jpg"
    assert rows.photo_manifest[0]["target_photo_path"] == (
        "src/diet_bot/data/recipe_photos/r711.jpg"
    )


def test_generate_production_rows_fails_if_import_ready_lacks_mapping() -> None:
    loaded, photos, classifications, ingredients, servings, mapping, nutrition = _fixtures()
    mapping["c001"] = IngredientMappingResult("c001", "blocked", "unknown", [])

    with pytest.raises(ValueError, match="import_ready candidate c001 lacks mapping"):
        generate_production_rows(
            loaded,
            photos,
            classifications,
            ingredient_results=ingredients,
            servings_results=servings,
            mapping_results=mapping,
            nutrition_results=nutrition,
            recipe_no_start=711,
            recipe_key_prefix="import202606_",
        )


def test_write_production_rows_writes_json_and_csv(tmp_path: Path) -> None:
    rows = _generate(recipe_no_start=711, recipe_key_prefix="import202606_")
    rows.write(tmp_path)

    assert {
        "curated_recipes.json",
        "curated_recipe_ingredients.json",
        "curated_recipe_nutrition.json",
        "photo_manifest.csv",
    } == {path.name for path in tmp_path.iterdir()}
    assert json.loads((tmp_path / "curated_recipes.json").read_text(encoding="utf-8"))[
        0
    ]["recipe_no"] == 711
    with (tmp_path / "photo_manifest.csv").open(encoding="utf-8", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    assert manifest[0]["target_photo_path"] == "src/diet_bot/data/recipe_photos/r711.jpg"


def _generate(*, recipe_no_start: int, recipe_key_prefix: str):
    loaded, photos, classifications, ingredients, servings, mapping, nutrition = _fixtures()
    return generate_production_rows(
        loaded,
        photos,
        classifications,
        ingredient_results=ingredients,
        servings_results=servings,
        mapping_results=mapping,
        nutrition_results=nutrition,
        recipe_no_start=recipe_no_start,
        recipe_key_prefix=recipe_key_prefix,
    )


def _fixtures():
    recipes = [
        _recipe("c001", "Alpha Bowl", "breakfast", "https://example.test/alpha"),
        _recipe("c002", "Beta Bowl", "main", ""),
        _recipe("c003", "Blocked Bowl", "main", ""),
    ]
    loaded = LoadedInput(recipes=recipes, duplicate_risks={}, source_counts={"photo_ready": 3})
    photos = {
        "c001": PhotoRecord(
            "c001",
            True,
            "found",
            relative_path=Path("batch_01/c001.jpg"),
            extension=".jpg",
            size_bytes=100,
        ),
        "c002": PhotoRecord(
            "c002",
            True,
            "found",
            relative_path=Path("batch_01/c002.png"),
            extension=".png",
            size_bytes=200,
        ),
        "c003": PhotoRecord("c003", False, "missing"),
    }
    classifications = [
        _classification("c001", "Alpha Bowl", "breakfast", "import_ready"),
        _classification("c002", "Beta Bowl", "main", "import_ready"),
        _classification("c003", "Blocked Bowl", "main", "blocked"),
    ]
    ingredients = {
        "c001": IngredientParseResult(
            "c001",
            "parsed",
            "",
            [
                ParsedIngredient("oats", 50.0, "g", '{"name": "oats"}'),
                ParsedIngredient("milk", 100.0, "g", '{"name": "milk"}'),
            ],
        ),
        "c002": IngredientParseResult(
            "c002",
            "parsed",
            "",
            [ParsedIngredient("rice", 80.0, "g", '{"name": "rice"}')],
        ),
        "c003": IngredientParseResult("c003", "blocked", "missing", []),
    }
    servings = {
        "c001": ServingsResult("valid", 1, False, "explicit", ""),
        "c002": ServingsResult("valid", 2, False, "explicit", ""),
        "c003": ServingsResult("blocked", 0, False, "", "invalid"),
    }
    mapping = {
        "c001": IngredientMappingResult(
            "c001",
            "mapped",
            "",
            [
                IngredientMappingRow("oats", "oats", "oats", 50.0, "g", "mapped", ""),
                IngredientMappingRow("milk", "milk", "milk", 100.0, "g", "mapped", ""),
            ],
        ),
        "c002": IngredientMappingResult(
            "c002",
            "mapped",
            "",
            [IngredientMappingRow("rice", "rice", "rice", 80.0, "g", "mapped", "")],
        ),
        "c003": IngredientMappingResult("c003", "blocked", "missing", []),
    }
    nutrition = {
        "c001": NutritionResult("c001", "ok", "", 101.0, 6.0, 2.0, 18.0, 3.0, 20.0),
        "c002": NutritionResult("c002", "ok", "", 95.0, 2.0, 1.0, 20.0, 1.0, 5.0),
        "c003": NutritionResult("c003", "blocked", "missing", 0, 0, 0, 0, 0, 0),
    }
    return loaded, photos, classifications, ingredients, servings, mapping, nutrition


def _recipe(candidate_id: str, title: str, meal_type: str, source: str) -> NormalizedRecipe:
    return NormalizedRecipe(
        candidate_id=candidate_id,
        title_ru=title,
        meal_type=meal_type,
        duplicate_risk="low",
        structured_ingredients="[]",
        servings="1",
        instructions=f"Cook {title}.",
        time="15 min",
        source=source,
    )


def _classification(
    candidate_id: str,
    title: str,
    meal_type: str,
    classification: str,
) -> ClassificationResult:
    return ClassificationResult(
        candidate_id=candidate_id,
        title_ru=title,
        classification=classification,
        blockers=[] if classification == "import_ready" else ["missing_photo"],
        review_reasons=[],
        duplicate_risk="low",
        photo_status="found",
        parse_status="parsed",
        servings_status="valid",
        mapping_status="mapped",
        nutrition_status="ok",
    )
