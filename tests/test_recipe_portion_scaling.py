from __future__ import annotations

from collections import defaultdict

import pytest

from diet_bot.builder import (
    _increase_existing_portions,
    _project_recipe_nutrients,
    _recipe_scale,
    _scaled_recipe_portions,
)
from diet_bot.domain import Food, FoodPortion, Meal, MealRole, NutrientVector
from diet_bot.recipe_catalog import RecipeTemplate


def _food(
    food_id: str,
    *,
    category: str,
    energy: float,
    protein: float = 0.0,
    fat: float = 0.0,
    carbohydrate: float = 0.0,
    max_per_meal_g: float = 1000,
    max_per_day_g: float = 5000,
) -> Food:
    return Food(
        id=food_id,
        name=f"{food_id} food",
        category=category,
        roles=frozenset({MealRole.PROTEIN}) if category == "protein" else frozenset(),
        max_per_meal_g=max_per_meal_g,
        max_per_day_g=max_per_day_g,
        nutrients_per_100g=NutrientVector(
            {
                "energy_kcal": energy,
                "protein_g": protein,
                "fat_g": fat,
                "carbohydrate_g": carbohydrate,
            }
        ),
    )


def _foods_by_id() -> dict[str, Food]:
    foods = (
        _food("egg", category="protein", energy=143, protein=12.6, fat=9.5, max_per_meal_g=180),
        _food("egg_white", category="protein", energy=52, protein=10.9, max_per_meal_g=150),
        _food("pita", category="grains", energy=260, protein=8, carbohydrate=52, max_per_meal_g=160),
        _food("olive_oil", category="fat", energy=884, fat=100, max_per_meal_g=35),
        _food("salt", category="spice", energy=0, max_per_meal_g=6),
        _food("lemon_juice", category="fruit", energy=22, carbohydrate=7, max_per_meal_g=80),
        _food("feta", category="dairy", energy=265, protein=14, fat=21, max_per_meal_g=100),
        _food("chicken_breast", category="protein", energy=165, protein=31, fat=3.6, max_per_meal_g=240),
        _food("tomato", category="vegetable", energy=20, protein=1, carbohydrate=4, max_per_meal_g=300),
    )
    return {food.id: food for food in foods}


def _assert_nutrients_close(left: NutrientVector, right: NutrientVector) -> None:
    keys = set(left.amounts) | set(right.amounts)
    for key in keys:
        assert left.get(key) == pytest.approx(right.get(key), abs=1e-9), key


def test_scaled_recipe_portions_use_practical_units_and_caps() -> None:
    food_by_id = _foods_by_id()
    recipe = RecipeTemplate(
        id="scaled_practical_recipe",
        slot="main",
        title="Scaled practical recipe",
        ingredients_g={
            "egg": 75,
            "egg_white": 33,
            "pita": 47,
            "olive_oil": 18,
            "salt": 6,
            "lemon_juice": 50,
            "feta": 15,
            "chicken_breast": 121,
            "tomato": 86,
        },
        instructions="Assemble.",
    )
    resolved = tuple((food_by_id[food_id], grams) for food_id, grams in recipe.ingredients_g.items())
    base_energy = NutrientVector.sum(food.portion(grams).nutrients for food, grams in resolved).get("energy_kcal")
    scale = _recipe_scale(base_energy * 1.70, base_energy)

    portions = _scaled_recipe_portions(
        resolved,
        scale,
        defaultdict(float),
        NutrientVector(),
        NutrientVector({"energy_kcal": 2400, "protein_g": 180, "fat_g": 100, "carbohydrate_g": 300}),
        meal_slot="main",
    )
    grams = {portion.food.id: portion.grams for portion in portions}

    assert grams["egg"] % 50 == 0
    assert grams["egg_white"] % 5 == 0
    assert grams["pita"] % 30 == 0
    assert grams["olive_oil"] <= 15
    assert grams["salt"] <= 3
    assert grams["lemon_juice"] <= 35
    assert grams["feta"] == 15
    assert grams["chicken_breast"] % 10 == 0
    assert grams["tomato"] % 10 == 0


def test_projection_nutrients_match_actual_scaled_food_portions() -> None:
    food_by_id = _foods_by_id()
    recipe = RecipeTemplate(
        id="projection_matches_actual",
        slot="main",
        title="Projection matches actual",
        ingredients_g={
            "egg": 75,
            "pita": 47,
            "olive_oil": 18,
            "salt": 6,
            "lemon_juice": 50,
            "feta": 15,
            "chicken_breast": 121,
            "tomato": 86,
        },
        instructions="Assemble.",
    )
    resolved = tuple((food_by_id[food_id], grams) for food_id, grams in recipe.ingredients_g.items())
    base_energy = NutrientVector.sum(food.portion(grams).nutrients for food, grams in resolved).get("energy_kcal")
    slot_energy_target = base_energy * 1.70
    target = NutrientVector({"energy_kcal": 2400, "protein_g": 180, "fat_g": 100, "carbohydrate_g": 300})

    projected = _project_recipe_nutrients(recipe, food_by_id, slot_energy_target, meal_slot="main")
    actual = NutrientVector.sum(
        portion.nutrients
        for portion in _scaled_recipe_portions(
            resolved,
            _recipe_scale(slot_energy_target, base_energy),
            defaultdict(float),
            NutrientVector(),
            target,
            meal_slot="main",
        )
    )

    assert projected is not None
    _assert_nutrients_close(projected, actual)


