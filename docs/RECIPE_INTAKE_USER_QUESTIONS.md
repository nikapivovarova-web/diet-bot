# Recipe Intake User Questions

Scope: user-facing questions for the 19 `needs_review` recipes in `tmp/recipe_intake/cleaned_recipes.xlsx`.

Sources read:

- `tmp/recipe_intake/cleaned_recipes.xlsx`
- `docs/RECIPE_INTAKE_REVIEW_BACKLOG.md`
- `docs/RECIPE_INTAKE_VALIDATION.md`

Current intake status: 105 recipes total, 86 `ready`, 19 `needs_review`.

This file is questions only. It does not approve imports, change mappings, edit the workbook, or change production recipe data.

## Quick Recommendation

Best default path: approve targeted nutrition mappings for real ingredients/products that preserve the recipe, and exclude recipes only when the catalog should not be expanded.

Highest-leverage decisions:

- Add one cod-liver mapping to unblock `intake_016`, `intake_024`, `intake_025`, `intake_026`, `intake_027`, and `intake_028`.
- Confirm dry buckwheat mapping to unblock `intake_021` and `intake_049`.
- Add fresh grape/kishmish grape mapping instead of replacing with raisins.
- Decide whether prepared products/sauces are allowed as mappings: frozen falafel and prepared bechamel.

## Questions By Recipe

### Неизвестный ингредиент / Nutrition Mapping

