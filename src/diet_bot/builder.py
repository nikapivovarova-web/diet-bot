from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from .calculator import calculate_targets
from .catalog import built_in_foods
from .chef import recipe_for
from .domain import (
    Food,
    FoodPortion,
    CookingTimePreference,
    Meal,
    MealPlan,
    MealRole,
    NutrientVector,
    SafetyResult,
    UserProfile,
    normalize_cooking_time_preference,
)
from .recipe_catalog import RecipeTemplate, built_in_recipes
from .safety import evaluate_safety, is_food_excluded


RecipeSource = Literal["all", "curated_only"]
TimeBucket = Literal["quick", "medium", "long"]
RecipeRankingMode = Literal["balanced", "protein_floor"]

PRIORITY_NUTRIENTS = {
    "energy_kcal": 1.0,
    "protein_g": 2.0,
    "fat_g": 0.35,
    "carbohydrate_g": 1.15,
    "fiber_g": 1.9,
    "calcium_mg": 1.2,
    "magnesium_mg": 1.2,
    "potassium_mg": 0.8,
    "iron_mg": 1.0,
    "zinc_mg": 0.6,
    "phosphorus_mg": 0.4,
    "vitamin_c_mg": 1.0,
    "vitamin_d_mcg": 0.9,
    "vitamin_b12_mcg": 0.8,
    "folate_mcg_dfe": 0.8,
    "vitamin_b6_mg": 0.5,
    "omega_3_mg": 0.8,
}
LOW_PROTEIN_CEILING_MULTIPLIER = 1.20
HIGH_PROTEIN_CEILING_MULTIPLIER = 1.35
SMALL_PROTEIN_TARGET_CEILING_MULTIPLIER = 1.45
SMALL_PROTEIN_TARGET_THRESHOLD_G = 90
PROTEIN_TOP_UP_TARGET_MULTIPLIER = 0.95
PROTEIN_REASONABLE_CEILING_MULTIPLIER = 1.30
PROTEIN_EXCESSIVE_CEILING_MULTIPLIER = 1.50
RECIPE_PLAN_CANDIDATE_COUNT = 1
FAT_TOP_UP_CEILING_MULTIPLIER = 1.05
FAT_RECIPE_SOFT_LIMIT_MULTIPLIER = 1.05
FAT_RECIPE_HARD_LIMIT_MULTIPLIER = 1.25
CARBOHYDRATE_TOP_UP_CEILING_MULTIPLIER = 1.18
CARBOHYDRATE_RECIPE_SOFT_LIMIT_MULTIPLIER = 1.08
CARBOHYDRATE_RECIPE_HARD_LIMIT_MULTIPLIER = 1.24
SIMPLE_COOKING_COMPLEXITY_TITLE_KEYWORDS = (
    "выпек",
    "марин",
    "охлажд",
    "ноч",
    "несколько этап",
    "ваф",
    "блендер",
    "комбайн",
    "гриль",
    "аэрогриль",
    "мультиварк",
    "фритюр",
    "bake",
    "baking",
    "marinat",
    "overnight",
    "waffle",
    "blender",
    "processor",
    "grill",
    "air fryer",
    "fryer",
)
SIMPLE_COOKING_COMPLEXITY_INSTRUCTION_KEYWORDS = (
    "several stages",
    "несколько этап",
    "ваф",
    "блендер",
    "комбайн",
    "гриль",
    "аэрогриль",
    "мультиварк",
    "фритюр",
    "bake",
    "baking",
    "marinat",
    "overnight",
    "waffle",
    "blender",
    "processor",
    "grill",
    "air fryer",
    "fryer",
)


@dataclass(frozen=True)
class MealEnergySlot:
    slot: str
    target_ratio: float
    min_ratio: float
    max_ratio: float


@dataclass(frozen=True)
class CookingEffortConstraints:
    max_active_minutes: int
    max_ingredients: int
    max_instruction_sentences: int
    allow_oven_or_sauces: bool


