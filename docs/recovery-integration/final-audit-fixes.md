# FoodBalance Final Audit Fixes

## B-AUDIT-1 Fish Exclusion / Sardines

- root cause
  - `Restriction(EXCLUDED_FOOD, "fish")` matched the `fish` category in `src/diet_bot/safety.py`, but that category did not include the catalog food IDs `sardines` or `herring`.
  - Seafood/shellfish IDs such as `calamari`, `shrimp`, `clams`, `mussels`, `scallops`, `crab_sticks`, and `seafood_mix` were only in the separate `seafood` category, so a user who excluded fish could still receive aquatic animal recipes.

- fix
  - Expanded the `fish` exclusion category to include all fish and seafood-like catalog IDs found in `curated_foods.json`, including `sardines`, `herring`, `calamari`, `clam_stock`, `clams`, `crab_sticks`, `mussels`, `scallops`, `seafood_mix`, and `shrimp`.
  - Added Russian and English aliases for sardines, herring, red fish/salmon wording, seafood, shellfish, shrimp, squid/calamari, mussels, scallops, clams/clam juice, and crab.
  - Added `clam_stock` to the standalone `seafood` category so explicit seafood exclusion covers clam juice as well.
  - Policy for this blocker: user-facing fish exclusion is treated as an aquatic animal exclusion in filtering. The separate seafood trigger remains available.

- tests
  - Added `test_excluded_fish_filters_sardines_and_aquatic_catalog_foods`, which failed before the fix because `sardines`, `herring`, and seafood IDs remained eligible, then passed after the taxonomy update.
  - Added `test_excluded_fish_profile_does_not_receive_sardine_recipe`, which verifies a fish-excluding user profile can build a valid curated one-day plan without sardine ingredients or sardine recipe IDs.
  - Verified non-fish foods (`chicken_breast`, `greek_yogurt`, `mushrooms`, `tofu`, `whole_grain_bread`) remain eligible under fish exclusion.
  - `pytest tests/test_safety_and_builder.py tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q` passed: `121 passed in 680.53s`.
  - `python scripts/dev/recipe_content_audit.py` passed with `blocking_findings=0`.

- remaining risks
  - B-AUDIT-2 weekly constrained generation remains open and was not changed in this stage.
  - Very constrained combinations such as no dairy + no meat + no fish may still need the separate B-AUDIT-2 feasibility/timeout work.
  - Telegram UX copy was not changed, so the current policy is enforced in taxonomy/filtering rather than explained through new questionnaire text.

## B-AUDIT-2 Weekly Constrained Generation

- root cause
  - Narrow exclusions leave too few strict-simple recipes for a no-repeat week: `dairy + meat + fish` has fewer usable strict-simple main recipes than the 14 weekly main slots, and vegan-like profiles are tighter.
  - The old no-recent weekly path kept trying unique daily candidates and could spend `45-60s` before returning no complete weekly plan.
  - Hard dietary filters were already correct after B-AUDIT-1; the failure was weekly uniqueness under a small eligible pool, not missing exclusions.

- fallback repeat strategy
  - Normal no-repeat weekly selection remains first for profiles that pass the existing path.
  - Empty-recent constrained profiles now get a fast feasibility precheck. If eligible weekly slot pools are below the repeat-fallback threshold, generation switches to `repeats_fallback` instead of spending the old no-recent timeout.
  - The repeat fallback builds a bounded pool of valid one-day plans, then fills seven days with a simple deterministic scheduler.
  - Dairy-excluded constrained profiles use a bounded slot-candidate pool from safe curated recipes: top 8 candidates per slot, at most 50 ranked combinations materialized, hard nutrition gates preserved.
  - Dairy-allowed constrained profiles first use the existing safe one-day builder for up to 7 seeds, then can fall back to the slot pool if needed.
  - Scheduling minimizes repeated recipe additions and repeat pressure, avoids adjacent repeats when an alternative exists, and keeps hard exclusions intact.
  - Fallback metadata is returned via `avoidance_phase="repeats_fallback"`, `repeat_fallback_used`, `repeat_recipe_count`, and `repeat_note`. No PDF layout or Telegram UX changes were made.

