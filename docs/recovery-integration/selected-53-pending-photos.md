# Selected-53 Pending Photos

Date: 2026-05-31

Scope: generated staging photos only for selected-53 rows that were user approved or edited and still had pending photo generation. No recipe import was run.

## Result

- Expected pending count: 11
- Pending rows found: 11
- Generated count: 11
- Failed count: 0
- Uncertain images needing visual review: none noted in contact-sheet review
- Final `ready_for_import=yes` count after photos: 45
- Remaining user-skipped rows: 7
- Remaining `needs_user_decision=yes` rows: 0

## Generated Photo Paths

- `staging_recipes/selected-53/photos/selected53_r56_molodaya_morkov_s_yogurtom_i_fistashkami.png`
- `staging_recipes/selected-53/photos/selected53_r62_teplyy_salat_iz_brokkoli_i_edamame.png`
- `staging_recipes/selected-53/photos/selected53_r67_teplyy_salat_s_kalmarami_seldereem_i_apelsinom.png`
- `staging_recipes/selected-53/photos/selected53_r59_hrustyaschaya_zelenaya_fasol_s_kunzhutnym_yogurtom.png`
- `staging_recipes/selected-53/photos/selected53_r91_hrustyaschie_rolly_iz_risovoy_bumagi_s_krevetkoy.png`
- `staging_recipes/selected-53/photos/selected53_r52_tsvetnaya_kapusta_tselikom_s_zelenym_sousom.png`
- `staging_recipes/selected-53/photos/selected53_r357_salat_tsezar.png`
- `staging_recipes/selected-53/photos/selected53_r145_kartoshka_tushennaya_s_kurinymi_serdechkami.png`
- `staging_recipes/selected-53/photos/selected53_r135_govyazhya_pechen_s_otvarnym_kartofelem.png`
- `staging_recipes/selected-53/photos/selected53_r44_burger_v_pite_s_kunzhutnym_yogurtom.png`
- `staging_recipes/selected-53/photos/selected53_r156_pitevoy_yogurt_s_yablokom_ili_grushey.png`

Temporary review contact sheet:

- `tmp/selected-53-photo-generation/selected53_pending_photos_contact_sheet.png`

## Staging Updates

- `photo-prompts.csv`: the 11 pending rows now have `photo_status=generated` and `photo_path` set to the generated PNG path.
- `review-table.csv`: the 11 pending rows now have `photo_status=generated`, `ready_for_import=yes`, and `photo_path` set. Existing generated rows were also joined to their existing `photo_path` for review-table completeness.
- `review-table.xlsx`: mirrored from the updated review table.
- `README.md`: counts updated for 49 generated/reused photos, 0 approved rows pending photo generation, and 45 rows ready for later import review.

## Verification

- All generated selected-53 image files exist and load.
- All `generated` photo rows in `photo-prompts.csv` load successfully.
- All approved non-skipped rows have a `photo_path`.
- `review-table.csv` still has 52 rows.
- No files under `src/diet_bot/data` were modified by this pass.
- No production code, bot run, deploy, push, commit, tag, PR, or recipe import was performed.
