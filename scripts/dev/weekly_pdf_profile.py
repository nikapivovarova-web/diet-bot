from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@dataclass(frozen=True)
class SelectionMetrics:
    seconds: float
    avoidance_phase: str
    day_count: int
    meal_count: int
    recipe_count: int
    recipe_key_count: int
    repeated_recipe_slots: int
    repeated_recipe_key_slots: int
    repeated_recipe_ids: tuple[str, ...]
    repeated_recipe_keys: tuple[str, ...]
    detail: "SelectionDetailMetrics | None" = None


@dataclass(frozen=True)
class SelectionStageMetric:
    name: str
    seconds: float
    calls: int


@dataclass(frozen=True)
class WeekPhaseMetric:
    phase: str
    seconds: float
    complete: bool
    day_count: int
    candidate_build_count: int
    build_one_day_plan_calls: int
    avoided_recipe_id_count: int
    avoided_recipe_key_count: int


@dataclass(frozen=True)
class WeekDayMetric:
    phase: str
    day_index: int | None
    seed: int
    seconds: float
    complete: bool
    meal_count: int
    recipe_count: int
    candidate_build_count: int
    selected_candidate_index: int | None
    rescue_used: bool


@dataclass(frozen=True)
class CandidateMetric:
    phase: str
    day_index: int | None
    candidate_index: int | None
    seed: int
    seconds: float
    complete: bool
    meal_count: int
    recipe_count: int
    used_avoided_recipe: bool
    recipe_plan_attempt_count: int
    recipe_plan_seconds: float


@dataclass(frozen=True)
class RecipePlanAttemptMetric:
    phase: str
    day_index: int | None
    candidate_index: int | None
    seed: int
    avoidance_step: str
    seconds: float
    success: bool
    meal_count: int
    avoided_recipe_id_count: int
    avoided_recipe_key_count: int
    allowed_time_buckets: tuple[str, ...] | None
    effort_phase: str


@dataclass(frozen=True)
class WeekDayScoreMetric:
    phase: str
    day_index: int | None
    candidate_index: int
    seconds: float
    score: tuple[float, ...]
    signature: tuple[str, ...]


@dataclass(frozen=True)
class SelectionDetailMetrics:
    build_one_day_plan_calls: int
    candidate_build_count: int
    phase_attempts: tuple[WeekPhaseMetric, ...]
    day_timings: tuple[WeekDayMetric, ...]
    candidate_timings: tuple[CandidateMetric, ...]
    recipe_plan_attempts: tuple[RecipePlanAttemptMetric, ...]
    weekly_day_scores: tuple[WeekDayScoreMetric, ...]
    stage_timings: tuple[SelectionStageMetric, ...]
    cache_stats: tuple[tuple[str, int], ...]
    weekly_trait_lookup_stats: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class PdfPayloadMetrics:
    render_seconds: float
    read_seconds: float
    delete_seconds: float
    page_count_seconds: float
    pdf_bytes: int
    page_count: int | None
    pdf_path: str
    pdf_deleted: bool


@dataclass(frozen=True)
class AssetSummary:
    font_load_count: int
    unique_font_count: int
    image_resolve_count: int
    unique_image_count: int
    missing_image_count: int
    branded_asset_count: int
    unique_branded_asset_count: int
    image_source_count: int
    unique_image_source_count: int
    fonts: tuple[str, ...]
    images: tuple[str, ...]
    missing_images: tuple[str, ...]
    branded_assets: tuple[str, ...]
    image_sources: tuple[str, ...]


@dataclass(frozen=True)
class RunMetrics:
    label: str
    seed: int
    total_weekly_seconds: float
    diagnostic_elapsed_seconds: float
    selection: SelectionMetrics
    pdf: PdfPayloadMetrics
    assets: AssetSummary


@dataclass
class AssetTracker:
    font_loads: list[str] = field(default_factory=list)
    resolved_images: list[str] = field(default_factory=list)
    missing_images: list[str] = field(default_factory=list)
    branded_assets: list[str] = field(default_factory=list)
    image_sources: list[str] = field(default_factory=list)

    def summary(self) -> AssetSummary:
        return AssetSummary(
            font_load_count=len(self.font_loads),
            unique_font_count=len(set(self.font_loads)),
            image_resolve_count=len(self.resolved_images),
            unique_image_count=len(set(self.resolved_images)),
            missing_image_count=len(self.missing_images),
            branded_asset_count=len(self.branded_assets),
            unique_branded_asset_count=len(set(self.branded_assets)),
            image_source_count=len(self.image_sources),
            unique_image_source_count=len(set(self.image_sources)),
            fonts=tuple(sorted(set(self.font_loads))),
            images=tuple(sorted(set(self.resolved_images))),
            missing_images=tuple(sorted(set(self.missing_images))),
            branded_assets=tuple(sorted(set(self.branded_assets))),
            image_sources=tuple(sorted(set(self.image_sources))),
        )


@dataclass
class _StageAccumulator:
    seconds: float = 0.0
    calls: int = 0


@dataclass(frozen=True)
class _ActiveWeekContext:
    phase: str
    base_seed: int
    started_at: float
    candidate_start: int
    day_start: int
    build_call_start: int
    avoided_recipe_id_count: int
    avoided_recipe_key_count: int


@dataclass(frozen=True)
class _ActiveDayContext:
    phase: str
    day_index: int | None
    seed: int
    started_at: float
    candidate_start: int
    score_start: int


@dataclass(frozen=True)
class _ActiveCandidateContext:
    phase: str
    day_index: int | None
    candidate_index: int | None
    seed: int
    started_at: float
    recipe_plan_attempt_start: int
    avoided_recipe_ids: frozenset[str]
    avoided_recipe_keys: frozenset[str]


