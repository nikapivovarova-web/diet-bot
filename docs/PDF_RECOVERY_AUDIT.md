# PDF recovery audit

Scope: docs-only audit for recovering the old PDF redesign into the clean tree by small slices. No production PDF code, tests, data, payment/storage, or Telegram UX was changed in this slice.

## Compared sources

- Old source material:
  - `C:\Users\adck8\Documents\New project 2\src\diet_bot\pdf_renderer.py`
  - `C:\Users\adck8\Documents\New project 2\tests\test_pdf_renderer.py`
  - `C:\Users\adck8\Documents\New project 2\tests\test_pdf_limits_smoke.py`
  - `C:\Users\adck8\Documents\New project 2\src\diet_bot\data\`
- Clean targets:
  - `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\pdf_renderer.py`
  - `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_pdf_renderer.py`
  - `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_pdf_limits_smoke.py`
  - `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\data\`

## Old PDF elements missing or reduced in clean

- Branded cover header: old uses `foodbalance_pdf_logo.png`, left-aligned `Food Balance`, larger title, date range, and a QR block with `@FOODBALANCERU_BOT`; clean has centered text-only `FoodBalance` cover.
- Cover summary cards: old has richer metric cards with BMI category hint, daily calorie target, water, and weekly meal count; clean has simpler summary cells.
- Cover safety copy: old puts a medical disclaimer, caloric drinks note, and variation/fine-print note on the cover; clean leaves most safety/orientation copy for the shopping section.
- Page background/footer polish: old paints a warm off-white page background on every page and keeps FoodBalance/page number footer; clean footer is text only on the default page background.
- Day layout: old starts every day on a fresh page and puts daily totals on a separate page after meals; clean flows all days more continuously and keeps daily totals attached after meals.
- Meal header design: old splits meal type into a green pill, recipe title, and four macro badges; clean uses one pale title bar plus a single nutrition chip.
- Ingredient presentation: old converts ingredients into a three-column table: ingredient, amount, approximate measure; clean mostly uses bullets or compact two-column bullet tables.
- Recipe presentation: old breaks recipe text into numbered steps and can place steps beside the meal photo; clean keeps recipe text as one paragraph below ingredients.
- Nutrient totals: old uses a full-width table with `Нутриент / Факт / Цель / %` and colored percent backgrounds with thresholds `<45`, `45-89`, `>=90`; clean uses two subtables with colored dots and different thresholds.
- Shopping layout: old packs grocery groups into two balanced card columns and has logic to keep dense lists within two pages; clean prints groups sequentially with plain item tables.
- Typography/color system: old uses smaller body text, additional colors (`DEEP_GREEN`, `PAGE_BACKGROUND`, `CARD_BACKGROUND`, `BEIGE`, warning/good/moderate/alert colors), rounded cards, white table headers, badge styles, fine print, QR caption, and several cover-specific styles.

Note: old `pdf_renderer.py` also contains helper pages such as `_calculation_page`, `_weekly_menu_page`, `_weekly_prep_page`, `_nutrient_report_section`, and `_disclaimer_section`, but they are not referenced from old `_build_story`. Treat them as source material only; do not re-enable them accidentally during visual recovery.

## Assets and data

- Old-only PDF assets needed for the branded cover slice:
  - `src\diet_bot\data\foodbalance_pdf_logo.png` (`861x867`, 444,713 bytes)
  - `src\diet_bot\data\foodbalance_pdf_qr.png` (`592x592`, 3,838 bytes)
- `welcome_foodbalance.png` exists in both trees with the same size and is not part of the old PDF renderer path.
- Recipe photo filenames match between old and clean; no additional recipe-photo asset is needed for the PDF layout recovery.
- JSON data is not identical:
  - `curated_recipes.json`: 400 recipes in both trees, same recipe ids, different bytes.
  - `curated_foods.json`: old has 336 foods, clean has 344 foods. Old-only food ids: `turkey_breast_cooked`, `chicken_breast_cooked`; clean-only ids include `agave_syrup`, `almond_milk`, `garam_masala`, `kale`, `monterey_jack`, `sambal_olek`, `tamari`, `turkey_or_chicken_breast`, `tzatziki`, `wensleydale_cheese`.
  - `curated_recipe_ingredients.json` and `curated_recipe_nutrition.json` differ by size.
- Recommendation: do not move JSON data as part of visual PDF slices. If a future old test depends on fixed recipe text or food ids, recover it in a separate data slice with targeted data tests.

## Tests worth recovering in small parts

- From old `tests/test_pdf_renderer.py`:
  - Content acceptance: assert `Ваш расчет`, ingredient table headers (`Ингредиент`, `Примерная мера`), `Факт`, `Цель`, `Список продуктов на неделю`, cover disclaimer, no emoji leakage in extracted text.
  - Nutrient thresholds: port `_coverage_level` tests with old agreed ranges only in the slice that replaces clean dot thresholds with old percent-background thresholds.
  - Single-day render smoke and long-token render smoke: useful renderer stability checks; adapt around current cleanup behavior.
  - Missing local photo smoke: already present conceptually, keep as regression coverage when recipe media layout changes.
  - Dense shopping packing: port only with the shopping layout slice because it imports old private layout helpers and uses a synthetic `ShoppingGroup`.
  - Soup/cracker text tests: likely data/text-fix coverage, not pure PDF layout. Port only if the data slice intentionally restores those recipe text changes.
- From old `tests/test_pdf_limits_smoke.py`:
  - Most of the file touches subscription limits, fallback behavior, Telegram sending, throttles, or access consumption. That is out of scope for PDF redesign recovery and should not be ported in the visual PDF slices.
  - If needed later, only the non-empty PDF payload check belongs near PDF safety, not visual redesign.

## Transfer risks

- Wholesale copy risk: old `pdf_renderer.py` includes unused helpers and historical alternatives; copying it whole would revive unclear pages and make review hard.
- Behavioral drift risk: old day breaks, daily totals placement, and shopping pagination can change PDF length and Telegram file size.
- Data coupling risk: some old tests pass because old JSON recipe text/foods differ from clean, not because of renderer behavior.
- Asset packaging risk: logo/QR must be package data and should degrade gracefully when missing or unreadable.
- Text extraction risk: visual changes that use emoji fonts or images can make `pypdf` assertions flaky; keep explicit no-emoji text checks.
- Private-helper test risk: old tests import many renderer internals. Port only one helper family per slice, otherwise tests will lock too much implementation at once.
- Scope risk: `test_pdf_limits_smoke.py` mixes PDF with access/payment/Telegram behavior. Keep it out of this redesign path unless a future slice is explicitly about PDF safety guards.

## Suggested implementation slices

1. Cover branding assets only: add logo/QR package assets, `_asset_image`, branded cover header/QR block, and graceful missing-asset tests.
2. Cover summary and safety copy: restore old metric card wording, BMI category hint, medical disclaimer, drinks note, and fine print.
3. Meal header polish: add meal type pill and four macro badges while keeping ingredients/recipe body unchanged.
4. Ingredient table: replace bullet ingredients with the old three-column ingredient table and add extracted-text assertions for headers and approximate measures.
5. Recipe steps/media: split instructions into numbered steps, place recipe steps beside photo when available, and keep long-token/single-day render tests green.
6. Daily totals thresholds: replace dot-based clean totals with old `Нутриент / Факт / Цель / %` table and port `_coverage_level` threshold tests.
7. Shopping cards and pagination: restore two-column shopping cards and the dense-list two-page packing test.
8. Page background and final typography pass: add page background, rounded card styles, smaller old type scale, and visual smoke checks if a rendered PDF comparison workflow is added.
9. Optional data-only slice: restore specific recipe text/nutrition fixes only with targeted data tests; do not combine this with renderer layout.
