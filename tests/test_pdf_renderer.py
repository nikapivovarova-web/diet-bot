from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

from diet_bot.curated_data import curated_foods
from diet_bot.domain import ActivityLevel, CookingTimePreference, Goal, Sex, UserProfile
from diet_bot.domain import Meal, MealPlan, NutritionTargets, SafetyResult, ShoppingItem
import diet_bot.pdf_renderer as pdf_renderer
from diet_bot.pdf_renderer import _clean_text, _html, render_week_plan_pdf, resolve_local_meal_image_path
from diet_bot.recipe_catalog import built_in_recipes
from diet_bot.shopping import ShoppingGroup
from diet_bot.telegram_app import _apply_batch_carryovers, _build_week_plans, _week_plan_dates


pytestmark = pytest.mark.slow_pdf_builder


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
    assert "●" in text
    assert "Список продуктов" in text
    assert "ориентировочный расчёт" in text


def test_week_pdf_uses_branded_cover_shell(tmp_path: Path, sample_week_dates) -> None:
    plan = _plan_for_recipe(built_in_recipes()[0])

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "branded-shell.pdf")
    text = _pdf_text(pdf_path)

    assert "Food Balance" in text
    assert "@FOODBALANCERU_BOT" in text


def test_week_pdf_cover_notes_and_summary_labels(tmp_path: Path, sample_week_dates) -> None:
    plan = _plan_for_recipe(built_in_recipes()[0])

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "cover-notes.pdf")
    reader = PdfReader(str(pdf_path))
    cover_text = _compact_text(reader.pages[0].extract_text() or "")

    assert "Медицинский дисклеймер" in cover_text
    assert "Если вы пьете соки, газировку, сладкий чай, энергетики" in cover_text
    assert "учитывайте их отдельно" in cover_text
    assert "ориентировочный расчет" in cover_text
    assert "В реальности значения могут немного отличаться из-за бренда продуктов" in cover_text
    assert "точности порций" in cover_text
    assert cover_text.count("Ваш расчет") == 1
    assert "Рацион" in cover_text
    assert "Блюд" not in cover_text


def test_week_pdf_keeps_cover_separate_from_day_one(tmp_path: Path, sample_week_dates) -> None:
    plan = _plan_for_recipe(built_in_recipes()[0])

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "cover-flow.pdf")
    reader = PdfReader(str(pdf_path))
    cover_text = _compact_text(reader.pages[0].extract_text() or "")
    first_day_text = _compact_text(reader.pages[1].extract_text() or "")
    first_meal_title = _clean_text(plan.meals[0].name).split(":", 1)[1].strip()

    assert "\u0414\u0435\u043d\u044c 1" not in cover_text
    assert _compact_text(first_meal_title) not in _compact_text(cover_text)
    assert "\u0414\u0435\u043d\u044c 1" in first_day_text
    assert _compact_text(first_meal_title) in _compact_text(first_day_text)


def test_pdf_brand_assets_can_be_embedded_and_scaled() -> None:
    logo = pdf_renderer._asset_image(pdf_renderer.PDF_LOGO_PATH, 30 * mm, 30 * mm)
    qr = pdf_renderer._asset_image(pdf_renderer.PDF_QR_PATH, 34 * mm, 34 * mm)

    assert logo is not None
    assert logo.drawWidth <= 30 * mm
    assert logo.drawHeight <= 30 * mm
    assert qr is not None
    assert qr.drawWidth <= 34 * mm
    assert qr.drawHeight <= 34 * mm


def test_nutrient_indicator_thresholds_for_pdf_display() -> None:
    cases = (
        (100, "DotGreen", "#4F9E5D"),
        (97, "DotGreen", "#4F9E5D"),
        (95, "DotGreen", "#4F9E5D"),
        (94, "DotYellow", "#D8A23A"),
        (45, "DotYellow", "#D8A23A"),
        (44, "DotRed", "#C95B4A"),
    )

    assert [
        (
            percent,
            pdf_renderer._coverage_dot_style(percent, 100),
            pdf_renderer._coverage_dot_color(percent, 100),
        )
        for percent, _expected_style, _expected_color in cases
    ] == [
        (percent, expected_style, pdf_renderer.colors.HexColor(expected_color))
        for percent, expected_style, expected_color in cases
    ]


