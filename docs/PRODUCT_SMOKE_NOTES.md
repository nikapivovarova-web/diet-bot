# Product Smoke Notes

Date: 2026-05-13

Scope: focused local smoke after PDF and recipe-quality recovery. No production Telegram polling, YooKassa checkout, Telegram Stars spend, cleanup, refactor, or push was performed.

## Checked

- Git status and recent recovery log from `C:\Users\adck8\Documents\New project 2 CLEAN`.
- PDF renderer and PDF delivery-limit smoke tests.
- Recipe quality focused tests for cooking effort preference, CIS-friendly substitutions, ingredient display, and recipe text guardrails.
- Local payment and Telegram handler tests that use fakes/mocks only and do not perform real YooKassa or Telegram Stars payments.
- One sample weekly ration PDF generated through existing local helpers: `_build_week_plans`, `_week_plan_dates`, and `render_week_plan_pdf`.
- Key PDF pages rendered with PyMuPDF and visually checked: cover, Day 1, recipe page, and shopping list.

## Commands Passed

- `git status --short --branch`
- `git log --oneline --decorate --max-count=12`
- `$env:DIET_BOT_TESTER_CHAT_IDS=''; python -m pytest tests\test_pdf_renderer.py tests\test_pdf_limits_smoke.py -q`
- `$env:DIET_BOT_TESTER_CHAT_IDS=''; python -m pytest tests\test_safety_and_builder.py::test_simple_cooking_preference_filters_curated_recipe_effort tests\test_safety_and_builder.py::test_cooking_effort_constraints_change_simple_vs_interesting_generation tests\test_safety_and_builder.py::test_recipe_plan_has_no_empty_meals_or_placeholder_recipe_text tests\test_safety_and_builder.py::test_generated_recipe_text_uses_natural_cases tests\test_safety_and_builder.py::test_recipe_catalog_text_has_no_service_labels_or_links tests\test_curated_recipe_data.py::test_curated_recipe_runtime_uses_cis_friendly_substitutions tests\test_curated_recipe_data.py::test_curated_recipe_runtime_text_uses_accessible_ingredient_names tests\test_curated_recipe_data.py::test_curated_recipe_runtime_preserves_normal_ingredient_mappings tests\test_curated_recipe_data.py::test_curated_recipe_source_json_has_no_truncated_instructions tests\test_curated_recipe_data.py::test_curated_recipe_runtime_blocks_service_only_instruction_text tests\test_questionnaire_and_presentation.py::test_recipe_instruction_text_uses_kitchen_amounts tests\test_questionnaire_and_presentation.py::test_recipe_instruction_text_removes_service_labels_without_losing_steps tests\test_questionnaire_and_presentation.py::test_recipe_instruction_text_keeps_normal_recipe_text_unchanged tests\test_questionnaire_and_presentation.py::test_recipe_instruction_text_normalizes_fractional_kitchen_units tests\test_questionnaire_and_presentation.py::test_meal_ingredients_include_household_measure_hints tests\test_questionnaire_and_presentation.py::test_visible_ingredient_grams_are_kitchen_rounded tests\test_questionnaire_and_presentation.py::test_citrus_potato_and_egg_hints_avoid_implausible_fractions -q`
- `$env:DIET_BOT_TESTER_CHAT_IDS=''; python -m pytest tests\test_payments_model.py tests\test_subscriptions.py tests\test_telegram_app_photos.py -k "paywall or pre_checkout or successful_payment or invoice or yookassa or stars or week_plan_with_access_refunds_limit_when_pdf_not_delivered or subscriber_cabinet_keyboard_shows_limits_without_upsells or subscription_payment_result_opens_subscriber_cabinet or subscription_payment_keyboard_has_monthly_options_only" -q`
- `$env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; ... | python -` to generate the sample PDF and PyMuPDF PNG renders.

## Results

- PDF tests: 19 passed.
- Recipe quality focused tests: 17 passed.
- Payment/Telegram targeted tests: 81 passed, 105 deselected.
- Sample PDF has 27 pages.
- Structural PyMuPDF checks:
  - cover has no Day 1 content;
  - Day 1 starts on page 2;
  - rendered recipe page contains ingredients and preparation steps;
  - rendered shopping page contains the weekly shopping heading.
- Visual review found no broken images, obvious overlaps, unreadable recipe tables, or unreadable shopping-list sections in the rendered key pages.

## Artifacts

- PDF: `output/pdf/product-smoke-2026-05-13/foodbalance-week-smoke.pdf`
- Summary: `output/pdf/product-smoke-2026-05-13/smoke-summary.json`
- Cover PNG: `output/pdf/product-smoke-2026-05-13/cover-page-1.png`
- Day 1 PNG: `output/pdf/product-smoke-2026-05-13/day1-page-2.png`
- Recipe PNG: `output/pdf/product-smoke-2026-05-13/recipe-page-3.png`
- Shopping list PNG: `output/pdf/product-smoke-2026-05-13/shopping-page-26.png`

## Known Limitations

- Real YooKassa payments were not run.
- Real Telegram Stars payments were not run.
- Telegram bot polling was not started; this was a local smoke using existing tests and helpers.
- Pytest emitted a Windows temp cleanup `PermissionError` after two successful runs, but both affected commands exited with code 0 and reported passing tests.
