# Final Telegram Product Smoke

Date: 2026-05-13

Scope: final Telegram product smoke/check slice for `C:\Users\adck8\Documents\New project 2 CLEAN`. No push and no real YooKassa or Telegram Stars payment was performed.

## Commits / Range Covered

- Branch at start: `codex/emergency-stabilization...origin/codex/emergency-stabilization [ahead 49]`.
- HEAD at start: `cd5148c ux: rename shopping list label`.
- Recent recovery range visible in `git log --oneline --decorate --max-count=20`: `b751e35` through `cd5148c`, including recipe quality, nutrition floors, PDF polish, Telegram UX, promo/payment/admin panel, and shopping list label work.
- Smoke found one explicit blocker in recipe repeat generation: `tests/test_safety_and_builder.py::test_five_repeat_generations_keep_key_meals_unique`.
- Minimal blocker fix applied during smoke: `src/diet_bot/builder.py` main-protein rotation weights changed from `1.35/0.65` to `2.40/0.35`. This made the run no longer docs-only.
- Code-fix commit: `e339b35 recipe quality: fix final smoke repeat blocker`.

## Baseline Checks

- `git status --short --branch`
  - Result at start: clean branch, ahead 49.
  - Result after smoke: `src/diet_bot/builder.py` modified and this document added.
- `git log --oneline --decorate --max-count=20`
  - Head entries included `cd5148c`, `6ffbec4`, `b410e04`, `484418f`, `3e73d41`, `3e74d2c`, `a69ddb6`, `fb16b64`, `02a88ef`, `7ebd8c3`, `302504e`, `7668531`, `97dbd26`, `a64eb9`, `b751e35`.
- Bot process check before launch initially found two `diet_bot.telegram_app` processes. Both were stopped before controlled launch.
- Controlled launch first showed the Windows venv redirector parent plus real Python child. Bot was restarted directly with the base Python interpreter and `.venv\Lib\site-packages` on `PYTHONPATH`.
- Final live bot process check: one `python.exe -B -m diet_bot.telegram_app` process, PID `6528`.

## Strict Healthcheck

Command:

```powershell
$env:PYTHONPATH='src'
$env:DIET_BOT_ENV='production'
$env:DIET_BOT_DATABASE_URL='postgresql://diet_bot@localhost:5432/diet_bot_test'
$env:DIET_BOT_TESTER_CHAT_IDS=''
.\.venv\Scripts\python.exe -B -m diet_bot.healthcheck --strict
```

Result: `healthcheck: ok`.

## Focused Test Commands

Telegram UX:

```powershell
$env:DIET_BOT_TESTER_CHAT_IDS=''
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests\test_telegram_app_photos.py tests\test_telegram_app_runtime.py tests\test_questionnaire_and_presentation.py -k "start or plan or profile or questionnaire or answer or selected or cancel or shopping or welcome or subscriber_cabinet or trial or test_access_off" --durations=10
```

Result: `54 passed, 93 deselected`.

Recipe quality / builder:

```powershell
$env:DIET_BOT_TESTER_CHAT_IDS=''
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests\test_safety_and_builder.py tests\test_curated_recipe_data.py tests\test_calculator.py tests\test_vectors_and_shopping.py --durations=10
```

Initial result: `1 failed, 63 passed` on repeat lunch uniqueness.
After blocker fix: `64 passed`.

PDF:

```powershell
$env:DIET_BOT_TESTER_CHAT_IDS=''
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests\test_pdf_renderer.py tests\test_pdf_limits_smoke.py --durations=10
```

Result: `27 passed`.

Promo/payment without real payment:

```powershell
$env:DIET_BOT_TESTER_CHAT_IDS=''
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests\test_promo_codes.py tests\test_payments_model.py tests\test_subscriptions.py tests\test_telegram_app_photos.py -k "promo or discount or paywall or pre_checkout or successful_payment or invoice or yookassa or stars or payment or subscriber_cabinet or subscription" --durations=10
```

Result: `168 passed, 46 deselected`.

