# Production Release Gap Audit

Дата: 2026-05-12

Scope: read-only audit clean-ветки `codex/emergency-stabilization` против старой папки `C:\Users\adck8\Documents\New project 2`. Код не менялся; этот файл - единственный создаваемый артефакт аудита.

## Executive Summary

Clean-проект сейчас не является production-ready платным продуктом. Это намеренно стабилизированная MVP/runtime-точка: локальный Telegram polling, JSON state, базовые подписки/лимиты, недельный PDF без текстового fallback и guard, который запрещает `DIET_BOT_ENV=production`.

Чтобы clean-ветка стала финальным платным production-продуктом, нужно восстановить production-слой по отдельным slices: durable PostgreSQL storage, строгий запрет JSON fallback в production, платежный orders/events ledger, точную обработку refunds/chargebacks/cancel, generation locks, Docker/health/liveness, backup/restore/runbook, CI lanes и manual release smoke.

Старую папку можно использовать как источник идей, тестов и отдельных модулей, но ее нельзя копировать целиком: в ней смешаны Postgres, payments, PDF, runtime hardening, CI, deploy и data changes, а `docs/AI_HANDOFF.md` уже фиксирует опасные зоны: неполный payment ledger migration, отсутствие DB statement/lock timeout, blocking JSON lock, риски refund/chargeback и отсутствие глобального generation semaphore/deadline.

## Current Clean State

- `README.md` прямо говорит, что durable Postgres storage не входит в clean runtime phase и production mode запрещен.
- `src/diet_bot/runtime_config.py` отклоняет `DIET_BOT_ENV=production`.
- `src/diet_bot/telegram_app.py` хранит chat history/profile в JSON через `_load_state()` / `_save_state()`.
- `src/diet_bot/subscriptions.py` хранит entitlements, processed charge ids и limits в JSON без durable transaction/locking guarantees.
- `src/diet_bot/telegram_app.py` создает Telegram Stars/YooKassa invoice links со статическими payload values, но без pending order nonce ledger.
- `src/diet_bot/telegram_app.py` применяет `successful_payment` напрямую к entitlement по `message.chat.id`.
- Refund/chargeback/cancel payment events в clean runtime отсутствуют.
- Weekly PDF delivery уже делает важный safety шаг: PDF отправляется документом, есть size guard, при ошибке PDF не отправляется текстовый weekly-menu fallback.
- Dockerfile, docker-compose, `.dockerignore`, `.github/workflows/*`, Postgres scripts и production runbook в clean отсутствуют.

## P0 Blockers For Paid Launch

1. Durable storage отсутствует.
   Production не может хранить платные entitlements, payment state, profiles, histories, promo redemptions и generation state в local JSON. Нужны PostgreSQL schema/migrations, store interface, atomic transactions и startup guard, который разрешает production только с DB.

2. JSON fallback не должен быть production path.
   Clean сейчас безопасно блокирует production полностью. Следующий production slice должен не ослабить это до молчаливого JSON fallback. JSON допустим только для local/dev с явным opt-in и lock timeout.

3. Нет payment orders/events ledger.
   Static invoice payload + direct successful_payment application недостаточны для платного запуска. Нужны pending payment orders с nonce, user_id, delivery_chat_id, provider, product, amount, currency, expiration, invoice_link, status и immutable event ledger.

4. Successful payment недостаточно защищен.
   Clean pre-checkout проверяет только payload/currency/amount. Финальный продукт должен reject-ить tampered/wrong-user/wrong-chat/wrong-provider/wrong-product/wrong-amount/expired orders, но принимать approved-before-expiry successful_payment идемпотентно.

5. Refund/chargeback/cancel behavior отсутствует.
   Нужны обработчики и/или admin reconciliation для refund, chargeback и cancel_subscription. Reversal должен быть привязан к точному original charge/product/period, чтобы refund старой подписки не сносил новую активную подписку, а refund extra не трогал unrelated subscription.

6. Extra purchases можно применить без active subscription на successful_payment path.
   UI пытается не продавать extras без активной подписки, но clean `apply_extra_*_payment()` сам не проверяет active access. В production это должно быть enforced в ledger/store transaction, не только в кнопках.

