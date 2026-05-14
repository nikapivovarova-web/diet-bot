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
