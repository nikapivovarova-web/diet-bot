# Payments Production Plan

Дата: 2026-05-12

Scope: read-only / docs-only plan for FoodBalance payments. This document is the only artifact for this task. It does not change `src/`, `tests/`, storage Task 4, or any runtime behavior.

## Hard Stop Before Any Payment Implementation

Payments implementation must not start until the storage layer has a durable PostgreSQL path and at least the `payment_orders` placeholder from the storage plan. Do not expand or edit Storage Task 4 for payments; Task 4 is storage connection/core state only.

Payment handler wiring must wait until order lookup, order status updates, and provider charge idempotency can happen in durable storage. Paid state must not be stored in JSON for production, and `successful_payment` must never be applied directly from `message.chat.id` without a durable order lookup.

Weekly PDF is a paid delivery product. If PDF delivery fails, the production path must refund or preserve the attempt according to the generation ledger. It must not fall back to a text weekly menu as paid delivery.

## Source Findings

Clean branch findings:

- `docs/AI_HANDOFF.md` says the old mixed branch is source material only and flags payment/refund/chargeback, incomplete payment ledger migration, and JSON fallback risks.
- `docs/PRODUCTION_RELEASE_GAP_AUDIT.md` identifies no durable payment orders/events ledger, direct `successful_payment` application, JSON subscription state, missing refund/chargeback/cancel handling, and missing production smoke coverage.
- `docs/superpowers/plans/2026-05-12-production-postgres-storage.md` reserves `payment_orders` as a storage placeholder and explicitly excludes payment business logic, refunds, chargebacks, reconciliation, and successful-payment handling from storage work.
- Clean `src/diet_bot/subscriptions.py` contains useful pure entitlement operations, but it stores processed charge ids in JSON and does not provide durable payment idempotency.
- Clean `src/diet_bot/telegram_app.py` currently uses static invoice payloads, validates pre-checkout only by payload/currency/amount, and applies `successful_payment` directly to entitlement state by chat id.

Old folder findings:

- Old `src/diet_bot/payments.py` has useful ideas for `PaymentOrder`, `PaymentEvent`, processed charge aliases, order payload encoding, orphan payments, and redaction.
- Old `src/diet_bot/subscriptions.py` has useful tests/ideas for subscription extension, extra access requiring active subscription, and reversal semantics, but it still contains JSON helpers.
- Old `tests/test_payments_smoke.py` has the highest-value payment acceptance tests, especially order nonce, idempotency, wrong user/chat, refunds, chargebacks, cancel, reconciliation, and raw payload redaction.
- Old specs describe product intent for Telegram Stars subscriptions, YooKassa Telegram Payments, free trial funnel, prices, limits, receipt email, and provider data.

## Required Paid Product Features

### Telegram Stars Monthly Subscription

- Product: `subscription_month`.
- Provider: `telegram_stars`.
- Currency: `XTR`.
- Current intended amount: `400` Stars.
- Billing period: 30 days / `2_592_000` seconds.
- Grants an active monthly period plus monthly package:
  - 5 one-day ration attempts.
  - 4 weekly PDF attempts.
- Renewal must create or match a new durable order/charge and must not accumulate unused monthly limits.
- If Telegram sends a subscription expiration timestamp, the ledger must store it with the paid period and use it only after order/provider validation.

### YooKassa/Card Monthly Access

- Product: `subscription_month`.
- Provider: `yookassa` through Telegram Payments.
- Currency: `RUB`.
- Current intended amount: `59900` kopecks.
- Production launch can use a monthly access invoice if recurring YooKassa subscription behavior is not implemented and verified. Do not market it as automatic card renewal unless recurring behavior is provider-tested and covered by tests.
- Invoice must request email and send receipt data to provider:
  - `need_email=True`.
  - `send_email_to_provider=True`.
  - `provider_data.receipt.items`.
- Privacy disclosure must be visible before payment because YooKassa email/receipt data is collected through Telegram checkout.

### Extra One-Day Ration

