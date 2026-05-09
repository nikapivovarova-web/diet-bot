import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:/Users/adck8/Desktop/bolshaya_tablica_receptov_s_foto_ready_for_sale.xlsx";
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("Рецепты");

const rows = sheet.getRange("A5:H204").values;
const summary = new Map();
const nonOne = [];

for (const row of rows) {
  const [num, category, title, portions, time, ingredients, description, source] = row;
  const p = String(portions ?? "").trim();
  summary.set(p, (summary.get(p) ?? 0) + 1);
  if (!/^1($|\s|,|большая|маленькая|порц|шт|боул|тарел)/i.test(p)) {
    nonOne.push({ num, category, title, portions: p, source });
  }
}

console.log("Portions summary for recipes 1-200:");
for (const [portion, count] of [...summary.entries()].sort((a, b) => String(a[0]).localeCompare(String(b[0]), "ru"))) {
  console.log(`${JSON.stringify(portion)}: ${count}`);
}
console.log(`\nNon-one-ish rows: ${nonOne.length}`);
for (const item of nonOne) {
  console.log(JSON.stringify(item));
}
