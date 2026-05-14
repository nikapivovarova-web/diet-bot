# Recipe History Fallback Debug

Date: 2026-05-14

Scope: debug/audit only. No production code was changed, no photos were generated, and no push was performed.

## Context

This slice investigates why recent recipe history avoidance did not lower overlap in the real `MAINTAIN/simple/5` smoke recorded in `docs/RECIPE_HISTORY_SMOKE_NOTES.md`.

Inputs matched the smoke profile:

- male, 32, 178 cm, 86 kg
- `Goal.MAINTAIN`
- `ActivityLevel.MODERATE`
- `CookingTimePreference.SIMPLE`
- `meal_count = 5`
- seeds `101` for week 1 and `129` for week 2

The harness used direct local Python calls into the existing builder and Telegram weekly helpers. It did not write state files or modify application code.

## Root Cause

The recent-history data is present and is being applied. The failure is feasibility under the current hard-avoid weekly path.

For `MAINTAIN/simple/5`, week 2 with week 1 as hard recent history can build only the first three days. It fails at `day_index = 3` because all four production day candidates return incomplete days. The bottleneck is the second snack slot (`slot_index = 4`, `snack`), with a small secondary signal on the second main slot (`slot_index = 3`, `main`).

This is not a simple catalog-size shortage. The profile still has enough theoretical non-recent recipes per broad slot. The problem is the current greedy weekly construction:

- week 1 contributes 35 hard-avoided recipe IDs and 35 hard-avoided keys;
- selected days in week 2 add same-week hard avoids on top;
- recipe filtering happens before weekly feasibility search;
- `simple` cooking effort removes a large part of the curated pool;
- the weekly selector only samples four day candidates per day;
- `reduced_recent` is identical to `full_recent` for week 2, so production falls from `full_recent` directly to `no_recent`.

Once the hard recent path fails, `no_recent` succeeds and naturally reuses many week 1 recipes, so overlap remains high.

## Reproduction

| Run | Avoided IDs | Avoided keys | Phase result | Shape | Unique IDs | Week 1 overlap |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| Week 1, seed 101 | 0 | 0 | success | 7x5 | 35/35 | n/a |
| Week 2, seed 129, `full_recent` | 35 | 35 | fails at `day_index=3` | partial internal attempt | n/a | n/a |
| Week 2, seed 129, forced `reduced_recent` | 35 | 35 | fails at `day_index=3` | partial internal attempt | n/a | n/a |
| Week 2, seed 129, `no_recent` | 0 | 0 | success | 7x5 | 35/35 | 22/35 |

The production fallback wrapper therefore returns `avoidance_phase = no_recent` for this profile and seed pair. The resulting overlap is the same as the no-history baseline: `22/35`.

## Failure Diagnostics

Candidate counts below are production day-builder attempts up to the failure day. "Accepted" means the candidate was complete and eligible for selection under the active phase.

| Phase | Days built before failure | Failure `day_index` | Candidates generated | Accepted | Rejected | Top candidate reject reason |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `full_recent` | 3 | 3 | 16 | 9 | 7 | `incomplete_day` x7 |
| forced `reduced_recent` | 3 | 3 | 16 | 9 | 7 | `incomplete_day` x7 |

Day-level breakdown:

| Phase | Day index | Seed range | Accepted | Rejected | Result |
| --- | ---: | --- | ---: | ---: | --- |
| `full_recent` | 0 | 129-132 | 4 | 0 | selected a complete day |
| `full_recent` | 1 | 133-136 | 4 | 0 | selected a complete day |
| `full_recent` | 2 | 137-140 | 1 | 3 | selected the only complete day |
| `full_recent` | 3 | 141-144 | 0 | 4 | week build fails |
| forced `reduced_recent` | 0 | 129-132 | 4 | 0 | selected a complete day |
| forced `reduced_recent` | 1 | 133-136 | 4 | 0 | selected a complete day |
| forced `reduced_recent` | 2 | 137-140 | 1 | 3 | selected the only complete day |
| forced `reduced_recent` | 3 | 141-144 | 0 | 4 | week build fails |

Candidate reject reason summary:

| Reason requested | `full_recent` candidates | forced `reduced_recent` candidates | Notes |
| --- | ---: | ---: | --- |
| Avoided recent `recipe_id` / key | 0 | 0 | These recipes are filtered before a complete day candidate is returned. |
| Same-week repeat | 0 | 0 | Same-week IDs/keys are also filtered before candidate return in this run. |
| Protein floor | 0 | 0 | The failing returned candidates are incomplete, not complete low-protein days. |
| Incomplete day | 7 | 7 | Direct candidate-level failure. |
| Exclusions | 0 | 0 | This profile has no food exclusions. |
| Effort/simple filter | 0 | 0 | Effort acts as a recipe-pool filter, not a candidate reject reason. |
| Carryover conflict | 0 | 0 | No batch carryover conflict was observed. |

Recipe-filter diagnostics across the same full/reduced attempts show where pressure enters the pool before candidates are returned:

| Filter reason | Count |
| --- | ---: |
| `effort_simple_filter` | 5,664 |
| `time_bucket` | 2,560 |
| `avoided_recent_recipe_id` | 1,120 |
| `same_week_repeat` | 240 |
| `avoided_recent_recipe_key` | 0 |
| `exclusions` | 0 |

These filter counts are diagnostic observations across candidate/time-attempt inspections, not distinct catalog rows. They are useful for ranking pressure points: the hard recent IDs and same-week IDs do remove candidates, but the visible production failure is incomplete day generation.

## Slot Bottlenecks

Slot-miss diagnostics from the full/reduced failure attempts:

| Slot index | Slot | Miss count | Interpretation |
| ---: | --- | ---: | --- |
| 4 | `snack` | 30 | Main bottleneck. This is the second snack in a 5-meal day. |
| 3 | `main` | 2 | Secondary bottleneck. |
| 0 | `breakfast` | 0 | No observed bottleneck. |
| 1 | `main` | 0 | No observed bottleneck for first main. |
| 2 | `snack` | 0 | No observed bottleneck for first snack. |

The failure day itself is clean: at `day_index=3`, seeds `141`, `142`, `143`, and `144` all return incomplete days, with the second snack slot missing in the low-level trace.

## Recent Pool By Slot

Theoretical slot pool after the profile's normal hard filters, using curated recipes that resolve against the food catalog and pass `simple` effort constraints:

| Slot | Recent served in week 1 | Eligible total | Available non-recent | Needed for 7x5 |
| --- | ---: | ---: | ---: | ---: |
| `breakfast` | 7 | 62 | 55 | 7 |
| `main` | 14 | 101 | 82 | 14 |
| `snack` | 14 | 131 | 117 | 14 |

So the broad slot pool is theoretically large enough. The real failure comes from the interaction of hard recent IDs, same-week IDs, `simple` effort, macro/protein gates, deterministic ranking, and only four candidates per day.

## Reduced Recent Check

For week 2, structured history produces:

| Field | Value |
| --- | ---: |
| `full_recipe_ids` | 35 |
| `full_recipe_keys` | 35 |
| `reduced_recipe_ids` | 35 |
| `reduced_recipe_keys` | 35 |
| `RECENT_RECIPE_REDUCED_DAYS` | 14 |
| `RECENT_RECIPE_REDUCED_LIMIT` | 70 |
| `RECENT_RECIPE_HISTORY_LIMIT` | 140 |
| Reduced equals full | yes |

The reduced set is not random. `_recent_recipe_avoidance_from_history` sorts history by `generated_at` descending, then keeps items inside the 14-day reduced window up to the limit. That means it keeps the freshest entries, not the least recent entries.

For the week 2 scenario, all 35 week 1 recipes are seven days old, so reduced is exactly as strict as full. Because `_weekly_recent_avoidance_phases` skips `reduced_recent` when `reduced == full`, production tries `full_recent` and then jumps directly to `no_recent`.

## Why Focused Tests Passed

The focused tests that produced `0/35` overlap do not cover this exact smoke profile.

Key difference:

- `tests/test_safety_and_builder.py::profile_with` defaults to `Goal.LOSE`.
- The recent-history tests override `cooking_time=SIMPLE` and `meal_count=5`, but not the goal.
- The real smoke uses `Goal.MAINTAIN`.

The lower-energy `LOSE/simple/5` profile is feasible under full hard recent avoidance for the sampled seeds. The higher-energy `MAINTAIN/simple/5` profile selects a different combination of recipes and becomes infeasible on day 4 under the same hard recent constraints.

The tests also use a helper where reduced and full recent sets are identical, and the main assertion checks the feasible path. They prove the mechanism can work when the profile is feasible; they do not prove the real `MAINTAIN/simple/5` smoke will avoid recent recipes.

## Recommendations

1. Add a soft recent penalty phase before `no_recent`.
   Keep allergies, exclusions, same-week repeats, protein floor, and complete-week requirements hard. When hard recent fails, allow recent recipes with a freshness penalty instead of removing all history pressure.

2. Use a shorter hard window.
   Consider making only the last completed weekly generation, or the last 7 days, hard. Older entries inside the month should become soft penalties.

3. Make recent avoidance slot-aware.
   Start with hard avoidance for the same effective meal slot, then cross-slot avoidance as a soft penalty. This is especially important for snack recipes that can also fill main slots.

4. Prefer least-recent repeats.
   The current reduced set keeps the freshest entries. Fallback should do the opposite: when repeats are unavoidable, prefer the oldest eligible recipe, not the newest one.

5. Add a controlled cooking-effort fallback.
   Before dropping to `no_recent`, try a bounded relaxation of `simple` effort, such as slightly higher active minutes or ingredient count, while still avoiding clearly complex techniques.

6. Add recipes only after optimizer changes if still needed.
   If hard/soft fallback still shows snack pressure, add more simple, high-protein second-snack recipes and main-like snack recipes. The current pool is broad enough on paper, so additions should be targeted by slot and feasibility traces rather than added blindly.
