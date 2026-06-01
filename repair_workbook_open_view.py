from __future__ import annotations

import argparse
import shutil
from copy import copy
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.views import Selection


REPO_ROOT = Path(__file__).resolve().parent


def _resolve_cli_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve()


def _is_inside_repo(path: Path) -> bool:
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def _validate_cli_path(parser: argparse.ArgumentParser, label: str, path: Path | None, allow_external: bool) -> None:
    if path is None or allow_external or _is_inside_repo(path):
        return
    parser.error(f"{label} must be inside {REPO_ROOT} unless --allow-external is set: {path}")


def parse_args(argv: list[str] | None = None) -> tuple[Path, Path, Path | None]:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy non-release workbook open-view repair utility. Requires explicit "
            "paths and refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("source", help="Source workbook.")
    parser.add_argument("output", help="Destination workbook.")
    parser.add_argument("--desktop-copy", help="Optional extra copy destination.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit paths outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    source = _resolve_cli_path(args.source)
    output = _resolve_cli_path(args.output)
    desktop_copy = _resolve_cli_path(args.desktop_copy) if args.desktop_copy else None
    _validate_cli_path(parser, "source", source, args.allow_external)
    _validate_cli_path(parser, "output", output, args.allow_external)
    _validate_cli_path(parser, "desktop_copy", desktop_copy, args.allow_external)
    return source, output, desktop_copy


def main(source: Path, output: Path, desktop_copy: Path | None) -> None:
    wb = load_workbook(source)
    wb.active = 0

    for ws in wb.worksheets:
        ws.sheet_state = "visible"
        ws.freeze_panes = "A5"
        ws.sheet_view.showGridLines = True
        ws.sheet_view.zoomScale = 75
        ws.sheet_view.zoomScaleNormal = 75
        ws.sheet_view.topLeftCell = "A1"
        ws.sheet_view.selection = [Selection(activeCell="A1", sqref="A1")]
        if ws.sheet_view.pane is not None:
            ws.sheet_view.pane.topLeftCell = "A5"
            ws.sheet_view.pane.activePane = "bottomLeft"
        ws.views.sheetView[0] = copy(ws.sheet_view)

    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)
    print(output)
    if desktop_copy is not None:
        desktop_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, desktop_copy)
        print(desktop_copy)


if __name__ == "__main__":
    main(*parse_args())
