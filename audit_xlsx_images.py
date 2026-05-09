from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS_D = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def image_map(xlsx: Path) -> dict[int, dict[str, str | int]]:
    with zipfile.ZipFile(xlsx, "r") as zf:
        drawing = ET.fromstring(zf.read("xl/drawings/drawing1.xml"))
        rels = ET.fromstring(zf.read("xl/drawings/_rels/drawing1.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"].replace("../", "xl/").lstrip("/")
            for rel in rels.findall(q(NS_REL, "Relationship"))
        }
        result: dict[int, dict[str, str | int]] = {}
        for anchor in drawing.findall(q(NS_D, "oneCellAnchor")):
            row_node = anchor.find(f"{q(NS_D, 'from')}/{q(NS_D, 'row')}")
            blip = anchor.find(f".//{q(NS_A, 'blip')}")
            if row_node is None or blip is None:
                continue
            recipe_no = int(row_node.text) - 3
            rid = blip.attrib.get(q(NS_R, "embed"))
            media = rel_map.get(rid or "")
            if media:
                data = zf.read(media)
                result[recipe_no] = {
                    "rid": rid or "",
                    "media": media,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
        return result


def main() -> None:
    paths = [Path(arg) for arg in sys.argv[1:]]
    for path in paths:
        mapping = image_map(path)
        missing = [n for n in range(1, 401) if n not in mapping]
        second_missing = [n for n in range(201, 401) if n not in mapping]
        sizes = [int(item["size"]) for item in mapping.values()]
        print(
            json.dumps(
                {
                    "path": str(path),
                    "mapped": len(mapping),
                    "missing_all": missing[:30],
                    "missing_201_400": second_missing,
                    "avg_size": round(sum(sizes) / len(sizes), 1) if sizes else 0,
                    "min_size": min(sizes) if sizes else 0,
                    "max_size": max(sizes) if sizes else 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
