# Recipe Fixes Round 2

Scope: high-suspicion / Top 25 / Recommended Fix Batch recipes from `recipe-content-review-pack-round2`, plus user-reported peanut-butter and hummus consistency examples in that pack.

No PDF, Telegram/privacy/questionnaire, payment, runtime, storage, deploy, bot process, commit, tag, PR, archive, `New project 2 CLEAN`, or recovered-bot work was done.

## Processed Recipe IDs

`r015`, `r034`, `r061`, `r062`, `r063`, `r093`, `r115`, `r171`, `r209`, `r225`, `r280`, `r308`, `r357`, `r452`, `r474`, `r480`, `r491`, `r498`, `r515`, `r538`, `r540`, `r577`, `r595`, `r598`, `r607`, `r631`.

## Fix Log

| Recipe | Before problem | Fix applied | Nutrition changed |
|---|---|---|---|
| `r015` | Tiny peanut/other nut paste lacked a user-friendly measure; steps used inflected wording that was easy to miss. | Kept 5 g as a scaled single-serving amount, added approx `1 ч. л.`, clarified milk/nut-paste/honey use. | No |
| `r034` | Four-topping pancake had tiny peanut butter and step/ingredient wording drift. | Kept tiny topping amount as intentional scaled topping, clarified flour, peanut paste, berries, syrup steps. | No |
| `r061` | Tiny seed topping and ingredient wording drift. | Added approx measure for seed mix and clarified apple puree, honey, flour, topping use. | No |
| `r062` | Tiny nut paste/pecan amounts and weak final instruction. | Kept scaled nut-paste amount, added approx measures, clarified flour/topping split, added cooling finish. | No |
| `r063` | Tiny pecan and gram-only dates; flour wording drift. | Added approx measures for dates/pecan and clarified spelt flour use. | No |
| `r093` | Steps triggered false soy-sauce missing warning from soy-yogurt wording; tomato paste/broth/oregano needed clearer use. | Aligned yogurt to existing `greek_yogurt`, clarified tomato paste, broth, oregano, tofu, garlic-yogurt steps. | No |
| `r115` | Title duplicated `соусе` and said red beans while ingredients/steps used black bean sauce. | Renamed to black-bean sauce with egg noodles; clarified black bean sauce, noodles, stir-fry vegetables, sesame, mint. | No |
| `r171` | Pork in title was not supported by ingredient wording because `сбульонй фарш` was corrupted; broth wording was broken. | Corrected ingredient/step wording to `свиной фарш` and `говяжий бульон`; kept existing generic meat nutrition. | No |
| `r209` | String beans were mapped as red beans; spicy sauce lacked approx measure. | Added `green_beans` catalog row, remapped string beans, clarified gado-gado bowl steps, added measures for peanut/chili sauce. | Yes |
| `r225` | Casserole stopped mid-recipe; panko was mapped as cottage cheese. | Rewrote full sauce/assembly/bake steps; remapped panko to breadcrumbs and added parmesan measure. | Yes |
| `r280` | Baba ganoush steps mentioned tahini absent from ingredients and used 80 ml oil instead of listed 16 ml. | Replaced tahini step with Greek yogurt, corrected oil amount, added garlic measure, preserved ingredient list. | No |
| `r308` | Gluten-free muffin used `wheat_flour` mapping for buckwheat flour; small nut measures missing. | Remapped buckwheat flour to `buckwheat`, added nut measures, clarified GF dry mix. | Yes |
| `r357` | Lettuce quantity was nonsensical (`4,5` leaves as 1350 g); 75 g Thai pepper was not CIS-friendly. | Corrected romaine to 135 g and changed 75 g hot/Thai pepper to sweet red pepper; clarified salad-cup steps. | Yes |
| `r452` | Pasta was mapped as poppy seed; steps ended before vegetables/garlic/greens were used. | Remapped pasta to `pasta_generic`, completed skillet steps using all vegetables and garnish. | Yes |
| `r474` | Chicken cutlet steps omitted most ingredients and ended weakly. | Rewrote steps to combine chicken mince, zucchini, carrot, egg, onion, garlic, mustard, salt; added serving finish. | No |
| `r480` | Thai-style meat steps omitted broccoli/ginger and ended at boiling noodles. | Rewrote steps to cook udon, stir-fry pork/veg/ginger, sauce, combine, garnish. | No |
| `r491` | Zrazy steps were incomplete; rice flour and oil were mapped poorly. | Rewrote full potato dough/filling/shaping/frying flow; remapped rice flour and vegetable oil. | Yes |
| `r498` | Tuna pasta steps started mid-boil and ended without serving; passata/tomato/vinegar use was unclear. | Rewrote pasta and sauce flow, clarified tuna, cream cheese, vinegar, passata, serving finish. | No |
| `r515` | Salad steps used generic `овощи` and did not name title ingredients. | Clarified cucumber, tomato, pepper, feta, lemon juice, greens, serving. | No |
| `r538` | Lazy cabbage rolls omitted onion/carrot/tomato paste in steps and ended weakly. | Rewrote saute, mix, sauce, simmer, serve flow; added tomato paste measure. | No |
| `r540` | Title said hake while ingredient row was pollock; steps used generic fish/vegetables. | Renamed to baked pollock with vegetables; clarified pollock, carrot, onion, tomatoes, pepper, lemon. | No |
| `r577` | Oat balls had generic “all ingredients” step and weak finish. | Rewrote with oats, peanut paste, honey, cocoa, seeds, chilling, serving. | No |
| `r595` | Steps offered optional mayonnaise absent from ingredients and did not name vegetables. | Removed mayonnaise option; clarified hummus, cucumber, lettuce, carrot, pink salmon, rolling. | No |
| `r598` | Tiny peanut paste was intentional but wording was easy to miss. | Kept `1 ч. л.` and clarified peanut paste dissolves into oatmeal. | No |
| `r607` | `разрыхлитель — 0 ч. л.` was nonsensical. | Set baking powder to `0,5 ч. л. (около 2 г)`, clarified dough steps, added cheese measure. | Yes |
| `r631` | Vinegar looked tiny without a measure; milk/flour wording drift. | Added approx vinegar measure for soda activation and clarified milk/flour in batter. | No |

