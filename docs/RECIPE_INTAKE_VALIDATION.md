# Recipe Intake Validation

Scope: cleanup validation for `tmp/recipe_intake/cleaned_recipes.xlsx`. No production curated data, builder, PDF, Telegram, promo, payments, storage, original Excel, or photo assets were changed.

## Summary

- Workbook rows after review-backlog triage: 105 recipes, 844 ingredient rows, 462 step rows, 175 QA issue rows.
- Status after triage: 86 recipes `ready`, 19 recipes `needs_review`.
- Review-backlog triage checked all 19 `needs_review` recipes. None could be safely promoted without a user nutrition-mapping or substitution decision.
- All recipes still have `servings_cleaned = 1`.
- Full import is still **not** recommended because 19 recipes retain product-ID/nutrition mapping blockers.
- A subset import is now reasonable for the 86 `ready` recipes only, assuming the importer filters `status=ready` and excludes `needs_review`.
- Detailed triage backlog: `docs/RECIPE_INTAKE_REVIEW_BACKLOG.md`.

## Review Backlog Triage Counts

| Check | Count | Result |
|---|---:|---|
| `needs_review` recipes before triage | 19 | PASS |
| `needs_review` recipes examined | 19 | PASS |
| Recipes promoted to `ready` | 0 | PASS |
| Recipes still requiring user decision | 19 | PASS |
| Existing `qa_issues` review rows rewritten with concrete user questions | 19 | PASS |

## Post-Triage Validation Checks

| Check | After triage | Result |
|---|---:|---|
| `ready` recipes missing ingredients, steps, or `photo_prompt_ru` | 0 | PASS |
| Recipes with `servings_cleaned != 1` | 0 | PASS |
| `ready` recipes with review/blocker QA rows | 0 | PASS |
| Duplicate `recipe_key` values | 0 | PASS |
| Ingredient-vs-steps mismatch count | 0 | PASS, ingredients and steps sheets unchanged from validated cleanup baseline |

## Before / After Counts

| Check | Before | After | Result |
|---|---:|---:|---|
| Workbook recipes | 105 | 105 | PASS |
| Ingredient rows | 843 | 844 | PASS |
| Step rows | 454 | 462 | PASS |
| Existing QA issue rows | 156 | 175 | PASS |
| Workbook status: `ready` | 105 | 86 | PASS |
| Workbook status: `needs_review` | 0 | 19 | PASS |
| Recipes with blocker-class issues | 74 | 19 | IMPROVED |
| Ingredient-vs-steps: missing ingredients in sheet | 24 | 0 | PASS |
| Portion consistency issues | 2 | 0 | PASS |
| Text cleanliness issues | 0 | 0 | PASS |
| Gram/unit quality issue rows | 90 | 0 | PASS |
| Nutrition mapping/calculation blocked recipes | 69 | 19 | IMPROVED |
| Non-minor unmapped ingredient rows | 78 | 22 | IMPROVED |
| Protein-anchor missing rows | 6 | 0 | PASS |
| Placeholder / too-thin step detail | 1 | 0 | PASS |

## Cleanup Applied

- Fixed targeted ingredient-vs-step mismatches by rewriting steps or normalizing ingredient names.
- Removed portion/batch wording such as the nut-mix split instruction and the `на 1 порцию` ingredient row.
- Filled normal household `amount`, `unit`, and `grams_estimate` values for main ingredients and non-spice condiments.
- Normalized obvious aliases to current nutrition IDs, including turkey/chicken/beef/pork rows, pasta rows, soy sauce, oils, calamari, shrimp, salmon, cheese, cornstarch, nori, greens, and several vegetables.
- Rebuilt placeholder steps for recipes that still had generic instructions.
- Cleaned protein anchors so `yes` remains only on clear protein products; missing anchors are now fixed.
- Added `review` QA rows for recipes that still cannot be reliably mapped without a manual nutrition decision.
- Re-triaged the 19 remaining `needs_review` recipes and rewrote their `qa_issues` review rows with concrete user decisions needed before any promotion to `ready`.

## Remaining Blockers

The remaining blockers are explicit food-ID/nutrition mapping gaps, not structure, portion, gram/unit, anchor, or step-detail issues.
The workbook `qa_issues` sheet now states the exact user decision needed for each blocker.

| Recipe | Remaining blocker |
|---|---|
| `intake_016` — Цельнозерновой хлеб с печенью трески | печень трески консервированная |
| `intake_021` — Гречка с запеченной индейкой и свекольным салатом | гречка сухая |
| `intake_024` — Салат из печени трески с яйцом | печень трески |
| `intake_025` — Салат из печени трески с огурцом и картофелем | печень трески |
| `intake_026` — Салат из печени трески с луком | печень трески |
| `intake_027` — Салат из консервированной печени трески | печень трески |
| `intake_028` — Домашний салат из печени трески с зеленым горошком | печень трески |
| `intake_029` — Белковый салат с курицей | виноград |
| `intake_035` — Кукурузная каша | кукурузная крупа / полента |
| `intake_048` — Цельнозерновой хлеб с паштетом из печени индейки | печень индейки, коньяк |
| `intake_049` — Гречка по-купечески с фаршем | гречка сухая |
| `intake_054` — Гуляш из куриной печени | куриная печень |
| `intake_071` — Гороховый суп-пюре | горох колотый, репа |
| `intake_073` — Тилапия в духовке | замороженная смесь «Овощи по-деревенски», белое сухое вино |
| `intake_077` — Стейк из форели с молодым картофелем | стейк из радужной форели |
| `intake_078` — Яйца по-флорентийски | бешамель |
| `intake_093` — Шаурма с фалафелем | фалафель замороженный |
| `intake_094` — Лосось в сливочном соусе со шпинатом и голубым сыром | сыр с голубой плесенью |
| `intake_095` — Салат с шампиньонами и спаржей | виноград кишмиш |

## Import Recommendation

Do not import all 105 recipes yet.

A subset import of the 86 `ready` recipes is acceptable for a next dry run, provided `needs_review` recipes are excluded. The remaining 19 need either explicit `food_id` mappings, approved substitutions, or recipe-level manual decisions before they can be imported safely.