| recipe_key | Название | Проблема простым языком | Вопрос пользователю | Варианты решения | Рекомендация |
|---|---|---|---|---|---|
| `intake_016` | Цельнозерновой хлеб с печенью трески | Нет nutrition mapping для консервированной печени трески; рецепт восстановлен по названию. | Можно ли добавить печень трески консервированную как отдельный food_id? | 1. Добавить mapping для консервированной печени трески. 2. Заменить на уже mapped рыбу/морепродукт. 3. Исключить рецепт. | Добавить mapping; это сохраняет рецепт и разблокирует весь cod-liver cluster. |
| `intake_021` | Гречка с запеченной индейкой и свекольным салатом | Сухая гречка 45 г не подтверждена как mapped ingredient; количества восстановлены бытово. | Подтверждаем сухую гречку как отдельный mapped продукт? | 1. Подтвердить/add mapping для сухой гречки. 2. Переписать на готовую гречку с новой граммовкой. 3. Заменить крупу на mapped grain. | Подтвердить сухую гречку; так не меняется рецепт и сохраняется логика 45 г dry. |
| `intake_024` | Салат из печени трески с яйцом | Нет nutrition mapping для печени трески. | Можно ли добавить печень трески как food_id? | 1. Добавить mapping для печени трески. 2. Заменить на mapped рыбу. 3. Исключить рецепт из импорта. | Добавить cod-liver mapping вместе с остальными рецептами этого кластера. |
| `intake_025` | Салат из печени трески с огурцом и картофелем | Нет nutrition mapping для печени трески; часть граммовок была нормализована. | Добавляем mapping для печени трески и принимаем текущие граммовки? | 1. Добавить cod-liver mapping и принять текущие граммовки. 2. Заменить печень трески на mapped рыбу. 3. Исключить рецепт. | Добавить mapping и принять текущую структуру, если нет замечаний по порции. |
| `intake_026` | Салат из печени трески с луком | Нет nutrition mapping для печени трески. | Можно ли использовать тот же cod-liver mapping? | 1. Добавить/использовать cod-liver mapping. 2. Заменить на mapped рыбу. 3. Исключить рецепт. | Использовать общий cod-liver mapping. |
| `intake_027` | Салат из консервированной печени трески | Нет nutrition mapping для печени трески; зелень была добавлена с бытовой граммовкой. | Подтверждаем mapping печени трески и текущую нормализацию ингредиентов? | 1. Добавить cod-liver mapping и принять текущие граммовки. 2. Заменить печень трески. 3. Исключить рецепт. | Добавить cod-liver mapping; граммовки выглядят вторичным review, не главным blocker. |
| `intake_028` | Домашний салат из печени трески с зеленым горошком | Нет nutrition mapping для печени трески; часть граммовок была нормализована. | Добавляем mapping для печени трески? | 1. Добавить cod-liver mapping. 2. Заменить печень трески. 3. Исключить рецепт. | Добавить общий cod-liver mapping. |
| `intake_029` | Белковый салат с курицей | Нет mapping для свежего винограда; изюм нельзя автоматически считать заменой. | Что делать со свежим виноградом в салате? | 1. Добавить mapping для свежего винограда. 2. Заменить на mapped свежий фрукт/ягоды. 3. Исключить рецепт. | Добавить fresh grape mapping; не заменять на изюм. |
| `intake_035` | Кукурузная каша | Нет mapping для кукурузной крупы/поленты; зерна кукурузы не подходят как замена. | Добавляем кукурузную крупу/поленту как mapped продукт? | 1. Добавить mapping для кукурузной крупы/поленты. 2. Заменить кашу на другую mapped крупу. 3. Исключить рецепт. | Добавить mapping для cornmeal/polenta. |
| `intake_048` | Цельнозерновой хлеб с паштетом из печени индейки | Нет mapping для печени индейки; также нужно решить, учитывать ли 3 мл коньяка. | Как считать паштет из печени индейки и коньяк? | 1. Добавить turkey liver mapping и учитывать коньяк отдельным ingredient. 2. Добавить turkey liver mapping, а коньяк исключить как малый технологический компонент. 3. Исключить рецепт. | Добавить turkey liver mapping; коньяк исключить из nutrition как 3 мл cooking component, если политика допускает. |
| `intake_049` | Гречка по-купечески с фаршем | Сухая гречка 45 г не подтверждена как mapped ingredient. | Подтверждаем сухую гречку для этого рецепта тоже? | 1. Подтвердить/add mapping для сухой гречки. 2. Переписать на готовую гречку с новой граммовкой. 3. Заменить крупу. | Подтвердить тот же dry buckwheat mapping, что и для `intake_021`. |
| `intake_054` | Гуляш из куриной печени | Нет mapping для куриной печени; замена на куриную грудку меняет блюдо. | Можно ли добавить куриную печень как mapped продукт? | 1. Добавить chicken liver mapping. 2. Заменить на другую mapped печень, если такая есть. 3. Исключить рецепт. | Добавить chicken liver mapping, не заменять на куриную грудку. |
| `intake_071` | Гороховый суп-пюре | Нет mapping для колотого гороха и репы. | Добавляем колотый горох и репу как mapped продукты? | 1. Добавить mappings для split peas и turnip. 2. Заменить репу на mapped овощ, а горох на mapped бобовые. 3. Исключить рецепт. | Добавить оба mapping; это минимально меняет суп. |
| `intake_077` | Стейк из форели с молодым картофелем | Нет mapping для радужной форели. | Добавляем радужную форель как mapped рыбу? | 1. Добавить trout mapping. 2. Заменить на mapped лосось/белую рыбу. 3. Исключить рецепт. | Добавить trout mapping и сделать форель protein anchor. |
| `intake_094` | Лосось в сливочном соусе со шпинатом и голубым сыром | Нет mapping для сыра с голубой плесенью. | Добавляем голубой сыр как mapped cheese? | 1. Добавить blue cheese mapping. 2. Заменить на mapped сыр из текущего каталога. 3. Исключить рецепт. | Добавить blue cheese mapping; ингредиент маленький, но вкусообразующий. |

### Непонятная замена продукта

