# Controlled Pilot Release Smoke - 2026-05-15

Final targeted release smoke for controlled pilot.

- Workspace: `C:\Users\adck8\Documents\New project 2 CLEAN`
- Branch: `codex/emergency-stabilization`
- Commit: `3130bf5`
- Timestamp: `2026-05-15 21:52:14 +04:00`
- Mode: controlled pilot
- Payment safety: `DIET_BOT_PUBLIC_PAYMENTS_ENABLED=0`
- Real payments: not run

## Automated Smoke Results

All listed PASS results are from fresh commands run in this workspace.

### Pytest Collection

Status: PASS

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest --collect-only -q
```

Result: `555 tests collected in 6.13s`.

### Config Tests

Status: PASS

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_runtime_config.py tests/test_storage_config.py tests/test_healthcheck.py
```

Result: `30 passed in 4.53s`.

### Telegram Runtime Tests

Status: PASS

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_telegram_app_runtime.py
```

Result: `49 passed in 4.94s`.

### Promo Tests

Status: PASS

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_promo_codes.py
```

Result: `9 passed in 0.12s`.

### Payment-Hidden / Pilot-Mode Tests

Status: PASS

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_telegram_app_runtime.py -k "public_payment or payment_keyboard"
```

Result: `10 passed, 39 deselected in 3.87s`.

### Payment Model / Subscription Safety Tests

Status: PASS

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_payments_model.py tests/test_subscriptions.py
```

Result: `109 passed in 0.23s`.

### Postgres / Storage Smoke

Status: PASS for non-DB storage smoke; SKIPPED for local Postgres integration.

Local DB availability check:

```powershell
if ($env:DIET_BOT_TEST_DATABASE_URL) { 'DIET_BOT_TEST_DATABASE_URL=set' } else { 'DIET_BOT_TEST_DATABASE_URL=<not set>' }
```

Result: `DIET_BOT_TEST_DATABASE_URL=<not set>`.

Storage smoke command:

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_postgres_test_lane.py tests/test_postgres_migrations.py tests/test_storage_contract.py tests/test_json_storage.py tests/test_json_to_postgres_migration.py
```

Result: `18 passed, 1 skipped in 0.58s`.

Known limitation: true PostgreSQL integration tests were not run because `DIET_BOT_TEST_DATABASE_URL` was not set.

### Curated Recipe Data Tests

Status: PASS

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_curated_recipe_data.py
```

Result: `27 passed in 110.76s`.

### Planner / Scaling / Weekly Selector Tests

Status: PASS for targeted release smoke.

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_calculator.py tests/test_recipe_portion_scaling.py tests/test_recipe_effort_slot_coverage.py tests/test_weekly_selector_scoring.py tests/test_weekly_optimizer_candidates.py tests/test_vectors_and_shopping.py
```

Result: `46 passed in 26.98s`.

Additional targeted safety-builder stabilization slice:

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_safety_and_builder.py -k "weekly_plan_success_contains_no_empty_days or low_weight_simple_weekly_seed101_has_no_collapsed_meals_and_keeps_protein_floor or weekly_infeasible_pool_returns_controlled_failure_not_partial_success or same_recipe_id_is_not_reused_across_week_slots_when_alternatives_exist or protein_top_up_reaches_95_percent_floor_when_feasible or recipe_builder_returns_controlled_empty_status_when_protein_floor_is_infeasible or hard_valid_candidate_scoring_prefers_best_macro_fit or exclusion_infeasible_case_returns_controlled_empty_plan_not_unsafe_ration"
```

Result: `8 passed, 81 deselected in 147.94s`.

Known limitation: full `tests/test_safety_and_builder.py` was attempted separately and timed out before producing pytest result output.

Timed-out commands:

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_calculator.py tests/test_recipe_portion_scaling.py tests/test_recipe_effort_slot_coverage.py tests/test_weekly_selector_scoring.py tests/test_weekly_optimizer_candidates.py tests/test_safety_and_builder.py tests/test_vectors_and_shopping.py
```

Result: command timeout after about 604s.

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_safety_and_builder.py
```

Result: command timeout after about 1204s.

### PDF Targeted Smoke

Status: PASS

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_pdf_renderer.py tests/test_pdf_limits_smoke.py
```

Result: `27 passed in 64.75s`.

### Photo / Empty Image URL Smoke

Status: PASS

```powershell
$py = ".\.venv\Scripts\python.exe"; $env:PYTHONPATH = "src"; $env:DIET_BOT_ENV = "development"; $env:DIET_BOT_ALLOW_JSON_STORAGE = "1"; $env:DIET_BOT_PUBLIC_PAYMENTS_ENABLED = "0"; & $py -m pytest -q -p no:cacheprovider tests/test_telegram_app_photos.py tests/test_pdf_renderer.py tests/test_curated_recipe_data.py -k "photo_input or long_meal_card_sends_photo or welcome_photo or local_meal_photo or ignores_missing_meal_photo or meal_photo_white_border or cleaned_intake_recipes_are_imported_with_required_metadata or curated_only_plan_uses_only_table_recipes_and_local_photos"
```

Result: `9 passed, 138 deselected in 62.70s`.

## Manual Telegram Smoke Checklist

Status: DESCRIBED, not executed in this local pass. No real payments were run.

Run against the controlled pilot bot with `DIET_BOT_PUBLIC_PAYMENTS_ENABLED=0` and no live payment checkout:

- `/start` as a new user: expect welcome flow and usable buttons.
- Complete questionnaire: sex, age, height, weight, goal, activity, meal count, allergies/restrictions, excluded foods; expect calculation summary and plan buttons.
- `/cancel` during an active state: expect active input state to clear while saved profile remains available.
- `/plan`: expect plan calculation flow to start and return a one-day ration with meals, portions, totals, and shopping list.
- `Ввести промокод`: enter a valid monthly-access pilot/admin code; expect monthly access to be granted.
- Invalid promo: enter an invalid code; expect retry state and clear `/cancel` guidance, with no access grant.
- Weekly PDF generation: with promo/admin/test access, request weekly ration; expect a PDF document attachment and no text weekly-menu fallback.
- Public payment buttons hidden in pilot mode: open subscription/paywall paths; expect promo access text and no YooKassa/card or Telegram Stars invoice buttons.

## Known Limitations

- Local Postgres integration smoke was skipped because `DIET_BOT_TEST_DATABASE_URL` was not configured.
- Full `tests/test_safety_and_builder.py` did not complete within the local timeout; targeted planner/safety stabilization tests passed.
- Some passing pytest commands printed a Windows pytest cleanup warning after completion: `PermissionError` on `%TEMP%\pytest-of-adck8\pytest-current`. The pytest exit code was `0` and the PASS line was printed before the cleanup warning.
- Photos `r401-r610` are still absent by design/current data state; empty or missing image handling was covered by targeted tests.
- Paid public launch remains blocked/disabled. Public payments must stay disabled unless explicitly enabled and separately payment-smoked.

## Release Recommendation

Recommendation: READY for controlled pilot based on targeted automated smoke, with public payments disabled and promo/admin access as the access path.

Not recommended for public paid launch. Enabling public YooKassa/Stars payments still requires explicit approval, live/test-provider payment smoke, and recorded evidence.
