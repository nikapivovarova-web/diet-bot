from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET


SHEET_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
RECIPES_SHEET_NAME = "Рецепты"
EXCEL_400_FIRST_DATA_ROW = 5


@dataclass(frozen=True)
class NormalizedRecipe:
    candidate_id: str
    title_ru: str
    meal_type: str
    duplicate_risk: str
    structured_ingredients: str
    raw_ingredient_text: str = ""
    servings: str = ""
    nutrition: str = ""
    instructions: str = ""
    time: str = ""
    source: str = ""
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DuplicateRisk:
    candidate_id: str
    duplicate_risk: str
    duplicate_reason: str
    possible_duplicate_candidate_ids: str


@dataclass(frozen=True)
class LoadedInput:
    recipes: list[NormalizedRecipe]
    duplicate_risks: dict[str, DuplicateRisk]
    source_counts: dict[str, int]


def load_photo_prep_317(input_dir: Path) -> LoadedInput:
    input_dir = Path(input_dir)
    photo_ready_path = input_dir / "photo_ready.csv"
    if not photo_ready_path.exists():
        raise FileNotFoundError(f"missing required input file: {photo_ready_path}")

    photo_rows = _read_csv(photo_ready_path)
    recipes = [_normalize_photo_ready_row(row) for row in photo_rows]
    duplicate_risks = _load_duplicate_risks(input_dir / "duplicate_risk.csv")

    return LoadedInput(
        recipes=recipes,
        duplicate_risks=duplicate_risks,
        source_counts={
            "photo_ready": len(recipes),
            "duplicate_risk": len(duplicate_risks),
        },
    )


def load_excel_400_workbook(workbook_path: Path) -> LoadedInput:
    workbook_path = Path(workbook_path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"missing required input file: {workbook_path}")
    if workbook_path.is_dir():
        raise IsADirectoryError(f"expected .xlsx workbook file, got directory: {workbook_path}")

    sheet_rows = _read_xlsx_sheet_rows(workbook_path, RECIPES_SHEET_NAME)
    recipes: list[NormalizedRecipe] = []
    non_empty_rows = 0
    for row_index in sorted(sheet_rows):
        if row_index < EXCEL_400_FIRST_DATA_ROW:
            continue
        row = sheet_rows[row_index]
        recipe_no = _pick(row, "A")
        title = _pick(row, "C")
        if not recipe_no and not title:
            continue
        non_empty_rows += 1
        if not recipe_no:
            raise ValueError(f"workbook row {row_index} is missing recipe number")
        if not title:
            raise ValueError(f"workbook row {row_index} is missing recipe title")

        recipes.append(
            NormalizedRecipe(
                candidate_id=_excel_candidate_id(recipe_no),
                title_ru=title,
                meal_type=_pick(row, "B"),
                duplicate_risk="",
                structured_ingredients="",
                raw_ingredient_text=_pick(row, "F"),
                servings=_normalize_excel_servings(_pick(row, "D")),
                nutrition="",
                instructions=_pick(row, "G"),
                time=_pick(row, "E"),
                source=_pick(row, "H"),
                raw={
                    "workbook_path": str(workbook_path),
                    "workbook_row": str(row_index),
                    "recipe_no": recipe_no,
                    "category": _pick(row, "B"),
                    "title": title,
                    "portions": _pick(row, "D"),
                    "time": _pick(row, "E"),
                    "ingredients": _pick(row, "F"),
                    "instructions": _pick(row, "G"),
                    "source": _pick(row, "H"),
                },
            )
        )

    return LoadedInput(
        recipes=recipes,
        duplicate_risks={},
        source_counts={
            "excel_400_workbook": len(recipes),
            "workbook_non_empty_rows": non_empty_rows,
        },
    )


