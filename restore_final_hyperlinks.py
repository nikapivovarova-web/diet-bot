from __future__ import annotations

import argparse
import copy
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parent

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("", NS_MAIN)
ET.register_namespace("r", NS_REL)


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


def parse_args(argv: list[str] | None = None) -> tuple[Path, Path, Path]:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy non-release hyperlink restoration utility. Requires explicit "
            "source/final/output paths and refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("original_workbook", help="Original workbook to copy hyperlink XML from.")
    parser.add_argument("final_workbook", help="Workbook to patch.")
    parser.add_argument("output_workbook", help="Destination patched workbook.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit paths outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    original = _resolve_cli_path(args.original_workbook)
    final = _resolve_cli_path(args.final_workbook)
    output = _resolve_cli_path(args.output_workbook)
    _validate_cli_path(parser, "original_workbook", original, args.allow_external)
    _validate_cli_path(parser, "final_workbook", final, args.allow_external)
    _validate_cli_path(parser, "output_workbook", output, args.allow_external)
    return original, final, output


def q(tag: str) -> str:
    return f"{{{NS_MAIN}}}{tag}"


def extract_file(xlsx: Path, member: str) -> bytes:
    with zipfile.ZipFile(xlsx, "r") as zf:
        return zf.read(member)


def main(original_workbook: Path, final_workbook: Path, output_workbook: Path) -> None:
    original_sheet = ET.fromstring(extract_file(original_workbook, "xl/worksheets/sheet1.xml"))
    original_hyperlinks = original_sheet.find(q("hyperlinks"))
    if original_hyperlinks is None:
        raise RuntimeError("Original workbook has no hyperlinks block.")
    original_rels = extract_file(original_workbook, "xl/worksheets/_rels/sheet1.xml.rels")

    with tempfile.TemporaryDirectory(prefix="restore_hyperlinks_") as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(final_workbook, "r") as zf:
            zf.extractall(tmp)

        sheet_path = tmp / "xl" / "worksheets" / "sheet1.xml"
        final_tree = ET.parse(sheet_path)
        final_root = final_tree.getroot()

        existing = final_root.find(q("hyperlinks"))
        if existing is not None:
            insert_at = list(final_root).index(existing)
            final_root.remove(existing)
        else:
            page_margins = final_root.find(q("pageMargins"))
            insert_at = list(final_root).index(page_margins) if page_margins is not None else len(list(final_root))
        final_root.insert(insert_at, copy.deepcopy(original_hyperlinks))

        drawing = final_root.find(q("drawing"))
        if drawing is not None:
            drawing.set(f"{{{NS_REL}}}id", "rId401")

        final_tree.write(sheet_path, encoding="utf-8", xml_declaration=True)
        rels_path = tmp / "xl" / "worksheets" / "_rels" / "sheet1.xml.rels"
        rels_path.write_bytes(original_rels)

        output_workbook.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output_workbook.with_suffix(".hyperlinks.tmp.xlsx")
        if temp_output.exists():
            temp_output.unlink()
        with zipfile.ZipFile(temp_output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in tmp.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(tmp).as_posix())
        temp_output.replace(output_workbook)
        print("Restored hyperlinks from original workbook.")


if __name__ == "__main__":
    main(*parse_args())
