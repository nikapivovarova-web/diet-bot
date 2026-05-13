from __future__ import annotations

from diet_bot.calculator import calculate_targets
from diet_bot.domain import (
    ActivityLevel,
    CookingTimePreference,
    Food,
    Goal,
    Meal,
    MealPlan,
    NutrientVector,
    Restriction,
    RestrictionType,
    SafetyResult,
    Sex,
    UserProfile,
)
from diet_bot.weekly_optimizer import (
    WeeklyDayCandidateBounds,
    _collect_recipe_ids,
    _generate_weekly_day_candidates,
    _score_weekly_day_candidate,
    _validate_weekly_day_candidate,
)


def profile_with(**kwargs) -> UserProfile:
    data = {
        "age": 32,
        "sex": Sex.MALE,
        "height_cm": 178,
        "weight_kg": 86,
        "goal": Goal.MAINTAIN,
        "activity": ActivityLevel.MODERATE,
        "meal_count": 3,
        "cooking_time": CookingTimePreference.SIMPLE,
    }
    data.update(kwargs)
    return UserProfile(**data)


def _food(food_id: str, energy: float, protein: float, fat: float, carbohydrate: float) -> Food:
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


def _meal(recipe_id: str, energy: float, protein: float, fat: float, carbohydrate: float) -> Meal:
    return Meal(
        name=f"meal {recipe_id}",
        portions=(_food(recipe_id, energy, protein, fat, carbohydrate).portion(100),),
        recipe="test recipe",
        recipe_id=recipe_id,
        recipe_key=f"slot:curated:{recipe_id}",
    )


def _plan(
    profile: UserProfile,
    recipe_ids: tuple[str, ...],
    *,
    energy: float = 2000,
    protein: float = 100,
    fat: float = 60,
    carbohydrate: float = 250,
    can_generate: bool = True,
) -> MealPlan:
    per_meal = len(recipe_ids) or 1
    return MealPlan(
        meals=tuple(
            _meal(
                recipe_id,
                energy / per_meal,
                protein / per_meal,
                fat / per_meal,
                carbohydrate / per_meal,
            )
            for recipe_id in recipe_ids
        ),
        targets=calculate_targets(profile),
        safety=SafetyResult(can_generate_plan=can_generate),
    )


def test_incomplete_day_candidate_is_rejected() -> None:
    profile = profile_with(meal_count=3)
    plan = _plan(profile, ("r001", "r002"))

    validation = _validate_weekly_day_candidate(plan, profile)

    assert not validation.ok
    assert validation.reason == "incomplete_day"


def test_candidate_with_repeated_recipe_id_is_rejected() -> None:
    profile = profile_with(meal_count=3)
    plan = _plan(profile, ("r001", "r001", "r002"))

    validation = _validate_weekly_day_candidate(plan, profile)

    assert _collect_recipe_ids(plan) == frozenset({"r001", "r002"})
    assert not validation.ok
    assert validation.reason == "repeated_recipe_id"


def test_candidate_respecting_avoided_ids_is_accepted() -> None:
    profile = profile_with(meal_count=3)
    plan = _plan(profile, ("r001", "r002", "r003"), protein=120)

    validation = _validate_weekly_day_candidate(plan, profile, avoided_recipe_ids=frozenset({"recent_r"}))

    assert validation.ok


def test_candidate_scoring_prefers_reasonable_protein_overage() -> None:
    profile = profile_with(meal_count=3)
    reasonable = _plan(profile, ("r001", "r002", "r003"), protein=120)
    excessive = _plan(profile, ("r004", "r005", "r006"), protein=170)

    assert _score_weekly_day_candidate(reasonable) > _score_weekly_day_candidate(excessive)


def test_candidate_generation_respects_max_candidate_limit() -> None:
    profile = profile_with(meal_count=3)

    def day_builder(profile: UserProfile, *, variety_seed: int, **kwargs) -> MealPlan:
        return _plan(profile, (f"r{variety_seed}a", f"r{variety_seed}b", f"r{variety_seed}c"), protein=120)

    result = _generate_weekly_day_candidates(
        profile,
        seed_start=10,
        seed_count=8,
        bounds=WeeklyDayCandidateBounds(max_candidates=3, max_attempts=8, deadline_seconds=None),
        day_builder=day_builder,
    )

    assert len(result.candidates) == 3
    assert result.stats.attempted == 3
    assert [candidate.seed for candidate in result.candidates] == [10, 11, 12]


def test_exclusions_flow_into_candidate_generation_when_using_day_builder() -> None:
    profile = profile_with(
        meal_count=3,
        restrictions=(Restriction(RestrictionType.ALLERGY, "eggs"),),
    )

    result = _generate_weekly_day_candidates(
        profile,
        seed_start=0,
        seed_count=2,
        bounds=WeeklyDayCandidateBounds(max_candidates=1, max_attempts=2, deadline_seconds=None),
    )

    assert result.candidates
    assert all(
        portion.food.id not in {"egg", "egg_white", "egg_yolk", "egg_white_extra"}
        for candidate in result.candidates
        for meal in candidate.plan.meals
        for portion in meal.portions
    )


def test_candidate_generation_passes_avoided_ids_to_day_builder() -> None:
    profile = profile_with(meal_count=3)
    calls: list[tuple[frozenset[str], frozenset[str]]] = []

    def day_builder(profile: UserProfile, *, avoided_recipe_ids, avoided_recipe_keys, **kwargs) -> MealPlan:
        calls.append((frozenset(avoided_recipe_ids), frozenset(avoided_recipe_keys)))
        return _plan(profile, ("r001", "r002", "r003"), protein=120)

    _generate_weekly_day_candidates(
        profile,
        seed_start=0,
        seed_count=1,
        avoided_recipe_ids=frozenset({"avoid_id"}),
        avoided_recipe_keys=frozenset({"avoid_key"}),
        bounds=WeeklyDayCandidateBounds(max_candidates=1, max_attempts=1, deadline_seconds=None),
        day_builder=day_builder,
    )

    assert calls == [(frozenset({"avoid_id"}), frozenset({"avoid_key"}))]
