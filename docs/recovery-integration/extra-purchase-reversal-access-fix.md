# Extra Purchase Reversal Access Fix

Date: 2026-05-31

## Scope

This closes only the high-risk issue from `codex-security-readonly-check.md`: refund/cancel/reversal for paid extra purchases left active extra access usable until manual review.

Not touched: selected-53 import, `src/diet_bot/data`, production curated recipes, bot runtime, Telegram API, production DB, real payments, secrets/env files, deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, recovered bot, or adjacent payment/UX/PDF/recipe issues.

## Initial Snapshot

- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- `git status --short`: checkout was already dirty before this scoped fix, including payment/subscription/test/recovery-doc changes plus selected-53/staging docs.

## Classification

This was a real production bug, not a stale security-report misunderstanding.

`apply_payment_reversal()` in `src/diet_bot/subscriptions.py` already checked that the reversed charge had been granted and recorded a reversal marker. For `extra_one_day` and `extra_weekly_pdf`, it returned `manual_review_required=True` without changing `extra_one_day_remaining` or `extra_weekly_pdf_remaining`. The durable path in `src/diet_bot/postgres_payment_store.py` then persisted the unchanged usable counter.

## Root Cause

Extra purchases are represented as aggregate counters, and the reversal path treated manual review as enough. As a result, a matching refund/cancel/reversal left the paid extra counter active, so a user could consume refunded extra access before operator review.

## Fix

- Matching granted `extra_one_day` reversal now decrements `extra_one_day_remaining` by 1 when an active extra unit exists.
- Matching granted `extra_weekly_pdf` reversal now decrements `extra_weekly_pdf_remaining` by 1 when an active extra unit exists.
- Manual review remains required for audit/operator follow-up.
- The duplicate reversal marker still prevents repeated subtraction for an identical reversal.
- Subscription reversal behavior was not weakened.
- Successful extra purchase grant behavior was not changed.

## Regression Coverage

- A focused unit regression test proves that a successful extra purchase first creates a usable counter, then `refunded`, `canceled`, or `reversed` makes that extra access unusable.
- The existing two-extra weekly PDF test now expects the matching refund to revoke exactly one extra unit while preserving independent test access.
- The Postgres regression expectation now requires repeated refund for extra weekly PDF to leave `extra_weekly_pdf_remaining == 0`, not `1`. DSN-backed execution was skipped in this session because no safe disposable `DIET_BOT_TEST_DATABASE_URL` is set.

## Verification

- RED before fix:
  - `PYTHONPATH=src python -m pytest tests/test_subscriptions.py::test_reversal_of_extra_purchase_revokes_unused_extra_access tests/test_subscriptions.py::test_refund_of_extra_purchase_revokes_one_extra_unit_without_removing_test_access -q`
  - Result: `4 failed`; failures showed extra counters stayed active.
- GREEN focused:
  - Same command.
  - Result: `4 passed in 0.09s`.
- Requested focused suite:
  - `PYTHONPATH=src python -m pytest tests/test_payments.py tests/test_subscriptions.py tests/test_payment_reconciliation_report.py -q`
  - Result: `63 passed in 0.31s`.
- Postgres boundary:
  - `DIET_BOT_TEST_DATABASE_URL=unset`; `pytest tests/test_postgres_payment_store.py -q` was not run, and no DSN-backed proof is claimed for this fix.
- `git diff --check`:
  - Exit code `0`; output contained only existing LF-to-CRLF working-copy warnings.

## Remaining Work

- Final manual smoke bot restart remains pending explicit approval.
- Payment sandbox/provider refund/cancel/reversal smoke remains a separate paid-launch gate.
- selected-53 import, new safety snapshot/commit, and deploy/VPS plan remain separate later steps.
