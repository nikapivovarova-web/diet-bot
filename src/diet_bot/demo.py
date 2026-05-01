from __future__ import annotations

from .builder import build_one_day_plan
from .domain import ActivityLevel, ConditionCode, Goal, Restriction, RestrictionType, Sex, UserProfile
from .shopping import build_shopping_list
from .validation import validate_plan


def main() -> None:
    profile = UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=4,
        restrictions=(Restriction(RestrictionType.ALLERGY, "яблоко"),),
        conditions=(ConditionCode.LACTOSE_INTOLERANCE,),
        allow_lactose_free_dairy=True,
    )

    plan = build_one_day_plan(profile)
    validation = validate_plan(plan)
    print(f"BMI: {plan.targets.bmi} ({plan.targets.bmi_category})")
    print(f"Target: {plan.targets.targets.get('energy_kcal'):.0f} kcal")
    print(f"Validation OK: {validation.ok}")
    if validation.errors:
        print("Errors:", validation.errors)
    if validation.warnings:
        print("Warnings:", validation.warnings)

    for meal in plan.meals:
        print(f"\n{meal.name}")
        for portion in meal.portions:
            print(f"- {portion.food.name}: {portion.grams:.0f} g")
        print(meal.recipe)

    print("\nTotals")
    for key in ("energy_kcal", "protein_g", "fat_g", "carbohydrate_g", "fiber_g", "magnesium_mg", "vitamin_c_mg"):
        print(f"{key}: {plan.totals.get(key):.1f}")

    print("\nShopping list")
    for item in build_shopping_list(plan):
        print(f"- {item.food_name}: {item.grams:.0f} g")

    if plan.safety.disclaimers:
        print("\nImportant")
        for disclaimer in plan.safety.disclaimers:
            print(disclaimer)


if __name__ == "__main__":
    main()
