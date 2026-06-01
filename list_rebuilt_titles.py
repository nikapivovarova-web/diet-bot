from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parent
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


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
            "Legacy non-release workbook title lister. Requires an explicit workbook "
            "path and refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("workbook", help="Workbook to inspect.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit a workbook path outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    workbook = _resolve_cli_path(args.workbook)
    _validate_cli_path(parser, "workbook", workbook, args.allow_external)
    return workbook


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def col(ref: str) -> str:
    return re.sub(r"\d+", "", ref)


def cell_text(cell: ET.Element, shared: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(q("t")))
    v = cell.find(q("v"))
    if v is None or v.text is None:
        return ""
    if cell.get("t") == "s":
        return shared[int(v.text)]
    return v.text


def main(workbook: Path) -> None:
    with zipfile.ZipFile(workbook, "r") as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(q("t"))) for si in root.findall(q("si"))]
        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    for row in sheet.findall(f"{q('sheetData')}/{q('row')}"):
        cells = {col(c.attrib["r"]): cell_text(c, shared) for c in row.findall(q("c"))}
        no = cells.get("A")
        if no and no.isdigit():
            n = int(no)
            if 201 <= n <= 400:
                print(f"{n}\t{cells.get('C', '')}")


if __name__ == "__main__":
    main(parse_args())