| recipe_key | Название | Проблема простым языком | Вопрос пользователю | Варианты решения | Рекомендация |
|---|---|---|---|---|---|
| `intake_073` | Тилапия в духовке | Замороженная смесь "Овощи по-деревенски" слишком общая; белое сухое вино тоже нужно считать или исключить. | На какие конкретные овощи разложить смесь 100 г, и что делать с 50 мл вина? | 1. Дать точную разбивку овощей и учитывать вино. 2. Дать точную разбивку овощей, а вино исключить как cooking component. 3. Исключить рецепт. | Разложить смесь на конкретные mapped овощи; вино считать только если alcohol/cooking-wine mapping уже разрешен. |
| `intake_078` | Яйца по-флорентийски | Готовый бешамель 20 г не имеет mapping; можно либо map готовый соус, либо разложить его на ингредиенты. | Как считать бешамель? | 1. Добавить prepared bechamel mapping. 2. Разложить соус на молоко/масло/муку с точными граммовками. 3. Убрать готовый бешамель, если текущие молоко/масло уже покрывают соус. | Разложить соус на ингредиенты, если пользователь может подтвердить граммы; иначе добавить prepared bechamel mapping. |
| `intake_093` | Шаурма с фалафелем | Замороженный фалафель 100 г является prepared product без mapping. | Можно ли добавить замороженный фалафель как mapped product? | 1. Добавить frozen falafel mapping. 2. Разложить на нутовую основу/домашний фалафель с граммовками. 3. Исключить рецепт. | Добавить frozen falafel mapping, если prepared products допустимы; иначе разложить на нутовую основу. |
| `intake_095` | Салат с шампиньонами и спаржей | Пак-чой и спаржа уже заменены на пекинскую капусту и стручковую фасоль; отдельно нет mapping для винограда кишмиш. | Подтверждаем эти замены и что делать с кишмишем? | 1. Подтвердить замены и добавить fresh kishmish/grape mapping. 2. Вернуть пак-чой/спаржу и добавить для них mappings. 3. Заменить кишмиш на mapped свежий фрукт. | Подтвердить текущие доступные замены и добавить mapping для свежего кишмиша/винограда. |

### Граммовка

These recipes have inferred, reconstructed, or otherwise review-worthy gram amounts in addition to the mapping blocker.

| recipe_key | Название | Что проверить | Варианты | Рекомендация |
|---|---|---|---|---|
| `intake_016` | Цельнозерновой хлеб с печенью трески | Рецепт восстановлен по названию; печень трески 55 г, хлеб 40 г. | 1. Принять текущую порцию. 2. Дать другую граммовку. 3. Исключить как слишком восстановленный. | Принять текущую порцию, если пользователь не хочет ручной редакторской правки. |
| `intake_021` | Гречка с запеченной индейкой и свекольным салатом | Исходник был без количеств и шагов; текущие граммы бытово восстановлены. | 1. Принять текущие граммы. 2. Дать точные граммы. 3. Исключить. | Принять текущие граммы после подтверждения dry buckwheat mapping. |
| `intake_025` | Салат из печени трески с огурцом и картофелем | Зеленый лук и часть порции нормализованы. | 1. Принять текущие граммы. 2. Дать точные граммы. 3. Исключить. | Принять текущие граммы; blocker все равно cod-liver mapping. |
| `intake_027` | Салат из консервированной печени трески | Зелень добавлена бытовой граммовкой. | 1. Принять 5 г зелени. 2. Изменить граммовку. 3. Исключить. | Принять 5 г зелени. |
| `intake_028` | Домашний салат из печени трески с зеленым горошком | Зеленый лук/майонез нормализованы. | 1. Принять текущие граммы. 2. Дать точные граммы. 3. Исключить. | Принять текущие граммы. |
| `intake_048` | Цельнозерновой хлеб с паштетом из печени индейки | Большой batch паштета пересобран в 1 порцию; коньяк 3 мл. | 1. Принять текущую порцию. 2. Дать точный batch-to-serving пересчет. 3. Исключить. | Принять текущую порцию только после решения по turkey liver и коньяку. |
| `intake_049` | Гречка по-купечески с фаршем | Часть ингредиентов scaled from source. | 1. Принять текущий scaling. 2. Дать точные граммы. 3. Исключить. | Принять текущий scaling после dry buckwheat mapping. |
| `intake_054` | Гуляш из куриной печени | Часть ингредиентов scaled/added from source tail. | 1. Принять текущие граммы. 2. Дать точные граммы. 3. Исключить. | Принять текущие граммы после chicken liver mapping. |
| `intake_095` | Салат с шампиньонами и спаржей | Часть граммовок inferred; есть уже сделанные доступные замены. | 1. Принять текущие граммы и замены. 2. Дать точные граммы/вернуть оригинальные продукты. 3. Исключить. | Принять текущие граммы и замены, если fresh grape/kishmish mapping будет добавлен. |

### Белковый Anchor