- Product: `extra_one_day`.
- Providers:
  - Telegram Stars: `35` Stars.
  - YooKassa/card: `5000` kopecks.
- Must be purchasable and applicable only with active paid subscription access, unless a future explicit product decision changes this.
- Extra quota is separate from monthly quota and is consumed only after monthly one-day quota is exhausted.

### Extra Weekly PDF

- Product: `extra_weekly_pdf`.
- Providers:
  - Telegram Stars: `170` Stars.
  - YooKassa/card: `25000` kopecks.
- Must be purchasable and applicable only with active paid subscription access, unless a future explicit product decision changes this.
- Delivery must be Telegram document PDF only. No text fallback weekly ration can satisfy this paid product.

### Promo Codes

- Promo codes are not provider payments.
- They should create auditable admin/product grants, not fake provider charges.
- Required grant types:
  - monthly access.
  - extra one-day attempts, if product wants promo extras.
  - extra weekly PDF attempts, if product wants promo extras.
  - test access days.
- Redemptions must be durable, one-per-user where configured, max-use limited where configured, and independent from processed provider charges.

### Test Access And Admin Grants

- Test access/admin grants are operational entitlements, not payments.
- They must be auditable with admin identity hashed/redacted in logs and payment-event raw payloads.
- They must not create provider charge ids or pollute `processed_provider_charges`.
- They must be revocable without touching paid orders/events.

## Payment Ledger Contract

The ledger is the source of truth for paid launch. Entitlement changes are derived from durable orders/events under transaction, not from JSON and not from Telegram message context alone.

### `payment_orders`

Purpose: durable checkout intent and validation target.

Required fields:

- `order_id`: unique internal id.
- `nonce`: unguessable value used in payload.
- `payload`: encoded as an order payload such as `diet:order:<order_id>:<nonce>`, not a static product payload.
- `user_id`: Telegram user id that initiated checkout.
- `delivery_chat_id`: chat where paid result/access should be delivered.
- `provider`: `telegram_stars` or `yookassa`.
- `product`: `subscription_month`, `extra_one_day`, or `extra_weekly_pdf`.
- `amount`: provider amount in the smallest unit used by Telegram checkout: Stars integer for `XTR`, kopecks for `RUB`.
- `currency`: `XTR` or `RUB`.
- `status`: at minimum `pending`, `paid`, `expired`, `failed_invoice_creation`.
- `created_at`, `expires_at`, `paid_at`, `updated_at`.
- `invoice_link`: Telegram invoice link returned by `create_invoice_link`, if created.
- `pre_checkout_approved_at`: recommended audit field or event so a successful payment that arrives after local TTL can still be accepted if it was approved before expiry.

Order rules:

- Repeated button taps may reuse an active pending order for the same user/provider/product/chat, but must not create multiple live payable links unnecessarily.
- Static legacy payloads must be disabled by default in production.
- Expired pending orders must be rejected at pre-checkout and marked expired.
- A final successful payment may be accepted after `expires_at` only if the same order was approved by valid pre-checkout before expiry and has no terminal successful/reversal conflict.

### `payment_events`

Purpose: append-only provider/admin event history.

Required fields:

- `event_id`: internal event id or provider/admin event id when available.
- `event_type`: `successful_payment`, `refund`, `chargeback`, `cancel_subscription`, `unknown`.
- `provider`: `telegram_stars`, `yookassa`, or controlled admin source for reconciliation events.
- `order_id`: nullable for orphan events, required when matched.
- `charge_id`: canonical id used for idempotency.
- `telegram_charge_id`: Telegram charge id when available.
- `provider_charge_id`: provider charge id when available.
- `user_id`, `delivery_chat_id`, `product`, `amount`, `currency`.
- `status`: `processed`, `duplicate`, `pending_reconciliation`, `orphan_recoverable`, or `ignored_non_terminal`.
- `reason`: precise machine-readable reason for ignored/pending events.
- `raw_payload_redacted`: safe diagnostic payload only.
- `created_at`, `processed_at`.

