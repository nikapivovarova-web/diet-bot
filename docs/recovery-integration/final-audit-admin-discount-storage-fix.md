# Final Audit HIGH-2 Admin Discount Storage Fix

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Scope

Fixed only `HIGH-2`: admin discount-list storage error handling in the
Telegram admin promo menu.

Forbidden areas remained untouched: other final-audit high/medium/low findings,
recipes/data/PDF, payment/reversal/worker/runtime logic, bot process,
Telegram API/getUpdates, production DB, real payments/refunds, deploy, push,
commit, tag, PR, secrets/env files, archive, `New project 2 CLEAN`, and the
recovered bot.

## Root Cause

`_send_admin_discount_promo_list()` already expected `_list_admin_discount_promos()`
to either return a `list[PromoCodeDefinition]` or raise `EntitlementStorageError`.
The Postgres helper broke that contract: `_list_postgres_admin_discount_promos()`
caught `EntitlementStorageError` and returned
`(None, ADMIN_PROMO_STORAGE_ERROR_TEXT)`.

The caller then passed that tuple into `_format_admin_discount_promo_list()`.
The formatter iterated the tuple and tried to read `discount_percent` from the
first item, `None`, producing:

`AttributeError: 'NoneType' object has no attribute 'discount_percent'`

## Fix

- `_list_postgres_admin_discount_promos()` now preserves one contract:
  return only `list[PromoCodeDefinition]` on success.
- On `EntitlementStorageError`, it logs the list failure and re-raises the
  storage error.
- `_send_admin_discount_promo_list()` keeps the existing fail-closed behavior:
  it catches `EntitlementStorageError` and sends
  `ADMIN_PROMO_STORAGE_ERROR_TEXT` to the admin.
- The admin callback guard remains before any storage access. Non-admin users
  receive `"Command is available only to admins."` and the promo store is not
  read.

## Changed Files

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/final-audit-admin-discount-storage-fix.md`
- `docs/recovery-integration/recovery-status.md`

## Tests

RED reproduced before the production fix:

- `PYTHONPATH=src pytest tests/test_telegram_app_runtime.py::test_admin_discount_list_callback_answers_storage_error_when_promo_store_unavailable -q`
  - failed as expected with
    `AttributeError: 'NoneType' object has no attribute 'discount_percent'`.
  - result: `1 failed`.

Focused GREEN after the fix:

- `PYTHONPATH=src pytest tests/test_telegram_app_runtime.py::test_admin_discount_list_callback_answers_storage_error_when_promo_store_unavailable tests/test_telegram_app_runtime.py::test_admin_discount_list_callback_renders_postgres_discount_promos tests/test_telegram_app_runtime.py::test_admin_discount_list_callback_keeps_non_admins_out -q`
  - result: `3 passed in 4.36s`.

Requested tests:

- `PYTHONPATH=src pytest tests/test_promo_codes.py -q`
  - result: `11 passed in 0.18s`.
- `PYTHONPATH=src pytest <explicit test_telegram_app*.py file list> -q`
  - explicit files: `tests/test_telegram_app_photos.py`,
    `tests/test_telegram_app_runtime.py`.
  - result: `178 passed in 18.55s`.
- `git diff --check`
  - exit code `0`.
  - Git printed only LF-to-CRLF working-copy warnings in the dirty checkout.

## Not Done

- Did not fix any other final-audit high/medium/low finding.
- Did not change storage schema or add a DB migration.
- Did not change recipe/data/PDF files.
- Did not change payment, reversal, worker, runtime, or subscription logic.
- Did not run the bot, touch Telegram API/getUpdates, use production DB, make
  real payments/refunds, deploy, push, commit, tag, PR, or edit secrets/env
  files.
- Did not touch archive, `New project 2 CLEAN`, or recovered bot.

## Verdict

READY FOR RE-AUDIT for `HIGH-2`.
