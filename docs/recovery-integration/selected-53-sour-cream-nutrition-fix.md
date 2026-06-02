# Selected-53 Sour Cream Nutrition Fix

## Verdict

READY FOR POST-FIX QUALITY REVIEW.

Do not proceed to final manual-smoke bot restart yet. The `sour_cream`
food-profile side effect found by the selected-53 post-fix quality review is
fixed locally: every saved nutrition row for recipes that use
`food_id=sour_cream` now matches recalculation from the current food catalog
and current ingredient grams.

## Provenance

- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- Initial checkout state was dirty before this scoped fix. Existing unrelated
  modified/untracked files were left in place.
- Forbidden source data files were hash-checked before and after the fix and
  stayed unchanged:
  - `src/diet_bot/data/curated_foods.json`:
    `16CDF243024BE39CFC4D9D06E4B492500A8FEE45FD3F9F372B758CFE574A7E9B`
  - `src/diet_bot/data/curated_recipes.json`:
    `8FA320364EB735A5C4878BA46C6F7731EF12205F533EB91FDA1AB4DCC84A1B05`
  - `src/diet_bot/data/curated_recipe_ingredients.json`:
    `06118CA596F1F01CC59DD3B109D0B174C5A0E4A6057F0BF52751E297FCFF38D8`

## Root Cause

The previous selected-53 blocker fix corrected the `sour_cream` catalog profile
from a sour-cream-and-onion potato-chip profile to FDC `171256`, but only
`r707` was recalculated. The other saved nutrition rows that include
`food_id=sour_cream` still reflected the old profile, leaving stale user-facing
KBJU values.

## Fix

Recalculated saved nutrition rows for all `26` recipes whose ingredients use
`food_id=sour_cream`, using only:

- current `src/diet_bot/data/curated_foods.json`
- current `src/diet_bot/data/curated_recipe_ingredients.json` grams
- the existing per-100g nutrient summing behavior used by the curated data
  builder

No food profiles, recipes, ingredient mappings, photos, runtime code, payment
code, Telegram code, secrets, deploy config, production DB state, or bot process
were changed.

## Explicit Before/After

| Recipe | Sour cream | Before saved nutrition | After recalculation | Result |
| --- | ---: | --- | --- | --- |
| `r670` | `30.0 g` | `421.73 kcal`, `30.02 P`, `19.76 F`, `33.36 C` | `298.13 kcal`, `28.93 P`, `12.26 F`, `19.25 C` | PASS |
| `r673` | `25.0 g` | `374.60 kcal`, `30.58 P`, `19.84 F`, `18.62 C` | `271.60 kcal`, `29.66 P`, `13.59 F`, `6.86 C` | PASS |
| `r707` | `100.0 g` | `653.56 kcal`, `57.39 P`, `28.99 F`, `46.02 C` | `653.56 kcal`, `57.39 P`, `28.99 F`, `46.02 C` | PASS; already current |

## Sour Cream Proof

- RED focused invariant before data update:
  `pytest tests/test_curated_recipe_data.py::test_sour_cream_recipe_nutrition_matches_current_food_profile -q`
  failed because saved rows still diverged from current recalculation.
- Pre-write analysis:
  - `sour_cream_recipe_count=26`
  - `mismatched_before_count=25`
  - `mismatched_after_count=0`
- Post-write independent check:
  - `sour_cream_recipe_count=26`
  - `mismatched_before_count=0`
  - `mismatched_after_count=0`
- Focused invariant after data update:
  - `1 passed`

Artifacts:

- `tmp/selected-53-sour-cream-nutrition-fix/recalc_sour_cream_nutrition.py`
- `tmp/selected-53-sour-cream-nutrition-fix/sour_cream_recalc_write_report.json`
- `tmp/selected-53-sour-cream-nutrition-fix/sour_cream_recalc_write_report.csv`
- `tmp/selected-53-sour-cream-nutrition-fix/sour_cream_recalc_check_report.json`
- `tmp/selected-53-sour-cream-nutrition-fix/sour_cream_recalc_check_report.csv`

## Preserved Previous Fixed Mappings

| Recipe | Expected preserved fix | Evidence | Result |
| --- | --- | --- | --- |
| `r684` | `green_beans` | `line_index=1`, `food_id=green_beans`, `grams=150.0` | PASS |
| `r685` | `rice_paper 45g` | `line_index=1`, `food_id=rice_paper`, `grams=45.0` | PASS |
| `r688` | `pasta_generic` | `line_index=1`, `food_id=pasta_generic`, `grams=50.0` | PASS |
| `r691` | `chicken_hearts` | `line_index=2`, `food_id=chicken_hearts`, `grams=150.0` | PASS |
| `r692` | `beef_liver 80g` | `line_index=1`, `food_id=beef_liver`, `grams=80.0` | PASS |
| `r705` | `almond_milk` | `line_index=2`, `food_id=almond_milk`, `grams=50.0` | PASS |
| `r707` | `sour_cream` normal profile | FDC `171256`, `135 kcal`, `2.94 P`, `12.0 F`, `4.26 C` per 100g | PASS |

## Selected-53 Blocker Check

The new selected-53 range `r666` through `r710` has no new blocker-level
nutrition mismatch after this fix. The earlier warning-only approximations were
not changed:

- beef tongue to generic beef
- kvass to water
- `r699`

## Validation

- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `249 passed in 117.14s`
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
- `git diff --check`
  - exit code `0`
  - only LF-to-CRLF warnings in the existing dirty working copy

## Files Changed

- `src/diet_bot/data/curated_recipe_nutrition.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/selected-53-sour-cream-nutrition-fix.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/selected-53-sour-cream-nutrition-fix/**`

## Not Done

- No `curated_foods.json`, `curated_recipes.json`, or
  `curated_recipe_ingredients.json` edits.
- No photo edits.
- No warning-only approximation edits.
- No payment, subscription, runtime, Telegram, or bot code changes.
- No bot launch, Telegram API/getUpdates, production DB, payment/refund,
  deploy, push, commit, tag, PR, secret/env-file, archive, `New project 2
  CLEAN`, or recovered-bot work.

## Remaining Work

- Post-fix quality review.
- Final manual-smoke bot restart.
- Payment sandbox/provider smoke.
- Safety snapshot/commit.
- Deploy/VPS plan.
