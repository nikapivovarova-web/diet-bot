# Balanced Recipe Selection v2 Design

Date: 2026-05-18

Scope: design slice only. This document does not implement planner v2, change scoring logic, change nutrition math, change storage, change Telegram UI, change payments, or change PDF generation.

## 1. Problem Statement

The current recipe picker can over-select local score winners. A recipe that fits the current slot, macro target, cooking preference, and metadata shape slightly better than its neighbors can win repeatedly across seeds, days, and weekly attempts. Recent-history avoidance helps, but it is a late guard around a picker that still concentrates on the same families when the viable pool is uneven.

Recent-history and hard no-repeat rules are not enough for month-long usage. Users may generate one-day rations and weekly PDFs for months. A plan can avoid yesterday's exact recipe and still feel repetitive if it keeps returning the same protein family, carb family, format, or preparation style. The product needs variety at the level a person notices: not just different recipe IDs, but different meals.

New recipe batches can dominate when they cluster in useful planner slots or have richer metadata than older recipes. If a new import adds many simple, high-protein, flexible bowls or snacks, those recipes can become the easiest local winners. That is not the same as better long-term planning. The growing catalog should improve coverage without letting any one batch take over simply because it was added recently or annotated more completely.

The broader product problem is stable selection from a growing catalog. The catalog will keep expanding, users will keep generating plans, and the team should not need multi-day manual old/new/fairness tuning after every import. Planner v2 should make recipe selection robust by design: hard constraints stay hard, quality score remains useful, and variety is enforced through balanced candidate choice rather than local symptom fixes.

## 2. Non-Goals

- Do not rewrite the calculator or nutrition math.
- Do not change payments, subscriptions, PDF rendering, or Telegram UI behavior.
- Do not enforce exact old/new ratios.
- Do not use hard old/new quotas, "max new recipes per week" as the core solution, or source-id balancing as the main mechanism.
- Do not sacrifice allergies, exclusions, medical safety, energy feasibility, macro floors, or controlled failure behavior for variety.
- Do not treat this design as a request to implement planner v2 in the current slice.

## 3. Architecture

Planner v2 should split recipe planning into three explicit layers. The main design goal is to make concentration visible and controllable before final selection, while keeping the existing safety and macro gates as the boundary conditions.

### Layer A: Eligibility

Eligibility is the hard-filter layer. A recipe that fails this layer is not a candidate for balanced selection.

Hard filters:

- Allergies, excluded foods, forbidden tags, and condition-specific exclusions.
- Slot suitability, including native slot, explicit `allowed_meal_slots`, and `slot_flex_type`.
- Cooking preference and allowed fallback phases.
- Portion scaling feasibility and practical serving feasibility where the current planner already enforces it.
- Macro and energy feasibility for the slot or day target, including hard protein floors.
- Recent hard no-repeat where required, such as same-week exact recipe repeats when alternatives exist and any product-defined strict cooldown window.

Layer A should produce a viable candidate pool plus rejection reasons. Those reasons matter because a thin pool is different from a scoring problem. If dairy-free snacks, simple native mains, or a specific macro profile leaves too few options, v2 should expose that as catalog health evidence instead of hiding it behind repeated local winners.

### Layer B: Candidate Stratification

Stratification groups eligible recipes by traits that influence perceived variety and future feasibility. These groups are not quotas. They are structure for selection and diagnostics.

Candidate traits:

- Slot: breakfast, snack, main, and explicit flexible slot use.
- Primary protein family: egg, poultry, fish, seafood, beef/lamb, pork, dairy, legumes, soy/tofu, nuts/seeds, mixed, none.
- Primary carb family: oats, bread/toast, rice, pasta/noodles, potato, buckwheat/grain, tortilla/wrap, fruit, low-carb/no-main-carb, mixed.
- Format/type: bowl, salad, soup, pasta, toast, sandwich, roll/wrap, skillet, stew, bake, porridge, smoothie, snack plate, dessert-like snack, simple plate, other.
- Effort/time: declared `cooking_effort`, `active_time_min`, and current inferred effort constraints.
- Recipe source/batch: source name, source tag, import batch, or recipe number range, used only as a weak diversity signal and debug dimension.
- Recency bucket: recently used, cooling down, fresh, and unknown/no history.

The existing code already has some pieces: slot flex metadata, cooking effort metadata, active time, source tags, recipe memory keys, and an inferred `_recipe_format`. V2 should consolidate those into a small trait view rather than spreading variety logic across scorer tweaks. Missing metadata should not make a recipe artificially attractive; it should get conservative defaults until curated.

### Layer C: Balanced Selection

Balanced selection chooses from the viable stratified pool. It keeps score as a quality signal, but prevents a small group of local winners from absorbing too many selections.

Selection policy:

- Generate a viable candidate pool for each needed slot.
- Rank candidates by existing quality signals: safety, macro fit, energy fit, slot fit, cooking preference, scaling feasibility, and recipe quality.
- Select from top-N viable candidates per slot and bucket rather than only the top global score.
- Use deterministic weighted random with a seed, so the same profile, history, catalog, and seed produce reproducible output.
- Penalize repeated protein, carb, format, and family traits across the current day/week and recent user history.
- Penalize recent exact recipes and recipe keys more strongly than broad family repeats.
- Treat source/batch as a weak diversity signal: useful for avoiding concentration, never the main rule.
- Prefer fresh or cooled-down candidates over recently used candidates when comparable hard-valid options exist.
- Keep a bounded escape hatch: if v2 cannot satisfy safety, meal count, energy, and macro constraints, fall back to the current picker and record that v2 failed to satisfy hard requirements.

The important distinction is that score should answer "is this candidate good enough?" while balanced selection answers "does this candidate keep the user's diet varied over time?" A high-scoring candidate can still lose if the current week already has the same protein, carb, and format pattern several times.

## 4. One-Day vs Weekly Generation

One-day generation should use the v2 slot selection policy. Even a single day benefits from avoiding a same-format day such as toast breakfast, wrap snack, and wrap main when equally valid alternatives exist. The day-level state should track selected recipe IDs, recipe keys, protein families, carb families, formats, and effort balance while building the meal list.

Weekly generation should use the same policy plus week-level diversity memory. The weekly planner should not be a separate fairness system. It should call the same eligibility and trait helpers, then carry a larger state across seven days: used recipe IDs/keys, trait counts, day signatures, batch carryovers, and macro feasibility. Weekly selection can still use a bounded optimizer or beam-like search, but its candidate scoring should include future flexibility and concentration costs.

Monthly usage should rely on persistent recent recipe history. The history layer should supply exact recipe/key cooldowns and softer trait recency signals. For example, a recipe served last week can be blocked or heavily penalized; a protein family used heavily across the last two weeks can receive a softer penalty; a recipe not seen for a month should be eligible again if it fits. This avoids turning recent history into a permanent ban while still preventing fast repetition.

## 5. Growing Catalog Behavior

Adding `r611-r900` should make the pool broader, not hand control of the planner to the newest import.

Expected behavior:

- New recipes enter the same trait buckets as existing recipes.
- New batches improve coverage in thin buckets, such as dairy-free snacks or simple mains, without bypassing the same selection policy.
- A batch with richer metadata should not dominate over older recipes only because older recipes have missing traits.
- Missing metadata should receive conservative inferred defaults: usable, but not over-rewarded.
- Import batch/source should be visible in diagnostics and weakly penalized for concentration, but never used as a hard old/new quota.
- Catalog health checks should report bucket imbalance, such as too many new recipes in one format, too few simple mains for a restriction, or too many unknown primary protein values.

The planner should treat catalog growth as more choices inside buckets. If a new import contains 80 simple chicken bowls, v2 should understand that as one well-covered protein/format region, not as 80 independent reasons to keep selecting chicken bowls.

## 6. Data Requirements

Required or useful metadata:

| Field | Purpose | Initial source | Later curation |
|---|---|---|---|
| `primary_protein` | Penalize repeated protein families and diagnose protein coverage. | Infer from dominant protein ingredient and recipe tags. | Curate ambiguous mixed dishes, vegetarian protein, and small protein toppings. |
| `primary_carb` | Penalize repeated carb families and diagnose energy coverage. | Infer from dominant carb ingredient. | Curate low-carb dishes, fruit-forward breakfasts, and mixed grain dishes. |
| `recipe_format` | Penalize repeated formats a user notices. | Extend current format inference from title, ID, slot, and ingredients. | Curate ambiguous dishes and add canonical format values. |
| `slot_flex` | Keep slot suitability explicit. | Use existing `allowed_meal_slots` and `slot_flex_type`; infer conservative default from native slot. | Curate older recipes with realistic flexible slots. |
| `active_time` / `effort` | Respect cooking preference and diversify effort within allowed range. | Use existing `active_time_min` and `cooking_effort`; infer from instructions when missing. | Curate old recipes with reliable active time and special equipment notes. |
| `batch/source generation` | Debug concentration and weakly diversify imports. | Use `source:*` tags, recipe key prefixes, source name, or recipe number ranges. | Add explicit import batch if current fields are not enough. |
| `cuisine/style_tags` | Optional broader variety and future user preference matching. | Infer cautiously from title/source where obvious. | Curate later; do not block v2 launch on this. |

Inference is enough for v2 bootstrap if defaults are conservative and tests cover unknown metadata. Curation should focus on high-impact ambiguous recipes and bucket health, not full manual perfection before the architecture can ship.

