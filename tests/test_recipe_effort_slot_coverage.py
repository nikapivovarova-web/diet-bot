from __future__ import annotations

from collections import Counter

from diet_bot.builder import (
    _build_recipe_plan_for_time,
    _cooking_effort_constraints,
    _meal_energy_slots,
    _rank_recipes,
    _recipe_matches_cooking_effort,
)
from diet_bot.calculator import calculate_targets
from diet_bot.catalog import built_in_foods
from diet_bot.domain import (
    ActivityLevel,
    CookingTimePreference,
    Food,
    Goal,
    MealRole,
    NutrientVector,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
)
from diet_bot.recipe_catalog import RecipeTemplate, built_in_recipes
from diet_bot.safety import evaluate_safety, is_food_excluded, is_name_excluded


def profile_with(**kwargs) -> UserProfile:
    data = {
        "age": 32,
        "sex": Sex.MALE,
        "height_cm": 178,
        "weight_kg": 86,
        "goal": Goal.MAINTAIN,
        "activity": ActivityLevel.MODERATE,
        "meal_count": 5,
        "cooking_time": CookingTimePreference.SIMPLE,
    }
    data.update(kwargs)
    return UserProfile(**data)


def _food(
    food_id: str,
    *,
    category: str,
    energy: float,
    protein: float = 0.0,
    fat: float = 0.0,
    carbohydrate: float = 0.0,
    roles: frozenset[MealRole] = frozenset(),
) -> Food:
    return Food(
        id=food_id,
        name=f"{food_id} food",
        category=category,
        nutrients_per_100g=NutrientVector(
            {
                "energy_kcal": energy,
                "protein_g": protein,
                "fat_g": fat,
                "carbohydrate_g": carbohydrate,
            }
        ),
        roles=roles,
        max_per_meal_g=1000,
        max_per_day_g=5000,
    )


def _simple_recipe(
    recipe_id: str,
    *,
    title: str,
    instructions: str,
    time_text: str = "25 minutes",
) -> RecipeTemplate:
    return RecipeTemplate(
        id=recipe_id,
        slot="main",
        title=title,
        ingredients_g={"chicken_breast": 140, "rice": 90, "tomato": 120},
        instructions=instructions,
        tags=frozenset({"curated"}),
        time_text=time_text,
    )


def test_interesting_effort_pool_includes_simple_curated_recipes() -> None:
    curated_recipes = [recipe for recipe in built_in_recipes() if "curated" in recipe.tags]

    simple_ids = {
        recipe.id
        for recipe in curated_recipes
        if _recipe_matches_cooking_effort(recipe, CookingTimePreference.SIMPLE)
    }
    interesting_ids = {
        recipe.id
        for recipe in curated_recipes
        if _recipe_matches_cooking_effort(recipe, CookingTimePreference.INTERESTING)
    }

    assert simple_ids
    assert simple_ids <= interesting_ids


def test_simple_strict_allows_ordinary_oven_pan_and_pot() -> None:
    ordinary_recipes = (
        _simple_recipe(
            "ordinary_oven",
            title="Simple baked chicken",
            instructions="Bake chicken and tomatoes in the oven. Serve with rice.",
        ),
        _simple_recipe(
            "ordinary_pan",
            title="Simple chicken skillet",
            instructions="Cook chicken in a pan. Warm rice and tomatoes.",
        ),
        _simple_recipe(
            "ordinary_pot",
            title="Simple chicken pot",
            instructions="Simmer chicken and rice in a pot. Stir in tomatoes.",
        ),
    )

    assert all(_recipe_matches_cooking_effort(recipe, CookingTimePreference.SIMPLE) for recipe in ordinary_recipes)


def test_simple_strict_excludes_rare_equipment() -> None:
    rare_equipment_recipes = (
        _simple_recipe("waffle", title="Savory waffle plate", instructions="Cook the batter in a waffle iron."),
        _simple_recipe("grill", title="Grilled chicken bowl", instructions="Cook the chicken on a grill."),
        _simple_recipe("processor", title="Chicken bowl", instructions="Chop the sauce in a food processor."),
    )

    assert all(not _recipe_matches_cooking_effort(recipe, CookingTimePreference.SIMPLE) for recipe in rare_equipment_recipes)
    assert all(
        _recipe_matches_cooking_effort(recipe, CookingTimePreference.INTERESTING)
        for recipe in rare_equipment_recipes
    )


