from __future__ import annotations

import json
import re
from dataclasses import dataclass

from scripts.dev.recipe_importer.loader import NormalizedRecipe


_TEXT_PATTERN = re.compile(
    r"^\s*(?P<name>.+?)\s*(?:—|–|:|\s-\s)\s*(?P<quantity>.+?)\s*$"
)
_QUANTITY_PATTERN = re.compile(
    r"(?:до\s*)?(?:≈|~=|~)?\s*"
    r"(?P<amount>\d+(?:[.,]\d+)?|\d+\s*/\s*\d+)"
    r"(?:\s*[–-]\s*\d+(?:[.,]\d+)?)?"
    r"\s*(?P<unit>"
    r"кг|kg|килограмм(?:а|ов)?|"
    r"г|g|гр|грамм(?:а|ов)?|"
    r"мл|ml|л|l|"
    r"ст\.?\s*л\.?|tbsp|tablespoons?|"
    r"ч\.?\s*л\.?|tsp|teaspoons?|"
    r"шт\.?|штук(?:и)?|зуб\.?|зуб(?:чик(?:а|ов)?)?|"
    r"яйц[ао]?|кружк(?:ов|а)?|пуч(?:ок|ка)?|пер(?:а|о)?|"
    r"стеб(?:ель|ля|лей)|лист(?:а|ов|ьев)?|веточ(?:ка|ки|ек)|"
    r"головк(?:а|и)?|стакан(?:а|ов)?|порци(?:я|и|ю)?|ломтик(?:а|ов)?|бан(?:ка|ки)"
    r")\b",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"\s*[•]\s*")
