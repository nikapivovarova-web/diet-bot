# Manual Smoke Defects Round 2

Status: do not release.

Scope: `codex/recover-product-ui-on-hardened-master` in `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`.

Constraints:

- Do not touch the archive.
- Do not use `New project 2 CLEAN`.
- Do not deploy, push, create PRs, tag, or commit.
- Do not edit secrets or env files.
- Do not run real payment actions, refunds, or chargebacks.
- Do not blind-merge or remove master hardening.
- Do not stop the recovered bot. If a manual-smoke bot restart is needed, restart only the integration process whose path belongs to this workspace.

## QA2 Defects

### QA2-001 Missing approximate measures

Status: fixed for confident common measures; remaining ambiguous backlog documented.

Problem:

- Approximate household measures are missing or inconsistent for some ingredients.
- Examples from QA: garlic `5 г` should show a usable measure such as `примерно 1 зубчик`; dates `45 г` should show a usable measure such as `примерно 2-3 финика`.

Plan:

- Audit all curated recipe ingredient rows.
- Normalize approximate measures for common user-hostile gram-only items.
- Avoid invented conversions where a neutral wording is safer.
- Add repeatable audit/test coverage.

Audit result:

- `scripts/dev/recipe_content_audit.py` checks all curated recipe ingredient rows.
- Current batch inspected 6130 ingredient rows and added/normalized 514 approximate measures in `curated_recipe_ingredients.json`.
- Handled garlic, dates, salt/pepper, sauces/pastes, nuts/seeds, and small cheeses where household measures were confident.
- `docs/recovery-integration/approximate-measures-round2.md` records before/after examples and unresolved categories.
- Latest audit reports `missing_approximate_measures.warnings=133`, down from the current pre-batch baseline of 406.
- Remaining warnings are intentionally left for content review where household measures would be ambiguous or misleading.

### QA2-002 Inconsistent PDF photos

Status: fixed.

Problem:

- Recipe photos still appear with inconsistent positioning and sizing.
- Some photos can move unexpectedly or sit awkwardly relative to text.

Plan:

- Make recipe images use one stable fixed-size layout.
- Reserve vertical space before drawing images.
- Keep image placement consistent and avoid text/table overlap.
- Generate smoke PDFs and PNG previews under `tmp/pdf-qa-round2-preview/`.

### QA2-003 Unclear or non-CIS products

Status: fixed for the high-suspicion recipe batch.

Problem:

- Ingredients such as `харисса` are unclear for the target audience.
- The existing approximate measure mentioning `примерно 1/2 столовой ложки сухой крупы` is wrong for harissa as a sauce/paste.

Plan:

- Search recipe/food data for `хариса`, `харисса`, `harissa`, `american cheese`, `американский сыр`, `edamame`, `эдамаме`, and similar flagged names.
- Replace or adapt inaccessible ingredients with coherent CIS-friendly alternatives where appropriate.
- Add assertions that flagged names are absent unless intentionally explained and accessible.

Fix result:

- High-suspicion recipe data no longer contains user-facing harissa/harisa or american cheese terms.
- The unused `edamame` food catalog row was removed after confirming no curated ingredient rows referenced it.
- `r357` was adapted from an unavailable/unclear Thai red pepper wording to CIS-friendly sweet red pepper.
- Latest audit reports `non_cis_unclear_ingredients.warnings=0`.

### QA2-004 Full recipe consistency/content audit

Status: high-suspicion batch fixed; broad approximate-measure backlog remains.

Problem:

- At least one recipe title mentions hummus, but hummus is absent from ingredients and instructions.
- QA requires a systematic pass over all recipes, not a one-off patch.

Plan:

- Add a repeatable recipe content audit helper.
- Check title/ingredient/instruction consistency, unused ingredients, missing ingredients used in steps, broken/truncated steps, zero/tiny quantity issues, and flagged ingredient names.
- Fix high-confidence blockers and document ambiguous items for follow-up review.

Fix result:

- Fixed the Top 25 / high-suspicion / recommended batch plus user-reported peanut-butter examples documented in `docs/recovery-integration/recipe-fixes-round2.md`.
- Fixed `r115`, `r607`, `r595`, the peanut-butter tiny cases (`r015`, `r034`, `r062`, `r598`), hummus/title support coverage, and the remaining harissa/american-cheese/edamame catalog exposure found by the audit.
- Latest audit reports `blocking_findings=0`, `warning_findings=1494`, `title_ingredient_mismatch.warnings=0`, `steps_mention_missing_ingredient.warnings=0`, and `tiny_gram_anomalies.warnings=0`.
- Remaining warnings are not all in scope for this pass; most are broad ingredient-step morphology warnings and the separate approximate-measures backlog.

### QA2-005 Privacy consent flow

Status: fixed.

Problem:

- `Политика конфиденциальности` appears as an inline button on nearly every questionnaire question.

Plan:

- Add a separate initial privacy consent step before questionnaire answers are collected.
- Show `Принять и продолжить` plus `Политика конфиденциальности`, with optional support.
- Continue to the first questionnaire question after acceptance.
- Keep `/privacy` and main menu privacy access.
- Add tests for the consent-first flow and removal of privacy buttons from normal questions.

## QA2-005 Privacy Consent Flow

- status: fixed
- files changed:
  - `src/diet_bot/telegram_app.py` (privacy consent implementation was already present in the dirty Round 2 state and verified here)
  - `tests/test_telegram_user_journeys_smoke.py`
  - `docs/recovery-integration/manual-smoke-defects-round2.md`
  - `docs/recovery-integration/recovery-status.md`
- tests run:
  - RED check: `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py -q` -> one test failed because the new assertion targeted the text-only age question, which has no inline keyboard.
  - GREEN check: `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py -q` -> `48 passed`
- remaining risks:
  - Privacy consent is stored in process memory via the existing questionnaire/session flow (`PRIVACY_CONSENT_CHAT_IDS`), with no database migration. After a bot restart, a user may see the consent screen again before starting a questionnaire.
  - No live bot, deployment, PDF, recipe, payment, storage, or runtime checks were run in this privacy-only pass.

## QA2-002 PDF Photo/Layout Consistency

- status: fixed
- what changed:
  - Recipe photo rendering now uses one stacked layout path: title/nutrition card, ingredients table, centered fixed-size photo, then cooking steps.
  - The photo and cooking steps are grouped together so ReportLab reserves vertical space before drawing the image and moves the image+steps block to the next page when needed.
  - Old side-by-side recipe/photo helpers were removed from `src/diet_bot/pdf_renderer.py`.
  - Photo fitting stays fixed-box and center-cropped through the existing Pillow path, without changing recipe text/data.
- files changed:
  - `src/diet_bot/pdf_renderer.py`
  - `tests/test_pdf_renderer.py`
  - `docs/recovery-integration/manual-smoke-defects-round2.md`
  - `docs/recovery-integration/recovery-status.md`
- tests/smoke run:
  - RED check: `pytest tests/test_pdf_renderer.py::test_recipe_media_always_uses_single_stacked_photo_layout tests/test_pdf_renderer.py::test_renderer_keeps_no_side_by_side_recipe_photo_layout_helpers tests/test_pdf_renderer.py::test_meal_photo_source_is_rendered_to_fixed_box_aspect -q` -> expected failures before renderer change, then `3 passed` after the fix.
  - `pytest tests/test_pdf_renderer.py -q` -> `12 passed`.
  - `python scripts/dev/pdf_renderer_recovery_smoke.py` -> `rendered_pdfs=8`, `recipes_checked=210`.
- preview PNG paths:
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p02-photo-after-ingredients.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p03-long-recipe-start.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p04-long-recipe-image-steps-next-page.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p28-cod-liver-salad-previous-example.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p30-shopping-list.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p31-shopping-list-continued.png`
- remaining risks:
  - Visual overlap cannot be fully proven by unit tests; this pass relies on smoke PDF generation plus rendered PNG inspection.
  - The cod-liver salad example was found and previewed. Hummus/soba and harissa/dip terms were not discoverable in the generated recovery smoke PDF text during this pass.
  - Other Round 2 recipe-content defects remain out of scope for this PDF-only stage.

## Verification Log

- QA2-001/QA2-003/QA2-004 recipe-audit-only pass: `python scripts/dev/recipe_content_audit.py` -> `recipes_checked=665`, `ingredients_checked=6130`, `blocking_findings=4`, `warning_findings=1634`.
- QA2-001/QA2-003/QA2-004 recipe-audit-only diff check: `git diff --check` -> exit code `0`; Git printed only existing CRLF checkout warnings.
- QA2-003/QA2-004 high-suspicion recipe-fix pass: `python scripts/dev/recipe_content_audit.py` -> `recipes_checked=665`, `ingredients_checked=6130`, `foods_checked=359`, `blocking_findings=0`, `warning_findings=1494`.
- QA2-003/QA2-004 high-suspicion recipe-fix targeted tests: `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q` -> `92 passed`.
- QA2-003/QA2-004 high-suspicion recipe-fix diff check: `git diff --check` -> exit code `0`; Git printed only existing CRLF checkout warnings.
- QA2-005 privacy-only targeted tests passed: `48 passed`.
- QA2-002 PDF-only targeted tests passed: `pytest tests/test_pdf_renderer.py -q` -> `12 passed`.
- QA2-002 PDF smoke passed: `python scripts/dev/pdf_renderer_recovery_smoke.py` -> `rendered_pdfs=8`, `recipes_checked=210`.
- `git diff --check` passed with exit code `0`; Git printed only existing CRLF checkout warnings.

## PDF Preview Artifacts

- `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p02-photo-after-ingredients.png`
- `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p03-long-recipe-start.png`
- `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p04-long-recipe-image-steps-next-page.png`
- `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p28-cod-liver-salad-previous-example.png`
- `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p30-shopping-list.png`
- `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p31-shopping-list-continued.png`

## Bot Restart

Pending. No process restarted yet.