MEAL_ENERGY_PROFILES: dict[int, tuple[MealEnergySlot, ...]] = {
    3: (
        MealEnergySlot("breakfast", 0.30, 0.24, 0.36),
        MealEnergySlot("main", 0.36, 0.30, 0.44),
        MealEnergySlot("main", 0.34, 0.28, 0.42),
    ),
    4: (
        MealEnergySlot("breakfast", 0.25, 0.20, 0.32),
        MealEnergySlot("main", 0.35, 0.28, 0.42),
        MealEnergySlot("snack", 0.12, 0.08, 0.18),
        MealEnergySlot("main", 0.28, 0.22, 0.35),
    ),
    5: (
        MealEnergySlot("breakfast", 0.25, 0.18, 0.32),
        MealEnergySlot("main", 0.30, 0.24, 0.38),
        MealEnergySlot("snack", 0.10, 0.07, 0.16),
        MealEnergySlot("main", 0.25, 0.20, 0.34),
        MealEnergySlot("snack", 0.10, 0.06, 0.15),
    ),
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

MAIN_PROTEIN_ROTATION = ("salmon", "chicken_breast", "turkey", "tuna", "tofu", "lentils", "egg")
BREAKFAST_BASE_ROTATION = (
    "oats",
    "cottage_cheese",
    "quinoa",
    "buckwheat",
    "egg",
)
SNACK_BASE_ROTATION = (
    "cottage_cheese",
    "greek_yogurt",
    "egg",
    "tuna",
    "tofu",
    "lactose_free_cottage_cheese",
    "lactose_free_yogurt",
)
RECIPE_SUBSTITUTIONS = {
    "greek_yogurt": "lactose_free_yogurt",
    "cottage_cheese": "lactose_free_cottage_cheese",
    "whole_grain_bread": "corn_tortilla",
    "whole_wheat_pasta": "rice",
}

ANIMAL_GARNISH_PROTEIN_IDS = frozenset(
    {
        "anchovies",
        "bacon",
        "beef_chuck",
        "beef_ground",
        "beef_sirloin",
        "beef_stew",
        "calamari",
        "chicken_breast",
        "chicken_drumstick",
        "chicken_ground",
        "chicken_thigh",
        "chicken_thigh_skinless",
        "chorizo",
        "clams",
        "cod_fillet",
        "crab_sticks",
        "ground_meat",
        "ham",
        "italian_sausage",
        "lamb_ground",
        "mackerel",
        "mussels",
        "pork_chop",
        "pork_loin",
        "pork_tenderloin",
        "prosciutto",
        "salmon",
        "sausage",
        "scallops",
        "seafood_mix",
        "shrimp",
        "smoked_white_fish",
        "tuna",
        "tuna_steak",
        "turkey",
        "turkey_ground",
        "turkey_or_chicken_breast",
        "white_fish",
    }
)
STARCHY_GARNISH_IDS = frozenset(
    {
        "buckwheat",
        "bulgur",
        "corn_tortilla",
        "couscous",
        "gnocchi",
        "lavash",
        "orzo",
        "pasta_generic",
        "pearl_barley",
        "pita",
        "potato",
        "quinoa",
        "rice",
        "soba_noodles",
        "spaghetti",
        "spelt",
        "sweet_potato",
        "whole_grain_bread",
        "whole_wheat_pasta",
    }
)
VEGETABLE_GARNISH_IDS = frozenset(
    {
        "asparagus",
        "bell_pepper",
        "bok_choy",
        "broccoli",
        "brussels_sprouts",
        "butternut_squash",
        "cabbage",
        "carrot",
        "cauliflower",
        "corn",
        "eggplant",
        "green_peas",
        "grilled_vegetables",
        "kale",
        "lettuce",
        "mushrooms",
        "parsnip",
        "red_cabbage",
        "root_vegetables",
        "spinach",
        "stir_fry_vegetables",
        "tomato",
        "zucchini",
    }
)


class NutritionFloorError(ValueError):
    """Raised when a generated plan misses a hard nutrition floor."""


@dataclass(frozen=True)
class MealSpec:
    name: str
    roles: tuple[MealRole, ...]


def build_one_day_plan(
    profile: UserProfile,
    foods: list[Food] | None = None,
    variety_seed: int = 0,
    avoided_recipe_ids: set[str] | frozenset[str] | None = None,
    avoided_recipe_keys: set[str] | frozenset[str] | None = None,
    recipe_source: RecipeSource = "all",
    allow_avoided_recipe_relaxation: bool = True,
) -> MealPlan:
    safety = evaluate_safety(profile)
    targets = calculate_targets(profile)
    if not safety.can_generate_plan:
        return MealPlan(meals=(), targets=targets, safety=safety)

    candidates = filter_foods(foods or built_in_foods(), safety)
    if not candidates:
        return MealPlan(meals=(), targets=targets, safety=safety)

    recipe_meals = _build_recipe_plan_for_time(
        candidates,
        targets.targets,
        profile.meal_count,
        profile.cooking_time,
        variety_seed,
        avoided_recipe_ids or frozenset(),
        avoided_recipe_keys or frozenset(),
        recipe_source,
    )
    if not recipe_meals and (avoided_recipe_ids or avoided_recipe_keys):
        recipe_meals = _build_recipe_plan_for_time(
            candidates,
            targets.targets,
            profile.meal_count,
            profile.cooking_time,
            variety_seed,
            avoided_recipe_ids or frozenset(),
            frozenset(),
            recipe_source,
        )
    if not recipe_meals and allow_avoided_recipe_relaxation and (avoided_recipe_ids or avoided_recipe_keys):
        recipe_meals = _build_recipe_plan_for_time(
            candidates,
            targets.targets,
            profile.meal_count,
            profile.cooking_time,
            variety_seed,
            frozenset(),
            frozenset(),
            recipe_source,
        )
    if recipe_meals:
        return MealPlan(meals=tuple(recipe_meals), targets=targets, safety=safety)
    if recipe_source == "curated_only":
        return MealPlan(meals=(), targets=targets, safety=safety)

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
    _ensure_hard_nutrition_floors(meals, targets.targets)
    return MealPlan(meals=tuple(meals), targets=targets, safety=safety)


def _build_recipe_plan_for_time(
    candidates: list[Food],
    target: NutrientVector,
    meal_count: int,
    cooking_time: CookingTimePreference,
    variety_seed: int,
    avoided_recipe_ids: set[str] | frozenset[str],
    avoided_recipe_keys: set[str] | frozenset[str],
    recipe_source: RecipeSource,
) -> list[Meal]:
    effort_constraints = _cooking_effort_constraints(cooking_time)
    for allowed_time_buckets in _time_filter_attempts(cooking_time):
        meals = _build_recipe_plan_candidates_for_attempt(
            candidates,
            target,
            meal_count,
            variety_seed,
            avoided_recipe_ids,
            avoided_recipe_keys,
            recipe_source,
            allowed_time_buckets,
            effort_constraints,
        )
        if meals:
            return meals

    return _build_recipe_plan_candidates_for_attempt(
        candidates,
        target,
        meal_count,
        variety_seed,
        avoided_recipe_ids,
        avoided_recipe_keys,
        recipe_source,
        None,
        effort_constraints,
    )


def _build_recipe_plan_candidates_for_attempt(
    candidates: list[Food],
    target: NutrientVector,
    meal_count: int,
    variety_seed: int,
    avoided_recipe_ids: set[str] | frozenset[str],
    avoided_recipe_keys: set[str] | frozenset[str],
    recipe_source: RecipeSource,
    allowed_time_buckets: frozenset[TimeBucket] | None,
    effort_constraints: CookingEffortConstraints,
) -> list[Meal]:
    meal_candidates: list[list[Meal]] = []
    seen_signatures: set[tuple[str | None, ...]] = set()
    for ranking_mode in ("balanced", "protein_floor"):
        for candidate_index in range(RECIPE_PLAN_CANDIDATE_COUNT):
            seed = variety_seed + candidate_index
            meals = _build_recipe_plan(
                candidates,
                target,
                meal_count,
                seed,
                avoided_recipe_ids,
                avoided_recipe_keys,
                recipe_source,
                allowed_time_buckets,
                effort_constraints,
                ranking_mode,
            )
            if not meals:
                continue
            meals = _finalize_recipe_meals(meals, candidates, target, seed)
            signature = tuple(meal.recipe_id for meal in meals)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            meal_candidates.append(meals)
            if ranking_mode == "balanced" and _passes_hard_nutrition_gates(meals, target):
                return _select_best_hard_valid_meals(meal_candidates, target)
    return _select_best_hard_valid_meals(meal_candidates, target)


def _build_recipe_plan(
    candidates: list[Food],
    target: NutrientVector,
    meal_count: int,
    variety_seed: int,
    avoided_recipe_ids: set[str] | frozenset[str],
    avoided_recipe_keys: set[str] | frozenset[str],
    recipe_source: RecipeSource,
    allowed_time_buckets: frozenset[TimeBucket] | None = None,
    effort_constraints: CookingEffortConstraints | None = None,
    ranking_mode: RecipeRankingMode = "balanced",
) -> list[Meal]:
    food_by_id = {food.id: food for food in candidates}
    recipes = [
        recipe
        for recipe in built_in_recipes()
        if _resolve_recipe_ingredients(recipe, food_by_id) is not None
        and recipe.id not in avoided_recipe_ids
        and _recipe_memory_key(recipe) not in avoided_recipe_keys
        and (recipe_source != "curated_only" or "curated" in recipe.tags)
        and (allowed_time_buckets is None or _recipe_time_bucket(recipe) in allowed_time_buckets)
        and (effort_constraints is None or _recipe_matches_cooking_effort(recipe, effort_constraints))
    ]
    if not recipes:
        return []

    used_recipe_ids: set[str] = set()
    used_food_ids: Counter[str] = Counter()
    used_formats: Counter[str] = Counter()
    used_grams: dict[str, float] = defaultdict(float)
    meals: list[Meal] = []
    total_energy = target.get("energy_kcal")
    slots = _meal_energy_slots(meal_count)

    for index, energy_slot in enumerate(slots):
        slot = energy_slot.slot
        slot_energy_target = total_energy * energy_slot.target_ratio
        current_total = NutrientVector.sum(meal.nutrients for meal in meals)
        selected_recipe: RecipeTemplate | None = None
        selected_portions: tuple[FoodPortion, ...] = tuple()
        for recipe in _rank_recipes(
            recipes,
            slot,
            used_recipe_ids,
            used_food_ids,
            used_formats,
            food_by_id,
            current_total,
            target,
            slot_energy_target,
            total_energy * energy_slot.min_ratio,
            total_energy * energy_slot.max_ratio,
            variety_seed,
            index,
            ranking_mode,
        ):
            resolved = _resolve_recipe_ingredients(recipe, food_by_id)
            if resolved is None:
                continue
            base_energy = NutrientVector.sum(food.portion(grams).nutrients for food, grams in resolved).get("energy_kcal")
            scale = _recipe_scale(slot_energy_target, base_energy)
            portions = _scaled_recipe_portions(resolved, scale, used_grams, current_total, target)
            if not portions:
                continue
            selected_recipe = recipe
            selected_portions = portions
            break
        if selected_recipe is None:
            continue
        recipe = selected_recipe
        portions = selected_portions
        used_recipe_ids.add(recipe.id)
        used_formats[_recipe_format(recipe)] += 1
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
                recipe_id=recipe.id,
                recipe_key=_recipe_memory_key(recipe),
            )
        )

    if len(meals) != len(slots):
        return []
    meals = _add_missing_garnishes(meals, candidates, target, used_grams, used_food_ids, variety_seed)
    return _increase_existing_portions(meals, target, used_grams)


