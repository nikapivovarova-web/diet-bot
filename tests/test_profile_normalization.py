from diet_bot.domain import ActivityLevel, ConditionCode, Goal, RestrictionType, Sex
from diet_bot.profile_normalization import _condition_code_for_item, normalize_conditions, normalize_free_text_list
from diet_bot.questionnaire import start_session
from diet_bot.telegram_app import _profile_from_dict, _profile_to_dict


def test_free_text_list_deduplicates_case_and_spaces() -> None:
    normalized = normalize_free_text_list("Молоко, молоко, МОЛОКО")

    assert normalized.errors == []
    assert normalized.items == ["молоко"]


def test_free_text_list_splits_common_separators() -> None:
    normalized = normalize_free_text_list(" молоко ; яйца \n арахис ")

    assert normalized.errors == []
    assert normalized.items == ["молоко", "яйца", "арахис"]


def test_free_text_list_rejects_oversized_raw_answer() -> None:
    normalized = normalize_free_text_list("м" * 301)

    assert normalized.items == []
    assert normalized.errors


def test_free_text_list_rejects_more_than_twelve_items() -> None:
    normalized = normalize_free_text_list(", ".join(f"еда{i}" for i in range(13)))

    assert normalized.was_trimmed
    assert len(normalized.items) == 12
    assert normalized.errors


def test_free_text_list_skips_overlong_items() -> None:
    normalized = normalize_free_text_list(f"молоко, {'оченьдлинныйпродукт' * 3}")

    assert normalized.errors == []
    assert normalized.items == ["молоко"]


def test_conditions_are_stored_as_known_codes_only() -> None:
    normalized = normalize_conditions("диабет, давление, гастрит")

    assert normalized.errors == []
    assert normalized.items == [
        ConditionCode.DIABETES.value,
        ConditionCode.HYPERTENSION.value,
        ConditionCode.GASTRITIS.value,
    ]


def test_condition_code_does_not_treat_food_allergy_as_eating_disorder() -> None:
    for item in ("пищевая аллергия", "пищевод", "пищеварение", "пищевое отравление"):
        assert _condition_code_for_item(item) is None


def test_condition_code_recognizes_explicit_eating_disorder_terms() -> None:
    assert _condition_code_for_item("пищевое расстройство") == ConditionCode.EATING_DISORDER
    assert _condition_code_for_item("РПП") == ConditionCode.EATING_DISORDER


def test_conditions_reject_unrecognized_text() -> None:
    normalized = normalize_conditions("странное состояние")

    assert normalized.items == []
    assert normalized.errors


def test_conditions_reject_partially_unrecognized_text() -> None:
    normalized = normalize_conditions("диабет, странное состояние")

    assert normalized.items == [ConditionCode.DIABETES.value]
    assert normalized.errors
    assert "Я распознал" in normalized.errors[0]


def test_questionnaire_stores_normalized_answers_not_raw_text() -> None:
    session = start_session()
    answers = [
        "32",
        "мужчина",
        "178",
        "86",
        "похудение",
        "умеренная",
        "4",
        "до 15 минут",
        "Молоко, молоко",
        "лактоза",
        "диабет, давление",
        "Свинина; печень",
    ]

    for answer in answers:
        session, error = session.receive(answer)
        assert error is None

    profile = session.build_profile()

    assert [restriction.value for restriction in profile.restrictions] == [
        "молоко",
        "лактоза",
        "свинина",
        "печень",
    ]
    assert profile.conditions == (ConditionCode.DIABETES, ConditionCode.HYPERTENSION, ConditionCode.LACTOSE_INTOLERANCE)


def test_questionnaire_rejects_too_many_free_text_items() -> None:
    session = start_session()
    for answer in ["32", "мужчина", "178", "86", "похудение", "умеренная", "4", "до 15 минут"]:
        session, error = session.receive(answer)
        assert error is None

    next_session, error = session.receive(", ".join(f"еда{i}" for i in range(13)))

    assert next_session == session
    assert error is not None


def test_legacy_profile_free_text_fields_are_migrated() -> None:
    profile = _profile_from_dict(
        {
            "age": 32,
            "sex": Sex.MALE.value,
            "height_cm": 178,
            "weight_kg": 86,
            "goal": Goal.LOSE.value,
            "activity": ActivityLevel.MODERATE.value,
            "meal_count": 4,
            "restrictions": [
                {"type": RestrictionType.ALLERGY.value, "value": "Молоко; молоко; яйца"},
                {"type": RestrictionType.EXCLUDED_FOOD.value, "value": "Свинина, печень"},
            ],
            "intolerances": ["лактоза", "лактоза"],
            "conditions": "diabetes_type_2, давление, неизвестное",
        }
    )

    assert profile is not None
    assert [restriction.value for restriction in profile.restrictions] == [
        "молоко",
        "яйца",
        "свинина",
        "печень",
        "лактоза",
    ]
    assert profile.conditions == (
        ConditionCode.DIABETES,
        ConditionCode.HYPERTENSION,
        ConditionCode.LACTOSE_INTOLERANCE,
    )

    saved = _profile_to_dict(profile)

    assert "allergies" not in saved
    assert "excluded_foods" not in saved
    assert saved["conditions"] == [
        ConditionCode.DIABETES.value,
        ConditionCode.HYPERTENSION.value,
        ConditionCode.LACTOSE_INTOLERANCE.value,
    ]


def test_stale_profile_with_invalid_measurements_is_rejected() -> None:
    profile = _profile_from_dict(
        {
            "age": 32,
            "sex": Sex.MALE.value,
            "height_cm": 0,
            "weight_kg": 86,
            "goal": Goal.LOSE.value,
            "activity": ActivityLevel.MODERATE.value,
            "meal_count": 4,
        }
    )

    assert profile is None
