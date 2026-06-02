# Stage 19.2 Promo Store Hardening Design

## Current Risk

External audit H-1 is valid. `src/diet_bot/promo_codes.py` currently stores promo definitions and use state in a mutable JSON file. `save_promo_codes()` serializes the whole registry and writes it with `path.write_text()`. There is no temp file, `fsync`, directory `fsync`, process lock, or atomic replace. `load_promo_codes()` catches `OSError` and `json.JSONDecodeError` and returns `{}`, so a torn or corrupt write can make the runtime behave as if all valid and used promo records disappeared.

The risk is worse than a local file durability issue because promo state is outside the existing Postgres backup, restore-drill, migration, and preflight path. Current Telegram wiring uses the JSON store for:

- `/promo` monthly-access activation;
- `/330366` admin creation of one-month access codes;
- `/330366` admin create/list/disable for discount promos;
- rollback after entitlement grant failure by writing JSON again.

The current monthly promo grant is split across two stores: JSON is marked used first, then `EntitlementService.apply_subscription_payment()` grants access. If the entitlement grant fails, Telegram attempts `release_promo_code_activation()` as a best-effort rollback. This is not atomic across promo use and entitlement grant.

Discount promo definitions exist, but user activation rejects discount codes as `not_access_code`, and payment orders do not yet carry promo metadata. Stage 18 wants `FOOD20`, so sending or enabling that offer before H-1 is fixed would create a launch-visible code backed by unsafe state.

## Recommendation

Use a Postgres-backed promo runtime for production. JSON should become either an import seed or a local/dev fallback only. The recommended design is option C with option B as the production runtime:

- Production: Postgres `promo_codes` and `promo_redemptions` tables, schema validation, migrations, preflight gate, backup/restore-drill inclusion, and transactional activation/payment integration.
- Transition: import existing JSON into Postgres with a strict importer that fails on corrupt input and never deletes existing Postgres promo rows.
- Local/dev fallback: keep JSON only for isolated tests or developer runs. If JSON remains writable, harden it with temp file, file `fsync`, `os.replace`, and directory `fsync`, but do not treat this as production mitigation.

Compared options:

- A. Minimal atomic JSON hardening reduces torn-write risk for local/dev, but promo state still remains outside Postgres DR and cannot be transactionally coupled to entitlement or payment grants. It is not sufficient for `FOOD20` launch.
- B. Postgres promo store solves DR, concurrency, idempotency, and auditability. It is the right production target.
- C. Hybrid transition keeps migration risk low: JSON is preserved as a seed/source for import and as a dev fallback, while production uses Postgres only.

This should be a fail-closed change. In production, if promo features are enabled and the promo store is not Postgres-ready, startup/preflight should fail before the bot can accept `/promo` or admin promo actions.

## Schema

Add a promo migration module following the existing `postgres_*_migrations.py` pattern. Proposed first migration version: `202605300001`.

`promo_codes`

```sql
CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    discount_type TEXT,
    discount_percent INTEGER,
    discount_amount_minor INTEGER,
    monthly_duration_months INTEGER NOT NULL DEFAULT 1,
    max_uses INTEGER NOT NULL DEFAULT 1,
    per_user_limit INTEGER NOT NULL DEFAULT 1,
    available_from TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    campaign_key TEXT,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at TIMESTAMPTZ,
    disabled_by BIGINT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT chk_promo_codes_code_non_empty CHECK (code <> ''),
    CONSTRAINT chk_promo_codes_kind CHECK (kind IN ('monthly_access', 'discount')),
    CONSTRAINT chk_promo_codes_status CHECK (status IN ('active', 'disabled')),
    CONSTRAINT chk_promo_codes_discount_type CHECK (
        discount_type IS NULL OR discount_type IN ('percent', 'amount')
    ),
    CONSTRAINT chk_promo_codes_discount_shape CHECK (
        (
            kind = 'monthly_access'
            AND discount_type IS NULL
            AND discount_percent IS NULL
            AND discount_amount_minor IS NULL
            AND monthly_duration_months >= 1
        )
        OR (
            kind = 'discount'
            AND monthly_duration_months = 1
            AND (
                (discount_type = 'percent'
                 AND discount_percent BETWEEN 1 AND 90
                 AND discount_amount_minor IS NULL)
                OR
                (discount_type = 'amount'
                 AND discount_amount_minor > 0
                 AND discount_percent IS NULL)
            )
        )
    ),
    CONSTRAINT chk_promo_codes_limits CHECK (max_uses >= 1 AND per_user_limit >= 1),
    CONSTRAINT chk_promo_codes_window CHECK (
        expires_at IS NULL OR available_from IS NULL OR expires_at > available_from
    )
)
```

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_promo_codes_active_kind
    ON promo_codes(kind, code)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_promo_codes_campaign_key
    ON promo_codes(campaign_key)
    WHERE campaign_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_promo_codes_expires_at
    ON promo_codes(expires_at)
    WHERE expires_at IS NOT NULL;
