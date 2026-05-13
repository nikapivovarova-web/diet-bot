# Recipe Quality Recovery Audit

Scope: docs-only audit for recovering recipe/ingredient/portion-quality work from the old mixed tree into the clean tree by small slices. No runtime code, data, payment/storage, PDF layout, or Telegram UX was changed in this slice.

Sources compared read-only:

- Old source: `C:\Users\adck8\Documents\New project 2`
- Clean target: `C:\Users\adck8\Documents\New project 2 CLEAN`

## Executive Summary

The app does not currently have an OpenAI/LLM recipe prompt implementation in either tree. Recipe generation is deterministic: `builder.py` selects/scales recipe templates, `curated_data.py` loads curated JSON, `chef.py`/`presentation.py`/`pdf_renderer.py` format output, and `telegram_app.py` delivers it.

The main recipe-quality delta in old is not a single prompt. It is a combination of:

- curated JSON data edits that replace less accessible or confusing ingredients with more practical names/products;
- tests that encode those replacements and known false ingredient mappings;
- builder guardrails for sodium/carbohydrate overshoot during recipe scaling and top-ups;
- safer free-text food exclusion matching;
- a small `curated_data.py` change that avoids overwriting already-fixed source instructions with stale hardcoded fallbacks;
- richer PDF recipe display work, which is relevant context only and should stay out of recovery slices that are not PDF-specific.

## Candidate File Map

Generation and recipe selection:

- `src/diet_bot/builder.py`
  - Builds one-day plans, filters by cooking time, selects curated recipes, scales ingredient grams, adds missing garnishes, applies recent recipe avoidance, and tops up nutrients.
- `src/diet_bot/recipe_catalog.py`
  - Converts curated recipes into runtime recipe templates via `built_in_recipes()`.
- `src/diet_bot/curated_data.py`
  - Loads `curated_recipes.json`, `curated_foods.json`, ingredient/nutrition JSON, cleans instruction text, and drops recipes whose instructions still look incomplete.
- `src/diet_bot/safety.py` and `src/diet_bot/validation.py`
  - Apply restrictions, allergies, intolerances, excluded foods, tags, and validation after plan construction.

Ingredient normalization, product replacements, and grams:

- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_foods.json`
- `scripts/build_curated_recipe_data.py`
  - Parses workbook ingredients, maps aliases to `food_id`, estimates grams from g/ml/spoon/cup/unit text, normalizes display names, and writes generated JSON.
- `src/diet_bot/chef.py`
  - Owns visible ingredient formatting (`format_ingredient()`), kitchen-friendly gram rounding (`format_display_grams()`), household hints, and instruction amount cleanup (`clean_recipe_instruction_text()`).

PDF/Telegram display:

- `src/diet_bot/presentation.py`
  - Builds Telegram/text meal cards and shopping lists using `format_ingredient()`.
- `src/diet_bot/pdf_renderer.py`
  - Renders ingredient/recipe text in the weekly PDF.
- `src/diet_bot/telegram_app.py`
  - Sends meal cards, weekly text fallback, and weekly PDF. Also contains batch-prep/carryover helpers in both trees.

Prompts:

- Runtime recipe prompts are absent. `pyproject.toml` keeps `openai` as a dependency/planned integration, and docs mention future OpenAI adapters, but no recipe-generation LLM prompt exists in `src/`.
- Existing runtime prompts are questionnaire/support/promo texts in `questionnaire.py` and `telegram_app.py`, not recipe creation prompts.

## Old Improvements Missing Or Reduced In Clean

### 1. Runtime Data Replacements For Accessible Ingredients

Old runtime JSON removes several confusing or harder-to-source product IDs that still exist in clean runtime JSON:

- Removed from old runtime data: `agave_syrup`, `almond_milk`, `garam_masala`, `kale`, `monterey_jack`, `sambal_olek`, `tamari`, `turkey_or_chicken_breast`, `tzatziki`, `wensleydale_cheese`.
- Added in old runtime data: `chicken_breast_cooked`, `turkey_breast_cooked`.
- Old `curated_foods.json` has 336 food IDs; clean has 344.
- Old `curated_recipe_ingredients.json` has 4177 ingredient rows; clean has 4174.

Examples of old title/data cleanup missing in clean:

- `r040`: "кейл" -> "шпинат"
- `r043`: "индейкой или курицей" -> "курицей", with `готовая куриная грудка` mapped to `chicken_breast_cooked`
- `r067`: "грюйером" -> "полутвердым сыром"
- `r085`, `r103`, `r109`, `r178`, `r180`, `r210`, `r214`, `r233`: "кейл" -> "шпинат"
- `r119`/`r278`: "цацики" -> "йогуртовый соус"
- `r197`: "масала" wording simplified to "в карри"

Old changed recipe title/instruction fields for 60 recipes: `006, 007, 010, 032, 033, 040, 043, 049, 051, 052, 053, 054, 056, 060, 066, 067, 071, 073, 075, 085, 092, 103, 108, 109, 117, 119, 125, 131, 137, 138, 143, 144, 146, 150, 152, 154, 157, 159, 166, 168, 171, 178, 180, 184, 193, 197, 209, 210, 214, 215, 227, 228, 233, 238, 278, 287, 316, 355, 358, 359`.

Where it lives in old:

- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_foods.json`
- `tests/test_curated_recipe_data.py:126`
- `tests/test_curated_recipe_data.py:178`
- `tests/test_curated_recipe_data.py:191`

