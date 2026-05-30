# FoodBalance Recovery Integration: Telegram UI Transfer

## Scope

Stage 4 restores product-facing Telegram UI text, buttons, onboarding wording, paywall appearance, and safe promo entry points from `origin/codex/emergency-stabilization` onto hardened master.

Allowed code areas for this stage:

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/presentation.py`
- `src/diet_bot/questionnaire.py`
- `src/diet_bot/promo_codes.py` only for UI/promo presentation if needed
- selected Telegram/questionnaire/promo tests

Out of scope:

- payment application, entitlement grants, refunds, chargebacks, reconciliation, ledgers, Postgres/runtime workers, production preflight, healthcheck, monitoring, queues, and bot polling/webhook startup.

## Pre-Transfer Gate

- Current branch: `codex/recover-product-ui-on-hardened-master`.
- Initial `git status --short` contained only expected Stage 2 data/assets and Stage 3 PDF renderer changes.
- No local changes were present in:
  - `src/diet_bot/telegram_app.py`
  - `src/diet_bot/presentation.py`
  - `src/diet_bot/questionnaire.py`
  - `src/diet_bot/promo_codes.py`
  - `src/diet_bot/payments.py`
  - `src/diet_bot/subscriptions.py`
  - runtime, payment recovery, preflight, healthcheck, send, or media-validation modules.
- Product-vs-master diff was inspected for the allowed files. `telegram_app.py` was mapped by constants, handlers, keyboard builders, promo flow, paywall/payment UI, and callback prefixes rather than copied.

## Draft UI Map Before Production Edits

### start/menu/home copy

- Product already has richer FoodBalance welcome copy in current master-derived file; preserve it.
- Candidate transfer: `/promo` command, product bot command descriptions, Russian private-chat guard copy, and product menu/promo/support labels.
- Keep master-owned private-chat guard flow and do not remove callback owner/stale-questionnaire token checks.

### onboarding/questionnaire copy

- Product changes cooking-time question from three time buckets to two recipe-effort choices:
  - `Побыстрее и попроще`
  - `Можно чуть интереснее`
- Product-facing answers use the two effort modes. Existing legacy bucket answers (`до 15 минут`, `15-30 минут`, `более 30 минут`) are still accepted for saved/user-entered compatibility and continue to normalize in the builder.

### planner flow UI

- Product keeps the one-day and weekly choice labels.
- Existing plan/subscriber menus stayed route-compatible with master smoke tests. Promo entry remains available from start, `/promo`, and disabled-payment surfaces.
- Keep master one-day durable admission, idempotency keys, chat-state DB wrappers, entitlement consumption/refund handling, and send wrappers.

### weekly PDF UI

- Product text is friendlier:
  - "Собираю ваш недельный PDF"
  - "Обычно это занимает 1-3 минуты..."
  - "PDF собирается..."
  - "Я пришлю PDF сюда, когда он будет готов."
- Keep master durable weekly PDF job runtime, queue/admission hooks, payload-size validation, media validation, and fallback/error handling.

### recipe/photos UI

- Product photo delivery logic is not copied because master already owns safe local media validation.
- Keep `validate_local_photo_path`, `validate_telegram_caption`, `safe_telegram_send`, and text fallback behavior.

### paywall/payment buttons UI

- Safe transfer: product-facing wording for visible payment choices:
  - YooKassa as one-time 30-day access.
  - Telegram Stars as auto-renewing monthly subscription.
  - disabled-payment copy points users to promo access during pilot.
- Deferred to payment stage: product prices `799 ₽`, `450 Stars`, Stars extras `29/141`, test-smoke prices, public-payment flags, order metadata/receipt metadata, discount pricing, and any actual amount changes. Current master amount constants feed invoice/ledger validation, so changing them here would alter payment semantics.

### promo/admin promo UI

- Safe transfer: `/promo` entry point and promo button in disabled-payment UI.
- Deferred to payment/promo stage: discount promo creation/list/disable, discount application, promo audit metadata, monthly-access promo model replacement, and atomic transaction changes.
- Preserve master `release_promo_code_activation` rollback after entitlement grant failure.

### error/empty/loading messages

- Transferred product disabled-payment pilot text.
- Private-chat rejection keeps product Russian text plus the old `private chat` phrase for compatibility with existing hardening smoke checks.
- Keep master storage, entitlement, payment-ledger, delayed-activation, and PDF failure handling.

### callback names where product differs

- Same and safe:
  - `diet:start`
  - `diet:repeat`
  - `diet:new`
  - `diet:subscribe_month`
  - `diet:pay_stars`
  - `diet:pay_ru_card`
  - `diet:pay_ru_extra_one_day`
  - `diet:pay_ru_extra_weekly_pdf`
  - `diet:buy_extra_one_day`
  - `diet:buy_extra_weekly_pdf`
  - `diet:features`
  - `diet:promo_code`
  - `diet:support`
  - `diet:one_day`
  - `diet:week_pdf`
  - `diet:answer:`
- Product-only, not transferred in Stage 4:
  - `diet:stars_auto_renew_cancel`
  - `diet:stars_auto_renew_enable`
  - admin discount promo callbacks under `diet:admin:*`
- Master-hardened questionnaire callback payloads include session token and step index; this remains master-owned.

### master hardening zones inside telegram_app that must stay master-owned

- Application setup and `run_bot` startup validation.
- Private-chat guards.
- Questionnaire callback token/step ownership checks.
- Throttled/retried Telegram send and media validation.
- Entitlement and chat-state DB wrappers.
- Durable one-day and weekly PDF job admission/recovery hooks.
- One-day and weekly idempotency keys.
- Payment service/order payload validation, successful-payment recovery spool, delayed activation messaging, and ledger unavailable handling.
- Logging/redaction and diagnostics.

## Transfer Log

- Updated Telegram start/payment copy to product-facing FoodBalance wording while keeping master payment amounts unchanged:
  - start subscribe button now says `Доступ на 30 дней`;
  - payment options distinguish YooKassa one-time access and Telegram Stars auto-renewing subscription;
  - disabled-payment text explains promo-code pilot access.
- Added `/promo` command handler using the existing promo activation path and rollback behavior.
- Kept `BOT_COMMANDS` route-compatible with master smoke tests; `/promo` works even though it is not advertised in the command list yet.
- Updated weekly PDF status/loading text to product copy while keeping durable queue/admission/recovery code intact.
- Updated questionnaire cooking-time UI to two product effort choices, with legacy bucket answers preserved.
- Updated presentation shopping wording from `покупок` to `продуктов` and product threshold dots (`green >= 95%`, `yellow >= 45%`).
- Added focused UI smoke tests for start menu, payment labels, disabled-payment promo entry, `/promo`, and callback-token/private-chat copy.
- Did not edit `promo_codes.py`, `payments.py`, `subscriptions.py`, runtime, Postgres, queue, recovery, preflight, healthcheck, send, or media-validation modules.

## Files Changed

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/presentation.py`
- `src/diet_bot/questionnaire.py`
- `tests/test_questionnaire_and_presentation.py`
- `tests/test_telegram_user_journeys_smoke.py`
- `tests/test_telegram_callback_owner_smoke.py`
- `docs/recovery-integration/telegram-ui-transfer.md`

