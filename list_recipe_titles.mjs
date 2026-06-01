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
  const workbookPath = path.resolve(args[0]);
  if (!allowExternal && !isInsideRepo(workbookPath)) usage();
  return workbookPath;
}

const workbookPath = parseArgs();
const { FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool");
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const sh = wb.worksheets.getItem("Р РµС†РµРїС‚С‹");
const rows = sh.getRange("A5:F404").values;
for (const r of rows) {
  console.log(`${r[0]}\t${r[1]}\t${r[2]}\t${String(r[5] ?? "").split("\n").slice(0, 3).join(" | ")}`);
}
