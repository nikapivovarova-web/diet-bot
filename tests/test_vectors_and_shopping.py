from diet_bot.builder import build_one_day_plan
from diet_bot.domain import (
    ActivityLevel,
    Food,
    FoodPortion,
    Goal,
    Meal,
    MealPlan,
    MealRole,
    NutrientVector,
    NutritionTargets,
    SafetyResult,
    Sex,
    UserProfile,
)
from diet_bot.presentation import format_week_shopping_list
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


def test_shopping_list_omits_tiny_rounded_zero_items() -> None:
    salt = Food(
        id="salt",
        name="соль",
        category="spice",
        nutrients_per_100g=NutrientVector(),
    )
    cinnamon = Food(
        id="cinnamon",
        name="корица",
        category="spice",
        nutrients_per_100g=NutrientVector(),
    )
    rice = Food(
        id="rice",
        name="рис",
        category="grains",
        nutrients_per_100g=NutrientVector(),
    )
    targets = NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector({"energy_kcal": 2000}),
        calorie_bounds=(1800, 2200),
        macro_bounds={},
    )
    plan = MealPlan(
        meals=(
            Meal(
                name="Тест",
                portions=(
                    FoodPortion(salt, 0.4),
                    FoodPortion(cinnamon, 0.5),
                    FoodPortion(rice, 120),
                ),
                recipe="",
            ),
        ),
        targets=targets,
        safety=SafetyResult(can_generate_plan=True),
    )

    item_names = {item.food_name for item in build_shopping_list(plan)}

    assert item_names == {"рис"}


def test_week_shopping_list_aggregates_all_day_plans() -> None:
    rice = Food(
        id="rice",
        name="рис",
        category="grains",
        nutrients_per_100g=NutrientVector(),
    )
    chicken = Food(
        id="chicken",
        name="куриная грудка",
        category="protein",
        nutrients_per_100g=NutrientVector(),
    )
    targets = NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=NutrientVector({"energy_kcal": 2000}),
        calorie_bounds=(1800, 2200),
        macro_bounds={},
    )
    safety = SafetyResult(can_generate_plan=True)
    first_day = MealPlan(
        meals=(Meal("День 1", (FoodPortion(rice, 100), FoodPortion(chicken, 120)), ""),),
        targets=targets,
        safety=safety,
    )
    second_day = MealPlan(
        meals=(Meal("День 2", (FoodPortion(rice, 150), FoodPortion(chicken, 80)), ""),),
        targets=targets,
        safety=safety,
    )

    text = format_week_shopping_list((first_day, second_day))

    assert "Общий список продуктов на неделю" in text
    assert "Крупы, хлеб и гарниры" in text
    assert "Мясо, рыба, яйца и белок" in text
    assert "рис: 250 г" in text
    assert "куриная грудка: 200 г" in text
