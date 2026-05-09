import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = "C:/Users/adck8/Documents/New project 2/outputs/recipes_final_400_rebuild/bolshaya_tablica_receptov_s_foto_400_final_opens_from_start.xlsx";
const previewDir = "C:/Users/adck8/Documents/New project 2/outputs/recipes_final_400_rebuild/photo_previews";

const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const sheetName = wb.worksheets.items[0].name;
const sh = wb.worksheets.getItem(sheetName);
const rows = sh.getRange("A5:J404").values;
const badPortions = rows.filter((r) => String(r[3] ?? "").trim() !== "1 порция");
const notes = rows.filter((r) => String(r[9] ?? "").trim());
const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
});
console.log(JSON.stringify({
  rowCount: rows.length,
  badPortionsCount: badPortions.length,
  notesCount: notes.length,
  formulaErrorScan: errors.ndjson,
}, null, 2));

await fs.mkdir(previewDir, { recursive: true });
for (const [name, range] of [
  ["targets_breakfast_36_43", "A35:J48"],
  ["targets_77_89", "A76:J94"],
  ["targets_107_118", "A106:J123"],
  ["targets_187_199", "A186:J204"],
]) {
  const preview = await wb.render({
    sheetName,
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(`${previewDir}/${name}.png`, new Uint8Array(await preview.arrayBuffer()));
  console.log(`Rendered ${name}: ${range}`);
}
