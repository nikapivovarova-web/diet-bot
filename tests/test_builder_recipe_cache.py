from __future__ import annotations

from dataclasses import replace

from diet_bot.builder import (
    _cooking_effort_constraints,
    _recipe_matches_cooking_effort,
    _resolve_recipe_ingredients,
    filter_foods,
)
from diet_bot.catalog import built_in_foods
from diet_bot.chef import format_ingredient
from diet_bot.domain import (
    ActivityLevel,
    ConditionCode,
    CookingTimePreference,
    Food,
    Goal,
    Meal,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
)
from diet_bot.recipe_catalog import RecipeTemplate, built_in_recipes
from diet_bot.safety import evaluate_safety
from diet_bot.shopping import build_shopping_list_for_meals


def _profile() -> UserProfile:
    return UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=5,
        cooking_time=CookingTimePreference.SIMPLE,
    )


def _hard_blender_profile() -> UserProfile:
    return UserProfile(
        age=32,
        sex=Sex.FEMALE,
        height_cm=168,
        weight_kg=68,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=5,
        cooking_time=CookingTimePreference.SIMPLE,
        conditions=(ConditionCode.LACTOSE_INTOLERANCE, ConditionCode.HYPERTENSION),
        restrictions=(
            Restriction(RestrictionType.ALLERGY, "\u044f\u0439\u0446\u0430"),
            Restriction(RestrictionType.ALLERGY, "\u043e\u0440\u0435\u0445\u0438"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "\u0433\u0440\u0438\u0431\u044b"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "\u043a\u0438\u043d\u0437\u0430"),
        ),
    )


def _milk_recipe() -> RecipeTemplate:
    return RecipeTemplate(
        id="milk_based_breakfast",
        slot="breakfast",
        title="Milk oats",
        ingredients_g={"milk": 180, "oats": 45, "banana": 100},
        instructions="Mix oats, milk, and banana. Chill and serve.",
        tags=frozenset({"curated"}),
        time_text="10 minutes",
        active_time_min=10,
        cooking_effort="simple",
    )


def _filtered_food_by_id(profile: UserProfile) -> dict[str, Food]:
    safety = evaluate_safety(profile)
    return {food.id: food for food in filter_foods(built_in_foods(), safety)}


def _hard_safe_simple_recipe_ids(food_by_id: dict[str, Food]) -> set[str]:
    strict_simple = _cooking_effort_constraints(CookingTimePreference.SIMPLE)
    return {
        recipe.id
        for recipe in built_in_recipes()
        if "curated" in recipe.tags
        and _resolve_recipe_ingredients(recipe, food_by_id) is not None
        and _recipe_matches_cooking_effort(recipe, strict_simple)
    }


def test_lactose_intolerance_resolves_milk_recipe_to_lactose_free_milk_without_mutating_source() -> None:
    profile = replace(_profile(), conditions=(ConditionCode.LACTOSE_INTOLERANCE,))
    recipe = _milk_recipe()
    original_ingredients = dict(recipe.ingredients_g)

    resolved = _resolve_recipe_ingredients(recipe, _filtered_food_by_id(profile))

    assert resolved is not None
    resolved_ids = [food.id for food, _grams in resolved]
    assert resolved_ids == ["lactose_free_milk", "oats", "banana"]
    assert recipe.ingredients_g == original_ingredients
    assert "lactose_free_milk" not in recipe.ingredients_g