class SelectionDetailTracker:
    def __init__(self, *, profile: Any, seed: int, recent_avoidance: Any) -> None:
        self.profile = profile
        self.seed = seed
        self.recent_avoidance = recent_avoidance
        self.phase_attempts: list[WeekPhaseMetric] = []
        self.day_timings: list[WeekDayMetric] = []
        self.candidate_timings: list[CandidateMetric] = []
        self.recipe_plan_attempts: list[RecipePlanAttemptMetric] = []
        self.weekly_day_scores: list[WeekDayScoreMetric] = []
        self.recipe_caches: list[Any] = []
        self.weekly_trait_lookups: list[Any] = []
        self._stage_timings: dict[str, _StageAccumulator] = defaultdict(_StageAccumulator)
        self._week_stack: list[_ActiveWeekContext] = []
        self._day_stack: list[_ActiveDayContext] = []
        self._candidate_stack: list[_ActiveCandidateContext] = []
        self.build_one_day_plan_calls = 0

    def summary(self) -> SelectionDetailMetrics:
        stage_timings = tuple(
            SelectionStageMetric(name=name, seconds=metric.seconds, calls=metric.calls)
            for name, metric in sorted(
                self._stage_timings.items(),
                key=lambda item: item[1].seconds,
                reverse=True,
            )
        )
        return SelectionDetailMetrics(
            build_one_day_plan_calls=self.build_one_day_plan_calls,
            candidate_build_count=len(self.candidate_timings),
            phase_attempts=tuple(self.phase_attempts),
            day_timings=tuple(self.day_timings),
            candidate_timings=tuple(self.candidate_timings),
            recipe_plan_attempts=tuple(self.recipe_plan_attempts),
            weekly_day_scores=tuple(self.weekly_day_scores),
            stage_timings=stage_timings,
            cache_stats=self._cache_stats_summary(),
            weekly_trait_lookup_stats=self._weekly_trait_lookup_stats_summary(),
        )

    def record_stage(self, name: str, seconds: float) -> None:
        metric = self._stage_timings[name]
        metric.seconds += seconds
        metric.calls += 1

    def _cache_stats_summary(self) -> tuple[tuple[str, int], ...]:
        stats: Counter[str] = Counter()
        for recipe_cache in self.recipe_caches:
            stats.update(getattr(recipe_cache, "stats", Counter()))
        return tuple(sorted(stats.items()))

    def _weekly_trait_lookup_stats_summary(self) -> tuple[tuple[str, int], ...]:
        stats: Counter[str] = Counter()
        for lookup in self.weekly_trait_lookups:
            stats.update(getattr(lookup, "stats", Counter()))
        return tuple(sorted(stats.items()))

    def classify_week_phase(
        self,
        avoided_recipe_ids: set[str] | frozenset[str],
        avoided_recipe_keys: set[str] | frozenset[str],
    ) -> str:
        avoided_ids = frozenset(avoided_recipe_ids)
        avoided_keys = frozenset(avoided_recipe_keys)
        full_ids = self.recent_avoidance.full_recipe_ids
        full_keys = self.recent_avoidance.full_recipe_keys
        reduced_ids = self.recent_avoidance.reduced_recipe_ids
        reduced_keys = self.recent_avoidance.reduced_recipe_keys
        if not avoided_ids and not avoided_keys:
            return "no_recent"
        if avoided_ids == full_ids and avoided_keys == full_keys:
            return "full_recent"
        if avoided_ids == reduced_ids and avoided_keys == reduced_keys:
            return "reduced_recent"
        return "custom_recent"

    def begin_week(
        self,
        *,
        phase: str,
        base_seed: int,
        avoided_recipe_ids: set[str] | frozenset[str],
        avoided_recipe_keys: set[str] | frozenset[str],
    ) -> _ActiveWeekContext:
        context = _ActiveWeekContext(
            phase=phase,
            base_seed=base_seed,
            started_at=time.perf_counter(),
            candidate_start=len(self.candidate_timings),
            day_start=len(self.day_timings),
            build_call_start=self.build_one_day_plan_calls,
            avoided_recipe_id_count=len(avoided_recipe_ids),
            avoided_recipe_key_count=len(avoided_recipe_keys),
        )
        self._week_stack.append(context)
        return context

    def end_week(self, context: _ActiveWeekContext, plans: Sequence[Any]) -> None:
        complete = _plans_are_complete_without_extra_calls(plans, self.profile)
        self.phase_attempts.append(
            WeekPhaseMetric(
                phase=context.phase,
                seconds=time.perf_counter() - context.started_at,
                complete=complete,
                day_count=len(plans),
                candidate_build_count=len(self.candidate_timings) - context.candidate_start,
                build_one_day_plan_calls=self.build_one_day_plan_calls - context.build_call_start,
                avoided_recipe_id_count=context.avoided_recipe_id_count,
                avoided_recipe_key_count=context.avoided_recipe_key_count,
            )
        )
        if self._week_stack and self._week_stack[-1] is context:
            self._week_stack.pop()

    def begin_day(self, *, seed: int) -> _ActiveDayContext:
        week = self._week_stack[-1] if self._week_stack else None
        day_index = _day_index_for_seed(seed, week.base_seed) if week is not None else None
        context = _ActiveDayContext(
            phase=week.phase if week is not None else "unknown",
            day_index=day_index,
            seed=seed,
            started_at=time.perf_counter(),
            candidate_start=len(self.candidate_timings),
            score_start=len(self.weekly_day_scores),
        )
        self._day_stack.append(context)
        return context

    def end_day(self, context: _ActiveDayContext, plan: Any | None) -> None:
        candidate_count = len(self.candidate_timings) - context.candidate_start
        scores = self.weekly_day_scores[context.score_start:]
        selected_candidate_index = _selected_candidate_index(plan, scores)
        rescue_used = any(
            candidate.candidate_index is not None
            and candidate.candidate_index >= _weekly_candidate_count()
            for candidate in self.candidate_timings[context.candidate_start:]
        )
        self.day_timings.append(
            WeekDayMetric(
                phase=context.phase,
                day_index=context.day_index,
                seed=context.seed,
                seconds=time.perf_counter() - context.started_at,
                complete=_plan_is_complete_without_extra_calls(plan, self.profile),
                meal_count=len(getattr(plan, "meals", ()) or ()),
                recipe_count=len(_recipe_ids_from_plan(plan)),
                candidate_build_count=candidate_count,
                selected_candidate_index=selected_candidate_index,
                rescue_used=rescue_used,
            )
        )
        if self._day_stack and self._day_stack[-1] is context:
            self._day_stack.pop()

    def begin_candidate(
        self,
        *,
        seed: int,
        avoided_recipe_ids: set[str] | frozenset[str],
        avoided_recipe_keys: set[str] | frozenset[str],
    ) -> _ActiveCandidateContext:
        day = self._day_stack[-1] if self._day_stack else None
        candidate_index = seed - day.seed if day is not None else None
        context = _ActiveCandidateContext(
            phase=day.phase if day is not None else "unknown",
            day_index=day.day_index if day is not None else None,
            candidate_index=candidate_index,
            seed=seed,
            started_at=time.perf_counter(),
            recipe_plan_attempt_start=len(self.recipe_plan_attempts),
            avoided_recipe_ids=frozenset(avoided_recipe_ids),
            avoided_recipe_keys=frozenset(avoided_recipe_keys),
        )
        self._candidate_stack.append(context)
        self.build_one_day_plan_calls += 1
        return context

    def end_candidate(self, context: _ActiveCandidateContext, plan: Any | None) -> None:
        attempts = self.recipe_plan_attempts[context.recipe_plan_attempt_start:]
        self.candidate_timings.append(
            CandidateMetric(
                phase=context.phase,
                day_index=context.day_index,
                candidate_index=context.candidate_index,
                seed=context.seed,
                seconds=time.perf_counter() - context.started_at,
                complete=_plan_is_complete_without_extra_calls(plan, self.profile),
                meal_count=len(getattr(plan, "meals", ()) or ()),
                recipe_count=len(_recipe_ids_from_plan(plan)),
                used_avoided_recipe=_plan_uses_avoided_without_extra_calls(
                    plan,
                    context.avoided_recipe_ids,
                    context.avoided_recipe_keys,
                ),
                recipe_plan_attempt_count=len(attempts),
                recipe_plan_seconds=sum(attempt.seconds for attempt in attempts),
            )
        )
        if self._candidate_stack and self._candidate_stack[-1] is context:
            self._candidate_stack.pop()

    def record_recipe_plan_attempt(
        self,
        *,
        seconds: float,
        meals: Sequence[Any],
        avoided_recipe_ids: set[str] | frozenset[str],
        avoided_recipe_keys: set[str] | frozenset[str],
        allowed_time_buckets: Any,
        effort_phase: Any,
        variety_seed: int,
    ) -> None:
        candidate = self._candidate_stack[-1] if self._candidate_stack else None
        avoidance_step = _recipe_plan_avoidance_step(
            candidate,
            avoided_recipe_ids,
            avoided_recipe_keys,
        )
        self.recipe_plan_attempts.append(
            RecipePlanAttemptMetric(
                phase=candidate.phase if candidate is not None else "unknown",
                day_index=candidate.day_index if candidate is not None else None,
                candidate_index=candidate.candidate_index if candidate is not None else None,
                seed=candidate.seed if candidate is not None else variety_seed,
                avoidance_step=avoidance_step,
                seconds=seconds,
                success=bool(meals),
                meal_count=len(meals),
                avoided_recipe_id_count=len(avoided_recipe_ids),
                avoided_recipe_key_count=len(avoided_recipe_keys),
                allowed_time_buckets=_allowed_time_bucket_names(allowed_time_buckets),
                effort_phase=str(getattr(effort_phase, "name", effort_phase)),
            )
        )

    def record_weekly_day_score(
        self,
        *,
        candidate_index: int,
        seconds: float,
        score: tuple[float, ...],
        plan: Any,
    ) -> None:
        day = self._day_stack[-1] if self._day_stack else None
        self.weekly_day_scores.append(
            WeekDayScoreMetric(
                phase=day.phase if day is not None else "unknown",
                day_index=day.day_index if day is not None else None,
                candidate_index=candidate_index,
                seconds=seconds,
                score=score,
                signature=_plan_signature(plan),
            )
        )


