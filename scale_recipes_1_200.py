from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


INPUT = Path(r"C:\Users\adck8\Desktop\bolshaya_tablica_receptov_s_foto_ready_for_sale.xlsx")
OUTPUT_DIR = Path(r"C:\Users\adck8\Documents\New project 2\outputs\recipes_1_200")
OUTPUT = OUTPUT_DIR / "bolshaya_tablica_receptov_s_foto_1_200_one_portion.xlsx"
REPORT = OUTPUT_DIR / "conversion_report.json"

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_XML = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("", NS_MAIN)


def q(tag: str) -> str:
    return f"{{{NS_MAIN}}}{tag}"


def get_shared_text(si: ET.Element) -> str:
    parts = []
    for t in si.iter(q("t")):
        parts.append(t.text or "")
    return "".join(parts)


def make_si(text: str) -> ET.Element:
    si = ET.Element(q("si"))
    t = ET.SubElement(si, q("t"))
    if text.startswith((" ", "\n")) or text.endswith((" ", "\n")) or "\n" in text:
        t.set(f"{{{NS_XML}}}space", "preserve")
    t.text = text
    return si


def cell_ref(col: str, row: int) -> str:
    return f"{col}{row}"


def cell_text(cell: ET.Element | None, shared: list[str]) -> str:
    if cell is None:
        return ""
    value = cell.find(q("v"))
    if value is None or value.text is None:
        return ""
    if cell.get("t") == "s":
        return shared[int(value.text)]
    return value.text


def set_cell_shared(cell: ET.Element, idx: int) -> None:
    cell.set("t", "s")
    value = cell.find(q("v"))
    if value is None:
        value = ET.SubElement(cell, q("v"))
    value.text = str(idx)


def parse_servings(portions: str, recipe_number: int) -> float:
    text = portions.strip().lower().replace("—", "–")
    if text in {"1", "1 порция", "1 большая порция"}:
        return 1.0
    if "буханк" in text and "10" in text:
        return 10.0
    if "как основное или" in text:
        m = re.search(r"\d+(?:[,.]\d+)?", text)
        return float(m.group(0).replace(",", ".")) if m else 1.0
    if "порц" in text:
        m = re.search(r"(\d+(?:[,.]\d+)?)(?:\s*[–-]\s*(\d+(?:[,.]\d+)?))?", text)
        if m:
            a = float(m.group(1).replace(",", "."))
            b = float(m.group(2).replace(",", ".")) if m.group(2) else a
            return (a + b) / 2
    m = re.search(r"(\d+(?:[,.]\d+)?)(?:\s*[–-]\s*(\d+(?:[,.]\d+)?))?", text)
    if not m:
        return 1.0
    a = float(m.group(1).replace(",", "."))
    b = float(m.group(2).replace(",", ".")) if m.group(2) else a
    return (a + b) / 2


def format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    if value >= 100:
        rounded = round(value * 2) / 2
    elif value >= 10:
        rounded = round(value, 1)
    elif value >= 1:
        rounded = round(value, 2)
    elif value >= 0.1:
        rounded = round(value, 2)
    else:
        rounded = round(value, 3)
    text = f"{rounded:.3f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def parse_number(token: str) -> float:
    token = token.replace(",", ".")
    if " " in token and "/" in token:
        whole, frac = token.split(" ", 1)
        num, den = frac.split("/", 1)
        return float(whole) + float(num) / float(den)
    if "/" in token:
        num, den = token.split("/", 1)
        return float(num) / float(den)
    return float(token)


NUMBER = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:[,.]\d+)?"
RANGE_RE = re.compile(rf"(?<![\w/])({NUMBER})\s*([–-])\s*({NUMBER})(?![\w/])")
SINGLE_RE = re.compile(rf"(?<![\w/])({NUMBER})(?![\w/])")
PREP_RE = re.compile(
    r",\s*(?=(?:нарез|разрез|очист|промы|обсуш|поруб|измельч|тонко|мелко|крупно|"
    r"натер|раскрош|размять|свар|готов|отвар|без кожи|очищ|разобрать|удалить))",
    re.IGNORECASE,
)


