# Recipe Intake Validation

Scope: validation for the decision cleanup pass on `tmp/recipe_intake/cleaned_recipes.xlsx`. No production curated data, builder, PDF, Telegram, promo, payments, storage, original Excel, or photo assets were changed.

## Summary

- Workbook recipes: 105.
- Status after previous triage: 86 `ready`, 19 `needs_review`.
- User decisions applied in this pass: 16 recipes.
- Status after this pass: 102 `ready`, 3 `needs_review`.
- Full import is still not recommended because 3 recipes retain unresolved product-ID/nutrition mapping blockers.
- A subset import is reasonable for the 102 `ready` recipes only, assuming the importer filters `status=ready` and excludes `needs_review`.

## Workbook Counts

| Check | Before decision pass | After decision pass | Result |
|---|---:|---:|---|
| Workbook recipes | 105 | 105 | PASS |
| Ingredient rows | 844 | 842 | PASS |
| Step rows | 462 | 462 | PASS |
| QA issue rows | 175 | 175 | PASS |
| Workbook status: `ready` | 86 | 102 | PASS |
| Workbook status: `needs_review` | 19 | 3 | PASS |
| `ready` recipes with `review` QA rows | 0 | 0 | PASS |

Ingredient rows decreased by 2 because `intake_048` removed cognac and `intake_071` merged turnip into carrot.

## Cleanup Applied

- Recorded staging-only mapping confirmations for cod liver, dry buckwheat, fresh grape/kishmish, cornmeal/polenta, chicken liver, split peas, and trout.
- Promoted the resolved recipes to `ready`.
- Replaced turkey liver with chicken liver in `intake_048`; removed cognac entirely; updated title, ingredients, steps, photo prompt, and protein anchor.
- Replaced turnip with carrot in `intake_071`; updated ingredients, steps, and photo prompt.
- Marked trout as the protein anchor in `intake_077`.
- Replaced blue cheese with regular cheese (`сыр гауда`) in `intake_094`; updated title, ingredients, steps, and photo prompt.
- Converted resolved `review` QA rows to decision notes while keeping unresolved review rows for the remaining blockers.

## Remaining Blockers

| Recipe | Remaining blocker |
|---|---|
| `intake_073` — Тилапия в духовке | Frozen vegetable mix `Овощи по-деревенски` and dry white wine need a user decision. |
| `intake_078` — Яйца по-флорентийски | Prepared bechamel needs a mapping, measured decomposition, or exclusion decision. |
| `intake_093` — Шаурма с фалафелем | Frozen falafel needs a mapping, chickpea-based rewrite/decomposition, or exclusion decision. |

## Import Recommendation

Do not import all 105 recipes yet. Importing only the 102 `ready` recipes is acceptable for the next dry run if the 3 remaining `needs_review` recipes are excluded.
