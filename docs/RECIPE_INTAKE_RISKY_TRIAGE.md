# Recipe Intake Risky Triage

Date: 2026-05-14

Scope: docs-only triage for the 34 recipes marked risky in `docs/RECIPE_INTAKE_IMPORT_PREVIEW.md`, cross-checked against `tmp/recipe_intake/cleaned_recipes.xlsx` and the dry-run analysis artifact under `tmp/recipe_intake/`. No production curated recipe, nutrition, photo, builder, PDF, Telegram, promo, payments, storage, or workbook data is changed by this report.

## Summary

- Import preview has 105 structurally ready recipes: 68 full-mapped, 3 near-full, and 34 risky for КБЖУ.
- The 34 risky recipes split into 26 recipes with unmapped ingredients and 8 recipes that are fully mapped but still risky because of prepared product or sauce policy.
- The risky set contains 30 unmapped ingredient rows and 24 unique unmapped ingredient names.
- 14 recipes have an unmapped protein anchor. These are the highest КБЖУ risk because the main protein, fat, and calories can be missing from preview totals.
- 17 recipes have semi-prepared or sauce risk. In several of them the nutrition row already exists, but import policy still needs an explicit decision.
- There are no duplicate recipe keys or exact/normalized title duplicates in the preview. The risk is nutrition-policy and mapping confidence, not catalog duplication.

Current "importable" count is 71 if counted as `full + near_full`. The previous low-risk production recommendation was 65 because it excluded protein-anchor warnings. To move from 71 toward 105, the practical path is: add exact nutrition mappings for simple missing foods, then approve or decompose prepared sauces/products, then make a small set of substitution and low-protein-main decisions.

## 34 Recipe Table

