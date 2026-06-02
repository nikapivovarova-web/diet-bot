# Codex security readonly check

Дата проверки: 2026-05-31

Рабочая директория: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`

Branch: `codex/recover-product-ui-on-hardened-master`

HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## 1. Что проверено

- Текущий git-state и границы dirty worktree перед проверкой.
- Diff после audit fixes по зонам риска: платежи, подписки, Postgres payment/promo storage, reconciliation, safety, runtime/preflight/healthcheck, Telegram runtime guards, weekly PDF fallback.
- Сценарии оплаты и возвратов:
  - payload/nonce/checksum/order binding;
  - pending order reuse и expiry;
  - successful payment grant transaction;
  - refund/cancel/reversal handling;
  - reconciliation report for mismatched, duplicate, missing, refunded/canceled/reversed charges.
- Promo/discount path:
  - Postgres promo migrations and tables;
  - claim locking and idempotency;
  - single active redemption constraints;
  - payment order and entitlement grant path for promo claims.
- Production guardrails:
  - payments disabled by default in safe env examples;
  - worker flags and fail-closed production preflight checks;
  - single-poller/preflight healthcheck paths;
  - secret redaction paths.
- Telegram app risk points:
  - admin callback ownership checks;
  - private chat/privacy guard paths;
  - payment callback/success handlers;
  - weekly PDF fallback execution path.
- Nearby existing tests for these paths.

## 2. Какие команды запускались

- `git status --short`
  - Зафиксирован уже dirty worktree до этой проверки; изменения были в коде и тестах, плюс новые recovery docs/staging files.
- `git rev-parse --abbrev-ref HEAD`
  - Branch: `codex/recover-product-ui-on-hardened-master`.
- `git rev-parse HEAD`
  - HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`.
- `git diff --stat`
  - 15 files changed, 2706 insertions(+), 48 deletions(-).
- `git diff --check`
  - Exit 0. Были только LF-to-CRLF warnings, без whitespace errors.
- `rg` / read-only file reads по:
  - `src/diet_bot/payments.py`
  - `src/diet_bot/payment_service.py`
  - `src/diet_bot/postgres_payment_store.py`
  - `src/diet_bot/payment_reconciliation.py`
  - `src/diet_bot/subscriptions.py`
  - `src/diet_bot/postgres_promo_store.py`
  - `src/diet_bot/postgres_promo_migrations.py`
  - `src/diet_bot/promo_codes.py`
  - `src/diet_bot/telegram_app.py`
  - `src/diet_bot/runtime_config.py`
  - `src/diet_bot/healthcheck.py`
  - `src/diet_bot/production_preflight.py`
  - `.env.example`
  - `docs/production-runbook.md`
  - `scripts/ops/postgres_restore_drill.py`
  - nearby tests.
- Targeted pytest without prod secrets, Telegram API, bot start, deploy, or real payments:

```powershell
$env:PYTHONPATH='src'
$env:DIET_BOT_ENV='test'
$env:DIET_BOT_PAYMENTS_ENABLED='0'
$env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED='0'
$env:TELEGRAM_PROVIDER_TOKEN=''
python -m pytest -q tests/test_payments.py tests/test_payment_reconciliation_report.py tests/test_subscriptions.py tests/test_runtime_config.py tests/test_healthcheck.py tests/test_production_preflight.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_runtime.py tests/test_safety_and_builder.py tests/test_weekly_pdf_postgres_wiring.py tests/test_postgres_promo_store.py tests/test_postgres_payment_store.py
```

Результат: `252 passed, 29 skipped in 586.84s (0:09:46)`.

Важно: DSN-backed Postgres integration checks from selected files were included, but skipped where no safe disposable local test DSN was available.

## 3. Findings by blocker/high/medium/low

### Blocker

No blocker findings found in the safe readonly scope.

### High

#### HIGH-1: Refund/cancel/reversal for extra purchases can leave paid extra access usable until manual review

Severity: high.

File:

- `src/diet_bot/subscriptions.py`
- `src/diet_bot/postgres_payment_store.py`
- confirming tests:
  - `tests/test_subscriptions.py`
  - `tests/test_postgres_payment_store.py`

Exact place:

- `src/diet_bot/subscriptions.py:339-376`
  - `apply_payment_reversal()` records a reversal marker, but for `extra_one_day` and `extra_weekly_pdf` returns `manual_review_required=True` with reason `extra_entitlement_requires_manual_review`.
  - It does not decrement `extra_one_day_remaining` or `extra_weekly_pdf_remaining`.
- `src/diet_bot/postgres_payment_store.py:289-370`
  - `record_payment_reversal()` updates the charge/order status and then applies entitlement reversal only on the non-mismatch path.
