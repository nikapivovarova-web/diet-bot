# Final Audit Low Promo Per-User Limit Semantics

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Verdict

Closed locally with a narrow promo-store fix.

Updated local final pre-release audit count: `0 high / 0 medium / 0 low`.

This is not final RC closure. A later disposable-DSN final RC verification pass
is still required because the previous privacy-consent durability fix skipped
Postgres integration checks when `DIET_BOT_TEST_DATABASE_URL` was absent.

## Classification

The low finding was a real behavior gap in the Postgres promo store. The
schema stored `per_user_limit`, and the Stage 19 design said to count active
redemptions for the same code and chat under the locked promo row. The runtime
instead treated any active `(code, chat_id)` redemption as a hard duplicate and
also had a unique active `(code, chat_id)` index. That made every promo behave
as `per_user_limit=1`, regardless of the stored value.

## Intended Semantics

- The runtime limit key is `(promo code, chat_id)`. `user_id` is retained as
  redemption metadata, but current Telegram private-chat promo enforcement is
  per chat.
- The limit is per promo code. Claims for different promo codes are counted
  independently.
- The count is based on active redemption rows with status `reserved` or
  `redeemed`. Released, failed, expired, and offered rows do not spend the
  active per-chat limit.
- `expires_at` remains the campaign/code lifetime gate. No separate
  per-chat campaign-window expiry was added in this scoped fix.
- Admin monthly-access creation still creates one-use codes with
  `max_redemptions=1` and `per_user_limit=1`.
- Admin discount create/update preserves an existing discount promo's limits,
  or creates the default `per_user_limit=1` row for the current UI.
- JSON promo state remains local/dev fallback and import seed material. JSON
  import preserves `per_user_limit` into Postgres, but production multi-use
  discount semantics are Postgres-only.

## Root Cause

The Postgres store kept the old duplicate-chat protection from the first promo
store cut:

- `idx_promo_code_redemptions_code_chat_active_unique` allowed only one active
  redemption row for a code/chat pair.
- `_claim_promo_code()` returned `already_redeemed` as soon as any active
  redemption existed for the code/chat pair.

Those two mechanisms were correct for one-time monthly-access promo codes, but
they ignored the generalized `per_user_limit` field needed before multi-use
discount campaigns.

## Fix

- Added promo migration `202605310002`.
- The migration drops the unique active `(code, chat_id)` index and replaces it
  with non-unique `idx_promo_code_redemptions_code_chat_status`.
- `PROMO_SCHEMA_EXPECTATION` now requires the new migration and lookup index.
- `_claim_promo_code()` now:
  - keeps idempotency-key retries idempotent;
  - counts active redemptions for the same `(code, chat_id)`;
  - blocks only when that count reaches `promo.per_user_limit`;
  - still enforces global `max_redemptions` under the same locked promo row.

## Tests

RED before the fix:

- `python -m pytest tests/test_postgres_promo_store.py::test_promo_migration_removes_unique_chat_code_index_for_per_user_limits -q`
  - `1 failed`
- `DIET_BOT_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55436/diet_bot_test python -m pytest tests/test_postgres_promo_store.py::test_per_user_limit_allows_same_chat_until_limit_then_blocks -q`
  - `1 failed`

GREEN after the fix:

- `python -m pytest tests/test_postgres_promo_store.py::test_promo_migration_declares_required_tables_indexes_and_constraints tests/test_postgres_promo_store.py::test_promo_migration_removes_unique_chat_code_index_for_per_user_limits tests/test_postgres_migration_versions.py -q`
  - `3 passed`
- `DIET_BOT_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55436/diet_bot_test python -m pytest tests/test_postgres_promo_store.py::test_schema_init_is_idempotent tests/test_postgres_promo_store.py::test_redeem_same_chat_same_code_is_idempotent tests/test_postgres_promo_store.py::test_single_use_code_cannot_be_redeemed_by_another_chat tests/test_postgres_promo_store.py::test_multi_use_code_respects_max_uses tests/test_postgres_promo_store.py::test_per_user_limit_allows_same_chat_until_limit_then_blocks -q`
  - `5 passed`
- `DIET_BOT_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55436/diet_bot_test python -m pytest tests/test_postgres_promo_store.py -q`
  - `11 passed`
- `python -m pytest tests/test_promo_codes.py tests/test_telegram_app_runtime.py -k promo -q`
  - `23 passed, 32 deselected`
- `python -m pytest tests/test_production_preflight.py tests/test_postgres_migration_versions.py -q`
  - `24 passed`
- `python -m pytest tests/test_postgres_restore_drill_ops.py -q`
  - `16 passed, 1 skipped`
- `python -m compileall -q src/diet_bot/postgres_promo_migrations.py src/diet_bot/postgres_promo_store.py`
  - exit code `0`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

The DSN runs used a disposable local Postgres container on
`127.0.0.1:55436/diet_bot_test`. No production database was used.

## Scope Boundaries

- No privacy-consent behavior was changed.
- No provider/refund/reversal logic was changed.
- No sales follow-up behavior was changed.
- No recipe data, import, or photos were changed.
- No bot process was started.
- No Telegram API or `getUpdates` call was made.
- No production database was used.
- No provider/live payment smoke was run.
- No deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or
  recovered-bot path was touched.

## Next Recommended Prompt

FoodBalance: run the final disposable-DSN RC verification pass only. Start by
recording branch, HEAD, and `git status --short`; verify the new promo
`per_user_limit` closure plus the previous privacy-consent Postgres integration
checks under a disposable local `DIET_BOT_TEST_DATABASE_URL`; then run the
agreed final RC local gates. Do not start the bot, call Telegram API/getUpdates,
use production DB, run provider/live payment smoke, deploy, push, commit, tag,
PR, archive, `New project 2 CLEAN`, or the recovered bot.
