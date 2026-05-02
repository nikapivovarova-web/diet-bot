# Curated Recipe Excel Design

## Goal

Create a first-pass Excel table with about 300 popular, tasty dishes for manual review before nutrition adaptation. The catalog should favor recognizable meals people actually want to eat, but every dish should be realistic for a simple recipe bot.

## Scope

The first version is a simple review list, not a final nutrition database. It should contain dish names grouped by meal category. Every selected dish should usually be cookable in about 40 minutes or less by a normal home cook.

Target distribution:

- 60 breakfasts
- 120 main dishes
- 120 snacks

## Selection Approach

Use a hybrid curation approach:

- Start from broadly popular dishes from home cooking, cafes, street food, fitness food, and international cuisines.
- Include familiar foods such as pasta, wraps, sandwiches, bowls, syrniki, omelets, quick soups, salads, smoothies, hummus, quick desserts, and similar meals.
- Do not exclude food groups at this stage. Meat, fish, seafood, dairy, gluten, sweet dishes, fried-style dishes, and richer meals may all appear.
- Avoid dishes that usually require long cooking, dough work, stuffing, careful multi-stage assembly, or long simmering.
- Avoid near-duplicates where the difference is only a tiny ingredient change.
- Prefer dishes that can later be adapted with better portions, more protein, more vegetables, controlled sauces, or lighter cooking methods.

Examples to avoid in this first table:

- homemade dumplings, pelmeni, khinkali, manti, vareniki
- borscht, solyanka, shurpa, lagman, long-simmered soups
- classic layered lasagna, complex casseroles, homemade pizza dough
- slow roasts, stuffed cabbage, dolma, long stews

## Excel Columns

The file should contain exactly these columns:

1. `Категория`
2. `Блюдо`

Allowed `Категория` values:

- `Завтрак`
- `Основное блюдо`
- `Перекус`

## Time Rule

Every dish in the table should be a practical quick recipe: usually up to about 40 minutes total cooking time, assuming normal store-bought ingredients such as tortillas, pita, bread, pasta, canned beans, canned tuna, prepared yogurt, or ready sauces when appropriate.

## Non-Goals

Do not add calories, macros, ingredients, cuisine tags, adaptation notes, image prompts, complexity labels, or filtering columns in this first pass. Those will be added after manual review.

Do not generate recipe instructions or photos in this step.

## Acceptance Criteria

- The Excel file has 300 rows.
- The category counts are 60 breakfasts, 120 main dishes, and 120 snacks.
- Every row has a category and dish name.
- The file does not contain a complexity column.
- The list avoids obviously long or complex recipes such as homemade pelmeni, borscht, khinkali, classic lasagna, dolma, and long stews.
- The list feels mixed: home-style dishes, popular cafe food, street food, international dishes, sweet snacks, savory snacks, and everyday meals.
- The table is easy for the user to scan, edit, delete, or add to manually.
