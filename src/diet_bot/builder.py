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
from .recipe_catalog import RecipeTemplate, built_in_recipes
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
    variety_seed: int = 0,
) -> MealPlan:
    safety = evaluate_safety(profile)
    targets = calculate_targets(profile)
    if not safety.can_generate_plan:
        return MealPlan(meals=(), targets=targets, safety=safety)

    candidates = filter_foods(foods or built_in_foods(), safety)
    if not candidates:
        raise ValueError("No eligible foods after restrictions.")

    recipe_meals = _build_recipe_plan(candidates, targets.targets, profile.meal_count, variety_seed)
    if recipe_meals:
        return MealPlan(meals=tuple(recipe_meals), targets=targets, safety=safety)

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
                variety_seed=variety_seed,
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

    meals = _top_up_if_needed(meals, candidates, targets.targets, used_grams, used_counts, variety_seed)
    return MealPlan(meals=tuple(meals), targets=targets, safety=safety)


def _build_recipe_plan(
    candidates: list[Food],
    target: NutrientVector,
    meal_count: int,
    variety_seed: int,
) -> list[Meal]:
    food_by_id = {food.id: food for food in candidates}
    recipes = [
        recipe
        for recipe in built_in_recipes()
        if _resolve_recipe_ingredients(recipe, food_by_id) is not None
    ]
    if not recipes:
        return []

    used_recipe_ids: set[str] = set()
    used_food_ids: Counter[str] = Counter()
    used_grams: dict[str, float] = defaultdict(float)
    meals: list[Meal] = []
    total_energy = target.get("energy_kcal")
    slots = _recipe_slots(meal_count)

    for index, (slot, ratio) in enumerate(slots):
        recipe = _select_recipe(recipes, slot, used_recipe_ids, used_food_ids, variety_seed, index)
        if recipe is None:
            continue
        resolved = _resolve_recipe_ingredients(recipe, food_by_id)
        if resolved is None:
            continue
        base_energy = NutrientVector.sum(food.portion(grams).nutrients for food, grams in resolved).get("energy_kcal")
        scale = _recipe_scale((total_energy * ratio), base_energy)
        portions = _scaled_recipe_portions(resolved, scale, used_grams)
        if not portions:
            continue
        used_recipe_ids.add(recipe.id)
        for portion in portions:
            used_food_ids[portion.food.id] += 1
            used_grams[portion.food.id] += portion.grams
        meals.append(
            Meal(
                name=f"{_meal_emoji(slot, index)} {_meal_name(slot, index)}: {recipe.title}",
                portions=tuple(portions),
                recipe=recipe.instructions,
                image_url=recipe.image_url,
                image_attribution=recipe.image_attribution,
                source_url=recipe.source_url,
            )
        )

    if len(meals) < min(3, meal_count):
        return []
    return _increase_existing_portions(meals, target, used_grams)


def _recipe_slots(meal_count: int) -> tuple[tuple[str, float], ...]:
    count = min(5, max(3, meal_count))
    if count == 3:
        return (("breakfast", 0.30), ("main", 0.38), ("main", 0.32))
    if count == 4:
        return (("breakfast", 0.27), ("main", 0.34), ("snack", 0.16), ("main", 0.23))
    return (("breakfast", 0.25), ("main", 0.30), ("snack", 0.14), ("main", 0.23), ("snack", 0.08))


def _select_recipe(
    recipes: list[RecipeTemplate],
    slot: str,
    used_recipe_ids: set[str],
    used_food_ids: Counter[str],
    variety_seed: int,
    index: int,
) -> RecipeTemplate | None:
    candidates = [recipe for recipe in recipes if recipe.slot == slot and recipe.id not in used_recipe_ids]
    if not candidates:
        return None

    def score(recipe: RecipeTemplate) -> float:
        overlap = sum(used_food_ids[food_id] for food_id in recipe.ingredients_g)
        seed_score = ((sum(ord(char) for char in recipe.id) + variety_seed * 31 + index * 11) % 100) / 100
        return seed_score - overlap * 0.35

    return max(candidates, key=score)


def _resolve_recipe_ingredients(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
) -> tuple[tuple[Food, float], ...] | None:
    substitutions = {
        "greek_yogurt": "lactose_free_yogurt",
        "cottage_cheese": "lactose_free_cottage_cheese",
        "whole_grain_bread": "corn_tortilla",
        "whole_wheat_pasta": "rice",
    }
    resolved: list[tuple[Food, float]] = []
    for food_id, grams in recipe.ingredients_g.items():
        food = food_by_id.get(food_id)
        if food is None and food_id in substitutions:
            food = food_by_id.get(substitutions[food_id])
        if food is None:
            return None
        resolved.append((food, grams))
    return tuple(resolved)


def _recipe_scale(target_energy: float, base_energy: float) -> float:
    if base_energy <= 0:
        return 1.0
    return max(0.70, min(1.75, target_energy / base_energy))


