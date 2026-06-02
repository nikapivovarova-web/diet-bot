# B-AUDIT-2 Weekly Fallback Checkpoint

## Stop Status

- Work stopped on request.
- No local long-running pytest/probe command is currently active in this Codex turn.
- No changes were reverted.
- No bot/deploy/push/commit/tag/PR work was done.
- No recipe JSON/data, secrets/env files, payment/refund/reconciliation code, or PDF layout files were intentionally changed for this B-AUDIT-2 attempt.

## Changed Files

B-AUDIT-2 files changed in this attempt:

- `src/diet_bot/telegram_app.py`
- `tests/test_safety_and_builder.py`
- `tests/test_weekly_pdf_postgres_wiring.py`
- `docs/recovery-integration/b-audit-2-weekly-fallback-checkpoint.md`

Pre-existing dirty/untracked items were present before this attempt, including:

- `src/diet_bot/safety.py`
- `docs/recovery-integration/final-audit-fixes.md`
- `docs/recovery-integration/weekly-constrained-generation-diagnosis.md`
- `docs/recovery-integration/recovery-status.md`
- additional recovery/staging artifacts shown by `git status --short`

Latest quick diff stat for tracked B-AUDIT-2 touched files before this checkpoint:

- `src/diet_bot/telegram_app.py`: large partial implementation, about 933 added lines in the current diff stat.
- `tests/test_safety_and_builder.py`: new weekly constrained tests, about 215 added lines.
- `tests/test_weekly_pdf_postgres_wiring.py`: one JSON entitlement refund regression test, about 35 added lines.
- `docs/recovery-integration/recovery-status.md`: already dirty before this checkpoint and included in the tracked diff stat.

## Tests Added

Added in `tests/test_safety_and_builder.py`:

- `test_weekly_no_dairy_meat_fish_uses_repeats_fallback_without_excluded_foods`
- `test_weekly_no_meat_fish_no_longer_waits_for_no_recent_timeout`
- `test_weekly_repeats_fallback_keeps_constrained_repeats_bounded`
- `test_weekly_baseline_and_single_exclusions_stay_low_repeat`
- `test_weekly_impossible_profile_returns_structured_failure`

Added in `tests/test_weekly_pdf_postgres_wiring.py`:

- `test_json_weekly_generation_failure_refunds_consumed_weekly_attempt`

The JSON refund test passed immediately because the existing JSON weekly path already refunds a consumed weekly attempt when `_send_week_plan(...)` returns `False`.

## Implementation Added

Partial implementation added in `src/diet_bot/telegram_app.py`:

- Extended `_WeekPlanBuildResult` with repeat/failure metadata:
  - `repeat_fallback_used`
  - `repeat_recipe_count`
  - `repeat_note`
  - `failure_reason`
- Added `WEEKLY_REPEATS_FALLBACK_NOTE` with the requested user-facing repeat explanation.
- Added repeat fallback constants and helper dataclasses.
- Added an early no-recent pool check intended to route narrow profiles to a repeat fallback before the old 60s no-recent retry path.
- Added a partial repeat fallback that builds eligible recipe context once, keeps safety filters hard, tries repeat-aware day generation, and schedules a small day pool across 7 days.
- Added structured failure returns for safety/no-safe-food/no-safe-recipe and incomplete fallback cases.

Current state: this is a partial implementation and should not be treated as launch-ready.

## Current Test Status

Observed RED before implementation:

- Command:
  `pytest tests/test_safety_and_builder.py::test_weekly_no_dairy_meat_fish_uses_repeats_fallback_without_excluded_foods tests/test_safety_and_builder.py::test_weekly_no_meat_fish_no_longer_waits_for_no_recent_timeout tests/test_safety_and_builder.py::test_weekly_repeats_fallback_keeps_constrained_repeats_bounded tests/test_safety_and_builder.py::test_weekly_impossible_profile_returns_structured_failure -q`
- Result:
  `4 failed in 10.97s`
