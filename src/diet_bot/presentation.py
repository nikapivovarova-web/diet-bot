from __future__ import annotations

import re
from collections.abc import Sequence

from .chef import format_display_grams, format_ingredient
from .domain import BatchPrep, Meal, MealPlan, NutritionTargets, SafetyResult
from .shopping import build_shopping_groups_for_meals, build_shopping_list
from .validation import ValidationResult


NUTRIENT_LABELS = {
    "energy_kcal": "калории, ккал",
    "protein_g": "белки, г",
    "fat_g": "жиры, г",
    "carbohydrate_g": "углеводы, г",
    "fiber_g": "клетчатка, г",
    "calcium_mg": "кальций, мг",
    "iron_mg": "железо, мг",
    "magnesium_mg": "магний, мг",
    "zinc_mg": "цинк, мг",
    "iodine_mcg": "йод, мкг",
    "selenium_mcg": "селен, мкг",
    "potassium_mg": "калий, мг",
    "sodium_mg": "натрий, мг",
    "phosphorus_mg": "фосфор, мг",
    "saturated_fat_g": "насыщенные жиры, г",
    "vitamin_c_mg": "витамин C, мг",
    "vitamin_d_mcg": "витамин D, мкг",
    "vitamin_b12_mcg": "витамин B12, мкг",
    "folate_mcg_dfe": "фолат/B9, мкг",
    "vitamin_a_mcg_rae": "витамин A, мкг RAE",
    "vitamin_e_mg": "витамин E, мг",
    "vitamin_k_mcg": "витамин K, мкг",
    "vitamin_b1_mg": "витамин B1, мг",
    "vitamin_b2_mg": "витамин B2, мг",
    "vitamin_b3_mg": "витамин B3, мг",
    "vitamin_b6_mg": "витамин B6, мг",
    "added_sugar_g": "добавленный сахар, г",
    "omega_3_mg": "омега-3, мг",
}
NUTRIENT_ORDER = (
    "energy_kcal",
    "protein_g",
    "fat_g",
    "carbohydrate_g",
    "fiber_g",
    "calcium_mg",
    "iron_mg",
    "magnesium_mg",
    "zinc_mg",
    "iodine_mcg",
    "selenium_mcg",
    "potassium_mg",
    "sodium_mg",
    "phosphorus_mg",
    "saturated_fat_g",
    "vitamin_d_mcg",
    "vitamin_b12_mcg",
    "folate_mcg_dfe",
    "vitamin_a_mcg_rae",
    "vitamin_c_mg",
    "vitamin_e_mg",
    "vitamin_k_mcg",
    "vitamin_b1_mg",
    "vitamin_b2_mg",
    "vitamin_b3_mg",
    "vitamin_b6_mg",
    "omega_3_mg",
)
ORIENTATION_SENTENCE = (
    "Это ориентировочный расчёт. В реальности состав продуктов может немного отличаться "
    "из-за бренда, способа приготовления и точности порций."
)
BATCH_CONTAINER_COUNT_RE = re.compile(
    r"\b\d+\s+("
    r"маффин(?:ов|а|ы)?|"
    r"батончик(?:ов|а|и)?|"
    r"крекер(?:ов|а|и|ы)?|"
    r"(?:ячейк(?:у|и|ах|ам|ами)|ячеек)(?:\s+формы)?|"
    r"формоч(?:ку|ки|ках|кам|ками|ек)|"
    r"капсул(?:у|ы|ах|ам|ами)?|"
    r"рамекин(?:а|ов|и|ах|ам|ами)?"
    r")",
    re.IGNORECASE,
)
BATCH_CONTAINER_WORD_COUNT_RE = re.compile(
    r"\b(?:четыре|шесть|девять|двенадцать)\s+"
    r"(рамекин(?:а|ов|и|ах|ам|ами)?|формоч(?:ку|ки|ках|кам|ками|ек))",
    re.IGNORECASE,
)


def format_plan_response(plan: MealPlan, validation: ValidationResult) -> str:
    return "\n\n".join(format_plan_messages(plan, validation))


