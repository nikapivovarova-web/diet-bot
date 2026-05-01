from diet_bot.builder import build_one_day_plan, filter_foods
from diet_bot.catalog import built_in_foods
from diet_bot.domain import (
    ActivityLevel,
    ConditionCode,
    Goal,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
)
from diet_bot.safety import evaluate_safety
from diet_bot.validation import validate_plan


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


def test_apple_allergy_excludes_apple() -> None:
    profile = profile_with(restrictions=(Restriction(RestrictionType.ALLERGY, "яблоко"),))
    plan = build_one_day_plan(profile)

    assert "яблоко" not in food_names(plan)
    assert validate_plan(plan).ok


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


def test_gain_plan_stays_close_to_calorie_target() -> None:
    profile = profile_with(weight_kg=75, goal=Goal.GAIN)
    plan = build_one_day_plan(profile)

    assert plan.totals.get("energy_kcal") >= plan.targets.targets.get("energy_kcal") * 0.96


def test_repeat_generation_changes_recipes() -> None:
    profile = profile_with(weight_kg=75, goal=Goal.GAIN, meal_count=5)
    first = build_one_day_plan(profile, variety_seed=0)
    second = build_one_day_plan(profile, variety_seed=1)

    first_names = {meal.name for meal in first.meals}
    second_names = {meal.name for meal in second.meals}
    assert first_names != second_names


def test_recipe_plan_has_no_empty_meals_or_placeholder_recipe_text() -> None:
    profile = profile_with(meal_count=5)
    plan = build_one_day_plan(profile)

    assert all(meal.portions for meal in plan.meals)
    text = "\n".join(meal.recipe for meal in plan.meals)
    assert "припустите" not in text
    assert "белковый продукт" not in text


def test_recipe_plan_includes_open_license_image_metadata() -> None:
    profile = profile_with(meal_count=5)
    plan = build_one_day_plan(profile)

    image_meals = [meal for meal in plan.meals if meal.image_url]
    assert image_meals
    assert all("wikimedia" in (meal.source_url or "") for meal in image_meals)
    assert all(meal.image_attribution for meal in image_meals)


def test_recipe_plan_prefers_vitamin_d_and_omega3_sources() -> None:
    profile = profile_with(meal_count=4)
    plan = build_one_day_plan(profile, variety_seed=0)

    assert plan.totals.get("omega_3_mg") >= plan.targets.targets.get("omega_3_mg")
    assert plan.totals.get("vitamin_d_mcg") > 0
