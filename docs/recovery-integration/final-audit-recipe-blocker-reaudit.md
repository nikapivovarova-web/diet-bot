# Final Audit Recipe Blocker Re-Audit

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Verdict

READY FOR NEXT HIGH FIXES.

This is not a production-launch verdict. It means the scoped final-audit recipe
blocker follow-up is no longer blocking the next high-priority fixes.

## Scope

Re-audited only:

- `BLOCKER-1`: legacy production recipe/food nutrition outliers.
- `HIGH-1`: `r678` broken user-facing text tail.
- The 51 recipe nutrition rows recalculated by
  `final-audit-recipe-blocker-fix.md`.
- The six requested food profiles:
  `acai_puree`, `cheddar`, `cooked_rice`, `cream_10_percent`,
  `cream_20_percent`, and `lean_beef_ground`.

Forbidden areas remained untouched: production data edits, code/config/env,
secrets, bot launch, Telegram API/getUpdates, production DB, payments/refunds,
deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, recovered bot,
and unrelated worker/payment/DevOps fixes.

## Provenance

- `git status --short` was captured first. The checkout was already dirty with
  tracked recovery/payment/recipe/test changes plus untracked recovery docs,
  selected-53 photos, and staging files before this re-audit.
- This re-audit added only:
  - `docs/recovery-integration/final-audit-recipe-blocker-reaudit.md`
  - `tmp/final-audit-recipe-blocker-reaudit/recipe-blocker-reaudit-summary.json`
  - this status update in `docs/recovery-integration/recovery-status.md`
- `pdf_renderer_recovery_smoke.py` also refreshed its standard ignored output
  under `tmp/pdf-renderer-recovery-smoke`.

## Recipe/Data Re-Audit

Evidence artifact:
`tmp/final-audit-recipe-blocker-reaudit/recipe-blocker-reaudit-summary.json`

The local re-audit scan checked:

- `foods=366`
- `recipes=710`
- `ingredients=6478`
- `nutrition_rows=710`
- `affected_51_found=51/51`
- `original_hard_recipes_checked=24`

Hard-scan thresholds used for this re-audit:

- `energy_kcal > 1200`
- `protein_g > 120`
- `fat_g > 100`
- `carbohydrate_g > 180`
- `ingredient grams > 650`

Results:

- Original final-audit hard recipe list: `0` remaining hard flags.
- 51 recalculated nutrition rows: `0` saved-vs-current-food recalculation
  mismatches.
- 51 recalculated nutrition rows: `0` hard kcal/protein/fat/carbs/grams flags.
- All-production hard scan with the same thresholds: `0` hard flags.
- Missing food references in the 51 affected rows: `0`.

Key blocker examples remain normalized:

| Recipe | kcal | protein | fat | carbs |
| --- | ---: | ---: | ---: | ---: |
| `r057` | 603.15 | 12.65 | 28.10 | 80.70 |
| `r154` | 900.34 | 35.57 | 39.00 | 110.97 |
| `r186` | 735.18 | 25.62 | 13.60 | 132.03 |

Maxima inside the 51 recalculated rows:

| Metric | Max | Recipe |
| --- | ---: | --- |
| kcal | 998.89 | `r496_karbonara_s_bekonom_i_slivkami` |
| protein | 54.99 | `r496_karbonara_s_bekonom_i_slivkami` |
| fat | 72.82 | `r108_kuritsa_s_kolbaskami_i_bryusselskoy_kapustoy_na_odnoy_` |
| carbs | 132.03 | `r186_boul_s_batatom_fasolyu_i_risom` |
| ingredient grams | 600.00 | `r235_kobb_salat_s_kuritsey_bekonom_avokado_i_yaytsami` |

## Food Profiles

All requested profiles passed existence, source-description, forbidden-term,
and nutrient-range checks.

| Food | Source/profile status | kcal | protein | fat | carbs |
| --- | --- | ---: | ---: | ---: | ---: |
| `acai_puree` | acai puree; no baking chocolate/chocolate terms | 80.0 | 2.0 | 6.0 | 5.0 |
| `cheddar` | cheddar cheese; no pretzel term | 403.0 | 22.87 | 33.31 | 3.37 |
| `cooked_rice` | cooked white rice | 130.0 | 2.72 | 0.28 | 28.17 |
| `cream_10_percent` | half-and-half/light 10 percent profile | 123.0 | 3.13 | 10.39 | 4.73 |
| `cream_20_percent` | light/table cream 20 percent profile | 195.0 | 3.0 | 19.1 | 3.7 |
| `lean_beef_ground` | 85 percent lean / 15 percent fat beef | 215.0 | 18.59 | 15.0 | 0.0 |

## r678

`r678_svekla_s_yogurtom_fistashkami_i_apelsinom` passed the focused text
check:

- broken tail `подде жки нкции печени`: absent;
- mojibake fragments `РїРѕРґРґРµ` and `РЅРєС†РёРё`: absent;
- instruction text is not truncated by the removed tail check and ends with a
  normal sentence terminator.

## Required Commands

- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `250 passed in 101.72s`
- `python scripts/dev/recipe_content_audit.py --no-write-report`
  - `recipes_checked=710`
  - `ingredients_checked=6478`
  - `foods_checked=366`
  - `nutrition_rows_checked=710`
  - `blocking_findings=0`
  - `warning_findings=1322`
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
  - output: `tmp/pdf-renderer-recovery-smoke`
- `git diff --check`
  - exit code `0`
  - output contained only existing LF-to-CRLF working-copy warnings.

## Findings Status

Closed by the recipe blocker fix and confirmed by this re-audit:

- `BLOCKER-1`: Legacy Production Recipe/Food Nutrition Outliers.
- `HIGH-1`: `r678` Contains User-Facing OCR Garbage.

No new recipe/data blockers were found.

Remaining final pre-release audit findings:

| Severity | Before | Closed | Remaining |
| --- | ---: | ---: | ---: |
| blocker | 1 | 1 | 0 |
| high | 7 | 1 | 6 |
| medium | 4 | 0 | 4 |
| low | 6 | 0 | 6 |

Remaining high findings are unchanged and out of this scope:

- `HIGH-2`: admin discount list storage-error handling.
- `HIGH-3`: no production ingress for provider reversal events.
- `HIGH-4`: worker jobs have no hard per-job deadline.
- `HIGH-5`: worker task death is logged while polling continues.
- `HIGH-6`: release evidence still contains stale reversal text.
- `HIGH-7`: timed unpaid funnel is design-only if in launch scope.

## Not Done

- Did not edit production data or code.
- Did not fix worker/payment/DevOps findings.
- Did not run the bot or touch Telegram API/getUpdates.
- Did not use production DB, real secrets, payment provider, refunds,
  cancellations, reversals, or chargebacks.
- Did not deploy, push, commit, tag, open PR, or touch archive,
  `New project 2 CLEAN`, or recovered bot.

## Next Recommended Prompt

Fix only the next final pre-release audit high finding in FoodBalance:
`docs/recovery-integration/final-pre-release-audit.md` `HIGH-2` admin discount
list storage-error handling.

Scope:

- Work only in `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`.
- Fix only the admin promo list fail-closed behavior described in `HIGH-2`.
- Add focused coverage proving the unavailable promo store returns the admin
  storage error and does not raise.
- Do not touch recipe/data, worker liveness, payment reversal ingress, DevOps,
  Telegram API/getUpdates, production DB, real payments/refunds, deploy, push,
  commit, tag, PR, archive, `New project 2 CLEAN`, or recovered bot.
