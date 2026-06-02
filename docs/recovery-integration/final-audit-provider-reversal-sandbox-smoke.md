# Final Audit HIGH-3 Provider Reversal Sandbox Smoke

Date: 2026-05-31

Verdict: BLOCKED.

The sandbox/staging acceptance smoke was stopped at hard preflight. No
production database, live provider credential, provider API, real payment, real
refund, real cancel, real reversal, real chargeback, bot process, deploy, push,
commit, tag, PR, archive, `New project 2 CLEAN`, recovered bot, or sales
follow-up worker/campaign action was used.

## Scope

Checklist source:
`docs/recovery-integration/final-audit-provider-reversal-sandbox-plan.md`.

Allowed target database env var:
`DIET_BOT_SANDBOX_DATABASE_URL`.

Allowed provider/operator scripts:

- `scripts/ops/apply_payment_reversal.py`
- `scripts/ops/payment_reconciliation_report.py`

## Hard Preflight Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Working folder | PASS | `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release` |
| Branch | PASS | `codex/recover-product-ui-on-hardened-master` |
| HEAD | PASS | `13d085c5a0459d1fd449a823cec19cb16b6f5e77` |
| Git status | PASS with existing dirty tree | Branch is ahead of `origin/master` by 1 and had existing tracked/untracked release-hardening changes before this smoke report. No commit/push/PR was performed. |
| Sandbox DB env | FAIL | `DIET_BOT_SANDBOX_DATABASE_URL` is absent. No DSN was printed. No database connection was attempted. |
| Generic runtime DB env | PASS | `DIET_BOT_DATABASE_URL` is absent in the checked shell context. |
| Sandbox DB identity | BLOCKED | Cannot verify sandbox database identity without `DIET_BOT_SANDBOX_DATABASE_URL`. |
| Sandbox bot credential | BLOCKED | `DIET_BOT_TOKEN` is present, but it is a generic variable and does not prove sandbox identity. Per hard preflight, ambiguous credential context stops the smoke. Value was not printed. |
| Telegram sandbox bot token aliases | SKIPPED | `TELEGRAM_BOT_TOKEN`, `DIET_BOT_SANDBOX_TOKEN`, and `TELEGRAM_SANDBOX_BOT_TOKEN` are absent in the checked shell context. |
| YooKassa sandbox provider credential | SKIPPED | `TELEGRAM_PROVIDER_TOKEN` and `DIET_BOT_SANDBOX_PROVIDER_TOKEN` are absent in the checked shell context. |
| Sales follow-up enablement | PASS | Sales follow-up env flags were absent, and no campaign/worker enablement was performed. |

## Providers Tested Or Skipped

| Provider | Status | Why |
| --- | --- | --- |
| `telegram_stars` | BLOCKED | Required sandbox DB env is missing. Bot credential context is ambiguous because only generic `DIET_BOT_TOKEN` is present. No Stars sandbox/test payment was attempted. |
| `yookassa` | SKIPPED/BLOCKED | Required sandbox DB env is missing, and sandbox/test provider token is absent. No YooKassa sandbox invoice, refund, cancel, reversal, or chargeback was attempted. |

## Smoke Matrix

| Case | `telegram_stars` | `yookassa` |
| --- | --- | --- |
| Successful subscription payment | NOT RUN: hard preflight blocked | NOT RUN: hard preflight blocked |
| Duplicate click/idempotency | NOT RUN: hard preflight blocked | NOT RUN: hard preflight blocked |
| Subscription refund/cancel/reversal/chargeback event | NOT RUN: hard preflight blocked | NOT RUN: hard preflight blocked |
| Successful `extra_one_day` payment | NOT RUN: hard preflight blocked | NOT RUN: hard preflight blocked |
| `extra_one_day` reversal | NOT RUN: hard preflight blocked | NOT RUN: hard preflight blocked |
| Successful `extra_weekly_pdf` payment | NOT RUN: hard preflight blocked | NOT RUN: hard preflight blocked |
| `extra_weekly_pdf` reversal | NOT RUN: hard preflight blocked | NOT RUN: hard preflight blocked |
| Reconciliation before/after | NOT RUN: no sandbox provider/ledger exports and no sandbox DB | NOT RUN: no sandbox provider/ledger exports and no sandbox DB |
| Operator dry-run | NOT RUN: no verified sandbox provider event and no sandbox DB | NOT RUN: no verified sandbox provider event and no sandbox DB |
| Operator apply | NOT RUN: dry-run/evidence gate not satisfied | NOT RUN: dry-run/evidence gate not satisfied |
| Operator replay/idempotency | NOT RUN: no apply event exists | NOT RUN: no apply event exists |

## Redacted Evidence

- No DSN, bot token, provider token, provider payment id, Telegram payment
  charge id, order id, chat id, customer id, or provider console data was
  printed.
- No sandbox database identity proof exists because the required
  `DIET_BOT_SANDBOX_DATABASE_URL` variable is absent.
- The only detected bot credential was a generic `DIET_BOT_TOKEN`; the value was
  not printed and was treated as ambiguous instead of sandbox-safe.

## Commands Run

```powershell
git branch --show-current
git rev-parse HEAD
git status --short --branch
```

```powershell
# Environment preflight; values were inspected only for presence/sandbox/live
# markers and were never printed.
$names = @(
  'DIET_BOT_SANDBOX_DATABASE_URL',
  'DIET_BOT_DATABASE_URL',
  'DIET_BOT_TOKEN',
  'TELEGRAM_BOT_TOKEN',
  'DIET_BOT_SANDBOX_TOKEN',
  'TELEGRAM_SANDBOX_BOT_TOKEN',
  'TELEGRAM_PROVIDER_TOKEN',
  'DIET_BOT_SANDBOX_PROVIDER_TOKEN',
  'DIET_BOT_PAYMENTS_ENABLED',
  'DIET_BOT_PUBLIC_PAYMENTS_ENABLED',
  'DIET_BOT_SALES_FOLLOWUP_ENABLED',
  'DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED'
)
foreach ($name in $names) {
  # Read env from Process/User/Machine scopes; print name, present/absent, and
  # sandbox/live/ambiguous classification only. Do not print values.
}
```

Commands intentionally not run because the hard preflight failed:

```powershell
python -m scripts.ops.payment_reconciliation_report ...
python -m scripts.ops.apply_payment_reversal --database-url-env DIET_BOT_SANDBOX_DATABASE_URL ... --dry-run
python -m scripts.ops.apply_payment_reversal --database-url-env DIET_BOT_SANDBOX_DATABASE_URL ... --apply
```

## Final HIGH-3 Verdict

BLOCKED.

HIGH-3 cannot be closed or partially accepted from this run because no required
launch-provider sandbox flow completed. The acceptance smoke must be rerun only
after a clearly sandbox/staging `DIET_BOT_SANDBOX_DATABASE_URL` is available and
provider credentials are either clearly sandbox/test or explicitly skipped per
provider.

## What Was Not Done

- No production DB, live provider credentials/API, real money, real refund,
  real cancel, real reversal, real chargeback, bot run, Telegram polling,
  webhook setup, deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`,
  recovered bot, or sales follow-up campaign/worker enablement.
- No sandbox provider payment was created.
- No reconciliation before/after report was run.
- No operator dry-run, apply, or replay was run.
- No code, tests, payment logic, data files, env files, scripts, or provider
  credentials were changed.
