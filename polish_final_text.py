from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent

REPLACEMENTS = {
    "1 банки": "1 банка",
    "1 пера": "1 перо",
    "1 ломтика": "1 ломтик",
    "1 крупных": "1 крупное",
    "1 средних": "1 среднее",
    "1 небольших": "1 небольшой",
    "1 небольшой или средних клубня": "1 небольшой или средний клубень",
    "0,5 средних клубня": "0,5 среднего клубня",
    "зеленый луком": "зеленым луком",
}


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
            "Legacy non-release workbook text polisher. Requires explicit input/output "
            "paths and refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("input_workbook", help="Workbook to polish.")
    parser.add_argument("output_workbook", help="Destination workbook.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit paths outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    input_workbook = _resolve_cli_path(args.input_workbook)
    output_workbook = _resolve_cli_path(args.output_workbook)
    _validate_cli_path(parser, "input_workbook", input_workbook, args.allow_external)
    _validate_cli_path(parser, "output_workbook", output_workbook, args.allow_external)
    return input_workbook, output_workbook


def main(input_workbook: Path, output_workbook: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="polish_final_") as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(input_workbook, "r") as zf:
            zf.extractall(tmp)

        sheet_path = tmp / "xl" / "worksheets" / "sheet1.xml"
        text = sheet_path.read_text(encoding="utf-8")
        replacements = 0
        for old, new in REPLACEMENTS.items():
            count = text.count(old)
            if count:
                replacements += count
                text = text.replace(old, new)
        sheet_path.write_text(text, encoding="utf-8")

        output_workbook.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output_workbook.with_suffix(".polished.tmp.xlsx")
        if temp_output.exists():
            temp_output.unlink()
        with zipfile.ZipFile(temp_output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in tmp.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(tmp).as_posix())
        temp_output.replace(output_workbook)
        print(f"Polished text replacements: {replacements}")


if __name__ == "__main__":
    main(*parse_args())
