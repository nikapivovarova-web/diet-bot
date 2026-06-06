from __future__ import annotations

import json
import re
from dataclasses import dataclass

from scripts.dev.recipe_importer.loader import NormalizedRecipe


_TEXT_PATTERN = re.compile(
    r"^\s*(?P<name>.+?)\s*[-:]\s*(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<unit>[^\d\s]+)?\s*$"
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
        amount = _parse_positive_amount(match.group("amount"))
        name = match.group("name").strip()
        if not name:
            return _blocked(recipe.candidate_id, "missing_ingredient_name")
        if amount is None:
            return _blocked(recipe.candidate_id, "invalid_ingredient_amount")
        ingredients.append(
            ParsedIngredient(
                name=name,
                amount=amount,
                unit=(match.group("unit") or "").strip(),
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


def _blocked(candidate_id: str, reason: str) -> IngredientParseResult:
    return IngredientParseResult(candidate_id, "blocked", reason, [])