| recipe_key | Title | Unmapped or risky ingredients | Why risky for КБЖУ | Issue type(s) | Recommended action |
| --- | --- | --- | --- | --- | --- |
| `intake_016` | Цельнозерновой хлеб с печенью трески | `печень трески консервированная` | Protein anchor is unmapped; preview misses cod liver protein, fat, and calories. Recipe was reconstructed from title, so confidence is lower. | missing nutrition mapping; prepared product; unit/grams problem | Add exact mapping/new food for canned cod liver, preferably drained-with-oil policy stated. Keep as anchor; mark low-confidence until source nutrition is accepted. |
| `intake_019` | Салат с тунцом, яйцом, фасолью и овощами | `соевый соус` as sauce-policy trigger | All ingredients mapped, but sauce terms force a semi-prepared policy decision. Macro impact is small; sodium can vary. | prepared product | Keep existing soy-sauce mapping if standard condiments are allowed; mark low-confidence for sodium rather than blocking import. |
| `intake_021` | Гречка с запеченной индейкой и свекольным салатом | `гречка сухая` | Dry buckwheat is unmapped, so carb and calorie totals are understated. Protein anchor `филе индейки` is mapped. | missing nutrition mapping | Add dry buckwheat food/mapping. This should become importable after mapping. |
| `intake_024` | Салат из печени трески с яйцом | `печень трески` | Cod liver is an unmapped anchor; preview misses the dominant fat/calorie component. | missing nutrition mapping; prepared product | Add cod liver mapping; keep ingredient as anchor. |
| `intake_025` | Салат из печени трески с огурцом и картофелем | `печень трески` | Same cod-liver anchor gap; macros are materially low without it. | missing nutrition mapping; prepared product | Add cod liver mapping; import after mapping and portion sanity check. |
| `intake_026` | Салат из печени трески с луком | `печень трески`; `майонез` | Cod liver anchor is unmapped; mayo is a prepared sauce with variable fat density. | missing nutrition mapping; prepared product | Add cod liver mapping. Then either keep mapped mayo as low-confidence or replace/decompose dressing. |
| `intake_027` | Салат из консервированной печени трески | `печень трески`; `майонез` | Cod liver anchor is unmapped; mayo adds prepared-product variance. Rice amount is tiny but unusual. | missing nutrition mapping; prepared product; unit/grams problem | Add cod liver mapping. Approve mayo policy or replace with yogurt/sour cream before import. |
| `intake_028` | Домашний салат из печени трески с зеленым горошком | `печень трески`; `майонез` | Cod liver anchor missing; mayo sauce decision affects fat/kcal. | missing nutrition mapping; prepared product | Add cod liver mapping. Keep mayo with low-confidence or replace/decompose. |
| `intake_029` | Белковый салат с курицей | `виноград` | Fresh grape is unmapped; fruit carbs/calories are missing. Important correction: must not substring-map to alcohol. | missing nutrition mapping; ambiguous ingredient | Add exact fresh grape mapping. Do not map to wine; do not replace with raisins unless user requests. |
| `intake_032` | Салат с помидорами «Красное море» | `крабовые палочки`; `майонез или йогурт` | Fully mapped, but processed surimi and ambiguous dressing choice can change fat/protein. | prepared product; ambiguous ingredient | Choose one dressing (`майонез` or `йогурт`) for production. Keep crab sticks with low-confidence, or defer if processed products are out of scope. |
| `intake_048` | Цельнозерновой хлеб с паштетом из куриной печени | `куриная печень` | Chicken liver is the anchor and unmapped. Recipe was reworked from a batch pate, so gram scaling should be treated carefully. | missing nutrition mapping; unit/grams problem; low confidence substitution | Add chicken liver mapping. Keep batch-derived grams but mark low-confidence until final portion review. |
| `intake_049` | Гречка по-купечески с фаршем | `гречка сухая` | Dry buckwheat unmapped; carb/calorie part of the main dish is missing. Meat anchor is mapped. | missing nutrition mapping | Add dry buckwheat mapping. |
| `intake_053` | Стручковая фасоль с чесноком и соевым соусом | `яйцо или тофу`; `соевый соус` | All mapped, but the anchor is ambiguous: egg vs tofu changes protein, fat, allergens, and vegan status. Soy sauce is a sauce-policy trigger. | ambiguous ingredient; prepared product | Replace `яйцо или тофу` with one production ingredient. Keep soy sauce as standard condiment if allowed; otherwise defer. |
| `intake_054` | Гуляш из куриной печени | `куриная печень` | Main protein anchor is unmapped, so protein, fat, and calories are materially wrong. | missing nutrition mapping | Add chicken liver mapping and keep as anchor. |
| `intake_063` | Салат с капустой, куриной грудкой и кунжутом | `соевый соус` | Fully mapped; flagged only by sauce term. Macro effect is tiny, sodium varies. | prepared product | Keep with low-confidence condiment policy. This is a quick accept if sauces like soy sauce are allowed. |
| `intake_070` | Тофу-нори в кляре | `соевый соус`; frying oil/batter | Fully mapped, but soy sauce triggers sauce policy and frying oil absorption is approximate. | prepared product; unit/grams problem | Keep soy sauce and current oil grams as low-confidence, or defer if fried/batter recipes need stricter handling. |
| `intake_071` | Гороховый суп-пюре | `горох колотый` | Split peas are the protein/carb anchor and unmapped; preview macros miss the base of the soup. | missing nutrition mapping | Add dry split pea mapping. |
| `intake_072` | Тофу-стейки в терияки | `соус терияки` | Fully mapped, but teriyaki sugar/sodium varies strongly by product. | prepared product | Keep existing teriyaki mapping with low-confidence, or decompose to soy sauce + sugar/seasonings if strict. |
| `intake_077` | Стейк из форели с молодым картофелем | `стейк из радужной форели`; `соус песто` | Trout anchor is unmapped; pesto is a prepared sauce. Missing fish dominates protein/fat error. | missing nutrition mapping; prepared product | Add trout mapping. Keep pesto low-confidence or decompose; then import. |
| `intake_080` | Мясо по-тайски с лапшой | `лапша удон для быстрого приготовления`; soy/sauce stack | Udon is unmapped, so carbs/calories are low. "Instant" wording makes product nutrition variable. | missing nutrition mapping; prepared product | Prefer replacing with generic dry udon mapping or add exact udon food. Avoid product-specific instant mapping unless nutrition source is accepted. |
| `intake_081` | Дорадо с рисом и яйцом пашот | `рис басмати` | Rice is unmapped; carb/calorie total is understated. Protein anchors are mapped. | missing nutrition mapping | Add alias to existing `rice` or create `basmati_rice`. |
| `intake_084` | Курица с овощами по-деревенски | `тыква кубиками «Айс»`; frozen-mix normalization | Branded/frozen pumpkin cubes are unmapped; previous vegetable normalization is a low-confidence substitution. | missing nutrition mapping; prepared product; low confidence substitution | Replace with generic pumpkin cubes/raw pumpkin mapping. Confirm or defer the normalized frozen vegetable replacement. |
| `intake_085` | Гуляш по-венгерски лёгкий | `консервированные томаты` | Canned tomato calories/carbs are missing; impact is moderate but easy to fix. | missing nutrition mapping | Map to canned tomatoes/passata/tomato puree according to texture policy. |
| `intake_086` | Эскалоп свиной с сыром | `свиные отбивные`; `приправа для овощей или универсальная` | Pork chop anchor is unmapped, so main protein/fat is missing. Seasoning has no grams and low macro impact. | missing nutrition mapping; unit/grams problem | Add plural alias `свиные отбивные` to `pork_chop`; map seasoning to `mixed_spices` or treat as 0g seasoning. |
| `intake_089` | Рулет из лаваша с хумусом | `вяленые томаты`; missing main anchor | Sun-dried tomatoes are unmapped, but bigger issue is that this main-slot recipe has no marked protein anchor. | missing nutrition mapping; ambiguous ingredient | Add sun-dried tomato mapping. Decide whether hummus is a plant-protein anchor, whether to re-slot as snack, or whether to keep as low-protein main. |
| `intake_093` | Шаурма с фалафелем | `фалафель замороженный`; `морковь по-корейски`; `соус «Классический майонезный соевый»`; frying oil | Plant protein anchor is an unmapped frozen product; sauce and frying oil make macros highly product-dependent. | missing nutrition mapping; prepared product; unit/grams problem | Decompose falafel and sauce, or add exact prepared-product foods and mark low-confidence. Best to defer unless prepared products are approved. |
| `intake_095` | Салат с шампиньонами и спаржей | `виноград кишмиш`; pak-choi/asparagus substitutions | Kishmish grape carbs are missing. Existing replacement of pak-choi/asparagus is low-confidence. | missing nutrition mapping; low confidence substitution | Add fresh grape/kishmish mapping. Ask user to approve replacements or defer. |
| `intake_096` | Карбонара с беконом и сливками | `яичные желтки` | Egg yolk anchor is unmapped even though a singular `egg_yolk` food exists; fat/kcal are understated. | missing nutrition mapping | Add plural alias `яичные желтки` to `egg_yolk`. |
| `intake_098` | Паста с консервированным тунцом и томатами | `томаты черри`; `протертые томаты` | Tomato components are unmapped; carbs/calories are understated, though tuna anchor is mapped. | missing nutrition mapping | Map cherry tomatoes to tomato and pureed tomatoes to passata/tomato puree. |
| `intake_099` | Паста с креветками и соусом песто | `песто` | Fully mapped, but pesto is 60g and dominates fat/calorie variability. | prepared product | Keep existing pesto mapping with low-confidence, or decompose if strict. |
| `intake_100` | Паста болоньезе | `томатный соус` | Prepared tomato sauce is unmapped and variable in sugar/oil/sodium. | missing nutrition mapping; prepared product | Map to marinara/passata if generic sauce is acceptable, or decompose to tomato puree + oil/spices. |
| `intake_101` | Паста с куриными колбасками в остром томатном соусе | `куриная колбаска`; `томатный соус аррабиата` | Protein anchor is an unmapped processed meat; sauce is also unmapped and product-dependent. | missing nutrition mapping; prepared product | Prefer replacing chicken sausage with a mapped lean protein, or add chicken-sausage food. Decompose/map arrabbiata. Defer if processed meats are not allowed. |
| `intake_104` | Макароны по-флотски | `резаные томаты`; `хмели-сунели` | Chopped tomatoes are unmapped; spice is tiny but unmapped. Anchors are mapped. | missing nutrition mapping | Map chopped tomatoes to canned tomatoes/passata policy. Map `хмели-сунели` to mixed spices or 0g seasoning. |
| `intake_105` | Пюре из зеленого горошка с креветками | `соус терияки`; edamame/scallop substitutions | Fully mapped, but teriyaki is a prepared sauce. The bigger confidence issue is user-visible substitution: edamame to peas and scallops to shrimp. | prepared product; low confidence substitution | Keep teriyaki low-confidence if sauce policy allows. Ask user to approve substitutions before production import. |

