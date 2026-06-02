# Final Audit HIGH-3 Provider Reversal Sandbox Acceptance Plan

Date: 2026-05-31

Verdict: READY FOR SANDBOX SMOKE WITH EXPLICIT APPROVAL.

This is a readiness plan only. No bot process, Telegram API/getUpdates,
provider API, production database, real payment, real refund, real cancel, real
reversal, chargeback, deploy, push, commit, tag, PR, secrets/env-file change, or
sales follow-up worker was used while preparing this report.

## Provenance

- Working folder:
  `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- `git status --short`: dirty before this plan. Existing tracked and untracked
  release-hardening files were already present, including payment/runtime/data
  changes and recovery docs. This stage adds only this report and a recovery
  status breadcrumb.

## Local Payment Contract To Accept In Sandbox

Current code exposes these providers:

| Provider | Runtime name | Credential shape | Notes |
| --- | --- | --- | --- |
| Telegram Stars | `telegram_stars` | Bot token only for invoice flow; no separate provider token in current runtime | Amounts are in `XTR`. |
| YooKassa/card via Telegram invoice | `yookassa` | Sandbox/test `TELEGRAM_PROVIDER_TOKEN` plus sandbox bot/token setup | Amounts are minor `RUB` units. |

Current products and prices:

| Product | Runtime name | Stars price | YooKassa price |
| --- | --- | --- | --- |
| Monthly subscription | `subscription_month` | `450 XTR` | `79900 RUB` |
| Extra one-day ration | `extra_one_day` | `29 XTR` | `5000 RUB` |
| Extra weekly PDF | `extra_weekly_pdf` | `141 XTR` | `25000 RUB` |

Operator reversal kinds accepted by the local apply command:

| Provider event kind | Command `--kind` | Local reversal status | Local charge status target |
| --- | --- | --- | --- |
| Refund | `refund` or `refunded` | `refunded` | `refunded` |
| Cancel | `cancel` or `canceled` | `canceled` | `canceled` |
| Reversal | `reversal` or `reversed` | `reversed` | `refunded` |
| Chargeback | `chargeback` | `chargeback` | `refunded` |

## Sandbox-Safe Prerequisites

All of these must be true before actual sandbox smoke starts:

1. Explicit approval exists for sandbox payment smoke, including any controlled
   bot start needed to create sandbox invoices.
2. The database target is a disposable or staging Postgres database, never
   production. Prefer a dedicated env var such as
   `DIET_BOT_SANDBOX_DATABASE_URL` for operator commands, and verify it does
   not point at the production host, database, or user.
3. Sandbox bot/provider credentials are available only through operator secret
   storage, not committed files:
   - `DIET_BOT_TOKEN` or `TELEGRAM_BOT_TOKEN` for the sandbox bot context.
   - `TELEGRAM_PROVIDER_TOKEN` for YooKassa sandbox/card invoices.
   - No separate provider token is expected by current runtime for Stars.
4. Payment flags for a future controlled sandbox bot run are explicitly set for
   the sandbox environment only:
   - `DIET_BOT_STORAGE_BACKEND=postgres`
   - `DIET_BOT_DATABASE_URL=<sandbox-or-disposable-postgres-dsn>`
   - `DIET_BOT_PAYMENTS_ENABLED=1`
   - `DIET_BOT_PUBLIC_PAYMENTS_ENABLED=1`
   - `DIET_BOT_PAYMENT_TEST_PRICES_ENABLED=0`
   - `DIET_BOT_PAYMENT_RECOVERY_SPOOL=<absolute-sandbox-spool-path>`
   - `DIET_BOT_SALES_FOLLOWUP_ENABLED=0`
   - `DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED=0`
5. Provider-side evidence can be exported or copied from sandbox only:
   provider payment id, Telegram payment charge id where available, order id,
   event kind, event timestamp, amount, currency, and provider status.
6. Local ledger exports for reconciliation come from the same sandbox database
   only. Provider exports must be local fake/synthetic/sandbox files; the
   reconciliation command never calls provider APIs.

If any prerequisite is not true, the smoke is blocked before any payment action.

## Acceptance Matrix

Run each provider/product case in sandbox only. For each successful payment,
capture the ledger order id and provider/Telegram charge identifiers before any
reversal action.

| Case | Providers | Prerequisites | Sandbox action | Command(s) | Expected result | Stop condition |
| --- | --- | --- | --- | --- | --- | --- |
| Successful subscription payment | `telegram_stars`, `yookassa` | Sandbox bot/provider credentials, sandbox DB, payments enabled only in sandbox | Complete one monthly subscription payment in sandbox | Reconciliation before reversal, see command template `R1` | Ledger has one granted `subscription_month` order and one succeeded charge with exact provider/currency/amount | Stop if price differs from `450 XTR` or `79900 RUB`, order is not granted, charge ids are missing, or any live credential/DB is detected |
| Duplicate click/idempotency | `telegram_stars`, `yookassa` | Same user/chat has an active pending order for the same provider/product/amount/currency | Press the same monthly purchase action twice before paying | Reconciliation/ledger inspection only; no apply command | Pending order is reused; no second active pending invoice/order for the same key | Stop if two active pending orders or two payable invoices are created |
| Subscription refund/cancel/reversal | `telegram_stars`, `yookassa` | Successful subscription payment exists in sandbox and provider event is visible in sandbox console/export | Trigger or record a sandbox refund/cancel/reversal/chargeback event | `R1`, then `A1` dry-run, then `A2` apply only after expected dry-run, then `R2` | Dry-run says `would_apply`; apply returns `applied` or `manual_review` only for intentional mismatch; subscription access is revoked, monthly counters are zeroed, order is failed with provider reversal reason | Stop if dry-run is `not_found`, `provider_mismatch`, unexpected `would_manual_review`, amount/currency mismatch, or provider event cannot be proven sandbox-only |
| Successful extra one-day payment | `telegram_stars`, `yookassa` | Sandbox DB has a user/chat eligible to buy an extra day | Complete one extra one-day payment in sandbox | `R1` | Ledger has granted `extra_one_day` order and one usable extra one-day unit | Stop if the charge is not exact `29 XTR` or `5000 RUB`, access is not granted, or more than one unit is granted |
| Extra one-day refund/cancel/reversal | `telegram_stars`, `yookassa` | Successful extra one-day payment exists with one unused active unit | Trigger or record sandbox provider reversal event | `R1`, `A1`, `A2`, `R2` | Dry-run says `would_apply`; apply removes one usable extra one-day unit and preserves manual review for audit follow-up where current reversal logic requires it | Stop if counter goes below zero, a consumed unit is removed silently, dry-run flags mismatch unexpectedly, or replay mutates access twice |
| Successful extra weekly PDF payment | `telegram_stars`, `yookassa` | Sandbox DB has a user/chat eligible to buy an extra weekly PDF | Complete one extra weekly PDF payment in sandbox | `R1` | Ledger has granted `extra_weekly_pdf` order and one usable extra weekly PDF unit | Stop if the charge is not exact `141 XTR` or `25000 RUB`, access is not granted, or more than one unit is granted |
| Extra weekly PDF refund/cancel/reversal | `telegram_stars`, `yookassa` | Successful extra weekly PDF payment exists with one unused active unit | Trigger or record sandbox provider reversal event | `R1`, `A1`, `A2`, `R2` | Dry-run says `would_apply`; apply removes one usable extra weekly PDF unit and preserves manual review for audit follow-up where current reversal logic requires it | Stop if counter goes below zero, a consumed unit is removed silently, dry-run flags mismatch unexpectedly, or replay mutates access twice |
| Reconciliation before apply | `telegram_stars`, `yookassa` | Provider sandbox export and local sandbox ledger export exist for the same event | Compare sandbox provider export against sandbox ledger export before local apply | `R1` | Report shows the provider reversal discrepancy that still needs local apply; the tool prints the read-only operator note | Stop if report is built from production exports, calls provider APIs, or says a reversed/refunded provider row is a clean granted match |
| Operator dry-run/apply path | `telegram_stars`, `yookassa` | Provider event identifiers, amount, currency, timestamp, and sandbox DB target are verified | Run dry-run first; run apply only after expected dry-run | `A1`; then `A2` only with explicit approval inside the sandbox smoke | Dry-run prints redacted JSON and does not mutate; apply routes through `PaymentService.handle_payment_reversal()` and returns `applied`, `manual_review`, or `duplicate` on replay | Stop if identifiers are unredacted in output, DSN is printed, status is `rejected`/`not_found`, or an apply is attempted before dry-run |
| Reconciliation after apply | `telegram_stars`, `yookassa` | Sandbox ledger export regenerated after apply | Compare provider and ledger exports after local apply | `R2` | No unresolved discrepancy remains for the applied full reversal; duplicate replay is reported as duplicate and does not change access again | Stop if the same reversal still appears as unapplied, or manual review state is not explicitly explainable |

## Command Templates

Use PowerShell line continuations exactly as shown. Replace placeholders only
with sandbox values. Do not put secrets or DSNs into shell history when an
operator secret manager can inject environment variables.

### R1: Reconciliation Before Apply

```powershell
python -m scripts.ops.payment_reconciliation_report `
  --provider-export <sandbox-provider-export.jsonl> `
  --ledger-export <sandbox-ledger-export-before.jsonl> `
  --recovery-spool <absolute-sandbox-payment-recovery-spool.jsonl> `
  --format table
