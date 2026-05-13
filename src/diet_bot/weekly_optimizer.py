from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import monotonic
from typing import TypeAlias

from .builder import (
    PROTEIN_EXCESSIVE_CEILING_MULTIPLIER,
    PROTEIN_REASONABLE_CEILING_MULTIPLIER,
    PROTEIN_TOP_UP_TARGET_MULTIPLIER,
    build_one_day_plan,
)
from .domain import MealPlan, NutrientVector, UserProfile


DayBuilder: TypeAlias = Callable[..., MealPlan]


@dataclass(frozen=True)
class WeeklyDayCandidateBounds:
    max_candidates: int = 8
    max_attempts: int = 16
    deadline_seconds: float | None = 2.0


@dataclass(frozen=True)
class WeeklyDayCandidateValidation:
    ok: bool
    reason: str | None = None


@dataclass(frozen=True)
class WeeklyDayCandidate:
    plan: MealPlan
    seed: int
    candidate_index: int
    recipe_ids: frozenset[str]
    recipe_keys: frozenset[str]
    score: tuple[float, float, float, float, int]


@dataclass(frozen=True)
class WeeklyDayCandidateStats:
    attempted: int = 0
    accepted: int = 0
    rejected_incomplete: int = 0
    rejected_repeated_recipe_id: int = 0
    rejected_repeated_recipe_key: int = 0
    rejected_avoided_recipe_id: int = 0
    rejected_avoided_recipe_key: int = 0
    rejected_missing_recipe_id: int = 0
    rejected_missing_recipe_key: int = 0
    rejected_protein_floor: int = 0
    rejected_duplicate_signature: int = 0
    deadline_hit: bool = False


@dataclass(frozen=True)
class WeeklyDayCandidateGeneration:
    candidates: tuple[WeeklyDayCandidate, ...]
    stats: WeeklyDayCandidateStats


def _generate_weekly_day_candidates(
    profile: UserProfile,
    *,
    seed_start: int,
    seed_count: int,
    avoided_recipe_ids: frozenset[str] | set[str] | None = None,
    avoided_recipe_keys: frozenset[str] | set[str] | None = None,
    bounds: WeeklyDayCandidateBounds = WeeklyDayCandidateBounds(),
    day_builder: DayBuilder = build_one_day_plan,
) -> WeeklyDayCandidateGeneration:
    avoided_ids = frozenset(avoided_recipe_ids or frozenset())
    avoided_keys = frozenset(avoided_recipe_keys or frozenset())
    max_candidates = max(0, bounds.max_candidates)
    max_attempts = max(0, min(seed_count, bounds.max_attempts))
    candidates: list[WeeklyDayCandidate] = []
    seen_signatures: set[tuple[str, ...]] = set()
    stats = WeeklyDayCandidateStats()
    started_at = monotonic()

    for candidate_index in range(max_attempts):
        if len(candidates) >= max_candidates:
            break
        if _deadline_hit(started_at, bounds.deadline_seconds):
            stats = _stats_with(stats, deadline_hit=True)
            break

        seed = seed_start + candidate_index
        plan = day_builder(
            profile,
            variety_seed=seed,
            avoided_recipe_ids=avoided_ids,
            avoided_recipe_keys=avoided_keys,
            recipe_source="curated_only",
            allow_avoided_recipe_relaxation=False,
        )
        stats = _stats_with(stats, attempted=stats.attempted + 1)
        validation = _validate_weekly_day_candidate(
            plan,
            profile,
            avoided_recipe_ids=avoided_ids,
            avoided_recipe_keys=avoided_keys,
        )
        if not validation.ok:
            stats = _increment_rejection(stats, validation.reason)
            continue

        signature = _candidate_signature(plan)
        if signature in seen_signatures:
            stats = _stats_with(stats, rejected_duplicate_signature=stats.rejected_duplicate_signature + 1)
            continue

        seen_signatures.add(signature)
        candidates.append(
            WeeklyDayCandidate(
                plan=plan,
                seed=seed,
                candidate_index=candidate_index,
                recipe_ids=_collect_recipe_ids(plan),
                recipe_keys=_collect_recipe_keys(plan),
                score=_score_weekly_day_candidate(plan, candidate_index=candidate_index),
            )
        )
        stats = _stats_with(stats, accepted=stats.accepted + 1)

    ranked = tuple(sorted(candidates, key=lambda candidate: candidate.score, reverse=True))
    return WeeklyDayCandidateGeneration(candidates=ranked, stats=stats)