def assert_safe_local_environment(env: dict[str, str] | None = None) -> None:
    values = os.environ if env is None else env
    if values.get("DIET_BOT_DATABASE_URL", "").strip():
        raise RuntimeError(
            "Refusing to profile with DIET_BOT_DATABASE_URL set. "
            "Run this diagnostic without production or staging database env."
        )
    if values.get("TELEGRAM_PROVIDER_TOKEN", "").strip():
        raise RuntimeError(
            "Refusing to profile with TELEGRAM_PROVIDER_TOKEN set. "
            "Payments are intentionally disabled for this local diagnostic."
        )


@contextmanager
def track_weekly_selection(profile: Any, seed: int, recent_avoidance: Any):
    import diet_bot.builder as builder
    import diet_bot.telegram_app as telegram_app

    tracker = SelectionDetailTracker(
        profile=profile,
        seed=seed,
        recent_avoidance=recent_avoidance,
    )
    originals: list[tuple[Any, str, Any]] = []

    def patch(module: Any, name: str, replacement: Any) -> None:
        original = getattr(module, name)
        originals.append((module, name, original))
        setattr(module, name, replacement)

    def timed_stage(name: str, original: Any):
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                tracker.record_stage(name, time.perf_counter() - started)

        return wrapper

    original_recipe_cache_cls = getattr(telegram_app, "_RecipePlanCache", None)
    if original_recipe_cache_cls is not None:
        class TrackingRecipePlanCache(original_recipe_cache_cls):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                tracker.recipe_caches.append(self)

        patch(telegram_app, "_RecipePlanCache", TrackingRecipePlanCache)

    original_weekly_trait_lookup_cls = getattr(telegram_app, "_WeeklyRecipeTraitLookup", None)
    if original_weekly_trait_lookup_cls is not None:
        class TrackingWeeklyRecipeTraitLookup(original_weekly_trait_lookup_cls):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                tracker.weekly_trait_lookups.append(self)

            def get(self, recipe_id):
                started = time.perf_counter()
                try:
                    return super().get(recipe_id)
                finally:
                    tracker.record_stage("weekly_trait_lookup_get", time.perf_counter() - started)

        patch(telegram_app, "_WeeklyRecipeTraitLookup", TrackingWeeklyRecipeTraitLookup)

    original_build_week_plans = telegram_app._build_week_plans

    def build_week_plans(profile_arg, seed_arg, avoided_recipe_ids, avoided_recipe_keys, *args, **kwargs):
        phase = tracker.classify_week_phase(avoided_recipe_ids, avoided_recipe_keys)
        context = tracker.begin_week(
            phase=phase,
            base_seed=seed_arg,
            avoided_recipe_ids=avoided_recipe_ids,
            avoided_recipe_keys=avoided_recipe_keys,
        )
        plans: Sequence[Any] = ()
        try:
            plans = original_build_week_plans(
                profile_arg,
                seed_arg,
                avoided_recipe_ids,
                avoided_recipe_keys,
                *args,
                **kwargs,
            )
            return plans
        finally:
            tracker.end_week(context, plans)

    patch(telegram_app, "_build_week_plans", build_week_plans)

    original_select_week_day_plan = telegram_app._select_week_day_plan

    def select_week_day_plan(profile_arg, seed_arg, *args, **kwargs):
        context = tracker.begin_day(seed=seed_arg)
        plan = None
        try:
            result = original_select_week_day_plan(profile_arg, seed_arg, *args, **kwargs)
            plan = result[0] if result else None
            return result
        finally:
            tracker.end_day(context, plan)

    patch(telegram_app, "_select_week_day_plan", select_week_day_plan)

    original_build_one_day_plan = telegram_app.build_one_day_plan

    def build_one_day_plan(profile_arg, *args, **kwargs):
        variety_seed = int(_call_arg(args, kwargs, "variety_seed", 1, 0) or 0)
        avoided_recipe_ids = frozenset(
            _call_arg(args, kwargs, "avoided_recipe_ids", 2, frozenset()) or frozenset()
        )
        avoided_recipe_keys = frozenset(
            _call_arg(args, kwargs, "avoided_recipe_keys", 3, frozenset()) or frozenset()
        )
        context = tracker.begin_candidate(
            seed=variety_seed,
            avoided_recipe_ids=avoided_recipe_ids,
            avoided_recipe_keys=avoided_recipe_keys,
        )
        plan = None
        started = time.perf_counter()
        try:
            plan = original_build_one_day_plan(profile_arg, *args, **kwargs)
            return plan
        finally:
            tracker.record_stage("build_one_day_plan", time.perf_counter() - started)
            tracker.end_candidate(context, plan)

    patch(telegram_app, "build_one_day_plan", build_one_day_plan)

    original_build_recipe_plan_for_time = builder._build_recipe_plan_for_time

    def build_recipe_plan_for_time(*args, **kwargs):
        variety_seed_arg = int(_call_arg(args, kwargs, "variety_seed", 4, 0) or 0)
        avoided_recipe_ids = frozenset(
            _call_arg(args, kwargs, "avoided_recipe_ids", 5, frozenset()) or frozenset()
        )
        avoided_recipe_keys = frozenset(
            _call_arg(args, kwargs, "avoided_recipe_keys", 6, frozenset()) or frozenset()
        )
        started = time.perf_counter()
        meals: Sequence[Any] = ()
        try:
            meals = original_build_recipe_plan_for_time(*args, **kwargs)
            return meals
        finally:
            seconds = time.perf_counter() - started
            tracker.record_stage("recipe_selection_total", seconds)
            tracker.record_recipe_plan_attempt(
                seconds=seconds,
                meals=meals,
                avoided_recipe_ids=avoided_recipe_ids,
                avoided_recipe_keys=avoided_recipe_keys,
                allowed_time_buckets=None,
                effort_phase=None,
                variety_seed=variety_seed_arg,
            )

    patch(builder, "_build_recipe_plan_for_time", build_recipe_plan_for_time)

    original_weekly_day_selection_score = telegram_app._weekly_day_selection_score

    def weekly_day_selection_score(plan, week_food_ids, candidate_index, *args, **kwargs):
        started = time.perf_counter()
        score = original_weekly_day_selection_score(
            plan,
            week_food_ids,
            candidate_index,
            *args,
            **kwargs,
        )
        seconds = time.perf_counter() - started
        tracker.record_stage("weekly_day_score", seconds)
        tracker.record_weekly_day_score(
            candidate_index=candidate_index,
            seconds=seconds,
            score=tuple(float(value) for value in score),
            plan=plan,
        )
        return score

    patch(telegram_app, "_weekly_day_selection_score", weekly_day_selection_score)

    for module, name, stage_name in (
        (builder, "filter_foods", "food_filter"),
        (builder, "_build_recipe_plan", "recipe_plan_build"),
        (builder, "_rank_recipes", "recipe_rank_filter_score_sort"),
        (builder, "_select_best_hard_valid_meals", "hard_valid_candidate_selection"),
        (builder, "_passes_hard_nutrition_gates", "hard_nutrition_validation"),
        (telegram_app, "_week_day_plan_is_complete", "weekly_day_complete_validation"),
        (telegram_app, "_plan_uses_avoided_recipes", "weekly_recent_candidate_validation"),
        (telegram_app, "_carryovers_use_avoided_recipes", "weekly_carryover_recent_validation"),
        (telegram_app, "_candidate_recipe_counts", "weekly_candidate_pool_count"),
        (telegram_app, "_weekly_completed_day_diversity_penalty", "weekly_diversity_penalty"),
        (telegram_app, "_ingredient_reuse_score", "weekly_ingredient_reuse_score"),
        (telegram_app, "_recipe_traits_by_id", "weekly_recipe_traits_lookup"),
    ):
        patch(module, name, timed_stage(stage_name, getattr(module, name)))

    try:
        yield tracker
    finally:
        for module, name, original in reversed(originals):
            setattr(module, name, original)


