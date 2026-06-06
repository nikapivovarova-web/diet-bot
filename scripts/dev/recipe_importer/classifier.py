from __future__ import annotations

import json
from dataclasses import dataclass

from scripts.dev.recipe_importer.loader import DuplicateRisk, NormalizedRecipe
from scripts.dev.recipe_importer.photos import PhotoRecord


@dataclass(frozen=True)
class ClassificationResult:
    candidate_id: str
    title_ru: str
    classification: str
    blockers: list[str]
    review_reasons: list[str]
    duplicate_risk: str
    photo_status: str


def classify_recipe(
    recipe: NormalizedRecipe,
    photo: PhotoRecord,
    duplicate_risk: DuplicateRisk | None,
) -> ClassificationResult:
    blockers: list[str] = []
    review_reasons: list[str] = []

    if not photo.found:
        blockers.append("missing_photo")

    if not _has_structured_ingredients(recipe.structured_ingredients):
        blockers.append("missing_structured_ingredients")
    if not _has_positive_servings(recipe.servings):
        blockers.append("missing_servings")
    if not _has_nutrition(recipe.nutrition):
        blockers.append("missing_nutrition")

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
    )


def _has_structured_ingredients(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, list) and bool(parsed)


def _has_positive_servings(value: str) -> bool:
    if not value:
        return False
    try:
        return float(value) > 0
    except ValueError:
        return False


def _has_nutrition(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and bool(parsed)
