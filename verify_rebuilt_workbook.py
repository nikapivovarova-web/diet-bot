from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parent
EXPECTED_PHOTO_MISMATCHES = [
    15,
    43,
    118,
    251,
    252,
    253,
    254,
    255,
    256,
    257,
    258,
    259,
    260,
    261,
    262,
    263,
    264,
    265,
    266,
    267,
    268,
    288,
    289,
    292,
    293,
    294,
    297,
    299,
    300,
    301,
    302,
    303,
    304,
    333,
    334,
    335,
    336,
    337,
    341,
    343,
    344,
    345,
    346,
    347,
    348,
    350,
    354,
    361,
    362,
    363,
    364,
    371,
    372,
    373,
    374,
    375,
    376,
    377,
    378,
    379,
    380,
    383,
    384,
    390,
    397,
    398,
]

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


def parse_args(argv: list[str] | None = None) -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy non-release rebuilt workbook verifier. Requires explicit base/workbook "
            "paths and refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("base_workbook", help="Original/base workbook for photo comparison.")
    parser.add_argument("workbook", help="Rebuilt workbook to verify.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit paths outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    base = _resolve_cli_path(args.base_workbook)
    workbook = _resolve_cli_path(args.workbook)
    _validate_cli_path(parser, "base_workbook", base, args.allow_external)
    _validate_cli_path(parser, "workbook", workbook, args.allow_external)
    return base, workbook


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def col(ref: str) -> str:
    return re.sub(r"\d+", "", ref)


def shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(q(NS_MAIN, "t"))) for si in root.findall(q(NS_MAIN, "si"))]


def cell_text(cell: ET.Element, shared: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(q(NS_MAIN, "t")))
    value = cell.find(q(NS_MAIN, "v"))
    if value is None or value.text is None:
        return ""
    if cell.get("t") == "s":
        return shared[int(value.text)]
    return value.text


def rows_from_sheet(zf: zipfile.ZipFile) -> list[dict[str, str]]:
    shared = shared_strings(zf)
    root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in root.findall(f"{q(NS_MAIN, 'sheetData')}/{q(NS_MAIN, 'row')}"):
        row_idx = int(row.attrib["r"])
        if 5 <= row_idx <= 404:
            rows.append({col(c.attrib["r"]): cell_text(c, shared) for c in row.findall(q(NS_MAIN, "c"))})
    return rows


def image_map(xlsx: Path) -> dict[int, dict[str, str]]:
    with zipfile.ZipFile(xlsx, "r") as zf:
        drawing = ET.fromstring(zf.read("xl/drawings/drawing1.xml"))
        rels = ET.fromstring(zf.read("xl/drawings/_rels/drawing1.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"].replace("../", "xl/").lstrip("/")
            for rel in rels.findall(q(NS_REL, "Relationship"))
        }
        result = {}
        for anchor in drawing.findall(q(NS_D, "oneCellAnchor")):
            row_node = anchor.find(f"{q(NS_D, 'from')}/{q(NS_D, 'row')}")
            blip = anchor.find(f".//{q(NS_A, 'blip')}")
            if row_node is None or blip is None:
                continue
            recipe_no = int(row_node.text) - 3
            rid = blip.attrib.get(q(NS_R, "embed"))
            media = rel_map.get(rid or "")
            if media:
                result[recipe_no] = {
                    "media": media,
                    "sha256": hashlib.sha256(zf.read(media)).hexdigest(),
                }
        return result


def hyperlink_count(zf: zipfile.ZipFile) -> int:
    root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    node = root.find(q(NS_MAIN, "hyperlinks"))
    if node is None:
        return 0
    return len(node.findall(q(NS_MAIN, "hyperlink")))


def main(base_workbook: Path, workbook: Path) -> None:
    with zipfile.ZipFile(workbook, "r") as zf:
        rows = rows_from_sheet(zf)
        hyperlinks = hyperlink_count(zf)
    nums = [int(float(row.get("A", "0") or 0)) for row in rows]
    bad_portions = [row.get("A") for row in rows if (row.get("D") or "").strip() != "1 порция"]
    notes = [row.get("A") for row in rows if (row.get("J") or "").strip()]
    rebuilt_images = image_map(workbook)
    base_images = image_map(base_workbook)
    mismatched_photos = [
        n for n in range(1, 401) if rebuilt_images.get(n, {}).get("sha256") != base_images.get(n, {}).get("sha256")
    ]
    print(
        json.dumps(
            {
                "workbook": str(workbook),
                "row_count": len(rows),
                "missing_numbers": [n for n in range(1, 401) if n not in nums],
                "duplicate_numbers": sorted({n for n in nums if nums.count(n) > 1}),
                "bad_portions_count": len(bad_portions),
                "notes_count": len(notes),
                "hyperlinks_count": hyperlinks,
                "image_count": len(rebuilt_images),
                "base_image_count": len(base_images),
                "photo_mismatches_vs_base_count": len(mismatched_photos),
                "photo_mismatches_vs_base": mismatched_photos[:40],
                "expected_photo_mismatches": EXPECTED_PHOTO_MISMATCHES,
                "unexpected_photo_mismatches": [n for n in mismatched_photos if n not in EXPECTED_PHOTO_MISMATCHES],
                "missing_expected_photo_mismatches": [n for n in EXPECTED_PHOTO_MISMATCHES if n not in mismatched_photos],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main(*parse_args())
