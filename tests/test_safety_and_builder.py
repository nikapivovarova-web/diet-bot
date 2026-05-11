from pathlib import Path

import pytest

from diet_bot.builder import _meal_energy_slots, _recipe_time_bucket, build_one_day_plan, filter_foods
from diet_bot.catalog import built_in_foods
from diet_bot.domain import (
    ActivityLevel,
    ConditionCode,
    CookingTimePreference,
    Meal,
    MealPlan,
    NutrientVector,
    NutritionTargets,
    Goal,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
)
from diet_bot.recipe_catalog import built_in_recipes
from diet_bot.safety import evaluate_safety, is_food_excluded, is_name_excluded
from diet_bot.validation import validate_plan


DATA_DIR = Path(__file__).resolve().parents[1] / "src" / "diet_bot" / "data"


def profile_with(**kwargs) -> UserProfile:
    data = {
        "age": 32,
        "sex": Sex.MALE,
        "height_cm": 178,
        "weight_kg": 86,
        "goal": Goal.LOSE,
        "activity": ActivityLevel.MODERATE,
        "meal_count": 4,
    }
    data.update(kwargs)
    return UserProfile(**data)


def food_names(plan) -> set[str]:
    return {portion.food.name for meal in plan.meals for portion in meal.portions}


def assert_meal_energy_distribution(plan) -> None:
    target_energy = plan.targets.targets.get("energy_kcal")
    for meal, slot in zip(plan.meals, _meal_energy_slots(len(plan.meals))):
        meal_energy = meal.nutrients.get("energy_kcal")

        assert meal_energy >= target_energy * slot.min_ratio - 10
        assert meal_energy <= target_energy * slot.max_ratio + 10


def test_apple_allergy_excludes_apple() -> None:
    profile = profile_with(restrictions=(Restriction(RestrictionType.ALLERGY, "яблоко"),))
    plan = build_one_day_plan(profile)

    assert "яблоко" not in food_names(plan)
    assert validate_plan(plan).ok


def test_excluded_mushrooms_filter_curated_recipes_by_alias() -> None:
    profile = profile_with(
        restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "не ем грибы"),),
        cooking_time=CookingTimePreference.QUICK,
        meal_count=5,
    )
    plan = build_one_day_plan(profile, variety_seed=1, recipe_source="curated_only")
    food_ids = {portion.food.id for meal in plan.meals for portion in meal.portions}
    validation = validate_plan(plan)

    assert len(plan.meals) == 5
    assert "mushrooms" not in food_ids
    assert not any("excluded" in error for error in validation.errors)


def test_name_exclusion_does_not_reverse_match_short_cyrillic_fragment() -> None:
    assert not is_name_excluded("сыр", frozenset({"сы"}))
    assert not is_name_excluded("мед", frozenset({"медовый месяц"}))
    assert not is_name_excluded("чай", frozenset({"чайная ложка"}))
    assert not is_name_excluded("сыр", frozenset({"сырые креветки"}))
    assert is_name_excluded("сыр", frozenset({"сыр", "сырный"}))
    assert is_name_excluded("сыр", frozenset({"сырный"}))
    assert is_name_excluded("сыр", frozenset({"не ем сыр"}))


def test_free_text_intolerance_excludes_named_food() -> None:
    profile = profile_with(restrictions=(Restriction(RestrictionType.INTOLERANCE, "peanut"),))
    safety = evaluate_safety(profile)
    peanut = next(food for food in built_in_foods() if food.id == "peanuts")

    assert is_food_excluded(peanut, safety.excluded_food_names)


def test_food_allergy_restriction_does_not_block_plan_generation() -> None:
    profile = profile_with(
        conditions=(),
        restrictions=(Restriction(RestrictionType.ALLERGY, "пищевая аллергия"),),
    )
    safety = evaluate_safety(profile)

    assert safety.can_generate_plan
    assert safety.red_flags == ()


def test_validate_plan_blocks_forbidden_food_for_intolerance() -> None:
    profile = profile_with(restrictions=(Restriction(RestrictionType.INTOLERANCE, "peanut"),))
    safety = evaluate_safety(profile)
    peanut = next(food for food in built_in_foods() if food.id == "peanuts")
    meal = Meal("Перекус: peanuts", (peanut.portion(20),), "Serve.")
    targets = NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector({"energy_kcal": 100}),
        calorie_bounds=(0, 10_000),
        macro_bounds={},
    )

    validation = validate_plan(MealPlan((meal,), targets, safety))

    assert not validation.ok
    assert any("excluded" in error for error in validation.errors)


def test_celiac_excludes_gluten_foods_and_oats_by_default() -> None:
    profile = profile_with(conditions=(ConditionCode.CELIAC,))
    safety = evaluate_safety(profile)
    eligible = filter_foods(built_in_foods(), safety)
    ids = {food.id for food in eligible}

    assert "whole_wheat_pasta" not in ids
    assert "oats" not in ids


