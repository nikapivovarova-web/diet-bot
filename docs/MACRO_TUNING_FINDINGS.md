# Macro Tuning Findings

## Context

The weekly curated recipe sample now builds complete weeks after the coverage repair:

- 7 days with 5 meals per day.
- 35/35 unique recipe IDs.
- exclusions respected.

The remaining quality risk is protein overage. The observed baseline weekly max protein ratio for the normal MAINTAIN / SIMPLE / 5-meal sample was about 1.49.

## Attempted Slice

A focused macro-selection experiment tried to strengthen day and weekly candidate scoring without changing hard constraints or returning to a larger weekly optimizer.

Findings:

- A simple day-selection macro score reduced the observed weekly max protein ratio from about 1.49 to roughly 1.4067, but it did not reach the target of `<= 1.30`.
- Adding protein tiers at recipe-ranking time made protein quality more visible, but it broke weekly completeness in the sampled path.
- Macro scoring alone did not solve the problem safely. It can prefer better days among available candidates, but the candidate generator still produces many days whose recipe portions have already overshot protein before weekly selection can choose.

## Constraints To Preserve

Future work must keep these as hard constraints:

- exclusions;
- no-repeat recipe IDs / keys across the week;
- protein floor;
- complete weekly plan.

The tuning should not trade these constraints away to improve macro quality.

## Next Direction

The more promising next approach is portion-level protein adjustment: scale protein anchor ingredients and high-protein supporting ingredients before or during finalization, while preserving meal completeness and slot coverage.

Future design should avoid long, unbounded optimizer experiments. Keep the next slice bounded around portion scaling rules, with targeted fixtures that prove a feasible lower-protein variant can be produced without weakening coverage, exclusions, no-repeat, protein floor, or complete-week requirements.
