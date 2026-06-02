# Selected 53 Staging Pack

Source file: `C:\Users\adck8\Desktop\РЕЦЕПТЫ НОВЫЕ 30.05.xlsx`

This staging pack prepares the selected recipes for later re-review only. User decisions for 18 disputed rows were applied inside the staging pack only. No FoodBalance curated data, production code, bot runtime, Telegram, PDF, payments, deploy, git push, commit, tag, PR, or recipe import was changed.

## Counts

- Parsed recipes: 52
- Source count note: Source workbook contains 52 non-empty data rows, although the task label says 53 selected recipes.
- Ready for later import re-review: 45
- User-approved/edited rows pending photo generation: 0
- User-skipped / not for import: 7
- Needs user decision: 0
- User decisions applied in this pass: 18
- Photos generated/reused: 49
- Photos pending generation for approved rows: 0
- Photos not required because row is skipped: 3
- Photos generated in this pass: 11
- Photos regenerated in this pass: 0
- Review workbook: `review-table.xlsx`

## Nutrition

Precise nutrition was not invented. The source workbook did not provide authoritative nutrition values. Each recipe has a `nutrition_status` in `recipes.json`; normalized ingredients are ready for a later calculation pass.

Nutrition status summary:
- pending_estimation_needed: 51
- not_calculated_standalone_snack: 1
- pending_needs_quantity_review: 0
- total pending/not calculated: 52

## Photos

Existing PNG files were reused and verified separately. The 11 user-approved or edited rows that were missing photos now have generated PNG files under `photos/`, `photo_status=generated`, and `ready_for_import=yes`. No recipes were imported.

## User Review

All 18 disputed rows from the decision guide now have `needs_user_decision=no`. Skipped rows are retained in staging with `user_decision=SKIP ...` for traceability and are not marked for import.

## Later Import Step

A separate import task should use only rows with `ready_for_import=yes`. This staging photo-generation pass prepares the remaining approved/edited rows for later import review, but does not import recipes. Do not treat this staging pass as an import.
