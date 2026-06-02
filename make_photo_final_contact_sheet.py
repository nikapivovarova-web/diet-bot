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

TARGETS = [36, 43, 77, 78, 80, 82, 89, 107, 111, 118, 187, 188, 198, 199]


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
            "Legacy non-release final photo contact-sheet builder. Requires explicit "
            "input/output paths and refuses outside-repo paths unless --allow-external is set."
        )
    )
    parser.add_argument("workbook", help="Workbook to inspect.")
    parser.add_argument("output", help="Destination contact-sheet image.")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Permit paths outside this repository for legacy maintenance.",
    )
    args = parser.parse_args(argv)
    workbook = _resolve_cli_path(args.workbook)
    output = _resolve_cli_path(args.output)
    _validate_cli_path(parser, "workbook", workbook, args.allow_external)
    _validate_cli_path(parser, "output", output, args.allow_external)
    return workbook, output


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def build_map(xlsx: Path) -> dict[int, str]:
    with zipfile.ZipFile(xlsx, "r") as zf:
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
        media = rel_map.get(rid or "")
        if media:
            result[recipe] = media.lstrip("/")
    return result


def fit_image(zf: zipfile.ZipFile, media: str) -> Image.Image:
    img = Image.open(io.BytesIO(zf.read(media))).convert("RGB")
    img.thumbnail((220, 165), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (220, 165), "white")
    canvas.paste(img, ((220 - img.width) // 2, (165 - img.height) // 2))
    return canvas


def main(workbook: Path, output: Path) -> None:
    mapping = build_map(workbook)
    font = ImageFont.load_default()
    cols = 4
    cell_w, cell_h = 235, 195
    rows = (len(TARGETS) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    with zipfile.ZipFile(workbook, "r") as zf:
        for idx, target in enumerate(TARGETS):
            col, row = idx % cols, idx // cols
            x, y = col * cell_w, row * cell_h
            draw.rectangle([x, y, x + cell_w - 1, y + cell_h - 1], outline=(210, 210, 210))
            draw.text((x + 8, y + 8), f"recipe {target}", fill=(0, 0, 0), font=font)
            media = mapping[target]
            sheet.paste(fit_image(zf, media), (x + 7, y + 25))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)
    print(output)


if __name__ == "__main__":
    main(*parse_args())
