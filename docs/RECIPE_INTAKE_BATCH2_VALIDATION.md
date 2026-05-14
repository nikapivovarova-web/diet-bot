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
- After the rescue-fix pass, batch2 has 106 recipes: 100 `ready`, 6 `needs_review`.
- `recipe_key` values are unique.
- Required recipe fields are filled: title, slots, effort, time, equipment, tags, coverage priority, photo prompt, ingredients, and steps.
- `allowed_meal_slots`, `slot_flex_type`, `coverage_priority`, and `cooking_effort` values are from the expected enum sets.
- `servings_cleaned = 1` for all 106 recipes.
- Text cleanliness passes for banned promo/service/link phrases: no `приятного аппетита`, links, channel/site/promo, or AI/service phrases found.
- Ready-only hard blockers are cleared: no invalid ingredient names, no 500-600 g one-portion ingredient rows, no production duplicate in `ready`, no disallowed prepared-product policy rows in `ready`, and no fish/vegetarian/fish_free conflicts in `ready`.
- Import-all is still not ready because 6 rows are intentionally quarantined as `needs_review`: the exact production duplicate, four sprats recipes without supported mapping, and `batch2_106` with source-restored quantities that still require manual confirmation.

Recommendation: import only `ready` rows after the normal importer dry-run. Do not import `needs_review` rows until the duplicate/prepared-product issues are explicitly resolved.

## Ready / Needs Review

| Status | Count |
|---|---:|
| ready | 100 |
| needs_review | 6 |

Needs review rows from the workbook:

| recipe_key | title | reason |
|---|---|---|
| `batch2_008` | Яичные маффины с овощами | Exact production duplicate of `r007_yaichnye_maffiny_s_ovoschami`; do not import as a new recipe. |
| `batch2_083` | Тосты со шпротами, огурцом и горчицей | Sprats normalized to drained weight, but no supported canonical sprats or close canned fish mapping exists. |
| `batch2_084` | Брускетты со шпротами и маринованным луком | Sprats normalized to drained weight; lemon juice row normalized; no supported sprats mapping exists. |
| `batch2_085` | Яйца, фаршированные шпротами | Sprats normalized to drained weight, but no supported canonical sprats or close canned fish mapping exists. |
| `batch2_086` | Рисовые хлебцы со шпротным паштетом | Sprats normalized to drained weight, but no supported canonical sprats or close canned fish mapping exists. |
| `batch2_106` | Быстрая пицца на хлебе | Tomato sauce was normalized, but source had no meal slot, effort, or exact quantities; keep excluded pending manual quantity confirmation. |

Moved from `needs_review` to `ready` in the rescue pass:

- `batch2_002`: crab sticks kept as canonical `crab_sticks`; no artificial decomposition.
- `batch2_005`: crab sticks kept as canonical `crab_sticks`; `плавленый сыр` replaced with `творожный сыр`.
- `batch2_052`: source-restored slot/effort/one-portion quantities accepted as conservative; tomato sauce replaced with `томаты в собственном соку`.
- `batch2_053`, `batch2_055`, `batch2_060`, `batch2_102`: tomato sauce replaced with `томаты в собственном соку` at the same grams.

## Validation Matrix

| Check | Result | Notes |
|---|---|---|
| `recipe_key` unique | PASS | 106 unique keys. |
| Duplicate with production | PASS for ready import | `batch2_008` still exactly matches production `r007_yaichnye_maffiny_s_ovoschami`, but is now `needs_review` and must not be imported as new. |
| Duplicate with batch1 workbook/imported recipes | PASS | No exact or high-similarity title matches found against batch1 workbook or production `r401`-`r505`. |
| Duplicate title inside batch2 | WARNING | `batch2_006` and `batch2_096` are both `Сэндвич с тунцом`. |
| Required fields filled | PASS | No blank title/slot/effort/time/equipment/tags/photo prompt; all recipes have ingredients and steps. |
| Allowed slot enum/slot-flex consistency | PASS | Values are consistent with `breakfast_only`, `snack_only`, `main_only`, `breakfast_snack`, `snack_light_main`. |
| `coverage_priority` enum | PASS | Values are within expected set. |
| Ingredients vs steps | WARNING | 10 step-vs-ingredient candidates need manual review; many are synonym/short-step artifacts, but they should be checked with the blocker rows. |
| One-portion normalization | PASS | `servings_cleaned` passes and no ingredient row has the prior impossible 500-600 g one-portion amount. |
| Main ingredient `по вкусу` | PASS | No main ingredient uses `по вкусу`; only minor salt/spice/herb style rows do. |
| Weird decimals | PASS | No weird decimal gram estimates found. |
| Text cleanliness | PASS | No banned phrases or links. Short steps exist, but no obvious truncated comma/ellipsis endings. |
| Nutrition/import mapping | WARNING | Heuristic dry-run maps 664/686 ingredient rows, 178/188 unique names. 22 rows remain unmapped against current production foods/aliases. |
| Prepared-product policy in ready rows | PASS | No disallowed prepared rows remain in `ready`: crab sticks are allowed by canonical `crab_sticks`; tomato sauce and processed cheese were normalized; sprats remain `needs_review`. |
| Fish/vegetarian/fish_free conflicts in ready rows | PASS | Targeted ready-only check found no fish-containing ready recipe with `vegetarian` tag or `fish_free` restriction. |
| Protein anchor | PASS | `batch2_036`, `batch2_006`, and `batch2_010` fish/tuna anchors were corrected where needed. |

