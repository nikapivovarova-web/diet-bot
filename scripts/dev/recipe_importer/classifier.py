from __future__ import annotations

from dataclasses import dataclass

from scripts.dev.recipe_importer.ingredients import IngredientParseResult
from scripts.dev.recipe_importer.loader import DuplicateRisk, NormalizedRecipe
from scripts.dev.recipe_importer.mapping import IngredientMappingResult
from scripts.dev.recipe_importer.nutrition import NutritionResult
from scripts.dev.recipe_importer.photos import PhotoRecord
from scripts.dev.recipe_importer.servings import ServingsResult


@dataclass(frozen=True)
class ClassificationResult:
    candidate_id: str
    title_ru: str
    classification: str
    blockers: list[str]
    review_reasons: list[str]
    duplicate_risk: str
    photo_status: str
    parse_status: str
    servings_status: str
    mapping_status: str
    nutrition_status: str


def classify_recipe(
    recipe: NormalizedRecipe,
    photo: PhotoRecord,
    duplicate_risk: DuplicateRisk | None,
    *,
    ingredients: IngredientParseResult,
    servings: ServingsResult,
    mapping: IngredientMappingResult,
    nutrition: NutritionResult,
) -> ClassificationResult:
    blockers: list[str] = []
    review_reasons: list[str] = []

    if not photo.found:
        _append_unique(blockers, "missing_photo")

    if ingredients.parse_status != "parsed":
        _append_unique(blockers, ingredients.blocker_reason or "ingredients_not_parsed")
    if servings.status != "valid":
        _append_unique(blockers, servings.blocker_reason or "invalid_servings")
    if mapping.status != "mapped":
        _append_unique(blockers, mapping.blocker_reason or "ingredients_not_mapped")
    if nutrition.calculation_status != "ok":
        _append_unique(blockers, nutrition.blocker_reason or "nutrition_not_calculated")

    risk = (duplicate_risk.duplicate_risk if duplicate_risk else recipe.duplicate_risk).lower()
    if risk and risk not in {"low", "none"}:
        review_reasons.append(f"duplicate_risk_{risk}")

    if "missing_photo" in blockers:
        classification = "blocked"
    elif blockers or review_reasons:
        classification = "needs_review"
    else:
        classification = "import_ready"

    return ClassificationResult(
        candidate_id=recipe.candidate_id,
        title_ru=recipe.title_ru,
        classification=classification,
        blockers=blockers,
        review_reasons=review_reasons,
        duplicate_risk=risk or "",
        photo_status=photo.status,
        parse_status=ingredients.parse_status,
        servings_status=servings.status,
        mapping_status=mapping.status,
        nutrition_status=nutrition.calculation_status,
    )


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
