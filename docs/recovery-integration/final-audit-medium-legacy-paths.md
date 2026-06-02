# Final Audit MEDIUM-2: Root-Level Legacy Paths

Date: 2026-05-31

Verdict: closed locally.

## Scope

- Workdir: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- Initial status: dirty before this MEDIUM-2 pass, with existing runtime,
  payment, recipe, test, recovery-doc, selected-53 photo, and staging changes.
- This pass stayed limited to root-level legacy workbook/photo utilities,
  focused legacy-root tests, the CI compile step, and these recovery docs.

## Root Cause

Several root-level one-off workbook/photo maintenance utilities had been left
at the release root with workstation-specific paths under local Desktop,
`New project 2\outputs`, and generated-image folders. Some of them performed
work immediately when run without arguments, so accidental execution from the
release checkout could read or rewrite external local workbook/photo artifacts.

The first MEDIUM-2 pass fixed only `apply_editorial_notes.py` and
`combine_fixed_400.py`. A broader root-level scan found the same class in the
remaining Python utilities and Node workbook helpers.

## Additional Risky Files Found

- `analyze_recipes.mjs`
- `apply_generated_rebuild_photos.py`
- `apply_grid_generated_photos.py`
- `compare_recipe_workbooks.mjs`
- `extract_notes.mjs`
- `final_check.mjs`
- `image_map.py`
- `inspect_recipes.mjs`
- `list_rebuilt_titles.py`
- `list_recipe_titles.mjs`
- `make_photo_contact_sheet.py`
- `make_photo_final_contact_sheet.py`
- `make_rebuild_photo_contact_sheets.py`
- `make_rebuild_target_contact_sheet.py`
- `polish_final_text.py`
- `rebuild_400_from_original_photos.py`
- `render_photo_workbook_checks.mjs`
- `repair_workbook_open_view.py`
- `replace_replaced_recipe_photos.py`
- `restore_final_hyperlinks.py`
- `scale_recipes_1_200.py`
- `verify_final_400.mjs`
- `verify_photo_workbook_integrity.py`
- `verify_rebuilt_workbook.py`
- `verify_recipes.mjs`

## Fix

- Removed hard-coded local/external workbook, photo, preview, report, generated
  image, Desktop, and `New project 2\outputs` defaults from the root-level
  legacy utilities.
- Added explicit CLI path arguments to every risky root utility.
- Added fail-closed no-argument behavior: running any covered utility without
  required paths exits with argparse/usage status before workbook/photo I/O.
- Added `--allow-external` gates for paths outside this repository.
- Converted Node workbook helpers to load `@oai/artifact-tool` only after CLI
  validation, so no-argument execution fails closed even when that optional
  local package is unavailable.
- Extended `tests/test_legacy_root_scripts.py` to cover the whole found
  root-level class, not only the first two scripts.
- Expanded CI compile coverage from two root utilities to all root `.py`
  utilities and root/script `.mjs` syntax checks.

## Scan Classification

Release-relevant risk is closed for root-level legacy utilities:

- Root-level `.py` and `.mjs` utility scan for `C:\Users`, `C:/Users`,
  `New project 2`, `FoodBalance-ARCHIVE`, `FoodBalance-RECOVERED`, and
  `outputs`: no matches.

Remaining broad-scan matches are non-risk for this finding:

- Historical recovery docs and design/evidence docs preserve prior absolute
  paths.
- `.git` contains the linked-worktree admin pointer.
- `tests/test_legacy_root_scripts.py` intentionally contains the forbidden
  patterns as regression literals.
- `scripts/build_curated_recipe_data.py`,
  `scripts/build_curated_recipe_workbook.mjs`, and
  `scripts/export_curated_recipe_photos.py` use repo-relative `outputs`
  paths, not workstation-local external defaults.

## Checks

- RED before implementation:
  `python -m pytest tests\test_legacy_root_scripts.py -q`
  - `26 failed, 2 passed`; failures showed hard-coded paths still present,
    Python no-argument utilities executing immediately, and Node helpers
    failing through optional dependency import instead of usage.
  - Important note: because the old behavior was unsafe, this RED command
    invoked several legacy no-argument scripts before the quarantine existed.
    That confirmed the risk but also caused those old external local utility
    targets to be touched. No app/runtime code, recipe data/imports/photos in
    this repository, bot process, Telegram API, production DB, payment/provider,
    sales follow-up, deploy, push, commit, tag, PR, archive, `New project 2
    CLEAN`, or recovered-bot work was intentionally performed.
- `python -m pytest tests\test_legacy_root_scripts.py -q`
  - `28 passed`
- `python -m compileall -q` over `src`, `scripts`, `tests`, and root `.py`
  utilities using explicit PowerShell path expansion
  - exit code `0`
- Root `.mjs` syntax check with `node --check`
  - exit code `0`
- Root-level `.py`/`.mjs` risky path scan
  - no matches

## Release Count

MEDIUM-2 is closed locally. Current local final pre-release audit count is now
`0` high, `1` medium, and `6` low.

Remaining medium finding:

- `MEDIUM-3` core import cycles.

## Not Touched

No MEDIUM-3 import-cycle work, app/runtime refactor, recipe data/import change,
bot start, Telegram API/getUpdates call, production DB, payment/provider/refund
path, sales follow-up behavior, deploy, push, commit, tag, PR, archive,
`New project 2 CLEAN`, or recovered-bot work was performed.

## Next Recommended Prompt

FoodBalance: fix MEDIUM-3 core import cycles only.

Scope:

- Work only in `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`.
- Read `docs/recovery-integration/final-pre-release-audit.md`,
  `docs/recovery-integration/recovery-status.md`, and current import-cycle
  evidence first.
- Do not touch MEDIUM-2, runtime behavior beyond import-cycle isolation, recipe
  data/imports/photos, bot startup, Telegram API/getUpdates, production DB,
  payments/provider/refunds, sales follow-up, deploy, push, commit, tag, PR,
  archive, `New project 2 CLEAN`, or recovered bot.