def format_calculation_summary(targets: NutritionTargets, safety: SafetyResult | None = None) -> str:
    calculation: list[str] = []
    calculation.append("🧮 Ваш расчет")
    calculation.append(f"📌 ИМТ (индекс массы тела): {targets.bmi} ({_bmi_ru(targets.bmi_category)})")
    if bmi_warning := _bmi_warning(targets.bmi):
        calculation.append(f"⚠️ {bmi_warning}")
    calculation.append(f"🔥 Поддерживающая калорийность: {targets.tdee_kcal:.0f} ккал")
    calculation.append(f"🎯 Цель на день: {targets.targets.get('energy_kcal'):.0f} ккал")
    calculation.append(f"💧 Питьевая вода: около {targets.water_l:.1f} л в день")
    calculation.append(
        "🥩 БЖУ: "
        f"{targets.targets.get('protein_g'):.0f} г белка, "
        f"{targets.targets.get('fat_g'):.0f} г жиров, "
        f"{targets.targets.get('carbohydrate_g'):.0f} г углеводов"
    )

    if safety and safety.caution_notes:
        calculation.append("")
        calculation.append("🛡️ Ограничения, которые я учел")
        calculation.extend(f"- {note}" for note in safety.caution_notes)

    return "\n".join(calculation)


def format_daily_totals(plan: MealPlan) -> str:
    totals: list[str] = ["📊 Итого за день и процент закрытия нормы"]
    for key in NUTRIENT_ORDER:
        value = plan.totals.get(key)
        target = plan.targets.targets.get(key)
        totals.append(
            f"- {_coverage_dot(value, target)} {NUTRIENT_LABELS[key]}: "
            f"{value:.1f} / {target:.1f} ({_coverage_percent(value, target)})"
        )
    return "\n".join(totals)


def format_week_shopping_list(plans: Sequence[MealPlan]) -> str:
    shopping: list[str] = ["🛒 Общий список продуктов на неделю"]
    meals = (meal for plan in plans for meal in plan.meals)
    groups = build_shopping_groups_for_meals(meals)
    if not groups:
        shopping.append("- Список пуст.")
    else:
        for group in groups:
            shopping.append("")
            shopping.append(group.title)
            for item in group.items:
                shopping.append(f"- {item.food_name}: {format_display_grams(item.grams)} г")

    disclaimers = tuple(
        dict.fromkeys(disclaimer for plan in plans for disclaimer in plan.safety.disclaimers)
    )
    if disclaimers:
        shopping.append("")
        shopping.append("⚠️ Важно")
        shopping.extend(disclaimers)

    shopping.append("")
    shopping.append(
        "🥤 Если вы пьете соки, газировку, сладкий чай, энергетики или другие калорийные напитки, "
        "учитывайте их в рационе: они могут заметно добавить калории и сахар."
    )
    shopping.append("")
    shopping.append(ORIENTATION_SENTENCE)
    return "\n".join(shopping)


def format_plan_messages(plan: MealPlan, validation: ValidationResult) -> tuple[str, ...]:
    if not plan.safety.can_generate_plan:
        red_flags = ", ".join(plan.safety.red_flags) or "медицинские ограничения"
        return (
            "\n".join(
            [
                "🩺 Я не буду составлять персональный рацион по этим данным.",
                f"Причина: {red_flags}.",
                *plan.safety.disclaimers,
            ]
            ),
        )

    meals: list[str] = ["🍽️ Рацион на день"]
    for meal in plan.meals:
        meals.append(f"\n{meal.name}")
        meals.extend(_meal_card_lines(meal))

    totals = format_daily_totals(plan)

    shopping: list[str] = ["🛒 Список продуктов"]
    for item in build_shopping_list(plan):
        shopping.append(f"- {item.food_name}: {format_display_grams(item.grams)} г")

    if plan.safety.disclaimers:
        shopping.append("")
        shopping.append("⚠️ Важно")
        shopping.extend(plan.safety.disclaimers)

    shopping.append("")
    shopping.append(
        "🥤 Если вы пьете соки, газировку, сладкий чай, энергетики или другие калорийные напитки, "
        "учитывайте их в рационе: они могут заметно добавить калории и сахар."
    )
    shopping.append("")
    shopping.append(ORIENTATION_SENTENCE)

    return (format_calculation_summary(plan.targets, plan.safety), "\n".join(meals), totals, "\n".join(shopping))


def format_meal_card(meal: Meal, include_photo_credit: bool = True) -> str:
    lines = [meal.name]
    lines.extend(_meal_card_lines(meal))
    if include_photo_credit and meal.image_attribution:
        lines.append("")
        credit = f"Фото: {meal.image_attribution}"
        if meal.source_url:
            credit += f"\n{meal.source_url}"
        lines.append(credit)
    return "\n".join(lines)


