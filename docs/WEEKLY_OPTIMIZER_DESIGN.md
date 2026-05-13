# Weekly Optimizer Design

Date: 2026-05-14

Scope: design/audit slice only. This document does not implement the optimizer, add tests, or change production code.

## Context Audited

- `docs/RECIPE_QUALITY_SMOKE_NOTES.md` records the follow-up after `fdb61bd`, `12f67bb`, and `b5c8119`.
- No `docs/debug` follow-up directory exists in this workspace.
- Current weekly generation entry point is `src/diet_bot/telegram_app.py::_send_week_plan`.
- Current weekly day selection is `src/diet_bot/telegram_app.py::_build_week_plans` -> `_select_week_day_plan`.
- Daily recipe construction, exclusions, recipe avoidance, and hard protein gates are in `src/diet_bot/builder.py`.

## Current Flow

`_send_week_plan` loads recent chat recipe history and passes `recent_recipe_ids` / `recent_recipe_keys` into `_build_week_plans`. `_build_week_plans` initializes weekly avoided sets from those recent values, then loops over 7 days.

For each day, `_select_week_day_plan` calls `build_one_day_plan` `WEEK_PLAN_CANDIDATE_COUNT` times. That count is currently `4`. Each call receives the current weekly avoided recipe IDs and keys with `allow_avoided_recipe_relaxation=False`, so recipes already used earlier in the week are filtered before the daily plan is built. `_select_week_day_plan` then picks the candidate with the best ingredient reuse score and returns a single day.

After a selected day returns, `_build_week_plans` immediately adds that day's `recipe_id` and `recipe_key` values to the weekly avoided sets. If any selected day is incomplete, `_build_week_plans` now returns `()`. `_send_week_plan` treats `()` or any incomplete week as controlled failure and does not render/send a partial PDF.

## Root Cause

The failure is not that exclusions or protein gates are being skipped. The failure is that the weekly algorithm commits too early.

For `MAINTAIN` / `SIMPLE` / `5 meals`, the feasible curated pool appears narrow and high-protein daily plans repeatedly depend on the same small set of recipes. The current greedy loop only sees one day at a time. It chooses the locally best day candidate, then makes those recipes unavailable to all future days. This can consume scarce breakfast/main/snack recipes before the algorithm has checked whether later days can still hit 5 meals and the hard protein floor.

Local audit for seed `101` reproduced the current behavior:

- Days 1-4 completed with 20 unique recipe IDs.
- Day 5 returned an empty plan once those 20 IDs were in the weekly avoided set.
- The same day-5 seeds generated complete plans when weekly avoided IDs were not passed, but those plans reused earlier scarce recipes such as `r041`, `r188`, `r217`, and `r349`.
- A simple set-packing check over the existing 4 no-avoid candidates per day found no disjoint 7-day solution, which means the current candidate pool is also too narrow.

So the weekly generator needs two changes in a later implementation slice: more day candidates, and a bounded week-level search that can reject early choices before they burn the pool.

## Hard Constraints

These should remain hard optimizer constraints:

- Allergies, excluded foods, and medical/condition exclusions must never be violated.
- `recipe_id` repeats should not be allowed across the 7-day week when alternatives exist.
- `recipe_key` memory should continue to protect against near-duplicate template reuse where the current code already tracks it.
- Daily protein must remain at or above the hard floor: `protein >= target * 0.95`.
- A partial week must never count as success. Weekly PDF success requires exactly 7 complete days and the expected meal count per day.
- Weekly generation must be bounded. A search timeout or exhausted candidate pool should return controlled failure, not a partial PDF.

## Candidate Strategies

### Bounded Backtracking

Generate candidates for each day, then recursively select one candidate per day while carrying the used `recipe_id` / `recipe_key` sets. Backtrack when a day candidate conflicts or when remaining candidate pools cannot complete the week.

Pros:

