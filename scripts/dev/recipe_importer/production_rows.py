from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from scripts.dev.recipe_importer.classifier import ClassificationResult
from scripts.dev.recipe_importer.ingredients import IngredientParseResult
from scripts.dev.recipe_importer.loader import LoadedInput, NormalizedRecipe
from scripts.dev.recipe_importer.mapping import IngredientMappingResult
from scripts.dev.recipe_importer.nutrition import NutritionResult
from scripts.dev.recipe_importer.photos import PhotoRecord
from scripts.dev.recipe_importer.servings import ServingsResult


NUTRIENT_FIELDS = (
    "energy_kcal",
    "protein_g",
    "fat_g",
    "saturated_fat_g",
    "carbohydrate_g",
    "fiber_g",
    "sugar_g",
    "added_sugar_g",
    "sodium_mg",
    "potassium_mg",
    "calcium_mg",
    "magnesium_mg",
    "iron_mg",
    "zinc_mg",
    "iodine_mcg",
    "selenium_mcg",
    "phosphorus_mg",
    "vitamin_c_mg",
    "vitamin_d_mcg",
    "vitamin_b12_mcg",
    "folate_mcg_dfe",
    "vitamin_b1_mg",
    "vitamin_b2_mg",
    "vitamin_b3_mg",
    "vitamin_b6_mg",
    "vitamin_a_mcg_rae",
    "vitamin_e_mg",
    "vitamin_k_mcg",
    "omega_3_mg",
)


@dataclass(frozen=True)
class ProductionRows:
    recipes: list[dict[str, object]]
    ingredients: list[dict[str, object]]
    nutrition: list[dict[str, object]]
    photo_manifest: list[dict[str, object]]

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_json(out_dir / "curated_recipes.json", self.recipes)
        _write_json(out_dir / "curated_recipe_ingredients.json", self.ingredients)
        _write_json(out_dir / "curated_recipe_nutrition.json", self.nutrition)
        _write_photo_manifest(out_dir / "photo_manifest.csv", self.photo_manifest)


def generate_production_rows(
    loaded: LoadedInput,
    photos: dict[str, PhotoRecord],
    classifications: list[ClassificationResult],
    *,
    ingredient_results: dict[str, IngredientParseResult],
    servings_results: dict[str, ServingsResult],
    mapping_results: dict[str, IngredientMappingResult],
    nutrition_results: dict[str, NutritionResult],
    recipe_no_start: int,
    recipe_key_prefix: str,
) -> ProductionRows:
    if recipe_no_start <= 0:
        raise ValueError("recipe_no_start must be a positive integer")
    if not recipe_key_prefix:
        raise ValueError("recipe_key_prefix is required")

    recipes_by_id = {recipe.candidate_id: recipe for recipe in loaded.recipes}
    ready = [
        result
        for result in classifications
        if result.classification == "import_ready"
    ]
    ready.sort(key=lambda result: result.candidate_id)

    recipes: list[dict[str, object]] = []
    ingredients: list[dict[str, object]] = []
    nutrition: list[dict[str, object]] = []
    photo_manifest: list[dict[str, object]] = []

    for offset, result in enumerate(ready):
        candidate_id = result.candidate_id
        recipe = recipes_by_id[candidate_id]
        photo = _require_photo(candidate_id, photos)
        mapping = _require_mapping(candidate_id, mapping_results)
        nutrition_result = _require_nutrition(candidate_id, nutrition_results)
        parsed_ingredients = _require_ingredients(candidate_id, ingredient_results)
        servings = _require_servings(candidate_id, servings_results)

        recipe_no = recipe_no_start + offset
        recipe_key = f"{recipe_key_prefix}{offset + 1:03d}"
        recipe_id = _recipe_id(recipe, recipe_no)
        target_photo_path = _target_photo_path(recipe_no, photo)

        recipes.append(
            _recipe_row(
                recipe,
                servings,
                ingredient_names=[ingredient.name for ingredient in parsed_ingredients.ingredients],
                recipe_no=recipe_no,
                recipe_id=recipe_id,
                recipe_key=recipe_key,
                image_url=_image_url(recipe_no, photo),
            )
        )
        ingredients.extend(
            _ingredient_rows(
                recipe_id=recipe_id,
                recipe_no=recipe_no,
                recipe_key=recipe_key,
                parsed=parsed_ingredients,
                mapping=mapping,
            )
        )
        nutrition.append(
            _nutrition_row(
                recipe_id=recipe_id,
                recipe_key=recipe_key,
                mapping=mapping,
                nutrition=nutrition_result,
            )
        )
        photo_manifest.append(
            {
                "candidate_id": candidate_id,
                "recipe_id": recipe_id,
                "recipe_no": recipe_no,
                "recipe_key": recipe_key,
                "source_photo_path": _path_text(photo.relative_path),
                "target_photo_path": target_photo_path,
                "photo_ext": photo.extension,
                "photo_size_bytes": photo.size_bytes,
            }
        )

    return ProductionRows(
        recipes=recipes,
        ingredients=ingredients,
        nutrition=nutrition,
        photo_manifest=photo_manifest,
    )


