# New recipe review table

- Source file path: `C:\Users\adck8\Documents\New project 5\outputs\recipe_excel\recipes_from_courses_fixed.xlsx`
- Source format: `.xlsx`, sheet `Все рецепты`
- Total recipes parsed: 541
- Parsing confidence: Medium-high: consolidated workbook sheet is structured; SWBAND rows came from OCR and 178 source rows have blank preparation steps, so those rows are flagged for review.
- CSV output: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\docs\recovery-integration\new-recipe-review-table.csv`
- Optional XLSX output: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\docs\recovery-integration\new-recipe-review-table.xlsx`

## Counts

- GOOD_CANDIDATE: 45
- MAYBE_REVIEW: 318
- REJECT: 178

## Source mix

- InfoVolna: 425
- SWBAND.CO: 116

## Top 30 GOOD_CANDIDATE

1. **Белковые фаршированные мини-перцы с лососем** — score 92; breakfast; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
2. **Бургер в хрустящем листе айсберга** — score 92; unknown; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
3. **Бургер в чесночной йогуртовой булочке** — score 92; unknown; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
4. **Зелёная окрошка на минералке с лососем** — score 92; lunch; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
5. **Классическая окрошка на квасе с языком** — score 92; lunch; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
6. **Лахмаджун** — score 92; unknown; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
7. **Молодая морковь с йогуртом и фисташками** — score 92; unknown; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
8. **Обновлённый «Король микробиома»** — score 92; snack; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
9. **Окрошка fit с индюшачьей колбасой** — score 92; lunch; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
10. **Окрошка на кефире и минералке с индейкой** — score 92; lunch; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
11. **Окрошка на мацони с курицей** — score 92; lunch; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
12. **Салат из запечённых овощей с бабагануш заправкой** — score 92; snack; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
13. **Салат из печёного перца и творога** — score 92; snack; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
14. **Салат из цукини с пармезаном и руколой** — score 92; snack; clear cooking steps; usable quantities; everyday cooking method.
15. **Свекольник с ацидофилином** — score 92; lunch; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
16. **Свёкла с йогуртом, фисташками и апельсином** — score 92; snack; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
17. **Стейки из капусты с тахини-йогуртом и нутом** — score 92; unknown; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
18. **Такос на домашней чечевичной лепёшке** — score 92; unknown; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
19. **Томатная овсянка с яйцом пашот** — score 92; breakfast; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
20. **Тёплый салат из брокколи и эдамаме** — score 92; snack; clear cooking steps; usable quantities.
21. **Тёплый салат с кальмарами, фенхелем и апельсином** — score 92; snack; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
22. **Холодный суп из авокадо и зелёНОГ0 горошка** — score 92; lunch; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
23. **Хрустящая зелёная фасоль с кунжутным йогуртом** — score 92; unknown; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
24. **Хрустящие роллы из рисовой бумаги с креветкой** — score 92; breakfast; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
25. **Хрустящие творожно кабачковые оладьи** — score 92; breakfast; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
26. **Цветная капуста целиком с зелёным соусом** — score 92; unknown; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
27. **Хрустящий салат из капусты, эдамаме и тахини** — score 89; snack; clear cooking steps; usable quantities; everyday cooking method.
28. **Легкие ленивые вареники** — score 88; breakfast; clear cooking steps; usable quantities; protein-forward; everyday cooking method.
29. **макаронник 1 порция** — score 88; lunch; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.
30. **Рис (или любая другая крупа) – 40 гр** — score 88; breakfast; clear cooking steps; usable quantities; protein-forward; balanced main ingredients.

## Top duplicate risks