```

`promo_redemptions`

This table represents both direct monthly-access redemption and discount offer/order/payment lifecycle. For the Stage 18 `FOOD20` 48-hour window, create an `offered` row when message 4 is sent, then transition it to `reserved` when a discounted order is created, and to `redeemed` only after the successful payment and entitlement grant transaction completes.

```sql
CREATE TABLE IF NOT EXISTS promo_redemptions (
    redemption_id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL REFERENCES promo_codes(code) ON DELETE RESTRICT,
    chat_id BIGINT NOT NULL,
    user_id BIGINT,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    offered_at TIMESTAMPTZ,
    reserved_at TIMESTAMPTZ,
    redeemed_at TIMESTAMPTZ,
    released_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    window_expires_at TIMESTAMPTZ,
    payment_order_id TEXT REFERENCES payment_orders(order_id) ON DELETE RESTRICT,
    payment_provider TEXT,
    payment_product TEXT,
    currency TEXT,
    original_amount_minor INTEGER,
    discount_amount_minor INTEGER,
    final_amount_minor INTEGER,
    entitlement_charge_id TEXT,
    campaign_key TEXT,
    campaign_step_key TEXT,
    telegram_message_id BIGINT,
    failure_reason TEXT,
    source TEXT NOT NULL DEFAULT 'runtime',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_promo_redemptions_status CHECK (
        status IN ('offered', 'reserved', 'redeemed', 'released', 'expired', 'failed')
    ),
    CONSTRAINT chk_promo_redemptions_idempotency_key_non_empty CHECK (idempotency_key <> ''),
    CONSTRAINT chk_promo_redemptions_amounts CHECK (
        (
            original_amount_minor IS NULL
            AND discount_amount_minor IS NULL
            AND final_amount_minor IS NULL
        )
        OR (
            original_amount_minor > 0
            AND discount_amount_minor > 0
            AND final_amount_minor > 0
            AND original_amount_minor = final_amount_minor + discount_amount_minor
        )
    ),
    CONSTRAINT chk_promo_redemptions_payment_provider CHECK (
        payment_provider IS NULL OR payment_provider IN ('telegram_stars', 'yookassa')
    ),
    CONSTRAINT chk_promo_redemptions_payment_status_shape CHECK (
        (payment_order_id IS NULL AND status IN ('offered', 'released', 'expired', 'failed', 'redeemed'))
        OR payment_order_id IS NOT NULL
    )
)
```

Recommended indexes and uniqueness rules:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_redemptions_idempotency_key_unique
    ON promo_redemptions(idempotency_key);

CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_redemptions_payment_order_unique
    ON promo_redemptions(payment_order_id)
    WHERE payment_order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_redemptions_entitlement_charge_unique
    ON promo_redemptions(entitlement_charge_id)
    WHERE entitlement_charge_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_redemptions_campaign_offer_unique
    ON promo_redemptions(code, chat_id, campaign_key)
    WHERE campaign_key IS NOT NULL
      AND status IN ('offered', 'reserved', 'redeemed');

CREATE INDEX IF NOT EXISTS idx_promo_redemptions_code_status
    ON promo_redemptions(code, status, created_at);

CREATE INDEX IF NOT EXISTS idx_promo_redemptions_chat_status
    ON promo_redemptions(chat_id, status, created_at);
```

Global `max_uses` and `per_user_limit` should be enforced inside a single transaction by locking the promo row:

```sql
SELECT *
FROM promo_codes
WHERE code = %s
FOR UPDATE;
```

