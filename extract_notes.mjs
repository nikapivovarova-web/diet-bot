import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:/Users/adck8/Desktop/bolshaya_tablica_receptov_s_foto_ready_for_sale.xlsx";
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("Рецепты");

const rows = sheet.getRange("A5:J204").values;
for (const row of rows) {
  const note = String(row[9] ?? "").trim();
  if (note) {
    console.log(JSON.stringify({
      num: row[0],
      title: row[2],
      portions: row[3],
      ingredients: row[5],
      description: row[6],
      note,
    }));
  }
}