def test_existing_portion_top_up_preserves_practical_rounding_and_caps() -> None:
    food_by_id = _foods_by_id()
    portions = (
        FoodPortion(food_by_id["egg"], 100),
        FoodPortion(food_by_id["pita"], 60),
        FoodPortion(food_by_id["olive_oil"], 10),
        FoodPortion(food_by_id["lemon_juice"], 30),
        FoodPortion(food_by_id["feta"], 15),
    )
    meals = [Meal("breakfast", portions, "Assemble.")]
    used_grams = defaultdict(float, {portion.food.id: portion.grams for portion in portions})

    updated = _increase_existing_portions(
        meals,
        NutrientVector({"energy_kcal": 3000, "protein_g": 120, "fat_g": 120, "carbohydrate_g": 320}),
        used_grams,
    )
    grams = {portion.food.id: portion.grams for portion in updated[0].portions}

    assert grams["egg"] % 50 == 0
    assert grams["pita"] % 30 == 0
    assert grams["olive_oil"] <= 10
    assert grams["lemon_juice"] <= 35
    assert grams["feta"] == 15


def test_carb_base_recovers_calories_when_protein_is_above_preferred_ceiling() -> None:
    lean_protein = _food(
        "lean_protein",
        category="protein",
        energy=50,
        protein=25,
        max_per_meal_g=600,
        max_per_day_g=600,
    )
    pita = _food(
        "pita",
        category="grains",
        energy=260,
        protein=8,
        carbohydrate=52,
        max_per_meal_g=160,
    )
    portions = (FoodPortion(lean_protein, 500), FoodPortion(pita, 60))
    meals = [Meal("breakfast", portions, "Assemble.")]
    used_grams = defaultdict(float, {portion.food.id: portion.grams for portion in portions})
    target = NutrientVector(
        {"energy_kcal": 2000, "protein_g": 100, "fat_g": 80, "carbohydrate_g": 280}
    )
    before = NutrientVector.sum(meal.nutrients for meal in meals)

    assert before.get("energy_kcal") < target.get("energy_kcal") * 0.96
    assert before.get("protein_g") > target.get("protein_g") * 1.20

    updated = _increase_existing_portions(meals, target, used_grams)
    grams = {portion.food.id: portion.grams for portion in updated[0].portions}
    total = NutrientVector.sum(meal.nutrients for meal in updated)

    assert grams["pita"] > 60
    assert grams["pita"] % 30 == 0
    assert total.get("protein_g") <= target.get("protein_g") * 1.50


def test_protein_anchor_cannot_recover_calories_past_strict_protein_ceiling() -> None:
    chicken = _food(
        "chicken_breast",
        category="protein",
        energy=165,
        protein=31,
        max_per_meal_g=600,
        max_per_day_g=600,
    )
    portions = (FoodPortion(chicken, 480),)
    meals = [Meal("breakfast", portions, "Assemble.")]
    used_grams = defaultdict(float, {"chicken_breast": 480})
    target = NutrientVector(
        {"energy_kcal": 2000, "protein_g": 100, "fat_g": 80, "carbohydrate_g": 280}
    )

    updated = _increase_existing_portions(meals, target, used_grams)
    grams = {portion.food.id: portion.grams for portion in updated[0].portions}
    total = NutrientVector.sum(meal.nutrients for meal in updated)

    assert grams["chicken_breast"] == 480
    assert total.get("protein_g") <= target.get("protein_g") * 1.50


def test_oil_salt_and_lemon_are_not_used_for_calorie_recovery() -> None:
    food_by_id = _foods_by_id()
    portions = (
        FoodPortion(food_by_id["olive_oil"], 10),
        FoodPortion(food_by_id["salt"], 3),
        FoodPortion(food_by_id["lemon_juice"], 30),
    )
    meals = [Meal("breakfast", portions, "Assemble.")]
    used_grams = defaultdict(float, {portion.food.id: portion.grams for portion in portions})

    updated = _increase_existing_portions(
        meals,
        NutrientVector({"energy_kcal": 2000, "protein_g": 100, "fat_g": 80, "carbohydrate_g": 280}),
        used_grams,
    )
    grams = {portion.food.id: portion.grams for portion in updated[0].portions}

    assert grams["olive_oil"] == 10
    assert grams["salt"] == 3
    assert grams["lemon_juice"] == 30


def test_scaled_recipe_portions_reject_tiny_garnish_only_remnant() -> None:
    food_by_id = _foods_by_id()
    resolved = (
        (food_by_id["tomato"], 50.0),
        (food_by_id["salt"], 1.0),
        (food_by_id["lemon_juice"], 10.0),
    )

    portions = _scaled_recipe_portions(
        resolved,
        1.0,
        defaultdict(float),
        NutrientVector({"protein_g": 75}),
        NutrientVector({"energy_kcal": 2182, "protein_g": 50, "fat_g": 73, "carbohydrate_g": 332}),
        meal_slot="snack",
    )

    assert portions == ()
