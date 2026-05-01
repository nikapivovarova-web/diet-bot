from __future__ import annotations

from .chef import format_ingredient
from .domain import MealPlan
from .shopping import build_shopping_list
from .validation import ValidationResult


NUTRIENT_LABELS = {
    "energy_kcal": "ккал",
    "protein_g": "белки, г",
    "fat_g": "жиры, г",
    "carbohydrate_g": "углеводы, г",
    "fiber_g": "клетчатка, г",
    "calcium_mg": "кальций, мг",
    "magnesium_mg": "магний, мг",
    "potassium_mg": "калий, мг",
    "iron_mg": "железо, мг",
    "vitamin_c_mg": "витамин C, мг",
    "vitamin_d_mcg": "витамин D, мкг",
    "vitamin_b12_mcg": "витамин B12, мкг",
    "folate_mcg_dfe": "фолат/B9, мкг",
    "vitamin_b6_mg": "витамин B6, мг",
    "omega_3_mg": "омега-3, мг",
}


def format_plan_response(plan: MealPlan, validation: ValidationResult) -> str:
    if not plan.safety.can_generate_plan:
        red_flags = ", ".join(plan.safety.red_flags) or "медицинские ограничения"
        return "\n".join(
            [
                "Я не буду составлять персональный рацион по этим данным.",
                f"Причина: {red_flags}.",
                *plan.safety.disclaimers,
            ]
        )

    lines: list[str] = []
    lines.append("Ваш расчет")
    lines.append(f"ИМТ: {plan.targets.bmi} ({_bmi_ru(plan.targets.bmi_category)})")
    lines.append(f"Поддерживающая калорийность: {plan.targets.tdee_kcal:.0f} ккал")
    lines.append(f"Цель на день: {plan.targets.targets.get('energy_kcal'):.0f} ккал")
    lines.append(
        "БЖУ: "
        f"{plan.targets.targets.get('protein_g'):.0f} г белка, "
        f"{plan.targets.targets.get('fat_g'):.0f} г жиров, "
        f"{plan.targets.targets.get('carbohydrate_g'):.0f} г углеводов"
    )

    if plan.safety.caution_notes:
        lines.append("")
        lines.append("Ограничения, которые я учел")
        lines.extend(f"- {note}" for note in plan.safety.caution_notes)

    lines.append("")
    lines.append("Рацион на день")
    for meal in plan.meals:
        lines.append(f"\n{meal.name}")
        lines.extend(f"- {format_ingredient(portion)}" for portion in meal.portions)
        lines.append(f"Рецепт: {meal.recipe}")

    lines.append("")
    lines.append("Итого за день")
    for key in (
        "energy_kcal",
        "protein_g",
        "fat_g",
        "carbohydrate_g",
        "fiber_g",
        "calcium_mg",
        "magnesium_mg",
        "potassium_mg",
        "vitamin_c_mg",
        "vitamin_d_mcg",
        "vitamin_b12_mcg",
        "omega_3_mg",
    ):
        value = plan.totals.get(key)
        target = plan.targets.targets.get(key)
        if value or target:
            lines.append(f"- {NUTRIENT_LABELS[key]}: {value:.1f} / {target:.1f}")

    if validation.warnings:
        lines.append("")
        lines.append("Что осталось доработать")
        lines.extend(f"- {warning}" for warning in validation.warnings)

    lines.append("")
    lines.append("Список покупок")
    for item in build_shopping_list(plan):
        lines.append(f"- {item.food_name}: {item.grams:.0f} г")

    if plan.safety.disclaimers:
        lines.append("")
        lines.append("Важно")
        lines.extend(plan.safety.disclaimers)

    if validation.errors:
        lines.append("")
        lines.append("Техническая проверка нашла ошибки")
        lines.extend(f"- {error}" for error in validation.errors)

    return "\n".join(lines)


def _bmi_ru(category: str) -> str:
    return {
        "underweight": "дефицит массы",
        "normal": "нормальный ИМТ",
        "overweight": "избыточная масса",
        "obesity": "ожирение",
    }.get(category, category)
