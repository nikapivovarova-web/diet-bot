from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

import diet_bot.builder as builder
import diet_bot.telegram_app as telegram_app
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
from diet_bot.recipe_catalog import RecipeTemplate
from diet_bot.recipe_traits import RecipeTraits
from diet_bot.telegram_app import WEEK_PLAN_CANDIDATE_COUNT, _select_week_day_plan
from diet_bot.validation import validate_plan


_WeeklySignature = tuple[
    tuple[tuple[str | None, ...], tuple[str | None, ...], tuple[float, ...]],
    ...,
]


def _profile(*, meal_count: int = 3) -> UserProfile:
    return UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.MAINTAIN,
        activity=ActivityLevel.MODERATE,
        meal_count=meal_count,
        cooking_time=CookingTimePreference.SIMPLE,
    )


def _food(food_id: str, energy: float, protein: float = 20, fat: float = 20, carbohydrate: float = 80) -> Food:
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


def _plan(profile: UserProfile, recipe_prefix: str, energy: float, food_ids: tuple[str, ...]) -> MealPlan:
    per_meal_energy = energy / len(food_ids)
    return MealPlan(
        meals=tuple(
            _meal(f"{recipe_prefix}_{index}", food_id, per_meal_energy)
            for index, food_id in enumerate(food_ids)
        ),
        targets=calculate_targets(profile),
        safety=SafetyResult(can_generate_plan=True),
    )


