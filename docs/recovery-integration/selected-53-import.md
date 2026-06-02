# Selected 53 Import Report

Date: 2026-05-31

## Scope

Imported only rows from `staging_recipes/selected-53/review-table.csv` with `ready_for_import=yes`.

- Staging rows checked: 52
- Imported rows: 45
- Skipped rows left out: 7
- Production recipe range added: `r666` through `r710`
- Production nutrition rows added: 45
- Production ingredient rows added: 348
- Production photos added: `src/diet_bot/data/recipe_photos/r666.jpg` through `r710.jpg`

No bot, Telegram API, production DB, payment provider, deploy, push, commit, tag, PR, archive, recovered-bot, secrets/env-file, payment/subscription/runtime refactor, or adjacent UX/PDF/security fix was run.

## Validation Summary

- Ready count: confirmed exactly 45.
- Skipped count: confirmed exactly 7 and none intersect the imported source IDs.
- Photo check: every imported ready row had a `photo_path`; every source PNG opened successfully; each was converted into the existing production local JPG photo format.
- ID check: no `recipe_no`, `recipe_id`, or title conflict was found before import.
- Nutrition check: all 45 imported recipes calculated locally to `calculation_status=ok`; no unmatched ingredient rows remained.
- Data format: existing production JSON files were preserved and appended using the current curated recipe, ingredient, nutrition, and local photo conventions.

Import normalization needed for existing production/audit contracts:

- `R62` user-facing `эдамаме` text was normalized to `зеленый горошек`, matching the existing no-user-facing-edamame curated-data contract.
- Unquantified salt, pepper, spice, lemon juice, and sesame garnish rows received small local defaults plus approximate measure text.
- Two short OCR instruction fragments were expanded: `Охладить` and `Посолить`.
- OCR temperature text `220 0 С` was normalized to `220 °C`.

## Imported Rows

