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
from reportlab.lib.enums import TA_CENTER, TA_LEFT
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
PDF_MARGIN = 9 * mm
BRAND_GREEN = colors.HexColor("#4F7D57")
SOFT_GREEN = colors.HexColor("#EEF6EC")
PALE_GREEN = colors.HexColor("#F7FBF5")
TEXT_COLOR = colors.HexColor("#243126")
MUTED_COLOR = colors.HexColor("#66736A")
LINE_COLOR = colors.HexColor("#D9E5D5")
EMOJI_RE = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf\ufe0f]")
LONG_TOKEN_MAX_CHARS = 48
LONG_TOKEN_RE = re.compile(r"\S{" + str(LONG_TOKEN_MAX_CHARS + 1) + r",}")


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
    remove_output_on_error = not output.exists()
    base_font, bold_font, emoji_font = _register_fonts()
    styles = _build_styles(base_font, bold_font, emoji_font)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=PAGE_SIZE,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=8 * mm,
        bottomMargin=9 * mm,
        title="FoodBalance weekly ration",
        author="FoodBalance",
    )
    story = _build_story(plans, plan_dates, styles, doc.width)
    try:
        doc.build(story, onFirstPage=_footer(base_font), onLaterPages=_footer(base_font))
    except Exception:
        if remove_output_on_error:
            with suppress(OSError):
                output.unlink()
        raise
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
    story.append(Spacer(1, 6 * mm))

    for day_index, (plan, plan_date) in enumerate(zip(plans, plan_dates), start=1):
        story.extend(_day_section(plan, plan_date, day_index, styles, doc_width))
        story.append(Spacer(1, 5 * mm))

    story.append(PageBreak())
    story.extend(_shopping_section(plans, styles, doc_width))

    return story


