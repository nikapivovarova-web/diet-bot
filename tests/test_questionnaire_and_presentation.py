from diet_bot.builder import build_one_day_plan
from diet_bot.domain import ConditionCode, Goal, Sex
from diet_bot.presentation import format_meal_card, format_plan_response
from diet_bot.questionnaire import QUESTIONS, start_session
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
    assert ConditionCode.LACTOSE_INTOLERANCE in profile.conditions
    assert ConditionCode.CKD in profile.conditions
    assert profile.restrictions[0].value == "яблоко"


def test_button_questions_have_options() -> None:
    questions = {question.key: question for question in QUESTIONS}

    assert questions["sex"].options == ("👨 Мужчина", "👩 Женщина")
    assert questions["goal"].options == ("⬇️ Похудение", "⚖️ Поддержание", "💪 Набор")
    assert questions["meal_count"].options == ("3", "4", "5")
    assert "⚡ Очень высокая" in questions["activity"].options


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
        "нет",
        "нет",
        "нет",
        "нет",
    ]

    for answer in answers:
        session, error = session.receive(answer)
        assert error is None

    assert session.build_profile().weight_kg == 62.5


def test_questionnaire_rejects_invalid_meal_count() -> None:
    session = start_session()
    for answer in ["32", "женщина", "165", "60", "поддержание", "легкая"]:
        session, error = session.receive(answer)
        assert error is None

    assert QUESTIONS[session.step_index].key == "meal_count"
    next_session, error = session.receive("8")

    assert next_session == session
    assert error is not None


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
    assert "Рацион на день" in text
    assert "Список покупок" in text
    assert "Что осталось доработать" not in text
    assert "Техническая проверка" not in text
    assert "яблоко" not in {portion.food.name for meal in plan.meals for portion in meal.portions}


def test_meal_card_includes_photo_credit_when_available() -> None:
    session = start_session()
    for answer in [
        "32",
        "мужчина",
        "178",
        "86",
        "похудение",
        "умеренная",
        "4",
        "нет",
        "нет",
        "нет",
        "нет",
    ]:
        session, error = session.receive(answer)
        assert error is None

    plan = build_one_day_plan(session.build_profile())
    meal = next(item for item in plan.meals if item.image_url)
    card = format_meal_card(meal)

    assert "Фото:" in card
    assert "Wikimedia Commons" in card
