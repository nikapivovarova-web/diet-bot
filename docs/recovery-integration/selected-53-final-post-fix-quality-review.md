# Selected-53 Final Post-Fix Quality Review

Date: 2026-05-31

## Verdict

READY FOR FINAL MANUAL SMOKE.

The selected-53 production import is internally consistent after the recipe-data
blocker fixes and the `sour_cream` nutrition side-effect fix. This clears only
the next local/manual bot-restart smoke gate. Payment sandbox/provider smoke,
safety snapshot/commit, and deploy/VPS planning remain separate gates.

## Scope

Reviewed production recipes `r666` through `r710`, their ingredient rows,
nutrition rows, food-profile references, local photos, and selected-53 staging
source coverage.

Read-only inputs:

- `src/diet_bot/data/**`
- `staging_recipes/selected-53/**`
- `docs/recovery-integration/selected-53-post-import-quality-review.md`
- `docs/recovery-integration/selected-53-post-import-data-blockers-fix.md`
- `docs/recovery-integration/selected-53-sour-cream-nutrition-fix.md`

Written outputs:

- `docs/recovery-integration/selected-53-final-post-fix-quality-review.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/selected-53-final-post-fix-review/**`

No production data, food profiles, recipes, ingredients, nutrition rows,
photos, runtime/payment/Telegram code, secrets/env files, archive, `New project
2 CLEAN`, or recovered-bot areas were changed.

## Provenance