def _call_arg(args: tuple[Any, ...], kwargs: dict[str, Any], name: str, index: int, default: Any) -> Any:
    if name in kwargs:
        return kwargs[name]
    if len(args) > index:
        return args[index]
    return default


def _expected_meal_count_for(profile: Any) -> int:
    return min(5, max(3, int(getattr(profile, "meal_count", 0) or 0)))


def _plan_is_complete_without_extra_calls(plan: Any | None, profile: Any) -> bool:
    if plan is None:
        return False
    safety = getattr(plan, "safety", None)
    return bool(getattr(safety, "can_generate_plan", False)) and len(getattr(plan, "meals", ()) or ()) == _expected_meal_count_for(profile)


def _plans_are_complete_without_extra_calls(plans: Sequence[Any], profile: Any) -> bool:
    import diet_bot.telegram_app as telegram_app

    return len(plans) == telegram_app.WEEK_PLAN_DAYS and all(
        _plan_is_complete_without_extra_calls(plan, profile) for plan in plans
    )


def _weekly_candidate_count() -> int:
    import diet_bot.telegram_app as telegram_app

    return int(telegram_app.WEEK_PLAN_CANDIDATE_COUNT)


def _day_index_for_seed(seed: int, base_seed: int) -> int | None:
    candidate_count = _weekly_candidate_count()
    if candidate_count <= 0:
        return None
    offset = seed - base_seed
    if offset < 0 or offset % candidate_count != 0:
        return None
    return offset // candidate_count