- `src/diet_bot/postgres_payment_store.py:684-703`
  - `_apply_payment_reversal_entitlement_cur()` loads entitlement, calls `apply_payment_reversal()`, and upserts the entitlement after the reversal result.
  - For extra purchases, the upsert persists the unchanged extra counter.
- `tests/test_subscriptions.py:397-416`
  - Existing unit test confirms that refunding one extra weekly PDF leaves `extra_weekly_pdf_remaining == 2`.
- `tests/test_postgres_payment_store.py:665-710`
  - Existing Postgres test confirms that a refunded extra weekly PDF charge is idempotent but leaves `extra_weekly_pdf_remaining == 1`.

What is wrong:

Refund/cancel/reversal events for extra purchases do not revoke or reserve the corresponding paid extra entitlement. They mark manual review required, but the extra access counter remains available.

Why this is important:

The requested launch/security condition was that refund/cancel/reversal must not leave paid access. For extra one-day access and extra weekly PDF purchases, a refunded purchase can still be consumed before an operator completes manual review. This is especially risky because these products are represented as aggregate counters, so the system cannot currently identify and remove exactly the refunded extra unit.

How to reproduce/verify:

- Unit-level: run `tests/test_subscriptions.py::test_refund_of_extra_purchase_requires_manual_review_without_removing_unrelated_access`.
  - It applies two extra weekly PDF grants, refunds one charge, and expects the counter to remain `2`.
- Postgres-level with a safe disposable test DSN: run `tests/test_postgres_payment_store.py::test_payment_reversal_repeated_refund_is_idempotent`.
  - It records an extra weekly PDF payment, records a refund twice, and expects the DB entitlement counter to remain `1`.

How to fix:

- Do not rely only on aggregate counters for refundable extra entitlements.
- Track extra purchase inventory by charge/order, or otherwise keep enough state to bind each extra entitlement unit to its payment charge.
- On full refund/cancel/reversal of an unused extra purchase, decrement the matching remaining counter exactly once.
- If the extra unit was already consumed or cannot be matched safely, fail closed for the affected extra access path: mark manual review and prevent further consumption of access derived from the reversed charge until review resolves it.
- Keep duplicate reversal idempotency: the second identical refund/cancel/reversal must not decrement twice.
- Consider applying the same fail-closed treatment to context-mismatch reversal paths where entitlement is currently left active for manual review.

Needed test:

- Unit tests for `extra_one_day` and `extra_weekly_pdf` reversal before consumption:
  - counter decreases once;
  - duplicate reversal is idempotent;
  - unrelated active subscription/test access is preserved.
- Unit tests for reversal after consumption or ambiguous mapping:
  - manual review is required;
  - no additional paid extra access from the reversed charge remains consumable.
- Postgres integration tests with disposable local DSN for the same scenarios in one transaction:
  - charge status updated;
  - order marked failed/refunded/canceled/reversed as appropriate;
  - entitlement counter/state updated;
  - duplicate reversal remains idempotent.

Blocks launch?

Yes for launching or enabling paid extra products and payment flows. For a non-payment manual smoke with payments disabled, this does not block basic smoke, but it does block the security/payment readiness verdict.

### Medium

No medium findings found in the safe readonly scope.

### Low

No low findings found in the safe readonly scope.

## 4. Что не удалось безопасно проверить

- Real Telegram API behavior, including `getUpdates`, webhook/polling conflicts, live callbacks, and real payment updates.
- Real Telegram Stars/provider payment processing.
- Production database state, production migrations against prod DB, production restore drill, or prod reconciliation.
- DSN-backed Postgres integration coverage where a disposable local `DIET_BOT_TEST_DATABASE_URL` was required but not available in this run.
- Manual UI smoke in Telegram.
- Full `pytest` suite beyond the targeted safe run; the instruction prohibited long full-suite runs over 20 minutes, and the targeted run already covered the requested risk zones in under 10 minutes.
- Photo/staging content import correctness outside the inspected code paths.

## 5. Final verdict

READY ONLY AFTER FIXES.

Reason: the selected readonly security/regression scope found one high payment-readiness risk. Refund/cancel/reversal for extra paid purchases can leave the extra entitlement counter available until manual review, which violates the requested "does not leave paid access" condition for payment launch.

## 6. Safety confirmation

- Application/source code was not edited by this check.
- Only this report file was created.
- Bot was not started.
- No deploy, restart, commit, tag, push, or PR was done.
- No Telegram API calls were made, including no `getUpdates`.
- No production DB was accessed.
- No real payment provider/Stars flow was used.
- Payments were not enabled.
- Secrets and DSNs were not printed.
- Archived/recovered bots, `New project 2 CLEAN`, and selected-53 import/staging content were not modified.
