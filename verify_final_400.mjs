import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputPath = "C:/Users/adck8/Documents/New project 2/outputs/recipes_final_400/bolshaya_tablica_receptov_s_foto_400_fixed_one_portion.xlsx";
const previewDir = "C:/Users/adck8/Documents/New project 2/outputs/recipes_final_400/previews";

const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
const sh = wb.worksheets.getItem("Рецепты");
const rows = sh.getRange("A5:J404").values;

const badPortions = rows
  .filter((r) => String(r[3] ?? "").trim() !== "1 порция")
  .map((r) => [r[0], r[2], r[3]]);
const notes = rows
  .filter((r) => String(r[9] ?? "").trim())
  .map((r) => [r[0], r[2], r[9]]);
const numbers = rows.map((r) => Number(r[0])).filter(Boolean);
const missingNumbers = [];
for (let i = 1; i <= 400; i++) {
  if (!numbers.includes(i)) missingNumbers.push(i);
}

const samples = {
  first: sh.getRange("A5:G14").values.map((r) => [r[0], r[2], r[3], String(r[5]).slice(0, 90)]),
  seam: sh.getRange("A200:G208").values.map((r) => [r[0], r[2], r[3], String(r[5]).slice(0, 90)]),
  last: sh.getRange("A395:G404").values.map((r) => [r[0], r[2], r[3], String(r[5]).slice(0, 90)]),
};

const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
});

console.log(JSON.stringify({
  rowCount: rows.length,
  badPortionsCount: badPortions.length,
  badPortions: badPortions.slice(0, 20),
  notesCount: notes.length,
  notes: notes.slice(0, 20),
  missingNumbers,
  formulaErrorScan: errors.ndjson,
  samples,
}, null, 2));

await fs.mkdir(previewDir, { recursive: true });
for (const [name, range] of [
  ["top", "A1:J20"],
  ["seam_200_201", "A198:J208"],
  ["end", "A395:J404"],
]) {
  const preview = await wb.render({
    sheetName: "Рецепты",
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(`${previewDir}/${name}.png`, new Uint8Array(await preview.arrayBuffer()));
  console.log(`Rendered ${name}: ${range}`);
}
