# Production-prep for second-pass candidates after PR #101 and PR #102 review fix

## Scope and provenance

- Truth surface: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Worktree: `C:\Users\adck8\Documents\codex-worktrees\production-prep-316-candidates`
- Branch: `codex/production-prep-316-candidates`
- Base: `origin/master` at `94168e4a81e1b6f34d2de5a76e8cba1182a56af3`
- Source CSV: `C:\Users\adck8\Documents\New project 2\tmp\candidate-recipe-review\second-pass\suitable_after_second_pass.csv`
- Photo source checked: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\tmp\parallel-photo-prep-317\photo-work`
- Fresh dry-run output: `tmp\production-prep-316-pr102`
- No bot, Telegram polling, production database, payments/provider, deploy, merge, or production import was run.

## Baseline

- `curated_recipes.json`: 710 rows
- `curated_recipe_ingredients.json`: 710 unique recipe IDs
- `curated_recipe_nutrition.json`: 710 unique recipe IDs
- Missing metadata: 0
- Local recipe photo files: 710

## Candidate input

- Source CSV rows: 317
- Exact title duplicate flagged: 1 (`c0835` -> `r690_salat_tsezar`)
- Candidates audited: 317

## Tooling changes in this branch

- `second_pass_suitable_csv` importer path handles bullet-separated ingredient text instead of only newline/dash rows.
- Household units are normalized where deterministic: `kg -> g`, `l -> ml`, `tbsp/tsp -> ml`, and common count units such as garlic cloves, eggs, onions, tomatoes, peppers, herbs, and bread slices to grams by conservative defaults.
- Importer alias mapping can use generated aliases from the current curated food definitions, with explicit overrides for common generic terms such as oil, generic cheese, and bell pepper.
- Unsafe alias prefix fallback is narrowed: exact aliases still map, safe reordered aliases still map when the full ingredient name is represented, and a multi-word alias no longer maps when it is only the prefix of a longer combined ingredient string.
- Nutrition dry-run treats ml as gram-equivalent for importer audit calculations so sodium can be calculated for liquid ingredients.

## PR #102 content-blocker fix

- The 157 imported recipe cards `r711-r868` except `r856` now have non-empty `time_text`, non-placeholder `short_description_ru`, and nonzero active time.
- Source CSV did not provide exact time values for this import, so recipe cards use a conservative deterministic fallback recorded in `import_metadata.time_policy`.
- Default time policy:
  - `second_pass_default:no_cook_or_quick_assembly`: 15 active / 0 passive minutes for salads, tartars, muesli, and direct mixing/assembly without cooking.
  - `second_pass_default:breakfast_or_snack`: 20 active / 0 passive minutes for breakfast/snack recipes without oven, simmering, soup, or stew signals.
  - `second_pass_default:stovetop_main`: 25 active / 10 passive minutes for regular main dishes without longer passive cooking signals.
  - `second_pass_default:baked_or_simmered_main`: 20 active / 25 passive minutes for oven, baked, simmered, soup, stew, or long-cooking signals.
- Applied distribution after the fix: baked/simmered `93`, stovetop main `42`, no-cook/quick assembly `17`, breakfast/snack `5`.
- User-facing recipe fields for the imported batch were sanitized for control characters, replacement characters, and `???` placeholders.

## Readiness result

- Stale committed report before PR #102 review fix said `import_ready=38`.
- Fresh exact-head dry-run before the mapping fix showed: rows 317, `import_ready=39`, photos missing 97, parsed 180, mapped 56, nutrition calculated 53, production preview rows 39.
- Fresh dry-run after the unsafe prefix fallback fix:
  - `import_ready`: 25
  - Not import-ready: 292
  - Parsed ingredients: 180 / 317
  - Mapped ingredients: 39 / 317
  - Nutrition calculated, including sodium: 37 / 317
  - Valid servings: 317 / 317
  - Photos found: 220 / 317
  - Photos missing: 97 / 317
  - `needs_review`: 195
  - `blocked`: 97
  - C01-compatible `import_ready`: 12
  - Production-shaped preview rows generated under ignored tmp only: 25 recipes, 70 ingredient rows, 25 nutrition rows, 25 photo-manifest rows
  - Production data imported: 0

## Blockers

Exact blocker occurrences across candidates:

- `unknown_ingredient_alias`: 141
- `no_ingredients_to_map`: 137
- `ambiguous_ingredient_text`: 136
- `missing_photo`: 97
- `missing_grams`: 2
- `missing_ingredients`: 1

Review reasons by exact reason:

- `duplicate_risk_exact_title_match`: 1

Top unmapped ingredient names from the fresh dry-run:

- low-sodium soy sauce plus water expression: 11
- ingredient-list header: 9
- starch: 4
- water/broth: 4
- pureed tomatoes: 3
- nuts: 3
- grated cheese: 3
- seafood: 3
- puff pastry: 3
- buckwheat: 3
- peas: 3
- pork mince: 3
- starch plus water expression: 3
- cooked rice: 3
- wheat noodles: 3

## Decision

The import gate is not met. `import_ready=25` after the prefix fallback fix is below the required minimum of 150, so this branch must remain a tooling/report PR and must not apply a small import PR for 5, 9, 19, 25, 38, or 39 recipes.

## Exact next rules to unblock a future bulk import

1. Generate or attach missing photos for the 97 candidates with `photo_status=missing`.
2. Normalize the primary `ambiguous_ingredient_text` candidates into one ingredient per line or bullet segment with an explicit amount.
3. Add safe aliases for the repeated unmapped ingredients above only after choosing the canonical FoodBalance food ID.
4. Split non-ingredient headers such as ingredient-list headers and base-section headers out of ingredient lists before parsing.
5. Resolve mixed expressions such as starch plus water, soy sauce plus water, or broth/water into separate ingredient rows with grams/ml.
6. Re-run the importer dry-run and apply production rows only if at least 150 candidates are `import_ready`.
