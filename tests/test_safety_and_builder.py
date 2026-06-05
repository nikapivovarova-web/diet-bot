from collections import Counter
from dataclasses import replace
from pathlib import Path
import time

import pytest

from diet_bot import builder
from diet_bot.builder import _meal_energy_slots, _recipe_time_bucket, build_one_day_plan, filter_foods
from diet_bot import telegram_app
from diet_bot.catalog import built_in_foods
from diet_bot.domain import (
    ActivityLevel,
    ConditionCode,
    CookingTimePreference,
    Food,
    FoodPortion,
    Goal,
    Meal,
    MealPlan,
    NutritionTargets,
    NutrientVector,
    Restriction,
    RestrictionType,
    SafetyResult,
    Sex,
    UserProfile,
)
from diet_bot.recipe_catalog import RecipeTemplate, built_in_recipes
from diet_bot.safety import evaluate_safety
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


def _empty_recent_avoidance() -> telegram_app._RecentRecipeAvoidance:
    return telegram_app._RecentRecipeAvoidance(
        full_recipe_ids=frozenset(),
        full_recipe_keys=frozenset(),
        reduced_recipe_ids=frozenset(),
        reduced_recipe_keys=frozenset(),
    )


def constrained_weekly_profile(*excluded_foods: str) -> UserProfile:
    return profile_with(
        age=32,
        sex=Sex.FEMALE,
        height_cm=168,
        weight_kg=72,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=4,
        cooking_time=CookingTimePreference.SIMPLE,
        restrictions=tuple(
            Restriction(RestrictionType.EXCLUDED_FOOD, food)
            for food in excluded_foods
        ),
    )


def _weekly_recipe_ids(plans) -> list[str]:
    return [
        meal.recipe_id
        for plan in plans
        for meal in plan.meals
        if meal.recipe_id
    ]


def _weekly_repeat_count(plans) -> int:
    return sum(
        count - 1
        for count in Counter(_weekly_recipe_ids(plans)).values()
        if count > 1
    )


def _weekly_max_repeat(plans) -> int:
    counts = Counter(_weekly_recipe_ids(plans))
    return max(counts.values()) if counts else 0


def _assert_no_excluded_foods_in_week(plans, profile: UserProfile) -> None:
    eligible_ids = {
        food.id
        for food in filter_foods(built_in_foods(), evaluate_safety(profile))
    }
    planned_ids = {
        portion.food.id
        for plan in plans
        for meal in plan.meals
        for portion in meal.portions
    }

    assert planned_ids <= eligible_ids


def _test_recipe_template(recipe_id: str) -> RecipeTemplate:
    return RecipeTemplate(
        id=recipe_id,
        slot="main",
        title=recipe_id,
        ingredients_g={},
        instructions="cook",
    )


def _synthetic_repeat_plan(recipe_ids: tuple[str, str, str]) -> MealPlan:
    targets = NutritionTargets(
        bmi=24.0,
        bmi_category="normal",
        bmr_kcal=1500.0,
        tdee_kcal=2000.0,
        water_l=2.0,
        targets=NutrientVector(
            {
                "energy_kcal": 1800.0,
                "protein_g": 90.0,
                "sodium_mg": 2300.0,
            }
        ),
        calorie_bounds=(1600.0, 2000.0),
        macro_bounds={"protein_g": (72.0, 140.0)},
    )
    safety = SafetyResult(can_generate_plan=True)
    meals: list[Meal] = []
    for meal_index, recipe_id in enumerate(recipe_ids):
        food = Food(
            id=f"food_{recipe_id}",
            name=f"food {recipe_id}",
            category="test",
            nutrients_per_100g=NutrientVector(
                {
                    "energy_kcal": 600.0,
                    "protein_g": 30.0,
                    "sodium_mg": 100.0,
                }
            ),
            max_per_meal_g=200.0,
            max_per_day_g=400.0,
        )
        meals.append(
            Meal(
                name=f"meal {meal_index}",
                portions=(FoodPortion(food=food, grams=100.0),),
                recipe="cook",
                recipe_id=recipe_id,
                recipe_key=recipe_id,
            )
        )
    return MealPlan(meals=tuple(meals), targets=targets, safety=safety)


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