def _meal_card_lines(meal: Meal) -> list[str]:
    if not meal.batch:
        lines = ["Ингредиенты:"]
        lines.extend(f"- {format_ingredient(portion)}" for portion in meal.portions)
        lines.append(f"👨‍🍳 Как приготовить: {meal.recipe}")
        return lines

    serving = _counted(meal.batch.serving_units, meal.batch.unit_forms)
    if meal.batch.is_carryover:
        return [
            f"- Порция сегодня: {serving}",
            f"👨‍🍳 Как приготовить: Съешьте {serving} из приготовленной партии.",
            "- В расчет дня входит только сегодняшняя порция.",
        ]

    total = _counted(meal.batch.total_units, meal.batch.unit_forms)
    prep_count = _counted(meal.batch.serving_count, ("перекус", "перекуса", "перекусов"))
    remaining_units = meal.batch.total_units - meal.batch.serving_units
    remaining_servings = meal.batch.serving_count - 1
    lines = [
        f"- Порция сегодня: {serving}",
        f"- Приготовьте {total} на {prep_count}: сегодня съешьте только {serving}.",
        (
            f"- Остальные {_counted(remaining_units, meal.batch.unit_forms)} уберите на "
            f"следующие {_counted(remaining_servings, ('перекус', 'перекуса', 'перекусов'))}."
        ),
        "Ингредиенты на партию:",
    ]
    lines.extend(f"- {format_ingredient(portion)}" for portion in meal.batch.batch_portions)
    lines.append(f"👨‍🍳 Как приготовить: {format_batch_recipe_text(meal.recipe, meal.batch)}")
    lines.append("- В расчет дня входит только сегодняшняя порция.")
    return lines


def format_batch_recipe_text(recipe: str, batch: BatchPrep) -> str:
    if not recipe:
        return recipe

    total_units = batch.total_units

    def replace_digit_count(match: re.Match[str]) -> str:
        unit = match.group(1)
        return f"{total_units} {unit}"

    def replace_word_count(match: re.Match[str]) -> str:
        unit = match.group(1).lower()
        forms = (
            ("рамекин", "рамекина", "рамекинов")
            if unit.startswith("рамекин")
            else ("формочка", "формочки", "формочек")
        )
        return f"{total_units} {_count_form(total_units, forms)}"

    text = BATCH_CONTAINER_COUNT_RE.sub(replace_digit_count, recipe)
    text = BATCH_CONTAINER_WORD_COUNT_RE.sub(replace_word_count, text)
    return text


def _counted(count: int, forms: tuple[str, str, str]) -> str:
    return f"{count} {_count_form(count, forms)}"


def _count_form(count: int, forms: tuple[str, str, str]) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return forms[0]
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return forms[1]
    return forms[2]


def _bmi_ru(category: str) -> str:
    return {
        "underweight": "дефицит массы",
        "normal": "нормальный ИМТ",
        "overweight": "избыточная масса",
        "obesity": "ожирение",
    }.get(category, category)


def _bmi_warning(bmi: float) -> str:
    if bmi < 16:
        return (
            "Ваш ИМТ находится в выраженном дефиците массы. Рацион можно использовать как ориентир, "
            "но лучше обсудить питание с лечащим врачом."
        )
    if bmi < 18.5:
        return (
            "Ваш ИМТ ниже нормы: дефицит массы. Лучше обсудить рацион с лечащим врачом, "
            "особенно если вес снижался непреднамеренно."
        )
    if bmi >= 35:
        return (
            "Ваш ИМТ находится в зоне выраженного избытка массы. Рацион можно использовать как ориентир, "
            "но лучше обсудить питание с лечащим врачом."
        )
    if bmi >= 30:
        return (
            "Ваш ИМТ указывает на сильный избыток массы. Лучше обсудить рацион с лечащим врачом, "
            "особенно при хронических заболеваниях."
        )
    return ""


def _coverage_dot(value: float, target: float) -> str:
    if target <= 0:
        return "🔴"
    percent = value / target * 100
    if percent >= 95:
        return "🟢"
    if percent >= 45:
        return "🟡"
    return "🔴"


def _coverage_percent(value: float, target: float) -> str:
    if target <= 0:
        return "0%"
    percent = value / target * 100
    return f"{percent:.0f}%"