- timing before/after
  - Before: `dairy + meat + fish` audit-shaped profile failed with `0` days in `27.090s` in the diagnosis probe; checkpoint reproduction also observed the old path reaching about `60s`.
  - After: `dairy + meat + fish` generated `7` days in `10.752s`, fallback used, repeat count `19`.
  - Before: `meat + fish` hit the old `no_recent` timeout at `60.026s`.
  - After: `meat + fish` generated `7` days in `18.308s`, fallback used, repeat count `15`.
  - After: `dairy + meat` generated `7` days in `3.690s`, fallback used, repeat count `20`.
  - Before: vegan-like `dairy + meat + fish + egg` failed in `45.479s`.
  - After: vegan-like failed structurally in `5.742s` with `failure_reason="repeats_fallback_no_valid_day_pool"` and no complete plan.
  - Normal/single-exclusion probe remained no-repeat: baseline `4.103s`, no fish `19.263s`, no dairy `15.032s`, no meat `23.638s`, all repeat count `0`.

- repeat counts
  - `dairy + meat`: `20` repeated recipe IDs across `28` weekly recipe slots.
  - `dairy + meat + fish`: `19` repeated recipe IDs across `28` weekly recipe slots.
  - `meat + fish`: `15` repeated recipe IDs across `28` weekly recipe slots.
  - Baseline, no fish, no dairy, and no meat cases: `0` repeated recipe IDs in the timing probe.

- exclusion validation
  - Focused tests assert planned food IDs stay within the `filter_foods(..., evaluate_safety(profile))` eligible set.
  - Timing probe reported `exclusions_ok=True` for constrained fallback cases.
  - No recipe JSON/data was changed, and dietary exclusions were not relaxed.

- tests
  - Focused B-AUDIT-2 tests: `pytest tests/test_safety_and_builder.py::test_weekly_no_dairy_meat_fish_uses_repeats_fallback_without_excluded_foods tests/test_safety_and_builder.py::test_weekly_no_meat_fish_no_longer_waits_for_no_recent_timeout tests/test_safety_and_builder.py::test_weekly_repeats_fallback_keeps_constrained_repeats_bounded tests/test_safety_and_builder.py::test_weekly_impossible_profile_returns_structured_failure -q` -> `4 passed in 37.23s`.
  - Weekly PDF/Postgres wiring: `pytest tests/test_weekly_pdf_postgres_wiring.py -q` -> `25 passed in 3.43s`.
  - Isolated slow repeat-generation tests:
    - `test_repeat_generation_changes_recipes` -> `1 passed in 28.84s`.
    - `test_repeat_generations_can_avoid_recent_recipe_ids` -> `1 passed in 89.36s`.
    - `test_repeat_generations_can_avoid_recent_recipe_families` -> `1 passed in 112.14s`.
  - `git diff --check` exited `0`; Git printed LF-to-CRLF working-copy warnings only.
  - Full `pytest tests/test_safety_and_builder.py -q` was not rerun to completion after the hard-stop instruction. Earlier attempts exceeded practical timeouts (`240s` and `604s`) because the broad safety module includes existing slow full-builder coverage.

- remaining risks
  - Repeat counts are intentionally high for the narrowest valid profiles; this is the requested tradeoff to return a complete weekly ration without violating exclusions.
  - Vegan-like profiles can still fail if no valid fallback day pool exists, but they now fail structurally and quickly instead of consuming the old long retry path.
  - The fallback note is available as metadata, but not surfaced in PDF/Telegram because PDF layout and unrelated Telegram UX were out of scope.

## B-AUDIT-3 Payment Double-Click Pending Invoices

- root cause
  - Payment callbacks always called order creation before creating a Telegram invoice link.
  - `PaymentService.create_order(...)` generated a fresh order ID/nonce on every call and the Postgres payment store inserted every pending order directly.
  - Successful-payment handling already rejected duplicate charges for a paid/granted order, but there was no server-side guard for duplicate active pending invoices before payment.

- fix
  - Added repository-backed pending-order idempotency to `PaymentService.create_order(...)`.
  - Added `PostgresPaymentStore.create_or_reuse_pending_order(...)`, which serializes `(chat_id, product, provider, amount, currency)` with a Postgres advisory transaction lock, reuses the first non-expired pending order, and marks expired pending orders failed before creating a new one.
  - Added a `PaymentOrder.reused_pending` marker for the creation response only; it is not persisted and does not change ledger statuses.
  - Telegram Stars and YooKassa invoice paths now stop before `create_invoice_link(...)` when the service returns a reused pending order, and send a clear existing-invoice notice instead of creating a second invoice link.
  - Amount/currency/provider validation remains tied to the order payload and is still enforced by the existing payment validation path.