def _validate_weekly_day_candidate(
    plan: MealPlan,
    profile: UserProfile,
    *,
    avoided_recipe_ids: frozenset[str] | set[str] | None = None,
    avoided_recipe_keys: frozenset[str] | set[str] | None = None,
) -> WeeklyDayCandidateValidation:
    if not plan.safety.can_generate_plan or len(plan.meals) != _expected_meal_count(profile):
        return WeeklyDayCandidateValidation(False, "incomplete_day")

    recipe_id_values = [meal.recipe_id for meal in plan.meals]
    if any(recipe_id is None for recipe_id in recipe_id_values):
        return WeeklyDayCandidateValidation(False, "missing_recipe_id")
    recipe_ids = [recipe_id for recipe_id in recipe_id_values if recipe_id]
    if len(recipe_ids) != len(plan.meals):
        return WeeklyDayCandidateValidation(False, "missing_recipe_id")
    if len(set(recipe_ids)) != len(recipe_ids):
        return WeeklyDayCandidateValidation(False, "repeated_recipe_id")

    recipe_key_values = [meal.recipe_key for meal in plan.meals]
    if any(recipe_key is None for recipe_key in recipe_key_values):
        return WeeklyDayCandidateValidation(False, "missing_recipe_key")
    recipe_keys = [recipe_key for recipe_key in recipe_key_values if recipe_key]
    if len(recipe_keys) != len(plan.meals):
        return WeeklyDayCandidateValidation(False, "missing_recipe_key")
    if len(set(recipe_keys)) != len(recipe_keys):
        return WeeklyDayCandidateValidation(False, "repeated_recipe_key")

    avoided_ids = frozenset(avoided_recipe_ids or frozenset())
    if avoided_ids & set(recipe_ids):
        return WeeklyDayCandidateValidation(False, "avoided_recipe_id")

    avoided_keys = frozenset(avoided_recipe_keys or frozenset())
    if avoided_keys & set(recipe_keys):
        return WeeklyDayCandidateValidation(False, "avoided_recipe_key")

    if plan.totals.get("protein_g") + 0.01 < _protein_hard_floor(plan.targets.targets):
        return WeeklyDayCandidateValidation(False, "protein_floor")

    return WeeklyDayCandidateValidation(True)


def _collect_recipe_ids(plan: MealPlan) -> frozenset[str]:
    return frozenset(meal.recipe_id for meal in plan.meals if meal.recipe_id)


def _collect_recipe_keys(plan: MealPlan) -> frozenset[str]:
    return frozenset(meal.recipe_key for meal in plan.meals if meal.recipe_key)


def _score_weekly_day_candidate(
    plan: MealPlan,
    *,
    candidate_index: int = 0,
    recipe_scarcity: dict[str, int] | None = None,
) -> tuple[float, float, float, float, int]:
    total = plan.totals
    target = plan.targets.targets
    macro_gap = _relative_gap(total, target, "energy_kcal") * 3.0
    macro_gap += _relative_gap(total, target, "fat_g")
    macro_gap += _relative_gap(total, target, "carbohydrate_g")
    protein_penalty = _protein_overage_penalty(total, target)
    repeat_penalty = _recipe_repeat_penalty(plan) * 100.0 + _food_repeat_penalty(plan) * 0.05
    scarcity_penalty = _recipe_scarcity_penalty(plan, recipe_scarcity or {})
    total_penalty = macro_gap + protein_penalty + repeat_penalty + scarcity_penalty
    return (-total_penalty, -macro_gap, -protein_penalty, -repeat_penalty, -candidate_index)


def _expected_meal_count(profile: UserProfile) -> int:
    return min(5, max(3, profile.meal_count))


def _candidate_signature(plan: MealPlan) -> tuple[str, ...]:
    return tuple(meal.recipe_id or "" for meal in plan.meals)


