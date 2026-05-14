# Recipe Intake Review Backlog

Date: 2026-05-14

Scope: risky-recipe mapping-policy cleanup for `tmp/recipe_intake/cleaned_recipes.xlsx`. This pass did not import recipes into production curated data, did not touch builder/PDF/Telegram/promo/payments/storage, did not change the source Excel, and did not generate photos.

## Summary

- Workbook total: 105 recipes.
- Status before this policy pass: 105 `ready`, 0 `needs_review`.
- Status after this policy pass: 105 `ready`, 0 `needs_review`.
- Still `needs_review`: 0 recipes.
- Workbook action taken: approved mapping/rewrite decisions were recorded in the staging workbook through recipe text updates and ingredient `issue_note` policy marks.
- Production nutrition rows were not added.

## Decisions Applied

| Recipe | Action |
|---|---|
| `intake_032` | Dressing ambiguity resolved to Greek yogurt; crab sticks kept as an approved generic product. |
| `intake_053` | Protein ambiguity resolved to tofu only; recipe text, steps, tags, and photo prompt updated. |
| `intake_080` | Udon ingredient normalized to generic udon noodles. |
| `intake_084` | Brand-specific pumpkin wording replaced with generic pumpkin cubes. |
| `intake_089` | Re-slotted to snack/light meal; hummus marked as weak plant-protein anchor. |
| `intake_095` | Asparagus restored; only the pak-choi replacement remains as a future import note. |
| `intake_098` | Tomato variants normalized and vinegar wording cleaned. |
| `intake_100` | Prepared tomato sauce normalized to passata plus spices policy. |
| `intake_101` | Processed poultry product replaced with chicken fillet; spicy tomato sauce normalized to passata plus spices. |
| `intake_062`, `intake_086`, `intake_096`, `intake_104` | Seasoning, pork-chop, egg-yolk, and chopped-tomato mapping policies recorded. |
| `intake_093` | Falafel and Korean carrot kept as accepted prepared products; prepared mayo-soy sauce replaced with Greek yogurt 30 g, soy sauce 5 g, and lemon juice 5 g. |

## Mapping Policy Recorded

- Cod liver: keep recipes; use drained/no-extra-jar-oil policy unless a recipe explicitly uses oil; cod liver can be an anchor but is not a future scalable anchor.
- Simple mappings marked ready: dry buckwheat, grapes/kishmish, cornmeal/polenta, chicken liver, split peas, trout, basmati rice, pumpkin, asparagus, egg yolk, pork chop, tomato variants, and sun-dried tomatoes.
- Condiment/product policy marked ready: soy sauce, explicit-gram mayo, crab sticks, prepared falafel, Korean carrot, explicit-gram pesto, and modest explicit-gram teriyaki.
- Tomato sauces are normalized toward passata plus spices where the recipe wording allowed it.
- Low-impact seasoning is normalized to mixed spices or 0 g seasoning policy.

## Remaining Needs Review

None for the staging workbook.

No policy-adjusted risky recipes remain. For a future all-105 production import, `intake_093` should be promoted only through the staging policy notes that accept falafel and Korean carrot as prepared products and use the controlled yogurt-soy-lemon sauce.