Event rules:

- Events are immutable except for controlled reconciliation of a transitional event from pending/orphan to processed.
- Every provider/admin event is recorded even when it does not grant or revoke access.
- Unknown events must not mutate access.
- Admin reconciliation events must include hashed admin metadata, not raw admin ids in user-facing or broadly logged payloads.

### Processed Provider Charges

Purpose: durable idempotency independent from bounded entitlement JSON arrays.

Required fields:

- `provider`.
- `charge_id`.
- `telegram_charge_id`.
- `provider_charge_id`.
- `order_id`.
- `event_type`.
- `user_id`.
- `product`.
- `created_at`.

Rules:

- Unique idempotency key must include provider, charge alias, and event type where appropriate.
- Charge aliases must match Telegram and YooKassa ids so a YooKassa refund can match `provider_payment_charge_id`.
- Legacy `processed_payment_charge_ids` from JSON can be imported only as limited legacy metadata, not as the final ledger.

### Raw Payload Redaction

Raw payment data must be redacted before storing in application logs, support messages, or durable event metadata.

Allowed examples:

- invoice payload / order id / nonce only if operationally needed.
- Telegram charge id and provider charge id in admin-only durable ledger.
- provider, product, amount, currency, event type, status, reason.

Forbidden in general logs/support/user-facing text:

- email, phone number, full `order_info`.
- raw receipt/customer payload.
- bot token, provider token, database URL.
- raw user/admin ids where a hash is enough.
- full raw provider webhook or Telegram object dump.

## P0 Risks To Close

1. Duplicate `successful_payment`
   - Must be idempotent by durable provider charge alias and order status.
   - Replays must not grant limits twice, even after any bounded in-memory/JSON list would have evicted an old charge id.

2. Wrong user
   - `successful_payment` must match `payment_orders.user_id`.
   - A payment update processed under another Telegram user id must not grant access.

3. Wrong chat
   - Delivery and entitlement mutation must match `delivery_chat_id` policy.
   - Group/foreign chat updates must not redirect paid access.

4. Wrong product
   - Product must come from the stored order, not from a mutable/static payload string.
   - A charge for subscription cannot be applied as an extra, and an extra cannot be applied as subscription.

5. Wrong amount/currency
   - Pre-checkout and final application must verify stored amount and currency.
   - `XTR` and `RUB` payloads must never be interchangeable.

6. Expired order
   - Pre-checkout must reject expired pending orders.
   - Final `successful_payment` can only pass after expiry when the same order had valid pre-checkout approval before expiry.

7. Replay
   - Nonce payload prevents fabricated/static payload replay.
   - Provider charge idempotency prevents repeated Telegram updates or admin commands from changing access twice.

8. Orphan `successful_payment`
   - Must be recorded as orphan/pending reconciliation.
   - Must not grant access without matching durable order.
   - Admin reconciliation can later match it once, with audit trail.

9. Refund before success
   - Must be recorded as `pending_reconciliation`.
   - If the successful payment arrives later, reconciliation must apply both events in order and leave access revoked when refund is terminal.

10. Chargeback
    - Must be a terminal negative event tied to exact original charge/product/period.
    - Must be idempotent and auditable.

11. Cancel subscription
    - Must record cancellation without revoking already paid access period.
    - Later refund/chargeback can still revoke only the matching paid period.

12. Extra purchase without active subscription
    - Must be blocked both at pre-checkout and at successful-payment transaction time.
    - UI button checks are not sufficient.

13. Refund old subscription should not revoke newer paid period
    - Subscription paid periods must be linked to their source order/charge.
    - Refund of an older order can revoke only the entitlement period created by that order. If the user has a newer paid period, current access must remain active.

## Implementation Slices

Do not begin these slices until durable storage and `payment_orders` placeholder exist in the clean storage layer. Tests should be written inside each slice before implementation, but the release order should stay narrow.

1. Payment model/data classes
   - Define final `PaymentOrder`, `PaymentEvent`, processed charge, provider/product enums, statuses, payload encode/decode, and redaction helpers.
   - Use old `payments.py` for ideas only.