def _finalize_recipe_meals(
    meals: list[Meal],
    candidates: list[Food],
    target: NutrientVector,
    variety_seed: int,
) -> list[Meal]:
    used_grams = _used_grams(meals)
    used_counts = Counter(
        portion.food.id
        for meal in meals
        for portion in meal.portions
    )
    return _top_up_if_needed(meals, candidates, target, used_grams, used_counts, variety_seed)


def _select_best_hard_valid_meals(
    meal_candidates: list[list[Meal]],
    target: NutrientVector,
) -> list[Meal]:
    hard_valid = [
        (candidate_index, meals)
        for candidate_index, meals in enumerate(meal_candidates)
        if _passes_hard_nutrition_gates(meals, target)
    ]
    if not hard_valid:
        return []
    _, selected = max(
        hard_valid,
        key=lambda item: (_meal_candidate_score(item[1], target), -item[0]),
    )
    return selected


def _passes_hard_nutrition_gates(meals: list[Meal], target: NutrientVector) -> bool:
    if not meals:
        return False
    total = NutrientVector.sum(meal.nutrients for meal in meals)
    return total.get("protein_g") + 0.01 >= _protein_hard_floor(target)


def _ensure_hard_nutrition_floors(meals: list[Meal], target: NutrientVector) -> None:
    if _passes_hard_nutrition_gates(meals, target):
        return
    total = NutrientVector.sum(meal.nutrients for meal in meals)
    raise NutritionFloorError(
        "Generated plan misses hard protein floor: "
        f"{total.get('protein_g'):.1f}g protein for "
        f"{_protein_hard_floor(target):.1f}g minimum."
    )


def _protein_hard_floor(target: NutrientVector) -> float:
    return target.get("protein_g") * PROTEIN_TOP_UP_TARGET_MULTIPLIER


def _meal_candidate_score(meals: list[Meal], target: NutrientVector) -> tuple[float, float, float]:
    total = NutrientVector.sum(meal.nutrients for meal in meals)
    macro_gap = _relative_gap(total, target, "energy_kcal") * 3.0
    macro_gap += _relative_gap(total, target, "fat_g")
    macro_gap += _relative_gap(total, target, "carbohydrate_g")
    protein_target = target.get("protein_g")
    if protein_target > 0:
        protein_ratio = total.get("protein_g") / protein_target
        if protein_ratio > 1.0:
            macro_gap += (protein_ratio - 1.0) * 0.35
        if protein_ratio > PROTEIN_REASONABLE_CEILING_MULTIPLIER:
            macro_gap += (protein_ratio - PROTEIN_REASONABLE_CEILING_MULTIPLIER) * 4.0
        if protein_ratio > PROTEIN_EXCESSIVE_CEILING_MULTIPLIER:
            macro_gap += (protein_ratio - PROTEIN_EXCESSIVE_CEILING_MULTIPLIER) * 10.0

    recipe_ids = [meal.recipe_id for meal in meals if meal.recipe_id]
    unique_recipe_ratio = len(set(recipe_ids)) / max(1, len(recipe_ids))
    repeated_food_penalty = _food_repeat_penalty(meals)
    return (-macro_gap, unique_recipe_ratio, -repeated_food_penalty)


def _relative_gap(total: NutrientVector, target: NutrientVector, nutrient: str) -> float:
    target_value = target.get(nutrient)
    if target_value <= 0:
        return 0.0
    return abs(total.get(nutrient) - target_value) / target_value


def _food_repeat_penalty(meals: list[Meal]) -> float:
    counts = Counter(portion.food.id for meal in meals for portion in meal.portions)
    return sum(max(0, count - 1) for count in counts.values())


def _time_filter_attempts(cooking_time: CookingTimePreference) -> tuple[frozenset[TimeBucket], ...]:
    preference = normalize_cooking_time_preference(cooking_time)
    if preference == CookingTimePreference.SIMPLE:
        return (frozenset({"quick", "medium"}),)
    return (frozenset({"quick", "medium", "long"}),)


def _cooking_effort_constraints(cooking_time: CookingTimePreference) -> CookingEffortConstraints:
    preference = normalize_cooking_time_preference(cooking_time)
    if preference == CookingTimePreference.INTERESTING:
        return CookingEffortConstraints(
            max_active_minutes=45,
            max_ingredients=12,
            max_instruction_sentences=7,
            allow_oven_or_sauces=True,
        )
    return CookingEffortConstraints(
        max_active_minutes=30,
        max_ingredients=11,
        max_instruction_sentences=6,
        allow_oven_or_sauces=False,
    )


def _recipe_matches_cooking_effort(
    recipe: RecipeTemplate,
    cooking_time: CookingTimePreference | CookingEffortConstraints,
) -> bool:
    constraints = (
        cooking_time
        if isinstance(cooking_time, CookingEffortConstraints)
        else _cooking_effort_constraints(cooking_time)
    )
    active_minutes = _parse_active_minutes(recipe.time_text)
    if active_minutes is not None and active_minutes > constraints.max_active_minutes:
        return False
    if len(recipe.ingredients_g) > constraints.max_ingredients:
        return False
    if _instruction_sentence_count(recipe.instructions) > constraints.max_instruction_sentences:
        return False
    if not constraints.allow_oven_or_sauces and _has_complex_cooking_technique(recipe):
        return False
    return True


def _instruction_sentence_count(text: str) -> int:
    sentences = [part.strip() for part in re.split(r"[.!?]+", text) if part.strip()]
    return len(sentences)


def _has_complex_cooking_technique(recipe: RecipeTemplate) -> bool:
    title_and_time = " ".join((recipe.title, recipe.time_text)).lower()
    instructions = recipe.instructions.lower()
    return any(keyword in title_and_time for keyword in SIMPLE_COOKING_COMPLEXITY_TITLE_KEYWORDS) or any(
        keyword in instructions for keyword in SIMPLE_COOKING_COMPLEXITY_INSTRUCTION_KEYWORDS
    )


def _recipe_time_bucket(recipe: RecipeTemplate) -> TimeBucket:
    minutes = _parse_active_minutes(recipe.time_text)
    if minutes is None:
        return "medium"
    if minutes <= 15:
        return "quick"
    if minutes <= 30:
        return "medium"
    return "long"


def _parse_active_minutes(time_text: str) -> float | None:
    normalized = time_text.lower().replace("–", "-").replace("—", "-")
    active_text = normalized.split("+", 1)[0]
    hour_minute_matches = re.findall(
        r"(\d+(?:[,.]\d+)?)\s*(?:ч|час\w*)\s*(?:(\d+)\s*мин)?",
        active_text,
    )
    if hour_minute_matches:
        return max(float(hours.replace(",", ".")) * 60 + float(minutes or 0) for hours, minutes in hour_minute_matches)

    minute_matches = re.findall(r"(\d+)(?:\s*-\s*(\d+))?\s*мин", active_text)
    if minute_matches:
        return max(float(end or start) for start, end in minute_matches)

    hour_matches = re.findall(r"(\d+(?:[,.]\d+)?)\s*(?:ч|час)", active_text)
    if hour_matches:
        return max(float(value.replace(",", ".")) * 60 for value in hour_matches)

    return None


def _recipe_slots(meal_count: int) -> tuple[tuple[str, float], ...]:
    return tuple((slot.slot, slot.target_ratio) for slot in _meal_energy_slots(meal_count))


def _meal_energy_slots(meal_count: int) -> tuple[MealEnergySlot, ...]:
    count = min(5, max(3, meal_count))
    return MEAL_ENERGY_PROFILES[count]


