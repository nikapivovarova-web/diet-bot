from __future__ import annotations

import pytest

from diet_bot.calculator import calculate_targets
from diet_bot.domain import (
    ActivityLevel,
    CookingTimePreference,
    Food,
    Goal,
    Meal,
    MealPlan,
    NutrientVector,
    SafetyResult,
    Sex,
    UserProfile,
)
from diet_bot.recipe_traits import RecipeTraits
from diet_bot.telegram_app import _select_week_day_plan


def _profile() -> UserProfile:
    return UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.MAINTAIN,
        activity=ActivityLevel.MODERATE,
        meal_count=3,
        cooking_time=CookingTimePreference.SIMPLE,
    )


def _food(food_id: str, energy: float, protein: float = 30, fat: float = 20, carbohydrate: float = 80) -> Food:
    return Food(
        id=food_id,
        name=f"{food_id} food",
        category="test",
        nutrients_per_100g=NutrientVector(
            {
                "energy_kcal": energy,
                "protein_g": protein,
                "fat_g": fat,
                "carbohydrate_g": carbohydrate,
            }
        ),
    )


def _meal(recipe_id: str, food_id: str, energy: float) -> Meal:
    return Meal(
        name=f"meal {recipe_id}",
        portions=(_food(food_id, energy).portion(100),),
        recipe="test recipe",
        recipe_id=recipe_id,
        recipe_key=f"slot:curated:{recipe_id}",
    )


def _plan(profile: UserProfile, recipe_prefix: str, energy: float, food_ids: tuple[str, str, str]) -> MealPlan:
    per_meal_energy = energy / len(food_ids)
    return MealPlan(
        meals=tuple(
            _meal(f"{recipe_prefix}_{index}", food_id, per_meal_energy)
            for index, food_id in enumerate(food_ids)
        ),
        targets=calculate_targets(profile),
        safety=SafetyResult(can_generate_plan=True),
    )


def _patch_day_candidates(monkeypatch: pytest.MonkeyPatch, plans: tuple[MealPlan, ...], *, seed_start: int) -> None:
    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        return plans[variety_seed - seed_start]

    monkeypatch.setattr("diet_bot.telegram_app.build_one_day_plan", day_builder)


def _selected_plan(
    profile: UserProfile,
    *,
    seed: int,
    week_food_ids: set[str],
    week_recipe_ids_for_diversity: set[str] | None = None,
) -> MealPlan:
    plan, carryovers = _select_week_day_plan(
        profile,
        seed,
        set(),
        set(),
        week_food_ids,
        {},
        week_recipe_ids_for_diversity=week_recipe_ids_for_diversity,
    )

    assert carryovers == {}
    return plan


def _recipe_prefixes(plan: MealPlan) -> set[str]:
    return {str(meal.recipe_id).rsplit("_", 1)[0] for meal in plan.meals}


def _traits(recipe_id: str, protein: str, carb: str, recipe_format: str) -> RecipeTraits:
    return RecipeTraits(
        recipe_id=recipe_id,
        recipe_no=None,
        source_batch="test",
        source_tag="test",
        native_slot="main",
        allowed_meal_slots=frozenset({"main"}),
        slot_flex_type="native",
        primary_protein=protein,
        primary_carb=carb,
        recipe_format=recipe_format,
        cooking_effort="simple",
        active_time_bucket="quick",
        main_signal="main",
    )


def test_weekly_selector_prefers_calorie_valid_candidate_over_better_ingredient_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    target_energy = calculate_targets(profile).targets.get("energy_kcal")
    seed = 50
    low_reuse = _plan(
        profile,
        "low_reuse",
        target_energy * 0.88,
        ("shared_food", "shared_food", "shared_food"),
    )
    valid_less_reuse = _plan(
        profile,
        "valid_less_reuse",
        target_energy * 0.94,
        ("valid_a", "valid_b", "valid_c"),
    )
    weaker_candidates = (
        _plan(profile, "weak_1", target_energy * 0.70, ("weak_a", "weak_b", "weak_c")),
        _plan(profile, "weak_2", target_energy * 0.68, ("weak_d", "weak_e", "weak_f")),
    )
    _patch_day_candidates(monkeypatch, (low_reuse, valid_less_reuse, *weaker_candidates), seed_start=seed)

    selected = _selected_plan(profile, seed=seed, week_food_ids={"shared_food"})

    assert _recipe_prefixes(selected) == {"valid_less_reuse"}


