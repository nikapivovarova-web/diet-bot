# Recipe Intake Validation

Scope: dry-run validation for `tmp/recipe_intake/cleaned_recipes.xlsx`. No production curated data, builder, PDF, Telegram, promo, payments, storage, or photo assets were changed.

## Summary

- Workbook rows: 105 recipes, 843 ingredient rows, 454 step rows, 156 existing QA issue rows.
- Structural shape is good: recipe keys are unique, required top-level recipe fields are filled, every recipe has ingredients and steps, `photo_prompt_ru` is filled, and all `servings_cleaned` values are `1`.
- Import readiness is not clean: 74 / 105 recipes need manual cleanup before a safe full import.
- Main blockers are nutrition mapping/calculation gaps (69 recipes), protein-anchor gaps (6 rows), core/ambiguous gram issues (90 rows total), and ingredient-vs-step mismatches (24 recipes with step-mentioned ingredients not listed).
- Recommendation: **fix workbook first**. Do not import all 105 as-is. A future subset import is possible only after mapping/anchor/ingredient consistency fixes are applied and revalidated.

## Pass/Fail Counts

| Check | Result | Count |
|---|---:|---:|
| Workbook structure | PASS | 0 |
| Ingredient-vs-steps: missing ingredients in sheet | FAIL | 24 |
| Ingredient-vs-steps: listed but not used warnings | PASS | 352 |
| Portion consistency | FAIL | 2 |
| Text cleanliness | PASS | 0 |
| Gram/unit quality | FAIL | 90 |
| Nutrition mapping/calculation readiness | FAIL | 69 |
| Protein anchors | FAIL | 6 |
| Step detail | FAIL | 1 |

## Blockers

- 74 recipes have at least one blocker-class issue for import readiness.
- 78 non-minor ingredient rows do not map with the existing product alias logic. This prevents reliable KBJU calculation unless the importer gets explicit `food_id` mapping or the names are normalized.
- 69 recipes cannot be fully calculated with current nutrition IDs and grams.
- 6 obvious protein rows are not marked as `is_protein_anchor=yes`.
- 24 recipes mention ingredients in steps that are not present on the ingredient sheet under the current matching heuristic.
- 2 portion-text issues need review.

## Warnings

- 352 listed ingredient rows were not found in steps. Some are likely legitimate serving/garnish rows, but they should be reviewed before import.
- 1 recipes have too few steps for their active time, ingredient count, or `interesting` effort.
- 14 possible duplicate candidates with existing curated recipes were found by fuzzy title/token matching.

## Recipes Requiring Manual Cleanup