- Simple mental model.
- Finds a full solution if the bounded candidate pool contains one.
- Easy to keep hard constraints explicit.

Cons:

- Can still blow up if implemented as unbounded DFS.
- Needs careful ordering and runtime guards.

### Beam Search

Generate candidate day plans, then walk days while keeping only the best `N` partial week states after each day. Each state carries plans, used recipe IDs/keys, score, and any batch carryover state. Invalid states are discarded immediately.

Pros:

- Bounded by construction: `days * beam_width * candidates_per_day`.
- Better than greedy because it preserves several viable partial weeks instead of only one.
- Easier to tune for Telegram runtime than open-ended DFS.

Cons:

- Not exhaustive if beam width is too small.
- Candidate scoring must reward future feasibility, not only today's ingredient reuse.

### Larger Candidate Pool + Scoring

Increase generated day candidates and rank them by macro fit, protein ratio, recipe scarcity, repeated ingredient cost, and future flexibility.

Pros:

- Directly addresses the current 4-candidate bottleneck.
- Makes either backtracking or beam search more effective.

Cons:

- By itself, larger greedy still commits too early.
- More calls to `build_one_day_plan` increase weekly PDF latency unless guarded.

### Curated Pool Expansion

Add more `SIMPLE` curated recipes suitable for `MAINTAIN` / `5 meals`, especially high-protein but not excessive-protein breakfasts, mains, and snacks.

Pros:

- Product-quality improvement, not only algorithmic recovery.
- Reduces pressure on the same rare recipe IDs.

Cons:

- Data/content work can mask but not fix the greedy algorithm.
- Requires separate validation for exclusions, macros, photos/text, and cooking effort.

### Controlled Fallback / Relaxation

If product policy allows it, the bot could relax only soft preferences after a bounded optimizer failure, such as recent-chat recipe memory or ingredient reuse preference.

Pros:

- Can reduce user-facing failures for tight pools.

Cons:

- Must not relax allergies/exclusions, protein floor, or partial-week success.
- Relaxing same-week `recipe_id` repeats would need an explicit product decision because current quality direction is no repeats when alternatives exist.

## Recommendation

Use bounded beam search with a small backtracking finisher.

The primary implementation should pre-generate a bounded pool of complete, hard-valid day candidates for each day position, then run a week-level beam search over those candidates. If the beam reaches day 7, choose the best full-week state. If the beam cannot complete the final day but the candidate pool is small, a limited depth-first finisher can try the top states under the same deadline. If no full week is found, return controlled failure.

This is better than the current greedy loop because it keeps several partial-week choices alive and can choose a slightly worse day 1 if that preserves scarce recipes needed on day 5 or day 6. It should not explode because generation and search are both capped:

- Candidate generation is capped per day and globally.
- Search states are capped by beam width.
- Runtime has a deadline.
- The optimizer only explores complete daily plans that already satisfy hard daily gates.

## Algorithm Sketch

### Candidate Generation

Generate candidates before weekly selection instead of passing the growing weekly avoided set into each day builder.

- Start from recent chat avoided IDs/keys as hard initial memory.
- For each of 7 day positions, call `build_one_day_plan` with `recipe_source="curated_only"` and `allow_avoided_recipe_relaxation=False`.
- Pass recent chat avoided IDs/keys, but do not pass same-week IDs during candidate generation.
- Generate an initial `8` unique complete candidates per day.
- If no full-week state is found and the deadline allows it, expand to `12` or `16` candidates per day.
- Dedupe candidates by ordered `recipe_id` signature.
- Drop candidates that are incomplete, fail `safety.can_generate_plan`, miss the meal count, miss the 95% protein floor, or violate exclusions.

This changes no hard constraints. It only postpones same-week no-repeat enforcement from daily filtering to week-level selection.

### Week State

Each beam state should carry:

- selected `MealPlan` objects;
- used `recipe_id` set, initialized from recent IDs;
- used `recipe_key` set, initialized from recent keys;
- carryover state, if batch prep remains active;
- accumulated score;
- timing/debug counters for smoke notes.

