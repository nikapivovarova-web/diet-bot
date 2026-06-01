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
  const workbookPath = path.resolve(args[0]);
  const previewDir = path.resolve(args[1]);
  if (!allowExternal && (!isInsideRepo(workbookPath) || !isInsideRepo(previewDir))) usage();
  return { workbookPath, previewDir };
}

const { workbookPath, previewDir } = parseArgs();
const { FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool");
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const sheetName = wb.worksheets.items[0].name;
const sh = wb.worksheets.getItem(sheetName);
const rows = sh.getRange("A5:J404").values;
const badPortions = rows.filter((r) => String(r[3] ?? "").trim() !== "1 РїРѕСЂС†РёСЏ");
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
  await fs.writeFile(path.join(previewDir, `${name}.png`), new Uint8Array(await preview.arrayBuffer()));
  console.log(`Rendered ${name}: ${range}`);
}