def _empty_plan(profile: UserProfile) -> MealPlan:
    return MealPlan(
        meals=(),
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


def _weekly_signature(
    plans: tuple[MealPlan, ...],
) -> _WeeklySignature:
    nutrient_keys = ("energy_kcal", "protein_g", "fat_g", "carbohydrate_g")
    return tuple(
        (
            tuple(meal.recipe_id for meal in plan.meals),
            tuple(meal.recipe_key for meal in plan.meals),
            tuple(round(plan.totals.get(key), 6) for key in nutrient_keys),
        )
        for plan in plans
    )


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


def _recipe_template(recipe_id: str, slot: str) -> RecipeTemplate:
    return RecipeTemplate(
        id=recipe_id,
        slot=slot,
        title=f"{slot} recipe {recipe_id}",
        ingredients_g={"egg": 100},
        instructions="Cook gently.",
        tags=frozenset({"curated"}),
        cooking_effort="simple",
        active_time_min=10,
    )


def _recipes_for_feasibility_pool(
    *,
    breakfast_count: int,
    main_count: int,
    snack_count: int = 0,
) -> tuple[RecipeTemplate, ...]:
    return (
        tuple(
            _recipe_template(f"pool_breakfast_{index}", "breakfast")
            for index in range(breakfast_count)
        )
        + tuple(_recipe_template(f"pool_main_{index}", "main") for index in range(main_count))
        + tuple(
            _recipe_template(f"pool_snack_{index}", "snack")
            for index in range(snack_count)
        )
    )


def _complete_week(profile: UserProfile, prefix: str = "week") -> tuple[MealPlan, ...]:
    target_energy = calculate_targets(profile).targets.get("energy_kcal")
    return tuple(
        _plan(
            profile,
            f"{prefix}_{day_index}",
            target_energy,
            tuple(
                f"{prefix}_{day_index}_{meal_index}"
                for meal_index in range(profile.meal_count)
            ),
        )
        for day_index in range(telegram_app.WEEK_PLAN_DAYS)
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


def test_scoped_weekly_trait_lookup_preserves_weekly_plan_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    target_energy = calculate_targets(profile).targets.get("energy_kcal")
    seed = 310
    candidates_by_seed: dict[int, MealPlan] = {}
    trait_map: dict[str, RecipeTraits] = {}
    proteins = ("fish", "poultry", "egg", "plant_protein")
    carbs = ("rice", "potato", "bread", "grain")
    formats = ("bowl", "skillet", "wrap", "salad")

    for day_index in range(telegram_app.WEEK_PLAN_DAYS):
        for candidate_index in range(WEEK_PLAN_CANDIDATE_COUNT):
            plan_seed = seed + day_index * WEEK_PLAN_CANDIDATE_COUNT + candidate_index
            prefix = f"day{day_index}_candidate{candidate_index}"
            plan = _plan(
                profile,
                prefix,
                target_energy * (0.94 + candidate_index * 0.005),
                (
                    f"food_{day_index}_{candidate_index}_a",
                    f"food_{day_index}_{candidate_index}_b",
                    f"food_{day_index}_{candidate_index}_c",
                ),
            )
            candidates_by_seed[plan_seed] = plan
            for meal_index, meal in enumerate(plan.meals):
                recipe_id = str(meal.recipe_id)
                trait_map[recipe_id] = _traits(
                    recipe_id,
                    proteins[(day_index + candidate_index + meal_index) % len(proteins)],
                    carbs[(day_index + candidate_index + meal_index) % len(carbs)],
                    formats[(day_index + candidate_index + meal_index) % len(formats)],
                )

    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        return candidates_by_seed[variety_seed]

    monkeypatch.setattr(telegram_app, "build_one_day_plan", day_builder)
    monkeypatch.setattr(telegram_app, "_recipe_traits_by_id", lambda: trait_map, raising=False)

    baseline = telegram_app._build_week_plans(
        profile,
        seed,
        set(),
        set(),
        recipe_trait_lookup=trait_map,
    )
    scoped_lookup = telegram_app._WeeklyRecipeTraitLookup.from_traits(trait_map)
    scoped = telegram_app._build_week_plans(
        profile,
        seed,
        set(),
        set(),
        recipe_trait_lookup=scoped_lookup,
    )

    assert _weekly_signature(scoped) == _weekly_signature(baseline)
    assert scoped_lookup.stats["weekly_trait_lookup_hits"] > 0
    assert scoped_lookup.stats["weekly_trait_lookup_misses"] > 0


def test_build_one_day_plan_checks_selection_guard_before_heavy_candidate_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()

    class GuardTrip(RuntimeError):
        pass

    class Guard:
        def __init__(self) -> None:
            self.stages: list[str] = []

        def check(self, *, stage: str, **_kwargs: object) -> None:
            self.stages.append(stage)
            if stage == "before_ranking_mode":
                raise GuardTrip(stage)

    def fail_if_heavy_candidate_runs(*_args: object, **_kwargs: object) -> list[Meal]:
        raise AssertionError("selection guard should run before heavy candidate work")

    guard = Guard()
    monkeypatch.setattr(builder, "_build_recipe_plan", fail_if_heavy_candidate_runs)

    with pytest.raises(GuardTrip):
        builder.build_one_day_plan(
            profile,
            variety_seed=101,
            recipe_source="curated_only",
            selection_guard=guard,
        )

    assert "before_ranking_mode" in guard.stages


def test_recent_phase_with_insufficient_slot_pool_is_skipped_before_week_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    recipes = tuple(
        _recipe_template(f"thin_breakfast_{index}", "breakfast")
        for index in range(21)
    ) + tuple(_recipe_template(f"thin_main_{index}", "main") for index in range(42))
    build_calls: list[str] = []

    def week_builder(
        profile: UserProfile,
        seed: int,
        avoided_recipe_ids: set[str],
        avoided_recipe_keys: set[str],
        *,
        selection_phase: str,
        **_kwargs: object,
    ) -> tuple[MealPlan, ...]:
        del seed, avoided_recipe_ids, avoided_recipe_keys
        build_calls.append(selection_phase)
        if selection_phase == "full_recent":
            raise AssertionError("hopeless recent phase should be skipped before week build")
        return _complete_week(profile, "no_recent")

    monkeypatch.setattr(telegram_app, "built_in_recipes", lambda: recipes)
    monkeypatch.setattr(telegram_app, "_build_week_plans", week_builder)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        910,
        telegram_app._RecentRecipeAvoidance(
            full_recipe_ids=frozenset({"recent_recipe"}),
            full_recipe_keys=frozenset(),
            reduced_recipe_ids=frozenset(),
            reduced_recipe_keys=frozenset(),
        ),
    )

    assert result.avoidance_phase == "no_recent"
    assert build_calls == ["no_recent"]


def test_recent_phase_with_feasible_slot_pool_is_not_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    recipes = tuple(
        _recipe_template(f"wide_breakfast_{index}", "breakfast")
        for index in range(55)
    ) + tuple(_recipe_template(f"wide_main_{index}", "main") for index in range(105))
    build_calls: list[str] = []

    def week_builder(
        profile: UserProfile,
        seed: int,
        avoided_recipe_ids: set[str],
        avoided_recipe_keys: set[str],
        *,
        selection_phase: str,
        **_kwargs: object,
    ) -> tuple[MealPlan, ...]:
        del seed, avoided_recipe_ids, avoided_recipe_keys
        build_calls.append(selection_phase)
        return _complete_week(profile, selection_phase)

    monkeypatch.setattr(telegram_app, "built_in_recipes", lambda: recipes)
    monkeypatch.setattr(telegram_app, "_build_week_plans", week_builder)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        930,
        telegram_app._RecentRecipeAvoidance(
            full_recipe_ids=frozenset({"recent_recipe"}),
            full_recipe_keys=frozenset(),
            reduced_recipe_ids=frozenset(),
            reduced_recipe_keys=frozenset(),
        ),
    )

    assert result.avoidance_phase == "full_recent"
    assert build_calls == ["full_recent"]


