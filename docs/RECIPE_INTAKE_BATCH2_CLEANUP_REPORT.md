# Recipe Intake Batch2 Cleanup Report

Date: 2026-05-14

Scope: preprocessing/cleanup slice for the second recipe batch only. Production curated data, builder, PDF, Telegram, promo, payments, storage, photo assets, and the first `tmp/recipe_intake/cleaned_recipes.xlsx` were not edited.

## Source

- Source workbook SHA256 before cleanup: `938B4C8A13458CC1155E12C8BBD6CF4BEE0A972888A451B39F83A21CE5B1C316`
- Source workbook SHA256 after cleanup: `938B4C8A13458CC1155E12C8BBD6CF4BEE0A972888A451B39F83A21CE5B1C316`
- Source structure: one worksheet, columns `название`, `прием пищи`, `сложность`, `ингридиенты`, `рецепт`; many later rows were pasted into the first column and parsed by labels.

## Output

- Staging workbook: `tmp/recipe_intake_batch2/cleaned_recipes_batch2.xlsx`

## Counts

- Total recipes: 106
- Ready after batch2_106 manual rescue pass: 105
- Needs review after batch2_106 manual rescue pass: 1

### Primary Meal Slot

| primary_meal_slot | count |
|---|---:|
| breakfast | 15 |
| snack | 35 |
| main | 56 |

### Allowed Meal Slots

| allowed_meal_slots | count |
|---|---:|
| breakfast | 3 |
| snack | 20 |
| main | 54 |
| breakfast,snack | 15 |
| snack,main | 14 |

## Gap-Oriented Counts

These are raw workbook counts retained from cleanup; production coverage should be recomputed on the ready-only import subset after the 1 `needs_review` row is resolved or excluded.

- Dairy-free snacks: 30
- Dairy-free mains: 49
- Gluten-free mains: 43
- Egg-free breakfasts: 16
- Simple native mains: 45

### Coverage Priority

| coverage_priority | count |
|---|---:|
| dairy_free_snack | 30 |
| dairy_free_main | 40 |
| gluten_free_main | 15 |
| egg_free_breakfast | 14 |
| simple_main | 0 |
| other | 7 |

## Frequent Problems

- 70 source rows were pasted into one cell and had to be split by `Ингредиенты:` / `Рецепт:` labels.
- 82 recipes had multiple quantities inferred from incomplete source text.
- 7 recipes had product adaptations for CIS availability or gluten/dairy wording cleanup.
- Several original recipes used multi-serving quantities; all cleaned rows were normalized to `servings_cleaned = 1` with rounded amounts.
- Optional alternatives were resolved to one concrete ingredient where needed, e.g. water instead of milk, rice flour instead of wheat/oats, avocado or hummus instead of optional mayo.

## Rescue Review Outcome

Moved from `needs_review` to `ready`:

- `batch2_002`: crab sticks are supported by canonical `crab_sticks`; no artificial decomposition.
- `batch2_005`: crab sticks are supported by canonical `crab_sticks`; `плавленый сыр` was replaced with `творожный сыр`.
- `batch2_052`: slot/effort/one-portion quantities accepted as conservative editorial correction; tomato sauce replaced with `томаты в собственном соку`.
- `batch2_053`, `batch2_055`, `batch2_060`, `batch2_102`: tomato sauce replaced with `томаты в собственном соку` using the same gram estimate.
- `batch2_083`, `batch2_084`, `batch2_085`, `batch2_086`: sprats are supported by canonical `sprats`, following the existing canned fish pattern. Oil is discarded and the recipe grams are drained fish weight.
- `batch2_106`: manual rescue accepted the existing quantities and breakfast/snack/simple/skillet metadata by comparison with ready `batch2_102` (lazy pizza on lavash), `batch2_104` (hot sandwich), and chicken sandwich/roll rows.

Still `needs_review`:

- `batch2_008` Яичные маффины с овощами: exact production duplicate `r007_yaichnye_maffiny_s_ovoschami`; do not import as a new recipe.

Policy choices:

- Tomato sauce: replaced with `томаты в собственном соку`; no alternate prepared-sauce wording is used in batch2 workbook edits.
- Sprats: allowed only through canonical `sprats`; the mapping uses a close canned-in-oil/drained-solids fish proxy, and workbook grams are drained fish weight with oil discarded.
- Crab sticks: allowed only where canonical `crab_sticks` mapping exists; no decomposition.
- Processed cheese: replaced with `творожный сыр` in `batch2_005`.
- `batch2_106`: tomato sauce remains normalized to `томаты в собственном соку`; bread 60 g, tomato base 120 g, cheese 30 g, tomato 120 g, and chicken 90 g are documented as ready-pattern comparisons rather than new inferred policy.

## Coverage Impact vs. 4-Week Audit

The audit in `docs/RECIPE_4_WEEK_COVERAGE_AUDIT.md` identified the largest strict SIMPLE gaps as dairy-free snacks, dairy-free mains, gluten/wheat-free mains, egg-free high-protein breakfasts, and extra native SIMPLE mains.

- This batch contributes 30 dairy-free snack-capable recipes, directly addressing the thinnest pool.
- It adds 49 dairy-free main-capable recipes and 43 gluten-free main-capable recipes, mostly from meat/fish/legume mains and snack-light-main formats.
- It adds 16 egg-free breakfast-capable recipes, though not all are high-protein; protein QA is still needed before production import.
- It adds 45 simple native mains, increasing buffer for unrestricted SIMPLE plans.

Conclusion: batch2 is useful for the documented gaps, especially dairy-free snacks and simple mains, but should remain staging until nutrition/protein checks and duplicate handling for the 1 `needs_review` row are complete. Only the 105 `ready` rows should be considered for the next importer dry-run.

## Validation

- recipe_key unique: yes
- servings_cleaned all 1: yes
- ready rows have required fields, ingredients, steps, photo_prompt: yes
- source Excel SHA256 before/after matched: yes
- workbook opens with sheets `recipes`, `ingredients`, `steps`, `qa_issues`: yes
- all workbook sheets rendered to PNG preview: yes
- formula/error scan: 0 matches
- rescue-fix targeted validation: invalid ingredient names 0; 500-600 g one-portion rows 0; production duplicates in ready rows 0; disallowed prepared-product policy rows in ready rows 0; fish/vegetarian/fish_free conflicts in ready rows 0
