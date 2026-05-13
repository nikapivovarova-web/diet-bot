# Recipe Coverage Smoke Notes

Date: 2026-05-14
Commit covered: `8aae199249dab1084231b8853a5530b724a4ba7b` (`8aae199 recipe quality: repair effort and slot coverage`)

## Scope

This was a smoke/check slice after the effort and slot coverage repair. No runtime code changes were made. Weekly samples were generated locally through internal plan-building functions, without a Telegram user-client flow.

## Focused Checks

| Check | Result |
| --- | ---: |
| `python -m pytest tests/test_recipe_effort_slot_coverage.py -q` | 9 passed |
| `python -m pytest tests/test_safety_and_builder.py tests/test_weekly_optimizer_candidates.py -k "exclusion or allergy or broccoli or egg" -q` | 42 passed, 47 deselected |
| Targeted weekly completeness/no-repeat/protein tests plus `tests/test_weekly_optimizer_candidates.py` | 17 passed |

The broad exploratory selector `-k "weekly or repeat or protein"` was stopped by timeout before completion and was replaced with the explicit targeted weekly/protein list above.

## Pool Counts

| Pool | Total | Breakfast | Main | Snack |
| --- | ---: | ---: | ---: | ---: |
| All runtime recipes | 12,975 | n/a | n/a | n/a |
| Curated recipes | 400 | 97 | 153 | 150 |
| SIMPLE curated after effort filter | 161 | 42 | 17 | 102 |
| INTERESTING curated after effort filter | 222 | 65 | 30 | 127 |

SIMPLE main-builder eligible counts for the MAINTAIN/simple/5 smoke profile:

| Main slot proxy | Total eligible | Native `main` | Snack-as-main fallback |
| --- | ---: | ---: | ---: |
| Lunch slot | 55 | 17 | 38 |
| Dinner slot | 55 | 17 | 38 |

This confirms the post-repair main-builder pool is 55 eligible recipes for both main slots in the smoke profile.

## Sample Results

Seed: `101`. Base profile: male, age 32, 178 cm, 86 kg, moderate activity, maintain goal, 5 meals.

| Sample | Status | Days/meals | Unique recipes | No repeats | Protein max ratio | Exclusions | Main-like snacks as main |
| --- | --- | --- | ---: | --- | ---: | --- | ---: |
| MAINTAIN/simple/5 no exclusions | Complete | 7 days, 5 meals/day | 35/35 | yes | 149.0% | n/a | 1 |
| MAINTAIN/simple/5 egg allergy | Complete | 7 days, 5 meals/day | 35/35 | yes | 154.2% | respected | 4 |
| MAINTAIN/simple/5 broccoli disliked | Complete | 7 days, 5 meals/day | 35/35 | yes | 141.7% | respected | 2 |
| MAINTAIN/interesting/5 no exclusions | Complete | 7 days, 5 meals/day | 35/35 | yes | 147.5% | n/a | 0 |

Observed daily protein ratios:

| Sample | Daily protein ratios |
| --- | --- |
| MAINTAIN/simple/5 no exclusions | 127.9%, 144.2%, 140.2%, 134.3%, 149.0%, 139.6%, 147.5% |
| MAINTAIN/simple/5 egg allergy | 132.8%, 150.5%, 137.7%, 154.2%, 145.1%, 135.7%, 136.3% |
| MAINTAIN/simple/5 broccoli disliked | 127.9%, 141.1%, 127.7%, 137.1%, 140.0%, 141.7%, 130.2% |
| MAINTAIN/interesting/5 no exclusions | 130.8%, 142.2%, 137.0%, 147.5%, 142.1%, 129.8%, 132.7% |

Egg allergy blocked IDs checked: `egg`, `egg_white`, `egg_white_extra`, `egg_yolk`, `egg_noodles`. None were present in portions or recipe ingredient IDs.

Broccoli disliked blocked ID checked: `broccoli`. It was not present in portions or recipe ingredient IDs.

## Known Limitations

- Weekly optimizer is still not wired into weekly assembly in this slice. The samples use the current `_build_week_plans` candidate loop.
- Coverage is repaired enough for these smoke profiles to build complete 7-day plans with no recipe ID repeats and controlled failure behavior covered by targeted tests.
- SIMPLE native main coverage is still only 17 recipes after the effort filter. The effective 55-recipe main-builder pool relies heavily on 38 snack-as-main fallback candidates.
- Protein quality is still not within the preferred `<= 130%` ceiling in these samples. Observed maximum daily ratios ranged from 141.7% to 154.2%.
- This smoke covers four MAINTAIN/5-meal profiles with seed `101`; it does not exhaustively cover all goals, meal counts, seeds, or restrictions.

## Weekly Optimizer Need

Yes, the weekly optimizer is still needed after coverage repair.

The repair appears sufficient for main slot coverage, complete 7-day assembly, no-repeat recipe IDs, and exclusion safety in this smoke slice. The remaining need is quality control: choosing among enough candidates to reduce protein overage, reduce reliance on snack-as-main fallback where possible, and preserve complete/no-repeat behavior across a wider seed/profile surface.
