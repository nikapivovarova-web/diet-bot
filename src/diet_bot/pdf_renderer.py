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
PDF_LOGO_PATH = DATA_DIR / "foodbalance_pdf_logo.png"
PDF_QR_PATH = DATA_DIR / "foodbalance_pdf_qr.png"
PAGE_SIZE = A4
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE
PDF_MARGIN = 12 * mm
BRAND_GREEN = colors.HexColor("#2F6B48")
DEEP_GREEN = colors.HexColor("#1F3A2A")
SOFT_GREEN = colors.HexColor("#EAF4EA")
PALE_GREEN = colors.HexColor("#F6FAF5")
PAGE_BACKGROUND = colors.HexColor("#FBFAF4")
CARD_BACKGROUND = colors.HexColor("#FFFFFF")
TEXT_COLOR = colors.HexColor("#243126")
MUTED_COLOR = colors.HexColor("#66736A")
LINE_COLOR = colors.HexColor("#D8E2D3")
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
        topMargin=12 * mm,
        bottomMargin=13 * mm,
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
    story.append(PageBreak())

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
        Spacer(1, 8 * mm),
        _cover_header(date_range, styles, doc_width),
        Spacer(1, 11 * mm),
        _summary_table(first_plan, meal_count, styles),
        Spacer(1, 6 * mm),
        _section_title_with_icon("🧮", "Ваш расчет", styles, doc_width),
    ]

    for line in format_calculation_summary(first_plan.targets, first_plan.safety).splitlines():
        if line.strip():
            story.append(_calculation_line(line, styles, doc_width))
        else:
            story.append(Spacer(1, 2 * mm))
    qr_block = _cover_qr_block(styles, doc_width)
    if qr_block is not None:
        story.append(Spacer(1, 7 * mm))
        story.append(qr_block)
    return story