## Original Blockers Fixed Or Quarantined

The following findings were the hard blockers from the initial validation. In the current workbook, parser defects and tag conflicts are fixed directly; exact duplicate and unresolved sprats/source-quantity rows are kept out of ready import with `status = needs_review`.

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

Dry-run mapping against current production foods/ingredient aliases after the workbook-fix pass:

| Metric | Count |
|---|---:|
| mapped ingredient rows | 664 / 686 |
| unmapped ingredient rows | 22 / 686 |
| mapped unique ingredient names | 178 / 188 |
| unmapped unique ingredient names | 10 / 188 |

Unmapped or risky unique ingredients:

- `кокосовое молоко` - 5 rows, no current production food id.
- `шпроты` - 4 rows, no current production food id.
- `селёдка` - 4 rows, no current production food id.
- `рисовая мука` / `рисовой муки` - 4 rows total, no current production food id.
- `базилик/орегано` - 1 row, should be split or normalized to spice policy.
- `рисовая лапша` - 1 row, no current production food id.
- `сардины` - 1 row, no current production food id.
- `варёная свёкла` / `Варёная свёкла` - 2 rows total, casing duplicate plus missing direct food id.

Prepared product or sauce policy choices after the rescue pass:

- Crab sticks: `batch2_002`, `batch2_005` are `ready` because `crab_sticks` exists as a canonical ingredient; no decomposition was applied.
- Processed cheese: `batch2_005` now uses `творожный сыр`; the recipe remains culinary-coherent as a lavash roll.
- Tomato sauce: `batch2_052`, `batch2_053`, `batch2_055`, `batch2_060`, `batch2_102`, and `batch2_106` now use `томаты в собственном соку` with the same gram estimates. No prepared tomato sauce row remains.
- Sprats: `batch2_083`, `batch2_084`, `batch2_085`, `batch2_086` remain `needs_review`; drained-weight notes were added, but no canonical sprats or close canned fish mapping exists.

Prepared rows fixed directly in ready recipes:

- `batch2_057`: `Куриная котлета` -> `куриный фарш`; `йогуртовый соус` -> `йогурт`.
- `batch2_088`: `постный майонез или масло` -> `растительное масло`.
- `batch2_092`: `соус из авокадо` -> `авокадо`.
- `batch2_084`: `уксус/лимонный сок` -> `лимонный сок`, matching the step text.

## Slot-Flex Issues

Slot-flex enum consistency passes, with 1 remaining `snack_light_main` quality warning:

| recipe_key | title | issue |
|---|---|---|
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

Fixed in workbook:

- `batch2_003`: three parser-artifact `0` ingredient rows removed; tomato/cucumber/onion restored to `0,5 шт.` one-portion amounts.
- `batch2_005`: parser-artifact `0` ingredient row removed; bell pepper restored to `0,5 шт.`.
- `batch2_006`: three parser-artifact `0` ingredient rows removed; tuna, bell pepper, and balsamic `0,5` amounts restored, and tuna is now the protein anchor.

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
| Import only 100 `ready` rows | 605 |
| Import after excluding blockers | 605; exclude 6 `needs_review` rows. |

Estimated 4-week gap closure using `docs/RECIPE_4_WEEK_COVERAGE_AUDIT.md` baseline:

| Gap | Current strict SIMPLE baseline | 4-week demand / target | Batch2 raw contribution | Raw post-import estimate |
|---|---:|---:|---:|---:|
| Dairy-free snacks | 29 | 56 hard minimum | +30 | 59, closes hard gap by 3 |
| Dairy-free mains | 28 | 56 hard minimum, 70 for 1.25x buffer | +49 | 77, closes hard gap and buffer |
| Gluten-free mains | 21 | 56 hard minimum, 70 for 1.25x buffer | +43 | 64, closes hard gap but remains about 6 short of 1.25x buffer |
| Egg-free breakfasts | 30 | 28 hard minimum, HP proxy still thin | +16 | 46 raw egg-free breakfasts; high-protein quality still needs QA |
| Native SIMPLE mains | 55 | 56 hard minimum, 70 for 1.25x buffer | +45 | 100 raw native simple mains |

Coverage value is high, especially for dairy-free snacks/mains and simple native mains. Treat coverage counts as ready-subset estimates only; unresolved sprats rows remain excluded, and unrelated mapping gaps for coconut milk, rice flour/noodles, herring, sardines, beetroot, and split spice rows still need normal importer policy review.

## Recommendation

Do not import all from the current workbook. Import readiness applies to the 100-row `ready` subset only; keep the 6 `needs_review` rows excluded.

1. `batch2_008` is marked `needs_review` and must not be imported as a new recipe.
2. All `ingredient_name_ru = 0` rows and embedded quantities in ingredient names are fixed.
3. The 500-600 g one-portion ingredient rows in `batch2_003`, `batch2_005`, and `batch2_006` are corrected.
4. Tomato sauce rows were normalized to `томаты в собственном соку`; processed cheese was normalized to `творожный сыр`; canonical crab sticks were allowed without decomposition.
5. Fish/vegetarian/fish_free conflicts are fixed for ready rows.
6. Duplicate, mapping, slot-flex, and ready-only blocker checks were rerun locally after the rescue fix.

Remaining before any production promotion: resolve the 6 `needs_review` rows, confirm mapping policy for coconut milk, rice flour, rice noodles, sprats, herring, sardines, beetroot, and split spice rows, then run the normal importer dry-run for the final ready subset.
