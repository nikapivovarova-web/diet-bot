# Recipe Import Smoke Notes

Date: 2026-05-14

## Commits Covered

- `53ef640` recipes: import cleaned intake recipes
- `57d3aec` recipe quality: prevent carryover weekly repeats

## Repository State

- Workspace: `C:\Users\adck8\Documents\New project 2 CLEAN`
- Branch at start: `codex/emergency-stabilization...origin/codex/emergency-stabilization [ahead 76]`
- Top log entries at start:
  - `57d3aec` recipe quality: prevent carryover weekly repeats
  - `53ef640` recipes: import cleaned intake recipes

## Focused Verification

### Post-Planner Stabilization Smoke - 2026-05-15

Scope: post-planner stabilization smoke/report slice after:

- `1a0e848` recipes: use slot flex metadata in builder
- `d668b73` recipes: soften cooking effort preference
- `9bc199c` recipes: make portion scaling practical
- `7fc52b7` recipes: prefer calorie-fit weekly candidates
- `559b5b7` recipes: recover calories with carb top ups
- `a77d7d9` recipes: avoid collapsed low-calorie meals

No code, recipe data, runtime state, validation bounds, or push was changed in this slice. The only intended repository change is this smoke note.

Probe: inline `.venv\Scripts\python.exe` smoke using existing `_build_week_plans`, `build_week_shopping_groups`, and `render_week_plan_pdf` helpers. Weekly profiles used male, age 32, height 178 cm, moderate activity, maintain goal, 5 meals.

Summary:

- All 9 planner smoke profiles generated complete weeks.
- Every generated week had `35/35` meals and `35` unique recipe IDs inside the week.
- Calorie lower-bound failures: none in the smoke matrix.
- Protein floor failures: none in the smoke matrix.
- Collapsed meals: none in the smoke matrix.
- Exclusion/allergy violations: none in the restrictive profiles.
- Downstream shopping totals matched generated `FoodPortion` totals after batch carryover handling for every generated week.
- One representative weekly PDF render completed with a forced empty `image_url`; output size was 1,900,925 bytes in a temporary directory.
- Existing validation errors/warnings remain, mostly sodium over 2300 mg/day and macro upper/lower bounds. They were recorded only and not fixed.

| Profile | Seed | Generation | Meals | Unique recipes | Calorie lower-bound failures | Protein floor failures | Collapsed meals | Weird quantities | Exclusion/allergy violations | Effort fallback |
| --- | ---: | --- | ---: | ---: | --- | --- | ---: | --- | --- | --- |
| 45kg simple | 101 | PASS | 35/35 | 35 | None | None | 0 | None | None | 7 relaxation logs; 0 selected non-simple recipes |
| 75kg simple | 101 | PASS | 35/35 | 35 | None | None | 0 | None | None | 0 logs; 0 selected non-simple recipes |
| 86kg simple | 101 | PASS | 35/35 | 35 | None | None | 0 | None | None | 0 logs; 0 selected non-simple recipes |
| 120kg simple | 101 | PASS | 35/35 | 35 | None | None | 0 | None | None | 0 logs; 0 selected non-simple recipes |
| 120kg interesting | 404 | PASS | 35/35 | 35 | None | None | 0 | None | None | n/a |
| Dairy-free simple | 101 | PASS | 35/35 | 35 | None | None | 0 | None | None | 0 logs; 0 selected non-simple recipes |
| Gluten/celiac simple | 202 | PASS | 35/35 | 35 | None | None | 0 | `corn_tortilla` 55 g in day 3 main `r211_govyadina_s_fasolyu_i_risom_na_skovorode` | None | 0 logs; 0 selected non-simple recipes |
| Egg allergy simple | 101 | PASS | 35/35 | 35 | None | None | 0 | None | None | 0 logs; 0 selected non-simple recipes |
| Fish+nuts excluded simple | 101 | PASS | 35/35 | 35 | None | None | 0 | None | None | 0 logs; 0 selected non-simple recipes |

Quantity heuristics checked in every generated week:

- Fractional whole eggs: none found.
- Strange bread/lavash/tortilla grams: 1 total `corn_tortilla` 55 g finding in the celiac run, listed above.
- Salt over 3 g per meal: none found.
- Lemon/lime over 35 g: none found.
- Oil/butter over 20 g: none found.
- Snack over 650 kcal: none found.

Observed energy and protein ranges:

