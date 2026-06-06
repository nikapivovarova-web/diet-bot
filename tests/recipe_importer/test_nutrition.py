import json
from pathlib import Path

from scripts.dev.recipe_importer.mapping import IngredientMappingResult, IngredientMappingRow
from scripts.dev.recipe_importer.nutrition import calculate_nutrition, load_curated_foods


def _write_foods(data_dir: Path, foods: list[dict[str, object]]) -> Path:
    data_dir.mkdir()
    path = data_dir / "curated_foods.json"
    path.write_text(json.dumps(foods), encoding="utf-8")
    return data_dir


def _food(food_id: str, nutrients: dict[str, float]) -> dict[str, object]:
    return {"food_id": food_id, "nutrients_per_100g": nutrients}


def _required(
    *,
    energy_kcal: float = 0,
    protein_g: float = 0,
    fat_g: float = 0,
    carbohydrate_g: float = 0,
    fiber_g: float = 0,
    sodium_mg: float = 0,
) -> dict[str, float]:
    return {
        "energy_kcal": energy_kcal,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbohydrate_g": carbohydrate_g,
        "fiber_g": fiber_g,
        "sodium_mg": sodium_mg,
    }


def _mapping(rows: list[IngredientMappingRow]) -> IngredientMappingResult:
    return IngredientMappingResult(
        candidate_id="c001",
        status="mapped",
        blocker_reason="",
        rows=rows,
    )


def _row(food_id: str, amount: float, unit: str = "g") -> IngredientMappingRow:
    return IngredientMappingRow(
        ingredient_name=food_id,
        normalized_alias=food_id,
        food_id=food_id,
        amount=amount,
        unit=unit,
        mapping_status="mapped",
        blocker_reason="",
    )


def test_nutrition_calculation_sums_multiple_ingredients(tmp_path: Path) -> None:
    foods = load_curated_foods(
        _write_foods(
            tmp_path / "data",
            [
                _food(
                    "rice",
                    _required(
                        energy_kcal=200,
                        protein_g=4,
                        fat_g=1,
                        carbohydrate_g=40,
                        fiber_g=2,
                        sodium_mg=10,
                    ),
                ),
                _food(
                    "oil",
                    _required(
                        energy_kcal=800,
                        protein_g=0,
                        fat_g=90,
                        carbohydrate_g=0,
                        fiber_g=0,
                        sodium_mg=5,
                    ),
                ),
            ],
        )
    )

    result = calculate_nutrition("c001", _mapping([_row("rice", 150), _row("oil", 10)]), foods)

    assert result.calculation_status == "ok"
    assert result.blocker_reason == ""
    assert result.energy_kcal == 380.0
    assert result.protein_g == 6.0
    assert result.fat_g == 10.5
    assert result.carbohydrate_g == 60.0
    assert result.fiber_g == 3.0
    assert result.sodium_mg == 15.5


def test_nutrition_treats_ml_as_gram_equivalent_for_importer_audit(tmp_path: Path) -> None:
    foods = load_curated_foods(
        _write_foods(
            tmp_path / "data",
            [
                _food(
                    "lemon_juice",
                    _required(
                        energy_kcal=20,
                        protein_g=0,
                        fat_g=0,
                        carbohydrate_g=7,
                        fiber_g=0,
                        sodium_mg=1,
                    ),
                )
            ],
        )
    )

    result = calculate_nutrition("c001", _mapping([_row("lemon_juice", 30, "ml")]), foods)

    assert result.calculation_status == "ok"
    assert result.energy_kcal == 6.0
    assert result.sodium_mg == 0.3


def test_nutrition_missing_food_id_blocks(tmp_path: Path) -> None:
    foods = load_curated_foods(
        _write_foods(tmp_path / "data", [_food("rice", _required(energy_kcal=200))])
    )

    result = calculate_nutrition("c001", _mapping([_row("", 100)]), foods)

    assert result.calculation_status == "blocked"
    assert result.blocker_reason == "missing_food_id"


def test_nutrition_missing_grams_blocks(tmp_path: Path) -> None:
    foods = load_curated_foods(
        _write_foods(tmp_path / "data", [_food("rice", _required(energy_kcal=200))])
    )

    result = calculate_nutrition("c001", _mapping([_row("rice", 100, "count")]), foods)

    assert result.calculation_status == "blocked"
    assert result.blocker_reason == "missing_grams"


def test_nutrition_missing_required_nutrient_blocks(tmp_path: Path) -> None:
    incomplete = _required(energy_kcal=200)
    del incomplete["fiber_g"]
    foods = load_curated_foods(_write_foods(tmp_path / "data", [_food("rice", incomplete)]))

    result = calculate_nutrition("c001", _mapping([_row("rice", 100)]), foods)

    assert result.calculation_status == "blocked"
    assert result.blocker_reason == "missing_required_nutrient:fiber_g"


def test_nutrition_requires_sodium(tmp_path: Path) -> None:
    incomplete = _required(energy_kcal=200)
    del incomplete["sodium_mg"]
    foods = load_curated_foods(_write_foods(tmp_path / "data", [_food("rice", incomplete)]))

    result = calculate_nutrition("c001", _mapping([_row("rice", 100)]), foods)

    assert result.calculation_status == "blocked"
    assert result.blocker_reason == "missing_required_nutrient:sodium_mg"
