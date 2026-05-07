# Nutrient Time Filter Plan Flow Design

## Goal

Update the Telegram diet bot so it builds and presents a personalized diet plan around the expanded nutrient checklist, the user's cooking-time preference, and a clearer post-questionnaire flow.

After the user completes the questionnaire, the bot should first show the calculation summary: BMI, maintenance calories, daily calorie target, water, and macro targets. It should then show two buttons:

- `Составить рацион на 1 день`
- `Составить рацион на неделю (PDF)`

The one-day button should run the current one-day plan generation. The weekly PDF button is visible but not active yet; pressing it should return: `Функция рациона на неделю в PDF пока в разработке.`

## Questionnaire

Add a new required question after meal count:

`Сколько времени вы готовы тратить на готовку в день?`

Options:

- `до 15 минут`
- `15–30 минут`
- `более 30 минут`

Store the answer in `UserProfile` as a normalized enum-like value. The choice is a cooking-time filter for recipe selection.

## Cooking-Time Filter

Recipe data already contains `time_text`. Runtime templates should expose a parsed `cooking_time_minutes` or a cooking-time bucket:

- `quick`: up to 15 minutes
- `medium`: 16-30 minutes
- `long`: more than 30 minutes

Selection behavior:

1. Try to build the full requested meal count using recipes that fit the selected bucket.
2. If not enough eligible recipes exist, expand one level:
   - `до 15 минут` may use `15–30 минут`
   - `15–30 минут` may use `более 30 минут`
   - `более 30 минут` already allows all buckets
3. Keep existing safety, allergy, intolerance, disease, and excluded-food filters stricter than the time filter.
4. If the expanded recipe set still cannot produce a complete plan, fall back to existing behavior.

The time filter should affect curated and generated recipe templates consistently where time metadata is available. Recipes without parseable time should be treated as `medium` unless their instructions clearly make them quick or long.

## Nutrient Scope

The final daily totals should include every requested nutrient:

- calories
- protein
- fat
- carbohydrate
- fiber
- calcium
- iron
- magnesium
- zinc
- iodine
- selenium
- potassium
- sodium
- phosphorus
- saturated fat
- vitamin D
- vitamin B12
- folate / B9
- vitamin A
- vitamin C
- vitamin E
- vitamin K
- vitamin B1
- vitamin B2
- vitamin B3
- vitamin B6
- added sugar
- omega-3

For each row, show:

- actual amount in the generated ration
- target or limit
- percent of target coverage

For nutrients already present in the catalog, use the existing `NutrientVector` summing path. For nutrients not yet present in food data, add stable keys and target defaults now; totals will show `0` until data is populated. Added sugar should be treated as a limit, not a minimum target.

## Target Calculation

Keep the current profile-based calculation for calories, protein, fat, carbohydrates, fiber, water, BMI, BMR, and TDEE.

Expand micronutrient target defaults with adult reference values differentiated by sex and age where the current code already has enough profile data. Do not ask extra medical questions for this pass.

Priority nutrients used for ranking should include the expanded list where data exists. Energy, protein, fiber, calcium, iron, magnesium, potassium, vitamin D, B12, folate, vitamin C, and omega-3 remain high-priority because they materially affect current recipe selection.

## Presentation

The plan total section should be renamed or structured so it is clear that it includes daily nutrient coverage. Each nutrient line should follow one consistent shape, for example:

`- белки, г: 112.0 / 120.0 (93%)`

At the end of the generated ration output, add exactly this sentence:

`Это ориентировочный расчёт. В реальности состав продуктов может немного отличаться из-за бренда, способа приготовления и точности порций.`

This sentence appears after the ration calculation is shown. It should not replace existing medical/safety disclaimers.

## Telegram Flow

Current behavior generates the plan immediately after the questionnaire. Replace that with:

1. User completes questionnaire.
2. Bot builds `UserProfile`.
3. Bot calculates targets and sends the calculation summary.
4. Bot sends inline buttons:
   - `Составить рацион на 1 день`
   - `Составить рацион на неделю (PDF)`
5. If the user presses the one-day button, generate and send the one-day plan, meal cards, totals, and shopping list using the current flow.
6. If the user presses the weekly PDF button, answer: `Функция рациона на неделю в PDF пока в разработке.`

The existing "generate another one-day plan from the same profile" behavior should still work after a one-day plan has been generated.

## Error Handling

- Invalid cooking-time answers should prompt the user to choose one of the three options.
- A week-PDF button press should not crash or clear the user's session.
- If cooking-time filtering leaves too few recipes, broaden the time bucket before failing.
- Safety red flags still stop plan generation before any recipe filtering.
- Unknown or missing nutrient values should be treated as zero and should not break formatting.

## Testing

Add or update tests for:

- questionnaire completion with the new cooking-time answer
- cooking-time question options
- parsing the cooking-time answer into `UserProfile`
- one-day recipe selection respecting the cooking-time filter and broadening one level when needed
- expanded nutrient target keys
- final totals showing percent coverage
- final orientation sentence
- post-questionnaire Telegram flow showing calculation first and one-day / weekly PDF buttons
- weekly PDF button returning `Функция рациона на неделю в PDF пока в разработке.`

## Acceptance Criteria

- The questionnaire includes the new cooking-time question with exactly three button options.
- The bot no longer generates a plan immediately after the last questionnaire answer.
- The calculation summary appears before plan-generation buttons.
- `Составить рацион на 1 день` runs the existing one-day ration generation.
- `Составить рацион на неделю (PDF)` is visible and returns `Функция рациона на неделю в PDF пока в разработке.`
- Recipe selection uses the selected cooking-time filter and expands by one interval if needed.
- The final daily totals include the full requested nutrient list with percent coverage.
- The exact orientation sentence appears at the end of the ration output.
