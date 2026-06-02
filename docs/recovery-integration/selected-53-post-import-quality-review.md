# Selected-53 Post-Import Quality Review

Date: 2026-05-31

## Verdict

BLOCKED.

Do not proceed to final manual-smoke bot restart yet. The import itself is
present as `r666` through `r710`, but the post-import data review found
blocker-level recipe quality issues in the new production range.

## Scope

Reviewed only the newly imported production recipes `r666` through `r710`.

Read-only inputs:

- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/recipe_photos/r666.jpg` through `r710.jpg`
- `staging_recipes/selected-53/**`
- `tmp/selected-53-import/**`
- `docs/recovery-integration/selected-53-import.md`

No production data, recipes, ingredients, nutrition rows, photos, app code,
bot runtime, Telegram API, production DB, payments, deploy, git publish, env
files, archive, `New project 2 CLEAN`, or recovered-bot areas were changed.

## Provenance

- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c`
- Initial working tree: already dirty before this review, including the
  selected-53 import data/photos and unrelated payment/runtime/test changes.

## Coverage

Structured review covered all 45 new recipes:

`r666`, `r667`, `r668`, `r669`, `r670`, `r671`, `r672`, `r673`, `r674`,
`r675`, `r676`, `r677`, `r678`, `r679`, `r680`, `r681`, `r682`, `r683`,
`r684`, `r685`, `r686`, `r687`, `r688`, `r689`, `r690`, `r691`, `r692`,
`r693`, `r694`, `r695`, `r696`, `r697`, `r698`, `r699`, `r700`, `r701`,
`r702`, `r703`, `r704`, `r705`, `r706`, `r707`, `r708`, `r709`, `r710`.

Confirmed structural import facts:

- Production recipe range is contiguous: `r666` through `r710`.
- Production recipe count: 45.
- Production ingredient rows in this range: 348.
- Production nutrition rows in this range: 45.
- Staging `ready_for_import=yes` rows: 45.
- Skipped staging rows: 7, and none intersect the imported source IDs.
- Production recipe, ingredient, and nutrition records match
  `tmp/selected-53-import/selected53_import_summary.json`.
- Photo files exist and open as JPGs for all `r666` through `r710`.
- Photo dimensions: 35 files at `1254x1254`, 9 files at `1402x1122`,
  1 file at `1536x1024`.

## Blockers

These are blocker-level because they can produce wrong nutrition, wrong
selection behavior, or wrong PDF/shopping-list/user-facing ingredient meaning
for the new production recipes.

| Recipe | Source | Blocker | Evidence | Impact |
| --- | --- | --- | --- | --- |
| `r684` | `R59` | Primary ingredient mapped to the wrong food. | Raw `Зелёная фасоль - 600 г` became `food_id=red_beans`, `ingredient_name_ru=красная фасоль консервированная`, `grams=150`. | Recipe title says green beans, but nutrition/shopping data uses red beans. |
| `r685` | `R91` | Rice paper mapped as raw rice with impossible quantity. | Raw `Рисовая бумага 12 листов` became `food_id=rice`, `grams=450`, `conversion_note=12 * 150 г`; nutrition is `1821.62 kcal`, `368.73 g carbs` for a snack. | Breaks nutrition, selection, and user meaning. |
| `r688` | `R375` | Pasta mapped to poppy seed. | Raw `Макароны Barilla или любые из твёрдых сортов пшеницы - 50 г` became `food_id=poppy_seed`, `ingredient_name_ru=мак`, `grams=50`; this exceeds `poppy_seed.max_per_meal_g=20`. | Shopping/PDF and nutrition use poppy seed instead of pasta. |
| `r691` | `R145` | Chicken hearts mapped to chicken thigh. | Raw `Куриные сердечки 150 г` became `food_id=chicken_thigh`, `ingredient_name_ru=куриное бедро`. | Primary protein and user-facing meaning are wrong. |
| `r692` | `R135` | Beef liver mapped to generic beef and imported as an unsafe one-serving quantity. | Raw `Говяжья печень 800 г` became `food_id=beef_stew`, `grams=800`; nutrition is `1240.95 kcal`, `179.38 g protein`. | Breaks nutrition and user meaning; the one-serving quantity is not credible for launch data. |
| `r705` | `R123` | Almond milk mapped to almonds. | Raw `Молоко миндальное - 50 мл` became `food_id=almonds`, `ingredient_name_ru=миндаль`, `grams=50`. | Adds nut calories/fat and shows the wrong ingredient. |
| `r707` | `R402` | Nutrition is inflated by an existing sour-cream food profile used by the new recipe. | Raw `сметана 15% - 100 г` uses `food_id=sour_cream`, whose current nutrients are `547 kcal/100g` and `51.3 g carbs/100g`; recipe total is `1065.56 kcal`. | The recipe's nutrition is not credible for a one-portion FoodBalance meal. |

Additional blocker candidates to sweep in the same fix pass:

- `r670`: `Отварной говяжий язык` is mapped to generic `beef_stew`; `несладкий квас` is mapped to `water`.
- `r673`: `индюшачья варёная колбаса` is mapped to cooked turkey/chicken breast; `квас` is mapped to `water`.
- `r699`: `квас` is mapped to `water`.

Those three did not create extreme calories, but they do affect PDF/shopping
and user-facing ingredient meaning for okroshka-style recipes.

## Warning-Only Findings

The existing import audit CSV in `tmp/selected-53-import` has no blockers for
`r666` through `r710`, but it contains 104 warnings for the new range:

- 81 `ingredient_missing_from_steps` warnings.
- 22 `truncation_fragments` / weak final sentence warnings.
- 1 `missing_approximate_measures` warning for `r687` cottage cheese.

These are warning-only because they are mostly alias/audit limitations or
low-risk wording issues, not direct production data blockers.

Other warning-level mapping noise found during structured review:

- `r681`, `r684`, `r685`, and `r693` map small amounts of refined oil to
  `butter`. This should be swept during the fix pass, but the severe blockers
  above are enough to stop this review before release smoke.
- `r693`, `r695`, and `r701` map white beans to `red_beans`. Nutritionally this
  is close enough to classify as warning in this review, but it can still make
  the shopping list inconsistent with the recipe title.

## Checks

Completed in this review:

- `git status --short`: captured initial dirty tree.
- `git branch --show-current`: `codex/recover-product-ui-on-hardened-master`.
- `git rev-parse --short HEAD`: `13d085c`.
- Read `docs/recovery-integration/selected-53-import.md`.
- Structured local review of all `r666` through `r710` titles, ingredients,
  measures, nutrition rows, photo paths, categories, slots, tags, staging
  source coverage, and import-summary equality.
- Read existing import audit findings from
  `tmp/selected-53-import/recipe-content-audit-findings.csv` and filtered them
  to `r666` through `r710`.

Stopped because blockers were found:

- Did not run `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`.
- Did not run a fresh `python scripts/dev/recipe_content_audit.py`, because
  the default command writes outside this prompt's allowed files and the
  blocker stop condition had already fired.
- Did not run `python scripts/dev/pdf_renderer_recovery_smoke.py`.
- Did not create a new `r666-r710` PDF sample.
- Did not visually inspect the full photo/contact sheet after blocker
  discovery.
- Did not run final `git diff --check`.

## Next Fix Prompt

FoodBalance: fix selected-53 post-import data blockers for r666-r710.

Working folder: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`.
Allowed: update only `src/diet_bot/data/**`, focused recipe-data tests, and
recovery docs. Do not run bot, Telegram API, production DB, payments, deploy,
push, commit, tag, PR, env/secrets, archive, `New project 2 CLEAN`, or
recovered-bot work.

Fix only the r666-r710 blockers from
`docs/recovery-integration/selected-53-post-import-quality-review.md`:
wrong primary mappings for `r684`, `r685`, `r688`, `r691`, `r692`, `r705`,
nutrition inflation for `r707`, and sweep the listed blocker candidates
`r670`, `r673`, `r699`. Recalculate nutrition for changed recipes, rerun the
focused recipe/data/photo tests, run a read-only recipe audit variant or an
allowed report path, create a temporary local PDF sample covering r666-r710,
then update the recovery docs with the verdict. Stop before manual smoke.
