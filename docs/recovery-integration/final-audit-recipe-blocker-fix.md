# Final Audit Recipe Blocker Fix

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Scope

Fixed only the two requested final pre-release audit items:

- `BLOCKER-1`: production recipe/food nutrition outliers, starting from
  `acai_puree`, `r057`, and `r154`.
- `HIGH-1`: broken user-facing text in `r678`.

Forbidden areas remained untouched: worker/runtime/payment/Telegram code,
Telegram API/getUpdates, bot process, production DB, real payments/refunds,
deploy/push/commit/tag/PR, secrets/env files, archive, `New project 2 CLEAN`,
and recovered bot.

## Root Cause

- `acai_puree` was mapped to `Baking chocolate, unsweetened, liquid`, which
  inflated `r057` to `1485.15 kcal`, `121.92 g fat`, and `150.90 g carbs`.
- Several legacy hard outliers from
  `tmp/final-pre-release-audit/recipes-photos/all-production-structural-scan.json`
  were stale cooked/raw or portion conversions: cooked rice counted through the
  dry `rice` profile, canned-bean fractions counted as whole cans, retained pan
  oil counted as the full cooking bath, bone-in chicken counted as all edible
  meat, bacon strips overcounted, cod-liver half cans counted as full cans, and
  explicit `10%`/`20%` cream rows reused the heavy-cream profile.
- `r157` also used the old `cheddar` profile from a cheddar-pretzel snack
  source, so the cheese row distorted carbs.
- `r678` had a copied OCR/source-text tail: `подде жки нкции печени.`

## Changed Files

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/final-audit-recipe-blocker-fix.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/final-audit-recipe-blocker-fix/**`

## Foods And Recipes

Changed food profiles / additions:

- `acai_puree`: replaced baking-chocolate source with unsweetened acai puree.
- `cheddar`: replaced cheddar-pretzel snack source with cheddar cheese.
- Added `cooked_rice`, `cream_10_percent`, `cream_20_percent`,
  `lean_beef_ground` for explicit cooked/percentage/lean mappings.

Nutrition was recalculated for 51 affected recipes:

`r007`, `r021`, `r026`, `r028`, `r030`, `r040`, `r048`, `r049`, `r050`,
`r057`, `r065`, `r073`, `r075`, `r076`, `r078`, `r084`, `r089`, `r097`,
`r108`, `r129`, `r130`, `r152`, `r154`, `r156`, `r157`, `r158`, `r160`,
`r161`, `r164`, `r165`, `r168`, `r171`, `r186`, `r198`, `r222`, `r224`,
`r229`, `r233`, `r235`, `r293`, `r297`, `r344`, `r360`, `r424`, `r425`,
`r496`, `r502`, `r503`, `r552`, `r642`, `r647`.

The original final-audit hard-outlier list now has `0` remaining hard flags in
`tmp/final-audit-recipe-blocker-fix/fix-summary.json`.

## Nutrition Before / After

Key blocker examples:

| Recipe | kcal | protein | fat | carbs |
| --- | ---: | ---: | ---: | ---: |
| `r057` before | 1485.15 | 35.37 | 121.92 | 150.90 |
| `r057` after | 603.15 | 12.65 | 28.10 | 80.70 |
| `r154` before | 2010.34 | 56.92 | 40.92 | 354.67 |
| `r154` after | 900.34 | 35.57 | 39.00 | 110.97 |
| `r186` before | 1216.05 | 46.66 | 16.19 | 225.59 |
| `r186` after | 735.18 | 25.62 | 13.60 | 132.03 |

Other original hard-outlier recipes normalized below the audit thresholds:
`r026`, `r075`, `r076`, `r108`, `r130`, `r152`, `r157`, `r158`, `r160`,
`r161`, `r164`, `r165`, `r168`, `r171`, `r198`, `r235`, `r424`, `r425`,
`r496`, `r502`, and `r552`.

Full before/after data is in
`tmp/final-audit-recipe-blocker-fix/fix-summary.json`.

## r678 Text

Before:

`Свёклу завернуть в фольгу, запечь 45-50 мин при 200°C. Остудить, очистить, нарезать дольками. Апельсин очистить сегментами. Выложить йогурт на блюдо. Сверху свёклу и апельсин. Посыпать фисташками и мятой. подде жки нкции печени.`

After:

`Свёклу завернуть в фольгу, запечь 45-50 мин при 200°C. Остудить, очистить, нарезать дольками. Апельсин очистить сегментами. Выложить йогурт на блюдо. Сверху свёклу и апельсин. Посыпать фисташками и мятой.`

## Verification

- RED reproduced:
  `pytest tests/test_curated_recipe_data.py::test_final_audit_recipe_blocker_profile_and_text_are_fixed -q`
  failed on `acai_puree -> Baking chocolate`.
- Focused regression after fix:
  `pytest tests/test_curated_recipe_data.py::test_final_audit_recipe_blocker_profile_and_text_are_fixed -q`
  passed.
- Requested pytest block:
  `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  passed: `250 passed in 99.58s`.
- Recipe content audit:
  `python scripts/dev/recipe_content_audit.py --no-write-report`
  passed with `blocking_findings=0`.
- PDF recovery smoke:
  `python scripts/dev/pdf_renderer_recovery_smoke.py`
  passed with `rendered_pdfs=8`, `recipes_checked=210`.
- `git diff --check` exited `0`; it printed existing LF-to-CRLF working-copy
  warnings only.

Selected-53 preservation:

- The requested pytest block includes the `r666` through `r710` selected-53
  rows/photos/food-resolution/fix invariants.
- This fix did not recalculate selected-53 nutrition rows; only `r678`
  instruction text was changed in that range.

## Not Done

- Did not fix unrelated final-audit high/medium/low findings.
- Did not change worker, runtime, payment, safety, or Telegram code.
- Did not run the bot, touch Telegram API/getUpdates, use production DB, make
  real payments/refunds, deploy, push, commit, tag, PR, or edit secrets/env
  files.
- Did not touch archive, `New project 2 CLEAN`, or recovered bot.

## Verdict

READY FOR RE-AUDIT for the scoped recipe blocker and `r678` text issue.
