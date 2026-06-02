# Final Audit Low Hygiene And Content Batch

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Verdict

The targeted low-risk hygiene/content batch is closed locally for the final
pre-release audit count.

Updated local final pre-release audit count: `0 high / 0 medium / 3 low`.

## Finding Disposition

### LOW: README / Package MVP Wording

Status: closed with edit.

The README and package description no longer describe the project as an MVP or
as only a small deterministic nutrition core. They now describe the current
controlled-QA release surface: curated recipe data/photos, one-day ration
generation, weekly PDF rendering, Postgres-backed production storage and
durable queues, and controlled payment/promo/admin/reconciliation tooling that
remains disabled until explicit approval.

Changed files:

- `README.md`
- `pyproject.toml`

### LOW: Selected-53 Warning-Only Approximations

Status: closed as documented/accepted RC limitation.

The selected-53 warning-only mappings remain intentionally unchanged in this
batch:

- `r670`: beef tongue mapped to generic beef and kvass mapped to water.
- `r673`: turkey sausage mapped to lean poultry and kvass mapped to water.
- `r699`: kvass mapped to water.

Rationale: the current selected-53 final review already proves these rows have
no missing food references, no stale nutrition mismatch, no hard KBJU or
single-ingredient outlier, and saved nutrition matches the current catalog.
Fixing them safely would require adding or sourcing explicit food profiles for
kvass, beef tongue, and turkey sausage, then recalculating affected nutrition
rows. That is broader than this low-risk hygiene/content batch and is better
handled as a separate recipe-profile task.

### LOW: r706 Calamari / Protein Portion Warning

Status: closed as documented/accepted RC limitation.

`r706_salat_iz_kalmarov_i_yaits` remains source-preserved at `400 g` calamari
and `90.70 g` protein. The source row explicitly labels the ingredient list as
for one portion, and the current data is internally consistent with no missing
food/profile/photo issue and no hard outlier threshold breach. Reducing the
calamari amount would be an editorial nutrition inference, not a safe
low-risk correction.

## Remaining Low Findings

The three low findings left open are outside this batch's allowed scope:

- Privacy consent storage durability if legal/product requires persisted
  acceptance.
- Promo `per_user_limit` semantics before enabling multi-use discount
  campaigns such as `FOOD20`.
- Legacy JSON one-day generation path still calling the planner directly in the
  event loop.

## Verification

- `python scripts/dev/recipe_content_audit.py --no-write-report`
  - `recipes_checked=710`
  - `ingredients_checked=6478`
  - `foods_checked=366`
  - `nutrition_rows_checked=710`
  - `blocking_findings=0`
  - `warning_findings=1322`
- `python -m pytest tests/test_curated_recipe_data.py::test_selected53_recipe_batch_r666_r710_has_required_rows_and_photos tests/test_curated_recipe_data.py::test_selected53_recipe_batch_r666_r710_foods_are_resolved tests/test_curated_recipe_data.py::test_selected53_post_import_blocker_mappings_are_fixed -q`
  - `3 passed in 0.31s`
- README/package stale wording search:
  - `rg -n "MVP|small built-in|OpenAI chef|current build focuses|package description" README.md pyproject.toml`
  - no matches.

PDF/render smoke was not rerun because no recipe/content data, photos, PDF
renderer, or runtime rendering code changed in this batch.

## Scope Boundaries

- No recipe data, food profiles, ingredient rows, nutrition rows, recipe
  photos, PDF renderer, runtime, payment, provider, promo, privacy, sales
  follow-up, Telegram, or bot startup code was changed.
- No bot process was started.
- No Telegram API or `getUpdates` call was made.
- No production database was used.
- No provider/live payment, refund, cancel, reversal, or chargeback smoke was
  run.
- No deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or
  recovered-bot path was touched.

## Next Recommended Prompt

FoodBalance: fix only the privacy-consent durability low finding, or explicitly
document it as accepted, with no payment/provider smoke, no bot start, no
Telegram API/getUpdates, no production DB, and no unrelated promo, JSON
planner, recipe, PDF, sales-follow-up, deploy, push, commit, tag, PR, archive,
`New project 2 CLEAN`, or recovered-bot work.