def load_second_pass_suitable_csv(csv_path: Path) -> LoadedInput:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"missing required input file: {csv_path}")
    if csv_path.is_dir():
        raise IsADirectoryError(f"expected second-pass CSV file, got directory: {csv_path}")

    rows = _read_csv(csv_path)
    recipes: list[NormalizedRecipe] = []
    duplicate_risks: dict[str, DuplicateRisk] = {}
    for row in rows:
        candidate_id = _pick(row, "candidate_id", "id", "recipe_id")
        if not candidate_id:
            raise ValueError("second-pass suitable CSV row is missing candidate_id")

        title = _pick(row, "title", "title_ru", "name")
        if not title:
            raise ValueError(f"second-pass suitable CSV row {candidate_id} is missing title")

        existing_match = _pick(row, "existing_catalog_match", "existing_catalog_match_id")
        existing_match_id = _pick(row, "existing_catalog_match_id")
        duplicate_risk = _pick(row, "duplicate_risk")
        if existing_match:
            duplicate_risks[candidate_id] = DuplicateRisk(
                candidate_id=candidate_id,
                duplicate_risk=duplicate_risk or "catalog_match",
                duplicate_reason=f"existing_catalog_match:{existing_match_id or existing_match}",
                possible_duplicate_candidate_ids=existing_match_id,
            )

        recipes.append(
            NormalizedRecipe(
                candidate_id=candidate_id,
                title_ru=title,
                meal_type=_pick(row, "likely_meal_slot", "meal_type", "category"),
                duplicate_risk=duplicate_risk,
                structured_ingredients="",
                raw_ingredient_text=_pick(row, "cleaned_ingredients", "ingredients"),
                servings="",
                nutrition="",
                instructions=_pick(row, "cleaned_instructions", "instructions"),
                time="",
                source=_second_pass_source(row),
                raw=row,
            )
        )

    return LoadedInput(
        recipes=recipes,
        duplicate_risks=duplicate_risks,
        source_counts={
            "second_pass_suitable_csv": len(recipes),
            "second_pass_existing_catalog_matches": len(duplicate_risks),
        },
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def _normalize_photo_ready_row(row: dict[str, str]) -> NormalizedRecipe:
    candidate_id = _pick(row, "candidate_id", "id", "recipe_id")
    if not candidate_id:
        raise ValueError("photo_ready.csv row is missing candidate_id")

    return NormalizedRecipe(
        candidate_id=candidate_id,
        title_ru=_pick(row, "title_ru", "title", "name"),
        meal_type=_pick(row, "meal_type_guess", "meal_type", "category"),
        duplicate_risk=_pick(row, "duplicate_risk"),
        structured_ingredients=_pick(
            row,
            "structured_ingredients",
            "ingredients_json",
            "ingredients_structured_json",
        ),
        raw_ingredient_text=_pick(
            row,
            "ingredient_text",
            "ingredients_text",
            "raw_ingredient_text",
            "raw_ingredients",
        ),
        servings=_pick(row, "servings", "servings_count", "default_servings"),
        nutrition=_pick(row, "nutrition", "nutrition_json", "nutrition_per_serving_json"),
        instructions=_pick(row, "instructions", "directions", "method"),
        time=_pick(row, "time", "total_time", "cook_time", "prep_time"),
        source=_pick(row, "source_url", "source", "url"),
        raw=row,
    )


def _load_duplicate_risks(path: Path) -> dict[str, DuplicateRisk]:
    if not path.exists():
        return {}

    risks: dict[str, DuplicateRisk] = {}
    for row in _read_csv(path):
        candidate_id = _pick(row, "candidate_id", "id", "recipe_id")
        if not candidate_id:
            continue
        risks[candidate_id] = DuplicateRisk(
            candidate_id=candidate_id,
            duplicate_risk=_pick(row, "duplicate_risk"),
            duplicate_reason=_pick(row, "duplicate_reason"),
            possible_duplicate_candidate_ids=_pick(row, "possible_duplicate_candidate_ids"),
        )
    return risks


def _pick(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key, "")
        if value:
            return value.strip()
    return ""


def _second_pass_source(row: dict[str, str]) -> str:
    page = _pick(row, "source_page")
    source_row = _pick(row, "source_row")
    if page or source_row:
        return f"source_page={page};source_row={source_row}"
    return _pick(row, "source", "source_url", "url")


def _read_xlsx_sheet_rows(workbook_path: Path, sheet_name: str) -> dict[int, dict[str, str]]:
    with ZipFile(workbook_path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_path = _sheet_path_for_name(archive, sheet_name)
        root = ET.fromstring(archive.read(sheet_path))

    rows: dict[int, dict[str, str]] = {}
    ns = {"main": SHEET_MAIN_NS}
    for cell in root.findall(".//main:sheetData/main:row/main:c", ns):
        ref = cell.attrib.get("r", "")
        column, row_index = _split_cell_reference(ref)
        if not column or row_index <= 0:
            continue
        value = _cell_value(cell, shared_strings)
        if value:
            rows.setdefault(row_index, {})[column] = value
    return rows


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    ns = {"main": SHEET_MAIN_NS}
    strings: list[str] = []
    for item in root.findall("main:si", ns):
        parts = [node.text or "" for node in item.findall(".//main:t", ns)]
        strings.append("".join(parts))
    return strings


def _sheet_path_for_name(archive: ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationships = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall(f"{{{REL_NS}}}Relationship")
        if "Id" in rel.attrib and "Target" in rel.attrib
    }

    for sheet in workbook.findall(f".//{{{SHEET_MAIN_NS}}}sheet"):
        if sheet.attrib.get("name") != sheet_name:
            continue
        rel_id = sheet.attrib.get(f"{{{OFFICE_REL_NS}}}id")
        target = relationships.get(rel_id or "")
        if not target:
            break
        return _normalize_xlsx_part("xl", target)
    raise ValueError(f"workbook is missing sheet: {sheet_name}")


def _normalize_xlsx_part(base_dir: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    parts: list[str] = []
    for piece in f"{base_dir}/{target}".split("/"):
        if piece in {"", "."}:
            continue
        if piece == "..":
            if parts:
                parts.pop()
            continue
        parts.append(piece)
    return "/".join(parts)


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        parts = [node.text or "" for node in cell.findall(f".//{{{SHEET_MAIN_NS}}}t")]
        return _cell_text("".join(parts))

    value_node = cell.find(f"{{{SHEET_MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text
    if cell_type == "s":
        try:
            return _cell_text(shared_strings[int(value)])
        except (IndexError, ValueError):
            return ""
    return _cell_text(value)


def _cell_text(value: object) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def _split_cell_reference(ref: str) -> tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", ref or "")
    if not match:
        return "", 0
    return match.group(1), int(match.group(2))


def _excel_candidate_id(recipe_no: str) -> str:
    normalized = _cell_text(recipe_no)
    if re.fullmatch(r"\d+", normalized):
        return f"recipe_{int(normalized)}"
    safe = re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")
    return f"recipe_{safe or normalized}"


def _normalize_excel_servings(value: str) -> str:
    match = re.search(r"\d+(?:[.,]\d+)?", value or "")
    if not match:
        return ""
    number = match.group(0).replace(",", ".")
    if re.fullmatch(r"\d+\.0", number):
        return number[:-2]
    return number
