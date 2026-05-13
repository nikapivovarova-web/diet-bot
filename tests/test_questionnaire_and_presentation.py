from diet_bot.builder import build_one_day_plan
from diet_bot.calculator import calculate_targets
from diet_bot.chef import clean_recipe_instruction_text, format_display_grams, format_ingredient
from diet_bot.domain import (
    ConditionCode,
    CookingTimePreference,
    Food,
    FoodPortion,
    Goal,
    Meal,
    NutrientVector,
    Sex,
    normalize_cooking_time_preference,
)
from diet_bot.presentation import format_calculation_summary, format_meal_card, format_plan_response
from diet_bot.questionnaire import QUESTIONS, start_session
from diet_bot.safety import evaluate_safety
from diet_bot.validation import validate_plan


def test_questionnaire_builds_profile_from_russian_answers() -> None:
    session = start_session()
    answers = [
        "32",
        "мужчина",
        "178",
        "86",
        "похудение",
        "умеренная",
        "4",
        "Побыстрее и попроще",
        "яблоко",
        "лактоза",
        "ХПН",
        "нет",
    ]

    for answer in answers:
        session, error = session.receive(answer)
        assert error is None

    assert session.is_complete
    profile = session.build_profile()
    assert profile.age == 32
    assert profile.sex == Sex.MALE
    assert profile.goal == Goal.LOSE
    assert profile.cooking_time == CookingTimePreference.SIMPLE
    assert ConditionCode.LACTOSE_INTOLERANCE in profile.conditions
    assert ConditionCode.CKD in profile.conditions
    assert profile.restrictions[0].value == "яблоко"


def test_button_questions_have_options() -> None:
    questions = {question.key: question for question in QUESTIONS}

    assert questions["sex"].options == ("👨 Мужчина", "👩 Женщина")
    assert questions["goal"].options == ("⬇️ Похудение", "⚖️ Поддержание", "💪 Набор")
    assert questions["meal_count"].options == ("3", "4", "5")
    assert questions["cooking_time"].options == ("Побыстрее и попроще", "Можно чуть интереснее")
    assert "⚡ Очень высокая" in questions["activity"].options
    assert questions["allergies"].options == ("Нет",)
    assert questions["intolerances"].options == ("Нет",)
    assert questions["conditions"].options == ("Нет",)
    assert questions["excluded_foods"].options == ("Нет",)


def test_questionnaire_accepts_decimal_comma_weight() -> None:
    session = start_session()
    answers = [
        "29",
        "женщина",
        "165",
        "62,5",
        "поддержание",
        "легкая",
        "3",
        "Можно чуть интереснее",
        "нет",
        "нет",
        "нет",
        "нет",
    ]

    for answer in answers:
        session, error = session.receive(answer)
        assert error is None

    assert session.build_profile().weight_kg == 62.5
    assert session.build_profile().cooking_time == CookingTimePreference.INTERESTING


def test_legacy_cooking_time_values_map_to_two_effort_modes() -> None:
    assert normalize_cooking_time_preference("quick") == CookingTimePreference.SIMPLE
    assert normalize_cooking_time_preference("до 15 минут") == CookingTimePreference.SIMPLE
    assert normalize_cooking_time_preference("medium") == CookingTimePreference.SIMPLE
    assert normalize_cooking_time_preference("15–30 минут") == CookingTimePreference.SIMPLE
    assert normalize_cooking_time_preference("long") == CookingTimePreference.INTERESTING
    assert normalize_cooking_time_preference("более 30 минут") == CookingTimePreference.INTERESTING
    assert normalize_cooking_time_preference("") == CookingTimePreference.SIMPLE
    assert normalize_cooking_time_preference("что-то непонятное") == CookingTimePreference.SIMPLE


