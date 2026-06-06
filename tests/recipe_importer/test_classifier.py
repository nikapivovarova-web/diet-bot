from scripts.dev.recipe_importer.classifier import classify_recipe
from scripts.dev.recipe_importer.ingredients import IngredientParseResult, ParsedIngredient
from scripts.dev.recipe_importer.loader import DuplicateRisk, NormalizedRecipe
from scripts.dev.recipe_importer.mapping import IngredientMappingResult, IngredientMappingRow
from scripts.dev.recipe_importer.nutrition import NutritionResult
from scripts.dev.recipe_importer.photos import PhotoRecord
from scripts.dev.recipe_importer.servings import ServingsResult


def _recipe(**overrides: str) -> NormalizedRecipe:
    values = {
        "candidate_id": "c001",
        "title_ru": "Structured recipe",
        "meal_type": "main",
        "duplicate_risk": "low",
        "structured_ingredients": '[{"name": "water", "amount": 100, "unit": "ml"}]',
        "raw_ingredient_text": "",
        "servings": "2",
        "nutrition": "",
        "instructions": "",
        "time": "",
        "source": "",
        "raw": {},
    }
    values.update(overrides)
    return NormalizedRecipe(**values)


def _parsed(status: str = "parsed", blocker: str = "") -> IngredientParseResult:
    return IngredientParseResult(
        candidate_id="c001",
        parse_status=status,
        blocker_reason=blocker,
        ingredients=[
            ParsedIngredient(name="Water", amount=100, unit="ml", raw="Water - 100 ml")
        ]
        if status == "parsed"
        else [],
    )


def _servings(status: str = "valid", blocker: str = "") -> ServingsResult:
    return ServingsResult(
        status=status,
        servings=2 if status == "valid" else 0,
        estimated=False,
        source="explicit",
        blocker_reason=blocker,
    )


def _mapping(status: str = "mapped", blocker: str = "") -> IngredientMappingResult:
    return IngredientMappingResult(
        candidate_id="c001",
        status=status,
        blocker_reason=blocker,
        rows=[
            IngredientMappingRow(
                ingredient_name="Water",
                normalized_alias="water",
                food_id="water" if status == "mapped" else "",
                amount=100,
                unit="ml",
                mapping_status=status,
                blocker_reason=blocker,
            )
        ],
    )


def _nutrition(status: str = "ok", blocker: str = "", sodium_mg: float = 0.0) -> NutritionResult:
    return NutritionResult(
        candidate_id="c001",
        calculation_status=status,
        blocker_reason=blocker,
        energy_kcal=10.0 if status == "ok" else 0.0,
        protein_g=1.0 if status == "ok" else 0.0,
        fat_g=1.0 if status == "ok" else 0.0,
        carbohydrate_g=1.0 if status == "ok" else 0.0,
        fiber_g=0.0,
        sodium_mg=sodium_mg if status == "ok" else 0.0,
    )


def test_classifier_fail_closed_when_photo_ready_lacks_structured_recipe_data() -> None:
    recipe = _recipe(title_ru="Photo ready only", structured_ingredients="", servings="")
    photo = PhotoRecord(candidate_id="c001", found=True, status="found")

    result = classify_recipe(
        recipe,
        photo,
        duplicate_risk=None,
        ingredients=_parsed("blocked", "missing_ingredients"),
        servings=_servings("blocked", "invalid_servings"),
        mapping=_mapping("blocked", "unknown_ingredient_alias"),
        nutrition=_nutrition("blocked", "mapping_not_mapped"),
    )

    assert result.classification == "needs_review"
    assert "missing_ingredients" in result.blockers
    assert "invalid_servings" in result.blockers
    assert "unknown_ingredient_alias" in result.blockers
    assert "mapping_not_mapped" in result.blockers


def test_classifier_blocks_missing_photo_even_with_structured_data() -> None:
    recipe = _recipe(candidate_id="c002")
    photo = PhotoRecord(candidate_id="c002", found=False, status="missing")

    result = classify_recipe(
        recipe,
        photo,
        duplicate_risk=None,
        ingredients=_parsed(),
        servings=_servings(),
        mapping=_mapping(),
        nutrition=_nutrition(),
    )

    assert result.classification == "blocked"
    assert result.blockers == ["missing_photo"]


def test_classifier_keeps_duplicate_risk_out_of_import_ready() -> None:
    recipe = _recipe(candidate_id="c003", title_ru="Structured duplicate", duplicate_risk="medium")
    photo = PhotoRecord(candidate_id="c003", found=True, status="found")
    duplicate = DuplicateRisk(
        candidate_id="c003",
        duplicate_risk="medium",
        duplicate_reason="rice family",
        possible_duplicate_candidate_ids="c090",
    )

    result = classify_recipe(
        recipe,
        photo,
        duplicate_risk=duplicate,
        ingredients=_parsed(),
        servings=_servings(),
        mapping=_mapping(),
        nutrition=_nutrition(),
    )

    assert result.classification == "needs_review"
    assert "duplicate_risk_medium" in result.review_reasons


def test_classifier_import_ready_requires_phase2a_gates_and_nutrition() -> None:
    recipe = _recipe(nutrition="")
    photo = PhotoRecord(candidate_id="c001", found=True, status="found")

    result = classify_recipe(
        recipe,
        photo,
        duplicate_risk=None,
        ingredients=_parsed(),
        servings=_servings(),
        mapping=_mapping(),
        nutrition=_nutrition(sodium_mg=12.5),
    )

    assert result.classification == "import_ready"
    assert result.blockers == []
    assert result.review_reasons == []
    assert result.nutrition_status == "ok"


def test_classifier_blocks_nutrition_failure() -> None:
    recipe = _recipe(nutrition="")
    photo = PhotoRecord(candidate_id="c001", found=True, status="found")

    result = classify_recipe(
        recipe,
        photo,
        duplicate_risk=None,
        ingredients=_parsed(),
        servings=_servings(),
        mapping=_mapping(),
        nutrition=_nutrition("blocked", "missing_required_nutrient:sodium_mg"),
    )

    assert result.classification == "needs_review"
    assert result.nutrition_status == "blocked"
    assert "missing_required_nutrient:sodium_mg" in result.blockers
