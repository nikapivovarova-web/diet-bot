from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from reportlab.platypus import Image, KeepTogether, Table

from diet_bot.curated_data import curated_foods
from diet_bot.domain import ActivityLevel, CookingTimePreference, Goal, Sex, UserProfile
from diet_bot.domain import Meal, MealPlan, NutritionTargets, SafetyResult
import diet_bot.pdf_renderer as pdf_renderer
from diet_bot.pdf_renderer import _clean_text, render_week_plan_pdf, resolve_local_meal_image_path
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
    assert "День 1" in text
    assert _compact_text(first_meal_title) in _compact_text(text)
    assert "Ингредиенты" in text
    assert "Ингредиент" in text
    assert "Примерная мера" in text
    assert "Как приготовить" in text
    assert "Итого за день" in text
    assert "●" not in text
    assert "Список продуктов" in text
    assert "ориентировочный расчёт" in text


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


def test_week_pdf_uses_product_brand_assets_and_new_recipe_photo(
    tmp_path: Path,
    sample_week_dates,
) -> None:
    recipes = {recipe.id: recipe for recipe in built_in_recipes()}
    plan = _plan_for_recipe(recipes["r401_farshirovannye_pertsy_s_risom_i_ovoschami_v_duhovke"])

    assert pdf_renderer.PDF_LOGO_PATH.exists()
    assert pdf_renderer.PDF_QR_PATH.exists()
    image_path = resolve_local_meal_image_path(plan.meals[0])
    assert image_path is not None
    assert image_path.exists()

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "product-brand-r401.pdf")
    text = _pdf_text(pdf_path)

    assert pdf_path.stat().st_size > 15_000
    assert "Food Balance" in text
    assert "@FOODBALANCERU_BOT" in text
    assert "Список продуктов" in text


def test_week_pdf_contains_fixed_soup_recipe_to_the_end(tmp_path: Path, sample_week_dates) -> None:
    recipes = {recipe.id: recipe for recipe in built_in_recipes()}
    recipe = recipes["r215_zolotoy_karri_sup_iz_krasnoy_chechevitsy_s_kokosovym_m"]
    plan = _plan_for_recipe(recipe)

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "soup.pdf")
    text = _pdf_text(pdf_path)

    assert "овощной бульон и кокосовое молоко" in text
    assert "посыпьте кинзой и добавьте по ложке кокосовых сливок" in text


def test_week_pdf_uses_batch_adjusted_cracker_recipe(tmp_path: Path, sample_week_dates) -> None:
    recipes = {recipe.id: recipe for recipe in built_in_recipes()}
    recipe = recipes["r331_rzhanye_krekery_s_tykvennymi_semechkami"]
    plan = _apply_batch_carryovers(_plan_for_recipe(recipe), {})

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "crackers.pdf")
    text = _pdf_text(pdf_path)

    assert "Приготовьте 6 крекеров на 3 перекуса" in text
    assert "ржаная мука" in text
    assert "пшеничная мука" in text
    assert "Выпекайте 45 минут" in text
    assert "пеките еще 45 минут" in text


def test_meal_header_uses_foodbalance_green_card(sample_week_plans) -> None:
    styles = pdf_renderer._build_styles(*pdf_renderer._register_fonts())
    header = pdf_renderer._meal_header_table(sample_week_plans[0].meals[0], styles, 180 * pdf_renderer.mm)

    backgrounds = [command for command in header._bkgrndcmds if command[0] == "BACKGROUND"]

    assert ("BACKGROUND", (0, 0), (-1, -1), pdf_renderer.SOFT_GREEN) in backgrounds
    assert ("BACKGROUND", (0, 0), (-1, -1), pdf_renderer.CARD_BACKGROUND) not in backgrounds


def test_meal_photo_uses_stable_fixed_box(sample_week_plans) -> None:
    styles = pdf_renderer._build_styles(*pdf_renderer._register_fonts())
    meal = next(
        meal
        for plan in sample_week_plans
        for meal in plan.meals
        if resolve_local_meal_image_path(meal) is not None
    )

    image_flowables = pdf_renderer._meal_image_flowables(meal, styles)

    assert image_flowables
    assert image_flowables[0].drawWidth == pytest.approx(pdf_renderer.PHOTO_MAX_WIDTH)
    assert image_flowables[0].drawHeight == pytest.approx(pdf_renderer.PHOTO_MAX_HEIGHT)


def test_meal_photo_source_is_rendered_to_fixed_box_aspect(sample_week_plans) -> None:
    if pdf_renderer.PILImage is None:
        pytest.skip("Pillow is required to inspect the fitted recipe photo source.")

    meal = next(
        meal
        for plan in sample_week_plans
        for meal in plan.meals
        if resolve_local_meal_image_path(meal) is not None
    )
    image_path = resolve_local_meal_image_path(meal)
    assert image_path is not None

    source = pdf_renderer._fixed_box_image_source(image_path)
    if not hasattr(source, "seek"):
        pytest.skip("Recipe photo source was not converted to an in-memory fixed box.")

    source.seek(0)
    with pdf_renderer.PILImage.open(source) as image:
        assert image.size == (
            round(pdf_renderer.PHOTO_MAX_WIDTH * 2),
            round(pdf_renderer.PHOTO_MAX_HEIGHT * 2),
        )


