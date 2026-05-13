# Recipe Coverage Funnel Audit

Date: 2026-05-14

Scope: docs/debug audit only. No production code, optimizer code, recipe data, photos, PDF, payments, or Telegram UX paths were changed.

## Question

`docs/RECIPE_COVERAGE_AUDIT.md` reported that the SIMPLE weekly no-repeat main pool is only 14-15 recipes. This follow-up checks whether that number is a real pool constraint or a counting/filtering artifact.

## Method

The funnel uses the same runtime objects and filters as the production weekly path:

- `built_in_recipes()` filtered to recipes tagged `curated`;
- `curated_data.curated_recipes()` as the curated source loader;
- `_recipe_memory_key` for recipe-key coverage;
- `_cooking_effort_constraints(CookingTimePreference.SIMPLE)`;
- `_cooking_effort_constraints(CookingTimePreference.INTERESTING)`;
- `_recipe_matches_cooking_effort`;
- `_has_complex_cooking_technique`;
- `_resolve_recipe_ingredients`;
- `evaluate_safety` and `filter_foods` for the no-exclusion baseline.

Protein suitability is the same audit proxy as the previous document: normal MAINTAIN/simple profile, male, 32, 178 cm, 86 kg, moderate activity, 5 meals. Targets are 2817 kcal and 95 g protein/day. The 95% protein floor is 90.25 g/day, so the 5-meal lunch main proxy is 27.07 g protein and the dinner main proxy is 22.56 g protein.

Important: the production builder does not have a hard per-recipe protein filter. It validates and scores a full day. The `SIMPLE + protein` number is an audit proxy for weekly no-repeat robustness, not a literal pre-rank production filter.

## Top-Level Funnel

| Stage | Count | % of base | Top exclusion reasons |
|---|---:|---:|---|
| Source curated recipe rows | 400 | 100.0% | none |
| Runtime curated templates from `curated_data()` | 400 | 100.0% | none |
| Valid `recipe_id` and runtime memory key | 400 | 100.0% | none |
| `built_in_recipes()` curated after catalog dedupe | 400 | 100.0% | none |
| SIMPLE-compatible strict effort | 151 | 37.8% | active time >30 min: 158; ingredients >11: 36; complex keyword: 32; instruction sentences >6: 23 |
| INTERESTING-compatible expanded effort | 222 | 55.5% | active time >45 min: 92; ingredients >12: 65; instruction sentences >7: 21 |

ID/key coverage is clean: no blank IDs, no blank memory keys, no duplicate recipe IDs, no duplicate memory keys, and no catalog-dedupe loss from duplicate ID/title/signature in the curated runtime pool.

## Slot Breakdown

| Slot/type | Count | % of curated | Notes |
|---|---:|---:|---|
| breakfast | 97 | 24.2% | Breakfast-only pool |
| snack | 150 | 37.5% | Snack-only pool |
| main/lunch/dinner | 153 | 38.2% | Lunch and dinner both draw from `slot="main"` |
| unknown | 0 | 0.0% | No unknown slots |

There is no separate `lunch` or `dinner` slot in the curated data. Both weekly lunch and dinner compete for the same 153 `main` recipes.

## Main Funnel

| Main-stage | Count | % of main | Top exclusion reasons |
|---|---:|---:|---|
| Main slot before protein filters | 153 | 100.0% | not applicable |
| Protein-suitable before SIMPLE, lunch ratio | 96 | 62.7% | below lunch protein proxy: 57 |
| Protein-suitable before SIMPLE, dinner ratio | 108 | 70.6% | below dinner protein proxy: 45 |
| After SIMPLE effort/equipment filter | 16 | 10.5% | active time >30 min: 104; ingredients >11: 23; instruction sentences >6: 9; complex keyword: 1 |
| After SIMPLE + lunch protein proxy | 14 | 9.2% | active time >30 min: 104; ingredients >11: 23; instruction sentences >6: 9; below lunch protein proxy: 2; complex keyword: 1 |
| After SIMPLE + dinner protein proxy | 15 | 9.8% | active time >30 min: 104; ingredients >11: 23; instruction sentences >6: 9; below dinner protein proxy: 1; complex keyword: 1 |
| After builder pre-rank eligibility filters | 16 | 10.5% | not quick/medium time bucket: 104; ingredients >11: 23; instruction sentences >6: 9; complex keyword: 1 |