| Profile | Energy range | Protein ratio range |
| --- | --- | --- |
| 45kg simple | 2110-2207 kcal | 1.587-1.890x target |
| 75kg simple | 2598-2672 kcal | 1.312-1.506x target |
| 86kg simple | 2753-2920 kcal | 1.352-1.614x target |
| 120kg simple | 3253-3418 kcal | 1.433-1.682x target |
| 120kg interesting | 3244-3374 kcal | 1.322-1.600x target |
| Dairy-free simple | 2727-2820 kcal | 1.289-1.542x target |
| Gluten/celiac simple | 2756-2812 kcal | 1.355-1.587x target |
| Egg allergy simple | 2771-2928 kcal | 1.455-1.583x target |
| Fish+nuts excluded simple | 2772-2845 kcal | 1.445-1.573x target |

Downstream quick smoke:

| Check | Result |
| --- | --- |
| Shopping totals vs final generated portions with batch carryover handling | PASS; `diff_count=0` for all 9 generated weeks |
| Representative PDF render | PASS; `120kg interesting`, seed 404, 1,900,925 bytes in temp output |
| Empty `image_url` handling | PASS; first meal image URL forced to empty string before the representative PDF render |

Validation warnings/errors recorded, not fixed:

| Profile | Sodium over target | Protein upper-bound errors | Other macro warnings/errors |
| --- | ---: | ---: | --- |
| 45kg simple | 5/7 days | 7/7 days | fat upper day 3; fat below day 1; carb below days 2-3 |
| 75kg simple | 4/7 days | 0/7 days | fat upper day 7; carb below day 7 |
| 86kg simple | 5/7 days | 4/7 days | carb below day 4 |
| 120kg simple | 7/7 days | 5/7 days | None |
| 120kg interesting | 6/7 days | 4/7 days | fat below days 2-3 |
| Dairy-free simple | 5/7 days | 1/7 day | fat below day 7 |
| Gluten/celiac simple | 1/7 day | 4/7 days | carb below day 7 |
| Egg allergy simple | 4/7 days | 4/7 days | fat below day 2 |
| Fish+nuts excluded simple | 7/7 days | 4/7 days | fat below days 1 and 7 |

Additional validation warnings observed: repeated-food warnings for salt, egg, onion, and vegetable oil in a few days. These were not treated as generation failures in this smoke.

Tests run:

| Check | Command | Result |
| --- | --- | --- |
| Recipe portion scaling | `python -m pytest tests/test_recipe_portion_scaling.py -q` | 7 passed |
| Recipe effort / slot coverage | `python -m pytest tests/test_recipe_effort_slot_coverage.py -q` | 20 passed |
| Curated recipe data | `python -m pytest tests/test_curated_recipe_data.py -q` | 27 passed |
| Weekly selector and optimizer candidates | `python -m pytest tests/test_weekly_selector_scoring.py tests/test_weekly_optimizer_candidates.py -q` | 10 passed |
| Targeted builder tests from previous slices | `python -m pytest` with 10 selected `tests/test_safety_and_builder.py` node IDs covering egg/broccoli exclusions, simple effort, weekly uniqueness, weekly completeness, seed 404 carryover, low-weight floor/collapse, and exclusion propagation | 10 passed |

Recommendation for next slice:

1. Tune sodium and macro upper-bound quality without relaxing validation bounds.
2. Investigate high protein ratios, especially 45kg simple where the ratio reached 1.890x target.
3. Fix the remaining carrier rounding edge that can leave `corn_tortilla` at 55 g.
4. Keep the restrictive-profile matrix as a regression smoke after any planner tuning.

### Post-Scaling Smoke - 2026-05-15

Scope: docs-only smoke/report slice after:

- `d668b73` recipes: soften cooking effort preference
- `9bc199c` recipes: make portion scaling practical

No code, recipe data, runtime state, or push was changed in this slice.

Probe: inline `.venv\Scripts\python.exe` smoke using existing `_build_week_plans`, `build_week_shopping_groups`, and `render_week_plan_pdf` helpers. Weekly profiles used male, age 32, height 178 cm, moderate activity, maintain goal, 5 meals.

