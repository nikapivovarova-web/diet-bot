from __future__ import annotations

import re

from .domain import FoodPortion


AMOUNT_PATTERN = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:[,.]\d+)?"
GRAM_OR_ML_RE = re.compile(fr"(?P<number>{AMOUNT_PATTERN})\s*(?P<unit>г|мл)\b")
SPOON_RE = re.compile(fr"(?P<number>{AMOUNT_PATTERN})\s*(?P<unit>ч\. л\.|ст\. л\.)")
CUP_RE = re.compile(fr"(?P<number>{AMOUNT_PATTERN})\s*стакан(?:а|ов)?\b")
RECIPE_TEXT_LABEL_RE = re.compile(
    r"^\s*(?:инструкци(?:я|и)|приготовление|способ приготовления|рецепт)\s*[:：-]\s*",
    re.IGNORECASE,
)
STEP_MARKER_RE = re.compile(
    r"(^|[\s.!?])(?:(?:шаг\s*)?\d+\s*\)\s*|шаг\s*\d+\s*[\.:]\s*|\d+\s*[\.:]\s+)",
    re.IGNORECASE,
)
SERVICE_SENTENCE_RE = re.compile(
    r"подпиш|подписыв|канал|https?://|www\.|telegram|@food|ai[-\s]?модель|как\s+ai|chatgpt|openai|"
    r"искусственн\w+\s+интеллект|lorem|placeholder|todo",
    re.IGNORECASE,
)


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
    protein_text = protein.food.name if protein else "основу блюда"
    grain_text = grain.food.name if grain else "гарнир"
    veg_text = ", ".join(vegetables) if vegetables else "свежие овощи"
    fat_text = f" Заправьте: {', '.join(fats)}." if fats else ""
    return (
        f"Соберите аккуратное горячее блюдо: приготовьте {protein_text}, отдельно доведите до готовности {grain_text}, "
        f"овощи ({veg_text}) подайте свежими или быстро прогрейте на сковороде.{fat_text} Ингредиенты: {ingredients}."
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
    if portion.food.id == "egg":
        return _format_egg_ingredient(portion)
    tiny_text = _tiny_ingredient_text(portion)
    if tiny_text:
        return tiny_text
    food_name = _display_food_name(portion)
    grams = format_display_grams(portion.grams)
    hint = _portion_hint(portion)
    if hint:
        return f"{food_name} - {grams} г ({hint})"
    return f"{food_name} - {grams} г"


def format_display_grams(grams: float) -> str:
    if 0 < grams < 1:
        return "менее 1"
    if grams <= 0:
        return "0"
    return _format_number(_round_kitchen_grams(grams))


def clean_recipe_instruction_text(text: str) -> str:
    text = _normalize_recipe_instruction_structure(text)
    text = SPOON_RE.sub(lambda match: _format_instruction_spoon(_parse_number(match["number"]), match["unit"]), text)
    text = CUP_RE.sub(lambda match: _format_instruction_cup(_parse_number(match["number"])), text)
    text = GRAM_OR_ML_RE.sub(
        lambda match: _format_instruction_weight_or_volume(_parse_number(match["number"]), match["unit"]),
        text,
    )
    return _remove_service_sentences(text)


def _normalize_recipe_instruction_structure(text: str) -> str:
    text = RECIPE_TEXT_LABEL_RE.sub("", text.strip())
    text = STEP_MARKER_RE.sub(lambda match: match.group(1), text)
    return _normalize_recipe_text_spaces(text)


def _remove_service_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", _normalize_recipe_text_spaces(text))
    kept = [sentence for sentence in sentences if sentence and not SERVICE_SENTENCE_RE.search(sentence)]
    return _normalize_recipe_text_spaces(" ".join(kept))


def _normalize_recipe_text_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _format_egg_ingredient(portion: FoodPortion) -> str:
    count = max(1, int(portion.grams / 50 + 0.5))
    return f"{portion.food.name} - {count} шт."


def _display_food_name(portion: FoodPortion) -> str:
    if portion.food.id == "vegetable_broth" and portion.grams <= 10:
        return "овощной бульонный порошок"
    return portion.food.name


def _tiny_ingredient_text(portion: FoodPortion) -> str | None:
    if not 0 < portion.grams < 1:
        return None
    if portion.food.id == "garlic":
        return f"{portion.food.name} - по вкусу"
    if portion.food.category == "spice":
        return f"{portion.food.name} - щепотка"
    return None


def _portion_hint(portion: FoodPortion) -> str | None:
    food_id = portion.food.id
    category = portion.food.category
    name = portion.food.name.lower()
    grams = _round_kitchen_grams(portion.grams) if portion.grams >= 1 else portion.grams

    if category == "spice":
        return _spice_hint(grams)
    if food_id == "egg":
        return _about_whole_units(grams / 50, ("яйцо", "яйца", "яиц"))
    if food_id == "banana":
        return _about_units(grams / 120, ("банан", "банана", "бананов"))
    if food_id == "apple":
        return _about_units(grams / 170, ("яблоко", "яблока", "яблок"), allow_quarters=True)
    if food_id == "orange":
        return _citrus_hint(grams, 200, ("апельсин", "апельсина", "апельсинов"))
    if food_id == "mandarins":
        return _citrus_hint(grams, 75, ("мандарин", "мандарина", "мандаринов"), small_hint="несколько долек")
    if food_id == "grapefruit":
        return _citrus_hint(grams, 280, ("грейпфрут", "грейпфрута", "грейпфрутов"))
    if food_id == "tomato":
        return _about_units(grams / 120, ("помидор", "помидора", "помидоров"), allow_quarters=True)
    if food_id == "cucumber":
        return _about_units(grams / 150, ("огурец", "огурца", "огурцов"), allow_quarters=True)
    if food_id == "bell_pepper":
        return _about_units(grams / 150, ("сладкий перец", "сладкого перца", "сладких перцев"), allow_quarters=True)
    if food_id == "potato":
        return _potato_hint(grams)
    if food_id == "whole_grain_bread":
        return _about_units(grams / 35, ("ломтик хлеба", "ломтика хлеба", "ломтиков хлеба"))
    if food_id == "corn_tortilla":
        return _about_units(grams / 60, ("тортилья", "тортильи", "тортилий"))
    if food_id == "berries":
        return _about_units(grams / 80, ("горсть ягод", "горсти ягод", "горстей ягод"))
    if food_id == "broccoli":
        return _about_units(grams / 80, ("горсть соцветий", "горсти соцветий", "горстей соцветий"))
    if food_id == "spinach":
        return _about_units(grams / 30, ("горсть шпината", "горсти шпината", "горстей шпината"))
    if food_id in {"greek_yogurt", "lactose_free_yogurt"} or "йогурт" in name:
        return _dairy_hint(grams, "йогурта", 200)
    if food_id in {"cottage_cheese", "lactose_free_cottage_cheese"} or "творог" in name:
        return _dairy_hint(grams, "творога", 180)
    if food_id in {"milk", "almond_milk", "soy_milk", "kefir", "buttermilk"} or any(
        word in name for word in ("молоко", "кефир", "пахта")
    ):
        return _dairy_hint(grams, "напитка", 200)
    if food_id in {"olive_oil", "vegetable_oil", "canola_oil", "sesame_oil", "coconut_oil"}:
        if grams < 9:
            return _about_units(
                grams / 5,
                ("чайная ложка", "чайной ложки", "чайные ложки", "чайных ложек"),
                allow_quarters=True,
            )
        return _about_units(
            grams / 14,
            ("столовая ложка", "столовой ложки", "столовые ложки", "столовых ложек"),
            allow_quarters=True,
        )
    if food_id == "tahini":
        return _sauce_hint(grams)
    if food_id == "pumpkin_seeds" or category == "nuts_seeds":
        return _nut_seed_hint(grams, name)
    if food_id == "avocado":
        return _about_units(grams / 150, ("авокадо", "авокадо", "авокадо"), allow_quarters=True)
    if food_id == "whole_wheat_pasta" or _is_pasta_like(name):
        return _about_units(
            grams / 70,
            (
                "небольшая порция сухой пасты",
                "небольшой порции сухой пасты",
                "небольшие порции сухой пасты",
                "небольших порций сухой пасты",
            ),
        )
    if food_id in {"buckwheat", "rice", "quinoa", "oats"} or _is_dry_grain_like(name):
        return _about_units(
            grams / 15,
            (
                "столовая ложка сухой крупы",
                "столовой ложки сухой крупы",
                "столовые ложки сухой крупы",
                "столовых ложек сухой крупы",
            ),
        )
    if category == "grains" and _is_bread_like(name):
        return _about_units(
            grams / 40,
            ("кусок хлеба или лаваша", "куска хлеба или лаваша", "куска хлеба или лаваша", "кусков хлеба или лаваша"),
        )
    if food_id in {"chicken_breast", "turkey", "salmon"}:
        return _about_units(
            grams / 120,
            ("кусок размером с ладонь", "куска размером с ладонь", "кусков размером с ладонь"),
        )
    if food_id == "tuna":
        return _about_units(
            grams / 120,
            ("небольшая банка без жидкости", "небольшие банки без жидкости", "небольших банок без жидкости"),
        )
    if food_id == "tofu":
        return _about_units(grams / 180, ("стандартный блок тофу", "стандартных блока тофу", "стандартных блоков тофу"))
    if category in {"sauce", "sweetener"}:
        return _sauce_hint(grams)
    if category == "vegetable" and grams >= 50:
        return _about_units(grams / 80, ("горсть", "горсти", "горстей"))
    if category == "fruit" and grams >= 80:
        return _about_units(grams / 120, ("порция фрукта", "порции фрукта", "порций фруктов"))
    if category == "protein" and grams >= 60:
        return _about_units(grams / 120, ("порция белковой основы", "порции белковой основы", "порций белковой основы"))
    return None


def _round_kitchen_grams(grams: float) -> float:
    if grams < 10:
        return _round_to_step(grams, 1)
    if grams < 100:
        return _round_to_step(grams, 5)
    return _round_to_step(grams, 10)


def _round_kitchen_volume(ml: float) -> float:
    if ml < 10:
        return _round_to_step(ml, 1)
    if ml < 100:
        return _round_to_step(ml, 5)
    if ml < 250:
        return _round_to_step(ml, 10)
    return _round_to_step(ml, 25)


def _round_to_step(value: float, step: float) -> float:
    return max(step, int(value / step + 0.5) * step)


def _dairy_hint(grams: float, product_genitive: str, cup_grams: float) -> str | None:
    if grams < cup_grams * 0.20:
        return _about_units(
            grams / 15,
            ("столовая ложка", "столовой ложки", "столовые ложки", "столовых ложек"),
        )
    return _about_cups(grams / cup_grams, product_genitive)


def _sauce_hint(grams: float) -> str | None:
    if grams < 15:
        return _about_units(
            grams / 5,
            ("чайная ложка", "чайной ложки", "чайные ложки", "чайных ложек"),
            allow_quarters=True,
        )
    return _about_units(
        grams / 15,
        ("столовая ложка", "столовой ложки", "столовые ложки", "столовых ложек"),
        allow_quarters=True,
    )


def _nut_seed_hint(grams: float, name: str) -> str | None:
    if any(word in name for word in ("сем", "кунжут", "чиа", "лен", "кокос")):
        forms = ("столовая ложка семян", "столовой ложки семян", "столовые ложки семян", "столовых ложек семян")
    else:
        forms = ("столовая ложка орехов", "столовой ложки орехов", "столовые ложки орехов", "столовых ложек орехов")
    return _about_units(grams / 10, forms, allow_quarters=True)


def _citrus_hint(
    grams: float,
    whole_edible_grams: float,
    forms: tuple[str, str, str],
    *,
    small_hint: str = "несколько долек",
) -> str | None:
    if grams < whole_edible_grams * 0.35:
        return small_hint if grams >= 30 else None
    return _about_whole_units(grams / whole_edible_grams, forms)


def _potato_hint(grams: float) -> str | None:
    if grams < 75:
        return None
    if grams <= 155:
        return "примерно 1 небольшая картофелина"
    if grams <= 240:
        return "примерно 1 средняя картофелина"
    return _about_whole_units(grams / 150, ("картофелина", "картофелины", "картофелин"))


def _spice_hint(grams: float) -> str | None:
    if 0 < grams < 1:
        return "щепотка"
    if grams < 2:
        return "щепотка"
    if grams < 4:
        return "примерно 1/2 чайной ложки"
    return _about_units(
        grams / 5,
        ("чайная ложка", "чайной ложки", "чайные ложки", "чайных ложек"),
        allow_quarters=True,
    )


def _is_pasta_like(name: str) -> bool:
    return any(word in name for word in ("паста", "макарон", "спагетти", "лапша", "орзо", "ньокки"))


def _is_dry_grain_like(name: str) -> bool:
    return any(word in name for word in ("рис", "булгур", "киноа", "овся", "греч", "круп", "кус-кус", "кускус"))


def _is_bread_like(name: str) -> bool:
    return any(
        word in name
        for word in ("хлеб", "лаваш", "тортиль", "лепеш", "лепёш", "булочка", "бейгл", "чиабатта", "багет")
    )


def _about_cups(value: float, product_genitive: str) -> str | None:
    if value < 0.35:
        return "несколько столовых ложек"
    amount = _friendly_amount(value, allow_quarters=True)
    if amount is None:
        return None
    forms = (
        f"стакан {product_genitive}",
        f"стакана {product_genitive}",
        f"стакана {product_genitive}",
        f"стаканов {product_genitive}",
    )
    return f"примерно {amount} {_choose_form(amount, forms)}"


def _about_units(
    value: float,
    forms: tuple[str, str, str] | tuple[str, str, str, str],
    *,
    allow_quarters: bool = False,
) -> str | None:
    amount = _friendly_amount(value, allow_quarters=allow_quarters)
    if amount is None:
        return None
    return f"примерно {amount} {_choose_form(amount, forms)}"


def _about_whole_units(value: float, forms: tuple[str, str, str]) -> str | None:
    if value < 0.70:
        return None
    amount = "1" if value <= 1.25 else str(round(value))
    return f"примерно {amount} {_choose_form(amount, forms)}"


def _friendly_amount(value: float, *, allow_quarters: bool = False) -> str | None:
    if value < 0.18:
        return None
    if allow_quarters:
        if value <= 0.65:
            return "1/2"
    elif value <= 0.65:
        return "1/2"
    if value <= 1.25:
        return "1"
    if value <= 1.75:
        return "1,5"
    return str(round(value))


def _choose_form(amount: str, forms: tuple[str, str, str] | tuple[str, str, str, str]) -> str:
    if "/" in amount or amount == "1,5":
        return forms[1]
    if amount == "1":
        return forms[0]
    number = int(amount)
    if number % 10 == 1 and number % 100 != 11:
        return forms[0]
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return forms[2] if len(forms) == 4 else forms[1]
    return forms[3] if len(forms) == 4 else forms[2]


def _format_instruction_weight_or_volume(value: float, unit: str) -> str:
    if 0 < value < 1:
        return f"менее 1 {unit}"
    rounded = _round_kitchen_volume(value) if unit == "мл" else _round_kitchen_grams(value)
    return f"{_format_number(rounded)} {unit}"


def _format_instruction_spoon(value: float, unit: str) -> str:
    if unit == "ст. л." and value < 0.75:
        return _format_common_spoon_amount(value * 3, "ч. л.")
    return _format_common_spoon_amount(value, unit)


def _format_instruction_cup(value: float) -> str:
    if value < 0.20:
        return _format_common_spoon_amount(value * 16, "ст. л.")
    if value < 0.35:
        return "несколько столовых ложек"
    amount = _friendly_amount(value, allow_quarters=True)
    if amount is None:
        return "несколько столовых ложек"
    if amount == "1":
        return "1 стакан"
    return f"{amount} стакана"


def _format_common_spoon_amount(value: float, unit: str) -> str:
    if value <= 0:
        return f"0 {unit}"
    if unit == "ч. л." and value < 0.25:
        return "щепотку"
    if value < 0.63:
        return f"1/2 {unit}"
    if value < 1.25:
        return f"1 {unit}"
    if value < 1.75:
        return f"1,5 {unit}"
    half_steps = round(value * 2) / 2
    if abs(value - half_steps) < 0.05 and half_steps < 4:
        return f"{_format_number(half_steps)} {unit}"
    return f"{int(value + 0.5)} {unit}"


def _parse_number(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    if "/" not in normalized:
        return float(normalized)
    if " " in normalized:
        whole, fraction = normalized.split(maxsplit=1)
        return float(whole) + _parse_fraction(fraction)
    return _parse_fraction(normalized)


def _parse_fraction(value: str) -> float:
    numerator, denominator = value.split("/", maxsplit=1)
    denominator_value = float(denominator)
    if denominator_value == 0:
        return 0.0
    return float(numerator) / denominator_value


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",")