def _add_missing_garnishes(
    meals: list[Meal],
    candidates: list[Food],
    target: NutrientVector,
    used_grams: dict[str, float],
    used_counts: Counter[str],
    variety_seed: int,
) -> list[Meal]:
    slots = _meal_energy_slots(len(meals))
    upper_energy = target.get("energy_kcal") * 1.04
    updated = list(meals)

    for meal_index, meal in enumerate(updated):
        if slots[meal_index].slot != "main" or not _has_animal_garnish_protein(meal):
            continue

        roles = _garnish_roles_for_meal(meal, NutrientVector.sum(current.nutrients for current in updated), target, variety_seed, meal_index)
        if not roles:
            continue

        additions: list[FoodPortion] = []
        portions = list(meal.portions)
        for role in roles:
            total = NutrientVector.sum(current.nutrients for current in updated)
            room_energy = min(
                _meal_energy_room(Meal(meal.name, tuple(portions), meal.recipe), target, slots[meal_index]),
                upper_energy - total.get("energy_kcal"),
            )
            if room_energy <= 10:
                continue

            deficit = target.minus(total).clipped_positive()
            if deficit.get("energy_kcal") <= 0:
                deficit = NutrientVector({"energy_kcal": room_energy})
            food = _select_garnish_food(candidates, role, deficit, used_grams, used_counts, portions, variety_seed + meal_index)
            if food is None:
                continue
            grams = _garnish_portion_for(food, role, used_grams, room_energy)
            if grams <= 0:
                continue

            portion = food.portion(grams)
            portions.append(portion)
            additions.append(portion)
            used_grams[food.id] += grams
            used_counts[food.id] += 1
            updated[meal_index] = Meal(
                meal.name,
                tuple(portions),
                _recipe_with_garnish_note(meal.recipe, additions),
                meal.image_url,
                meal.image_attribution,
                meal.source_url,
                meal.recipe_id,
                meal.recipe_key,
            )

    return updated


def _has_animal_garnish_protein(meal: Meal) -> bool:
    return any(portion.food.id in ANIMAL_GARNISH_PROTEIN_IDS for portion in meal.portions)


def _garnish_roles_for_meal(
    meal: Meal,
    current_total: NutrientVector,
    target: NutrientVector,
    variety_seed: int,
    meal_index: int,
) -> tuple[MealRole, ...]:
    has_vegetable = _has_substantial_garnish(meal, MealRole.VEGETABLE)
    has_starch = _has_substantial_garnish(meal, MealRole.CARB)
    if has_vegetable and has_starch:
        return ()

    carb_ratio = _nutrient_ratio(current_total, target, "carbohydrate_g")
    fiber_ratio = _nutrient_ratio(current_total, target, "fiber_g")
    energy_ratio = _nutrient_ratio(current_total, target, "energy_kcal")
    needs_starch = carb_ratio < 0.88 or energy_ratio < 0.90
    needs_vegetable = fiber_ratio < 0.92

    if not has_vegetable and not has_starch:
        if needs_starch and needs_vegetable:
            return (MealRole.VEGETABLE, MealRole.CARB)
        if needs_vegetable:
            return (MealRole.VEGETABLE,)
        if needs_starch:
            return (MealRole.CARB,)
        variant = (variety_seed + meal_index) % 3
        if variant == 0:
            return (MealRole.VEGETABLE,)
        if variant == 1:
            return (MealRole.CARB,)
        return (MealRole.VEGETABLE, MealRole.CARB)

    roles: list[MealRole] = []
    if not has_vegetable and needs_vegetable:
        roles.append(MealRole.VEGETABLE)
    if not has_starch and needs_starch:
        roles.append(MealRole.CARB)
    return tuple(roles)


def _has_substantial_garnish(meal: Meal, role: MealRole) -> bool:
    allowed = VEGETABLE_GARNISH_IDS if role == MealRole.VEGETABLE else STARCHY_GARNISH_IDS
    return any(
        portion.food.id in allowed and portion.grams >= _minimum_garnish_grams(portion.food, role)
        for portion in meal.portions
    )


def _nutrient_ratio(total: NutrientVector, target: NutrientVector, nutrient: str) -> float:
    target_value = target.get(nutrient)
    if target_value <= 0:
        return 1.0
    return total.get(nutrient) / target_value


def _select_garnish_food(
    candidates: list[Food],
    role: MealRole,
    deficit: NutrientVector,
    used_grams: dict[str, float],
    used_counts: Counter[str],
    portions: list[FoodPortion],
    variety_seed: int,
) -> Food | None:
    allowed = VEGETABLE_GARNISH_IDS if role == MealRole.VEGETABLE else STARCHY_GARNISH_IDS
    existing_ids = {portion.food.id for portion in portions}
    scored = [
        (_score_food(food, role, deficit, used_grams, used_counts, set()), food)
        for food in candidates
        if food.id in allowed
        and food.id not in existing_ids
        and used_grams[food.id] < food.max_per_day_g
    ]
    scored = [item for item in scored if item[0] > -1000]
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0] + _variety_bonus(item[1].id, variety_seed), item[1].id), reverse=True)
    return scored[0][1]


def _garnish_portion_for(
    food: Food,
    role: MealRole,
    used_grams: dict[str, float],
    room_energy: float,
) -> float:
    grams = min(_default_garnish_portion(food, role), food.max_per_meal_g, max(0.0, food.max_per_day_g - used_grams[food.id]))
    energy_per_g = food.nutrients_per_100g.get("energy_kcal") / 100
    if energy_per_g > 0:
        grams = min(grams, room_energy / energy_per_g)
    grams = round(max(0.0, grams), 1)
    if grams < _minimum_garnish_grams(food, role):
        return 0.0
    return grams


def _default_garnish_portion(food: Food, role: MealRole) -> float:
    if role == MealRole.VEGETABLE:
        if food.id in {"butternut_squash", "corn", "green_peas", "parsnip", "root_vegetables"}:
            return 140
        return 160
    if food.id in {"potato", "sweet_potato"}:
        return 180
    if food.id in {"whole_grain_bread", "corn_tortilla", "lavash", "pita"}:
        return 55
    return 50


def _minimum_garnish_grams(food: Food, role: MealRole) -> float:
    if role == MealRole.VEGETABLE:
        return 80
    if food.id in {"potato", "sweet_potato"}:
        return 110
    if food.id in {"whole_grain_bread", "corn_tortilla", "lavash", "pita"}:
        return 35
    return 35


def _recipe_with_garnish_note(recipe: str, additions: list[FoodPortion]) -> str:
    if not additions:
        return recipe
    vegetables = [portion.food.name for portion in additions if portion.food.id in VEGETABLE_GARNISH_IDS]
    starches = [portion.food.name for portion in additions if portion.food.id in STARCHY_GARNISH_IDS]
    notes: list[str] = []
    if starches:
        notes.append(f"{', '.join(starches)} отварите или запеките без лишнего масла")
    if vegetables:
        notes.append(f"{', '.join(vegetables)} приготовьте на пару, запеките или быстро прогрейте")
    if not notes:
        return recipe
    note = f"Гарнир: {'; '.join(notes)}."
    if "Гарнир:" in recipe:
        return recipe
    return f"{recipe.rstrip()} {note}".strip()


def _select_recipe(
    recipes: list[RecipeTemplate],
    slot: str,
    used_recipe_ids: set[str],
    used_food_ids: Counter[str],
    used_formats: Counter[str],
    food_by_id: dict[str, Food],
    current_total: NutrientVector,
    target: NutrientVector,
    slot_energy_target: float,
    slot_min_energy: float,
    slot_max_energy: float,
    variety_seed: int,
    index: int,
) -> RecipeTemplate | None:
    ranked = _rank_recipes(
        recipes,
        slot,
        used_recipe_ids,
        used_food_ids,
        used_formats,
        food_by_id,
        current_total,
        target,
        slot_energy_target,
        slot_min_energy,
        slot_max_energy,
        variety_seed,
        index,
    )
    return ranked[0] if ranked else None