| Profile | Seed | Generation | Meals | Unique recipes | Protein floor | Calories vs +/-8% bounds | Effort fallback | Weird quantities |
| --- | ---: | --- | ---: | ---: | --- | --- | --- | --- |
| 45kg simple | 101 | PASS | 35/35 | 35 | PASS; 1.480-1.501x target | FAIL low all 7 days; 1542-1865 kcal vs 2007-2356 bound | No | None |
| 75kg simple | 101 | PASS | 35/35 | 35 | PASS; 1.470-1.495x target | FAIL low days 1,2,6,7; 2230-2597 kcal vs 2435-2858 bound | No | None |
| 86kg simple | 101 | PASS | 35/35 | 35 | PASS; 1.277-1.490x target | FAIL low days 1,3; 2347-2931 kcal vs 2592-3042 bound | Yes; 3 relaxation logs, `r459_pisto` once | 1 strange carrier: `corn_tortilla` 55 g in `r572_tykvennoe_karri_s_kuritsey` |
| 120kg simple | 101 | PASS | 35/35 | 35 | PASS; 1.335-1.490x target | FAIL low days 2-6; 2852-3263 kcal vs 3077-3612 bound | Yes; 3 relaxation logs, `r459_pisto` once | None |
| 120kg interesting | 404 | PASS | 35/35 | 35 | PASS; 1.328-1.490x target | FAIL low days 4,7; 2932-3492 kcal vs 3077-3612 bound | n/a | None |
| 86kg simple, egg allergy + celiac | 202 | PASS | 35/35 | 35 | PASS; 1.291-1.484x target | FAIL low day 1; 2539-2817 kcal vs 2592-3042 bound | Yes; 2 relaxation logs, selected recipes still matched strict-simple heuristic | 1 strange carrier: `corn_tortilla` 55 g in `r558_krevetki_v_kokosovom_karri_s_risom` |

Quantity heuristics checked in every generated week:

- Fractional whole eggs: none found.
- Strange bread/lavash/tortilla grams: 2 total `corn_tortilla` 55 g findings, listed above.
- Salt over 3 g per meal: none found.
- Lemon/lime over 35 g: none found.
- Oil/butter over 20 g: none found.
- Snack over 650 kcal: none found.

Restrictive profile check:

- Egg allergy + celiac generated a complete week.
- No egg, egg part, gluten-tagged, or celiac-excluded food violations were found in final scaled portions.
- Dairy-free was not separately run because the existing fast celiac helper path covered the requested restrictive smoke shape.

Shopping/PDF quick smoke:

- Shopping totals matched final scaled `FoodPortion` totals for all 6 generated weeks after batch carryover handling; `diff_count=0` in each case.
- Representative PDF render for `120kg interesting`, seed 404, completed without crashing; output size in the temporary render was 2,054,426 bytes.

Known limitations / failures to fix later:

- Weekly generation completeness passed for every requested profile, but calorie lower-bound tolerance failed in every sample. All calorie failures were below the lower bound; no sampled day exceeded the upper calorie bound.
- Protein floor passed everywhere, but protein remains high in all samples: observed ratios were 1.277-1.501x target.
- Simple effort fallback is still used for 86kg/120kg simple and the restrictive simple run. In unrestricted 86kg/120kg simple weeks, `r459_pisto` surfaced as a non-simple recipe once.
- Carrier rounding still has at least one practical-portion edge: `corn_tortilla` can appear at 55 g as a garnish/carrier.
- This smoke did not fix any of the above by request; it only records the post-scaling behavior.

### Batch2 Ready Import - 2026-05-14

Imported the ready-only subset from `tmp/recipe_intake_batch2/cleaned_recipes_batch2.xlsx`.

| Check | Result |
| --- | --- |
| Curated recipe count before / after | 505 -> 610 |
| Imported batch2 recipes | 105 ready rows |
| Excluded rows | `batch2_008` excluded as `needs_review` / exact production duplicate |
| Imported ingredient rows | 680 |
| New canonical food rows | `coconut_milk`, `rice_flour`, `rice_noodles`, `herring`, `sardines` |
| Existing sprats mapping | Reused; `batch2_083`-`batch2_086` import as `sprats`, 70 g drained |
| Empty image handling | 105/105 batch2 rows keep empty `image_url`; 105/105 keep `photo_prompt_ru` |

Ready-only import integrity check:

| Gate | Result |
| --- | --- |
| `batch2_008` absent from production | PASS |
| No `needs_review` rows imported | PASS |
| `recipe_key` unique | PASS |
| `recipe_id` unique | PASS |
| No exact title duplicates with preexisting curated recipes | PASS |
| `servings_cleaned = 1` | 105/105 |
| `allowed_meal_slots`, `slot_flex_type`, `coverage_priority` match workbook | 105/105 |
| Ingredient mapping / nutrition readiness | 105 nutrition rows `ok`, 0 unmatched ingredients |

Targeted tests and smokes:

