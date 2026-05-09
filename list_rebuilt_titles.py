from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


WORKBOOK = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion_original_photos.xlsx"
)
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def col(ref: str) -> str:
    return re.sub(r"\d+", "", ref)


def cell_text(cell: ET.Element, shared: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(q("t")))
    v = cell.find(q("v"))
    if v is None or v.text is None:
        return ""
    if cell.get("t") == "s":
        return shared[int(v.text)]
    return v.text


def main() -> None:
    with zipfile.ZipFile(WORKBOOK, "r") as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(q("t"))) for si in root.findall(q("si"))]
        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    for row in sheet.findall(f"{q('sheetData')}/{q('row')}"):
        cells = {col(c.attrib["r"]): cell_text(c, shared) for c in row.findall(q("c"))}
        no = cells.get("A")
        if no and no.isdigit():
            n = int(no)
            if 201 <= n <= 400:
                print(f"{n}\t{cells.get('C', '')}")


if __name__ == "__main__":
    main()
