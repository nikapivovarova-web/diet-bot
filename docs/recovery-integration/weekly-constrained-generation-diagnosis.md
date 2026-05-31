# Weekly Constrained Generation Diagnosis

## Scope And Entry Points

Diagnosis only. Production code, recipe data, payments, refunds, reconciliation, PDF layout, Telegram UX, bot runtime, deploy, git commit/tag/push/PR, secrets/env files, archive, `New project 2 CLEAN`, and recovered-bot files were not changed.

Reference audit blocker B-AUDIT-2 reported `no_dairy + no_meat + no_fish`, seed `607`, via `_build_week_plans_with_recent_fallback(profile, 607, empty_recent_avoidance)`, taking `58.448s` and returning zero days. This local run used the current integration worktree, where the pre-existing B-AUDIT-1 fish fix already broadens `fish` to exclude sardines and seafood-like IDs. That makes the same constrained profile stricter than the external audit snapshot: it still fails, but now in `27.090s`.

Weekly generation path:

- Weekly Telegram/PDF request: `src/diet_bot/telegram_app.py::_send_week_plan`.
- Selection entry point: `_build_week_plans_with_recent_fallback(profile, seed, recent_avoidance)`.
- Weekly selector: `_build_week_plans` -> `_select_week_day_plan`.
- Daily candidate builder: `build_one_day_plan(..., recipe_source="curated_only", allow_avoided_recipe_relaxation=False)`.
- Recipe/time/constraint filtering: `evaluate_safety`, `filter_foods`, `_build_recipe_plan_for_time`, `_build_recipe_plan`, `_rank_recipe_candidates`.
- PDF render path after successful selection: `_build_week_pdf_payload` -> `build_week_plan_pdf`. The failing cases do not reach PDF rendering.

Probe artifacts:

- Script: `tmp/weekly-constrained-diagnosis/weekly_constrained_probe.py`
- JSON results: `tmp/weekly-constrained-diagnosis/weekly_constrained_probe_results.json`

All cases below use female/loss/simple, 4 meals/day, seed `607`, empty recent avoidance. "Eligible recipes" means curated recipes surviving safety food filters, excluded-title checks, and resolvable ingredient checks before weekly avoidance.

## Repro Cases

| case id | profile/filters | eligible recipes count | generated yes/no | elapsed seconds | repeated recipe count | failure reason |
|---|---:|---:|---:|---:|---:|---|
| C00_baseline_simple | no exclusions | 665 | yes | 3.194 | 0 | - |
| C01_audit_no_dairy_meat_fish | dairy + meat + fish excluded | 130 | no | 27.090 | 0 | Failed on day 1 after 8 candidates; 0 complete. Strict-simple main pool is 13 recipes, below 14 weekly main slots. |
| C02_no_fish | fish excluded | 548 | yes | 16.600 | 0 | - |
| C03_no_dairy | dairy excluded | 285 | yes | 11.393 | 0 | - |
| C04_no_meat | meat excluded | 460 | yes | 24.503 | 0 | - |
| C05_vegetarian_like_no_meat_fish | meat + fish excluded | 353 | no | 60.026 | 0 | Hit `no_recent` 60s phase timeout on day 3, candidate 2, before unfiltered time attempt. |
| C06_no_dairy_meat | dairy + meat excluded | 191 | yes | 23.254 | 0 | - |
| C07_no_dairy_fish | dairy + fish excluded | 217 | yes | 19.615 | 0 | - |
| C08_vegan_like_no_dairy_meat_fish_egg | dairy + meat + fish + egg excluded | 105 | no | 45.479 | 0 | Failed on day 1 after 8 candidates; 0 complete. Strict-simple main pool is 9 recipes, below 14 weekly main slots. |

Vegetarian/vegan note: `RestrictionType.DIETARY_PATTERN` exists in the domain model, but no active vegetarian/vegan safety/generator handling was found. C05/C08 are explicit-exclusion approximations, not native dietary-pattern tests.

Variety and constraint checks:

- Generated cases C00, C02, C03, C04, C06, and C07 all returned 7 days x 4 meals.
- Generated cases had per-day unique recipe IDs `4/4` for every day.
- Repeated recipe IDs were `0` in every generated case.
- Repeated dish names were `0` except C04, which had `1` repeated dish name across distinct recipe IDs.
- Constraint checks found no excluded-food violations in generated plans.

Key selector timings:

| case id | top bottleneck |
|---|---|
| C01 | `build_one_day_plan=27.088s/8`, `recipe_selection_total=20.202s/8`, `recipe_plan_build=14.820s/64`, `food_filter=6.868s/8` |
| C05 | `build_one_day_plan=60.018s/11`, `recipe_selection_total=52.702s/16`, `recipe_plan_build=40.322s/104`, `food_filter=7.294s/11` |
| C08 | `build_one_day_plan=45.477s/8`, `recipe_selection_total=37.783s/8`, `recipe_plan_build=19.696s/64`, `food_filter=7.678s/8` |

Additional independent one-day probe for failed profiles:

- C01 with no weekly avoidance: `0/7` day seeds produced a complete curated-only day; total `26.946s`.
- C05 with no weekly avoidance: `4/7` day seeds produced a complete curated-only day; total `30.998s`. Weekly no-repeat/diversity pressure then collapses by day 3.
- C08 with no weekly avoidance: `0/7` day seeds produced a complete curated-only day; total `46.328s`.

## Root Cause

Primary root cause is constrained-pool infeasibility plus expensive retry behavior before the product gets a clear unsupported result.

- Too few eligible recipes: yes for C01 and C08. The stricter current fish exclusion plus no dairy/no meat leaves only 13 strict-simple main recipes for C01 and 9 for C08, while a 4-meal week needs 14 main slots.
- Search algorithm retries too long: yes. Failed day-1 profiles still try 8 weekly candidates and 64 inner recipe-plan builds before returning no plan. C05 reaches the 60s `no_recent` phase timeout after partial weekly progress.
- Constraints impossible: yes for C01/C08 under current curated-only, simple, explicit exclusion constraints.
- Nutrition target too strict/category coverage issue: likely yes. Removing dairy/meat/fish leaves weak simple protein coverage; hard protein floors reject many otherwise structurally possible meals.
- No timeout/fallback: partial. There is a 60s phase timeout and 90s total timeout, but no fast no-recent infeasibility gate and no graceful fallback/unsupported result before the user waits tens of seconds.
- Bug in filters: not shown for generated weekly cases. Generated cases respected exclusions. The current tree already includes the B-AUDIT-1 fish taxonomy broadening, which makes B-AUDIT-2 stricter than the external audit snapshot.
- PDF renderer: not root cause. Failed cases never reach `_build_week_pdf_payload` / `build_week_plan_pdf`.

## Recommended Fix Options

| option | risk | expected implementation size | tests needed |
|---|---|---:|---|
| A. Add fast infeasibility precheck with clear user message | Low to medium. Main risk is false negatives for narrow-but-generatable profiles if thresholds are too conservative. | Small to medium | Unit tests for slot coverage counts; weekly matrix for no dairy/no meat/no fish/vegan-like; Telegram/worker admission test that unsupported constraints fail fast and do not consume paid value. |
| B. Add timeout/budget and graceful fallback | Medium. Too-low budgets can reject valid but slow cases such as no meat or no dairy+meat. | Medium | Low-budget selector test; worker/local request test for graceful result; no paid value consumed/refunded deterministically. |
| C. Relax constraints in ordered way with user-visible explanation | Medium to high. Dietary exclusions must never be relaxed; only diversity/recent/simple effort can be relaxed safely. | Medium to large | Tests proving exclusions remain hard; tests for ordered relaxation labels; weekly matrix latency and repetition assertions. |
| D. Improve weekly selector candidate pool/scoring | Medium. Could change weekly variety/nutrition behavior. | Medium | Selector scoring tests, constrained matrix, nutrition gate tests, repetition tests. |
| E. Add recipe coverage for weak categories later | Low algorithm risk but larger content/data risk. | Large | Recipe audit, trait coverage checks, constrained generation matrix, manual recipe review. |

## Recommended Minimal Launch Fix

Pick option A first: add a fast no-recent infeasibility precheck that blocks clearly unsupported constrained weekly profiles before expensive selection and returns a user-visible "cannot build a full week under these constraints" result without consuming paid weekly value.

The precheck should include at least:

- hard slot coverage: each repeated weekly slot must have at least the required number of strict-simple eligible recipes after safety/title/ingredient filters;
- constrained-main risk gate tuned from the matrix so C01/C05/C08 fail fast while C06/C07 still run;
- diagnostics in tests/results showing eligible base pool, strict-simple slot counts, and reason code.

Option B should follow as defense-in-depth, but A is the least invasive launch blocker fix because it avoids changing recipe data, PDF rendering, Telegram UX layout, or the selector's nutrition/scoring behavior.
