from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from diet_bot.builder import (  # noqa: E402
    _cooking_effort_phases,
    _meal_energy_slots,
    _recipe_matches_cooking_effort,
    _recipe_slot_eligibility,
    _recipe_title_uses_excluded_food,
    _resolve_recipe_ingredients,
    build_one_day_plan,
    filter_foods,
)
from diet_bot.calculator import calculate_targets  # noqa: E402
from diet_bot.catalog import built_in_foods  # noqa: E402
from diet_bot.domain import (  # noqa: E402
    ActivityLevel,
    CookingTimePreference,
    Goal,
    MealPlan,
    NutrientVector,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
)
from diet_bot.recipe_catalog import RecipeTemplate, built_in_recipes  # noqa: E402
from diet_bot.recipe_traits import infer_recipe_traits  # noqa: E402
from diet_bot.safety import evaluate_safety  # noqa: E402
from diet_bot.telegram_app import (  # noqa: E402
    WEEK_PLAN_CANDIDATE_COUNT,
    WEEK_PLAN_DAYS,
    _BatchCarryover,
    _apply_batch_carryovers,
    _candidate_recipe_counts,
    _carryovers_use_avoided_recipes,
    _copy_carryovers,
    _meal_slot,
    _plan_uses_avoided_recipes,
    _week_day_plan_is_complete,
    _week_food_ids,
    _weekly_day_selection_score,
)


TITLE_LIMIT = 42
TOP_SHARED_CORE_CANDIDATES = 3


@dataclass(frozen=True)
class ProfileSpec:
    key: str
    label: str
    seeds: range
    profile: UserProfile


@dataclass(frozen=True)
class CandidateTrace:
    candidate_index: int
    seed: int
    recipe_ids: tuple[str, ...]
    score: tuple[float, float, float, int] | None
    complete: bool
    selectable: bool
    rejection: str | None
    calorie_gap: float
    macro_gap: float


@dataclass(frozen=True)
class DayTrace:
    week_seed: int
    day_index: int
    selected_plan: MealPlan
    candidates: tuple[CandidateTrace, ...]


@dataclass(frozen=True)
class WeekTrace:
    week_seed: int
    plans: tuple[MealPlan, ...]
    day_traces: tuple[DayTrace, ...]
    complete: bool


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    recipes_by_id = {recipe.id: recipe for recipe in built_in_recipes()}
    selected_specs = [
        _with_seed_limit(spec, args.seed_limit)
        for spec in _profile_specs()
        if args.profile in {"all", spec.key}
    ]
    exit_code = 0

    for index, spec in enumerate(selected_specs):
        if index:
            print()
        weeks = tuple(_trace_week(spec.profile, seed) for seed in spec.seeds)
        repeated_core = _recipes_present_in_every_week(weeks, len(spec.seeds))
        _print_profile_report(spec, weeks, recipes_by_id, repeated_core, args)
        if args.assert_no_repeated_core and repeated_core:
            print(
                f"ASSERTION FAILED: Profile {spec.key} has {len(repeated_core)} recipe(s) present in every seed.",
                file=sys.stderr,
            )
            exit_code = 1

    return exit_code


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only weekly completed-day diversity diagnostic.")
    parser.add_argument("--profile", choices=("all", "A", "B"), default="all")
    parser.add_argument("--mode", choices=("all", "selected", "candidates"), default="all")
    parser.add_argument("--max-repeat-lines", type=int, default=12)
    parser.add_argument("--max-selection-points", type=int, default=80)
    parser.add_argument("--seed-limit", type=int, default=None, help="Optional smoke-run cap; default uses the full profile seed range.")
    parser.add_argument(
        "--assert-no-repeated-core",
        action="store_true",
        help="Exit non-zero when any selected profile has a recipe present in every seed.",
    )
    return parser.parse_args(argv)