```

Expected before apply: a provider refund/cancel/reversal row is visible as a
local ledger/access discrepancy that requires operator review. The command is
read-only and must not call a provider API.

### A1: Operator Dry-Run By Telegram Charge Id

Use this form when the verified sandbox event has a Telegram payment charge id:

```powershell
python -m scripts.ops.apply_payment_reversal `
  --database-url-env DIET_BOT_SANDBOX_DATABASE_URL `
  --provider <telegram_stars-or-yookassa> `
  --telegram-payment-charge-id <sandbox-telegram-payment-charge-id> `
  --kind <refund-or-cancel-or-reversal-or-chargeback> `
  --event-timestamp <provider-event-timestamp-utc> `
  --amount <full-original-amount> `
  --currency <XTR-or-RUB> `
  --reason "sandbox provider event verified in provider console/export" `
  --operator "<sandbox-operator-id>" `
  --dry-run
```

Expected clean full-reversal dry-run: `status` is `would_apply`,
`manual_review_required` is `false`, `entitlement_reversal` is `will_apply`,
and all order/charge identifiers are redacted.

### A1b: Operator Dry-Run By Provider Payment Id

Use this form when the verified sandbox event has only the provider payment id:

```powershell
python -m scripts.ops.apply_payment_reversal `
  --database-url-env DIET_BOT_SANDBOX_DATABASE_URL `
  --provider <telegram_stars-or-yookassa> `
  --provider-payment-id <sandbox-provider-payment-id> `
  --kind <refund-or-cancel-or-reversal-or-chargeback> `
  --event-timestamp <provider-event-timestamp-utc> `
  --amount <full-original-amount> `
  --currency <XTR-or-RUB> `
  --reason "sandbox provider event verified in provider console/export" `
  --operator "<sandbox-operator-id>" `
  --dry-run