7. Нет atomic generation locks.
   Paid quota consumption/refund сейчас JSON-based. Concurrent callbacks/retries can double-consume or race. Нужен one-active-generation-per-user lock, lifecycle statuses (`generating`, `delivering`, `completed`, `failed`, `failed_timeout`), heartbeat, stale cleanup и refund-on-failure exactly once.

8. Production deploy path отсутствует.
   Нет Dockerfile/Compose, no non-root image, no package-data build verification, no strict healthcheck, no polling heartbeat liveness, no graceful shutdown contract.

9. Backup/restore/runbook отсутствуют в clean.
   Платный запуск без регулярного Postgres backup, restore drill, migration rollback notes и incident runbook небезопасен.

10. CI lanes отсутствуют.
    Нужны fast PR gate, slow_pdf_builder lane, postgres_integration lane, docker-smoke lane и release/full gate. Сейчас clean имеет только pytest marker `slow_pdf_builder`; `.github` отсутствует.

11. Security/privacy gaps для платежей.
    Clean support admin message включает последние `processed_payment_charge_ids`; нет production-required privacy policy URL, pre-payment privacy/support guardrail, raw payment redaction policy и secret placeholder validation. YooKassa email collection требует privacy disclosure before payment.

12. Manual Telegram/payment release smoke не покрывает production.
    Current clean smoke checklist local/dev oriented. Для paid launch нужен smoke на staging/prod-like bot: Stars, YooKassa test provider, PDF delivery, refund/reconciliation, support, privacy, liveness, backup/restore evidence.

## P1 Blockers Before Public Sale

1. Production support/privacy UX.
   Добавить `/privacy`, privacy policy URL/button before payment, support command/callback, support metadata without charge ids/raw payloads, production config requiring support chat and public HTTPS privacy URL.

2. Telegram callback ownership hardening.
   Clean уже reject-ит group/foreign callbacks in basic cases, но public sale требует session/question-key callback payloads, stale callback rejection, callback throttle and owner attribution based on clicking user rather than bot-authored message.

3. Runtime latency/deadline hardening.
   Weekly PDF offloaded to thread, но нужны bounded deadlines, global generation concurrency cap, capped Telegram retry-after, clear user-facing failure, and no event-loop blocking in heavy one-day generation.

4. PDF quality release gate.
   Нужны финальные sample PDFs across representative profiles, visual/readability QA, file-size budget, local photo/package-data verification, text extraction sanity, Cyrillic rendering check and no temporary file leaks.

5. Production observability.
   Structured logs without secrets, payment/generation/audit events, health/liveness alerting, backup alerts, failed payment/admin reconciliation alerts.

6. Migration safety.
   JSON-to-Postgres migration must include all live state, including payment orders/events/processed charges, or block release if old JSON lacks recoverable ledger data.

7. Operations documentation.
   Runbook should cover deploy, rollback, healthcheck interpretation, Telegram webhook/polling issues, payment incidents, refunds/chargebacks, stale generation cleanup, backup restore and support escalation.

8. Dependency/package hardening.
   Lock production dependencies, include package-data explicitly, run `pip check`, keep image context allow-listed, ensure data/photos/assets are present after install.

## P2 Improvements After Stable Launch

1. Admin dashboard or command improvements for payment event reconciliation, refunds and user support diagnostics.
2. Analytics warehouse/PostHog integration with strict PII filtering and stable pseudonymous IDs.
3. Automated scheduled restore drills in staging.
4. PDF visual redesign/branding, QR/logo polish and richer printable layout after reliability is proven.
5. Load/performance profiling for high-volume PDF generation and recipe selection.
6. Feature flags for gradual rollout of new payment providers or subscription plans.
7. Better user self-service: subscription status, invoice history, support ticket references.

## Gap Matrix By Direction

### 1. PostgreSQL Durable Storage

Clean gap:
- No `psycopg` dependency, no Postgres store, no migrations, no storage interface.
- JSON files are used for history/profile/subscription/promo state.
- Production startup is blocked rather than supported.

