from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.dev.recipe_importer.mapping import IngredientMappingResult


DEFAULT_DATA_DIR = Path("src/diet_bot/data")
REQUIRED_NUTRIENTS = (
    "energy_kcal",
    "protein_g",
    "fat_g",
    "carbohydrate_g",
    "fiber_g",
    "sodium_mg",
)


@dataclass(frozen=True)
class CuratedFood:
    food_id: str
    nutrients_per_100g: dict[str, float]


@dataclass(frozen=True)
class NutritionResult:
    candidate_id: str
    calculation_status: str
    blocker_reason: str
    energy_kcal: float
    protein_g: float
    fat_g: float
    carbohydrate_g: float
    fiber_g: float
    sodium_mg: float


def load_curated_foods(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, CuratedFood]:
    path = Path(data_dir) / "curated_foods.json"
    with path.open("r", encoding="utf-8") as handle:
        rows = json.load(handle)

    foods: dict[str, CuratedFood] = {}
    for row in rows:
        food_id = str(row.get("food_id", "")).strip()
        if not food_id:
            continue
        nutrients = row.get("nutrients_per_100g") or {}
        foods[food_id] = CuratedFood(
            food_id=food_id,
            nutrients_per_100g={
                key: float(value)
                for key, value in nutrients.items()
                if isinstance(value, int | float)
            },
        )
    return foods


def calculate_nutrition(
    candidate_id: str,
    mapping: IngredientMappingResult,
    foods: dict[str, CuratedFood],
) -> NutritionResult:
    if mapping.status != "mapped":
        return _blocked(candidate_id, mapping.blocker_reason or "ingredients_not_mapped")
    if not mapping.rows:
        return _blocked(candidate_id, "no_mapped_ingredients")

    totals = {nutrient: 0.0 for nutrient in REQUIRED_NUTRIENTS}
    for row in mapping.rows:
        if row.mapping_status != "mapped":
            return _blocked(candidate_id, row.blocker_reason or "ingredient_not_mapped")
        if not row.food_id:
            return _blocked(candidate_id, "missing_food_id")

        grams = _grams(row.amount, row.unit)
        if grams is None:
            return _blocked(candidate_id, "missing_grams")

        food = foods.get(row.food_id)
        if food is None:
            return _blocked(candidate_id, f"food_id_not_found:{row.food_id}")

        missing = _missing_required_nutrient(food)
        if missing:
            return _blocked(candidate_id, f"missing_required_nutrient:{missing}")

        for nutrient in REQUIRED_NUTRIENTS:
            totals[nutrient] += food.nutrients_per_100g[nutrient] * grams / 100

    return NutritionResult(
        candidate_id=candidate_id,
        calculation_status="ok",
        blocker_reason="",
        **{key: round(value, 2) for key, value in totals.items()},
    )


def _grams(amount: float, unit: str) -> float | None:
    normalized = (unit or "").strip().lower()
    if amount <= 0:
        return None
    if normalized in {"g", "gram", "grams"}:
        return amount
    if normalized in {"kg", "kilogram", "kilograms"}:
        return amount * 1000
    return None


def _missing_required_nutrient(food: CuratedFood) -> str:
    for nutrient in REQUIRED_NUTRIENTS:
        if nutrient not in food.nutrients_per_100g:
            return nutrient
    return ""


def _blocked(candidate_id: str, reason: str) -> NutritionResult:
    return NutritionResult(
        candidate_id=candidate_id,
        calculation_status="blocked",
        blocker_reason=reason,
        energy_kcal=0.0,
        protein_g=0.0,
        fat_g=0.0,
        carbohydrate_g=0.0,
        fiber_g=0.0,
        sodium_mg=0.0,
    )
