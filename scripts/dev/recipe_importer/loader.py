from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NormalizedRecipe:
    candidate_id: str
    title_ru: str
    meal_type: str
    duplicate_risk: str
    structured_ingredients: str
    servings: str
    nutrition: str
    raw: dict[str, str]


@dataclass(frozen=True)
class DuplicateRisk:
    candidate_id: str
    duplicate_risk: str
    duplicate_reason: str
    possible_duplicate_candidate_ids: str


@dataclass(frozen=True)
class LoadedInput:
    recipes: list[NormalizedRecipe]
    duplicate_risks: dict[str, DuplicateRisk]
    source_counts: dict[str, int]


def load_photo_prep_317(input_dir: Path) -> LoadedInput:
    input_dir = Path(input_dir)
    photo_ready_path = input_dir / "photo_ready.csv"
    if not photo_ready_path.exists():
        raise FileNotFoundError(f"missing required input file: {photo_ready_path}")

    photo_rows = _read_csv(photo_ready_path)
    recipes = [_normalize_photo_ready_row(row) for row in photo_rows]
    duplicate_risks = _load_duplicate_risks(input_dir / "duplicate_risk.csv")

    return LoadedInput(
        recipes=recipes,
        duplicate_risks=duplicate_risks,
        source_counts={
            "photo_ready": len(recipes),
            "duplicate_risk": len(duplicate_risks),
        },
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def _normalize_photo_ready_row(row: dict[str, str]) -> NormalizedRecipe:
    candidate_id = _pick(row, "candidate_id", "id", "recipe_id")
    if not candidate_id:
        raise ValueError("photo_ready.csv row is missing candidate_id")

    return NormalizedRecipe(
        candidate_id=candidate_id,
        title_ru=_pick(row, "title_ru", "title", "name"),
        meal_type=_pick(row, "meal_type_guess", "meal_type", "category"),
        duplicate_risk=_pick(row, "duplicate_risk"),
        structured_ingredients=_pick(
            row,
            "structured_ingredients",
            "ingredients_json",
            "ingredients_structured_json",
        ),
        servings=_pick(row, "servings", "servings_count", "default_servings"),
        nutrition=_pick(row, "nutrition", "nutrition_json", "nutrition_per_serving_json"),
        raw=row,
    )


def _load_duplicate_risks(path: Path) -> dict[str, DuplicateRisk]:
    if not path.exists():
        return {}

    risks: dict[str, DuplicateRisk] = {}
    for row in _read_csv(path):
        candidate_id = _pick(row, "candidate_id", "id", "recipe_id")
        if not candidate_id:
            continue
        risks[candidate_id] = DuplicateRisk(
            candidate_id=candidate_id,
            duplicate_risk=_pick(row, "duplicate_risk"),
            duplicate_reason=_pick(row, "duplicate_reason"),
            possible_duplicate_candidate_ids=_pick(row, "possible_duplicate_candidate_ids"),
        )
    return risks


def _pick(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key, "")
        if value:
            return value.strip()
    return ""