def _profile_specs() -> tuple[ProfileSpec, ProfileSpec]:
    base = {
        "age": 32,
        "sex": Sex.MALE,
        "height_cm": 178,
        "weight_kg": 86,
        "goal": Goal.LOSE,
        "activity": ActivityLevel.MODERATE,
        "meal_count": 5,
        "cooking_time": CookingTimePreference.SIMPLE,
    }
    profile_a = UserProfile(**base)
    profile_b = UserProfile(
        **base,
        restrictions=(
            Restriction(RestrictionType.ALLERGY, "\u044f\u0439\u0446\u0430"),
            Restriction(
                RestrictionType.EXCLUDED_FOOD,
                "\u043a\u0438\u0441\u043b\u043e\u043c\u043e\u043b\u043e\u0447\u043d\u044b\u0435 "
                "\u043f\u0440\u043e\u0434\u0443\u043a\u0442\u044b",
            ),
            Restriction(RestrictionType.EXCLUDED_FOOD, "\u043a\u0430\u0448\u0430"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "\u043c\u043e\u043b\u043e\u0447\u043a\u0430"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "\u043c\u043e\u043b\u043e\u043a\u043e"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "\u0433\u0440\u0438\u0431\u044b"),
        ),
    )
    specs = (
        ProfileSpec("A", "male 32/178/86 LOSE MODERATE SIMPLE 5 meals, no exclusions, seeds 0..9", range(10), profile_a),
        ProfileSpec("B", "same profile with manual-like exclusions, seeds 0..5", range(6), profile_b),
    )
    return specs


def _with_seed_limit(spec: ProfileSpec, seed_limit: int | None) -> ProfileSpec:
    if seed_limit is None:
        return spec
    limit = max(0, seed_limit)
    seeds = range(spec.seeds.start, min(spec.seeds.stop, spec.seeds.start + limit))
    return ProfileSpec(spec.key, f"{spec.label} (limited to {len(seeds)} seed(s))", seeds, spec.profile)


def _trace_week(profile: UserProfile, week_seed: int) -> WeekTrace:
    plans: list[MealPlan] = []
    day_traces: list[DayTrace] = []
    week_recipe_ids: set[str] = set()
    week_recipe_keys: set[str] = set()
    carryovers: dict[str, _BatchCarryover] = {}

    for day_index in range(WEEK_PLAN_DAYS):
        selected_plan, carryovers, candidates = _trace_select_week_day_plan(
            profile,
            week_seed + day_index * WEEK_PLAN_CANDIDATE_COUNT,
            week_recipe_ids,
            week_recipe_keys,
            _week_food_ids(plans),
            carryovers,
            has_future_week_days=day_index < WEEK_PLAN_DAYS - 1,
        )
        day_traces.append(DayTrace(week_seed, day_index, selected_plan, tuple(candidates)))
        if not _week_day_plan_is_complete(selected_plan, profile):
            return WeekTrace(week_seed, tuple(plans), tuple(day_traces), complete=False)

        plans.append(selected_plan)
        week_recipe_ids.update(meal.recipe_id for meal in selected_plan.meals if meal.recipe_id)
        week_recipe_keys.update(meal.recipe_key for meal in selected_plan.meals if meal.recipe_key)

    return WeekTrace(week_seed, tuple(plans), tuple(day_traces), complete=len(plans) == WEEK_PLAN_DAYS)


