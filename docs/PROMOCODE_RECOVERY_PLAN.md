# Promocode Recovery Plan

Scope: docs-only design/audit slice for promocodes after the storage/payments phase. No production code, PDF work, recipe quality work, Telegram UX changes, cleanup, refactor, or push is included in this slice.

## Product Goal

FoodBalance needs two promo categories:

1. One-time access promocodes that grant monthly access.
2. Reusable discount promocodes that reduce the amount on a real payment order.

These categories should share validation, audit, and admin tooling where practical, but they should not be treated as the same financial event. Access grants are operational grants. Discount codes are payment-order modifiers. Neither should create fake provider payments.

## Existing Promo And Access Code

### User-facing promo entry

- `src/diet_bot/telegram_app.py`
  - Start menu includes a "promo code" button through `PROMO_CODE_TEXT` and `CALLBACK_PROMO_CODE`.
  - `_start_promo_code_request()` puts the chat into `PROMO_CODE_REQUEST_CHAT_IDS`.
  - `_handle_promo_code_request()` accepts the next text message and calls `_activate_promo_code_for_chat()`.
  - On success, the bot sends the subscriber cabinet.
  - In Postgres mode, activation delegates to `store.activate_promo_code(chat_id, promo_code)`.
  - In JSON mode, activation uses `promo_codes.activate_promo_code()` and then calls `apply_subscription_payment(entitlement, f"promo:{code}")`.

### Promo model and JSON fallback

- `src/diet_bot/promo_codes.py`
  - Has `PromoCodeRecord` with only `used_by_chat_id` and `used_at`.
  - Has `PromoCodeActivation` with statuses `activated`, `not_found`, and `already_used`.
  - `activate_promo_code()` is one-time only: first redeemer wins, later attempts return `already_used`.
  - `generate_promo_codes()` creates unique `FB-AAAA-BBBB-CCCC` style codes.
  - There is no kind, validity window, max uses, discount value, target user, admin metadata, or audit metadata in the JSON model.

### Storage contract

- `src/diet_bot/storage.py`
  - `DietBotStore` exposes `upsert_promo_code()` and `activate_promo_code()`.
  - The protocol has no methods for creating rich promo definitions, listing codes, disabling codes, applying a discount to an order, reserving a promo use, or releasing an expired reservation.

### Postgres promo storage

- `src/diet_bot/postgres_migrations.py`
  - `promo_codes` exists with `code`, `kind`, `value`, `max_uses`, `used_count`, `valid_from`, `valid_until`, `is_active`, and `created_at`.
  - `kind` currently allows `subscription_month`, `extra_one_day`, `extra_weekly_pdf`, and `test_access_days`.
  - `promo_redemptions` exists with `promo_code_id`, `user_id`, `redeemed_at`, and `UNIQUE(promo_code_id, user_id)`.
  - Index `idx_promo_redemptions_user` exists.

- `src/diet_bot/postgres_store.py`
  - `upsert_promo_code()` imports/upserts simple monthly access codes as `subscription_month`, `value=1`, `max_uses=1`.
  - `activate_promo_code()` is transactional, selects the promo row `FOR UPDATE`, checks active dates, checks duplicate redemption for that user, checks `max_uses`, inserts a redemption, increments `used_count`, applies the grant, updates entitlement, and writes an entitlement snapshot.
  - `_apply_promo_grant_cur()` supports:
    - `subscription_month`: applies monthly access for `value` months.
    - `extra_one_day`: adds `value` extra one-day attempts.
    - `extra_weekly_pdf`: adds `value` extra weekly PDF attempts.
    - `test_access_days`: grants test access for `value` days.

### Entitlements

- `src/diet_bot/subscriptions.py`
  - `apply_subscription_payment()` sets `subscription_period_start`, `subscription_period_end`, `MONTHLY_ONE_DAY_LIMIT`, and `MONTHLY_WEEKLY_PDF_LIMIT`.
  - Existing monthly access semantics match the target one-month access grant.
  - The helper currently records promo grants as synthetic charge ids such as `promo:<code>` in `processed_payment_charge_ids`.

### Payment order and event model