def test_recent_phase_with_pool_above_five_week_buffer_below_seven_is_not_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile(meal_count=5)
    recipes = _recipes_for_feasibility_pool(
        breakfast_count=98,
        main_count=98,
        snack_count=75,
    )
    build_calls: list[str] = []

    def week_builder(
        profile: UserProfile,
        seed: int,
        avoided_recipe_ids: set[str],
        avoided_recipe_keys: set[str],
        *,
        selection_phase: str,
        **_kwargs: object,
    ) -> tuple[MealPlan, ...]:
        del seed, avoided_recipe_ids, avoided_recipe_keys
        build_calls.append(selection_phase)
        return _complete_week(profile, selection_phase)

    monkeypatch.setattr(telegram_app, "built_in_recipes", lambda: recipes)
    monkeypatch.setattr(telegram_app, "_build_week_plans", week_builder)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        940,
        telegram_app._RecentRecipeAvoidance(
            full_recipe_ids=frozenset({"recent_recipe"}),
            full_recipe_keys=frozenset(),
            reduced_recipe_ids=frozenset(),
            reduced_recipe_keys=frozenset(),
        ),
    )

    assert result.avoidance_phase == "full_recent"
    assert build_calls == ["full_recent"]


def test_recent_phase_with_pool_at_exact_five_week_buffer_is_not_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile(meal_count=5)
    snack_weekly_required = 14
    snack_threshold = (
        snack_weekly_required
        * telegram_app.WEEKLY_RECENT_FEASIBILITY_POOL_MULTIPLIER
    )
    recipes = _recipes_for_feasibility_pool(
        breakfast_count=98,
        main_count=98,
        snack_count=snack_threshold,
    )
    build_calls: list[str] = []

    def week_builder(
        profile: UserProfile,
        seed: int,
        avoided_recipe_ids: set[str],
        avoided_recipe_keys: set[str],
        *,
        selection_phase: str,
        **_kwargs: object,
    ) -> tuple[MealPlan, ...]:
        del seed, avoided_recipe_ids, avoided_recipe_keys
        build_calls.append(selection_phase)
        return _complete_week(profile, selection_phase)

    assert snack_threshold == 70

    monkeypatch.setattr(telegram_app, "built_in_recipes", lambda: recipes)
    monkeypatch.setattr(telegram_app, "_build_week_plans", week_builder)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        945,
        telegram_app._RecentRecipeAvoidance(
            full_recipe_ids=frozenset({"recent_recipe"}),
            full_recipe_keys=frozenset(),
            reduced_recipe_ids=frozenset(),
            reduced_recipe_keys=frozenset(),
        ),
    )

    assert result.avoidance_phase == "full_recent"
    assert build_calls == ["full_recent"]


