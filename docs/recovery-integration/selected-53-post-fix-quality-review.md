# Selected-53 Post-Fix Quality Review

Date: 2026-05-31

## Verdict

BLOCKED.

Do not proceed to final manual-smoke bot restart yet. The seven requested
recipe-data fixes for `r684`, `r685`, `r688`, `r691`, `r692`, `r705`, and
`r707` are present, but the `sour_cream` catalog fix created a broader
nutrition consistency blocker: most saved nutrition rows that use
`sour_cream` still reflect the previous food profile.

## Scope

Reviewed only the selected-53 production range `r666` through `r710`, the
current food catalog entries needed by that range, staging selected-53 inputs,
and the two prerequisite reports:

- `docs/recovery-integration/selected-53-post-import-quality-review.md`
- `docs/recovery-integration/selected-53-post-import-data-blockers-fix.md`

Temporary read-only analysis artifacts were written under:

- `tmp/selected-53-post-fix-review/post_fix_data_audit.json`
- `tmp/selected-53-post-fix-review/r666_r710_nutrition_summary.csv`
- `tmp/selected-53-post-fix-review/r666_r710_recalc_check.csv`
- `tmp/selected-53-post-fix-review/r666_r710_semantic_warning_candidates.csv`
- `tmp/selected-53-post-fix-review/sour_cream_recalc_check.csv`

No production data, food profiles, recipes, ingredients, nutrition rows,
photos, app/runtime/payment/Telegram code, tests, secrets/env files, deploy,
push, commit, tag, PR, archive, `New project 2 CLEAN`, or recovered-bot areas
were changed.

## Provenance

- Working folder: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- Initial working tree: already dirty before this review, including the
  selected-53 import/fix data and unrelated payment/runtime/test changes.

## Seven Requested Fixes

All seven requested fixes are present in the current data.

| Recipe | Check | Current evidence | Result |
| --- | --- | --- | --- |
| `r684` | Green beans are not red beans. | `line_index=1`: `food_id=green_beans`, `grams=150.0`; no `red_beans` in the recipe. Nutrition: `144.29 kcal`, `7.85 g protein`, `7.82 g fat`, `13.87 g carbs`. | PASS |
| `r685` | Rice paper is not raw rice or `450 g`. | `line_index=1`: `food_id=rice_paper`, `grams=45.0`; no `rice` in the recipe. Nutrition: `324.47 kcal`, `22.07 g protein`, `8.01 g fat`, `41.49 g carbs`. | PASS |
| `r688` | Pasta is not poppy seed. | `line_index=1`: `food_id=pasta_generic`, `grams=50.0`; no `poppy_seed` in the recipe. Nutrition: `633.45 kcal`, `63.02 g protein`, `15.97 g fat`, `60.02 g carbs`. | PASS |
| `r691` | Chicken hearts are not chicken thigh. | `line_index=2`: `food_id=chicken_hearts`, `grams=150.0`; no `chicken_thigh` in the recipe. Nutrition: `454.61 kcal`, `28.50 g protein`, `19.58 g fat`, `42.15 g carbs`. | PASS |
| `r692` | Beef liver is not generic beef and not `800 g`. | `line_index=1`: `food_id=beef_liver`, `grams=80.0`; no `beef_stew` in the recipe. Nutrition: `356.95 kcal`, `20.47 g protein`, `13.07 g fat`, `39.70 g carbs`. | PASS |
| `r705` | Almond milk is not almonds. | `line_index=2`: `food_id=almond_milk`, `grams=50.0`; no `almonds` in the recipe. Nutrition: `336.65 kcal`, `24.22 g protein`, `19.53 g fat`, `15.02 g carbs`. | PASS |
| `r707` | Sour-cream nutrition is no longer the potato-chip profile. | `sour_cream` now uses FDC `171256`, `Cream, sour, reduced fat, cultured`: `135 kcal`, `2.94 g protein`, `12.0 g fat`, `4.26 g carbs` per `100 g`. `r707` recalculates consistently to `653.56 kcal`, `57.39 g protein`, `28.99 g fat`, `46.02 g carbs`. | PASS |

## Blocker

The `sour_cream` food profile was corrected, but the saved nutrition rows for
other recipes using `sour_cream` were not recalculated.

The current catalog profile is:

- `food_id=sour_cream`
- FDC `171256`
- `135 kcal`, `2.94 g protein`, `12.0 g fat`, `4.26 g carbs` per `100 g`

Current impact:

- `26` recipes use `food_id=sour_cream`.
- `r707` matches the current profile.
- `25` other saved nutrition rows do not match a recalculation from current
  `curated_foods.json`.
- In the selected-53 range, the blocker affects `r670` and `r673`.

Selected-53 stale rows:

