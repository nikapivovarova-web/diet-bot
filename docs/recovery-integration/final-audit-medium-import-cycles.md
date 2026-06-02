# Final Audit MEDIUM-3 Import Cycle Fix

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Verdict

MEDIUM-3 is closed locally.

The reported cycles were real static module-boundary cycles, but not observed
as top-level import crashes because the back edges were local imports. The
release risk was weak core ownership: recipe templates were owned by
`recipe_catalog` while curated data needed the same type, and entitlement JSON
storage needed the entitlement model while `subscriptions` also exposed legacy
JSON load/save wrappers.

## Exact Cycles Found

- `recipe_catalog <-> curated_data`
  - `recipe_catalog.built_in_recipes()` imported `curated_data.curated_recipes`.
  - `curated_data.curated_recipes()` imported `RecipeTemplate` from
    `recipe_catalog`.
- `entitlement_storage <-> subscriptions`
  - `entitlement_storage` imported `Entitlement` from `subscriptions`.
  - `subscriptions.load_entitlements()` and `subscriptions.save_entitlements()`
    imported `JsonEntitlementStore` from `entitlement_storage`.

## Fix

- Added `src/diet_bot/recipe_models.py` for the shared `RecipeTemplate` model.
- Updated `recipe_catalog` to import and keep exposing `RecipeTemplate` from the
  neutral model module.
- Updated `curated_data` to import `RecipeTemplate` from `recipe_models` instead
  of importing back from `recipe_catalog`.
- Added `src/diet_bot/entitlement_model.py` for the shared `Entitlement` model,
  entitlement source/status parsing, and datetime serialization helpers used by
  the entitlement model.
- Updated `subscriptions` to import and keep exposing `Entitlement`,
  `SubscriptionSource`, `AutoRenewStatus`, and shared helpers from
  `entitlement_model`.
- Updated `entitlement_storage` to import `Entitlement` from `entitlement_model`
  instead of importing back from `subscriptions`.
- Added `tests/test_import_boundaries.py` so the two MEDIUM-3 pairs cannot
  regain mutual local-import edges.

## Verification

Initial provenance:

- `git status --short`
  - Existing dirty recovery checkout before this MEDIUM-3 pass, including many
    unrelated changed and untracked files.
- `git branch --show-current`
  - `codex/recover-product-ui-on-hardened-master`
- `git rev-parse HEAD`
  - `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

RED before the fix:

- `PYTHONPATH=src python -m pytest tests/test_import_boundaries.py -q`
  - `1 failed`
  - Failure listed both cycles:
    - `recipe_catalog <-> curated_data`
    - `entitlement_storage <-> subscriptions`

GREEN after the fix:

- `PYTHONPATH=src python -m pytest tests/test_import_boundaries.py -q`
  - `1 passed in 0.08s`
- `PYTHONPATH=src python -m pytest tests/test_import_boundaries.py tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_builder_recipe_cache.py tests/test_weekly_selector_scoring.py tests/test_entitlement_storage.py tests/test_entitlement_service.py tests/test_entitlement_json_migration.py tests/test_subscriptions.py -q`
  - `193 passed, 1 skipped in 119.12s`
- `PYTHONPATH=src python -m pytest tests/test_postgres_entitlement_store.py -q -rs`
  - `35 passed, 12 skipped in 0.20s`
  - skipped cases require `DIET_BOT_TEST_DATABASE_URL`.
- `PYTHONPATH=src python -m compileall -q src/diet_bot/recipe_models.py src/diet_bot/recipe_catalog.py src/diet_bot/curated_data.py src/diet_bot/entitlement_model.py src/diet_bot/entitlement_storage.py src/diet_bot/subscriptions.py tests/test_import_boundaries.py`
  - exit code `0`
- `git diff --check`
  - exit code `0`
  - output contained LF-to-CRLF working-copy warnings only.

## Count

Updated local final pre-release audit count: `0 high / 0 medium / 6 low`.

`HIGH-3` sandbox/provider acceptance remains a separate paid-launch acceptance
gate and was not exercised in this MEDIUM-3 pass.

## Scope Boundaries

- No recipe data/import/photo files were changed.
- No legacy workbook/photo utilities were run.
- No bot process was started.
- No Telegram API or `getUpdates` call was made.
- No production database was used.
- No payments/provider/refund behavior was changed.
- No sales follow-up behavior was changed.
- No deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or
  recovered-bot work was done.

## Next Recommended Prompt

FoodBalance: run HIGH-3 sandbox/provider acceptance smoke only, with sandbox
DSN/provider credentials preflight and no production payment actions.
