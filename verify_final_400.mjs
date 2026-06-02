import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.dirname(fileURLToPath(import.meta.url));

function usage() {
  console.error(`usage: node ${path.basename(process.argv[1])} <workbook> <preview-dir> [--allow-external]`);
  process.exit(2);
}

function isInsideRepo(candidate) {
  const relative = path.relative(repoRoot, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function parseArgs() {
  const args = process.argv.slice(2);
  const allowExternalIndex = args.indexOf("--allow-external");
  const allowExternal = allowExternalIndex !== -1;
  if (allowExternal) args.splice(allowExternalIndex, 1);
  if (args.length !== 2) usage();
  const outputPath = path.resolve(args[0]);
  const previewDir = path.resolve(args[1]);
  if (!allowExternal && (!isInsideRepo(outputPath) || !isInsideRepo(previewDir))) usage();
  return { outputPath, previewDir };
}

const { outputPath, previewDir } = parseArgs();
const { FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool");
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
const sh = wb.worksheets.getItem("Р РµС†РµРїС‚С‹");
const rows = sh.getRange("A5:J404").values;

const badPortions = rows
  .filter((r) => String(r[3] ?? "").trim() !== "1 РїРѕСЂС†РёСЏ")
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
    sheetName: "Р РµС†РµРїС‚С‹",
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(path.join(previewDir, `${name}.png`), new Uint8Array(await preview.arrayBuffer()));
  console.log(`Rendered ${name}: ${range}`);
}