def write_apply_preview(path: Path, rows: ProductionRows) -> None:
    lines = [
        "# Recipe Importer Apply Preview",
        "",
        "No production data was modified.",
        "",
        "## Production-shaped rows",
        "",
        f"- curated_recipes.json rows: {len(rows.recipes)}",
        f"- curated_recipe_ingredients.json rows: {len(rows.ingredients)}",
        f"- curated_recipe_nutrition.json rows: {len(rows.nutrition)}",
        f"- photo_manifest.csv rows: {len(rows.photo_manifest)}",
        "",
        "## Future apply boundary",
        "",
        "- Review these artifacts before any separate production-data import.",
        "- Photo paths are targets only; this dry-run does not copy files.",
        "- Phase 3 apply requires approval.json and validates manifest hashes before writing.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _recipe_row(
    recipe: NormalizedRecipe,
    servings: ServingsResult,
    *,
    ingredient_names: list[str],
    recipe_no: int,
    recipe_id: str,
    recipe_key: str,
    image_url: str,
) -> dict[str, object]:
    slot = _slot(recipe.meal_type)
    title = _clean_user_text(recipe.title_ru)
    meal_type = _clean_user_text(recipe.meal_type)
    instructions = _clean_user_text(recipe.instructions)
    source = _clean_user_text(recipe.source)
    time_fields = _time_fields(recipe, slot)
    row: dict[str, object] = {
        "recipe_id": recipe_id,
        "recipe_no": recipe_no,
        "recipe_key": recipe_key,
        "slot": slot,
        "meal_slot": slot,
        "category_ru": meal_type or slot,
        "title_ru": title,
        "short_description_ru": _short_description(
            title=title or recipe.candidate_id,
            slot=slot,
            ingredient_names=ingredient_names,
            instructions=instructions,
        ),
        "servings": servings.servings,
        "servings_original": recipe.servings,
        "servings_cleaned": servings.servings,
        "cooking_effort": "simple",
        "active_time_min": time_fields["active_time_min"],
        "passive_time_min": time_fields["passive_time_min"],
        "equipment": "",
        "tags": f"{slot}, recipe_importer_preview",
        "time_text": time_fields["time_text"],
        "instructions_ru": instructions,
        "source_name": "FoodBalance recipe importer preview",
        "source_url": source,
        "image_url": image_url,
        "image_attribution": "",
        "import_metadata": {
            "candidate_id": recipe.candidate_id,
            "source": source,
            "time_policy": time_fields["time_policy"],
        },
    }
    return row


