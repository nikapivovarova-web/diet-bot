# Recipe Coverage Audit

Date: 2026-05-14

Scope: docs-only coverage audit. No production code, optimizer code, PDF, promo, payments, or Telegram UX paths were changed.

## Method

The audit counts the production-relevant weekly recipe pool: `built_in_recipes()` filtered to recipes tagged `curated`, because weekly generation calls the builder with `recipe_source="curated_only"`.

The simple-compatible count uses the existing builder logic:

- `_cooking_effort_constraints(CookingTimePreference.SIMPLE)`;
- `_recipe_matches_cooking_effort`;
- `_has_complex_cooking_technique` for the special-equipment/complex-technique cut;
- `_recipe_memory_key` for recipe-key coverage;
- `evaluate_safety`, `filter_foods`, `_resolve_recipe_ingredients`, and recipe-title exclusion checks for sensitivity checks.

Protein sufficiency is estimated per recipe at the relevant 5-meal slot energy ratio for a normal MAINTAIN/simple profile: male, 32, 178 cm, 86 kg, moderate activity, 5 meals. A recipe is counted as protein-sufficient for a slot when projected protein is at least the slot's proportional share of the daily `95%` protein floor. This is not a replacement for daily builder validation; it is a coverage proxy for whether enough high-protein recipe IDs exist before the optimizer starts selecting days.

Important slot note: the catalog has `slot="breakfast"`, `slot="main"`, and `slot="snack"`. Lunch and dinner both draw from the same `main` recipe pool. Counts below show lunch and dinner separately only because their target energy ratios differ.

## Top-Level Counts

| Metric | Count |
|---|---:|
| All built-in recipes, including generated non-curated recipes | 12,975 |
| Curated recipes used by weekly `curated_only` path | 400 |
| Curated recipes that pass the full SIMPLE cooking-effort filter | 151 |
| Curated recipes cut by special equipment / complex technique | 84 |

The catalog is large overall, but the weekly production path only sees the 400 curated recipes. After SIMPLE filters, it sees 151 recipes.

## Slot Breakdown

| Slot | Curated total | Protein-sufficient | SIMPLE-compatible | SIMPLE + protein | Cut by special equipment | Missing/weak id/key |
|---|---:|---:|---:|---:|---:|---:|
| breakfast | 97 | 31 | 37 | 16 | 21 | 0 |
| lunch (`main`) | 153 | 96 | 16 | 14 | 34 | 0 |
| dinner (`main`) | 153 | 108 | 16 | 15 | 34 | 0 |
| snack | 150 | 119 | 98 | 93 | 29 | 0 |

ID/key coverage is clean in the audited curated pool: no blank recipe IDs, no blank memory keys, no duplicate recipe IDs, no duplicate memory keys, and no non-`r...` IDs.

## Weekly Coverage

| Meal count | Weekly unique recipe IDs needed | Slot demand per week | Available SIMPLE + protein recipes |
|---:|---:|---|---|
| 3 | 21 | breakfast 7, main 14 | breakfast 16, main 14-15 |
| 4 | 28 | breakfast 7, main 14, snack 7 | breakfast 16, main 14-15, snack 93 |
| 5 | 35 | breakfast 7, main 14, snack 14 | breakfast 16, main 14-15, snack 93 |

The no-exclusion profile technically has enough main recipes only at the edge: 14 lunch-sufficient SIMPLE main recipes for a weekly requirement of 14 main slots. That leaves no buffer for macro balance, protein overage avoidance, recipe-key memory, recent-chat memory, broccoli/egg/dairy/gluten/fish exclusions, or deterministic seed clustering.

This explains why a greedy weekly builder can fail even though the catalog looks large: the effective high-protein SIMPLE main pool is just barely large enough before real-world constraints are applied.

## Sensitivity Checks

Counts below are already filtered to recipes that survive the exclusion and pass SIMPLE. The `SIMPLE + protein` column is the practical no-repeat coverage number.