def test_recent_phase_with_pool_below_five_week_buffer_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile(meal_count=5)
    recipes = _recipes_for_feasibility_pool(
        breakfast_count=98,
        main_count=98,
        snack_count=69,
    )
    build_calls: list[str] = []

    def week_builder(
        profile: UserProfile,
        seed: int,
        avoided_recipe_ids: set[str],
        avoided_recipe_keys: set[str],
        *,
        selection_phase: str,
        **_kwargs: object,
    ) -> tuple[MealPlan, ...]:
        del seed, avoided_recipe_ids, avoided_recipe_keys
        build_calls.append(selection_phase)
        if selection_phase == "full_recent":
            raise AssertionError("slot pool below five-week buffer should be skipped")
        return _complete_week(profile, "no_recent")

    monkeypatch.setattr(telegram_app, "built_in_recipes", lambda: recipes)
    monkeypatch.setattr(telegram_app, "_build_week_plans", week_builder)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        950,
        telegram_app._RecentRecipeAvoidance(
            full_recipe_ids=frozenset({"recent_recipe"}),
            full_recipe_keys=frozenset(),
            reduced_recipe_ids=frozenset(),
            reduced_recipe_keys=frozenset(),
        ),
    )

    assert result.avoidance_phase == "no_recent"
    assert build_calls == ["no_recent"]


def test_non_empty_recent_history_skips_no_recent_when_pool_below_repeat_fallback_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    recipes = _recipes_for_feasibility_pool(
        breakfast_count=21,
        main_count=41,
    )
    fallback_reasons: list[str | None] = []

    def week_builder(
        profile: UserProfile,
        seed: int,
        avoided_recipe_ids: set[str],
        avoided_recipe_keys: set[str],
        *,
        selection_phase: str,
        **_kwargs: object,
    ) -> tuple[MealPlan, ...]:
        del profile, seed, avoided_recipe_ids, avoided_recipe_keys
        raise AssertionError(f"{selection_phase} should be skipped before week build")

    def repeats_fallback(
        profile: UserProfile,
        seed: int,
        **kwargs: object,
    ) -> telegram_app._WeekPlanBuildResult:
        del seed
        fallback_reasons.append(kwargs.get("failure_reason"))
        return telegram_app._WeekPlanBuildResult(
            plans=_complete_week(profile, "fallback"),
            avoidance_phase="repeats_fallback",
            repeat_fallback_used=True,
            failure_reason=kwargs.get("failure_reason"),
        )

    monkeypatch.setattr(telegram_app, "built_in_recipes", lambda: recipes)
    monkeypatch.setattr(telegram_app, "_build_week_plans", week_builder)
    monkeypatch.setattr(telegram_app, "_build_week_plans_with_repeats_fallback", repeats_fallback)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        955,
        telegram_app._RecentRecipeAvoidance(
            full_recipe_ids=frozenset({"recent_recipe"}),
            full_recipe_keys=frozenset(),
            reduced_recipe_ids=frozenset({"less_recent_recipe"}),
            reduced_recipe_keys=frozenset(),
        ),
    )

    assert result.avoidance_phase == "repeats_fallback"
    assert result.repeat_fallback_used is True
    assert fallback_reasons == ["repeat_fallback_slot_pool_below_threshold:main:41<42"]


