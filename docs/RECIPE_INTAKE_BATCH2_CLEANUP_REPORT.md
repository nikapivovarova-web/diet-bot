# Recipe Intake Batch2 Cleanup Report

Date: 2026-05-14

Scope: preprocessing/cleanup slice for the second recipe batch only. Production curated data, builder, PDF, Telegram, promo, payments, storage, photo assets, and the first `tmp/recipe_intake/cleaned_recipes.xlsx` were not edited.

## Source

- Source workbook SHA256 before cleanup: `938B4C8A13458CC1155E12C8BBD6CF4BEE0A972888A451B39F83A21CE5B1C316`
- Source workbook SHA256 after cleanup: `938B4C8A13458CC1155E12C8BBD6CF4BEE0A972888A451B39F83A21CE5B1C316`
- Source structure: one worksheet, columns `название`, `прием пищи`, `сложность`, `ингридиенты`, `рецепт`; many later rows were pasted into the first column and parsed by labels.

## Output

- Staging workbook: `tmp/recipe_intake_batch2/cleaned_recipes_batch2.xlsx`

## Counts

- Total recipes: 106
- Ready: 104
- Needs review: 2

### Primary Meal Slot

| primary_meal_slot | count |
|---|---:|
| breakfast | 15 |
| snack | 35 |
| main | 56 |

### Allowed Meal Slots

| allowed_meal_slots | count |
|---|---:|
| breakfast | 3 |
| snack | 20 |
| main | 54 |
| breakfast,snack | 15 |
| snack,main | 14 |

## Gap-Oriented Counts

- Dairy-free snacks: 30
- Dairy-free mains: 49
- Gluten-free mains: 43
- Egg-free breakfasts: 16
- Simple native mains: 45

### Coverage Priority

| coverage_priority | count |
|---|---:|
| dairy_free_snack | 30 |
| dairy_free_main | 40 |
| gluten_free_main | 15 |
| egg_free_breakfast | 14 |
| simple_main | 0 |
| other | 7 |

## Frequent Problems

- 70 source rows were pasted into one cell and had to be split by `Ингредиенты:` / `Рецепт:` labels.
- 82 recipes had multiple quantities inferred from incomplete source text.
- 7 recipes had product adaptations for CIS availability or gluten/dairy wording cleanup.
- Several original recipes used multi-serving quantities; all cleaned rows were normalized to `servings_cleaned = 1` with rounded amounts.
- Optional alternatives were resolved to one concrete ingredient where needed, e.g. water instead of milk, rice flour instead of wheat/oats, avocado or hummus instead of optional mayo.

## Needs Review

- `batch2_052` Картофельные ньокки: В исходнике нет приема пищи и сложности; основной слот и effort восстановлены редакционно.
- `batch2_106` Быстрая пицца на хлебе: В исходнике нет приема пищи, сложности и точных количеств; нужна ручная проверка перед production-import.

## Coverage Impact vs. 4-Week Audit

The audit in `docs/RECIPE_4_WEEK_COVERAGE_AUDIT.md` identified the largest strict SIMPLE gaps as dairy-free snacks, dairy-free mains, gluten/wheat-free mains, egg-free high-protein breakfasts, and extra native SIMPLE mains.

- This batch contributes 30 dairy-free snack-capable recipes, directly addressing the thinnest pool.
- It adds 49 dairy-free main-capable recipes and 43 gluten-free main-capable recipes, mostly from meat/fish/legume mains and snack-light-main formats.
- It adds 16 egg-free breakfast-capable recipes, though not all are high-protein; protein QA is still needed before production import.
- It adds 45 simple native mains, increasing buffer for unrestricted SIMPLE plans.

Conclusion: batch2 is useful for the documented gaps, especially dairy-free snacks and simple mains, but should remain staging until nutrition/protein checks and manual review of the two `needs_review` rows are complete.

## Validation

- recipe_key unique: yes
- servings_cleaned all 1: yes
- ready rows have required fields, ingredients, steps, photo_prompt: yes
- source Excel SHA256 before/after matched: yes
- workbook opens with sheets `recipes`, `ingredients`, `steps`, `qa_issues`: yes
- all workbook sheets rendered to PNG preview: yes
- formula/error scan: 0 matches
- validation errors: 0