Storage lifecycle / local Postgres:

```powershell
$env:DIET_BOT_TESTER_CHAT_IDS=''
$env:DIET_BOT_TEST_DATABASE_URL='postgresql://diet_bot@localhost:5432/diet_bot_test'
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --require-postgres tests\test_storage_contract.py tests\test_storage_config.py tests\test_json_storage.py tests\test_postgres_migrations.py tests\test_postgres_store.py tests\test_json_to_postgres_migration.py tests\test_postgres_test_lane.py --durations=10
```

Result: `49 passed`.

## Local Bot Launch

Command shape, with token inherited from env and not printed:

```powershell
$env:PYTHONPATH='src;.venv\Lib\site-packages'
$env:PYTHONIOENCODING='utf-8'
$env:DIET_BOT_ENV='production'
$env:DIET_BOT_DATABASE_URL='postgresql://diet_bot@localhost:5432/diet_bot_test'
$env:DIET_BOT_TESTER_CHAT_IDS=''
Start-Process -FilePath 'C:\Users\adck8\AppData\Local\Programs\Python\Python312\python.exe' -ArgumentList @('-B','-m','diet_bot.telegram_app') -WorkingDirectory (Get-Location) -WindowStyle Hidden
```

Telegram Bot API `getMe` result: ok, bot username `FoodbalanceRu_bot`.

Live bot logs:

- `tmp/final_smoke_bot.out.log`
- `tmp/final_smoke_bot.err.log`

Both were empty immediately after startup check.

## Manual Telegram Checks

Codex could not perform manual Telegram clicks through a user-client from this environment because no Telegram client/account is available in Codex. The bot was started and reachable through Bot API, but `/start`, button taps, PDF receipt, and admin/non-admin UI checks require a Telegram user client/account.

Manual checklist status:

- `/start` with saved questionnaire shows calculation: not manually executed by Codex; automated UX coverage passed.
- `/plan` shows calculation: not manually executed by Codex; automated UX coverage passed.
- Questionnaire is saved clearly: not manually executed by Codex; automated UX coverage passed.
- Selected answers show `✅`: not manually executed by Codex; automated UX coverage passed.
- `/cancel` text is clear: not manually executed by Codex; automated UX coverage passed.
- One-day ration generation has no obvious repeats/weird foods and protein/KBJU are acceptable: not manually executed in Telegram; recipe/builder bundle passed after blocker fix.
- Weekly PDF is received and visually current: not manually executed in Telegram; PDF renderer and PDF delivery-limit tests passed.
- `🛒 Список продуктов` label is used: not manually executed in Telegram; focused UX/presentation tests passed.
- Paywall appears after free trial: not manually executed in Telegram; paywall/subscription tests passed with `DIET_BOT_TESTER_CHAT_IDS` empty.
- Discount promo invoice creation without real payment: not manually executed live. Automated fake/mock invoice tests passed. Live YooKassa invoice creation could not be verified because `TELEGRAM_PROVIDER_TOKEN` was not set.
- Monthly access promo via hidden admin panel creates and activates: not manually executed in Telegram; automated admin/promo tests passed.
- Discount promo via hidden admin panel create/list/disable: not manually executed in Telegram; automated promo/payment tests passed.
- Non-admin does not see admin panel: not manually executed in Telegram; automated non-admin tests passed.

## Limitations

- No real YooKassa payment was performed.
- No real Telegram Stars payment was performed.
- True manual Telegram user-client clicks/checks were not completed by Codex because no Telegram user client/account is available in this environment.
- Live YooKassa discounted invoice creation was not verified because `TELEGRAM_PROVIDER_TOKEN` was absent.
- Several successful pytest runs exited with code 0 and then emitted the known Windows pytest temp cleanup `PermissionError` for `pytest-current`.

## Known Issues

- The smoke found and fixed a recipe repeat blocker in main-meal rotation. Final recipe/builder tests passed after the fix.
- Because a code blocker fix was applied, this was not a docs-only update. The requested docs-only commit condition does not apply as-is.
