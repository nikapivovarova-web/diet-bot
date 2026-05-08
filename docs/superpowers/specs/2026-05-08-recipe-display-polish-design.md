# Recipe Display Polish Design

## Goal

Make recipe ingredient text feel natural and useful for a person cooking from the bot.

The current display can over-explain broad categories, for example "1 горсть овощей", or attach the wrong category to an ingredient, for example tahini shown as "1 ложка орехов". Very small ingredient amounts can also look awkward when shown as "менее 1 г". The daily totals also show "добавленный сахар" even when it is always zero for generated plans.

## User-Facing Changes

1. Generic vegetable handful hints should omit the word "овощей":
   - Before: `лук - 50 г (примерно 1 горсть овощей)`
   - After: `лук - 50 г (примерно 1 горсть)`
   - Plurals should remain natural: `2 горсти`, `5 горстей`.

2. Tahini should not use nut wording:
   - Before: `тахини - 15 г (примерно 1 столовая ложка орехов)`
   - After: `тахини - 15 г (примерно 1 столовая ложка)`

3. Tiny flavoring amounts should use kitchen language instead of micro-grams:
   - Dry spices below 1 g: `корица - щепотка`
   - Fresh garlic below 1 g: `чеснок - по вкусу`
   - These lines should not append `г` for those tiny cases.

4. The daily nutrition totals should no longer display `добавленный сахар, г`.
   The internal nutrient target and calculations can stay unchanged; this is only a presentation change.

## Implementation Notes

Update the ingredient formatter in `src/diet_bot/chef.py`.

Add a tiny-ingredient display path before normal gram formatting. It should return a full ingredient line for spices and garlic below 1 g, because the normal formatter always appends grams.

Change the generic vegetable fallback forms from "горсть овощей" to plain "горсть" forms.

Special-case tahini before the generic `nuts_seeds` branch so it uses the same spoon sizing as sauces without category nouns.

Update `src/diet_bot/presentation.py` so `added_sugar_g` is removed from the visible `NUTRIENT_ORDER`. Leave `NUTRIENT_LABELS` intact unless removing the label is cleaner.

## Testing

Update presentation tests to cover:

- Generic vegetable hints do not contain "горсть овощей".
- Tahini hint does not contain "орехов".
- Spice below 1 g displays as `щепотка`.
- Garlic below 1 g displays as `по вкусу`.
- Plan response no longer contains `добавленный сахар`.
