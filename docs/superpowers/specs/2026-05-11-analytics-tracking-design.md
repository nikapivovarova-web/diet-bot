# Analytics Tracking Design

## Context

FoodBalance already stores production-critical state in PostgreSQL: users,
profiles, entitlements, payment orders, payment events, promo codes, and meal
generation records. The bot also has Telegram-native payment handling for Stars
and YooKassa/card payments.

The next analytics layer should make product behavior visible without making
analytics a dependency for core bot flows. Payments, subscriptions, refunds, and
entitlements must continue to be counted from the PostgreSQL payment/subscription
state, not from button clicks or external analytics events.

## Approach

Use a hybrid setup:

- PostHog for visual product analytics, funnels, cohorts, and dashboards.
- PostgreSQL `analytics_events` for a first-party archive of important product
  events.

PostHog gives the operator convenient charts for user behavior. PostgreSQL keeps
an auditable copy of the important events and allows later Metabase dashboards
without losing historical data if the external analytics provider changes.

## Configuration

Analytics is optional and controlled by environment variables:

- `DIET_BOT_ANALYTICS_ENABLED`: enables analytics when set to `1`.
- `POSTHOG_API_KEY`: PostHog project API key.
- `POSTHOG_HOST`: optional PostHog host, defaulting to `https://app.posthog.com`.

If analytics is disabled or PostHog is not configured, the bot must keep working.
Missing analytics config is not a healthcheck failure for the current MVP.

## PostgreSQL Storage

Add an `analytics_events` table:

- `id BIGSERIAL PRIMARY KEY`
- `user_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL`
- `event_name TEXT NOT NULL`
- `properties_json JSONB NOT NULL DEFAULT '{}'::jsonb`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Add indexes for common dashboard queries:

- `(event_name, created_at DESC)`
- `(user_id, created_at DESC)`

The table stores only product analytics metadata. It must not store full message
text, medical free-text answers, Telegram tokens, payment provider raw payloads,
or secrets.

## Event Client

Add a small analytics module with one main API:

```python
track_event(user_id: int | None, event_name: str, properties: dict[str, object] | None = None) -> None
```

The function should:

1. Normalize properties into a JSON-safe dictionary.
2. Store the event in PostgreSQL when a PostgreSQL store is active.
3. Send the event to PostHog when analytics is enabled and the API key is set.
4. Swallow and log analytics failures so user-facing flows do not fail.

PostHog calls can be implemented with the Python standard library HTTP client to
avoid adding a runtime dependency, or with the official package later if the
project needs richer PostHog features.

## Initial Events

Track only high-signal events at first:

- `bot_started`
- `questionnaire_started`
- `questionnaire_completed`
- `plan_requested`
- `weekly_pdf_requested`
- `paywall_shown`
- `checkout_started`
- `invoice_created`
- `payment_succeeded`
- `payment_failed`
- `promo_redeemed`
- `support_requested`

Do not track every user message. That would waste analytics quota and create
privacy risk without adding useful business insight.

## Event Properties

Use compact, non-sensitive properties:

- `source`: command, callback, keyboard, or payment handler.
- `product`: subscription, extra one-day ration, or extra weekly PDF.
- `provider`: Telegram Stars, YooKassa, or another provider identifier.
- `amount`: payment amount in the smallest currency unit when relevant.
- `currency`: payment currency when relevant.
- `ration_kind`: one-day or weekly PDF when relevant.
- `result`: success, failure, duplicate, ignored, or blocked when relevant.
- `reason`: short internal reason code when relevant.

Do not include questionnaire answers, generated plan contents, support message
contents, card details, provider raw payloads, or personally sensitive health
details.

## Integration Points

Track events from existing Telegram flow boundaries:

- `/start`: `bot_started`
- Questionnaire consent/start: `questionnaire_started`
- Completed questionnaire: `questionnaire_completed`
- One-day ration request: `plan_requested`
- Weekly PDF request: `weekly_pdf_requested`
- Limit/payment prompt: `paywall_shown`
- Payment button click before invoice creation: `checkout_started`
- Successful invoice link creation: `invoice_created`
- Invoice creation exception or failed order marking: `payment_failed`
- `successful_payment` after entitlement application: `payment_succeeded`
- Promo activation success: `promo_redeemed`
- Support request start: `support_requested`

Payment revenue dashboards should still read from payment tables and entitlement
state. Analytics events are used for product funnels and operational visibility.

## Privacy And Reliability

Analytics is best-effort. A PostHog timeout, network error, invalid API key, or
database insert failure must be logged but must not block:

- sending bot messages,
- creating invoices,
- answering pre-checkout queries,
- applying successful payments,
- granting subscription access.

Properties should be allowlisted by the call site or sanitized centrally. The
implementation should prefer short codes over user-provided text.

## Dashboard Plan

PostHog dashboards should start with:

- New users by day from `bot_started`.
- Questionnaire funnel: `bot_started -> questionnaire_started -> questionnaire_completed`.
- Purchase funnel: `bot_started -> checkout_started -> invoice_created -> payment_succeeded`.
- Paywall conversion by `ration_kind`.
- Payment success by `product` and `provider`.

Later, Metabase can connect directly to PostgreSQL for finance-oriented
dashboards:

- real paid orders by day,
- active subscriptions,
- monthly revenue,
- refunds and chargebacks,
- promo-code conversion.

## Tests

Add focused tests for:

- PostgreSQL schema creates `analytics_events`.
- Recording an analytics event inserts a row without sensitive fields.
- Analytics disabled mode does nothing externally.
- PostHog failures are logged and swallowed.
- Key Telegram flows call analytics without changing existing user-facing
  behavior.
