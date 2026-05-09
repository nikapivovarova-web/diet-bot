from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageOps


INPUT = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion_rebuilt_checked.xlsx"
)
OUTPUT = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion_rebuilt_generated_checked.xlsx"
)
ASSET_DIR = Path(r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\generated_grid_photos")
REPORT = Path(r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\grid_photo_replacements.json")

GEN_DIR = Path(r"C:\Users\adck8\.codex\generated_images\019dfeb1-503c-7542-9789-8bcf365ab966")
GRID_BATCHES = [
    (
        GEN_DIR / "ig_07687b1fb73b5ec60169fbc0b7c6e48191a3dbd201f59bcd7b.png",
        [251, 252, 253, 254, 255, 256, 257, 258, 259],
    ),
    (
        GEN_DIR / "ig_07687b1fb73b5ec60169fbc246954081919e546a932676bdb7.png",
        [260, 261, 262, 263, 264, 265, 266, 267, 268],
    ),
    (
        GEN_DIR / "ig_07687b1fb73b5ec60169fbc2a970ec81918f60fd58e6712ee2.png",
        [288, 289, 292, 293, 294, 297, 299, 300, 301],
    ),
    (
        GEN_DIR / "ig_07687b1fb73b5ec60169fbc315a5048191a8c2fc9a27d0049c.png",
        [302, 303, 304, 333, 334, 335, 336, 337, 341],
    ),
    (
        GEN_DIR / "ig_07687b1fb73b5ec60169fbc3805924819186091e1399abbb4b.png",
        [343, 344, 345, 346, 347, 348, 350, 354, 361],
    ),
    (
        GEN_DIR / "ig_07687b1fb73b5ec60169fbc3eccf0881918e690562b5c48ecd.png",
        [362, 363, 364, 371, 372, 373, 374, 375, 376],
    ),
    (
        GEN_DIR / "ig_07687b1fb73b5ec60169fbc4542f548191848a3ce2e867d91e.png",
        [377, 378, 379, 380, 383, 384, 390, 397, 398],
    ),
]

NS_D = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


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


def crop_grid(grid_path: Path, recipe_numbers: list[int]) -> list[tuple[int, Path]]:
    if len(recipe_numbers) != 9:
        raise ValueError("Each grid batch must contain exactly 9 recipe numbers.")
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
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
            dest = ASSET_DIR / f"recipe_{recipe_no}.jpg"
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


def main() -> None:
    replacements: list[tuple[int, Path]] = []
    for grid, recipe_numbers in GRID_BATCHES:
        if not grid.exists():
            raise FileNotFoundError(grid)
        replacements.extend(crop_grid(grid, recipe_numbers))

    with tempfile.TemporaryDirectory(prefix="recipes_grid_generated_") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(INPUT, "r") as zf:
            zf.extractall(root)
        media_map = build_map(root)
        report = []
        for recipe_no, photo in replacements:
            media = media_map[recipe_no]
            shutil.copyfile(photo, root / media)
            report.append({"recipe_no": recipe_no, "photo": str(photo), "xlsx_media": media})
        zip_dir(root, OUTPUT)

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT)
    print(f"replaced {len(replacements)} grid photos")


if __name__ == "__main__":
    main()
