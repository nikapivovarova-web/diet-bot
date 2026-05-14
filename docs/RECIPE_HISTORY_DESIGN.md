# Recipe History / Recent Avoidance Design

## Scope

This is a design/audit slice only. It does not change production code.

Goal: reduce cross-week recipe overlap so a subscribed user is not served nearly the same dishes in the next week or month, while preserving hard exclusions, same-week no-repeat, protein floor, complete weekly plans, and existing PDF/Telegram delivery behavior.

## 1. Current State

### Storage and Generation Lifecycle

There is no table named `generation_attempts`. The current generation attempt model is split across:

- `AttemptConsumption` in `src/diet_bot/subscriptions.py`.
- `generation_records` in `src/diet_bot/postgres_migrations.py`.
- `entitlement_events` in `src/diet_bot/postgres_migrations.py`.
- Store methods in `src/diet_bot/storage.py` and `src/diet_bot/postgres_store.py`.

Postgres generation flow today:

- `consume_generation_attempt(user_id, ration_kind)` locks the user's entitlement row, fails stale active generations, checks monthly/extra/free/test access, inserts a `generation_records` row with status `generating`, inserts an `entitlement_events` row with `event_type = 'consume'`, and returns an `AttemptConsumption` with private `_postgres_generation_id` / `_postgres_entitlement_event_id` attributes.
- `start_generation_delivery(...)` can move an active record to `delivering`, increment `delivery_attempts`, and refresh the heartbeat. The method exists in the store contract, but the Telegram app currently completes attempts directly without a visible call to `start_generation_delivery`.
- `complete_generation_attempt(...)` marks the active `generation_records` row as `completed`, clears `error_message`, sets `delivered_at` / `finished_at`, and can store `pdf_path` and `telegram_message_id`.
- `refund_generation_attempt(...)` marks an active generation as `failed`, inserts a refund entitlement event, and restores the consumed access.
- `cleanup_stale_generations(...)` marks stale active generations as `failed_timeout` and refunds once.

Payment/subscription generation locks:

- `generation_records` has statuses `generating`, `delivering`, `completed`, `failed`, and `failed_timeout`.
- `uniq_active_generation_per_user` enforces one active generation per user for statuses `generating` and `delivering`.
- `entitlement_events` has unique indexes for one `consume` and one `refund` per generation.
- Entitlements store monthly limits and extra generation counts; payment orders and payment events are separate ledgers.

Completed generation records currently store:

- `generation_records.id`
- `user_id`
- `ration_kind`
- `status`
- `entitlement_event_id`
- `pdf_path`
- `telegram_message_id`
- heartbeat/delivery/finish timestamps
- `error_message`

What is already stored as metadata:

- `entitlement_events.metadata_json` stores at least `ration_kind` and `attempt_source` for consume events.
- `payment_orders.metadata_json` stores order-side metadata, promo linkage, invoice state, and discount information.
- `payment_events.raw_payload_redacted` stores redacted provider payloads.
- `promo_codes`, `promo_redemptions`, and `promo_events` have JSON metadata.
- `chat_state.state_json` stores per-chat app state in Postgres; the dev JSON fallback stores the same shape in `.diet_bot_state/history.json`.

What is missing:

- `generation_records` has no `metadata_json` column.
- The store contract has no method to record result meal metadata.
- Completed generations do not store `recipe_id`, `recipe_key`, meal slot, day index, or plan signature.
- There is no structured query surface for "recipes served to this user in the last N weeks".

### Current Recent Recipe Memory

The Telegram app currently keeps recent recipes in flat per-chat lists:

- In-memory maps: `RECENT_RECIPE_IDS_BY_CHAT_ID` and `RECENT_RECIPE_KEYS_BY_CHAT_ID`.
- `RECENT_RECIPE_LIMIT = 160`.
- `_load_chat_history(chat_id)` loads `recipe_ids` / `recipe_keys` from chat state.
- `_save_chat_history(chat_id)` writes `recipe_ids` / `recipe_keys` back to chat state.
- With Postgres enabled, chat state is `chat_state.state_json`.
- With local JSON enabled, chat state is `.diet_bot_state/history.json`.