_NORMALIZATION_TAIL_RE = re.compile(
    r"\s+Нормализация\s+граммовок\s+для\s+импорта:.*$",
    re.IGNORECASE | re.DOTALL,
)
_COMMA_SPLIT_RE = re.compile(r"(?<!\d)\s*,\s*(?=[^,]*\d)")
_PLUS_SPLIT_RE = re.compile(
    r"\s+\+\s+(?=(?:вода|бульон|масло|оливковое масло|лимонный сок|сок)\b)",
    re.IGNORECASE,
)
_INLINE_QUANTITY_SPLIT_RE = re.compile(
    r"((?:\d+(?:[.,]\d+)?|\d+\s*/\s*\d+)\s*"
    r"(?:кг|г|гр|грамм(?:а|ов)?|мл|л|шт\.?|ст\.?\s*л\.?|ч\.?\s*л\.?)"
    r"(?:\s*\([^)]*\))?)"
    r"\s+(?=[A-ZА-ЯЁ][^•\n:]{1,60}\s*(?:—|–|-)\s*\d)",
    re.IGNORECASE,
)
_QUANTITY_FIRST_SPLIT_RE = re.compile(
    r"(?<!^)\s+(?=\d+(?:[.,]\d+)?\s*(?:кг|г|гр|мл|л|шт\.?|ст\.?\s*л\.?|ч\.?\s*л\.?)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedIngredient:
    name: str
    amount: float
    unit: str
    raw: str


@dataclass(frozen=True)
class IngredientParseResult:
    candidate_id: str
    parse_status: str
    blocker_reason: str
    ingredients: list[ParsedIngredient]


def parse_ingredients(recipe: NormalizedRecipe) -> IngredientParseResult:
    if recipe.structured_ingredients:
        return _parse_structured(recipe)
    if recipe.raw_ingredient_text:
        return _parse_text(recipe)
    return _blocked(recipe.candidate_id, "missing_ingredients")


def _parse_structured(recipe: NormalizedRecipe) -> IngredientParseResult:
    try:
        parsed = json.loads(recipe.structured_ingredients)
    except json.JSONDecodeError:
        return _blocked(recipe.candidate_id, "invalid_ingredients_json")
    if not isinstance(parsed, list):
        return _blocked(recipe.candidate_id, "ingredients_not_list")
    if not parsed:
        return _blocked(recipe.candidate_id, "missing_ingredients")

    ingredients: list[ParsedIngredient] = []
    for row in parsed:
        if not isinstance(row, dict):
            return _blocked(recipe.candidate_id, "invalid_ingredient_row")
        name = _pick(row, "name", "ingredient", "title")
        if not name:
            return _blocked(recipe.candidate_id, "missing_ingredient_name")
        raw_amount = _pick(row, "amount", "quantity", "qty")
        if raw_amount == "":
            return _blocked(recipe.candidate_id, "missing_ingredient_amount")
        amount = _parse_positive_amount(raw_amount)
        if amount is None:
            return _blocked(recipe.candidate_id, "invalid_ingredient_amount")
        unit = _pick(row, "unit", "measure", "measurement")
        ingredients.append(
            ParsedIngredient(
                name=str(name).strip(),
                amount=amount,
                unit=str(unit).strip(),
                raw=json.dumps(row, ensure_ascii=False, sort_keys=True),
            )
        )
    return IngredientParseResult(recipe.candidate_id, "parsed", "", ingredients)


def _parse_text(recipe: NormalizedRecipe) -> IngredientParseResult:
    ingredients: list[ParsedIngredient] = []
    lines = _ingredient_segments(recipe.raw_ingredient_text)
    if not lines:
        return _blocked(recipe.candidate_id, "missing_ingredients")

    for line in lines:
        parsed = _parse_text_line(line)
        if parsed is None:
            if _is_ignorable_amountless_line(line):
                continue
            return _blocked(recipe.candidate_id, "ambiguous_ingredient_text")
        name, amount, unit = parsed
        if not name:
            return _blocked(recipe.candidate_id, "missing_ingredient_name")
        ingredients.append(
            ParsedIngredient(
                name=name,
                amount=amount,
                unit=unit,
                raw=line,
            )
        )
    if not ingredients:
        return _blocked(recipe.candidate_id, "missing_ingredients")
    return IngredientParseResult(recipe.candidate_id, "parsed", "", ingredients)


def _pick(row: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return ""


def _parse_positive_amount(value: object) -> float | None:
    if isinstance(value, str) and "/" in value:
        fraction = _parse_fraction(value)
        if fraction is None:
            return None
        return fraction
    try:
        amount = float(str(value).replace(",", "."))
    except ValueError:
        return None
    if amount <= 0:
        return None
    return amount


def _ingredient_segments(value: str) -> list[str]:
    cleaned = _NORMALIZATION_TAIL_RE.sub("", value or "").strip()
    cleaned = _strip_leading_serving_header(cleaned)
    if not cleaned:
        return []

    raw_segments: list[str] = []
    for line in cleaned.splitlines():
        pieces = _BULLET_RE.split(line)
        raw_segments.extend(piece.strip() for piece in pieces if piece.strip())

    segments: list[str] = []
    for segment in raw_segments:
        segment = _INLINE_QUANTITY_SPLIT_RE.sub(r"\1\n", segment)
        if re.match(r"^\s*\d", segment):
            segment = _QUANTITY_FIRST_SPLIT_RE.sub("\n", segment)
        for piece in segment.splitlines():
            for plus_piece in _PLUS_SPLIT_RE.split(piece):
                segments.extend(
                    comma_piece.strip()
                    for comma_piece in _COMMA_SPLIT_RE.split(plus_piece)
                    if comma_piece.strip()
                )
    return segments


def _parse_text_line(line: str) -> tuple[str, float, str] | None:
    match = _TEXT_PATTERN.match(line)
    if match:
        quantity = _parse_text_quantity(match.group("quantity"), match.group("name"))
        if quantity is None:
            return None
        amount, unit = quantity
        return _clean_name(match.group("name")), amount, unit

    quantity_matches = list(_QUANTITY_PATTERN.finditer(line or ""))
    if not quantity_matches:
        return None
    quantity_match = _prefer_grams(quantity_matches)
    amount = _parse_positive_amount(quantity_match.group("amount"))
    if amount is None:
        return None
    raw_unit = quantity_match.group("unit")
    before = line[: quantity_match.start()].strip()
    after = line[quantity_match.end() :].strip()
    name = before or _name_from_quantity_first_unit(raw_unit, after)
    if not name:
        return None
    amount, unit = _normalize_amount_unit(_clean_name(name), amount, raw_unit)
    return _clean_name(name), amount, unit


def _strip_leading_serving_header(value: str) -> str:
    cleaned = re.sub(
        r"^\s*\d+\s+стандарт\.\s*/\s*\d+\s+мал\.\s*порци[ияй]\s+",
        "",
        value or "",
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^\s*\d+\s+стандарт\.\s*порци[ияй]\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^\s*\d+\s+[^\d:]+/\s*\d+\s+[^:]+:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _parse_text_quantity(value: str, name: str = "") -> tuple[float, str] | None:
    matches = list(_QUANTITY_PATTERN.finditer(value or ""))
    if not matches:
        return None

    chosen = _prefer_grams(matches)
    amount = _parse_positive_amount(chosen.group("amount"))
    if amount is None:
        return None
    return _normalize_amount_unit(name, amount, chosen.group("unit"))


def _prefer_grams(matches: list[re.Match[str]]) -> re.Match[str]:
    for match in reversed(matches):
        if _normalize_unit(match.group("unit")) == "g":
            return match
    return matches[-1]


def _normalize_unit(unit: str) -> str:
    normalized = (unit or "").strip().lower()
    if normalized in {"кг", "kg", "килограмм", "килограмма", "килограммов"}:
        return "kg"
    if normalized in {"г", "g", "гр", "грамм", "грамма", "граммов"}:
        return "g"
    if normalized in {"мл", "ml"}:
        return "ml"
    if normalized in {"л", "l"}:
        return "l"
    if re.fullmatch(r"ст\.?\s*л\.?|tbsp|tablespoons?", normalized):
        return "tbsp"
    if re.fullmatch(r"ч\.?\s*л\.?|tsp|teaspoons?", normalized):
        return "tsp"
    if re.fullmatch(
        r"шт\.?|штук(?:и)?|зуб\.?|зуб(?:чик(?:а|ов)?)?|яйц[ао]?|кружк(?:ов|а)?|"
        r"пуч(?:ок|ка)?|пер(?:а|о)?|стеб(?:ель|ля|лей)|лист(?:а|ов|ьев)?|"
        r"веточ(?:ка|ки|ек)|головк(?:а|и)?|стакан(?:а|ов)?|порци(?:я|и|ю)?|"
        r"ломтик(?:а|ов)?|бан(?:ка|ки)",
        normalized,
    ):
        return "count"
    return normalized


def _normalize_amount_unit(name: str, amount: float, raw_unit: str) -> tuple[float, str]:
    unit = _normalize_unit(raw_unit)
    if unit == "kg":
        return round(amount * 1000, 2), "g"
    if unit == "l":
        return round(amount * 1000, 2), "ml"
    if unit == "tbsp":
        return round(amount * 15, 2), "ml"
    if unit == "tsp":
        return round(amount * 5, 2), "ml"
    if unit == "count":
        grams = _count_grams(name, raw_unit)
        if grams is not None:
            return round(amount * grams, 2), "g"
    return round(amount, 2), unit


def _parse_fraction(value: str) -> float | None:
    parts = [part.strip() for part in value.split("/", 1)]
    if len(parts) != 2:
        return None
    try:
        numerator = float(parts[0].replace(",", "."))
        denominator = float(parts[1].replace(",", "."))
    except ValueError:
        return None
    if denominator <= 0:
        return None
    return numerator / denominator


def _clean_name(value: str) -> str:
    cleaned = re.sub(r"\([^)]*\)", "", value or "")
    cleaned = cleaned.replace("*", " ")
    cleaned = re.sub(r"\s+", " ", cleaned.replace("•", " ")).strip(" .:-;")
    cleaned = re.sub(r"\b\d+(?:[.,]\d+)?\s*$", "", cleaned).strip(" .:-;")
    return cleaned


def _name_from_quantity_first_unit(unit: str, after: str) -> str:
    normalized = (unit or "").casefold()
    if normalized.startswith("яйц"):
        return "яйцо"
    return after


def _count_grams(name: str, unit: str) -> float | None:
    text = f"{name} {unit}".casefold().replace("ё", "е")
    if "зуб" in text or "чеснок" in text:
        return 5.0
    if "яй" in text:
        return 50.0
    if "лук" in text and "зелен" not in text:
        return 100.0
    if "помид" in text or "томат" in text:
        return 120.0
    if "перец" in text and "черн" not in text and "чили" not in text:
        return 150.0
    if "лимон" in text or "лайм" in text:
        return 60.0
    if "карто" in text:
        return 150.0
    if "морков" in text:
        return 80.0
    if "огур" in text:
        return 100.0
    if "яблок" in text:
        return 180.0
    if "банан" in text:
        return 120.0
    if "авокад" in text:
        return 150.0
    if "баклаж" in text:
        return 300.0
    if "кабач" in text or "цукини" in text:
        return 200.0
    if "свек" in text:
        return 150.0
    if "пуч" in text and ("базилик" in text or "зел" in text or "кинз" in text or "петруш" in text):
        return 30.0
    if "круж" in text and ("тесто" in text or "эмпанада" in text):
        return 25.0
    if "ломтик" in text and ("хлеб" in text or "тост" in text):
        return 35.0
    if "стеб" in text and "сельдер" in text:
        return 40.0
    if "голов" in text and "чеснок" in text:
        return 50.0
    if "лист" in text and "фило" in text:
        return 25.0
    if "лист" in text and ("рисов" in text or "бумаг" in text):
        return 10.0
    if "лист" in text and "капуст" in text:
        return 30.0
    if "лист" in text and ("салат" in text or "романо" in text or "айсберг" in text):
        return 10.0
    if "стакан" in text and ("вод" in text or "бульон" in text):
        return 240.0
    if "порци" in text and ("тесто" in text or "пюре" in text):
        return 500.0
    if "пер" in text and "зелен" in text and "лук" in text:
        return 5.0
    if "бан" in text and ("кукуруз" in text or "фасол" in text or "тунец" in text):
        return 300.0
    return None


def _is_ignorable_amountless_line(line: str) -> bool:
    normalized = (line or "").casefold().replace("ё", "е")
    normalized = re.sub(r"[^0-9a-zа-я]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized in {
        "ингредиенты",
        "начинка",
        "основа",
        "для соуса",
        "для супа",
        "для рагу",
        "для гранолы",
        "для запеканки",
        "соль",
        "перец",
        "черный перец",
        "белый перец",
        "крупная соль",
        "соль перец",
        "соль масло",
        "соль масло для жарки",
        "соль оливковое масло",
        "соль оливковое масло для жарки",
        "соль и перец",
        "соль и специи",
        "соль специи",
        "специи",
        "сухари",
        "панировка",
        "зелень",
        "петрушка",
        "кинза",
        "укроп",
        "базилик",
        "орегано",
        "лавр",
        "лавровый лист",
        "мускат",
        "мускатный орех",
        "корица",
        "шафран куркума",
        "шафран",
        "куркума",
        "паприка",
        "кунжут для посыпки",
        "масло для жарки",
        "масло для смазывания",
        "соус для подачи",
        "листья кукурузы или пергамент",
        "нитка шпагат",
        "лимон",
        "лайм",
        "пита овощи тцацики",
    }:
        return True
    if "щепотк" in normalized and any(
        spice in normalized
        for spice in (
            "корица",
            "мускат",
            "мускатный орех",
            "черный перец",
            "соль",
            "специи",
            "ванилин",
            "ваниль",
        )
    ):
        return True
    if normalized.startswith("на ") and "порци" in normalized:
        return True
    return any(
        marker in normalized
        for marker in (
            "по вкусу",
            "по желанию",
            "для подпыла",
            "для подачи",
            "украшения",
        )
    )


def _blocked(candidate_id: str, reason: str) -> IngredientParseResult:
    return IngredientParseResult(candidate_id, "blocked", reason, [])
