from __future__ import annotations

import math

from .domain import Food


SALT_MAX_G = 3.0
LEMON_LIME_JUICE_MAX_G = 35.0
OIL_BREAKFAST_SNACK_MAX_G = 10.0
OIL_MAIN_MAX_G = 15.0
OIL_HARD_MAX_G = 20.0
FLAVOR_CHEESE_MAX_G = 20.0

HERB_IDS = frozenset(
    {
        "basil",
        "cilantro",
        "dill",
        "greens",
        "mint",
        "parsley",
        "rosemary",
        "sage",
        "thyme",
    }
)
CHEESE_IDS = frozenset(
    {
        "american_cheese",
        "cheddar",
        "cream_cheese",
        "feta",
        "goat_cheese",
        "gouda",
        "mascarpone",
        "mozzarella",
        "monterey_jack",
        "parmesan",
        "pecorino",
        "processed_cheese",
        "ricotta",
        "swiss_cheese",
        "wensleydale_cheese",
    }
)


def recipe_scale_for_food(food: Food, recipe_scale: float, base_grams: float | None = None) -> float:
    if _is_salt(food) or _is_spice_herb_or_garlic(food) or _is_lemon_lime_juice(food) or _is_oil_or_butter(food):
        return min(recipe_scale, 1.0)
    if _is_cheese(food):
        if base_grams is not None and base_grams <= FLAVOR_CHEESE_MAX_G:
            return min(recipe_scale, 1.0)
        if recipe_scale > 1.0:
            return min(1.25, 1.0 + (recipe_scale - 1.0) * 0.5)
    if food.category in {"sauce", "sweetener", "spice", "other", "processed_meat"}:
        return min(recipe_scale, 1.0)
    return recipe_scale


def scaled_recipe_grams(
    food: Food,
    base_grams: float,
    recipe_scale: float,
    *,
    meal_slot: str | None = None,
    max_grams: float | None = None,
) -> float:
    grams = base_grams * recipe_scale_for_food(food, recipe_scale, base_grams)
    grams = _apply_ingredient_caps(food, grams, meal_slot)
    return practical_grams(food, grams, meal_slot=meal_slot, max_grams=max_grams)


def practical_grams(
    food: Food,
    grams: float,
    *,
    meal_slot: str | None = None,
    max_grams: float | None = None,
    prefer_floor: bool = False,
) -> float:
    del meal_slot
    grams = _bounded(grams, max_grams)
    if grams <= 0:
        return 0.0

    step = _rounding_step(food, grams)
    rounded = _floor_to_step(grams, step) if prefer_floor else _round_to_step(grams, step)
    if rounded <= 0:
        rounded = step
    if max_grams is not None and rounded > max_grams:
        rounded = _floor_to_step(max_grams, step)
    if rounded <= 0:
        return 0.0
    return float(int(rounded)) if float(rounded).is_integer() else round(rounded, 1)


def top_up_increment_step(food: Food, default_step: float) -> float:
    if _is_whole_egg(food):
        return 50.0
    carrier_step = _carrier_step_g(food)
    if carrier_step is not None:
        return carrier_step
    return default_step


def top_up_total_grams(
    food: Food,
    current_grams: float,
    add_grams: float,
    *,
    meal_slot: str | None = None,
    max_grams: float | None = None,
) -> float:
    if add_grams <= 0 or not can_top_up_existing_portion(food, current_grams, meal_slot=meal_slot):
        return current_grams
    cap = _top_up_cap(food, current_grams, meal_slot)
    if cap is not None:
        max_grams = cap if max_grams is None else min(max_grams, cap)
    proposed = current_grams + add_grams
    if max_grams is not None:
        proposed = min(proposed, max_grams)
    prefer_floor = _is_whole_egg(food) or _carrier_step_g(food) is not None or cap is not None
    rounded = practical_grams(food, proposed, meal_slot=meal_slot, max_grams=max_grams, prefer_floor=prefer_floor)
    if rounded <= current_grams:
        return current_grams
    return rounded