def _trace_select_week_day_plan(
    profile: UserProfile,
    seed: int,
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
    week_food_ids: set[str],
    carryovers: dict[str, _BatchCarryover],
    *,
    has_future_week_days: bool,
) -> tuple[MealPlan, dict[str, _BatchCarryover], list[CandidateTrace]]:
    best_plan: MealPlan | None = None
    best_carryovers: dict[str, _BatchCarryover] | None = None
    best_score: tuple[float, float, float, int] | None = None
    rejected_plan: MealPlan | None = None
    traces: list[CandidateTrace] = []
    selectable_options: list[tuple[MealPlan, dict[str, _BatchCarryover], int]] = []

    for candidate_index in range(WEEK_PLAN_CANDIDATE_COUNT):
        candidate_seed = seed + candidate_index
        plan = build_one_day_plan(
            profile,
            variety_seed=candidate_seed,
            avoided_recipe_ids=avoided_recipe_ids,
            avoided_recipe_keys=avoided_recipe_keys,
            recipe_source="curated_only",
            allow_avoided_recipe_relaxation=False,
        )
        candidate_carryovers = _copy_carryovers(carryovers)
        plan = _apply_batch_carryovers(plan, candidate_carryovers)
        rejection = _candidate_rejection(
            plan,
            candidate_carryovers,
            avoided_recipe_ids,
            avoided_recipe_keys,
            has_future_week_days,
        )
        selectable = rejection is None
        recipe_ids = tuple(meal.recipe_id or "" for meal in plan.meals)
        traces.append(
            CandidateTrace(
                candidate_index=candidate_index,
                seed=candidate_seed,
                recipe_ids=recipe_ids,
                score=None,
                complete=_week_day_plan_is_complete(plan, profile),
                selectable=selectable,
                rejection=rejection,
                calorie_gap=_calorie_gap(plan),
                macro_gap=_macro_gap(plan),
            )
        )

        if not selectable:
            rejected_plan = rejected_plan or plan
            continue
        selectable_options.append((plan, candidate_carryovers, candidate_index))

    if selectable_options:
        candidate_recipe_counts = _candidate_recipe_counts(tuple(option[0] for option in selectable_options))
        scores_by_index = {
            candidate_index: _weekly_day_selection_score(
                plan,
                week_food_ids,
                candidate_index,
                week_recipe_ids_for_diversity=avoided_recipe_ids,
                candidate_recipe_counts=candidate_recipe_counts,
            )
            for plan, _, candidate_index in selectable_options
        }
        traces = [
            replace(trace, score=scores_by_index.get(trace.candidate_index))
            if trace.selectable
            else trace
            for trace in traces
        ]
        for plan, candidate_carryovers, candidate_index in selectable_options:
            score = scores_by_index[candidate_index]
            if best_score is None or score > best_score:
                best_plan = plan
                best_carryovers = candidate_carryovers
                best_score = score

    if best_plan is None or best_carryovers is None:
        if rejected_plan is not None:
            return replace(rejected_plan, meals=()), carryovers, traces
        fallback = build_one_day_plan(
            profile,
            variety_seed=seed,
            avoided_recipe_ids=avoided_recipe_ids,
            avoided_recipe_keys=avoided_recipe_keys,
            recipe_source="curated_only",
            allow_avoided_recipe_relaxation=False,
        )
        return fallback, carryovers, traces
    return best_plan, best_carryovers, traces


def _candidate_rejection(
    plan: MealPlan,
    candidate_carryovers: dict[str, _BatchCarryover],
    avoided_recipe_ids: set[str],
    avoided_recipe_keys: set[str],
    has_future_week_days: bool,
) -> str | None:
    if _plan_uses_avoided_recipes(plan, avoided_recipe_ids, avoided_recipe_keys):
        return "uses_avoided_recipe"
    next_avoided_recipe_ids = set(avoided_recipe_ids)
    next_avoided_recipe_ids.update(meal.recipe_id for meal in plan.meals if meal.recipe_id)
    next_avoided_recipe_keys = set(avoided_recipe_keys)
    next_avoided_recipe_keys.update(meal.recipe_key for meal in plan.meals if meal.recipe_key)
    if has_future_week_days and _carryovers_use_avoided_recipes(
        candidate_carryovers,
        next_avoided_recipe_ids,
        next_avoided_recipe_keys,
    ):
        return "future_carryover_uses_avoided_recipe"
    return None


def _print_profile_report(
    spec: ProfileSpec,
    weeks: tuple[WeekTrace, ...],
    recipes_by_id: dict[str, RecipeTemplate],
    repeated_core: frozenset[str],
    args: argparse.Namespace,
) -> None:
    print(f"=== Profile {spec.key}: {spec.label} ===")
    print(f"completed weeks: {sum(1 for week in weeks if week.complete)}/{len(weeks)}")
    print(f"weekly selection candidates per day: {WEEK_PLAN_CANDIDATE_COUNT}")
    if args.mode in {"all", "selected"}:
        _print_selected_days(weeks, recipes_by_id)
        _print_repeat_summary(spec, weeks, recipes_by_id, repeated_core, args.max_repeat_lines)
        _print_hard_filter_alternatives(spec.profile, weeks, recipes_by_id, repeated_core)
    if args.mode in {"all", "candidates"}:
        _print_candidate_summary(weeks, recipes_by_id, repeated_core, args.max_selection_points)


def _print_selected_days(weeks: tuple[WeekTrace, ...], recipes_by_id: dict[str, RecipeTemplate]) -> None:
    print()
    print("Selected recipes by day/slot:")
    for week in weeks:
        print(f"seed {week.week_seed}:")
        if not week.complete:
            print("  incomplete week")
        for day_index, plan in enumerate(week.plans, start=1):
            cells = []
            for meal in plan.meals:
                recipe_id = meal.recipe_id or "missing"
                cells.append(f"{_meal_slot(meal)}={_recipe_label(recipe_id, recipes_by_id.get(recipe_id))}")
            print(f"  day {day_index}: " + " | ".join(cells))