def test_week_pdf_renders_shopping_heading_categories_items(
    monkeypatch,
    tmp_path: Path,
    sample_week_dates,
) -> None:
    groups = (
        ShoppingGroup(
            category="vegetable",
            title="Vegetables and greens",
            items=(
                ShoppingItem(food_name="Tomatoes", category="vegetable", grams=300),
                ShoppingItem(food_name="Cucumber", category="vegetable", grams=150),
            ),
        ),
        ShoppingGroup(
            category="protein",
            title="Protein",
            items=(ShoppingItem(food_name="Chicken breast", category="protein", grams=420),),
        ),
    )
    monkeypatch.setattr(pdf_renderer, "build_week_shopping_groups", lambda _plans: groups)
    plan = _plan_for_recipe(built_in_recipes()[0])

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "shopping-content.pdf")
    text = _pdf_text(pdf_path)

    assert pdf_path.exists()
    assert "Список продуктов на неделю" in text
    assert "Vegetables and greens" in text
    assert "Tomatoes" in text
    assert "300 г" in text
    assert "Protein" in text
    assert "Chicken breast" in text
    assert "420 г" in text


def test_week_pdf_handles_long_shopping_list_without_layout_error(
    monkeypatch,
    tmp_path: Path,
    sample_week_dates,
) -> None:
    groups = _dense_shopping_groups()
    monkeypatch.setattr(pdf_renderer, "build_week_shopping_groups", lambda _plans: groups)
    plan = _plan_for_recipe(built_in_recipes()[0])

    pdf_path = render_week_plan_pdf((plan,), (sample_week_dates[0],), tmp_path / "long-shopping.pdf")
    reader = PdfReader(str(pdf_path))
    text = _compact_text("\n".join(page.extract_text() or "" for page in reader.pages))

    assert pdf_path.exists()
    assert len(reader.pages) >= 2
    assert "Список продуктов на неделю" in text
    assert "Vegetables and greens ingredient 25" in text
    assert "Other ingredient 1" in text


def test_week_pdf_packs_dense_shopping_list_into_stable_pages(tmp_path: Path) -> None:
    groups = _dense_shopping_groups()
    base_font, bold_font, emoji_font = pdf_renderer._register_fonts()
    styles = pdf_renderer._build_styles(base_font, bold_font, emoji_font)
    doc = SimpleDocTemplate(
        str(tmp_path / "shopping-probe.pdf"),
        pagesize=A4,
        leftMargin=pdf_renderer.PDF_MARGIN,
        rightMargin=pdf_renderer.PDF_MARGIN,
        topMargin=12 * mm,
        bottomMargin=13 * mm,
    )
    title = pdf_renderer._emoji_title("🛒", "Shopping list for the week", styles)
    first_page_height = pdf_renderer._shopping_first_page_available_height(title, doc.width)

    pages = pdf_renderer._shopping_page_groups(groups, styles, doc.width, first_page_height)

    assert len(pages) == 2
    for page_index, page_groups in enumerate(pages):
        available_height = first_page_height if page_index == 0 else pdf_renderer._shopping_frame_height()
        _, page_height = pdf_renderer._shopping_columns(page_groups, styles, doc.width).wrap(
            pdf_renderer._shopping_layout_width(doc.width),
            available_height,
        )
        assert page_height <= available_height - 2


