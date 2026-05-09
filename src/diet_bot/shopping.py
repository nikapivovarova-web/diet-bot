from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .domain import Meal, MealPlan, ShoppingItem

MIN_SHOPPING_GRAMS = 1.0
SHOPPING_CATEGORY_ORDER = (
    "grains",
    "vegetable",
    "fruit",
    "protein",
    "dairy",
    "fat",
    "nuts_seeds",
    "spice",
    "sauce",
    "sweetener",
    "processed_meat",
    "snack",
    "other",
)
SHOPPING_CATEGORY_TITLES = {
    "grains": "Крупы, хлеб и гарниры",
    "vegetable": "Овощи и зелень",
    "fruit": "Фрукты и ягоды",
    "protein": "Мясо, рыба, яйца и белок",
    "dairy": "Молочные продукты",
    "fat": "Масла и жиры",
    "nuts_seeds": "Орехи и семена",
    "spice": "Специи и травы",
    "sauce": "Соусы и заправки",
    "sweetener": "Сладкое и подсластители",
    "processed_meat": "Колбасы и готовое мясо",
    "snack": "Перекусы и готовое",
    "other": "Прочее",
}


@dataclass(frozen=True)
class ShoppingGroup:
    category: str
    title: str
    items: tuple[ShoppingItem, ...]


def build_shopping_list(plan: MealPlan) -> tuple[ShoppingItem, ...]:
    return build_shopping_list_for_meals(plan.meals)


def build_shopping_list_for_meals(meals: Iterable[Meal]) -> tuple[ShoppingItem, ...]:
    totals: dict[str, float] = defaultdict(float)
    categories: dict[str, str] = {}
    for meal in meals:
        portions = meal.portions
        if meal.batch:
            portions = () if meal.batch.is_carryover else meal.batch.batch_portions
        for portion in portions:
            totals[portion.food.name] += portion.grams
            categories[portion.food.name] = portion.food.category

    return tuple(
        ShoppingItem(food_name=name, category=categories[name], grams=round(grams, 1))
        for name, grams in sorted(totals.items(), key=lambda item: (categories[item[0]], item[0]))
        if round(grams) >= MIN_SHOPPING_GRAMS
    )


def build_shopping_groups(plan: MealPlan) -> tuple[ShoppingGroup, ...]:
    return build_shopping_groups_for_meals(plan.meals)


def build_week_shopping_groups(plans: Iterable[MealPlan]) -> tuple[ShoppingGroup, ...]:
    return build_shopping_groups_for_meals(meal for plan in plans for meal in plan.meals)


def build_shopping_groups_for_meals(meals: Iterable[Meal]) -> tuple[ShoppingGroup, ...]:
    return group_shopping_items(build_shopping_list_for_meals(meals))


def group_shopping_items(items: Iterable[ShoppingItem]) -> tuple[ShoppingGroup, ...]:
    buckets: dict[str, list[ShoppingItem]] = defaultdict(list)
    for item in items:
        buckets[item.category].append(item)

    known_categories = [category for category in SHOPPING_CATEGORY_ORDER if category in buckets]
    unknown_categories = sorted(category for category in buckets if category not in SHOPPING_CATEGORY_ORDER)
    return tuple(
        ShoppingGroup(
            category=category,
            title=SHOPPING_CATEGORY_TITLES.get(category, category.replace("_", " ").title()),
            items=tuple(sorted(buckets[category], key=lambda item: item.food_name)),
        )
        for category in (*known_categories, *unknown_categories)
    )