def _recipe_ids_from_plan(plan: Any | None) -> tuple[str, ...]:
    return tuple(
        str(meal.recipe_id)
        for meal in getattr(plan, "meals", ()) or ()
        if getattr(meal, "recipe_id", None)
    )


def _recipe_keys_from_plan(plan: Any | None) -> tuple[str, ...]:
    return tuple(
        str(meal.recipe_key)
        for meal in getattr(plan, "meals", ()) or ()
        if getattr(meal, "recipe_key", None)
    )


def _plan_signature(plan: Any | None) -> tuple[str, ...]:
    return _recipe_ids_from_plan(plan)


def _selected_candidate_index(plan: Any | None, scores: Sequence[WeekDayScoreMetric]) -> int | None:
    signature = _plan_signature(plan)
    if not signature:
        return None
    matching = [score for score in scores if score.signature == signature]
    if not matching:
        return None
    return max(matching, key=lambda score: score.score).candidate_index


def _plan_uses_avoided_without_extra_calls(
    plan: Any | None,
    avoided_recipe_ids: frozenset[str],
    avoided_recipe_keys: frozenset[str],
) -> bool:
    recipe_ids = set(_recipe_ids_from_plan(plan))
    recipe_keys = set(_recipe_keys_from_plan(plan))
    return bool((avoided_recipe_ids & recipe_ids) or (avoided_recipe_keys & recipe_keys))


def _recipe_plan_avoidance_step(
    candidate: _ActiveCandidateContext | None,
    avoided_recipe_ids: set[str] | frozenset[str],
    avoided_recipe_keys: set[str] | frozenset[str],
) -> str:
    ids = frozenset(avoided_recipe_ids)
    keys = frozenset(avoided_recipe_keys)
    if candidate is None:
        if ids or keys:
            return "recent_avoidance"
        return "no_recent"
    original_ids = candidate.avoided_recipe_ids
    original_keys = candidate.avoided_recipe_keys
    if ids == original_ids and keys == original_keys:
        if ids or keys:
            return "strict_avoidance"
        return "no_recent"
    if ids == original_ids and not keys and original_keys:
        return "recipe_keys_relaxed"
    if not ids and not keys and (original_ids or original_keys):
        return "all_avoidance_relaxed"
    return "custom_avoidance"


def _allowed_time_bucket_names(allowed_time_buckets: Any) -> tuple[str, ...] | None:
    if allowed_time_buckets is None:
        return None
    try:
        return tuple(sorted(str(value) for value in allowed_time_buckets))
    except TypeError:
        return (str(allowed_time_buckets),)


def measure_pdf_payload(
    *,
    plans: Sequence[Any],
    plan_dates: Sequence[date],
    output_dir: Path,
    keep_pdf: bool,
    count_pages: bool,
    build_week_plan_pdf_func: Callable[..., Path] | None = None,
) -> PdfPayloadMetrics:
    if build_week_plan_pdf_func is None:
        from diet_bot.pdf_renderer import build_week_plan_pdf as build_week_plan_pdf_func

    render_started = time.perf_counter()
    pdf_path = Path(build_week_plan_pdf_func(plans, plan_dates, output_dir=output_dir))
    render_seconds = time.perf_counter() - render_started

    pdf_data = b""
    read_started = time.perf_counter()
    try:
        pdf_data = pdf_path.read_bytes()
    finally:
        read_seconds = time.perf_counter() - read_started

    page_count_started = time.perf_counter()
    page_count = _count_pdf_pages(pdf_data) if count_pages else None
    page_count_seconds = time.perf_counter() - page_count_started

    deleted = False
    delete_started = time.perf_counter()
    try:
        if not keep_pdf:
            with suppress(OSError):
                pdf_path.unlink()
            deleted = not pdf_path.exists()
    finally:
        delete_seconds = time.perf_counter() - delete_started

    return PdfPayloadMetrics(
        render_seconds=render_seconds,
        read_seconds=read_seconds,
        delete_seconds=delete_seconds,
        page_count_seconds=page_count_seconds,
        pdf_bytes=len(pdf_data),
        page_count=page_count,
        pdf_path=str(pdf_path),
        pdf_deleted=deleted,
    )


