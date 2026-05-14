# Recipe Intake Import Preview

Date: 2026-05-14

Scope: dry-run transform of `tmp/recipe_intake/cleaned_recipes.xlsx` only. No production curated recipe, ingredient, nutrition, photo, builder, PDF, Telegram, promo, payments, or storage data was modified.

## Inputs Read

- `tmp/recipe_intake/cleaned_recipes.xlsx`
- `docs/RECIPE_INTAKE_VALIDATION.md`
- `docs/RECIPE_INTAKE_CLEANUP_REPORT.md`
- `docs/RECIPE_INTAKE_REVIEW_BACKLOG.md`
- `docs/RECIPE_COVERAGE_AUDIT.md`
- `docs/RECIPE_COVERAGE_FUNNEL.md`
- `docs/RECIPE_COVERAGE_SMOKE_NOTES.md`
- Current read-only curated data under `src/diet_bot/data/`

Temporary dry-run artifacts were written under ignored `tmp/recipe_intake/` and are intentionally not part of this docs-only result.

## Dry-Run Transform Shape

The preview transformed the 105 `ready` recipes into a shape close to current curated data without importing it:

- recipe rows: `recipe_key` as preview `recipe_id`, `meal_slot` as `slot`, `title_ru`, `servings = 1`, `time_text` from active/passive minutes, ordered `instructions_ru` from the steps sheet, and source marker for intake preview.
- ingredient rows: one row per workbook ingredient with `line_index`, raw/name fields, grams estimate, optional protein-anchor marker, preview `food_id` when a current food or alias could be matched, and parseability status.
- nutrition readiness: approximate macro totals only for mapped ingredients, for import-readiness screening. These are not production nutrition entries.
- media: `photo_prompt_ru` was checked for presence only. No photos were generated and no `image_url` values were created.

## Workbook Counts

- Total recipes: 105
- Status: 105 `ready`, 0 `needs_review`
- `servings_cleaned = 1`: 105/105
- Ingredient rows: 845
- Step rows: 462
- QA rows retained in workbook: 175, with 90 notes and 85 warnings
- Meal slots: 53 main, 22 breakfast, 30 snack
- Cooking effort: 89 simple, 16 interesting
- Simple by slot: 43 main, 17 breakfast, 29 snack
- Interesting by slot: 10 main, 5 breakfast, 1 snack

## Validation

Passes:

- `recipe_key` uniqueness inside workbook: pass, 0 duplicates
- Duplicate check against existing curated recipes by `recipe_key`/`recipe_id`: 0 matches
- Duplicate check against existing curated recipes by exact title: 0 matches
- Duplicate check against existing curated recipes by normalized repaired title: 0 matches
- Valid `meal_slot`: 105/105, allowed values are `breakfast`, `main`, `snack`
- Valid `cooking_effort`: 105/105, allowed values are `simple`, `interesting`
- Ingredient parseability: 845/845 parseable for dry-run purposes
- Step parseability: 462/462 parseable, step numbering sequential per recipe
- `photo_prompt_ru`: present for 105/105
- Cooking alcohol terms: 0 exact hits for wine/cognac/brandy/alcohol terms

Protein anchor warnings where an anchor is expected but not marked:

- `intake_035` - Кукурузная каша, breakfast
- `intake_042` - Банановые оладьи с шоколадной начинкой, breakfast
- `intake_043` - Овсяные блинчики, breakfast
- `intake_059` - Писто, main
- `intake_089` - Рулет из лаваша с хумусом, main
- `intake_091` - Картофельные зразы с белыми грибами, main
- `intake_092` - Суп-пюре из батата, main

Interpretation: the three breakfast warnings look like tag/expectation cleanup candidates. The four main warnings should be resolved before production import by adding a real anchor, re-slotting, or explicitly accepting them as low-protein mains.

## Nutrition Readiness

Ingredient mapping:

- Mapped ingredient rows: 812/845, 96.1%
- Mapped unique ingredient names: 313/339, 92.3%
- Preview mapped food IDs used: 134
- Full mapped recipes: 68
- Near-full mapped recipes: 3
- Risky for КБЖУ: 34

Important correction in the dry-run: `виноград`/`виноград кишмиш` were kept unmapped instead of allowing a substring match to `wine`. This preserves the "no cooking alcohol" result and makes the nutrition-readiness risk visible.