def _scaled_recipe_portions(
    resolved: tuple[tuple[Food, float], ...],
    scale: float,
    used_grams: dict[str, float],
) -> tuple[FoodPortion, ...]:
    portions: list[FoodPortion] = []
    for food, base_grams in resolved:
        grams = round(base_grams * scale, 1)
        grams = min(grams, food.max_per_meal_g, max(0.0, food.max_per_day_g - used_grams[food.id]))
        if grams <= 0:
            continue
        portions.append(food.portion(grams))
    return tuple(portions)


def _meal_emoji(slot: str, index: int) -> str:
    if slot == "breakfast":
        return "🍳"
    if slot == "snack":
        return "🥣"
    return "🍽️" if index == 1 else "🌙"


def _meal_name(slot: str, index: int) -> str:
    if slot == "breakfast":
        return "Завтрак"
    if slot == "snack":
        return "Перекус" if index < 4 else "Второй перекус"
    return "Обед" if index == 1 else "Ужин"


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
    variety_seed: int,
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
    scored.sort(key=lambda item: (item[0] + _variety_bonus(item[1].id, variety_seed), item[1].id), reverse=True)
    return scored[0][1]


def _variety_bonus(food_id: str, variety_seed: int) -> float:
    if variety_seed <= 0:
        return 0.0
    return ((sum(ord(char) for char in food_id) + variety_seed * 17) % 7) * 0.08


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
    variety_seed: int,
) -> list[Meal]:
    total = NutrientVector.sum(meal.nutrients for meal in meals)
    lower_energy = target.get("energy_kcal") * 0.96
    if total.get("energy_kcal") >= lower_energy:
        return meals

    dinner = meals[-1]
    portions = list(dinner.portions)
    for role in (MealRole.FAT, MealRole.CARB, MealRole.FAT, MealRole.CARB):
        deficit = target.minus(NutrientVector.sum(meal.nutrients for meal in meals)).clipped_positive()
        meal_categories = {portion.food.category for portion in portions}
        food = _select_food(candidates, role, deficit, used_grams, used_counts, meal_categories, variety_seed)
        if food is None:
            continue
        grams = _portion_for(food, role, deficit, used_grams)
        if grams <= 0:
            continue
        portion = food.portion(grams)
        portions.append(portion)
        used_grams[food.id] += grams
        used_counts[food.id] += 1
        meals[-1] = Meal(
            dinner.name,
            tuple(portions),
            dinner.recipe,
            dinner.image_url,
            dinner.image_attribution,
            dinner.source_url,
        )
        total = NutrientVector.sum(meal.nutrients for meal in meals)
        if total.get("energy_kcal") >= lower_energy:
            break
    return _increase_existing_portions(meals, target, used_grams)


def _increase_existing_portions(
    meals: list[Meal],
    target: NutrientVector,
    used_grams: dict[str, float],
) -> list[Meal]:
    lower_energy = target.get("energy_kcal") * 0.96
    upper_energy = target.get("energy_kcal") * 1.04
    priority_categories = ("grains", "fat", "nuts_seeds", "dairy", "fruit", "protein")

    for _ in range(12):
        changed_any = False
        for category in priority_categories:
            for meal_index, meal in enumerate(list(meals)):
                portions = list(meal.portions)
                changed = False
                for portion_index, portion in enumerate(list(portions)):
                    total = NutrientVector.sum(current_meal.nutrients for current_meal in meals)
                    if total.get("energy_kcal") >= lower_energy:
                        return meals
                    food = portion.food
                    if food.category != category:
                        continue
                    step = _increase_step(food.category)
                    room_meal = food.max_per_meal_g - portion.grams
                    room_day = food.max_per_day_g - used_grams[food.id]
                    grams = max(0.0, min(step, room_meal, room_day))
                    if grams <= 0:
                        continue
                    energy_per_g = food.nutrients_per_100g.get("energy_kcal") / 100
                    if energy_per_g <= 0:
                        continue
                    added_energy = energy_per_g * grams
                    if total.get("energy_kcal") + added_energy > upper_energy:
                        grams = max(0.0, (upper_energy - total.get("energy_kcal")) / energy_per_g)
                    if grams <= 0:
                        continue
                    portions[portion_index] = FoodPortion(food=food, grams=round(portion.grams + grams, 1))
                    used_grams[food.id] += grams
                    changed = True
                    changed_any = True
                if changed:
                    meals[meal_index] = Meal(
                        meal.name,
                        tuple(portions),
                        meal.recipe,
                        meal.image_url,
                        meal.image_attribution,
                        meal.source_url,
                    )
        if not changed_any:
            return meals
    return meals


def _increase_step(category: str) -> float:
    return {
        "grains": 20,
        "protein": 25,
        "dairy": 40,
        "fat": 5,
        "nuts_seeds": 5,
        "fruit": 30,
    }.get(category, 20)
