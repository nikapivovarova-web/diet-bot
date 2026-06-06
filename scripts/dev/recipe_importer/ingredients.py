from __future__ import annotations

import json
import re
from dataclasses import dataclass

from scripts.dev.recipe_importer.loader import NormalizedRecipe


_TEXT_PATTERN = re.compile(
    r"^\s*(?P<name>.+?)\s*(?:—|–|-|:)\s*(?P<quantity>.+?)\s*$"
)
_QUANTITY_PATTERN = re.compile(
    r"(?:≈|~)?\s*"
    r"(?P<amount>\d+(?:[.,]\d+)?)"
    r"(?:\s*[–-]\s*\d+(?:[.,]\d+)?)?"
    r"\s*(?P<unit>кг|kg|килограмм(?:а|ов)?|г|g|гр|грамм(?:а|ов)?|мл|ml)\b",
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
    lines = [line.strip() for line in recipe.raw_ingredient_text.splitlines() if line.strip()]
    if not lines:
        return _blocked(recipe.candidate_id, "missing_ingredients")

    for line in lines:
        match = _TEXT_PATTERN.match(line)
        if not match:
            return _blocked(recipe.candidate_id, "ambiguous_ingredient_text")
        quantity = _parse_text_quantity(match.group("quantity"))
        if quantity is None:
            return _blocked(recipe.candidate_id, "ambiguous_ingredient_text")
        amount, unit = quantity
        name = match.group("name").strip()
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
    return IngredientParseResult(recipe.candidate_id, "parsed", "", ingredients)


def _pick(row: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return ""


def _parse_positive_amount(value: object) -> float | None:
    try:
        amount = float(str(value).replace(",", "."))
    except ValueError:
        return None
    if amount <= 0:
        return None
    return amount


def _parse_text_quantity(value: str) -> tuple[float, str] | None:
    matches = list(_QUANTITY_PATTERN.finditer(value or ""))
    if not matches:
        return None

    chosen = _prefer_grams(matches)
    amount = _parse_positive_amount(chosen.group("amount"))
    if amount is None:
        return None
    return amount, _normalize_unit(chosen.group("unit"))


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
    return normalized


def _blocked(candidate_id: str, reason: str) -> IngredientParseResult:
    return IngredientParseResult(candidate_id, "blocked", reason, [])
