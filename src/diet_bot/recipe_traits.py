from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .recipe_catalog import RecipeTemplate


UNKNOWN = "unknown"

_RECIPE_NO_RE = re.compile(r"^r(?P<number>\d{3,})(?:\D|$)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RecipeTraits:
    recipe_id: str
    recipe_no: int | None
    source_batch: str
    source_tag: str
    native_slot: str
    allowed_meal_slots: frozenset[str]
    slot_flex_type: str
    primary_protein: str
    primary_carb: str
    recipe_format: str
    cooking_effort: str
    active_time_bucket: str
    main_signal: str


def infer_recipe_traits(recipe: RecipeTemplate) -> RecipeTraits:
    native_slot = _clean_value(recipe.slot)
    allowed_slots = _allowed_meal_slots(recipe, native_slot)
    slot_flex_type = _clean_value(recipe.slot_flex_type) or "native"
    recipe_no = infer_recipe_number(recipe.id)
    return RecipeTraits(
        recipe_id=recipe.id,
        recipe_no=recipe_no,
        source_batch=_explicit_trait(recipe, "source_batch") or infer_source_batch(recipe.id),
        source_tag=_source_tag(recipe.tags),
        native_slot=native_slot or UNKNOWN,
        allowed_meal_slots=allowed_slots,
        slot_flex_type=slot_flex_type,
        primary_protein=infer_primary_protein(recipe),
        primary_carb=infer_primary_carb(recipe),
        recipe_format=infer_recipe_format(recipe),
        cooking_effort=_cooking_effort(recipe),
        active_time_bucket=_active_time_bucket(recipe),
        main_signal=_main_signal(native_slot, allowed_slots, slot_flex_type),
    )


def infer_recipe_number(recipe_id: str) -> int | None:
    match = _RECIPE_NO_RE.match(recipe_id.strip())
    if match is None:
        return None
    return int(match.group("number"))


def infer_source_batch(recipe_id: str) -> str:
    recipe_no = infer_recipe_number(recipe_id)
    if recipe_no is None:
        return UNKNOWN
    if recipe_no <= 400:
        return "r001-r400"
    if recipe_no <= 610:
        return "r401-r610"
    return "r611+"


def infer_primary_protein(recipe: RecipeTemplate) -> str:
    explicit = _explicit_trait(recipe, "primary_protein")
    if explicit:
        return explicit

    scores: dict[str, float] = {}
    for food_id, grams in recipe.ingredients_g.items():
        family = _ingredient_family(food_id, _PROTEIN_EXACT, _PROTEIN_KEYWORDS)
        if family is None:
            continue
        scores[family] = scores.get(family, 0.0) + max(float(grams), 0.0) * _PROTEIN_DENSITY_WEIGHT[family]
    if scores:
        return _best_scored_family(scores, _PROTEIN_PRIORITY)

    return _text_family(_recipe_text(recipe), _PROTEIN_TEXT_KEYWORDS) or UNKNOWN


def infer_primary_carb(recipe: RecipeTemplate) -> str:
    explicit = _explicit_trait(recipe, "primary_carb")
    if explicit:
        return explicit

    starch_scores: dict[str, float] = {}
    has_fruit_or_veg = False
    for food_id, grams in recipe.ingredients_g.items():
        family = _ingredient_family(food_id, _CARB_EXACT, _CARB_KEYWORDS)
        if family in _STARCH_CARB_FAMILIES:
            starch_scores[family] = starch_scores.get(family, 0.0) + max(float(grams), 0.0)
        elif family == "fruit_veg":
            has_fruit_or_veg = True

    if starch_scores:
        return _best_scored_family(starch_scores, _CARB_PRIORITY)

    text_family = _text_family(_recipe_text(recipe), _CARB_TEXT_KEYWORDS)
    if text_family in _STARCH_CARB_FAMILIES:
        return text_family
    if has_fruit_or_veg or text_family == "fruit_veg":
        return "fruit_veg"
    if recipe.ingredients_g:
        return "low_carb"
    return UNKNOWN


def infer_recipe_format(recipe: RecipeTemplate) -> str:
    explicit = _explicit_trait(recipe, "recipe_format") or _explicit_trait(recipe, "format")
    if explicit:
        return explicit

    text = _recipe_text(recipe)
    for recipe_format, keywords in _FORMAT_KEYWORDS:
        if _contains_any(text, keywords):
            return recipe_format
    ingredient_format = _ingredient_carrier_format(recipe.ingredients_g)
    if ingredient_format:
        return ingredient_format
    if _has_protein_side_pattern(recipe):
        return "protein_side"
    if _clean_value(recipe.slot) == "snack":
        return "snack"
    return UNKNOWN


def _allowed_meal_slots(recipe: RecipeTemplate, native_slot: str) -> frozenset[str]:
    slots = frozenset(_clean_value(slot) for slot in recipe.allowed_meal_slots if _clean_value(slot))
    if slots:
        return slots
    return frozenset({native_slot}) if native_slot else frozenset()


def _source_tag(tags: Iterable[str]) -> str:
    source_tags = sorted(
        tag.split(":", 1)[1].strip()
        for tag in tags
        if tag.strip().lower().startswith("source:") and tag.split(":", 1)[1].strip()
    )
    return source_tags[0] if source_tags else UNKNOWN


def _explicit_trait(recipe: RecipeTemplate, field_name: str) -> str | None:
    value = _clean_value(str(getattr(recipe, field_name, "") or ""))
    if value:
        return value
    tag_prefixes = (f"{field_name}:", f"{field_name}=")
    for tag in sorted(recipe.tags):
        normalized = tag.strip()
        lower = normalized.lower()
        for prefix in tag_prefixes:
            if lower.startswith(prefix):
                return _clean_value(normalized[len(prefix) :]) or None
    return None


def _ingredient_family(
    food_id: str,
    exact: dict[str, str],
    keywords: tuple[tuple[str, str], ...],
) -> str | None:
    normalized = _clean_value(food_id)
    if normalized in exact:
        return exact[normalized]
    for keyword, family in keywords:
        if keyword in normalized:
            return family
    return None


def _best_scored_family(scores: dict[str, float], priority: tuple[str, ...]) -> str:
    priority_index = {family: index for index, family in enumerate(priority)}
    return sorted(scores, key=lambda family: (-scores[family], priority_index.get(family, len(priority))))[0]


def _recipe_text(recipe: RecipeTemplate) -> str:
    return " ".join(
        (
            _clean_text(recipe.id),
            _clean_text(recipe.title),
            _clean_text(recipe.instructions),
        )
    )


def _recipe_name_text(recipe: RecipeTemplate) -> str:
    return " ".join((_clean_text(recipe.id), _clean_text(recipe.title)))


def _text_family(text: str, keyword_map: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    for family, keywords in keyword_map:
        if _contains_any(text, keywords):
            return family
    return None


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    tokens = frozenset(_TOKEN_RE.findall(text))
    for keyword in keywords:
        keyword = keyword.lower()
        if " " in keyword:
            if keyword in text:
                return True
            continue
        if keyword in tokens or any(token.startswith(keyword) for token in tokens):
            return True
    return False


def _ingredient_carrier_format(ingredients_g: dict[str, float]) -> str | None:
    ingredients = frozenset(_clean_value(food_id) for food_id in ingredients_g)
    for recipe_format, exact_ids, keyword_ids in _FORMAT_INGREDIENT_CARRIERS:
        if ingredients.intersection(exact_ids):
            return recipe_format
        if any(keyword in ingredient for ingredient in ingredients for keyword in keyword_ids):
            return recipe_format
    return None


def _has_protein_side_pattern(recipe: RecipeTemplate) -> bool:
    if _clean_value(recipe.slot) != "main":
        return False
    if infer_primary_protein(recipe) == UNKNOWN:
        return False
    if infer_primary_carb(recipe) in {UNKNOWN, "low_carb"}:
        return False
    return _contains_any(_recipe_name_text(recipe), _PROTEIN_SIDE_TEXT_KEYWORDS)


def _clean_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lower().replace("-", " ").replace("_", " ")


def _cooking_effort(recipe: RecipeTemplate) -> str:
    effort = _clean_value(recipe.cooking_effort)
    if effort in {"simple", "interesting"}:
        return effort
    return UNKNOWN


def _active_time_bucket(recipe: RecipeTemplate) -> str:
    minutes = recipe.active_time_min
    if minutes is None:
        minutes = _parse_minutes(recipe.time_text)
    if minutes is None:
        return UNKNOWN
    if minutes <= 15:
        return "quick"
    if minutes <= 30:
        return "medium"
    return "long"


def _parse_minutes(time_text: str) -> int | None:
    text = _clean_text(time_text)
    hour_matches = re.findall(r"(\d+)\s*(?:h|hr|hrs|hour|hours)", text)
    minute_matches = re.findall(r"(\d+)\s*(?:m|min|mins|minute|minutes)", text)
    values = [int(value) * 60 for value in hour_matches] + [int(value) for value in minute_matches]
    return max(values) if values else None


def _main_signal(native_slot: str, allowed_slots: frozenset[str], slot_flex_type: str) -> str:
    if native_slot == "main":
        return "main"
    if "main" in allowed_slots:
        if native_slot == "snack" or "light" in slot_flex_type:
            return "light_main"
        return "main_flexible"
    if native_slot == "snack":
        return "light"
    return UNKNOWN


_PROTEIN_PRIORITY = (
    "poultry",
    "meat",
    "fish",
    "seafood",
    "egg",
    "plant_protein",
    "dairy",
)

_PROTEIN_DENSITY_WEIGHT = {
    "poultry": 1.4,
    "meat": 1.4,
    "fish": 1.4,
    "seafood": 1.4,
    "egg": 1.1,
    "plant_protein": 0.9,
    "dairy": 0.7,
}

_PROTEIN_EXACT = {
    "egg": "egg",
    "egg_white": "egg",
    "egg_white_extra": "egg",
    "egg_yolk": "egg",
    "tofu": "plant_protein",
    "tempeh": "plant_protein",
    "edamame": "plant_protein",
    "lentils": "plant_protein",
    "red_lentils": "plant_protein",
    "green_lentils": "plant_protein",
    "chickpeas": "plant_protein",
    "hummus": "plant_protein",
    "black_beans": "plant_protein",
    "white_beans": "plant_protein",
    "red_kidney_beans": "plant_protein",
    "kidney_beans": "plant_protein",
    "pinto_beans": "plant_protein",
    "cannellini_beans": "plant_protein",
    "greek_yogurt": "dairy",
    "lactose_free_yogurt": "dairy",
    "yogurt": "dairy",
    "cottage_cheese": "dairy",
    "lactose_free_cottage_cheese": "dairy",
    "kefir": "dairy",
    "milk": "dairy",
    "ricotta": "dairy",
    "feta": "dairy",
    "cheddar": "dairy",
    "gouda": "dairy",
    "mozzarella": "dairy",
    "parmesan": "dairy",
    "cream_cheese": "dairy",
    "goat_cheese": "dairy",
    "swiss_cheese": "dairy",
    "salmon": "fish",
    "trout": "fish",
    "cod": "fish",
    "tuna": "fish",
    "tuna_steak": "fish",
    "sprats": "fish",
    "anchovies": "fish",
    "shrimp": "seafood",
    "crab": "seafood",
    "squid": "seafood",
    "mussels": "seafood",
    "scallops": "seafood",
}

_PROTEIN_KEYWORDS = (
    ("chicken", "poultry"),
    ("turkey", "poultry"),
    ("duck", "poultry"),
    ("beef", "meat"),
    ("pork", "meat"),
    ("lamb", "meat"),
    ("bacon", "meat"),
    ("ham", "meat"),
    ("chorizo", "meat"),
    ("sausage", "meat"),
    ("prosciutto", "meat"),
    ("salmon", "fish"),
    ("trout", "fish"),
    ("cod", "fish"),
    ("haddock", "fish"),
    ("tuna", "fish"),
    ("sprat", "fish"),
    ("anchov", "fish"),
    ("fish", "fish"),
    ("shrimp", "seafood"),
    ("prawn", "seafood"),
    ("crab", "seafood"),
    ("squid", "seafood"),
    ("mussel", "seafood"),
    ("scallop", "seafood"),
    ("seafood", "seafood"),
    ("tofu", "plant_protein"),
    ("tempeh", "plant_protein"),
    ("edamame", "plant_protein"),
    ("lentil", "plant_protein"),
    ("chickpea", "plant_protein"),
    ("bean", "plant_protein"),
    ("hummus", "plant_protein"),
    ("yogurt", "dairy"),
    ("yoghurt", "dairy"),
    ("cottage_cheese", "dairy"),
    ("cheese", "dairy"),
    ("kefir", "dairy"),
    ("ricotta", "dairy"),
    ("feta", "dairy"),
    ("mozzarella", "dairy"),
)

_PROTEIN_TEXT_KEYWORDS = (
    ("poultry", ("chicken", "turkey")),
    ("meat", ("beef", "pork", "lamb", "bacon", "ham", "chorizo", "sausage")),
    ("fish", ("salmon", "trout", "cod", "tuna", "sprat", "anchovy", "fish")),
    ("seafood", ("shrimp", "prawn", "crab", "squid", "mussels", "scallop", "seafood")),
    ("egg", ("egg",)),
    ("plant_protein", ("tofu", "lentil", "chickpea", "beans", "bean", "hummus", "edamame")),
    ("dairy", ("yogurt", "cottage cheese", "cheese", "kefir", "ricotta")),
)

_STARCH_CARB_FAMILIES = frozenset(
    {
        "rice",
        "buckwheat",
        "oats",
        "pasta",
        "potato",
        "bread",
        "grain",
        "legume",
    }
)

_CARB_PRIORITY = (
    "rice",
    "buckwheat",
    "oats",
    "pasta",
    "potato",
    "bread",
    "grain",
    "legume",
)

_CARB_EXACT = {
    "rice": "rice",
    "brown_rice": "rice",
    "rice_flour": "rice",
    "rice_noodles": "rice",
    "buckwheat": "buckwheat",
    "buckwheat_groats": "buckwheat",
    "soba_noodles": "buckwheat",
    "oats": "oats",
    "rolled_oats": "oats",
    "steel_cut_oats": "oats",
    "oat_flour": "oats",
    "muesli": "oats",
    "granola": "oats",
    "pasta": "pasta",
    "whole_wheat_pasta": "pasta",
    "spaghetti": "pasta",
    "linguine": "pasta",
    "orzo": "pasta",
    "gnocchi": "pasta",
    "egg_noodles": "pasta",
    "potato": "potato",
    "sweet_potato": "potato",
    "batat": "potato",
    "whole_grain_bread": "bread",
    "bread": "bread",
    "rye_bread": "bread",
    "lavash": "bread",
    "tortilla": "bread",
    "pita": "bread",
    "pitta": "bread",
    "bagel": "bread",
    "english_muffin": "bread",
    "crackers": "bread",
    "crispbread": "bread",
    "quinoa": "grain",
    "barley": "grain",
    "bulgur": "grain",
    "farro": "grain",
    "millet": "grain",
    "couscous": "grain",
    "corn": "grain",
    "polenta": "grain",
    "lentils": "legume",
    "red_lentils": "legume",
    "green_lentils": "legume",
    "chickpeas": "legume",
    "black_beans": "legume",
    "white_beans": "legume",
    "red_kidney_beans": "legume",
    "kidney_beans": "legume",
    "pinto_beans": "legume",
    "apple": "fruit_veg",
    "banana": "fruit_veg",
    "berries": "fruit_veg",
    "blueberries": "fruit_veg",
    "raspberries": "fruit_veg",
    "strawberries": "fruit_veg",
    "mango": "fruit_veg",
    "pear": "fruit_veg",
    "peach": "fruit_veg",
    "orange": "fruit_veg",
    "pineapple": "fruit_veg",
    "kiwi": "fruit_veg",
    "grapes": "fruit_veg",
    "dates": "fruit_veg",
    "raisins": "fruit_veg",
    "spinach": "fruit_veg",
    "tomato": "fruit_veg",
    "cucumber": "fruit_veg",
    "bell_pepper": "fruit_veg",
    "broccoli": "fruit_veg",
    "zucchini": "fruit_veg",
    "carrot": "fruit_veg",
}

_CARB_KEYWORDS = (
    ("rice", "rice"),
    ("buckwheat", "buckwheat"),
    ("soba", "buckwheat"),
    ("oat", "oats"),
    ("muesli", "oats"),
    ("granola", "oats"),
    ("pasta", "pasta"),
    ("spaghetti", "pasta"),
    ("linguine", "pasta"),
    ("noodle", "pasta"),
    ("orzo", "pasta"),
    ("gnocchi", "pasta"),
    ("potato", "potato"),
    ("batat", "potato"),
    ("bread", "bread"),
    ("toast", "bread"),
    ("lavash", "bread"),
    ("tortilla", "bread"),
    ("pita", "bread"),
    ("pitta", "bread"),
    ("bagel", "bread"),
    ("cracker", "bread"),
    ("quinoa", "grain"),
    ("barley", "grain"),
    ("bulgur", "grain"),
    ("farro", "grain"),
    ("millet", "grain"),
    ("couscous", "grain"),
    ("lentil", "legume"),
    ("chickpea", "legume"),
    ("bean", "legume"),
    ("fruit", "fruit_veg"),
    ("berry", "fruit_veg"),
    ("berries", "fruit_veg"),
    ("apple", "fruit_veg"),
    ("banana", "fruit_veg"),
    ("vegetable", "fruit_veg"),
)

_CARB_TEXT_KEYWORDS = (
    ("rice", ("rice", "ris", "gohan", "plov", "biryani", "rizotto", "risotto")),
    ("buckwheat", ("buckwheat", "grech", "soba")),
    ("oats", ("oat", "oats", "oatmeal", "ovsyan", "myusli", "muesli", "granola")),
    ("pasta", ("pasta", "spaghetti", "linguine", "noodle", "orzo", "gnocchi", "nokki")),
    ("potato", ("potato", "kartof", "batat")),
    ("bread", ("bread", "toast", "tost", "lavash", "tortilla", "pita", "pitta", "bagel", "cracker")),
    ("grain", ("quinoa", "kinoa", "barley", "bulgur", "farro", "millet", "couscous", "kuskus")),
    ("legume", ("lentil", "chechev", "chickpea", "nut", "bean", "fasol", "hummus")),
    ("fruit_veg", ("fruit", "berry", "berries", "apple", "banana", "vegetable")),
)

_FORMAT_KEYWORDS = (
    ("soup", ("soup", "sup", "borsch", "broth", "minestrone", "harira", "shorba", "chowder")),
    ("stew", ("stew", "ragu", "chili", "karri", "curry", "tushen", "gulyash", "dal", "masala", "bigus")),
    (
        "pasta",
        (
            "pasta",
            "spaghetti",
            "spagetti",
            "linguine",
            "lingvini",
            "noodle",
            "noodles",
            "lapsha",
            "lapshoy",
            "makarony",
            "karbonara",
            "kacho e pepe",
            "tetratstsini",
            "lo meyn",
            "ramen",
            "udon",
            "soba",
            "orzo",
            "gnocchi",
            "nokki",
            "ziti",
        ),
    ),
    ("salad", ("salad", "salat", "tabule", "tabbouleh", "coleslaw", "slaw")),
    (
        "egg_dish",
        (
            "omelet",
            "omlet",
            "frittata",
            "shakshuk",
            "menemen",
            "skrembl",
            "scramble",
            "yaytsa",
            "yaichn",
            "tamago",
            "tortilya",
        ),
    ),
    ("smoothie", ("smoothie", "smuzi", "shake", "sheyk", "lassi", "latte", "napitok")),
    (
        "wrap",
        (
            "wrap",
            "roll",
            "rolly",
            "rulet",
            "ruletik",
            "burrito",
            "quesadilla",
            "kesadilya",
            "lavash",
            "tortilla",
            "tako",
            "fajita",
            "fahit",
            "shaurm",
            "enchilad",
            "pita",
            "pitoy",
        ),
    ),
    ("sandwich", ("sandwich", "sendvich", "burger", "bap", "bagel", "beygl", "buterbrod")),
    ("toast", ("toast", "tost", "bruschetta", "brusketta", "crostini", "krostini")),
    ("stuffed", ("stuffed", "farshirov", "golubtsy", "dolma", "boats")),
    (
        "cutlet",
        (
            "cutlet",
            "cutlets",
            "kotlet",
            "patty",
            "patties",
            "fritter",
            "fritters",
            "frikadel",
            "teftel",
            "falafel",
            "draniki",
            "zrazy",
            "oladi",
        ),
    ),
    ("bowl", ("bowl", "boul", "chasha", "tarelka", "poke", "bibimbap", "budda", "buddha")),
    (
        "rice_dish",
        (
            "risotto",
            "rizotto",
            "plov",
            "pilaf",
            "dzhambalay",
            "jambalaya",
            "paella",
            "biryani",
            "kuskus",
            "couscous",
            "kedzheri",
        ),
    ),
    ("porridge", ("porridge", "oatmeal", "ovsyanka", "kasha", "birher", "congee", "kondzhi")),
    (
        "dessert",
        (
            "dessert",
            "desert",
            "pudding",
            "puding",
            "parfait",
            "parfe",
            "cheesecake",
            "chizkeyk",
            "tiramisu",
            "pankeyk",
            "vafl",
            "krepy",
            "blin",
            "granola",
            "muffin",
            "maffin",
            "syrnik",
            "shokolad",
            "karamel",
        ),
    ),
    (
        "bake",
        (
            "bake",
            "baked",
            "casserole",
            "zapekan",
            "zapech",
            "gratin",
            "lazanya",
            "lasagna",
            "oven",
            "duhovk",
            "protivne",
            "musaka",
            "pirog",
            "khachapuri",
            "hachapuri",
            "krambl",
        ),
    ),
    (
        "skillet",
        (
            "skillet",
            "hash",
            "hesh",
            "stir fry",
            "stir_fry",
            "skovorod",
            "zharen",
            "obzhar",
            "sote",
            "pulkogi",
            "kung pao",
            "mapo",
            "pisto",
        ),
    ),
    ("snack", ("snack", "dip", "chips", "nuts", "orekhi", "semechki", "plate", "kreker", "cracker")),
)

_FORMAT_INGREDIENT_CARRIERS = (
    (
        "pasta",
        frozenset(
            {
                "pasta",
                "whole_wheat_pasta",
                "pasta_generic",
                "spaghetti",
                "linguine",
                "orzo",
                "gnocchi",
                "egg_noodles",
                "rice_noodles",
                "soba_noodles",
                "udon_noodles",
            }
        ),
        ("pasta", "spaghetti", "linguine", "noodle", "soba", "udon", "orzo", "gnocchi"),
    ),
    (
        "wrap",
        frozenset({"lavash", "tortilla", "flour_tortilla", "corn_tortilla", "pita", "pitta"}),
        ("tortilla",),
    ),
    (
        "sandwich",
        frozenset({"bread", "whole_grain_bread", "rye_bread", "bagel", "english_muffin", "crispbread"}),
        (),
    ),
)

_PROTEIN_SIDE_TEXT_KEYWORDS = (
    "kurits",
    "kurin",
    "chicken",
    "indeyk",
    "turkey",
    "govyad",
    "beef",
    "svinin",
    "pork",
    "baran",
    "lamb",
    "losos",
    "salmon",
    "tresk",
    "cod",
    "ryba",
    "fish",
    "tunets",
    "tuna",
    "tofu",
    "krevet",
    "shrimp",
    "kalmar",
    "calamari",
    "pechen",
)