Top unmapped ingredient names:

- `печень трески` - 5 rows
- `гречка сухая` - 2 rows
- `куриная печень` - 2 rows
- `хмели-сунели` - 2 rows
- Single-row unmapped items: `сумах`, `печень трески консервированная`, `виноград`, `горох колотый`, `стейк из радужной форели`, `лапша удон для быстрого приготовления`, `рис басмати`, `тыква кубиками «Айс»`, `консервированные томаты`, `свиные отбивные`, `приправа для овощей или универсальная`, `вяленые томаты`, `масло растительное для жарки`, `фалафель замороженный`, `виноград кишмиш`, `яичные желтки`, `томаты черри`, `протертые томаты`, `томатный соус`, `куриная колбаска`, `томатный соус аррабиата`, `резаные томаты`

### Full Mapped Recipes

- `intake_001` | main | interesting | Фаршированные перцы с рисом и овощами в духовке
- `intake_002` | breakfast | simple | Творог с яйцом на сковороде
- `intake_003` | breakfast | simple | Омлет с творогом и зеленью
- `intake_004` | main | interesting | Котлеты из индейки с цукини и овощами на гарнир
- `intake_005` | snack | simple | Белковый салат с тунцом, яйцом и свежими овощами
- `intake_006` | snack | simple | Бутерброд с сыром и ветчиной
- `intake_007` | snack | simple | Бутерброд с тунцом и помидором
- `intake_008` | snack | simple | Сэндвич с творожным соусом
- `intake_009` | breakfast | simple | Рикотта с фруктами
- `intake_011` | breakfast | simple | ПП-оладьи из кабачков
- `intake_012` | snack | simple | Ролл с овощами и курицей
- `intake_013` | breakfast | simple | Омлет с зеленым горошком и свеклой
- `intake_014` | snack | simple | Овсяноблин с творожным сыром, консервированным тунцом, авокадо и огурцом
- `intake_015` | snack | simple | Смесь орехов
- `intake_017` | main | interesting | Ароматный суп-пюре из цукини и чечевицы
- `intake_018` | snack | simple | Сливочный тыквенно-шоколадный мусс
- `intake_020` | breakfast | simple | Ленивый хачапури по-аджарски
- `intake_022` | breakfast | simple | Шпинатный овсяноблин с семенами чиа
- `intake_023` | breakfast | simple | Овсяная каша с томатами, зелёным горошком и рикоттой
- `intake_030` | snack | simple | Белковый салат с фасолью
- `intake_031` | snack | simple | Марокканский салат с помидорами, корицей и нутом
- `intake_033` | breakfast | simple | Шоколадный ПП-десерт с бананом в микроволновке
- `intake_034` | snack | simple | Запеченное яблоко с апельсином и корицей
- `intake_035` | breakfast | simple | Кукурузная каша
- `intake_036` | breakfast | simple | Ленивая овсянка с ягодами и орехами
- `intake_037` | breakfast | simple | Творог с мёдом и фруктами
- `intake_038` | breakfast | simple | Авокадо-тост
- `intake_039` | snack | simple | Смузи из банана, шпината и орехового молока
- `intake_040` | breakfast | simple | Каша из киноа с фруктами
- `intake_041` | breakfast | simple | Омлет из нутовой муки с брокколи и стручковой фасолью
- `intake_042` | breakfast | interesting | Банановые оладьи с шоколадной начинкой
- `intake_043` | breakfast | interesting | Овсяные блинчики
- `intake_044` | snack | simple | Творог с укропом с цельнозерновым хлебом
- `intake_045` | snack | simple | Творог с укропом и хлебцами
- `intake_046` | snack | simple | Творог с укропом и морковными палочками
- `intake_047` | breakfast | interesting | Скрэмбл из тофу
- `intake_050` | main | simple | Спагетти с курицей в сметанном соусе
- `intake_051` | main | simple | Гуляш с гречкой
- `intake_052` | main | simple | Макароны с курицей и овощами на сковороде
- `intake_055` | main | simple | Рыба под маринадом
- `intake_056` | main | simple | Говядина в томатно-сметанном соусе
- `intake_057` | main | simple | Азу из индейки на сковороде
- `intake_058` | main | simple | Индейка тушеная в сметане
- `intake_059` | main | simple | Писто
- `intake_060` | main | simple | Макароны с яйцом и сыром
- `intake_061` | main | simple | Бигус из свежей капусты
- `intake_064` | main | simple | Лосось, запеченный в фольге
- `intake_065` | main | interesting | Кальмары с картофелем и шпинатом
- `intake_066` | snack | simple | Шаурма из моркови
- `intake_067` | snack | simple | Пирожки с яйцом и творогом
- `intake_068` | breakfast | interesting | Скрэмбл без яиц
- `intake_069` | main | simple | Котлеты из нута
- `intake_073` | main | simple | Тилапия в духовке
- `intake_074` | main | simple | Куриные котлеты с кабачком
- `intake_075` | breakfast | simple | Омлет с зеленью
- `intake_076` | breakfast | interesting | Сырники на кокосовой муке
- `intake_078` | main | simple | Яйца по-флорентийски
- `intake_079` | main | simple | Кускус с курицей
- `intake_082` | main | simple | Стейк из индейки с фасолью
- `intake_083` | main | interesting | Кальмар, фаршированный сыром и курицей
- `intake_087` | main | simple | Курино-картофельные оладьи
- `intake_088` | main | simple | Быстрый суп с нутом и курицей
- `intake_090` | breakfast | simple | Бутерброд с ветчиной и омлетом
- `intake_092` | main | interesting | Суп-пюре из батата
- `intake_094` | main | simple | Лосось в сливочном соусе со шпинатом и сыром
- `intake_097` | main | simple | Качо-э-пепе
- `intake_102` | main | simple | Паста с лососем и шпинатом в сливочном соусе
- `intake_103` | main | interesting | Мак-энд-чиз