Current limitations:

- The lists contain strings only. They do not include `generated_at`, `generation_id`, `ration_kind`, `meal_slot`, or whether the generation completed.
- They are capped by count, not by product time window.
- They cannot distinguish a recipe served yesterday from a recipe served four weeks ago.
- They cannot implement "repeat the least recent recipe" except by list order approximation.
- They are tied to chat state, not to completed generation records.
- Existing JSON-to-Postgres migration preserves chat state, including `recipe_ids` and `recipe_keys`, but does not turn them into a structured recipe history ledger.

### Current Generation Inputs

`avoided_recipe_ids` and `avoided_recipe_keys` already exist in the plan builders.

One-day flow:

- `_send_plan(...)` calls `_load_chat_history(chat_id)`.
- It passes `recent_recipe_ids` and `recent_recipe_keys` into `build_one_day_plan(...)`.
- `build_one_day_plan(...)` filters recipes by `recipe.id not in avoided_recipe_ids` and `_recipe_memory_key(recipe) not in avoided_recipe_keys`.
- If no recipe plan is possible, it first relaxes key avoidance. If `allow_avoided_recipe_relaxation=True`, it can relax both IDs and keys to keep a complete one-day plan.
- `_remember_recipes(chat_id, plan_result)` appends served meal IDs/keys to chat state.

Weekly flow:

- `_send_week_plan(...)` loads the same chat history.
- `_build_week_plans(...)` initializes `week_recipe_ids` and `week_recipe_keys` with the recent IDs/keys.
- Each day calls `_select_week_day_plan(...)`.
- `_select_week_day_plan(...)` calls `build_one_day_plan(..., allow_avoided_recipe_relaxation=False)` and rejects any plan or carryover that uses avoided IDs/keys.
- After a successful PDF send, `_send_week_plan(...)` calls `_remember_recipes(...)` for each day.

Important success boundary:

- Weekly history is remembered after successful PDF payload generation and document send.
- One-day history is remembered inside `_send_plan(...)`, before `_complete_generation_attempt(...)` is called by the access wrapper. If a later delivery step throws after `_remember_recipes`, the attempt can be refunded while history has already been recorded. The recommended design should move durable history recording to the same success boundary as generation completion.

## 2. Data Model Options

### Option A: Store Issued Recipes Per Generation Attempt

Add a normalized child table such as `generation_recipe_items`:

- `id`
- `generation_id`
- `user_id`
- `ration_kind`
- `day_index`
- `meal_index`
- `meal_slot`
- `recipe_id`
- `recipe_key`
- `generated_at`

Pros:

- Strong audit trail: every served recipe is attached to a completed generation.
- Easy to prove that a weekly generation produced 35 records.
- Natural fit for avoiding failed/refunded attempts by only inserting rows after generation completion.
- Supports future admin/debug views per generation.

Cons:

- Recent lookup requires joining or duplicating `user_id` / `ration_kind`.
- A pure "latest recipe use by user" query is less direct than a user-first history table unless indexed carefully.
- It is still awkward for the dev JSON fallback, which has no generation table.

### Option B: Separate `user_recipe_history` Table

Add a user-first ledger table:

- `id`
- `user_id`
- `generation_id`
- `ration_kind`
- `generated_at`
- `day_index`
- `meal_index`
- `meal_slot`
- `recipe_id`
- `recipe_key`

Pros:

- Direct query path for recent avoidance: `WHERE user_id = ? AND generated_at >= ?`.
- Supports least-recent fallback with `max(generated_at)` per `recipe_id` / `recipe_key`.
- Keeps product behavior independent from payment/order metadata.
- Works well with indexes on `(user_id, generated_at DESC)`, `(user_id, recipe_id, generated_at DESC)`, and `(user_id, recipe_key, generated_at DESC)`.
- Can still reference `generation_records(id)` for auditability.
- Has a close dev JSON fallback shape: an array of recipe history entries.

Cons:

- Duplicates some generation facts already present in `generation_records`.
- Needs idempotency protection if completion is retried.
- Requires store contract additions.

### Option C: JSON Metadata on Generation Events

Store generated recipe arrays in `generation_records.metadata_json` or in the existing `entitlement_events.metadata_json`.

Pros:

- Smallest schema change if only adding `generation_records.metadata_json`.
- Keeps all data attached to generation/payment lifecycle rows.
- Useful for debug snapshots and plan signatures.

Cons:

- Poor query ergonomics for "avoid last 2 weeks, penalize weeks 3-4".
- JSONB indexes are possible but heavier than normal relational indexes.
- Harder to enforce one row per served recipe or count 35 weekly records.
- Harder to implement least-recent fallback cleanly.
- Entitlement events are payment/access ledger records; overloading them with plan result data blurs responsibilities.

## 3. Recommended Approach

Use a normalized `user_recipe_history` table for Postgres and an equivalent `recipe_history` array in dev JSON chat state. Keep the existing flat `recipe_ids` / `recipe_keys` as backward-compatible derived fields during the transition.

Recommended Postgres table:

```sql
CREATE TABLE IF NOT EXISTS user_recipe_history (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    generation_id BIGINT REFERENCES generation_records(id) ON DELETE SET NULL,
    ration_kind TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    day_index INTEGER,
    meal_index INTEGER NOT NULL,
    meal_slot TEXT NOT NULL,
    recipe_id TEXT NOT NULL,
    recipe_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ration_kind IN ('one_day', 'weekly_pdf')),
    CHECK (meal_index >= 0),
    CHECK (day_index IS NULL OR day_index >= 0)
);
```

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_user_recipe_history_recent
    ON user_recipe_history(user_id, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_recipe_history_recipe_id
    ON user_recipe_history(user_id, recipe_id, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_recipe_history_recipe_key
    ON user_recipe_history(user_id, recipe_key, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_recipe_history_generation
    ON user_recipe_history(generation_id);
```

Recommended idempotency:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uniq_user_recipe_history_generation_slot
    ON user_recipe_history(generation_id, day_index, meal_index, recipe_id)
    WHERE generation_id IS NOT NULL;
```

Store these fields for every served meal:

- `user_id`
- `recipe_id`
- `recipe_key`
- `meal_slot`
- `generated_at`
- `ration_kind`
- `generation_id`

Also store `day_index` and `meal_index`. They are not required for avoidance, but they make weekly count tests, audits, and duplicate diagnostics much cheaper.

Recommended store contract:

- `load_recent_recipe_history(user_id, *, since, limit) -> list[RecipeHistoryItem]`
- `record_recipe_history(user_id, consumption, items, *, generated_at=None) -> None`

`record_recipe_history` should use `consumption` to resolve the Postgres `generation_id`, so the application layer does not need to know about private `_postgres_generation_id` attributes. For JSON fallback, the same function can write entries into chat state under `recipe_history`.

Dev JSON fallback shape:

```json
{
  "recipe_history": [
    {
      "recipe_id": "r001_...",
      "recipe_key": "breakfast:curated:r001_...",
      "meal_slot": "breakfast",
      "generated_at": "2026-05-14T10:30:00+00:00",
      "ration_kind": "weekly_pdf",
      "generation_id": null,
      "day_index": 0,
      "meal_index": 0
    }
  ],
  "recipe_ids": ["..."],
  "recipe_keys": ["..."]
}
```

The JSON fallback should prune by count and/or age to avoid unbounded local state growth. A practical local cap is the most recent 250-400 recipe history items per chat.

## 4. Selection Semantics

Hard constraints:

- Allergies, exclusions, and intolerances remain hard.
- Same-week no-repeat by `recipe_id` and `recipe_key` remains hard.
- Complete week remains hard: no partial weekly PDF success.
- Protein floor remains hard.
- PDF and Telegram formatting remain unaffected by history.

Recent avoidance windows:

- Current week / inside one generated weekly plan: hard no-repeat.
- Recent 1-2 weeks: hard avoid if a complete valid week is feasible.
- Recent 3-4 weeks: strong penalty / soft avoid.
- Older than the soft window: allowed, but still ranked below genuinely fresh equivalent options when all else is equal.

Recommended lookup:

- Load the user's completed recipe history for the last 28 days.
- Build:
  - `hard_recent_recipe_ids` / `hard_recent_recipe_keys` for the last 14 days.
  - `soft_recent_recipe_ids` / `soft_recent_recipe_keys` for days 15-28.
  - `last_seen_by_recipe_id` / `last_seen_by_recipe_key` for least-recent fallback.

Fallback behavior:

1. Try to build a complete week with hard recent avoidance plus same-week no-repeat.
2. If no complete valid week exists, relax only the 1-2 week recent avoid into a scored penalty.
3. Prefer repeats whose `last_seen_at` is oldest.
4. Continue to reject allergy/exclusion/intolerance violations, same-week repeats, protein-floor failures, and incomplete weeks.
5. If even the relaxed pool cannot produce a valid week, return controlled failure rather than breaking hard health/product constraints.

Least-recent scoring:

- New recipe: best score.
- Older-than-28-day recipe: small or zero penalty.
- 15-28-day recipe: significant penalty.
- 0-14-day recipe during fallback: highest penalty, increasing sharply for very recent use.
- Tie-break with existing macro/protein/candidate scoring so fallback does not destroy nutrition quality.

Batch/carryover note:

- Current product goal says same-week no-repeat remains hard. Batch carryovers should not silently override this. If future product requirements intentionally allow batch repeats, that exception should be explicit and should not count as a normal "fresh recipe" in history scoring.

## 5. Product Semantics

User promise:

- A subscribed user should see meaningfully more variety across subscription weeks.
- The next weekly PDF should avoid the last 1-2 weeks of recipes when the catalog and user constraints make that feasible.
- The system should prefer recipes not seen in the last month over recipes seen recently.

Exact guarantees:

- No repeated `recipe_id` / `recipe_key` inside one completed weekly plan.
- Allergies, exclusions, intolerances, protein floor, and complete-week requirements remain stronger than variety.
- Failed/refunded attempts should not add durable recipe history.
- Completed one-day and weekly generations can add history, depending on the final product decision for one-day ration semantics.

Limitations:

- A user with many exclusions, narrow cooking-time preferences, or a small eligible slot pool may still see repeats.
- When repeats are unavoidable, the repeat should come from the oldest eligible history entry, not the newest week.
- The product should avoid claiming "no repeats for a month" unless feasibility checks prove enough eligible recipes for that user's profile.

## 6. Integration Plan

### Storage Contract and Migration

1. Add a small `RecipeHistoryItem` dataclass or typed dict near `storage.py`.
2. Extend `DietBotStore` with load and record methods for recipe history.
3. Add an idempotent Postgres migration for `user_recipe_history` and indexes.
4. Implement Postgres read/write methods.
5. Implement JSON fallback read/write methods against chat state `recipe_history`, while preserving existing `recipe_ids` / `recipe_keys`.
6. Update JSON-to-Postgres migration only if legacy flat lists need to be converted. Since legacy lists have no timestamps or slots, import them as low-confidence history only if product wants continuity. Otherwise preserve them as legacy chat state and let new structured history build from future completions.

### Record Only Successful Generations

Record recipe history after successful generation and delivery only:

- One-day: record after all meal cards and final plan messages are sent, and after the generation is marked completed.
- Weekly PDF: record after PDF payload generation and successful Telegram document send, and after the generation is marked completed.
- Do not record failed generations.
- Do not record attempts that are refunded after generation or delivery failure.
- Do not record stale `failed_timeout` attempts.

The cleanest implementation is a success helper that completes the generation and records history in one storage-level transaction for Postgres. If the app keeps two calls, `record_recipe_history` must be idempotent by `generation_id` plus day/meal indexes.

### One-Day and Weekly Behavior

Weekly:

- Load recent history before `_build_week_plans`.
- Feed recent windows into the weekly builder/optimizer.
- Persist 35 history rows for a 7 x 5 completed week.
- Keep PDF rendering unchanged because history operates before selection and after successful delivery.

One-day:

- Continue to use recent history as input to `build_one_day_plan`.
- Decide whether one-day generations should contribute to weekly recent avoidance. The recommended default is yes, because a user should not receive a weekly PDF that immediately repeats yesterday's one-day plan.
- If one-day history proves too restrictive, include it only in the 3-4 week soft penalty or only for matching meal slots.

PDF and Telegram:

- No PDF schema or renderer changes are required.
- Telegram meal cards do not need new user-facing text.
- Existing behavior without `image_url` is unaffected.

## 7. Test Plan

Storage and migration:

- Postgres migration creates `user_recipe_history` and all indexes idempotently.
- Storage contract exposes recipe-history load/write methods.
- Postgres `record_recipe_history` writes 35 rows for a completed weekly generation.
- JSON fallback writes and reloads structured `recipe_history`.
- Existing flat `recipe_ids` / `recipe_keys` remain backward compatible during transition.

Success/failure boundaries:

- Completed weekly records exactly 35 `recipe_id` values for a 7 x 5 week.
- Failed generation does not record history.
- Refunded generation does not record history.
- Stale timeout cleanup does not record history.
- Retried completion does not duplicate history rows.

Selection:

- Next weekly generation avoids recent recipes when the catalog is feasible.
- Inside-week no-repeat remains hard even when recent history is relaxed.
- If recent avoid is impossible, controlled fallback uses least-recent recipes, not the newest recipes.
- Recent 3-4 week recipes are penalized but can appear when needed for completeness.
- Allergies, exclusions, and intolerances remain hard under every fallback phase.
- Protein floor remains hard under every fallback phase.
- Complete-week-only behavior remains hard.

Regression/smoke:

- Existing PDF/Telegram formatting tests remain unchanged.
- Weekly samples still build 7 x 5.
- PDF and Telegram still work when meals have no `image_url`.
- Cross-week overlap smoke should compare week N and week N+1 for the same user and assert overlap is low when the eligible catalog can support it.

## 8. Implementation Slices

### Slice 1: Storage Model and Migration

- Add `RecipeHistoryItem` structure.
- Add `user_recipe_history` migration and indexes.
- Add Postgres load/write methods.
- Add storage contract tests and migration tests.
- Add JSON fallback helpers and tests.

### Slice 2: Record History on Successful Generation

- Collect meal history items from one-day and weekly plans.
- Move one-day durable history recording out of `_send_plan` and into the post-success path.
- Record weekly history only after successful PDF send.
- Ensure failed/refunded attempts do not write history.
- Keep legacy flat recent lists updated as derived compatibility state during rollout.

### Slice 3: Feed Recent IDs Into Builder

- Replace direct reads from flat `recipe_ids` / `recipe_keys` with `load_recent_recipe_history`.
- Build hard and soft windows from structured history.
- Pass hard recent IDs/keys into the existing builder path first.
- Preserve existing same-week no-repeat state.

### Slice 4: Soft Fallback and Least-Recent Selection

- Add a bounded fallback phase for infeasible hard recent avoidance.
- Score candidates by freshness using `last_seen_at`.
- Prefer least-recent repeats while preserving macro/protein scoring.
- Add tests for impossible recent-avoid pools.

### Slice 5: Smoke Notes

- Record recipe-history smoke results in docs.
- Include same-user week-over-week overlap numbers.
- Include hard-exclusion and protein-floor checks.
- Include PDF/Telegram unchanged checks.

## 9. Open Questions

- Avoid window: should product use 2 weeks hard + 4 weeks soft, or a different split?
- Should one-day ration history affect weekly PDFs, weekly history only, or only matching meal slots?
- Should admin/test generations record history?
- Should legacy flat `recipe_ids` / `recipe_keys` be imported into structured history with approximate timestamps, or left as compatibility-only state?
- Should history be per Telegram chat ID only, or future-proofed for a separate account/user ID if the product adds multi-chat/account support?
