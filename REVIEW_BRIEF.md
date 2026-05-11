# Claude Code Review Brief

Use this file as the starting prompt/context when asking Claude Code to review
this repository.

## Project

This is a Python 3.11+ Telegram nutrition bot MVP.

Main runtime:

- Package: `src/diet_bot`
- Entry point: `diet-bot-telegram = diet_bot.telegram_app:main`
- Telegram framework: `aiogram`
- Runtime mode: polling bot, not webhook/FastAPI/nginx
- Storage: PostgreSQL in production, local JSON fallback only when explicitly enabled
- PDF generation: ReportLab weekly ration PDF
- Payments: Telegram Payments/YooKassa-style provider token through Telegram invoices
- Analytics: optional local PostgreSQL archive and optional PostHog forwarding

The bot handles:

- Questionnaire/profile collection
- BMI/BMR/TDEE, calories, macros, micronutrient targets
- Allergy/restriction/disease caution filters
- One-day and weekly meal planning from curated recipe data
- Telegram payments, subscriptions, promo codes, test access, refunds/reversals
- Support requests and privacy-policy/payment preflight buttons
- PDF delivery for weekly rations

## Review Mode

First pass must be read-only.

Do not modify files yet. Do not refactor. Do not format unrelated files. Do not
delete generated data. Do not run destructive git commands.

Assume existing uncommitted changes are intentional. Do not revert user/Codex
changes unless explicitly asked.

Do not inspect or print `.env`. Use `.env.example` for configuration context.
Never expose tokens, provider credentials, database URLs, chat ids, payment
charge ids, raw payment payloads, or private support messages in review output.

## Commands

Useful setup/check commands:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[dev]
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m diet_bot.healthcheck --package-data-only
```

If the virtual environment is not available, use:

```powershell
python -m pip install -e .[dev]
python -m pytest
python -m diet_bot.healthcheck --package-data-only
```

Docker/production checks, only if the user explicitly wants container smoke:

```powershell
docker compose config
docker compose up -d --build
docker compose exec bot python -m diet_bot.healthcheck --strict
docker compose --profile smoke run --rm bot-smoke
```

Strict healthcheck needs real production-like env values and PostgreSQL.
`--telegram` calls the Telegram API and should not be used in an automated
review without explicit approval.

## Important Files

- `src/diet_bot/telegram_app.py`: Telegram handlers, callbacks, payments,
  support flow, generation locks, delivery helpers.
- `src/diet_bot/payments.py`: payment orders, payload encoding/decoding,
  payment event recording and idempotency helpers.
- `src/diet_bot/subscriptions.py`: entitlements, limits, consumption, refunds,
  reversals, test access.
- `src/diet_bot/postgres_store.py`: schema bootstrap and transactional store
  methods for users, entitlements, payments, promo codes, meal plans, analytics.
- `src/diet_bot/json_storage.py`: local JSON storage lock for development mode.
- `src/diet_bot/runtime_config.py`: production env validation.
- `src/diet_bot/healthcheck.py`: local/package/strict/Telegram readiness checks.
- `src/diet_bot/questionnaire.py`: questionnaire flow and input normalization.
- `src/diet_bot/profile_normalization.py`: stored free-text normalization.
- `src/diet_bot/safety.py`: restriction/allergy/disease filtering.
- `src/diet_bot/builder.py`: deterministic meal-plan construction.
- `src/diet_bot/validation.py`: plan validation.
- `src/diet_bot/pdf_renderer.py`: weekly PDF rendering.
- `src/diet_bot/analytics.py`: analytics sanitization/storage/PostHog sending.
- `scripts/migrate_json_to_postgres.py`: JSON-to-PostgreSQL migration.
- `tests/`: pytest suite, including smoke/security/storage/payment/PDF tests.
- `.env.example`: safe env reference.
- `Dockerfile`, `docker-compose.yml`: deployment path.
- `codex_audit_notes.md`: prior audit notes and already-fixed issues.

## High-Value Review Targets

Prioritize concrete release risks:

- Telegram callback ownership: user A must not be able to act on user B's
  inline buttons, invoices, generation jobs, support state, or trial flows.
- Payment security: forged payloads, replayed successful payments, duplicate
  updates, expired orders, wrong user/order/product/amount/currency/provider,
  refund/chargeback/cancel-subscription behavior, orphan payment handling.
- Entitlement accounting: one-day/weekly PDF quotas, free trial, subscription
  renewal, test access, promo codes, idempotency, refunding failed generations.
- PostgreSQL concurrency: row locks, unique indexes, active generation races,
  duplicate payment charge races, migration completeness, sync DB calls inside
  async handlers.
- JSON fallback: local-dev opt-in only, file-lock correctness, corrupt partial
  writes, parity with PostgreSQL where relevant.
- Secrets/privacy: raw payment payloads, support messages, analytics properties,
  logs, exception text, healthcheck output, `.env` safety.
- Input validation: questionnaire numeric bounds, free-text normalization,
  allergy/intolerance food exclusions, unsupported disease text, invalid stored
  profiles.
- PDF delivery: file cleanup on exceptions, Telegram size limits, long-token
  wrapping, image/package-data availability, stable rendering.
- Production readiness: bot must reject unsafe production config, require
  support/privacy before payments, and avoid accidental JSON storage in prod.
- Tests: missing regression tests for any real bug found.

Known remaining concerns from the previous Codex audit that deserve an
independent second look:

- Expired pending order after approved `pre_checkout` but before
  `successful_payment` needs a product decision.
- Synchronous psycopg calls may block the async event loop under DB latency or
  locks.
- Legacy monthly payment payloads may still be accepted until the configured
  deadline.
- One-day PDF flow is absent if it becomes a release requirement.
- Explicit Telegram PDF size guard and PDF long-token wrapping may still need
  improvement.

## Desired Read-Only Output

Return findings first, ordered by severity.

Use this format for every finding:

```text
P0/P1/P2/P3 - Short title
File/line:
What can go wrong:
Why it matters:
How to reproduce or reason about it:
Minimal fix:
Regression test:
```

Severity guide:

- P0: exploitable security issue, payment/access bypass, data loss, or bot
  cannot safely run.
- P1: serious production bug affecting payments, subscriptions, privacy,
  persistent data, or a major user journey.
- P2: real bug with narrower blast radius or important missing guard/test.
- P3: maintainability issue only when tied to concrete risk.

Avoid broad style comments. Avoid speculative rewrites. Do not recommend a new
framework, database, queue, or architecture unless it directly addresses a
specific P0/P1 risk.

## Follow-Up Fix Prompt

After the user chooses findings to fix, use this second prompt:

```text
Fix only the selected findings from your review.

Keep changes minimal and consistent with the existing code style.
Do not refactor unrelated code.
Do not touch `.env`.
Do not revert uncommitted changes you did not make.
Add or update focused regression tests.
Run the smallest relevant tests first, then the full test suite if feasible.

At the end, report:
- files changed
- tests run and results
- any remaining risk or manual production check
```

