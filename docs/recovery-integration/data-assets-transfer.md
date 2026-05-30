# FoodBalance Recovery Integration: Data/Assets Transfer

## Scope

Stage 2 transferred only the safe product data/assets layer from `origin/codex/emergency-stabilization` (`ee24c06709a607e9e7ef2e27bf474f5eb3e9f14b`) onto hardened master (`aa8336a250d0357e819904e0786abfbf1c0ea108`).

No payment/runtime/hardening modules were edited. `telegram_app.py` and `pdf_renderer.py` were not edited. The recovered bot workspace and forbidden archive/CLEAN workspaces were not touched.

## Pre-Transfer Gate

- Initial `git status --short` showed only `?? docs/recovery-integration/`; the directory contained only the allowed `diff-map.md`.
- Current branch was `codex/recover-product-ui-on-hardened-master`.
- Local refs matched expected commits:
  - `origin/master`: `aa8336a250d0357e819904e0786abfbf1c0ea108`
  - `origin/codex/emergency-stabilization`: `ee24c06709a607e9e7ef2e27bf474f5eb3e9f14b`
- `git diff --name-status origin/master origin/codex/emergency-stabilization -- src/diet_bot/data tests` confirmed product data/assets are additive, while product tests are not safe to copy as a set because they delete many hardening tests.

## Data Safety Findings

- Top-level JSON type is `list` for all four curated files in both master and product.
- Product removes 0 master recipe ids and 0 master food ids.
- Product adds 210 recipe ids: the complete `r401-r610` interval.
- Product adds 13 food ids.
- Product recipe, ingredient, nutrition, and food references are internally consistent.
- Product media references for `r401-r610` all resolve to local `recipe_photos/rNNN.jpg` assets.
- Product adds `coverage_priority` on recipes and `recipe_key` on some ingredient/nutrition rows; these are additive fields and are compatible with current loaders.

## Transfer Method

The curated JSON files were merged conservatively:

- Existing master rows were kept for existing recipe ids, food ids, ingredient rows, and nutrition rows.
- Product-only recipes `r401-r610` were added.
- Product-only ingredient and nutrition rows for `r401-r610` were added.
- Product-only foods were appended.
- Product rows `r488_bystryy_sup_s_nutom_i_kuritsey` and `r489_rulet_iz_lavasha_s_humusom` had only `title_ru` disambiguated because their original titles duplicated master `r637` and `r640`; without this data-only adjustment, `built_in_recipes()` dedupe hid two master ids from the runtime catalog.

## Counts

| dataset | master | after transfer | added |
|---|---:|---:|---:|
| curated recipes | 455 | 665 | 210 |
| curated foods | 348 | 361 | 13 |
| recipe ingredients | 4541 | 6130 | 1589 |
| recipe nutrition | 455 | 665 | 210 |
| runtime `curated_recipes()` | 455 | 665 | 210 |

Runtime `curated_foods()` now returns 353 foods after the existing CIS-friendly filtering/extra-row logic.

## Added Ids

Recipe ids added: full contiguous range `r401` through `r610`.

First added id: `r401_farshirovannye_pertsy_s_risom_i_ovoschami_v_duhovke`.

Last added id: `r610_bystraya_pitstsa_na_hlebe`.

Food ids added:

`chicken_liver`, `cod_liver_canned_drained`, `cornmeal`, `falafel_prepared`, `grapes`, `korean_carrot`, `pumpkin`, `split_peas`, `sprats`, `udon_noodles`, `rice_noodles`, `herring`, `sardines`.

## Added Assets

- `src/diet_bot/data/recipe_photos/r401.jpg` through `src/diet_bot/data/recipe_photos/r610.jpg`
  - 210 JPEG files
  - total size: 23,463,502 bytes
  - min/max file size: 44,779 / 197,714 bytes
- `src/diet_bot/data/foodbalance_pdf_logo.png`
  - PNG, 444,713 bytes
- `src/diet_bot/data/foodbalance_pdf_qr.png`
  - PNG, 3,838 bytes

No renderer/runtime changes were made to consume the logo/QR yet.

## Files Changed

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/foodbalance_pdf_logo.png`
- `src/diet_bot/data/foodbalance_pdf_qr.png`
- `src/diet_bot/data/recipe_photos/r401.jpg` through `src/diet_bot/data/recipe_photos/r610.jpg`
- `tests/test_curated_recipe_data.py`
- `tests/test_recipe_traits.py`
- `docs/recovery-integration/data-assets-transfer.md`

Test edits were minimal and additive/expectation updates for the expanded curated catalog.

## Checks Run

Passed:

- Lightweight schema/import/media check:
  - loaded all four curated JSON files;
  - imported `diet_bot.curated_data` and `diet_bot.recipe_catalog`;
  - verified 665 recipe rows, 361 food rows, 6130 ingredient rows, 665 nutrition rows;
  - verified all recipe image references exist locally;
  - verified all `r401-r610` photos are JPEGs;
  - verified logo/QR assets are PNGs;
  - verified all runtime curated ids survive `built_in_recipes()` dedupe.
- `pytest tests/test_curated_recipe_data.py -q`
  - `19 passed`
- `pytest tests/test_recipe_traits.py -q`
  - `70 passed`
- `pytest tests/test_telegram_app_photos.py -q`
  - `149 passed`
- `pytest tests/test_pdf_renderer.py -q`
  - `5 passed`
- Combined required gate:
  - `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py tests/test_pdf_renderer.py -q`
  - `243 passed in 77.04s`

Additional optional builder/selection suite:

- `pytest tests/test_builder_recipe_cache.py tests/test_safety_and_builder.py tests/test_vectors_and_shopping.py tests/test_weekly_selector_scoring.py -q`
  - `59 passed, 1 skipped, 2 failed`
  - Failures:
    - `tests/test_safety_and_builder.py::test_five_repeat_generations_keep_key_meals_unique`
    - `tests/test_safety_and_builder.py::test_repeat_generations_can_avoid_recent_recipe_families`
  - Investigation result: product data exposes existing recipe-selection edge cases. One example is flexible recipe `r601_tost_s_arahisovoy_pastoy_i_yablokom`, whose native slot is `breakfast` but it can be selected as `snack`; current avoidance filtering checks the native memory key before final slot assignment, while the emitted meal key uses the selected slot. Fixing this belongs to a separate runtime/builder stage, not this data/assets-only transfer.

## Risks For Next Stage

- PDF renderer stage can proceed with the new local assets and expanded recipe/photo catalog.
- The logo/QR assets are copied but not wired into `pdf_renderer.py`; QR destination/bot handle should still be manually confirmed before release.
- Before broader UI/runtime release, handle the optional builder variety/avoidance findings in a separate runtime-safe stage. No runtime changes were made here by design.
