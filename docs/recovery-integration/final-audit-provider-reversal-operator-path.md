# Final Audit HIGH-3 Provider Reversal Operator Path

Date: 2026-05-31

Verdict: READY FOR HIGH-3 SANDBOX ACCEPTANCE.

## Scope

This closes the local operator apply path gap for `HIGH-3: No Production
Ingress For Provider Reversal Events`.

No live provider webhook, provider API call, real payment, real refund, real
cancel, real reversal, real chargeback, Telegram API, bot process, production
database, deploy, push, commit, tag, or PR was used.

## Command

Local operator command:

```powershell
python -m scripts.ops.apply_payment_reversal `
  --provider telegram_stars `
  --telegram-payment-charge-id <verified-ledger-charge-id> `
  --kind refund `
  --event-timestamp 2026-05-31T12:00:00Z `
  --amount 450 `
  --currency XTR `
  --reason "provider event verified in provider console"
```

The command reads the Postgres DSN from `DIET_BOT_DATABASE_URL` by default.
Use `--database-url-env <ENV_NAME>` to point at a different configured DSN.
The DSN is never printed in success or error output.

Accepted identifiers:

- `--telegram-payment-charge-id`
- `--provider-payment-id` / `--provider-payment-charge-id`
- `--order-id`

Accepted event kinds:

- `refund`
- `cancel`
- `reversal`
- `chargeback`

`--order-id` is resolved with a read-only payment charge lookup, then the
actual mutation still goes through `PaymentService.handle_payment_reversal()`.

## Dry Run

Default mode is dry-run. It performs read-only charge lookup and prints a JSON
audit preview:

- target ledger charge status (`refunded` or `canceled`);
- target payment-order failure reason;
- whether entitlement reversal logic would be invoked;
- whether the event would require manual review;
- redacted order and charge identifiers.

Dry-run does not call `record_payment_reversal()` and does not mutate payment
ledger, order state, or entitlement counters.

`--dry-run` may be passed explicitly, but is not required.

## Apply

Apply mode requires `--apply`:

```powershell
python -m scripts.ops.apply_payment_reversal `
  --provider telegram_stars `
  --provider-payment-id <verified-provider-payment-id> `
  --kind refund `
  --event-timestamp 2026-05-31T12:00:00Z `
  --amount 450 `
  --currency XTR `
  --reason "provider event verified in provider console" `
  --operator "<operator-id>" `
  --apply
```

Apply mode:

- resolves the ledger charge by provider/Telegram/order identifier;
- calls `PaymentService.handle_payment_reversal()`;
- persists through the existing `PostgresPaymentStore.record_payment_reversal()`
  transaction;
- writes provider event metadata to the charge audit payload;
- prints redacted JSON status: `applied`, `manual_review`, `duplicate`,
  `not_found`, or `rejected`.

## Idempotency

Idempotency remains in the existing reversal service/store path:

- `PostgresPaymentStore.record_payment_reversal()` returns
  `duplicate_reversal` when the charge already has the target ledger reversal
  status.
- `subscriptions.apply_payment_reversal()` records a
  `reversal:<status>:<charge-id>` processed marker before mutating access.
- Replaying the same provider event does not double-revoke subscription access
  and does not double-decrement extra one-day or weekly PDF counters.

## Access Effects

Matching subscription reversal:

- marks the charge reversed locally;
- marks the payment order failed with the provider reversal reason;
- revokes current paid subscription access;
- zeroes monthly one-day and weekly PDF counters;
- cancels auto-renew status for Telegram Stars/current reversal cases.

Matching extra one-day or weekly PDF reversal:

- marks the charge reversed locally;
- marks the payment order failed;
- removes one usable extra unit when an active counter exists;
- preserves `manual_review_required=True` for audit/operator follow-up.

Partial amount, currency mismatch, old subscription charge, missing order, and
no-active-counter extra cases route to manual review without unsafe access
mutation.

## Reconciliation

`scripts.ops.payment_reconciliation_report` remains read-only. Its successful
CLI output now prints an operator note to stderr:

- reconciliation reports discrepancies only;
- after verifying a provider event, run
  `python -m scripts.ops.apply_payment_reversal --dry-run`;
- rerun with `--apply` only for the verified provider event.

## Verification

Focused coverage added:

- CLI default dry-run does not call the reversal recorder and redacts DB/charge
  identifiers.
- CLI apply routes through `PaymentService.handle_payment_reversal()` with
  normalized reversal status, event timestamp, and audit payload.
- CLI can resolve `--order-id` to a payment charge before apply.
- CLI dry-run flags mismatched amount as manual review without applying.
- CLI rejects missing identifiers.
- CLI redacts DSN/secret text on store errors.
- DSN-backed operator path tests cover subscription apply, extra one-day apply,
  extra weekly PDF apply, dry-run non-mutation, replay idempotency, and
  mismatched amount manual review without extra access mutation.
- Reconciliation CLI says the report is read-only and points to the apply
  command.

## Remaining Gap

Sandbox/provider acceptance remains pending. This stage deliberately did not
add a live provider webhook, configure provider secrets, call provider APIs, or
perform sandbox/live payments or refunds.