## Top Missing Mappings And Policy Unlocks

| Mapping or policy cluster | Recipes affected | Unlock impact | Recommended treatment |
| --- | ---: | --- | --- |
| Cod liver: `печень трески`, `печень трески консервированная` | 6 | Highest frequency and often the protein/fat anchor. Unlocks `intake_016`, `intake_024`-`intake_028`, subject to mayo policy for three of them. | Add `cod_liver_canned` or equivalent exact nutrition row and aliases. Decide drained vs with oil. |
| Tomato variants: `консервированные томаты`, `томаты черри`, `протертые томаты`, `томатный соус`, `томатный соус аррабиата`, `резаные томаты`, `вяленые томаты` | 6 | Converts multiple pasta/main recipes from risky to near/full mapped. | Map simple tomato forms to `tomato`, `passata`, `tomato_puree`, or a new canned/chopped tomato food. Treat tomato sauces/arrabbiata as prepared-product policy. |
| Standard sauce/condiment policy: soy sauce, mayo, teriyaki, pesto, crab sticks | 8 otherwise mapped recipes, 17 semi-prepared-risk recipes total | Fastest way to reduce false-risk once nutrition mappings exist. | Whitelist common generic sauce rows as low-confidence, or require decomposition for large sauce amounts like 60g pesto and 80g mayo-soy sauce. |
| Dry buckwheat: `гречка сухая` | 2 | Straightforward carb/calorie mapping. | Add new dry buckwheat food/mapping. |
| Chicken liver: `куриная печень` | 2 | Unlocks one snack and one main where liver is the anchor. | Add chicken liver nutrition row and alias. |
| Fresh grapes: `виноград`, `виноград кишмиш` | 2 | Fixes fruit carb gaps and avoids bad alcohol substring matching. | Add exact grape/kishmish fruit mapping; never map to wine. |
| High-impact one-off protein anchors: pork chop, trout, falafel, chicken sausage, egg yolks, split peas | 6 | Each unlocks one recipe, several with anchor-unmapped risk. | Add aliases where existing food exists (`свиные отбивные` -> `pork_chop`, `яичные желтки` -> `egg_yolk`); add/decompose foods for trout, falafel, chicken sausage, split peas. |
| Starch aliases: `рис басмати`, `лапша удон для быстрого приготовления` | 2 | Fixes carb/calorie totals. | Map basmati to existing rice or add `basmati_rice`; replace instant udon with generic dry udon or add exact udon. |
| Vegetable/product odds: `тыква кубиками «Айс»`, `вяленые томаты` | 2 | Small-to-moderate macro gaps, but product wording reduces confidence. | Replace with generic pumpkin and sun-dried tomato foods; avoid brand-specific names in production. |
| Spices/seasonings: `хмели-сунели`, `приправа для овощей или универсальная` | 2 | Low macro impact, but cleans mapping completeness. | Map to `mixed_spices` or explicit 0g seasoning policy. |

