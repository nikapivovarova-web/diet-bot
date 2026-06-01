from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parent
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_XML = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("", NS_MAIN)


def _is_inside_repo(path: Path) -> bool:
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def _resolve_cli_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve()


def _validate_cli_path(parser: argparse.ArgumentParser, label: str, path: Path, allow_external: bool) -> None:
    if allow_external or _is_inside_repo(path):
        return
    parser.error(f"{label} must be inside {REPO_ROOT} unless --allow-external is set: {path}")


def parse_args(argv: list[str] | None = None) -> tuple[Path, Path, Path]:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy non-release workbook combiner. Requires explicit paths and "
            "refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("first_200", help="Corrected first-block .xlsx workbook.")
    parser.add_argument("second_200", help="Base second-block .xlsx workbook.")
    parser.add_argument("output", help="Destination combined .xlsx workbook.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit input/output paths outside this repository for legacy workbook maintenance.",
    )
    args = parser.parse_args(argv)

    first_200 = _resolve_cli_path(args.first_200)
    second_200 = _resolve_cli_path(args.second_200)
    output = _resolve_cli_path(args.output)
    _validate_cli_path(parser, "first_200", first_200, args.allow_external)
    _validate_cli_path(parser, "second_200", second_200, args.allow_external)
    _validate_cli_path(parser, "output", output, args.allow_external)
    return first_200, second_200, output


def q(tag: str) -> str:
    return f"{{{NS_MAIN}}}{tag}"


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
        is_node = cell.find(q("is"))
        if is_node is None:
            return ""
        return "".join(t.text or "" for t in is_node.iter(q("t")))
    v = cell.find(q("v"))
    if v is None or v.text is None:
        return ""
    if cell.get("t") == "s":
        return shared[int(v.text)]
    return v.text


def set_shared(cell: ET.Element, text: str, add_shared) -> None:
    cell.set("t", "s")
    v = cell.find(q("v"))
    if v is None:
        v = ET.SubElement(cell, q("v"))
    v.text = str(add_shared(text))


def set_inline_string(cell: ET.Element, text: str) -> None:
    cell.set("t", "inlineStr")
    for child in list(cell):
        if child.tag in {q("v"), q("is")}:
            cell.remove(child)
    is_node = ET.SubElement(cell, q("is"))
    t = ET.SubElement(is_node, q("t"))
    if text.startswith((" ", "\n")) or text.endswith((" ", "\n")) or "\n" in text:
        t.set(f"{{{NS_XML}}}space", "preserve")
    t.text = text


def clear_contents(cell: ET.Element | None) -> None:
    if cell is None:
        return
    cell.attrib.pop("t", None)
    v = cell.find(q("v"))
    if v is not None:
        cell.remove(v)


def load_sheet_and_shared(root: Path):
    shared_path = root / "xl" / "sharedStrings.xml"
    sheet_path = root / "xl" / "worksheets" / "sheet1.xml"
    shared_tree = ET.parse(shared_path) if shared_path.exists() else None
    sheet_tree = ET.parse(sheet_path)
    shared_root = shared_tree.getroot() if shared_tree is not None else None
    strings = [shared_text(si) for si in shared_root.findall(q("si"))] if shared_root is not None else []
    cells = {c.get("r"): c for c in sheet_tree.getroot().iter(q("c")) if c.get("r")}
    return shared_tree, sheet_tree, strings, cells


def main(first_200: Path, second_200: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="recipes_final_base_") as base_name, tempfile.TemporaryDirectory(prefix="recipes_first_") as first_name:
        base_dir = Path(base_name)
        first_dir = Path(first_name)
        with zipfile.ZipFile(second_200, "r") as zf:
            zf.extractall(base_dir)
        with zipfile.ZipFile(first_200, "r") as zf:
            zf.extractall(first_dir)

        base_shared_tree, base_sheet_tree, base_strings, base_cells = load_sheet_and_shared(base_dir)
        _, _, first_strings, first_cells = load_sheet_and_shared(first_dir)
        base_shared_root = base_shared_tree.getroot() if base_shared_tree is not None else None
        base_index = {text: i for i, text in enumerate(base_strings)}

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
                set_inline_string(cell, text)
            else:
                set_shared(cell, text, add_base_string)

        # Rows 5:204 are recipes 1:200. Copy the corrected text fields from the
        # first-pass workbook. Keep links, images, row heights, and styles from base.
        copied_cells = 0
        for row in range(5, 205):
            for col in ("B", "C", "D", "E", "F", "G"):
                source_ref = f"{col}{row}"
                target_ref = f"{col}{row}"
                if source_ref in first_cells and target_ref in base_cells:
                    set_base_text(base_cells[target_ref], cell_value(first_cells[source_ref], first_strings))
                    copied_cells += 1

        # Final table should have a uniform one-portion label and no editorial
        #/status notes in helper column J.
        for row in range(5, 405):
            if f"D{row}" in base_cells:
                set_base_text(base_cells[f"D{row}"], "1 порция")
            clear_contents(base_cells.get(f"J{row}"))

        if base_shared_root is not None and base_shared_tree is not None:
            base_shared_root.set("count", str(len(base_strings)))
            base_shared_root.set("uniqueCount", str(len(base_strings)))
            base_shared_tree.write(base_dir / "xl" / "sharedStrings.xml", encoding="utf-8", xml_declaration=True)
        base_sheet_tree.write(base_dir / "xl" / "worksheets" / "sheet1.xml", encoding="utf-8", xml_declaration=True)

        if output.exists():
            output.unlink()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in base_dir.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(base_dir).as_posix())

        print(f"Copied corrected first-block cells: {copied_cells}")
        print(f"Saved: {output}")


if __name__ == "__main__":
    main(*parse_args())
