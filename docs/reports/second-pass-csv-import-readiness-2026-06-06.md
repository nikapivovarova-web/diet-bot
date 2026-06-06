# Second-pass CSV import readiness - 2026-06-06

## Scope

- Truth surface: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Worktree: `C:\Users\adck8\Documents\codex-worktrees\bulk-recipe-readiness-317`
- Base: `origin/master` at `1b0eb0b8d49b9a546567f1c72dea0cc82e54ed83`
- Primary source: `C:\Users\adck8\Documents\New project 2\tmp\candidate-recipe-review\second-pass\suitable_after_second_pass.csv`
- Excel workbook was not used as the primary source.
- No bot, Telegram polling, production database, payments, deploy, merge, or production import was run.

## Catalog Surface

- `suitable_after_second_pass.csv` rows: 317
- `curated_recipes.json` rows: 689
- `curated_recipe_ingredients.json` unique `recipe_id`: 710
- `curated_recipe_nutrition.json` unique `recipe_id`: 710
- Ingredients/nutrition unique `recipe_id` union: 710
- Missing metadata cards in `curated_recipes.json`: 21

Missing `curated_recipes.json` metadata recipe IDs:

- `r416_tselnozernovoy_hleb_s_pechenyu_treski`
- `r424_salat_iz_pecheni_treski_s_yaytsom`
- `r425_salat_iz_pecheni_treski_s_ogurtsom_i_kartofelem`
- `r426_salat_iz_pecheni_treski_s_lukom`
- `r427_salat_iz_konservirovannoy_pecheni_treski`
- `r428_domashniy_salat_iz_pecheni_treski_s_zelenym_goroshkom`
- `r448_tselnozernovoy_hleb_s_pashtetom_iz_kurinoy_pecheni`
- `r454_gulyash_iz_kurinoy_pecheni`
- `r496_karbonara_s_bekonom_i_slivkami`
- `r502_pasta_s_lososem_i_shpinatom_v_slivochnom_souse`
- `r548_kurinaya_pechen_s_grechkoy`
- `r552_meksikanskaya_zapekanka_s_risom_i_fasolyu`
- `r585_tost_s_sardinami_i_ogurtsom`
- `r587_tosty_so_shprotami_ogurtsom_i_gorchitsey`
- `r588_brusketty_so_shprotami_i_marinovannym_lukom`
- `r589_yaytsa_farshirovannye_shprotami`
- `r590_risovye_hlebtsy_so_shprotnym_pashtetom`
- `r591_kartofelnye_kanape_s_seledkoy`
- `r592_tosty_s_seledkoy_i_svekloy`
- `r593_yaytsa_s_seledkoy_i_lukom`
- `r594_svekolnye_kruzhochki_s_seledkoy`

## Duplicate Check

- Exact title duplicates against current `curated_recipes.json`: 1
- Fuzzy duplicates at threshold `0.86`: 0
- CSV rows with `existing_catalog_match` or `existing_catalog_match_id`: 0
- Really new candidates by this pass: 316

The exact duplicate is `c0835` (`салат цезарь`) matching `r690_salat_tsezar`.

## Import Readiness

- `import_ready`: 0
- Blocked: 317
- Photo status: 317 missing

Blocked reasons:

- `ingredient_amounts_not_gram_normalized`: 317
- `missing_photo`: 317
- `missing_servings`: 317
- `nutrition_not_calculated`: 317
- `duplicate_review_required`: 1

The CSV has useful candidate title, likely slot/category, ingredients, and instructions, but it is not production-import-ready by the current gate. It does not provide serving counts, candidate photos, structured grams for every ingredient, food ID mappings, calculated nutrition, or sodium values.

## Decision

Do not create a small import PR for 5, 9, or 19 recipes. Fewer than 150 candidates are actually import-ready, so this branch is a tooling/report PR:

- add first-class loader support for `suitable_after_second_pass.csv`;
- preserve the CSV as the primary source, not Excel;
- keep the current audit output as blocker evidence;
- use the report to define the mass-unblock rules before a bulk import.

## Repair Plan for 710 vs 689

1. Restore the 21 missing `curated_recipes.json` metadata cards from the same source snapshot that produced the existing ingredient/nutrition rows.
2. Reuse the already-present `recipe_id`, `recipe_no`, ingredients, nutrition, and photos where available; do not recalculate unrelated nutrition.
3. For each restored card, verify title, slot, category, servings, time text, instructions, source fields, and `image_url`.
4. Run catalog integrity tests to prove `curated_recipes.json`, `curated_recipe_ingredients.json`, and `curated_recipe_nutrition.json` have the same recipe ID surface.
5. Keep this repair separate from the 317-candidate bulk-import decision unless the user explicitly asks to combine them.