def profile_weekly_pdf_once(
    *,
    label: str,
    profile: Any,
    seed: int,
    recent_avoidance: Any,
    output_dir: Path,
    keep_pdf: bool,
    count_pages: bool,
) -> RunMetrics:
    from diet_bot.telegram_app import _build_week_plans_with_recent_fallback, _week_plan_dates

    diagnostic_started = time.perf_counter()

    selection_started = time.perf_counter()
    with track_weekly_selection(profile, seed, recent_avoidance) as selection_tracker:
        build_result = _build_week_plans_with_recent_fallback(profile, seed, recent_avoidance)
    selection_seconds = time.perf_counter() - selection_started

    plans = tuple(build_result.plans)
    if not plans:
        raise RuntimeError(
            f"Weekly plan selection returned no complete plans for seed={seed} "
            f"phase={build_result.avoidance_phase!r}."
        )

    plan_dates = _week_plan_dates()
    recipe_ids = {
        meal.recipe_id
        for plan in plans
        for meal in plan.meals
        if getattr(meal, "recipe_id", None)
    }
    recipe_id_values = [
        str(meal.recipe_id)
        for plan in plans
        for meal in plan.meals
        if getattr(meal, "recipe_id", None)
    ]
    recipe_key_values = [
        str(meal.recipe_key)
        for plan in plans
        for meal in plan.meals
        if getattr(meal, "recipe_key", None)
    ]
    recipe_id_counts = Counter(recipe_id_values)
    recipe_key_counts = Counter(recipe_key_values)
    selection = SelectionMetrics(
        seconds=selection_seconds,
        avoidance_phase=str(build_result.avoidance_phase),
        day_count=len(plans),
        meal_count=sum(len(plan.meals) for plan in plans),
        recipe_count=len(recipe_ids),
        recipe_key_count=len(set(recipe_key_values)),
        repeated_recipe_slots=len(recipe_id_values) - len(recipe_ids),
        repeated_recipe_key_slots=len(recipe_key_values) - len(set(recipe_key_values)),
        repeated_recipe_ids=tuple(sorted(recipe_id for recipe_id, count in recipe_id_counts.items() if count > 1)),
        repeated_recipe_keys=tuple(sorted(recipe_key for recipe_key, count in recipe_key_counts.items() if count > 1)),
        detail=selection_tracker.summary(),
    )

    with track_pdf_assets() as tracker:
        pdf_metrics = measure_pdf_payload(
            plans=plans,
            plan_dates=plan_dates,
            output_dir=output_dir,
            keep_pdf=keep_pdf,
            count_pages=count_pages,
        )

    total_weekly_seconds = (
        selection.seconds
        + pdf_metrics.render_seconds
        + pdf_metrics.read_seconds
        + pdf_metrics.delete_seconds
    )
    diagnostic_elapsed_seconds = time.perf_counter() - diagnostic_started
    return RunMetrics(
        label=label,
        seed=seed,
        total_weekly_seconds=total_weekly_seconds,
        diagnostic_elapsed_seconds=diagnostic_elapsed_seconds,
        selection=selection,
        pdf=pdf_metrics,
        assets=tracker.summary(),
    )


@contextmanager
def track_pdf_assets():
    import diet_bot.pdf_renderer as pdf_renderer

    tracker = AssetTracker()
    originals: dict[str, Any] = {}

    def remember(name: str) -> Any:
        original = getattr(pdf_renderer, name)
        originals[name] = original
        return original

    original_resolve = remember("resolve_local_meal_image_path")

    def resolve_local_meal_image_path(meal):
        resolved = original_resolve(meal)
        if resolved is None:
            raw = getattr(meal, "image_url", None)
            if raw:
                tracker.missing_images.append(str(raw))
        else:
            tracker.resolved_images.append(str(Path(resolved)))
        return resolved

    pdf_renderer.resolve_local_meal_image_path = resolve_local_meal_image_path

    original_asset_image = remember("_asset_image")

    def asset_image(path, max_width, max_height):
        tracker.branded_assets.append(str(Path(path)))
        return original_asset_image(path, max_width, max_height)

    pdf_renderer._asset_image = asset_image

    original_cover_logo = remember("_cover_logo_image")

    def cover_logo_image(max_width, max_height):
        tracker.branded_assets.append(str(pdf_renderer.PDF_LOGO_PATH))
        return original_cover_logo(max_width, max_height)

    pdf_renderer._cover_logo_image = cover_logo_image

    original_image_from_source = remember("_image_from_source")

    def image_from_source(source, max_width, max_height):
        tracker.image_sources.append(_source_label(source))
        return original_image_from_source(source, max_width, max_height)

    pdf_renderer._image_from_source = image_from_source

    image_source_hook_name = next(
        (
            name
            for name in ("_fixed_box_image_source", "_cropped_image_source")
            if hasattr(pdf_renderer, name)
        ),
        None,
    )
    if image_source_hook_name is None:
        raise RuntimeError("pdf_renderer has no supported meal image source hook")
    original_image_source_hook = remember(image_source_hook_name)

    def tracked_image_source(image_path):
        tracker.image_sources.append(str(Path(image_path)))
        return original_image_source_hook(image_path)

    setattr(pdf_renderer, image_source_hook_name, tracked_image_source)

    original_ttfont = remember("TTFont")

    def ttfont(name, filename, *args, **kwargs):
        tracker.font_loads.append(f"{name}:{filename}")
        return original_ttfont(name, filename, *args, **kwargs)

    pdf_renderer.TTFont = ttfont

    try:
        yield tracker
    finally:
        for name, original in originals.items():
            setattr(pdf_renderer, name, original)


def make_profile(profile_key: str):
    from diet_bot.domain import (
        ActivityLevel,
        CookingTimePreference,
        Goal,
        Restriction,
        RestrictionType,
        Sex,
        UserProfile,
    )

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
    if profile_key == "A":
        return UserProfile(**base)
    if profile_key == "B":
        return UserProfile(
            **base,
            restrictions=(
                Restriction(RestrictionType.ALLERGY, "eggs"),
                Restriction(RestrictionType.EXCLUDED_FOOD, "dairy"),
                Restriction(RestrictionType.EXCLUDED_FOOD, "porridge"),
                Restriction(RestrictionType.EXCLUDED_FOOD, "mushrooms"),
            ),
        )
    raise ValueError(f"Unsupported profile key: {profile_key!r}")


