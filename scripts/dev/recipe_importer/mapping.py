from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.dev.recipe_importer.ingredients import ParsedIngredient


DEFAULT_ALIASES_PATH = Path(__file__).parent / "config" / "ingredient_aliases.csv"


@dataclass(frozen=True)
class IngredientMappingRow:
    ingredient_name: str
    normalized_alias: str
    food_id: str
    amount: float
    unit: str
    mapping_status: str
    blocker_reason: str


@dataclass(frozen=True)
class IngredientMappingResult:
    candidate_id: str
    status: str
    blocker_reason: str
    rows: list[IngredientMappingRow]


def load_alias_config(path: Path = DEFAULT_ALIASES_PATH) -> dict[str, str]:
    aliases: dict[str, str] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            alias = _normalize_alias(row.get("alias", ""))
            food_id = (row.get("food_id") or row.get("canonical_name") or "").strip()
            if not alias or not food_id:
                continue
            if alias in aliases:
                raise ValueError(f"duplicate alias in ingredient_aliases.csv: {alias}")
            aliases[alias] = food_id
    return aliases


def map_ingredients(
    candidate_id: str,
    ingredients: list[ParsedIngredient],
    aliases: dict[str, str],
) -> IngredientMappingResult:
    if not ingredients:
        return IngredientMappingResult(candidate_id, "blocked", "no_ingredients_to_map", [])

    rows: list[IngredientMappingRow] = []
    blocked = False
    for ingredient in ingredients:
        normalized = _normalize_alias(ingredient.name)
        food_id = aliases.get(normalized, "")
        if not food_id:
            blocked = True
            rows.append(_row(ingredient, normalized, "", "blocked", "unknown_ingredient_alias"))
            continue
        rows.append(_row(ingredient, normalized, food_id, "mapped", ""))

    if blocked:
        return IngredientMappingResult(
            candidate_id,
            "blocked",
            "unknown_ingredient_alias",
            rows,
        )
    return IngredientMappingResult(candidate_id, "mapped", "", rows)


def _normalize_alias(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _row(
    ingredient: ParsedIngredient,
    normalized_alias: str,
    food_id: str,
    status: str,
    blocker_reason: str,
) -> IngredientMappingRow:
    return IngredientMappingRow(
        ingredient_name=ingredient.name,
        normalized_alias=normalized_alias,
        food_id=food_id,
        amount=ingredient.amount,
        unit=ingredient.unit,
        mapping_status=status,
        blocker_reason=blocker_reason,
    )
