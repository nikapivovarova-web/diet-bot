# Recipe Intake Review Backlog

Scope: final cleanup of the remaining `needs_review` recipes in `tmp/recipe_intake/cleaned_recipes.xlsx`, based on the user's decisions. This pass did not import recipes into production curated data, did not touch builder/PDF/Telegram/promo/payments/storage, did not change the source Excel, and did not generate photos.

## Summary

- Workbook total: 105 recipes.
- Status before final pass: 102 `ready`, 3 `needs_review`.
- Promoted to `ready`: 3 recipes.
- Still `needs_review`: 0 recipes.
- Status after final pass: 105 `ready`, 0 `needs_review`.
- Workbook action taken: final user decisions were recorded in the staging workbook; no production nutrition mappings were added.

## Final Decisions Applied

| Recipe | Title | Action |
|---|---|---|
| `intake_073` | Тилапия в духовке | Removed the alcohol cooking component, replaced the frozen vegetable mix with zucchini 40 g, bell pepper 30 g, carrot 20 g, and onion 10 g, added lemon juice 10 g, and updated ingredients, steps, and photo prompt. |
| `intake_078` | Яйца по-флорентийски | Replaced prepared sauce 20 g with milk 15 g, butter 3 g, and flour 2 g; merged the added milk and butter into existing ingredient rows, added flour, and updated steps. |
| `intake_093` | Шаурма с фалафелем | Kept frozen/prepared falafel as a semi-prepared ingredient for staging readiness and marked falafel as the plant protein anchor. |

## Remaining Needs Review

None.

## Import Recommendation

All 105 recipes are `ready` in the staging workbook. Production import remains a separate task and was not performed here.