def _print_repeat_summary(
    spec: ProfileSpec,
    weeks: tuple[WeekTrace, ...],
    recipes_by_id: dict[str, RecipeTemplate],
    repeated_core: frozenset[str],
    max_lines: int,
) -> None:
    placements: Counter[str] = Counter()
    week_presence: Counter[str] = Counter()
    source_placements: Counter[str] = Counter()
    unique_by_source: defaultdict[str, set[str]] = defaultdict(set)

    for week in weeks:
        present_in_week: set[str] = set()
        for plan in week.plans:
            for meal in plan.meals:
                if not meal.recipe_id:
                    continue
                recipe = recipes_by_id.get(meal.recipe_id)
                source = _source_bucket(recipe)
                source_placements[source] += 1
                unique_by_source[source].add(meal.recipe_id)
                placements[meal.recipe_id] += 1
                present_in_week.add(meal.recipe_id)
        week_presence.update(present_in_week)

    print()
    print("Selection counts:")
    print(f"  unique selected recipes: {len(placements)}")
    print("  source placements: " + _counter_pairs(source_placements))
    print("  unique by source: " + ", ".join(f"{key}={len(value)}" for key, value in sorted(unique_by_source.items())))
    print(f"  recipes present in every seed: {len(repeated_core)}")

    print()
    print("Top repeats across weekly seeds:")
    total_weeks = len(spec.seeds)
    top_rows = sorted(placements, key=lambda recipe_id: (-week_presence[recipe_id], -placements[recipe_id], recipe_id))
    for recipe_id in top_rows[:max_lines]:
        print(
            f"  {week_presence[recipe_id]}/{total_weeks} weeks; "
            f"{placements[recipe_id]} placements; {_recipe_label(recipe_id, recipes_by_id.get(recipe_id))}"
        )


def _print_hard_filter_alternatives(
    profile: UserProfile,
    weeks: tuple[WeekTrace, ...],
    recipes_by_id: dict[str, RecipeTemplate],
    repeated_core: frozenset[str],
) -> None:
    print()
    if not repeated_core:
        print("Repeated-core hard-filter alternatives: none")
        return

    print("Repeated-core hard-filter alternatives:")
    slots_by_recipe = _selected_slots_by_recipe(weeks)
    for recipe_id in sorted(repeated_core):
        recipe = recipes_by_id.get(recipe_id)
        if recipe is None:
            continue
        traits = infer_recipe_traits(recipe)
        slots = tuple(sorted(slots_by_recipe.get(recipe_id) or {recipe.slot}))
        alternatives = ", ".join(f"{slot}:{_same_slot_alternative_count(profile, recipe, slot)}" for slot in slots)
        print(
            f"  {_recipe_label(recipe_id, recipe)}; slots={','.join(slots)}; alternatives={alternatives}; "
            f"traits=protein:{traits.primary_protein}, carb:{traits.primary_carb}, "
            f"format:{traits.recipe_format}, effort:{traits.cooking_effort}, batch:{traits.source_batch}"
        )


