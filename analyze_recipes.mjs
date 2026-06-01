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

const rows = sheet.getRange("A5:H204").values;
const summary = new Map();
const nonOne = [];

for (const row of rows) {
  const [num, category, title, portions, time, ingredients, description, source] = row;
  const p = String(portions ?? "").trim();
  summary.set(p, (summary.get(p) ?? 0) + 1);
  if (!/^1($|\s|,|Р±РѕР»СЊС€Р°СЏ|РјР°Р»РµРЅСЊРєР°СЏ|РїРѕСЂС†|С€С‚|Р±РѕСѓР»|С‚Р°СЂРµР»)/i.test(p)) {
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
