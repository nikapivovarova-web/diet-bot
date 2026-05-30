# Stage 16 Telegram UX Quick Fixes

## What Changed

- Removed the extra weekly PDF admission notice from the durable Postgres admission path.
- Added the calculation intro before BMI/calories/water/BJU.
- Added the calculation follow-up before the one-day ration or action buttons.
- Added a short KBJU line to each daily meal card and daily ration text.
- Updated the offer copy shown after the free one-day ration.

## Duplicate PDF Message Fix

The Postgres weekly PDF admission handler no longer sends the separate `WEEK_PDF_ACCEPTED_TEXT` message. The user-facing generation notice is now the single polished status message:

`Собираю ваш недельный PDF. Обычно это занимает 1-3 минуты. Можно закрыть Telegram — я пришлю файл сюда, когда он будет готов.`

The queue/worker status path still uses this message when generation actually starts.

## Calculation Copy

`format_calculation_summary` now starts with:

`Готово. Вот что я рассчитал специально под тебя:`

After the calculation details and safety notes, it now adds:

`Твой рацион на сегодня составлен так, чтобы покрыть эти показатели вкусной и разнообразной едой. Смотри:`

## Per-Meal KBJU Source

The per-meal KBJU line is formatted from `Meal.nutrients`.

`Meal.nutrients` is calculated from the meal's `FoodPortion` values, which derive nutrients from `Food.nutrients_per_100g` scaled by grams. No nutrition numbers were invented or hardcoded in presentation code.

For meal names with role prefixes such as `🍳 Завтрак: ...`, the KBJU line uses the role label (`Завтрак`) so long meal cards do not duplicate the full dish title.

## Offer Copy

The post-free-ration offer now explains the weekly menu, recipes with grams, KBJU per dish, vitamin/mineral table, shopping list, and monthly access as 4 weekly rations plus 5 additional days.

Payment buttons and paywall mechanics were left unchanged.

## Tests Run

- RED before implementation:
  `pytest tests/test_questionnaire_and_presentation.py::test_calculation_summary_adds_stage16_intro_and_follow_up tests/test_questionnaire_and_presentation.py::test_plan_response_includes_per_meal_kbju_lines_from_real_nutrients tests/test_questionnaire_and_presentation.py::test_meal_card_includes_kbju_line_from_meal_nutrients tests/test_telegram_app_photos.py::test_trial_subscription_keyboard_has_cta_button tests/test_telegram_app_photos.py::test_postgres_weekly_pdf_admission_does_not_send_duplicate_generation_message -q`
  - `5 failed`
- GREEN after implementation:
  same command
  - `5 passed`
- Regression check for the long-card title issue:
  `pytest tests/test_questionnaire_and_presentation.py::test_plan_response_includes_per_meal_kbju_lines_from_real_nutrients tests/test_questionnaire_and_presentation.py::test_meal_card_includes_kbju_line_from_meal_nutrients tests/test_telegram_app_photos.py::test_long_meal_card_sends_photo_without_duplicate_title -q`
  - `3 passed`
- Requested targeted suite:
  `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_photos.py -q`
  - `201 passed`
- Whitespace check:
  `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF warnings for dirty files.

## Remaining Risks

- The repository already had many unrelated dirty files before Stage 16; this stage did not revert or normalize them.
- Durable weekly PDF admission no longer sends an immediate accepted text; the single generation notice is sent by the weekly PDF status path when the worker handles the job.
- No live bot restart or live payment action was run.