## Quick Wins

- Add aliases to existing foods: `свиные отбивные` -> `pork_chop`, `яичные желтки` -> `egg_yolk`, `рис басмати` -> `rice` or `basmati_rice`, `томаты черри` -> `tomato`, `протертые томаты` -> `passata`/`tomato_puree`, `резаные томаты` and `консервированные томаты` -> canned tomato policy, `хмели-сунели` and universal seasoning -> `mixed_spices` or 0g.
- Add new food rows for repeated/high-impact gaps: cod liver, dry buckwheat, chicken liver, split peas, fresh grapes, trout, generic udon, and possibly generic pumpkin.
- Treat soy sauce as a standard condiment. That likely releases `intake_019`, `intake_063`, and `intake_070` with only a low-confidence sodium note.
- Treat teriyaki and pesto separately from soy sauce: amounts are larger and sugar/fat variance matters more.
- Fix `intake_053` by choosing either egg or tofu, not `яйцо или тофу`.
- For cod-liver recipes with mayo (`intake_026`-`intake_028`), cod liver mapping is the main blocker; mayo can be kept low-confidence if generic mayo is allowed.

## Decisions Needed From User

- Cod liver policy: use canned cod liver with oil, drained canned cod liver, or another nutrition source?
- Prepared product policy: can generic nutrition rows be used for mayo, pesto, teriyaki, crab sticks, falafel, chicken sausage, and tomato sauces, or should these be decomposed/replaced?
- Ambiguous ingredient policy: choose one ingredient for `яйцо или тофу` and one dressing for `майонез или йогурт`.
- Low-confidence substitutions: approve or reject pak-choi/asparagus -> пекинская капуста/стручковая фасоль in `intake_095`, edamame/scallops -> green peas/shrimp in `intake_105`, and branded pumpkin/frozen-mix simplification in `intake_084`.
- Low-protein main policy: for `intake_089`, decide whether hummus counts as a plant protein anchor, whether the recipe should become a snack, or whether it can remain a low-protein main.
- Product-specific recipes: decide whether `intake_093` frozen falafel and mayo-soy sauce, `intake_101` chicken sausage + arrabbiata, and `intake_080` instant udon should be imported, replaced, decomposed, or deferred.