def test_empty_recent_history_skips_no_recent_when_pool_below_repeat_fallback_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    recipes = _recipes_for_feasibility_pool(
        breakfast_count=21,
        main_count=41,
    )
    fallback_reasons: list[str | None] = []

    def week_builder(
        profile: UserProfile,
        seed: int,
        avoided_recipe_ids: set[str],
        avoided_recipe_keys: set[str],
        *,
        selection_phase: str,
        **_kwargs: object,
    ) -> tuple[MealPlan, ...]:
        del profile, seed, avoided_recipe_ids, avoided_recipe_keys
        raise AssertionError(f"{selection_phase} should be skipped before week build")

    def repeats_fallback(
        profile: UserProfile,
        seed: int,
        **kwargs: object,
    ) -> telegram_app._WeekPlanBuildResult:
        del seed
        fallback_reasons.append(kwargs.get("failure_reason"))
        return telegram_app._WeekPlanBuildResult(
            plans=_complete_week(profile, "fallback"),
            avoidance_phase="repeats_fallback",
            repeat_fallback_used=True,
            failure_reason=kwargs.get("failure_reason"),
        )

    monkeypatch.setattr(telegram_app, "built_in_recipes", lambda: recipes)
    monkeypatch.setattr(telegram_app, "_build_week_plans", week_builder)
    monkeypatch.setattr(telegram_app, "_build_week_plans_with_repeats_fallback", repeats_fallback)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        956,
        telegram_app._RecentRecipeAvoidance(
            full_recipe_ids=frozenset(),
            full_recipe_keys=frozenset(),
            reduced_recipe_ids=frozenset(),
            reduced_recipe_keys=frozenset(),
        ),
    )

    assert result.avoidance_phase == "repeats_fallback"
    assert result.repeat_fallback_used is True
    assert fallback_reasons == ["repeat_fallback_slot_pool_below_threshold:main:41<42"]


def test_recent_fallback_reuses_recipe_cache_without_changing_weekly_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    seed = 720
    target_energy = calculate_targets(profile).targets.get("energy_kcal")
    recent_ids = {"recent_full", "recent_reduced"}
    recent_keys = {
        "breakfast:curated:recent_full",
        "breakfast:curated:recent_reduced",
    }
    caches_seen: list[object] = []

    def day_builder(
        profile: UserProfile,
        *,
        variety_seed: int,
        avoided_recipe_ids: set[str] | frozenset[str] | None = None,
        avoided_recipe_keys: set[str] | frozenset[str] | None = None,
        recipe_cache: object | None = None,
        **_kwargs: object,
    ) -> MealPlan:
        if recipe_cache is not None:
            caches_seen.append(recipe_cache)
        if recent_ids & set(avoided_recipe_ids or ()):
            return _empty_plan(profile)
        if recent_keys & set(avoided_recipe_keys or ()):
            return _empty_plan(profile)
        prefix = f"seed{variety_seed}"
        return _plan(
            profile,
            prefix,
            target_energy,
            (
                f"food_{variety_seed}_a",
                f"food_{variety_seed}_b",
                f"food_{variety_seed}_c",
            ),
        )

    monkeypatch.setattr(telegram_app, "build_one_day_plan", day_builder)

    baseline = telegram_app._build_week_plans(profile, seed, set(), set())
    caches_seen.clear()
    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        seed,
        telegram_app._RecentRecipeAvoidance(
            full_recipe_ids=frozenset({"recent_full"}),
            full_recipe_keys=frozenset({"breakfast:curated:recent_full"}),
            reduced_recipe_ids=frozenset({"recent_reduced"}),
            reduced_recipe_keys=frozenset({"breakfast:curated:recent_reduced"}),
        ),
    )

    assert result.avoidance_phase == "no_recent"
    assert _weekly_signature(result.plans) == _weekly_signature(baseline)
    assert len({id(cache) for cache in caches_seen}) == 1


def test_weekly_selector_rescues_after_normal_window_has_no_complete_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    seed = 20
    calls: list[int] = []
    rescue_plan = _plan(profile, "rescued", calculate_targets(profile).targets.get("energy_kcal"), ("a", "b", "c"))

    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        calls.append(variety_seed)
        if variety_seed < seed + WEEK_PLAN_CANDIDATE_COUNT:
            return _empty_plan(profile)
        return rescue_plan

    monkeypatch.setattr("diet_bot.telegram_app.build_one_day_plan", day_builder)

    selected = _selected_plan(profile, seed=seed, week_food_ids=set())

    assert _recipe_prefixes(selected) == {"rescued"}
    assert calls == [20, 21, 22, 23, 24, 25, 26, 27]


