# Recipe Intake Review Backlog

Scope: cleanup pass for the 19 previously `needs_review` recipes in `tmp/recipe_intake/cleaned_recipes.xlsx`, based on the user's decisions. This pass did not import recipes into production curated data, did not touch builder/PDF/Telegram/promo/payments/storage, did not change the source Excel, and did not generate photos.

## Summary

- Workbook total: 105 recipes.
- Status before this decision pass: 86 `ready`, 19 `needs_review`.
- Promoted to `ready`: 16 recipes.
- Still `needs_review`: 3 recipes.
- Status after this pass: 102 `ready`, 3 `needs_review`.
- Workbook action taken: user decisions were recorded in the staging workbook; no production nutrition mappings were added.

## Decisions Applied

| Recipe | Title after cleanup | Action |
|---|---|---|
| `intake_016` | Цельнозерновой хлеб с печенью трески | Kept; canned cod liver mapping confirmed for staging; cod liver marked as protein anchor. |
| `intake_021` | Гречка с запеченной индейкой и свекольным салатом | Kept; dry buckwheat mapping confirmed. |
| `intake_024` | Салат из печени трески с яйцом | Kept; cod liver mapping confirmed. |
| `intake_025` | Салат из печени трески с огурцом и картофелем | Kept; cod liver mapping confirmed. |
| `intake_026` | Салат из печени трески с луком | Kept; cod liver mapping confirmed. |
| `intake_027` | Салат из консервированной печени трески | Kept; cod liver mapping confirmed. |
| `intake_028` | Домашний салат из печени трески с зеленым горошком | Kept; cod liver mapping confirmed. |
| `intake_029` | Белковый салат с курицей | Kept; fresh grape mapping confirmed; not replaced with raisins. |
| `intake_035` | Кукурузная каша | Kept; cornmeal/polenta mapping confirmed; incorrect meat/poultry tag removed. |
| `intake_048` | Цельнозерновой хлеб с паштетом из куриной печени | Turkey liver replaced with chicken liver; cognac removed completely; title, ingredients, steps, photo prompt, and anchor updated. |
| `intake_049` | Гречка по-купечески с фаршем | Kept; dry buckwheat mapping confirmed. |
| `intake_054` | Гуляш из куриной печени | Kept; chicken liver mapping confirmed; chicken liver marked as protein anchor. |
| `intake_071` | Гороховый суп-пюре | Kept; split pea mapping confirmed; turnip replaced with carrot; ingredients, steps, and photo prompt updated. |
| `intake_077` | Стейк из форели с молодым картофелем | Kept; trout mapping confirmed; trout marked as protein anchor. |
| `intake_094` | Лосось в сливочном соусе со шпинатом и сыром | Blue cheese replaced with regular cheese (`сыр гауда`); title, ingredients, steps, and photo prompt updated. |
| `intake_095` | Салат с шампиньонами и спаржей | Kept; fresh kishmish grape mapping confirmed; not replaced with raisins. |

## Remaining Needs Review

These recipes were not changed to `ready` because the user's provided decisions did not cover their blockers.

| Recipe | Current blocker | Needed decision |
|---|---|---|
| `intake_073` | Frozen vegetable mix `Овощи по-деревенски`, dry white wine | Provide exact vegetable breakdown and decide whether wine is counted or omitted as a cooking component. |
| `intake_078` | Prepared bechamel | Confirm prepared bechamel mapping, decompose into measured ingredients, or exclude. |
| `intake_093` | Frozen falafel | Confirm frozen falafel mapping, decompose/rewrite as chickpea falafel, or exclude. |

## Import Recommendation

Do not import all 105 recipes yet. A subset import of the 102 `ready` recipes is reasonable only if the importer filters `status=ready` and excludes the 3 remaining `needs_review` recipes.
