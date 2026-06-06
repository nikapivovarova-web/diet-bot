from scripts.dev.recipe_importer.classifier import classify_recipe
from scripts.dev.recipe_importer.loader import DuplicateRisk, NormalizedRecipe
from scripts.dev.recipe_importer.photos import PhotoRecord


def test_classifier_fail_closed_when_photo_ready_lacks_structured_recipe_data() -> None:
    recipe = NormalizedRecipe(
        candidate_id="c001",
        title_ru="Photo ready only",
        meal_type="main",
        duplicate_risk="low",
        structured_ingredients="",
        servings="",
        nutrition="",
        raw={},
    )
    photo = PhotoRecord(candidate_id="c001", found=True, status="found")

    result = classify_recipe(recipe, photo, duplicate_risk=None)

    assert result.classification == "needs_review"
    assert "missing_structured_ingredients" in result.blockers
    assert "missing_servings" in result.blockers
    assert "missing_nutrition" in result.blockers


def test_classifier_blocks_missing_photo_even_with_structured_data() -> None:
    recipe = NormalizedRecipe(
        candidate_id="c002",
        title_ru="Structured recipe",
        meal_type="main",
        duplicate_risk="low",
        structured_ingredients='[{"name": "rice", "amount": 100, "unit": "g"}]',
        servings="2",
        nutrition='{"kcal": 300, "protein_g": 10, "fat_g": 5, "carbs_g": 40}',
        raw={},
    )
    photo = PhotoRecord(candidate_id="c002", found=False, status="missing")

    result = classify_recipe(recipe, photo, duplicate_risk=None)

    assert result.classification == "blocked"
    assert result.blockers == ["missing_photo"]


def test_classifier_keeps_duplicate_risk_out_of_import_ready() -> None:
    recipe = NormalizedRecipe(
        candidate_id="c003",
        title_ru="Structured duplicate",
        meal_type="main",
        duplicate_risk="medium",
        structured_ingredients='[{"name": "rice", "amount": 100, "unit": "g"}]',
        servings="2",
        nutrition='{"kcal": 300, "protein_g": 10, "fat_g": 5, "carbs_g": 40}',
        raw={},
    )
    photo = PhotoRecord(candidate_id="c003", found=True, status="found")
    duplicate = DuplicateRisk(
        candidate_id="c003",
        duplicate_risk="medium",
        duplicate_reason="rice family",
        possible_duplicate_candidate_ids="c090",
    )

    result = classify_recipe(recipe, photo, duplicate_risk=duplicate)

    assert result.classification == "needs_review"
    assert "duplicate_risk_medium" in result.review_reasons
