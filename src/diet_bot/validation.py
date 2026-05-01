from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .domain import MealPlan
from .safety import is_name_excluded


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_plan(plan: MealPlan) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not plan.safety.can_generate_plan:
        if plan.meals:
            errors.append("Plan was generated despite red flags.")
        return ValidationResult(ok=not errors, errors=tuple(errors), warnings=tuple(plan.safety.red_flags))

    if not plan.meals:
        errors.append("Plan has no meals.")

    food_counts: Counter[str] = Counter()
    food_grams: dict[str, float] = defaultdict(float)
    for meal in plan.meals:
        if not meal.portions:
            errors.append(f"{meal.name} has no ingredients.")
        for portion in meal.portions:
            food = portion.food
            food_counts[food.id] += 1
            food_grams[food.id] += portion.grams
            if portion.grams <= 0:
                errors.append(f"{food.name} has non-positive portion.")
            if portion.grams > food.max_per_meal_g + 0.01:
                errors.append(f"{food.name} exceeds max per meal.")
            if food.has_any_tag(set(plan.safety.excluded_tags)):
                errors.append(f"{food.name} contains excluded tag.")
            if is_name_excluded(food.name, plan.safety.excluded_food_names):
                errors.append(f"{food.name} is excluded by name.")

    for meal in plan.meals:
        for portion in meal.portions:
            if food_grams[portion.food.id] > portion.food.max_per_day_g + 0.01:
                errors.append(f"{portion.food.name} exceeds max per day.")

    for food_id, count in food_counts.items():
        if count > 2:
            warnings.append(f"Food {food_id} appears in more than two meals.")

    totals = plan.totals
    lower, upper = plan.targets.calorie_bounds
    energy = totals.get("energy_kcal")
    if energy < lower:
        warnings.append(f"Energy is below target range: {energy:.0f} kcal.")
    if energy > upper:
        errors.append(f"Energy exceeds target range: {energy:.0f} kcal.")

    for macro, (macro_lower, macro_upper) in plan.targets.macro_bounds.items():
        value = totals.get(macro)
        if value < macro_lower:
            warnings.append(f"{macro} is below target range: {value:.1f}.")
        if value > macro_upper:
            errors.append(f"{macro} exceeds target range: {value:.1f}.")

    sodium = totals.get("sodium_mg")
    sodium_limit = plan.targets.targets.get("sodium_mg")
    if sodium_limit and sodium > sodium_limit:
        errors.append(f"Sodium exceeds limit: {sodium:.0f} mg.")

    return ValidationResult(ok=not errors, errors=tuple(dict.fromkeys(errors)), warnings=tuple(dict.fromkeys(warnings)))
