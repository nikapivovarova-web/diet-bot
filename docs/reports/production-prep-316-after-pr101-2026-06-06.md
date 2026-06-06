# Production-prep for 316 second-pass candidates after PR #101

## Scope and provenance

- Truth surface: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Worktree: `C:\Users\adck8\Documents\codex-worktrees\production-prep-316-candidates`
- Branch: `codex/production-prep-316-candidates`
- Base: `origin/master` at `94168e4a81e1b6f34d2de5a76e8cba1182a56af3`
- Source CSV: `C:\Users\adck8\Documents\New project 2\tmp\candidate-recipe-review\second-pass\suitable_after_second_pass.csv`
- Photo source checked: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\tmp\parallel-photo-prep-317\photo-work`
- No bot, Telegram polling, production database, payments/provider, deploy, merge, or production import was run.

## Baseline

- `curated_recipes.json`: 710 rows
- `curated_recipe_ingredients.json`: 710 unique recipe IDs
- `curated_recipe_nutrition.json`: 710 unique recipe IDs
- Missing metadata: 0
- Local recipe photo files: 710

## Candidate input

- Source CSV rows: 317
- Duplicate excluded: `c0835` / `салат цезарь` -> `r690_salat_tsezar`
- Candidates processed after exclusion: 316

## Tooling changes in this branch

- `second_pass_suitable_csv` importer path now handles bullet-separated ingredient text instead of only newline/dash rows.
- Household units are normalized where deterministic: `kg -> g`, `l -> ml`, `tbsp/tsp -> ml`, and common count units such as garlic cloves, eggs, onions, tomatoes, peppers, herbs, and bread slices to grams by conservative defaults.
- Importer alias mapping can use generated aliases from the current curated food definitions, with explicit overrides for common generic terms such as oil, generic cheese, and bell pepper.
- Nutrition dry-run treats ml as gram-equivalent for importer audit calculations so sodium can be calculated for liquid ingredients.

## Readiness result

- `import_ready`: 38
- Not import-ready: 278
- Parsed ingredients: 179 / 316
- Mapped ingredients: 55 / 316
- Nutrition calculated, including sodium: 52 / 316
- Valid servings: 316 / 316
- Photos found: 220 / 316
- Photos missing: 96 / 316
- Production-shaped preview rows generated under ignored tmp only: 38 recipes, 146 ingredient rows, 38 nutrition rows
- Production data imported: 0

## Blockers

Primary candidate blocker counts:

- `ambiguous_ingredient_text`: 100
- `missing_photo`: 96
- `unknown_ingredient_alias`: 79
- `missing_grams`: 3

Exact blocker occurrences across candidates:

- `no_ingredients_to_map`: 137
- `ambiguous_ingredient_text`: 136
- `unknown_ingredient_alias`: 124
- `missing_photo`: 96
- `missing_grams`: 3
- `missing_ingredients`: 1

Top unmapped ingredient names:

- `Ингредиенты`: 9
- `вода/бульон`: 4
- `крахмал`: 4
- `морепродукты`: 3
- `горошек`: 3
- `сыр тёртый`: 3
- `фарш свиной`: 3
- `крахмал 1 ст. л. + вода`: 3
- `рис варёный`: 3
- `пшеничная лапша`: 3
- `слоёное тесто`: 3
- `Гречка`: 3
- `несолёный овощной или куриный бульон`: 2
- `готовая фасоль с бульоном`: 2
- `лук красный`: 2

## Decision

The import gate is not met. `import_ready=38` is below the required minimum of 150, so this branch must remain a tooling/report PR and must not apply a small import PR for 5, 9, 19, or 38 recipes.

## Exact next rules to unblock a future bulk import

1. Generate or attach missing photos for the 96 candidates with `photo_status=missing`.
2. Normalize the 100 primary `ambiguous_ingredient_text` candidates into one ingredient per line or bullet segment with an explicit amount.
3. Add safe aliases for the repeated unmapped ingredients above only after choosing the canonical FoodBalance food ID.
4. Split non-ingredient headers such as `Ингредиенты` and `Основа` out of ingredient lists before parsing.
5. Resolve mixed expressions such as `крахмал 1 ст. л. + вода` into separate ingredient rows with grams/ml.
6. Re-run the importer dry-run and apply production rows only if at least 150 candidates are `import_ready`.
