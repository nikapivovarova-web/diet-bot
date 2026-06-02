from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


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


def parse_args(argv: list[str] | None = None) -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy non-release rebuilt-photo contact-sheet builder. Requires explicit "
            "input/output paths and refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("workbook", help="Workbook to inspect.")
    parser.add_argument("output_dir", help="Destination directory for contact-sheet images.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit paths outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    workbook = _resolve_cli_path(args.workbook)
    output_dir = _resolve_cli_path(args.output_dir)
    _validate_cli_path(parser, "workbook", workbook, args.allow_external)
    _validate_cli_path(parser, "output_dir", output_dir, args.allow_external)
    return workbook, output_dir


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def build_map(xlsx: Path) -> dict[int, str]:
    with zipfile.ZipFile(xlsx, "r") as zf:
        drawing = ET.fromstring(zf.read("xl/drawings/drawing1.xml"))
        rels = ET.fromstring(zf.read("xl/drawings/_rels/drawing1.xml.rels"))
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
        recipe_no = int(row_node.text) - 3
        rid = blip.attrib.get(q(NS_R, "embed"))
        media = rel_map.get(rid or "")
        if media:
            result[recipe_no] = media
    return result


def fit(zf: zipfile.ZipFile, media: str, size: tuple[int, int]) -> Image.Image:
    image = Image.open(io.BytesIO(zf.read(media))).convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "white")
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def make_sheet(workbook: Path, output_dir: Path, start: int, end: int) -> Path:
    mapping = build_map(workbook)
    cols = 5
    thumb = (180, 135)
    cell_w, cell_h = 190, 165
    count = end - start + 1
    rows = (count + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    with zipfile.ZipFile(workbook, "r") as zf:
        for idx, recipe_no in enumerate(range(start, end + 1)):
            x = (idx % cols) * cell_w
            y = (idx // cols) * cell_h
            draw.rectangle([x, y, x + cell_w - 1, y + cell_h - 1], outline=(210, 210, 210))
            draw.text((x + 7, y + 7), str(recipe_no), fill=(0, 0, 0), font=font)
            media = mapping.get(recipe_no)
            if media:
                sheet.paste(fit(zf, media, thumb), (x + 5, y + 25))
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"photos_{start}_{end}.jpg"
    sheet.save(out, quality=92)
    return out


def main(workbook: Path, output_dir: Path) -> None:
    for start, end in [(201, 250), (251, 300), (301, 350), (351, 400)]:
        print(make_sheet(workbook, output_dir, start, end))


if __name__ == "__main__":
    main(*parse_args())
