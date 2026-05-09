from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


INPUT = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion.xlsx"
)
OUTPUT = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion_photos.xlsx"
)
REPORT = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400\photo_replacement_report.json"
)

NS_D = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

# Only these target photos were visibly mismatched after checking all directly
# replaced recipes. Most target rows already had suitable pictures.
PHOTO_REPLACEMENTS = {
    43: 49,    # toast/sandwich with egg and vegetables
    118: 103,  # chicken with potatoes
    199: 200,  # potato/sweet-potato hash with egg
}


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def build_map(root: Path) -> dict[int, str]:
    drawing = ET.parse(root / "xl" / "drawings" / "drawing1.xml").getroot()
    rels = ET.parse(root / "xl" / "drawings" / "_rels" / "drawing1.xml.rels").getroot()
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


def zip_dir(src: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in src.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(src).as_posix())


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(INPUT, "r") as zf:
            zf.extractall(root)

        mapping = build_map(root)
        report = []
        for target, source in PHOTO_REPLACEMENTS.items():
            target_media = mapping[target]
            source_media = mapping[source]
            target_path = root / target_media
            source_path = root / source_media
            before_size = target_path.stat().st_size
            shutil.copyfile(source_path, target_path)
            report.append(
                {
                    "target_recipe": target,
                    "source_recipe": source,
                    "target_media": target_media,
                    "source_media": source_media,
                    "before_size": before_size,
                    "after_size": target_path.stat().st_size,
                }
            )

        zip_dir(root, OUTPUT)

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "replacements": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
