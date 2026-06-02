# Stage 6 - Builder / Selection Fix

## Scope

Fixed the remaining builder/selection edge case after product recipe data transfer without deleting recipes/data and without weakening validation or avoidance behavior.

## Root Cause

The planner emitted flexible curated recipe keys with the selected meal slot, for example:

- `snack:curated:r601_tost_s_arahisovoy_pastoy_i_yablokom`

But the initial recipe prefilter compared `avoided_recipe_keys` using the recipe's native slot. For `r601_tost_s_arahisovoy_pastoy_i_yablokom`, the native recipe slot is `breakfast`, while product metadata allows the recipe in both `breakfast` and `snack`. That meant a previously emitted snack key could be missed by the prefilter and selected again.

A second deterministic variety failure came from the controlled selection window still preferring the same high-scoring snack candidate for multiple adjacent seeds. The selector had safe alternative candidates, but the window score could keep returning the top candidate.

## Changes

- Moved avoided recipe-key filtering from the global native-slot recipe prefilter into slot-aware ranking.
- `_rank_recipe_candidates` now skips a candidate when the key for the requested slot matches `avoided_recipe_keys`.
- `_rank_recipes` accepts `avoided_recipe_keys` for targeted tests and cache-safe ranking calls.
- Added bounded seed rotation inside the existing controlled recipe window:
  - only candidates passing existing energy/protein/sodium guards are considered;
  - only least-repeated candidates are rotated;
  - rotation is limited to candidates close to the best pressure score;
  - candidates outside that score window fall back to the prior safety-aware selection score.
- Added a regression test proving that a snack-slot avoided key blocks a flexible breakfast-native curated recipe while the breakfast key does not block the snack placement.

## Changed Files

- `src/diet_bot/builder.py`
- `tests/test_builder_recipe_cache.py`
- `docs/recovery-integration/builder-selection-fix.md`

## Tests Run

- RED reproduction before fix:
  - `pytest tests/test_safety_and_builder.py::test_five_repeat_generations_keep_key_meals_unique tests/test_safety_and_builder.py::test_repeat_generations_can_avoid_recent_recipe_families -q`
  - Result: `2 failed`.
- Targeted regression:
  - `pytest tests/test_builder_recipe_cache.py::test_rank_recipes_filters_avoided_recipe_keys_by_requested_slot -q`
  - Result: `1 passed`.
- Original Stage 6 failures after fix:
  - `pytest tests/test_safety_and_builder.py::test_five_repeat_generations_keep_key_meals_unique tests/test_safety_and_builder.py::test_repeat_generations_can_avoid_recent_recipe_families -q`
  - Result: `2 passed`.
- Broad builder/cache/data/trait suite:
  - `pytest tests/test_safety_and_builder.py tests/test_builder_recipe_cache.py tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q`
  - First pass found one carbohydrate-range regression in the hard-profile window rotation.
  - After tightening rotation, final result: `131 passed`.

## Stop Gates

- No recipes or product data were deleted.
- Safety/validation thresholds were not weakened.
- PDF/UI/payments logic was not changed in this stage.
- The temporary carb-range regression was fixed by tightening selection, not by relaxing validation.

## Open Risks

- Builder tests are slow because they exercise the full curated recipe pool.
- The new rotation remains intentionally conservative; future product data expansion should keep the Stage 6 tests in the safety suite.
