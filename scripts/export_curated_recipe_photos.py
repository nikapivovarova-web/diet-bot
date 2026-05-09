from __future__ import annotations

import argparse
import json
import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK = (
    ROOT
    / "outputs"
    / "recipes_final_400_rebuild"
    / "bolshaya_tablica_receptov_s_foto_400_final_opens_from_start.xlsx"
)
DEFAULT_RECIPES_JSON = ROOT / "src" / "diet_bot" / "data" / "curated_recipes.json"
DEFAULT_PHOTO_DIR = ROOT / "src" / "diet_bot" / "data" / "recipe_photos"

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

NS = {
    "m": MAIN_NS,
    "xdr": DRAWING_NS,
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": REL_NS,
    "rel": PACKAGE_REL_NS,
}


def _cell_column(cell_ref: str) -> str:
    return "".join(char for char in cell_ref if char.isalpha())


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))

    value = cell.find("m:v", NS)
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        return shared_strings[int(value.text)]
    return value.text


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("m:si", NS):
        strings.append("".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t")))
    return strings


def _load_recipe_rows(archive: zipfile.ZipFile) -> dict[int, int]:
    shared_strings = _load_shared_strings(archive)
    root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    recipe_no_by_row: dict[int, int] = {}

    for row in root.findall("m:sheetData/m:row", NS):
        row_number = int(row.attrib["r"])
        cells = {
            _cell_column(cell.attrib["r"]): _cell_value(cell, shared_strings)
            for cell in row.findall("m:c", NS)
        }
        if "A" not in cells:
            continue
        try:
            recipe_no_by_row[row_number] = int(float(cells["A"]))
        except ValueError:
            continue

    return recipe_no_by_row


def _drawing_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    root = ET.fromstring(archive.read("xl/drawings/_rels/drawing1.xml.rels"))
    return {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in root.findall("rel:Relationship", NS)
    }


def _media_path(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl/drawings", target))


def _image_targets_by_recipe_no(archive: zipfile.ZipFile) -> dict[int, str]:
    recipe_no_by_row = _load_recipe_rows(archive)
    relationships = _drawing_relationships(archive)
    drawing = ET.fromstring(archive.read("xl/drawings/drawing1.xml"))
    targets_by_recipe_no: dict[int, str] = {}

    for anchor in drawing.findall("xdr:oneCellAnchor", NS):
        anchor_from = anchor.find("xdr:from", NS)
        if anchor_from is None:
            continue
        row_node = anchor_from.find("xdr:row", NS)
        if row_node is None or row_node.text is None:
            continue
        excel_row = int(row_node.text) + 1
        recipe_no = recipe_no_by_row.get(excel_row)
        if recipe_no is None:
            continue

        blip = anchor.find("xdr:pic/xdr:blipFill/a:blip", NS)
        if blip is None:
            continue
        relationship_id = blip.attrib.get(f"{{{REL_NS}}}embed")
        if not relationship_id:
            continue
        target = relationships.get(relationship_id)
        if target:
            targets_by_recipe_no[recipe_no] = _media_path(target)

    return targets_by_recipe_no


def export_photos(workbook: Path, recipes_json: Path, photo_dir: Path) -> dict[str, int]:
    recipes = json.loads(recipes_json.read_text(encoding="utf-8"))
    recipe_by_no = {int(recipe["recipe_no"]): recipe for recipe in recipes}
    photo_dir.mkdir(parents=True, exist_ok=True)

    exported = 0
    with zipfile.ZipFile(workbook) as archive:
        targets_by_recipe_no = _image_targets_by_recipe_no(archive)
        missing = sorted(set(recipe_by_no) - set(targets_by_recipe_no))
        if missing:
            raise RuntimeError(f"Missing workbook images for recipe numbers: {missing[:20]}")

        for recipe_no, recipe in sorted(recipe_by_no.items()):
            target = targets_by_recipe_no[recipe_no]
            suffix = Path(target).suffix.lower()
            extension = ".jpg" if suffix in {".jpeg", ".jpg"} else suffix
            if not extension:
                extension = ".jpg"

            filename = f"{recipe['recipe_id']}{extension}"
            output_path = photo_dir / filename
            output_path.write_bytes(archive.read(target))
            recipe["image_url"] = f"recipe_photos/{filename}"
            recipe["image_attribution"] = recipe.get("image_attribution") or ""
            exported += 1

    recipes_json.write_text(json.dumps(recipes, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"recipes": len(recipes), "exported": exported}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--recipes-json", type=Path, default=DEFAULT_RECIPES_JSON)
    parser.add_argument("--photo-dir", type=Path, default=DEFAULT_PHOTO_DIR)
    args = parser.parse_args()

    result = export_photos(args.workbook, args.recipes_json, args.photo_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