2. Payment order creation
   - Create/reuse pending orders under transaction.
   - Store user id, delivery chat id, provider, product, amount, currency, expiry, and invoice link.
   - Do not grant entitlements in this slice.

3. Invoice payload generation
   - Replace static payloads with order payloads containing order id + nonce.
   - Preserve Telegram Stars `subscription_period` for monthly Stars.
   - Preserve YooKassa receipt/email provider data and privacy pre-payment requirements.

4. Pre-checkout validation
   - Decode order payload.
   - Lookup order by id/nonce.
   - Validate status, expiry, user/chat policy, provider, product, amount, currency, and active subscription requirement for extras.
   - Record pre-checkout approval for accepted orders.

5. `successful_payment` idempotent application
   - Lookup order before any entitlement mutation.
   - Validate provider charge aliases, amount/currency/product/user/chat.
   - Record `successful_payment` event and processed provider charge.
   - Apply entitlement changes in the same durable transaction.
   - Mark order paid exactly once.

6. Extra purchase enforcement
   - Enforce active subscription at order creation, pre-checkout, and success transaction.
   - Add tests for expired subscription between invoice creation and success.

7. Refund/chargeback/cancel
   - Add provider/admin event ingestion.
   - Apply refund/chargeback only to matching order/product/period.
   - Record cancel without revoking paid period.
   - Keep consumed extra refund behavior precise: if already consumed, record ignored reason instead of inventing quota.

8. Admin reconciliation
   - Add admin-only command or tool path for orphan success, pending refund, chargeback, and cancel.
   - Reconciliation must be idempotent and redact admin/user identifiers in logs.

9. Telegram handler wiring
   - Wire invoice buttons, `pre_checkout_query`, `successful_payment`, refund/cancel/admin paths to the ledger.
   - Keep this separate from model/storage work so handler regressions are easy to isolate.

10. Tests
    - Transfer tests in priority order from old files, adapting APIs and fixtures instead of bulk-copying.
    - Keep payment unit tests fast; mark provider/Postgres integration separately.

11. Manual payment smoke
    - Run staging/prod-like Telegram + Stars + YooKassa smoke only after automated gates pass.
    - Record bot/environment, healthcheck, order ids, redacted charge ids, and refund/reconciliation evidence.

## Old Files To Use As Source Of Ideas