def _rank_recipes(
    recipes: list[RecipeTemplate],
    slot: str,
    used_recipe_ids: set[str],
    used_food_ids: Counter[str],
    used_formats: Counter[str],
    food_by_id: dict[str, Food],
    current_total: NutrientVector,
    target: NutrientVector,
    slot_energy_target: float,
    slot_min_energy: float,
    slot_max_energy: float,
    variety_seed: int,
    index: int,
    ranking_mode: RecipeRankingMode = "balanced",
) -> list[RecipeTemplate]:
    candidates = [recipe for recipe in recipes if recipe.slot == slot and recipe.id not in used_recipe_ids]
    if not candidates:
        return []

    def score(recipe: RecipeTemplate) -> float:
        overlap = sum(used_food_ids[food_id] for food_id in recipe.ingredients_g)
        seed_score = _seeded_score(recipe.id, variety_seed, index) * 2.0
        nutrient_bonus = _recipe_nutrient_bonus(recipe, current_total, target)
        macro_bonus = _recipe_projected_macro_gap_bonus(recipe, food_by_id, slot_energy_target, current_total, target)
        if ranking_mode == "protein_floor":
            seed_score = _seeded_score(recipe.id, variety_seed, index) * 0.25
            macro_bonus += _recipe_projected_protein_floor_bonus(
                recipe,
                food_by_id,
                slot_energy_target,
                current_total,
                target,
            )
        rotation_bonus = _recipe_rotation_bonus(recipe, slot, variety_seed, index)
        curated_bonus = 1.15 if "curated" in recipe.tags else 0.0
        format_penalty = used_formats[_recipe_format(recipe)] * 0.85
        macro_penalty = _recipe_macro_penalty(recipe, current_total, target)
        macro_penalty += _recipe_projected_protein_penalty(recipe, food_by_id, slot_energy_target, current_total, target)
        macro_penalty += _recipe_projected_fat_penalty(recipe, food_by_id, slot_energy_target, current_total, target)
        macro_penalty += _recipe_projected_carbohydrate_penalty(recipe, food_by_id, slot_energy_target, current_total, target)
        energy_penalty = _recipe_projected_energy_penalty(
            recipe,
            food_by_id,
            slot_energy_target,
            slot_min_energy,
            slot_max_energy,
        )
        return seed_score + nutrient_bonus + macro_bonus + rotation_bonus + curated_bonus - overlap * 0.55 - format_penalty - macro_penalty - energy_penalty

    return sorted(candidates, key=score, reverse=True)


def _recipe_format(recipe: RecipeTemplate) -> str:
    title = recipe.title.lower()
    recipe_id = recipe.id
    if "ролл" in title or "roll" in recipe_id or "tortilla" in recipe_id:
        return "roll"
    if "боул" in title or "bowl" in recipe_id:
        return "bowl"
    if "салат" in title or "salad" in recipe_id:
        return "salad"
    if "сковород" in title or "skillet" in recipe_id:
        return "skillet"
    if "рагу" in title or "stew" in recipe_id:
        return "stew"
    if "запеч" in title or "oven" in recipe_id:
        return "oven"
    if "сэндвич" in title or "тост" in title or "sandwich" in recipe_id or "toast" in recipe_id:
        return "toast"
    if "каша" in title or "овсян" in title or "porridge" in recipe_id:
        return "porridge"
    if "тарелк" in title or "plate" in recipe_id:
        return "plate"
    if "перекус" in title or "snack" in recipe_id:
        return "snack"
    return "simple"


def _recipe_memory_key(recipe: RecipeTemplate) -> str:
    if "curated" in recipe.tags:
        return f"{recipe.slot}:curated:{recipe.id}"

    ingredients = set(recipe.ingredients_g)
    recipe_format = _recipe_format(recipe)
    if recipe.slot == "breakfast":
        return f"breakfast:{_breakfast_primary(recipe)}:{recipe_format}:{_first_present(ingredients, ('banana', 'orange', 'berries', 'apple', 'tomato', 'cucumber', 'bell_pepper', 'spinach'))}"
    if recipe.slot == "snack":
        base = _first_present(
            ingredients,
            (
                "cottage_cheese",
                "lactose_free_cottage_cheese",
                "greek_yogurt",
                "lactose_free_yogurt",
                "egg",
                "tuna",
                "tofu",
            ),
        )
        accent = _first_present(
            ingredients,
            ("orange", "banana", "berries", "apple", "cucumber", "tomato", "bell_pepper", "spinach", "avocado"),
        )
        carrier = _first_present(ingredients, ("whole_grain_bread", "corn_tortilla", "potato"))
        return f"snack:{base}:{accent}:{carrier}:{recipe_format}"
    protein = _first_present(ingredients, MAIN_PROTEIN_ROTATION)
    carb = _first_present(
        ingredients,
        ("buckwheat", "rice", "whole_wheat_pasta", "potato", "quinoa", "corn_tortilla", "whole_grain_bread"),
    )
    vegetables = sorted(ingredients & {"broccoli", "tomato", "cucumber", "bell_pepper", "spinach"})
    vegetable_key = "-".join(vegetables[:2])
    return f"main:{protein}:{carb}:{vegetable_key}:{recipe_format}"


def _first_present(ingredients: set[str], options: tuple[str, ...]) -> str:
    return next((option for option in options if option in ingredients), "none")


def _breakfast_primary(recipe: RecipeTemplate) -> str:
    if recipe.id.startswith("breakfast_egg_") or recipe.id in {
        "breakfast_omelet_tomato",
        "breakfast_scramble_avocado",
        "breakfast_tortilla_egg_roll",
    }:
        return "egg"
    if recipe.id.startswith("breakfast_cottage"):
        return "cottage_cheese"
    if recipe.id.startswith("breakfast_quinoa"):
        return "quinoa"
    if recipe.id.startswith("breakfast_banana_oats") or recipe.id.startswith("breakfast_oat"):
        return "oats"
    for part in recipe.id.split("_"):
        if part in {"oats", "quinoa", "buckwheat"}:
            return part
    if "cottage_cheese" in recipe.ingredients_g or "lactose_free_cottage_cheese" in recipe.ingredients_g:
        return "cottage_cheese"
    if "egg" in recipe.ingredients_g:
        return "egg"
    return next(iter(recipe.ingredients_g), "")


def _seeded_score(recipe_id: str, variety_seed: int, index: int) -> float:
    payload = f"{variety_seed}:{index}:{recipe_id}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=4).digest()
    return int.from_bytes(digest, "big") / 0xFFFFFFFF


def _recipe_rotation_bonus(recipe: RecipeTemplate, slot: str, variety_seed: int, index: int) -> float:
    ingredients = set(recipe.ingredients_g)
    if slot == "breakfast":
        preferred = BREAKFAST_BASE_ROTATION[variety_seed % len(BREAKFAST_BASE_ROTATION)]
        primary = _breakfast_primary(recipe)
        if primary == preferred:
            return 2.40
        if "egg" in ingredients:
            return -0.55
        return 0.0
    if slot == "snack":
        preferred = SNACK_BASE_ROTATION[(variety_seed + index) % len(SNACK_BASE_ROTATION)]
        if preferred in ingredients:
            return 1.55
        if recipe.id in {"snack_cottage_orange", "snack_banana_yogurt", "snack_yogurt_berries"}:
            return -0.25
        return 0.0
    if slot != "main":
        return 0.0
    preferred = MAIN_PROTEIN_ROTATION[(variety_seed + index - 1) % len(MAIN_PROTEIN_ROTATION)]
    secondary = MAIN_PROTEIN_ROTATION[(variety_seed * 3 + index - 1) % len(MAIN_PROTEIN_ROTATION)]
    if preferred in ingredients:
        return 2.40
    if secondary in ingredients:
        return 0.35
    if "salmon" in ingredients:
        return -0.2
    return 0.0


