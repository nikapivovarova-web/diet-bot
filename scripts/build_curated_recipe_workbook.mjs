import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const dataDir = path.join(root, "src", "diet_bot", "data");
const outputDir = path.join(root, "outputs", "curated_nutrition");
const outputPath = path.join(outputDir, "curated_recipe_nutrition_database.xlsx");

const nutrientFields = [
  "energy_kcal",
  "protein_g",
  "fat_g",
  "carbohydrate_g",
  "fiber_g",
  "sugar_g",
  "sodium_mg",
  "potassium_mg",
  "calcium_mg",
  "magnesium_mg",
  "iron_mg",
  "zinc_mg",
  "vitamin_c_mg",
  "vitamin_d_mcg",
  "vitamin_b12_mcg",
  "folate_mcg_dfe",
  "vitamin_b6_mg",
  "vitamin_a_mcg_rae",
  "vitamin_e_mg",
  "omega_3_mg",
];

async function readJson(name) {
  return JSON.parse(await fs.readFile(path.join(dataDir, name), "utf8"));
}

function colName(index) {
  let name = "";
  while (index > 0) {
    const rem = (index - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    index = Math.floor((index - 1) / 26);
  }
  return name;
}

function writeRows(sheet, rows) {
  const rowCount = rows.length;
  const colCount = rows[0]?.length ?? 1;
  sheet.getRange(`A1:${colName(colCount)}${rowCount}`).values = rows;
}

function tableRows(headers, objects) {
  return [
    headers,
    ...objects.map((row) => headers.map((header) => row[header] ?? "")),
  ];
}

const recipes = await readJson("curated_recipes.json");
const ingredients = await readJson("curated_recipe_ingredients.json");
const foods = await readJson("curated_foods.json");
const nutrition = await readJson("curated_recipe_nutrition.json");

const workbook = Workbook.create();

const recipesSheet = workbook.worksheets.add("recipes");
writeRows(
  recipesSheet,
  tableRows(
    [
      "recipe_id",
      "recipe_no",
      "slot",
      "category_ru",
      "title_ru",
      "servings",
      "time_text",
      "source_name",
      "instructions_ru",
    ],
    recipes,
  ),
);

const ingredientsSheet = workbook.worksheets.add("ingredients");
writeRows(
  ingredientsSheet,
  tableRows(
    [
      "recipe_id",
      "recipe_no",
      "line_index",
      "food_id",
      "ingredient_name_ru",
      "grams",
      "state",
      "parse_method",
      "quantity_text",
      "conversion_note",
      "raw_text",
    ],
    ingredients,
  ),
);

const foodsSheet = workbook.worksheets.add("foods");
const foodHeaders = [
  "food_id",
  "name_ru",
  "name_en",
  "category",
  "tags",
  "roles",
  "default_state",
  "source",
  "fdc_id",
  "source_description",
  "match_confidence",
  "max_per_meal_g",
  "max_per_day_g",
  ...nutrientFields,
];
writeRows(foodsSheet, [
  foodHeaders,
  ...foods.map((food) => [
    food.food_id,
    food.name_ru,
    food.name_en,
    food.category,
    (food.tags ?? []).join(", "),
    (food.roles ?? []).join(", "),
    food.default_state,
    food.source,
    food.fdc_id,
    food.source_description,
    food.match_confidence,
    food.max_per_meal_g,
    food.max_per_day_g,
    ...nutrientFields.map((field) => food.nutrients_per_100g?.[field] ?? 0),
  ]),
]);

const nutritionSheet = workbook.worksheets.add("recipe_nutrition");
writeRows(
  nutritionSheet,
  tableRows(
    [
      "recipe_id",
      "ingredient_count",
      "unmatched_ingredient_count",
      "calculation_status",
      "calculation_notes",
      ...nutrientFields,
    ],
    nutrition,
  ),
);

const okRecipes = nutrition.filter((row) => row.calculation_status === "ok").length;
const blockedRecipes = nutrition.length - okRecipes;
const manualFoods = foods.filter((row) => row.match_confidence === "manual").length;
const missingFoods = foods.filter((row) => row.match_confidence === "missing").length;
const qaSheet = workbook.worksheets.add("qa_checks");
writeRows(qaSheet, [
  ["metric", "value"],
  ["recipes", recipes.length],
  ["ingredient_rows", ingredients.length],
  ["foods", foods.length],
  ["ok_recipes", okRecipes],
  ["blocked_recipes", blockedRecipes],
  ["manual_foods", manualFoods],
  ["missing_foods", missingFoods],
  ["all_ingredients_have_food_id", ingredients.every((row) => row.food_id) ? "yes" : "no"],
  ["all_ingredients_have_grams", ingredients.every((row) => row.grams !== null && row.grams !== undefined) ? "yes" : "no"],
]);

const inspectSummary = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 6000,
  tableMaxRows: 4,
  tableMaxCols: 8,
});
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
});

for (const [sheetName, range] of [
  ["recipes", "A1:I12"],
  ["ingredients", "A1:K12"],
  ["foods", "A1:M12"],
  ["recipe_nutrition", "A1:Y12"],
  ["qa_checks", "A1:B10"],
]) {
  await workbook.render({ sheetName, range, scale: 1 });
}

await fs.mkdir(outputDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

console.log(JSON.stringify({
  outputPath,
  inspectSummary: inspectSummary.ndjson,
  formulaErrors: formulaErrors.ndjson,
}, null, 2));