| Check | Command | Result |
| --- | --- | --- |
| Curated recipe data tests | `python -m pytest tests/test_curated_recipe_data.py -q` | 25 passed |
| Recipe effort / coverage tests | `python -m pytest tests/test_recipe_effort_slot_coverage.py -q` | 9 passed |
| Weekly optimizer candidate tests | `python -m pytest tests/test_weekly_optimizer_candidates.py -q` | 7 passed |
| Weekly / exclusion / builder targeted tests | `python -m pytest tests/test_safety_and_builder.py::test_weekly_recipe_plan_does_not_reuse_recipe_ids_across_days_or_slots tests/test_safety_and_builder.py::test_weekly_generation_with_enough_pool_has_no_repeated_recipe_id tests/test_safety_and_builder.py::test_weekly_generation_respects_food_exclusions_across_all_days tests/test_safety_and_builder.py::test_same_recipe_id_is_not_reused_across_week_slots_when_alternatives_exist tests/test_safety_and_builder.py::test_egg_allergy_excludes_recipes_with_egg_variants tests/test_safety_and_builder.py::test_broccoli_exclusion_excludes_broccoli_recipes -q` | 6 passed |
| Generation smoke, simple 5 meals | Custom `_build_week_plans` probe, seed 101 | 7 days x 5 meals; 35/35 unique recipe IDs; 16 meals with empty `image_url`; no crash |
| Generation smoke, gluten-free | Custom `_build_week_plans` probe with `ConditionCode.CELIAC`, seed 202 | 7 days x 5 meals; 35/35 unique recipe IDs; 0 gluten/oats violations; 20 meals with empty `image_url`; no crash |

The post-import `tmp/recipe_intake_batch2/validate_batch2.py` mapping dry-run now reports 0 unmapped rows. Its duplicate counters are no longer meaningful after production import because the workbook rows now self-match the production rows; the ready-only import integrity check above is the post-import duplicate gate.

| Check | Command | Result |
| --- | --- | --- |
| Curated recipe data tests | `.venv\Scripts\python.exe -m pytest tests\test_curated_recipe_data.py -q` | 23 passed |
| Recipe effort / coverage tests | `.venv\Scripts\python.exe -m pytest tests\test_recipe_effort_slot_coverage.py -q` | 9 passed |
| Weekly optimizer candidate tests | `.venv\Scripts\python.exe -m pytest tests\test_weekly_optimizer_candidates.py -q` | 7 passed |
| Weekly / exclusion / builder targeted tests | `.venv\Scripts\python.exe -m pytest tests\test_safety_and_builder.py::test_egg_allergy_excludes_recipes_with_egg_variants tests\test_safety_and_builder.py::test_broccoli_exclusion_excludes_broccoli_recipes tests\test_safety_and_builder.py::test_simple_cooking_preference_filters_curated_recipe_effort tests\test_safety_and_builder.py::test_weekly_recipe_plan_does_not_reuse_recipe_ids_across_days_or_slots tests\test_safety_and_builder.py::test_weekly_generation_with_enough_pool_has_no_repeated_recipe_id tests\test_safety_and_builder.py::test_weekly_generation_respects_food_exclusions_across_all_days tests\test_safety_and_builder.py::test_same_recipe_id_is_not_reused_across_week_slots_when_alternatives_exist -q` | 7 passed |
| Carryover regression seed 404 | `.venv\Scripts\python.exe -m pytest tests\test_safety_and_builder.py::test_interesting_weekly_seed_404_has_no_carryover_recipe_repeat -q` | 1 passed |
| PDF missing-photo / no-image smoke | `.venv\Scripts\python.exe -m pytest tests\test_pdf_renderer.py::test_week_pdf_ignores_missing_meal_photo tests\test_pdf_renderer.py::test_week_pdf_handles_long_recipe_card_without_layout_error -q` | 2 passed; pytest emitted an ignored Windows temp cleanup `PermissionError` after pass |
| Local sample weekly smoke | Custom local probe using `_build_week_plans`, `render_week_plan_pdf`, `format_meal_card`, `_send_meal_card`, and `format_week_shopping_list`; no Telegram user-client | 7 sample weeks checked, `hard_failures=[]` |

Note: the first local sample probe completed all sample builds plus PDF and Telegram formatting checks, then failed only while printing JSON to a Windows `cp1251` console because a recipe card contained an emoji. A follow-up run with `PYTHONIOENCODING=utf-8` produced the metrics below and exited 0.

## Sample Results

All sample weeks produced a full `7 x 5` plan and `35/35` unique recipe IDs inside the week. No duplicate recipe IDs were found within any week. No obvious weird recipe title/ingredient markers were detected by the smoke heuristics (`placeholder`, service labels, URLs, empty fields).

