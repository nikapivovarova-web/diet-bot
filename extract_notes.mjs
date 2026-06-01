import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.dirname(fileURLToPath(import.meta.url));

function usage() {
  console.error(`usage: node ${path.basename(process.argv[1])} <input-workbook> [--allow-external]`);
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
  const inputPath = path.resolve(args[0]);
  if (!allowExternal && !isInsideRepo(inputPath)) usage();
  return inputPath;
}

const inputPath = parseArgs();
const { FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool");
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("Р РµС†РµРїС‚С‹");

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
