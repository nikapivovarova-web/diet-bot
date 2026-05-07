# Friendly Portion Display Design

## Goal

Make the diet bot's recipe output feel like kitchen guidance instead of lab data. User-facing meal cards, plan messages, and PDFs should avoid odd visible amounts such as 296 g, 54 g, 48 g, 73 ml, 8.33 g, or 0.071 tsp. Internal nutrition calculations must keep using exact gram values.

## Scope

This change covers presentation only:

- ingredient lines shown in Telegram and PDFs
- household measure hints in parentheses
- recipe instruction text loaded from curated recipes
- shopping list quantities, where rounded display is more useful than exact decimals

It does not change calorie, macro, micronutrient, safety, recipe selection, or validation calculations.

## Approach

Add a small presentation layer around portions:

- Round visible grams to kitchen-friendly steps.
- Keep sub-gram amounts as "менее 1 г".
- Use 1 g steps for tiny amounts, 5 g steps for ordinary ingredients, and 10 g steps for larger portions.
- Use cautious household hints only when the conversion is plausible.
- Sanitize instruction text with the same display philosophy: round g/ml values and normalize tiny fractional teaspoon/tablespoon measures into "щепотка", "1/4 ч. л.", "1/2 ч. л.", or similar common kitchen amounts.

## Household Hints

Hints should be practical, not mathematically over-eager:

- Yogurt, kefir, milk-like dairy, and cottage cheese can show tablespoons for small amounts and cup fractions only from realistic thresholds.
- Oil can show teaspoons or tablespoons.
- Grains can show tablespoons for dry portions.
- Eggs, bread, tortillas, fruit, vegetables, berries, nuts, seeds, proteins, and avocado can keep item/handful/slice/palm hints where meaningful.
- Very small amounts should not be forced into "1/2 стакана" or "1/2 банка". If no safe household hint exists, omit it.

## Data Flow

`builder.py` keeps exact portion grams. `chef.py` owns user-facing formatting through `format_ingredient()`. `presentation.py` and `pdf_renderer.py` already consume that formatter, so most surfaces benefit from one implementation. Recipe instructions are sanitized when curated recipes are loaded in `curated_data.py`, so every downstream renderer receives cleaned text.

## Testing

Add focused tests for:

- 48 g yogurt displays around 50 g and does not claim half a glass.
- 11 g yogurt displays as a tablespoon-scale amount.
- common values such as 54 g, 73 g/ml, and 296 g round to friendly values.
- recipe instructions with fractional g/ml/tsp/tbsp values are cleaned.
- existing sub-gram behavior still says "менее 1 г".

## Risks

Displayed portions will no longer exactly match internal nutrition totals. That is intentional and should be acceptable because the bot already describes the ration as approximate. Keep the wording around visible portions approximate enough to avoid implying precision.