def test_passive_overnight_time_can_be_simple_but_active_eight_hours_is_not() -> None:
    passive_overnight = _simple_recipe(
        "passive_overnight",
        title="Overnight chicken marinade bowl",
        instructions="Mix the marinade and chicken. Leave overnight in the fridge. Cook quickly in the morning.",
        time_text="10 minutes + 8 hours chilling",
    )
    active_eight_hours = _simple_recipe(
        "active_eight_hours",
        title="Slow active stew",
        instructions="Stir and tend the pot throughout cooking. Serve with rice.",
        time_text="8 hours active cooking",
    )

    assert _recipe_matches_cooking_effort(passive_overnight, CookingTimePreference.SIMPLE)
    assert not _recipe_matches_cooking_effort(active_eight_hours, CookingTimePreference.SIMPLE)


def test_garlic_night_substring_does_not_make_simple_recipe_complex() -> None:
    garlic_recipe = _simple_recipe(
        "garlic_salmon",
        title="\u041b\u043e\u0441\u043e\u0441\u044c \u0441 \u0447\u0435\u0441\u043d\u043e\u0447\u043d\u044b\u043c \u0441\u043e\u0443\u0441\u043e\u043c",
        instructions="\u0417\u0430\u043f\u0435\u043a\u0438\u0442\u0435 \u043b\u043e\u0441\u043e\u0441\u044c. \u0421\u043c\u0435\u0448\u0430\u0439\u0442\u0435 \u0447\u0435\u0441\u043d\u043e\u0447\u043d\u044b\u0439 \u0441\u043e\u0443\u0441.",
        time_text="20 minutes",
    )

    assert _recipe_matches_cooking_effort(garlic_recipe, CookingTimePreference.SIMPLE)
    assert not is_name_excluded(
        "\u0447\u0435\u0441\u043d\u043e\u0447\u043d\u044b\u0439 \u0441\u043e\u0443\u0441",
        frozenset({"\u043d\u043e\u0447"}),
    )


def test_food_exclusion_boundaries_keep_eggplant_and_broccolini_behavior() -> None:
    egg_safety = evaluate_safety(
        profile_with(restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "egg"),))
    )
    eggplant = Food("eggplant", "eggplant", "vegetable", NutrientVector())
    egg = Food("egg", "egg", "protein", NutrientVector())

    assert not is_food_excluded(eggplant, egg_safety.excluded_food_names)
    assert is_food_excluded(egg, egg_safety.excluded_food_names)

    broccoli_safety = evaluate_safety(
        profile_with(
            restrictions=(
                Restriction(
                    RestrictionType.EXCLUDED_FOOD,
                    "\u0431\u0435\u0437 \u0431\u0440\u043e\u043a\u043a\u043e\u043b\u0438",
                ),
            )
        )
    )
    assert is_name_excluded("broccolini salad", broccoli_safety.excluded_food_names)
    assert not is_name_excluded("broccolinium supplement", broccoli_safety.excluded_food_names)


def _fallback_foods() -> list[Food]:
    return [
        _food("egg", category="protein", energy=150, protein=13, fat=10, roles=frozenset({MealRole.PROTEIN})),
        _food(
            "chicken_breast",
            category="protein",
            energy=165,
            protein=31,
            fat=4,
            roles=frozenset({MealRole.PROTEIN}),
        ),
        _food("tuna", category="protein", energy=130, protein=28, fat=1, roles=frozenset({MealRole.PROTEIN})),
        _food("pita", category="grains", energy=260, protein=8, carbohydrate=52, roles=frozenset({MealRole.CARB})),
        _food("rice", category="grains", energy=360, protein=7, carbohydrate=78, roles=frozenset({MealRole.CARB})),
        _food("tomato", category="vegetable", energy=20, protein=1, carbohydrate=4, roles=frozenset({MealRole.VEGETABLE})),
        _food("cucumber", category="vegetable", energy=15, protein=1, carbohydrate=3, roles=frozenset({MealRole.VEGETABLE})),
        _food("greek_yogurt", category="dairy", energy=95, protein=10, carbohydrate=4),
        _food("berries", category="fruit", energy=50, carbohydrate=12),
    ]


