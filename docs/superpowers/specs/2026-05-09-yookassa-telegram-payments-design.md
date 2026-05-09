# YooKassa Telegram Payments Design

## Context

FoodBalance already has a Telegram payment flow built on aiogram. Telegram Stars invoices are generated with `create_invoice_link`, and successful payments grant the existing subscription or extra attempt entitlements. Ruble payment buttons exist, but currently show a pending message instead of creating a real YooKassa invoice.

YooKassa is now connected through Telegram Payments. Because receipt auto-sending may be enabled, the bot must request the payer email and send receipt data in `provider_data`.

## Approach

Use Telegram's native payments integration with YooKassa instead of direct YooKassa API calls. This keeps the checkout inside Telegram and lets the existing `pre_checkout_query` and `successful_payment` handlers remain the source of truth for granting access.

The bot will read the YooKassa provider token from `TELEGRAM_PROVIDER_TOKEN`. If the token is absent, ruble payment buttons will explain that card payment is not configured yet instead of creating a broken invoice.

## Products

The ruble products mirror the current paid access model:

- Monthly FoodBalance access: 599 RUB.
- One extra one-day ration: 50 RUB.
- One extra weekly PDF ration: 250 RUB.

Each product gets a dedicated `RUB` payload. The existing Stars payloads remain unchanged.

## Invoice Flow

When a user taps a ruble payment button, the bot creates a Telegram invoice link with:

- `currency="RUB"`.
- `prices` in kopecks.
- `need_email=True`.
- `send_email_to_provider=True`.
- `provider_token` from `TELEGRAM_PROVIDER_TOKEN`.
- `provider_data` containing `receipt.items`.

The bot sends a short product message and an inline URL button that opens the invoice in Telegram.

## Receipt Data

For each ruble product, `provider_data` includes one receipt item:

- `description`: product title.
- `quantity`: `1.00`.
- `amount.value`: product price in rubles with two decimal places.
- `amount.currency`: `RUB`.
- `vat_code`: `1`.
- `payment_mode`: `full_payment`.
- `payment_subject`: `service`.

The invoice price remains in kopecks, while receipt amount remains in rubles.

## Validation

`pre_checkout_query` must answer within Telegram's 10 second limit. It will accept a payment only when:

- The payload is recognized.
- The currency matches the payload family: `XTR` for Stars, `RUB` for YooKassa.
- The total amount exactly matches the configured amount in the smallest currency unit.

Unknown payloads, wrong currencies, and wrong amounts are rejected with a user-facing retry message.

## Successful Payment Handling

Successful payments continue through the existing entitlement application path:

- Monthly access resets monthly limits.
- Extra one-day ration adds one extra one-day attempt.
- Extra weekly PDF adds one extra weekly PDF attempt.

The same duplicate protection remains in place through stored Telegram charge IDs. YooKassa's provider charge ID is not required for granting access because Telegram sends `successful_payment` only after successful checkout.

## Error Handling

If `TELEGRAM_PROVIDER_TOKEN` is missing, ruble payment attempts send a configuration message and leave Stars available.

If invoice creation fails with a Telegram API error, the bot tells the user that the invoice could not be created and suggests trying again later.

## Tests

Add or update tests for:

- Ruble payment buttons creating invoice links instead of pending text.
- Provider token, currency, prices, email flags, and receipt `provider_data`.
- Pre-checkout validation for valid and invalid `RUB` payments.
- Existing Stars invoice behavior remaining unchanged.