def test_weekly_selector_returns_closest_available_candidate_when_none_are_calorie_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    target_energy = calculate_targets(profile).targets.get("energy_kcal")
    seed = 70
    very_low_reuse = _plan(
        profile,
        "very_low_reuse",
        target_energy * 0.82,
        ("shared_food", "shared_food", "shared_food"),
    )
    closest_below_band = _plan(
        profile,
        "closest_below_band",
        target_energy * 0.90,
        ("close_a", "close_b", "close_c"),
    )
    weaker_candidates = (
        _plan(profile, "weak_1", target_energy * 0.78, ("weak_a", "weak_b", "weak_c")),
        _plan(profile, "weak_2", target_energy * 0.76, ("weak_d", "weak_e", "weak_f")),
    )
    _patch_day_candidates(monkeypatch, (very_low_reuse, closest_below_band, *weaker_candidates), seed_start=seed)

    selected = _selected_plan(profile, seed=seed, week_food_ids={"shared_food"})

    assert _recipe_prefixes(selected) == {"closest_below_band"}


def test_weekly_selector_uses_ingredient_reuse_to_break_calorie_ties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    target_energy = calculate_targets(profile).targets.get("energy_kcal")
    seed = 90
    valid_no_reuse = _plan(
        profile,
        "valid_no_reuse",
        target_energy * 0.96,
        ("new_a", "new_b", "new_c"),
    )
    valid_reuse = _plan(
        profile,
        "valid_reuse",
        target_energy * 0.96,
        ("shared_food", "shared_food", "shared_food"),
    )
    weaker_candidates = (
        _plan(profile, "weak_1", target_energy * 0.80, ("weak_a", "weak_b", "weak_c")),
        _plan(profile, "weak_2", target_energy * 0.78, ("weak_d", "weak_e", "weak_f")),
    )
    _patch_day_candidates(monkeypatch, (valid_no_reuse, valid_reuse, *weaker_candidates), seed_start=seed)

    selected = _selected_plan(profile, seed=seed, week_food_ids={"shared_food"})

    assert _recipe_prefixes(selected) == {"valid_reuse"}


def test_weekly_selector_prefers_less_repeated_traits_before_ingredient_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    target_energy = calculate_targets(profile).targets.get("energy_kcal")
    seed = 120
    repeated_traits_better_reuse = _plan(
        profile,
        "repeated_traits",
        target_energy * 0.96,
        ("shared_food", "shared_food", "shared_food"),
    )
    fresh_traits_less_reuse = _plan(
        profile,
        "fresh_traits",
        target_energy * 0.96,
        ("fresh_a", "fresh_b", "fresh_c"),
    )
    weaker_candidates = (
        _plan(profile, "weak_1", target_energy * 0.80, ("weak_a", "weak_b", "weak_c")),
        _plan(profile, "weak_2", target_energy * 0.78, ("weak_d", "weak_e", "weak_f")),
    )
    trait_map = {
        "week_anchor": _traits("week_anchor", "fish", "rice", "bowl"),
        **{
            f"repeated_traits_{index}": _traits(f"repeated_traits_{index}", "fish", "rice", "bowl")
            for index in range(3)
        },
        **{
            f"fresh_traits_{index}": _traits(f"fresh_traits_{index}", "poultry", "potato", "skillet")
            for index in range(3)
        },
    }
    _patch_day_candidates(
        monkeypatch,
        (repeated_traits_better_reuse, fresh_traits_less_reuse, *weaker_candidates),
        seed_start=seed,
    )
    monkeypatch.setattr("diet_bot.telegram_app._recipe_traits_by_id", lambda: trait_map, raising=False)

    selected = _selected_plan(
        profile,
        seed=seed,
        week_food_ids={"shared_food"},
        week_recipe_ids_for_diversity={"week_anchor"},
    )

    assert _recipe_prefixes(selected) == {"fresh_traits"}