## Recommended Path Toward 105

1. Keep the first production slice conservative until mappings are actually added. The cleanest immediate import remains the 65 low-risk recipe slice from the preview, or the 71 `full + near_full` set if anchor-warning acceptance is documented.
2. Do a mapping-only pass for simple foods and aliases: cod liver, buckwheat, chicken liver, grape/kishmish, split peas, pork chop plural alias, egg yolks plural alias, basmati rice, simple tomato variants, chopped/canned tomatoes, and low-impact spices. This should move roughly 16 risky recipes out of the risky bucket with minimal product-policy debate.
3. Approve a standard-condiment policy for soy sauce and small mayo amounts, then re-run preview. This should unlock several fully mapped semi-prepared-risk recipes and the cod-liver mayo recipes if cod liver is mapped.
4. Handle large prepared sauces separately: pesto, teriyaki, tomato sauce, arrabbiata, and the mayo-soy sauce in `intake_093`. For each, either add a generic food mapping with low-confidence or decompose into base ingredients.
5. Resolve the remaining product/substitution recipes: `intake_080`, `intake_084`, `intake_089`, `intake_093`, `intake_101`, and `intake_105`. These are the last recipes to defer if the goal is a high-confidence import rather than simply reaching 105.
6. After each mapping/policy pass, re-run the import preview and only then promote a batch into production curated data. Do not import these 34 directly from this triage report.

Expected outcome: mapping-only work should bring the importable pool from 71 into the high 80s. Accepting standard condiments and straightforward prepared sauces can push it into the high 90s. Getting all the way to 105 requires explicit user acceptance or decomposition of the prepared-product and low-confidence-substitution cases.