These are not separate import blockers in validation, but they are follow-up decisions after the missing foods are mapped.

| recipe_key | Название | Текущий anchor status | Вопрос | Рекомендация |
|---|---|---|---|---|
| `intake_016` | Цельнозерновой хлеб с печенью трески | No current protein anchor. | Если cod liver mapping добавлен, ставим печень трески protein anchor? | Yes. |
| `intake_035` | Кукурузная каша | No current protein anchor. | Нужен ли protein anchor для этой каши? | No, это cereal breakfast без явного белкового anchor; оставить без anchor или исключить, если anchor обязателен. |
| `intake_048` | Цельнозерновой хлеб с паштетом из печени индейки | No current protein anchor. | Если turkey liver mapping добавлен, ставим печень индейки protein anchor? | Yes. |
| `intake_054` | Гуляш из куриной печени | No current protein anchor. | Если chicken liver mapping добавлен, ставим куриную печень protein anchor? | Yes. |
| `intake_071` | Гороховый суп-пюре | No current protein anchor. | Если split peas mapping добавлен, ставим колотый горох plant protein anchor? | Yes, если растительный белок допускается как anchor для main. |
| `intake_077` | Стейк из форели с молодым картофелем | No current protein anchor. | Если trout mapping добавлен, ставим форель protein anchor? | Yes. |
| `intake_093` | Шаурма с фалафелем | No current protein anchor. | Если frozen falafel/chickpea mapping добавлен, ставим фалафель protein anchor? | Yes, as plant protein anchor. |
| `intake_095` | Салат с шампиньонами и спаржей | Current anchor is стручковая фасоль. | Оставляем стручковую фасоль как plant protein anchor после подтверждения замен? | Yes only if plant anchors for snacks are acceptable; otherwise mark no anchor. |

### Рецепт лучше исключить

Use exclusion only if the user does not want to add new nutrition mappings or approve ingredient decomposition.

| recipe_key | Название | Почему может быть better to exclude | Варианты | Рекомендация |
|---|---|---|---|---|
| `intake_016`, `intake_024`, `intake_025`, `intake_026`, `intake_027`, `intake_028` | Cod-liver cluster | Six recipes depend on one missing cod-liver mapping. | 1. Add cod-liver mapping. 2. Exclude all six. 3. Replace cod liver recipe-by-recipe. | Do not exclude if one mapping can be added. |
| `intake_048` | Цельнозерновой хлеб с паштетом из печени индейки | Turkey liver plus cognac makes the nutrition decision less standard. | 1. Add turkey liver and omit/count cognac. 2. Exclude. 3. Rewrite with approved pate ingredient. | Keep only if turkey liver mapping is approved. |
| `intake_073` | Тилапия в духовке | Needs decomposition of a frozen vegetable mix and a wine decision. | 1. Provide exact vegetable breakdown. 2. Exclude. 3. Replace with mapped vegetables and omit wine. | Exclude if exact vegetable breakdown is not approved. |
| `intake_078` | Яйца по-флорентийски | Prepared bechamel needs either a sauce mapping or exact component grams. | 1. Map prepared bechamel. 2. Decompose sauce. 3. Exclude. | Keep if sauce mapping/decomposition is approved; otherwise exclude. |
| `intake_093` | Шаурма с фалафелем | Frozen falafel is a prepared product and may not fit the nutrition catalog policy. | 1. Map frozen falafel. 2. Decompose/rewrite as chickpea falafel. 3. Exclude. | Keep if prepared products are allowed; otherwise rewrite or exclude. |

## User Answer Template

Suggested compact way for the user to answer:

```text
Cod liver: add mapping
Dry buckwheat: add/confirm mapping
Fresh grapes/kishmish: add mapping
Cornmeal/polenta: add mapping
Turkey liver: add mapping; cognac: omit as cooking component
Chicken liver: add mapping
Split peas + turnip: add mappings
Frozen vegetable mix: break into [exact grams]; wine: count/omit
Trout: add mapping
Bechamel: map prepared sauce / decompose into exact grams
Frozen falafel: add mapping / decompose
Blue cheese: add mapping
intake_095 replacements: approve / revise
Exclusions: none / list keys
```