### Near-Full Mapped Recipes

- `intake_010` | snack | simple | Салат из консервированной красной фасоли
- `intake_062` | main | interesting | Индейка с баклажанами в духовке
- `intake_091` | main | interesting | Картофельные зразы с белыми грибами

### Risky for КБЖУ

- `intake_086` | main | simple | Эскалоп свиной с сыром | unmapped: свиные отбивные, приправа для овощей или универсальная; anchor unmapped
- `intake_098` | main | simple | Паста с консервированным тунцом и томатами | unmapped: томаты черри, протертые томаты
- `intake_101` | main | simple | Паста с куриными колбасками в остром томатном соусе | unmapped: куриная колбаска, томатный соус аррабиата; anchor unmapped; semi-prepared/sauce decision
- `intake_104` | main | simple | Макароны по-флотски | unmapped: резаные томаты, хмели-сунели
- `intake_016` | snack | simple | Цельнозерновой хлеб с печенью трески | unmapped: печень трески консервированная; anchor unmapped
- `intake_021` | main | simple | Гречка с запеченной индейкой и свекольным салатом | unmapped: гречка сухая
- `intake_024` | snack | simple | Салат из печени трески с яйцом | unmapped: печень трески; anchor unmapped
- `intake_025` | snack | simple | Салат из печени трески с огурцом и картофелем | unmapped: печень трески; anchor unmapped
- `intake_026` | snack | simple | Салат из печени трески с луком | unmapped: печень трески; anchor unmapped; semi-prepared/sauce decision
- `intake_027` | snack | simple | Салат из консервированной печени трески | unmapped: печень трески; anchor unmapped; semi-prepared/sauce decision
- `intake_028` | snack | simple | Домашний салат из печени трески с зеленым горошком | unmapped: печень трески; anchor unmapped; semi-prepared/sauce decision
- `intake_029` | snack | simple | Белковый салат с курицей | unmapped: виноград
- `intake_048` | snack | interesting | Цельнозерновой хлеб с паштетом из куриной печени | unmapped: куриная печень; anchor unmapped
- `intake_049` | main | simple | Гречка по-купечески с фаршем | unmapped: гречка сухая
- `intake_054` | main | simple | Гуляш из куриной печени | unmapped: куриная печень; anchor unmapped
- `intake_071` | main | simple | Гороховый суп-пюре | unmapped: горох колотый; anchor unmapped
- `intake_077` | main | simple | Стейк из форели с молодым картофелем | unmapped: стейк из радужной форели; anchor unmapped; semi-prepared/sauce decision
- `intake_080` | main | simple | Мясо по-тайски с лапшой | unmapped: лапша удон для быстрого приготовления; semi-prepared/sauce decision
- `intake_081` | main | simple | Дорадо с рисом и яйцом пашот | unmapped: рис басмати
- `intake_084` | main | simple | Курица с овощами по-деревенски | unmapped: тыква кубиками «Айс»; semi-prepared/sauce decision
- `intake_085` | main | simple | Гуляш по-венгерски лёгкий | unmapped: консервированные томаты
- `intake_089` | main | simple | Рулет из лаваша с хумусом | unmapped: вяленые томаты
- `intake_093` | main | simple | Шаурма с фалафелем | unmapped: фалафель замороженный; anchor unmapped; semi-prepared/sauce decision
- `intake_095` | snack | simple | Салат с шампиньонами и спаржей | unmapped: виноград кишмиш
- `intake_096` | main | simple | Карбонара с беконом и сливками | unmapped: яичные желтки; anchor unmapped
- `intake_100` | main | simple | Паста болоньезе | unmapped: томатный соус; semi-prepared/sauce decision
- `intake_019` | snack | simple | Салат с тунцом, яйцом, фасолью и овощами | semi-prepared/sauce decision
- `intake_032` | snack | simple | Салат с помидорами «Красное море» | semi-prepared/sauce decision
- `intake_053` | main | simple | Стручковая фасоль с чесноком и соевым соусом | semi-prepared/sauce decision
- `intake_063` | main | simple | Салат с капустой, куриной грудкой и кунжутом | semi-prepared/sauce decision
- `intake_070` | snack | simple | Тофу-нори в кляре | semi-prepared/sauce decision
- `intake_072` | main | simple | Тофу-стейки в терияки | semi-prepared/sauce decision
- `intake_099` | main | simple | Паста с креветками и соусом песто | semi-prepared/sauce decision
- `intake_105` | main | interesting | Пюре из зеленого горошка с креветками | semi-prepared/sauce decision

