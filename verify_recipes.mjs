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
const input = await FileBlob.load(outputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("Р РµС†РµРїС‚С‹");

const rows = sheet.getRange("A5:H204").values;
const badPortions = rows
  .filter((row) => String(row[3] ?? "").trim() !== "1 РїРѕСЂС†РёСЏ")
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
    sheetName: "Р РµС†РµРїС‚С‹",
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(path.join(previewDir, `${name}.png`), new Uint8Array(await preview.arrayBuffer()));
  console.log(`Rendered ${name}: ${range}`);
}