- Working folder: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c`
- Initial working tree: dirty before this review, with existing selected-53
  import/fix files and unrelated payment/runtime/test changes already present.

## Structured Data Review

Machine audit artifact:

- `tmp/selected-53-final-post-fix-review/structured_audit.json`
- `tmp/selected-53-final-post-fix-review/selected_r666_r710_nutrition_summary.csv`

Results for `r666` through `r710`:

- Recipe rows: `45`; contiguous range, no missing recipe numbers.
- Ingredient rows: `348`; all `45` recipes have ingredient rows.
- Nutrition rows: `45`; all have `calculation_status=ok`.
- Local photos: `45/45` exist and open as JPEG.
- Photo dimensions: `35` at `1254x1254`, `9` at `1402x1122`, `1` at
  `1536x1024`.
- Recipe IDs: unique.
- Titles: unique.
- Missing `food_id` references: `0`.
- Material nutrition mismatches against current food catalog and ingredient
  grams: `0`.
- Hard outliers for kcal/protein/fat/carbs/single ingredient grams: `0`.
- Staging coverage: `45` ready-or-approved source rows imported; `7`
  user-skipped rows not imported; skipped source IDs imported: `0`.

The independent full-nutrient recalculation found `28` selected rows with only
`0.01` rounding variance in non-blocking nutrient fields. KBJU and material
nutrient comparisons match; this is rounding noise, not a blocker.

Highest selected-53 nutrition values inspected:

| Recipe | kcal | Protein | Fat | Carbs | Review |
| --- | ---: | ---: | ---: | ---: | --- |
| `r706` | `757.80` | `90.70` | `21.87` | `43.73` | Highest protein/kcal row; source-preserved `400 g` calamari, no missing food or hard threshold breach. |
| `r671` | `673.17` | `32.61` | `48.39` | `27.56` | Within range for a main dish. |
| `r667` | `659.04` | `33.66` | `54.26` | `8.87` | Within range for a burger-style main dish. |
| `r707` | `653.56` | `57.39` | `28.99` | `46.02` | Matches recalculation after `sour_cream` correction. |
| `r688` | `633.45` | `63.02` | `15.97` | `60.02` | Matches preserved `pasta_generic` fix. |

## Preserved Seven Fixes

All seven requested recipe fixes remain present:

| Recipe | Expected fix | Evidence | Result |
| --- | --- | --- | --- |
| `r684` | `green_beans` | `line_index=1`, `food_id=green_beans`, `grams=150.0` | PASS |
| `r685` | `rice_paper 45g` | `line_index=1`, `food_id=rice_paper`, `grams=45.0` | PASS |
| `r688` | `pasta_generic` | `line_index=1`, `food_id=pasta_generic`, `grams=50.0` | PASS |
| `r691` | `chicken_hearts` | `line_index=2`, `food_id=chicken_hearts`, `grams=150.0` | PASS |
| `r692` | `beef_liver 80g` | `line_index=1`, `food_id=beef_liver`, `grams=80.0` | PASS |
| `r705` | `almond_milk` | `line_index=2`, `food_id=almond_milk`, `grams=50.0` | PASS |
| `r707` | corrected `sour_cream` profile | FDC `171256`, `135 kcal`, `2.94 P`, `12.0 F`, `4.26 C` per 100g | PASS |

## Sour Cream Review

Machine artifacts:

- `tmp/selected-53-final-post-fix-review/sour_cream_recalc_check.csv`
- `tmp/selected-53-final-post-fix-review/structured_audit.json`

Results:

- Recipes using `food_id=sour_cream`: `26`.
- Material saved-nutrition mismatches after recalculation: `0`.
- KBJU mismatches for the selected-53 explicit rows: `0`.
- Full-nutrient rounding-only rows: `11`; all differences are `0.01` and do
  not affect KBJU/material consistency.

Explicit selected-53 proof:

| Recipe | Sour cream | Saved KBJU | Recalc KBJU | Result |
| --- | ---: | --- | --- | --- |
| `r670` | `30.0 g` | `298.13 kcal`, `28.93 P`, `12.26 F`, `19.25 C` | same | PASS |
| `r673` | `25.0 g` | `271.60 kcal`, `29.66 P`, `13.59 F`, `6.86 C` | same | PASS |
| `r707` | `100.0 g` | `653.56 kcal`, `57.39 P`, `28.99 F`, `46.02 C` | same | PASS |

## Candidate Sweep

The prior candidate approximations remain warning-only, not blockers:

- `r670`: beef tongue remains approximated by generic beef and kvass by water;
  saved nutrition matches current catalog and totals are within one-serving
  thresholds.
- `r673`: turkey sausage remains approximated by lean poultry and kvass by
  water; saved nutrition matches current catalog and totals are within
  one-serving thresholds.
- `r699`: kvass remains approximated by water; saved nutrition matches current
  catalog and totals are within one-serving thresholds.

Additional warning-only observation:

- `r706` remains a high-protein/high-calamari row (`400 g` calamari,
  `90.70 g` protein), but it is source-preserved, internally consistent, has no
  missing food/profile/photo issue, and stays below the hard outlier thresholds
  used for this release gate.

## Validation

- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `249 passed in 143.87s (0:02:23)`
- `python scripts/dev/recipe_content_audit.py --no-write-report`
  - `recipes_checked=710`
  - `ingredients_checked=6478`
  - `foods_checked=362`
  - `nutrition_rows_checked=710`
  - `blocking_findings=0`
  - `warning_findings=1322`
  - warning categories: `ingredient_missing_from_steps=995`,
    `truncation_fragments=193`, `missing_approximate_measures=134`
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
  - output under `tmp/pdf-renderer-recovery-smoke`
  - coverage is `r401-r610`, so it does not cover selected-53 `r666-r710`.
- Temporary selected-53 local PDF sample:
  - `rendered_pdfs=2`
  - `recipes_checked=45`
  - output under `tmp/selected-53-final-post-fix-review/pdf-sample`
  - `selected53-r666-r710-01.pdf` size: `2,282,641` bytes
  - `selected53-r666-r710-02.pdf` size: `1,588,275` bytes
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

## Not Done

No bot launch, no Telegram API/getUpdates, no production DB, no payment/refund
or provider action, no runtime/payment/Telegram code change, no production
data/profile/recipe/ingredient/nutrition/photo change, no secrets/env-file
change, no deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or
recovered-bot work was done.

## Next Step

Proceed to final manual-smoke bot restart only. Payment sandbox/provider smoke,
safety snapshot/commit, and deploy/VPS planning remain separate later stages.
