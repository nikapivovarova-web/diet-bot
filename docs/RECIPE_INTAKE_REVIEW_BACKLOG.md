# Recipe Intake Review Backlog

Scope: triage for the 19 `needs_review` recipes in `tmp/recipe_intake/cleaned_recipes.xlsx`. This pass did not import recipes into production curated data, did not touch builder/PDF/Telegram/promo/payments/storage, did not change the source Excel, and did not generate photos.

## Summary

- `needs_review` before triage: 19 recipes.
- Promoted to `ready`: 0 recipes.
- Still `needs_review`: 19 recipes.
- Reason no recipes were promoted: every remaining blocker requires a nutrition mapping or substitution decision. Replacing these ingredients editorially would change the recipe or rely on an unapproved food alias.
- Workbook action taken: the existing `qa_issues` review rows were rewritten with concrete user questions.

## Triage

| Recipe | Title | Blocker category | What is needed | Editorially fixable without external info? | User decision needed? |
|---|---|---|---|---|---|
| `intake_016` | Цельнозерновой хлеб с печенью трески | nutrition mapping blocker | Add/confirm food ID and nutrient values for canned cod liver. | No | Yes |
| `intake_021` | Гречка с запеченной индейкой и свекольным салатом | nutrition mapping blocker | Confirm dry buckwheat mapping or approve an ingredient change. | No | Yes |
| `intake_024` | Салат из печени трески с яйцом | nutrition mapping blocker | Add/confirm food ID and nutrient values for cod liver. | No | Yes |
| `intake_025` | Салат из печени трески с огурцом и картофелем | nutrition mapping blocker | Add/confirm food ID and nutrient values for cod liver. | No | Yes |
| `intake_026` | Салат из печени трески с луком | nutrition mapping blocker | Add/confirm food ID and nutrient values for cod liver. | No | Yes |
| `intake_027` | Салат из консервированной печени трески | nutrition mapping blocker | Add/confirm food ID and nutrient values for cod liver. | No | Yes |
| `intake_028` | Домашний салат из печени трески с зеленым горошком | nutrition mapping blocker | Add/confirm food ID and nutrient values for cod liver. | No | Yes |
| `intake_029` | Белковый салат с курицей | nutrition mapping blocker | Add fresh grape mapping or approve a replacement. Raisins are not a safe automatic replacement. | No | Yes |
| `intake_035` | Кукурузная каша | nutrition mapping blocker | Add cornmeal/polenta mapping or approve a different grain. Corn kernels are not a reliable substitute. | No | Yes |
| `intake_048` | Цельнозерновой хлеб с паштетом из печени индейки | nutrition mapping blocker | Add turkey liver mapping and decide whether cognac should be counted or removed as a small cooking component. | No | Yes |
| `intake_049` | Гречка по-купечески с фаршем | nutrition mapping blocker | Confirm dry buckwheat mapping or approve an ingredient change. | No | Yes |
| `intake_054` | Гуляш из куриной печени | nutrition mapping blocker | Add/confirm chicken liver mapping. Chicken breast is not a safe editorial substitute. | No | Yes |
| `intake_071` | Гороховый суп-пюре | nutrition mapping blocker | Add split pea and turnip mappings or approve ingredient replacements. | No | Yes |
| `intake_073` | Тилапия в духовке | nutrition mapping blocker | Break the frozen vegetable mix into concrete vegetables and decide how to map/count dry white wine. | No | Yes |
| `intake_077` | Стейк из форели с молодым картофелем | nutrition mapping blocker | Add trout mapping or approve replacement with an existing fish mapping. | No | Yes |
| `intake_078` | Яйца по-флорентийски | nutrition mapping blocker | Confirm prepared bechamel mapping or approve a sauce breakdown with exact gram amounts. | No | Yes |
| `intake_093` | Шаурма с фалафелем | nutrition mapping blocker | Add frozen falafel mapping or approve a chickpea-based breakdown/replacement. | No | Yes |
| `intake_094` | Лосось в сливочном соусе со шпинатом и голубым сыром | nutrition mapping blocker | Add blue cheese mapping or approve a cheese replacement from the current catalog. | No | Yes |
| `intake_095` | Салат с шампиньонами и спаржей | nutrition mapping blocker | Add fresh kishmish grape mapping or approve a replacement. Raisins are not a safe automatic replacement. | No | Yes |

## User Questions

- Should cod liver be added as a nutrition-mapped food? This would unblock `intake_016`, `intake_024`, `intake_025`, `intake_026`, `intake_027`, and `intake_028`.
- Should dry buckwheat be accepted as a mapped food for this intake workbook? This would unblock `intake_021` and `intake_049`.
- Should fresh grapes/kishmish grapes get a food mapping, or should those recipes be rewritten with another fruit?
- Should cornmeal/polenta, turkey liver, chicken liver, split peas, turnip, trout, prepared bechamel, frozen falafel, and blue cheese be added as mapped foods?
- For `intake_048`, should cognac be counted nutritionally, mapped to an alcohol item, or removed as a negligible cooking component?
- For `intake_073`, what exact vegetables should replace the frozen "Овощи по-деревенски" mix, and should the white wine be counted or omitted?

## Exclusion Candidates

No recipe is structurally impossible after cleanup, but these are the strongest exclusion candidates if new nutrition mappings are not allowed:

- `intake_016`, `intake_024`, `intake_025`, `intake_026`, `intake_027`, `intake_028`: cod-liver cluster; all depend on one missing mapping.
- `intake_048`: turkey liver plus cognac makes the nutrition decision less standard.
- `intake_073`: frozen vegetable mix needs ingredient decomposition, not just an alias.
- `intake_078`: prepared bechamel needs either a mapped sauce or a measured ingredient breakdown.
- `intake_093`: frozen falafel is a prepared product and needs a mapped product or recipe-level replacement.
