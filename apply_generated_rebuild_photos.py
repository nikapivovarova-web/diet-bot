from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageOps


INPUT = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion_original_photos.xlsx"
)
OUTPUT = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion_rebuilt_checked.xlsx"
)
ASSET_DIR = Path(r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\generated_recipe_photos")
REPORT = Path(r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\generated_photo_replacements.json")

GENERATED = {
    15: Path(
        r"C:\Users\adck8\.codex\generated_images\019dfeb1-503c-7542-9789-8bcf365ab966\ig_07687b1fb73b5ec60169fbbbf4438081919ab487d28713ae17.png"
    ),
    43: Path(
        r"C:\Users\adck8\.codex\generated_images\019dfeb1-503c-7542-9789-8bcf365ab966\ig_07687b1fb73b5ec60169fbbd2fb9588191b25a90ecc2338463.png"
    ),
    118: Path(
        r"C:\Users\adck8\.codex\generated_images\019dfeb1-503c-7542-9789-8bcf365ab966\ig_07687b1fb73b5ec60169fbbd839b448191af74453c9cc9cdc2.png"
    ),
}

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


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="recipes_rebuild_generated_photos_") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(INPUT, "r") as zf:
            zf.extractall(root)
        media_map = build_map(root)
        report = []
        for recipe_no, source in GENERATED.items():
            if not source.exists():
                raise FileNotFoundError(source)
            standardized = ASSET_DIR / f"recipe_{recipe_no}.jpg"
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
        zip_dir(root, OUTPUT)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