- HIGH: **Пицца на основе цветной капусты** -> `Пицца на основе из цветной капусты` (score 66)
- HIGH: **Огуречные лодочки с тунцовым муссом** -> `Огуречные лодочки с тунцом` (score 28)
- MEDIUM: **Ленивый хачапури** -> `Ленивый хачапури по-аджарски` (score 92)
- MEDIUM: **Печёные перцы с белой фасолью и травами** -> `Куриный суп с белой фасолью и кейлом` (score 92)
- MEDIUM: **Салат с огурцом, редисом и творожным кремом** -> `Омлет с беконом, гаудой и творожным сыром` (score 92)
- MEDIUM: **Томатный салат с белой фасолью и базиликом** -> `Куриный суп с белой фасолью и кейлом` (score 92)
- MEDIUM: **Тёплый салат с чечевицей и томатами** -> `Зеленое карри с чечевицей и рисом` (score 92)
- MEDIUM: **Хрустящий салат с брокколи и нутом** -> `Марокканский салат с помидорами, корицей и нутом` (score 87)
- MEDIUM: **Бургер в пите с тахини йогуртом** -> `Буррито в банке с фасолью и йогуртом` (score 83)
- MEDIUM: **Хрустящие рулеты из лаваша с креветкой** -> `Рулет из лаваша с тунцом` (score 83)
- MEDIUM: **Веганская окрошка на квасе с нутом** -> `Веганская шакшука с тофу` (score 82)
- MEDIUM: **Огуречный салат с мацони и грецким орехом** -> `Йогурт с ягодным соусом и грецким орехом` (score 81)
- MEDIUM: **Салат с арбузом, халуми и мятой** -> `Салат с тунцом, фасолью, яблоком и фетой` (score 77)
- MEDIUM: **Гаспачо с белой фасолью** -> `Куриный суп с белой фасолью и кейлом` (score 74)
- MEDIUM: **ПП-та6уле с булгуром и зеленью** -> `Омлет с творогом и зеленью` (score 72)
- MEDIUM: **бутерброды с говядиной и сыром** -> `Бутерброд с ветчиной и омлетом` (score 69)
- MEDIUM: **бутерброды с сыром и слабосоленой семгой** -> `Бутерброд с сыром и ветчиной` (score 69)
- MEDIUM: **Бутерброды с сыром и яйцом** -> `Бутерброд с сыром и ветчиной` (score 69)
- MEDIUM: **Гечка по купечески** -> `Гречка по-купечески с фаршем` (score 69)
- MEDIUM: **грудка запеченая с сыром и помидором** -> `Лаваш с сыром и помидором` (score 69)
- MEDIUM: **Грудка куриная с рисом и овощной нарезкой** -> `Курица с рисом и овощами на сковороде` (score 69)
- MEDIUM: **Запеченный минтай с лимоном и рисом** -> `Запеченный минтай с овощами` (score 69)
- MEDIUM: **Куриная запеканка под сыром** -> `Куриная запеканка кордон блю с брокколи и фузилли` (score 69)
- MEDIUM: **Куриные котлеты кусочками + макароны** -> `Куриные котлеты с кабачком` (score 69)
- MEDIUM: **ЛЕНИВАЯ ОВСЯНКА С БАНАНОМ** -> `Ленивая овсянка с ягодами и орехами` (score 69)

## Top rejection reasons

- poor nutrition feasibility: 66
- mostly sugar dessert: 49
- drink/cocktail: 33
- standalone sauce/dip/marinade: 25
- requires grill/mangal/open fire: 18
- no usable quantities: 12
- too complex/restaurant-style: 9
- rare/expensive ingredients: 2
- duplicate or near-duplicate of current FoodBalance recipe: 2
- missing ingredients: 1

## User instructions

1. Open the CSV or XLSX review table.
2. Read full recipe text in `source_ingredients_full` and `source_steps_full`.
3. Fill `user_decision` manually with `TAKE`, `SKIP`, or `MAYBE`.
4. Do not import anything until a later explicit import step.
5. Treat `GOOD_CANDIDATE` as a shortlist, not as a final decision.
6. Review rows marked with duplicate risk, OCR notes, missing steps, or adaptation notes before deciding.
