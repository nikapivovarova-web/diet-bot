# Telegram Stars Subscription Limits Design

## Goal

Add real Telegram Stars monetization to the FoodBalance bot.

Users without a paid subscription should be able to generate exactly one free one-day ration. A paid monthly Stars subscription should refresh a fixed monthly package of ration-generation attempts. When the package is exhausted, users can either wait for the next subscription renewal or buy one extra ration attempt with Stars.

## Prices

- Monthly subscription: 400 Stars.
- Extra one-day ration: 35 Stars.
- Extra weekly PDF ration: 170 Stars.

These prices are intentionally rounded for clear button labels. The earlier project conversion used 599 RUB as roughly 402 Stars, so 50 RUB maps to about 35 Stars and 250 RUB maps to about 170 Stars.

## Access Model

Each Telegram user has an entitlement record.

The record tracks:

- Whether the free one-day trial ration has been used.
- Whether a paid subscription is active.
- Current subscription period start and end.
- Remaining monthly one-day attempts.
- Remaining monthly weekly-PDF attempts.
- Extra purchased one-day attempts.
- Extra purchased weekly-PDF attempts.
- Processed Telegram payment charge IDs, so repeated payment updates cannot grant limits twice.

Free users can generate one one-day ration for the lifetime of their account in this bot. Free users cannot generate weekly PDF rations.

A subscription is active only during the currently paid subscription period. If Telegram does not deliver a successful renewal payment for the next period, the bot should stop treating the user as subscribed after the stored period end.

Subscribed users receive a monthly package:

- 5 one-day ration attempts.
- 4 weekly PDF ration attempts.

Limits do not accumulate. When a new monthly subscription payment succeeds, the bot resets the subscription package to 5 one-day attempts and 4 weekly-PDF attempts. Unused attempts from the previous period expire.

Extra purchased attempts are separate from the monthly package. They are granted after a successful one-time Stars payment. Extra attempts are consumed only when the corresponding monthly subscription attempt is not available.

## Payment Flow

The existing Stars payment button should stop being a placeholder.

Pressing the monthly subscription button should create a Telegram Stars subscription invoice:

- Currency: `XTR`.
- Price: 400 Stars.
- Subscription period: 2,592,000 seconds, which is 30 days.
- Payload: stable internal payment code for the monthly subscription.

Telegram should handle the payment UI. The bot must approve valid pre-checkout queries and then process `successful_payment` updates.

After a successful monthly subscription payment, the bot should:

- Store the Telegram payment charge ID.
- Mark the subscription active.
- Set the current subscription period.
- Reset monthly limits to 5 one-day attempts and 4 weekly-PDF attempts.
- Tell the user that access is active and show the current remaining attempts.

When the user buys an extra one-day ration, the bot should send a one-time Stars invoice for 35 Stars and grant 1 extra one-day attempt after successful payment.

When the user buys an extra weekly PDF ration, the bot should send a one-time Stars invoice for 170 Stars and grant 1 extra weekly-PDF attempt after successful payment.

## Ration Generation Flow

Before generating a ration, the bot should check access.

For a one-day ration:

1. If the user is subscribed and has monthly one-day attempts, consume 1 monthly one-day attempt.
2. Otherwise, if the user has extra one-day attempts, consume 1 extra one-day attempt.
3. Otherwise, if the user has not used the free trial, consume the free trial and generate the ration.
4. Otherwise, block generation and show payment options.

For a weekly PDF ration:

1. If the user is subscribed and has monthly weekly-PDF attempts, consume 1 monthly weekly-PDF attempt.
2. Otherwise, if the user has extra weekly-PDF attempts, consume 1 extra weekly-PDF attempt.
3. Otherwise, block generation and show payment options.

The bot should consume the attempt only when it is about to start generation. If generation fails before producing a result because of an internal error, the implementation should restore the consumed attempt where practical.

## User Messages

After every successful ration generation, the final message should include the remaining attempts.

Example:

```text
Осталось:
Рационы на 1 день: 4 из 5
PDF на неделю: 4 из 4
```

If the user has extra attempts, the message should include them as a separate line:

```text
Дополнительно куплено:
Рационы на 1 день: 1
PDF на неделю: 0
```

When a limit is exhausted, the bot should show a concise paywall message:

```text
Лимит для этого типа рациона закончился.

Осталось:
Рационы на 1 день: 0 из 5
PDF на неделю: 2 из 4

Следующее обновление подписки: 08.06.2026

Можно дождаться следующего обновления подписки или купить разовую попытку.
```

If the user does not have an active subscription, the next-renewal line should be omitted.

The paywall should include relevant buttons:

- Monthly subscription: 400 Stars.
- Buy 1 one-day ration: 35 Stars.
- Buy 1 weekly PDF ration: 170 Stars.

For one-day ration blocks, the one-day extra purchase button should be most prominent. For weekly-PDF blocks, the weekly extra purchase button should be most prominent.

## Storage

Use a small JSON state file next to the existing bot state:

```text
.diet_bot_state/subscriptions.json
```

This keeps the feature simple for the current MVP and avoids introducing a database before deployment details are settled.

The storage layer should be isolated behind helper functions so it can later be replaced with SQLite or Postgres without rewriting the Telegram handlers.

## Telegram API Notes

The Bot API Stars flow uses `XTR` as the currency. Digital goods can use an empty provider token. Stars subscription invoices support a 30-day subscription period through `subscription_period=2592000`.

The implementation should handle:

- `pre_checkout_query`.
- `successful_payment`.
- Invoice payload routing for subscription, extra one-day purchase, and extra weekly-PDF purchase.
- Duplicate payment updates by checking `telegram_payment_charge_id`.

## Testing

Add focused tests for:

- Free users can generate one one-day ration.
- Free users cannot generate a second one-day ration without paying.
- Free users cannot generate weekly PDF rations.
- A successful monthly subscription payment resets limits to 5 one-day attempts and 4 weekly-PDF attempts.
- Monthly limits do not accumulate across renewal payments.
- A one-day ration consumes one one-day attempt and reports the remaining count.
- A weekly PDF ration consumes one weekly-PDF attempt and reports the remaining count.
- Extra one-day purchase grants exactly one extra one-day attempt.
- Extra weekly purchase grants exactly one extra weekly-PDF attempt.
- Duplicate successful payment updates do not grant limits twice.
- Exhausted limits show the correct paywall buttons and prices.
