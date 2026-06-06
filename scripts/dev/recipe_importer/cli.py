from __future__ import annotations

import argparse
from pathlib import Path

from scripts.dev.recipe_importer.classifier import classify_recipe
from scripts.dev.recipe_importer.ingredients import parse_ingredients
from scripts.dev.recipe_importer.loader import load_photo_prep_317
from scripts.dev.recipe_importer.mapping import load_alias_config, map_ingredients
from scripts.dev.recipe_importer.nutrition import calculate_nutrition, load_curated_foods
from scripts.dev.recipe_importer.photos import build_photo_manifest
from scripts.dev.recipe_importer.production_rows import (
    generate_production_rows,
    write_apply_preview,
)
from scripts.dev.recipe_importer.servings import resolve_servings
from scripts.dev.recipe_importer.writer import write_audit_outputs


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "audit":
        return _run_audit(args)

    parser.error("missing command")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recipe-importer")
    subparsers = parser.add_subparsers(dest="command")

    audit = subparsers.add_parser("audit")
    audit.add_argument("--input", required=True, type=Path)
    audit.add_argument("--input-format", required=True, choices=["photo_prep_317"])
    audit.add_argument("--photos", required=True, type=Path)
    audit.add_argument("--out", required=True, type=Path)
    audit.add_argument("--data-dir", type=Path, default=Path("src/diet_bot/data"))
    audit.add_argument("--recipe-no-start", type=int)
    audit.add_argument("--recipe-key-prefix")
    audit.add_argument("--dry-run", action="store_true")
    return parser


def _run_audit(args: argparse.Namespace) -> int:
    loaded = load_photo_prep_317(args.input)
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


if __name__ == "__main__":
    raise SystemExit(main())