| Sample | Seed | Week shape | Unique IDs | Exclusions | Protein ratios by day | Imported recipes used | Missing `image_url` handling |
| --- | ---: | --- | ---: | --- | --- | ---: | --- |
| `MAINTAIN/simple/5`, no exclusions | 101 | 7 days x 5 meals | 35/35 | n/a | 1.329, 1.426, 1.277, 1.448, 1.505, 1.401, 1.418 | 12 unique / 12 placements | 12 meals without `image_url`; PDF ok; Telegram fake send routed all 12 as text |
| `MAINTAIN/simple/5`, egg allergy | 101 | 7 days x 5 meals | 35/35 | respected; 0 violations | 1.302, 1.425, 1.533, 1.440, 1.392, 1.255, 1.411 | 13 unique / 13 placements | 13 meals without `image_url`; PDF ok; Telegram fake send routed all 13 as text |
| `MAINTAIN/simple/5`, broccoli disliked | 101 | 7 days x 5 meals | 35/35 | respected; 0 violations | 1.329, 1.423, 1.392, 1.518, 1.254, 1.520, 1.378 | 13 unique / 13 placements | 13 meals without `image_url`; PDF ok; Telegram fake send routed all 13 as text |
| `MAINTAIN/interesting/5`, seed 404 | 404 | 7 days x 5 meals | 35/35 | n/a | 1.449, 1.270, 1.414, 1.324, 1.458, 1.320, 1.420 | 7 unique / 7 placements | 7 meals without `image_url`; PDF ok; Telegram fake send routed all 7 as text |
| Repeat same profile, simple | 102 | 7 days x 5 meals | 35/35 | n/a | 1.329, 1.426, 1.392, 1.305, 1.489, 1.454, 1.450 | 14 unique / 14 placements | 14 meals without `image_url`; PDF ok; Telegram fake send routed all 14 as text |
| Repeat same profile, simple | 103 | 7 days x 5 meals | 35/35 | n/a | 1.257, 1.421, 1.325, 1.453, 1.478, 1.438, 1.412 | 14 unique / 14 placements | 14 meals without `image_url`; PDF ok; Telegram fake send routed all 14 as text |
| Repeat same profile, simple | 104 | 7 days x 5 meals | 35/35 | n/a | 1.257, 1.421, 1.437, 1.396, 1.455, 1.305, 1.313 | 14 unique / 14 placements | 14 meals without `image_url`; PDF ok; Telegram fake send routed all 14 as text |

Protein ratio range observed across samples: `1.254x` to `1.533x` of the daily protein target. No sampled day missed the protein floor; some simple/exclusion days overshot the target materially.

## Repeat / Overlap Observations

Same-profile repeated weekly generations used seeds `101`, `102`, `103`, and `104`. Cross-week overlap was present, but no pair produced the exact same week.

| Week seeds | Shared recipe IDs | Exact same week |
| --- | ---: | --- |
| 101 vs 102 | 20/35 | no |
| 101 vs 103 | 23/35 | no |
| 101 vs 104 | 21/35 | no |
| 102 vs 103 | 23/35 | no |
| 102 vs 104 | 19/35 | no |
| 103 vs 104 | 24/35 | no |

This smoke should not fail solely on cross-week overlap. Persistent recipe history / recent avoidance across user generations remains planned future work.

## Remaining Risks

- Imported intake recipes intentionally have no generated photos yet. The smoke confirms no crash path for absent `image_url`, but the user-facing visual experience still depends on future photo generation.
- Protein is consistently above target in sampled weeks, with maximum day ratios up to `1.533x`. This is not a blocker for the import smoke, but portion adjustment should tune the upper side.
- Cross-week overlap is high for repeated generations of the same profile (`19-24` shared recipe IDs out of `35`). The exact-week repeat bug is not reproduced, but recipe history is still needed for product-level variety.
- Smoke coverage is focused on MAINTAIN, 5 meals, simple/interesting effort, egg and broccoli exclusions. Other restrictions and edge profiles still need broader regression coverage before a full release confidence call.

## Next Recommendations

1. Cooking effort fallback: define the product rule for what happens when the strict simple pool is too narrow after exclusions, and keep controlled empty-plan behavior rather than silent unsafe fallback.
2. Portion adjustment: add a tuning pass for protein overshoot so high-protein weeks stay closer to the target while preserving the floor.
3. Recipe history: persist recent recipe IDs / recipe keys per user and pass them into repeated weekly generations to reduce cross-week overlap.
4. Photo generation: generate or attach photos for the imported intake recipes, then re-run PDF/Telegram visual smoke with imported images present.