def make_recent_avoidance(
    *,
    full_recipe_ids: Sequence[str],
    full_recipe_keys: Sequence[str],
    reduced_recipe_ids: Sequence[str],
    reduced_recipe_keys: Sequence[str],
):
    from diet_bot.telegram_app import _RecentRecipeAvoidance

    return _RecentRecipeAvoidance(
        full_recipe_ids=frozenset(full_recipe_ids),
        full_recipe_keys=frozenset(full_recipe_keys),
        reduced_recipe_ids=frozenset(reduced_recipe_ids),
        reduced_recipe_keys=frozenset(reduced_recipe_keys),
    )


def _count_pdf_pages(pdf_data: bytes) -> int | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None

    try:
        return len(PdfReader(BytesIO(pdf_data)).pages)
    except Exception:
        return None


def _source_label(source: Any) -> str:
    if isinstance(source, (str, Path)):
        return str(Path(source))
    name = getattr(source, "name", None)
    if name:
        return str(name)
    return f"<{type(source).__name__}>"


def _run_labels(runs: int) -> list[str]:
    if runs <= 1:
        return ["single"]
    return ["cold-ish"] + [f"warm-{index}" for index in range(1, runs)]


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / (1024 * 1024):.2f} MiB"


def _print_report(runs: Sequence[RunMetrics], *, asset_detail_limit: int) -> None:
    print("Weekly PDF local profile")
    print("Safety: Telegram API not used; DIET_BOT_DATABASE_URL and TELEGRAM_PROVIDER_TOKEN must be unset.")
    print()
    for run in runs:
        print(f"[{run.label}] seed={run.seed}")
        print(f"  total_weekly_pdf: {run.total_weekly_seconds:.3f}s")
        print(
            "  build_week_plans_with_recent_fallback: "
            f"{run.selection.seconds:.3f}s "
            f"(phase={run.selection.avoidance_phase}, days={run.selection.day_count}, "
            f"meals={run.selection.meal_count}, recipes={run.selection.recipe_count}, "
            f"recipe_keys={run.selection.recipe_key_count}, "
            f"recipe_repeats={run.selection.repeated_recipe_slots}, "
            f"recipe_key_repeats={run.selection.repeated_recipe_key_slots})"
        )
        if run.selection.repeated_recipe_ids or run.selection.repeated_recipe_keys:
            print(
                "  repeated recipes: "
                f"ids={_short_tuple(run.selection.repeated_recipe_ids)} "
                f"keys={_short_tuple(run.selection.repeated_recipe_keys)}"
            )
        _print_selection_details(run.selection.detail)
        print(f"  build_week_plan_pdf/render: {run.pdf.render_seconds:.3f}s")
        print(f"  temp_pdf_read: {run.pdf.read_seconds:.4f}s")
        print(f"  temp_pdf_delete: {run.pdf.delete_seconds:.4f}s deleted={run.pdf.pdf_deleted}")
        page_text = "n/a" if run.pdf.page_count is None else str(run.pdf.page_count)
        print(
            f"  pdf: {_format_bytes(run.pdf.pdf_bytes)} pages={page_text} "
            f"page_count_overhead={run.pdf.page_count_seconds:.4f}s"
        )
        print(
            "  assets: "
            f"fonts={run.assets.font_load_count}/{run.assets.unique_font_count} unique, "
            f"images={run.assets.image_resolve_count}/{run.assets.unique_image_count} unique, "
            f"missing_images={run.assets.missing_image_count}, "
            f"branded_assets={run.assets.branded_asset_count}/{run.assets.unique_branded_asset_count} unique"
        )
        _print_asset_details(run.assets, limit=asset_detail_limit)
        print()

    if len(runs) >= 2:
        cold = runs[0].total_weekly_seconds
        warm = runs[1].total_weekly_seconds
        delta = warm - cold
        print(f"warm_vs_coldish_delta: {delta:+.3f}s ({_percent_delta(warm, cold)})")


def _print_selection_details(detail: SelectionDetailMetrics | None) -> None:
    if detail is None:
        return
    print(
        "  selection detail: "
        f"build_one_day_plan_calls={detail.build_one_day_plan_calls}, "
        f"candidates_built={detail.candidate_build_count}"
    )
    if detail.phase_attempts:
        print("    weekly phases:")
        for phase in detail.phase_attempts:
            print(
                "      - "
                f"{phase.phase}: {phase.seconds:.3f}s complete={phase.complete} "
                f"days={phase.day_count} candidates={phase.candidate_build_count} "
                f"build_one_day_calls={phase.build_one_day_plan_calls} "
                f"avoided_ids={phase.avoided_recipe_id_count} "
                f"avoided_keys={phase.avoided_recipe_key_count}"
            )

    if detail.day_timings:
        print("    day timings:")
        candidates_by_day = _candidate_timings_by_day(detail.candidate_timings)
        for day in detail.day_timings:
            label = _day_label(day.day_index)
            selected = "n/a" if day.selected_candidate_index is None else f"c{day.selected_candidate_index}"
            print(
                "      - "
                f"{label} phase={day.phase} seed={day.seed}: {day.seconds:.3f}s "
                f"complete={day.complete} candidates={day.candidate_build_count} "
                f"selected={selected} rescue={day.rescue_used} "
                f"meals={day.meal_count} recipes={day.recipe_count}"
            )
            candidate_line = _candidate_timing_line(
                candidates_by_day.get((day.phase, day.day_index), ())
            )
            if candidate_line:
                print(f"        candidates: {candidate_line}")

    if detail.recipe_plan_attempts:
        print("    build_one_day_plan avoidance attempts:")
        for step, attempts in _group_recipe_attempts(detail.recipe_plan_attempts).items():
            seconds = sum(attempt.seconds for attempt in attempts)
            successes = sum(1 for attempt in attempts if attempt.success)
            print(
                "      - "
                f"{step}: calls={len(attempts)} success={successes} "
                f"time={seconds:.3f}s"
            )

    if detail.stage_timings:
        print("    stage timings (nested, not exclusive):")
        for metric in detail.stage_timings[:10]:
            print(f"      - {metric.name}: {metric.seconds:.3f}s calls={metric.calls}")

    trait_lookup_metric = _stage_metric(detail.stage_timings, "weekly_trait_lookup_get")
    if trait_lookup_metric is not None:
        print(
            "    weekly trait lookup time: "
            f"{trait_lookup_metric.seconds:.3f}s calls={trait_lookup_metric.calls}"
        )

    if detail.weekly_trait_lookup_stats:
        print("    weekly trait lookup stats:")
        for name, value in detail.weekly_trait_lookup_stats:
            print(f"      - {name}: {value}")

    if detail.cache_stats:
        print("    recipe cache stats:")
        for name, value in detail.cache_stats:
            print(f"      - {name}: {value}")

    top_day_ops = sorted(detail.day_timings, key=lambda item: item.seconds, reverse=True)[:5]
    top_candidate_ops = sorted(detail.candidate_timings, key=lambda item: item.seconds, reverse=True)[:5]
    if top_day_ops:
        print("    top-5 day operations:")
        for day in top_day_ops:
            print(
                "      - "
                f"{_day_label(day.day_index)} phase={day.phase} "
                f"seed={day.seed}: {day.seconds:.3f}s"
            )
    if top_candidate_ops:
        print("    top-5 candidate operations:")
        for candidate in top_candidate_ops:
            print(
                "      - "
                f"{_day_label(candidate.day_index)} c{_optional_index(candidate.candidate_index)} "
                f"phase={candidate.phase} seed={candidate.seed}: {candidate.seconds:.3f}s "
                f"attempts={candidate.recipe_plan_attempt_count} complete={candidate.complete}"
            )


