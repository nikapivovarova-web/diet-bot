# Final Audit HIGH-2 Admin Discount Storage Re-audit

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Verdict

`HIGH-2` is closed in this scoped re-audit.

The admin discount-list storage-error path no longer reproduces the original
crash. The Postgres helper has a single return contract, the caller answers the
admin with `ADMIN_PROMO_STORAGE_ERROR_TEXT`, the normal admin discount list flow
still renders active discount promos, and the non-admin callback guard remains
before promo storage access.

Updated final-audit count: `0` blocker, `5` high, `4` medium, `6` low.

Production launch is still not approved. This re-audit did not address the
remaining final-audit high, medium, or low findings.

## Validation Rubric

- [x] `_list_postgres_admin_discount_promos()` returns only
  `list[PromoCodeDefinition]` on success.
- [x] `_list_postgres_admin_discount_promos()` does not return a tuple on
  storage failure; it raises `EntitlementStorageError`.
- [x] `_send_admin_discount_promo_list()` catches storage failure and sends
  `ADMIN_PROMO_STORAGE_ERROR_TEXT`.
- [x] Normal admin discount listing still renders active discount promos and
  excludes non-discount promos.
- [x] Non-admin admin-promo callbacks are rejected before storage access.

## Audit Inputs

Original finding:

- `docs/recovery-integration/final-pre-release-audit.md`
  - `HIGH-2` identified that `_list_postgres_admin_discount_promos()` was typed
    and consumed as returning `list[PromoCodeDefinition]`, but returned
    `(None, ADMIN_PROMO_STORAGE_ERROR_TEXT)` on `EntitlementStorageError`.
  - Impact was an admin callback `AttributeError` instead of a storage-error
    answer.
  - Required fix was to return only a list or raise `EntitlementStorageError`
    and let the caller handle `ADMIN_PROMO_STORAGE_ERROR_TEXT`.

Fix report:

- `docs/recovery-integration/final-audit-admin-discount-storage-fix.md`
  - Fix scope was limited to `HIGH-2`.
  - The helper was changed to return only active discount promo definitions on
    success and re-raise storage errors.
  - The caller kept fail-closed behavior by sending
    `ADMIN_PROMO_STORAGE_ERROR_TEXT`.
  - The admin guard remained before storage access.

## Static Evidence

- `src/diet_bot/telegram_app.py:1535`
  - The admin list callback checks `_is_admin_callback(callback)` first.
  - Non-admin users receive `"Command is available only to admins."` and return
    before `_send_admin_discount_promo_list()`.
- `src/diet_bot/telegram_app.py:6399`
  - `_send_admin_discount_promo_list()` calls `_list_admin_discount_promos()` in
    a `try` block.
  - It catches `EntitlementStorageError` and sends
    `ADMIN_PROMO_STORAGE_ERROR_TEXT`.
  - On success it passes the returned list to
    `_format_admin_discount_promo_list()`.
- `src/diet_bot/telegram_app.py:6597`
  - `_list_postgres_admin_discount_promos()` is annotated as
    `list[PromoCodeDefinition]`.
  - On `EntitlementStorageError`, it logs and raises.
  - On other exceptions, it raises `EntitlementStorageError`.
  - On success, it returns `sorted(promos, key=lambda item: item.code)`.
  - No tuple return remains in this helper.

## Runtime Evidence

Focused callback re-audit:

- Command:
  `PYTHONPATH=src pytest tests/test_telegram_app_runtime.py::test_admin_discount_list_callback_answers_storage_error_when_promo_store_unavailable tests/test_telegram_app_runtime.py::test_admin_discount_list_callback_renders_postgres_discount_promos tests/test_telegram_app_runtime.py::test_admin_discount_list_callback_keeps_non_admins_out -q`
- Result:
  `3 passed in 3.67s`
- Evidence:
  - Storage-error admin callback answered
    `ADMIN_PROMO_STORAGE_ERROR_TEXT`.
  - Normal admin discount list rendered the discount promo and excluded a
    monthly-access promo.
  - Non-admin callback returned `"Command is available only to admins."` and the
    test guard would fail if promo storage were read.

Requested runtime file:

- Command:
  `PYTHONPATH=src pytest tests/test_telegram_app_runtime.py -q`
- Result:
  `28 passed in 7.90s`

Requested promo unit file:

- Command:
  `PYTHONPATH=src pytest tests/test_promo_codes.py -q`
- Result:
  `11 passed in 0.11s`

Whitespace check:

- Command:
  `git diff --check`
- Result:
  `exit 0`; only LF-to-CRLF working-copy warnings were printed.

Logs:

- `tmp/final-audit-admin-discount-storage-reaudit/focused-admin-discount-callbacks.log`
- `tmp/final-audit-admin-discount-storage-reaudit/test_telegram_app_runtime.log`
- `tmp/final-audit-admin-discount-storage-reaudit/test_promo_codes.log`
- `tmp/final-audit-admin-discount-storage-reaudit/git-diff-check-before-status-update.log`
- `tmp/final-audit-admin-discount-storage-reaudit/git-diff-check-final.log`

## Scope Boundaries

Changed in this re-audit:

- `docs/recovery-integration/final-audit-admin-discount-storage-reaudit.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/final-audit-admin-discount-storage-reaudit/**`

Read-only in this re-audit:

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/final-pre-release-audit.md`
- `docs/recovery-integration/final-audit-admin-discount-storage-fix.md`

Not done:

- No code, data, config, env, or secret changes.
- No other final-audit high, medium, or low fixes.
- No bot process start.
- No Telegram API or `getUpdates`.
- No production DB access.
- No payments or refunds.
- No deploy, push, commit, tag, PR, or branch changes.
- No archive, `New project 2 CLEAN`, or recovered-bot work.

## Next Prompt

Recommended next prompt:

`FoodBalance: fix next explicitly selected final pre-release audit high finding`