def test_questionnaire_rejects_invalid_meal_count() -> None:
    session = start_session()
    for answer in ["32", "женщина", "165", "60", "поддержание", "легкая"]:
        session, error = session.receive(answer)
        assert error is None

    assert QUESTIONS[session.step_index].key == "meal_count"
    next_session, error = session.receive("8")

    assert next_session == session
    assert error is not None


def test_questionnaire_stops_under_18_after_age_answer() -> None:
    session = start_session()
    session, error = session.receive("17")

    assert error is None
    assert session.should_stop_after_answer()
    assert session.step_index == 1


def test_presentation_contains_plan_sections_and_shopping_list() -> None:
    session = start_session()
    for answer in [
        "32",
        "мужчина",
        "178",
        "86",
        "похудение",
        "умеренная",
        "4",
        "15–30 минут",
        "яблоко",
        "лактоза",
        "нет",
        "нет",
    ]:
        session, error = session.receive(answer)
        assert error is None

    plan = build_one_day_plan(session.build_profile())
    validation = validate_plan(plan)
    text = format_plan_response(plan, validation)

    assert "Ваш расчет" in text
    assert "ИМТ (индекс массы тела)" in text
    assert "Питьевая вода" in text
    assert "калорийные напитки" in text
    assert "процент закрытия нормы" in text
    assert "добавленный сахар" not in text
    assert "Это ориентировочный расчёт" in text
    assert "Рацион на день" in text
    assert "Список покупок" in text
    assert "Что осталось доработать" not in text
    assert "Техническая проверка" not in text
    assert "яблоко" not in {portion.food.name for meal in plan.meals for portion in meal.portions}


def test_totals_use_consistent_percent_style_and_status_dots() -> None:
    session = start_session()
    for answer in [
        "32",
        "мужчина",
        "178",
        "86",
        "похудение",
        "умеренная",
        "4",
        "15–30 минут",
        "нет",
        "нет",
        "нет",
        "нет",
    ]:
        session, error = session.receive(answer)
        assert error is None

    plan = build_one_day_plan(session.build_profile())
    text = format_plan_response(plan, validate_plan(plan))
    totals_section = next(section for section in text.split("\n\n") if "процент закрытия нормы" in section)

    assert "лимита" not in totals_section
    assert "🟢" in totals_section
    assert "🟡" in totals_section
    assert "🔴" in totals_section
    assert all(
        line.startswith(("- 🟢 ", "- 🟡 ", "- 🔴 "))
        for line in totals_section.splitlines()
        if line.startswith("- ")
    )


def test_calculation_summary_warns_for_very_low_bmi_without_refusing() -> None:
    session = start_session()
    for answer in [
        "30",
        "женщина",
        "159",
        "40",
        "поддержание",
        "легкая",
        "4",
        "15–30 минут",
        "нет",
        "нет",
        "нет",
        "нет",
    ]:
        session, error = session.receive(answer)
        assert error is None

    profile = session.build_profile()
    text = format_calculation_summary(calculate_targets(profile), evaluate_safety(profile))

    assert "выраженном дефиците массы" in text
    assert "лечащим врачом" in text


def test_calculation_summary_warns_for_high_bmi() -> None:
    session = start_session()
    for answer in [
        "35",
        "мужчина",
        "170",
        "105",
        "поддержание",
        "легкая",
        "4",
        "15–30 минут",
        "нет",
        "нет",
        "нет",
        "нет",
    ]:
        session, error = session.receive(answer)
        assert error is None

    profile = session.build_profile()
    text = format_calculation_summary(calculate_targets(profile), evaluate_safety(profile))

    assert "выраженного избытка массы" in text
    assert "лечащим врачом" in text


def test_meal_card_includes_photo_credit_when_available() -> None:
    meal = Meal(
        name="Тестовый рецепт",
        portions=(),
        recipe="Смешать и подать.",
        image_url="https://example.com/photo.jpg",
        image_attribution="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Photo.jpg",
    )
    card = format_meal_card(meal)

    assert "Фото:" in card
    assert "Wikimedia Commons" in card


