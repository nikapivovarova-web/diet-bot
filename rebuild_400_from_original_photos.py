from __future__ import annotations

import argparse
import json
import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parent

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_XML = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("", NS_MAIN)

TEXT_COLUMNS = ("B", "C", "D", "E", "F", "G")
ONE_PORTION = "1 \u043f\u043e\u0440\u0446\u0438\u044f"


def _resolve_cli_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve()


def _is_inside_repo(path: Path) -> bool:
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def _validate_cli_path(parser: argparse.ArgumentParser, label: str, path: Path, allow_external: bool) -> None:
    if allow_external or _is_inside_repo(path):
        return
    parser.error(f"{label} must be inside {REPO_ROOT} unless --allow-external is set: {path}")


def parse_args(argv: list[str] | None = None) -> tuple[Path, Path, Path, Path, Path]:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy non-release 400-recipe workbook rebuilder. Requires explicit input/output/report "
            "paths and refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("base_with_good_photos", help="Base workbook whose photos/media are preserved.")
    parser.add_argument("fixed_1_200_text", help="Corrected text workbook for recipes 1-200.")
    parser.add_argument("fixed_201_400_text", help="Corrected text workbook for recipes 201-400.")
    parser.add_argument("output_workbook", help="Destination rebuilt workbook.")
    parser.add_argument("report", help="Destination JSON report.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit paths outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    base_with_good_photos = _resolve_cli_path(args.base_with_good_photos)
    fixed_1_200_text = _resolve_cli_path(args.fixed_1_200_text)
    fixed_201_400_text = _resolve_cli_path(args.fixed_201_400_text)
    output_workbook = _resolve_cli_path(args.output_workbook)
    report = _resolve_cli_path(args.report)
    for label, path in (
        ("base_with_good_photos", base_with_good_photos),
        ("fixed_1_200_text", fixed_1_200_text),
        ("fixed_201_400_text", fixed_201_400_text),
        ("output_workbook", output_workbook),
        ("report", report),
    ):
        _validate_cli_path(parser, label, path, args.allow_external)
    return base_with_good_photos, fixed_1_200_text, fixed_201_400_text, output_workbook, report


def q(tag: str) -> str:
    return f"{{{NS_MAIN}}}{tag}"


def column_name(cell_ref: str) -> str:
    return re.sub(r"\d+", "", cell_ref)


def shared_text(si: ET.Element) -> str:
    return "".join(t.text or "" for t in si.iter(q("t")))


def make_si(text: str) -> ET.Element:
    si = ET.Element(q("si"))
    t = ET.SubElement(si, q("t"))
    if text.startswith((" ", "\n")) or text.endswith((" ", "\n")) or "\n" in text:
        t.set(f"{{{NS_XML}}}space", "preserve")
    t.text = text
    return si


def cell_value(cell: ET.Element | None, shared: list[str]) -> str:
    if cell is None:
        return ""
    if cell.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(q("t")))
    v = cell.find(q("v"))
    if v is None or v.text is None:
        return ""
    if cell.get("t") == "s":
        return shared[int(v.text)]
    return v.text


def set_shared(cell: ET.Element, text: str, add_shared) -> None:
    for child in list(cell):
        if child.tag in {q("v"), q("is")}:
            cell.remove(child)
    cell.set("t", "s")
    v = ET.SubElement(cell, q("v"))
    v.text = str(add_shared(text))


def set_inline(cell: ET.Element, text: str) -> None:
    for child in list(cell):
        if child.tag in {q("v"), q("is")}:
            cell.remove(child)
    cell.set("t", "inlineStr")
    is_node = ET.SubElement(cell, q("is"))
    t = ET.SubElement(is_node, q("t"))
    if text.startswith((" ", "\n")) or text.endswith((" ", "\n")) or "\n" in text:
        t.set(f"{{{NS_XML}}}space", "preserve")
    t.text = text


def clear_cell(cell: ET.Element | None) -> None:
    if cell is None:
        return
    cell.attrib.pop("t", None)
    for child in list(cell):
        if child.tag in {q("v"), q("is")}:
            cell.remove(child)


