# FoodBalance Recovery Integration: PDF Renderer Transfer

## Scope

Stage 3 restored the product PDF appearance/branding layer onto hardened master.

Only PDF-owned surfaces were changed:

- `src/diet_bot/pdf_renderer.py`
- `tests/test_pdf_renderer.py`
- `scripts/dev/pdf_renderer_recovery_smoke.py`
- `docs/recovery-integration/pdf-renderer-transfer.md`

No Telegram UI, payments, subscriptions, runtime, storage, queue, recovery, preflight, or monitoring modules were edited.

## Pre-Transfer Gate

- Current branch: `codex/recover-product-ui-on-hardened-master`.
- Initial `git status --short` contained only expected Stage 2 data/assets/tests/docs changes.
- No unexpected edits were present in `src/diet_bot/telegram_app.py`, `src/diet_bot/payments.py`, `src/diet_bot/subscriptions.py`, or runtime/storage/recovery/monitoring modules.
- Product `pdf_renderer.py` was inspected before porting. Its public API matched master:
  - `build_week_plan_pdf(plans, plan_dates, output_dir=None)`
  - `render_week_plan_pdf(plans, plan_dates, output_path)`
  - `resolve_local_meal_image_path(meal)`
- Product renderer did not require old storage/runtime, Telegram handlers, payment state, or incompatible API. The transfer was therefore limited to visual PDF rendering behavior.

## PDF Difference Map

Before changes, product differed from master in these areas:

| area | product behavior | transfer decision |
|---|---|---|
| layout | Separate branded cover, stronger day pages, denser recipe/card layout, more whitespace control | Port visual structure while keeping master render entry points |
| typography | Smaller body/table fonts, stronger title hierarchy, right-aligned day date, badge labels | Port style changes and new style names |
| logo/QR usage | Uses `foodbalance_pdf_logo.png`, `foodbalance_pdf_qr.png`, and `@FOODBALANCERU_BOT` on cover | Port asset paths and cover placement |
| cover/header/footer | Product cover has logo, metric cards, notice, drinks note, QR, fine print; footer paints soft page background | Port cover/footer; keep master SimpleDocTemplate contract |
| recipe photos | Product scales/crops local recipe images and places them beside short steps | Port local photo scaling/cropping and recipe media layout |
| page breaks | Product separates cover/content/shopping more clearly | Port cover-to-day and shopping page breaks; did not introduce Telegram/runtime coupling |
| colors/branding | Product green `#2F6B48`, soft green cards, cream page background, warning box | Port palette |
| limits/safety behavior | Keeps local image resolution tolerant; missing image failures do not abort PDF; failed render removes new partial output | Preserve master-compatible missing-photo and cleanup behavior |
| public API/signatures | Same public renderer API as master | Preserve master API |

## Transferred Product PDF Appearance

- Branded cover with Food Balance logo, product green palette, QR code, bot handle, summary metric cards, notice box, drinks note, and fine print.
- PDF brand asset constants:
  - `PDF_LOGO_PATH`
  - `PDF_QR_PATH`
- Optional Pillow-based cleanup for logo/photo rendering:
  - transparent logo edge cleanup;
  - local photo crop/scale before embedding.
- Product-style recipe layout:
  - meal type pill;
  - recipe title header;
  - nutrition badges;
  - ingredient table with product/amount/kitchen measure columns;
  - numbered recipe steps;
  - photo placement beside short recipes.
- Product-style daily totals:
  - colored percent cells instead of dot markers;
  - thresholds: green at `>= 95%`, yellow at `>= 45%`, red below that.
- Shopping heading/copy changed to product language: `Список продуктов на неделю`.
- Softer page background, footer rendering, tighter table typography, and section spacing.

## Master Behaviors Preserved

- Master public API and call contract for `telegram_app.py` remained unchanged.
- `build_week_plan_pdf()` still writes to a temp/output directory, returns a `Path`, and removes a newly created failed output.
- `render_week_plan_pdf()` still validates non-empty plans and matching dates.
- `resolve_local_meal_image_path()` still rejects remote URLs and resolves only local data/project paths.
- Missing or unreadable meal photos remain non-fatal.
- No Telegram/payment/runtime/storage imports were added to the renderer.
- Existing curated data/photo tests continue to pass against the transferred Stage 2 assets.

## Tests And Checks

Passed:

- Red/green PDF test gate:
  - Added `test_week_pdf_uses_product_brand_assets_and_new_recipe_photo`.
  - It initially failed because master renderer had no `PDF_LOGO_PATH`.
  - It passed after the PDF appearance transfer.
- `pytest tests/test_pdf_renderer.py -q`
  - `6 passed in 17.24s`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `238 passed in 69.39s`
- `git diff --check`
  - exit code `0`
  - only line-ending warnings for existing Windows checkout behavior.

Smoke render:

- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
  - verified logo/QR assets;
  - verified local photos for all `r401-r610`;
  - rendered all new recipes in weekly-sized chunks.
- `python scripts/dev/weekly_pdf_profile.py --runs 1 --keep-pdfs --output-dir tmp/weekly_pdf_profile --no-page-count`
  - `build_week_plan_pdf/render: 2.781s`
  - `pdf: 4.17 MiB`
  - `images=35/35 unique`
  - `missing_images=0`
  - `branded_assets=2/2 unique`

Visual preview:

- `pdftoppm` was not installed in this environment.
- PyMuPDF rendered PNG previews from the profile PDF instead.
- Visual spot-check of pages 1-2 showed:
  - cover logo/metric cards/notice/QR/fine print render correctly;
  - first day page has header, pills, badges, ingredient tables, recipe photo, and footer without obvious overlap.

## Artifacts

- Range smoke PDFs:
  - `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-01.pdf`
  - `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-08.pdf`
  - directory: `tmp/pdf-renderer-recovery-smoke/`
- Existing weekly profile PDF:
  - `tmp/weekly_pdf_profile/foodbalance-week-2026-05-30-56bc2e52.pdf`
- PNG previews:
  - `tmp/pdf-renderer-preview/weekly-profile-page-1.png`
  - `tmp/pdf-renderer-preview/weekly-profile-page-2.png`

## Remaining Risks For Later Stages

- Telegram UI stage must still wire product copy/buttons without bypassing master private-chat, durable job, idempotency, safe-send, and media-validation behavior.
- Payment/subscription stages remain untouched; product pricing, promo, Stars auto-renew, YooKassa wording, and reconciliation semantics still need a separate manual integration.
- Production preflight/healthcheck may later need explicit logo/QR asset checks, but those modules were intentionally not edited in this PDF-only stage.
- The visual target is product-like and smoke-rendered, not pixel-identical to the old product branch.
