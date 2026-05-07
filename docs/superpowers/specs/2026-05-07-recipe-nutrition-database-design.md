# Recipe Nutrition Database Design

## Goal

Turn the finished 400-recipe workbook into a machine-readable recipe and nutrition database for the Telegram diet bot. The bot must be able to select a recipe, read its ingredients, calculate calories, macros, vitamins, and minerals, and include those totals in the user's daily plan.

The current workbook is strong for human review: it has recipe names, categories, one-serving ingredient lists, instructions, sources, and photos. The missing layer is a normalized ingredient catalog that lets the bot calculate every dish consistently.

## Approved Direction

Use a local expanded food catalog plus recipe-to-ingredient links.

The local catalog becomes the source the bot uses at runtime. USDA FoodData Central is used as the primary reference for filling nutrient values because it provides downloadable CSV/JSON data, API access, public domain/CC0 licensing, and nutrient amounts per 100 g. Relevant references:

- https://fdc.nal.usda.gov/download-datasets/
- https://fdc.nal.usda.gov/api-guide/
- https://catalog.data.gov/dataset/fooddata-central
- https://fdc.nal.usda.gov/portal-data/external/dataDictionary

This avoids runtime dependency on network calls while keeping every value auditable.

## Data Model

### Recipes

One row per finished dish.

Required fields:

- `recipe_id`: stable bot-facing ID.
- `slot`: bot meal slot, one of `breakfast`, `main`, `snack`.
- `category_ru`: original workbook category.
- `title_ru`: recipe title.
- `servings`: expected to be `1`.
- `time_text`: original cooking time text.
- `instructions_ru`: cooking instructions.
- `source_name`: original recipe/source label.
- `source_url`: optional source URL when available.
- `image_url`: optional image URL or local image reference.
- `image_attribution`: optional image credit.

### Recipe Ingredients

One row per ingredient in a recipe. This is the main bridge between the workbook and nutrition calculations.

Required fields:

- `recipe_id`: links to `recipes.recipe_id`.
- `line_index`: ingredient order inside the recipe.
- `raw_text`: original ingredient text from the workbook.
- `ingredient_name_ru`: cleaned Russian ingredient name.
- `food_id`: normalized catalog food ID.
- `grams`: edible grams used for calculation.
- `quantity_text`: optional original quantity text, for example `1 шт.` or `0.5 ст. л.`.
- `state`: `raw`, `cooked`, `dry`, `drained`, or `as_sold`.
- `is_optional`: true only for ingredients that should not affect the calculated default recipe.
- `conversion_note`: short note when the original line needed conversion.

Rules:

- Every calculable ingredient must have `food_id` and `grams`.
- Household measures are preserved in `quantity_text`, but calculation always uses `grams`.
- Dry grains and pasta stay dry unless the recipe line explicitly says cooked.
- Canned beans, tuna, chickpeas, corn, and similar foods are treated as drained when the recipe implies normal edible use.
- Spices, salt, herbs, lemon juice, and sauces are included when gram amounts are present or can be reasonably converted.

### Foods

One row per normalized food.

Required fields:

- `food_id`: stable snake_case ID used by code.
- `name_ru`: user-facing Russian name.
- `name_en`: optional source/search name.
- `category`: bot category such as `protein`, `grains`, `vegetable`, `fruit`, `dairy`, `fat`, `nuts_seeds`, `sauce`, `spice`.
- `tags`: allergy, intolerance, diet, and caution tags.
- `roles`: optional meal-building roles when the food should be used by the planner.
- `default_state`: default calculation state.
- `source`: nutrient data source, usually `USDA FoodData Central`.
- `fdc_id`: source food ID when sourced from USDA.
- `source_description`: source food description used for matching.
- `match_confidence`: `exact`, `close`, or `manual`.

Nutrient fields are stored per 100 g:

- `energy_kcal`
- `protein_g`
- `fat_g`
- `carbohydrate_g`
- `fiber_g`
- `sugar_g`
- `sodium_mg`
- `potassium_mg`
- `calcium_mg`
- `magnesium_mg`
- `iron_mg`
- `zinc_mg`
- `vitamin_c_mg`
- `vitamin_d_mcg`
- `vitamin_b12_mcg`
- `folate_mcg_dfe`
- `vitamin_b6_mg`
- `vitamin_a_mcg_rae`
- `vitamin_e_mg`
- `omega_3_mg`

### Recipe Nutrition

One calculated row per recipe.

Required fields:

- `recipe_id`
- all nutrient totals listed above
- `ingredient_count`
- `unmatched_ingredient_count`
- `calculation_status`: `ok`, `needs_review`, or `blocked`
- `calculation_notes`

The bot should use recipe totals for quick filtering and ranking, and it should still keep ingredient-level data for shopping lists, restrictions, substitutions, and transparent meal cards.

## Bot Integration

The existing `Food`, `FoodPortion`, `Meal`, and `NutrientVector` model already supports ingredient-level calculation. The implementation should adapt the workbook data into the same internal shape instead of adding a separate calculation path.

Runtime flow:

1. Load foods from the expanded catalog.
2. Load recipes and their normalized ingredient rows.
3. Filter recipes whose ingredients violate user restrictions or conditions.
4. Build `Meal` objects from recipe ingredients.
5. Sum `FoodPortion.nutrients` for each meal and day.
6. Present dish name, ingredient list, instructions, daily totals, and shopping list.

The existing generated recipe pool can remain as a fallback while the curated 400-recipe set is being validated.

## Accuracy Rules

"Exact" means auditable and consistent enough for a nutrition bot, not laboratory certainty. The system must make assumptions explicit.

Required controls:

- No recipe is marked `ok` while it has unmatched required ingredients.
- Every food has a source or a manual note.
- Every ingredient has grams used for calculation.
- Raw/cooked/drained/dry state is explicit when it changes the nutrient basis.
- Recipe totals are recomputed from ingredient rows, not typed manually.
- QA checks flag calorie outliers, missing macros, missing key micronutrients, and suspicious gram conversions.

## Workbook Output

The next workbook version should keep the human-friendly `Рецепты` sheet and add machine-readable sheets:

- `recipes`
- `recipe_ingredients`
- `foods`
- `recipe_nutrition`
- `qa_checks`

The existing visual recipe table should remain easy to scan and edit. Machine sheets should use stable English field names so code can parse them without locale or encoding issues.

## Implementation Scope

First implementation pass:

- Parse the 400-row recipe workbook.
- Generate stable `recipe_id` values.
- Split ingredient cells into ingredient rows.
- Normalize obvious ingredient names.
- Build a draft expanded food catalog for all unique ingredients.
- Mark unmapped or ambiguous ingredients for review.
- Calculate recipe totals only where all required ingredients are mapped.
- Add tests for recipe parsing, nutrient summing, and blocked calculations with unmatched ingredients.

Later passes:

- Improve USDA matching and source notes.
- Add recipe selection/ranking from curated recipes.
- Add substitutions for lactose, gluten, allergies, and excluded foods.
- Add admin review tooling for ambiguous ingredients.

## Acceptance Criteria

- All 400 recipes are represented in `recipes`.
- All ingredient lines are represented in `recipe_ingredients`.
- Every recipe has a clear `calculation_status`.
- No recipe is marked `ok` with missing `food_id` or missing grams for required ingredients.
- Expanded `foods` covers all ingredients needed by `ok` recipes.
- Recipe nutrition totals are formula/code-derived from ingredient rows.
- Bot code can construct `Meal` objects from curated recipes and produce daily nutrient totals.
- Tests cover parsing, lookup, calculation, and restriction filtering for curated recipes.