def test_lactose_intolerance_prefers_lactose_free_dairy() -> None:
    profile = profile_with(conditions=(ConditionCode.LACTOSE_INTOLERANCE,), allow_lactose_free_dairy=True)
    plan = build_one_day_plan(profile)
    names = food_names(plan)

    assert "греческий йогурт" not in names
    assert "безлактозный йогурт" in names


def test_regular_profile_does_not_use_lactose_free_dairy() -> None:
    profile = profile_with()
    plan = build_one_day_plan(profile)
    names = food_names(plan)

    assert not any("безлактоз" in name for name in names)


def test_maintain_plan_does_not_grossly_overshoot_protein() -> None:
    profile = profile_with(goal=Goal.MAINTAIN, weight_kg=90, meal_count=5)
    plan = build_one_day_plan(profile, variety_seed=4)

    assert plan.totals.get("protein_g") <= plan.targets.targets.get("protein_g") * 1.35


def test_ckd_excludes_high_sodium_foods_and_adds_caution() -> None:
    profile = profile_with(conditions=(ConditionCode.CKD,))
    plan = build_one_day_plan(profile)
    names = food_names(plan)

    assert "соленая колбаса" not in names
    assert plan.safety.caution_notes
    assert validate_plan(plan).ok


def test_red_flag_under_18_stops_plan_generation() -> None:
    profile = profile_with(age=17)
    plan = build_one_day_plan(profile)

    assert not plan.safety.can_generate_plan
    assert plan.meals == ()


def test_very_low_bmi_does_not_stop_plan_generation() -> None:
    profile = profile_with(height_cm=159, weight_kg=40, goal=Goal.MAINTAIN)
    plan = build_one_day_plan(profile, recipe_source="curated_only")

    assert plan.targets.bmi == 15.8
    assert plan.safety.can_generate_plan
    assert len(plan.meals) == profile.meal_count


def test_gain_plan_stays_close_to_calorie_target() -> None:
    profile = profile_with(weight_kg=75, goal=Goal.GAIN)
    plan = build_one_day_plan(profile)

    assert plan.totals.get("energy_kcal") >= plan.targets.targets.get("energy_kcal") * 0.96


@pytest.mark.slow_pdf_builder
def test_recipe_plan_keeps_meal_calories_reasonably_distributed() -> None:
    cases = (
        (3, (6,)),
        (4, (1, 2, 4, 11, 25, 32, 47)),
        (5, (7,)),
    )

    for meal_count, seeds in cases:
        profile = profile_with(meal_count=meal_count)
        for seed in seeds:
            plan = build_one_day_plan(profile, variety_seed=seed)

            assert_meal_energy_distribution(plan)


def test_high_bmi_loss_plan_does_not_report_catastrophic_protein_gap() -> None:
    profile = profile_with(height_cm=170, weight_kg=132, goal=Goal.LOSE)
    plan = build_one_day_plan(profile, variety_seed=0)

    assert plan.targets.targets.get("protein_g") == 139
    assert plan.totals.get("protein_g") >= plan.targets.targets.get("protein_g") * 0.85


def test_curated_high_bmi_loss_plan_tops_up_protein_when_possible() -> None:
    profile = profile_with(height_cm=170, weight_kg=132, goal=Goal.LOSE)
    plan = build_one_day_plan(profile, variety_seed=43, recipe_source="curated_only")

    assert plan.totals.get("protein_g") >= plan.targets.targets.get("protein_g") * 0.90
    assert plan.totals.get("energy_kcal") <= plan.targets.targets.get("energy_kcal") * 1.04


@pytest.mark.slow_pdf_builder
def test_repeat_generation_changes_recipes() -> None:
    profile = profile_with(weight_kg=75, goal=Goal.GAIN, meal_count=5)
    first = build_one_day_plan(profile, variety_seed=0)
    second = build_one_day_plan(profile, variety_seed=1)

    first_names = {meal.name for meal in first.meals}
    second_names = {meal.name for meal in second.meals}
    assert first_names != second_names


def test_recipe_catalog_has_large_unique_recipe_pool() -> None:
    recipes = built_in_recipes()
    ids = {recipe.id for recipe in recipes}
    titles = {(recipe.slot, recipe.title) for recipe in recipes}
    ingredient_signatures = {
        (recipe.slot, tuple(sorted(recipe.ingredients_g.items())))
        for recipe in recipes
    }

    assert len(recipes) >= 5000
    assert len(ids) == len(recipes)
    assert len(titles) == len(recipes)
    assert len(ingredient_signatures) == len(recipes)
    assert sum(1 for recipe in recipes if recipe.slot == "breakfast") >= 1200
    assert sum(1 for recipe in recipes if recipe.slot == "snack") >= 1000
    assert sum(1 for recipe in recipes if recipe.slot == "main") >= 4000