def _recipe_nutrient_bonus(recipe: RecipeTemplate, current_total: NutrientVector, target: NutrientVector) -> float:
    bonus = 0.0
    vitamin_d_gap = target.get("vitamin_d_mcg") - current_total.get("vitamin_d_mcg")
    omega_3_gap = target.get("omega_3_mg") - current_total.get("omega_3_mg")
    ingredients = set(recipe.ingredients_g)
    if vitamin_d_gap > target.get("vitamin_d_mcg") * 0.50:
        if "salmon" in ingredients:
            bonus += 0.65
        if "egg" in ingredients:
            bonus += 0.35
        if "tuna" in ingredients:
            bonus += 0.25
    if omega_3_gap > target.get("omega_3_mg") * 0.50:
        if "salmon" in ingredients:
            bonus += 0.65
        if "tuna" in ingredients:
            bonus += 0.3
    return bonus


def _recipe_projected_macro_gap_bonus(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
    slot_energy_target: float,
    current_total: NutrientVector,
    target: NutrientVector,
) -> float:
    estimated = _project_recipe_nutrients(recipe, food_by_id, slot_energy_target)
    if estimated is None:
        return 0.0

    bonus = 0.0
    protein_floor = target.get("protein_g") * PROTEIN_TOP_UP_TARGET_MULTIPLIER
    protein_gap = protein_floor - current_total.get("protein_g")
    if protein_gap > 0:
        bonus += min(estimated.get("protein_g"), protein_gap) / max(1.0, protein_floor) * 8.0

    for nutrient, weight in (("fat_g", 1.0), ("carbohydrate_g", 0.9)):
        nutrient_target = target.get(nutrient)
        if nutrient_target <= 0:
            continue
        gap = nutrient_target - current_total.get(nutrient)
        if gap > nutrient_target * 0.15:
            bonus += min(estimated.get(nutrient), gap) / nutrient_target * weight
    return bonus


def _recipe_projected_protein_floor_bonus(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
    slot_energy_target: float,
    current_total: NutrientVector,
    target: NutrientVector,
) -> float:
    estimated = _project_recipe_nutrients(recipe, food_by_id, slot_energy_target)
    if estimated is None:
        return 0.0

    protein_floor = _protein_hard_floor(target)
    protein_gap = protein_floor - current_total.get("protein_g")
    if protein_gap <= 0:
        return 0.0
    estimated_protein = estimated.get("protein_g")
    protein_density = estimated_protein / max(1.0, estimated.get("energy_kcal"))
    return min(estimated_protein, protein_gap) / max(1.0, protein_floor) * 30.0 + protein_density * 10.0


def _recipe_macro_penalty(recipe: RecipeTemplate, current_total: NutrientVector, target: NutrientVector) -> float:
    protein_target = max(1.0, target.get("protein_g"))
    protein_pressure = current_total.get("protein_g") / protein_target
    if protein_pressure < 0.65:
        return 0.0

    ingredients = set(recipe.ingredients_g)
    penalty = 0.0
    if ingredients & {"whole_wheat_pasta", "quinoa", "buckwheat"}:
        penalty += 1.25 * protein_pressure
    if ingredients & {"whole_grain_bread", "corn_tortilla"}:
        penalty += 0.45 * protein_pressure
    if ingredients & {"chicken_breast", "turkey", "tuna", "tofu"}:
        penalty += 0.40 * protein_pressure
    return penalty


def _recipe_projected_protein_penalty(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
    slot_energy_target: float,
    current_total: NutrientVector,
    target: NutrientVector,
) -> float:
    protein_target = target.get("protein_g")
    if protein_target <= 0:
        return 0.0

    estimated = _project_recipe_nutrients(recipe, food_by_id, slot_energy_target)
    if estimated is None:
        return 0.0
    estimated_protein = estimated.get("protein_g")
    projected_protein = current_total.get("protein_g") + estimated_protein
    soft_limit = protein_target * PROTEIN_REASONABLE_CEILING_MULTIPLIER
    hard_limit = protein_target * PROTEIN_EXCESSIVE_CEILING_MULTIPLIER

    penalty = 0.0
    if estimated_protein > protein_target * 0.40:
        penalty += (estimated_protein - protein_target * 0.40) / max(1.0, protein_target) * 8.0
    if projected_protein > soft_limit:
        penalty += (projected_protein - soft_limit) / max(1.0, protein_target) * 16.0
    if projected_protein > hard_limit:
        penalty += (projected_protein - hard_limit) / max(1.0, protein_target) * 45.0
    return penalty


def _recipe_projected_fat_penalty(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
    slot_energy_target: float,
    current_total: NutrientVector,
    target: NutrientVector,
) -> float:
    fat_target = target.get("fat_g")
    if fat_target <= 0:
        return 0.0

    estimated = _project_recipe_nutrients(recipe, food_by_id, slot_energy_target)
    if estimated is None:
        return 0.0

    estimated_fat = estimated.get("fat_g")
    projected_fat = current_total.get("fat_g") + estimated_fat
    soft_limit = fat_target * FAT_RECIPE_SOFT_LIMIT_MULTIPLIER
    hard_limit = fat_target * FAT_RECIPE_HARD_LIMIT_MULTIPLIER

    penalty = 0.0
    if estimated_fat > fat_target * 0.34:
        penalty += (estimated_fat - fat_target * 0.34) / max(1.0, fat_target) * 7.0
    if projected_fat > soft_limit:
        penalty += (projected_fat - soft_limit) / max(1.0, fat_target) * 10.0
    if projected_fat > hard_limit:
        penalty += (projected_fat - hard_limit) / max(1.0, fat_target) * 30.0
    return penalty


def _recipe_projected_carbohydrate_penalty(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
    slot_energy_target: float,
    current_total: NutrientVector,
    target: NutrientVector,
) -> float:
    carbohydrate_target = target.get("carbohydrate_g")
    if carbohydrate_target <= 0:
        return 0.0

    estimated = _project_recipe_nutrients(recipe, food_by_id, slot_energy_target)
    if estimated is None:
        return 0.0

    projected_carbohydrate = current_total.get("carbohydrate_g") + estimated.get("carbohydrate_g")
    soft_limit = carbohydrate_target * CARBOHYDRATE_RECIPE_SOFT_LIMIT_MULTIPLIER
    hard_limit = carbohydrate_target * CARBOHYDRATE_RECIPE_HARD_LIMIT_MULTIPLIER

    penalty = 0.0
    if projected_carbohydrate > soft_limit:
        penalty += (projected_carbohydrate - soft_limit) / max(1.0, carbohydrate_target) * 8.0
    if projected_carbohydrate > hard_limit:
        penalty += (projected_carbohydrate - hard_limit) / max(1.0, carbohydrate_target) * 24.0
    return penalty


def _recipe_projected_energy_penalty(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
    slot_energy_target: float,
    slot_min_energy: float,
    slot_max_energy: float,
) -> float:
    projected_energy = _project_recipe_energy(recipe, food_by_id, slot_energy_target)
    if projected_energy is None:
        return 0.0

    if projected_energy < slot_min_energy:
        return (slot_min_energy - projected_energy) / max(1.0, slot_energy_target) * 10.0
    if projected_energy > slot_max_energy:
        return (projected_energy - slot_max_energy) / max(1.0, slot_energy_target) * 14.0
    return abs(projected_energy - slot_energy_target) / max(1.0, slot_energy_target) * 1.5


def _project_recipe_energy(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
    slot_energy_target: float,
) -> float | None:
    projected = _project_recipe_nutrients(recipe, food_by_id, slot_energy_target)
    if projected is None:
        return None
    return projected.get("energy_kcal")


def _project_recipe_nutrients(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
    slot_energy_target: float,
) -> NutrientVector | None:
    resolved: list[tuple[Food, float]] = []
    base_energy = 0.0
    for food_id, grams in recipe.ingredients_g.items():
        food = _resolve_recipe_food(food_id, food_by_id)
        if food is None:
            return None
        resolved.append((food, grams))
        base_energy += food.nutrients_per_100g.get("energy_kcal") * grams / 100

    scale = _recipe_scale(slot_energy_target, base_energy)
    return NutrientVector.sum(
        food.portion(min(round(grams * _scale_for_food(food, scale), 1), food.max_per_meal_g)).nutrients
        for food, grams in resolved
    )