| Recipe | Issues |
|---|---|
| `intake_001` — Фаршированные перцы с рисом и овощами в духовке | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_003` — Омлет с творогом и зеленью | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `missing_grams_estimate` |
| `intake_004` — Котлеты из индейки с цукини и овощами на гарнир | `cannot_calculate_nutrition`, `mapping_gap`, `step_mentions_unlisted_ingredient` |
| `intake_005` — Белковый салат с тунцом, яйцом и свежими овощами | `cannot_calculate_nutrition`, `missing_grams_estimate` |
| `intake_006` — Бутерброд с сыром и ветчиной | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_009` — Рикотта с фруктами | `step_mentions_unlisted_ingredient` |
| `intake_015` — Смесь орехов | `batch_instruction` |
| `intake_016` — Цельнозерновой хлеб с печенью трески | `cannot_calculate_nutrition`, `mapping_gap`, `step_mentions_unlisted_ingredient` |
| `intake_020` — Ленивый хачапури по-аджарски | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_021` — Гречка с запеченной индейкой и свекольным салатом | `cannot_calculate_nutrition`, `mapping_gap`, `step_mentions_unlisted_ingredient` |
| `intake_022` — Шпинатный овсяноблин с семенами чиа | `protein_anchor_missing` |
| `intake_024` — Салат из печени трески с яйцом | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate` |
| `intake_025` — Салат из печени трески с огурцом и картофелем | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate` |
| `intake_026` — Салат из печени трески с луком | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_027` — Салат из консервированной печени трески | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_028` — Домашний салат из печени трески с зеленым горошком | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate`, `package_unit_without_grams` |
| `intake_029` — Белковый салат с курицей | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `step_mentions_unlisted_ingredient` |
| `intake_030` — Белковый салат с фасолью | `cannot_calculate_nutrition` |
| `intake_032` — Салат с помидорами «Красное море» | `cannot_calculate_nutrition`, `mapping_gap`, `protein_anchor_missing`, `step_mentions_unlisted_ingredient` |
| `intake_035` — Кукурузная каша | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate`, `step_mentions_unlisted_ingredient` |
| `intake_036` — Ленивая овсянка с ягодами и орехами | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_037` — Творог с мёдом и фруктами | `step_mentions_unlisted_ingredient` |
| `intake_040` — Каша из киноа с фруктами | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_042` — Банановые оладьи с шоколадной начинкой | `amount_or_unit_leaked_into_ingredient_name`, `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate` |
| `intake_043` — Овсяные блинчики | `amount_or_unit_leaked_into_ingredient_name`, `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_047` — Скрэмбл из тофу | `cannot_calculate_nutrition`, `missing_grams_estimate`, `step_mentions_unlisted_ingredient` |
| `intake_048` — Цельнозерновой хлеб с паштетом из печени индейки | `cannot_calculate_nutrition`, `mapping_gap`, `step_mentions_unlisted_ingredient` |
| `intake_049` — Гречка по-купечески с фаршем | `cannot_calculate_nutrition`, `mapping_gap`, `step_mentions_unlisted_ingredient` |
| `intake_051` — Гуляш с гречкой | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_052` — Макароны с курицей и овощами на сковороде | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `missing_grams_estimate` |
| `intake_054` — Гуляш из куриной печени | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_055` — Рыба под маринадом | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_056` — Говядина в томатно-сметанном соусе | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate` |
| `intake_057` — Азу из индейки на сковороде | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_059` — Писто | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `missing_grams_estimate`, `step_mentions_unlisted_ingredient` |
| `intake_060` — Макароны с яйцом и сыром | `cannot_calculate_nutrition`, `mapping_gap`, `step_mentions_unlisted_ingredient` |
| `intake_061` — Бигус из свежей капусты | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_062` — Индейка с баклажанами в духовке | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `missing_grams_estimate` |
| `intake_063` — Салат с капустой, куриной грудкой и кунжутом | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate` |
| `intake_064` — Лосось, запеченный в фольге | `cannot_calculate_nutrition`, `missing_grams_estimate` |
| `intake_065` — Кальмары с картофелем и шпинатом | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `step_mentions_unlisted_ingredient` |
| `intake_066` — Шаурма из моркови | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_067` — Пирожки с яйцом и творогом | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_068` — Скрэмбл без яиц | `cannot_calculate_nutrition`, `missing_grams_estimate` |
| `intake_069` — Котлеты из нута | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate` |
| `intake_070` — Тофу-нори в кляре | `cannot_calculate_nutrition`, `missing_grams_estimate`, `step_mentions_unlisted_ingredient` |
| `intake_071` — Гороховый суп-пюре | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_072` — Тофу-стейки в терияки | `amount_or_unit_leaked_into_ingredient_name`, `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `package_unit_without_grams`, `step_mentions_unlisted_ingredient` |
| `intake_073` — Тилапия в духовке | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `step_mentions_unlisted_ingredient` |
| `intake_074` — Куриные котлеты с кабачком | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_077` — Стейк из форели с молодым картофелем | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate` |
| `intake_078` — Яйца по-флорентийски | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `serving_text_in_ingredient` |
| `intake_079` — Кускус с курицей | `cannot_calculate_nutrition`, `mapping_gap`, `step_mentions_unlisted_ingredient` |
| `intake_080` — Мясо по-тайски с лапшой | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_081` — Дорадо с рисом и яйцом пашот | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_082` — Стейк из индейки с фасолью | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `step_mentions_unlisted_ingredient` |
| `intake_083` — Кальмар, фаршированный сыром и курицей | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate`, `package_unit_without_grams`, `step_mentions_unlisted_ingredient` |
| `intake_084` — Курица с овощами по-деревенски | `cannot_calculate_nutrition`, `mapping_gap`, `step_mentions_unlisted_ingredient` |
| `intake_085` — Гуляш по-венгерски лёгкий | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `package_unit_without_grams` |
| `intake_086` — Эскалоп свиной с сыром | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `package_unit_without_grams` |
| `intake_087` — Курино-картофельные оладьи | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `mapping_gap`, `missing_grams_estimate`, `package_unit_without_grams`, `step_mentions_unlisted_ingredient` |
| `intake_090` — Бутерброд с ветчиной и омлетом | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_091` — Картофельные зразы с белыми грибами | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `package_unit_without_grams` |
| `intake_092` — Суп-пюре из батата | `cannot_calculate_nutrition`, `missing_grams_estimate` |
| `intake_093` — Шаурма с фалафелем | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `package_unit_without_grams` |
| `intake_094` — Лосось в сливочном соусе со шпинатом и голубым сыром | `cannot_calculate_nutrition`, `mapping_gap`, `missing_grams_estimate`, `package_unit_without_grams` |
| `intake_095` — Салат с шампиньонами и спаржей | `cannot_calculate_nutrition`, `mapping_gap` |
| `intake_096` — Карбонара с беконом и сливками | `cannot_calculate_nutrition`, `mapping_gap`, `protein_anchor_missing` |
| `intake_099` — Паста с креветками и соусом песто | `cannot_calculate_nutrition`, `missing_grams_estimate`, `step_mentions_unlisted_ingredient` |
| `intake_100` — Паста болоньезе | `cannot_calculate_nutrition`, `core_or_non_spice_po_vkusu`, `missing_grams_estimate` |
| `intake_101` — Паста с куриными колбасками в остром томатном соусе | `cannot_calculate_nutrition`, `mapping_gap`, `protein_anchor_missing` |
| `intake_102` — Паста с лососем и шпинатом в сливочном соусе | `cannot_calculate_nutrition`, `mapping_gap`, `protein_anchor_missing` |
| `intake_103` — Мак-энд-чиз | `protein_anchor_missing` |
| `intake_104` — Макароны по-флотски | `cannot_calculate_nutrition`, `mapping_gap`, `step_mentions_unlisted_ingredient` |

## Mapping Gaps

Unique unmapped ingredient names by current `build_curated_recipe_data.find_food_def` alias logic: 87. Non-minor unique names after ignoring salt/pepper/spice-like rows: 65.

Non-minor mapping gaps to fix or explicitly map:
- печень трески (5)
- крахмал кукурузный (3)
- сыр легкий (2)
- гречка сухая (2)
- орехи (2)
- говядина (2)
- соус соевый (2)
- филе куриной грудки (2)
- филе цыплёнка-бройлера кубиком (2)
- твёрдый сыр
- фарш из индейки
- сыр с высоким содержанием белка
- печень трески консервированная
- грудка индейки
- сыр твердый
- горошек зеленый
- виноград
- твердый сыр
- кукурузная крупа
- фрукты
- шоколадные чипсы
- печень индейки
- коньяк
- смешанный фарш
- куриная печень
- рыба минтай
- огурцы соленые
- сыр
- мясо
- кальмары
- сыр «Лёгкий»
- сухари панировочные
- горох колотый
- репа
- терияки
- для гарнира из моркови
- филе тилапии
- замороженная смесь «Овощи по-деревенски»
- белое сухое вино
- фарш из курицы или индейки
- стейк из радужной форели
- на 1 порцию
- бешамель
- свинина постная
- лапша удон
- дорадо горячего копчения
- стейк из индейки
- кальмар командорский тушки очищенные
- сыр «Голландский»
- филе бедра курицы
- смесь овощная «Три капусты»
- смесь овощная «Лечо по-венгерски», быстрозамороженная
- эскалоп свиной
- сыр тёртый «Три сыра»
- айсберг
- для начинки
- фалафель замороженный
- огурцы свежие
- сёмга филе на коже замороженное
- сыр с голубой плесенью
- виноград кишмиш
- желток
- куриные колбаски
- красная рыба
- полутвердый сыр

Recipes that cannot currently be calculated:
- `intake_001` — Фаршированные перцы с рисом и овощами в духовке — unmapped: твёрдый сыр
- `intake_003` — Омлет с творогом и зеленью — missing grams: шпинат или листовая зелень
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — unmapped: фарш из индейки
- `intake_005` — Белковый салат с тунцом, яйцом и свежими овощами — missing grams: салатные листья
- `intake_006` — Бутерброд с сыром и ветчиной — unmapped: сыр с высоким содержанием белка
- `intake_016` — Цельнозерновой хлеб с печенью трески — unmapped: печень трески консервированная
- `intake_020` — Ленивый хачапури по-аджарски — unmapped: сыр легкий
- `intake_021` — Гречка с запеченной индейкой и свекольным салатом — unmapped: гречка сухая, грудка индейки
- `intake_024` — Салат из печени трески с яйцом — unmapped: печень трески; missing grams: лук красный
- `intake_025` — Салат из печени трески с огурцом и картофелем — unmapped: печень трески; missing grams: зеленый лук
- `intake_026` — Салат из печени трески с луком — unmapped: печень трески, сыр твердый
- `intake_027` — Салат из консервированной печени трески — unmapped: печень трески; missing grams: зелень укропа или петрушки
- `intake_028` — Домашний салат из печени трески с зеленым горошком — unmapped: печень трески, горошек зеленый; missing grams: зеленый лук, майонез
- `intake_029` — Белковый салат с курицей — unmapped: виноград; missing grams: сметана 15%
- `intake_030` — Белковый салат с фасолью — missing grams: кинза
- `intake_032` — Салат с помидорами «Красное море» — unmapped: твердый сыр
- `intake_035` — Кукурузная каша — unmapped: кукурузная крупа; missing grams: мёд
- `intake_036` — Ленивая овсянка с ягодами и орехами — unmapped: орехи
- `intake_040` — Каша из киноа с фруктами — unmapped: фрукты, орехи
- `intake_042` — Банановые оладьи с шоколадной начинкой — unmapped: шоколадные чипсы; missing grams: растительное масло 1 ч.л
- `intake_043` — Овсяные блинчики — unmapped: крахмал кукурузный
- `intake_047` — Скрэмбл из тофу — missing grams: авокадо
- `intake_048` — Цельнозерновой хлеб с паштетом из печени индейки — unmapped: печень индейки, коньяк
- `intake_049` — Гречка по-купечески с фаршем — unmapped: смешанный фарш, гречка сухая
- `intake_051` — Гуляш с гречкой — unmapped: говядина
- `intake_052` — Макароны с курицей и овощами на сковороде — missing grams: зелень, чеснок
- `intake_054` — Гуляш из куриной печени — unmapped: куриная печень
- `intake_055` — Рыба под маринадом — unmapped: рыба минтай
- `intake_056` — Говядина в томатно-сметанном соусе — unmapped: говядина; missing grams: зелень картофель
- `intake_057` — Азу из индейки на сковороде — unmapped: огурцы соленые
- `intake_059` — Писто — missing grams: сахар
- `intake_060` — Макароны с яйцом и сыром — unmapped: сыр
- `intake_061` — Бигус из свежей капусты — unmapped: мясо
- `intake_062` — Индейка с баклажанами в духовке — missing grams: баклажаны, зелень
- `intake_063` — Салат с капустой, куриной грудкой и кунжутом — unmapped: соус соевый; missing grams: куриное филе, редис, кунжут, масло растительное рафинированное
- `intake_064` — Лосось, запеченный в фольге — missing grams: лимон, эстрагон
- `intake_065` — Кальмары с картофелем и шпинатом — unmapped: кальмары; missing grams: лимоны, петрушка
- `intake_066` — Шаурма из моркови — unmapped: сыр легкий
- `intake_067` — Пирожки с яйцом и творогом — unmapped: сыр «Лёгкий»
- `intake_068` — Скрэмбл без яиц — missing grams: баклажан
- `intake_069` — Котлеты из нута — unmapped: сухари панировочные; missing grams: мука рисовая, лук зелёный
- `intake_070` — Тофу-нори в кляре — missing grams: нори
- `intake_071` — Гороховый суп-пюре — unmapped: горох колотый, репа
- `intake_072` — Тофу-стейки в терияки — unmapped: терияки, для гарнира из моркови; missing grams: тофу, кинза для подачи
- `intake_073` — Тилапия в духовке — unmapped: филе тилапии, замороженная смесь «Овощи по-деревенски», белое сухое вино; missing grams: лимон, зелёный лук, петрушка
- `intake_074` — Куриные котлеты с кабачком — unmapped: фарш из курицы или индейки
- `intake_077` — Стейк из форели с молодым картофелем — unmapped: стейк из радужной форели; missing grams: сухой чеснок
- `intake_078` — Яйца по-флорентийски — unmapped: на 1 порцию, бешамель; missing grams: микрозелень для украшения
- `intake_079` — Кускус с курицей — unmapped: филе куриной грудки
- `intake_080` — Мясо по-тайски с лапшой — unmapped: свинина постная, лапша удон
- `intake_081` — Дорадо с рисом и яйцом пашот — unmapped: дорадо горячего копчения
- `intake_082` — Стейк из индейки с фасолью — unmapped: стейк из индейки
- `intake_083` — Кальмар, фаршированный сыром и курицей — unmapped: кальмар командорский тушки очищенные, филе куриной грудки, сыр «Голландский»; missing grams: петрушка сухая, чеснок сухой
- `intake_084` — Курица с овощами по-деревенски — unmapped: филе бедра курицы, смесь овощная «Три капусты», соус соевый
- `intake_085` — Гуляш по-венгерски лёгкий — unmapped: филе цыплёнка-бройлера кубиком, смесь овощная «Лечо по-венгерски», быстрозамороженная, крахмал кукурузный; missing grams: томаты в собственном соку, укроп сухой, петрушка сухая
- `intake_086` — Эскалоп свиной с сыром — unmapped: эскалоп свиной, сыр тёртый «Три сыра»
- `intake_087` — Курино-картофельные оладьи — unmapped: филе цыплёнка-бройлера кубиком, крахмал кукурузный; missing grams: чеснок сухой
- `intake_090` — Бутерброд с ветчиной и омлетом — unmapped: айсберг
- `intake_091` — Картофельные зразы с белыми грибами — unmapped: для начинки; missing grams: укроп свежий
- `intake_092` — Суп-пюре из батата — missing grams: батат
- `intake_093` — Шаурма с фалафелем — unmapped: фалафель замороженный, огурцы свежие; missing grams: лаваш «Армянский» тандырный, томаты свежие, лук зелёный
- `intake_094` — Лосось в сливочном соусе со шпинатом и голубым сыром — unmapped: сёмга филе на коже замороженное, сыр с голубой плесенью; missing grams: сливки 30%
- `intake_095` — Салат с шампиньонами и спаржей — unmapped: виноград кишмиш
- `intake_096` — Карбонара с беконом и сливками — unmapped: желток
- `intake_099` — Паста с креветками и соусом песто — missing grams: креветки крупные
- `intake_100` — Паста болоньезе — missing grams: сахар
- `intake_101` — Паста с куриными колбасками в остром томатном соусе — unmapped: куриные колбаски
- `intake_102` — Паста с лососем и шпинатом в сливочном соусе — unmapped: красная рыба
- `intake_104` — Макароны по-флотски — unmapped: полутвердый сыр

## Ingredient-vs-Steps Consistency

Step-mentioned ingredients missing from the ingredient sheet:
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — `ground_meat`, `turkey`
- `intake_009` — Рикотта с фруктами — `cottage_cheese`
- `intake_016` — Цельнозерновой хлеб с печенью трески — `white_fish`
- `intake_021` — Гречка с запеченной индейкой и свекольным салатом — `turkey`
- `intake_029` — Белковый салат с курицей — `lettuce`
- `intake_032` — Салат с помидорами «Красное море» — `lettuce`
- `intake_035` — Кукурузная каша — `corn`
- `intake_037` — Творог с мёдом и фруктами — `berries`
- `intake_047` — Скрэмбл из тофу — `olives`
- `intake_048` — Цельнозерновой хлеб с паштетом из печени индейки — `olives`, `turkey`
- `intake_049` — Гречка по-купечески с фаршем — `bell_pepper`
- `intake_059` — Писто — `olives`
- `intake_060` — Макароны с яйцом и сыром — `pasta_generic`
- `intake_065` — Кальмары с картофелем и шпинатом — `calamari`
- `intake_070` — Тофу-нори в кляре — `sour_cream`
- `intake_072` — Тофу-стейки в терияки — `carrot`
- `intake_073` — Тилапия в духовке — `olives`
- `intake_079` — Кускус с курицей — `chicken_breast`
- `intake_082` — Стейк из индейки с фасолью — `turkey`
- `intake_083` — Кальмар, фаршированный сыром и курицей — `chicken_breast`
- `intake_084` — Курица с овощами по-деревенски — `chicken_breast`
- `intake_087` — Курино-картофельные оладьи — `chicken_breast`
- `intake_099` — Паста с креветками и соусом песто — `chili_pepper`
- `intake_104` — Макароны по-флотски — `pasta_generic`

Listed but not detected in steps (review; spices/salt/water are excluded):
- `intake_001` — Фаршированные перцы с рисом и овощами в духовке — `bell_pepper` / болгарский перец / 150 g
- `intake_001` — Фаршированные перцы с рисом и овощами в духовке — `carrot` / морковь / 10 g
- `intake_001` — Фаршированные перцы с рисом и овощами в духовке — `corn` / кукуруза консервированная / 10 g
- `intake_001` — Фаршированные перцы с рисом и овощами в духовке — `onion` / лук / 10 g
- `intake_001` — Фаршированные перцы с рисом и овощами в духовке — `red_beans` / фасоль стручковая зеленая / 10 g
- `intake_001` — Фаршированные перцы с рисом и овощами в духовке — `rice` / рис / 30 g
- `intake_002` — Творог с яйцом на сковороде — `egg` / яйцо / 110 g
- `intake_003` — Омлет с творогом и зеленью — `cottage_cheese` / творог / 80 g
- `intake_003` — Омлет с творогом и зеленью — `egg` / яйца / 110 g
- `intake_003` — Омлет с творогом и зеленью — `tomato` / помидоры черри / 60 g
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — `bell_pepper` / болгарский перец / 40 g
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — `broccoli` / брокколи / 50 g
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — `carrot` / морковь / 40 g
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — `cauliflower` / цветная капуста / 50 g
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — `egg` / яйцо / 55 g
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — `oats` / овсяные хлопья или отруби / 10 g
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — `onion` / лук репчатый / 20 g
- `intake_004` — Котлеты из индейки с цукини и овощами на гарнир — `zucchini` / кабачок / 50 g
- `intake_005` — Белковый салат с тунцом, яйцом и свежими овощами — `olive_oil` / оливковое масло / 6 g
- `intake_005` — Белковый салат с тунцом, яйцом и свежими овощами — `tomato` / помидоры черри / 80 g
- `intake_005` — Белковый салат с тунцом, яйцом и свежими овощами — `tuna` / тунец консервированный / 70 g
- `intake_006` — Бутерброд с сыром и ветчиной — `cucumber` / огурец или лист салата / 30 g
- `intake_006` — Бутерброд с сыром и ветчиной — `ham` / ветчина из индейки или курицы / 35 g
- `intake_007` — Бутерброд с тунцом и помидором — `cream_cheese` / творожный крем-сыр нежирный / 25 g
- `intake_007` — Бутерброд с тунцом и помидором — `tomato` / помидор / 80 g
- `intake_007` — Бутерброд с тунцом и помидором — `tuna` / тунец в собственном соку / 70 g
- `intake_008` — Сэндвич с творожным соусом — `celery` / сельдерей / 25 g
- `intake_008` — Сэндвич с творожным соусом — `cucumber` / огурец / 70 g
- `intake_008` — Сэндвич с творожным соусом — `lavash` / лаваш или хлебец цельнозерновой / 45 g
- `intake_008` — Сэндвич с творожным соусом — `walnuts` / грецкие орехи / 10 g
- `intake_010` — Салат из консервированной красной фасоли — `cucumber` / огурец / 80 g
- `intake_010` — Салат из консервированной красной фасоли — `lime_juice` / сок лайма или лимона / 10 g
- `intake_010` — Салат из консервированной красной фасоли — `olive_oil` / оливковое масло / 15 g
- `intake_010` — Салат из консервированной красной фасоли — `onion` / красный лук / 20 g
- `intake_010` — Салат из консервированной красной фасоли — `red_beans` / красная фасоль консервированная / 110 g
- `intake_010` — Салат из консервированной красной фасоли — `tomato` / помидоры черри / 45 g
- `intake_011` — ПП-оладьи из кабачков — `egg` / яйцо куриное / 55 g
- `intake_011` — ПП-оладьи из кабачков — `greek_yogurt` / йогурт натуральный 2% / 20 g
- `intake_011` — ПП-оладьи из кабачков — `oats` / овсяные хлопья / 30 g
- `intake_011` — ПП-оладьи из кабачков — `zucchini` / кабачок / 150 g
- `intake_012` — Ролл с овощами и курицей — `cucumber` / огурец / 80 g
- `intake_012` — Ролл с овощами и курицей — `lavash` / тонкий лаваш / 60 g
- `intake_012` — Ролл с овощами и курицей — `lettuce` / листья салата / 30 g
- `intake_012` — Ролл с овощами и курицей — `onion` / красный лук / 15 g
- `intake_012` — Ролл с овощами и курицей — `sour_cream` / сметана нежирная или сальса / 25 g
- `intake_013` — Омлет с зеленым горошком и свеклой — `beet` / свекла вареная / 80 g
- `intake_013` — Омлет с зеленым горошком и свеклой — `green_peas` / зеленый горошек консервированный / 60 g
- `intake_014` — Овсяноблин с творожным сыром, консервированным тунцом, авокадо и огурцом — `avocado` / авокадо / 50 g
- `intake_014` — Овсяноблин с творожным сыром, консервированным тунцом, авокадо и огурцом — `cream_cheese` / творожный сыр / 25 g
- `intake_014` — Овсяноблин с творожным сыром, консервированным тунцом, авокадо и огурцом — `cucumber` / огурец / 60 g
- `intake_014` — Овсяноблин с творожным сыром, консервированным тунцом, авокадо и огурцом — `milk` / молоко или кефир / 40 g
- `intake_014` — Овсяноблин с творожным сыром, консервированным тунцом, авокадо и огурцом — `oats` / овсяные хлопья / 30 g
- `intake_014` — Овсяноблин с творожным сыром, консервированным тунцом, авокадо и огурцом — `tuna` / тунец в собственном соку / 70 g
- `intake_015` — Смесь орехов — `almonds` / миндаль / 10 g
- `intake_015` — Смесь орехов — `cashews` / кешью / 10 g
- `intake_015` — Смесь орехов — `walnuts` / грецкие орехи / 10 g
- `intake_016` — Цельнозерновой хлеб с печенью трески — `cucumber` / огурец / 50 g
- `intake_017` — Ароматный суп-пюре из цукини и чечевицы — `bell_pepper` / болгарский перец / 40 g
- `intake_017` — Ароматный суп-пюре из цукини и чечевицы — `carrot` / морковь / 25 g
- `intake_017` — Ароматный суп-пюре из цукини и чечевицы — `leek` / лук-порей / 25 g
- `intake_017` — Ароматный суп-пюре из цукини и чечевицы — `lentils` / красная чечевица / 25 g
- `intake_017` — Ароматный суп-пюре из цукини и чечевицы — `onion` / лук репчатый / 25 g
- `intake_017` — Ароматный суп-пюре из цукини и чечевицы — `zucchini` / кабачок / 200 g
- `intake_018` — Сливочный тыквенно-шоколадный мусс — `butter` / сливочное масло / 10 g
- `intake_018` — Сливочный тыквенно-шоколадный мусс — `butternut_squash` / тыква / 80 g
- `intake_018` — Сливочный тыквенно-шоколадный мусс — `cream` / сливки / 100 g
- `intake_018` — Сливочный тыквенно-шоколадный мусс — `gelatin` / желатин / 2 g
- `intake_019` — Салат с тунцом, яйцом, фасолью и овощами — `carrot` / морковь / 50 g
- `intake_019` — Салат с тунцом, яйцом, фасолью и овощами — `egg` / яйцо вареное / 55 g
- `intake_019` — Салат с тунцом, яйцом, фасолью и овощами — `lettuce` / салат айсберг / 50 g
- `intake_019` — Салат с тунцом, яйцом, фасолью и овощами — `onion` / красный лук / 15 g
- `intake_019` — Салат с тунцом, яйцом, фасолью и овощами — `red_beans` / фасоль консервированная / 70 g
- `intake_019` — Салат с тунцом, яйцом, фасолью и овощами — `sour_cream` / сметана / 20 g
- `intake_019` — Салат с тунцом, яйцом, фасолью и овощами — `tuna` / тунец консервированный без масла / 80 g
- `intake_020` — Ленивый хачапури по-аджарски — `egg` / яйцо / 55 g
- `intake_020` — Ленивый хачапури по-аджарски — `wheat_flour` / рисовая цельнозерновая мука / 15 g
- `intake_021` — Гречка с запеченной индейкой и свекольным салатом — `beet` / свекла вареная / 120 g
- `intake_021` — Гречка с запеченной индейкой и свекольным салатом — `sour_cream` / сметана 10-15% / 25 g
- `intake_022` — Шпинатный овсяноблин с семенами чиа — `chia_seeds` / семена чиа / 15 g
- `intake_022` — Шпинатный овсяноблин с семенами чиа — `egg` / яйцо / 110 g
- … еще 272

## Portion Consistency

- `intake_015` — Смесь орехов — `batch_instruction` in `step_2`: Разделите на одну порцию и подавайте как быстрый перекус.
- `intake_078` — Яйца по-флорентийски — `serving_text_in_ingredient` in `ingredient`: на 1 порцию

## Text Cleanliness

- No blocked service/marketing phrases, URLs/domains, `приятного аппетита`, `очень вкусно`, or suspicious truncated tails were detected in title/description/photo_prompt/steps.

## Gram And Unit Quality

- Total gram/unit issue rows: 90.
- `missing_grams_estimate`: 53
- `core_or_non_spice_po_vkusu`: 19
- `package_unit_without_grams`: 12
- `amount_or_unit_leaked_into_ingredient_name`: 6

Representative gram/unit rows to fix:
- `intake_003` — Омлет с творогом и зеленью — `core_or_non_spice_po_vkusu`: шпинат или листовая зелень; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_003` — Омлет с творогом и зеленью — `missing_grams_estimate`: шпинат или листовая зелень; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_005` — Белковый салат с тунцом, яйцом и свежими овощами — `missing_grams_estimate`: салатные листья; amount=1/2; unit=пучок; grams_estimate=None
- `intake_024` — Салат из печени трески с яйцом — `core_or_non_spice_po_vkusu`: лук красный; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_024` — Салат из печени трески с яйцом — `missing_grams_estimate`: лук красный; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_025` — Салат из печени трески с огурцом и картофелем — `core_or_non_spice_po_vkusu`: зеленый лук; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_025` — Салат из печени трески с огурцом и картофелем — `missing_grams_estimate`: зеленый лук; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_028` — Домашний салат из печени трески с зеленым горошком — `missing_grams_estimate`: горошек зеленый; amount=1/4; unit=банка; grams_estimate=None
- `intake_028` — Домашний салат из печени трески с зеленым горошком — `package_unit_without_grams`: горошек зеленый; amount=1/4; unit=банка; grams_estimate=None
- `intake_028` — Домашний салат из печени трески с зеленым горошком — `core_or_non_spice_po_vkusu`: зеленый лук; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_028` — Домашний салат из печени трески с зеленым горошком — `missing_grams_estimate`: зеленый лук; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_028` — Домашний салат из печени трески с зеленым горошком — `core_or_non_spice_po_vkusu`: майонез; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_028` — Домашний салат из печени трески с зеленым горошком — `missing_grams_estimate`: майонез; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_029` — Белковый салат с курицей — `missing_grams_estimate`: сметана 15%; amount=3-4; unit=ст. л.; grams_estimate=None
- `intake_035` — Кукурузная каша — `core_or_non_spice_po_vkusu`: мёд; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_035` — Кукурузная каша — `missing_grams_estimate`: мёд; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_042` — Банановые оладьи с шоколадной начинкой — `amount_or_unit_leaked_into_ingredient_name`: спелый банан 90 г; amount=70; unit=мл; grams_estimate=70
- `intake_042` — Банановые оладьи с шоколадной начинкой — `amount_or_unit_leaked_into_ingredient_name`: кукурузная мука 30 г; amount=25; unit=г; grams_estimate=25
- `intake_042` — Банановые оладьи с шоколадной начинкой — `amount_or_unit_leaked_into_ingredient_name`: растительное масло 1 ч.л; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_042` — Банановые оладьи с шоколадной начинкой — `core_or_non_spice_po_vkusu`: растительное масло 1 ч.л; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_042` — Банановые оладьи с шоколадной начинкой — `missing_grams_estimate`: растительное масло 1 ч.л; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_042` — Банановые оладьи с шоколадной начинкой — `missing_grams_estimate`: шоколадные чипсы; amount=для начинки; unit=; grams_estimate=None
- `intake_043` — Овсяные блинчики — `amount_or_unit_leaked_into_ingredient_name`: овсяная мука без глютена 70 г; amount=10; unit=г; grams_estimate=10
- `intake_043` — Овсяные блинчики — `amount_or_unit_leaked_into_ingredient_name`: вода 120 мл; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_047` — Скрэмбл из тофу — `missing_grams_estimate`: авокадо; amount=1/3; unit=шт; grams_estimate=None
- `intake_052` — Макароны с курицей и овощами на сковороде — `core_or_non_spice_po_vkusu`: зелень; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_052` — Макароны с курицей и овощами на сковороде — `missing_grams_estimate`: зелень; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_052` — Макароны с курицей и овощами на сковороде — `core_or_non_spice_po_vkusu`: чеснок; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_052` — Макароны с курицей и овощами на сковороде — `missing_grams_estimate`: чеснок; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_056` — Говядина в томатно-сметанном соусе — `core_or_non_spice_po_vkusu`: зелень картофель; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_056` — Говядина в томатно-сметанном соусе — `missing_grams_estimate`: зелень картофель; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_059` — Писто — `core_or_non_spice_po_vkusu`: сахар; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_059` — Писто — `missing_grams_estimate`: сахар; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_062` — Индейка с баклажанами в духовке — `missing_grams_estimate`: баклажаны; amount=1/2; unit=шт; grams_estimate=None
- `intake_062` — Индейка с баклажанами в духовке — `core_or_non_spice_po_vkusu`: зелень; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_062` — Индейка с баклажанами в духовке — `missing_grams_estimate`: зелень; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_063` — Салат с капустой, куриной грудкой и кунжутом — `missing_grams_estimate`: куриное филе; amount=1/2; unit=шт; grams_estimate=None
- `intake_063` — Салат с капустой, куриной грудкой и кунжутом — `missing_grams_estimate`: редис; amount=1; unit=шт; grams_estimate=None
- `intake_063` — Салат с капустой, куриной грудкой и кунжутом — `core_or_non_spice_po_vkusu`: кунжут; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_063` — Салат с капустой, куриной грудкой и кунжутом — `missing_grams_estimate`: кунжут; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_063` — Салат с капустой, куриной грудкой и кунжутом — `core_or_non_spice_po_vkusu`: масло растительное рафинированное; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_063` — Салат с капустой, куриной грудкой и кунжутом — `missing_grams_estimate`: масло растительное рафинированное; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_064` — Лосось, запеченный в фольге — `missing_grams_estimate`: лимон; amount=1/4; unit=шт; grams_estimate=None
- `intake_064` — Лосось, запеченный в фольге — `missing_grams_estimate`: эстрагон; amount=1/3; unit=веточка; grams_estimate=None
- `intake_065` — Кальмары с картофелем и шпинатом — `missing_grams_estimate`: лимоны; amount=1/3; unit=шт; grams_estimate=None
- `intake_068` — Скрэмбл без яиц — `missing_grams_estimate`: баклажан; amount=1/3; unit=шт; grams_estimate=None
- `intake_069` — Котлеты из нута — `core_or_non_spice_po_vkusu`: мука рисовая; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_069` — Котлеты из нута — `missing_grams_estimate`: мука рисовая; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_069` — Котлеты из нута — `missing_grams_estimate`: лук зелёный; amount=пара перьев; unit=; grams_estimate=None
- `intake_070` — Тофу-нори в кляре — `missing_grams_estimate`: нори; amount=1; unit=шт; grams_estimate=None
- `intake_072` — Тофу-стейки в терияки — `missing_grams_estimate`: тофу; amount=1/2; unit=упаковка; grams_estimate=None
- `intake_072` — Тофу-стейки в терияки — `package_unit_without_grams`: тофу; amount=1/2; unit=упаковка; grams_estimate=None
- `intake_072` — Тофу-стейки в терияки — `amount_or_unit_leaked_into_ingredient_name`: шрирача —15 мл; amount=1/2; unit=ст. л.; grams_estimate=8
- `intake_072` — Тофу-стейки в терияки — `missing_grams_estimate`: для гарнира из моркови; amount=1/2; unit=шт; grams_estimate=None
- `intake_073` — Тилапия в духовке — `missing_grams_estimate`: лимон; amount=1/2; unit=шт; grams_estimate=None
- `intake_073` — Тилапия в духовке — `missing_grams_estimate`: зелёный лук; amount=несколько перьев; unit=; grams_estimate=None
- `intake_077` — Стейк из форели с молодым картофелем — `core_or_non_spice_po_vkusu`: сухой чеснок; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_077` — Стейк из форели с молодым картофелем — `missing_grams_estimate`: сухой чеснок; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_078` — Яйца по-флорентийски — `missing_grams_estimate`: на 1 порцию; amount=2; unit=шт; grams_estimate=None
- `intake_082` — Стейк из индейки с фасолью — `missing_grams_estimate`: стейк из индейки; amount=1; unit=шт; grams_estimate=None
- `intake_083` — Кальмар, фаршированный сыром и курицей — `missing_grams_estimate`: кальмар командорский тушки очищенные; amount=1/3; unit=упаковка; grams_estimate=None
- `intake_083` — Кальмар, фаршированный сыром и курицей — `package_unit_without_grams`: кальмар командорский тушки очищенные; amount=1/3; unit=упаковка; grams_estimate=None
- `intake_083` — Кальмар, фаршированный сыром и курицей — `core_or_non_spice_po_vkusu`: чеснок сухой; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_083` — Кальмар, фаршированный сыром и курицей — `missing_grams_estimate`: чеснок сухой; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_085` — Гуляш по-венгерски лёгкий — `missing_grams_estimate`: филе цыплёнка-бройлера кубиком; amount=1/4; unit=упаковка; grams_estimate=None
- `intake_085` — Гуляш по-венгерски лёгкий — `package_unit_without_grams`: филе цыплёнка-бройлера кубиком; amount=1/4; unit=упаковка; grams_estimate=None
- `intake_085` — Гуляш по-венгерски лёгкий — `missing_grams_estimate`: смесь овощная «Лечо по-венгерски», быстрозамороженная; amount=1/3; unit=упаковка; grams_estimate=None
- `intake_085` — Гуляш по-венгерски лёгкий — `package_unit_without_grams`: смесь овощная «Лечо по-венгерски», быстрозамороженная; amount=1/3; unit=упаковка; grams_estimate=None
- `intake_085` — Гуляш по-венгерски лёгкий — `missing_grams_estimate`: томаты в собственном соку; amount=1/4; unit=банка; grams_estimate=None
- `intake_085` — Гуляш по-венгерски лёгкий — `package_unit_without_grams`: томаты в собственном соку; amount=1/4; unit=банка; grams_estimate=None
- `intake_086` — Эскалоп свиной с сыром — `missing_grams_estimate`: сыр тёртый «Три сыра»; amount=1/2; unit=упаковка; grams_estimate=None
- `intake_086` — Эскалоп свиной с сыром — `package_unit_without_grams`: сыр тёртый «Три сыра»; amount=1/2; unit=упаковка; grams_estimate=None
- `intake_086` — Эскалоп свиной с сыром — `package_unit_without_grams`: дольки картофеля без специй; amount=1/2; unit=упаковка; grams_estimate=None
- `intake_087` — Курино-картофельные оладьи — `missing_grams_estimate`: филе цыплёнка-бройлера кубиком; amount=1/4; unit=упаковка; grams_estimate=None
- `intake_087` — Курино-картофельные оладьи — `package_unit_without_grams`: филе цыплёнка-бройлера кубиком; amount=1/4; unit=упаковка; grams_estimate=None
- `intake_087` — Курино-картофельные оладьи — `core_or_non_spice_po_vkusu`: чеснок сухой; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_087` — Курино-картофельные оладьи — `missing_grams_estimate`: чеснок сухой; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_091` — Картофельные зразы с белыми грибами — `missing_grams_estimate`: для начинки; amount=1/4; unit=упаковка; grams_estimate=None
- `intake_091` — Картофельные зразы с белыми грибами — `package_unit_without_grams`: для начинки; amount=1/4; unit=упаковка; grams_estimate=None
- `intake_092` — Суп-пюре из батата — `missing_grams_estimate`: батат; amount=2/3; unit=шт; grams_estimate=None
- `intake_093` — Шаурма с фалафелем — `missing_grams_estimate`: фалафель замороженный; amount=4; unit=шт; grams_estimate=None
- `intake_093` — Шаурма с фалафелем — `missing_grams_estimate`: лаваш «Армянский» тандырный; amount=1/2; unit=упаковка; grams_estimate=None
- `intake_093` — Шаурма с фалафелем — `package_unit_without_grams`: лаваш «Армянский» тандырный; amount=1/2; unit=упаковка; grams_estimate=None
- `intake_093` — Шаурма с фалафелем — `missing_grams_estimate`: томаты свежие; amount=1/2; unit=шт; grams_estimate=None
- `intake_093` — Шаурма с фалафелем — `missing_grams_estimate`: лук зелёный; amount=несколько перьев; unit=; grams_estimate=None
- `intake_094` — Лосось в сливочном соусе со шпинатом и голубым сыром — `missing_grams_estimate`: сливки 30%; amount=1/4; unit=банка; grams_estimate=None
- `intake_094` — Лосось в сливочном соусе со шпинатом и голубым сыром — `package_unit_without_grams`: сливки 30%; amount=1/4; unit=банка; grams_estimate=None
- `intake_099` — Паста с креветками и соусом песто — `missing_grams_estimate`: креветки крупные; amount=4; unit=шт; grams_estimate=None
- `intake_100` — Паста болоньезе — `core_or_non_spice_po_vkusu`: сахар; amount=по вкусу; unit=по вкусу; grams_estimate=None
- `intake_100` — Паста болоньезе — `missing_grams_estimate`: сахар; amount=по вкусу; unit=по вкусу; grams_estimate=None

## Protein Anchors

- `intake_022` — Шпинатный овсяноблин с семенами чиа — кефир -> `kefir`, 45 g, anchor=`no`
- `intake_032` — Салат с помидорами «Красное море» — крабовые палочки -> `crab_sticks`, 70 g, anchor=`no`
- `intake_096` — Карбонара с беконом и сливками — пармезан -> `parmesan`, 20 g, anchor=`no`
- `intake_101` — Паста с куриными колбасками в остром томатном соусе — пармезан -> `parmesan`, 20 g, anchor=`no`
- `intake_102` — Паста с лососем и шпинатом в сливочном соусе — пармезан -> `parmesan`, 20 g, anchor=`no`
- `intake_103` — Мак-энд-чиз — моцарелла -> `mozzarella`, 35 g, anchor=`no`

## Duplicate Candidates With Existing Curated Recipes

| Intake recipe | Score | Existing curated candidate |
|---|---:|---|
| `intake_001` — Фаршированные перцы с рисом и овощами в духовке | 0.73 | `r156_farshirovannye_pertsy_s_risom_chernoy_fasolyu_i_syrom` — Фаршированные перцы с рисом, черной фасолью и сыром |
| `intake_005` — Белковый салат с тунцом, яйцом и свежими овощами | 0.76 | `r237_salat_s_tuntsom_fasolyu_yablokom_i_fetoy` — Салат с тунцом, фасолью, яблоком и фетой |
| `intake_012` — Ролл с овощами и курицей | 0.75 | `r252_lavash_roll_s_kuritsey_i_ovoschami` — Лаваш-ролл с курицей и овощами |
| `intake_019` — Салат с тунцом, яйцом, фасолью и овощами | 1.00 | `r237_salat_s_tuntsom_fasolyu_yablokom_i_fetoy` — Салат с тунцом, фасолью, яблоком и фетой |
| `intake_023` — Овсяная каша с томатами, зелёным горошком и рикоттой | 0.50 | `r009_klassicheskaya_ovsyanaya_kasha` — Классическая овсяная каша |
| `intake_029` — Белковый салат с курицей | 0.78 | `r232_pitatelnyy_salat_s_kuritsey_shpinatom_fetoy_i_semechka` — Питательный салат с курицей, шпинатом, фетой и семечками |
| `intake_038` — Авокадо-тост | 1.00 | `r002_tost_s_avokado` — Тост с авокадо |
| `intake_040` — Каша из киноа с фруктами | 0.74 | `r236_salat_iz_kinoa_s_nutom_ogurtsom_i_sladkim_pertsem` — Салат из киноа с нутом, огурцом и сладким перцем |
| `intake_047` — Скрэмбл из тофу | 0.73 | `r094_skrembl_s_fetoy_shpinatom_i_tomatami` — Скрэмбл с фетой, шпинатом и томатами |
| `intake_063` — Салат с капустой, куриной грудкой и кунжутом | 0.76 | `r258_salat_s_nutom_tuntsom_i_ogurtsom` — Салат с нутом, тунцом и огурцом |
| `intake_077` — Стейк из форели с молодым картофелем | 0.74 | `r194_kolbaski_s_molodym_kartofelem_artishokami_i_pesto_na_p` — Колбаски с молодым картофелем, артишоками и песто на противне |
| `intake_079` — Кускус с курицей | 0.73 | `r289_tost_s_kuritsey_shampinonami_i_syrom` — Тост с курицей, шампиньонами и сыром |
| `intake_081` — Дорадо с рисом и яйцом пашот | 0.72 | `r188_kuritsa_s_risom_i_yaytsom` — Курица с рисом и яйцом |
| `intake_097` — Качо-э-пепе | 0.76 | `r176_nokki_kacho_e_pepe` — Ньокки качо-э-пепе |

## Coverage Impact

Workbook distribution:
- Meal slots: {'main': 53, 'breakfast': 22, 'snack': 30}
- Cooking effort: {'interesting': 16, 'simple': 89}
- Slot/effort:
  - `breakfast/interesting`: 5
  - `breakfast/simple`: 17
  - `main/interesting`: 10
  - `main/simple`: 43
  - `snack/interesting`: 1
  - `snack/simple`: 29
- Tag counts:
  - `simple`: 89
  - `без яиц`: 75
  - `main`: 53
  - `без молочки`: 46
  - `мясо/птица`: 44
  - `snack`: 30
  - `breakfast`: 22
  - `рыба/морепродукты`: 21
  - `без готовки`: 18
  - `растительный белок`: 17
  - `interesting`: 16

Estimated gap impact, using only recipes that can be fully mapped/calculated now:
- Breakfast without eggs: 12 candidates.
- No dairy: 57 candidates.
- Simple high-protein mains (>=25 g protein, calc-ok): 5 candidates.
- High-protein snacks/light mains (>=20 g protein, calc-ok): 10 candidates.

Impact on `docs/RECIPE_COVERAGE_FUNNEL.md`: the slice is directionally useful for the documented gaps because it contains many simple recipes and main/snack items, but it is not yet a reliable way to widen the SIMPLE weekly main pool. The current blocker is not count; it is importability. Mapping gaps and anchor gaps must be fixed before the funnel can be rerun with meaningful numbers.

## Recommendation

**Fix workbook first.** Do not import all 105 as-is.

Recommended next slice:
1. Normalize unmapped/ambiguous ingredient names to existing product aliases or add explicit `food_id` mapping in the import path.
2. Fix rows where amount/unit leaked into `ingredient_name_ru`, especially `на 1 порцию`, `вода 120 мл`, `кукурузная мука 30 г`, `овсяная мука без глютена 70 г`, `спелый банан 90 г`, `растительное масло 1 ч.л`, `шрирача —15 мл`.
3. Add missing protein anchors on obvious protein ingredients.
4. Review ingredient-vs-step mismatches and listed-but-unused rows, then rerun this validation.
5. Only after a clean rerun, import either the whole workbook or a targeted subset for the coverage funnel.