- `src/diet_bot/payments.py`
  - `PaymentOrder` stores provider, product, amount, currency, status, nonce payload, invoice link, and pre-checkout approval time.
  - `build_payment_invoice_metadata()` requires the order amount/currency to match the production catalog exactly.
  - `validate_payment_pre_checkout()` and `apply_successful_payment()` validate order id, nonce, user, delivery chat, provider, product, amount, currency, expiration, and duplicate charge aliases.
  - `payment_events` and `processed_provider_charges` are for real provider/admin payment events.
  - There is no promo or discount metadata on `PaymentOrder`.
  - There is no discounted amount calculation path.

### Admin and support flows

- `src/diet_bot/telegram_app.py`
  - `/330366` is an admin/test-access command for granting, revoking, enabling, and disabling test access.
  - `/payment_event` supports admin reconciliation for refunds, chargebacks, subscription cancellation, orphan success reconciliation, pending reversal reconciliation, and ignored events.
  - Support request flow records `support_state` and redacts payment-sensitive support text.
  - There is no admin command to create, list, inspect, disable, or audit promo codes.
  - There is no support/admin lookup command for "why did this promo fail?".

## Existing Tests

- `tests/test_promo_codes.py`
  - Covers generation uniqueness, one-time JSON activation, unknown codes, and hyphenless normalization.

- `tests/test_telegram_app_photos.py`
  - Covers the promo button prompt and JSON fallback activation granting monthly subscription.

- `tests/test_postgres_store.py`
  - Covers Postgres promo redemption as one redemption per user, `max_uses`, and monthly access grant.
  - Covers payment order creation/reuse, successful payment idempotency, support state, and entitlement persistence.

- `tests/test_postgres_migrations.py`
  - Asserts required paid storage tables and indexes, including `promo_codes` and `promo_redemptions`.

- `tests/test_payments_model.py`
  - Covers order nonce payloads, invoice metadata, pre-checkout validation, successful-payment application, duplicate protection, redaction, reversals, and reconciliation.

- `tests/test_storage_contract.py`
  - Ensures the store protocol exposes promo activation plus payment and support methods.

- `tests/test_json_to_postgres_migration.py`
  - Imports legacy promo codes and intentionally sanitizes paid entitlement state in limited non-payment migration mode.

## Gap Analysis Against Target Behavior

### One-time monthly access promo

Already present:

- User can enter a promo code from the start menu.
- JSON fallback supports one-time code activation and monthly entitlement grant.
- Postgres supports durable monthly promo grants with `max_uses`, `valid_from`, `valid_until`, `is_active`, row locking, and per-user redemption uniqueness.
- Postgres can already model one code with `max_uses=1`, `kind='subscription_month'`, and `value=1`.

Missing or weak:

- No rich Python promo model for Postgres fields. The public dataclass only knows `used_by_chat_id` and `used_at`.
- No admin creation/listing/disable command.
- No explicit entitlement event with `source='promo'`, promo id, code hash, admin actor hash, or reason. Current Postgres activation writes a generic entitlement snapshot.
- No user-targeted restriction, such as "this code can only be redeemed by user 123".
- No reusable support lookup: admins cannot ask the bot for code status, redemptions, max uses, dates, or failure reason.
- JSON fallback cannot represent valid windows, max uses greater than one, multiple kinds, target users, or discount behavior.
- Current promo grant uses `processed_payment_charge_ids` with `promo:<code>`. That works for duplicate protection inside the old entitlement shape, but it blurs promo grants with provider payment charge history.

### Reusable discount promo

Already present:

- Payment orders are durable and validated by nonce, user, delivery chat, provider, product, amount, and currency.
- Payment events and processed charge aliases are durable and idempotent.
- Postgres promo tables have some reusable-code primitives: `max_uses`, `used_count`, validity windows, active flag, and redemptions.

Missing:

- No discount promo kind, discount amount/percent fields, product/provider/currency applicability fields, minimum amount, or max discount cap.
- No payment-order fields for `promo_code_id`, `promo_redemption_id`, `list_amount`, `discount_amount`, final amount provenance, or order metadata.
- `build_payment_invoice_metadata()` rejects any order amount that differs from the fixed catalog amount, so a discounted order cannot currently produce an invoice.
- YooKassa receipt provider data is built from the catalog amount, not a discounted final amount.
- No UX or command path applies a discount code before creating an invoice.
- No reservation lifecycle. If a discount is counted only after payment success, max-use codes can oversubscribe during concurrent pending checkouts. If counted at order creation, unpaid orders can burn codes unless reservations are released.
- Current `UNIQUE(promo_code_id, user_id)` means the default model is one use per user per code. That is good for safety, but it does not support "same user can use this reusable discount many times" without a migration.