def test_lactose_free_milk_substitution_is_visible_in_portions_shopping_and_pdf_ingredients() -> None:
    profile = replace(_profile(), conditions=(ConditionCode.LACTOSE_INTOLERANCE,))
    resolved = _resolve_recipe_ingredients(_milk_recipe(), _filtered_food_by_id(profile))

    assert resolved is not None
    milk_food, milk_grams = resolved[0]
    milk_portion = milk_food.portion(milk_grams)
    meal = Meal(
        name="Breakfast",
        portions=(milk_portion,),
        recipe="Serve.",
        recipe_id="milk_based_breakfast",
        recipe_key="breakfast:curated:milk_based_breakfast",
    )
    shopping = build_shopping_list_for_meals((meal,))

    assert milk_food.id == "lactose_free_milk"
    assert "\u0431\u0435\u0437\u043b\u0430\u043a\u0442\u043e\u0437" in milk_food.name.casefold()
    assert "\u0431\u0435\u0437\u043b\u0430\u043a\u0442\u043e\u0437" in format_ingredient(milk_portion).casefold()
    assert [item.food_name for item in shopping] == [milk_food.name]


def test_milk_allergy_and_explicit_milk_exclusion_block_lactose_free_milk_substitution() -> None:
    lactose_profile = replace(_profile(), conditions=(ConditionCode.LACTOSE_INTOLERANCE,))
    guarded_profiles = (
        replace(
            lactose_profile,
            restrictions=(Restriction(RestrictionType.ALLERGY, "milk"),),
        ),
        replace(
            lactose_profile,
            restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "milk"),),
        ),
        replace(
            lactose_profile,
            restrictions=(Restriction(RestrictionType.ALLERGY, "dairy"),),
        ),
    )

    for guarded_profile in guarded_profiles:
        food_by_id = _filtered_food_by_id(guarded_profile)

        assert "milk" not in food_by_id
        assert "lactose_free_milk" not in food_by_id
        assert _resolve_recipe_ingredients(_milk_recipe(), food_by_id) is None


def test_existing_lactose_free_yogurt_and_cottage_substitutions_do_not_bypass_exclusions() -> None:
    lactose_profile = replace(_profile(), conditions=(ConditionCode.LACTOSE_INTOLERANCE,))
    yogurt_recipe = RecipeTemplate(
        id="yogurt_recipe",
        slot="snack",
        title="Yogurt snack",
        ingredients_g={"greek_yogurt": 150, "berries": 100},
        instructions="Serve.",
        tags=frozenset({"curated"}),
    )
    cottage_recipe = RecipeTemplate(
        id="cottage_recipe",
        slot="snack",
        title="Cottage snack",
        ingredients_g={"cottage_cheese": 150, "berries": 100},
        instructions="Serve.",
        tags=frozenset({"curated"}),
    )

    dairy_allergy_foods = _filtered_food_by_id(
        replace(lactose_profile, restrictions=(Restriction(RestrictionType.ALLERGY, "dairy"),))
    )
    yogurt_exclusion_foods = _filtered_food_by_id(
        replace(lactose_profile, restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "yogurt"),))
    )
    cottage_exclusion_foods = _filtered_food_by_id(
        replace(lactose_profile, restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "cottage cheese"),))
    )

    assert _resolve_recipe_ingredients(yogurt_recipe, dairy_allergy_foods) is None
    assert _resolve_recipe_ingredients(cottage_recipe, dairy_allergy_foods) is None
    assert _resolve_recipe_ingredients(yogurt_recipe, yogurt_exclusion_foods) is None
    assert _resolve_recipe_ingredients(cottage_recipe, cottage_exclusion_foods) is None


def test_lactose_free_milk_expands_hard_profile_strict_simple_eligible_pool() -> None:
    profile = _hard_blender_profile()
    food_by_id = _filtered_food_by_id(profile)
    without_lactose_free_milk = {
        food_id: food
        for food_id, food in food_by_id.items()
        if food_id != "lactose_free_milk"
    }

    recovered_ids = (
        _hard_safe_simple_recipe_ids(food_by_id)
        - _hard_safe_simple_recipe_ids(without_lactose_free_milk)
    )

    recipes_by_id = {recipe.id: recipe for recipe in built_in_recipes()}

    assert recovered_ids
    assert all("milk" in recipes_by_id[recipe_id].ingredients_g for recipe_id in recovered_ids)
