import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.dirname(fileURLToPath(import.meta.url));

function usage() {
  console.error(`usage: node ${path.basename(process.argv[1])} <workbook> [--allow-external]`);
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
  if (args.length !== 1) usage();
  const outputPath = path.resolve(args[0]);
  if (!allowExternal && !isInsideRepo(outputPath)) usage();
  return outputPath;
}

const outputPath = parseArgs();
const { FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool");
const input = await FileBlob.load(outputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("Р РµС†РµРїС‚С‹");
const rows = sheet.getRange("A5:J204").values;

const badPortions = rows.filter((row) => String(row[3] ?? "").trim() !== "1 РїРѕСЂС†РёСЏ").length;
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