Important durability note: `scripts/build_curated_recipe_data.py` is effectively the same in old and clean for these replacements and still contains many blocked source aliases/food definitions. Copying only generated JSON would recover the current runtime behavior but would be fragile on the next data rebuild. A proper recovery slice should either update the builder script/source mapping or explicitly document that the JSON is manually curated and must not be regenerated blindly.

Category: post-processing/data normalization.

### 2. Better Handling Of Incomplete Instruction Fixes

Clean always applies `INSTRUCTION_FIXES_BY_RECIPE_ID` when a recipe ID is present. Old only applies a hardcoded fix if the source JSON instruction still looks incomplete after normal cleaning:

- Clean: `src/diet_bot/curated_data.py:103`
- Old: `src/diet_bot/curated_data.py:104`

This matters because old data already contains improved source instructions for recipes such as `r215`; the old loader avoids replacing newer source text with stale fallback text.

Where it lives in old:

- `src/diet_bot/curated_data.py:104`
- `src/diet_bot/curated_data.py:107`
- `tests/test_curated_recipe_data.py:82`
- `tests/test_curated_recipe_data.py:114`

Category: post-processing/filtering.

### 3. Macro And Sodium Guardrails During Recipe Scaling

Old `builder.py` adds limits that clean does not have:

- `CARBOHYDRATE_CEILING_MULTIPLIER`
- `SODIUM_CEILING_HEADROOM_MULTIPLIER`
- projected sodium penalty during recipe selection
- gram limiting for carbohydrate and sodium ceilings when scaling recipes, adding garnishes, topping up, and increasing existing portions
- stronger sodium scoring when the sodium deficit is already exhausted

Where it lives in old:

- `src/diet_bot/builder.py:57`
- `src/diet_bot/builder.py:58`
- `src/diet_bot/builder.py:714`
- `src/diet_bot/builder.py:949`
- `src/diet_bot/builder.py:1056`
- `src/diet_bot/builder.py:1587`
- `src/diet_bot/builder.py:1606`

Clean has the same surrounding functions but not the sodium/carbohydrate ceiling helpers.

Category: generation/plan selection.

### 4. Safer User Exclusion Matching

Old improves free-text exclusion matching:

- treats `INTOLERANCE` like allergy/excluded-food for name-based exclusions;
- adds cheese aliases;
- avoids reverse matching short Cyrillic fragments such as `сы` blocking `сыр`;
- expands/caches matchable excluded names and requires a minimum length.

Where it lives in old:

- `src/diet_bot/safety.py:26`
- `src/diet_bot/safety.py:145`
- `src/diet_bot/safety.py:199`
- `src/diet_bot/safety.py:225`
- `tests/test_safety_and_builder.py:76`
- `tests/test_safety_and_builder.py:88`
- `tests/test_safety_and_builder.py:98`

Category: generation input filtering / recipe exclusion.

### 5. PDF Recipe Display Context

Old PDF rendering has richer recipe presentation than clean:

- ingredient table with ingredient, amount, and approximate measure;
- `_ingredient_cells()` splitting `format_ingredient()` output into structured columns;
- recipe steps table via `_recipe_steps()` and `_recipe_steps_table()`;
- different nutrient coverage thresholding (`>=90`, `>=45`) and background/text color helpers;
- broader long-token wrapping and page layout work.

