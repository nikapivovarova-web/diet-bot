from diet_bot.builder import build_one_day_plan
from diet_bot.domain import ActivityLevel, Food, Goal, MealRole, NutrientVector, Sex, UserProfile
from diet_bot.shopping import build_shopping_list


def test_full_nutrient_vector_subtraction_for_banana() -> None:
    banana = Food(
        id="banana",
        name="банан",
        category="fruit",
        roles=frozenset({MealRole.FRUIT}),
        nutrients_per_100g=NutrientVector(
            {
                "energy_kcal": 89,
                "carbohydrate_g": 22.8,
                "fiber_g": 2.6,
                "vitamin_c_mg": 8.7,
                "vitamin_b6_mg": 0.37,
                "magnesium_mg": 27,
                "potassium_mg": 358,
            }
        ),
    )
    target = NutrientVector({"energy_kcal": 2000, "vitamin_b6_mg": 1.3, "potassium_mg": 3400})
    remaining = target.minus(banana.portion(120).nutrients)

    assert round(remaining.get("energy_kcal"), 1) == 1893.2
    assert round(remaining.get("vitamin_b6_mg"), 3) == 0.856
    assert round(remaining.get("potassium_mg"), 1) == 2970.4


def test_shopping_list_aggregates_ingredients() -> None:
    profile = UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=4,
    )
    plan = build_one_day_plan(profile)
    items = build_shopping_list(plan)
    item_names = {item.food_name for item in items}

    assert item_names
    assert len(item_names) == len(items)
    assert all(item.grams > 0 for item in items)