def _fallback_breakfast() -> RecipeTemplate:
    return RecipeTemplate(
        id="fallback_breakfast",
        slot="breakfast",
        title="Egg breakfast",
        ingredients_g={"egg": 200, "pita": 60},
        instructions="Cook eggs. Serve with pita.",
        tags=frozenset({"curated"}),
        time_text="10 minutes",
    )


def _main_like_snacks() -> tuple[RecipeTemplate, RecipeTemplate]:
    return (
        RecipeTemplate(
            id="snack_chicken_pita_roll",
            slot="snack",
            title="Chicken pita roll",
            ingredients_g={"chicken_breast": 180, "pita": 70, "cucumber": 100},
            instructions="Fill the pita with chicken and cucumber.",
            tags=frozenset({"curated"}),
            time_text="10 minutes",
        ),
        RecipeTemplate(
            id="snack_tuna_rice_bowl",
            slot="snack",
            title="Tuna rice bowl",
            ingredients_g={"tuna": 180, "rice": 80, "tomato": 120},
            instructions="Toss tuna, rice and tomato in a bowl.",
            tags=frozenset({"curated"}),
            time_text="10 minutes",
        ),
    )


def _snack_dessert(recipe_id: str = "snack_yogurt_berry_parfait") -> RecipeTemplate:
    return RecipeTemplate(
        id=recipe_id,
        slot="snack",
        title="Yogurt berry parfait",
        ingredients_g={"greek_yogurt": 350, "berries": 120},
        instructions="Layer yogurt and berries.",
        tags=frozenset({"curated"}),
        time_text="10 minutes",
    )


def test_main_builder_can_use_high_protein_main_like_snack_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "diet_bot.builder.built_in_recipes",
        lambda: (_fallback_breakfast(), *_main_like_snacks(), _snack_dessert()),
    )

    meals = _build_recipe_plan_for_time(
        _fallback_foods(),
        NutrientVector({"energy_kcal": 1900, "protein_g": 80, "fat_g": 55, "carbohydrate_g": 220}),
        3,
        CookingTimePreference.SIMPLE,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
    )

    recipe_ids = {meal.recipe_id for meal in meals}
    assert {"snack_chicken_pita_roll", "snack_tuna_rice_bowl"} <= recipe_ids
    assert "snack_yogurt_berry_parfait" not in recipe_ids
    assert all(meal.recipe_key and meal.recipe_key.split(":", 1)[0] == "main" for meal in meals[1:])


def test_snack_dessert_does_not_fill_main_slot(monkeypatch) -> None:
    monkeypatch.setattr(
        "diet_bot.builder.built_in_recipes",
        lambda: (_fallback_breakfast(), _snack_dessert("snack_dessert_one"), _snack_dessert("snack_dessert_two")),
    )

    meals = _build_recipe_plan_for_time(
        _fallback_foods(),
        NutrientVector({"energy_kcal": 1900, "protein_g": 80, "fat_g": 55, "carbohydrate_g": 220}),
        3,
        CookingTimePreference.SIMPLE,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
    )

    assert meals == []


def test_simple_main_eligible_coverage_exceeds_audit_baseline() -> None:
    profile = profile_with()
    target = calculate_targets(profile).targets
    food_by_id = {food.id: food for food in built_in_foods()}
    lunch_slot = _meal_energy_slots(5)[1]
    simple_curated = [
        recipe
        for recipe in built_in_recipes()
        if "curated" in recipe.tags and _recipe_matches_cooking_effort(recipe, _cooking_effort_constraints(CookingTimePreference.SIMPLE))
    ]

    def is_imported_intake(recipe) -> bool:
        return recipe.id.startswith("r") and recipe.id[1:4].isdigit() and int(recipe.id[1:4]) >= 401

    def ranked_main_count(recipes) -> int:
        return len(
            _rank_recipes(
                recipes,
                "main",
                set(),
                Counter(),
                Counter(),
                food_by_id,
                NutrientVector(),
                target,
                target.get("energy_kcal") * lunch_slot.target_ratio,
                target.get("energy_kcal") * lunch_slot.min_ratio,
                target.get("energy_kcal") * lunch_slot.max_ratio,
                0,
                1,
            )
        )

    legacy_eligible = ranked_main_count([recipe for recipe in simple_curated if not is_imported_intake(recipe)])
    eligible = ranked_main_count(simple_curated)

    assert legacy_eligible >= 55
    assert eligible >= 86
    assert eligible - legacy_eligible >= 26