After that lock, count `promo_redemptions` rows for the code and chat where `status IN ('reserved', 'redeemed')`. Because every redemption path locks the same `promo_codes` row first, concurrent activations cannot both pass the limit checks. The unique idempotency key prevents duplicate processing of the same request/order/message. The unique payment/order and entitlement-charge indexes prevent the same external grant from being attached to more than one redemption row.

`promo_import_runs`

```sql
CREATE TABLE IF NOT EXISTS promo_import_runs (
    migration_id TEXT PRIMARY KEY,
    source_fingerprint TEXT NOT NULL,
    source_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'started',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    CONSTRAINT chk_promo_import_runs_status CHECK (status IN ('started', 'applied', 'failed'))
)
```

Schema validation should use `PostgresSchemaExpectation`, covering all three tables, the migration version, indexes, and critical constraints.

## Migration / Import Existing JSON

Migration must be additive. It must not delete JSON files, truncate Postgres tables, or overwrite known used state.

Import strategy:

1. Add Postgres tables and validation first.
2. Create `scripts/migrate_promo_codes_json_to_postgres.py` modeled after `migrate_entitlements_json_to_postgres.py`, but with strict JSON parsing. Do not call `load_promo_codes()` for import because it silently returns `{}` on corrupt input.
3. Dry-run by default. Report source path, byte size, fingerprint, promo count, active/disabled count, discount count, monthly-access count, and used redemption count.
4. Apply only with `--apply`, `--migration-id`, expected source fingerprint, and expected counts.
5. Record the import in `promo_import_runs` with `source_fingerprint` and a result payload.
6. Upsert new promo definitions only when no conflicting Postgres row exists. If a code already exists with different material fields, fail and require an explicit operator decision. Do not delete Postgres-only promo rows.
7. Convert JSON `used_by_chat_id` and `used_at` to a `promo_redemptions` row with `status='redeemed'`, `source='json_import'`, and `entitlement_charge_id='promo:{CODE}'` for compatibility with existing entitlement duplicate guards.
8. Preserve `kind`, `active`, `max_redemptions`, `per_user_limit`, `expires_at`, `discount_percent`, `discount_amount`, and `monthly_duration_months`.

Corrupt, empty, non-object, or missing JSON must fail before opening a Postgres connection. A corrupt JSON import must never wipe or replace Postgres promo rows.

## Runtime Config / Production Gate

Add an explicit promo store runtime setting instead of inferring safety from `DIET_BOT_PROMO_CODES_STATE_FILE`.

Recommended config:

- `DIET_BOT_PROMO_STORE_BACKEND=postgres|json|memory`
- default `postgres` when `DIET_BOT_STORAGE_BACKEND=postgres`;
- default `json` only for local/dev JSON storage;
- `DIET_BOT_PROMO_FEATURES_ENABLED=1|0` if a separate global promo kill switch is desired;
- optional `DIET_BOT_PROMO_JSON_FALLBACK_ENABLED=1` for tests and local manual development only.

Production gate:

- production requires `DIET_BOT_PROMO_STORE_BACKEND=postgres`;
- production requires `DIET_BOT_DATABASE_URL`;
- `/promo`, `/330366` promo admin actions, discount order creation, and sales follow-up `FOOD20` must fail closed when the promo store schema is not valid;
- preflight must include a "promo schema" check and fail if promo features are enabled but the Postgres promo schema is absent;
- local unit tests may use JSON or in-memory stores, but production and controlled QA should use Postgres to exercise the real path.

Keep `DIET_BOT_PROMO_CODES_STATE_FILE` only as the JSON seed/fallback path. It must not be the production source of truth after this stage.

## Activation And Idempotency

Introduce a `PromoStore` interface with Postgres and JSON/dev implementations. Telegram should call the store/service interface, not `load_promo_codes()` and `save_promo_codes()` directly.

Monthly-access activation flow:

