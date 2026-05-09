import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const paths = [
  "C:/Users/adck8/Documents/New project 2/outputs/recipes_1_200/bolshaya_tablica_receptov_s_foto_1_200_one_portion.xlsx",
  "C:/Users/adck8/Documents/New project 2/outputs/recipe_workbook/bolshaya_tablica_receptov_s_foto_ready_for_sale_rows_200_404_fixed.xlsx",
  "C:/Users/adck8/Documents/New project 2/outputs/recipe_workbook/bolshaya_tablica_receptov_s_foto_ready_for_sale_rows_200_400_fixed.xlsx",
  "C:/Users/adck8/Desktop/bolshaya_tablica_receptov_s_foto_ready_for_sale.xlsx",
];

async function inspectPath(path) {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
  const sh = wb.worksheets.getItem("Рецепты");
  const all = sh.getRange("A5:J404").values;
  const first = sh.getRange("A5:J204").values;
  const second = sh.getRange("A205:J404").values;
  const countNonOne = (rows) => rows.filter((r) => String(r[3] ?? "").trim() !== "1 порция").length;
  const countNotes = (rows) => rows.filter((r) => String(r[9] ?? "").trim()).length;
  const rowsSample = sh.getRange("A202:J208").values.map((r) => [r[0], r[2], r[3], String(r[9] ?? "").slice(0, 60)]);
  console.log(JSON.stringify({
    path,
    usedRange: sh.getUsedRange().address,
    nonOneAll: countNonOne(all),
    nonOneFirst: countNonOne(first),
    nonOneSecond: countNonOne(second),
    notesAll: countNotes(all),
    notesFirst: countNotes(first),
    notesSecond: countNotes(second),
    sampleAround200: rowsSample,
  }, null, 2));
}

for (const path of paths) {
  await inspectPath(path);
}