def load_parts(root: Path):
    sheet_path = root / "xl" / "worksheets" / "sheet1.xml"
    shared_path = root / "xl" / "sharedStrings.xml"
    sheet_tree = ET.parse(sheet_path)
    shared_tree = ET.parse(shared_path) if shared_path.exists() else None
    shared_root = shared_tree.getroot() if shared_tree is not None else None
    strings = [shared_text(si) for si in shared_root.findall(q("si"))] if shared_root is not None else []
    cells = {c.attrib["r"]: c for c in sheet_tree.getroot().iter(q("c")) if c.get("r")}
    return shared_tree, sheet_tree, strings, cells


def zip_dir(src: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())


def main(
    base_with_good_photos: Path,
    fixed_1_200_text: Path,
    fixed_201_400_text: Path,
    output_workbook: Path,
    report_path: Path,
) -> None:
    output_workbook.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="recipes_rebuild_base_") as base_tmp, tempfile.TemporaryDirectory(
        prefix="recipes_rebuild_1_200_"
    ) as first_tmp, tempfile.TemporaryDirectory(prefix="recipes_rebuild_201_400_") as second_tmp:
        base_dir = Path(base_tmp)
        first_dir = Path(first_tmp)
        second_dir = Path(second_tmp)
        for xlsx, target in (
            (base_with_good_photos, base_dir),
            (fixed_1_200_text, first_dir),
            (fixed_201_400_text, second_dir),
        ):
            with zipfile.ZipFile(xlsx, "r") as zf:
                zf.extractall(target)

        base_shared_tree, base_sheet_tree, base_strings, base_cells = load_parts(base_dir)
        _, _, first_strings, first_cells = load_parts(first_dir)
        _, _, second_strings, second_cells = load_parts(second_dir)

        base_shared_root = base_shared_tree.getroot() if base_shared_tree is not None else None
        base_index = {text: idx for idx, text in enumerate(base_strings)}

        def add_base_string(text: str) -> int:
            if text in base_index:
                return base_index[text]
            idx = len(base_strings)
            base_strings.append(text)
            base_index[text] = idx
            if base_shared_root is not None:
                base_shared_root.append(make_si(text))
            return idx

        def set_base_text(cell: ET.Element, text: str) -> None:
            if base_shared_root is None:
                set_inline(cell, text)
            else:
                set_shared(cell, text, add_base_string)

        copied = {"rows_1_200": 0, "rows_201_400": 0}
        for row in range(5, 205):
            for col in TEXT_COLUMNS:
                ref = f"{col}{row}"
                if ref in first_cells and ref in base_cells:
                    set_base_text(base_cells[ref], cell_value(first_cells[ref], first_strings))
                    copied["rows_1_200"] += 1

        for row in range(205, 405):
            for col in TEXT_COLUMNS:
                ref = f"{col}{row}"
                if ref in second_cells and ref in base_cells:
                    set_base_text(base_cells[ref], cell_value(second_cells[ref], second_strings))
                    copied["rows_201_400"] += 1

        for row in range(5, 405):
            d_ref = f"D{row}"
            if d_ref in base_cells:
                set_base_text(base_cells[d_ref], ONE_PORTION)
            clear_cell(base_cells.get(f"J{row}"))

        if base_shared_root is not None and base_shared_tree is not None:
            base_shared_root.set("count", str(len(base_strings)))
            base_shared_root.set("uniqueCount", str(len(base_strings)))
            base_shared_tree.write(base_dir / "xl" / "sharedStrings.xml", encoding="utf-8", xml_declaration=True)
        base_sheet_tree.write(base_dir / "xl" / "worksheets" / "sheet1.xml", encoding="utf-8", xml_declaration=True)
        zip_dir(base_dir, output_workbook)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "base_with_good_photos": str(base_with_good_photos),
                "fixed_1_200_text": str(fixed_1_200_text),
                "fixed_201_400_text": str(fixed_201_400_text),
                "output": str(output_workbook),
                "copied_cells": copied,
                "text_columns_copied": list(TEXT_COLUMNS),
                "photos_policy": "all drawing/media files kept from base workbook",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output_workbook)


if __name__ == "__main__":
    main(*parse_args())
