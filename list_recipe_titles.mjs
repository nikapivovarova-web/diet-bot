import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const path = "C:/Users/adck8/Documents/New project 2/outputs/recipes_final_400/bolshaya_tablica_receptov_s_foto_400_fixed_one_portion.xlsx";
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
const sh = wb.worksheets.getItem("Рецепты");
const rows = sh.getRange("A5:F404").values;
for (const r of rows) {
  console.log(`${r[0]}\t${r[1]}\t${r[2]}\t${String(r[5] ?? "").split("\n").slice(0, 3).join(" | ")}`);
}