| Recipe No | Source | Title | Photo |
| --- | --- | --- | --- |
| 666 | R89 | Белковые фаршированные мини-перцы с лососем | `recipe_photos/r666.jpg` |
| 667 | R42 | Бургер в хрустящем листе айсберга | `recipe_photos/r667.jpg` |
| 668 | R43 | Бургер в чесночной йогуртовой булочке | `recipe_photos/r668.jpg` |
| 669 | R80 | Зелёная окрошка на минералке с лососем | `recipe_photos/r669.jpg` |
| 670 | R75 | Классическая окрошка на квасе с говяжьим языком | `recipe_photos/r670.jpg` |
| 671 | R41 | Лахмаджун | `recipe_photos/r671.jpg` |
| 672 | R56 | Молодая морковь с йогуртом и фисташками | `recipe_photos/r672.jpg` |
| 673 | R79 | Окрошка fit с индюшачьей колбасой | `recipe_photos/r673.jpg` |
| 674 | R77 | Окрошка на кефире и минералке с индейкой | `recipe_photos/r674.jpg` |
| 675 | R78 | Окрошка на мацони с курицей | `recipe_photos/r675.jpg` |
| 676 | R71 | Салат из печёного перца и творога | `recipe_photos/r676.jpg` |
| 677 | R69 | Салат из цукини с пармезаном и руколой | `recipe_photos/r677.jpg` |
| 678 | R68 | Свёкла с йогуртом, фисташками и апельсином | `recipe_photos/r678.jpg` |
| 679 | R45 | Такос на домашней чечевичной лепёшке | `recipe_photos/r679.jpg` |
| 680 | R85 | Томатная овсянка с яйцом пашот | `recipe_photos/r680.jpg` |
| 681 | R62 | Тёплый салат из брокколи и зеленый горошек | `recipe_photos/r681.jpg` |
| 682 | R67 | Тёплый салат с кальмарами, сельдереем и апельсином | `recipe_photos/r682.jpg` |
| 683 | R84 | Холодный суп из авокадо и зелёного горошка | `recipe_photos/r683.jpg` |
| 684 | R59 | Хрустящая зелёная фасоль с кунжутным йогуртом | `recipe_photos/r684.jpg` |
| 685 | R91 | Хрустящие роллы из рисовой бумаги с креветкой | `recipe_photos/r685.jpg` |
| 686 | R52 | Цветная капуста целиком с зелёным соусом | `recipe_photos/r686.jpg` |
| 687 | R138 | Лёгкие ленивые вареники | `recipe_photos/r687.jpg` |
| 688 | R375 | Макаронник с куриным филе | `recipe_photos/r688.jpg` |
| 689 | R132 | Салат с семгой, перепелиными яйцами и помидорами черри | `recipe_photos/r689.jpg` |
| 690 | R357 | Салат Цезарь | `recipe_photos/r690.jpg` |
| 691 | R145 | Картошка, тушенная с куриными сердечками | `recipe_photos/r691.jpg` |
| 692 | R135 | Говяжья печень с отварным картофелем | `recipe_photos/r692.jpg` |
| 693 | R55 | Печёные перцы с белой фасолью и травами | `recipe_photos/r693.jpg` |
| 694 | R65 | Салат с огурцом, редисом и творожным кремом | `recipe_photos/r694.jpg` |
| 695 | R66 | Томатный салат с белой фасолью и базиликом | `recipe_photos/r695.jpg` |
| 696 | R64 | Тёплый салат с чечевицей и томатами | `recipe_photos/r696.jpg` |
| 697 | R44 | Бургер в пите с кунжутным йогуртом | `recipe_photos/r697.jpg` |
| 698 | R49 | Хрустящие рулеты из лаваша с креветкой | `recipe_photos/r698.jpg` |
| 699 | R76 | Веганская окрошка на квасе с нутом | `recipe_photos/r699.jpg` |
| 700 | R72 | Огуречный салат с мацони и грецким орехом | `recipe_photos/r700.jpg` |
| 701 | R81 | Гаспачо с белой фасолью | `recipe_photos/r701.jpg` |
| 702 | R61 | ПП-табуле с булгуром и зеленью | `recipe_photos/r702.jpg` |
| 703 | R142 | Горбуша стейки с вареным картофелем и овощной нарезкой | `recipe_photos/r703.jpg` |
| 704 | R156 | Питьевой йогурт с яблоком или грушей | `recipe_photos/r704.jpg` |
| 705 | R123 | Омлет с сыром | `recipe_photos/r705.jpg` |
| 706 | R152 | Салат из кальмаров и яиц | `recipe_photos/r706.jpg` |
| 707 | R402 | Фрикасе из курицы и грибов | `recipe_photos/r707.jpg` |
| 708 | R238 | Бутерброды с сыром и слабосолёной сёмгой | `recipe_photos/r708.jpg` |
| 709 | R250 | Куриная запеканка под сыром | `recipe_photos/r709.jpg` |
| 710 | R185 | Плов с говядиной | `recipe_photos/r710.jpg` |

## Skipped Rows

| Source | Title | Reason |
| --- | --- | --- |
| R87 | Хрустящие творожно-кабачковые оладьи | User requested duplicate to be removed/skipped. |
| R120 | Грудка индейки с рисом и овощной нарезкой | User requested deletion. |
| R190 | Грудка индейки с рисом и овощной нарезкой | User requested deletion. |
| R40 | Шаурма фит | User requested deletion. |
| R70 | Хрустящий салат с брокколи и нутом | User requested deletion. |
| R522 | Сырно-творожная лепёшка | User requested deletion. |
| R388 | Творожный омлет | User requested deletion. |

## Checks

- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`: 247 passed.
- `python scripts/dev/recipe_content_audit.py --report-path tmp/selected-53-import/recipe-content-audit.md --csv-path tmp/selected-53-import/recipe-content-audit-findings.csv --fail-on-blocker`: `blocking_findings=0`, `warning_findings=1325`.
- `python scripts/dev/pdf_renderer_recovery_smoke.py`: `rendered_pdfs=8`, `recipes_checked=210`.
- `git diff --check`: passed; only existing LF-to-CRLF warnings were printed.

## Remaining Work

- Visual review of imported recipe/photo results.
- Final manual-smoke bot restart.
- Payment sandbox/provider smoke.
- New safety snapshot/commit.
- Deploy/VPS plan.