def _resolve_recipe_ingredients(
    recipe: RecipeTemplate,
    food_by_id: dict[str, Food],
) -> tuple[tuple[Food, float], ...] | None:
    resolved: list[tuple[Food, float]] = []
    for food_id, grams in recipe.ingredients_g.items():
        food = _resolve_recipe_food(food_id, food_by_id)
        if food is None:
            return None
        resolved.append((food, grams))
    return tuple(resolved)


def _resolve_recipe_food(food_id: str, food_by_id: dict[str, Food]) -> Food | None:
    food = food_by_id.get(food_id)
    if food is None and food_id in RECIPE_SUBSTITUTIONS:
        food = food_by_id.get(RECIPE_SUBSTITUTIONS[food_id])
    return food


def _recipe_scale(target_energy: float, base_energy: float) -> float:
    if base_energy <= 0:
        return 1.0
    return max(0.50, min(1.75, target_energy / base_energy))


def _scaled_recipe_portions(
    resolved: tuple[tuple[Food, float], ...],
    scale: float,
    used_grams: dict[str, float],
    current_total: NutrientVector,
    target: NutrientVector,
) -> tuple[FoodPortion, ...]:
    portions: list[FoodPortion] = []
    for food, base_grams in resolved:
        grams = round(base_grams * _scale_for_food(food, scale), 1)
        grams = min(grams, food.max_per_meal_g, max(0.0, food.max_per_day_g - used_grams[food.id]))
        grams = _limit_grams_for_protein_ceiling(food, grams, current_total, target, portions)
        if grams <= 0:
            if food.category in {"protein", "dairy"}:
                return tuple()
            continue
        portions.append(food.portion(grams))
    return tuple(portions)


def _scale_for_food(food: Food, recipe_scale: float) -> float:
    if food.category in {"protein", "dairy", "nuts_seeds", "fat", "sauce", "sweetener", "spice", "other", "snack", "processed_meat"}:
        return min(recipe_scale, 1.0)
    if food.category == "vegetable":
        return min(recipe_scale, 1.35)
    return recipe_scale


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
        if "lactose" not in safety.excluded_tags and "lactose_free" in food.tags:
            continue
        if food.has_any_tag(set(safety.excluded_tags)):
            continue
        if is_food_excluded(food, safety.excluded_food_names):
            continue
        eligible.append(food)
    return eligible


def _used_grams(meals: list[Meal]) -> dict[str, float]:
    used: dict[str, float] = defaultdict(float)
    for meal in meals:
        for portion in meal.portions:
            used[portion.food.id] += portion.grams
    return used


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


def _meal_energy_room(meal: Meal, target: NutrientVector, slot: MealEnergySlot) -> float:
    return max(0.0, target.get("energy_kcal") * slot.max_ratio - meal.nutrients.get("energy_kcal"))


def _meal_energy_gap(meal: Meal, target: NutrientVector, slot: MealEnergySlot) -> float:
    return target.get("energy_kcal") * slot.target_ratio - meal.nutrients.get("energy_kcal")


def _meal_min_energy_gap(meal: Meal, target: NutrientVector, slot: MealEnergySlot) -> float:
    return target.get("energy_kcal") * slot.min_ratio - meal.nutrients.get("energy_kcal")


def _has_meal_below_min_energy(meals: list[Meal], target: NutrientVector) -> bool:
    slots = _meal_energy_slots(len(meals))
    return any(_meal_min_energy_gap(meal, target, slot) > 10 for meal, slot in zip(meals, slots))


def _meal_indices_by_energy_gap(meals: list[Meal], target: NutrientVector) -> list[int]:
    slots = _meal_energy_slots(len(meals))
    return sorted(
        range(len(meals)),
        key=lambda index: (
            _meal_energy_gap(meals[index], target, slots[index]),
            _meal_energy_room(meals[index], target, slots[index]),
        ),
        reverse=True,
    )


def _top_up_roles_for_slot(slot: str) -> tuple[MealRole, ...]:
    if slot == "breakfast":
        return (MealRole.CARB, MealRole.CALCIUM, MealRole.FRUIT, MealRole.FAT)
    if slot == "snack":
        return (MealRole.CALCIUM, MealRole.FRUIT, MealRole.PROTEIN, MealRole.CARB)
    return (MealRole.CARB, MealRole.VEGETABLE, MealRole.PROTEIN, MealRole.FAT)


def _top_up_if_needed(
    meals: list[Meal],
    candidates: list[Food],
    target: NutrientVector,
    used_grams: dict[str, float],
    used_counts: Counter[str],
    variety_seed: int,
) -> list[Meal]:
    meals = _increase_existing_portions(meals, target, used_grams)
    total = NutrientVector.sum(meal.nutrients for meal in meals)
    lower_energy = target.get("energy_kcal") * 0.96
    upper_energy = target.get("energy_kcal") * 1.04
    if total.get("energy_kcal") >= lower_energy and not _has_meal_below_min_energy(meals, target):
        return _increase_existing_protein_if_needed(meals, target, used_grams)

    slots = _meal_energy_slots(len(meals))
    for _ in range(4):
        changed_any = False
        for meal_index in _meal_indices_by_energy_gap(meals, target):
            total = NutrientVector.sum(meal.nutrients for meal in meals)
            total_energy = total.get("energy_kcal")
            if total_energy >= lower_energy and not _has_meal_below_min_energy(meals, target):
                return _increase_existing_protein_if_needed(meals, target, used_grams)
            if total_energy >= upper_energy:
                return _increase_existing_protein_if_needed(meals, target, used_grams)

            meal = meals[meal_index]
            room_energy = min(_meal_energy_room(meal, target, slots[meal_index]), upper_energy - total_energy)
            if room_energy <= 20:
                continue

            portions = list(meal.portions)
            meal_categories = {portion.food.category for portion in portions}
            for role in _top_up_roles_for_slot(slots[meal_index].slot):
                deficit = target.minus(total).clipped_positive()
                if deficit.get("energy_kcal") <= 0:
                    deficit = NutrientVector({"energy_kcal": room_energy})
                food = _select_food(candidates, role, deficit, used_grams, used_counts, meal_categories, variety_seed)
                if food is None:
                    continue
                grams = _portion_for(food, role, deficit, used_grams)
                energy_per_g = food.nutrients_per_100g.get("energy_kcal") / 100
                if energy_per_g <= 0:
                    continue
                grams = min(grams, room_energy / energy_per_g)
                grams = round(max(0.0, grams), 1)
                grams = _limit_grams_for_protein_ceiling(food, grams, total, target, portions)
                grams = _limit_grams_for_fat_ceiling(food, grams, total, target, portions)
                grams = _limit_grams_for_carbohydrate_ceiling(food, grams, total, target, portions)
                if grams <= 0:
                    continue
                portion = food.portion(grams)
                portions.append(portion)
                used_grams[food.id] += grams
                used_counts[food.id] += 1
                meals[meal_index] = Meal(
                    meal.name,
                    tuple(portions),
                    meal.recipe,
                    meal.image_url,
                    meal.image_attribution,
                    meal.source_url,
                    meal.recipe_id,
                    meal.recipe_key,
                )
                changed_any = True
                break
        if not changed_any:
            break
    return _increase_existing_portions(meals, target, used_grams)


