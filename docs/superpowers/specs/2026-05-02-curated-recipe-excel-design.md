# Curated Recipe Excel Design

## Goal

Create a first-pass Excel table with about 300 popular, tasty dishes for manual review before nutrition adaptation. The catalog should favor recognizable meals people actually want to eat, not a strict diet-only list.

## Scope

The first version is a simple review list, not a final nutrition database. It should contain dish names grouped by meal category and marked as either simple or complex.

Target distribution:

- 60 breakfasts
- 120 main dishes
- 120 snacks

## Selection Approach

Use a hybrid curation approach:

- Start from broadly popular dishes from home cooking, cafes, street food, fitness food, and international cuisines.
- Include familiar examples such as pasta, lasagna, shawarma/wraps, sandwiches, bowls, syrniki, omelets, casseroles, desserts, smoothies, hummus, and similar foods.
- Do not exclude food groups at this stage. Meat, fish, seafood, dairy, gluten, sweet dishes, fried-style dishes, and richer meals may all appear.
- Avoid near-duplicates where the difference is only a tiny ingredient change.
- Prefer dishes that can later be adapted with better portions, more protein, more vegetables, controlled sauces, or lighter cooking methods.

## Excel Columns

The file should contain exactly these columns:

1. `Категория`
2. `Блюдо`
3. `Сложность`

Allowed `Категория` values:

- `Завтрак`
- `Основное блюдо`
- `Перекус`

Allowed `Сложность` values:

- `простое`
- `сложное`

## Complexity Rules

Mark a dish as `простое` when it is quick or normal everyday cooking, has a clear process, and does not require long preparation. This includes many ordinary 20-40 minute dishes.

Mark a dish as `сложное` when it usually needs long cooking, several stages, dough, layered baking, stuffing, careful assembly, or other steps that make it slower to prepare.

## Non-Goals

Do not add calories, macros, ingredients, cuisine tags, adaptation notes, image prompts, or filtering columns in this first pass. Those will be added after manual review.

Do not generate recipe instructions or photos in this step.

## Acceptance Criteria

- The Excel file has about 300 rows.
- The category counts are close to 60 breakfasts, 120 main dishes, and 120 snacks.
- Every row has a category, dish name, and complexity value.
- Complexity values use only `простое` or `сложное`.
- The list feels mixed: home-style dishes, popular cafe food, street food, international dishes, sweet snacks, savory snacks, and everyday meals.
- The table is easy for the user to scan, edit, delete, or add to manually.