def _ingredient_rows(
    *,
    recipe_id: str,
    recipe_no: int,
    recipe_key: str,
    parsed: IngredientParseResult,
    mapping: IngredientMappingResult,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_index, (ingredient, mapped) in enumerate(
        zip(parsed.ingredients, mapping.rows, strict=True),
        start=1,
    ):
        rows.append(
            {
                "recipe_id": recipe_id,
                "recipe_no": recipe_no,
                "recipe_key": recipe_key,
                "line_index": line_index,
                "raw_text": ingredient.raw,
                "ingredient_name_ru": ingredient.name,
                "food_id": mapped.food_id,
                "grams": mapped.amount,
                "quantity_text": _quantity_text(ingredient.amount, ingredient.unit),
                "state": "raw",
                "is_optional": False,
                "conversion_note": "",
                "parse_method": "recipe_importer_mapping",
            }
        )
    return rows


def _nutrition_row(
    *,
    recipe_id: str,
    recipe_key: str,
    mapping: IngredientMappingResult,
    nutrition: NutritionResult,
) -> dict[str, object]:
    row: dict[str, object] = {
        "recipe_id": recipe_id,
        "recipe_key": recipe_key,
        "ingredient_count": len(mapping.rows),
        "unmatched_ingredient_count": 0,
        "calculation_status": "ok",
        "calculation_notes": "recipe importer dry-run preview",
    }
    for field in NUTRIENT_FIELDS:
        row[field] = getattr(nutrition, field, 0.0)
    return row


def _require_photo(candidate_id: str, photos: dict[str, PhotoRecord]) -> PhotoRecord:
    photo = photos.get(candidate_id)
    if photo is None or not photo.found or photo.relative_path is None:
        raise ValueError(f"import_ready candidate {candidate_id} lacks photo")
    return photo


def _require_mapping(
    candidate_id: str,
    mapping_results: dict[str, IngredientMappingResult],
) -> IngredientMappingResult:
    mapping = mapping_results.get(candidate_id)
    if mapping is None or mapping.status != "mapped" or not mapping.rows:
        raise ValueError(f"import_ready candidate {candidate_id} lacks mapping")
    return mapping


def _require_nutrition(
    candidate_id: str,
    nutrition_results: dict[str, NutritionResult],
) -> NutritionResult:
    nutrition = nutrition_results.get(candidate_id)
    if nutrition is None or nutrition.calculation_status != "ok":
        raise ValueError(f"import_ready candidate {candidate_id} lacks nutrition")
    return nutrition


def _require_ingredients(
    candidate_id: str,
    ingredient_results: dict[str, IngredientParseResult],
) -> IngredientParseResult:
    ingredients = ingredient_results.get(candidate_id)
    if ingredients is None or ingredients.parse_status != "parsed" or not ingredients.ingredients:
        raise ValueError(f"import_ready candidate {candidate_id} lacks ingredients")
    return ingredients


def _require_servings(
    candidate_id: str,
    servings_results: dict[str, ServingsResult],
) -> ServingsResult:
    servings = servings_results.get(candidate_id)
    if servings is None or servings.status != "valid":
        raise ValueError(f"import_ready candidate {candidate_id} lacks servings")
    return servings


def _recipe_id(recipe: NormalizedRecipe, recipe_no: int) -> str:
    slug = _slug(recipe.title_ru) or _slug(recipe.candidate_id) or "recipe"
    return f"r{recipe_no:03d}_{slug[:54]}"


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return re.sub(r"_+", "_", text)


def _slot(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"breakfast", "lunch", "dinner", "snack", "main"}:
        return normalized
    return "main"


def _slot_label(slot: str) -> str:
    return {
        "breakfast": "завтрак",
        "lunch": "основное блюдо",
        "dinner": "основное блюдо",
        "main": "основное блюдо",
        "snack": "перекус",
    }.get(slot, "основное блюдо")


def _short_description(
    *,
    title: str,
    slot: str,
    ingredient_names: list[str],
    instructions: str,
) -> str:
    ingredient_summary = ", ".join(
        _clean_user_text(name)
        for name in ingredient_names[:3]
        if _clean_user_text(name)
    )
    instruction_summary = _first_instruction_sentence(instructions)
    parts = [f"{title}: {_slot_label(slot)}"]
    if ingredient_summary:
        parts.append(f"ингредиенты: {ingredient_summary}")
    if instruction_summary:
        parts.append(instruction_summary)
    return ". ".join(parts).rstrip(".") + "."


def _time_fields(recipe: NormalizedRecipe, slot: str) -> dict[str, object]:
    source_time = _clean_user_text(recipe.time)
    active_minutes = _first_positive_int(source_time)
    if active_minutes > 0:
        return {
            "time_text": source_time,
            "active_time_min": active_minutes,
            "passive_time_min": 0,
            "time_policy": "source_time",
        }

    title_and_instructions = " ".join((recipe.title_ru, recipe.instructions)).lower()
    if _looks_no_cook_or_quick_assembly(title_and_instructions):
        return {
            "time_text": "около 15 минут (оценка: сборка/без длительного ожидания)",
            "active_time_min": 15,
            "passive_time_min": 0,
            "time_policy": "second_pass_default:no_cook_or_quick_assembly",
        }
    if _looks_baked_or_simmered(title_and_instructions):
        return {
            "time_text": "около 45 минут (оценка: 20 активных + 25 пассивных)",
            "active_time_min": 20,
            "passive_time_min": 25,
            "time_policy": "second_pass_default:baked_or_simmered_main",
        }
    if slot in {"breakfast", "snack"}:
        return {
            "time_text": "около 20 минут (оценка по категории)",
            "active_time_min": 20,
            "passive_time_min": 0,
            "time_policy": "second_pass_default:breakfast_or_snack",
        }
    return {
        "time_text": "около 35 минут (оценка: 25 активных + 10 пассивных)",
        "active_time_min": 25,
        "passive_time_min": 10,
        "time_policy": "second_pass_default:stovetop_main",
    }


def _first_positive_int(value: str) -> int:
    match = re.search(r"\d+", value or "")
    if not match:
        return 0
    return int(match.group(0))


def _clean_user_text(value: str) -> str:
    text = "".join(
        " "
        if unicodedata.category(character)[0] == "C"
        and character not in {"\n", "\r", "\t"}
        else character
        for character in str(value or "")
    )
    text = text.replace("\ufffd", "").replace("???", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _first_instruction_sentence(instructions: str) -> str:
    text = _clean_user_text(instructions)
    if not text:
        return ""
    match = re.search(r"(.{20,160}?[.!?])(?:\s|$)", text)
    if match:
        return match.group(1).strip()
    return text[:160].strip()


def _looks_no_cook_or_quick_assembly(text: str) -> bool:
    if _looks_baked_or_simmered(text) or _looks_active_cooking(text):
        return False
    return any(
        marker in text
        for marker in (
            "салат",
            "тартар",
            "мюсли",
            "смешайте",
            "заправьте",
            "разомните",
        )
    )


def _looks_baked_or_simmered(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "выпек",
            "запек",
            "духовк",
            "туш",
            "варит",
            "варите",
            "суп",
            "рагу",
        )
    )


def _looks_active_cooking(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "жар",
            "обжар",
            "грил",
            "сковород",
            "кип",
            "отвар",
            "бланш",
        )
    )


def _quantity_text(amount: float, unit: str) -> str:
    amount_text = str(int(amount)) if amount.is_integer() else str(amount)
    return f"{amount_text} {unit}".strip()


def _image_url(recipe_no: int, photo: PhotoRecord) -> str:
    return f"recipe_photos/r{recipe_no:03d}{_photo_extension(photo)}"


def _target_photo_path(recipe_no: int, photo: PhotoRecord) -> str:
    return f"src/diet_bot/data/{_image_url(recipe_no, photo)}"


def _path_text(path: Path | None) -> str:
    return path.as_posix() if path is not None else ""


def _photo_extension(photo: PhotoRecord) -> str:
    return photo.extension if photo.extension else ".jpg"


def _write_json(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_photo_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "candidate_id",
        "recipe_id",
        "recipe_no",
        "recipe_key",
        "source_photo_path",
        "target_photo_path",
        "photo_ext",
        "photo_size_bytes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
