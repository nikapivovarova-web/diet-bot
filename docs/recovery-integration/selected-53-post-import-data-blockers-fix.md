# Selected-53 Post-Import Data Blockers Fix

Date: 2026-05-31

## Verdict

READY FOR POST-FIX QUALITY REVIEW.

The seven requested blocker-level recipe-data issues in production recipes
`r684`, `r685`, `r688`, `r691`, `r692`, `r705`, and `r707` are fixed locally.
This does not approve final manual-smoke bot restart; the next step is a
post-fix quality review.

## Provenance

- Working folder: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c`
- Initial working tree: already dirty before this fix, including selected-53
  import data/photos and unrelated payment/runtime/test changes.

## Root Cause And Fixes

| Recipe | Root cause | Exact fix |
| --- | --- | --- |
| `r684` | Source/staging row was green beans, but production ingredient line 1 mapped it to canned red beans. | `line_index=1`: `red_beans` -> `green_beans`, name -> `стручковая фасоль`, state -> `raw`, grams stay `150.0`. |
| `r685` | Source/staging row was rice paper `12 листов`, but production mapped it to raw rice and converted leaves as `12 * 150 г`. | `line_index=1`: `rice` `450.0 г` -> `rice_paper` `45.0 г`, using `3 листа / 45 г` per serving and FDC rice-paper profile. |
| `r688` | Source/staging row was pasta from durum wheat, but production matched `Макароны` to `poppy_seed`. | `line_index=1`: `poppy_seed` -> `pasta_generic`, state -> `dry`, grams stay `50.0`. |
| `r691` | Source/staging row was chicken hearts, but production mapped it to chicken thigh. | `line_index=2`: `chicken_thigh` -> `chicken_hearts`, grams stay `150.0`; added FDC chicken-heart profile. |
| `r692` | Source/staging row was beef liver, but production mapped it to generic beef and kept an unsafe `800 г` one-serving quantity. Staging already marked the amount as looking like several portions. | `line_index=1`: `beef_stew` -> `beef_liver`, `800.0 г` -> `80.0 г`; added FDC beef-liver profile. |
| `r705` | Source/staging row was almond milk, but production mapped it to almonds. | `line_index=2`: `almonds` -> `almond_milk`, grams stay `50.0`. |
| `r707` | Existing `sour_cream` catalog profile was a sour-cream-and-onion potato-chip profile at `547 kcal/100g`. | `sour_cream` catalog profile now uses FDC `171256` (`Cream, sour, reduced fat, cultured`) at `135 kcal/100g`; r707 nutrition recalculated. |

New/updated food catalog profiles:

- Added `beef_liver` from FDC `169451`.
- Added `chicken_hearts` from FDC `171458`.
- Added `rice_paper` from FDC `2708166`.
- Corrected `sour_cream` to FDC `171256`.

## Nutrition Before/After

| Recipe | kcal | protein g | fat g | carbs g |
| --- | ---: | ---: | ---: | ---: |
| `r684` | `283.79 -> 144.29` | `17.07 -> 7.85` | `9.07 -> 7.82` | `35.65 -> 13.87` |
| `r685` | `1821.62 -> 324.47` | `51.50 -> 22.07` | `10.48 -> 8.01` | `368.73 -> 41.49` |
| `r688` | `714.95 -> 633.45` | `65.26 -> 63.02` | `35.41 -> 15.97` | `37.53 -> 60.02` |
| `r691` | `556.61 -> 454.61` | `29.95 -> 28.50` | `30.50 -> 19.58` | `41.46 -> 42.15` |
| `r692` | `1240.95 -> 356.95` | `179.38 -> 20.47` | `42.09 -> 13.07` | `38.27 -> 39.70` |
| `r705` | `623.15 -> 336.65` | `32.89 -> 24.22` | `43.75 -> 19.53` | `28.34 -> 15.02` |
| `r707` | `1065.56 -> 653.56` | `61.05 -> 57.39` | `53.99 -> 28.99` | `93.06 -> 46.02` |

All seven affected nutrition rows remain `calculation_status=ok`.

## Files Changed

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/selected-53-post-import-data-blockers-fix.md`
- `docs/recovery-integration/recovery-status.md`

`src/diet_bot/data/curated_recipes.json` was not changed by this fix pass.
Recipe IDs, titles, steps, and photo paths for the seven affected recipes were
compared before/after and stayed unchanged.

## Validation

- Focused static-field check for r684/r685/r688/r691/r692/r705/r707:
  passed; recipe IDs, titles, steps, recipe keys, source IDs, and image paths
  unchanged.
- Focused blocker assertion script:
  passed.
- `pytest tests/test_curated_recipe_data.py::test_selected53_post_import_blocker_mappings_are_fixed -q`
  - `1 passed in 0.34s`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `248 passed in 125.31s (0:02:05)`
- `python scripts/dev/recipe_content_audit.py --no-write-report`
  - `recipes_checked=710`
  - `ingredients_checked=6478`
  - `foods_checked=362`
  - `nutrition_rows_checked=710`
  - `blocking_findings=0`
  - `warning_findings=1322`
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
  - output under `tmp/pdf-renderer-recovery-smoke`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

## Skipped Or Bounded

- The exact default `python scripts/dev/recipe_content_audit.py` write mode was
  not used because it writes `recipe-content-audit-round2.*`, which is outside
  this prompt's allowed file list. The same audit ran in `--no-write-report`
  mode and found zero blockers.
- The r670/r673/r699 candidate sweep from the prior review was not done because
  this prompt explicitly limited the fix to the seven listed recipes.
- Warning-only items, including refined-oil-to-butter noise and white-bean
  mapping noise, were not changed.

## Not Done

No bot launch, Telegram API/getUpdates, production DB access, payments/refunds,
payment/subscription/runtime/Telegram code changes, secrets/env-file changes,
deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or recovered-bot
work was done.
