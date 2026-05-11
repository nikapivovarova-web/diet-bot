# PostgreSQL State Storage Design

## Goal

Move bot runtime state out of JSON files and into PostgreSQL so subscriptions, profiles, promo codes, payment processing, and generation limits are handled with transactions, row locks, unique constraints, and explicit failures.

## Runtime Mode

The bot reads `DIET_BOT_DATABASE_URL`. When it is set, the bot uses PostgreSQL only. JSON files are not used as a runtime fallback because fallback reads can hide migration mistakes and corrupt production state.

The existing JSON path remains available only when `DIET_BOT_ALLOW_JSON_STORAGE=1` and `DIET_BOT_DATABASE_URL` is absent. It is for local development and existing tests, not deployment. Production deployment must set the database URL and leave JSON storage disabled.

## Tables

- `users`: Telegram user identity and last-seen metadata.
- `chat_state`: lightweight conversation/history state, stored as JSONB.
- `user_profiles`: saved questionnaire profile, stored as JSONB for now.
- `entitlements`: current subscription, trial, test-access, and separate one-day/weekly PDF balances.
- `entitlement_events`: audit trail for payments, promo codes, manual grants, generation consumption, and refunds.
- `processed_payment_charges`: idempotency table with `UNIQUE(provider, charge_id)`.
- `promo_codes`: promo definition, type, value, usage limit, validity window, and active flag.
- `promo_redemptions`: per-user promo activations with `UNIQUE(promo_code_id, user_id)`.
- `meal_plans`: generation records with `generating`, `completed`, or `failed` status.

## Critical Transactions

Promo activation:

1. Lock the promo code row with `FOR UPDATE`.
2. Validate active flag, dates, and usage limit.
3. Insert a redemption with a unique `(promo_code_id, user_id)` constraint.
4. Increment `used_count`.
5. Lock/update the user entitlement.
6. Write an entitlement event.
7. Commit all changes together.

Payment processing:

1. Insert `(provider, charge_id)` into `processed_payment_charges`.
2. If the insert conflicts, return a duplicate result and do not grant anything.
3. Lock/update the entitlement for new payments only.
4. Write an entitlement event.
5. Commit.

Generation consumption:

1. Lock the entitlement row.
2. Expire stale subscription/test-access state if needed.
3. Consume the correct balance source.
4. Create a `meal_plans` row with status `generating` if access is allowed.
5. Write an entitlement event.
6. Commit.

Generation refund:

1. Lock the entitlement row.
2. Restore the consumed balance when applicable.
3. Mark the `meal_plans` row as `failed`.
4. Write an entitlement event.
5. Commit.

## Migration

Migration is an explicit one-time command:

```powershell
$env:DIET_BOT_DATABASE_URL = "postgresql://..."
.\.venv\Scripts\python.exe scripts\migrate_json_to_postgres.py
```

The migration reads `.diet_bot_state/history.json`, `subscriptions.json`, and `promo_codes.json`, writes them to PostgreSQL, and does not change the runtime bot behavior by itself. After migration, deployment should set `DIET_BOT_DATABASE_URL` and run the bot against PostgreSQL only.

## Testing

Unit tests keep covering the existing business rules. PostgreSQL integration tests use `DIET_BOT_TEST_DATABASE_URL` when available and are skipped otherwise. They cover duplicate payment idempotency, one-user-one-promo redemption, and transactional generation consumption/refund.
