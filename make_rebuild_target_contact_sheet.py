from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


WORKBOOK = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion_rebuilt_generated_checked.xlsx"
)
OUT = Path(r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\replaced_rows_generated_checked_photos.jpg")
TARGETS = [15, 36, 43, 77, 78, 80, 82, 89, 107, 111, 118, 187, 188, 198, 199, 207, 219, 289, 354, 391, 392]

NS_D = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def build_map() -> dict[int, str]:
    with zipfile.ZipFile(WORKBOOK, "r") as zf:
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
        if row_node is not None and blip is not None:
            media = rel_map.get(blip.attrib.get(q(NS_R, "embed"), ""))
            if media:
                result[int(row_node.text) - 3] = media
    return result


def fit(zf: zipfile.ZipFile, media: str) -> Image.Image:
    image = Image.open(io.BytesIO(zf.read(media))).convert("RGB")
    image.thumbnail((220, 165), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (220, 165), "white")
    canvas.paste(image, ((220 - image.width) // 2, (165 - image.height) // 2))
    return canvas


def main() -> None:
    mapping = build_map()
    cols = 4
    cell_w, cell_h = 235, 195
    rows = (len(TARGETS) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    with zipfile.ZipFile(WORKBOOK, "r") as zf:
        for idx, recipe_no in enumerate(TARGETS):
            x = (idx % cols) * cell_w
            y = (idx // cols) * cell_h
            draw.rectangle([x, y, x + cell_w - 1, y + cell_h - 1], outline=(210, 210, 210))
            draw.text((x + 8, y + 8), f"recipe {recipe_no}", fill=(0, 0, 0), font=font)
            media = mapping.get(recipe_no)
            if media:
                sheet.paste(fit(zf, media), (x + 7, y + 25))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT, quality=92)
    print(OUT)


if __name__ == "__main__":
    main()