Needed:
- Postgres-backed store for users, profiles, chat history, entitlements, promo redemptions, payment orders, payment events, processed charges, generation/meal-plan lifecycle and optional analytics.
- Idempotent migrations with constraints and indexes.
- `connect_timeout`, `statement_timeout`, `lock_timeout`, transaction boundaries and row-level locking around paid quotas.
- Integration tests with skip-safe default and release-blocking `--require-postgres` mode.

Old source:
- `src/diet_bot/postgres_migrations.py`
- `src/diet_bot/postgres_store.py`
- `tests/test_postgres_store.py`
- `tests/test_json_to_postgres_migration.py`

Risk:
- Do not copy old `postgres_store.py` wholesale. It is large and old handoff notes flag missing statement/lock timeout and mixed payment/runtime behavior.

### 2. JSON Fallback Ban In Production

Clean gap:
- Production is blocked, but local JSON is always the clean runtime storage path.
- JSON writes are not a production-safe fallback.

Needed:
- `DIET_BOT_ALLOW_JSON_STORAGE=1` only for local/dev.
- Production requires `DIET_BOT_DATABASE_URL` and rejects JSON path variables as the primary store.
- Healthcheck strict mode verifies production env, DB and support/privacy requirements.
- JSON lock timeout for dev fallback if retained.

Old source:
- `src/diet_bot/runtime_config.py`
- `src/diet_bot/healthcheck.py`
- `src/diet_bot/json_storage.py` as a reference only.

Risk:
- Old `json_storage.py` uses blocking locks without timeout; adapt, do not copy as-is.

### 3. Payment Orders/Events Ledger

Clean gap:
- No `src/diet_bot/payments.py`.
- Invoice payloads are static product strings.
- No durable order status, no invoice reuse record, no event ledger.
- Duplicate guard is only a capped list on `Entitlement`.

Needed:
- Payment order lifecycle: pending, paid, expired, failed_invoice_creation.
- Unique order nonce and payload encoding.
- Payment events: successful_payment, refund, chargeback, cancel_subscription, unknown/orphan/pending_reconciliation.
- Idempotency by provider + charge_id + event_type.
- Raw payload redaction and safe metadata.
- Admin reconciliation for orphan successful_payment and early refund/chargeback events.

Old source:
- `src/diet_bot/payments.py`
- Payment-related tests in `tests/test_payments_smoke.py`
- Payment specs under `docs/superpowers/specs/2026-05-09-yookassa-telegram-payments-design.md`

Risk:
- Old payments are broad and intertwined with old `telegram_app.py`. Extract model/tests first, then wire narrowly.

### 4. Subscriptions, Limits, Extra Purchases

Clean gap:
- Basic subscription model exists, but state is JSON and payment application is not transactionally tied to orders/events.
- Extras require active subscription in UI but not in the successful payment application function.
- Monthly renewal and recurring payments need provider-aware behavior.

Needed:
- Entitlement updates only through durable ledger/store transactions.
- Monthly quota reset rules pinned by tests.
- Extras usable only with active paid access unless explicitly product-approved otherwise.
- Test access and promo grants separated from paid ledger but auditable.
- Race-safe consume/refund for one-day and weekly PDF attempts.

Old source:
- `src/diet_bot/subscriptions.py`
- `tests/test_subscriptions.py`
- Relevant payment tests from `tests/test_payments_smoke.py`

Risk:
- Do not let JSON `processed_payment_charge_ids` remain the production duplicate registry.

### 5. Refund/Chargeback/Cancel Behavior

Clean gap:
- No refund/chargeback/cancel handlers.
- No admin command/reconciliation path.
- No matching against provider charge id for YooKassa.

Needed:
- Refund/chargeback/cancel events recorded durably and applied once.
- Subscription refund revokes only the matching paid period unless current access came from a newer payment.
- Cancel subscription records cancellation but keeps paid period access.
- Extra refund removes only matching unused extra; consumed extra refund is ignored with precise reason.
- Unknown/orphan events do not grant access and are recoverable.