## Coverage Impact

Baseline from latest audit/smoke:

- Current curated pool: 400 recipes
- Latest smoke SIMPLE after effort filter: 161 recipes
- Latest smoke main-builder eligible pool: 55 total, with 17 native main and 38 snack-as-main fallback
- Latest audit strict SIMPLE high-protein main proxy: 14 lunch / 15 dinner

Preview intake counts:

- Breakfast/snack/main: 22 / 30 / 53
- Simple/interesting: 89 / 16
- Simple high-protein native main, strict proxy: 14 recipes
- High-protein snack/light-main candidates: 5 recipes, all 5 also pass snack-as-main fallback
- Native SIMPLE main eligible increase on the full dry-run: +20
- Snack-as-main fallback increase on the full dry-run: +5
- Estimated SIMPLE main-builder eligible pool increase: +25, moving latest smoke from about 55 to about 80 if production mappings and import checks are accepted
- Conservative Batch 1 estimate after excluding anchor warnings: +19 native SIMPLE main and +5 fallback, moving latest smoke from about 55 to about 79
- Strict high-protein native main proxy increase: +14, moving audit proxy from about 14/15 to about 28/29

Strict simple high-protein native main candidates:

- `intake_050` - Спагетти с курицей в сметанном соусе
- `intake_051` - Гуляш с гречкой
- `intake_052` - Макароны с курицей и овощами на сковороде
- `intake_055` - Рыба под маринадом
- `intake_056` - Говядина в томатно-сметанном соусе
- `intake_058` - Индейка тушеная в сметане
- `intake_064` - Лосось, запеченный в фольге
- `intake_074` - Куриные котлеты с кабачком
- `intake_079` - Кускус с курицей
- `intake_082` - Стейк из индейки с фасолью
- `intake_087` - Курино-картофельные оладьи
- `intake_088` - Быстрый суп с нутом и курицей
- `intake_094` - Лосось в сливочном соусе со шпинатом и сыром
- `intake_102` - Паста с лососем и шпинатом в сливочном соусе

High-protein snack/light-main candidates:

- `intake_005` - Белковый салат с тунцом, яйцом и свежими овощами
- `intake_007` - Бутерброд с тунцом и помидором
- `intake_012` - Ролл с овощами и курицей
- `intake_014` - Овсяноблин с творожным сыром, консервированным тунцом, авокадо и огурцом
- `intake_066` - Шаурма из моркови

