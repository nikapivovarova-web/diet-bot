from __future__ import annotations

import re
import tempfile
import uuid
import math
from collections.abc import Sequence
from contextlib import suppress
from datetime import date
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .chef import format_display_grams, format_ingredient
from .domain import Meal, MealPlan
from .presentation import (
    NUTRIENT_LABELS,
    NUTRIENT_ORDER,
    ORIENTATION_SENTENCE,
    format_batch_recipe_text,
    format_calculation_summary,
)
from .shopping import build_week_shopping_groups


DATA_DIR = Path(__file__).with_name("data")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_SIZE = A4
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE
PDF_MARGIN = 12 * mm
BRAND_GREEN = colors.HexColor("#2F6B48")
DEEP_GREEN = colors.HexColor("#1F3A2A")
SOFT_GREEN = colors.HexColor("#EAF4EA")
PALE_GREEN = colors.HexColor("#F6FAF5")
PAGE_BACKGROUND = colors.HexColor("#FBFAF4")
CARD_BACKGROUND = colors.HexColor("#FFFFFF")
BEIGE = colors.HexColor("#F1E8D9")
LIGHT_GRAY = colors.HexColor("#EEF1EC")
TEXT_COLOR = colors.HexColor("#243126")
MUTED_COLOR = colors.HexColor("#66736A")
LINE_COLOR = colors.HexColor("#D8E2D3")
WARNING_BG = colors.HexColor("#FFF1DC")
WARNING_TEXT = colors.HexColor("#875A1C")
GOOD_BG = colors.HexColor("#E6F3EA")
MODERATE_BG = colors.HexColor("#FFF4D7")
ALERT_BG = colors.HexColor("#FBE8E0")
GOOD_TEXT = colors.HexColor("#2F6B48")
MODERATE_TEXT = colors.HexColor("#7A5C13")
ALERT_TEXT = colors.HexColor("#8A3E2B")
EMOJI_RE = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf\ufe0f]")


def build_week_plan_pdf(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    output_dir: str | Path | None = None,
) -> Path:
    if not plans:
        raise ValueError("At least one meal plan is required.")
    if len(plans) != len(plan_dates):
        raise ValueError("Plans and dates must have the same length.")

    target_dir = Path(output_dir) if output_dir else Path(tempfile.gettempdir()) / "diet_bot_pdfs"
    target_dir.mkdir(parents=True, exist_ok=True)
    first_date = plan_dates[0].strftime("%Y-%m-%d")
    output_path = target_dir / f"foodbalance-week-{first_date}-{uuid.uuid4().hex[:8]}.pdf"
    try:
        return render_week_plan_pdf(plans, plan_dates, output_path)
    except Exception:
        with suppress(OSError):
            output_path.unlink()
        raise


def render_week_plan_pdf(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    output_path: str | Path,
) -> Path:
    if not plans:
        raise ValueError("At least one meal plan is required.")
    if len(plans) != len(plan_dates):
        raise ValueError("Plans and dates must have the same length.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    base_font, bold_font, emoji_font = _register_fonts()
    styles = _build_styles(base_font, bold_font, emoji_font)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=PAGE_SIZE,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=12 * mm,
        bottomMargin=13 * mm,
        title="FoodBalance weekly ration",
        author="FoodBalance",
    )
    story = _build_story(plans, plan_dates, styles, doc.width)
    doc.build(story, onFirstPage=_footer(base_font), onLaterPages=_footer(base_font))
    return output


