from __future__ import annotations

import re
from dataclasses import dataclass

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
MATCH_TOKEN_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF]+")


@dataclass(frozen=True)
class FoodExclusionCategory:
    canonical_id: str
    canonical_name: str
    trigger_aliases: tuple[str, ...]
    ingredient_ids: tuple[str, ...]
    aliases: tuple[str, ...]
    excluded_tags: tuple[str, ...] = ()


FOOD_EXCLUSION_CATEGORIES: tuple[FoodExclusionCategory, ...] = (
    FoodExclusionCategory(
        canonical_id="egg",
        canonical_name="eggs",
        trigger_aliases=("\u044f\u0439", "\u044f\u0438\u0447", "egg", "eggs"),
        ingredient_ids=("egg", "egg_white", "egg_white_extra", "egg_yolk", "egg_noodles"),
        aliases=(
            "\u044f\u0439\u0446\u043e",
            "\u044f\u0439\u0446\u0430",
            "\u044f\u0438\u0446",
            "\u044f\u0438\u0447\u043d\u044b\u0439",
            "\u044f\u0438\u0447\u043d\u044b\u0439 \u0431\u0435\u043b\u043e\u043a",
            "\u044f\u0438\u0447\u043d\u044b\u0439 \u0436\u0435\u043b\u0442\u043e\u043a",
            "\u0436\u0435\u043b\u0442\u043e\u043a",
            "egg",
            "eggs",
            "egg white",
            "egg yolk",
            "egg noodles",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="broccoli",
        canonical_name="broccoli",
        trigger_aliases=("\u0431\u0440\u043e\u043a\u043a\u043e\u043b", "broccoli", "broccolini"),
        ingredient_ids=("broccoli",),
        aliases=(
            "\u0431\u0440\u043e\u043a\u043a\u043e\u043b\u0438",
            "\u0431\u0440\u043e\u043a\u043a\u043e\u043b\u0438\u043d\u0438",
            "broccoli",
            "broccolini",
            "broccoli rabe",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="porridge",
        canonical_name="porridge",
        trigger_aliases=("\u043a\u0430\u0448", "porridge"),
        ingredient_ids=(),
        aliases=(
            "\u043a\u0430\u0448\u0430",
            "\u043a\u0430\u0448\u0438",
            "\u043a\u0430\u0448\u0443",
            "\u043e\u0432\u0441\u044f\u043d\u043a\u0430",
            "\u043e\u0432\u0441\u044f\u043d\u043a\u043e\u0439",
            "\u043e\u0432\u0441\u044f\u043d\u043a\u0443",
            "\u043e\u0432\u0441\u044f\u043d\u0430\u044f \u043a\u0430\u0448\u0430",
            "\u043e\u0432\u0441\u044f\u043d\u0430\u044f \u0447\u0430\u0448\u0430",
            "\u043e\u0432\u0441\u044f\u043d\u0430\u044f \u0442\u0430\u0440\u0435\u043b\u043a\u0430",
            "\u043e\u0432\u0441\u044f\u043d\u044b\u0439 \u0431\u043e\u0443\u043b",
            "\u043b\u0435\u043d\u0438\u0432\u0430\u044f \u043e\u0432\u0441\u044f\u043d\u043a\u0430",
            "\u0433\u0440\u0435\u0447\u043d\u0435\u0432\u0430\u044f \u043a\u0430\u0448\u0430",
            "\u0440\u0438\u0441\u043e\u0432\u0430\u044f \u043a\u0430\u0448\u0430",
            "\u043f\u0448\u0435\u043d\u043d\u0430\u044f \u043a\u0430\u0448\u0430",
            "\u043c\u0430\u043d\u043d\u0430\u044f \u043a\u0430\u0448\u0430",
            "\u043f\u0435\u0440\u043b\u043e\u0432\u0430\u044f \u043a\u0430\u0448\u0430",
            "\u043a\u0443\u043a\u0443\u0440\u0443\u0437\u043d\u0430\u044f \u043a\u0430\u0448\u0430",
            "\u043a\u0430\u0448\u0430 \u0438\u0437 \u043a\u0438\u043d\u043e\u0430",
            "porridge",
            "oatmeal",
            "overnight oats",
            "oat porridge",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="dairy",
        canonical_name="milk and dairy",
        trigger_aliases=(
            "\u043c\u043e\u043b\u043e\u0447",
            "\u043b\u0430\u043a\u0442\u043e\u0437",
            "dairy",
            "lactose",
        ),
        ingredient_ids=(
            "milk",
            "buttermilk",
            "greek_yogurt",
            "lactose_free_yogurt",
            "cottage_cheese",
            "lactose_free_cottage_cheese",
            "cream_cheese",
            "goat_cheese",
            "american_cheese",
            "processed_cheese",
            "swiss_cheese",
            "gouda",
            "cheddar",
            "feta",
            "mozzarella",
            "parmesan",
            "ricotta",
            "mascarpone",
        ),
        aliases=(
            "\u043c\u043e\u043b\u043e\u043a\u043e",
            "\u043c\u043e\u043b\u043e\u0447\u043d\u044b\u0435 \u043f\u0440\u043e\u0434\u0443\u043a\u0442\u044b",
            "\u043c\u043e\u043b\u043e\u0447\u043d\u044b\u0439",
            "\u043c\u043e\u043b\u043e\u0447\u043d\u0430\u044f",
            "\u043c\u043e\u043b\u043e\u0447\u043d\u043e\u0435",
            "\u0439\u043e\u0433\u0443\u0440\u0442",
            "\u0442\u0432\u043e\u0440\u043e\u0433",
            "\u0441\u044b\u0440",
            "milk",
            "dairy",
            "yogurt",
            "cottage cheese",
            "cheese",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="cottage_cheese",
        canonical_name="cottage cheese",
        trigger_aliases=("\u0442\u0432\u043e\u0440\u043e\u0433", "\u0442\u0432\u043e\u0440\u043e\u0436", "cottage cheese"),
        ingredient_ids=("cottage_cheese", "lactose_free_cottage_cheese"),
        aliases=(
            "\u0442\u0432\u043e\u0440\u043e\u0433",
            "\u0442\u0432\u043e\u0440\u043e\u0436\u043d\u044b\u0439",
            "\u0442\u0432\u043e\u0440\u043e\u0436\u043d\u0430\u044f",
            "\u0442\u0432\u043e\u0440\u043e\u0436\u043d\u044b\u0435",
            "cottage cheese",
            "curd",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="cheese",
        canonical_name="cheese",
        trigger_aliases=("\u0441\u044b\u0440", "cheese"),
        ingredient_ids=(
            "cream_cheese",
            "goat_cheese",
            "american_cheese",
            "processed_cheese",
            "swiss_cheese",
            "gouda",
            "cheddar",
            "feta",
            "mozzarella",
            "parmesan",
            "ricotta",
            "mascarpone",
        ),
        aliases=(
            "\u0441\u044b\u0440",
            "\u0441\u044b\u0440\u043d\u044b\u0439",
            "\u0441\u044b\u0440\u043d\u0430\u044f",
            "\u0441\u044b\u0440\u043d\u044b\u0435",
            "\u0444\u0435\u0442\u0430",
            "\u0447\u0435\u0434\u0434\u0435\u0440",
            "\u0433\u0430\u0443\u0434\u0430",
            "\u043f\u0430\u0440\u043c\u0435\u0437\u0430\u043d",
            "\u0440\u0438\u043a\u043e\u0442\u0442\u0430",
            "\u043c\u043e\u0446\u0430\u0440\u0435\u043b\u043b\u0430",
            "cheese",
            "cheddar",
            "gouda",
            "feta",
            "parmesan",
            "ricotta",
            "mozzarella",
            "cream cheese",
            "goat cheese",
            "swiss cheese",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="tree_nuts",
        canonical_name="nuts",
        trigger_aliases=("\u043e\u0440\u0435\u0445", "nut", "nuts"),
        ingredient_ids=(
            "almond_butter",
            "almonds",
            "brazil_nuts",
            "cashews",
            "mixed_nuts",
            "nuts_mix",
            "pecans",
            "pine_nuts",
            "pistachios",
            "walnuts",
            "peanut_butter",
            "peanut_oil",
            "peanuts",
        ),
        aliases=(
            "\u043e\u0440\u0435\u0445",
            "\u043e\u0440\u0435\u0445\u0438",
            "\u043c\u0438\u043d\u0434\u0430\u043b\u044c",
            "\u043a\u0435\u0448\u044c\u044e",
            "\u043f\u0435\u043a\u0430\u043d",
            "\u0444\u0438\u0441\u0442\u0430\u0448\u043a\u0438",
            "\u0433\u0440\u0435\u0446\u043a\u0438\u0439 \u043e\u0440\u0435\u0445",
            "\u0433\u0440\u0435\u0446\u043a\u0438\u0435 \u043e\u0440\u0435\u0445\u0438",
            "\u0431\u0440\u0430\u0437\u0438\u043b\u044c\u0441\u043a\u0438\u0435 \u043e\u0440\u0435\u0445\u0438",
            "\u043a\u0435\u0434\u0440\u043e\u0432\u044b\u0435 \u043e\u0440\u0435\u0445\u0438",
            "\u0430\u0440\u0430\u0445\u0438\u0441",
            "nut",
            "nuts",
            "walnut",
            "walnuts",
            "almond",
            "almonds",
            "cashew",
            "cashews",
            "pecan",
            "pecans",
            "pistachio",
            "pistachios",
            "brazil nut",
            "brazil nuts",
            "pine nut",
            "pine nuts",
            "peanut",
            "peanuts",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="peanut",
        canonical_name="peanut",
        trigger_aliases=("\u0430\u0440\u0430\u0445\u0438\u0441", "peanut"),
        ingredient_ids=("peanut_butter", "peanut_oil", "peanuts"),
        aliases=(
            "\u0430\u0440\u0430\u0445\u0438\u0441",
            "\u0430\u0440\u0430\u0445\u0438\u0441\u043e\u0432\u0430\u044f \u043f\u0430\u0441\u0442\u0430",
            "\u0430\u0440\u0430\u0445\u0438\u0441\u043e\u0432\u043e\u0435 \u043c\u0430\u0441\u043b\u043e",
            "peanut",
            "peanuts",
            "peanut butter",
            "peanut oil",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="fish",
        canonical_name="fish",
        trigger_aliases=("\u0440\u044b\u0431", "fish", "salmon", "tuna", "cod"),
        ingredient_ids=(
            "cod_fillet",
            "fish_sauce",
            "fish_stock",
            "mackerel",
            "salmon",
            "smoked_white_fish",
            "tuna",
            "tuna_steak",
            "white_fish",
        ),
        aliases=(
            "\u0440\u044b\u0431\u0430",
            "\u0440\u044b\u0431\u043d\u044b\u0439",
            "\u043b\u043e\u0441\u043e\u0441\u044c",
            "\u0442\u0443\u043d\u0435\u0446",
            "\u0442\u0440\u0435\u0441\u043a\u0430",
            "\u0441\u043a\u0443\u043c\u0431\u0440\u0438\u044f",
            "\u0431\u0435\u043b\u0430\u044f \u0440\u044b\u0431\u0430",
            "fish",
            "salmon",
            "tuna",
            "cod",
            "mackerel",
            "white fish",
            "fish sauce",
            "fish stock",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="seafood",
        canonical_name="seafood",
        trigger_aliases=(
            "\u043c\u043e\u0440\u0435\u043f\u0440\u043e\u0434\u0443\u043a\u0442",
            "\u043a\u0440\u0435\u0432\u0435\u0442",
            "\u043c\u0438\u0434\u0438",
            "\u043a\u0430\u043b\u044c\u043c\u0430\u0440",
            "seafood",
            "shrimp",
            "prawn",
            "mussel",
            "calamari",
        ),
        ingredient_ids=("calamari", "clams", "crab_sticks", "mussels", "scallops", "seafood_mix", "shrimp"),
        aliases=(
            "\u043c\u043e\u0440\u0435\u043f\u0440\u043e\u0434\u0443\u043a\u0442\u044b",
            "\u043a\u0440\u0435\u0432\u0435\u0442\u043a\u0438",
            "\u043a\u0440\u0435\u0432\u0435\u0442\u043a\u0430",
            "\u043c\u0438\u0434\u0438\u0438",
            "\u043a\u0430\u043b\u044c\u043c\u0430\u0440",
            "\u0433\u0440\u0435\u0431\u0435\u0448\u043a\u0438",
            "\u043a\u0440\u0430\u0431",
            "seafood",
            "shrimp",
            "shrimps",
            "prawn",
            "prawns",
            "mussels",
            "calamari",
            "scallops",
            "clams",
            "crab",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="meat",
        canonical_name="meat and poultry",
        trigger_aliases=("\u043c\u044f\u0441", "meat"),
        ingredient_ids=(
            "bacon",
            "beef_broth",
            "beef_chuck",
            "beef_ground",
            "beef_sirloin",
            "beef_stew",
            "chicken_breast",
            "chicken_breast_cooked",
            "chicken_broth",
            "chicken_drumstick",
            "chicken_ground",
            "chicken_liver",
            "chicken_thigh",
            "chicken_thigh_skinless",
            "chorizo",
            "ground_meat",
            "ham",
            "italian_sausage",
            "lamb_ground",
            "pork_chop",
            "pork_loin",
            "pork_tenderloin",
            "prosciutto",
            "sausage",
            "turkey",
            "turkey_breast_cooked",
            "turkey_ground",
            "turkey_or_chicken_breast",
        ),
        aliases=(
            "\u043c\u044f\u0441\u043e",
            "\u043c\u044f\u0441\u043d\u043e\u0439",
            "\u043c\u044f\u0441\u043d\u0430\u044f",
            "\u043c\u044f\u0441\u043d\u043e\u0435",
            "\u043f\u0442\u0438\u0446\u0430",
            "\u043a\u0443\u0440\u0438\u0446\u0430",
            "\u043a\u0443\u0440\u0438\u043d\u0430\u044f",
            "\u043a\u0443\u0440\u0438\u043d\u044b\u0439",
            "\u0438\u043d\u0434\u0435\u0439\u043a\u0430",
            "\u0433\u0440\u0443\u0434\u043a\u0430 \u0438\u043d\u0434\u0435\u0439\u043a\u0438",
            "\u0433\u043e\u0432\u044f\u0434\u0438\u043d\u0430",
            "\u0433\u043e\u0432\u044f\u0436\u0438\u0439",
            "\u0433\u043e\u0432\u044f\u0436\u0438\u0439 \u0444\u0430\u0440\u0448",
            "\u0441\u0432\u0438\u043d\u0438\u043d\u0430",
            "\u0441\u0432\u0438\u043d\u0430\u044f",
            "\u0431\u0430\u0440\u0430\u043d\u0438\u043d\u0430",
            "\u0431\u0430\u0440\u0430\u043d\u0438\u0439 \u0444\u0430\u0440\u0448",
            "\u0444\u0430\u0440\u0448",
            "\u043c\u044f\u0441\u043d\u043e\u0439 \u0444\u0430\u0440\u0448",
            "\u043a\u0443\u0440\u0438\u043d\u044b\u0439 \u0444\u0430\u0440\u0448",
            "\u0444\u0430\u0440\u0448 \u0438\u043d\u0434\u0435\u0439\u043a\u0438",
            "\u0431\u0435\u043a\u043e\u043d",
            "\u0432\u0435\u0442\u0447\u0438\u043d\u0430",
            "\u043a\u043e\u043b\u0431\u0430\u0441\u0430",
            "\u0441\u043e\u0441\u0438\u0441\u043a\u0438",
            "\u0447\u043e\u0440\u0438\u0437\u043e",
            "meat",
            "poultry",
            "chicken",
            "turkey",
            "beef",
            "pork",
            "lamb",
            "ground meat",
            "minced meat",
            "ground beef",
            "ground chicken",
            "ground turkey",
            "ground lamb",
            "bacon",
            "ham",
            "sausage",
            "chorizo",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="minced_meat",
        canonical_name="minced meat",
        trigger_aliases=("\u0444\u0430\u0440\u0448", "ground meat", "minced meat"),
        ingredient_ids=("beef_ground", "chicken_ground", "ground_meat", "lamb_ground", "turkey_ground"),
        aliases=(
            "\u0444\u0430\u0440\u0448",
            "\u043c\u044f\u0441\u043d\u043e\u0439 \u0444\u0430\u0440\u0448",
            "\u0433\u043e\u0432\u044f\u0436\u0438\u0439 \u0444\u0430\u0440\u0448",
            "\u043a\u0443\u0440\u0438\u043d\u044b\u0439 \u0444\u0430\u0440\u0448",
            "\u0444\u0430\u0440\u0448 \u0438\u043d\u0434\u0435\u0439\u043a\u0438",
            "\u0431\u0430\u0440\u0430\u043d\u0438\u0439 \u0444\u0430\u0440\u0448",
            "ground meat",
            "minced meat",
            "ground beef",
            "ground chicken",
            "ground turkey",
            "ground lamb",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="chicken",
        canonical_name="chicken",
        trigger_aliases=("\u043a\u0443\u0440\u0438\u0446", "\u043a\u0443\u0440\u0438\u043d", "chicken"),
        ingredient_ids=(
            "chicken_breast",
            "chicken_breast_cooked",
            "chicken_broth",
            "chicken_drumstick",
            "chicken_ground",
            "chicken_liver",
            "chicken_thigh",
            "chicken_thigh_skinless",
            "turkey_or_chicken_breast",
        ),
        aliases=(
            "\u043a\u0443\u0440\u0438\u0446\u0430",
            "\u043a\u0443\u0440\u0438\u043d\u044b\u0439",
            "\u043a\u0443\u0440\u0438\u043d\u0430\u044f",
            "\u043a\u0443\u0440\u0438\u043d\u043e\u0435",
            "\u043a\u0443\u0440\u0438\u043d\u0430\u044f \u0433\u0440\u0443\u0434\u043a\u0430",
            "\u043a\u0443\u0440\u0438\u043d\u044b\u0439 \u0431\u0443\u043b\u044c\u043e\u043d",
            "\u043a\u0443\u0440\u0438\u043d\u043e\u0435 \u0444\u0438\u043b\u0435",
            "\u043a\u0443\u0440\u0438\u043d\u044b\u0439 \u0444\u0430\u0440\u0448",
            "\u043a\u0443\u0440\u0438\u043d\u0430\u044f \u043f\u0435\u0447\u0435\u043d\u044c",
            "chicken",
            "chicken breast",
            "chicken thigh",
            "chicken broth",
            "chicken drumstick",
            "ground chicken",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="turkey",
        canonical_name="turkey",
        trigger_aliases=("\u0438\u043d\u0434\u0435\u0439\u043a", "turkey"),
        ingredient_ids=("turkey", "turkey_breast_cooked", "turkey_ground", "turkey_or_chicken_breast"),
        aliases=(
            "\u0438\u043d\u0434\u0435\u0439\u043a\u0430",
            "\u0438\u043d\u0434\u0435\u0439\u043a\u0438",
            "\u0444\u0438\u043b\u0435 \u0438\u043d\u0434\u0435\u0439\u043a\u0438",
            "\u0433\u0440\u0443\u0434\u043a\u0430 \u0438\u043d\u0434\u0435\u0439\u043a\u0438",
            "\u0444\u0430\u0440\u0448 \u0438\u043d\u0434\u0435\u0439\u043a\u0438",
            "turkey",
            "turkey breast",
            "ground turkey",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="pork",
        canonical_name="pork",
        trigger_aliases=("\u0441\u0432\u0438\u043d", "\u0431\u0435\u043a\u043e\u043d", "\u0432\u0435\u0442\u0447\u0438\u043d", "pork", "bacon", "ham"),
        ingredient_ids=(
            "bacon",
            "chorizo",
            "ham",
            "italian_sausage",
            "pork_chop",
            "pork_loin",
            "pork_tenderloin",
            "prosciutto",
            "sausage",
        ),
        aliases=(
            "\u0441\u0432\u0438\u043d\u0438\u043d\u0430",
            "\u0441\u0432\u0438\u043d\u043e\u0439",
            "\u0441\u0432\u0438\u043d\u0430\u044f",
            "\u0441\u0432\u0438\u043d\u0430\u044f \u0432\u044b\u0440\u0435\u0437\u043a\u0430",
            "\u0441\u0432\u0438\u043d\u0430\u044f \u043e\u0442\u0431\u0438\u0432\u043d\u0430\u044f",
            "\u0431\u0435\u043a\u043e\u043d",
            "\u0432\u0435\u0442\u0447\u0438\u043d\u0430",
            "\u0447\u043e\u0440\u0438\u0437\u043e",
            "\u043f\u0440\u043e\u0448\u0443\u0442\u0442\u043e",
            "pork",
            "pork chop",
            "pork loin",
            "pork tenderloin",
            "bacon",
            "ham",
            "chorizo",
            "prosciutto",
            "sausage",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="beef",
        canonical_name="beef",
        trigger_aliases=("\u0433\u043e\u0432\u044f\u0434", "beef"),
        ingredient_ids=("beef_broth", "beef_chuck", "beef_ground", "beef_sirloin", "beef_stew", "ground_meat"),
        aliases=(
            "\u0433\u043e\u0432\u044f\u0434\u0438\u043d\u0430",
            "\u0433\u043e\u0432\u044f\u0436\u0438\u0439",
            "\u0433\u043e\u0432\u044f\u0436\u044c\u044f",
            "\u0433\u043e\u0432\u044f\u0436\u0438\u0439 \u0444\u0430\u0440\u0448",
            "\u0433\u043e\u0432\u044f\u0436\u0438\u0439 \u0431\u0443\u043b\u044c\u043e\u043d",
            "beef",
            "ground beef",
            "beef broth",
            "beef chuck",
            "beef sirloin",
            "beef stew",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="lamb",
        canonical_name="lamb",
        trigger_aliases=("\u0431\u0430\u0440\u0430\u043d", "lamb"),
        ingredient_ids=("lamb_ground",),
        aliases=(
            "\u0431\u0430\u0440\u0430\u043d\u0438\u043d\u0430",
            "\u0431\u0430\u0440\u0430\u043d\u0438\u0439",
            "\u0431\u0430\u0440\u0430\u043d\u0438\u0439 \u0444\u0430\u0440\u0448",
            "lamb",
            "ground lamb",
        ),
    ),
    FoodExclusionCategory(
        canonical_id="gluten_wheat",
        canonical_name="gluten and wheat",
        trigger_aliases=("\u0433\u043b\u044e\u0442\u0435\u043d", "\u043f\u0448\u0435\u043d", "gluten", "wheat"),
        ingredient_ids=(
            "breadcrumbs",
            "bulgur",
            "couscous",
            "egg_noodles",
            "gnocchi",
            "lavash",
            "orzo",
            "pasta_generic",
            "pita",
            "rye_flour",
            "spaghetti",
            "spelt",
            "thin_flatbread",
            "wheat_flour",
            "wheat_germ",
            "whole_grain_bread",
            "whole_wheat_pasta",
        ),
        aliases=(
            "\u0433\u043b\u044e\u0442\u0435\u043d",
            "\u043f\u0448\u0435\u043d\u0438\u0446\u0430",
            "\u043f\u0448\u0435\u043d\u0438\u0447\u043d\u044b\u0439",
            "\u043f\u0448\u0435\u043d\u0438\u0447\u043d\u0430\u044f \u043c\u0443\u043a\u0430",
            "\u0440\u0436\u0430\u043d\u0430\u044f \u043c\u0443\u043a\u0430",
            "\u043f\u0430\u0441\u0442\u0430",
            "\u043c\u0430\u043a\u0430\u0440\u043e\u043d\u044b",
            "\u0445\u043b\u0435\u0431",
            "\u043b\u0430\u0432\u0430\u0448",
            "\u043f\u0438\u0442\u0430",
            "\u043a\u0443\u0441\u043a\u0443\u0441",
            "\u0431\u0443\u043b\u0433\u0443\u0440",
            "gluten",
            "wheat",
            "wheat flour",
            "whole wheat",
            "whole grain bread",
            "bread",
            "pasta",
            "rye",
            "spelt",
            "bulgur",
            "couscous",
            "lavash",
            "pita",
        ),
        excluded_tags=("gluten",),
    ),
    FoodExclusionCategory(
        canonical_id="mushrooms",
        canonical_name="mushrooms",
        trigger_aliases=("\u0433\u0440\u0438\u0431", "\u0448\u0430\u043c\u043f\u0438\u043d\u044c\u043e\u043d", "mushroom"),
        ingredient_ids=("mushrooms", "shiitake"),
        aliases=(
            "\u0433\u0440\u0438\u0431",
            "\u0433\u0440\u0438\u0431\u044b",
            "\u0448\u0430\u043c\u043f\u0438\u043d\u044c\u043e\u043d",
            "\u0448\u0430\u043c\u043f\u0438\u043d\u044c\u043e\u043d\u044b",
            "\u0448\u0438\u0438\u0442\u0430\u043a\u0435",
            "\u0432\u0435\u0448\u0435\u043d\u043a\u0430",
            "\u0432\u0435\u0448\u0435\u043d\u043a\u0438",
            "\u0431\u0435\u043b\u044b\u0439 \u0433\u0440\u0438\u0431",
            "\u0431\u0435\u043b\u044b\u0435 \u0433\u0440\u0438\u0431\u044b",
            "\u043b\u0438\u0441\u0438\u0447\u043a\u0438",
            "\u043e\u043f\u044f\u0442\u0430",
            "mushroom",
            "mushrooms",
            "shiitake",
            "champignon",
            "champignons",
            "oyster mushroom",
            "oyster mushrooms",
            "porcini",
        ),
    ),
)

PLANT_MILK_EXCEPTIONS = (
    "almond milk",
    "coconut milk",
    "oat milk",
    "rice milk",
    "soy milk",
    "soya milk",
    "\u043c\u0438\u043d\u0434\u0430\u043b\u044c\u043d\u043e\u0435 \u043c\u043e\u043b\u043e\u043a\u043e",
    "\u043a\u043e\u043a\u043e\u0441\u043e\u0432\u043e\u0435 \u043c\u043e\u043b\u043e\u043a\u043e",
    "\u043e\u0432\u0441\u044f\u043d\u043e\u0435 \u043c\u043e\u043b\u043e\u043a\u043e",
    "\u0440\u0438\u0441\u043e\u0432\u043e\u0435 \u043c\u043e\u043b\u043e\u043a\u043e",
    "\u0441\u043e\u0435\u0432\u043e\u0435 \u043c\u043e\u043b\u043e\u043a\u043e",
)
MATCH_EXCEPTIONS_BY_EXCLUDED_NAME = {
    "milk": PLANT_MILK_EXCEPTIONS,
    "\u043c\u043e\u043b\u043e\u043a\u043e": PLANT_MILK_EXCEPTIONS,
}


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
            categories = _matching_exclusion_categories(value)
            excluded_food_names.update(_expanded_excluded_food_names(value, categories))
            for category in categories:
                excluded_tags.update(category.excluded_tags)
        if "\u043b\u0430\u043a\u0442\u043e\u0437" in value or "lactose" in value:
            excluded_tags.add("lactose")
        if "\u0433\u043b\u044e\u0442\u0435\u043d" in value or "gluten" in value:
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
    normalized_ids = {
        _normalize_exclusion_match_text(food.id),
        _normalize_exclusion_match_text(food.id.replace("_", " ")),
    }
    normalized_excluded = {_normalize_exclusion_match_text(name) for name in excluded_names}
    if normalized_ids & normalized_excluded:
        return True
    return any(
        is_name_excluded(value, excluded_names)
        for value in (
            food.name,
            food.id,
            food.id.replace("_", " "),
        )
    )


def _expanded_excluded_food_names(
    value: str,
    categories: tuple[FoodExclusionCategory, ...] | None = None,
) -> set[str]:
    names = {_normalize_exclusion_match_text(value)}
    matched_categories = categories if categories is not None else _matching_exclusion_categories(value)
    for category in matched_categories:
        names.update(
            _normalize_exclusion_match_text(term)
            for term in (
                category.canonical_id,
                category.canonical_name,
                *category.ingredient_ids,
                *category.aliases,
            )
        )
    return {name for name in names if name}


def _matching_exclusion_categories(value: str) -> tuple[FoodExclusionCategory, ...]:
    normalized_value = _normalize_exclusion_match_text(value)
    return tuple(
        category
        for category in FOOD_EXCLUSION_CATEGORIES
        if any(_matches_excluded_name(normalized_value, trigger) for trigger in category.trigger_aliases)
    )


def _normalize_exclusion_match_text(value: str) -> str:
    normalized = normalize_text(value)
    for separator in ("_", "-", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015"):
        normalized = normalized.replace(separator, " ")
    return " ".join(normalized.split())


def _matches_excluded_name(normalized_food_name: str, excluded_name: str) -> bool:
    normalized_excluded = _normalize_exclusion_match_text(excluded_name)
    if not normalized_excluded:
        return False
    if _has_match_exception(normalized_food_name, normalized_excluded):
        return False
    if normalized_food_name == normalized_excluded:
        return True
    if _is_latin_exclusion(normalized_excluded):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_excluded)}(?![a-z0-9])",
                normalized_food_name,
            )
        )
    return _tokenized_name_match(normalized_food_name, normalized_excluded) or _tokenized_name_match(
        normalized_excluded,
        normalized_food_name,
    )


def _tokenized_name_match(haystack: str, needle: str) -> bool:
    haystack_tokens = MATCH_TOKEN_RE.findall(haystack)
    needle_tokens = MATCH_TOKEN_RE.findall(needle)
    if not haystack_tokens or not needle_tokens:
        return False
    if len(needle_tokens) == 1:
        needle_token = needle_tokens[0]
        return any(token == needle_token or token.startswith(needle_token) for token in haystack_tokens)
    for index in range(0, len(haystack_tokens) - len(needle_tokens) + 1):
        window = haystack_tokens[index : index + len(needle_tokens)]
        if all(token == expected or token.startswith(expected) for token, expected in zip(window, needle_tokens)):
            return True
    return False


def _has_match_exception(normalized_food_name: str, normalized_excluded: str) -> bool:
    exceptions = MATCH_EXCEPTIONS_BY_EXCLUDED_NAME.get(normalized_excluded, ())
    return normalized_food_name in {
        _normalize_exclusion_match_text(exception)
        for exception in exceptions
    }


def _is_latin_exclusion(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9 ]*[a-z0-9]", value))
