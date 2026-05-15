# Promocode Smoke Notes

Date: 2026-05-13

Scope: focused local smoke/check slice for promocode recovery commits. No runtime code changes, cleanup, refactor, push, or real YooKassa/Telegram Stars payments were performed.

## Commits Covered

- `fb16b64` `promo: add promocode storage model`
- `a69ddb6` `promo: redeem monthly access codes`
- `3e74d2c` `promo: apply discount codes to payments`
- `3e73d41` `promo: add admin access code command`
- `484418f` `promo: add hidden admin promo panel`
- `b410e04` `promo: add admin discount management panel`

## Git Context

- Workspace: `C:\Users\adck8\Documents\New project 2 CLEAN`
- Branch: `codex/emergency-stabilization`
- Recent log head: `b410e04`, `484418f`, `3e73d41`, `3e74d2c`, `a69ddb6`, `fb16b64`
- Pre-docs smoke working tree: clean; branch was ahead of origin by 47 commits.

## Checked

- Promo model/storage behavior:
  - code normalization and definition validation;
  - monthly access defaults;
  - discount amount calculation;
  - generated monthly access code uniqueness;
  - one-time JSON monthly activation;
  - discount code rejection from monthly-access activation;
  - disabled/expired/unknown promo rejection.
- Telegram promo/admin flows:
  - promo code prompt;
  - monthly access activation and replay rejection;
  - invalid/non-monthly promo activation responses;
  - existing subscription extension;
  - hidden admin promo panel admin-only access;
  - monthly access code creation through admin panel and `/330366 code`;
  - non-admin rejection for admin promo actions.
- Payment discount behavior:
  - discounted YooKassa invoice metadata uses final amount and redacted promo metadata;
  - discounted order rejects catalog amount at pre-checkout and successful-payment validation;
  - discount code entered by user is applied to the next YooKassa invoice/order creation without completing payment.
- Admin discount panel manual-safe dry-run:
  - admin panel opens only for admin;
  - monthly access code created through panel;
  - monthly access code activated by user;
  - repeat monthly activation rejected;
  - discount code created and then updated through panel;
  - discount list shows discount codes only;
  - monthly access code is absent from discount list;
  - discount code applies to fake YooKassa invoice/order creation without payment;
  - disabled discount is no longer remembered or applied.

## Commands Run

- `git status --short --branch`
- `git log --oneline --decorate -n 20`
- `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_promo_codes.py tests/test_telegram_app_photos.py tests/test_payments_model.py -k "promo or discount" --durations=10`
- `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider -m postgres_integration tests/test_postgres_store.py -k "promo or discount" --durations=5`
- `$env:PYTHONPATH = "src"; ... | .\.venv\Scripts\python.exe -` manual-safe promo/admin/discount dry-run with fake Telegram bot and in-memory store.

## Results

- Focused promo pytest subset: `21 passed, 182 deselected`.
- Postgres promo subset without local DB lane: `10 skipped, 18 deselected`.
- Manual-safe promo/admin/discount dry-run: passed all assertions.
  - Admin panel callbacks present: monthly create, discount create/update, discount list, discount disable.
  - Fake discounted invoice/order: list amount `59900`, discount `14975`, final amount `44925`.
  - Fake full-price invoice/order after discount disable: final amount `59900`, discount `0`.
  - Fake invoice links created: `2`.
  - Real payments performed: `false`.

## 2026-05-15 User-Facing Flow Follow-up

Scope: Telegram user-facing promo code entry for payment/subscription UX only. No planner, recipes, PDF, payment core, storage migrations, admin promo panel changes, push, or real YooKassa/Telegram Stars payments were performed.

Checked:

- subscription/payment keyboard now exposes the existing `Ввести промокод` entry point;
- promo prompt and retryable errors mention `/cancel`;
- monthly access code redemption through the user flow grants active monthly access;
- invalid code keeps the input state so the user can retry or cancel;
- discount code entered by the user is remembered and passed to the next fake YooKassa subscription invoice/order;
- `/cancel` exits promo input without deleting the saved profile.

Commands run:

- `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp .pytest_tmp_telegram_runtime tests/test_telegram_app_runtime.py`
- `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp .pytest_tmp_telegram_photos_promo tests/test_telegram_app_photos.py -k "promo or discount"`
- `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp .pytest_tmp_promo_codes tests/test_promo_codes.py`
- `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp .pytest_tmp_payment_promo tests/test_payments_model.py -k "promo or discount"`

Results:

- Telegram runtime handler tests: `40 passed`.
- Telegram promo/photo subset: `10 passed, 86 deselected`.
- Promo model tests: `9 passed`.
- Payment promo subset: `2 passed, 96 deselected`.
- Real payments performed: `false`.

## Postgres Lane

Local Postgres lane was not available in this shell:

- `DIET_BOT_TEST_DATABASE_URL` was not set.
- `pg_isready` was not available.

The skip-safe Postgres marker behavior was checked with the focused promo/discount subset, and the marked tests skipped cleanly without `--require-postgres`.

## Not Checked

- Real YooKassa checkout was not run.
- Real Telegram Stars spend/checkout was not run.
- Live Telegram Bot API polling was not started.
- Provider-side pre-checkout and successful-payment webhooks/events were not exercised against real providers.

## Known Issues / Gaps

- No dedicated pytest functions were found for the new admin discount management panel paths in `tests/test_telegram_app_photos.py`; those paths were covered by the manual-safe inline dry-run instead.
- The focused pytest command exited with code 0 after passing tests, then emitted a non-blocking Windows pytest temp cleanup `PermissionError` for `pytest-current`.
- The first manual-safe inline runner attempt failed before exercising scenarios because `PYTHONPATH=src` was missing; rerun with `PYTHONPATH=src` passed.