```

### A1c: Operator Dry-Run By Order Id

Use this form only when the provider event was manually mapped to the local
sandbox order id and the charge lookup must resolve by order:

```powershell
python -m scripts.ops.apply_payment_reversal `
  --database-url-env DIET_BOT_SANDBOX_DATABASE_URL `
  --provider <telegram_stars-or-yookassa> `
  --order-id <sandbox-order-id> `
  --kind <refund-or-cancel-or-reversal-or-chargeback> `
  --event-timestamp <provider-event-timestamp-utc> `
  --amount <full-original-amount> `
  --currency <XTR-or-RUB> `
  --reason "sandbox provider event verified in provider console/export" `
  --operator "<sandbox-operator-id>" `
  --dry-run
```

### A2: Operator Apply

Run apply only after the matching dry-run output is reviewed and approved:

```powershell
python -m scripts.ops.apply_payment_reversal `
  --database-url-env DIET_BOT_SANDBOX_DATABASE_URL `
  --provider <telegram_stars-or-yookassa> `
  --telegram-payment-charge-id <sandbox-telegram-payment-charge-id> `
  --kind <refund-or-cancel-or-reversal-or-chargeback> `
  --event-timestamp <provider-event-timestamp-utc> `
  --amount <full-original-amount> `
  --currency <XTR-or-RUB> `
  --reason "sandbox provider event verified in provider console/export" `
  --operator "<sandbox-operator-id>" `
  --apply
