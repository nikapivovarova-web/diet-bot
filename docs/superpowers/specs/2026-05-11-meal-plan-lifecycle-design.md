# Meal Plan Lifecycle Design

## Goal

Make ration generation and weekly PDF delivery durable enough to avoid stuck, duplicated, or unfairly refunded generations.

PostgreSQL `meal_plans` is the authoritative lifecycle source for production generation state. JSON storage remains a development-only best-effort fallback and does not attempt crash recovery.

This design covers:

- crash after Telegram delivery but before `completed`
- long generation without heartbeat
- stale cleanup refunding a live generation
- JSON fallback lost-limit behavior
- tester IDs bypassing durable locks and audit in production

## Non-Goals

- No JSON recovery journal.
- No Telegram delivery outbox that retries after process restart.
- No guaranteed recovery for a Telegram send that succeeded externally but crashed before the bot recorded completion.
- No change to ration-generation business rules, recipe selection, nutrition validation, payment grants, or payment reversal semantics except where they touch generation lifecycle state.

## Storage Authority

Production generation lifecycle is authoritative in PostgreSQL:

- `meal_plans` owns durable generation status, heartbeat, delivery state, and completion.
- `entitlement_events` remains the durable ledger for consume/refund audit.
- Telegram in-memory locks remain a fast local guard only. They do not replace PostgreSQL locks or lifecycle checks.

JSON fallback is explicitly limited:

```text
JSON fallback is dev-only best-effort storage.
It is not crash-safe, not delivery-recoverable, and must not be used in production.
Production requires PostgreSQL storage.
```

Production startup must fail fast when `DIET_BOT_DATABASE_URL` is not configured, even if `DIET_BOT_ALLOW_JSON_STORAGE=1`.

Recommended production configuration:

```env
DIET_BOT_ENV=production
DIET_BOT_DATABASE_URL=postgresql://...
DIET_BOT_ALLOW_JSON_STORAGE=0
```

## Meal Plan Statuses

`meal_plans.status` has these allowed values:

- `generating`: a generation attempt is active; a ration/PDF payload is not ready yet.
- `delivering`: generation succeeded and the bot is attempting required Telegram delivery.
- `completed`: every mandatory Telegram send for this attempt has successfully returned.
- `failed`: generation, validation, PDF build, or delivery failed before durable completion.
- `failed_timeout`: cleanup atomically closed a stale active attempt.

Only `generating` and `delivering` are active lock-holding statuses.

## Schema Changes

Extend `meal_plans` with:

- `heartbeat_at TIMESTAMPTZ`
- `delivery_started_at TIMESTAMPTZ`
- `delivered_at TIMESTAMPTZ`
- `telegram_message_id BIGINT`
- `delivery_attempts INTEGER NOT NULL DEFAULT 0`

`updated_at` remains a generic row-update timestamp. `heartbeat_at` is the liveness signal used by cleanup. For legacy rows without `heartbeat_at`, cleanup may fall back to `updated_at`.

Add or update indexes and constraints:

- active unique index covers `status IN ('generating', 'delivering')`
- status check includes `delivering`
- `delivery_attempts >= 0`
- cleanup-friendly index on active rows and `heartbeat_at`

## Generation Flow

When access is consumed:

1. Lock entitlement row.
2. Close this user's truly stale active rows if their heartbeat has expired.
3. Deny the request if another active row remains.
4. Consume entitlement and write ledger `consume`.
5. Insert `meal_plans` with `status='generating'`, `heartbeat_at=now()`, `expires_at=now()+timeout`.

During one-day generation and weekly PDF generation, the bot updates heartbeat periodically. Heartbeat updates must be best-effort from the caller's perspective: a transient heartbeat failure should be logged, but it should not by itself fail the generation.

Weekly PDF generation has a long synchronous section, so it needs heartbeat while building day candidates and while rendering the PDF. The implementation can use a lightweight async heartbeat task around the blocking work, plus explicit heartbeat calls before and after known long steps.

## Delivery Flow

The bot transitions to `delivering` only after the required payload is ready and immediately before mandatory Telegram sends begin.

Entering `delivering`:

- update `status='delivering'`
- set `delivery_started_at=COALESCE(delivery_started_at, now())`
- increment `delivery_attempts`
- update `heartbeat_at` and `updated_at`

Completion rule:

- `completed` is written only after all mandatory Telegram sends for the attempt have successfully awaited.
- The completion call happens immediately after the successful await path, before nonessential follow-up work.
- `message_id` is stored best-effort from the returned Telegram message when available.

For one-day ration delivery, all meal cards and required text chunks must send successfully before completion. The final post-plan UI/status message is part of the required delivery if the attempt currently depends on it to communicate the successful ration result.