def _candidate_timings_by_day(
    candidates: Sequence[CandidateMetric],
) -> dict[tuple[str, int | None], list[CandidateMetric]]:
    grouped: dict[tuple[str, int | None], list[CandidateMetric]] = defaultdict(list)
    for candidate in candidates:
        grouped[(candidate.phase, candidate.day_index)].append(candidate)
    return grouped


def _stage_metric(
    stage_timings: Sequence[SelectionStageMetric],
    name: str,
) -> SelectionStageMetric | None:
    return next((metric for metric in stage_timings if metric.name == name), None)


def _candidate_timing_line(candidates: Sequence[CandidateMetric]) -> str:
    if not candidates:
        return ""
    parts = []
    for candidate in sorted(
        candidates,
        key=lambda item: (999 if item.candidate_index is None else item.candidate_index),
    ):
        label = f"c{_optional_index(candidate.candidate_index)}"
        status = "ok" if candidate.complete else "reject"
        avoided = ",used_avoided" if candidate.used_avoided_recipe else ""
        parts.append(
            f"{label}={candidate.seconds:.3f}s/{status}"
            f"/attempts={candidate.recipe_plan_attempt_count}{avoided}"
        )
    return ", ".join(parts)


def _group_recipe_attempts(
    attempts: Sequence[RecipePlanAttemptMetric],
) -> dict[str, list[RecipePlanAttemptMetric]]:
    grouped: dict[str, list[RecipePlanAttemptMetric]] = defaultdict(list)
    for attempt in attempts:
        grouped[attempt.avoidance_step].append(attempt)
    return dict(sorted(grouped.items(), key=lambda item: item[0]))


def _day_label(day_index: int | None) -> str:
    if day_index is None:
        return "day ?"
    return f"day {day_index + 1}"


def _optional_index(value: int | None) -> str:
    return "?" if value is None else str(value)


def _short_tuple(values: Sequence[str], limit: int = 8) -> str:
    if not values:
        return "()"
    shown = tuple(values[:limit])
    suffix = "" if len(values) <= limit else f", ... +{len(values) - limit}"
    return f"({', '.join(shown)}{suffix})"


def _print_asset_details(summary: AssetSummary, *, limit: int) -> None:
    for label, values in (
        ("fonts", summary.fonts),
        ("images", summary.images),
        ("branded", summary.branded_assets),
        ("sources", summary.image_sources),
    ):
        shown = values[:limit]
        if not shown:
            continue
        suffix = "" if len(values) <= limit else f" ... +{len(values) - limit}"
        print(f"    {label}:")
        for value in shown:
            print(f"      - {value}")
        if suffix:
            print(f"      {suffix}")


def _percent_delta(value: float, baseline: float) -> str:
    if baseline <= 0:
        return "n/a"
    return f"{((value - baseline) / baseline * 100):+.1f}%"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local weekly PDF profiler without Telegram, payments, or production DB."
    )
    parser.add_argument("--profile", choices=("A", "B"), default="A")
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--increment-seed", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "tmp" / "weekly_pdf_profile")
    parser.add_argument("--keep-pdfs", action="store_true")
    parser.add_argument("--no-page-count", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--asset-detail-limit", type=int, default=12)
    parser.add_argument("--avoid-recipe-id", action="append", default=[])
    parser.add_argument("--avoid-recipe-key", action="append", default=[])
    parser.add_argument("--reduced-avoid-recipe-id", action="append", default=[])
    parser.add_argument("--reduced-avoid-recipe-key", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    assert_safe_local_environment()

    run_count = max(1, args.runs)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = make_profile(args.profile)
    recent_avoidance = make_recent_avoidance(
        full_recipe_ids=args.avoid_recipe_id,
        full_recipe_keys=args.avoid_recipe_key,
        reduced_recipe_ids=args.reduced_avoid_recipe_id or args.avoid_recipe_id,
        reduced_recipe_keys=args.reduced_avoid_recipe_key or args.avoid_recipe_key,
    )

    runs: list[RunMetrics] = []
    for index, label in enumerate(_run_labels(run_count)):
        run_seed = args.seed + index if args.increment_seed else args.seed
        runs.append(
            profile_weekly_pdf_once(
                label=label,
                profile=profile,
                seed=run_seed,
                recent_avoidance=recent_avoidance,
                output_dir=output_dir,
                keep_pdf=args.keep_pdfs,
                count_pages=not args.no_page_count,
            )
        )

    if args.as_json:
        print(json.dumps([asdict(run) for run in runs], ensure_ascii=False, indent=2))
    else:
        _print_report(runs, asset_detail_limit=max(0, args.asset_detail_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
