# Recipe Intake User Questions

Scope: remaining user-facing questions for `tmp/recipe_intake/cleaned_recipes.xlsx` after applying the user's latest decisions. This file does not approve production imports, change production nutrition data, edit the source Excel, or generate photos.

## Current Status

- Workbook total: 105 recipes.
- Ready after this pass: 102 recipes.
- Still `needs_review`: 3 recipes.
- Decisions applied: cod liver, dry buckwheat, fresh grape/kishmish, cornmeal/polenta, turkey-liver replacement, chicken liver, split pea soup turnip replacement, trout, and blue-cheese replacement.

## Remaining Questions

| recipe_key | Title | Question | Options |
|---|---|---|---|
| `intake_073` | Тилапия в духовке | How should the frozen vegetable mix and white wine be handled? | 1. Break `Овощи по-деревенски` into exact mapped vegetables and count wine. 2. Break the mix into exact mapped vegetables and omit wine as a cooking component. 3. Exclude the recipe. |
| `intake_078` | Яйца по-флорентийски | How should prepared bechamel be counted? | 1. Add/confirm prepared bechamel mapping. 2. Decompose into milk/butter/flour/cheese with exact grams. 3. Exclude the recipe. |
| `intake_093` | Шаурма с фалафелем | How should frozen falafel be counted? | 1. Add/confirm frozen falafel mapping. 2. Rewrite/decompose as chickpea falafel with exact grams. 3. Exclude the recipe. |

## Resolved Decisions

- Cod liver recipes were kept; cod liver mapping is recorded as confirmed in the staging workbook.
- Dry buckwheat was kept in `intake_021` and `intake_049`.
- Fresh grapes and kishmish were kept; neither was replaced with raisins.
- Cornmeal/polenta was kept in `intake_035`.
- Turkey liver in `intake_048` was replaced with chicken liver, and cognac was removed completely.
- Chicken liver was kept in `intake_054`.
- `intake_071` was kept; turnip was replaced with carrot.
- Trout was kept in `intake_077` and marked as the protein anchor.
- Blue cheese in `intake_094` was replaced with regular cheese.

## Compact Answer Template

```text
intake_073 vegetable mix: [exact vegetables + grams]; wine: count/omit
intake_078 bechamel: map prepared sauce / decompose into [exact grams] / exclude
intake_093 falafel: map frozen falafel / decompose-rewrite / exclude
```