1. Normalize the code with the existing `normalize_promo_code()` behavior.
2. Open one Postgres transaction.
3. Lock the `promo_codes` row with `FOR UPDATE`.
4. Validate `status='active'`, `kind='monthly_access'`, `available_from`, `expires_at`, `max_uses`, and `per_user_limit`.
5. Check existing redemptions for the code and chat under the same promo row lock.
6. Lock entitlement state using the same advisory lock pattern already used by payment grant transactions.
7. Load the chat entitlement `FOR UPDATE`.
8. Insert the `promo_redemptions` row and apply the entitlement grant before commit.
9. Use a stable entitlement charge id. For migrated single-use codes, `promo:{CODE}` is acceptable. For new Postgres redemptions, prefer `promo:{CODE}:redemption:{redemption_id}` so future multi-use access codes cannot collide for the same chat.
10. Commit only if both redemption and entitlement grant succeed.

Use `apply_monthly_access_promo_grant()` rather than the current direct `apply_subscription_payment()` call so `monthly_duration_months` is honored and active subscriptions can be extended from the current subscription end instead of always resetting from now.

Idempotency outcomes:

- Same chat repeats an already redeemed monthly code: do not grant again; return a user-facing "already activated for this chat" result.
- Different chat tries a single-use redeemed code: return "already used".
- Disabled code: return "disabled".
- Expired code or expired per-chat campaign window: return "expired".
- Discount code entered through the monthly-access `/promo` path before discount order wiring: return "not an access code" with a clear prompt to use the payment flow once implemented.

Discount activation/payment flow:

1. Validate discount code and calculate discount with the same positive-final-amount rule as `calculate_discount_amount()`.
2. For `FOOD20`, require an active per-chat `offered` row whose `window_expires_at` is still in the future.
3. Create the payment order and reserve the promo redemption in one Postgres transaction. The payment order amount is the final amount after discount; the redemption row records original amount, discount amount, final amount, currency, product, provider, campaign key, and payment order id.
4. If Telegram invoice creation fails, mark the order failed and release the redemption.
5. On successful payment, extend `PostgresPaymentStore.record_successful_payment_and_grant_entitlement()` or an equivalent shared transaction so payment charge insertion, payment event recording, order state, entitlement grant, and `promo_redemptions.status='redeemed'` commit or roll back together.
6. Duplicate successful payment events should use the existing payment charge uniqueness and should not increment promo use or grant entitlement again.

## Admin Promo Menu Impact

`/330366` should keep the existing admin-facing capabilities, but all promo mutations must go through Postgres in production:

- create monthly access code: insert `promo_codes(kind='monthly_access', status='active', max_uses=1, per_user_limit=1, monthly_duration_months=1, created_by=<admin_user_id>)`;
- create/update discount promo: insert or update only `kind='discount'` rows, with percent 1-90 or a positive fixed amount, and `created_by`/`metadata_json` audit context;
- list discount promos: query active, unexpired Postgres discount rows, and include `max_uses`, current redeemed/reserved count, expiry, and campaign key;
- disable discount promo: set `status='disabled'`, `disabled_at=now()`, and `disabled_by=<admin_user_id>`;
- reject edits that attempt to change a monthly-access code through the discount flow or a discount code through the monthly-access generation flow.

Admin actions should return a clear storage-unavailable message if Postgres promo schema validation fails. They should never fall back to JSON in production.

## FOOD20 Campaign Decision

Do not enable `FOOD20` before this implementation is complete and verified.

Recommended campaign semantics:

- `FOOD20` is a discount promo: `kind='discount'`, `discount_type='percent'`, `discount_percent=20`, `per_user_limit=1`;
- the 48-hour validity should be per chat, starting when sales follow-up message 4 is successfully sent;
- represent that per-chat window as a `promo_redemptions` row with `status='offered'`, `campaign_key='free_trial_v1'`, `campaign_step_key='m04_three_days_food20'`, `offered_at=<send time>`, and `window_expires_at=<send time + 48 hours>`;
- optional global `promo_codes.expires_at` can cap the overall campaign, but it should not replace the per-chat 48-hour window promised by the message copy;
- payment order creation should fail with an expired-code message if the user tries to use `FOOD20` after their personal window expires.

This approach matches Stage 18 copy and avoids an ambiguous fixed campaign deadline where some users receive a "48 hours" message near the end of a global window.

## Tests

Required test coverage for 19.2B-19.2F:

