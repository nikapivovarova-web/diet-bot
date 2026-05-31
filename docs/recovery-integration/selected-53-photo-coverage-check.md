# Selected 53 Photo Coverage Check

Date: 2026-05-31

## Scope

Checked the current staging pack only:

- Review table: `staging_recipes/selected-53/review-table.csv`
- Photo folder: `staging_recipes/selected-53/photos/`

No import was run. No photos were generated. No recipe/code/data files were changed.

## Counting Rules

- Total recipes: data rows in `review-table.csv`.
- Ready rows: `ready_for_import == yes` or `user_decision == APPROVE_IMPORT`.
- Needs user decision rows: `needs_user_decision == yes`.
- Generated photo-status rows: `photo_status == generated`.
- Photo matching: recipe ID `R...` from `source_id` matched to photo filename prefix `selected53_r..._`.

## Results

- Total recipe rows: 52
- Ready rows: 34
- `needs_user_decision` rows: 18
- Rows with `photo_status == generated`: 38
- Photo files in `photos/`: 38
- Ready rows without matching photo file: 0
- Photo files without a ready row: 4

## Ready Rows Missing Photos

None. All 34 current ready rows have matching files in `photos/`.

## Photos Without Ready Row

These photo files exist, but their review-table rows are not currently ready for import:

| Recipe ID | Photo file |
| --- | --- |
| R40 | `selected53_r40_shaurma_fit.png` |
| R87 | `selected53_r87_hrustyaschie_tvorozhno_kabachkovye_oladi.png` |
| R388 | `selected53_r388_tvorozhnyy_omlet.png` |
| R522 | `selected53_r522_syrno_tvorozhnaya_lepeshka.png` |

All four rows are marked `ready_for_import == no`, `needs_user_decision == yes`, and `photo_status == generated`.

## Import Readiness From Photo Coverage Only

No additional photo generation is needed before importing the current ready set of 34 recipes.

If more `needs_user_decision` rows are later approved for import, photo coverage should be rechecked at that time. Four non-ready rows already have generated photos, while the remaining non-ready rows currently have `photo_status == not_applicable_until_decision`.

## Guardrails Confirmed

This was a photo coverage check only. It did not import recipes, generate photos, edit production code, edit curated data, or change staging CSV/JSON/XLSX recipe data.
