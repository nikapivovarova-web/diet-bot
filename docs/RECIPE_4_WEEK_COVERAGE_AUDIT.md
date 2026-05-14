# Recipe 4-Week Coverage Audit

Date: 2026-05-14

Scope: docs/audit slice only. No production code, recipe data, builder, PDF, Telegram, promo, payments, storage, or photo assets were changed.

## Summary

The current curated catalog has 505 recipes, not 400. The older coverage docs were correct for their slice, but they predate the `r401`-`r505` import. The current curated-only planner pool is:

| Pool | Total | Breakfast | Snack | Main |
|---|---:|---:|---:|---:|
| Curated source/runtime recipes | 505 | 119 | 181 | 205 |
| Strict SIMPLE-compatible | 248 | 62 | 131 | 55 |
| INTERESTING expanded | 324 | 87 | 158 | 79 |
| Last-resort effort-relaxed, no effort filter | 505 | 119 | 181 | 205 |

For unrestricted `5 meals/day` over 4 weeks, strict native SIMPLE is short by exactly 1 native main recipe: 55 available for 56 main positions. However, current builder semantics allow main-like snack recipes to fill main slots. With that fallback, the strict SIMPLE effective main pool is 101 recipes, so the current no-restriction 4-week problem is not a raw slot-count shortage.

The real shortages appear under common hard exclusions, especially dairy-free. The current recent-history fallback issue is therefore mixed:

- Unrestricted current catalog: enough by broad slot count if snack-as-main fallback is allowed.
- Strict native SIMPLE mains: thin, with almost no 4-week buffer.
- Common restrictions: real catalog gaps, led by dairy-free snacks/mains and gluten/wheat-free native mains.
- Current history failure: mostly algorithm/search behavior under hard recent avoidance, not a 505-recipe total-size problem.

## Inputs Read

Existing docs reviewed:

- `docs/RECIPE_COVERAGE_FUNNEL.md`
- `docs/RECIPE_COVERAGE_SMOKE_NOTES.md`
- `docs/RECIPE_IMPORT_SMOKE_NOTES.md`
- `docs/RECIPE_HISTORY_FALLBACK_DEBUG.md`

Current runtime/data checked:

- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/curated_data.py`
- `src/diet_bot/recipe_catalog.py`
- `src/diet_bot/builder.py`
- `src/diet_bot/safety.py`

One direct runtime weekly-generation probe was attempted for the current `MAINTAIN/simple/5` profile with full recent avoidance, but it exceeded 124 seconds and produced no usable result. The feasibility results below are static catalog counts plus the already-recorded runtime debug evidence.

## Catalog Identity

| Metric | Count |
|---|---:|
| Raw curated JSON recipes | 505 |
| Built-in runtime recipes, all sources | 13,080 |
| Built-in curated recipes | 505 |
| Manual non-curated recipes | 23 |
| Generated combinatorial recipes | 12,552 |
| Curated + manual recipes | 528 |
| Curated `recipe_id` duplicates | 0 |
| Curated native memory-key duplicates | 0 |
| Imported `r401`-`r505` recipes | 105 |

This audit uses the 505 curated recipes as the source of truth because weekly product smoke uses `recipe_source="curated_only"`.

## Effort Pools

Runtime effort semantics:

- `SIMPLE`: active time <= 30 min, <= 11 ingredients, <= 6 instruction sentences, no special-equipment/complex keyword.
- `INTERESTING`: active time <= 45 min, <= 12 ingredients, <= 7 instruction sentences, complex equipment allowed.
- `INTERESTING` is expanded, not complex-only. The SIMPLE pool is a subset of the INTERESTING pool.
- Last-resort relaxed effort below means no effort filter, while hard exclusions still apply.

| Effort pool | Total | Breakfast | Snack | Main | Notes |
|---|---:|---:|---:|---:|---|
| Strict SIMPLE | 248 | 62 | 131 | 55 | Main is the native bottleneck |
| INTERESTING expanded | 324 | 87 | 158 | 79 | Adds 76 recipes over SIMPLE |
| Last-resort relaxed effort | 505 | 119 | 181 | 205 | Includes long/complex recipes |

Primary SIMPLE exclusion reasons:

| Reason | Total | Breakfast | Snack | Main |
|---|---:|---:|---:|---:|
| Passes SIMPLE | 248 | 62 | 131 | 55 |
| Active time > 30 min | 160 | 37 | 18 | 105 |
| Ingredients > 11 | 46 | 8 | 6 | 32 |
| Instruction sentences > 6 | 24 | 3 | 11 | 10 |
| Special equipment/complex technique | 27 | 9 | 15 | 3 |

Special-equipment/complex keyword flags, regardless of primary reason:

| Keyword family | Curated matches | Breakfast | Snack | Main |
|---|---:|---:|---:|---:|
| Blender | 39 | 12 | 13 | 14 |
| Grill | 17 | 2 | 3 | 12 |
| Food processor | 8 | 0 | 7 | 1 |
| Waffle iron | 1 | 1 | 0 | 0 |
| Any complex keyword | 62 | 15 | 21 | 26 |

## Hard Restriction Pools

Counts below are after production-style hard filtering: excluded foods/tags removed, recipe ingredients must resolve, and excluded food names in recipe titles are rejected.

### Strict SIMPLE

| Restriction | Total | Breakfast | Snack | Main |
|---|---:|---:|---:|---:|
| None | 248 | 62 | 131 | 55 |
| Egg-free | 175 | 30 | 102 | 43 |
| Dairy-free | 73 | 16 | 29 | 28 |
| Gluten/wheat-free | 153 | 41 | 91 | 21 |
| Fish/seafood-free | 204 | 58 | 108 | 38 |
| Broccoli-free | 243 | 59 | 131 | 53 |
| Nut-free | 203 | 49 | 102 | 52 |

### INTERESTING Expanded

| Restriction | Total | Breakfast | Snack | Main |
|---|---:|---:|---:|---:|
| None | 324 | 87 | 158 | 79 |
| Egg-free | 228 | 39 | 125 | 64 |
| Dairy-free | 107 | 24 | 39 | 44 |
| Gluten/wheat-free | 198 | 58 | 109 | 31 |
| Fish/seafood-free | 275 | 83 | 135 | 57 |
| Broccoli-free | 315 | 83 | 158 | 74 |
| Nut-free | 258 | 66 | 118 | 74 |

### Last-Resort Effort-Relaxed

| Restriction | Total | Breakfast | Snack | Main |
|---|---:|---:|---:|---:|
| None | 505 | 119 | 181 | 205 |
| Egg-free | 361 | 48 | 143 | 170 |
| Dairy-free | 204 | 30 | 53 | 121 |
| Gluten/wheat-free | 270 | 72 | 114 | 84 |
| Fish/seafood-free | 429 | 114 | 158 | 157 |
| Broccoli-free | 484 | 115 | 181 | 188 |
| Nut-free | 407 | 89 | 132 | 186 |

Hard exclusions should not be relaxed. Effort relaxation fixes many dairy/gluten/fish main deficits, but dairy-free snacks remain thin even with no effort filter: 53 available for 56 four-week snack positions.

## Protein Proxy

This is an audit proxy, not a production hard per-recipe filter. Production validates/scales a whole day. Proxy profile: male, 32, 178 cm, 86 kg, moderate activity, maintain goal, 5 meals/day. Daily target is about 2,817 kcal and 95 g protein. The 95% protein floor is 90.25 g/day.

5-meal proxy thresholds:

| Slot | Target ratio | Protein proxy |
|---|---:|---:|
| Breakfast | 0.25 | 22.56 g |
| Lunch main | 0.30 | 27.07 g |
| Snack | 0.10 | 9.03 g |
| Dinner main | 0.25 | 22.56 g |
| Second snack | 0.10 | 9.03 g |

No-restriction high-protein proxy counts:

| Pool | Breakfast HP | Snack HP | Lunch-main HP | Dinner-main HP | 4-week HP deficit |
|---|---:|---:|---:|---:|---|
| Strict SIMPLE | 24/28 | 113/56 | 45/28 | 50/28 | Breakfast short 4; main unique capacity short 6 |
| INTERESTING expanded | 30/28 | 132/56 | 60/28 | 66/28 | none |
| Last-resort relaxed | 38/28 | 139/56 | 135/28 | 150/28 | none |

Strict SIMPLE high-protein proxy under common restrictions:

| Restriction | Breakfast HP deficit | Snack HP deficit | Main HP deficit | Notes |
|---|---:|---:|---:|---|
| None | 4 | 0 | 6 | Main capacity uses dinner-suitable unique count |
| Egg-free | 21 | 0 | 18 | Egg-free breakfasts are very thin |
| Dairy-free | 25 | 42 | 30 | Dairy-free snacks are the largest protein bottleneck |
| Gluten/wheat-free | 16 | 0 | 37 | Main shortage dominates |
| Fish/seafood-free | 7 | 0 | 23 | Fish removal hits high-protein mains |
| Broccoli-free | 5 | 0 | 8 | Small but real protein-buffer gap |
| Nut-free | 8 | 0 | 9 | Breakfast/main protein buffer gap |

## Coverage Need

Builder supports 3, 4, and 5 meals/day. The slot profiles are:

| Meal count | Runtime slots/day |
|---:|---|
| 3 | breakfast, main, main |
| 4 | breakfast, main, snack, main |
| 5 | breakfast, main, snack, main, snack |

Demand by duration:

| Meal count | Weeks | Total positions | Breakfast | Snack | Main |
|---:|---:|---:|---:|---:|---:|
| 3 | 1 | 21 | 7 | 0 | 14 |
| 3 | 2 | 42 | 14 | 0 | 28 |
| 3 | 4 | 84 | 28 | 0 | 56 |
| 4 | 1 | 28 | 7 | 7 | 14 |
| 4 | 2 | 56 | 14 | 14 | 28 |
| 4 | 4 | 112 | 28 | 28 | 56 |
| 5 | 1 | 35 | 7 | 14 | 14 |
| 5 | 2 | 70 | 14 | 28 | 28 |
| 5 | 4 | 140 | 28 | 56 | 56 |

## No-Restriction Scenario Coverage

Strict SIMPLE native-slot coverage:

| Meal count | Weeks | Demand B/S/M | Buffer B/S/M | Deficit | Bottleneck |
|---:|---:|---|---|---:|---|
| 3 | 1 | 7 / 0 / 14 | 8.86 / n/a / 3.93 | 0 | none |
| 3 | 2 | 14 / 0 / 28 | 4.43 / n/a / 1.96 | 0 | none |
| 3 | 4 | 28 / 0 / 56 | 2.21 / n/a / 0.98 | 1 | main |
| 4 | 1 | 7 / 7 / 14 | 8.86 / 18.71 / 3.93 | 0 | none |
| 4 | 2 | 14 / 14 / 28 | 4.43 / 9.36 / 1.96 | 0 | none |
| 4 | 4 | 28 / 28 / 56 | 2.21 / 4.68 / 0.98 | 1 | main |
| 5 | 1 | 7 / 14 / 14 | 8.86 / 9.36 / 3.93 | 0 | none |
| 5 | 2 | 14 / 28 / 28 | 4.43 / 4.68 / 1.96 | 0 | none |
| 5 | 4 | 28 / 56 / 56 | 2.21 / 2.34 / 0.98 | 1 | main |

4-week `5 meals/day` effort scenarios:

| Pool | Native B/S/M | Native buffer B/S/M | Native deficit | Snack-as-main fallback | Effective main capacity | Effective deficit |
|---|---:|---|---:|---:|---:|---:|
| Strict SIMPLE | 62 / 131 / 55 | 2.21 / 2.34 / 0.98 | main 1 | 46 | 101 | 0 |
| INTERESTING expanded | 87 / 158 / 79 | 3.11 / 2.82 / 1.41 | 0 | 49 | 128 | 0 |
| Last-resort relaxed | 119 / 181 / 205 | 4.25 / 3.23 / 3.66 | 0 | 50 | 255 | 0 |

Important: the 101 SIMPLE effective main capacity assumes snack-as-main fallback remains acceptable. If product quality requires native main-only meals, the SIMPLE main pool needs additions even with no exclusions.

## Restriction Scenario Coverage

Four-week `5 meals/day` strict SIMPLE demand is 28 breakfasts, 56 snacks, and 56 mains.

| Restriction | Native B/S/M | Native hard deficit | Snack-as-main fallback | Effective main deficit | Bottleneck |
|---|---:|---|---:|---:|---|
| None | 62 / 131 / 55 | main 1 | 46 | 0 | none if fallback allowed |
| Egg-free | 30 / 102 / 43 | main 13 | 33 | 0 | native main; HP breakfast |
| Dairy-free | 16 / 29 / 28 | breakfast 12; snack 27; main 28 | 7 | 28 | breakfast, snack, main |
| Gluten/wheat-free | 41 / 91 / 21 | main 35 | 32 | 3 | main |
| Fish/seafood-free | 58 / 108 / 38 | main 18 | 34 | 0 | native main |
| Broccoli-free | 59 / 131 / 53 | main 3 | 46 | 0 | native main |
| Nut-free | 49 / 102 / 52 | main 4 | 45 | 0 | native main |

Interesting expanded coverage helps most cases:

| Restriction | INTERESTING B/S/M | Native hard deficit | Effective main deficit |
|---|---:|---|---:|
| None | 87 / 158 / 79 | 0 | 0 |
| Egg-free | 39 / 125 / 64 | 0 | 0 |
| Dairy-free | 24 / 39 / 44 | breakfast 4; snack 17; main 12 | 12 |
| Gluten/wheat-free | 58 / 109 / 31 | main 25 | 0 |
| Fish/seafood-free | 83 / 135 / 57 | 0 | 0 |
| Broccoli-free | 83 / 158 / 74 | 0 | 0 |
| Nut-free | 66 / 118 / 74 | 0 | 0 |

Last-resort effort relaxation removes almost every hard count deficit except dairy-free snacks:

| Restriction | Relaxed B/S/M | Hard deficit |
|---|---:|---|
| None | 119 / 181 / 205 | 0 |
| Egg-free | 48 / 143 / 170 | 0 |
| Dairy-free | 30 / 53 / 121 | snack 3 |
| Gluten/wheat-free | 72 / 114 / 84 | 0 |
| Fish/seafood-free | 114 / 158 / 157 | 0 |
| Broccoli-free | 115 / 181 / 188 | 0 |
| Nut-free | 89 / 132 / 186 | 0 |

## Recent Avoidance Feasibility

After week 1 in a 5-meal plan, the user-described usage is 7 breakfasts, 14 snacks, and 14 mains.

Theoretical strict SIMPLE non-recent availability, no restrictions:

| Slot | Week 1 used | Strict SIMPLE native total | Non-recent left | Week 2 demand | Feasible by count |
|---|---:|---:|---:|---:|---|
| Breakfast | 7 | 62 | 55 | 7 | yes |
| Snack | 14 | 131 | 117 | 14 | yes |
| Main, native only | 14 | 55 | 41 | 14 | yes |
| Main, effective with snack fallback | 14 | 101 | 87 | 14 | yes |

Four-week theoretical no-repeat feasibility, no restrictions:

| Slot model | Available | 4-week demand | Surplus/deficit |
|---|---:|---:|---:|
| Breakfast native SIMPLE | 62 | 28 | +34 |
| Snack native SIMPLE | 131 | 56 | +75 |
| Main native SIMPLE | 55 | 56 | -1 |
| Main effective SIMPLE with snack fallback | 101 | 56 | +45 |

So week 2 can be built without repeating week 1 by broad slot count. Four weeks can be built theoretically if snack-as-main fallback is allowed. Four weeks cannot be built with strict native SIMPLE main-only recipes: it lacks exactly 1 native main recipe before any quality buffer or restrictions.

This aligns with `docs/RECIPE_HISTORY_FALLBACK_DEBUG.md`: the hard recent failure is not explained by raw slot counts. It is caused by hard recent filtering plus same-week no-repeat, macro/protein scoring, greedy weekly construction, candidate limits, and fallback jumping from full recent to no recent.

## Recommended Additions

Definitions:

- Hard minimum: enough unique native recipes for 4 weeks of `5 meals/day`.
- Recommended buffer: 1.25x demand, rounded up, for subscription variety and search slack.
- HP means the audit high-protein proxy above, not a production hard filter.
- Effective main fallback can reduce hard deficits, but native mains are still preferable for product quality.

### No Restrictions

| Target | Simple breakfasts | Simple snacks | Simple mains |
|---|---:|---:|---:|
| Hard minimum, fallback allowed | 0 | 0 | 0 |
| Hard minimum, native main-only | 0 | 0 | 1 |
| 1.25x native buffer | 0 | 0 | 15 |
| 1.25x HP proxy buffer | 11 HP breakfasts | 0 | 20-25 HP mains |

### Common Restrictions

| Restriction | Hard minimum native additions | Recommended 1.25x native buffer additions | HP proxy gaps to prioritize |
|---|---|---|---|
| Egg-free | +13 mains; snacks 0; breakfasts 0 | +5 breakfasts; +27 mains; snacks 0 | +21 HP breakfasts; +18 HP mains |
| Dairy-free | +12 breakfasts; +27 snacks; +28 mains | +19 breakfasts; +41 snacks; +42 mains | +25 HP breakfasts; +42 HP snacks; +30 HP mains |
| Gluten/wheat-free | +35 native mains, or +3 if fallback is allowed | +49 native mains | +16 HP breakfasts; +37 HP mains |
| Fish/seafood-free | +18 native mains, or 0 if fallback is allowed | +32 native mains | +7 HP breakfasts; +23 HP mains |
| Broccoli-free | +3 native mains, or 0 if fallback is allowed | +17 native mains | +5 HP breakfasts; +8 HP mains |
| Nut-free | +4 native mains, or 0 if fallback is allowed | +18 native mains | +8 HP breakfasts; +9 HP mains |

Practical priority list:

1. Dairy-free SIMPLE snacks first: at least 27 hard-minimum additions, preferably about 41 for buffer. Make them high-protein where possible.
2. Dairy-free SIMPLE mains next: at least 28 hard-minimum additions, preferably about 42 for buffer.
3. Gluten/wheat-free SIMPLE mains: add at least 3 main-like/native recipes if fallback is accepted, but 35-49 native mains if the product wants real native-main coverage and buffer.
4. Egg-free high-protein breakfasts: add at least 21 to cover the 4-week HP proxy; prioritize dairy-free/gluten-free variants when possible so one recipe helps multiple restrictions.
5. Fish/seafood-free SIMPLE mains: add 18-32 native mains if native-main quality is required; fallback covers the hard count today.
6. Nut-free and broccoli-free SIMPLE mains: smaller native-main buffer gaps, useful after dairy/gluten/egg work.

## Conclusion

For unrestricted `MAINTAIN/simple/5`, the problem is mostly algorithmic once the current 505 curated recipes are considered. Broad slot counts support week 2 with full recent avoidance, and 4 weeks are feasible if snack-as-main fallback is allowed. The observed fallback to `no_recent` should be handled with algorithm changes: soft recent penalties, slot-aware recent avoidance, least-recent repeats, more candidate search, and controlled effort fallback before dropping all history pressure.

For strict native SIMPLE 4-week variety, there is still a small main shortage and no meaningful main buffer. Add at least 1 native simple main to hit the hard 56-main count, or about 15 native simple mains to reach a 1.25x buffer.

For common restrictions, there are real recipe shortages. Dairy-free is the clear bottleneck across breakfast, snack, and main. Gluten/wheat-free, fish/seafood-free, nut-free, broccoli-free, and egg-free mostly become native-main or high-protein-breakfast problems. Reliable 4-week subscription variety needs targeted additions, not just more recipes in aggregate.
