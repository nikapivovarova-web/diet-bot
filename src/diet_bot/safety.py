from __future__ import annotations

import re

from .domain import (
    ConditionCode,
    Food,
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


FOOD_EXCLUSION_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("\u044f\u0439", "egg"),
        (
            "\u044f\u0439\u0446\u043e",
            "\u044f\u0439\u0446\u0430",
            "\u044f\u0438\u0446",
            "\u044f\u0438\u0447",
            "\u044f\u0438\u0447\u043d\u044b\u0439 \u0431\u0435\u043b\u043e\u043a",
            "\u044f\u0438\u0447\u043d\u044b\u0439 \u0436\u0435\u043b\u0442\u043e\u043a",
            "\u0436\u0435\u043b\u0442\u043e\u043a",
            "egg",
            "eggs",
            "egg yolk",
            "egg white",
            "egg noodles",
            "egg_noodles",
            "egg_yolk",
            "egg_white_extra",
        ),
    ),
    (
        ("\u0431\u0440\u043e\u043a", "broccoli", "broccolini"),
        (
            "\u0431\u0440\u043e\u043a\u043a\u043e\u043b\u0438",
            "\u0431\u0440\u043e\u043a\u043a\u043e\u043b\u0438\u043d\u0438",
            "broccoli",
            "broccolini",
            "broccoli rabe",
        ),
    ),
    (
        ("гриб", "шампиньон", "mushroom"),
        ("гриб", "грибы", "шампиньон", "шампиньоны", "mushroom", "mushrooms", "шиитаке", "shiitake"),
    ),
    (
        ("орех", "nuts"),
        (
            "орех",
            "орехи",
            "грецкий орех",
            "грецкие орехи",
            "миндаль",
            "арахис",
            "кешью",
            "пекан",
            "фисташки",
            "walnut",
            "walnuts",
            "almond",
            "almonds",
            "peanut",
            "peanuts",
            "cashew",
            "cashews",
            "pecan",
            "pecans",
            "pistachio",
            "pistachios",
            "nuts",
        ),
    ),
    (
        ("арахис", "peanut"),
        ("арахис", "арахисовая паста", "peanut", "peanuts", "peanut butter"),
    ),
    (
        ("молок", "молоч", "dairy", "milk"),
        (
            "молоко",
            "молочные продукты",
            "творог",
            "йогурт",
            "сыр",
            "milk",
            "dairy",
            "cottage cheese",
            "yogurt",
            "cheese",
        ),
    ),
    (
        ("рыб", "fish"),
        ("рыба", "лосось", "тунец", "треска", "fish", "salmon", "tuna", "cod", "white fish"),
    ),
    (
        ("морепродукт", "кревет", "seafood", "shrimp"),
        ("морепродукты", "креветки", "мидии", "кальмар", "seafood", "shrimp", "mussels", "calamari"),
    ),
)


def evaluate_safety(profile: UserProfile) -> SafetyResult:
    excluded_tags: set[str] = set()
    excluded_food_names: set[str] = set()
    caution_notes: list[str] = []
    disclaimers: list[str] = []
    red_flags: list[str] = []

    if profile.age < 18:
        red_flags.append("age under 18")

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
            excluded_food_names.update(_expanded_excluded_food_names(value))
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
        else:
            excluded_tags.add("lactose_free")

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
    normalized = _normalize_exclusion_match_text(food_name)
    return any(_matches_excluded_name(normalized, name) for name in excluded_names)


def is_food_excluded(food: Food, excluded_names: frozenset[str]) -> bool:
    return any(
        is_name_excluded(value, excluded_names)
        for value in (
            food.name,
            food.id,
            food.id.replace("_", " "),
        )
    )


def _expanded_excluded_food_names(value: str) -> set[str]:
    names = {value}
    for needles, aliases in FOOD_EXCLUSION_ALIASES:
        if any(needle in value for needle in needles):
            names.update(normalize_text(alias) for alias in aliases)
    return {name for name in names if name}


def _normalize_exclusion_match_text(value: str) -> str:
    return normalize_text(value).replace("_", " ")


def _matches_excluded_name(normalized_food_name: str, excluded_name: str) -> bool:
    normalized_excluded = _normalize_exclusion_match_text(excluded_name)
    if not normalized_excluded:
        return False
    if _is_latin_exclusion(normalized_excluded):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_excluded)}(?![a-z0-9])",
                normalized_food_name,
            )
        )
    return normalized_excluded in normalized_food_name or normalized_food_name in normalized_excluded


def _is_latin_exclusion(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9 ]*[a-z0-9]", value))