- tests
  - Initial RED before fix:
    - `pytest tests/test_payments.py::test_create_order_reuses_active_pending_order_for_same_payment_key tests/test_payments.py::test_concurrent_create_order_reuses_one_active_pending_order_for_same_payment_key tests/test_payments.py::test_create_order_allows_distinct_pending_orders_for_different_products tests/test_payments.py::test_create_order_ignores_expired_or_failed_pending_order_for_same_payment_key tests/test_payments.py::test_reused_pending_order_keeps_original_amount_currency_provider_validation tests/test_telegram_app_runtime.py::test_payment_callback_double_click_reuses_pending_order_without_second_invoice -q`
    - `5 failed, 1 passed`, confirming duplicate pending orders and duplicate invoice-link creation.
  - GREEN after fix:
    - Same focused command after expanding mismatch cases to provider, amount, and currency: `8 passed in 3.49s`.
    - `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`: `54 passed`.
    - `pytest tests/test_postgres_payment_store.py -q`: `20 passed, 19 skipped`; DSN-backed cases, including new Postgres pending-order concurrency tests, skipped because `DIET_BOT_TEST_DATABASE_URL` is not configured locally.
    - `pytest tests/test_telegram_app_runtime.py -q`: `25 passed`.
    - `git diff --check`: exit code `0`; Git printed LF-to-CRLF working-copy warnings only.
  - Final DSN-backed disposable Postgres verification:
    - `pytest tests/test_postgres_payment_store.py -q` -> `42 passed in 12.30s`; no skips. This covered the durable pending-order reuse and concurrent pending-order path.
    - Focused concurrency/reversal selector in the same file: `pytest tests/test_postgres_payment_store.py -q -k "concurrent or reversal"` -> `5 passed, 37 deselected in 3.45s`.
    - `DIET_BOT_TEST_DATABASE_URL` was set only in the test process environment for the disposable local database.

- remaining risks
  - Existing active duplicate pending orders, if already present from before this fix, are not cleaned up retroactively.
  - Refund, cancel, reversal, and reconciliation semantics were not changed as part of B-AUDIT-3; they are covered separately by B-AUDIT-4/B-AUDIT-5 below.

## B-AUDIT-4 Refund/Cancel/Reversal Entitlement

- root cause
  - The payment ledger already had `refunded` and `canceled` charge statuses, but runtime payment handling only had a successful-payment path.
  - Entitlements recorded the current subscription payment order/charge, but no reversal API used that provenance to revoke or flag access after provider refund/cancel/reversal.
  - Extra one-day and weekly PDF balances are counters, not per-charge buckets. Current follow-up evidence must distinguish the implemented one-unit revocation for a matching unused extra from the still-required manual review/audit path for consumed, superseded, partial, or mismatched cases.

- fix
  - Added `PaymentService.handle_payment_reversal(...)` as the runtime service entry point for provider refund/cancel/reversal events.
  - Added `PostgresPaymentStore.record_payment_reversal(...)` to lock the existing charge/order, update `payment_charges.status`, preserve reversal details in `raw_payload_json`, and move the affected order to `failed` with a payment reversal reason.
  - Added `subscriptions.apply_payment_reversal(...)`.
  - Current active subscription charges are automatically revoked when the entitlement still points at the same payment order/charge: subscription end is set to the reversal time, monthly counters are zeroed, and managed auto-renew status becomes `canceled`.
  - Old subscription charge reversals after a later valid payment are manual review only and leave the later current entitlement intact.
  - Matching extra one-day / weekly PDF reversals now remove one usable extra unit when the reversed charge was granted and an active extra counter exists.
  - Extra one-day / weekly PDF reversals still return `manual_review_required=True` so operators can audit consumed, superseded, partial, mismatched, or no-active-counter cases.

- automatic revocation vs manual review behavior
  - Automatic: current paid subscription reversal where `current_period_payment_order_id` and current charge metadata still match the reversed charge.
  - Extra-counter revocation plus manual review: matching `extra_one_day` or `extra_weekly_pdf` reversal decrements one available extra counter, preserves independent valid extra purchases, records the reversal marker, and keeps `manual_review_required=True` with `reason="extra_entitlement_requires_manual_review"`.
  - Manual-review-only: partial refund amount/currency mismatch, old subscription charge not current, missing order, missing matching grant, unsupported product, and extra reversal with no active counter left to remove.
  - Repeated reversal events are idempotent through a persisted reversal marker in entitlement processed charge IDs and existing charge status checks.

