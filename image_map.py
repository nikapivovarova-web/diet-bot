from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


XLSX = Path(r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion.xlsx")
NS_D = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def build_map(xlsx: Path):
    with zipfile.ZipFile(xlsx, "r") as zf:
        drawing = ET.fromstring(zf.read("xl/drawings/drawing1.xml"))
        rels = ET.fromstring(zf.read("xl/drawings/_rels/drawing1.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"].replace("../", "xl/")
        for rel in rels.findall(q(NS_REL, "Relationship"))
    }
    result = {}
    for anchor in drawing.findall(q(NS_D, "oneCellAnchor")):
        row_node = anchor.find(f"{q(NS_D, 'from')}/{q(NS_D, 'row')}")
        blip = anchor.find(f".//{q(NS_A, 'blip')}")
        if row_node is None or blip is None:
            continue
        zero_row = int(row_node.text)
        recipe = zero_row - 3
        rid = blip.attrib.get(q(NS_R, "embed"))
        result[recipe] = {"rid": rid, "media": rel_map.get(rid), "zero_row": zero_row}
    return result


if __name__ == "__main__":
    mapping = build_map(XLSX)
    targets = [36, 43, 77, 78, 80, 82, 89, 107, 111, 118, 187, 188, 198, 199]
    for n in targets:
        print(n, mapping.get(n))
    print("mapped", len(mapping), "min", min(mapping), "max", max(mapping))
