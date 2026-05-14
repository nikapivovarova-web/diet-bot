# Recipe Intake Import Preview

Date: 2026-05-14

Scope: dry-run transform of `tmp/recipe_intake/cleaned_recipes.xlsx` only. No production curated recipe, ingredient, nutrition, photo, builder, PDF, Telegram, promo, payments, or storage data was modified.

## Inputs Read

- `tmp/recipe_intake/cleaned_recipes.xlsx`
- Intake docs under `docs/`
- Current read-only curated data under `src/diet_bot/data/`

Temporary dry-run artifacts were written under ignored `tmp/recipe_intake/` and are intentionally not part of the committed result.

## Workbook Counts

- Total recipes: 105
- Status: 105 `ready`, 0 `needs_review`
- `servings_cleaned = 1`: 105/105
- Ingredient rows: 845
- Step rows: 462
- QA rows retained in workbook: 188, with 103 notes and 85 warnings
- Meal slots: 52 main, 22 breakfast, 31 snack
- Cooking effort: 89 simple, 16 interesting
- Simple by slot: 42 main, 17 breakfast, 30 snack
- Interesting by slot: 10 main, 5 breakfast, 1 snack

## Validation

Passes:

- `recipe_key` uniqueness inside workbook: pass, 0 duplicates
- Duplicate check against existing curated recipes by `recipe_key`/`recipe_id`: 0 matches
- Duplicate check against existing curated recipes by exact title: 0 matches
- Duplicate check against existing curated recipes by normalized repaired title: 0 matches
- Valid `meal_slot`: 105/105
- Valid `cooking_effort`: 105/105
- Ingredient parseability: 845/845 parseable for dry-run purposes
- Step parseability: 462/462 parseable, step numbering sequential per recipe
- `photo_prompt_ru`: present for 105/105
- Cooking-beverage ingredient terms: 0 exact hits in recipe content

Protein anchor warnings where the unchanged preview expects an anchor but none is marked:

- `intake_035` - Кукурузная каша, breakfast
- `intake_042` - Банановые оладьи с шоколадной начинкой, breakfast
- `intake_043` - Овсяные блинчики, breakfast
- `intake_059` - Писто, main
- `intake_091` - Картофельные зразы с белыми грибами, main
- `intake_092` - Суп-пюре из батата, main

`intake_089` is no longer a main-slot anchor warning because it was re-slotted to snack/light meal.

## Nutrition Readiness

Current unchanged dry-run logic:

- Mapped ingredient rows: 824/845, 97.5%
- Mapped unique ingredient names: 316/331, 95.5%
- Preview mapped food IDs used: 138
- Full mapped recipes: 75
- Near-full mapped recipes: 2
- Risky for nutrition readiness: 28

Policy-adjusted readiness after applying workbook `issue_note` decisions:

- Full mapped recipes: 102
- Near-full mapped recipes: 2
- Risky for nutrition readiness: 1

The difference exists because this cleanup intentionally did not add production nutrition rows or import aliases. The unchanged preview still flags approved staging policies such as cod liver, grapes/kishmish, buckwheat, chicken liver, split peas, trout, generic udon, canned/chopped tomatoes, sun-dried tomatoes, soy sauce, explicit-gram mayo, crab sticks, pesto, falafel, and teriyaki.

## Remaining Risk

Policy-adjusted remaining risky recipe:

- `intake_093` - falafel itself is approved, but the large prepared mayo-soy sauce and Korean-carrot component still need either decomposition or explicit generic-product acceptance before all-105 production import.

Near-full but not risky:

- `intake_010` - sumac remains a tiny unmapped spice gap.
- `intake_091` - frying oil wording remains approximate.

## Coverage Impact

Updated preview counts:

- Breakfast/snack/main: 22 / 31 / 52
- Simple/interesting: 89 / 16
- Simple high-protein native main, strict proxy: 19 recipes
- High-protein snack/light-main candidates: 5 recipes, all 5 also pass snack-as-main fallback
- Native SIMPLE main eligible increase on the full dry-run: +26
- Snack-as-main fallback increase on the full dry-run: +5
- Estimated SIMPLE main-builder eligible pool increase: +31, moving latest smoke from about 55 to about 86 if production mappings and import checks are accepted

## Recommended Import Plan

Do not import in this task.

For the next import-preview task:

1. Teach the preview/import process to consume the staging workbook policy notes, or add production nutrition aliases in a separate mapping-only change.
2. Keep `intake_093` out of an all-105 import until its prepared sauce/vegetable product policy is resolved.
3. Generate no photos until the separate media/import slice.

## Conclusion

The intake workbook remains structurally clean and has 105 ready recipes. The approved risky-recipe policies are now represented in staging, moving the policy-adjusted readiness from 68/3/34 to 102/2/1. Production import remains intentionally deferred.
