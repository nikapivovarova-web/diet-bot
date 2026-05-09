from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path


FINAL = Path(r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion.xlsx")

REPLACEMENTS = {
    "1 банки": "1 банка",
    "1 пера": "1 перо",
    "1 ломтика": "1 ломтик",
    "1 крупных": "1 крупное",
    "1 средних": "1 среднее",
    "1 небольших": "1 небольшой",
    "1 небольшой или средних клубня": "1 небольшой или средний клубень",
    "0,5 средних клубня": "0,5 среднего клубня",
    "зеленый луком": "зеленым луком",
}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="polish_final_") as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(FINAL, "r") as zf:
            zf.extractall(tmp)

        sheet_path = tmp / "xl" / "worksheets" / "sheet1.xml"
        text = sheet_path.read_text(encoding="utf-8")
        replacements = 0
        for old, new in REPLACEMENTS.items():
            count = text.count(old)
            if count:
                replacements += count
                text = text.replace(old, new)
        sheet_path.write_text(text, encoding="utf-8")

        temp_output = FINAL.with_suffix(".polished.tmp.xlsx")
        if temp_output.exists():
            temp_output.unlink()
        with zipfile.ZipFile(temp_output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in tmp.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(tmp).as_posix())
        temp_output.replace(FINAL)
        print(f"Polished text replacements: {replacements}")


if __name__ == "__main__":
    main()