def test_weekly_repeats_fallback_ranks_sodium_valid_combo_ahead_of_high_sodium_combo() -> None:
    high_sodium = _test_recipe_template("high_sodium")
    sodium_valid = _test_recipe_template("sodium_valid")
    lunch = _test_recipe_template("lunch")
    dinner = _test_recipe_template("dinner")
    target = NutrientVector(
        {
            "protein_g": 90.0,
            "energy_kcal": 1800.0,
            "sodium_mg": 2300.0,
        }
    )

    diagnostics = telegram_app._weekly_repeat_fallback_ranked_combinations_with_diagnostics(
        (
            (
                telegram_app._WeeklyRepeatFallbackFastOption(
                    recipe=high_sodium,
                    estimated_protein_g=30.0,
                    estimated_energy_kcal=600.0,
                    estimated_sodium_mg=2300.0,
                ),
                telegram_app._WeeklyRepeatFallbackFastOption(
                    recipe=sodium_valid,
                    estimated_protein_g=28.0,
                    estimated_energy_kcal=590.0,
                    estimated_sodium_mg=100.0,
                ),
            ),
            (
                telegram_app._WeeklyRepeatFallbackFastOption(
                    recipe=lunch,
                    estimated_protein_g=30.0,
                    estimated_energy_kcal=600.0,
                    estimated_sodium_mg=100.0,
                ),
            ),
            (
                telegram_app._WeeklyRepeatFallbackFastOption(
                    recipe=dinner,
                    estimated_protein_g=30.0,
                    estimated_energy_kcal=600.0,
                    estimated_sodium_mg=100.0,
                ),
            ),
        ),
        _meal_energy_slots(3),
        target,
        Counter(),
        frozenset(),
    )
    ranked = diagnostics.combinations

    assert diagnostics.has_sodium_valid_combo is True
    assert tuple(recipe.id for recipe in ranked[0]) == ("sodium_valid", "lunch", "dinner")


def test_weekly_no_dairy_meat_fish_uses_repeats_fallback_without_excluded_foods(monkeypatch) -> None:
    profile = constrained_weekly_profile("dairy", "meat", "fish")
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS", 30.0, raising=False)

    started_at = time.perf_counter()
    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        607,
        _empty_recent_avoidance(),
    )
    elapsed_s = time.perf_counter() - started_at

    assert telegram_app._week_plans_are_complete(result.plans, profile)
    assert result.avoidance_phase == "repeats_fallback"
    assert result.repeat_fallback_used is True
    assert result.repeat_note
    assert elapsed_s < telegram_app.WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS
    assert _weekly_repeat_count(result.plans) > 0
    _assert_no_excluded_foods_in_week(result.plans, profile)
    assert all(validate_plan(plan).ok for plan in result.plans)


def test_c01_weekly_no_dairy_meat_fish_seed_607_passes_sodium_with_production_timeouts() -> None:
    profile = profile_with(
        age=32,
        sex=Sex.FEMALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=4,
        cooking_time=CookingTimePreference.SIMPLE,
        restrictions=(
            Restriction(RestrictionType.EXCLUDED_FOOD, "dairy"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "meat"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "fish"),
        ),
    )

    started_at = time.perf_counter()
    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        607,
        _empty_recent_avoidance(),
    )
    elapsed_s = time.perf_counter() - started_at

    assert telegram_app._week_plans_are_complete(result.plans, profile)
    assert result.avoidance_phase == "repeats_fallback"
    assert result.repeat_fallback_used is True
    assert elapsed_s < telegram_app.WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS
    targets = result.plans[0].targets.targets
    assert targets.get("energy_kcal") == 2176
    assert targets.get("protein_g") == 138
    assert targets.get("sodium_mg") == 2300
    _assert_no_excluded_foods_in_week(result.plans, profile)
    assert all(validate_plan(plan).ok for plan in result.plans)
    assert all(plan.totals.get("sodium_mg") <= 2300.01 for plan in result.plans)
    assert _weekly_max_repeat(result.plans) <= 3


def test_c05_weekly_no_meat_fish_seed_607_uses_no_recent_when_pool_is_sufficient(
    monkeypatch,
) -> None:
    profile = constrained_weekly_profile("meat", "fish")
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS", 120.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS", 150.0, raising=False)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        607,
        _empty_recent_avoidance(),
    )

    assert len(result.plans) == 7
    assert telegram_app._week_plans_are_complete(result.plans, profile)
    assert result.avoidance_phase == "no_recent"
    assert result.repeat_fallback_used is False
    assert sum(len(plan.meals) for plan in result.plans) == 28
    assert len(set(_weekly_recipe_ids(result.plans))) == 28
    _assert_no_excluded_foods_in_week(result.plans, profile)
    assert all(validate_plan(plan).ok for plan in result.plans)
    assert all(plan.totals.get("sodium_mg") <= 2300.01 for plan in result.plans)
    assert _weekly_max_repeat(result.plans) <= 2


