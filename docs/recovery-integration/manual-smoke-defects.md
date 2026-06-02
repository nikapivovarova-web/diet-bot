# Manual smoke product defects

Branch: `codex/recover-product-ui-on-hardened-master`
Workspace: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
Status date: 2026-05-29

## Scope guardrails

- No archive files were touched.
- `New project 2 CLEAN` was not used.
- No deploy, push, PR, tag, or commit was performed.
- No secrets or env files were changed.
- No real payments, refunds, or chargebacks were executed.
- Master hardening was preserved: PostgreSQL stores, queues, recovery, monitoring, preflight, throttling, and callback owner guards remain in place.

## Manual smoke process snapshot

- Integration manual-smoke bot PID found before changes: `8996`
- Observed child process: `30384`
- Command observed: `python -m diet_bot.telegram_app`
- Log path: `tmp/manual-smoke-run/bot-integration-smoke.stderr.log`
- The running integration process was not stopped or restarted during these fixes.

## Blocking defects

### QA-001 quiz correct-answer visual feedback missing

Status: Fixed and covered by tests.

Fix:
- Restored selected-answer visual feedback in questionnaire inline keyboards.
- Correct answer selection now marks the chosen option with the product-style check indicator.
- The callback owner token remains preserved in answer callbacks.

Coverage:
- `tests/test_telegram_callback_owner_smoke.py::test_question_keyboard_marks_selected_answer_with_product_check`
- `tests/test_telegram_callback_owner_smoke.py::test_answer_callback_marks_selected_option_and_keeps_owner_token`

### QA-002 `/330366` promo/admin menu missing

Status: Fixed with safe admin-only JSON promo management.

Fix:
- Restored `/330366` as an admin promo entrypoint.
- Added admin promo menu actions for monthly access code generation, discount promo creation, discount promo listing, and discount promo disabling.
- Kept current hardened admin permission checks and private-chat/callback safety guards.
- No payment mutation is performed by the menu; promo state is written through the existing promo-code JSON storage path.
- Discount activation remains safe for monthly-access-only flows and does not bypass payment/storage safety.

Coverage:
- `tests/test_telegram_user_journeys_smoke.py::test_admin_330366_opens_promo_panel`
- `tests/test_promo_codes.py`

### QA-003 privacy policy missing

Status: Fixed and covered by tests.

Fix:
- Added `/privacy` command.
- Added privacy callback route.
- Added product-ready fallback privacy policy text when `PRIVACY_POLICY_URL` is not configured.
- Kept URL button behavior when `PRIVACY_POLICY_URL` is configured.

Coverage:
- `tests/test_telegram_user_journeys_smoke.py::test_privacy_policy_is_reachable_without_external_url`

### QA-004 main menu missing promo/privacy/product entries

Status: Fixed and covered by tests.

Fix:
- Restored promo and privacy entry points in plan, paywall, subscription, and subscriber cabinet keyboards.
- Kept support entries and existing hardened guards.

Coverage:
- `tests/test_telegram_user_journeys_smoke.py::test_main_plan_menu_keeps_promo_and_privacy_entries`
- Runtime Telegram smoke tests listed below.

### QA-005 PDF photos inconsistent/overlapping

Status: Fixed and visually previewed.

Fix:
- Recipe photos are now rendered into stable fixed-size boxes.
- Image sources are cropped/fitted consistently before ReportLab draws them.
- Layout reserves image space before recipe text is drawn.

Coverage:
- `tests/test_pdf_renderer.py::test_meal_photo_uses_stable_fixed_box`
- `scripts/dev/pdf_renderer_recovery_smoke.py`

Preview PNGs:
- `tmp/pdf-qa-fixes-preview/recovery-r401-r610-01-page-01.png`
- `tmp/pdf-qa-fixes-preview/recovery-r401-r610-01-page-02.png`
- `tmp/pdf-qa-fixes-preview/recovery-r401-r610-01-page-26.png`
- `tmp/pdf-qa-fixes-preview/recovery-r401-r610-08-page-01.png`
- `tmp/pdf-qa-fixes-preview/recovery-r401-r610-08-page-02.png`
- `tmp/pdf-qa-fixes-preview/recovery-r401-r610-08-page-13.png`

### QA-006 PDF dish-title card white background

Status: Fixed and visually previewed.

Fix:
- Dish title cards now use FoodBalance green styling instead of a white card background.
- Nutrition badges are embedded in the green title card with readable contrast.

Coverage:
- `tests/test_pdf_renderer.py::test_meal_header_uses_foodbalance_green_card`
- Rendered previews listed under QA-005.

### QA-007 PDF shopping list layout regression

Status: Fixed and visually previewed.

Fix:
- Restored a more structured shopping-list layout with two balanced card columns.
- Group cards use FoodBalance green headers and stable spacing.
- Smoke PDFs render shopping list pages without observed overlap in generated previews.

Coverage:
- `tests/test_pdf_renderer.py::test_shopping_columns_build_two_structured_card_columns`
- `scripts/dev/pdf_renderer_recovery_smoke.py`
- Rendered previews listed under QA-005.

### QA-008 recipe ingredient anomalies: peanut butter 1g, American cheese naming

Status: Fixed and covered by data tests.

Fix:
- Corrected peanut butter gram anomalies in affected recipes.
- Renamed `american_cheese` Russian display name to a more product-friendly sliced-cheese name.
- Corrected similar tiny/zero/outlier gram anomalies found during scan, including affected muesli, flour, butter, egg, onion, carrot, bay leaf, bread slices, and hummus side-vegetable rows.
- Updated affected recipe nutrition rows after data corrections.

Coverage:
- `tests/test_curated_recipe_data.py::test_curated_recipe_data_fixes_manual_smoke_ingredient_anomalies`
- Full curated data/vector recipe regression set listed below.

## Verification commands

Executed during the fix pass:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_telegram_app_runtime.py tests\test_telegram_user_journeys_smoke.py tests\test_telegram_callback_owner_smoke.py tests\test_questionnaire_and_presentation.py tests\test_promo_codes.py -q
```

Result: `54 passed in 38.55s`

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_pdf_renderer.py -q
```

Result: `9 passed`

```powershell
.\.venv\Scripts\python.exe scripts\dev\pdf_renderer_recovery_smoke.py
```

Result: rendered 8 smoke PDFs; `recipes_checked=210`; output directory `tmp/pdf-renderer-recovery-smoke`.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_curated_recipe_data.py tests\test_recipe_traits.py tests\test_vectors_and_shopping.py -q
```

Result: `94 passed in 59.67s`

```powershell
git diff --check
```

Result: exit code `0`; only Git line-ending warnings were printed.

## Notes for release gate

- This report records product-blocker fixes only; it is not a release approval.
- Manual product smoke should be repeated before release, especially for live Telegram UI flows and visual PDF review.
- PyMuPDF was installed into the local virtual environment only to render preview PNGs from generated smoke PDFs.