def _protein_hard_floor(target: NutrientVector) -> float:
    return target.get("protein_g") * PROTEIN_TOP_UP_TARGET_MULTIPLIER


def _protein_overage_penalty(total: NutrientVector, target: NutrientVector) -> float:
    protein_target = target.get("protein_g")
    if protein_target <= 0:
        return 0.0
    protein_ratio = total.get("protein_g") / protein_target
    if protein_ratio < PROTEIN_TOP_UP_TARGET_MULTIPLIER:
        return (PROTEIN_TOP_UP_TARGET_MULTIPLIER - protein_ratio) * 20.0

    penalty = abs(protein_ratio - 1.0) * 0.25
    if protein_ratio > 1.15:
        penalty += (protein_ratio - 1.15) * 1.5
    if protein_ratio > PROTEIN_REASONABLE_CEILING_MULTIPLIER:
        penalty += (protein_ratio - PROTEIN_REASONABLE_CEILING_MULTIPLIER) * 6.0
    if protein_ratio > PROTEIN_EXCESSIVE_CEILING_MULTIPLIER:
        penalty += (protein_ratio - PROTEIN_EXCESSIVE_CEILING_MULTIPLIER) * 14.0
    return penalty


def _relative_gap(total: NutrientVector, target: NutrientVector, nutrient: str) -> float:
    target_value = target.get(nutrient)
    if target_value <= 0:
        return 0.0
    return abs(total.get(nutrient) - target_value) / target_value


def _recipe_repeat_penalty(plan: MealPlan) -> int:
    ids = [meal.recipe_id for meal in plan.meals if meal.recipe_id]
    keys = [meal.recipe_key for meal in plan.meals if meal.recipe_key]
    return (len(ids) - len(set(ids))) + (len(keys) - len(set(keys)))


def _food_repeat_penalty(plan: MealPlan) -> int:
    counts = Counter(portion.food.id for meal in plan.meals for portion in meal.portions)
    return sum(max(0, count - 1) for count in counts.values())


def _recipe_scarcity_penalty(plan: MealPlan, recipe_scarcity: dict[str, int]) -> float:
    if not recipe_scarcity:
        return 0.0
    penalty = 0.0
    for recipe_id in _collect_recipe_ids(plan):
        scarcity_count = max(1, recipe_scarcity.get(recipe_id, 1))
        penalty += 1.0 / scarcity_count
    return penalty * 0.15


def _deadline_hit(started_at: float, deadline_seconds: float | None) -> bool:
    if deadline_seconds is None:
        return False
    if deadline_seconds <= 0:
        return True
    return monotonic() - started_at >= deadline_seconds


def _increment_rejection(stats: WeeklyDayCandidateStats, reason: str | None) -> WeeklyDayCandidateStats:
    if reason == "incomplete_day":
        return _stats_with(stats, rejected_incomplete=stats.rejected_incomplete + 1)
    if reason == "repeated_recipe_id":
        return _stats_with(stats, rejected_repeated_recipe_id=stats.rejected_repeated_recipe_id + 1)
    if reason == "repeated_recipe_key":
        return _stats_with(stats, rejected_repeated_recipe_key=stats.rejected_repeated_recipe_key + 1)
    if reason == "avoided_recipe_id":
        return _stats_with(stats, rejected_avoided_recipe_id=stats.rejected_avoided_recipe_id + 1)
    if reason == "avoided_recipe_key":
        return _stats_with(stats, rejected_avoided_recipe_key=stats.rejected_avoided_recipe_key + 1)
    if reason == "missing_recipe_id":
        return _stats_with(stats, rejected_missing_recipe_id=stats.rejected_missing_recipe_id + 1)
    if reason == "missing_recipe_key":
        return _stats_with(stats, rejected_missing_recipe_key=stats.rejected_missing_recipe_key + 1)
    if reason == "protein_floor":
        return _stats_with(stats, rejected_protein_floor=stats.rejected_protein_floor + 1)
    return stats


def _stats_with(stats: WeeklyDayCandidateStats, **updates: object) -> WeeklyDayCandidateStats:
    return replace(stats, **updates)
