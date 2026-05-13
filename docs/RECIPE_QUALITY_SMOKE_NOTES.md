# Recipe Quality Smoke Notes

Date: 2026-05-13

Scope: focused local smoke/check slice after `fdb61bd recipe quality: generalize food exclusion matching`. No runtime code changes, cleanup, refactor, push, real YooKassa payment, or real Telegram Stars payment were performed.

## Commits Covered

- `fdb61bd` `recipe quality: generalize food exclusion matching`
- Relevant immediate predecessor: `b53bf1f` `recipe quality: enforce exclusions and macro bounds`

## Git Context

- Workspace: `C:\Users\adck8\Documents\New project 2 CLEAN`
- Branch at start: `codex/emergency-stabilization...origin/codex/emergency-stabilization [ahead 53]`
- Recent log head: `fdb61bd`, `b53bf1f`, `c8090b3`, `e339b35`, `cd5148c`, `6ffbec4`, `b410e04`, `484418f`
- Pre-docs smoke working tree: clean.

## Bot Process

- Found one existing `python.exe -B -m diet_bot.telegram_app` process, PID `6528`.
- PID `6528` started at `2026-05-13 21:14:57`; covered commit `fdb61bd` was created at `2026-05-13 23:17:07 +0400`, so the process was older than the checked code.
- Stopped only PID `6528`.
- First clean restart attempt exited immediately because this shell did not have `DIET_BOT_DATABASE_URL` or `DIET_BOT_ALLOW_JSON_STORAGE=1`.
- Restarted one clean instance from the current workspace with `PYTHONPATH=src` and `DIET_BOT_ALLOW_JSON_STORAGE=1`; final bot process PID `2216`, started at `2026-05-13 23:34:17`.

## Test Commands

Git checks:

```powershell
git status --short --branch
git log --oneline -8
```

Targeted food exclusion tests:

```powershell
pytest -q tests\test_safety_and_builder.py -k "food_exclusion or egg_allergy or broccoli_exclusion or excluded_mushrooms or recipe_title_exclusions or apple_allergy or weekly_generation_respects_food_exclusions"
```

Result: `41 passed, 38 deselected in 22.05s`.

Full safety/builder attempt:

```powershell
pytest -q tests\test_safety_and_builder.py
```

Result: timed out after `244s`; switched to focused subsets.

Grouped repeat/weekly attempt:

```powershell
pytest -q tests\test_safety_and_builder.py -k "repeat or weekly or avoid_recent or same_recipe_id"
```

Result: timed out after `304s`; switched to exact repeat/weekly targets.

Related restriction tests:

```powershell
pytest -q tests\test_safety_and_builder.py -k "celiac or lactose or cooking_effort or simple_cooking"
```

Result: `6 passed, 73 deselected in 35.54s`.

Related macro/protein tests:

```powershell
pytest -q tests\test_safety_and_builder.py -k "protein_top_up or protein_floor or protein_scoring or recipe_ranking or overshoot or macro or high_bmi or curated_only or hard_floor"
```

Result: `11 passed, 68 deselected in 36.79s`.

Exact repeat/weekly tests:

```powershell
pytest -q tests\test_safety_and_builder.py::test_weekly_generation_with_enough_pool_has_no_repeated_recipe_id
pytest -q tests\test_safety_and_builder.py::test_same_recipe_id_is_not_reused_across_week_slots_when_alternatives_exist
pytest -q tests\test_safety_and_builder.py::test_repeat_generations_can_avoid_recent_recipe_ids
```

Results:

- `test_weekly_generation_with_enough_pool_has_no_repeated_recipe_id`: `1 passed in 22.40s`
- `test_same_recipe_id_is_not_reused_across_week_slots_when_alternatives_exist`: `1 passed in 18.62s`
- `test_repeat_generations_can_avoid_recent_recipe_ids`: `1 passed in 149.85s`

Not run by request:

- PDF tests.
- Promo/payment tests.

## Sample Scenarios

Samples were generated locally through direct Python calls to `build_one_day_plan` and `_build_week_plans`; no Telegram real user-client was used.

### Egg Allergy Daily Ration