- Postgres schema migration is idempotent and schema validation rejects missing promo tables, indexes, constraints, and migration versions.
- JSON import dry-run reports counts and fingerprint without connecting to Postgres.
- Corrupt, empty, missing, list-shaped, or scalar JSON import fails before any Postgres connection.
- JSON import preserves used state as `promo_redemptions.status='redeemed'`.
- Re-running the same import idempotently returns the recorded `promo_import_runs` result.
- Import with a conflicting existing Postgres promo row fails without modifying existing rows.
- Concurrent activation of the same single-use monthly code grants exactly one entitlement.
- Concurrent activation of a multi-use discount code respects `max_uses`.
- Used single-use code cannot be reused by another chat.
- Same chat retry after successful activation is idempotent and does not double grant.
- Expired and disabled promos are rejected.
- Discount code is not activated through the monthly-access `/promo` path.
- Discount code creates a payment order with final amount, original amount, discount amount, code, campaign key, and expiry metadata recorded in `promo_redemptions`.
- Duplicate successful payment events do not double redeem the promo or double grant entitlement.
- Payment/entitlement grant failure rolls back promo redemption status in the same transaction.
- Admin create/list/disable monthly and discount promos use Postgres and record admin audit fields.
- Production runtime/preflight fails when promo features are enabled but `DIET_BOT_PROMO_STORE_BACKEND` is not `postgres`.
- Production runtime/preflight fails when promo schema validation fails.
- Backup/restore drill required tables include `promo_codes`, `promo_redemptions`, and `promo_import_runs`.
- `FOOD20` cannot be enabled while promo store is JSON-backed.
- `FOOD20` expires 48 hours after each user's message 4 send time and is limited to one use per chat.
- Local JSON fallback tests cover temp file, file `fsync`, `os.replace`, directory `fsync`, backup behavior, and a torn/corrupt write path that does not silently erase an existing valid in-memory/Postgres state.

## Rollout Plan

1. Keep all live promo campaign sends disabled. Do not seed or enable `FOOD20` yet.
2. Add Postgres schema and store behind runtime config. JSON remains the default only in local/dev tests.
3. Run schema tests and Postgres integration tests against a disposable test database.
4. Run JSON import dry-run against a copied promo JSON file and record expected counts/fingerprint.
5. Take a normal Postgres backup before applying the import.
6. Apply import once with expected fingerprint and counts.
7. Run parity checks: promo definition count, redeemed count, active discount count, active monthly count, and spot checks for known used codes.
8. Run production preflight with promo schema validation.
9. Run backup and restore drill and verify promo table row counts are present in the report.
10. Only after the above, wire Telegram `/promo`, `/330366`, and discount payment creation to the Postgres promo store.
11. Keep `FOOD20` disabled until the discounted order flow and per-chat 48-hour window tests pass.
12. Update the production runbook with import, preflight, restore-drill, admin disable, and campaign rollback steps.

Rollback strategy:

- Before Telegram is wired, rollback is simply disabling `DIET_BOT_PROMO_FEATURES_ENABLED` or keeping the JSON runtime in local/dev only.
- After Telegram is wired, production rollback should disable promo features and `FOOD20`; do not switch production back to JSON because that reintroduces H-1.
- If an imported promo row is wrong, use an audited Postgres correction script/runbook SQL, not JSON replacement.

## Implementation Stages

19.2B schema + store + tests:

- add promo Postgres migrations, schema validation, import audit table, `PromoStore` interface, Postgres store, JSON/dev store hardening if retained, and strict JSON import tests;
- do not wire Telegram runtime yet;
- do not enable `FOOD20`.

19.2C activation flow wiring:

- replace direct JSON activation in Telegram with the promo service;
- make monthly-access activation and entitlement grant one Postgres transaction;
- add idempotent user messages and storage-unavailable handling;
- add discount order reservation/payment metadata wiring, still gated.

19.2D admin menu wiring:

- route `/330366` create/list/disable through Postgres;
- record `created_by`, `disabled_by`, and audit metadata;
- keep JSON admin writes unavailable in production.

19.2E preflight/runbook/restore-drill:

- add runtime config gate, production preflight promo schema check, backup/restore required table coverage, and runbook procedures;
- require restore-drill confirmation before live promo campaigns.

19.2F FOOD20 enablement decision:

- seed or create `FOOD20` only after 19.2B-19.2E pass;
- choose the recommended per-chat 48-hour window from sales follow-up message 4;
- run controlled QA with a test bot/database before any production campaign send.