def test_meal_ingredients_include_household_measure_hints() -> None:
    session = start_session()
    for answer in [
        "32",
        "мужчина",
        "178",
        "86",
        "похудение",
        "умеренная",
        "4",
        "15–30 минут",
        "нет",
        "нет",
        "нет",
        "нет",
    ]:
        session, error = session.receive(answer)
        assert error is None

    plan = build_one_day_plan(session.build_profile())
    text = format_plan_response(plan, validate_plan(plan))

    assert "примерно" in text
    assert "(" in text


def test_tiny_ingredient_amount_uses_kitchen_language() -> None:
    meal = Meal(
        name="Тестовый рецепт",
        portions=(
            FoodPortion(
                Food(
                    id="cinnamon",
                    name="корица",
                    category="spice",
                    nutrients_per_100g=NutrientVector(),
                ),
                0.4,
            ),
            FoodPortion(
                Food(
                    id="garlic",
                    name="чеснок",
                    category="vegetable",
                    nutrients_per_100g=NutrientVector(),
                ),
                0.5,
            ),
        ),
        recipe="Смешать.",
    )

    card = format_meal_card(meal)

    assert "корица - щепотка" in card
    assert "чеснок - по вкусу" in card
    assert "корица - менее 1 г" not in card
    assert "чеснок - менее 1 г" not in card
    assert "корица - 0 г" not in card


def test_visible_ingredient_grams_are_kitchen_rounded() -> None:
    assert format_display_grams(48) == "50"
    assert format_display_grams(54) == "55"
    assert format_display_grams(73) == "75"
    assert format_display_grams(296) == "300"


def test_yogurt_hint_uses_plausible_household_measure() -> None:
    yogurt = Food(
        id="greek_yogurt",
        name="греческий йогурт",
        category="dairy",
        nutrients_per_100g=NutrientVector(),
    )

    small = format_ingredient(FoodPortion(yogurt, 11))
    quarter_cup = format_ingredient(FoodPortion(yogurt, 48))

    assert "греческий йогурт - 10 г" in small
    assert "столов" in small
    assert "стакан" not in small
    assert "греческий йогурт - 50 г" in quarter_cup
    assert "несколько столовых ложек" in quarter_cup
    assert "1/2 стакана" not in quarter_cup


def test_small_spoon_hints_are_practical_not_surgical() -> None:
    oil = Food(id="olive_oil", name="оливковое масло", category="fat", nutrients_per_100g=NutrientVector())
    broth = Food(id="vegetable_broth", name="овощной бульон", category="sauce", nutrients_per_100g=NutrientVector())

    oil_text = format_ingredient(FoodPortion(oil, 4))
    broth_text = format_ingredient(FoodPortion(broth, 2))

    assert "оливковое масло - 4 г (примерно 1 чайная ложка)" == oil_text
    assert "3/4" not in oil_text
    assert broth_text.startswith("овощной бульонный порошок - ")


def test_vegetable_and_tahini_hints_avoid_wrong_category_words() -> None:
    onion = Food(id="onion", name="лук", category="vegetable", nutrients_per_100g=NutrientVector())
    cabbage = Food(id="cabbage", name="капуста", category="vegetable", nutrients_per_100g=NutrientVector())
    tahini = Food(id="tahini", name="тахини", category="nuts_seeds", nutrients_per_100g=NutrientVector())

    onion_text = format_ingredient(FoodPortion(onion, 80))
    cabbage_text = format_ingredient(FoodPortion(cabbage, 160))
    tahini_text = format_ingredient(FoodPortion(tahini, 15))

    assert "лук - 80 г (примерно 1 горсть)" == onion_text
    assert "капуста - 160 г (примерно 2 горсти)" == cabbage_text
    assert "овощей" not in onion_text
    assert "овощей" not in cabbage_text
    assert tahini_text == "тахини - 15 г (примерно 1 столовая ложка)"
    assert "орех" not in tahini_text


