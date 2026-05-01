from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .calculator import calculate_targets
from .catalog import built_in_foods
from .chef import recipe_for
from .domain import (
    Food,
    FoodPortion,
    Meal,
    MealPlan,
    MealRole,
    NutrientVector,
    SafetyResult,
    UserProfile,
)
from .safety import evaluate_safety, is_name_excluded


PRIORITY_NUTRIENTS = {
    "energy_kcal": 1.0,
    "protein_g": 2.0,
    "fat_g": 0.8,
    "carbohydrate_g": 1.0,
    "fiber_g": 1.7,
    "calcium_mg": 1.2,
    "magnesium_mg": 1.2,
    "potassium_mg": 0.8,
    "iron_mg": 1.0,
    "vitamin_c_mg": 1.0,
    "vitamin_d_mcg": 0.9,
    "vitamin_b12_mcg": 0.8,
    "folate_mcg_dfe": 0.8,
    "omega_3_mg": 0.8,
}

PREFERRED_CATEGORIES: dict[MealRole, tuple[str, ...]] = {
    MealRole.PROTEIN: ("protein", "dairy"),
    MealRole.CARB: ("grains",),
    MealRole.VEGETABLE: ("vegetable",),
    MealRole.FRUIT: ("fruit",),
    MealRole.FAT: ("fat", "nuts_seeds"),
    MealRole.CALCIUM: ("dairy",),
    MealRole.BOOSTER: ("vegetable", "nuts_seeds", "fruit"),
}


@dataclass(frozen=True)
class MealSpec:
    name: str
    roles: tuple[MealRole, ...]


def build_one_day_plan(
    profile: UserProfile,
    foods: list[Food] | None = None,
) -> MealPlan:
    safety = evaluate_safety(profile)
    targets = calculate_targets(profile)
    if not safety.can_generate_plan:
        return MealPlan(meals=(), targets=targets, safety=safety)

    candidates = filter_foods(foods or built_in_foods(), safety)
    if not candidates:
        raise ValueError("No eligible foods after restrictions.")

    used_grams: dict[str, float] = defaultdict(float)
    used_counts: Counter[str] = Counter()
    used_categories: Counter[str] = Counter()
    running_total = NutrientVector()
    meals: list[Meal] = []

    for spec in _meal_specs(profile.meal_count):
        portions: list[FoodPortion] = []
        meal_categories: set[str] = set()
        for role in spec.roles:
            deficit = targets.targets.minus(running_total).clipped_positive()
            food = _select_food(
                candidates=candidates,
                role=role,
                deficit=deficit,
                used_grams=used_grams,
                used_counts=used_counts,
                meal_categories=meal_categories,
            )
            if food is None:
                continue
            grams = _portion_for(food, role, deficit, used_grams)
            if grams <= 0:
                continue
            portion = food.portion(grams)
            portions.append(portion)
            used_grams[food.id] += grams
            used_counts[food.id] += 1
            used_categories[food.category] += 1
            meal_categories.add(food.category)
            running_total = running_total.plus(portion.nutrients)
        meals.append(Meal(spec.name, tuple(portions), recipe_for(spec.name, tuple(portions))))

    meals = _top_up_if_needed(meals, candidates, targets.targets, used_grams, used_counts)
    return MealPlan(meals=tuple(meals), targets=targets, safety=safety)


def filter_foods(foods: list[Food], safety: SafetyResult) -> list[Food]:
    eligible: list[Food] = []
    for food in foods:
        if food.has_any_tag(set(safety.excluded_tags)):
            continue
        if is_name_excluded(food.name, safety.excluded_food_names):
            continue
        eligible.append(food)
    return eligible


def _meal_specs(meal_count: int) -> tuple[MealSpec, ...]:
    count = min(5, max(3, meal_count))
    specs = [
        MealSpec("Завтрак", (MealRole.CARB, MealRole.CALCIUM, MealRole.FRUIT, MealRole.BOOSTER)),
        MealSpec("Обед", (MealRole.PROTEIN, MealRole.CARB, MealRole.VEGETABLE, MealRole.FAT)),
        MealSpec("Ужин", (MealRole.PROTEIN, MealRole.CARB, MealRole.VEGETABLE, MealRole.FAT)),
    ]
    if count >= 4:
        specs.insert(2, MealSpec("Перекус", (MealRole.CALCIUM, MealRole.FRUIT, MealRole.BOOSTER)))
    if count >= 5:
        specs.append(MealSpec("Второй перекус", (MealRole.PROTEIN, MealRole.FRUIT)))
    return tuple(specs)


