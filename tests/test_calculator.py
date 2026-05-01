import pytest

from diet_bot.calculator import calculate_bmi, calculate_targets, validate_custom_targets
from diet_bot.domain import ActivityLevel, Goal, NutrientVector, Sex, UserProfile


def test_bmi_calculation() -> None:
    assert round(calculate_bmi(86, 178), 1) == 27.1


def test_targets_have_consistent_macros() -> None:
    profile = UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
    )
    targets = calculate_targets(profile)

    assert targets.targets.get("energy_kcal") > 0
    assert targets.targets.get("protein_g") > 100
    assert targets.targets.get("magnesium_mg") == 420
    assert targets.bmi_category == "overweight"


def test_impossible_macro_target_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_custom_targets(
            NutrientVector(
                {
                    "energy_kcal": 2000,
                    "protein_g": 100,
                    "carbohydrate_g": 200,
                    "fat_g": 300,
                }
            )
        )