def test_citrus_potato_and_egg_hints_avoid_implausible_fractions() -> None:
    orange = Food(id="orange", name="апельсин", category="fruit", nutrients_per_100g=NutrientVector())
    mandarins = Food(id="mandarins", name="мандарины", category="fruit", nutrients_per_100g=NutrientVector())
    grapefruit = Food(id="grapefruit", name="грейпфрут", category="fruit", nutrients_per_100g=NutrientVector())
    potato = Food(id="potato", name="картофель", category="grains", nutrients_per_100g=NutrientVector())
    egg = Food(id="egg", name="яйцо", category="protein", nutrients_per_100g=NutrientVector())

    orange_text = format_ingredient(FoodPortion(orange, 40))
    mandarin_text = format_ingredient(FoodPortion(mandarins, 75))
    grapefruit_text = format_ingredient(FoodPortion(grapefruit, 80))
    potato_text = format_ingredient(FoodPortion(potato, 110))
    egg_text = format_ingredient(FoodPortion(egg, 25))

    assert "1/2 апельсина" not in orange_text
    assert "порции фрукта" not in mandarin_text
    assert "1 мандарин" in mandarin_text
    assert "3/4" not in grapefruit_text
    assert "1 небольшая картофелина" in potato_text
    assert "3/4 картофелины" not in potato_text
    assert egg_text == "яйцо - 1 шт."


def test_recipe_instruction_text_uses_kitchen_amounts() -> None:
    text = "Добавьте 37,5 мл молока, 8,33 г сахара, 0,071 ч. л. соли и 0,12 стакана воды."

    cleaned = clean_recipe_instruction_text(text)

    assert "37,5 мл" not in cleaned
    assert "8,33 г" not in cleaned
    assert "0,071 ч. л." not in cleaned
    assert "0,12 стакана" not in cleaned
    assert "40 мл" in cleaned
    assert "8 г" in cleaned
    assert "щепотку" in cleaned
    assert "2 ст. л." in cleaned


def test_recipe_instruction_text_removes_service_labels_without_losing_steps() -> None:
    text = (
        "Инструкция: Шаг 1. Разогрейте духовку до 180 °C. "
        "2) Смешайте творог с ягодами. Подписывайтесь на наш канал."
    )

    cleaned = clean_recipe_instruction_text(text)

    assert "Инструкция" not in cleaned
    assert "Шаг 1" not in cleaned
    assert "2)" not in cleaned
    assert "Подписывайтесь" not in cleaned
    assert "Разогрейте духовку до 180 °C." in cleaned
    assert "Смешайте творог с ягодами." in cleaned


def test_recipe_instruction_text_keeps_normal_recipe_text_unchanged() -> None:
    text = "Сварите овсянку до мягкости. Добавьте йогурт и ягоды."

    assert clean_recipe_instruction_text(text) == text


def test_recipe_instruction_text_normalizes_fractional_kitchen_units() -> None:
    text = "Добавьте 2 1/2 ч. л. крахмала, 1/4 стакана воды и 0,33 г соли."

    cleaned = clean_recipe_instruction_text(text)

    assert "2 1/2 ч. л." not in cleaned
    assert "1/4 стакана" not in cleaned
    assert "0,33 г" not in cleaned
    assert "2,5 ч. л." in cleaned
    assert "несколько столовых ложек" in cleaned
    assert "менее 1 г" in cleaned


def test_meal_card_can_hide_photo_credit() -> None:
    session = start_session()
    for answer in [
        "32",
        "мужчина",
        "178",
        "86",
        "похудение",
        "умеренная",
        "4",
        "15–30 минут",
        "нет",
        "нет",
        "нет",
        "нет",
    ]:
        session, error = session.receive(answer)
        assert error is None

    plan = build_one_day_plan(session.build_profile())
    meal = next(item for item in plan.meals if item.image_url)
    card = format_meal_card(meal, include_photo_credit=False)

    assert "Фото:" not in card