def resolve_local_meal_image_path(meal: Meal) -> Path | None:
    if not meal.image_url or meal.image_url.startswith(("http://", "https://")):
        return None

    image_path = Path(meal.image_url)
    candidates = [image_path] if image_path.is_absolute() else [DATA_DIR / image_path, PROJECT_ROOT / image_path]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _build_story(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> list:
    story: list = []
    story.extend(_cover_page(plans, plan_dates, styles, doc_width))
    story.append(PageBreak())
    story.extend(_calculation_page(plans[0], styles, doc_width))
    story.append(PageBreak())
    story.extend(_weekly_menu_page(plans, plan_dates, styles, doc_width))
    story.append(PageBreak())
    story.extend(_weekly_prep_page(styles, doc_width))

    for day_index, (plan, plan_date) in enumerate(zip(plans, plan_dates), start=1):
        story.append(PageBreak())
        story.extend(_day_section(plan, plan_date, day_index, styles, doc_width))

    story.append(PageBreak())
    story.extend(_nutrient_report_section(plans, plan_dates, styles, doc_width))
    story.append(PageBreak())
    story.extend(_shopping_section(plans, styles, doc_width))
    story.append(PageBreak())
    story.extend(_disclaimer_section(plans, styles, doc_width))

    return story


def _cover_page(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> list:
    first_plan = plans[0]
    date_range = _date_range(plan_dates)
    meal_count = sum(len(plan.meals) for plan in plans)
    story: list = [
        Spacer(1, 22 * mm),
        _p("FoodBalance", styles["CoverBrand"]),
        Spacer(1, 12 * mm),
        _p("Рацион на неделю", styles["CoverTitle"]),
        _p(date_range, styles["Subtitle"]),
        Spacer(1, 16 * mm),
        _summary_table(first_plan, meal_count, styles, doc_width),
    ]

    if warning := _bmi_cover_warning(first_plan):
        story.append(Spacer(1, 12 * mm))
        story.append(_notice_box("Медицинское предупреждение", warning, styles, doc_width))

    story.extend(
        [
            Spacer(1, 22 * mm),
            _p(
                "Персональный недельный рацион с расчетом калорий, макронутриентов, воды, "
                "рецептами, подготовкой и списком покупок.",
                styles["CoverNote"],
            ),
        ]
    )
    return story


def _summary_table(plan: MealPlan, meal_count: int, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    targets = plan.targets.targets
    data = [
        [
            _metric_card("Калории/день", f"{targets.get('energy_kcal'):.0f} ккал", "цель на день", styles),
            _metric_card(
                "БЖУ",
                (
                    f"Б {targets.get('protein_g'):.0f} г / "
                    f"Ж {targets.get('fat_g'):.0f} г / "
                    f"У {targets.get('carbohydrate_g'):.0f} г"
                ),
                "ориентир на день",
                styles,
            ),
            _metric_card("Вода", f"{plan.targets.water_l:.1f} л", "в день", styles),
            _metric_card("Блюд", str(meal_count), "за неделю", styles),
        ]
    ]
    table = Table(data, colWidths=[doc_width / 4] * 4, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def _date_range(plan_dates: Sequence[date]) -> str:
    return f"{plan_dates[0]:%d.%m.%Y} - {plan_dates[-1]:%d.%m.%Y}"


def _metric_card(label: str, value: str, hint: str, styles: dict[str, ParagraphStyle]) -> list:
    return [
        _p(label, styles["MetricLabel"]),
        Spacer(1, 1.5 * mm),
        _p(value, styles["MetricValue"]),
        Spacer(1, 1 * mm),
        _p(hint, styles["MetricHint"]),
    ]


def _bmi_cover_warning(plan: MealPlan) -> str | None:
    bmi = float(plan.targets.bmi or 0)
    if bmi <= 0:
        return None
    if bmi < 18.5:
        return (
            f"ИМТ {bmi:g} ниже нормы. Рацион лучше согласовать с врачом или нутрициологом, "
            "особенно если вес снижался непреднамеренно."
        )
    if bmi > 24.9:
        return (
            f"ИМТ {bmi:g} выше нормы. Рацион рассчитан автоматически; при заболеваниях, "
            "резком наборе веса или плохом самочувствии лучше обсудить план со специалистом."
        )
    return None


def _notice_box(title: str, text: str, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    table = Table(
        [[_p(title, styles["NoticeTitle"])], [_p(text, styles["NoticeBody"])]],
        colWidths=[doc_width],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WARNING_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E7C28D")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def _calculation_page(plan: MealPlan, styles: dict[str, ParagraphStyle], doc_width: float) -> list:
    lines = [
        _clean_text(line)
        for line in format_calculation_summary(plan.targets, plan.safety).splitlines()
        if _clean_text(line)
    ]
    if lines and lines[0].lower() == "ваш расчет":
        lines = lines[1:]

    story: list = [
        *_page_title("Ваш расчет", "Ориентиры ниже нужны только для чтения PDF. Расчетные значения не меняются.", styles),
        Spacer(1, 5 * mm),
        _calculation_table(lines, styles, doc_width),
        Spacer(1, 6 * mm),
        _p(
            "Калорийность, БЖУ, вода и нутриенты рассчитаны на основе данных анкеты и используются в рационе без изменений.",
            styles["FinePrint"],
        ),
    ]
    return story


def _calculation_table(lines: Sequence[str], styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    rows = [[_p("Показатель", styles["TableHeader"]), _p("Значение", styles["TableHeader"])]]
    for line in lines:
        label, value = _split_calculation_line(line)
        rows.append([_p(label, styles["TableCell"]), _p(value, styles["TableCell"])])

    table = Table(rows, colWidths=[doc_width * 0.34, doc_width * 0.66], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), SOFT_GREEN),
                ("BACKGROUND", (0, 1), (-1, -1), CARD_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _split_calculation_line(line: str) -> tuple[str, str]:
    cleaned = line.strip("- ").strip()
    if ":" not in cleaned:
        return "Комментарий", cleaned
    label, value = cleaned.split(":", 1)
    return label.strip(), value.strip()


def _weekly_menu_page(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> list:
    return [
        *_page_title("Меню на неделю", "Короткий обзор всех приемов пищи перед рецептами.", styles),
        Spacer(1, 5 * mm),
        _weekly_menu_table(plans, plan_dates, styles, doc_width),
    ]


def _weekly_menu_table(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> Table:
    rows = [[
        _p("День", styles["TableHeaderWhite"]),
        _p("Завтрак", styles["TableHeaderWhite"]),
        _p("Обед", styles["TableHeaderWhite"]),
        _p("Перекус", styles["TableHeaderWhite"]),
        _p("Ужин", styles["TableHeaderWhite"]),
    ]]
    slots = ("Завтрак", "Обед", "Перекус", "Ужин")
    for index, (plan, plan_date) in enumerate(zip(plans, plan_dates), start=1):
        by_slot = {_meal_type(meal): _meal_recipe_title(meal) for meal in plan.meals}
        rows.append(
            [
                _p(f"День {index}\n{plan_date:%d.%m}", styles["MenuDay"]),
                *[_p(_short_text(by_slot.get(slot, ""), 54), styles["MenuCell"]) for slot in slots],
            ]
        )

    day_width = 23 * mm
    meal_width = (doc_width - day_width) / 4
    table = Table(rows, colWidths=[day_width, meal_width, meal_width, meal_width, meal_width], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_GREEN),
                ("BACKGROUND", (0, 1), (-1, -1), CARD_BACKGROUND),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _weekly_prep_page(styles: dict[str, ParagraphStyle], doc_width: float) -> list:
    sections = (
        (
            "Отварить заранее",
            "рис, киноа, гречку, пасту или другие крупы из меню. Храните в закрытом контейнере 2-3 дня.",
        ),
        (
            "Нарезать и помыть",
            "овощи, зелень, салатные листья, ягоды. Влажную зелень лучше завернуть в бумажное полотенце.",
        ),
        (
            "Купить свежим ближе к дню приготовления",
            "авокадо, ягоды, зелень, салатные миксы, мягкие фрукты и хлеб для тостов.",
        ),
        (
            "Готовить в день подачи",
            "рыбу, яйца, роллы, блюда с авокадо, свежие салаты и все, что быстро теряет текстуру.",
        ),
    )
    rows = [[_p(title, styles["PrepTitle"]), _p(text, styles["Body"])] for title, text in sections]
    table = Table(rows, colWidths=[doc_width * 0.34, doc_width * 0.66], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [
        *_page_title("Подготовка на неделю", "Небольшая заготовка заранее делает рацион проще в будни.", styles),
        Spacer(1, 5 * mm),
        table,
    ]


def _day_section(
    plan: MealPlan,
    plan_date: date,
    day_index: int,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> list:
    story: list = [
        _day_header(day_index, plan_date, styles, doc_width),
        Spacer(1, 4 * mm),
        _daily_brief_table(plan, styles, doc_width),
        Spacer(1, 5 * mm),
    ]
    for meal in plan.meals:
        story.extend(_meal_card(meal, styles, doc_width))
        story.append(Spacer(1, 5 * mm))
    return story


def _day_header(
    day_index: int,
    plan_date: date,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> Table:
    data = [[_p(f"День {day_index}", styles["DayTitle"]), _p(f"{plan_date:%d.%m.%Y}", styles["DayDate"])]]
    table = Table(data, colWidths=[doc_width * 0.55, doc_width * 0.45])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BRAND_GREEN),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def _daily_brief_table(plan: MealPlan, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    totals = plan.totals
    items = [
        ("Калории", f"{totals.get('energy_kcal'):.0f} ккал"),
        ("Белки", f"{totals.get('protein_g'):.0f} г"),
        ("Жиры", f"{totals.get('fat_g'):.0f} г"),
        ("Углеводы", f"{totals.get('carbohydrate_g'):.0f} г"),
        ("Клетчатка", f"{totals.get('fiber_g'):.0f} г"),
        ("Вода", f"{plan.targets.water_l:.1f} л"),
    ]
    rows = [[_p(label, styles["BriefLabel"]), _p(value, styles["BriefValue"])] for label, value in items]
    columns = 3
    grid_rows: list[list] = []
    for index in range(0, len(rows), columns):
        grid_rows.append([cell for pair in rows[index : index + columns] for cell in pair])

    table = Table(grid_rows, colWidths=[doc_width / 6] * 6, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _meal_card(meal: Meal, styles: dict[str, ParagraphStyle], doc_width: float) -> list:
    flowables: list = [
        _meal_header_table(meal, styles, doc_width),
        _meal_nutrition_badges(meal, styles, doc_width),
        Spacer(1, 3 * mm),
    ]
    if meal.batch and meal.batch.is_carryover:
        flowables.append(_soft_note(f"Порция сегодня: {_counted(meal.batch.serving_units, meal.batch.unit_forms)} из приготовленной партии.", styles, doc_width))
        flowables.extend(_ingredient_section("Ингредиенты порции", meal.portions, styles, doc_width))
        flowables.extend(
            _recipe_section(
                f"Съешьте {_counted(meal.batch.serving_units, meal.batch.unit_forms)} из приготовленной партии. "
                "В расчет дня входит только сегодняшняя порция.",
                styles,
                doc_width,
            )
        )
    elif meal.batch:
        serving = _counted(meal.batch.serving_units, meal.batch.unit_forms)
        total = _counted(meal.batch.total_units, meal.batch.unit_forms)
        prep_count = _counted(meal.batch.serving_count, ("перекус", "перекуса", "перекусов"))
        remaining_units = meal.batch.total_units - meal.batch.serving_units
        remaining_servings = meal.batch.serving_count - 1
        batch_note = (
            f"Приготовьте {total} на {prep_count}. Сегодня съешьте {serving}; "
            f"остальные {_counted(remaining_units, meal.batch.unit_forms)} уберите на "
            f"следующие {_counted(remaining_servings, ('перекус', 'перекуса', 'перекусов'))}."
        )
        flowables.append(_soft_note(batch_note, styles, doc_width))
        flowables.extend(_ingredient_section("Ингредиенты на партию", meal.batch.batch_portions, styles, doc_width))
        flowables.extend(_recipe_section(format_batch_recipe_text(meal.recipe, meal.batch), styles, doc_width))
        flowables.append(_p("В расчет дня входит только сегодняшняя порция.", styles["FinePrint"]))
    else:
        flowables.extend(_ingredient_section("Ингредиенты", meal.portions, styles, doc_width))
        flowables.extend(_recipe_section(meal.recipe, styles, doc_width))
    return flowables


def _meal_header_table(meal: Meal, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    meal_type = _meal_type(meal)
    recipe_title = _meal_recipe_title(meal)
    table = Table(
        [[_p(meal_type, styles["MealType"]), _p(recipe_title, styles["MealTitle"])]],
        colWidths=[28 * mm, doc_width - 28 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), BRAND_GREEN),
                ("BACKGROUND", (1, 0), (1, -1), CARD_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _meal_nutrition_badges(meal: Meal, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    nutrients = meal.nutrients
    badges = [
        ("ккал", f"{nutrients.get('energy_kcal'):.0f}"),
        ("Б", f"{nutrients.get('protein_g'):.0f} г"),
        ("Ж", f"{nutrients.get('fat_g'):.0f} г"),
        ("У", f"{nutrients.get('carbohydrate_g'):.0f} г"),
    ]
    table = Table(
        [[[_p(label, styles["BadgeLabel"]), _p(value, styles["BadgeValue"])] for label, value in badges]],
        colWidths=[doc_width / 4] * 4,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _ingredient_section(
    title: str,
    portions: Sequence,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> list:
    return [
        _p(title, styles["Label"]),
        _ingredient_table(portions, styles, doc_width),
        Spacer(1, 3 * mm),
    ]


def _ingredient_table(portions: Sequence, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    rows = [[
        _p("Продукт", styles["TableHeader"]),
        _p("Количество", styles["TableHeader"]),
        _p("Бытовая мера", styles["TableHeader"]),
    ]]
    if not portions:
        rows.append([_p("Нет данных по ингредиентам", styles["TableCell"]), "", ""])
    else:
        for portion in portions:
            product, amount, measure = _ingredient_cells(portion)
            rows.append(
                [
                    _p(product, styles["TableCell"]),
                    _p(amount, styles["TableCell"]),
                    _p(measure, styles["TableCell"]),
                ]
            )

    table = Table(rows, colWidths=[doc_width * 0.46, doc_width * 0.22, doc_width * 0.32], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BEIGE),
                ("BACKGROUND", (0, 1), (-1, -1), CARD_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _ingredient_cells(portion) -> tuple[str, str, str]:
    text = format_ingredient(portion)
    if " - " not in text:
        return text, "", ""
    product, rest = text.split(" - ", 1)
    measure = ""
    amount = rest
    if rest.endswith(")") and " (" in rest:
        amount, measure = rest.rsplit(" (", 1)
        measure = measure[:-1]
    return product.strip(), amount.strip(), measure.strip()


def _recipe_section(recipe: str, styles: dict[str, ParagraphStyle], doc_width: float) -> list:
    return [
        _p("Как приготовить", styles["Label"]),
        _recipe_steps_table(recipe, styles, doc_width),
    ]


def _recipe_steps_table(recipe: str, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    steps = _recipe_steps(recipe)
    rows = [
        [
            _p(f"{index}.", styles["StepNumber"]),
            _p(step, styles["Body"]),
        ]
        for index, step in enumerate(steps, start=1)
    ]
    table = Table(rows, colWidths=[10 * mm, doc_width - 10 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.2, LIGHT_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _recipe_steps(recipe: str) -> tuple[str, ...]:
    text = _clean_text(recipe or "")
    if not text:
        return ("Инструкция приготовления не указана.",)

    normalized = re.sub(r"\s+", " ", text).strip()
    if "\n" in text:
        chunks = [chunk.strip(" -0123456789.()") for chunk in text.splitlines()]
        chunks = [chunk for chunk in chunks if chunk]
        if chunks:
            return tuple(chunks)

    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", normalized) if sentence.strip()]
    if len(sentences) <= 1:
        return tuple(_chunk_long_text(normalized))

    steps: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > 260:
            if current:
                steps.append(current)
                current = ""
            steps.extend(_chunk_long_text(sentence))
            continue
        if current and len(current) + len(sentence) > 220:
            steps.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        steps.append(current)
    return tuple(steps)


def _chunk_long_text(text: str, max_chars: int = 240) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + len(word) + 1 > max_chars:
            chunks.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        chunks.append(current)
    return chunks or ["Инструкция приготовления не указана."]


def _soft_note(text: str, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    table = Table([[_p(text, styles["FinePrint"])]], colWidths=[doc_width], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _meal_type(meal: Meal) -> str:
    text = _clean_text(meal.name)
    if ":" in text:
        return text.split(":", 1)[0].strip() or "Прием пищи"
    for slot in ("Завтрак", "Обед", "Перекус", "Ужин"):
        if text.startswith(slot):
            return slot
    return "Прием пищи"


def _meal_recipe_title(meal: Meal) -> str:
    text = _clean_text(meal.name)
    if ":" in text:
        return text.split(":", 1)[1].strip() or text
    for slot in ("Завтрак", "Обед", "Перекус", "Ужин"):
        if text.startswith(slot):
            return text.removeprefix(slot).strip(" :")
    return text or "Блюдо"


def _short_text(text: str, max_chars: int) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 3].rstrip()}..."


def _meal_ingredients_media_table(
    meal: Meal,
    image: list | None,
    styles: dict[str, ParagraphStyle],
    available_width: float,
) -> Table:
    if not image:
        return _ingredient_portions_panel(meal.portions, styles, available_width)

    ingredient_width = available_width * 0.68
    image_width = available_width * 0.28
    ingredients = _ingredient_list_flowables("Ингредиенты:", meal.portions, styles, ingredient_width)
    media: list = []
    if image:
        media.extend(image)

    table = Table([[ingredients, media]], colWidths=[ingredient_width, image_width], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _ingredient_portions_panel(
    portions: Sequence,
    styles: dict[str, ParagraphStyle],
    available_width: float,
) -> Table:
    table = Table([[_ingredient_list_flowables("Ингредиенты:", portions, styles, available_width)]], colWidths=[available_width])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _meal_detail_flowables(meal: Meal, styles: dict[str, ParagraphStyle], available_width: float) -> list:
    if not meal.batch:
        return [
            *_ingredient_list_flowables("Ингредиенты:", meal.portions, styles, available_width),
            _p("Как приготовить:", styles["Label"]),
            _p(meal.recipe, styles["Body"]),
            Spacer(1, 1.5 * mm),
        ]

    serving = _counted(meal.batch.serving_units, meal.batch.unit_forms)
    if meal.batch.is_carryover:
        return [
            _p(f"Порция сегодня: {serving}", styles["Body"]),
            _p(f"Как приготовить: съешьте {serving} из приготовленной партии.", styles["Body"]),
            _p("В расчет дня входит только сегодняшняя порция.", styles["Body"]),
            Spacer(1, 1.5 * mm),
        ]

    total = _counted(meal.batch.total_units, meal.batch.unit_forms)
    prep_count = _counted(meal.batch.serving_count, ("перекус", "перекуса", "перекусов"))
    remaining_units = meal.batch.total_units - meal.batch.serving_units
    remaining_servings = meal.batch.serving_count - 1
    return [
        _p(f"Порция сегодня: {serving}", styles["Body"]),
        _p(f"Приготовьте {total} на {prep_count}: сегодня съешьте только {serving}.", styles["Body"]),
        _p(
            (
                f"Остальные {_counted(remaining_units, meal.batch.unit_forms)} уберите на "
                f"следующие {_counted(remaining_servings, ('перекус', 'перекуса', 'перекусов'))}."
            ),
            styles["Body"],
        ),
        Spacer(1, 1 * mm),
        *_ingredient_list_flowables("Ингредиенты на партию:", meal.batch.batch_portions, styles, available_width),
        _p("Как приготовить:", styles["Label"]),
        _p(format_batch_recipe_text(meal.recipe, meal.batch), styles["Body"]),
        _p("В расчет дня входит только сегодняшняя порция.", styles["Body"]),
        Spacer(1, 1.5 * mm),
    ]


def _ingredient_list_flowables(
    title: str,
    portions: Sequence,
    styles: dict[str, ParagraphStyle],
    available_width: float,
) -> list:
    flowables: list = [_p(title, styles["Label"])]
    if len(portions) >= 6 and available_width >= 90 * mm:
        flowables.append(_ingredient_portions_table(portions, styles, available_width))
    else:
        for portion in portions:
            flowables.append(_p(f"- {format_ingredient(portion)}", styles["Body"]))
    flowables.append(Spacer(1, 1.5 * mm))
    return flowables


def _ingredient_portions_table(
    portions: Sequence,
    styles: dict[str, ParagraphStyle],
    available_width: float,
) -> Table:
    columns = 2
    row_count = math.ceil(len(portions) / columns)
    rows: list[list] = []
    for row_index in range(row_count):
        row: list = []
        for column_index in range(columns):
            item_index = row_index + column_index * row_count
            if item_index < len(portions):
                row.append(_p(f"- {format_ingredient(portions[item_index])}", styles["Body"]))
            else:
                row.append("")
        rows.append(row)

    table = Table(rows, colWidths=[available_width / columns] * columns, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _counted(count: int, forms: tuple[str, str, str]) -> str:
    return f"{count} {_count_form(count, forms)}"


def _count_form(count: int, forms: tuple[str, str, str]) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return forms[0]
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return forms[1]
    return forms[2]


def _meal_image_flowables(meal: Meal, styles: dict[str, ParagraphStyle]) -> list | None:
    image_path = resolve_local_meal_image_path(meal)
    if image_path is None:
        return None
    try:
        reader = ImageReader(str(image_path))
        width, height = reader.getSize()
        scale = min((58 * mm) / width, (42 * mm) / height)
        flowables: list = [Image(str(image_path), width=width * scale, height=height * scale)]
    except Exception:
        return None

    if meal.image_attribution:
        credit = f"Фото: {meal.image_attribution}"
        if meal.source_url:
            credit = f"{credit}\n{meal.source_url}"
        flowables.append(Spacer(1, 1.5 * mm))
        flowables.append(_p(credit, styles["Credit"]))
    return flowables


def _meal_nutrition_text(meal: Meal) -> str:
    nutrients = meal.nutrients
    return (
        f"{nutrients.get('energy_kcal'):.0f} ккал   "
        f"Б {nutrients.get('protein_g'):.0f} г   "
        f"Ж {nutrients.get('fat_g'):.0f} г   "
        f"У {nutrients.get('carbohydrate_g'):.0f} г"
    )


def _nutrient_report_section(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> list:
    story: list = [
        *_page_title(
            "Подробный нутриентный отчет",
            "Проценты показывают отношение факта к дневной цели. Мягкий зеленый - 90-110%, бежевый - умеренное отклонение, оранжевый - заметное отклонение.",
            styles,
        ),
        Spacer(1, 5 * mm),
    ]
    for day_index, (plan, plan_date) in enumerate(zip(plans, plan_dates), start=1):
        if day_index > 1:
            story.append(PageBreak())
        story.append(_p(f"День {day_index} - {plan_date:%d.%m.%Y}", styles["SectionTitle"]))
        story.append(_daily_totals_table(plan, styles, doc_width))
        story.append(Spacer(1, 4 * mm))
    return story


def _daily_totals_table(plan: MealPlan, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    rows = [
        [
            _p("Нутриент", styles["TableHeader"]),
            _p("Факт", styles["TableHeader"]),
            _p("Цель", styles["TableHeader"]),
            _p("%", styles["TableHeader"]),
        ]
    ]
    row_styles: list[tuple] = []
    for key in NUTRIENT_ORDER:
        value = plan.totals.get(key)
        target = plan.targets.targets.get(key)
        row_index = len(rows)
        rows.append(
            [
                _p(NUTRIENT_LABELS[key], styles["TableCell"]),
                _p(f"{value:.1f}", styles["TableCell"]),
                _p(f"{target:.1f}", styles["TableCell"]),
                _p(_coverage_percent(value, target), styles["TableCell"]),
            ]
        )
        row_styles.extend(
            [
                ("BACKGROUND", (3, row_index), (3, row_index), _coverage_background(value, target)),
                ("TEXTCOLOR", (3, row_index), (3, row_index), _coverage_text_color(value, target)),
            ]
        )
    table = Table(
        rows,
        colWidths=[doc_width * 0.46, doc_width * 0.18, doc_width * 0.18, doc_width * 0.18],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), SOFT_GREEN),
                ("BACKGROUND", (0, 1), (-1, -1), CARD_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
            + row_styles
        )
    )
    return table


def _shopping_section(plans: Sequence[MealPlan], styles: dict[str, ParagraphStyle], doc_width: float) -> list:
    story: list = [
        *_page_title("Список покупок", "Чек-лист по категориям для магазина или печати.", styles),
        Spacer(1, 4 * mm),
    ]
    groups = build_week_shopping_groups(plans)
    if not groups:
        story.append(_p("Список пуст.", styles["Body"]))
    else:
        for group in groups:
            story.append(_shopping_group_title(group.title, styles, doc_width))
            story.append(_shopping_items_table(group.items, styles, doc_width))
            story.append(Spacer(1, 3 * mm))
    return story


def _shopping_group_title(title: str, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    table = Table([[_p(title, styles["ShoppingGroupTitle"])]], colWidths=[doc_width], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _shopping_items_table(items: Sequence, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    columns = 2 if len(items) >= 8 else 1
    row_count = max(1, math.ceil(len(items) / columns))
    rows: list[list] = []
    for row_index in range(row_count):
        row: list = []
        for column_index in range(columns):
            item_index = row_index + column_index * row_count
            if item_index < len(items):
                item = items[item_index]
                row.append(_p(f"[ ] {item.food_name} - {format_display_grams(item.grams)} г", styles["ShoppingItem"]))
            else:
                row.append("")
        rows.append(row)

    table = Table(rows, colWidths=[doc_width / columns] * columns, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BACKGROUND),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.2, LIGHT_GRAY),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _page_title(title: str, subtitle: str, styles: dict[str, ParagraphStyle]) -> list:
    return [
        _p(title, styles["PageTitle"]),
        Spacer(1, 1.5 * mm),
        _p(subtitle, styles["PageSubtitle"]),
    ]


def _disclaimer_section(plans: Sequence[MealPlan], styles: dict[str, ParagraphStyle], doc_width: float) -> list:
    story: list = [
        *_page_title("Дисклеймер", "Важные ограничения автоматического рациона.", styles),
        Spacer(1, 5 * mm),
        _notice_box(
            "Важно",
            (
                "Рацион рассчитан автоматически на основе указанных данных. Он не заменяет консультацию врача "
                "или нутрициолога. При заболеваниях, беременности, кормлении грудью, расстройствах пищевого "
                "поведения, выраженном дефиците или избытке массы тела рацион лучше согласовать со специалистом."
            ),
            styles,
            doc_width,
        ),
        Spacer(1, 5 * mm),
        _p(
            "Если вы пьете соки, газировку, сладкий чай, энергетики или другие калорийные напитки, учитывайте их "
            "в рационе: они могут заметно добавить калории и сахар.",
            styles["Body"],
        ),
        _p(ORIENTATION_SENTENCE, styles["Body"]),
    ]
    disclaimers = tuple(dict.fromkeys(disclaimer for plan in plans for disclaimer in plan.safety.disclaimers))
    if disclaimers:
        story.append(Spacer(1, 5 * mm))
        story.append(_p("Дополнительные предупреждения", styles["SectionTitle"]))
        for disclaimer in disclaimers:
            story.append(_p(disclaimer, styles["Body"]))
    return story


def _section_title_with_icon(
    icon: str,
    title: str,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> Table:
    table = Table(
        [[_emoji_p(icon, styles["SectionEmoji"]), _p(title, styles["SectionTitle"])]],
        colWidths=[8 * mm, doc_width - 8 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _calculation_line(line: str, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    icon = _leading_icon(line)
    text = _clean_text(line)
    table = Table(
        [[_emoji_p(icon, styles["InlineEmoji"]), _p(text, styles["Body"])]],
        colWidths=[7 * mm, doc_width - 7 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return table


def _emoji_label(icon: str, text: str, styles: dict[str, ParagraphStyle]) -> list:
    return [_emoji_p(icon, styles["MetricEmoji"]), _p(text, styles["MetricLabel"])]


def _emoji_title(icon: str, text: str, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [[_emoji_p(icon, styles["SectionEmoji"]), _p(text, styles["TitleSmall"])]],
        colWidths=[10 * mm, 160 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _leading_icon(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "•"
    for icon in ("🧮", "📌", "⚠️", "🔥", "🎯", "💧", "🥩", "🛡️", "🛒", "🥤"):
        if stripped.startswith(icon):
            return icon
    return "•"


def _coverage_percent(value: float, target: float) -> str:
    if target <= 0:
        return "0%"
    return f"{value / target * 100:.0f}%"


def _coverage_level(value: float, target: float) -> str:
    if target <= 0:
        return "alert"
    percent = value / target * 100
    if 90 <= percent <= 110:
        return "good"
    if 70 <= percent < 90 or 110 < percent <= 130:
        return "moderate"
    return "alert"


def _coverage_background(value: float, target: float):
    level = _coverage_level(value, target)
    if level == "good":
        return GOOD_BG
    if level == "moderate":
        return MODERATE_BG
    return ALERT_BG


def _coverage_text_color(value: float, target: float):
    level = _coverage_level(value, target)
    if level == "good":
        return GOOD_TEXT
    if level == "moderate":
        return MODERATE_TEXT
    return ALERT_TEXT


def _register_fonts() -> tuple[str, str, str]:
    regular_candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/local/share/fonts/dejavu/DejaVuSans.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/local/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ]
    regular = next((path for path in regular_candidates if path.exists()), None)
    bold = next((path for path in bold_candidates if path.exists()), regular)
    if regular is None:
        return "Helvetica", "Helvetica-Bold", "Helvetica"

    pdfmetrics.registerFont(TTFont("FoodBalanceRegular", str(regular)))
    if bold and bold != regular:
        pdfmetrics.registerFont(TTFont("FoodBalanceBold", str(bold)))
        return "FoodBalanceRegular", "FoodBalanceBold", "FoodBalanceRegular"
    return "FoodBalanceRegular", "FoodBalanceRegular", "FoodBalanceRegular"


def _build_styles(base_font: str, bold_font: str, emoji_font: str) -> dict[str, ParagraphStyle]:
    _ = emoji_font
    sample = getSampleStyleSheet()
    body = ParagraphStyle(
        "FoodBalanceBody",
        parent=sample["BodyText"],
        fontName=base_font,
        fontSize=10.6,
        leading=14.2,
        textColor=TEXT_COLOR,
        spaceAfter=1.2 * mm,
    )
    return {
        "Brand": ParagraphStyle(
            "FoodBalanceBrand",
            parent=body,
            fontName=bold_font,
            fontSize=17,
            leading=20,
            alignment=TA_CENTER,
            textColor=BRAND_GREEN,
        ),
        "CoverBrand": ParagraphStyle(
            "FoodBalanceCoverBrand",
            parent=body,
            fontName=bold_font,
            fontSize=22,
            leading=25,
            alignment=TA_CENTER,
            textColor=BRAND_GREEN,
        ),
        "Title": ParagraphStyle(
            "FoodBalanceTitle",
            parent=body,
            fontName=bold_font,
            fontSize=30,
            leading=34,
            alignment=TA_CENTER,
            textColor=TEXT_COLOR,
            spaceAfter=2 * mm,
        ),
        "CoverTitle": ParagraphStyle(
            "FoodBalanceCoverTitle",
            parent=body,
            fontName=bold_font,
            fontSize=39,
            leading=44,
            alignment=TA_CENTER,
            textColor=DEEP_GREEN,
            spaceAfter=2 * mm,
        ),
        "TitleSmall": ParagraphStyle(
            "FoodBalanceTitleSmall",
            parent=body,
            fontName=bold_font,
            fontSize=22,
            leading=26,
            textColor=TEXT_COLOR,
        ),
        "PageTitle": ParagraphStyle(
            "FoodBalancePageTitle",
            parent=body,
            fontName=bold_font,
            fontSize=24,
            leading=29,
            textColor=DEEP_GREEN,
            spaceAfter=1 * mm,
        ),
        "PageSubtitle": ParagraphStyle(
            "FoodBalancePageSubtitle",
            parent=body,
            fontSize=11.2,
            leading=14,
            textColor=MUTED_COLOR,
        ),
        "Subtitle": ParagraphStyle(
            "FoodBalanceSubtitle",
            parent=body,
            fontSize=15,
            leading=18,
            alignment=TA_CENTER,
            textColor=MUTED_COLOR,
        ),
        "CoverNote": ParagraphStyle(
            "FoodBalanceCoverNote",
            parent=body,
            fontSize=11.5,
            leading=15,
            alignment=TA_CENTER,
            textColor=MUTED_COLOR,
        ),
        "SectionTitle": ParagraphStyle(
            "FoodBalanceSectionTitle",
            parent=body,
            fontName=bold_font,
            fontSize=14.5,
            leading=18,
            textColor=BRAND_GREEN,
            spaceBefore=2 * mm,
            spaceAfter=2 * mm,
        ),
        "SectionEmoji": ParagraphStyle(
            "FoodBalanceSectionEmoji",
            parent=body,
            fontName=base_font,
            fontSize=14,
            leading=17,
            textColor=BRAND_GREEN,
            alignment=TA_CENTER,
        ),
        "InlineEmoji": ParagraphStyle(
            "FoodBalanceInlineEmoji",
            parent=body,
            fontName=base_font,
            fontSize=10.6,
            leading=14.2,
            textColor=BRAND_GREEN,
            alignment=TA_CENTER,
        ),
        "MetricEmoji": ParagraphStyle(
            "FoodBalanceMetricEmoji",
            parent=body,
            fontName=base_font,
            fontSize=10,
            leading=12,
            textColor=BRAND_GREEN,
        ),
        "DayTitle": ParagraphStyle(
            "FoodBalanceDayTitle",
            parent=body,
            fontName=bold_font,
            fontSize=23,
            leading=27,
            textColor=colors.white,
        ),
        "DayDate": ParagraphStyle(
            "FoodBalanceDayDate",
            parent=body,
            fontName=bold_font,
            fontSize=15,
            leading=18,
            alignment=TA_RIGHT,
            textColor=colors.white,
        ),
        "BriefLabel": ParagraphStyle(
            "FoodBalanceBriefLabel",
            parent=body,
            fontSize=8.5,
            leading=10.5,
            textColor=MUTED_COLOR,
        ),
        "BriefValue": ParagraphStyle(
            "FoodBalanceBriefValue",
            parent=body,
            fontName=bold_font,
            fontSize=11.5,
            leading=13.5,
            textColor=DEEP_GREEN,
        ),
        "MealType": ParagraphStyle(
            "FoodBalanceMealType",
            parent=body,
            fontName=bold_font,
            fontSize=10.6,
            leading=13,
            alignment=TA_CENTER,
            textColor=colors.white,
        ),
        "MealTitle": ParagraphStyle(
            "FoodBalanceMealTitle",
            parent=body,
            fontName=bold_font,
            fontSize=13.8,
            leading=17,
            textColor=TEXT_COLOR,
        ),
        "Body": body,
        "Label": ParagraphStyle(
            "FoodBalanceLabel",
            parent=body,
            fontName=bold_font,
            fontSize=12,
            leading=15,
            textColor=TEXT_COLOR,
            spaceAfter=1 * mm,
        ),
        "NoticeTitle": ParagraphStyle(
            "FoodBalanceNoticeTitle",
            parent=body,
            fontName=bold_font,
            fontSize=11.8,
            leading=14.5,
            textColor=WARNING_TEXT,
        ),
        "NoticeBody": ParagraphStyle(
            "FoodBalanceNoticeBody",
            parent=body,
            fontSize=10.5,
            leading=14,
            textColor=WARNING_TEXT,
        ),
        "PrepTitle": ParagraphStyle(
            "FoodBalancePrepTitle",
            parent=body,
            fontName=bold_font,
            fontSize=11.5,
            leading=14.5,
            textColor=BRAND_GREEN,
        ),
        "Credit": ParagraphStyle(
            "FoodBalanceCredit",
            parent=body,
            fontSize=8.2,
            leading=10,
            textColor=MUTED_COLOR,
        ),
        "ChipText": ParagraphStyle(
            "FoodBalanceChipText",
            parent=body,
            fontName=bold_font,
            fontSize=10.8,
            leading=13,
            textColor=BRAND_GREEN,
            backColor=PALE_GREEN,
            borderPadding=(3, 4, 3),
        ),
        "MetricLabel": ParagraphStyle(
            "FoodBalanceMetricLabel",
            parent=body,
            fontName=bold_font,
            fontSize=9.4,
            leading=11.5,
            textColor=MUTED_COLOR,
        ),
        "MetricValue": ParagraphStyle(
            "FoodBalanceMetricValue",
            parent=body,
            fontName=bold_font,
            fontSize=12.8,
            leading=16,
            textColor=DEEP_GREEN,
        ),
        "MetricHint": ParagraphStyle(
            "FoodBalanceMetricHint",
            parent=body,
            fontSize=8.8,
            leading=10.5,
            textColor=MUTED_COLOR,
        ),
        "BadgeLabel": ParagraphStyle(
            "FoodBalanceBadgeLabel",
            parent=body,
            fontSize=8.5,
            leading=10,
            textColor=MUTED_COLOR,
        ),
        "BadgeValue": ParagraphStyle(
            "FoodBalanceBadgeValue",
            parent=body,
            fontName=bold_font,
            fontSize=11.2,
            leading=13.5,
            textColor=BRAND_GREEN,
        ),
        "StepNumber": ParagraphStyle(
            "FoodBalanceStepNumber",
            parent=body,
            fontName=bold_font,
            fontSize=10.5,
            leading=14,
            alignment=TA_CENTER,
            textColor=BRAND_GREEN,
        ),
        "TableHeaderCenter": ParagraphStyle(
            "FoodBalanceTableHeaderCenter",
            parent=body,
            fontName=bold_font,
            fontSize=9.5,
            leading=11.5,
            alignment=TA_CENTER,
            textColor=TEXT_COLOR,
        ),
        "TableHeader": ParagraphStyle(
            "FoodBalanceTableHeader",
            parent=body,
            fontName=bold_font,
            fontSize=9.5,
            leading=11.5,
            textColor=TEXT_COLOR,
        ),
        "TableHeaderWhite": ParagraphStyle(
            "FoodBalanceTableHeaderWhite",
            parent=body,
            fontName=bold_font,
            fontSize=9.5,
            leading=11.5,
            textColor=colors.white,
        ),
        "TableCell": ParagraphStyle(
            "FoodBalanceTableCell",
            parent=body,
            fontSize=9.4,
            leading=12,
            textColor=TEXT_COLOR,
        ),
        "MenuDay": ParagraphStyle(
            "FoodBalanceMenuDay",
            parent=body,
            fontName=bold_font,
            fontSize=8.8,
            leading=11,
            textColor=DEEP_GREEN,
        ),
        "MenuCell": ParagraphStyle(
            "FoodBalanceMenuCell",
            parent=body,
            fontSize=8.6,
            leading=10.8,
            textColor=TEXT_COLOR,
        ),
        "ShoppingGroupTitle": ParagraphStyle(
            "FoodBalanceShoppingGroupTitle",
            parent=body,
            fontName=bold_font,
            fontSize=12.5,
            leading=15,
            textColor=BRAND_GREEN,
        ),
        "ShoppingItem": ParagraphStyle(
            "FoodBalanceShoppingItem",
            parent=body,
            fontSize=10.4,
            leading=13,
            textColor=TEXT_COLOR,
            spaceAfter=0,
        ),
        "FinePrint": ParagraphStyle(
            "FoodBalanceFinePrint",
            parent=body,
            fontSize=9.4,
            leading=12.2,
            textColor=MUTED_COLOR,
            spaceAfter=0.8 * mm,
        ),
        "DotGreen": ParagraphStyle(
            "FoodBalanceDotGreen",
            parent=body,
            fontName=bold_font,
            fontSize=12,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#4F9E5D"),
        ),
        "DotYellow": ParagraphStyle(
            "FoodBalanceDotYellow",
            parent=body,
            fontName=bold_font,
            fontSize=12,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#D8A23A"),
        ),
        "DotRed": ParagraphStyle(
            "FoodBalanceDotRed",
            parent=body,
            fontName=bold_font,
            fontSize=12,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#C95B4A"),
        ),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_html(text), style)


def _emoji_p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_html(text, strip_emoji=False), style)


def _html(text: str, strip_emoji: bool = True) -> str:
    cleaned = _clean_text(text) if strip_emoji else _clean_basic_text(text)
    return escape(cleaned, quote=False).replace("\n", "<br/>")


def _clean_text(text: str) -> str:
    normalized = _clean_basic_text(text)
    return EMOJI_RE.sub("", normalized).strip()


def _clean_basic_text(text: str) -> str:
    return (
        str(text)
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u00a0", " ")
    ).strip()


def _footer(base_font: str):
    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFillColor(PAGE_BACKGROUND)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
        canvas.setFont(base_font, 8)
        canvas.setFillColor(MUTED_COLOR)
        canvas.drawString(doc.leftMargin, 8 * mm, "FoodBalance")
        canvas.drawRightString(PAGE_WIDTH - doc.rightMargin, 8 * mm, f"Страница {doc.page}")
        canvas.restoreState()

    return draw