def test_weekly_selector_does_not_rescue_when_normal_window_has_complete_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    seed = 40
    calls: list[int] = []
    target_energy = calculate_targets(profile).targets.get("energy_kcal")
    plans = tuple(
        _plan(profile, f"normal_{index}", target_energy, (f"a{index}", f"b{index}", f"c{index}"))
        for index in range(WEEK_PLAN_CANDIDATE_COUNT)
    )

    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        calls.append(variety_seed)
        if variety_seed >= seed + WEEK_PLAN_CANDIDATE_COUNT:
            raise AssertionError("rescue window should not run")
        return plans[variety_seed - seed]

    monkeypatch.setattr("diet_bot.telegram_app.build_one_day_plan", day_builder)

    _selected_plan(profile, seed=seed, week_food_ids=set())

    assert calls == [40, 41, 42, 43]


def test_weekly_selector_rescue_keeps_hard_gate_and_avoidance_rejections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    seed = 80
    calls: list[int] = []
    target_energy = calculate_targets(profile).targets.get("energy_kcal")
    blocked_id_plan = _plan(profile, "blocked_id", target_energy, ("a", "b", "c"))
    blocked_key_plan = _plan(profile, "blocked_key", target_energy, ("d", "e", "f"))
    valid_plan = _plan(profile, "valid", target_energy, ("g", "h", "i"))

    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        calls.append(variety_seed)
        if variety_seed in {seed, seed + 3, seed + 4}:
            return _empty_plan(profile)
        if variety_seed in {seed + 1, seed + 5}:
            return blocked_id_plan
        if variety_seed == seed + 2:
            return blocked_key_plan
        return valid_plan

    monkeypatch.setattr("diet_bot.telegram_app.build_one_day_plan", day_builder)

    plan, carryovers = _select_week_day_plan(
        profile,
        seed,
        {"blocked_id_0"},
        {"slot:curated:blocked_key_1"},
        set(),
        {},
    )

    assert _recipe_prefixes(plan) == {"valid"}
    assert carryovers == {}
    assert calls == [80, 81, 82, 83, 84, 85, 86, 87]


def test_weekly_selection_timeout_stops_unproductive_recent_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    seed = 600
    calls: list[int] = []
    clock = {"now": 0.0}

    def fake_perf_counter() -> float:
        return clock["now"]

    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        calls.append(variety_seed)
        clock["now"] += 1.0
        return _empty_plan(profile)

    monkeypatch.setattr(telegram_app.time, "perf_counter", fake_perf_counter)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_RECENT_PHASE_TIMEOUT_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS", 3.0, raising=False)
    monkeypatch.setattr(telegram_app, "build_one_day_plan", day_builder)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        seed,
        telegram_app._RecentRecipeAvoidance(
            full_recipe_ids=frozenset({"recent_full"}),
            full_recipe_keys=frozenset({"breakfast:curated:recent_full"}),
            reduced_recipe_ids=frozenset({"recent_reduced"}),
            reduced_recipe_keys=frozenset({"breakfast:curated:recent_reduced"}),
        ),
    )

    assert result.plans == ()
    assert result.avoidance_phase == "timeout"
    assert len(calls) <= 4


def _carried_history_avoidance() -> "telegram_app._RecentRecipeAvoidance":
    return telegram_app._RecentRecipeAvoidance(
        full_recipe_ids=frozenset({"recent_full"}),
        full_recipe_keys=frozenset({"breakfast:curated:recent_full"}),
        reduced_recipe_ids=frozenset({"recent_reduced"}),
        reduced_recipe_keys=frozenset({"breakfast:curated:recent_reduced"}),
    )


