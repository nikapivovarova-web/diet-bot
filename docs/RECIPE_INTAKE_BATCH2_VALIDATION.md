# Recipe Intake Batch2 Validation

Date: 2026-05-14

Scope: validation/dry-run slice for `tmp/recipe_intake_batch2/cleaned_recipes_batch2.xlsx`. No production curated recipe data, nutrition rows, builder, PDF, Telegram, promo, payments, storage, photo assets, generated photos, or the batch1 workbook were edited.

## Inputs Read

- `tmp/recipe_intake_batch2/cleaned_recipes_batch2.xlsx`
- `docs/RECIPE_INTAKE_BATCH2_CLEANUP_REPORT.md`
- `tmp/recipe_intake/cleaned_recipes.xlsx` for batch1 duplicate checks only
- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_foods.json`
- `docs/RECIPE_4_WEEK_COVERAGE_AUDIT.md`

## Summary

- Workbook shape is valid: sheets `recipes`, `ingredients`, `steps`, `qa_issues` are present.
- Batch2 has 106 recipes: 104 `ready`, 2 `needs_review`.
- `recipe_key` values are unique.
- Required recipe fields are filled: title, slots, effort, time, equipment, tags, coverage priority, photo prompt, ingredients, and steps.
- `allowed_meal_slots`, `slot_flex_type`, `coverage_priority`, and `cooking_effort` values are from the expected enum sets.
- `servings_cleaned = 1` for all 106 recipes.
- Text cleanliness passes for banned promo/service/link phrases: no `приятного аппетита`, links, channel/site/promo, or AI/service phrases found.
- Import-all is not ready: there is one exact production duplicate, multiple ingredient parsing defects, a same-title duplicate inside batch2, mapping gaps, and prepared-product policy issues.

Recommendation: fix workbook first. Do not import all. A subset import could be considered later, but only after excluding or fixing the blocker rows and rerunning the import preview.

## Ready / Needs Review

| Status | Count |
|---|---:|
| ready | 104 |
| needs_review | 2 |

Needs review rows from the workbook:

| recipe_key | title | reason |
|---|---|---|
| `batch2_052` | Картофельные ньокки | Source had no meal slot or effort; slot, effort, and 6 quantities were restored editorially. |
| `batch2_106` | Быстрая пицца на хлебе | Source had no meal slot, effort, or exact quantities; 5 quantities were restored editorially. |

## Validation Matrix

| Check | Result | Notes |
|---|---|---|
| `recipe_key` unique | PASS | 106 unique keys. |
| Duplicate with production | BLOCKER | `batch2_008` exactly duplicates production `r007_yaichnye_maffiny_s_ovoschami`. |
| Duplicate with batch1 workbook/imported recipes | PASS | No exact or high-similarity title matches found against batch1 workbook or production `r401`-`r505`. |
| Duplicate title inside batch2 | WARNING | `batch2_006` and `batch2_096` are both `Сэндвич с тунцом`. |
| Required fields filled | PASS | No blank title/slot/effort/time/equipment/tags/photo prompt; all recipes have ingredients and steps. |
| Allowed slot enum/slot-flex consistency | PASS | Values are consistent with `breakfast_only`, `snack_only`, `main_only`, `breakfast_snack`, `snack_light_main`. |
| `coverage_priority` enum | PASS | Values are within expected set. |
| Ingredients vs steps | WARNING | 10 step-vs-ingredient candidates need manual review; many are synonym/short-step artifacts, but they should be checked with the blocker rows. |
| One-portion normalization | BLOCKER | `servings_cleaned` passes, but 4 ingredient rows have impossible 500-600 g amounts for one portion. |
| Main ingredient `по вкусу` | PASS | No main ingredient uses `по вкусу`; only minor salt/spice/herb style rows do. |
| Weird decimals | PASS | No weird decimal gram estimates found. |
| Text cleanliness | PASS | No banned phrases or links. Short steps exist, but no obvious truncated comma/ellipsis endings. |
| Nutrition/import mapping | WARNING | Heuristic dry-run maps 664/693 ingredient rows, 190/201 unique names. 29 rows remain unmapped against current production foods/aliases. |
| Protein anchor | WARNING | `batch2_036` is a fish main but `филе минтая` is not marked as `is_protein_anchor=yes`. |

## Blockers

1. Production duplicate:

| batch2 key | batch2 title | production match |
|---|---|---|
| `batch2_008` | Яичные маффины с овощами | `r007_yaichnye_maffiny_s_ovoschami`, exact title match |

2. Invalid ingredient names or embedded quantities:

| recipe_key | title | issue |
|---|---|---|
| `batch2_003` | Бутерброды с курицей и овощами | Three ingredient rows have `ingredient_name_ru = 0`; also 500 g tomato, 500 g cucumber, 250 g onion. |
| `batch2_005` | Рулет из лаваша с крабовыми палочками | One ingredient row has `ingredient_name_ru = 0`; 600 g bell pepper. |
| `batch2_006` | Сэндвич с тунцом | Three ingredient rows have `ingredient_name_ru = 0`; 600 g bell pepper; no protein anchor despite tuna title. |
| `batch2_021` | Лосось с рисом и брокколи | Ingredient name contains quantity: `лосось 2 куска`. |
| `batch2_022` | Паста с тунцом и томатами | Ingredient name contains quantity: `томаты 250`. |
| `batch2_027` | Шакшука с нутом | Ingredient name contains quantity: `яйца 3`. |
| `batch2_037` | Фалафель в лаваше | Ingredient name contains quantity: `мука 2`. |
| `batch2_043` | Ризотто с курицей и грибами | Ingredient name contains quantity: `вода - 3 стакана`. |
| `batch2_096` | Сэндвич с тунцом | Ingredient name contains quantity: `тунец 80`. |
| `batch2_097` | Тост с арахисовой пастой и яблоком | Ingredient name contains quantity: `арахисовая паста 1`. |
| `batch2_101` | Творог с солёной карамелью из фиников | Ingredient names contain quantities: `финики 4`, `молоко 2`. |
| `batch2_103` | Сырные лепёшки | Ingredient name contains quantity: `мука 180`. |

3. Restriction/tag conflicts that can poison coverage counts:

| recipe_key | title | conflict |
|---|---|---|
| `batch2_002` | Онигири | Has `fish_free` and `vegetarian`, but contains crab sticks. |
| `batch2_005` | Рулет из лаваша с крабовыми палочками | Has `fish_free` and `vegetarian`, but contains crab sticks. |
| `batch2_006` | Сэндвич с тунцом | Has `fish_free` and `vegetarian`, but contains tuna. |
| `batch2_010` | Рулет из лаваша с тунцом | Has `fish_free` and `vegetarian`, but contains tuna. |
| `batch2_036` | Запеченный хек с овощами | Has `fish_free` and `vegetarian`, but contains fish; protein anchor is also missing. |
| `batch2_081` | Тост с сардинами и огурцом | Has `vegetarian`, but contains sardines. |

## Duplicate Candidates

- Production duplicate: `batch2_008` exactly matches `r007_yaichnye_maffiny_s_ovoschami`.
- Batch1 workbook duplicate candidates: none found.
- Batch1 imported production duplicate candidates, `r401`-`r505`: none found.
- Batch2 internal same-title candidate: `batch2_006` and `batch2_096`, both `Сэндвич с тунцом`.

## Mapping Gaps

Dry-run mapping against current production foods/ingredient aliases:

| Metric | Count |
|---|---:|
| mapped ingredient rows | 664 / 693 |
| unmapped ingredient rows | 29 / 693 |
| mapped unique ingredient names | 190 / 201 |
| unmapped unique ingredient names | 11 / 201 |

Unmapped or risky unique ingredients:

- `0` - 7 rows, true blocker.
- `кокосовое молоко` - 5 rows, no current production food id.
- `шпроты` - 4 rows, no current production food id.
- `селёдка` - 4 rows, no current production food id.
- `рисовая мука` / `рисовой муки` - 4 rows total, no current production food id.
- `базилик/орегано` - 1 row, should be split or normalized to spice policy.
- `рисовая лапша` - 1 row, no current production food id.
- `сардины` - 1 row, no current production food id.
- `варёная свёкла` / `Варёная свёкла` - 2 rows total, casing duplicate plus missing direct food id.

Prepared product or sauce policy issues, 17 rows:

- Crab sticks: `batch2_002`, `batch2_005`.
- Processed cheese: `batch2_005`.
- Tomato sauce: `batch2_052`, `batch2_053`, `batch2_055`, `batch2_060`, `batch2_102`, `batch2_106`.
- Prepared chicken cutlet and yogurt sauce: `batch2_057`.
- Sprats: `batch2_083`, `batch2_084`, `batch2_085`, `batch2_086`.
- Postny mayo or oil: `batch2_088`.
- Avocado sauce: `batch2_092`.

## Slot-Flex Issues

Slot-flex enum consistency passes, but 3 recipes should be manually reviewed for `snack_light_main` quality:

| recipe_key | title | issue |
|---|---|---|
| `batch2_006` | Сэндвич с тунцом | `snack_light_main` but no protein anchor and no `high_protein` tag. |
| `batch2_010` | Рулет из лаваша с тунцом | `snack_light_main`; strongest marked anchor is only 45 g творожный сыр while tuna is not marked as anchor. |
| `batch2_011` | Салат с гречкой, овощами и фетой | `snack_light_main`; strongest marked anchor is 50 g feta, likely weak for main fallback. |

`breakfast_snack` rows look broadly reasonable: they are mostly rolls, sandwiches, toast, lavash, muffins, or quick pizza/flatbread formats rather than hot porridge/omelet plates. No porridge/omelet snack-flex blocker found.

## Ingredient-vs-Steps Consistency

High-confidence blocker findings are already covered by invalid ingredient rows and missing anchors. The heuristic step scan also produced 10 manual-review candidates where a root appears in steps but not as an explicit ingredient, or vice versa. Many are likely acceptable synonyms or terse instructions, for example mushrooms written as `шампиньоны` in ingredients but `грибы` in steps.

Notable candidates to check while fixing the workbook:

- `batch2_057` uses prepared `Куриная котлета` while steps mention `фарш`.
- `batch2_091` has a step-level mayo reference while the ingredient policy row is not aligned.
- `batch2_054` mentions curry paste style wording while ingredient row is generic `карри`.

## Portion / Grams

Passes:

- All `servings_cleaned` values are 1.
- No `разделите на порции`, `1 кг`, `на всю семью`, or similar multi-serving phrases found.
- No weird decimal gram estimates found.
- No `по вкусу` for main ingredients.

Blockers:

- `batch2_003`: 500 g tomato, 500 g cucumber, 250 g onion, plus three `0` ingredient rows.
- `batch2_005`: 600 g bell pepper, plus one `0` ingredient row.
- `batch2_006`: 600 g bell pepper, plus three `0` ingredient rows.

## Text Cleanliness

- No `приятного аппетита`.
- No links, channel/site/promo phrases, or AI/service phrases.
- No obvious truncated steps ending with comma, colon, ellipsis, or dangling conjunction.
- 35 steps are very terse, for example `Отвари пасту.` or `Подавай с рисом.` They are complete enough for validation and are not treated as blockers.

## Coverage Impact

The cleanup report counts are confirmed:

| Gap-oriented count | Report | Recomputed |
|---|---:|---:|
| Dairy-free snacks | 30 | 30 |
| Dairy-free mains | 49 | 49 |
| Gluten-free mains | 43 | 43 |
| Egg-free breakfasts | 16 | 16 |
| Simple native mains | 45 | 45 |

If imported on top of the current 505 production recipes:

| Scenario | Production total |
|---|---:|
| Import all 106 raw batch2 recipes | 611 |
| Import only 104 `ready` rows | 609 |
| Import after excluding blockers | Needs a rerun after workbook fixes; current workbook is not subset-ready without manual exclusions. |

Estimated 4-week gap closure using `docs/RECIPE_4_WEEK_COVERAGE_AUDIT.md` baseline:

| Gap | Current strict SIMPLE baseline | 4-week demand / target | Batch2 raw contribution | Raw post-import estimate |
|---|---:|---:|---:|---:|
| Dairy-free snacks | 29 | 56 hard minimum | +30 | 59, closes hard gap by 3 |
| Dairy-free mains | 28 | 56 hard minimum, 70 for 1.25x buffer | +49 | 77, closes hard gap and buffer |
| Gluten-free mains | 21 | 56 hard minimum, 70 for 1.25x buffer | +43 | 64, closes hard gap but remains about 6 short of 1.25x buffer |
| Egg-free breakfasts | 30 | 28 hard minimum, HP proxy still thin | +16 | 46 raw egg-free breakfasts; high-protein quality still needs QA |
| Native SIMPLE mains | 55 | 56 hard minimum, 70 for 1.25x buffer | +45 | 100 raw native simple mains |

Coverage value is high, especially for dairy-free snacks/mains and simple native mains, but the current blocker rows can inflate or misclassify those counts. In particular, `fish_free`/`vegetarian` conflicts and unmapped dairy/gluten substitute ingredients must be fixed before treating coverage closure as production-ready.

## Recommendation

Fix workbook first.

Do not import all from the current workbook. The minimum fix pass should:

1. Remove the production duplicate `batch2_008` or explicitly mark it not importable.
2. Fix all `ingredient_name_ru = 0` rows and ingredient names with embedded quantities.
3. Correct impossible one-portion gram amounts in `batch2_003`, `batch2_005`, and `batch2_006`.
4. Resolve the two `needs_review` rows before any production promotion.
5. Correct restriction/tag conflicts, especially fish-containing recipes marked `fish_free` or `vegetarian`.
6. Add/confirm production mapping policy for coconut milk, rice flour, rice noodles, sprats, herring, sardines, beetroot, and split spice rows.
7. Normalize prepared sauce/product policy rows or replace them with controlled component ingredients.
8. Re-run duplicate, mapping, slot-flex, and 4-week coverage validation after workbook fixes.
