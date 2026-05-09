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
    assert targets.targets.get("iodine_mcg") == 150
    assert targets.targets.get("selenium_mcg") == 55
    assert targets.targets.get("phosphorus_mg") == 700
    assert targets.targets.get("vitamin_k_mcg") == 120
    assert targets.targets.get("vitamin_b1_mg") == 1.2
    assert targets.targets.get("vitamin_b2_mg") == 1.3
    assert targets.targets.get("vitamin_b3_mg") == 16
    assert targets.targets.get("saturated_fat_g") > 0
    assert targets.targets.get("added_sugar_g") > 0
    assert targets.bmi_category == "overweight"
    assert targets.water_l > 2


def test_high_bmi_protein_target_uses_adjusted_weight() -> None:
    profile = UserProfile(
        age=35,
        sex=Sex.MALE,
        height_cm=170,
        weight_kg=132,
        goal=Goal.LOSE,
        activity=ActivityLevel.LIGHT,
    )

    targets = calculate_targets(profile)

    assert targets.bmi == 45.7
    assert targets.targets.get("protein_g") == 139
    assert targets.targets.get("protein_g") < 160


def test_high_bmi_gain_protein_target_does_not_scale_from_full_weight() -> None:
    profile = UserProfile(
        age=35,
        sex=Sex.MALE,
        height_cm=170,
        weight_kg=117,
        goal=Goal.GAIN,
        activity=ActivityLevel.LIGHT,
    )

    targets = calculate_targets(profile)

    assert targets.bmi == 40.5
    assert targets.targets.get("protein_g") == 150
    assert targets.targets.get("protein_g") < 180


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
