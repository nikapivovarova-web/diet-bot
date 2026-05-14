# Recipe Intake Risky Triage

Date: 2026-05-14

Scope: mapping-policy triage for the 34 recipes previously marked risky in `docs/RECIPE_INTAKE_IMPORT_PREVIEW.md`, applied only to `tmp/recipe_intake/cleaned_recipes.xlsx` and intake docs. No production curated recipe, nutrition, photo, builder, PDF, Telegram, promo, payments, storage, or source workbook data was changed.

## Summary

- Starting preview state: 105 structurally ready recipes, with 68 full-mapped, 3 near-full, and 34 risky for nutrition readiness.
- Workbook cleanup applied approved user decisions for normal-food mappings, generic condiment/product policies, tomato normalization, ambiguous ingredients, asparagus restoration, pumpkin wording, udon wording, and the processed-poultry replacement.
- The unchanged dry-run preview now reports 75 full-mapped, 2 near-full, and 28 risky.
- The unchanged dry-run still flags approved items because it does not yet consume workbook `issue_note` policy marks.
- Policy-adjusted readiness from workbook notes is 102 full-mapped, 2 near-full, and 1 risky.

## Before / After Counts

| Classification layer | Full mapped | Near-full | Risky |
|---|---:|---:|---:|
| Original dry-run before this pass | 68 | 3 | 34 |
| Current unchanged dry-run after workbook rewrites | 75 | 2 | 28 |
| Policy-adjusted readiness after user-approved decisions | 102 | 2 | 1 |

## Resolved By This Pass

- Ingredient ambiguity resolved: `intake_032` now uses yogurt, and `intake_053` now uses tofu only.
- Product-specific wording resolved: `intake_080` uses generic udon noodles, and `intake_084` uses generic pumpkin cubes.
- Slot/anchor policy resolved: `intake_089` is now a snack/light meal, with hummus marked as a weak plant-protein anchor.
- Protein/product rewrite resolved: `intake_101` now uses chicken fillet and passata plus spices.
- Asparagus restored: `intake_095` uses asparagus in title, ingredients, steps, and photo prompt.
- Tomato policy recorded: cherry tomatoes, passata/pureed tomatoes, canned/chopped tomatoes, tomato sauce, and spicy tomato sauce have staging policy notes.
- Alias/seasoning policy recorded: pork chop, egg yolk, basmati rice, khmeli-suneli, and universal seasoning.
- Generic product policy recorded: soy sauce, explicit-gram mayo, crab sticks, falafel, pesto, and modest teriyaki.

## Current Dry-Run Caveat

The dry-run script was rerun without changing production data or import code. It still classifies 28 recipes as risky because it only uses current production food aliases and a hard-coded semi-prepared term check. It does not read staging `issue_note` approvals such as cod liver readiness, grape readiness, generic mayo policy, or tomato policy.

This is expected for this cleanup slice. The next preview/import task should either consume the workbook policy notes or add production nutrition aliases in a separate controlled change.

## Remaining Policy-Adjusted Risk

| recipe_key | Reason |
|---|---|
| `intake_093` | Frozen/prepared falafel is accepted, but the large prepared mayo-soy sauce and Korean-carrot component still need either decomposition or explicit generic-product acceptance before an all-105 import. |

## Near-Full Items Still Not Risky

| recipe_key | Remaining small gap |
|---|---|
| `intake_010` | Sumac is still unmapped; macro impact is tiny. |
| `intake_091` | Frying oil wording remains approximate; recipe also has no main protein anchor by design. |

## Recommendation

Do not import from this triage report directly. Re-run the import preview in a separate task with the workbook policy marks accounted for. A production import can then promote the policy-ready slice while either deferring or decomposing `intake_093`.