### Restrictions

Already present:

- Postgres has `valid_from`, `valid_until`, `is_active`, `max_uses`, `used_count`.
- Postgres has per-user duplicate prevention through `UNIQUE(promo_code_id, user_id)`.

Missing:

- Target user or allowlist restriction.
- Per-user max uses greater than one.
- Product/provider/currency restrictions for discount codes.
- Minimum order amount and max discount cap.
- Reservation expiration/release for discount codes.
- Admin-visible reasons and notes.

### Audit and events

Already present:

- Payment events are append-only-ish and redacted for provider/admin payment events.
- Entitlement events exist and are used for generation consumption/refunds and snapshots.
- Support state exists without raw support message storage.

Missing:

- Explicit `promo_created`, `promo_disabled`, `promo_reserved`, `promo_redeemed`, `promo_released`, and `promo_grant_applied` audit records.
- Admin actor hashing/redaction for promo admin actions.
- Link from promo redemption to entitlement event for access grants.
- Link from discount redemption to payment order and successful payment event.
- Clear separation between provider charges and promo/admin grants.

### Security against repeat use

Already present:

- JSON one-time activation marks the code as used.
- JSON activation is guarded with `json_storage_transaction()` in Telegram fallback.
- Postgres activation locks the promo row, checks `max_uses`, checks per-user redemption, inserts redemption, and increments `used_count` inside one transaction.
- Payment success is idempotent by provider charge aliases and paid order state.

Missing:

- Discount reservation idempotency and release.
- Final successful-payment validation that the discounted final amount matches immutable order discount metadata.
- Admin tooling that never displays full sensitive identifiers when a code fails or is inspected.
- Target-user enforcement for access codes if product needs invite-style codes.

## Storage And Migration Recommendations

### Access-only monthly promo

Strictly required schema changes: none for Postgres if the first implementation slice only uses:

- `promo_codes.kind='subscription_month'`
- `value=1`
- `max_uses=1`
- existing `valid_from`, `valid_until`, and `is_active`
- existing `promo_redemptions`

Recommended before launch:

- Add an explicit promo audit event path, either by using `entitlement_events` with clear `event_type='grant'`/`source='promo'` metadata or by adding a small `promo_events` table.
- Add admin metadata fields if audit must answer who created/disabled a code:
  - `created_by_admin_hash`
  - `disabled_at`
  - `disabled_by_admin_hash`
  - `admin_note` or `metadata_json`
- Add optional `target_user_id` only if product needs single-user invite codes. If not, avoid it in the first slice.

JSON fallback:

- Do not expand JSON into the final production promo engine.
- Keep it as local/dev compatibility for legacy one-time monthly codes only.

### Reusable discount promo

Schema changes are required. The current payment order model cannot safely represent a discounted invoice.

Recommended minimal migration:

- Extend `promo_codes`:
  - allow discount kind, for example `discount_percent` and/or `discount_amount`.
  - add `applies_to_product TEXT`, nullable for all current payment products or fixed to `subscription_month` for first slice.
  - add `applies_to_provider TEXT`, nullable if both Stars and YooKassa are allowed.
  - add `currency TEXT`, nullable for percent discounts; required for fixed amount discounts.
  - add `max_discount_amount INTEGER`, nullable.
  - add `min_order_amount INTEGER`, nullable.
  - add `metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb`.

- Extend `payment_orders`:
  - `promo_code_id BIGINT REFERENCES promo_codes(id) ON DELETE SET NULL`
  - `list_amount INTEGER`
  - `discount_amount INTEGER NOT NULL DEFAULT 0`
  - `metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb`
  - keep `amount` as the final provider amount charged by Telegram.

- Extend `promo_redemptions` for discount lifecycle:
  - `order_id TEXT REFERENCES payment_orders(order_id) ON DELETE SET NULL`
  - `status TEXT NOT NULL DEFAULT 'redeemed'` with values like `reserved`, `redeemed`, `released`
  - `discount_amount INTEGER`
  - `metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb`

Unique constraint policy:

- Keep one use per user per code for the first discount slice unless product explicitly needs repeat use by the same user.
- If repeat use by the same user is required, replace or augment `UNIQUE(promo_code_id, user_id)` with an order-based unique key and a separate per-user-limit enforcement query. That is a bigger migration and should be its own slice.