## Hummus Consistency Review

Reviewed title-hummus cases from the pack/current data: `r262`, `r271`, `r272`, `r273`, `r274`, `r276`, `r356`, `r359`, `r489`, `r580`, `r604`, `r640`, `r658`. Each has ready hummus or clear hummus-making support from chickpeas/beans plus blending steps. No recipe edit was needed for these support-yes cases.

Related non-title case `r595` was fixed by removing absent mayonnaise and requiring the listed hummus.

## Intentionally Left Unchanged

- Hummus title support cases listed above: left unchanged because the support was already present.
- Peanut-butter tiny amounts in `r015`, `r034`, `r062`, and `r598`: quantities were kept because they are scaled single-serving/topping amounts with clear measures after this pass.

## Needs User Decision

None for this batch.

## Audit Result After Fixes

`python scripts/dev/recipe_content_audit.py`

- `recipes_checked=665`
- `ingredients_checked=6130`
- `foods_checked=359`
- `nutrition_rows_checked=665`
- `blocking_findings=0`
- `warning_findings=1494`
- `title_ingredient_mismatch.warnings=0`
- `steps_mention_missing_ingredient.warnings=0`
- `non_cis_unclear_ingredients.warnings=0`
- `tiny_gram_anomalies.warnings=0`
- Remaining warnings are broad heuristic warnings, mostly ingredient-step morphology/wording and approximate-measure backlog.

## Verification

- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q` -> `92 passed`
- `git diff --check` -> exit code `0`; Git printed only existing CRLF checkout warnings.