Old source:
- `tests/test_payments_smoke.py`
- `tests/test_postgres_store.py`
- Old `payments.py` event types and data classes.

Risk:
- Old handoff flags exact bugs here; treat old tests as valuable, old implementation as suspect until reviewed.

### 6. Telegram Callback Ownership And Generation Locks

Clean gap:
- Basic private/group callback guard exists.
- Answer callbacks are not fully session/question-key hardened like the old tests expect.
- No durable generation lock or stale cleanup.

Needed:
- Callback payloads include session id/question key where stateful.
- Reject stale or foreign callbacks without state mutation.
- Throttle repeated callbacks.
- One active generation per user with heartbeat and stale cleanup.
- Consumption/refund tied to a generation/meal_plan id.

Old source:
- `tests/test_telegram_callback_owner_smoke.py`
- Callback/session tests in old `tests/test_telegram_app_photos.py`
- Generation lifecycle tests in old `tests/test_postgres_store.py`

Risk:
- Do not copy old `telegram_app.py` wholesale; it mixes storage, payments, analytics, privacy, runtime and UI.

### 7. Weekly PDF Final Delivery And Quality

Clean gap:
- PDF-only delivery path is present and tests cover no text fallback on failure.
- No production packaging/Docker proof that PDF data/photos/assets are installed.
- No global deadline/concurrency cap.
- No visual QA artifacts in release checklist.

Needed:
- Keep PDF-only contract for weekly ration.
- Validate Telegram max file size before upload.
- Refund attempt if PDF is not delivered.
- Verify Cyrillic text, page count, recipe completeness, shopping list, photos and file size.
- Mark heavy PDF tests as `slow_pdf_builder` and keep fast lane lean.
- Optional branding assets only after safety path is stable.

Old source:
- `src/diet_bot/pdf_renderer.py`
- `tests/test_pdf_renderer.py`
- `tests/test_pdf_limits_smoke.py`
- `src/diet_bot/data/foodbalance_pdf_logo.png`
- `src/diet_bot/data/foodbalance_pdf_qr.png`

Risk:
- Do not bring full PDF redesign together with storage/payments.

### 8. Docker/Healthcheck/Liveness

Clean gap:
- No Dockerfile, docker-compose, `.dockerignore`, liveness heartbeat or strict healthcheck.
- `src/diet_bot/healthcheck.py` only verifies local package data and runtime config guard.

Needed:
- Non-root Docker image, locked runtime dependencies, package-data install check.
- Compose with Postgres service and bot service.
- Strict healthcheck that validates production env, DB, support/privacy guardrails.
- Polling heartbeat file written by bot process and checked locally.
- Graceful shutdown and cleanup.

Old source:
- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `src/diet_bot/healthcheck.py`
- `docs/production-runbook.md`
- `tests/test_production_deploy_files.py`

Risk:
- Old deploy files assume old runtime capabilities; adapt after storage/payment slices land.

### 9. Backup/Restore/Runbook

Clean gap:
- No backup/restore scripts.
- No production runbook in clean.

Needed:
- `pg_dump` custom-format backup with retention.
- Restore drill to disposable DB with explicit safety checks.
- Runbook for deploy, rollback, health/liveness, payment incidents, refunds, support, stale generation cleanup and backup restore.

Old source:
- `scripts/ops/backup_postgres.sh`
- `scripts/ops/restore_postgres_drill.sh`
- `scripts/ops/smoke_liveness.sh`
- `docs/production-runbook.md`
- `docs/regression-checklist.md`

Risk:
- Runbook must not claim production readiness before clean implementation catches up.

### 10. CI

Clean gap:
- No `.github/workflows`.
- Only `slow_pdf_builder` marker exists.
- No `postgres_integration` marker or `--require-postgres` skip strategy.

Needed:
- Fast PR lane: `pytest -m "not slow_pdf_builder and not postgres_integration"`.
- Slow PDF lane via manual/schedule/tag.
- Postgres integration lane with service DB and `--require-postgres`.
- Docker smoke lane after deploy files land.
- Full release lane when capacity allows.

