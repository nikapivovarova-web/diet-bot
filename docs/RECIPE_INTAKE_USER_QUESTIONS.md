# Recipe Intake User Questions

Date: 2026-05-14

Scope: user-facing question status for `tmp/recipe_intake/cleaned_recipes.xlsx` after applying the approved risky-recipe mapping and rewrite decisions. This file does not approve production imports, change production nutrition data, edit the source Excel, or generate photos.

## Current Status

- Workbook total: 105 recipes.
- Ready after policy pass: 105 recipes.
- Still `needs_review`: 0 recipes.
- Remaining user questions for this staging cleanup: none.

## Resolved Questions

| Decision area | Resolution |
|---|---|
| Cod liver recipes | Kept; drained/no-extra-jar-oil policy recorded unless a recipe explicitly uses oil. |
| Normal product mappings | Buckwheat, grapes/kishmish, cornmeal/polenta, chicken liver, split peas, trout, basmati rice, tomato variants, sun-dried tomatoes, pumpkin, asparagus, egg yolk, pork chop, and mixed-spice seasoning policies recorded. |
| Standard condiments/products | Soy sauce, explicit-gram mayo, crab sticks, prepared falafel, pesto with grams, and modest teriyaki with grams marked as staging-approved policy. |
| `intake_032` | Dressing ambiguity resolved to yogurt. |
| `intake_053` | Protein ambiguity resolved to tofu only. |
| `intake_080` | Udon wording normalized to generic udon noodles. |
| `intake_084` | Pumpkin wording normalized to generic pumpkin cubes. |
| `intake_089` | Hummus roll classified as snack/light meal; hummus can be a weak plant-protein anchor. |
| `intake_095` | Asparagus restored and no longer replaced by green beans. |
| `intake_101` | Processed poultry product replaced with chicken fillet; spicy tomato sauce normalized to passata plus spices. |

## Future Import Question

Not blocking this staging cleanup: `intake_093` still needs an import-time decision for the large prepared mayo-soy sauce and Korean-carrot component if the goal is to import all 105 recipes at once.
