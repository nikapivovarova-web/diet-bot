# Selected 53 user decisions applied

Date: 2026-05-31

## Scope

Applied the 18 user decisions from:

- `C:\Users\adck8\Documents\selected-53-user-decision-guide.md`
- `C:\Users\adck8\Documents\selected-53-user-decision-guide.csv`

Changes were limited to `staging_recipes/selected-53/*`, this report, and `tmp/selected-53-user-decisions/*`. No import was run.

## Final counts

- Decisions applied: 18
- Final `ready_for_import=yes`: 34
- Final `SKIP` / not for import: 7
- Final `needs_user_decision=yes`: 0
- User-approved/edited rows pending photo generation: 11
- Nutrition pending/not calculated rows: 52
- Nutrition rows still blocked by quantity review: 0

## Recipes edited or approved

- R56 — масло авокадо заменено на рафинированное растительное масло.
- R357 — яйца оставлены как в рецепте; батон для сухариков задан как 60 г, шаг сухариков уточнен.
- R145 — картофель 150 г подтвержден.
- R135 — добавлен картофель 150 г и шаги для отварного картофеля.
- R156 — сахзам удален; перекус оформлен как питьевой йогурт с яблоком или грушей.
- R62 — эдамаме оставлены.
- R91 — рисовая бумага оставлена.

## Replacements made

- R67 — фенхель заменен на стеблевой сельдерей 200 г; название и шаги обновлены.
- R59 — тахини заменена на молотый кунжут 20 г.
- R52 — рисовое масло заменено на рафинированное растительное, тахини заменена на молотый кунжут.
- R44 — тахини заменена на молотый кунжут, томаты заданы как 200 г; название и шаги обновлены.

## Replacements not possible and skipped

None. All four requested replacement attempts had direct product-safe substitutions inside the guide options.

## Skipped by user decision

- R87 — SKIP as duplicate.
- R120 — SKIP.
- R190 — SKIP.
- R40 — SKIP.
- R70 — SKIP.
- R522 — SKIP.
- R388 — SKIP.

Skipped rows were retained in staging for traceability and are not marked for import. Existing skipped-row photos, where already present, were left in place.

## Photos

- Reused/kept existing PNG files: 38
- Regenerated photos: 0
- Pending generation for newly approved/edited rows: 11
- Not required because skipped: 3

Newly approved/edited rows without an existing PNG remain `ready_for_import=no`, `needs_user_decision=no`, `photo_status=pending_generation`. This keeps the current strict ready set valid: every `ready_for_import=yes` row still has a photo path and file.

## Import recommendation

Do not import this staging pack yet as a whole. The current strictly ready set is 34 rows. The 11 newly approved/edited rows should be imported only after their photos are generated and verified, and after the normal nutrition calculation/mapping pass. The 7 SKIP rows should not be imported.

## Guardrails

- No production curated data was edited.
- No production code was edited.
- No PDF, Telegram, payments, runtime, bot, deploy, commit, push, tag, or PR action was run.
- Source workbook was not deleted or modified.