A candidate can extend a state only when its recipe IDs and keys do not conflict with that state. If product later allows recent-memory relaxation, keep it as a separate explicit fallback phase, not mixed into the main hard path.

### Scoring

Score full and partial weeks with penalties rather than binary preferences:

- Reject hard invalid candidates first.
- Prefer protein ratios near `1.00-1.15`; penalize ratios above `1.30`, and heavily penalize above `1.50`.
- Prefer energy/fat/carbohydrate closeness using the existing daily candidate scoring idea.
- Prefer lower recipe scarcity usage early in the week. A recipe that appears in few candidate pools should be saved unless it unlocks the best path.
- Prefer moderate ingredient reuse for shopping-list practicality, but never ahead of hard feasibility.
- Prefer candidate diversity across slots and recipe formats.
- Use deterministic tie-breakers based on seed/day/candidate index.

### Runtime Limits

Proposed first-pass bounds:

- `initial_candidates_per_day = 8`;
- `expanded_candidates_per_day = 16` only after first failure and only if under deadline;
- `beam_width = 12`;
- optional finisher examines at most the top `4` partial states;
- total wall-clock deadline around the existing weekly PDF tolerance, with a test guard that forces fast controlled failure when exceeded.

With pre-generated candidates, week search is cheap: roughly `7 * beam_width * candidates_per_day` compatibility checks after candidate generation. The expensive part remains `build_one_day_plan`, so the implementation should count and cap those calls.

### Failure Behavior

If the optimizer cannot produce 7 complete days:

- return `()`, matching the current controlled-failure contract;
- do not render a PDF;
- do not remember recipes from partial states;
- include internal debug counters in smoke notes or logs, such as candidates generated, candidates rejected by hard gates, beam states kept, and failure reason.

## Test Plan

- `MAINTAIN` / `SIMPLE` / `5 meals` produces a full 7-day week for the known failing profile/seed when the curated pool contains enough alternatives.
- Weekly success has no repeated `recipe_id` across all 7 days.
- Every day remains at `protein >= target * 0.95`.
- Protein overage is not above `130%` when alternatives exist; higher ratios should be treated as a scoring failure to avoid unless the pool is truly infeasible.
- Egg allergy exclusions still remove egg variants from foods, recipe ingredients, and recipe titles across all days.
- Broccoli excluded-food preference still removes broccoli/broccolini variants across all days.
- An intentionally infeasible pool returns controlled failure (`()`), not a partial week.
- Runtime guard test proves optimizer failure does not hang and does not run unbounded DFS.
- Regression coverage keeps the existing partial-week controlled failure behavior in `_send_week_plan`.

## Implementation Slices

### Slice 1: Candidate Generation and Scoring Helpers

- Add helper(s) that generate unique complete day candidates for a day seed range.
- Add reusable scoring helpers for candidate/day/week macro quality, protein overage, ingredient reuse, recipe scarcity, and deterministic tie-breaks.
- Add debug counters without changing production messaging.
- Keep the existing greedy path available until the optimizer is ready to replace it.

### Slice 2: Bounded Optimizer

- Add a bounded beam search that selects 7 compatible day candidates.
- Enforce no same-week `recipe_id` / `recipe_key` conflicts in the week state.
- Preserve hard exclusions, hard protein floor, and complete-week-only success.
- Return controlled failure when no full state is found within bounds.

### Slice 3: Smoke Notes and Performance/Runtimes

- Record the known `MAINTAIN` / `SIMPLE` / `5 meals` profile result.
- Record no-repeat, protein floor, protein overage, egg exclusion, broccoli exclusion, and infeasible-pool results.
- Record candidate counts, beam width, elapsed runtime, and any deadline-triggered controlled failure.
- Keep PDF/payment/promo smokes out of scope unless separately requested.
