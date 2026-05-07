# Weekly Ration PDF Design

## Goal

Change the 7-day ration flow so the Telegram bot does not send a long chain of weekly text messages by default. Instead, it should generate and send one polished PDF file that contains the same content the bot currently sends in Telegram: calculation context, every day, every meal, ingredient gram amounts, cooking instructions, daily nutrient totals, shopping list, warnings, and the final orientation note.

The PDF generation must be free at runtime for mass use. The bot must not call paid PDF APIs or any per-document external rendering service.

## Approved Direction

Use `reportlab` as the local Python PDF generator inside the existing bot process. It is free to run, works without network calls, and fits the current Python codebase.

The visual direction is a hybrid PDF:

- first page with user calculation summary and weekly overview
- each day shown as structured sections, not one text block
- each meal shown as one recipe block
- the meal photo placed inside that same recipe block, next to the recipe text
- final pages with the weekly shopping list, warnings, and orientation note

The PDF should organize the existing content; it should not shorten the recipe data just to make the file smaller.

## User Flow

1. User completes the questionnaire.
2. Bot shows the calculation summary and plan-choice buttons.
3. User chooses `Составить рацион на неделю (PDF)`.
4. Bot builds seven one-day plans with the existing weekly variety logic.
5. Bot tries to render a PDF.
6. If rendering succeeds, bot sends the PDF as a Telegram document.
7. If rendering fails, bot sends the full weekly ration using the existing text/photo flow so the user still receives the result.

The one-day ration flow remains unchanged.

## PDF Content

The PDF must include the same user-facing information as the current weekly Telegram output:

- calculation summary: BMI, BMI warning when applicable, maintenance calories, target calories, water, macro targets, and safety notes
- seven dated days
- each meal name
- ingredient list with gram amounts and household hints from the existing formatter
- full cooking instruction text
- meal nutrition chips for calories, protein, fat, and carbohydrates when available
- daily nutrient totals with coverage percentages
- weekly shopping list
- medical/safety disclaimers
- calorie-drink reminder
- final orientation sentence about the calculation being approximate

Photo placement rule:

- if a meal has a local image, render it inside that meal block, beside the text
- if a local image cannot be found or decoded, omit only that image and keep the recipe text
- remote image URLs should not be fetched during PDF generation in this pass; the PDF remains local and predictable
- image credits are shown in small text when attribution exists

## Layout

Use A4 portrait pages.

Suggested structure:

- Cover/summary page: title, date range, BMI/target/water/macros, short contents summary.
- Day pages: one day header, then meal cards. Each meal card uses a two-column layout when the page width allows: recipe text on the left, photo on the right. If there is no photo, the text uses the full width.
- Daily totals: compact nutrient table after the day’s meals.
- Shopping pages: grouped weekly shopping list.
- Footer: page number and `FoodBalance`.

The design should use restrained colors, readable typography, consistent margins, and enough spacing that it feels like a document rather than pasted chat text.

## Components

Add a dedicated module, for example `src/diet_bot/pdf_renderer.py`.

Responsibilities:

- accept a sequence of `MealPlan` objects and their dates
- format meal ingredients through existing presentation/chef helpers
- calculate and format daily totals from existing plan data
- build the weekly shopping list from existing shopping helpers
- resolve local meal image paths safely
- write the PDF to a temporary local file

Keep Telegram-specific sending in `telegram_app.py`. The PDF renderer should not import aiogram.

## Error Handling

PDF rendering should be best-effort but isolated:

- rendering errors should not crash the bot
- missing fonts should fall back to bundled/default fonts where possible
- missing or invalid images should not fail the entire PDF
- temporary PDF files should use unique names and be deleted after the Telegram send attempt finishes
- if any unrecoverable PDF error happens, the bot sends the current weekly text/photo flow as fallback

## Free Generation Constraint

Do not use:

- paid PDF APIs
- external document-generation services
- paid image or layout services
- runtime network calls to render the PDF

Allowed:

- local Python libraries such as `reportlab`
- local fonts and local recipe photos
- local temporary files

## Testing

Add tests for:

- PDF renderer creates a non-empty PDF for a valid 7-day plan
- PDF text extraction contains day headers, recipe names, ingredients, cooking instructions, daily totals, shopping list, and orientation note
- local meal photos can be resolved and included without failing
- missing meal photo paths do not fail PDF creation
- Telegram weekly flow sends a document when PDF rendering succeeds
- Telegram weekly flow falls back to the existing text/photo weekly output when PDF rendering raises an error
- the one-day flow remains unchanged

Manual verification:

- render a sample PDF
- inspect several pages visually for clipping, unreadable text, bad page breaks, and photo placement
- confirm the file opens locally

## Acceptance Criteria

- Pressing the weekly PDF button normally sends one PDF document instead of a long text/photo sequence.
- The PDF contains the full weekly ration content, not a shortened summary.
- Each recipe photo appears next to its own recipe block when a local photo exists.
- PDF generation is free and local.
- If PDF generation fails, the bot still sends the complete weekly ration text/photo output.
- Existing safety stops and recipe generation failures keep their current user-facing behavior.