The key shape is: protein is not the first-order bottleneck. Before SIMPLE effort filters, 96 lunch-ratio and 108 dinner-ratio main recipes are protein-suitable. The pool collapses from 153 to 16 at the SIMPLE effort/equipment stage, before the protein proxy is applied.

The two SIMPLE main recipes below the lunch protein proxy are:

- `r089_yaichnaya_skovoroda_s_lavashom_i_avokado`: 27.0 g projected lunch protein vs 27.07 g threshold, so this is effectively a borderline/rounding proxy miss; it passes the dinner proxy.
- `r176_nokki_kacho_e_pepe`: 17.6 g projected lunch/dinner protein, a real low-protein main.

## Why Main Recipes Miss The SIMPLE Weekly Pool

For the 153 actual `slot="main"` recipes, using the lunch proxy as the stricter main slot:

| Reason bucket | Count | Notes |
|---|---:|---|
| SIMPLE metadata limits too strict | 136 | Primary blockers: active time, ingredient count, or instruction sentence count |
| Protein/macro proxy too strict | 2 | One is a 0.1 g borderline miss |
| Special-equipment/complex keyword primary blocker | 1 | `r133`, caused by a substring false positive |
| Missing/incorrect meal slot within `main` records | 0 | Main records are actually `slot="main"` |
| Missing `recipe_id`/key | 0 | Clean |
| Duplicate by ID/key/title/signature | 0 | Clean |
| Baseline title/ingredient exclusion false positive | 0 | No user exclusions in this baseline |
| Other | 0 | None observed |

Slot taxonomy is still a real adjacent issue. A heuristic scan found 50 snack recipes that look like meal-sized savory mains by ID/ingredients; 39 are SIMPLE-compatible, 34 pass the lunch protein proxy, and 34 pass both. They are invisible to the main builder because they are `slot="snack"`.

## Cooking Effort Semantics

The previous audit did not treat INTERESTING as "only complex". Runtime semantics are:

- SIMPLE strict pool: 151 curated recipes.
- INTERESTING expanded pool: 222 curated recipes.
- SIMPLE is a strict subset of INTERESTING: 0 SIMPLE recipes are excluded from INTERESTING.

So the intended relationship is `interesting = simple + expanded`, not `interesting = complex-only`.

## Equipment And Technique Checks

Production SIMPLE complexity has two layers:

- hard metadata limits: active minutes, ingredient count, instruction sentence count;
- keyword cut via `_has_complex_cooking_technique`.

Any complex keyword appears in 84 curated recipes and 34 main recipes, but because the production check evaluates time, ingredient count, and sentence count first, complex keyword is the primary blocker for only 32 curated recipes and only 1 main recipe.

Top production keyword matches:

| Keyword | Curated matches | Main matches | Notes |
|---|---:|---:|---|
| `блендер` | 34 | 11 | All fail SIMPLE if not already cut earlier |
| `гриль` | 15 | 11 | All fail SIMPLE if not already cut earlier |
| `ноч` | 13 | 5 | Includes true overnight recipes and false positives in `чесноч...` |
| `охлажд` | 10 | 4 | Mostly real cooling/resting cases |
| `марин` | 9 | 6 | Mostly real marinating, but also ingredient names like marinara/rosemary-adjacent text should be watched |
| `комбайн` | 8 | 1 | Food processor |
| `выпек` | 3 | 0 | Only in title/time text; Russian baking in instructions is not a blanket keyword cut |
| `ваф` | 1 | 0 | Waffle iron |

Specific equipment/tech semantics check:

| Term family | Curated mentions | Main mentions | SIMPLE pass | Production complex keyword match |
|---|---:|---:|---:|---:|
| blender | 34 | 11 | 0 | 34 |
| waffle | 1 | 0 | 0 | 1 |
| grill | 15 | 11 | 0 | 15 |
| food processor | 8 | 1 | 0 | 8 |
| oven/roast/bake text | 126 | 65 | 15 | 28 |
| pan/skillet | 129 | 72 | 29 | 31 |
| pot/saucepan | 63 | 49 | 5 | 15 |