def test_c05_no_recent_fallback_allows_near_threshold_main_pool(
    monkeypatch,
) -> None:
    profile = constrained_weekly_profile("meat", "fish")

    def feasible_near_threshold(*args, **kwargs):
        return telegram_app._WeeklyPhaseFeasibility(
            skipped=False,
            reason="feasible",
            slot_counts=(
                telegram_app._WeeklyPhaseSlotFeasibility(
                    slot="main",
                    weekly_required=14,
                    available_count=60,
                    strict_simple_count=44,
                    threshold=42,
                ),
            ),
        )

    monkeypatch.setattr(telegram_app, "_weekly_phase_feasibility", feasible_near_threshold)

    reason = telegram_app._weekly_no_recent_repeat_fallback_reason(
        profile,
        recipe_cache=telegram_app._RecipePlanCache(),
    )

    assert reason is None


def test_c01_no_recent_fallback_still_treats_below_threshold_main_pool_as_constrained(
    monkeypatch,
) -> None:
    profile = constrained_weekly_profile("dairy", "meat", "fish")

    def feasible_near_threshold(*args, **kwargs):
        return telegram_app._WeeklyPhaseFeasibility(
            skipped=False,
            reason="feasible",
            slot_counts=(
                telegram_app._WeeklyPhaseSlotFeasibility(
                    slot="main",
                    weekly_required=14,
                    available_count=19,
                    strict_simple_count=19,
                    threshold=42,
                ),
            ),
        )

    monkeypatch.setattr(telegram_app, "_weekly_phase_feasibility", feasible_near_threshold)

    reason = telegram_app._weekly_no_recent_repeat_fallback_reason(
        profile,
        recipe_cache=telegram_app._RecipePlanCache(),
    )

    assert reason == "repeat_fallback_slot_pool_below_threshold:main:19<42"


def test_c00_public_weekly_seed_607_stays_sodium_valid() -> None:
    profile = profile_with(
        age=32,
        sex=Sex.FEMALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=4,
        cooking_time=CookingTimePreference.SIMPLE,
    )

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        607,
        _empty_recent_avoidance(),
    )

    assert len(result.plans) == 7
    for plan in result.plans:
        assert validate_plan(plan).ok
        assert plan.totals.get("sodium_mg") <= 2300.01


def test_builder_enables_sodium_management_when_target_has_sodium(monkeypatch) -> None:
    captured_manage_sodium: list[bool] = []

    def capture_recipe_path(*args, **kwargs):
        captured_manage_sodium.append(kwargs["manage_sodium"])
        raise RuntimeError("captured manage_sodium")

    monkeypatch.setattr(builder, "_build_recipe_plan_for_time", capture_recipe_path)

    with pytest.raises(RuntimeError, match="captured manage_sodium"):
        build_one_day_plan(profile_with(restrictions=()))

    assert captured_manage_sodium == [True]


@pytest.mark.parametrize(
    "synthetic_target",
    (
        NutrientVector({"energy_kcal": 1800.0, "protein_g": 90.0}),
        NutrientVector({"energy_kcal": 1800.0, "protein_g": 90.0, "sodium_mg": 0.0}),
    ),
)
def test_builder_keeps_sodium_management_disabled_without_sodium_target(
    monkeypatch,
    synthetic_target: NutrientVector,
) -> None:
    captured_manage_sodium: list[bool] = []

    def fake_targets(profile: UserProfile) -> NutritionTargets:
        return NutritionTargets(
            bmi=24.0,
            bmi_category="normal",
            bmr_kcal=1500.0,
            tdee_kcal=2000.0,
            water_l=2.0,
            targets=synthetic_target,
            calorie_bounds=(1600.0, 2000.0),
            macro_bounds={},
        )

    def capture_recipe_path(*args, **kwargs):
        captured_manage_sodium.append(kwargs["manage_sodium"])
        raise RuntimeError("captured manage_sodium")

    monkeypatch.setattr(builder, "calculate_targets", fake_targets)
    monkeypatch.setattr(builder, "_build_recipe_plan_for_time", capture_recipe_path)

    with pytest.raises(RuntimeError, match="captured manage_sodium"):
        build_one_day_plan(profile_with(restrictions=()))

    assert captured_manage_sodium == [False]


def test_weekly_no_meat_fish_falls_back_after_no_recent_timeout(monkeypatch) -> None:
    profile = constrained_weekly_profile("meat", "fish")
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS", 45.0, raising=False)

    started_at = time.perf_counter()
    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        607,
        _empty_recent_avoidance(),
    )
    elapsed_s = time.perf_counter() - started_at
    recipe_counts = Counter(_weekly_recipe_ids(result.plans))

    assert telegram_app._week_plans_are_complete(result.plans, profile)
    assert result.avoidance_phase == "repeats_fallback"
    assert result.repeat_fallback_used is True
    assert result.repeat_recipe_count == _weekly_repeat_count(result.plans)
    assert _weekly_repeat_count(result.plans) <= 18
    assert len(recipe_counts) >= 10
    assert max(recipe_counts.values()) <= 3
    assert elapsed_s < telegram_app.WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS
    _assert_no_excluded_foods_in_week(result.plans, profile)