```

If the event was dry-run by `--provider-payment-id` or `--order-id`, use the
same identifier in apply. Do not switch identifiers between dry-run and apply
unless the mapping has been reverified in the sandbox ledger.

Expected apply statuses:

- `applied`: local charge/order/access state changed for the verified sandbox
  event.
- `manual_review`: event was recorded but requires operator follow-up; this is
  expected for some extra-purchase reversal audit paths and for intentional
  mismatch probes.
- `duplicate`: replay was detected and did not mutate access again.
- `not_found`, `provider_mismatch`, `rejected`, or process exit `2`: stop and
  do not continue the smoke.

### R2: Reconciliation After Apply

Regenerate the sandbox ledger export after apply, then run:

```powershell
python -m scripts.ops.payment_reconciliation_report `
  --provider-export <sandbox-provider-export.jsonl> `
  --ledger-export <sandbox-ledger-export-after.jsonl> `
  --recovery-spool <absolute-sandbox-payment-recovery-spool.jsonl> `
  --format table `
  --fail-on-findings
```

Expected after apply: the specific provider event is no longer an unapplied
granted-access discrepancy. Any manual-review item must be explicitly tied to
the verified sandbox event and recorded as an acceptance note, not ignored.

## Negative/Mismatch Probes

Run these only after the happy path works in sandbox:

1. Replay the exact same provider event with `--dry-run`, then `--apply`.
   Expected: `duplicate`; no extra entitlement decrement and no second
   subscription revocation.
2. Dry-run the same event with the wrong amount. Expected:
   `would_manual_review`, reason `partial_refund_manual_review`, and no apply.
3. Dry-run the same event with the wrong currency. Expected:
   `would_manual_review`, reason `currency_mismatch`, and no apply.
4. Dry-run a valid identifier with the wrong provider. Expected:
   `provider_mismatch`, no apply.

## Forbidden Without Separate Approval

- Starting or restarting the real production bot.
- Calling Telegram `getUpdates`, polling, webhook setup, or Telegram API in the
  current planning stage.
- Using production `DIET_BOT_DATABASE_URL`, production payment recovery spool,
  production bot token, live `TELEGRAM_PROVIDER_TOKEN`, live provider console,
  live provider API, or real customer account.
- Creating real-money payments, refunds, cancels, reversals, or chargebacks.
- Applying `scripts.ops.apply_payment_reversal --apply` against any non-sandbox
  database.
- Enabling sales follow-up campaign or worker.
- Deploying, pushing, committing, tagging, opening a PR, or editing secrets/env
  files.
- Touching archive, `New project 2 CLEAN`, or recovered bot checkouts.

## Readiness Verdict

READY FOR SANDBOX SMOKE WITH EXPLICIT APPROVAL.

The local code/config contract is clear enough to run a controlled sandbox
acceptance: supported providers/products/prices are identified, the operator
command defaults to dry-run, can be pointed at a non-production DSN through
`--database-url-env`, and reconciliation remains read-only. Actual acceptance is
still pending and must be blocked if sandbox credentials, sandbox DB isolation,
or explicit approval are missing.

## Next Prompt For Actual Sandbox Smoke

Work in `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`.

Use
`docs/recovery-integration/final-audit-provider-reversal-sandbox-plan.md` as
the acceptance checklist. With explicit approval, perform sandbox-only
provider acceptance for HIGH-3:

- do not use production DB, live provider credentials, live provider API, real
  money, real refunds/cancels/reversals/chargebacks, deploy, push, commit, tag,
  PR, archive, `New project 2 CLEAN`, or recovered bot;
- first prove branch, HEAD, `git status --short`, sandbox DB DSN identity
  without printing secrets, and sandbox credential presence without printing
  secrets;
- run only sandbox provider flows for `telegram_stars` and `yookassa` where
  sandbox credentials exist;
- cover subscription, duplicate click/idempotency, extra one-day, extra weekly
  PDF, refund/cancel/reversal/chargeback where the provider sandbox supports
  them, reconciliation before/after, dry-run before apply, apply only after
  expected dry-run, and replay idempotency;
- stop immediately on any live credential/DB/provider boundary breach or
  unexpected dry-run/apply/reconciliation result;
- return changed files, exact commands run, redacted provider/ledger evidence,
  pass/fail matrix, and final HIGH-3 verdict.
