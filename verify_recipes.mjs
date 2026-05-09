import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputPath = "C:/Users/adck8/Documents/New project 2/outputs/recipes_1_200/bolshaya_tablica_receptov_s_foto_1_200_one_portion.xlsx";
const previewDir = "C:/Users/adck8/Documents/New project 2/outputs/recipes_1_200/previews";

const input = await FileBlob.load(outputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("Рецепты");

const rows = sheet.getRange("A5:H204").values;
const badPortions = rows
  .filter((row) => String(row[3] ?? "").trim() !== "1 порция")
  .map((row) => ({ num: row[0], title: row[2], portions: row[3] }));

console.log(`Bad portions in recipes 1-200: ${badPortions.length}`);
if (badPortions.length) console.log(JSON.stringify(badPortions.slice(0, 20), null, 2));

for (const address of ["A4:H14", "A21:H24", "A99:H105", "A194:H204"]) {
  console.log(`\n## ${address}`);
  const values = sheet.getRange(address).values;
  for (const row of values) {
    console.log(JSON.stringify(row));
  }
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log("\nFormula/value errors:");
console.log(errors.ndjson);

await fs.mkdir(previewDir, { recursive: true });
for (const [name, range] of [
  ["top", "A1:J25"],
  ["middle", "A99:J115"],
  ["end_1_200", "A190:J204"],
]) {
  const preview = await workbook.render({
    sheetName: "Рецепты",
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(`${previewDir}/${name}.png`, new Uint8Array(await preview.arrayBuffer()));
  console.log(`Rendered ${name}: ${range}`);
}
