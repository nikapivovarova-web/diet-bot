from __future__ import annotations

from .domain import ActivityLevel, Goal, NutrientVector, NutritionTargets, Sex, UserProfile


ACTIVITY_MULTIPLIERS: dict[ActivityLevel, float] = {
    ActivityLevel.SEDENTARY: 1.2,
    ActivityLevel.LIGHT: 1.375,
    ActivityLevel.MODERATE: 1.55,
    ActivityLevel.ACTIVE: 1.725,
    ActivityLevel.VERY_ACTIVE: 1.9,
}


def calculate_bmi(weight_kg: float, height_cm: float) -> float:
    height_m = height_cm / 100
    return weight_kg / (height_m * height_m)


def bmi_category(bmi: float) -> str:
    if bmi < 18.5:
        return "underweight"
    if bmi < 25:
        return "normal"
    if bmi < 30:
        return "overweight"
    return "obesity"


def calculate_bmr(profile: UserProfile) -> float:
    base = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * profile.age
    if profile.sex == Sex.MALE:
        return base + 5
    return base - 161


def calculate_tdee(profile: UserProfile) -> float:
    return calculate_bmr(profile) * ACTIVITY_MULTIPLIERS[profile.activity]


def calculate_targets(profile: UserProfile) -> NutritionTargets:
    bmi = calculate_bmi(profile.weight_kg, profile.height_cm)
    bmr = calculate_bmr(profile)
    tdee = calculate_tdee(profile)
    energy = _goal_energy(profile.goal, tdee)
    protein_g = _protein_target(profile)
    fat_g = round((energy * 0.30) / 9)
    carb_g = round((energy - protein_g * 4 - fat_g * 9) / 4)
    fiber_g = 38 if profile.sex == Sex.MALE and profile.age <= 50 else 25

    macros = {
        "energy_kcal": round(energy),
        "protein_g": round(protein_g),
        "fat_g": round(fat_g),
        "carbohydrate_g": round(carb_g),
        "fiber_g": fiber_g,
    }
    micronutrients = _micronutrient_targets(profile)
    targets = NutrientVector(macros | micronutrients)
    _validate_macro_energy(targets)

    return NutritionTargets(
        bmi=round(bmi, 1),
        bmi_category=bmi_category(bmi),
        bmr_kcal=round(bmr),
        tdee_kcal=round(tdee),
        targets=targets,
        calorie_bounds=(energy * 0.92, energy * 1.08),
        macro_bounds={
            "protein_g": (protein_g * 0.85, protein_g * 1.50),
            "fat_g": (fat_g * 0.80, fat_g * 1.25),
            "carbohydrate_g": (carb_g * 0.80, carb_g * 1.25),
        },
    )


def _goal_energy(goal: Goal, tdee: float) -> float:
    if goal == Goal.LOSE:
        return max(1200.0, tdee * 0.85)
    if goal == Goal.GAIN:
        return tdee * 1.10
    return tdee


def _protein_target(profile: UserProfile) -> float:
    if profile.goal == Goal.LOSE:
        return profile.weight_kg * 1.6
    if profile.goal == Goal.GAIN:
        return profile.weight_kg * 1.8
    return profile.weight_kg * 1.1


def _micronutrient_targets(profile: UserProfile) -> dict[str, float]:
    female_19_to_50 = profile.sex == Sex.FEMALE and profile.age <= 50
    return {
        "sodium_mg": 2300,
        "potassium_mg": 3400 if profile.sex == Sex.MALE else 2600,
        "calcium_mg": 1200 if profile.sex == Sex.FEMALE and profile.age >= 51 else 1000,
        "magnesium_mg": 420 if profile.sex == Sex.MALE else 320,
        "iron_mg": 18 if female_19_to_50 else 8,
        "zinc_mg": 11 if profile.sex == Sex.MALE else 8,
        "vitamin_c_mg": 90 if profile.sex == Sex.MALE else 75,
        "vitamin_d_mcg": 15,
        "vitamin_b12_mcg": 2.4,
        "folate_mcg_dfe": 400,
        "vitamin_b6_mg": 1.3 if profile.age <= 50 else 1.7,
        "vitamin_a_mcg_rae": 900 if profile.sex == Sex.MALE else 700,
        "vitamin_e_mg": 15,
        "omega_3_mg": 1000,
    }


def _validate_macro_energy(targets: NutrientVector) -> None:
    energy = targets.get("energy_kcal")
    macro_energy = (
        targets.get("protein_g") * 4
        + targets.get("carbohydrate_g") * 4
        + targets.get("fat_g") * 9
    )
    if macro_energy > energy * 1.10:
        raise ValueError(
            f"Macro targets are impossible: {macro_energy:.0f} kcal from macros for {energy:.0f} kcal target."
        )


def validate_custom_targets(targets: NutrientVector) -> None:
    _validate_macro_energy(targets)