Old source:
- `.github/workflows/tests.yml`
- `.github/workflows/slow-pdf-builder.yml`
- `.github/workflows/postgres-integration.yml`
- `.github/workflows/docker-smoke.yml`
- `.github/workflows/full-suite.yml`
- `tests/conftest.py`

Risk:
- Do not copy CI until markers/dependencies exist in clean; otherwise workflows will fail or give false confidence.

### 11. Security/Privacy/Secrets

Clean gap:
- `.env.example` is safe for local use, but production secret validation is minimal.
- Support metadata currently can include processed payment charge ids.
- No public privacy policy URL requirement.
- No analytics PII filtering if analytics is reintroduced.
- YooKassa email collection needs explicit privacy disclosure.

Needed:
- Secret placeholder validation for bot token, provider token where required, DB URL and analytics salt.
- No charge ids/raw payloads/payment provider IDs in support/admin user-facing text or logs unless strictly admin-only and hashed/redacted.
- Privacy policy URL required in production and visible before payment.
- Support/admin commands guarded and audited.
- `.dockerignore` allow-list excludes `.env`, local state, backups, dumps, logs.

Old source:
- `tests/test_security_privacy.py`
- `src/diet_bot/analytics.py`
- Security/privacy checks in old healthcheck/tests.

Risk:
- Old admin reconciliation exposes operational detail; review every message/log before reusing.

### 12. Manual Telegram/Payment Release Smoke

Clean gap:
- `docs/RELEASE_SMOKE_CHECKLIST.md` is local clean-runtime oriented.
- It does not cover production DB, Docker, liveness, payment reversals or backup/restore.

Needed:
- Staging/prod-like smoke with real bot token and test payment credentials.
- Telegram `/start`, questionnaire, support, privacy, subscriber cabinet, one-day ration and weekly PDF.
- Stars subscription, Stars extra, YooKassa/card invoice with test provider.
- Pre-checkout tamper/expired/wrong-user test where feasible.
- Successful payment idempotency replay.
- Refund, chargeback and cancel via provider/admin reconciliation.
- Docker healthcheck, liveness heartbeat and backup/restore drill evidence.

Old source:
- `docs/regression-checklist.md`
- `docs/production-runbook.md`
- Old user journey and payment smoke tests.

## Old Files That Can Be Used As Source

- `src/diet_bot/postgres_migrations.py`: schema ideas, constraints, indexes.
- `src/diet_bot/postgres_store.py`: transaction patterns and generation lifecycle ideas, after review.
- `src/diet_bot/payments.py`: order/event dataclasses and payload encoding ideas.
- `src/diet_bot/runtime_config.py`: production validation helpers.
- `src/diet_bot/healthcheck.py`: strict/telegram/liveness healthcheck shape.
- `src/diet_bot/json_storage.py`: dev-only file lock concept, but add timeout.
- `scripts/migrate_json_to_postgres.py`: migration CLI structure.
- `scripts/ops/backup_postgres.sh`, `restore_postgres_drill.sh`, `smoke_liveness.sh`: ops script baseline.
- `Dockerfile`, `docker-compose.yml`, `.dockerignore`: deployment baseline.
- `.github/workflows/*.yml`: lane shape for fast, slow PDF, Postgres, Docker smoke and full suite.
- `tests/test_payments_smoke.py`: high-value payment/reversal acceptance tests.
- `tests/test_postgres_store.py`: high-value durable storage/generation tests.
- `tests/test_json_to_postgres_migration.py`: migration acceptance tests.
- `tests/test_security_privacy.py`: privacy/security regressions.
- `tests/test_telegram_callback_owner_smoke.py`: callback ownership regressions.
- `tests/test_production_deploy_files.py`: Docker/deploy file checks.
- `docs/production-runbook.md` and `docs/regression-checklist.md`: operational checklist seed.
- `docs/superpowers/specs/*payments*`, `*postgresql*`, `*weekly-ration-pdf*`: product/spec intent.

## Old Files Dangerous To Copy Wholesale

