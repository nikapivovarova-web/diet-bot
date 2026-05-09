from __future__ import annotations

import copy
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ORIGINAL = Path(r"C:\Users\adck8\Desktop\bolshaya_tablica_receptov_s_foto_ready_for_sale.xlsx")
FINAL = Path(r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion.xlsx")

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("", NS_MAIN)
ET.register_namespace("r", NS_REL)


def q(tag: str) -> str:
    return f"{{{NS_MAIN}}}{tag}"


def extract_file(xlsx: Path, member: str) -> bytes:
    with zipfile.ZipFile(xlsx, "r") as zf:
        return zf.read(member)


def main() -> None:
    original_sheet = ET.fromstring(extract_file(ORIGINAL, "xl/worksheets/sheet1.xml"))
    original_hyperlinks = original_sheet.find(q("hyperlinks"))
    if original_hyperlinks is None:
        raise RuntimeError("Original workbook has no hyperlinks block.")
    original_rels = extract_file(ORIGINAL, "xl/worksheets/_rels/sheet1.xml.rels")

    with tempfile.TemporaryDirectory(prefix="restore_hyperlinks_") as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(FINAL, "r") as zf:
            zf.extractall(tmp)

        sheet_path = tmp / "xl" / "worksheets" / "sheet1.xml"
        final_tree = ET.parse(sheet_path)
        final_root = final_tree.getroot()

        existing = final_root.find(q("hyperlinks"))
        if existing is not None:
            insert_at = list(final_root).index(existing)
            final_root.remove(existing)
        else:
            page_margins = final_root.find(q("pageMargins"))
            insert_at = list(final_root).index(page_margins) if page_margins is not None else len(list(final_root))
        final_root.insert(insert_at, copy.deepcopy(original_hyperlinks))

        drawing = final_root.find(q("drawing"))
        if drawing is not None:
            drawing.set(f"{{{NS_REL}}}id", "rId401")

        final_tree.write(sheet_path, encoding="utf-8", xml_declaration=True)
        rels_path = tmp / "xl" / "worksheets" / "_rels" / "sheet1.xml.rels"
        rels_path.write_bytes(original_rels)

        temp_output = FINAL.with_suffix(".hyperlinks.tmp.xlsx")
        if temp_output.exists():
            temp_output.unlink()
        with zipfile.ZipFile(temp_output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in tmp.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(tmp).as_posix())
        temp_output.replace(FINAL)
        print("Restored hyperlinks from original workbook.")


if __name__ == "__main__":
    main()
