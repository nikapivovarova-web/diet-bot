from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from scripts.dev.recipe_importer.apply import apply_run
from scripts.dev.recipe_importer.classifier import classify_recipe
from scripts.dev.recipe_importer.ingredients import parse_ingredients
from scripts.dev.recipe_importer.loader import DuplicateRisk, LoadedInput, load_excel_400_workbook, load_photo_prep_317
from scripts.dev.recipe_importer.mapping import load_alias_config, map_ingredients
from scripts.dev.recipe_importer.nutrition import calculate_nutrition, load_curated_foods
from scripts.dev.recipe_importer.photos import build_photo_manifest
from scripts.dev.recipe_importer.production_rows import (
    generate_production_rows,
    write_apply_preview,
)
from scripts.dev.recipe_importer.servings import resolve_servings
from scripts.dev.recipe_importer.writer import write_audit_outputs


INPUT_LOADERS = {
    "photo_prep_317": load_photo_prep_317,
    "excel_400_workbook": load_excel_400_workbook,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "audit":
        return _run_audit(args)
    if args.command == "apply":
        return _run_apply(args)

    parser.error("missing command")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recipe-importer")
    subparsers = parser.add_subparsers(dest="command")

    audit = subparsers.add_parser("audit")
    audit.add_argument("--input", required=True, type=Path)
    audit.add_argument("--input-format", required=True, choices=sorted(INPUT_LOADERS))
    audit.add_argument("--photos", required=True, type=Path)
    audit.add_argument("--out", required=True, type=Path)
    audit.add_argument("--data-dir", type=Path, default=Path("src/diet_bot/data"))
    audit.add_argument("--recipe-no-start", type=int)
    audit.add_argument("--recipe-key-prefix")
    audit.add_argument("--dry-run", action="store_true")

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--run", required=True, type=Path)
    apply_parser.add_argument("--data-dir", required=True, type=Path)
    apply_parser.add_argument("--write", action="store_true")
    return parser


def _run_audit(args: argparse.Namespace) -> int:
    loaded = INPUT_LOADERS[args.input_format](args.input)
    loaded = _with_catalog_title_duplicates(loaded, args.data_dir)
    candidate_ids = [recipe.candidate_id for recipe in loaded.recipes]
    photos = build_photo_manifest(candidate_ids, args.photos)
    aliases = load_alias_config()
    foods = load_curated_foods(args.data_dir)
    ingredient_results = {recipe.candidate_id: parse_ingredients(recipe) for recipe in loaded.recipes}
    servings_results = {
        recipe.candidate_id: resolve_servings(recipe.servings, recipe.meal_type)
        for recipe in loaded.recipes
    }
    mapping_results = {
        recipe.candidate_id: map_ingredients(
            recipe.candidate_id,
            ingredient_results[recipe.candidate_id].ingredients,
            aliases,
        )
        for recipe in loaded.recipes
    }
    nutrition_results = {
        recipe.candidate_id: calculate_nutrition(
            recipe.candidate_id,
            mapping_results[recipe.candidate_id],
            foods,
        )
        for recipe in loaded.recipes
    }
    classifications = [
        classify_recipe(
            recipe,
            photos[recipe.candidate_id],
            loaded.duplicate_risks.get(recipe.candidate_id),
            ingredients=ingredient_results[recipe.candidate_id],
            servings=servings_results[recipe.candidate_id],
            mapping=mapping_results[recipe.candidate_id],
            nutrition=nutrition_results[recipe.candidate_id],
        )
        for recipe in loaded.recipes
    ]
    production_rows = None
    if args.recipe_no_start is not None or args.recipe_key_prefix is not None:
        if args.recipe_no_start is None or args.recipe_key_prefix is None:
            raise ValueError("--recipe-no-start and --recipe-key-prefix must be provided together")
        production_rows = generate_production_rows(
            loaded,
            photos,
            classifications,
            ingredient_results=ingredient_results,
            servings_results=servings_results,
            mapping_results=mapping_results,
            nutrition_results=nutrition_results,
            recipe_no_start=args.recipe_no_start,
            recipe_key_prefix=args.recipe_key_prefix,
        )
        production_rows.write(args.out / "production_rows")
        write_apply_preview(args.out / "apply_preview.md", production_rows)
    write_audit_outputs(
        args.out,
        loaded,
        photos,
        classifications,
        ingredient_results=ingredient_results,
        servings_results=servings_results,
        mapping_results=mapping_results,
        nutrition_results=nutrition_results,
        input_dir=args.input,
        photos_dir=args.photos,
        dry_run=args.dry_run,
        production_rows=production_rows,
    )
    return 0


def _run_apply(args: argparse.Namespace) -> int:
    plan = apply_run(args.run, args.data_dir, write=args.write)
    print(plan.summary())
    return 0


def _with_catalog_title_duplicates(loaded: LoadedInput, data_dir: Path) -> LoadedInput:
    title_index = _load_catalog_title_index(data_dir)
    if not title_index:
        return loaded

    risks = dict(loaded.duplicate_risks)
    for recipe in loaded.recipes:
        normalized = _normalize_title(recipe.title_ru)
        if not normalized or normalized not in title_index:
            continue
        risks[recipe.candidate_id] = DuplicateRisk(
            candidate_id=recipe.candidate_id,
            duplicate_risk="exact_title_match",
            duplicate_reason=f"catalog_title_match:{title_index[normalized]}",
            possible_duplicate_candidate_ids=title_index[normalized],
        )
    return LoadedInput(
        recipes=loaded.recipes,
        duplicate_risks=risks,
        source_counts={
            **loaded.source_counts,
            "catalog_title_duplicate_matches": len(risks) - len(loaded.duplicate_risks),
        },
    )


def _load_catalog_title_index(data_dir: Path) -> dict[str, str]:
    path = Path(data_dir) / "curated_recipes.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    index: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title_ru") or row.get("title") or "").strip()
        recipe_id = str(row.get("recipe_id") or row.get("id") or "").strip()
        normalized = _normalize_title(title)
        if normalized and recipe_id:
            index.setdefault(normalized, recipe_id)
    return index


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


if __name__ == "__main__":
    raise SystemExit(main())