def should_skip_number(text: str, start: int) -> bool:
    before = text[max(0, start - 4) : start].lower()
    after = text[start : start + 12].lower()
    if before.endswith("по "):
        return True
    if after.startswith("1%") or after.startswith("2%"):
        return True
    return False


def scale_amount_text(text: str, divisor: float) -> str:
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"@@P{len(protected) - 1}@@"

    def protect_literal(value: str) -> str:
        protected.append(value)
        return f"@@P{len(protected) - 1}@@"

    work = re.sub(
        r"по\s+\d+(?:[,.]\d+)?(?:\s*[–-]\s*\d+(?:[,.]\d+)?)?\s*(?:г|мл|л|кг)\b",
        protect,
        text,
        flags=re.IGNORECASE,
    )

    def repl_range(match: re.Match[str]) -> str:
        if should_skip_number(work, match.start()):
            return match.group(0)
        first = parse_number(match.group(1)) / divisor
        second = parse_number(match.group(3)) / divisor
        return protect_literal(f"{format_number(first)}{match.group(2)}{format_number(second)}")

    work = RANGE_RE.sub(repl_range, work)

    def repl_single(match: re.Match[str]) -> str:
        token = match.group(1)
        if token.startswith("@@P") or should_skip_number(work, match.start()):
            return token
        return format_number(parse_number(token) / divisor)

    work = SINGLE_RE.sub(repl_single, work)

    for i, original in enumerate(protected):
        work = work.replace(f"@@P{i}@@", original)
    return work


def scale_ingredient_line(line: str, divisor: float) -> str:
    if "—" not in line:
        return line
    name, amount = line.split("—", 1)
    parts = PREP_RE.split(amount, maxsplit=1)
    if len(parts) == 1:
        scaled = scale_amount_text(amount, divisor)
        return f"{name}—{scaled}"
    scaled = scale_amount_text(parts[0], divisor)
    detail = amount[len(parts[0]) :]
    return f"{name}—{scaled}{detail}"


def scale_ingredients(text: str, divisor: float) -> str:
    if divisor == 1:
        return text
    return "\n".join(scale_ingredient_line(line, divisor) for line in text.splitlines())


DESC_UNIT = (
    r"г|кг|мл|л|ст\.?\s*л\.?|ч\.?\s*л\.?|стакан(?:а|ов|е)?|"
    r"чашк(?:а|и|у|ек|е)?|зубчик(?:а|ов)?|шт\.?|ломтик(?:а|ов)?|"
    r"пер(?:о|а|ьев)?|бан(?:ка|ки|ок|ку|ке)?|кочан(?:а|ов)?|"
    r"клуб(?:ень|ня|ней)|луковиц(?:а|ы|у)?|яйц(?:о|а)?|дольк(?:а|и|у|ек)?"
)
DESC_RANGE_RE = re.compile(rf"(?<![\w/])({NUMBER})\s*([–-])\s*({NUMBER})(?=\s*(?:{DESC_UNIT})\b)", re.IGNORECASE)
DESC_SINGLE_RE = re.compile(rf"(?<![\w/])({NUMBER})(?=\s*(?:{DESC_UNIT})\b)", re.IGNORECASE)