Where it lives in old:

- `src/diet_bot/pdf_renderer.py:794`
- `src/diet_bot/pdf_renderer.py:836`
- `src/diet_bot/pdf_renderer.py:894`
- `src/diet_bot/pdf_renderer.py:918`
- `src/diet_bot/pdf_renderer.py:1778`
- `tests/test_pdf_renderer.py`

Category: PDF display only. Keep this out of recipe/data recovery slices unless the slice is explicitly PDF-focused.

## What Clean Already Has

Clean already contains the major kitchen-friendly display layer:

- `src/diet_bot/chef.py` has `format_display_grams()`, `format_ingredient()`, household hints, tiny ingredient text, and `clean_recipe_instruction_text()`.
- `src/diet_bot/presentation.py` and `src/diet_bot/pdf_renderer.py` already consume `format_ingredient()` and `format_display_grams()`.
- `tests/test_questionnaire_and_presentation.py` already covers display rounding for values such as 48/54/73/296 g, small yogurt amounts, tiny spices/garlic, citrus/potato/egg hints, and instruction amount cleanup.
- Batch-prep/carryover concepts are already present in clean `domain.py`, `presentation.py`, `telegram_app.py`, and `tests/test_telegram_app_photos.py`.

So the first recovery pass should not rewrite the display formatter wholesale. The highest-value missing pieces are data replacements, durable data-generation rules, and builder/safety guardrails.

## Tests From Old Worth Adapting

Data/replacement tests:

- `tests/test_curated_recipe_data.py:126`
  Adapt `test_curated_recipe_data_excludes_approved_replacement_sources_from_runtime`.
- `tests/test_curated_recipe_data.py:178`
  Adapt corrected title assertions for accessible ingredient names.
- `tests/test_curated_recipe_data.py:191`
  Adapt known false-match checks, especially `chicken_breast_cooked`, spinach replacing kale, water/banana/chili-oil/peanut-oil mapping.
- `tests/test_curated_recipe_data.py:82` and `:114`
  Keep coverage for complete source instructions and no truncated instructions.

Generation tests:

- Add focused tests around sodium/carbohydrate ceilings before porting builder limits. Old has implementation but limited direct tests, so write small deterministic tests rather than relying only on broad plan generation.
- Use existing clean `tests/test_safety_and_builder.py` as the landing place for builder/safety guardrails.

Safety tests:

- `tests/test_safety_and_builder.py:76`
- `tests/test_safety_and_builder.py:88`
- `tests/test_safety_and_builder.py:98`
- `tests/test_safety_and_builder.py:109`

PDF tests:

- Treat old `tests/test_pdf_renderer.py` as reference only for a later PDF slice. Do not mix it into recipe-data recovery.

## Proposed Small Slices

1. Data replacement test slice
   Add failing clean tests for blocked runtime terms/food IDs and a few representative corrected titles/ingredient mappings. No data changes yet.

2. Durable data-source slice
   Decide whether the source of truth is generated JSON or `scripts/build_curated_recipe_data.py`. If rebuilds are expected, update the builder script mapping/aliases so blocked IDs cannot reappear. If JSON is currently hand-curated, document that explicitly before copying JSON deltas.

3. Runtime curated data slice
   Apply the minimal curated JSON replacements for the blocked products and changed recipes. Run curated-data tests only.

4. Instruction fallback slice
   Port the old conditional `INSTRUCTION_FIXES_BY_RECIPE_ID` behavior so hardcoded fallbacks are used only when source instructions still look incomplete.

5. Builder sodium/carbohydrate guardrail slice
   Add targeted tests, then port the old ceiling helpers and selection penalties in `builder.py`.

6. Safety exclusion slice
   Port old free-text matching improvements in `safety.py` and related tests.

7. PDF recipe display slice
   Only after recipe/data recovery: recover ingredient tables, recipe step splitting, and nutrient coverage styling in a PDF-specific branch/slice.

## Do Not Recover In This Path

- Do not copy old `telegram_app.py` wholesale.
- Do not mix payment/storage/Postgres/Telegram runtime work into recipe-quality recovery.
- Do not recover PDF redesign together with data/generation quality.
- Do not run cleanup/deletion of workbook helper scripts as part of recipe-quality work.