def _select_food(
    candidates: list[Food],
    role: MealRole,
    deficit: NutrientVector,
    used_grams: dict[str, float],
    used_counts: Counter[str],
    meal_categories: set[str],
) -> Food | None:
    preferred = PREFERRED_CATEGORIES.get(role, ())
    role_candidates = [
        food
        for food in candidates
        if role in food.roles
        and (not preferred or food.category in preferred)
        and _category_allowed_in_meal(food, role, meal_categories)
    ]
    if not role_candidates:
        role_candidates = [
            food
            for food in candidates
            if role in food.roles and _category_allowed_in_meal(food, role, meal_categories)
        ]
    scored = [
        (_score_food(food, role, deficit, used_grams, used_counts, meal_categories), food)
        for food in role_candidates
        if used_grams[food.id] < food.max_per_day_g
    ]
    scored = [item for item in scored if item[0] > -1000]
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _category_allowed_in_meal(food: Food, role: MealRole, meal_categories: set[str]) -> bool:
    if role in {MealRole.PROTEIN, MealRole.CARB, MealRole.FAT, MealRole.CALCIUM}:
        return food.category not in meal_categories
    return True


def _score_food(
    food: Food,
    role: MealRole,
    deficit: NutrientVector,
    used_grams: dict[str, float],
    used_counts: Counter[str],
    meal_categories: set[str],
) -> float:
    grams = _default_portion(food, role)
    vector = food.nutrients_per_100g.scaled(grams / 100)
    score = 0.0
    for nutrient, weight in PRIORITY_NUTRIENTS.items():
        need = deficit.get(nutrient)
        if need <= 0:
            continue
        contribution = min(vector.get(nutrient), need) / need
        score += contribution * weight

    if used_counts[food.id]:
        score -= 2.5 * used_counts[food.id]
    if food.category in meal_categories:
        score -= 1.2
    if food.category == "nuts_seeds" and used_grams[food.id] > 0:
        score -= 4.0
    if vector.get("sodium_mg") > deficit.get("sodium_mg") * 0.5:
        score -= 1.0
    if vector.get("energy_kcal") > max(300, deficit.get("energy_kcal") * 0.45):
        score -= 0.8
    return score


def _portion_for(
    food: Food,
    role: MealRole,
    deficit: NutrientVector,
    used_grams: dict[str, float],
) -> float:
    default = _default_portion(food, role)
    remaining_day = max(0.0, food.max_per_day_g - used_grams[food.id])
    grams = min(default, food.max_per_meal_g, remaining_day)

    energy_per_g = food.nutrients_per_100g.get("energy_kcal") / 100
    if energy_per_g > 0 and deficit.get("energy_kcal") < grams * energy_per_g * 0.6:
        grams = max(0.0, deficit.get("energy_kcal") / energy_per_g)

    return round(grams, 1)


def _default_portion(food: Food, role: MealRole) -> float:
    if food.category == "grains":
        return 60
    if food.category == "protein":
        if food.id == "egg":
            return 100
        if food.id == "lentils":
            return 150
        return 130
    if food.category == "dairy":
        return 170
    if food.category == "vegetable":
        return 150
    if food.category == "fruit":
        return 120
    if food.category == "fat":
        return 10
    if food.category == "nuts_seeds":
        return 15
    return min(100, food.max_per_meal_g)


def _top_up_if_needed(
    meals: list[Meal],
    candidates: list[Food],
    target: NutrientVector,
    used_grams: dict[str, float],
    used_counts: Counter[str],
) -> list[Meal]:
    total = NutrientVector.sum(meal.nutrients for meal in meals)
    lower_energy = target.get("energy_kcal") * 0.88
    if total.get("energy_kcal") >= lower_energy:
        return meals

    dinner = meals[-1]
    portions = list(dinner.portions)
    for role in (MealRole.FAT, MealRole.CARB, MealRole.PROTEIN):
        deficit = target.minus(NutrientVector.sum(meal.nutrients for meal in meals)).clipped_positive()
        meal_categories = {portion.food.category for portion in portions}
        food = _select_food(candidates, role, deficit, used_grams, used_counts, meal_categories)
        if food is None:
            continue
        grams = _portion_for(food, role, deficit, used_grams)
        if grams <= 0:
            continue
        portion = food.portion(grams)
        portions.append(portion)
        used_grams[food.id] += grams
        used_counts[food.id] += 1
        meals[-1] = Meal(dinner.name, tuple(portions), recipe_for(dinner.name, tuple(portions)))
        total = NutrientVector.sum(meal.nutrients for meal in meals)
        if total.get("energy_kcal") >= lower_energy:
            break
    return meals
