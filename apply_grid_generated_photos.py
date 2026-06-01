from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageOps


REPO_ROOT = Path(__file__).resolve().parent

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


def _parse_grid_batch(value: str) -> tuple[Path, list[int]]:
    path_raw, separator, recipes_raw = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("expected GRID_IMAGE=RECIPE,RECIPE,...")
    try:
        recipe_numbers = [int(item.strip()) for item in recipes_raw.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("recipe numbers must be integers") from exc
    if len(recipe_numbers) != 9:
        raise argparse.ArgumentTypeError("each grid batch must contain exactly 9 recipe numbers")
    return _resolve_cli_path(path_raw), recipe_numbers


def parse_args(argv: list[str] | None = None) -> tuple[Path, Path, Path, Path, list[tuple[Path, list[int]]]]:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy non-release generated-grid photo applicator. Requires explicit workbook, "
            "asset/report, and grid image paths; refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("input_workbook", help="Source workbook.")
    parser.add_argument("output_workbook", help="Destination workbook.")
    parser.add_argument("asset_dir", help="Directory for cropped grid photos.")
    parser.add_argument("report", help="Destination JSON report.")
    parser.add_argument(
        "--grid-batch",
        action="append",
        type=_parse_grid_batch,
        required=True,
        metavar="IMAGE=R1,...,R9",
        help="Grid image path and its 9 recipe numbers. May be repeated.",
    )
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit paths outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    input_workbook = _resolve_cli_path(args.input_workbook)
    output_workbook = _resolve_cli_path(args.output_workbook)
    asset_dir = _resolve_cli_path(args.asset_dir)
    report = _resolve_cli_path(args.report)
    for label, path in (
        ("input_workbook", input_workbook),
        ("output_workbook", output_workbook),
        ("asset_dir", asset_dir),
        ("report", report),
    ):
        _validate_cli_path(parser, label, path, args.allow_external)
    for index, (grid_path, _) in enumerate(args.grid_batch, start=1):
        _validate_cli_path(parser, f"grid_batch[{index}]", grid_path, args.allow_external)
    return input_workbook, output_workbook, asset_dir, report, args.grid_batch


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def build_map(root: Path) -> dict[int, str]:
    drawing = ET.parse(root / "xl" / "drawings" / "drawing1.xml").getroot()
    rels = ET.parse(root / "xl" / "drawings" / "_rels" / "drawing1.xml.rels").getroot()
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"].replace("../", "xl/").lstrip("/")
        for rel in rels.findall(q(NS_REL, "Relationship"))
    }
    result: dict[int, str] = {}
    for anchor in drawing.findall(q(NS_D, "oneCellAnchor")):
        row_node = anchor.find(f"{q(NS_D, 'from')}/{q(NS_D, 'row')}")
        blip = anchor.find(f".//{q(NS_A, 'blip')}")
        if row_node is None or blip is None:
            continue
        media = rel_map.get(blip.attrib.get(q(NS_R, "embed"), ""))
        if media:
            result[int(row_node.text) - 3] = media
    return result


def crop_grid(grid_path: Path, recipe_numbers: list[int], asset_dir: Path) -> list[tuple[int, Path]]:
    if len(recipe_numbers) != 9:
        raise ValueError("Each grid batch must contain exactly 9 recipe numbers.")
    asset_dir.mkdir(parents=True, exist_ok=True)
    out: list[tuple[int, Path]] = []
    with Image.open(grid_path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        w, h = img.size
        cell_w, cell_h = w / 3, h / 3
        margin = max(8, round(min(w, h) * 0.008))
        for idx, recipe_no in enumerate(recipe_numbers):
            row, col = divmod(idx, 3)
            left = round(col * cell_w + margin)
            top = round(row * cell_h + margin)
            right = round((col + 1) * cell_w - margin)
            bottom = round((row + 1) * cell_h - margin)
            crop = img.crop((left, top, right, bottom))
            crop = ImageOps.fit(crop, (512, 384), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            dest = asset_dir / f"recipe_{recipe_no}.jpg"
            crop.save(dest, "JPEG", quality=90, optimize=True)
            out.append((recipe_no, dest))
    return out


def zip_dir(src: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())


def main(
    input_workbook: Path,
    output_workbook: Path,
    asset_dir: Path,
    report_path: Path,
    grid_batches: list[tuple[Path, list[int]]],
) -> None:
    replacements: list[tuple[int, Path]] = []
    for grid, recipe_numbers in grid_batches:
        if not grid.exists():
            raise FileNotFoundError(grid)
        replacements.extend(crop_grid(grid, recipe_numbers, asset_dir))

    with tempfile.TemporaryDirectory(prefix="recipes_grid_generated_") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(input_workbook, "r") as zf:
            zf.extractall(root)
        media_map = build_map(root)
        report = []
        for recipe_no, photo in replacements:
            media = media_map[recipe_no]
            shutil.copyfile(photo, root / media)
            report.append({"recipe_no": recipe_no, "photo": str(photo), "xlsx_media": media})
        zip_dir(root, output_workbook)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_workbook)
    print(f"replaced {len(replacements)} grid photos")


if __name__ == "__main__":
    main(*parse_args())
