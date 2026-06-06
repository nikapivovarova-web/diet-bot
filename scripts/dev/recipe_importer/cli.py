from __future__ import annotations

import argparse
from pathlib import Path

from scripts.dev.recipe_importer.classifier import classify_recipe
from scripts.dev.recipe_importer.ingredients import parse_ingredients
from scripts.dev.recipe_importer.loader import load_photo_prep_317
from scripts.dev.recipe_importer.mapping import load_alias_config, map_ingredients
from scripts.dev.recipe_importer.photos import build_photo_manifest
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
    audit.add_argument("--dry-run", action="store_true")
    return parser


def _run_audit(args: argparse.Namespace) -> int:
    loaded = load_photo_prep_317(args.input)
    candidate_ids = [recipe.candidate_id for recipe in loaded.recipes]
    photos = build_photo_manifest(candidate_ids, args.photos)
    aliases = load_alias_config()
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
    classifications = [
        classify_recipe(
            recipe,
            photos[recipe.candidate_id],
            loaded.duplicate_risks.get(recipe.candidate_id),
            ingredients=ingredient_results[recipe.candidate_id],
            servings=servings_results[recipe.candidate_id],
            mapping=mapping_results[recipe.candidate_id],
        )
        for recipe in loaded.recipes
    ]
    write_audit_outputs(
        args.out,
        loaded,
        photos,
        classifications,
        ingredient_results=ingredient_results,
        servings_results=servings_results,
        mapping_results=mapping_results,
        input_dir=args.input,
        photos_dir=args.photos,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
