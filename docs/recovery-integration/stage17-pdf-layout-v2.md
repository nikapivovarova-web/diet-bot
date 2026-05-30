# Stage 17 PDF Layout V2

Date: 2026-05-30

Scope: PDF renderer only.

## Implemented

- Restored visible day context on PDF pages. The renderer now sets a page label before each day and before the shopping-list section, and the page callback draws that label in the top margin. Recipe continuation pages keep the active label, so pages with Day 1 recipes show `День 1`, Day 5 pages show `День 5`, and shopping-list pages show `Список продуктов`.
- Replaced the centered/stacked recipe-photo path with one uniform right-photo layout for meals with local photos.
- Recipe title and nutrition card remain at the top. Below that, the body uses fixed metrics:
  - left column starts at x `0`;
  - gutter is `7 mm`;
  - right photo column width is `64 mm`;
  - right photo height is `46 mm`;
  - minimum reserved photo block height is `54 mm`.
- Ingredients and the initial cooking section are rendered in the bounded left column. The image is rendered only in the fixed right column.
- `_meal_image_flowables` now aligns recipe images to the right, not center.

## Long Recipe Continuation

- The renderer measures the left-column content and keeps a bounded initial body beside the fixed right photo.
- If the recipe steps do not fit cleanly in that first body area, remaining steps continue below the photo block as a normal full-width steps table.
- If the block does not fit in the remaining page space, ReportLab moves it to the next page. Extra pages are acceptable for this stage.
- No fallback places the recipe photo centered above or below text.

## Tests And Smoke

- RED before implementation:
  - `pytest tests/test_pdf_renderer.py::test_recipe_with_photo_uses_right_photo_two_column_body tests/test_pdf_renderer.py::test_long_recipe_steps_continue_below_photo_block tests/test_pdf_renderer.py::test_recipe_photo_has_no_centered_photo_fallback tests/test_pdf_renderer.py::test_day_label_is_visible_on_recipe_continuation_pages -q`
  - result: `4 failed`
- Focused GREEN after implementation:
  - same command
  - result: `4 passed`
- Full PDF tests:
  - `pytest tests/test_pdf_renderer.py -q`
  - result: `14 passed`
- Recovery PDF smoke:
  - `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - result: `rendered_pdfs=8`, `recipes_checked=210`
- Diff hygiene:
  - `git diff --check`
  - result: exit code `0`; Git printed only existing CRLF checkout warnings.

## Preview Paths

PDF smoke output:

- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-01.pdf`
- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-08.pdf`

PyMuPDF PNG previews:

- `tmp/pdf-qa-stage17-preview/p03-day1-normal-right-photo.png`
- `tmp/pdf-qa-stage17-preview/p05-long-recipe-continuation.png`
- `tmp/pdf-qa-stage17-preview/p20-day5-label-right-photo.png`
- `tmp/pdf-qa-stage17-preview/p27-cod-liver-previous-example.png`
- `tmp/pdf-qa-stage17-preview/p33-shopping-list.png`
- `tmp/pdf-qa-stage17-preview/p34-shopping-list-continued.png`

## Remaining Risks

- Unit tests verify renderer structure, page text labels, and right-column metrics, but overlap is still ultimately visual. The listed PNG previews were rendered and inspected for this pass.
- Some recipes have enough ingredients that steps naturally continue below the photo block. This is intentional and matches the Stage 17 rule that longer recipes may gain vertical space or pages.
- This stage did not address Telegram UX, recipe data, payments, runtime/storage/deploy, or bot execution.
