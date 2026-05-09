from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from pypdf import PdfReader

from diet_bot.curated_data import curated_foods
from diet_bot.domain import ActivityLevel, CookingTimePreference, Goal, Sex, UserProfile
from diet_bot.domain import Meal, MealPlan, NutritionTargets, SafetyResult
from diet_bot.pdf_renderer import EMOJI_RE, _clean_text, render_week_plan_pdf, resolve_local_meal_image_path
from diet_bot.recipe_catalog import built_in_recipes
from diet_bot.telegram_app import _apply_batch_carryovers, _build_week_plans, _week_plan_dates


@pytest.fixture(scope="module")
def sample_week_plans():
    profile = UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=4,
        cooking_time=CookingTimePreference.QUICK,
    )
    return _build_week_plans(profile, 101, set(), set())


@pytest.fixture()
def sample_week_dates():
    return _week_plan_dates(date(2026, 5, 7))


def test_week_pdf_contains_full_week_content(tmp_path: Path, sample_week_plans, sample_week_dates) -> None:
    pdf_path = render_week_plan_pdf(sample_week_plans, sample_week_dates, tmp_path / "week.pdf")

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 10_000

    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    first_meal_title = _clean_text(sample_week_plans[0].meals[0].name).split(":", 1)[1].strip()

    assert "Рацион на неделю" in text
    assert "Ваш расчет" in text
    assert "Меню на неделю" in text
    assert "Подготовка на неделю" in text
    assert "День 1" in text
    assert _compact_text(first_meal_title) in _compact_text(text)
    assert "Ингредиенты" in text
    assert "Продукт" in text
    assert "Бытовая мера" in text
    assert "Как приготовить" in text
    assert "Подробный нутриентный отчет" in text
    assert "Нутриент" in text
    assert "Факт" in text
    assert "Цель" in text
    assert "Список покупок" in text
    assert "[ ]" in text
    assert "Дисклеймер" in text
    assert "ориентировочный расчёт" in text
    assert not EMOJI_RE.search(text)


def test_local_meal_photo_can_be_resolved(sample_week_plans) -> None:
    meal = next(
        meal
        for plan in sample_week_plans
        for meal in plan.meals
        if meal.image_url and not meal.image_url.startswith(("http://", "https://"))
    )

    image_path = resolve_local_meal_image_path(meal)

    assert image_path is not None
    assert image_path.exists()


def test_week_pdf_ignores_missing_meal_photo(
    tmp_path: Path,
    sample_week_plans,
    sample_week_dates,
) -> None:
    missing_photo_meal = replace(sample_week_plans[0].meals[0], image_url="recipe_photos/missing.jpg")
    plan_with_missing_photo = replace(
        sample_week_plans[0],
        meals=(missing_photo_meal, *sample_week_plans[0].meals[1:]),
    )

    pdf_path = render_week_plan_pdf((plan_with_missing_photo,), (sample_week_dates[0],), tmp_path / "missing.pdf")

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1_000


def test_week_pdf_contains_fixed_soup_recipe_to_the_end(tmp_path: Path, sample_week_dates) -> None:
    recipes = {recipe.id: recipe for recipe in built_in_recipes()}
    recipe = recipes["r215_zolotoy_karri_sup_iz_krasnoy_chechevitsy_s_kokosovym_m"]
    plan = _plan_for_recipe(recipe)

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "soup.pdf")
    text = _pdf_text(pdf_path)

    assert "овощной бульон и кокосовое молоко" in text
    assert "подавайте с кинзой и кокосовыми сливками" in text


def test_week_pdf_uses_batch_adjusted_cracker_recipe(tmp_path: Path, sample_week_dates) -> None:
    recipes = {recipe.id: recipe for recipe in built_in_recipes()}
    recipe = recipes["r331_rzhanye_krekery_s_tykvennymi_semechkami"]
    plan = _apply_batch_carryovers(_plan_for_recipe(recipe), {})

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "crackers.pdf")
    text = _pdf_text(pdf_path)

    assert "Приготовьте 6 крекеров на 3 перекуса" in text
    assert "ржаная мука" in text
    assert "пшеничная мука" in text
    assert "выпекайте 60-90 минут" in text


def _plan_for_recipe(recipe) -> MealPlan:
    food_by_id = {food.id: food for food in curated_foods()}
    meal = Meal(
        name=f"🥣 Перекус: {recipe.title}" if recipe.slot == "snack" else f"Ужин: {recipe.title}",
        portions=tuple(food_by_id[food_id].portion(grams) for food_id, grams in recipe.ingredients_g.items()),
        recipe=recipe.instructions,
        image_url=recipe.image_url,
        image_attribution=recipe.image_attribution,
        source_url=recipe.source_url,
        recipe_id=recipe.id,
        recipe_key=f"{recipe.slot}:curated:{recipe.id}",
    )
    targets = NutritionTargets(
        bmi=22,
        bmi_category="normal",
        bmr_kcal=1500,
        tdee_kcal=2000,
        water_l=2.0,
        targets=meal.nutrients,
        calorie_bounds=(1500, 2500),
        macro_bounds={},
    )
    return MealPlan((meal,), targets, SafetyResult(can_generate_plan=True))


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return _compact_text("\n".join(page.extract_text() or "" for page in reader.pages))


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