def test_carried_history_no_recent_reserve_exhausted_routes_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Carried-history (non-empty avoidance): when no_recent exhausts its
    # reserve-capped budget while total budget remains, route to the repeats
    # fallback instead of returning an empty timeout result.
    profile = _profile()
    seed = 600
    clock = {"now": 0.0}

    def fake_perf_counter() -> float:
        return clock["now"]

    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        clock["now"] += 1.0
        return _empty_plan(profile)

    fallback_calls: list[str | None] = []
    sentinel_week = tuple(
        _plan(profile, "fallback", 1800.0, ("f0", "f1", "f2"))
        for _ in range(telegram_app.WEEK_PLAN_DAYS)
    )

    def fake_fallback(
        profile: UserProfile,
        seed: int,
        *,
        recipe_cache,
        failure_reason: str | None = None,
        selection_guard=None,
    ) -> "telegram_app._WeekPlanBuildResult":
        fallback_calls.append(failure_reason)
        return telegram_app._WeekPlanBuildResult(
            plans=sentinel_week,
            avoidance_phase="repeats_fallback",
            repeat_fallback_used=True,
        )

    # reserve == total drives the reserve-capped no_recent budget to zero, so the
    # phase trips on its first guard check (the in-loop reserve-exhausted route)
    # while total budget still remains.
    monkeypatch.setattr(telegram_app.time, "perf_counter", fake_perf_counter)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_RECENT_PHASE_TIMEOUT_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS", 60.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS", 40.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_REPEATS_FALLBACK_RESERVE_SECONDS", 40.0, raising=False)
    monkeypatch.setattr(telegram_app, "build_one_day_plan", day_builder)
    monkeypatch.setattr(telegram_app, "_build_week_plans_with_repeats_fallback", fake_fallback)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        seed,
        _carried_history_avoidance(),
    )

    assert result.avoidance_phase == "repeats_fallback"
    assert result.plans == sentinel_week
    assert fallback_calls == ["no_recent_fallback_reserve_exhausted"]


def test_carried_history_no_recent_incomplete_routes_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Carried-history: no_recent finishes incomplete without tripping the guard but
    # total budget remains -> post-loop routing must hand off to the fallback rather
    # than returning a strict failure.
    profile = _profile()
    seed = 600
    clock = {"now": 0.0}

    def fake_perf_counter() -> float:
        return clock["now"]

    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        clock["now"] += 1.0
        return _empty_plan(profile)

    fallback_calls: list[str | None] = []
    sentinel_week = tuple(
        _plan(profile, "fallback", 1800.0, ("f0", "f1", "f2"))
        for _ in range(telegram_app.WEEK_PLAN_DAYS)
    )

    def fake_fallback(
        profile: UserProfile,
        seed: int,
        *,
        recipe_cache,
        failure_reason: str | None = None,
        selection_guard=None,
    ) -> "telegram_app._WeekPlanBuildResult":
        fallback_calls.append(failure_reason)
        return telegram_app._WeekPlanBuildResult(
            plans=sentinel_week,
            avoidance_phase="repeats_fallback",
            repeat_fallback_used=True,
        )

    monkeypatch.setattr(telegram_app.time, "perf_counter", fake_perf_counter)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_RECENT_PHASE_TIMEOUT_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS", 60.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS", 20.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_REPEATS_FALLBACK_RESERVE_SECONDS", 5.0, raising=False)
    monkeypatch.setattr(telegram_app, "build_one_day_plan", day_builder)
    monkeypatch.setattr(telegram_app, "_build_week_plans_with_repeats_fallback", fake_fallback)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        seed,
        _carried_history_avoidance(),
    )

    assert result.avoidance_phase == "repeats_fallback"
    assert result.plans == sentinel_week
    assert fallback_calls == ["no_recent_incomplete_carried_history"]