def _cover_header(date_range: str, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    logo = _asset_image(PDF_LOGO_PATH, 30 * mm, 30 * mm) or ""
    text = [
        _p("Food Balance", styles["CoverBrandLeft"]),
        _p("Рацион на неделю", styles["CoverTitleLeft"]),
        _p(date_range, styles["CoverSubtitleLeft"]),
    ]
    table = Table([[logo, text]], colWidths=[45 * mm, doc_width - 45 * mm], hAlign="LEFT")
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


def _cover_qr_block(styles: dict[str, ParagraphStyle], doc_width: float) -> Table | None:
    qr = _asset_image(PDF_QR_PATH, 34 * mm, 34 * mm)
    if qr is None:
        return None
    table = Table(
        [[qr], [_p("@FOODBALANCERU_BOT", styles["QrCaption"])]],
        colWidths=[doc_width],
        hAlign="CENTER",
    )
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _asset_image(path: Path, max_width: float, max_height: float) -> Image | None:
    if not path.exists():
        return None
    try:
        reader = ImageReader(str(path))
        width, height = reader.getSize()
        scale = min(max_width / width, max_height / height)
        return Image(str(path), width=width * scale, height=height * scale)
    except Exception:
        return None


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
    flowables: list = [
        _meal_header_table(meal, styles, doc_width),
        Spacer(1, 3 * mm),
    ]
    if meal.batch and meal.batch.is_carryover:
        flowables.append(
            _soft_note(
                f"Порция сегодня: {_counted(meal.batch.serving_units, meal.batch.unit_forms)} из приготовленной партии.",
                styles,
                doc_width,
            )
        )
        flowables.extend(_ingredient_section("Ингредиенты порции", meal.portions, styles, doc_width))
        flowables.extend(
            _recipe_section(
                f"Съешьте {_counted(meal.batch.serving_units, meal.batch.unit_forms)} из приготовленной партии. "
                "В расчет дня входит только сегодняшняя порция.",
                styles,
                doc_width,
                meal,
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
        flowables.extend(_recipe_section(format_batch_recipe_text(meal.recipe, meal.batch), styles, doc_width, meal))
        flowables.append(_p("В расчет дня входит только сегодняшняя порция.", styles["FinePrint"]))
    else:
        flowables.extend(_ingredient_section("Ингредиенты", meal.portions, styles, doc_width))
        flowables.extend(_recipe_section(meal.recipe, styles, doc_width, meal))
    return flowables


def _meal_header_table(meal: Meal, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    meal_type = _meal_type(meal)
    recipe_title = _meal_recipe_title(meal)
    badges = _meal_nutrition_badges(meal, styles, doc_width - 12 * mm)
    table = Table(
        [
            [_meal_type_pill(meal_type, styles), _p(recipe_title, styles["MealTitle"])],
            [badges, ""],
        ],
        colWidths=[38 * mm, doc_width - 38 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT_GREEN),
                ("SPAN", (0, 1), (-1, 1)),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, 0), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("TOPPADDING", (0, 1), (-1, 1), 5),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _meal_type_pill(meal_type: str, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table([[_p(meal_type, styles["MealType"])]], colWidths=[31 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BRAND_GREEN),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _meal_nutrition_badges(meal: Meal, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    nutrients = meal.nutrients
    badges = [
        ("Калории", f"{nutrients.get('energy_kcal'):.0f} ккал"),
        ("Белки", f"{nutrients.get('protein_g'):.0f} г"),
        ("Жиры", f"{nutrients.get('fat_g'):.0f} г"),
        ("Углеводы", f"{nutrients.get('carbohydrate_g'):.0f} г"),
    ]
    gap = 3 * mm
    badge_width = (doc_width - gap * 3) / 4
    badge_cells: list = []
    badge_widths: list[float] = []
    for index, (label, value) in enumerate(badges):
        if index:
            badge_cells.append("")
            badge_widths.append(gap)
        badge_cells.append(_nutrition_badge(label, value, styles, badge_width))
        badge_widths.append(badge_width)
    table = Table([badge_cells], colWidths=badge_widths, hAlign="LEFT")
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


def _nutrition_badge(label: str, value: str, styles: dict[str, ParagraphStyle], width: float) -> Table:
    table = Table(
        [[_p(label, styles["BadgeLabel"])], [_p(value, styles["BadgeValue"])]],
        colWidths=[width],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
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
    rows = [
        [
            _p("Ингредиент", styles["TableHeaderWhiteCenter"]),
            _p("Кол-во", styles["TableHeaderWhiteCenter"]),
            _p("Примерная мера", styles["TableHeaderWhiteCenter"]),
        ]
    ]
    if not portions:
        rows.append([_p("Нет данных по ингредиентам", styles["TableCell"]), "", ""])
    else:
        for portion in portions:
            product, amount, measure = _ingredient_cells(portion)
            rows.append(
                [
                    _p(product, styles["TableCellCenter"]),
                    _p(amount, styles["TableCellCenter"]),
                    _p(measure or "-", styles["TableCellCenter"]),
                ]
            )

    table = Table(rows, colWidths=[doc_width * 0.46, doc_width * 0.22, doc_width * 0.32], repeatRows=1)
    row_styles = [
        ("BACKGROUND", (0, row_index), (-1, row_index), PALE_GREEN if row_index % 2 else CARD_BACKGROUND)
        for row_index in range(1, len(rows))
    ]
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
            + row_styles
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


def _recipe_section(
    recipe: str,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
    meal: Meal | None = None,
) -> list:
    return [
        _p("Как приготовить", styles["Label"]),
        *_recipe_media_flowables(recipe, meal, styles, doc_width),
    ]


def _recipe_media_flowables(
    recipe: str,
    meal: Meal | None,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> list:
    steps = _recipe_steps(recipe)
    image = _meal_image_flowables(meal, styles) if meal is not None else None
    if image and _recipe_fits_beside_image(steps):
        return [_recipe_media_table(steps, image, styles, doc_width)]
    return [_recipe_steps_table(steps, styles, doc_width)]


def _recipe_media_table(
    steps: Sequence[str],
    image: list,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
) -> Table:
    image_width = doc_width * 0.34
    text_width = doc_width - image_width - 8 * mm
    table = Table(
        [[_recipe_steps_table(steps, styles, text_width), image]],
        colWidths=[text_width, image_width],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _recipe_steps_table(steps: Sequence[str], styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
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
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _recipe_steps(recipe: str) -> tuple[str, ...]:
    text = _clean_text(recipe or "")
    if not text:
        return ("Инструкция приготовления не указана.",)

    if "\n" in text:
        chunks = [chunk.strip(" -0123456789.()") for chunk in text.splitlines()]
        chunks = [chunk for chunk in chunks if chunk]
        if chunks:
            return tuple(chunks)

    normalized = re.sub(r"\s+", " ", text).strip()
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


def _recipe_fits_beside_image(steps: Sequence[str]) -> bool:
    return len(steps) <= 7 and sum(len(step) for step in steps) <= 1100


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
    title = _emoji_title("🛒", "Список продуктов на неделю", styles)
    story: list = [title, Spacer(1, 7 * mm)]
    groups = build_week_shopping_groups(plans)
    if not groups:
        story.append(_p("Список пуст.", styles["Body"]))
    else:
        first_page_available_height = _shopping_first_page_available_height(title, doc_width)
        for page_index, page_groups in enumerate(_shopping_page_groups(groups, styles, doc_width, first_page_available_height)):
            if page_index:
                story.append(PageBreak())
            story.append(_shopping_columns(page_groups, styles, doc_width))

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


def _shopping_first_page_available_height(title, doc_width: float) -> float:
    frame_height = _shopping_frame_height()
    _, title_height = title.wrap(doc_width, frame_height)
    return frame_height - title_height - 7 * mm


def _shopping_page_groups(
    groups: Sequence,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
    first_page_available_height: float,
) -> list[list]:
    pages: list[list] = []
    start = 0
    frame_height = _shopping_frame_height()
    while start < len(groups):
        available_height = first_page_available_height if not pages else frame_height
        end = _shopping_page_end(groups, start, styles, doc_width, available_height)
        pages.append(list(groups[start:end]))
        start = end

    if len(pages) > 2:
        balanced_pages = _shopping_balanced_two_pages(
            groups,
            styles,
            doc_width,
            first_page_available_height,
            frame_height,
        )
        if balanced_pages:
            return balanced_pages
    return pages


def _shopping_page_end(
    groups: Sequence,
    start: int,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
    available_height: float,
) -> int:
    best_end = start + 1
    for end in range(start + 1, len(groups) + 1):
        table = _shopping_columns(groups[start:end], styles, doc_width)
        _, height = table.wrap(_shopping_layout_width(doc_width), available_height)
        if height <= available_height - 2:
            best_end = end
        else:
            break
    return best_end


def _shopping_frame_height() -> float:
    return PAGE_HEIGHT - 12 * mm - 13 * mm - 12


def _shopping_layout_width(doc_width: float) -> float:
    return max(1, doc_width - 12)


def _shopping_columns(groups: Sequence, styles: dict[str, ParagraphStyle], doc_width: float) -> Table:
    card_gap = 7 * mm
    layout_width = _shopping_layout_width(doc_width)
    col_width = (layout_width - card_gap) / 2
    left_groups, right_groups = _split_shopping_columns(groups, styles, col_width)

    left = _shopping_column_flowables(left_groups, styles, col_width)
    right = _shopping_column_flowables(right_groups, styles, col_width)
    table = Table([[left, "", right]], colWidths=[col_width, card_gap, col_width], hAlign="LEFT")
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


def _split_shopping_columns(
    groups: Sequence,
    styles: dict[str, ParagraphStyle],
    col_width: float,
) -> tuple[list, list]:
    group_list = list(groups)
    if len(group_list) <= 1:
        return group_list, []

    heights = [_shopping_group_height(group, styles, col_width) for group in group_list]
    _, left_indexes, right_indexes = _best_shopping_column_indexes(range(len(group_list)), heights)
    return (
        [group_list[index] for index in left_indexes],
        [group_list[index] for index in right_indexes],
    )


def _shopping_balanced_two_pages(
    groups: Sequence,
    styles: dict[str, ParagraphStyle],
    doc_width: float,
    first_page_available_height: float,
    frame_height: float,
) -> list[list] | None:
    group_list = list(groups)
    if len(group_list) <= 2 or len(group_list) > 16:
        return None

    layout_width = _shopping_layout_width(doc_width)
    col_width = (layout_width - 7 * mm) / 2
    heights = [_shopping_group_height(group, styles, col_width) for group in group_list]
    full_mask = (1 << len(group_list)) - 1
    height_cache: dict[int, float] = {}

    def page_height(mask: int) -> float:
        if mask not in height_cache:
            indexes = [index for index in range(len(group_list)) if mask & (1 << index)]
            height_cache[mask] = _best_shopping_column_indexes(indexes, heights)[0]
        return height_cache[mask]

    best_score: tuple[int, float, float, int] | None = None
    best_pages: list[list] | None = None

    for mask in range(1, full_mask):
        if not mask & 1:
            continue
        other_mask = full_mask ^ mask
        first_height = page_height(mask)
        if first_height > first_page_available_height - 2:
            continue
        second_height = page_height(other_mask)
        if second_height > frame_height - 2:
            continue

        prefix_count = _shopping_prefix_count(mask, len(group_list))
        first_count = sum(1 for index in range(len(group_list)) if mask & (1 << index))
        second_count = len(group_list) - first_count
        score = (
            -prefix_count,
            max(first_height / first_page_available_height, second_height / frame_height),
            abs(first_height - second_height),
            abs(first_count - second_count),
        )
        if best_score is None or score < best_score:
            best_score = score
            best_pages = [
                [
                    group_list[index]
                    for index in range(len(group_list))
                    if mask & (1 << index)
                ],
                [
                    group_list[index]
                    for index in range(len(group_list))
                    if other_mask & (1 << index)
                ],
            ]

    return best_pages


def _shopping_prefix_count(mask: int, group_count: int) -> int:
    prefix_count = 0
    for index in range(group_count):
        if not mask & (1 << index):
            break
        prefix_count += 1
    return prefix_count


def _best_shopping_column_indexes(
    indexes: Sequence[int],
    group_heights: Sequence[float],
) -> tuple[float, list[int], list[int]]:
    index_list = list(indexes)
    if not index_list:
        return 1, [], []
    if len(index_list) == 1:
        return group_heights[index_list[0]], index_list, []

    best_score: tuple[float, float, int] | None = None
    best_columns: tuple[list[int], list[int]] = (index_list, [])

    for mask in range(1, 1 << len(index_list)):
        if not mask & 1:
            continue
        left_indexes = [
            index_list[index]
            for index in range(len(index_list))
            if mask & (1 << index)
        ]
        if len(left_indexes) == len(index_list):
            continue
        right_indexes = [
            index_list[index]
            for index in range(len(index_list))
            if not mask & (1 << index)
        ]
        left_height = _shopping_column_height(group_heights, left_indexes)
        right_height = _shopping_column_height(group_heights, right_indexes)
        score = (
            max(left_height, right_height),
            abs(left_height - right_height),
            abs(len(left_indexes) - len(right_indexes)),
        )
        if best_score is None or score < best_score:
            best_score = score
            best_columns = (left_indexes, right_indexes)

    return (
        best_score[0] if best_score else _shopping_column_height(group_heights, index_list),
        best_columns[0],
        best_columns[1],
    )


def _shopping_group_height(group, styles: dict[str, ParagraphStyle], col_width: float) -> float:
    _, height = _shopping_group_card(group, styles, col_width).wrap(col_width, PAGE_HEIGHT)
    return height


def _shopping_column_height(group_heights: Sequence[float], indexes: Sequence[int]) -> float:
    if not indexes:
        return 1
    return sum(group_heights[index] for index in indexes) + (len(indexes) - 1) * 4 * mm


def _shopping_column_flowables(groups: Sequence, styles: dict[str, ParagraphStyle], col_width: float) -> list:
    flowables: list = []
    for index, group in enumerate(groups):
        if index:
            flowables.append(Spacer(1, 4 * mm))
        flowables.append(_shopping_group_card(group, styles, col_width))
    return flowables or [Spacer(1, 1)]


def _shopping_group_card(group, styles: dict[str, ParagraphStyle], col_width: float) -> Table:
    items = [
        _p(f"• {item.food_name}: {format_display_grams(item.grams)} г", styles["ShoppingItem"])
        for item in group.items
    ]
    table = Table(
        [[_p(group.title, styles["ShoppingGroupTitle"])], [items]],
        colWidths=[col_width],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


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
        "CoverBrandLeft": ParagraphStyle(
            "FoodBalanceCoverBrandLeft",
            parent=body,
            fontName=bold_font,
            fontSize=18,
            leading=21,
            textColor=BRAND_GREEN,
        ),
        "CoverTitleLeft": ParagraphStyle(
            "FoodBalanceCoverTitleLeft",
            parent=body,
            fontName=bold_font,
            fontSize=31,
            leading=35,
            textColor=DEEP_GREEN,
            spaceAfter=1 * mm,
        ),
        "CoverSubtitleLeft": ParagraphStyle(
            "FoodBalanceCoverSubtitleLeft",
            parent=body,
            fontSize=15,
            leading=18,
            textColor=MUTED_COLOR,
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
        "TitleSmall": ParagraphStyle(
            "FoodBalanceTitleSmall",
            parent=body,
            fontName=bold_font,
            fontSize=22,
            leading=26,
            textColor=TEXT_COLOR,
        ),
        "Subtitle": ParagraphStyle(
            "FoodBalanceSubtitle",
            parent=body,
            fontSize=15,
            leading=18,
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
            fontName=emoji_font,
            fontSize=14,
            leading=17,
            textColor=BRAND_GREEN,
            alignment=TA_CENTER,
        ),
        "InlineEmoji": ParagraphStyle(
            "FoodBalanceInlineEmoji",
            parent=body,
            fontName=emoji_font,
            fontSize=10.6,
            leading=14.2,
            textColor=BRAND_GREEN,
            alignment=TA_CENTER,
        ),
        "MetricEmoji": ParagraphStyle(
            "FoodBalanceMetricEmoji",
            parent=body,
            fontName=emoji_font,
            fontSize=13,
            leading=15,
            textColor=BRAND_GREEN,
            alignment=TA_CENTER,
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
            fontSize=14.3,
            leading=17.5,
            textColor=BRAND_GREEN,
        ),
        "Body": body,
        "Label": ParagraphStyle(
            "FoodBalanceLabel",
            parent=body,
            fontName=bold_font,
            fontSize=12,
            leading=15,
            textColor=BRAND_GREEN,
            spaceAfter=1 * mm,
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
        "BadgeLabel": ParagraphStyle(
            "FoodBalanceBadgeLabel",
            parent=body,
            fontSize=8.5,
            leading=10,
            textColor=MUTED_COLOR,
            alignment=TA_CENTER,
        ),
        "BadgeValue": ParagraphStyle(
            "FoodBalanceBadgeValue",
            parent=body,
            fontName=bold_font,
            fontSize=11.2,
            leading=13.5,
            textColor=BRAND_GREEN,
            alignment=TA_CENTER,
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
        "MetricLabel": ParagraphStyle(
            "FoodBalanceMetricLabel",
            parent=body,
            fontName=bold_font,
            fontSize=9.4,
            leading=11.5,
            textColor=MUTED_COLOR,
            alignment=TA_CENTER,
        ),
        "MetricValue": ParagraphStyle(
            "FoodBalanceMetricValue",
            parent=body,
            fontName=bold_font,
            fontSize=12.8,
            leading=16,
            textColor=DEEP_GREEN,
            alignment=TA_CENTER,
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
        "TableHeaderWhiteCenter": ParagraphStyle(
            "FoodBalanceTableHeaderWhiteCenter",
            parent=body,
            fontName=bold_font,
            fontSize=9.5,
            leading=11.5,
            alignment=TA_CENTER,
            textColor=colors.white,
        ),
        "TableCell": ParagraphStyle(
            "FoodBalanceTableCell",
            parent=body,
            fontSize=9.4,
            leading=12,
            textColor=TEXT_COLOR,
        ),
        "TableCellCenter": ParagraphStyle(
            "FoodBalanceTableCellCenter",
            parent=body,
            fontSize=9.4,
            leading=12,
            alignment=TA_CENTER,
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
        "QrCaption": ParagraphStyle(
            "FoodBalanceQrCaption",
            parent=body,
            fontName=bold_font,
            fontSize=11,
            leading=13,
            alignment=TA_CENTER,
            textColor=BRAND_GREEN,
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
        canvas.setFillColor(PAGE_BACKGROUND)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
        canvas.setFont(base_font, 8)
        canvas.setFillColor(MUTED_COLOR)
        canvas.drawString(doc.leftMargin, 8 * mm, "FoodBalance")
        canvas.drawRightString(PAGE_WIDTH - doc.rightMargin, 8 * mm, f"Страница {doc.page}")
        canvas.restoreState()

    return draw
