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
    return "\n\n".join(format_plan_messages(plan, validation))


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

    calculation: list[str] = []
    calculation.append("🧮 Ваш расчет")
    calculation.append(f"📌 ИМТ: {plan.targets.bmi} ({_bmi_ru(plan.targets.bmi_category)})")
    calculation.append(f"🔥 Поддерживающая калорийность: {plan.targets.tdee_kcal:.0f} ккал")
    calculation.append(f"🎯 Цель на день: {plan.targets.targets.get('energy_kcal'):.0f} ккал")
    calculation.append(
        "🥩 БЖУ: "
        f"{plan.targets.targets.get('protein_g'):.0f} г белка, "
        f"{plan.targets.targets.get('fat_g'):.0f} г жиров, "
        f"{plan.targets.targets.get('carbohydrate_g'):.0f} г углеводов"
    )

    if plan.safety.caution_notes:
        calculation.append("")
        calculation.append("🛡️ Ограничения, которые я учел")
        calculation.extend(f"- {note}" for note in plan.safety.caution_notes)

    meals: list[str] = ["🍽️ Рацион на день"]
    for meal in plan.meals:
        meals.append(f"\n{meal.name}")
        meals.extend(f"- {format_ingredient(portion)}" for portion in meal.portions)
        meals.append(f"👨‍🍳 Как приготовить: {meal.recipe}")

    totals: list[str] = ["📊 Итого за день"]
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
            totals.append(f"- {NUTRIENT_LABELS[key]}: {value:.1f} / {target:.1f}")

    shopping: list[str] = ["🛒 Список покупок"]
    for item in build_shopping_list(plan):
        shopping.append(f"- {item.food_name}: {item.grams:.0f} г")

    if plan.safety.disclaimers:
        shopping.append("")
        shopping.append("⚠️ Важно")
        shopping.extend(plan.safety.disclaimers)

    return ("\n".join(calculation), "\n".join(meals), "\n".join(totals), "\n".join(shopping))


def _bmi_ru(category: str) -> str:
    return {
        "underweight": "дефицит массы",
        "normal": "нормальный ИМТ",
        "overweight": "избыточная масса",
        "obesity": "ожирение",
    }.get(category, category)