def _cover_page(
    plans: Sequence[MealPlan],
    plan_dates: Sequence[date],
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> list:
    first_plan = plans[0]
    date_range = f"{plan_dates[0]:%d.%m.%Y} - {plan_dates[-1]:%d.%m.%Y}"
    meal_count = sum(len(plan.meals) for plan in plans)
    story: list = [
        Spacer(1, 7 * mm),
        _p("FoodBalance", styles["Brand"]),
        Spacer(1, 6 * mm),
        _p("Рацион на неделю", styles["Title"]),
        _p(date_range, styles["Subtitle"]),
        Spacer(1, 7 * mm),
        _summary_table(first_plan, meal_count, styles),
        Spacer(1, 6 * mm),
        _section_title_with_icon("🧮", "Ваш расчет", styles, doc_width),
    ]

    for line in format_calculation_summary(first_plan.targets, first_plan.safety).splitlines():
        if line.strip():
            story.append(_calculation_line(line, styles, doc_width))
        else:
            story.append(Spacer(1, 2 * mm))
    return story


def _summary_table(plan: MealPlan, meal_count: int, styles: dict[str, ParagraphStyle]) -> Table:
    targets = plan.targets.targets
    data = [[
        [_emoji_label("📌", "ИМТ", styles), _p(str(plan.targets.bmi), styles["MetricValue"])],
        [_emoji_label("🎯", "Цель", styles), _p(f"{targets.get('energy_kcal'):.0f} ккал/день", styles["MetricValue"])],
        [_emoji_label("💧", "Вода", styles), _p(f"{plan.targets.water_l:.1f} л/день", styles["MetricValue"])],
        [_emoji_label("🍽️", "Блюд", styles), _p(f"{meal_count} за неделю", styles["MetricValue"])],
    ]
    ]
    table = Table(data, colWidths=[42 * mm, 42 * mm, 42 * mm, 42 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _day_section(
    plan: MealPlan,
    plan_date: date,
    day_index: int,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> list:
    story: list = [
        _day_header(day_index, plan_date, styles, doc_width),
        Spacer(1, 3 * mm),
    ]
    for meal in plan.meals:
        story.extend(_meal_card(meal, styles, doc_width))
        story.append(Spacer(1, 3 * mm))

    story.append(
        KeepTogether(
            [
                _section_title_with_icon("📊", "Итого за день", styles, doc_width),
                _daily_totals_table(plan, styles, doc_width),
            ]
        )
    )
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


def _meal_card(meal: Meal, styles: dict[str, ParagraphStyle], doc_width: float) -> list:
    image = _meal_image_flowables(meal, styles)
    flowables: list = [
        _meal_title_table(meal.name, styles, doc_width),
        Spacer(1, 1.5 * mm),
    ]
    if meal.batch:
        flowables.extend(_meal_detail_flowables(meal, styles, doc_width))
    else:
        flowables.append(_meal_ingredients_media_table(meal, image, styles, doc_width))
        flowables.extend(
            [
                _p("Как приготовить:", styles["Label"]),
                _p(meal.recipe, styles["Body"]),
            ]
        )
    flowables.extend(
        [
            Spacer(1, 0.5 * mm),
            _p(_meal_nutrition_text(meal), styles["ChipText"]),
        ]
    )
    return flowables


def _meal_title_table(title: str, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    table = Table([[_p(title, styles["MealTitle"])]], colWidths=[doc_width], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


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


def _daily_totals_table(plan: MealPlan, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    split_at = math.ceil(len(NUTRIENT_ORDER) / 2)
    left = _daily_totals_subtable(plan, NUTRIENT_ORDER[:split_at], styles, doc_width * 0.49)
    right = _daily_totals_subtable(plan, NUTRIENT_ORDER[split_at:], styles, doc_width * 0.49)
    table = Table([[left, right]], colWidths=[doc_width * 0.50, doc_width * 0.50], hAlign="LEFT")
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


def _daily_totals_subtable(
    plan: MealPlan,
    nutrient_keys: Sequence[str],
    styles: dict[str, ParagraphStyle],
    width: float,
) -> Table:
    rows = [
        [
            _p("●", styles["TableHeaderCenter"]),
            _p("Нутриент", styles["TableHeader"]),
            _p("Факт / цель", styles["TableHeader"]),
            _p("%", styles["TableHeader"]),
        ]
    ]
    row_styles: list[tuple] = []
    for key in nutrient_keys:
        value = plan.totals.get(key)
        target = plan.targets.targets.get(key)
        dot_style = styles[_coverage_dot_style(value, target)]
        row_index = len(rows)
        rows.append(
            [
                _p("●", dot_style),
                _p(NUTRIENT_LABELS[key], styles["TableCell"]),
                _p(f"{value:.1f} / {target:.1f}", styles["TableCell"]),
                _p(_coverage_percent(value, target), styles["TableCell"]),
            ]
        )
        row_styles.append(("TEXTCOLOR", (0, row_index), (0, row_index), _coverage_dot_color(value, target)))
    table = Table(
        rows,
        colWidths=[width * 0.08, width * 0.43, width * 0.34, width * 0.15],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), SOFT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
            + row_styles
        )
    )
    return table


def _shopping_section(plans: Sequence[MealPlan], styles: dict[str, ParagraphStyle], doc_width: float) -> list:
    story: list = [_emoji_title("🛒", "Список покупок на неделю", styles), Spacer(1, 4 * mm)]
    groups = build_week_shopping_groups(plans)
    if not groups:
        story.append(_p("Список пуст.", styles["Body"]))
    else:
        for group in groups:
            story.append(KeepTogether([_p(group.title, styles["ShoppingGroupTitle"])]))
            story.append(_shopping_items_table(group.items, styles, doc_width))
            story.append(Spacer(1, 2 * mm))

    disclaimers = tuple(
        dict.fromkeys(disclaimer for plan in plans for disclaimer in plan.safety.disclaimers)
    )
    if disclaimers:
        story.append(Spacer(1, 2 * mm))
        story.append(_p("Важно", styles["SectionTitle"]))
        for disclaimer in disclaimers:
            story.append(_p(disclaimer, styles["Body"]))

    story.append(Spacer(1, 2 * mm))
    story.append(
        _p(
            "Если вы пьете соки, газировку, сладкий чай, энергетики или другие калорийные напитки, "
            "учитывайте их в рационе: они могут заметно добавить калории и сахар.",
            styles["FinePrint"],
        )
    )
    story.append(_p(ORIENTATION_SENTENCE, styles["FinePrint"]))
    return story


def _shopping_items_table(items: Sequence, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    columns = 3 if len(items) >= 12 else 2
    row_count = max(1, math.ceil(len(items) / columns))
    rows: list[list] = []
    for row_index in range(row_count):
        row: list = []
        for column_index in range(columns):
            item_index = row_index + column_index * row_count
            if item_index < len(items):
                item = items[item_index]
                row.append(_p(f"• {item.food_name}: {format_display_grams(item.grams)} г", styles["ShoppingItem"]))
            else:
                row.append("")
        rows.append(row)

    table = Table(rows, colWidths=[doc_width / columns] * columns, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return table


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


def _coverage_dot_style(value: float, target: float) -> str:
    if target <= 0:
        return "DotRed"
    percent = value / target * 100
    if percent >= 100:
        return "DotGreen"
    if percent >= 50:
        return "DotYellow"
    return "DotRed"


def _coverage_dot_color(value: float, target: float):
    if target <= 0:
        return colors.HexColor("#C95B4A")
    percent = value / target * 100
    if percent >= 100:
        return colors.HexColor("#4F9E5D")
    if percent >= 50:
        return colors.HexColor("#D8A23A")
    return colors.HexColor("#C95B4A")


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
    emoji = Path("C:/Windows/Fonts/seguiemj.ttf")
    emoji_font = "Helvetica"
    if emoji.exists():
        with suppress(Exception):
            pdfmetrics.registerFont(TTFont("FoodBalanceEmoji", str(emoji)))
            emoji_font = "FoodBalanceEmoji"

    if regular is None:
        return "Helvetica", "Helvetica-Bold", emoji_font

    pdfmetrics.registerFont(TTFont("FoodBalanceRegular", str(regular)))
    if bold and bold != regular:
        pdfmetrics.registerFont(TTFont("FoodBalanceBold", str(bold)))
        return "FoodBalanceRegular", "FoodBalanceBold", emoji_font
    return "FoodBalanceRegular", "FoodBalanceRegular", emoji_font


def _build_styles(base_font: str, bold_font: str, emoji_font: str) -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    body = ParagraphStyle(
        "FoodBalanceBody",
        parent=sample["BodyText"],
        fontName=base_font,
        fontSize=13.4,
        leading=16.5,
        textColor=TEXT_COLOR,
        spaceAfter=1.4 * mm,
    )
    return {
        "Brand": ParagraphStyle(
            "FoodBalanceBrand",
            parent=body,
            fontName=bold_font,
            fontSize=17,
            leading=19.5,
            alignment=TA_CENTER,
            textColor=BRAND_GREEN,
        ),
        "Title": ParagraphStyle(
            "FoodBalanceTitle",
            parent=body,
            fontName=bold_font,
            fontSize=34,
            leading=38,
            alignment=TA_CENTER,
            textColor=TEXT_COLOR,
            spaceAfter=2 * mm,
        ),
        "TitleSmall": ParagraphStyle(
            "FoodBalanceTitleSmall",
            parent=body,
            fontName=bold_font,
            fontSize=27,
            leading=32,
            textColor=TEXT_COLOR,
        ),
        "Subtitle": ParagraphStyle(
            "FoodBalanceSubtitle",
            parent=body,
            fontSize=16,
            leading=19,
            alignment=TA_CENTER,
            textColor=MUTED_COLOR,
        ),
        "SectionTitle": ParagraphStyle(
            "FoodBalanceSectionTitle",
            parent=body,
            fontName=bold_font,
            fontSize=18,
            leading=21.5,
            textColor=BRAND_GREEN,
            spaceBefore=2 * mm,
            spaceAfter=2 * mm,
        ),
        "SectionEmoji": ParagraphStyle(
            "FoodBalanceSectionEmoji",
            parent=body,
            fontName=emoji_font,
            fontSize=18,
            leading=21.5,
            textColor=BRAND_GREEN,
            alignment=TA_CENTER,
        ),
        "InlineEmoji": ParagraphStyle(
            "FoodBalanceInlineEmoji",
            parent=body,
            fontName=emoji_font,
            fontSize=13.4,
            leading=16.5,
            textColor=BRAND_GREEN,
            alignment=TA_CENTER,
        ),
        "MetricEmoji": ParagraphStyle(
            "FoodBalanceMetricEmoji",
            parent=body,
            fontName=emoji_font,
            fontSize=12,
            leading=14,
            textColor=BRAND_GREEN,
        ),
        "DayTitle": ParagraphStyle(
            "FoodBalanceDayTitle",
            parent=body,
            fontName=bold_font,
            fontSize=23,
            leading=26,
            textColor=colors.white,
        ),
        "DayDate": ParagraphStyle(
            "FoodBalanceDayDate",
            parent=body,
            fontName=bold_font,
            fontSize=17,
            leading=20,
            alignment=TA_LEFT,
            textColor=colors.white,
        ),
        "MealTitle": ParagraphStyle(
            "FoodBalanceMealTitle",
            parent=body,
            fontName=bold_font,
            fontSize=18,
            leading=21.5,
            textColor=TEXT_COLOR,
            spaceAfter=1 * mm,
        ),
        "Body": body,
        "Label": ParagraphStyle(
            "FoodBalanceLabel",
            parent=body,
            fontName=bold_font,
            fontSize=13.4,
            leading=16.5,
            textColor=TEXT_COLOR,
            spaceAfter=0.5 * mm,
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
            fontSize=12.4,
            leading=15,
            textColor=BRAND_GREEN,
            backColor=PALE_GREEN,
            borderPadding=(3, 4, 3),
        ),
        "MetricLabel": ParagraphStyle(
            "FoodBalanceMetricLabel",
            parent=body,
            fontSize=10.2,
            leading=12,
            textColor=MUTED_COLOR,
        ),
        "MetricValue": ParagraphStyle(
            "FoodBalanceMetricValue",
            parent=body,
            fontName=bold_font,
            fontSize=13.5,
            leading=16.2,
            textColor=TEXT_COLOR,
        ),
        "TableHeaderCenter": ParagraphStyle(
            "FoodBalanceTableHeaderCenter",
            parent=body,
            fontName=bold_font,
            fontSize=11.2,
            leading=13.5,
            alignment=TA_CENTER,
            textColor=TEXT_COLOR,
        ),
        "TableHeader": ParagraphStyle(
            "FoodBalanceTableHeader",
            parent=body,
            fontName=bold_font,
            fontSize=11.2,
            leading=13.5,
            textColor=TEXT_COLOR,
        ),
        "TableCell": ParagraphStyle(
            "FoodBalanceTableCell",
            parent=body,
            fontSize=10.9,
            leading=13.2,
            textColor=TEXT_COLOR,
        ),
        "ShoppingGroupTitle": ParagraphStyle(
            "FoodBalanceShoppingGroupTitle",
            parent=body,
            fontName=bold_font,
            fontSize=16,
            leading=19,
            textColor=BRAND_GREEN,
            spaceBefore=1 * mm,
            spaceAfter=0.5 * mm,
        ),
        "ShoppingItem": ParagraphStyle(
            "FoodBalanceShoppingItem",
            parent=body,
            fontSize=12.6,
            leading=15.2,
            textColor=TEXT_COLOR,
            spaceAfter=0,
        ),
        "FinePrint": ParagraphStyle(
            "FoodBalanceFinePrint",
            parent=body,
            fontSize=11.4,
            leading=13.8,
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
    cleaned = _soft_wrap_long_tokens(cleaned)
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


def _soft_wrap_long_tokens(text: str) -> str:
    def wrap(match: re.Match[str]) -> str:
        token = match.group(0)
        return " ".join(
            token[index : index + LONG_TOKEN_MAX_CHARS]
            for index in range(0, len(token), LONG_TOKEN_MAX_CHARS)
        )

    return LONG_TOKEN_RE.sub(wrap, text)


def _footer(base_font: str):
    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(base_font, 8)
        canvas.setFillColor(MUTED_COLOR)
        canvas.drawString(doc.leftMargin, 8 * mm, "FoodBalance")
        canvas.drawRightString(PAGE_WIDTH - doc.rightMargin, 8 * mm, f"Страница {doc.page}")
        canvas.restoreState()

    return draw
