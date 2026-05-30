# Stage 20C Payment Store Blocker

## Scope

This pass handled only the Stage 20 payment-store blocker in
`tests/test_postgres_payment_store.py`. It did not continue the full Stage 20
suite.

## Reproduction

Initial focused run without `DIET_BOT_TEST_DATABASE_URL` did not exercise the
Postgres integration path:

- `pytest tests/test_postgres_payment_store.py -q`
  - `20 passed, 15 skipped`

The failure was reproduced against a disposable local Postgres schema with the
DSN kept in process environment and redacted from output:

- `pytest tests/test_postgres_payment_store.py -q`
  - before fix: `4 failed, 31 passed`

## Failing Tests

- `test_successful_payment_transaction_rolls_back_if_entitlement_grant_fails`
  - Expected: a valid subscription payment reaches the injected grant callback,
    the callback raises `RuntimeError("grant failed")`, and the whole transaction
    rolls back to pending with no charge row.
  - Actual: no exception was raised because validation rejected the payment
    first with `amount_mismatch`.
  - Cause: stale request amount `400 XTR`; current subscription order amount is
    `450 XTR`.

- `test_successful_payment_transaction_grants_entitlement_tables`
  - Expected: a valid Stars subscription payment inserts a charge, marks the
    order granted, and writes monthly entitlement counters plus processed charge
    id.
  - Actual: result was `inserted=False, reason="amount_mismatch"`.
  - Cause: stale request amount `400 XTR`; current subscription order amount is
    `450 XTR`.

- `test_successful_payment_transaction_rejects_new_charge_for_granted_order`
  - Expected: first valid charge grants the order; a second different charge for
    the already granted order is rejected as `order_not_payable`.
  - Actual: first charge was rejected as `amount_mismatch`, so the granted-order
    duplicate path was never reached.
  - Cause: stale request amount `400 XTR`; current subscription order amount is
    `450 XTR`.

- `test_successful_payment_transaction_rejects_mismatched_payment_context[currency_mismatch]`
  - Expected: valid amount with wrong currency returns `currency_mismatch` and
    grants nothing.
  - Actual: baseline amount was still `400`, so amount validation failed first
    with `amount_mismatch`.
  - Cause: stale baseline amount; the test was not isolating currency mismatch
    against the current `450 XTR` subscription price.

## Root Cause

The payment store behavior was correct. Current product price semantics in
`payments.py` are:

- Telegram Stars monthly subscription: `450 XTR`
- Telegram Stars extra one-day plan: `29 XTR`
- Telegram Stars extra weekly PDF: `141 XTR`
- YooKassa monthly subscription: `79_900 RUB`
- YooKassa extra one-day plan: `5_000 RUB`
- YooKassa extra weekly PDF: `25_000 RUB`

The failing tests mixed current order fixtures with old Stars subscription
request amounts (`400 XTR`). The store correctly rejected those requests before
recording a charge or granting entitlement.

## Changes

Only test code changed:

- `tests/test_postgres_payment_store.py`
  - `_order(...)` now derives price from `expected_payment_price(...)` instead
    of duplicating static amounts.
  - Successful payment transaction tests pass `order.amount` and
    `order.currency`.
  - The amount mismatch case uses `order.amount + 1`.
  - The currency mismatch case now starts from the current valid amount, so it
    proves the currency guard specifically.

No production payment-store, payment-service, or payment contract code was
changed in this pass.

## Verification

- `pytest tests/test_postgres_payment_store.py -q`
  - after fix with disposable local Postgres: `35 passed`
- `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
  - `47 passed`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

## Remaining Risks

- This was not a full Stage 20 rerun. Work intentionally stopped after the
  payment-store blocker.
- The local run used disposable Postgres schemas on an existing local Docker
  Postgres service; no production database or real payment provider was used.
- Existing unrelated dirty files remain outside this scope.

## Explicit Non-Work

No PDF, recipe/data, Telegram UI copy, promo store/admin, runtime/preflight
worker flags, weekly PDF tests, bot launch, deploy, push, commit, tag, PR, real
payment/refund/chargeback action, secrets/env-file edit, archive, `New project 2
CLEAN`, or recovered-bot work was done.
