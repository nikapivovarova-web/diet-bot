from __future__ import annotations

from .domain import FoodPortion


def recipe_for(meal_name: str, portions: tuple[FoodPortion, ...]) -> str:
    names = [portion.food.name for portion in portions]
    if "Завтрак" in meal_name:
        return _breakfast_recipe(portions)
    if "Перекус" in meal_name:
        return _snack_recipe(portions)
    return _main_meal_recipe(portions)


def _breakfast_recipe(portions: tuple[FoodPortion, ...]) -> str:
    names = {portion.food.name for portion in portions}
    ingredients = _ingredient_sentence(portions)
    if "овсяные хлопья" in names and any("йогурт" in name for name in names):
        fruit = _first_by_category(portions, "fruit")
        booster = _first_by_category(portions, "vegetable") or _first_by_category(portions, "nuts_seeds")
        extra = f", сверху добавьте {fruit.food.name}" if fruit else ""
        if booster:
            extra += f" и мелко нарезанный {booster.food.name}"
        return (
            f"Сделайте густой овсяно-йогуртовый боул: залейте хлопья небольшим количеством горячей воды на 5-7 минут, "
            f"затем вмешайте йогурт{extra}. Ингредиенты: {ingredients}."
        )
    if "яйцо" in names:
        vegetables = [portion.food.name for portion in portions if portion.food.category == "vegetable"]
        veg_text = ", ".join(vegetables) if vegetables else "овощами"
        return f"Приготовьте мягкий омлет с {veg_text}: взбейте яйцо, готовьте на слабом огне 4-5 минут. Ингредиенты: {ingredients}."
    return (
        f"Соберите сбалансированный завтрак: отдельно приготовьте крупу или белковую основу, "
        f"добавьте фрукт и свежий овощной компонент. Ингредиенты: {ingredients}."
    )


def _main_meal_recipe(portions: tuple[FoodPortion, ...]) -> str:
    protein = _first_by_category(portions, "protein")
    grain = _first_by_category(portions, "grains")
    vegetables = [portion.food.name for portion in portions if portion.food.category == "vegetable"]
    fats = [portion.food.name for portion in portions if portion.food.category in {"fat", "nuts_seeds"}]
    ingredients = _ingredient_sentence(portions)
    protein_text = protein.food.name if protein else "белковый продукт"
    grain_text = grain.food.name if grain else "гарнир"
    veg_text = ", ".join(vegetables) if vegetables else "овощи"
    fat_text = f" Заправьте: {', '.join(fats)}." if fats else ""
    return (
        f"Сделайте тарелку-конструктор: приготовьте {protein_text} до готовности, отдельно сварите {grain_text}, "
        f"овощи ({veg_text}) слегка припустите или оставьте свежими.{fat_text} Ингредиенты: {ingredients}."
    )


def _snack_recipe(portions: tuple[FoodPortion, ...]) -> str:
    dairy = _first_by_category(portions, "dairy")
    fruit = _first_by_category(portions, "fruit")
    booster = _first_by_category(portions, "vegetable") or _first_by_category(portions, "nuts_seeds")
    ingredients = _ingredient_sentence(portions)
    if dairy and fruit:
        extra = f", добавьте {booster.food.name}" if booster else ""
        return f"Сделайте быстрый перекус: смешайте {dairy.food.name} с кусочками {fruit.food.name}{extra}. Ингредиенты: {ingredients}."
    return f"Соберите легкий перекус без добавления сахара. Ингредиенты: {ingredients}."


def _first_by_category(portions: tuple[FoodPortion, ...], category: str) -> FoodPortion | None:
    return next((portion for portion in portions if portion.food.category == category), None)


def _ingredient_sentence(portions: tuple[FoodPortion, ...]) -> str:
    return ", ".join(format_ingredient(portion) for portion in portions)


def format_ingredient(portion: FoodPortion) -> str:
    grams = round(portion.grams)
    return f"{portion.food.name} - {grams} г"