Reservation policy:

- Reserve a discount use when creating the pending payment order.
- Store the reservation on the payment order.
- Convert reservation to `redeemed` only inside the successful-payment transaction.
- Release reservations when the order expires or invoice creation fails.
- Never grant access from the discount itself; access still comes from the successful provider payment for the discounted order.

## Telegram And Admin Commands Needed

Keep the user-facing command surface small:

- Existing "enter promo code" flow can continue to redeem access codes.
- For discount codes, the same text entry can detect a discount code and route the user to the relevant payment options with the discount attached to the next order, but this should be a later Telegram slice.

Admin commands recommended:

- `/promo create_access <code|auto> [months=1] [max_uses=1] [valid_until=YYYY-MM-DD] [note]`
- `/promo create_discount <code|auto> <percent|amount> [product=subscription_month] [provider=any] [max_uses] [valid_until=YYYY-MM-DD] [note]`
- `/promo list [active|inactive|expired|access|discount]`
- `/promo show <code>`
- `/promo disable <code> [reason]`

Support/admin lookup requirements:

- Show code status, kind, value, validity window, max uses, used count, and recent redemption count.
- For discount codes, show linked order ids in shortened form and final redemption status.
- Redact or hash admin actor ids and any sensitive payment/support payload.
- Do not expose full provider charge ids, bot tokens, provider tokens, database URLs, emails, phone numbers, or receipt/customer payloads.

## Tests Needed

Storage/model:

- Promo model normalizes codes and validates access vs discount kinds.
- Postgres migrations include new columns/checks/indexes and are idempotent.
- Monthly access code with `max_uses=1` grants exactly one month and monthly limits.
- Monthly access code with `valid_until` expired returns `not_found` or a precise inactive/expired status without granting.
- Same user replay and different user replay after exhaustion are no-ops.
- Optional target-user restriction rejects non-target users if that field is added.

Discount application:

- Discount code computes final amount from catalog amount and stores list amount plus discount amount immutably on the payment order.
- Discount percent/fixed amount never makes final amount negative or zero.
- Discount code rejects wrong product/provider/currency/min amount.
- Pending order reuse preserves the same promo metadata and does not double-reserve.
- Expired or failed invoice creation releases the reservation.
- Successful payment converts reservation to redeemed and increments used count once.
- Duplicate successful payment does not increment used count, does not create a second redemption, and does not grant access twice.
- Wrong user/chat/amount/currency/provider still rejects against the discounted order.

Admin/Telegram:

- Admin-only guard for `/promo` commands.
- Create/list/show/disable happy paths.
- Non-admin attempts are rejected.
- User access-code flow still grants monthly access.
- Discount-code user flow creates or attaches a discounted pending order only after the user chooses a paid product/provider.
- Support lookup redacts sensitive fields.

Migration:

- Legacy JSON promo import continues to import one-time monthly codes.
- Limited migration still does not import paid entitlement state as provider payments.
- New discount fields are absent from legacy JSON import unless explicitly provided by an admin/storage path.

Smoke:

- Local targeted unit tests for promo model, Postgres store, payment model, and Telegram command parsing.
- Staging DB smoke for access code redemption and discount payment order creation.
- Provider payment smoke only after discounted orders are implemented and configured in a production-like environment.

## Small Implementation Slices

### Slice 1: Storage/model foundation

Goal: make the promo domain explicit without changing user behavior.

Files likely touched:

- `src/diet_bot/promo_codes.py`
- `src/diet_bot/storage.py`
- `src/diet_bot/postgres_migrations.py`
- `src/diet_bot/postgres_store.py`
- `tests/test_promo_codes.py`
- `tests/test_postgres_migrations.py`
- `tests/test_postgres_store.py`
- `tests/test_storage_contract.py`

Work:

- Add richer promo dataclasses/enums for access and discount definitions.
- Add store methods for create/list/show/disable or keep them internal until admin slice.
- Add explicit promo grant audit for access grants.
- Decide whether access-only launch needs admin metadata columns now or in the admin slice.

Exit criteria:

- Existing one-time monthly activation behavior is unchanged.
- Postgres promo activation has explicit audit metadata.
- No discount payment behavior yet.

### Slice 2: One-time monthly access redemption

