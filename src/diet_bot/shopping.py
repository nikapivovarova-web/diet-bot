from __future__ import annotations

from collections import defaultdict

from .domain import MealPlan, ShoppingItem


def build_shopping_list(plan: MealPlan) -> tuple[ShoppingItem, ...]:
    totals: dict[str, float] = defaultdict(float)
    categories: dict[str, str] = {}
    for meal in plan.meals:
        for portion in meal.portions:
            totals[portion.food.name] += portion.grams
            categories[portion.food.name] = portion.food.category

    return tuple(
        ShoppingItem(food_name=name, category=categories[name], grams=round(grams, 1))
        for name, grams in sorted(totals.items(), key=lambda item: (categories[item[0]], item[0]))
    )