def _increase_existing_portions(
    meals: list[Meal],
    target: NutrientVector,
    used_grams: dict[str, float],
) -> list[Meal]:
    lower_energy = target.get("energy_kcal") * 0.96
    upper_energy = target.get("energy_kcal") * 1.04
    priority_categories = ("grains", "vegetable", "fruit", "dairy", "protein", "fat", "nuts_seeds")
    slots = _meal_energy_slots(len(meals))

    for _ in range(12):
        changed_any = False
        for category in priority_categories:
            for meal_index in _meal_indices_by_energy_gap(meals, target):
                meal = meals[meal_index]
                portions = list(meal.portions)
                changed = False
                room_energy_for_meal = _meal_energy_room(meal, target, slots[meal_index])
                if room_energy_for_meal <= 5:
                    continue
                for portion_index, portion in enumerate(list(portions)):
                    total = NutrientVector.sum(current_meal.nutrients for current_meal in meals)
                    if total.get("energy_kcal") >= lower_energy and not _has_meal_below_min_energy(meals, target):
                        return _increase_existing_protein_if_needed(meals, target, used_grams)
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
                    if grams * energy_per_g > room_energy_for_meal:
                        grams = max(0.0, room_energy_for_meal / energy_per_g)
                    if grams <= 0:
                        continue
                    grams = _limit_grams_for_protein_ceiling(food, grams, total, target)
                    grams = _limit_grams_for_fat_ceiling(food, grams, total, target)
                    grams = _limit_grams_for_carbohydrate_ceiling(food, grams, total, target)
                    if grams <= 0:
                        continue
                    portions[portion_index] = FoodPortion(food=food, grams=round(portion.grams + grams, 1))
                    used_grams[food.id] += grams
                    room_energy_for_meal -= energy_per_g * grams
                    changed = True
                    changed_any = True
                    if room_energy_for_meal <= 5:
                        break
                if changed:
                    meals[meal_index] = Meal(
                        meal.name,
                        tuple(portions),
                        meal.recipe,
                        meal.image_url,
                        meal.image_attribution,
                        meal.source_url,
                        meal.recipe_id,
                        meal.recipe_key,
                    )
        if not changed_any:
            return _increase_existing_protein_if_needed(meals, target, used_grams)
    return _increase_existing_protein_if_needed(meals, target, used_grams)


def _increase_existing_protein_if_needed(
    meals: list[Meal],
    target: NutrientVector,
    used_grams: dict[str, float],
) -> list[Meal]:
    protein_lower = target.get("protein_g") * PROTEIN_TOP_UP_TARGET_MULTIPLIER
    upper_energy = target.get("energy_kcal") * 1.04
    slots = _meal_energy_slots(len(meals))

    for _ in range(8):
        total = NutrientVector.sum(meal.nutrients for meal in meals)
        if total.get("protein_g") >= protein_lower:
            return meals
        if total.get("energy_kcal") >= upper_energy:
            return meals

        changed_any = False
        for meal_index in _meal_indices_by_energy_gap(meals, target):
            meal = meals[meal_index]
            room_energy_for_meal = _meal_energy_room(meal, target, slots[meal_index])
            if room_energy_for_meal <= 5:
                continue
            portions = list(meal.portions)
            protein_indexes = sorted(
                range(len(portions)),
                key=lambda index: _protein_density_score(portions[index].food),
                reverse=True,
            )
            for portion_index in protein_indexes:
                total = NutrientVector.sum(current_meal.nutrients for current_meal in meals)
                protein_gap = protein_lower - total.get("protein_g")
                energy_room = upper_energy - total.get("energy_kcal")
                if protein_gap <= 0 or energy_room <= 0:
                    return meals

                portion = portions[portion_index]
                food = portion.food
                protein_per_g = food.nutrients_per_100g.get("protein_g") / 100
                energy_per_g = food.nutrients_per_100g.get("energy_kcal") / 100
                if protein_per_g < 0.08 or energy_per_g <= 0:
                    continue

                room_meal = food.max_per_meal_g - portion.grams
                room_day = food.max_per_day_g - used_grams[food.id]
                grams = min(
                    _protein_increase_step(food.category),
                    room_meal,
                    room_day,
                    energy_room / energy_per_g,
                    room_energy_for_meal / energy_per_g,
                    protein_gap / protein_per_g,
                )
                grams = max(0.0, round(grams, 1))
                grams = _limit_grams_for_protein_ceiling(food, grams, total, target)
                grams = _limit_grams_for_carbohydrate_ceiling(food, grams, total, target)
                if grams <= 0:
                    continue

                portions[portion_index] = FoodPortion(food=food, grams=round(portion.grams + grams, 1))
                used_grams[food.id] += grams
                meals[meal_index] = Meal(
                    meal.name,
                    tuple(portions),
                    meal.recipe,
                    meal.image_url,
                    meal.image_attribution,
                    meal.source_url,
                    meal.recipe_id,
                    meal.recipe_key,
                )
                changed_any = True
                break
            if changed_any:
                break

        if not changed_any:
            return meals

    return meals


def _protein_density_score(food: Food) -> float:
    protein = food.nutrients_per_100g.get("protein_g")
    energy = food.nutrients_per_100g.get("energy_kcal")
    if energy <= 0:
        return 0.0
    return protein / energy


def _protein_increase_step(category: str) -> float:
    if category == "dairy":
        return 40
    return 30


def _increase_step(category: str) -> float:
    return {
        "grains": 20,
        "vegetable": 40,
        "protein": 25,
        "dairy": 40,
        "fat": 5,
        "nuts_seeds": 5,
        "fruit": 30,
    }.get(category, 20)


def _limit_grams_for_protein_ceiling(
    food: Food,
    grams: float,
    current_total: NutrientVector,
    target: NutrientVector,
    pending_portions: list[FoodPortion] | None = None,
) -> float:
    protein_per_g = food.nutrients_per_100g.get("protein_g") / 100
    if protein_per_g < 0.03:
        return grams

    pending_total = NutrientVector.sum(portion.nutrients for portion in (pending_portions or ()))
    protein_room = target.get("protein_g") * _protein_ceiling_multiplier(target)
    protein_room -= current_total.plus(pending_total).get("protein_g")
    if protein_room <= 0:
        return 0.0
    return round(min(grams, protein_room / protein_per_g), 1)


def _limit_grams_for_fat_ceiling(
    food: Food,
    grams: float,
    current_total: NutrientVector,
    target: NutrientVector,
    pending_portions: list[FoodPortion] | None = None,
) -> float:
    if food.category not in {"fat", "nuts_seeds"}:
        return grams

    fat_per_g = food.nutrients_per_100g.get("fat_g") / 100
    if fat_per_g <= 0:
        return grams

    pending_total = NutrientVector.sum(portion.nutrients for portion in (pending_portions or ()))
    fat_room = target.get("fat_g") * FAT_TOP_UP_CEILING_MULTIPLIER
    fat_room -= current_total.plus(pending_total).get("fat_g")
    if fat_room <= 0:
        return 0.0
    return round(min(grams, fat_room / fat_per_g), 1)


def _limit_grams_for_carbohydrate_ceiling(
    food: Food,
    grams: float,
    current_total: NutrientVector,
    target: NutrientVector,
    pending_portions: list[FoodPortion] | None = None,
) -> float:
    carbohydrate_per_g = food.nutrients_per_100g.get("carbohydrate_g") / 100
    if carbohydrate_per_g <= 0:
        return grams

    pending_total = NutrientVector.sum(portion.nutrients for portion in (pending_portions or ()))
    carbohydrate_room = target.get("carbohydrate_g") * CARBOHYDRATE_TOP_UP_CEILING_MULTIPLIER
    carbohydrate_room -= current_total.plus(pending_total).get("carbohydrate_g")
    if carbohydrate_room <= 0:
        return 0.0
    return round(min(grams, carbohydrate_room / carbohydrate_per_g), 1)


def _protein_ceiling_multiplier(target: NutrientVector) -> float:
    if target.get("protein_g") < SMALL_PROTEIN_TARGET_THRESHOLD_G:
        return SMALL_PROTEIN_TARGET_CEILING_MULTIPLIER
    if target.get("protein_g") >= 120:
        return HIGH_PROTEIN_CEILING_MULTIPLIER
    return LOW_PROTEIN_CEILING_MULTIPLIER