Goal: product-ready one-time monthly access codes.

Files likely touched:

- `src/diet_bot/postgres_store.py`
- `src/diet_bot/telegram_app.py`
- `tests/test_postgres_store.py`
- `tests/test_telegram_app_photos.py`

Work:

- Use `kind='subscription_month'`, `value=1`, `max_uses=1`.
- Ensure activation writes a clear promo grant event.
- Keep JSON fallback legacy-only.
- Add tests for active/expired/inactive/exhausted paths.

Exit criteria:

- Redeeming the code grants one 30-day access period with monthly limits.
- Replaying the same code by same or different user cannot extend access.
- Promo grant is auditable without a fake provider payment event.

### Slice 3: Reusable discount application to payment order

Goal: apply a discount code to a real payment order while preserving payment idempotency.

Files likely touched:

- `src/diet_bot/promo_codes.py`
- `src/diet_bot/payments.py`
- `src/diet_bot/postgres_migrations.py`
- `src/diet_bot/postgres_store.py`
- `src/diet_bot/telegram_app.py`
- `tests/test_payments_model.py`
- `tests/test_postgres_store.py`
- `tests/test_postgres_migrations.py`

Work:

- Add discount kind and discount calculation.
- Add immutable promo metadata to payment orders.
- Allow invoice metadata to use the discounted final amount while still validating catalog list amount and discount provenance.
- Reserve discount use at pending order creation.
- Convert reservation to redeemed inside successful-payment transaction.
- Release reservations for expired/failed invoice orders.

Exit criteria:

- Discounted order has a nonce payload like all other orders.
- Pre-checkout validates the discounted final amount.
- Successful payment grants access from the paid order, not from the promo code.
- Duplicate successful payment is a no-op for both entitlement and promo use count.

### Slice 4: Admin creation and listing

Goal: let admins safely operate promos without direct DB edits.

Files likely touched:

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/storage.py`
- `src/diet_bot/postgres_store.py`
- `tests/test_telegram_app_runtime.py`
- `tests/test_postgres_store.py`

Work:

- Add `/promo create_access`, `/promo create_discount`, `/promo list`, `/promo show`, and `/promo disable`.
- Reuse existing admin guard pattern from `/payment_event`.
- Store hashed/redacted admin actor metadata.
- Keep command responses short and redacted.

Exit criteria:

- Non-admin users cannot operate promo commands.
- Admin can create, inspect, and disable both access and discount codes.
- Listing shows enough operational state to support users without leaking sensitive payment data.

### Slice 5: Smoke checklist and release notes

Goal: add manual evidence steps before using codes in production.

Files likely touched:

- `docs/RELEASE_SMOKE_CHECKLIST.md`
- `docs/checklists/PAYMENT_SMOKE_NOTES.md` or a new promo smoke notes file

Work:

- Add access-code smoke:
  - create code.
  - redeem once.
  - verify entitlement, redemptions, audit event.
  - replay same code and verify no-op.
  - try expired/disabled code.
- Add discount-code smoke:
  - create code.
  - apply to subscription order.
  - verify invoice amount and order metadata.
  - complete provider test payment.
  - verify successful payment event, processed charge, entitlement, and promo redemption.
  - replay successful payment update and verify no-op.

Exit criteria:

- Promo smoke can be run without touching PDF, recipe quality, or unrelated Telegram UX.
- Evidence instructions are redaction-safe.

## Recommended Order

1. Ship access-only monthly promo hardening first because Postgres already has most of the schema and behavior.
2. Add admin create/list/show/disable for access codes before giving codes to real users.
3. Add discount storage/order metadata next, because discounts require payment-order changes and must be validated with payment idempotency.
4. Add discount Telegram flow last, after the storage and payment invariants are tested.
5. Update smoke docs only after the implementation exists and the exact commands are known.

## Highest Risks

- Treating a discount as an entitlement grant would bypass provider payment validation.
- Counting discount use only after payment success can oversubscribe max-use codes during concurrent pending orders.
- Counting discount use before payment without release can burn codes on abandoned or failed invoices.
- Letting discounted orders bypass catalog validation can allow tampered amounts.
- Keeping promo grants in `processed_payment_charge_ids` makes audit and provider charge idempotency harder to reason about.
- Adding broad Telegram UX changes before storage/payment invariants are tested would increase blast radius.