## Tests And Checks

RED before production edits:

- `pytest tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_questionnaire_and_presentation.py -q`
  - expected RED: `15 failed, 12 passed`
  - failures covered old payment labels, missing `/promo`, missing product private-chat constants, old cooking-time prompt/options, old shopping wording, and old threshold dots.

Passed after implementation:

- `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_questionnaire_and_presentation.py -q`
  - `38 passed in 44.65s`
- `pytest tests/test_promo_codes.py -q`
  - `6 passed in 0.14s`
- `pytest tests/test_pdf_renderer.py tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `244 passed in 80.49s`
- `$env:PYTHONPATH='src'; python -m diet_bot.healthcheck`
  - exit code `0`, `issues: none`
  - first plain `python -m diet_bot.healthcheck` failed only because the source checkout was not on `PYTHONPATH`.
- `git diff --check`
  - exit code `0`
  - only existing Windows CRLF checkout warnings were printed.

## Deferred To Stage 5

- Product payment amounts and test-smoke prices:
  - subscription `799 ₽` / `450 Stars`;
  - Stars extras `29` and `141`;
  - test prices `100 ₽` / `1 Star`.
- Public payment flags and production/test-price gates from product runtime config.
- Discount promo model, admin discount create/list/disable callbacks, pending discount storage, audit metadata, and discounted order metadata.
- Stars managed subscription fields and UI callbacks:
  - `diet:stars_auto_renew_cancel`
  - `diet:stars_auto_renew_enable`
- Payment invoice/order metadata and receipt title migration where it is tied to payment model tests.
- Successful payment application, idempotency, entitlement grants, refunds, chargebacks, reversal/reconciliation, recovery spool/replay, and durable payment storage changes.
- Broader promo placement in plan/subscriber/paywall/trial paid keyboards can be revisited with payment/promo UX tests; Stage 4 kept those master-compatible.

## Master Hardening Preserved

- Application setup and `run_bot` startup validation.
- Private-chat checks and existing hardening tests.
- Questionnaire callback session-token and step ownership checks.
- Chat-state and entitlement DB wrappers.
- Durable one-day and weekly PDF job runtime/admission/recovery hooks.
- Payment order payload validation, pre-checkout validation, successful-payment recovery spool, delayed activation messaging, and ledger unavailable handling.
- Telegram media validation and text chunking.
- Logging/redaction and diagnostics.

## Remaining Risks

- UI is product-like but not a blind product copy. Product-only discount/admin promo and Stars auto-renew UI require Stage 5 data/payment fields.
- Payment labels now describe current master amounts as one-time YooKassa access and Stars auto-renewing subscription; product amount migration remains explicitly deferred.
- The known builder/selection edge case from Stage 2 remains unresolved and should be closed before final release/full builder gate, though it does not block moving into payment/promo/subscription integration.
