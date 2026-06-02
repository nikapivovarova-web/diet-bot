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

async function logInspect(label, config) {
  console.log(`\n## ${label}`);
  const result = await workbook.inspect(config);
  console.log(result.ndjson);
}

await logInspect("Workbook summary", {
  kind: "workbook,sheet,table",
  maxChars: 12000,
  tableMaxRows: 5,
  tableMaxCols: 10,
  tableMaxCellChars: 120,
});

await logInspect("Sheet names", {
  kind: "sheet",
  include: "id,name",
  maxChars: 3000,
});

const sheet = workbook.worksheets.getItem("Р РµС†РµРїС‚С‹");

function printRange(label, address) {
  console.log(`\n## ${label} ${address}`);
  const values = sheet.getRange(address).values;
  for (const row of values) {
    console.log(JSON.stringify(row));
  }
}

printRange("Header and first recipes", "A4:H14");
printRange("Around recipe 190", "A194:H209");
printRange("Around recipe 300", "A304:H314");
printRange("Final recipes", "A394:H404");