| Scenario | Breakfast SIMPLE + protein | Lunch/main SIMPLE + protein | Dinner/main SIMPLE + protein | Snack SIMPLE + protein | Coverage risk |
|---|---:|---:|---:|---:|---|
| No eggs | 3 | 9 | 9 | 77 | Fails breakfast and main no-repeat coverage |
| No dairy | 3 | 6 | 6 | 7 | Fails breakfast, main, and 5-meal snack coverage |
| No gluten/wheat | 8 | 5 | 5 | 64 | Fails main no-repeat coverage |
| No fish/seafood | 14 | 7 | 8 | 82 | Fails main no-repeat coverage |
| No broccoli | 15 | 13 | 14 | 93 | Lunch/main is below the 14-recipe weekly requirement |

The main pool is the recurring failure point. Breakfast also becomes too narrow for egg-free or dairy-free users. Snacks are generally abundant, except dairy-free 5-meal weeks, where only 7 SIMPLE + protein snacks remain for 14 snack slots.

## Gaps

The biggest gap is not raw recipe count. It is robust SIMPLE high-protein recipes in the `main` slot that survive common exclusions.

Priority gaps:

- SIMPLE high-protein mains without egg, dairy, gluten/wheat, fish/seafood, or broccoli.
- SIMPLE high-protein breakfasts without egg or dairy.
- SIMPLE high-protein dairy-free snacks, especially savory snacks.
- More moderate-protein mains, so weekly selection can avoid protein ratios above `130%` when lower-overage alternatives exist.
- More main recipe format variety: bowls, skillet meals, salads, soups/stews, wraps, and plates that do not depend on oven, blender, waffle iron, food processor, long marinating, or multi-stage prep.

Approximate additions for stable weekly generation:

| Area | Minimum to meet hard weekly count | Better stability target |
|---|---:|---:|
| Robust SIMPLE main recipes | +9 to cover the worst individual exclusion (`no_gluten/wheat`: 5 -> 14) | +16 or more to reach about 21 robust mains |
| Egg-free/dairy-free protein breakfasts | +4 to reach 7 | +8-10 for buffer |
| Dairy-free protein snacks | +7 to support 5-meal weeks | +10-14 for buffer |
| Moderate-protein main alternatives | +8-12 | +15+ spread across poultry, lean meat, tofu, legumes |

The most useful new recipes are those that survive multiple exclusions at once:

- chicken/turkey/tofu/lean beef/legume rice bowls;
- potato or quinoa plates with poultry/tofu/legumes;
- corn-tortilla wraps with poultry/tofu/beans;
- lentil, chickpea, tofu, or turkey skillet meals;
- egg-free tofu or turkey breakfasts;
- dairy-free snacks built around tuna alternatives, tofu, turkey/chicken, hummus/legumes, or lactose-free only if the product policy treats lactose-free as acceptable for dairy exclusions. Currently the dairy exclusion removes lactose-free dairy too.

Avoid adding recipes that only expand already-abundant zones, such as dairy snacks or complex oven/baking recipes, until the main-slot shortage is fixed.

## Recommendation

Do not continue expanding the optimizer first.

A bounded optimizer can make better choices than the current greedy path, but the audited pool has no real buffer in the exact place the weekly generator needs it most: SIMPLE high-protein main recipes. Under common individual exclusions, the main pool falls below the hard 14 unique main recipes needed for any 7-day week, regardless of whether the user asks for 3, 4, or 5 meals.

Recommended next step:

1. Add a small targeted data slice before another optimizer implementation slice.
2. Start with robust SIMPLE main recipes that avoid egg, dairy, gluten/wheat, fish/seafood, and broccoli.
3. Add enough egg-free/dairy-free breakfasts and dairy-free snacks to make exclusion cases feasible.
4. Re-run this audit and only then wire the bounded optimizer into production weekly generation.

Minimum high-impact data slice:

- 12-16 robust SIMPLE main recipes;
- 6-8 egg-free/dairy-free high-protein breakfasts;
- 8-10 dairy-free high-protein snacks.

After that, an optimizer slice is more likely to be small, bounded, and green because it will be choosing among real alternatives instead of trying to solve a pool coverage problem with search.