def scale_description_measurements(text: str, divisor: float) -> str:
    if divisor == 1:
        return text
    sentence_parts = re.split(r"(?<=[.!?])\s+(?=[А-ЯA-ZЁ])", text)
    if len(sentence_parts) > 1:
        scaled_sentences = []
        for sentence in sentence_parts:
            if "на порц" in sentence.lower():
                scaled_sentences.append(sentence)
            else:
                scaled_sentences.append(scale_description_measurements(sentence, divisor))
        return " ".join(scaled_sentences)

    protected: list[str] = []

    def protect_match(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"@@D{len(protected) - 1}@@"

    def protect_literal(value: str) -> str:
        protected.append(value)
        return f"@@D{len(protected) - 1}@@"

    work = re.sub(
        r"по\s+\d+(?:[,.]\d+)?(?:\s*[–-]\s*\d+(?:[,.]\d+)?)?\s*(?:г|мл|л|кг)\b",
        protect_match,
        text,
        flags=re.IGNORECASE,
    )

    def repl_range(match: re.Match[str]) -> str:
        first = parse_number(match.group(1)) / divisor
        second = parse_number(match.group(3)) / divisor
        return protect_literal(f"{format_number(first)}{match.group(2)}{format_number(second)}")

    work = DESC_RANGE_RE.sub(repl_range, work)

    def repl_single(match: re.Match[str]) -> str:
        return format_number(parse_number(match.group(1)) / divisor)

    work = DESC_SINGLE_RE.sub(repl_single, work)
    for i, original in enumerate(protected):
        work = work.replace(f"@@D{i}@@", original)
    return work


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="recipes_xlsx_") as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(INPUT, "r") as zf:
            zf.extractall(tmp)

        shared_path = tmp / "xl" / "sharedStrings.xml"
        sheet_path = tmp / "xl" / "worksheets" / "sheet1.xml"
        shared_tree = ET.parse(shared_path)
        shared_root = shared_tree.getroot()
        si_items = list(shared_root.findall(q("si")))
        shared = [get_shared_text(si) for si in si_items]
        shared_index = {text: i for i, text in enumerate(shared)}

        def add_shared(text: str) -> int:
            if text in shared_index:
                return shared_index[text]
            idx = len(shared)
            shared.append(text)
            shared_index[text] = idx
            shared_root.append(make_si(text))
            return idx

        one_portion_idx = add_shared("1 порция")

        sheet_tree = ET.parse(sheet_path)
        sheet_root = sheet_tree.getroot()
        cells = {cell.get("r"): cell for cell in sheet_root.iter(q("c")) if cell.get("r")}

        report = []
        for excel_row in range(5, 205):
            num = int(float(cell_text(cells.get(cell_ref("A", excel_row)), shared) or 0))
            if not 1 <= num <= 200:
                continue
            portion_ref = cell_ref("D", excel_row)
            ingredients_ref = cell_ref("F", excel_row)
            description_ref = cell_ref("G", excel_row)
            portion_cell = cells[portion_ref]
            ingredients_cell = cells[ingredients_ref]
            description_cell = cells[description_ref]
            old_portion = cell_text(portion_cell, shared)
            old_ingredients = cell_text(ingredients_cell, shared)
            old_description = cell_text(description_cell, shared)
            divisor = parse_servings(old_portion, num)
            new_ingredients = scale_ingredients(old_ingredients, divisor)
            new_description = scale_description_measurements(old_description, divisor)

            set_cell_shared(portion_cell, one_portion_idx)
            if new_ingredients != old_ingredients:
                set_cell_shared(ingredients_cell, add_shared(new_ingredients))
            if new_description != old_description:
                set_cell_shared(description_cell, add_shared(new_description))
            report.append(
                {
                    "recipe": num,
                    "excel_row": excel_row,
                    "old_portions": old_portion,
                    "divisor": divisor,
                    "ingredients_changed": new_ingredients != old_ingredients,
                    "description_changed": new_description != old_description,
                }
            )

        shared_root.set("count", str(len(shared)))
        shared_root.set("uniqueCount", str(len(shared)))
        shared_tree.write(shared_path, encoding="utf-8", xml_declaration=True)
        sheet_tree.write(sheet_path, encoding="utf-8", xml_declaration=True)

        if OUTPUT.exists():
            OUTPUT.unlink()
        with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in tmp.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(tmp).as_posix())

        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved: {OUTPUT}")
        print(f"Changed ingredient rows: {sum(1 for item in report if item['ingredients_changed'])}")
        print(f"Changed description rows: {sum(1 for item in report if item['description_changed'])}")
        print(f"Rows normalized to one portion: {len(report)}")


if __name__ == "__main__":
    main()