The simple mode is not directly treating ordinary pan/skillet or pot/saucepan as special equipment. Those words are not complexity keywords. Many pan/pot recipes still fail because they are >30 minutes, have >11 ingredients, have >6 instruction sentences, or contain another keyword.

Oven/baking is only partially and inconsistently represented as a special technique. Russian `духовка`/`запеч...` is not a blanket complexity keyword. Some oven recipes pass SIMPLE, while many oven-looking recipes fail because of time or ingredient count.

There is one important false positive: `ноч` catches the substring inside `чесноч...`. The only main recipe where complex keyword is the primary blocker is:

- `r133_limonnyy_zapechennyy_losos_s_chesnochno_ukropnym_souso` / "Лимонный запеченный лосось с чесночно-укропным соусом": 20 minutes, 8 ingredients, 5 instruction sentences, projected lunch protein 45.3 g. It is cut by the `ноч` substring in `чесночно`. Fixing that would raise the SIMPLE main pool from 16 to 17 and the lunch proxy pool from 14 to 15, but it would not create a healthy weekly buffer by itself.

## Examples Of Ordinary-Looking Main Dishes That Were Excluded

Protein values are projected at the 5-meal lunch/dinner main ratios. `Complex keywords` means production `_has_complex_cooking_technique` keyword matches, not a human judgment of the recipe.

| Recipe | Slot | Tags | Time / metadata | Complex keywords | Protein info | Exclusion reason |
|---|---|---|---|---|---|---|
| Чесночные креветки со шпинатом в одной сковороде | main | source:EatingWell | 25 min, 8 ingredients, 7 sentences | `ноч` false positive in `чесночные` | lunch 19.4 g; dinner 19.4 g | instruction sentences >6; also below protein proxy |
| Куриные фахитас с перцем и сальсой | main | source:BBC Good Food | 25 min, 16 ingredients, 8 sentences | `гриль` | lunch 40.0 g; dinner 37.8 g | ingredients >11 |
| Быстро обжаренная говядина с брокколи и морковью | main | source:EatingWell | 30 min, 13 ingredients, 10 sentences | none | lunch 50.9 g; dinner 45.8 g | ingredients >11 |
| Курица кунг пао с овощами и арахисом | main | source:Food Network | 25 min, 13 ingredients, 28 sentences | none | lunch 42.9 g; dinner 42.9 g | ingredients >11 |
| Куриный суп с белой фасолью и шпинатом | main | source:Minimalist Baker | 30 min, 9 ingredients, 8 sentences | none | lunch 21.4 g; dinner 21.4 g | instruction sentences >6; also below protein proxy |
| Курица с картофелем и греческим йогуртом | main | source:BBC Good Food | 2 hours, 9 ingredients, 4 sentences | none | lunch 50.3 g; dinner 49.3 g | active time >30 min |
| Свинина с лаймом, фарро и шпинатом | main | source:EatingWell | 25 min, 11 ingredients, 10 sentences | none | lunch 57.4 g; dinner 51.2 g | instruction sentences >6 |
| Дал из красной чечевицы со шпинатом и бататом | main | source:BBC Good Food | 45 min, 15 ingredients, 8 sentences | none | lunch 10.8 g; dinner 10.8 g | active time >30 min; low protein proxy |
| Домашний вегетарианский чили с черной и пинто фасолью | main | source:Cookie and Kate | 1 hour, 19 ingredients, 11 sentences | `блендер` | lunch 28.2 g; dinner 27.2 g | active time >30 min |
| Боул с киноа, нутом, бататом и тахини | main | source:EatingWell | 30 min, 12 ingredients, 9 sentences | none | lunch 24.2 g; dinner 21.2 g | ingredients >11; low-ish protein |
| Веганская джамбалайя с рисом и белой фасолью | main | source:BBC Good Food | 45 min, 14 ingredients, 9 sentences | none | lunch 22.4 g; dinner 20.5 g | active time >30 min; low protein proxy |
| Греческий боул с курицей, кускусом и дзадзики | main | source:Allrecipes | 55 min, 26 ingredients, 16 sentences | none | lunch 51.8 g; dinner 45.5 g | active time >30 min |
| Средиземноморский боул с курицей, киноа и соусом из печеного перца | main | source:EatingWell | 30 min, 16 ingredients, 12 sentences | `гриль` | lunch 44.4 g; dinner 41.6 g | ingredients >11 |
| Куриный салат шаурма с тахини-йогуртовой заправкой | main | source:BBC Good Food | 40 min + marinating, 20 ingredients, 13 sentences | `марин`, `гриль` | lunch 53.2 g; dinner 50.1 g | active time >30 min |
| Тако-салат с курицей, шпинатом, фасолью и авокадо-ранч | main | source:EatingWell | 25 min, 14 ingredients, 4 sentences | `блендер`, `комбайн` | lunch 25.1 g; dinner 25.1 g | ingredients >11 |
| Лаваш-ролл с курицей и овощами | snack | source:BBC Good Food | 10 min, 8 ingredients, 3 sentences | none | lunch 42.7 g; dinner 41.6 g | `slot="snack"`, so main builder never sees it |
| Пита с хумусом и курицей | snack | source:BBC Good Food | 10 min, 7 ingredients, 2 sentences | none | lunch 38.3 g; dinner 37.5 g | `slot="snack"`, so main builder never sees it |
| Пита с тунцом, кукурузой и йогуртом | snack | source:BBC Good Food | 10 min, 8 ingredients, 2 sentences | none | lunch 47.0 g; dinner 46.8 g | `slot="snack"`, so main builder never sees it |
| Боул с курицей, фасолью и авокадо | snack | source:EatingWell | 10 min, 9 ingredients, 2 sentences | none | lunch 44.0 g; dinner 44.0 g | `slot="snack"`, so main builder never sees it |
| Куриный ролл с томатом и йогуртом | snack | source:Tesco Real Food | 10 min, 8 ingredients, 3 sentences | none | lunch 47.5 g; dinner 47.3 g | `slot="snack"`, so main builder never sees it |

