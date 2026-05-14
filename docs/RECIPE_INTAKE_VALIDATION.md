# Recipe Intake Validation

Scope: final validation for `tmp/recipe_intake/cleaned_recipes.xlsx`. No production curated data, builder, PDF, Telegram, promo, payments, storage, original Excel, or photo assets were changed.

## Summary

- Workbook recipes: 105.
- Status before final pass: 102 `ready`, 3 `needs_review`.
- User decisions applied in this final pass: 3 recipes.
- Status after final pass: 105 `ready`, 0 `needs_review`.
- All intake review decisions are now represented in the staging workbook.
- Production import was not run.

## Workbook Counts

| Check | Before final pass | After final pass | Result |
|---|---:|---:|---|
| Workbook recipes | 105 | 105 | PASS |
| Ingredient rows | 842 | 845 | PASS |
| Step rows | 462 | 462 | PASS |
| QA issue rows | 175 | 175 | PASS |
| Workbook status: `ready` | 102 | 105 | PASS |
| Workbook status: `needs_review` | 3 | 0 | PASS |
| `ready` recipes with `review` QA rows | 0 | 0 | PASS |

Ingredient rows increased by 3 because `intake_073` replaced one mixed-vegetable row and one alcohol cooking component with four concrete vegetables plus lemon juice.

## Final Cleanup Applied

| Recipe | Final action |
|---|---|
| `intake_073` | Removed the alcohol cooking component, replaced the frozen vegetable mix with zucchini 40 g, bell pepper 30 g, carrot 20 g, and onion 10 g, added lemon juice 10 g, and updated ingredients, steps, photo prompt, and status. |
| `intake_078` | Replaced prepared sauce 20 g with milk 15 g, butter 3 g, and flour 2 g by merging milk and butter into existing rows and adding flour; updated ingredients, steps, photo prompt, and status. |
| `intake_093` | Kept frozen/prepared falafel as a staging-ready semi-prepared ingredient, marked it as the plant protein anchor, and updated status. |

## Validation Checks

| Check | Result |
|---|---|
| `servings_cleaned = 1` for all recipes | PASS |
| No explicit cooking alcohol ingredient remains in recipe content | PASS |
| No `ready` recipes have `review` QA rows | PASS |
| `recipe_key` values are unique | PASS |
| Ingredients are present for every recipe | PASS |
| Steps are present for every recipe | PASS |
| Photo prompts are present for every recipe | PASS |
| Workbook opens successfully | PASS |
| All four sheets render successfully | PASS |

## Import Recommendation

The staging workbook has no remaining `needs_review` recipes. A production import can be considered only in a separate import task; this pass did not import or modify production data.