def _print_candidate_summary(
    weeks: tuple[WeekTrace, ...],
    recipes_by_id: dict[str, RecipeTemplate],
    repeated_core: frozenset[str],
    max_selection_points: int,
) -> None:
    print()
    print("Completed-day candidate selection points:")
    completed_distribution: Counter[int] = Counter()
    unique_set_distribution: Counter[int] = Counter()
    diverse_available: Counter[bool] = Counter()
    repeated_available: Counter[bool] = Counter()
    calorie_deltas: list[float] = []
    macro_deltas: list[float] = []
    reuse_deltas: list[float] = []
    printed = 0

    for week in weeks:
        for point in week.day_traces:
            completed = [candidate for candidate in point.candidates if candidate.complete and candidate.selectable]
            unique_sets = {tuple(sorted(candidate.recipe_ids)) for candidate in completed}
            sorted_completed = sorted(completed, key=lambda candidate: candidate.score or (-999, -999, -999, -999), reverse=True)
            repetitive = [candidate for candidate in completed if set(candidate.recipe_ids) & repeated_core]
            diverse = [candidate for candidate in completed if not (set(candidate.recipe_ids) & repeated_core)]
            best_repetitive = _best_candidate(repetitive)
            best_diverse = _best_candidate(diverse)
            delta_text = "n/a"
            if best_repetitive and best_diverse and best_repetitive.score and best_diverse.score:
                calorie_delta = best_diverse.calorie_gap - best_repetitive.calorie_gap
                macro_delta = best_diverse.macro_gap - best_repetitive.macro_gap
                reuse_delta = best_diverse.score[2] - best_repetitive.score[2]
                calorie_deltas.append(calorie_delta)
                macro_deltas.append(macro_delta)
                reuse_deltas.append(reuse_delta)
                delta_text = (
                    f"diverse-minus-repetitive cal_gap={calorie_delta:+.4f}, "
                    f"macro_gap={macro_delta:+.4f}, reuse={reuse_delta:+.2f}"
                )

            completed_distribution[len(completed)] += 1
            unique_set_distribution[len(unique_sets)] += 1
            diverse_available[bool(diverse)] += 1
            repeated_available[bool(repetitive)] += 1

            if printed < max_selection_points:
                selected_ids = {meal.recipe_id for meal in point.selected_plan.meals if meal.recipe_id}
                top_core = _top_shared_core(sorted_completed, repeated_core)
                print(
                    f"  seed {week.week_seed} day {point.day_index + 1}: "
                    f"completed={len(completed)}/{len(point.candidates)}, unique_sets={len(unique_sets)}, "
                    f"selected_core_hits={len(selected_ids & repeated_core)}, "
                    f"top_shared_core={_compact_recipe_ids(top_core, recipes_by_id) if top_core else 'none'}, "
                    f"{delta_text}"
                )
                printed += 1

    if printed >= max_selection_points:
        print(f"  ... truncated at {max_selection_points} selection-point rows")

    print()
    print("Candidate aggregate:")
    print(f"  completed candidate count distribution: {_int_counter_text(completed_distribution)}")
    print(f"  unique recipe-set distribution: {_int_counter_text(unique_set_distribution)}")
    print(f"  diverse candidate available: {_bool_counter_text(diverse_available)}")
    print(f"  repeated-core candidate available: {_bool_counter_text(repeated_available)}")
    if calorie_deltas:
        print(
            "  diverse-minus-repetitive calorie_gap: "
            f"min={min(calorie_deltas):+.4f}, avg={sum(calorie_deltas) / len(calorie_deltas):+.4f}, "
            f"max={max(calorie_deltas):+.4f}"
        )
        print(
            "  diverse-minus-repetitive macro_gap: "
            f"min={min(macro_deltas):+.4f}, avg={sum(macro_deltas) / len(macro_deltas):+.4f}, "
            f"max={max(macro_deltas):+.4f}"
        )
        print(
            "  diverse-minus-repetitive ingredient_reuse_score: "
            f"min={min(reuse_deltas):+.2f}, avg={sum(reuse_deltas) / len(reuse_deltas):+.2f}, "
            f"max={max(reuse_deltas):+.2f}"
        )


def _recipes_present_in_every_week(weeks: tuple[WeekTrace, ...], expected_weeks: int) -> frozenset[str]:
    presence: Counter[str] = Counter()
    for week in weeks:
        presence.update({meal.recipe_id for plan in week.plans for meal in plan.meals if meal.recipe_id})
    return frozenset(recipe_id for recipe_id, count in presence.items() if count == expected_weeks)


def _selected_slots_by_recipe(weeks: tuple[WeekTrace, ...]) -> dict[str, set[str]]:
    slots_by_recipe: dict[str, set[str]] = defaultdict(set)
    for week in weeks:
        for plan in week.plans:
            for meal in plan.meals:
                if meal.recipe_id:
                    slots_by_recipe[meal.recipe_id].add(_meal_slot(meal))
    return slots_by_recipe


