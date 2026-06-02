# Round 2 Manual Smoke Ready

Date: 2026-05-30

Workspace: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`

Branch: `codex/recover-product-ui-on-hardened-master`

HEAD: `aa8336a250d0357e819904e0786abfbf1c0ea108`

## Summary

Round 2 fixes prepared for repeated manual smoke:

- Privacy consent now appears before questionnaire collection, instead of adding a privacy-policy inline button to each normal question.
- Telegram menu/photo smoke expectations were aligned with the current promo/privacy/support menu.
- PDF recipe photos use the fixed stacked layout path with reserved image space.
- High-suspicion recipe content fixes are applied for the documented batch, including hummus consistency, no user-facing harissa/American-cheese/edamame exposure, and the cod-liver-salad examples.
- Confident approximate household measures were added/normalized for common gram-only rows; ambiguous rows remain documented.

No deploy, push, PR, tag, commit, production webhook, payment action, refund, chargeback, archive work, `New project 2 CLEAN` work, or recovered-bot work was performed in this verification pass.

## Verification Results

- `git status --short` before verification: dirty integration worktree with existing Round 2/stage changes.
- `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py -q` -> `48 passed in 40.14s`.
- `pytest tests/test_pdf_renderer.py -q` -> `12 passed in 15.19s`.
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q` -> `244 passed in 91.18s`.
- `python scripts/dev/recipe_content_audit.py` -> blockers `0`, warnings `1221`.
- `python scripts/dev/pdf_renderer_recovery_smoke.py` -> `rendered_pdfs=8`, `recipes_checked=210`.
- `python -m diet_bot.healthcheck` with safe local dummy token and `PYTHONPATH=src` -> `issues: none`.
- `git diff --check` -> exit code `0`; Git printed only existing LF-to-CRLF checkout warnings.
- `pytest -q` full suite was attempted after targeted checks passed, but was stopped after a 20 minute timeout without a complete result. Previous completed full-suite status remains documented in `docs/recovery-integration/recovery-status.md` as `890 passed, 115 skipped`.

Healthcheck note: the first plain `python -m diet_bot.healthcheck` attempt failed before app execution because the shell did not include `src` on `PYTHONPATH`; the safe rerun with `PYTHONPATH=src` passed.

## Recipe Audit

Latest audit:

- `recipes_checked=665`
- `ingredients_checked=6130`
- `foods_checked=359`
- `nutrition_rows_checked=665`
- `blocking_findings=0`
- `warning_findings=1221`
- `title_ingredient_mismatch.warnings=0`
- `steps_mention_missing_ingredient.warnings=0`
- `non_cis_unclear_ingredients.warnings=0`
- `tiny_gram_anomalies.warnings=0`
- `missing_approximate_measures.warnings=133`

Remaining warnings are known limitations for manual/content review, mostly broad ingredient-step morphology/wording heuristics and intentionally unresolved ambiguous approximate-measure rows.

## PDF Smoke And Preview

Fresh smoke PDFs:

- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-01.pdf`
- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-02.pdf`
- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-03.pdf`
- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-04.pdf`
- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-05.pdf`
- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-06.pdf`
- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-07.pdf`
- `tmp/pdf-renderer-recovery-smoke/recovery-r401-r610-08.pdf`

Final PNG preview folder:

- `tmp/pdf-qa-round2-final-preview/`

Representative previews:

- `tmp/pdf-qa-round2-final-preview/recovery-r401-r610-01-p02-photo-after-ingredients.png`
- `tmp/pdf-qa-round2-final-preview/recovery-r401-r610-01-p03-long-recipe-start.png`
- `tmp/pdf-qa-round2-final-preview/recovery-r401-r610-01-p04-long-recipe-image-steps-next-page.png`
- `tmp/pdf-qa-round2-final-preview/recovery-r401-r610-01-p28-cod-liver-salad-previous-example.png`
- `tmp/pdf-qa-round2-final-preview/recovery-r401-r610-01-p30-shopping-list.png`
- `tmp/pdf-qa-round2-final-preview/recovery-r401-r610-01-p31-shopping-list-continued.png`

Additional targeted example PDF and previews for manually inspectable previous cases:

- `tmp/pdf-qa-round2-final-preview/targeted-examples-r357-r359-r595-r604.pdf`
- `tmp/pdf-qa-round2-final-preview/targeted-examples-r357-r359-r595-r604-p01.png`
- `tmp/pdf-qa-round2-final-preview/targeted-examples-r357-r359-r595-r604-p02.png`
- `tmp/pdf-qa-round2-final-preview/targeted-examples-r357-r359-r595-r604-p03.png`
- `tmp/pdf-qa-round2-final-preview/targeted-examples-r357-r359-r595-r604-p04.png`
- `tmp/pdf-qa-round2-final-preview/targeted-examples-r357-r359-r595-r604-p05.png`
- `tmp/pdf-qa-round2-final-preview/targeted-examples-r357-r359-r595-r604-p06.png`
- `tmp/pdf-qa-round2-final-preview/targeted-examples-r357-r359-r595-r604-p07.png`

Preview pixel check: all rendered PNGs are `1191x1684` and nonblank.

## Current Git Status Summary

Current worktree remains dirty as expected for the integration branch:

- Modified tracked paths: `38`
- Untracked paths: `217`
- Other short-status categories: `0`

Notable untracked groups include `docs/recovery-integration/`, `scripts/dev/pdf_renderer_recovery_smoke.py`, `scripts/dev/recipe_content_audit.py`, `src/diet_bot/data/foodbalance_pdf_logo.png`, `src/diet_bot/data/foodbalance_pdf_qr.png`, recipe photos `r401.jpg` through `r610.jpg`, and Telegram smoke tests.

## Remaining Known Limitations

- Full `pytest -q` was not completed in this pass because it exceeded 20 minutes; targeted verification passed and previous completed full-suite status is documented.
- No disposable Postgres integration test database was provided, so live Postgres integration tests remain unrun in this pass.
- Privacy consent acceptance is intentionally process-memory based; after a bot restart a user may see the consent screen again.
- PDF visual overlap cannot be mathematically proven by unit tests; this pass relies on PDF smoke generation plus rendered PNG previews.
- Recipe audit still reports `1221` warnings, including `133` missing approximate-measure warnings intentionally left for ambiguous categories.
- Do not perform real payments yet.

## Integration Bot Restart

Completed safely after verification.

- Previous manual-smoke PID file pointed to `45240`.
- Process `45240` was stopped only after its executable path and command line confirmed the current integration worktree and `diet_bot.telegram_app`.
- Its child `45168` exited with the confirmed parent; no recovered-bot process was stopped.
- New integration parent PID: `43144`.
- Observed child PID: `42960`.
- `getMe` check: `FoodbalanceRu_bot` (`8683450754`).
- stdout log: `tmp/manual-smoke-run/bot-integration-smoke.stdout.log`
- stderr log: `tmp/manual-smoke-run/bot-integration-smoke.stderr.log`
- PID file: `tmp/manual-smoke-run/bot-integration-smoke.pid.txt`
- Env summary: `tmp/manual-smoke-run/bot-integration-smoke-env-summary.txt`

Safe startup settings recorded in the env summary:

- `DIET_BOT_ENV=manual-smoke`
- `DIET_BOT_STORAGE_BACKEND=postgres`
- `DIET_BOT_ALLOW_JSON_STORAGE=0`
- `DIET_BOT_DATABASE_URL=postgresql://diet_bot@localhost:5432/diet_bot_integration_manual_smoke`
- `DIET_BOT_PAYMENTS_ENABLED=0`
- `DIET_BOT_PUBLIC_PAYMENTS_ENABLED=0`
- `DIET_BOT_PAYMENT_TEST_PRICES_ENABLED=0`
- `TELEGRAM_PROVIDER_TOKEN=absent`