## Sanity Check Against Actual Builder Selection

A short production-builder sample over 50 seeds, no exclusions, 5 meals, `recipe_source="curated_only"`, produced complete days for all 50 seeds and selected 14 unique main recipe IDs. This is not the same as the static eligibility pool, but it confirms that ranking/seed behavior concentrates choices around a very narrow main set even when the pre-rank SIMPLE main pool has 16 recipes.

## Conclusion

The 14-15 figure is arithmetically real for the previous audit's `SIMPLE + per-slot protein proxy` definition. It is not caused by missing IDs, missing keys, duplicate recipe keys, catalog dedupe, or treating INTERESTING as complex-only.

However, it should be described as a strict audit proxy, not as a literal production hard filter. The production pre-rank builder eligibility pool is 16 SIMPLE main recipes; the 14/15 number appears after applying the audit's per-recipe protein proxy. The actual first-order bottleneck is the SIMPLE effort/metadata filter: 153 main recipes become 16 before protein is even considered.

Recommended order:

1. Fix/clarify filter and metadata semantics before adding a large data slice.
2. Patch the `ноч` false positive so garlic/`чесноч...` does not look like overnight prep.
3. Revisit whether >30 minutes, >11 ingredients, and >6 instruction sentences are too strict for "simple weekly main", especially for bowls, soups, one-pan meals, and straightforward salads.
4. Review snack/main slot taxonomy or support dual-slot recipes. There are 34 snack recipes that look like SIMPLE high-protein mains under a conservative heuristic.
5. Re-run the funnel. If the main pool is still below a comfortable 21+ robust recipes after filter/slot cleanup, then add targeted robust SIMPLE mains.

So the answer is mixed: the 14-15 count was not a math/counting bug, but it is also not proof that the catalog truly lacks simple main dishes. First fix marking/filter semantics and slot eligibility; then decide the exact recipe additions.