def test_carried_history_total_budget_exhaustion_stays_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Genuine total-budget exhaustion must NOT be masked as a fallback success:
    # there is nowhere left to run the fallback, so surface an honest timeout.
    profile = _profile()
    seed = 600
    clock = {"now": 0.0}

    def fake_perf_counter() -> float:
        return clock["now"]

    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        clock["now"] += 1.0
        return _empty_plan(profile)

    fallback_calls: list[str | None] = []

    def fake_fallback(*args, **kwargs) -> "telegram_app._WeekPlanBuildResult":
        fallback_calls.append(kwargs.get("failure_reason"))
        return telegram_app._WeekPlanBuildResult(plans=(), avoidance_phase="repeats_fallback")

    monkeypatch.setattr(telegram_app.time, "perf_counter", fake_perf_counter)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_RECENT_PHASE_TIMEOUT_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_NO_RECENT_PHASE_TIMEOUT_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(telegram_app, "WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS", 3.0, raising=False)
    monkeypatch.setattr(telegram_app, "build_one_day_plan", day_builder)
    monkeypatch.setattr(telegram_app, "_build_week_plans_with_repeats_fallback", fake_fallback)

    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        seed,
        _carried_history_avoidance(),
    )

    assert result.plans == ()
    assert result.avoidance_phase == "timeout"
    assert fallback_calls == []


def test_live_seed_604374606_local_state_weekly_selection_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.getenv("DIET_BOT_RUN_LOCAL_LIVE_QA") != "1":
        pytest.skip("local live QA state test is opt-in")

    state_path = Path(__file__).resolve().parents[1] / ".diet_bot_state" / "history.json"
    if not state_path.exists():
        pytest.skip("local live QA state is not available")

    raw_state = json.loads(state_path.read_text(encoding="utf-8"))
    chat_id = 498196878
    raw_chat_state = raw_state.get(str(chat_id))
    if not isinstance(raw_chat_state, dict) or not isinstance(raw_chat_state.get("profile"), dict):
        pytest.skip("local live QA profile is not available")

    profile = telegram_app._profile_from_dict(raw_chat_state["profile"])
    assert profile is not None

    monkeypatch.setattr(telegram_app, "STATE_FILE", state_path)
    feasibility_events: list[dict[str, object]] = []

    def capture_weekly_selection_diag(
        event: str,
        *,
        always: bool = False,
        **fields: object,
    ) -> None:
        del always
        if event in {"phase_feasibility_start", "phase_feasibility_end"}:
            feasibility_events.append({"event": event, **fields})

    monkeypatch.setattr(telegram_app, "_weekly_selection_diag", capture_weekly_selection_diag)
    recent_avoidance = telegram_app._load_recent_recipe_avoidance(chat_id, now=datetime.now(UTC))

    started_at = time.perf_counter()
    result = telegram_app._build_week_plans_with_recent_fallback(
        profile,
        604374606,
        recent_avoidance,
    )
    elapsed_s = time.perf_counter() - started_at

    skipped_phases = {
        event.get("raw_phase")
        for event in feasibility_events
        if event.get("event") == "phase_feasibility_end" and event.get("skipped") is True
    }
    checked_recent_phases = {
        event.get("raw_phase")
        for event in feasibility_events
        if event.get("event") == "phase_feasibility_end"
        and event.get("raw_phase") in {"full_recent", "reduced_recent"}
    }
    planned_recipe_ids = [
        meal.recipe_id
        for plan in result.plans
        for meal in plan.meals
        if meal.recipe_id
    ]
    validation_errors = [
        error
        for plan in result.plans
        for error in validate_plan(plan).errors
    ]

    assert elapsed_s < float(telegram_app.WEEKLY_SELECTION_TOTAL_TIMEOUT_SECONDS)
    assert "full_recent" in checked_recent_phases
    assert skipped_phases.isdisjoint({"full_recent", "reduced_recent"})
    assert result.avoidance_phase != "timeout"
    assert telegram_app._week_plans_are_complete(result.plans, profile)
    assert len(planned_recipe_ids) == profile.meal_count * telegram_app.WEEK_PLAN_DAYS
    assert len(set(planned_recipe_ids)) == len(planned_recipe_ids)
    assert validation_errors == []
