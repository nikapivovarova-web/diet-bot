import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputPath = "C:/Users/adck8/Documents/New project 2/outputs/recipes_1_200/bolshaya_tablica_receptov_s_foto_1_200_one_portion.xlsx";
const input = await FileBlob.load(outputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("Рецепты");
const rows = sheet.getRange("A5:J204").values;

const badPortions = rows.filter((row) => String(row[3] ?? "").trim() !== "1 порция").length;
const nonemptyNotes = rows.filter((row) => String(row[9] ?? "").trim()).length;
const categories = new Map();
for (const row of rows) categories.set(row[1], (categories.get(row[1]) ?? 0) + 1);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
});

console.log(JSON.stringify({
  badPortions,
  nonemptyNotes,
  categoryCounts: Object.fromEntries(categories),
  formulaErrorScan: errors.ndjson,
}));