- `src/diet_bot/telegram_app.py`: too many concerns mixed together; copy only small reviewed hunks.
- `src/diet_bot/postgres_store.py`: large implementation; old notes flag timeout/lock and ledger migration gaps.
- `src/diet_bot/payments.py`: useful model, but must be revalidated against exact production ledger semantics.
- `src/diet_bot/json_storage.py`: blocking file lock without timeout.
- `scripts/migrate_json_to_postgres.py`: old handoff says `payment_events.json` is not migrated; do not ship as final migration.
- `tests/` as a whole: old tests assume old runtime/API and will create false failures/noise if bulk-copied.
- `.github/workflows/*`: require clean markers/dependencies first.
- `Dockerfile` / `docker-compose.yml`: old deploy assumes old strict healthcheck/Postgres runtime already exists.
- `README.md` / `docs/production-runbook.md`: old docs claim capabilities not present in clean.
- Full PDF redesign/assets batch: keep separate from payments/storage.

## Recommended Implementation Slices

1. Test/CI marker separation.
   Add `postgres_integration` marker, skip strategy, and fast/slow commands in docs. No production logic changes.

2. Storage contract and production config.
   Define store interface and runtime config semantics: production requires Postgres, JSON dev fallback requires explicit opt-in.

3. PostgreSQL schema/store core.
   Implement migrations and store for profiles/history/entitlements/promo/generation lifecycle with timeouts and row locks.

4. JSON migration and backup/restore.
   Implement dry-run/apply migration with audit output, one-shot migration id, backup before apply and restore drill.

5. Payment order/event model.
   Add payment orders and events as source of truth before changing Telegram payment handlers.

6. Payment handler wiring.
   Wire invoice creation, pre-checkout and successful_payment to order ledger. Enforce user/chat/provider/amount/product matching.

7. Refund/chargeback/cancel/reconciliation.
   Add reversal handlers/admin command and exact product/period matching. Keep this separate from invoice creation.

8. Generation locks and runtime hardening.
   Add one-active-generation lock, heartbeat/stale cleanup, callback session keys, throttling and bounded background work.

9. Weekly PDF finalization.
   Keep PDF-only delivery, add release quality gates, packaging checks, file-size/deadline guards and representative sample QA.

10. Docker/health/liveness/runbook.
    Add Dockerfile, Compose, `.dockerignore`, strict healthcheck, polling heartbeat, ops scripts and production runbook.

11. CI workflows.
    Add fast PR, slow_pdf_builder, postgres_integration, docker-smoke and full-suite workflows after local gates pass.

12. Manual release smoke.
    Run staged Telegram/payment smoke and capture evidence before approving paid launch.

## Acceptance Criteria For Final Product

- Production startup succeeds only with `DIET_BOT_ENV=production`, valid bot token, `DIET_BOT_DATABASE_URL`, support chat id and public HTTPS privacy policy URL.
- Production startup fails if JSON fallback is active or DB is unavailable.
- All paid state survives restart: subscription, limits, extras, payment orders/events, processed charges, promo redemptions, user profiles and generation lifecycle.
- Payment invoice payloads are unique order payloads, not static product-only strings.
- Pre-checkout rejects tampered, expired, wrong-user, wrong-chat, wrong-provider, wrong-product, wrong-currency and wrong-amount orders.
- Repeated successful_payment and repeated provider events are idempotent.
- Refund, chargeback and cancel events alter only the matching product/period and are auditable.
- Extras cannot be purchased or applied without active access unless a deliberate product rule says otherwise.
- One user cannot run overlapping paid generations that double-consume quota.
- Failed or timed-out generation refunds exactly once; completed delivery is never refunded by late failure.
- Weekly PDF is delivered as a Telegram document and never replaced by a text weekly-menu fallback on PDF failure.
- PDF samples pass visual/readability QA, file-size limit, text extraction sanity and photo/package-data checks.
- Docker image runs as non-root, contains no `.env`/local JSON/backups/dumps/logs, and passes package-data healthcheck at build.
- Compose bot healthcheck validates strict config, Postgres and polling liveness.
- Backup and restore drill pass against disposable DB.
- CI fast, slow_pdf_builder, postgres_integration and docker-smoke gates pass.
- Manual Telegram/payment release smoke is recorded with exact bot, environment, healthcheck output and payment/refund evidence.

