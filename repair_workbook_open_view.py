import shutil
from copy import copy
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.views import Selection


SOURCE = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild"
    r"\bolshaya_tablica_receptov_s_foto_400_fixed_one_portion_rebuilt_generated_checked.xlsx"
)

OUTPUT = Path(
    r"C:\Users\adck8\Documents\New project 2\outputs\recipes_final_400_rebuild"
    r"\bolshaya_tablica_receptov_s_foto_400_final_opens_from_start.xlsx"
)
DESKTOP_COPY = Path(r"C:\Users\adck8\Desktop\recepty_400_final.xlsx")


def main() -> None:
    wb = load_workbook(SOURCE)
    wb.active = 0

    for ws in wb.worksheets:
        ws.sheet_state = "visible"
        ws.freeze_panes = "A5"
        ws.sheet_view.showGridLines = True
        ws.sheet_view.zoomScale = 75
        ws.sheet_view.zoomScaleNormal = 75
        ws.sheet_view.topLeftCell = "A1"
        ws.sheet_view.selection = [Selection(activeCell="A1", sqref="A1")]
        if ws.sheet_view.pane is not None:
            ws.sheet_view.pane.topLeftCell = "A5"
            ws.sheet_view.pane.activePane = "bottomLeft"
        ws.views.sheetView[0] = copy(ws.sheet_view)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUTPUT)
    shutil.copy2(OUTPUT, DESKTOP_COPY)
    print(OUTPUT)
    print(DESKTOP_COPY)


if __name__ == "__main__":
    main()
