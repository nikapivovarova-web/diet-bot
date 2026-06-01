from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parent
PHOTO_REPLACEMENTS = {43: 49, 118: 103, 199: 200}

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_D = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


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


def parse_args(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy non-release photo workbook integrity verifier. Requires an explicit "
            "workbook path and refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("workbook", help="Workbook to verify.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit a workbook path outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    workbook = _resolve_cli_path(args.workbook)
    _validate_cli_path(parser, "workbook", workbook, args.allow_external)
    return workbook


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for si in root.findall(q(NS_MAIN, "si")):
        strings.append("".join(t.text or "" for t in si.iter(q(NS_MAIN, "t"))))
    return strings


def column_name(ref: str) -> str:
    return re.sub(r"\d+", "", ref)


def cell_text(cell: ET.Element, shared: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(q(NS_MAIN, "t")))
    value = cell.find(q(NS_MAIN, "v"))
    if value is None or value.text is None:
        return ""
    if cell.get("t") == "s":
        return shared[int(value.text)]
    return value.text


def drawing_map(zf: zipfile.ZipFile) -> dict[int, str]:
    drawing = ET.fromstring(zf.read("xl/drawings/drawing1.xml"))
    rels = ET.fromstring(zf.read("xl/drawings/_rels/drawing1.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"].replace("../", "xl/")
        for rel in rels.findall(q(NS_REL, "Relationship"))
    }
    result: dict[int, str] = {}
    for anchor in drawing.findall(q(NS_D, "oneCellAnchor")):
        row_node = anchor.find(f"{q(NS_D, 'from')}/{q(NS_D, 'row')}")
        blip = anchor.find(f".//{q(NS_A, 'blip')}")
        if row_node is None or blip is None:
            continue
        recipe = int(row_node.text) - 3
        rid = blip.attrib.get(q(NS_R, "embed"))
        if rid and rid in rel_map:
            result[recipe] = rel_map[rid].lstrip("/")
    return result


def digest(zf: zipfile.ZipFile, path: str) -> str:
    return hashlib.sha256(zf.read(path)).hexdigest()


def main(workbook: Path) -> None:
    with zipfile.ZipFile(workbook, "r") as zf:
        shared = shared_strings(zf)
        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        rows = []
        for row in sheet.findall(f"{q(NS_MAIN, 'sheetData')}/{q(NS_MAIN, 'row')}"):
            row_idx = int(row.attrib["r"])
            if not 5 <= row_idx <= 404:
                continue
            values = {column_name(c.attrib["r"]): cell_text(c, shared) for c in row.findall(q(NS_MAIN, "c"))}
            rows.append(values)

        numbers = [int(float(r.get("A", "0") or 0)) for r in rows]
        bad_portions = [
            {"row_number": r.get("A"), "title": r.get("C"), "portion": r.get("D")}
            for r in rows
            if (r.get("D") or "").strip() != "1 порция"
        ]
        notes = [
            {"row_number": r.get("A"), "title": r.get("C"), "note": r.get("J")}
            for r in rows
            if (r.get("J") or "").strip()
        ]
        hyperlinks = sheet.findall(q(NS_MAIN, "hyperlinks") + "/" + q(NS_MAIN, "hyperlink"))
        media_files = [name for name in zf.namelist() if name.startswith("xl/media/")]
        draw_map = drawing_map(zf)
        copied = []
        for target, source in PHOTO_REPLACEMENTS.items():
            target_media = draw_map[target]
            source_media = draw_map[source]
            copied.append(
                {
                    "target_recipe": target,
                    "source_recipe": source,
                    "same_bytes": digest(zf, target_media) == digest(zf, source_media),
                    "target_media": target_media,
                    "source_media": source_media,
                }
            )

    missing_numbers = [n for n in range(1, 401) if n not in numbers]
    duplicate_numbers = sorted({n for n in numbers if numbers.count(n) > 1})
    print(
        json.dumps(
            {
                "workbook": str(workbook),
                "row_count": len(rows),
                "missing_numbers": missing_numbers,
                "duplicate_numbers": duplicate_numbers,
                "bad_portions_count": len(bad_portions),
                "notes_count": len(notes),
                "hyperlinks_count": len(hyperlinks),
                "media_count": len(media_files),
                "drawing_anchor_count": len(draw_map),
                "photo_copies": copied,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main(parse_args())