def can_top_up_existing_portion(food: Food, current_grams: float, *, meal_slot: str | None = None) -> bool:
    if _is_salt(food) or _is_spice_herb_or_garlic(food) or _is_lemon_lime_juice(food) or _is_oil_or_butter(food):
        return False
    if _is_cheese(food) and current_grams <= FLAVOR_CHEESE_MAX_G:
        return False
    return _top_up_cap(food, current_grams, meal_slot) is None or current_grams < _top_up_cap(food, current_grams, meal_slot)


def _apply_ingredient_caps(food: Food, grams: float, meal_slot: str | None) -> float:
    if _is_salt(food):
        grams = min(grams, SALT_MAX_G)
    if _is_lemon_lime_juice(food):
        grams = min(grams, LEMON_LIME_JUICE_MAX_G)
    if _is_oil_or_butter(food):
        grams = min(grams, _oil_slot_cap(meal_slot), OIL_HARD_MAX_G)
    return grams


def _top_up_cap(food: Food, current_grams: float, meal_slot: str | None) -> float | None:
    del current_grams
    if _is_oil_or_butter(food):
        return min(_oil_slot_cap(meal_slot), OIL_HARD_MAX_G)
    if _is_salt(food):
        return SALT_MAX_G
    if _is_lemon_lime_juice(food):
        return LEMON_LIME_JUICE_MAX_G
    return None


def _rounding_step(food: Food, grams: float) -> float:
    if _is_whole_egg(food):
        return 50.0
    if _is_egg_part(food):
        return 5.0
    carrier_step = _carrier_step_g(food)
    if carrier_step is not None:
        return carrier_step
    if grams < 10:
        return 1.0
    if grams < 100:
        return 5.0
    return 10.0


def _carrier_step_g(food: Food) -> float | None:
    unit = _carrier_unit_g(food)
    if unit is None:
        return None
    return unit / 2.0


def _carrier_unit_g(food: Food) -> float | None:
    food_id = food.id.lower()
    if "breadcrumb" in food_id:
        return None
    if "tortilla" in food_id:
        return 40.0
    if "lavash" in food_id or "flatbread" in food_id or "pita" in food_id:
        return 60.0
    if "bagel" in food_id:
        return 90.0
    if "cracker" in food_id or "crouton" in food_id or "pretzel" in food_id:
        return 30.0
    if "bread" in food_id or food_id in {"baguette", "ciabatta"}:
        return 30.0
    return None


def _oil_slot_cap(meal_slot: str | None) -> float:
    return OIL_MAIN_MAX_G if (meal_slot or "").lower() == "main" else OIL_BREAKFAST_SNACK_MAX_G


def _is_whole_egg(food: Food) -> bool:
    return food.id.lower() in {"egg", "whole_egg"}


def _is_egg_part(food: Food) -> bool:
    food_id = food.id.lower()
    return food_id.startswith("egg_white") or food_id == "egg_yolk"


def _is_salt(food: Food) -> bool:
    food_id = food.id.lower()
    return food.category == "spice" and (food_id == "salt" or food_id.endswith("_salt"))


def _is_lemon_lime_juice(food: Food) -> bool:
    return food.id.lower() in {"lemon_juice", "lime_juice"}


def _is_oil_or_butter(food: Food) -> bool:
    food_id = food.id.lower()
    return food.category == "fat" and ("oil" in food_id or "butter" in food_id)


def _is_spice_herb_or_garlic(food: Food) -> bool:
    food_id = food.id.lower()
    if food.category == "spice":
        return True
    return food_id in HERB_IDS or food_id.startswith("garlic")


def _is_cheese(food: Food) -> bool:
    food_id = food.id.lower()
    return food.category == "dairy" and (food_id in CHEESE_IDS or "cheese" in food_id)


def _bounded(value: float, max_value: float | None) -> float:
    value = max(0.0, value)
    if max_value is None:
        return value
    return min(value, max(0.0, max_value))


def _round_to_step(value: float, step: float) -> float:
    return math.floor(value / step + 0.5) * step


def _floor_to_step(value: float, step: float) -> float:
    return math.floor(value / step) * step
