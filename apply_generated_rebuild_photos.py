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


def _parse_generated(value: str) -> tuple[int, Path]:
    recipe_raw, separator, path_raw = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("expected RECIPE_NUMBER=IMAGE_PATH")
    try:
        recipe_number = int(recipe_raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("recipe number must be an integer") from exc
    return recipe_number, _resolve_cli_path(path_raw)


def parse_args(argv: list[str] | None = None) -> tuple[Path, Path, Path, Path, dict[int, Path]]:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy non-release generated-photo applicator. Requires explicit workbook, "
            "asset/report, and generated image paths; refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("input_workbook", help="Source workbook.")
    parser.add_argument("output_workbook", help="Destination workbook.")
    parser.add_argument("asset_dir", help="Directory for standardized generated photos.")
    parser.add_argument("report", help="Destination JSON report.")
    parser.add_argument(
        "--generated",
        action="append",
        type=_parse_generated,
        required=True,
        metavar="RECIPE=IMAGE",
        help="Generated image path for one recipe number. May be repeated.",
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
    generated = dict(args.generated)
    for label, path in (
        ("input_workbook", input_workbook),
        ("output_workbook", output_workbook),
        ("asset_dir", asset_dir),
        ("report", report),
    ):
        _validate_cli_path(parser, label, path, args.allow_external)
    for recipe_number, path in generated.items():
        _validate_cli_path(parser, f"generated[{recipe_number}]", path, args.allow_external)
    return input_workbook, output_workbook, asset_dir, report, generated


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
        rid = blip.attrib.get(q(NS_R, "embed"))
        media = rel_map.get(rid or "")
        if media:
            result[int(row_node.text) - 3] = media
    return result


def standardize(src: Path, dest: Path) -> None:
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img = ImageOps.fit(img, (512, 384), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "JPEG", quality=90, optimize=True)


def zip_dir(src: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())


def main(input_workbook: Path, output_workbook: Path, asset_dir: Path, report_path: Path, generated: dict[int, Path]) -> None:
    asset_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="recipes_rebuild_generated_photos_") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(input_workbook, "r") as zf:
            zf.extractall(root)
        media_map = build_map(root)
        report = []
        for recipe_no, source in generated.items():
            if not source.exists():
                raise FileNotFoundError(source)
            standardized = asset_dir / f"recipe_{recipe_no}.jpg"
            standardize(source, standardized)
            media = media_map[recipe_no]
            shutil.copyfile(standardized, root / media)
            report.append(
                {
                    "recipe_no": recipe_no,
                    "generated_source": str(source),
                    "standardized_photo": str(standardized),
                    "xlsx_media": media,
                }
            )
        zip_dir(root, output_workbook)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_workbook)


if __name__ == "__main__":
    main(*parse_args())