def _same_slot_alternative_count(profile: UserProfile, repeated_recipe: RecipeTemplate, slot: str) -> int:
    safety = evaluate_safety(profile)
    targets = calculate_targets(profile)
    candidates = filter_foods(built_in_foods(), safety)
    food_by_id = {food.id: food for food in candidates}
    total_energy = targets.targets.get("energy_kcal")
    energy_slot = _meal_energy_slots(profile.meal_count)[_first_slot_index(profile.meal_count, slot)]
    slot_energy_target = total_energy * energy_slot.target_ratio

    count = 0
    for recipe in built_in_recipes():
        if recipe.id == repeated_recipe.id or "curated" not in recipe.tags:
            continue
        if _resolve_recipe_ingredients(recipe, food_by_id) is None:
            continue
        if _recipe_title_uses_excluded_food(recipe, safety.excluded_food_names):
            continue
        if not _recipe_slot_eligibility(recipe, slot, food_by_id, slot_energy_target, targets.targets).eligible:
            continue
        if not _matches_any_effort_phase(recipe, profile.cooking_time):
            continue
        count += 1
    return count


def _matches_any_effort_phase(recipe: RecipeTemplate, cooking_time: CookingTimePreference) -> bool:
    for phase in _cooking_effort_phases(cooking_time):
        if phase.constraints is None or _recipe_matches_cooking_effort(recipe, phase.constraints):
            return True
    return False


def _first_slot_index(meal_count: int, slot: str) -> int:
    for index, energy_slot in enumerate(_meal_energy_slots(meal_count)):
        if energy_slot.slot == slot:
            return index
    return 0


def _best_candidate(candidates: list[CandidateTrace]) -> CandidateTrace | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda candidate: candidate.score or (-999, -999, -999, -999), reverse=True)[0]


def _top_shared_core(candidates: list[CandidateTrace], repeated_core: frozenset[str]) -> tuple[str, ...]:
    top = candidates[:TOP_SHARED_CORE_CANDIDATES]
    if not top:
        return tuple()
    shared = set(top[0].recipe_ids)
    for candidate in top[1:]:
        shared &= set(candidate.recipe_ids)
    return tuple(sorted(shared & repeated_core))


def _recipe_label(recipe_id: str, recipe: RecipeTemplate | None) -> str:
    if recipe is None:
        return recipe_id
    traits = infer_recipe_traits(recipe)
    number = f"#{traits.recipe_no}" if traits.recipe_no is not None else "#?"
    return f"{recipe.id}/{number} {_short(recipe.title)}"


def _compact_recipe_ids(recipe_ids: tuple[str, ...], recipes_by_id: dict[str, RecipeTemplate]) -> str:
    labels = [_recipe_label(recipe_id, recipes_by_id.get(recipe_id)).split(" ", 1)[0] for recipe_id in recipe_ids]
    return ",".join(labels)


def _short(value: str) -> str:
    if len(value) <= TITLE_LIMIT:
        return value
    return value[: TITLE_LIMIT - 3].rstrip() + "..."


def _source_bucket(recipe: RecipeTemplate | None) -> str:
    if recipe is None:
        return "missing"
    source_batch = infer_recipe_traits(recipe).source_batch
    if source_batch == "r001-r400":
        return "old"
    if source_batch in {"r401-r610", "r611+"}:
        return "new"
    return source_batch


def _calorie_gap(plan: MealPlan) -> float:
    energy = plan.totals.get("energy_kcal")
    target = plan.targets.targets.get("energy_kcal")
    lower, upper = plan.targets.calorie_bounds
    denominator = max(target, 1.0)
    if lower <= energy <= upper:
        return abs(energy - target) / denominator
    if energy < lower:
        return (lower - energy) / denominator
    return (energy - upper) / denominator


def _macro_gap(plan: MealPlan) -> float:
    total = plan.totals
    target = plan.targets.targets
    return (
        _relative_gap(total, target, "energy_kcal") * 3.0
        + _relative_gap(total, target, "protein_g")
        + _relative_gap(total, target, "fat_g")
        + _relative_gap(total, target, "carbohydrate_g")
    )


def _relative_gap(total: NutrientVector, target: NutrientVector, nutrient: str) -> float:
    target_value = target.get(nutrient)
    if target_value <= 0:
        return 0.0
    return abs(total.get(nutrient) - target_value) / target_value


def _int_counter_text(counter: Counter[int]) -> str:
    return ", ".join(f"{key}:{counter[key]}" for key in sorted(counter)) or "none"


def _bool_counter_text(counter: Counter[bool]) -> str:
    return f"yes:{counter[True]}, no:{counter[False]}"


def _counter_pairs(counter: Counter[str]) -> str:
    return ", ".join(f"{key}={counter[key]}" for key in sorted(counter)) or "none"


if __name__ == "__main__":
    raise SystemExit(main())
