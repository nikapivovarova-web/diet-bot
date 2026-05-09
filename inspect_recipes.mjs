import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:/Users/adck8/Desktop/bolshaya_tablica_receptov_s_foto_ready_for_sale.xlsx";

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

const sheet = workbook.worksheets.getItem("Рецепты");

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