## 7. Test Strategy

The tests should prove safety remains hard and concentration is bounded without asserting exact old/new ratios.

Recommended tests and smokes:

- Deterministic one-day sample across seeds: fixed profile/history/catalog gives stable recipe IDs for each seed and shows variety across seed range.
- Deterministic weekly sample across seeds: same seed gives the same week; several seeds produce different but complete weeks.
- Future batch simulation: add a synthetic new batch with many attractive candidates in one or two formats and verify it does not dominate selections beyond concentration guard thresholds.
- Long-term simulation: generate 30 one-day plans or 4 weekly plans for one user with persisted history, then report recipe repeat rate, protein/carb/format concentration, safety status, and macro floors.
- Safety/exclusion tests: allergies, excluded foods, and condition exclusions remain hard filters even when variety pressure is high.
- Macro-floor tests: daily protein and other hard floors still hold; variety penalties cannot select macro-invalid meals.
- Fallback tests: when v2 cannot satisfy safety/macro constraints, current picker fallback is called and the fallback reason is recorded.
- Metadata-default tests: recipes with missing trait metadata get conservative defaults and do not become preferred because fields are unknown.
- Catalog health smoke: bucket counts by slot, effort, protein, carb, format, source/batch, and restriction profile are reported.
- Concentration guards: assert upper bounds for repeated exact recipes, recipe keys, protein families, carb families, formats, and single source/batch share over simulated periods.

Avoid tests that require exact old/new ratios. A healthy result might select many new recipes if they fill genuinely thin buckets, or many older recipes if they are the best safe fit. The guard should be concentration, not age.

## 8. Implementation Plan Outline

This is a future implementation outline only.

### Slice 1: Trait Inference Helpers and Tests

Add a focused trait module that maps `RecipeTemplate` to `RecipeTraits`. It should infer `primary_protein`, `primary_carb`, `recipe_format`, slot flexibility, effort bucket, source/batch, and metadata confidence. Tests should cover old curated recipes, imported recipes with explicit metadata, generated/manual recipes, and missing fields.

### Slice 2: Balanced Slot Candidate Picker for One-Day

Add a slot-level picker that takes eligible candidates, existing score output, trait history, and seed. It should choose from top-N viable candidates with deterministic weighted random and concentration penalties. Wire it behind a narrow internal interface so the current one-day builder can fall back cleanly if v2 cannot produce a hard-valid day.

### Slice 3: Weekly v2 Selection Using the Same Policy

Reuse the same eligibility and trait scoring for weekly generation. Add week-level state for recipe IDs, recipe keys, family counts, format counts, source/batch counts, carryovers, and future feasibility. Keep search bounded by candidate limits and deadlines. Weekly success still means seven complete days with the expected meal count.

### Slice 4: Recent-History and Month-Long Simulation

Use persisted recent recipe history to feed exact cooldowns and softer trait recency penalties. Add a 30-day / 4-week simulation harness that can run against the current catalog and synthetic future batches. Use this as the main regression surface for "users stay for months."

### Slice 5: Manual QA and Tuning

Review generated one-day and weekly menus for normal profiles plus hard profiles such as dairy-free, gluten-free, egg-free, fish-free, simple cooking, and five meals. Tune concentration weights, top-N sizes, fallback thresholds, and catalog health warnings from observed menus, not from old/new batch share alone.

## 9. Risks

- Over-constraining candidates: too many soft penalties can make thin profiles fail or fall back too often.
- Slower generation: top-N pools, trait scoring, and weekly search add work, so v2 needs candidate caps, deadlines, and cached trait inference.
- Unstable tests: deterministic weighted random must use explicit seeds and stable ordering to avoid noisy CI.
- Hiding real data quality issues: broad fallback can mask thin buckets or missing metadata unless diagnostics report why v2 struggled.
- Worse macro fit: variety penalties can pull selection away from the best macro candidates, so hard floors and macro feasibility must remain before selection and in final validation.
- Metadata bias: new recipes with explicit metadata and old recipes with inferred metadata can still skew selection unless defaults and confidence handling are tested.
- User-visible repetition under restrictions: some profiles may have genuinely thin safe pools, so the product needs honest controlled fallback and catalog health follow-up rather than fake variety.

## Success Criteria

- Exact recipe repeats and near-duplicate recipe keys are controlled across one-day, weekly, and month-long usage.
- Protein, carb, format, and source/batch concentration are bounded without enforcing old/new ratios.
- Safety, exclusions, complete meal count, and macro floors remain hard.
- Adding a large future batch improves coverage without taking over the planner by default.
- Missing metadata does not become a ranking advantage.
- Failures are diagnosable as eligibility shortage, metadata imbalance, v2 selection exhaustion, or fallback to current picker.