- `C:\Users\adck8\Documents\New project 2\src\diet_bot\payments.py`
  - Use for order/event dataclass ideas, payload encoding, processed charge aliases, orphan event shape, and redaction direction.
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\subscriptions.py`
  - Use for pure entitlement behavior ideas: renewal extension, extra consumption requiring active subscription, and reversal result reasons.
- `C:\Users\adck8\Documents\New project 2\tests\test_payments_smoke.py`
  - Use as the primary acceptance-test source for payments.
- `C:\Users\adck8\Documents\New project 2\tests\test_subscriptions.py`
  - Use for entitlement, renewal, extra, reversal, and corruption-safety expectations.
- `C:\Users\adck8\Documents\New project 2\tests\test_security_privacy.py`
  - Use for no charge ids in support text, hashed invoice-error log metadata, and privacy policy expectations.
- `C:\Users\adck8\Documents\New project 2\docs\superpowers\specs\2026-05-09-yookassa-telegram-payments-design.md`
  - Use for YooKassa provider-token, email, receipt, `RUB`, and receipt-item details.
- `C:\Users\adck8\Documents\New project 2\docs\superpowers\specs\2026-05-08-telegram-stars-subscription-limits-design.md`
  - Use for Stars prices, monthly limits, free trial restrictions, and subscription period.
- `C:\Users\adck8\Documents\New project 2\docs\superpowers\specs\2026-05-08-free-trial-subscription-flow-design.md`
  - Use for product funnel context around free trial and subscription CTA.

## Old Files Not To Copy Wholesale

- Old `src\diet_bot\payments.py`
  - Useful concepts, but JSON persistence and old assumptions must be replaced by durable storage semantics.
- Old `src\diet_bot\subscriptions.py`
  - Keep pure logic ideas only; do not copy JSON storage helpers or processed-charge JSON registry as production design.
- Old `tests\test_payments_smoke.py`
  - Do not bulk-copy. Port tests by behavior after clean APIs exist.
- Old `tests\test_subscriptions.py`
  - Do not bulk-copy. Select and adapt tests that match the final storage/ledger design.
- Old `tests\test_security_privacy.py`
  - Do not bulk-copy. Port specific privacy/security regressions.
- Old payment specs
  - Treat as source intent, not final architecture; older specs mention JSON MVP storage, which is not acceptable for paid production.
- Any old `telegram_app.py`, entire `tests/`, or storage/deploy files from the old folder
  - They are mixed with unrelated runtime, storage, PDF, CI, deploy, analytics, and data changes.

## Tests To Transfer First

Priority 1: order and payload safety from `test_payments_smoke.py`.

- Unique order payload per product/provider.
- Tampered nonce rejected.
- Static legacy payload rejected by default.
- Stars and YooKassa orders preserve provider/product/currency/recurring metadata.
- Repeated payment callback reuses active pending order.
- Expired pending order rejected at pre-checkout.

Priority 2: successful-payment idempotency and ownership.

- Duplicate `successful_payment` does not grant twice.
- Dedupe survives legacy entitlement charge-id FIFO eviction.
- Legacy processed charge ids are backfilled/matched safely.
- Wrong delivery chat rejected.
- Other user id rejected.
- Successful payment after valid pre-checkout approval is accepted idempotently.

Priority 3: subscription/extras behavior from `test_subscriptions.py`.

- Renewal extends active period from current end.
- Monthly limits reset without accumulation.
- Extras require active subscription to consume.
- Extras unlock after renewal.
- Duplicate charge does not grant twice.

Priority 4: reversals and reconciliation from `test_payments_smoke.py`.

- Refund after subscription removes matching access.
- Refund before success is pending then reconciled.
- Refund old subscription keeps newer paid period.
- Refund subscription keeps separately paid extras.
- Refund/chargeback specific extra affects only that extra.
- Consumed extra refund is ignored with precise reason.
- Cancel subscription keeps paid period.
- Admin reconciliation applies orphan success and pending refund once.

Priority 5: privacy/security.

- Raw payment payload redacts email/phone/order info.
- Support admin message does not include charge ids.
- Invoice exception logs hash user/order identifiers.
- Admin event payloads do not expose raw admin id or user id.
- Privacy policy mentions payment/support metadata and is shown before YooKassa email collection.

Priority 6: promo/test access.

- Promo code grants intended access and cannot be reused when configured.
- Admin/test access is auditable and independent from provider payment ledger.

## Acceptance Criteria For Paid Launch

- Production startup requires durable database configuration and fails if production would write paid state to JSON.
- `payment_orders`, `payment_events`, and processed provider charges survive restart.
- Invoice payloads are order nonce payloads, not static product strings.
- Pre-checkout rejects tampered, expired, wrong-user, wrong-chat, wrong-provider, wrong-product, wrong-currency, and wrong-amount orders.
- `successful_payment` never grants access without durable order lookup.
- Repeated successful payments and repeated provider/admin events are idempotent.
- Telegram Stars monthly subscription grants exactly the monthly product period and limits.
- YooKassa/card invoice grants the same monthly access only after valid provider/amount/currency/order validation.
- Extras cannot be bought or applied without active subscription.
- Refund, chargeback, and cancel events mutate only matching product/order/period and are auditable.
- Refund of an old subscription does not revoke a newer paid period.
- Promo/test/admin grants are auditable and do not create fake provider charges.
- No charge ids/raw payloads/email/phone leak into support text, user-facing messages, or non-admin logs.
- Weekly PDF paid delivery is a Telegram document and never a text weekly-menu fallback.
- Manual Telegram/Stars/YooKassa smoke is completed against a production-like deployment with redacted evidence.

## Manual Telegram / YooKassa / Stars Smoke Checklist

### Preflight

- Confirm staging/prod-like bot uses durable DB and production-style config.
- Run strict healthcheck and confirm production JSON fallback is disabled.
- Confirm privacy URL/support path are visible before payment.
- Confirm bot token, YooKassa provider token, database URL, and support/admin ids are not printed in logs.
- Confirm backup/restore or disposable DB reset plan is available before live payment testing.

### Telegram Stars

- Create monthly Stars invoice.
- Verify invoice payload is `diet:order:<order_id>:<nonce>`.
- Pay monthly subscription.
- Confirm order is `paid`, success event recorded, provider charge recorded, subscription period active, monthly limits set.
- Replay the same `successful_payment`; confirm no second grant.
- Buy extra one-day with active subscription; confirm one extra grant.
- Buy extra weekly PDF with active subscription; confirm one extra weekly PDF grant.
- Attempt extra purchase without active subscription; confirm blocked before checkout and again at final application if state changed.
- Run cancel subscription event; confirm paid period remains active.
- Run refund/chargeback against the matching charge; confirm only matching access/quota changes.

### YooKassa/Card Via Telegram Payments

- Create monthly YooKassa invoice with test provider token.
- Confirm `RUB`, amount in kopecks, `need_email=True`, `send_email_to_provider=True`, and receipt provider data.
- Complete test card payment and verify durable order/event/charge records.
- Confirm email/phone/order_info are not stored in raw payload metadata.
- Replay the successful payment update; confirm idempotency.
- Apply YooKassa refund using provider charge id; confirm provider-charge alias matching.
- Verify wrong currency/amount test queries are rejected.

### Paid Delivery

- Generate one-day ration after subscription and confirm quota consumption is recorded.
- Generate weekly PDF after subscription or extra weekly purchase.
- Confirm Telegram receives a document PDF.
- Simulate PDF generation/delivery failure in staging; confirm attempt is refunded/preserved exactly once and no text weekly menu is delivered as paid fallback.

### Admin/Reconciliation

- Record an orphan successful payment and confirm it does not grant access until admin reconciliation.
- Reconcile orphan success once; confirm second reconciliation is duplicate/no-op.
- Record refund before success and confirm pending status.
- Reconcile after matching success and confirm final access state is correct.
- Run admin chargeback/cancel/refund commands with redacted admin metadata.
- Confirm support/admin messages do not expose charge ids or raw provider payloads.

### Restart/Durability

- Restart bot process after payment success.
- Confirm subscription, extras, orders, events, processed charges, promo redemptions, and generation state remain available.
- Repeat a replay/idempotency check after restart.

## Storage Dependencies And No-Start Gates

Do not start payment implementation until these storage conditions are true:

- Durable PostgreSQL storage is the production path.
- Production JSON fallback is disabled.
- Storage migrations can add and verify payment tables safely.
- `payment_orders` placeholder exists from storage layer with order id, nonce, user id, delivery chat id, provider, product, amount, currency, status, expiry, and invoice link.
- Store operations needed by payments can run in transactions with row locks and DB timeouts.
- Entitlements can be updated durably in the same transaction as payment event/order application.
- Promo redemptions and test/admin grants have durable audit records or a defined storage slice.
- Generation consumption/refund ledger exists before paid weekly PDF delivery is treated as production-safe.

The following work must not start before the durable payment ledger exists:

- Telegram handler rewrite for payment buttons.
- Replacement of invoice payloads in production.
- Pre-checkout order validation in production.
- `successful_payment` entitlement mutation.
- Refund, chargeback, cancel, or admin reconciliation behavior.
- JSON-to-Postgres migration for live paid users.
- Paid launch smoke.

The storage plan may reserve `payment_orders` first, but paid launch requires the full payment ledger: orders, events, processed provider charges, and exact entitlement mutation history. A storage-only `payment_orders` placeholder is not enough to launch paid payments.
