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


GENERATED_ALIAS_OVERRIDES = {
    "масло": "olive_oil",
    "растительное масло": "vegetable_oil",
    "сыр": "gouda",
    "перец": "bell_pepper",
}


def load_alias_config(
    path: Path = DEFAULT_ALIASES_PATH,
    *,
    include_generated_aliases: bool = False,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            alias = _normalize_alias(row.get("alias", ""))
            food_id = (row.get("food_id") or row.get("canonical_name") or "").strip()
            if not alias or not food_id:
                continue
            if alias in aliases and aliases[alias] != food_id:
                raise ValueError(f"duplicate alias in ingredient_aliases.csv: {alias}")
            aliases[alias] = food_id
    if include_generated_aliases:
        _add_generated_aliases(aliases)
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
        food_id = _lookup_alias(normalized, aliases)
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
    normalized = (value or "").casefold().replace("ё", "е")
    normalized = re.sub(r"\([^)]*\)", " ", normalized)
    normalized = normalized.replace("•", " ")
    normalized = re.sub(r"[^0-9a-zа-я_]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _lookup_alias(normalized: str, aliases: dict[str, str]) -> str:
    direct = aliases.get(normalized)
    if direct:
        return direct
    reordered = _lookup_reordered_alias(normalized, aliases)
    if reordered:
        return reordered
    if len(normalized) < 5:
        return ""
    candidates = {
        food_id
        for alias, food_id in aliases.items()
        if len(alias) >= 5 and _is_prefix_fallback_match(normalized, alias)
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    return ""


def _lookup_reordered_alias(normalized: str, aliases: dict[str, str]) -> str:
    normalized_tokens = _alias_tokens(normalized)
    if len(normalized_tokens) < 2:
        return ""
    candidates = {
        food_id
        for alias, food_id in aliases.items()
        if len(_alias_tokens(alias)) == len(normalized_tokens)
        and sorted(_alias_tokens(alias)) == sorted(normalized_tokens)
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    return ""


def _is_prefix_fallback_match(normalized: str, alias: str) -> bool:
    if alias in GENERIC_PREFIX_FALLBACK_ALIASES or normalized in GENERIC_PREFIX_FALLBACK_ALIASES:
        return False
    return alias.startswith(normalized) or normalized.startswith(alias)


def _alias_tokens(value: str) -> list[str]:
    return value.split()


GENERIC_PREFIX_FALLBACK_ALIASES = frozenset({"масло", "сыр", "перец"})


def _add_generated_aliases(aliases: dict[str, str]) -> None:
    from scripts.build_curated_recipe_data import FOOD_DEFS

    for alias, food_id in GENERATED_ALIAS_OVERRIDES.items():
        aliases[_normalize_alias(alias)] = food_id
    for food in FOOD_DEFS:
        for alias in (food.name_ru, *food.aliases):
            normalized = _normalize_alias(alias)
            if not normalized:
                continue
            aliases.setdefault(normalized, food.id)


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
