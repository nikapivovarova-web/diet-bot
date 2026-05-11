# Codex audit notes

Temporary working file for the Telegram diet bot pre-release QA/security audit.

## Initial structure

- Runtime package: `src/diet_bot`
- Main Telegram entry point: `src/diet_bot/telegram_app.py`
- Storage: `src/diet_bot/postgres_store.py`, JSON fallback helpers in `telegram_app.py`, `subscriptions.py`, `payments.py`, `promo_codes.py`
- Payments/subscriptions: `src/diet_bot/telegram_app.py`, `src/diet_bot/payments.py`, `src/diet_bot/subscriptions.py`
- PDF: `src/diet_bot/pdf_renderer.py`, delivery helpers in `telegram_app.py`
- Diet/profile: `src/diet_bot/questionnaire.py`, `profile_normalization.py`, `builder.py`, `calculator.py`, `safety.py`, `validation.py`
- Deploy/config: `pyproject.toml`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `src/diet_bot/healthcheck.py`
- Tests: `tests/`
- Repo instructions: no `AGENTS.md` found.

## Initial risk map

- Telegram polling/webhook cleanup appears present: `_prepare_polling_webhook_state()` checks webhook and deletes it before polling.
- Private chat guard exists on commands, callbacks, successful payments, and text handler; group behavior still needs path review.
- Callback answer payloads include session id and question key, not only index; stale handling still needs review.
- Payment flow has pending orders and `processed_payment_charges`; needs idempotency and mismatch review.
- PostgreSQL store has schema bootstrap and transactional methods; needs row lock/concurrency review.
- JSON fallback still exists for local development; needs read/write failure behavior review.
- PDF path uses temp output and deletes generated file after reading; needs exception cleanup and Telegram size behavior review.
- Free-text normalization module exists; needs end-to-end questionnaire/profile persistence review.
- Docker Compose already uses env-required Postgres password, healthcheck, and service_healthy dependency.

## Subagent results

Completed:

- Telegram flow: no critical; medium support-chat group guard noise and stale trial callbacks for paid users; low unknown callbacks and hidden `/myid`.
- Payments/subscriptions: no critical; medium duplicate successful_payment on paid order treated as orphan, expired-order race after pre_checkout, no monetary refund/chargeback flow.
- Storage/concurrency: critical migration did not import `payment_orders.json` or JSON processed charge ids; medium sync PostgreSQL calls in async handlers, JSON file fallback corruption behavior, stale generation timeout without heartbeat, weak DB CHECK constraints.
- Security/privacy: no critical; medium raw payment payload persisted too much data, support message included charge ids, production DB not enforced by runtime, legacy payloads active until 2026-05-17.
- PDF: no critical; medium no one-day PDF flow if required, no explicit Telegram document size check, long unbroken words can overflow PDF.
- Input/diet logic: critical arbitrary `INTOLERANCE` did not exclude named foods; medium stale profile numeric bounds, validation errors not blocking send.
- Deploy/config: no critical found locally; Compose has required env, Postgres healthcheck, bot depends_on service_healthy, local healthcheck avoids Telegram API.
- Tests/static: initial full pytest passed 219/6 skipped. After fixes, full pytest passed 227/6 skipped. No ruff/black/mypy/pyright config found.

## Fixed in this run

- `safety.py`: `RestrictionType.INTOLERANCE` now contributes to hard food-name exclusions.
- `questionnaire.py`: age and meal count must be integer values.
- `telegram_app.py`: invalid stored profile measurements are rejected; support-chat group messages clear pending support/promo state without private guard reply; stale trial questionnaire start is downgraded for active paid users; successful duplicate payment for an already paid order is idempotent; raw payment payload is allowlisted; support admin message no longer includes processed charge ids.
- `postgres_store.py`: duplicate processed charge is checked before invalid paid-order classification; added import helper for migrated processed charges.
- `scripts/migrate_json_to_postgres.py`: migrates `payment_orders.json` and imports JSON entitlement processed charge ids into `processed_payment_charges`.
- Tests added/updated for the above paths.

## Remaining important risks

- Refund/chargeback/cancel-subscription flow is implemented for JSON and PostgreSQL paths: refund/chargeback reverse related access, cancel stops subscription access, and unknown/orphan events do not grant access.
- Expired pending order after approved pre_checkout but before successful_payment needs a product decision.
- Synchronous psycopg calls can block the async event loop under DB latency/locks.
- JSON fallback is now explicit local-dev opt-in via `DIET_BOT_ALLOW_JSON_STORAGE=1` and guarded by a process/file lock around runtime read-modify-write paths. PostgreSQL remains the only production-safe transactional path.
- Legacy monthly payloads remain accepted until configured deadline.
- One-day PDF is absent if it is a release requirement.
- Explicit Telegram PDF size guard and PDF long-token wrapping are still improvements.
