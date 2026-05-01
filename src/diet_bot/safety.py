from __future__ import annotations

from .domain import (
    ConditionCode,
    RestrictionType,
    SafetyResult,
    UserProfile,
    normalize_text,
)


MEDICAL_DISCLAIMER = (
    "Этот рацион не является медицинским назначением или клинической рекомендацией. "
    "Если у вас есть диагностированное заболевание, согласуйте рацион с лечащим врачом "
    "или клиническим диетологом."
)


RED_FLAG_CONDITIONS = {
    ConditionCode.PREGNANCY: "pregnancy",
    ConditionCode.LACTATION: "lactation",
    ConditionCode.EATING_DISORDER: "eating disorder",
    ConditionCode.DIALYSIS: "dialysis",
    ConditionCode.ONCOLOGY: "oncology treatment",
    ConditionCode.SEVERE_LIVER_DISEASE: "severe liver disease",
}


def evaluate_safety(profile: UserProfile) -> SafetyResult:
    excluded_tags: set[str] = set()
    excluded_food_names: set[str] = set()
    caution_notes: list[str] = []
    disclaimers: list[str] = []
    red_flags: list[str] = []

    if profile.age < 18:
        red_flags.append("age under 18")

    bmi = profile.weight_kg / ((profile.height_cm / 100) ** 2)
    if bmi < 16:
        red_flags.append("very low BMI")

    for condition in profile.conditions:
        if condition in RED_FLAG_CONDITIONS:
            red_flags.append(RED_FLAG_CONDITIONS[condition])

    _apply_restrictions(profile, excluded_tags, excluded_food_names)
    _apply_conditions(profile, excluded_tags, caution_notes)

    if profile.conditions:
        disclaimers.append(MEDICAL_DISCLAIMER)

    if red_flags:
        disclaimers.append(
            "По указанным данным бот не должен составлять персональный рацион. "
            "Лучше обсудить питание с врачом очно."
        )

    return SafetyResult(
        can_generate_plan=not red_flags,
        excluded_tags=frozenset(excluded_tags),
        excluded_food_names=frozenset(excluded_food_names),
        caution_notes=tuple(caution_notes),
        disclaimers=tuple(dict.fromkeys(disclaimers)),
        red_flags=tuple(red_flags),
    )


def _apply_restrictions(
    profile: UserProfile,
    excluded_tags: set[str],
    excluded_food_names: set[str],
) -> None:
    for restriction in profile.restrictions:
        value = restriction.normalized_value
        if restriction.type in {RestrictionType.ALLERGY, RestrictionType.EXCLUDED_FOOD}:
            excluded_food_names.add(value)
        if restriction.type == RestrictionType.INTOLERANCE:
            if "лактоз" in value or "lactose" in value:
                excluded_tags.add("lactose")
            if "глютен" in value or "gluten" in value:
                excluded_tags.add("gluten")


def _apply_conditions(
    profile: UserProfile,
    excluded_tags: set[str],
    caution_notes: list[str],
) -> None:
    conditions = set(profile.conditions)

    if ConditionCode.CELIAC in conditions or ConditionCode.GLUTEN_INTOLERANCE in conditions:
        excluded_tags.add("gluten")
        if not profile.allow_gluten_free_oats:
            excluded_tags.add("oats")
        caution_notes.append(
            "Глютен исключен. Овес допустим только сертифицированный gluten-free и после согласования с врачом."
        )

    if ConditionCode.LACTOSE_INTOLERANCE in conditions:
        excluded_tags.add("lactose")
        if profile.allow_lactose_free_dairy:
            caution_notes.append("Обычные молочные продукты с лактозой исключены; допустимы безлактозные аналоги.")

    if ConditionCode.CKD in conditions:
        excluded_tags.add("high_sodium")
        caution_notes.append(
            "При ХПН белок, натрий, калий и фосфор зависят от стадии болезни и анализов; рацион нужно согласовать с нефрологом."
        )

    if ConditionCode.DIABETES in conditions:
        excluded_tags.add("sweet_drink")
        caution_notes.append(
            "При диабете углеводы и приемы пищи должны учитывать терапию и целевые значения глюкозы."
        )

    if ConditionCode.HYPERTENSION in conditions:
        excluded_tags.add("high_sodium")
        caution_notes.append("При гипертонии ограничены очень соленые и ультрапереработанные продукты.")

    if ConditionCode.GERD in conditions or ConditionCode.GASTRITIS in conditions:
        excluded_tags.add("very_spicy")
        caution_notes.append("При ГЭРБ/гастрите исключены агрессивно острые и кислые шаблоны блюд.")

    if ConditionCode.GOUT in conditions:
        excluded_tags.add("organ_meat")
        caution_notes.append("При подагре ограничены субпродукты и избыток красного мяса.")


def is_name_excluded(food_name: str, excluded_names: frozenset[str]) -> bool:
    normalized = normalize_text(food_name)
    return any(name in normalized or normalized in name for name in excluded_names)