def test_weekly_repeats_fallback_keeps_constrained_repeats_bounded(monkeypatch) -> None:
    profile = constrained_weekly_profile("dairy", "meat", "fish")
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS", 30.0, raising=False)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        607,
        _empty_recent_avoidance(),
    )
    recipe_counts = Counter(_weekly_recipe_ids(result.plans))

    assert telegram_app._week_plans_are_complete(result.plans, profile)
    assert result.repeat_fallback_used is True
    assert result.repeat_recipe_count == _weekly_repeat_count(result.plans)
    assert 0 < _weekly_repeat_count(result.plans) <= 20
    assert max(recipe_counts.values()) <= telegram_app.WEEK_PLAN_DAYS
    assert len(recipe_counts) >= 8


def test_weekly_repeat_optimizer_uses_cap_three_when_it_is_feasible() -> None:
    profile = profile_with(meal_count=3)
    day_pool = (
        _synthetic_repeat_plan(("a1", "a2", "a3")),
        _synthetic_repeat_plan(("b1", "b2", "b3")),
        _synthetic_repeat_plan(("c1", "c2", "c3")),
    )

    scheduled = telegram_app._optimize_weekly_repeat_fallback_schedule(
        day_pool,
        profile,
    )

    assert len(scheduled) == 7
    assert all(validate_plan(plan).ok for plan in scheduled)
    assert _weekly_max_repeat(scheduled) <= 3


def test_weekly_repeat_fallback_skips_narrow_slots_pool_when_builder_can_cap_three(
    monkeypatch,
) -> None:
    profile = replace(constrained_weekly_profile("meat", "fish"), meal_count=3)
    slots_pool = (_synthetic_repeat_plan(("slot1", "slot2", "slot3")),)
    builder_pool = (
        _synthetic_repeat_plan(("a1", "a2", "a3")),
        _synthetic_repeat_plan(("b1", "b2", "b3")),
        _synthetic_repeat_plan(("c1", "c2", "c3")),
    )
    calls: list[str] = []

    def fake_slots(*args, **kwargs):
        calls.append("slots")
        return slots_pool, None

    def fake_builder(*args, **kwargs):
        calls.append("builder")
        return builder_pool, None

    monkeypatch.setattr(
        telegram_app,
        "_build_weekly_repeat_fallback_day_pool_from_slots",
        fake_slots,
    )
    monkeypatch.setattr(
        telegram_app,
        "_build_weekly_repeat_fallback_day_pool_from_builder",
        fake_builder,
    )

    selected_pool, failure_reason = telegram_app._build_weekly_repeat_fallback_day_pool(
        profile,
        607,
        recipe_cache=telegram_app._RecipePlanCache(),
    )

    assert calls == ["slots", "builder"]
    assert failure_reason is None
    assert selected_pool == builder_pool
    scheduled = telegram_app._optimize_weekly_repeat_fallback_schedule(
        selected_pool,
        profile,
    )
    assert _weekly_max_repeat(scheduled) <= 3


def test_weekly_baseline_and_single_exclusions_stay_low_repeat(monkeypatch) -> None:
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS", 90.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS", 120.0, raising=False)
    cases = (
        (),
        ("fish",),
        ("dairy",),
        ("meat",),
    )

    for exclusions in cases:
        profile = constrained_weekly_profile(*exclusions)
        result = telegram_app._build_week_plans_with_recent_fallback(
            profile,
            607,
            _empty_recent_avoidance(),
        )

        assert telegram_app._week_plans_are_complete(result.plans, profile)
        assert _weekly_repeat_count(result.plans) <= 1
        _assert_no_excluded_foods_in_week(result.plans, profile)


def test_weekly_impossible_profile_returns_structured_failure() -> None:
    profile = constrained_weekly_profile("dairy", "meat", "fish")
    profile = replace(profile, age=17)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        607,
        _empty_recent_avoidance(),
    )

    assert result.plans == ()
    assert result.avoidance_phase == "failed"
    assert result.failure_reason == "safety_cannot_generate"
    assert result.repeat_fallback_used is False


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


def test_five_repeat_generations_keep_key_meals_unique() -> None:
    profile = profile_with(weight_kg=75, goal=Goal.GAIN, meal_count=5)
    plans = [build_one_day_plan(profile, variety_seed=seed) for seed in range(5)]

    assert len({plan.meals[0].name for plan in plans}) == 5
    assert len({plan.meals[1].name for plan in plans}) == 5
    assert len({plan.meals[2].name for plan in plans}) == 5
    assert len({tuple(meal.name for meal in plan.meals) for plan in plans}) == 5


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