- tests
  - Initial RED focused command produced `7 failed`: refunded/canceled/reversed provider rows still reconciled as granted, and the reversal entitlement/service API was absent.
  - Focused GREEN command: `7 passed`.
  - `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q` -> `59 passed`.
  - `pytest tests/test_postgres_payment_store.py -q` -> `20 passed, 22 skipped`; DSN-backed reversal/store tests skipped because no `DIET_BOT_TEST_DATABASE_URL` is configured locally.
  - Final DSN-backed disposable Postgres verification:
    - `pytest tests/test_postgres_payment_store.py -q` -> `42 passed in 12.30s`; no skips. This covered refund/reversal persistence for the durable payment store.
    - `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q` -> `59 passed in 0.33s`.
    - Focused concurrency/reversal selector: `pytest tests/test_postgres_payment_store.py -q -k "concurrent or reversal"` -> `5 passed, 37 deselected in 3.45s`.

- remaining risks
  - No live Telegram/YooKassa/Stars refund, cancel, chargeback, or provider action was performed.
  - Extra product reversals still require manual review until the entitlement model can track per-charge consumption, but matching unused extra reversals are no longer manual-review-only: one usable unit is removed.
  - Production provider ingress and sandbox/provider refund, cancel, reversal, and chargeback acceptance remain a separate paid-launch gate tracked by HIGH-3.

## B-AUDIT-5 Reconciliation Refunded Payment

- root cause
  - `payment_reconciliation._provider_row()` parsed provider `status`, but exact grant matching ignored that provider-side status.
  - A provider export row with `status="refunded"` and ledger `order_status="granted"` was classified as `matched_paid_granted`, hiding an active entitlement after reversal.

- fix
  - Reconciliation now only treats paid-like provider statuses as clean granted matches.
  - Provider rows with refunded, canceled/cancelled/voided, reversed, or chargeback statuses plus granted ledger rows produce explicit finding categories:
    - `provider_refunded_but_granted`
    - `provider_canceled_but_granted`
    - `provider_reversed_but_granted`
  - Unknown/non-paid provider statuses no longer become clean `matched_paid_granted` rows.

- automatic revocation vs manual review behavior
  - Reconciliation is detection/reporting only; it does not revoke entitlement.
  - After the B-AUDIT-4 reversal path runs, the affected order is no longer `granted`, so a refunded provider payment no longer reconciles as clean granted.
  - If a provider export is refunded/canceled/reversed while the local ledger still says granted, reconciliation reports a discrepancy until entitlement is revoked or manually resolved.

- tests
  - `pytest tests/test_payment_reconciliation_report.py -q` -> `12 passed`.
  - Focused RED reproduced the audit bug with refunded/canceled/reversed provider rows reporting clean matches before the fix.
  - Final DSN-backed disposable Postgres verification:
    - `pytest tests/test_payment_reconciliation_report.py -q` -> `12 passed in 0.23s`.
    - `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q` -> `59 passed in 0.33s`.

- remaining risks
  - Provider export vocabulary may need expansion after real sandbox exports are reviewed.
  - Full payment sandbox/manual acceptance remains required before paid launch.

## Final DSN-Backed Payment Verification

- Scope
  - Ran only disposable local Postgres payment verification with `DIET_BOT_TEST_DATABASE_URL` set in each test process.
  - No production database, bot process, deploy, push, commit, tag, PR, real payment, refund, cancellation, reversal, chargeback, PDF, recipe, weekly-generation, Telegram UX, archive, `New project 2 CLEAN`, or recovered-bot work was performed.
  - The disposable `foodbalance-stage20-pg` container used for this run was removed after verification.

- results
  - `pytest tests/test_postgres_payment_store.py -q` -> `42 passed in 12.30s`; no skips.
  - `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q` -> `59 passed in 0.33s`.
  - `pytest tests/test_payment_reconciliation_report.py -q` -> `12 passed in 0.23s`.
  - Extra focused Postgres concurrency/reversal selector: `pytest tests/test_postgres_payment_store.py -q -k "concurrent or reversal"` -> `5 passed, 37 deselected in 3.45s`.
  - `git diff --check` exited `0`; Git printed LF-to-CRLF working-copy warnings only.

- closure
  - B-AUDIT-3 durable duplicate pending-order concurrency is closed for the disposable-DSN local Postgres gate.
  - B-AUDIT-4 durable refund/cancel/reversal persistence is closed for the disposable-DSN local Postgres gate.
  - B-AUDIT-5 refunded/canceled/reversed reconciliation reporting is closed for the requested local verification gate.
  - Remaining launch gate is manual sandbox/provider acceptance; no live provider action was part of this run.
