# Batch Recipe Portions Design

## Goal

Make recipe portions feel realistic in a kitchen and make multi-serving recipes usable inside weekly rations. The bot should not tell a user to take 3 g flour, 10 g banana, half a raw egg, 3/4 potato, or a visibly wrong fruit fraction. When a recipe only makes sense as a batch, the ration should plan the batch across multiple days.

## Problems To Fix

- Household hints are too eager. Examples: 40 g orange shown as about 1/2 orange, 75 g mandarins shown as about 1/2 fruit portion, 80 g grapefruit shown as about 3/4 fruit portion, and 110 g potato shown as about 3/4 potato.
- Some ingredients are indivisible or awkward to divide in practice. Raw eggs should not be displayed as 1/2 egg in a normal cooking instruction.
- Multi-serving source recipes were normalized into one daily portion too literally. Muffins and similar recipes become unusable because the display shows tiny divided amounts instead of a normal batter.
- Weekly plans currently avoid recent recipe repeats, but batch recipes need intentional repeats until the prepared portions are eaten.

## Scope

This design covers curated recipe planning, ingredient display, Telegram meal cards, text week output, weekly PDF output, and shopping lists.

It does not change the nutrition target formulas, safety exclusions, or medical disclaimers. Nutrition totals still represent only what the user eats on that specific day.

## Recommended Approach

Use two related rules:

1. Human-friendly portion display for ordinary recipes.
2. Batch-prep carryover for recipes that should be cooked once and eaten over several days.

The builder keeps exact grams for nutrient math. Presentation can show rounded practical amounts. Batch recipes additionally keep two sets of quantities: eaten today and prepared in the full batch.

## Portion Hint Rules

Fruit and vegetable item hints should use realistic kitchen thresholds:

- Orange: treat one medium orange as roughly 250-320 g whole weight, or about 180-220 g edible weight. Do not call 40 g half an orange. For small amounts, omit the item hint or say a few slices.
- Mandarin: use plural-friendly hints such as 1 small mandarin, 2 mandarins, or a few segments. Do not compare mandarins through generic fruit portions.
- Grapefruit: treat one grapefruit as much larger than citrus snack portions. For 80 g, prefer a few segments or omit the hint; do not show 3/4 grapefruit.
- Potato: avoid 1/4 and 3/4 potato hints. Around 90-150 g should display as 1 small potato. If a fraction is unavoidable, only 1/2 potato is acceptable for a clearly large potato, but the preferred output is whole small/medium potatoes.
- Tomato can keep 1/2 tomato when plausible.
- Egg should only display whole eggs in ordinary recipes. If the recipe would require a raw half egg, it should either become a batch recipe or the egg hint should be omitted.

## Batch Recipe Detection

A recipe is batch-prep when either:

- Its instructions mention a batch container or repeated units such as 6/12 muffin cups, a muffin tin, bars, loaf, casserole, tray bake, or portions cut from one bake.
- It has ingredients that become impractical after per-portion scaling, such as less than 10 g flour, less than 25 g banana/apple, or fractional raw eggs.

Batch-prep candidates include muffins, egg muffins, baked oat cups, bars, loaves, granola bars, casseroles, and similar recipes.

## Batch Carryover Behavior

When a weekly ration selects a batch recipe, it creates a small carryover record:

- recipe id
- meal slot, usually snack or breakfast
- total prepared units, for example 6 muffins
- units eaten per serving, for example 2 muffins
- remaining units
- prepared ingredient grams for the full batch
- eaten ingredient grams for daily nutrition

Example: if the plan says "prepare 6 muffins, eat 2 today", the next two suitable days should reuse that recipe as "eat 2 muffins from the batch" before selecting a new snack recipe. The repeated recipe is intentional and should not be blocked by recent recipe history until the batch is finished.

If a user asks for a one-day plan outside a week, the bot can still show batch-prep wording, but it should not invent future days unless there is persisted carryover state. For weekly PDF generation, carryover is planned within the seven generated days.

## Presentation

Meal cards for the first day of a batch should show:

- Daily portion line, for example "Порция сегодня: 2 маффина".
- Batch note, for example "Приготовьте 6 маффинов на 3 перекуса".
- Ingredients for the full batch, using practical quantities.
- A short note that calories and nutrients for the day count only today's portion.

Carryover days should show:

- "Съешьте 2 маффина из приготовленной партии".
- No full repeated cooking instruction unless useful for context.
- Shopping list should include the batch ingredients only once for the week, not repeated each carryover day.

## Data Flow

Add batch metadata to the domain model without replacing current exact portions:

- `Meal.portions` remains the daily eaten portion for nutrition and validation.
- A new optional batch/prep metadata object can store prepared units, serving units, remaining units, and full-batch ingredient portions.
- Weekly planning should pass a carryover queue from day to day.
- The one-day builder can stay mostly unchanged, but weekly assembly needs a wrapper that consumes carryovers before selecting a fresh recipe for that meal slot.

## Validation

Validation should continue to check daily eaten grams against per-meal and per-day limits. For batch display, validation should also ensure:

- No batch recipe displays fractional eggs in full-batch ingredients.
- Full-batch ingredient display has no tiny absurd values for flour, banana, oats, sugar, or similar baking ingredients.
- Carryover meals preserve the original recipe id and do not count as variety failures while remaining units exist.
- Weekly shopping aggregates full-batch ingredients once.

## Testing

Add focused tests for:

- 40 g orange does not display as 1/2 orange.
- 75 g mandarins does not display as 1/2 fruit portion.
- 80 g grapefruit does not display as 3/4 grapefruit or 3/4 fruit portion.
- 110 g potato displays as 1 small potato rather than 3/4 potato.
- Half raw egg is not shown in ordinary ingredient hints.
- A muffin recipe selected for a weekly plan is prepared as a batch and repeated until its servings are finished.
- A 6-muffin batch eaten as 2 muffins per snack occupies three suitable snack slots before a new snack recipe is selected.
- Weekly shopping includes full-batch muffin ingredients once, not once per carryover day.

## Risks

Batch display adds a distinction between "prepared amount" and "eaten today". The UI must make that distinction explicit so users do not eat the full batch in one day. The implementation should keep nutrition math tied to daily eaten portions and keep full-batch quantities only for cooking instructions and shopping.