def test_recipe_with_photo_uses_right_photo_two_column_body(sample_week_plans) -> None:
    styles = pdf_renderer._build_styles(*pdf_renderer._register_fonts())
    doc_width = 180 * pdf_renderer.mm
    meal = next(
        meal
        for plan in sample_week_plans
        for meal in plan.meals
        if resolve_local_meal_image_path(meal) is not None
    )

    flowables = pdf_renderer._recipe_body_flowables(meal, styles, doc_width)

    assert isinstance(flowables[0], Table)
    layout = pdf_renderer._recipe_layout_metrics(doc_width)
    assert flowables[0]._colWidths == pytest.approx(
        [layout.left_width, layout.gutter, layout.photo_width]
    )
    assert layout.left_x == pytest.approx(0)
    assert layout.photo_x == pytest.approx(layout.left_width + layout.gutter)
    assert layout.photo_x + layout.photo_width == pytest.approx(doc_width)

    left_cell, _gap, right_cell = flowables[0]._cellvalues[0]
    assert "Ингредиенты" in "\n".join(_flowable_texts(left_cell))
    assert "Как приготовить" in "\n".join(_flowable_texts(left_cell))
    assert not _contains_reportlab_image(left_cell)
    assert _contains_reportlab_image(right_cell)


def test_long_recipe_steps_continue_below_photo_block(sample_week_plans) -> None:
    styles = pdf_renderer._build_styles(*pdf_renderer._register_fonts())
    doc_width = 180 * pdf_renderer.mm
    meal = next(
        meal
        for plan in sample_week_plans
        for meal in plan.meals
        if resolve_local_meal_image_path(meal) is not None
    )
    long_recipe_meal = replace(
        meal,
        recipe="\n".join(
            f"{index}. Перемешайте ингредиенты, прогрейте основу и проверьте текстуру шага {index}."
            for index in range(1, 34)
        ),
    )

    flowables = pdf_renderer._recipe_body_flowables(long_recipe_meal, styles, doc_width)

    assert isinstance(flowables[0], Table)
    continuation_tables = [
        flowable
        for flowable in flowables[1:]
        if isinstance(flowable, Table) and flowable._colWidths == pytest.approx([8 * pdf_renderer.mm, doc_width - 8 * pdf_renderer.mm])
    ]
    assert continuation_tables


def test_recipe_photo_has_no_centered_photo_fallback(sample_week_plans) -> None:
    styles = pdf_renderer._build_styles(*pdf_renderer._register_fonts())
    meal = next(
        meal
        for plan in sample_week_plans
        for meal in plan.meals
        if resolve_local_meal_image_path(meal) is not None
    )

    image_flowables = pdf_renderer._meal_image_flowables(meal, styles)

    assert image_flowables
    assert image_flowables[0].hAlign == "RIGHT"
    assert not isinstance(pdf_renderer._recipe_body_flowables(meal, styles, 180 * pdf_renderer.mm)[0], KeepTogether)


def test_day_label_is_visible_on_recipe_continuation_pages(tmp_path: Path, sample_week_dates) -> None:
    recipes = {recipe.id: recipe for recipe in built_in_recipes()}
    base_plan = _plan_for_recipe(recipes["r401_farshirovannye_pertsy_s_risom_i_ovoschami_v_duhovke"])
    long_recipe = "\n".join(
        f"{index}. Нарежьте овощи, прогрейте начинку, аккуратно соберите порцию и проверьте готовность шага {index}."
        for index in range(1, 42)
    )
    meals = tuple(
        replace(
            base_plan.meals[0],
            name=f"Ужин: Длинный тестовый рецепт {index}",
            recipe=long_recipe,
        )
        for index in range(1, 5)
    )
    plan = replace(base_plan, meals=meals)

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "day-continuation.pdf")
    pages = [page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages]
    day_pages = []
    day_started = False
    for page_text in pages:
        if "Список продуктов" in page_text:
            break
        if "Длинный тестовый рецепт" in page_text:
            day_started = True
        if day_started:
            day_pages.append(page_text)

    assert len(day_pages) >= 2
    assert all("День 1" in page_text for page_text in day_pages)


def test_shopping_columns_build_two_structured_card_columns() -> None:
    styles = pdf_renderer._build_styles(*pdf_renderer._register_fonts())
    groups = [
        SimpleNamespace(
            title="Овощи",
            items=[
                SimpleNamespace(food_name="помидоры", grams=300),
                SimpleNamespace(food_name="огурцы", grams=200),
            ],
        ),
        SimpleNamespace(
            title="Белки",
            items=[
                SimpleNamespace(food_name="курица", grams=500),
                SimpleNamespace(food_name="творог", grams=250),
            ],
        ),
    ]

    table = pdf_renderer._shopping_columns(groups, styles, 180 * pdf_renderer.mm)

    assert len(table._colWidths) == 3
    assert table._colWidths[1] == pytest.approx(7 * pdf_renderer.mm)
    assert table._cellvalues[0][0]
    assert table._cellvalues[0][2]


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


def _flowable_texts(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        texts: list[str] = []
        for item in value:
            texts.extend(_flowable_texts(item))
        return texts
    if isinstance(value, Table):
        return _flowable_texts(value._cellvalues)
    if isinstance(value, KeepTogether):
        return _flowable_texts(value._content)
    if hasattr(value, "getPlainText"):
        return [value.getPlainText()]
    return []


def _contains_reportlab_image(value) -> bool:
    if isinstance(value, Image):
        return True
    if isinstance(value, (list, tuple)):
        return any(_contains_reportlab_image(item) for item in value)
    if isinstance(value, Table):
        return _contains_reportlab_image(value._cellvalues)
    if isinstance(value, KeepTogether):
        return _contains_reportlab_image(value._content)
    return False


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return _compact_text("\n".join(page.extract_text() or "" for page in reader.pages))


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
