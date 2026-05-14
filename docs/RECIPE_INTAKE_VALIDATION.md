# Recipe Intake Validation

Date: 2026-05-14

Scope: validation for `tmp/recipe_intake/cleaned_recipes.xlsx` after the risky-recipe mapping-policy cleanup. No production curated data, nutrition rows, builder, PDF, Telegram, promo, payments, storage, source Excel, or photo assets were changed.

## Summary

- Workbook recipes: 105.
- Status before this policy pass: 105 `ready`, 0 `needs_review`.
- Status after this policy pass: 105 `ready`, 0 `needs_review`.
- Recipe-specific rewrites and mapping-policy notes were applied in the staging workbook only.
- Production import was not run.

## Workbook Counts

| Check | Before policy pass | After policy pass | Result |
|---|---:|---:|---|
| Workbook recipes | 105 | 105 | PASS |
| Ingredient rows | 845 | 845 | PASS |
| Step rows | 462 | 462 | PASS |
| QA issue rows | 175 | 188 | PASS |
| Workbook status: `ready` | 105 | 105 | PASS |
| Workbook status: `needs_review` | 0 | 0 | PASS |
| `servings_cleaned = 1` | 105/105 | 105/105 | PASS |

QA rows increased by 13 because this pass recorded explicit staging-only policy notes for the approved ambiguous-ingredient, generic-product, tomato, seasoning, and protein-anchor decisions.

## Cleanup Applied

| Recipe | Final action |
|---|---|
| `intake_032` | Ambiguous dressing normalized to Greek yogurt; crab sticks kept as an approved generic product. |
| `intake_053` | Ambiguous protein option normalized to tofu; tags, ingredient row, steps, and photo prompt updated. |
| `intake_080` | Product-specific udon wording normalized to generic udon noodles. |
| `intake_084` | Brand-specific pumpkin wording replaced with generic pumpkin cubes. |
| `intake_089` | Hummus roll moved from `main` to `snack` / light meal; hummus marked as a weak plant-protein anchor. |
| `intake_095` | Asparagus restored in ingredients, steps, tags, and photo prompt; green-bean replacement removed. |
| `intake_098` | Cherry tomatoes mapped to tomato policy, pureed tomatoes to passata, and vinegar wording cleaned. |
| `intake_100` | Prepared tomato sauce normalized to passata plus spices policy. |
| `intake_101` | Processed poultry product replaced with chicken fillet; prepared spicy tomato sauce normalized to passata plus spices. |
| `intake_062`, `intake_086`, `intake_096`, `intake_104` | Seasoning, pork-chop, egg-yolk, and chopped-tomato mapping policies recorded/normalized. |

## Validation Checks

| Check | Result |
|---|---|
| `recipe_key` values are unique | PASS |
| All recipes are `ready`; none are `needs_review` | PASS |
| Ingredients are present for every recipe | PASS |
| Steps are present for every recipe | PASS |
| Photo prompts are present for every recipe | PASS |
| Step numbering is sequential per recipe | PASS |
| `servings_cleaned = 1` for all recipes | PASS |
| No cooking-beverage ingredient terms remain in workbook recipe content | PASS |
| No strong-cheese replacement terms remain in workbook content | PASS |
| Asparagus remains asparagus in `intake_095` | PASS |
| No ambiguous tofu/egg protein wording remains | PASS |
| No ambiguous mayo/yogurt dressing wording remains | PASS |
| No brand-specific pumpkin wording remains | PASS |
| No product-specific udon wording remains | PASS |
| Processed poultry product in `intake_101` is replaced with chicken fillet | PASS |

## Dry-Run Preview Snapshot

The same existing dry-run preview script was rerun after the workbook cleanup. Because that script does not yet consume `issue_note` policy marks, it still reports some approved mappings as unmapped or semi-prepared risk.

| Preview layer | Full mapped | Near-full | Risky |
|---|---:|---:|---:|
| Before this policy pass | 68 | 3 | 34 |
| After workbook rewrites, unchanged dry-run logic | 75 | 2 | 28 |
| Policy-adjusted readiness from workbook notes | 102 | 2 | 1 |

Remaining policy-adjusted risky recipe: `intake_093`, because the large prepared mayo-soy sauce and Korean-carrot component still need either decomposition or explicit generic-product acceptance before an all-105 import.

## Import Recommendation

The staging workbook is structurally ready, but production import remains a separate task. The next import preview should read the workbook policy notes before promoting recipes into production curated data.