For weekly PDF delivery, the required send is the PDF document path. If PDF rendering falls back to weekly text, the fallback text delivery is required for success; otherwise the attempt fails and is refunded.

## Failure and Refund Rules

If generation fails before `completed`, mark the row `failed` and refund from ledger when applicable.

If Telegram delivery fails after `delivering` but before `completed`, mark `failed` and refund. This may refund a case where Telegram accepted the message but the process did not receive or record the successful await; this is accepted because there is no durable confirmation.

Refunds remain idempotent:

- refund is based on the original `consume` ledger event for the meal plan
- unique refund constraints prevent double refunds
- `test_access` ledger source has amount and generation delta `0`

## Cleanup Semantics

Cleanup only considers active statuses:

- `generating`
- `delivering`

Cleanup must not refund based on a read-only stale query alone. For each stale candidate it must:

1. Lock the row and the user's entitlement transactionally.
2. Atomically transition the row from `generating` or `delivering` to `failed_timeout` only if the heartbeat is still expired.
3. Refund from ledger only after that status transition succeeds.
4. Leave the row untouched when heartbeat has been refreshed or status is no longer active.

Heartbeat freshness:

- primary signal: `heartbeat_at`
- legacy fallback: `updated_at` only when `heartbeat_at IS NULL`
- stale threshold: existing generation timeout window unless configuration later introduces separate thresholds

This prevents cleanup from refunding a generation that is alive but has not changed other columns recently.

## Tester Access

`TESTER_CHAT_IDS` must not bypass storage before production lock/audit checks.

Production rules:

- `TESTER_CHAT_IDS` is not an entitlement override in production.
- Production test access must be represented by durable entitlement state and audited through PostgreSQL.
- A production request must initialize and use storage before any generation access decision.

Development rules:

- `TESTER_CHAT_IDS` may remain as a local development shortcut.
- The shortcut is allowed only after storage configuration guards have run.
- It must not weaken production startup validation.

Durable test access continues to write generation audit rows with `source='test_access'`, `amount=0`, and `delta_generations=0`.

## JSON Fallback

JSON fallback stays intentionally simple:

- development only
- guarded by process/file locks
- no recovery journal
- no delivery recovery
- no production use

Documentation and runtime tests should make this explicit. The JSON path may keep current best-effort consume/refund behavior for local manual testing, but production correctness must not depend on it.

## Implementation Plan

1. Add schema/migration support for `delivering`, heartbeat, and delivery metadata.
2. Add store methods for heartbeat, delivery start, completion with delivery metadata, and atomic timeout close.
3. Update cleanup to use heartbeat and refund only after successful active-to-timeout transition.
4. Update Telegram generation flows to heartbeat during long work, enter `delivering` before sends, and complete immediately after successful required sends.
5. Remove production `TESTER_CHAT_IDS` bypass and ensure storage guards run before any tester shortcut.
6. Strengthen README/runtime docs for JSON fallback and production storage.
7. Add tests for lifecycle transitions, heartbeat-safe cleanup, crash-window behavior, JSON dev-only guard, and production tester behavior.

## Test Coverage

PostgreSQL tests:

- new attempts deny while either `generating` or `delivering` exists
- heartbeat refresh prevents cleanup refund
- stale `generating` transitions to `failed_timeout` and refunds once
- stale `delivering` transitions to `failed_timeout` and refunds once
- cleanup does not refund if atomic transition affects zero rows
- completion only succeeds from active delivery/generation states as intended
- duplicate refund attempts do not change limits twice
- `test_access` consume/refund audit remains zero-amount

Telegram flow tests:

- one-day flow calls delivery start before required sends and complete after successful sends
- one-day send failure refunds
- weekly PDF flow heartbeats during long build/PDF work
- weekly PDF document success completes after `send_document` await
- weekly PDF fallback text success completes only after required fallback sends
- failed PDF/fallback delivery refunds

Configuration tests:

- production without PostgreSQL fails fast, regardless of JSON fallback flag
- JSON fallback is allowed only in non-production with explicit flag
- `TESTER_CHAT_IDS` does not grant production generation access without durable entitlement
- development tester shortcut still works when explicitly allowed by local config

## Rollout Notes

Existing `generating` rows without `heartbeat_at` remain compatible through the legacy `updated_at` fallback. New rows should always set `heartbeat_at`.

The main residual risk is the narrow window where Telegram accepts a send and the process crashes before `completed` is written. This design minimizes that window by completing immediately after the awaited send returns, but does not add an outbox or post-crash delivery reconciliation.

That residual risk is acceptable for this pass because an outbox could create duplicate Telegram deliveries and is outside the chosen scope.