def test_recipe_card_layout_helpers_split_meal_and_ingredient_text() -> None:
    recipe = built_in_recipes()[0]
    plan = _plan_for_recipe(recipe)
    meal = plan.meals[0]

    meal_type = getattr(pdf_renderer, "_meal_type", None)
    meal_title = getattr(pdf_renderer, "_meal_recipe_title", None)
    ingredient_cells = getattr(pdf_renderer, "_ingredient_cells", None)

    assert meal_type is not None
    assert meal_title is not None
    assert ingredient_cells is not None
    assert meal_type(meal) == "Ужин"
    assert meal_title(meal) == recipe.title

    product, amount, measure = ingredient_cells(meal.portions[0])

    assert product
    assert amount
    assert measure


def test_recipe_steps_are_numbered_chunks_for_readability() -> None:
    recipe_steps = getattr(pdf_renderer, "_recipe_steps", None)

    assert recipe_steps is not None

    steps = recipe_steps("1. Обжарьте овощи.\n2. Добавьте крупу и воду.\n3. Подавайте теплым.")

    assert len(steps) == 3
    assert all(step for step in steps)


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


def test_week_pdf_html_soft_wraps_long_unbroken_tokens() -> None:
    html = _html("TOKEN" + "A" * 160)

    assert max(len(token) for token in html.split()) <= 48


def test_week_pdf_handles_long_recipe_card_without_layout_error(tmp_path: Path, sample_week_dates) -> None:
    recipe = built_in_recipes()[0]
    plan = _plan_for_recipe(recipe)
    long_recipe = " ".join(
        f"Шаг {index}: добавьте ингредиенты, перемешайте и готовьте до мягкости."
        for index in range(1, 28)
    )
    long_meal = replace(plan.meals[0], recipe=long_recipe, image_url=None)
    long_plan = replace(plan, meals=(long_meal,))

    pdf_path = render_week_plan_pdf((long_plan,), (sample_week_dates[0],), tmp_path / "long-recipe.pdf")
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert pdf_path.exists()
    assert len(reader.pages) >= 2
    assert "Шаг 27" in text


def test_week_pdf_removes_partial_output_when_render_fails(monkeypatch, tmp_path: Path, sample_week_dates) -> None:
    class FailingDoc:
        width = 120

        def __init__(self, path, **_kwargs) -> None:
            self.path = Path(path)

        def build(self, *_args, **_kwargs) -> None:
            self.path.write_bytes(b"%PDF-1.4\npartial")
            raise RuntimeError("render failed")

    recipe = built_in_recipes()[0]
    plan = _plan_for_recipe(recipe)
    pdf_path = tmp_path / "partial.pdf"
    monkeypatch.setattr("diet_bot.pdf_renderer.SimpleDocTemplate", FailingDoc)

    with pytest.raises(RuntimeError, match="render failed"):
        render_week_plan_pdf((plan,), (sample_week_dates[0],), pdf_path)

    assert not pdf_path.exists()


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


def _dense_shopping_groups() -> tuple[ShoppingGroup, ...]:
    return (
        _shopping_group("grains", "Grains, bread and side dishes", 11),
        _shopping_group("vegetable", "Vegetables and greens", 25),
        _shopping_group("fruit", "Fruit and berries", 11),
        _shopping_group("protein", "Meat, fish, eggs and protein", 12),
        _shopping_group("dairy", "Dairy products", 9),
        _shopping_group("fat", "Oils and fats", 7),
        _shopping_group("nuts", "Nuts and seeds", 8),
        _shopping_group("spice", "Spices and herbs", 11),
        _shopping_group("sauce", "Sauces and dressings", 13),
        _shopping_group("sweet", "Sweeteners", 4),
        _shopping_group("processed", "Processed meat", 2),
        _shopping_group("other", "Other", 1),
    )


def _shopping_group(category: str, title: str, item_count: int) -> ShoppingGroup:
    return ShoppingGroup(
        category=category,
        title=title,
        items=tuple(
            ShoppingItem(
                food_name=f"{title} ingredient {index + 1}",
                category=category,
                grams=100 + index,
            )
            for index in range(item_count)
        ),
    )


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return _compact_text("\n".join(page.extract_text() or "" for page in reader.pages))


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