@pytest.mark.slow_pdf_builder
def test_five_repeat_generations_keep_key_meals_unique() -> None:
    profile = profile_with(weight_kg=75, goal=Goal.GAIN, meal_count=5)
    plans = [build_one_day_plan(profile, variety_seed=seed) for seed in range(5)]

    assert len({plan.meals[0].name for plan in plans}) == 5
    assert len({plan.meals[1].name for plan in plans}) == 5
    assert len({plan.meals[2].name for plan in plans}) == 5
    assert len({tuple(meal.name for meal in plan.meals) for plan in plans}) == 5


@pytest.mark.slow_pdf_builder
def test_repeat_generations_can_avoid_recent_recipe_ids() -> None:
    profile = profile_with(weight_kg=75, goal=Goal.GAIN, meal_count=5)
    avoided_recipe_ids: set[str] = set()
    seen_recipe_ids: set[str] = set()

    for seed in range(8):
        plan = build_one_day_plan(profile, variety_seed=seed, avoided_recipe_ids=avoided_recipe_ids)
        recipe_ids = {meal.recipe_id for meal in plan.meals}

        assert None not in recipe_ids
        assert not recipe_ids & seen_recipe_ids

        avoided_recipe_ids.update(recipe_id for recipe_id in recipe_ids if recipe_id)
        seen_recipe_ids.update(recipe_id for recipe_id in recipe_ids if recipe_id)


@pytest.mark.slow_pdf_builder
def test_repeat_generations_can_avoid_recent_recipe_families() -> None:
    profile = profile_with(weight_kg=75, goal=Goal.GAIN, meal_count=5)
    avoided_recipe_keys: set[str] = set()
    seen_recipe_keys: set[str] = set()

    for seed in range(10):
        plan = build_one_day_plan(profile, variety_seed=seed, avoided_recipe_keys=avoided_recipe_keys)
        recipe_keys = {meal.recipe_key for meal in plan.meals}

        assert None not in recipe_keys
        assert not recipe_keys & seen_recipe_keys

        avoided_recipe_keys.update(recipe_key for recipe_key in recipe_keys if recipe_key)
        seen_recipe_keys.update(recipe_key for recipe_key in recipe_keys if recipe_key)


def test_recipe_plan_has_no_empty_meals_or_placeholder_recipe_text() -> None:
    profile = profile_with(meal_count=5)
    plan = build_one_day_plan(profile)

    assert all(meal.portions for meal in plan.meals)
    text = "\n".join(meal.recipe for meal in plan.meals)
    assert "припустите" not in text
    assert "белковый продукт" not in text


def test_generated_recipe_text_uses_natural_cases() -> None:
    text = "\n".join(recipe.instructions for recipe in built_in_recipes())

    assert "приготовьте индейкой" not in text.lower()
    assert "подготовьте цельнозерновым тостом" not in text.lower()
    assert "добавьте яйцом" not in text.lower()
    assert "добавьте огурцом" not in text.lower()


def test_recipe_plan_includes_usable_image_metadata() -> None:
    profile = profile_with(meal_count=5)
    plan = build_one_day_plan(profile)

    image_meals = [meal for meal in plan.meals if meal.image_url]
    assert image_meals
    for meal in image_meals:
        if meal.image_url.startswith(("http://", "https://")):
            assert meal.source_url
            assert meal.image_attribution
        else:
            assert (DATA_DIR / meal.image_url).exists()


def test_recipe_plan_prefers_vitamin_d_and_omega3_sources() -> None:
    profile = profile_with(meal_count=4)
    plan = build_one_day_plan(profile, variety_seed=0)

    assert plan.totals.get("omega_3_mg") >= plan.targets.targets.get("omega_3_mg")
    assert plan.totals.get("vitamin_d_mcg") > 0


def test_quick_cooking_preference_filters_curated_recipe_times() -> None:
    profile = profile_with(cooking_time=CookingTimePreference.QUICK, meal_count=5)
    plan = build_one_day_plan(profile, variety_seed=1, recipe_source="curated_only")
    recipes_by_id = {recipe.id: recipe for recipe in built_in_recipes()}

    assert len(plan.meals) == 5
    assert {
        _recipe_time_bucket(recipes_by_id[meal.recipe_id])
        for meal in plan.meals
        if meal.recipe_id
    } <= {"quick", "medium"}


def test_curated_only_plan_builds_for_low_protein_maintenance_profile() -> None:
    profile = UserProfile(
        age=30,
        sex=Sex.MALE,
        height_cm=180,
        weight_kg=65,
        goal=Goal.MAINTAIN,
        activity=ActivityLevel.MODERATE,
        meal_count=5,
        cooking_time=CookingTimePreference.QUICK,
    )

    plan = build_one_day_plan(profile, variety_seed=3, recipe_source="curated_only")

    assert len(plan.meals) == 5
    assert all(meal.recipe_id and meal.recipe_id.startswith("r") for meal in plan.meals)
    assert all(meal.image_url and meal.image_url.startswith("recipe_photos/") for meal in plan.meals)
    assert plan.totals.get("protein_g") <= plan.targets.targets.get("protein_g") * 1.50