- Profile: male, age `32`, `178cm`, `86kg`, goal `LOSE`, `MODERATE`, `5` meals, `SIMPLE`, `RestrictionType.ALLERGY` = `яйца`.
- Command shape: `PYTHONPATH=src`, inline Python, `build_one_day_plan(..., variety_seed=11, recipe_source="curated_only")`.
- Result: `5` meals.
- Recipe IDs:
  - `r058_tropicheskaya_yogurtovaya_chasha_s_greypfrutom_i_manda`
  - `r204_boul_s_lososem_brokkoli_i_bulgurom`
  - `r288_tost_s_indeykoy_tvorozhnym_syrom_i_inzhirom`
  - `r211_govyadina_s_fasolyu_i_risom_na_skovorode`
  - `r257_grecheskiy_yogurt_s_ovsyankoy_i_arahisovoy_pastoy`
- Structural check: no `egg` / `яйца` terms in ration recipe titles or ingredients.
- Protein: `140.2g` vs target `138.0g`, ratio `1.016`.
- Pass/fail: PASS.

### Broccoli Disliked Daily Ration

- Profile: male, age `32`, `178cm`, `86kg`, goal `LOSE`, `MODERATE`, `5` meals, `SIMPLE`, `RestrictionType.EXCLUDED_FOOD` = `disliked broccoli`.
- Command shape: `PYTHONPATH=src`, inline Python, `build_one_day_plan(..., variety_seed=12, recipe_source="curated_only")`.
- Result: `5` meals.
- Recipe IDs:
  - `r041_beygl_klab_s_lososem_yaytsom_i_krem_syrom`
  - `r217_tayskiy_zelenyy_karri_sup_s_udonom_i_krevetkami`
  - `r346_mango_yogurtovyy_boul_s_tvorogom`
  - `r250_roll_s_kuritsey_yaytsom_i_myatnym_yogurtom`
  - `r328_tost_s_rikottoy_persikom_fistashkami_i_medom`
- Structural check: no `broccoli` / `брокколи` terms in ration recipe titles or ingredients.
- Protein: `147.3g` vs target `138.0g`, ratio `1.067`.
- Pass/fail: PASS.

### Weekly No Extra Exclusions

- Profile: male, age `32`, `178cm`, `86kg`, goal `LOSE`, `MODERATE`, `5` meals, `SIMPLE`, no restrictions.
- Command shape: `PYTHONPATH=src`, inline Python, `_build_week_plans(profile, 101, set(), set())`.
- Result: `7` days, `35` meals, `35` recipe IDs.
- Unique recipe IDs: `35/35`.
- Repeated recipe IDs: none.
- Protein ratios by day:
  - Day 1: `155.2g / 138.0g = 1.124`
  - Day 2: `139.4g / 138.0g = 1.010`
  - Day 3: `153.1g / 138.0g = 1.109`
  - Day 4: `162.4g / 138.0g = 1.177`
  - Day 5: `138.3g / 138.0g = 1.002`
  - Day 6: `170.0g / 138.0g = 1.232`
  - Day 7: `131.1g / 138.0g = 0.950`
- Max protein ratio: `1.232`, below `1.500`.
- Pass/fail: PASS.

## Overall Result

PASS for the targeted `fdb61bd` smoke slice:

- Egg exclusion sample and pytest coverage did not surface egg/egg-variant leakage.
- Broccoli exclusion sample and pytest coverage did not surface broccoli leakage.
- Weekly no-extra-exclusions smoke produced no repeated `recipe_id` when alternatives were available.
- Protein stayed below `150%` in the weekly smoke and related macro/protein tests passed.

## Known Limitations

- Full `tests/test_safety_and_builder.py` did not complete in `244s`; focused subsets were used instead.
- Grouped repeat/weekly pytest selection did not complete in `304s`; exact repeat/weekly tests passed individually.
- A side exploratory `MAINTAIN` weekly profile without extra exclusions showed empty days:
  - `meal_count=4`: meals by day `[4, 4, 4, 4, 4, 0, 4]`, total `24/28`.
  - `meal_count=5`: meals by day `[5, 5, 5, 5, 0, 0, 0]`, total `20/35`.
  - No repeated recipe IDs were present and max non-empty protein ratios stayed below `150%`, but the empty days should be followed up if maintenance weekly PDFs are in scope.
- No PDF tests were run.
- No promo/payment tests were run.
- No real Telegram user-client checks were performed.
- No real YooKassa or Telegram Stars payments were performed.
