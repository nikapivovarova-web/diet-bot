# Stage 19.4 Env Example / Deploy Config Hygiene

## Scope

Stage 19.4 adds the committed production environment template and aligns the
production runbook with the current runtime configuration requirements.

This stage is documentation and deploy-config hygiene only. It does not change
runtime behavior, Telegram UX, payment or promo logic, PDF rendering, recipe
data, sales follow-up logic, bot startup, deploy execution, git state, archives,
`New project 2 CLEAN`, or recovered-bot files.

## Env Template

`.env.example` now has safe placeholders and grouped operator sections:

- Telegram
- Storage/Postgres
- Workers/Queues
- Payments
- Promo/Admin
- Privacy/Support
- Monitoring/Ops
- Local/dev only

Production defaults in the template include:

- `DIET_BOT_ENV=production`
- `DIET_BOT_STORAGE_BACKEND=postgres`
- `DIET_BOT_ALLOW_JSON_STORAGE=0`
- `DIET_BOT_ONE_DAY_WORKER_ENABLED=1`
- `DIET_BOT_WEEKLY_PDF_WORKER_ENABLED=1`
- empty secret placeholders for `DIET_BOT_TOKEN`,
  `TELEGRAM_BOT_TOKEN`, `DIET_BOT_DATABASE_URL`,
  `TELEGRAM_PROVIDER_TOKEN`, support/privacy/admin values, backup DSNs, and
  payment recovery spool path.

Payment notes document that YooKassa/card invoices use
`TELEGRAM_PROVIDER_TOKEN` when payments are enabled, while Telegram Stars has
no separate provider-token environment variable in the current runtime.

Promo notes document that production promo activation/admin actions require the
Postgres promo store whenever `DIET_BOT_STORAGE_BACKEND=postgres`, and that
JSON promo state is only an import seed/local fallback.

## Runbook

`docs/production-runbook.md` now points operators to `.env.example` as the
committed checklist, warns that real values belong only in the deployment secret
manager/operator environment, includes the JSON-storage guard line, and expands
payment notes for public payment UI, test prices, YooKassa/card provider token,
Telegram Stars, and the payment recovery spool.

## Test Coverage

`tests/test_production_deploy_files.py` covers:

- `.env.example` exists;
- required production variables are documented;
- storage and worker flags have production-safe template values;
- expected operator sections exist;
- Postgres promo store and JSON promo fallback notes are present;
- assignment values do not look like real Telegram tokens, Postgres DSNs with
  credentials, or provider tokens.

## Verification

RED before `.env.example` existed:

- `pytest tests/test_production_deploy_files.py -q`
  - `5 failed`
  - failures confirmed `.env.example` was missing.

GREEN after template and deploy-file test:

- `pytest tests/test_production_deploy_files.py -q`
  - `5 passed`
- `pytest tests/test_runtime_config.py tests/test_healthcheck.py -q`
  - `50 passed`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

## Guardrails

- Bot was not launched.
- No deploy, push, commit, tag, or PR was done.
- No secrets or real env files were created or edited.
- No runtime behavior, Telegram UX, payment/promo logic, PDF, recipe data, or
  sales follow-up code was changed.