- Expected failure shape:
  constrained weekly cases returned `timeout` or lacked the new metadata.

Observed after first partial implementation:

- Same command.
- Result:
  `3 failed, 1 passed in 145.79s`
- Passing:
  `test_weekly_impossible_profile_returns_structured_failure`
- Failing:
  constrained fallback tests still did not produce complete plans at that point; result was `avoidance_phase='failed'`, `failure_reason='repeats_fallback_no_complete_day'`.

Observed JSON refund test:

- Command:
  `pytest tests/test_weekly_pdf_postgres_wiring.py::test_json_weekly_generation_failure_refunds_consumed_weekly_attempt -q`
- Result:
  `1 passed in 3.63s`

No full test suite was run. No fresh test run was performed after the final STOP instruction.

## Slow Commands And Cases Observed

Initial local probe command:

- Command: inline `python -B -` probe that ran `_build_week_plans_with_recent_fallback(...)` for `no_dairy + no_meat + no_fish` and `no_meat + no_fish`, plus a 20-seed one-day probe.
- Result: timed out after `184.029s`.
- Problem: this combined probe was too broad and buffered output, so it consumed too much time without useful incremental feedback.

Baseline reproduction before implementation:

- Case: `no_dairy + no_meat + no_fish`, female/loss/simple, 4 meals, seed `607`, empty recent avoidance.
- Result: `_build_week_plans_with_recent_fallback(...)` returned `0` plans, `avoidance_phase='timeout'`, elapsed `60.014s`.

Partial fallback probes:

- Day-by-day fallback probe after early beam attempt:
  - day 0: `1.119s`, complete
  - day 1: `8.966s`, complete
  - day 2: `48.348s`, incomplete
  - total before failure: `58.435s`
- Later beam-shaped probe produced a complete 7-day result in `41.640s`, but repeat count was `16`, with some recipes used up to `4` times.
- Fast-combination experiments twice hit the command timeout at about `124s`.
- Current partial pooled fallback was observed, with a monkeypatched pool size matching the current constant, at about `10.464s` for `no_dairy + no_meat + no_fish`, complete but with repeat count `16`. This is still too slow/too repetitive for the requested target and was not verified by pytest after STOP.

## Why The Current Approach Is Too Slow

- The current partial implementation still does too much search: beam exploration, candidate reranking, combo building, and repeated `_finalize_recipe_meals(...)` calls.
- Some combinations look good by estimated protein/energy but fail after real portion scaling/top-up, causing expensive repeated finalization.
- The approach optimizes too many goals at once: repeat minimization, adjacent avoidance, protein recovery, energy fit, slot flexibility, and day-pool scheduling.
- This turns a launch-blocker fallback into another search problem, which recreates the original failure mode: long retries and uncertain completion.
- The current repeat count is also too high in observed complete fallback probes, so more tuning would likely continue the slow loop instead of simplifying the algorithm.

## Recommended Simpler Next Approach

Evaluate later with a smaller, deterministic fallback, not more beam/scoring tuning:

- Keep the normal no-repeat weekly path first.
- If it fails or the eligible main pool is below required unique weekly main slots, switch to deterministic repeat fallback.
- Build eligible candidate pools once from the existing hard safety filters.
- Allow repeats explicitly.
- Fill week day-by-day from a small set of valid one-day plans or deterministic slot pools.
- Minimize repeats using simple counters.
- Avoid adjacent repeats if possible, but do not spend long searching for it.
- Apply a strict max time budget, target under 10 seconds.
- Keep dietary exclusions hard; never relax fish/dairy/meat exclusions.
- If repeated fallback cannot build a complete week under budget, return structured failure and ensure paid weekly value is not consumed or is refunded through the existing failure path.

Recommended reset point for the next prompt:

- Either replace the current partial repeat-search implementation with the simpler deterministic fallback above, or first isolate it behind a new function and ignore the beam/combo path.
- Do not keep tuning beam sizes, combo limits, or scoring weights blindly.