Dietary coverage, ingredient-derived:

- Without eggs: 76 total
- Without dairy: 46 total
- Without gluten: 54 total
- Simple high-protein main intersections: 12 without eggs, 6 without dairy, 6 without gluten
- High-protein snack intersections: 2 without eggs, 1 without dairy, 3 without gluten

Note: the workbook has explicit `без яиц` and `без молочки` tags, but no explicit gluten tag. Gluten-free availability should be treated as ingredient-derived until production tags are added or confirmed.

## Recommended Import Plan

Recommendation: import in batches, not all 105 at once.

Reason: all 105 are structurally ready, but 34 recipes still have КБЖУ risk from unmapped ingredients, unmapped anchors, or semi-prepared/sauce decisions. The first production slice should maximize coverage impact while keeping nutrition and anchor risk low.

### Batch 1 Candidate

Use the 65 recipes that are `full` or `near_full` mapped and do not have protein-anchor warnings.

Batch 1 counts:

- 65 total recipes
- 28 main, 19 breakfast, 18 snack
- 55 simple, 10 interesting
- 19 native SIMPLE main eligible candidates after anchor-warning exclusion
- 14 strict simple high-protein native main candidates
- 5 high-protein snack/light-main fallback candidates

Batch 1 keys by slot:

- Breakfast: `intake_002`, `intake_003`, `intake_009`, `intake_011`, `intake_013`, `intake_020`, `intake_022`, `intake_023`, `intake_033`, `intake_036`, `intake_037`, `intake_038`, `intake_040`, `intake_041`, `intake_047`, `intake_068`, `intake_075`, `intake_076`, `intake_090`
- Snack: `intake_005`, `intake_006`, `intake_007`, `intake_008`, `intake_010`, `intake_012`, `intake_014`, `intake_015`, `intake_018`, `intake_030`, `intake_031`, `intake_034`, `intake_039`, `intake_044`, `intake_045`, `intake_046`, `intake_066`, `intake_067`
- Main: `intake_001`, `intake_004`, `intake_017`, `intake_050`, `intake_051`, `intake_052`, `intake_055`, `intake_056`, `intake_057`, `intake_058`, `intake_060`, `intake_061`, `intake_062`, `intake_064`, `intake_065`, `intake_069`, `intake_073`, `intake_074`, `intake_078`, `intake_079`, `intake_082`, `intake_083`, `intake_087`, `intake_088`, `intake_094`, `intake_097`, `intake_102`, `intake_103`

Why this batch:

- It adds nearly all of the immediate SIMPLE-main coverage value with the lowest nutrition risk.
- It avoids the 7 protein-anchor warnings until they are intentionally resolved.
- It excludes the cod-liver/chicken-liver/falafel/prepared-sauce cluster that needs more explicit nutrition policy.
- It keeps the first production import testable as a single coverage-focused slice.

### Later Batches

Batch 2 should contain recipes that only need straightforward food aliases or food additions, for example buckwheat, cod liver, chicken liver, split peas, trout steak, udon, basmati rice, canned tomatoes, grape, grape kishmish, tomato sauce variants, egg yolks, and spice blends.

Batch 3 should contain recipes requiring product or semi-prepared policy decisions, for example falafel frozen, chicken sausage, arrabbiata sauce, pesto, teriyaki, mayonnaise/crab-stick recipes, and other ready sauce/product cases.

## Blockers Before Production Import

- Add or approve nutrition mappings for the 33 unmapped ingredient rows and 26 unique unmapped names.
- Resolve the 7 protein-anchor warnings, especially the four main-slot recipes.
- Decide whether semi-prepared sauces/products can map to existing foods, require new foods, or should stay excluded.
- Decide how to handle `виноград` and `виноград кишмиш`: add exact food rows or approve a fruit proxy. They must not map to alcohol.
- Confirm gluten-free tagging strategy, because the dry-run only inferred gluten from ingredients.
- Add production media handling later. `photo_prompt_ru` is present, but this preview intentionally generated no photos.

## Conclusion

The intake slice is structurally clean and does not duplicate existing curated recipes. It is not ready for an all-105 production import because the remaining КБЖУ and anchor decisions would make the blast radius too large. The recommended first import batch is the 65-recipe low-risk slice above, followed by targeted nutrition-mapping batches.
