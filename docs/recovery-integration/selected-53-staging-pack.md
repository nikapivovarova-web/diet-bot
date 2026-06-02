# Selected 53 Staging Pack Report

## Source

- Source file path: `C:\Users\adck8\Desktop\РЕЦЕПТЫ НОВЫЕ 30.05.xlsx`
- Workbook sheet: `Review Table`
- Recipes parsed count: 52
- Count note: Source workbook contains 52 non-empty data rows, although the task label says 53 selected recipes.

## Output

- Staging folder: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\staging_recipes\selected-53`
- Recipes JSON: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\staging_recipes\selected-53\recipes.json`
- Ingredients JSON: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\staging_recipes\selected-53\ingredients.json`
- Review CSV: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\staging_recipes\selected-53\review-table.csv`
- Review XLSX: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\staging_recipes\selected-53\review-table.xlsx`
- Photo prompts CSV: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\staging_recipes\selected-53\photo-prompts.csv`
- Photos folder: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\staging_recipes\selected-53\photos`
- README: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\staging_recipes\selected-53\README.md`

## Quality Summary

- Ready for import count: 38
- Needs user decision count: 14
- Photos generated count: 38
- Photos pending count: 0

## Duplicate Risks

- low: 38
- medium: 14

## Nutrition Status Summary

- not_calculated_standalone_snack: 1
- pending_estimation_needed: 33
- pending_needs_quantity_review: 18

No precise nutrition values were invented. Source nutrition was absent in the workbook, so nutrition remains pending for later calculation from the normalized ingredient table.

## Top Issues Needing User Decision

- редкое масло: можно заменить нейтральным растительным
- редкий для СНГ ингредиент: эдамаме
- редкий для СНГ ингредиент: фенхель
- не базовый СНГ-продукт: тахини/кунжутная паста
- не базовый СНГ-продукт: рисовая бумага
- не базовый СНГ-продукт: тахини/кунжутная паста; редкое масло: можно заменить нейтральным растительным
- дубликат внутри выбранного staging pack; нужно выбрать одну версию
- дубликат внутри выбранного staging pack; нужно выбрать одну версию
- соус Цезарь требует безопасного решения по яйцам; батон без количества
- OCR/quantity issue: картофель указан как 150 кг
- у блюда с печенью отсутствуют количество и шаги для картофеля
- не базовый СНГ-продукт: тахини/кунжутная паста

## Next Step For Later Import

1. Review `review-table.csv` or `review-table.xlsx` and fill `user_decision`.
2. Resolve recipes blocked by rare/non-CIS ingredients, duplicate candidates, missing quantities, or standalone snack status.
3. Use the generated PNGs in `photos/` for approved ready recipes, or replace any that the user rejects.
4. In a separate future task, map approved staging records into FoodBalance curated data.

## Guardrails Confirmed

This task prepared staging files only. It did not import recipes into FoodBalance curated data and did not intentionally modify production code, bot runtime, Telegram, PDF, payments, release blocker files, or archive/recovered folders.
