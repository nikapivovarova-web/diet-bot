from __future__ import annotations

from .domain import FoodPortion


def recipe_for(meal_name: str, portions: tuple[FoodPortion, ...]) -> str:
    names = [portion.food.name for portion in portions]
    if "Завтрак" in meal_name:
        return _breakfast_recipe(names)
    if "Перекус" in meal_name:
        return _snack_recipe(names)
    return _main_meal_recipe(names)


def _breakfast_recipe(names: list[str]) -> str:
    return (
        "Соберите простой завтрак: приготовьте крупу или белковую основу, "
        "добавьте фрукт и небольшой микроэлементный усилитель, если он есть в списке."
    )


def _main_meal_recipe(names: list[str]) -> str:
    return (
        "Приготовьте белковый продукт, отдельно сварите крупу или бобовые, "
        "добавьте овощи и заправьте допустимым количеством масла или семян."
    )


def _snack_recipe(names: list[str]) -> str:
    return "Соберите перекус из указанных ингредиентов без добавления сахара."


def format_ingredient(portion: FoodPortion) -> str:
    grams = round(portion.grams)
    return f"{portion.food.name} - {grams} г"
