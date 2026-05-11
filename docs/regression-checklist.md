# Regression checklist

Use this checklist before a release candidate or any risky change touching
payments, generation, storage, or runtime behavior.

## CI gates

- [ ] `fast` passed on the PR branch.
- [ ] `integration-postgres` passed from `workflow_dispatch` or a `v*` tag.
- [ ] `slow-pdf-builder` passed for release candidates or changes touching PDF, recipes, plan generation, or builder behavior.
- [ ] `full-suite` passed for release candidates when CI capacity allows.
- [ ] Docker smoke passed for runtime packaging changes.

## Payments

- [ ] Telegram Stars subscription invoice creation still records a pending order.
- [ ] Extra day and extra weekly PDF purchases require an active subscription.
- [ ] YooKassa invoice creation preserves provider, amount, currency, receipt, and product type.
- [ ] Pre-checkout rejects expired, tampered, wrong-user, wrong-currency, and wrong-amount payloads.
- [ ] Successful payment is idempotent across repeated Telegram/provider events.
- [ ] Refund and chargeback paths revoke only the intended subscription or extra quota.
- [ ] Admin reconciliation applies orphan success/refund events once and rejects user-id mismatches.
- [ ] Logs and support/admin messages do not expose provider charge IDs or raw payment payloads.

## Generations

- [ ] Free users receive only the intended lifetime trial generation.
- [ ] Active subscribers can consume monthly one-day and weekly PDF quotas.
- [ ] Extra quotas are consumed after monthly quotas and are not usable without active access.
- [ ] Failed one-day generation refunds the consumed attempt.
- [ ] Failed weekly PDF generation either refunds before delivery or completes with text fallback after successful delivery.
- [ ] Double-click and concurrent generation attempts keep one active lock per user.
- [ ] Stale generation cleanup refunds abandoned locks once and does not refund completed deliveries.
- [ ] Recent recipe ID/family avoidance still changes repeated plans.
- [ ] Invalid generated plans are not delivered and do not consume quota.

## Runtime and storage

- [ ] Production startup requires `DIET_BOT_DATABASE_URL`, support chat ID, and public privacy URL.
- [ ] Development JSON storage fallback remains opt-in only.
- [ ] PostgreSQL migrations initialize idempotently.
- [ ] JSON-to-PostgreSQL migration dry run does not write state.
- [ ] JSON-to-PostgreSQL apply is one-shot per migration ID and skips existing live rows.
- [ ] Healthcheck strict mode validates package assets, runtime config, and PostgreSQL connectivity.
- [ ] Polling startup handles webhook cleanup and stale generation cleanup without blocking startup.
- [ ] Support group commands are ignored unless explicitly allowed by private/admin guards.

## Workspace hygiene

- [ ] Ignored local artifacts (`.venv`, `.pytest_cache`, `.diet_bot_state`, `tmp`, `output`, `outputs`, `exports`, logs, dumps, backups) are not included in logic PRs.
- [ ] Artifact cleanup is done in a separate hygiene PR with no bot logic, test marker, or CI behavior changes.
