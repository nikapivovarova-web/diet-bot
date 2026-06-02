# Approximate Measures Round 2

Scope: confident household measures for common user-hostile gram-only ingredients in curated recipe ingredient data.

Guardrails followed:

- No PDF, Telegram/privacy/questionnaire, payment, runtime, storage, deploy, bot, push, PR, tag, or commit work.
- No recipe titles or recipe instructions were changed.
- No attempt was made to clear every remaining approximate-measure warning; ambiguous rows were left for review.

## Inspection Summary

- Ingredient rows inspected by audit: 6130.
- Current pre-batch audit baseline: `warning_findings=1494`, `missing_approximate_measures.warnings=406`.
- Approximate measures added/normalized in this batch: 514 ingredient rows.
- Post-batch audit: `warning_findings=1221`, `missing_approximate_measures.warnings=133`.
- Missing-approximate warnings reduced by 273. The row update count is higher because salt/pepper and several seed/measure cases were outside the audit's missing-approximate heuristic but were still common high-confidence gram-only UX issues.

## Categories Handled

- Garlic: 50 rows, e.g. `1/4 зубчика`, `1/2 зубчика`, `1 зубчик`.
- Dates: 2 rows, e.g. `1 финик`, `2-3 финика`.
- Salt and black pepper: 215 rows in the confident 0.25-1 g band, e.g. `щепотка`, `1-2 щепотки`.
- Sauces and pastes: 73 rows for mayonnaise, soy/teriyaki/hot sauce, tomato paste, nut pastes, tahini, hummus, pesto, salsa.
- Nuts and seeds: 90 rows for walnuts, almonds, cashews, peanuts, pecans, pine nuts, pistachios, Brazil nuts, mixed nuts, pumpkin/sesame/sunflower seeds.
- Small cheeses: 84 rows for gouda, cheddar, parmesan, feta, cream cheese, ricotta, mozzarella, goat cheese, Swiss cheese, Monterey Jack.

## Examples

| Row | Before | After |
| --- | --- | --- |
| `r214` | `чеснок — 5 г` | `чеснок — 5 г (примерно 1 зубчик)` |
| `r649` | `финики — 15 г` | `финики — 15 г (примерно 1 финик)` |
| `r651` | `финики — 35 г` | `финики — 35 г (примерно 2-3 финика)` |
| `r493` | `соевый соус ... — 5 г` | `соевый соус ... — 5 г (примерно 1 ч. л.)` |
| `r021` | `соль — 1 г` | `соль — 1 г (примерно 1-2 щепотки)` |
| `r007` | `Чеддер/грюйер — 12,5 г` | `Чеддер/грюйер — 12,5 г (примерно 1 тонкий ломтик)` |
| `r019` | `миндальные лепестки — 6,25 г` | `миндальные лепестки — 6,25 г (примерно 1 ст. л.)` |
| `r306` | `поджаренный грецкий орех или пекан — 5 г` | `поджаренный грецкий орех или пекан — 5 г (примерно 1 ст. л.)` |

## Intentionally Left Unresolved

- Cottage cheese and larger dairy portions where grams may be clearer than rough cup/spoon conversions.
- Pasta, grains, seafood/protein portions, and tomato/tomato-sauce rows where dry/cooked state or serving shape is ambiguous.
- Very tiny precise seasoning rows such as nutmeg and other micro spice amounts.
- Rows that look structurally suspicious or need content review before a measure, such as the remaining roasted-pepper/tomato/combined-ingredient candidates.
- Large sauce or paste amounts where the household conversion would become clumsy and less useful.

## Verification

- Targeted RED before data changes:
  - `pytest tests/test_curated_recipe_data.py::test_round2_confident_approximate_measure_targets_are_not_gram_only tests/test_curated_recipe_data.py::test_round2_garlic_and_date_examples_have_household_measures_when_present tests/test_curated_recipe_data.py::test_round2_sauce_and_paste_measures_do_not_use_dry_grain_wording -q`
  - Result: `2 failed, 1 passed`.
- Targeted GREEN after data changes:
  - Same command.
  - Result: `3 passed`.
- Current audit after data changes:
  - `python scripts/dev/recipe_content_audit.py`
  - Result: `blocking_findings=0`, `warning_findings=1221`, `missing_approximate_measures.warnings=133`.

Final requested pytest and diff-check results are recorded in `docs/recovery-integration/recovery-status.md`.
