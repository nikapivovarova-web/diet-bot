from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from diet_bot.curated_data import curated_foods  # noqa: E402
from diet_bot.domain import Meal, MealPlan, NutrientVector, NutritionTargets, SafetyResult  # noqa: E402
from diet_bot.pdf_renderer import (  # noqa: E402
    PDF_LOGO_PATH,
    PDF_QR_PATH,
    render_week_plan_pdf,
    resolve_local_meal_image_path,
)
from diet_bot.recipe_catalog import built_in_recipes  # noqa: E402


NEW_RECIPE_START = 401
NEW_RECIPE_END = 610
MEALS_PER_DAY = 4
DAYS_PER_PDF = 7


def main() -> int:
    parser = argparse.ArgumentParser(description="Render recovery PDF smoke samples for recipes r401-r610.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "tmp" / "pdf-renderer-recovery-smoke",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    for asset_path in (PDF_LOGO_PATH, PDF_QR_PATH):
        if not asset_path.exists():
            raise SystemExit(f"Missing PDF brand asset: {asset_path}")

    food_by_id = {food.id: food for food in curated_foods()}
    recipes = [
        recipe
        for recipe in built_in_recipes()
        if _new_recipe_number(recipe.id) is not None
        and NEW_RECIPE_START <= _new_recipe_number(recipe.id) <= NEW_RECIPE_END
    ]
    recipes.sort(key=lambda recipe: _new_recipe_number(recipe.id) or 0)
    if len(recipes) != NEW_RECIPE_END - NEW_RECIPE_START + 1:
        raise SystemExit(f"Expected 210 new recipes, found {len(recipes)}")

    missing_photos = []
    for recipe in recipes:
        meal = _meal_for_recipe(recipe, food_by_id)
        image_path = resolve_local_meal_image_path(meal)
        if image_path is None or not image_path.exists():
            missing_photos.append(recipe.id)
    if missing_photos:
        raise SystemExit(f"Missing local photos for recipes: {', '.join(missing_photos[:10])}")

    pdf_paths: list[Path] = []
    recipes_per_pdf = MEALS_PER_DAY * DAYS_PER_PDF
    for chunk_index, start in enumerate(range(0, len(recipes), recipes_per_pdf), start=1):
        chunk = recipes[start : start + recipes_per_pdf]
        plans = _plans_for_chunk(chunk, food_by_id)
        start_date = date(2026, 5, 8) + timedelta(days=(chunk_index - 1) * DAYS_PER_PDF)
        plan_dates = tuple(start_date + timedelta(days=offset) for offset in range(len(plans)))
        pdf_path = render_week_plan_pdf(
            plans,
            plan_dates,
            output_dir / f"recovery-r401-r610-{chunk_index:02d}.pdf",
        )
        if pdf_path.stat().st_size <= 15_000:
            raise SystemExit(f"Smoke PDF is unexpectedly small: {pdf_path} ({pdf_path.stat().st_size} bytes)")
        pdf_paths.append(pdf_path)

    print(f"rendered_pdfs={len(pdf_paths)}")
    print(f"recipes_checked={len(recipes)}")
    print(f"output_dir={output_dir}")
    print(f"first_pdf={pdf_paths[0] if pdf_paths else ''}")
    print(f"last_pdf={pdf_paths[-1] if pdf_paths else ''}")
    return 0


def _new_recipe_number(recipe_id: str) -> int | None:
    prefix = recipe_id.split("_", 1)[0]
    if len(prefix) < 2 or prefix[0] != "r" or not prefix[1:].isdigit():
        return None
    return int(prefix[1:])


def _plans_for_chunk(recipes, food_by_id) -> tuple[MealPlan, ...]:
    plans = []
    for day_start in range(0, len(recipes), MEALS_PER_DAY):
        day_recipes = recipes[day_start : day_start + MEALS_PER_DAY]
        meals = tuple(_meal_for_recipe(recipe, food_by_id) for recipe in day_recipes)
        plans.append(_plan_for_meals(meals))
    return tuple(plans)


def _meal_for_recipe(recipe, food_by_id) -> Meal:
    meal_type = {
        "breakfast": "Завтрак",
        "lunch": "Обед",
        "dinner": "Ужин",
        "snack": "Перекус",
    }.get(recipe.slot, "Блюдо")
    return Meal(
        name=f"{meal_type}: {recipe.title}",
        portions=tuple(food_by_id[food_id].portion(grams) for food_id, grams in recipe.ingredients_g.items()),
        recipe=recipe.instructions,
        image_url=recipe.image_url,
        image_attribution=recipe.image_attribution,
        source_url=recipe.source_url,
        recipe_id=recipe.id,
        recipe_key=f"{recipe.slot}:curated:{recipe.id}",
    )


def _plan_for_meals(meals: tuple[Meal, ...]) -> MealPlan:
    totals = NutrientVector.sum(meal.nutrients for meal in meals)
    targets = NutrientVector(
        {
            key: max(1.0, totals.get(key))
            for key in (
                "energy_kcal",
                "protein_g",
                "fat_g",
                "carbohydrate_g",
                "fiber_g",
                "calcium_mg",
                "iron_mg",
                "magnesium_mg",
                "potassium_mg",
                "zinc_mg",
                "folate_mcg",
                "vitamin_c_mg",
            )
        }
    )
    return MealPlan(
        meals,
        NutritionTargets(
            bmi=22,
            bmi_category="normal",
            bmr_kcal=1500,
            tdee_kcal=2000,
            water_l=2.0,
            targets=targets,
            calorie_bounds=(1500, 2500),
            macro_bounds={},
        ),
        SafetyResult(can_generate_plan=True),
    )


if __name__ == "__main__":
    raise SystemExit(main())