| Recipe | Sour cream | Saved nutrition | Recalculated from current foods | Delta |
| --- | ---: | --- | --- | --- |
| `r670` | `30.0 g` | `421.73 kcal`, `30.02 P`, `19.76 F`, `33.36 C` | `298.13 kcal`, `28.93 P`, `12.26 F`, `19.25 C` | `+123.60 kcal`, `+7.50 F`, `+14.11 C` stale overstatement |
| `r673` | `25.0 g` | `374.60 kcal`, `30.58 P`, `19.84 F`, `18.62 C` | `271.60 kcal`, `29.66 P`, `13.59 F`, `6.86 C` | `+103.00 kcal`, `+6.25 F`, `+11.76 C` stale overstatement |

This blocks final manual smoke because user-facing KBJU and any nutrition-based
selection behavior can read inconsistent saved nutrition rows after the food
catalog change.

## r666-r710 Range Findings

The current `r666` through `r710` recalculation check found only the two stale
nutrition rows above: `r670` and `r673`.

No hard outlier was found for:

- missing `food_id` references;
- non-`ok` calculation status;
- unmatched ingredients;
- `energy_kcal > 900`;
- `protein_g > 95`;
- `fat_g > 65`;
- `carbohydrate_g > 110`;
- single ingredient quantity above `500 g`.

Warning-level quantity/profile notes found during the scan:

- `r689`: lettuce is `200 g` against `lettuce.max_per_meal_g=180`; this is a
  small source-preserving amount warning, not a blocker.
- `r706`: calamari is `400 g` against `calamari.max_per_meal_g=240`; staging
  source explicitly says the ingredients are for one portion. This is a high
  protein/large seafood-portion warning, not classified as a new blocker in
  this pass.
- `r707`: sour cream is `100 g` against `sour_cream.max_per_meal_g=80`; the
  saved nutrition now matches the corrected profile, so this is a quantity
  warning, not the current blocker.

## Candidate Sweep Items

Previously noted candidate sweep items were checked read-only.

| Recipe | Current status |
| --- | --- |
| `r670` | BLOCKER due stale saved nutrition after the `sour_cream` profile change. The separate semantic mappings, beef tongue to generic beef and kvass to water, remain warning-level approximation issues in this review. |
| `r673` | BLOCKER due stale saved nutrition after the `sour_cream` profile change. The separate semantic mappings, turkey sausage to cooked breast and kvass to water, remain warning-level approximation issues in this review. |
| `r699` | Warning-only: kvass is mapped to water, but there is no stale nutrition mismatch, missing `food_id`, or hard kcal/protein/fat/carbs/grams outlier. |

Other warning-only semantic candidates in `r666` through `r710` are captured in
`tmp/selected-53-post-fix-review/r666_r710_semantic_warning_candidates.csv`.
They include refined oil mapped to butter in small amounts and white beans
mapped to red beans in bean-salad recipes.

## Commands

Completed:

- `git status --short`
  - captured dirty working tree before this review.
- `git branch --show-current`
  - `codex/recover-product-ui-on-hardened-master`
- `git rev-parse HEAD`
  - `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- Read prerequisite reports:
  - `docs/recovery-integration/selected-53-post-import-quality-review.md`
  - `docs/recovery-integration/selected-53-post-import-data-blockers-fix.md`
- Local read-only data checks over the curated JSON and staging selected-53
  inputs, with temporary artifacts under `tmp/selected-53-post-fix-review`.

Stopped after blocker discovery, per the prompt stop conditions:

- Did not run
  `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`.
- Did not run `python scripts/dev/recipe_content_audit.py --no-write-report`.
- Did not run `python scripts/dev/pdf_renderer_recovery_smoke.py`.
- Did not run `git diff --check`.
- Did not create a PDF sample artifact.

## Next Fix Prompt

FoodBalance: fix selected-53 post-fix sour_cream nutrition side effect.

Working folder: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`.
Allowed: update only `src/diet_bot/data/curated_recipe_nutrition.json`,
focused recipe-data tests if needed, `docs/recovery-integration` status/report
docs, and `tmp/selected-53-post-fix-review/**` artifacts. Do not change
`curated_foods.json`, recipe ingredients, recipe titles/steps/photos, runtime,
payment, Telegram, secrets/env files, production DB, bot process, deploy, push,
commit, tag, PR, archive, `New project 2 CLEAN`, or recovered-bot work.

Recalculate saved nutrition rows for every recipe that uses
`food_id=sour_cream` so they match the current `sour_cream` food profile,
with explicit proof for `r670`, `r673`, and `r707`. Preserve the seven already
fixed selected-53 mappings for `r684`, `r685`, `r688`, `r691`, `r692`, `r705`,
and `r707`. Rerun the focused recipe/data/photo pytest command, the no-write
recipe content audit, PDF renderer recovery smoke, and `git diff --check`.
Then update recovery docs with the verdict and stop before manual smoke.
