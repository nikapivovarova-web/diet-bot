import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.dirname(fileURLToPath(import.meta.url));

function usage() {
  console.error(`usage: node ${path.basename(process.argv[1])} <workbook> [<workbook> ...] [--allow-external]`);
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
  if (args.length === 0) usage();
  const paths = args.map((item) => path.resolve(item));
  if (!allowExternal && paths.some((item) => !isInsideRepo(item))) usage();
  return paths;
}

const paths = parseArgs();
const { FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool");

async function inspectPath(workbookPath) {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
  const sh = wb.worksheets.getItem("Р РµС†РµРїС‚С‹");
  const all = sh.getRange("A5:J404").values;
  const first = sh.getRange("A5:J204").values;
  const second = sh.getRange("A205:J404").values;
  const countNonOne = (rows) => rows.filter((r) => String(r[3] ?? "").trim() !== "1 РїРѕСЂС†РёСЏ").length;
  const countNotes = (rows) => rows.filter((r) => String(r[9] ?? "").trim()).length;
  const rowsSample = sh.getRange("A202:J208").values.map((r) => [r[0], r[2], r[3], String(r[9] ?? "").slice(0, 60)]);
  console.log(JSON.stringify({
    path: workbookPath,
    usedRange: sh.getUsedRange().address,
    nonOneAll: countNonOne(all),
    nonOneFirst: countNonOne(first),
    nonOneSecond: countNonOne(second),
    notesAll: countNotes(all),
    notesFirst: countNotes(first),
    notesSecond: countNotes(second),
    sampleAround200: rowsSample,
  }, null, 2));
}

for (const workbookPath of paths) {
  await inspectPath(workbookPath);
}