## Test Gates By Stage

### Stage 1: Baseline/Test Separation

- `python -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"`
- `python -m pytest -q -p no:cacheprovider -m slow_pdf_builder`
- Postgres tests skip cleanly without DB unless `--require-postgres` is used.

### Stage 2: Runtime Config/Storage Contract

- `tests/test_runtime_config.py`
- `tests/test_healthcheck.py`
- Production without DB/support/privacy fails with clear messages and no secret values printed.
- Dev JSON fallback requires explicit opt-in.

### Stage 3: PostgreSQL Store

- `python -m pytest -q -p no:cacheprovider -m postgres_integration --require-postgres tests/test_postgres_store.py`
- Migration idempotency, constraints, payment idempotency, generation consume/refund, stale cleanup and lock timeout tests pass.

### Stage 4: JSON Migration/Backup

- `tests/test_json_to_postgres_migration.py`
- Dry-run writes nothing.
- Apply is one-shot per migration id and skips existing live rows.
- Payment orders, processed charges and payment events are included or release is blocked.
- `scripts/ops/backup_postgres.sh` creates non-empty dump.
- `scripts/ops/restore_postgres_drill.sh` restores into disposable DB and runs app smoke.

### Stage 5: Payment Ledger

- `tests/test_payments_smoke.py`
- `tests/test_subscriptions.py`
- Static/tampered payloads rejected.
- Wrong user/chat/provider/amount/currency/product rejected.
- Duplicate successful_payment does not grant twice.
- Extras require active subscription in both pre-checkout and successful_payment transaction.

### Stage 6: Refund/Chargeback/Cancel

- Payment smoke tests for refund before success, orphan success, chargeback, cancel_subscription and admin reconciliation.
- Refund old subscription does not revoke newer active subscription.
- Extra refund affects only matching unused extra.
- Consumed extra refund is ignored with precise reason.

### Stage 7: Telegram Runtime/Generation Locks

- `tests/test_telegram_callback_owner_smoke.py`
- User journey smoke tests for start/questionnaire/cancel/profile/menu.
- Generation lifecycle tests: concurrent double-click, stale cleanup, delivery transition and late failure.
- Bot startup/polling tests: webhook cleanup, heartbeat, graceful shutdown.

### Stage 8: Weekly PDF

- `tests/test_pdf_limits_smoke.py`
- `tests/test_pdf_renderer.py` under `slow_pdf_builder`.
- Manual sample PDFs for low/high BMI, allergies, exclusions, multiple meal counts and weekly shopping list.
- Confirm no text fallback, no oversized upload, no partial temp file left.

### Stage 9: Docker/Ops/CI

- `docker compose config`
- `docker compose build bot`
- `docker compose up -d --wait postgres`
- `docker compose run --rm bot python -m diet_bot.healthcheck --strict`
- `docker compose exec bot python -m diet_bot.healthcheck --strict --polling-liveness`
- `.github/workflows/tests.yml`, `slow-pdf-builder.yml`, `postgres-integration.yml`, `docker-smoke.yml` pass on target triggers.

### Stage 10: Manual Release Smoke

- `/start`, `/plan`, `/cancel`, `/support`, `/privacy`, `/myid`.
- New user questionnaire and free trial.
- Stars subscription and extras.
- YooKassa/card invoice with test provider and receipt/email disclosure.
- Successful payment replay/idempotency.
- Refund/chargeback/cancel/admin reconciliation.
- Weekly PDF document delivery and failure behavior.
- Healthcheck/liveness/backup/restore evidence recorded before launch approval.

## Release Decision

Current clean branch is a good stabilized base, but not a paid production product. Paid launch should remain blocked until all P0 items are implemented and their gates pass. Public sale should remain blocked until P1 items are complete and the manual Telegram/payment release smoke is recorded against a production-like deployment.
