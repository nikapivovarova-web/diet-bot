# Emergency Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the clean FoodBalance branch with minimal runtime/config guards, a local healthcheck, a safe env example, and Telegram startup sanity tests without pulling in Postgres, payments, or PDF redesign.

**Architecture:** Keep the phase deliberately small: add one focused runtime config module, one focused healthcheck module, one env example, and tiny testable seams around Telegram startup. The existing `src/diet_bot/telegram_app.py` should only be touched around imports and `run_bot` startup/polling, never copied wholesale.

**Tech Stack:** Python 3.11, aiogram 3.x, pytest, PowerShell on Windows.

---

## Hard Boundaries

- Work only in `C:\Users\adck8\Documents\New project 2 CLEAN`.
- Do not read, edit, copy from, or run tooling out of `C:\Users\adck8\Documents\New project 2` during this phase.
- Do not copy the old `telegram_app.py`.
- Do not add Postgres dependencies, storage migration, payment/refund logic, Docker/CI, or PDF redesign.
- Keep every implementation slice working after its targeted tests and full test suite.
- Do not stage, commit, push, or open a PR unless the user explicitly asks. Commit boundaries below are the planned boundaries for later authorized commits.

## Preflight Commands

Run these before any implementation slice:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
git status --short --branch
git branch --show-current
```

Expected:

```text
## codex/emergency-stabilization
codex/emergency-stabilization
```

Use a clean-local virtualenv so the old folder is not touched:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
if (!(Test-Path ".\.venv\Scripts\python.exe")) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Expected test result should stay equivalent to the clean baseline: all current tests pass. If the full suite fails before code changes, stop and diagnose baseline instead of starting this phase.

## Exact Files To Touch

Create:

- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\runtime_config.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\healthcheck.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\.env.example`
- `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_runtime_config.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_healthcheck.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_env_example.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_telegram_startup.py`

Modify:

- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\telegram_app.py`

Do not modify in this phase:

- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\payments.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\subscriptions.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\pdf_renderer.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\data\*`
- `C:\Users\adck8\Documents\New project 2 CLEAN\pyproject.toml`
- `C:\Users\adck8\Documents\New project 2 CLEAN\.github\*`

## Task 1: Minimal Runtime Config Guard

**Purpose:** Make startup config explicit and testable before Telegram polling starts.

**Files:**

- Create: `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\runtime_config.py`
- Create: `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_runtime_config.py`
- Modify later in Task 4 only: `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\telegram_app.py`

**Behavior to implement:**

- A small `RuntimeConfigError` exception for clear operator-facing failures.
- A small config loader that reads from a provided mapping, defaulting to `os.environ`.
- Token lookup must preserve current behavior: `DIET_BOT_TOKEN` first, then `TELEGRAM_BOT_TOKEN`.
- Missing startup token must produce the current clear message: `Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN.`
- Local/dev mode remains simple and supports the current JSON state files.
- Production mode must not silently run on JSON state. In this clean branch, `DIET_BOT_ENV=production` should fail with a clear message explaining that production durable storage is not implemented in this phase.
- Optional settings must not break import or local startup when absent:
  - `TELEGRAM_PROVIDER_TOKEN`
  - `DIET_BOT_SUPPORT_CHAT_ID`
  - `DIET_BOT_ADMIN_USER_IDS`
  - `DIET_BOT_TESTER_CHAT_IDS`
  - `DIET_BOT_STATE_FILE`
  - `DIET_BOT_SUBSCRIPTIONS_STATE_FILE`
  - `DIET_BOT_PROMO_CODES_STATE_FILE`
- Do not introduce `DATABASE_URL`, Postgres clients, storage adapters, or payment config validation in this task.

**Tests to add:**

- `test_runtime_config_prefers_diet_bot_token_over_legacy_alias`
- `test_runtime_config_accepts_legacy_telegram_bot_token`
- `test_runtime_config_requires_token_for_startup`
- `test_runtime_config_allows_local_mode_without_production_storage`
- `test_runtime_config_rejects_production_mode_in_clean_runtime`
- `test_runtime_config_parses_admin_and_tester_ids_without_crashing_on_invalid_values`
- `test_runtime_config_optional_provider_token_defaults_to_empty_string`

**Steps:**

- [ ] Write `tests/test_runtime_config.py` with the test names above and no dependency on real environment variables.
- [ ] Run the new targeted test file and confirm it fails because `diet_bot.runtime_config` does not exist yet.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_runtime_config.py
```

Expected: fail during import of `diet_bot.runtime_config`.

- [ ] Create `src/diet_bot/runtime_config.py` with only the config parsing and validation needed by these tests.
- [ ] Re-run the targeted test file.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_runtime_config.py
```

Expected: `tests/test_runtime_config.py` passes.

- [ ] Run the existing Telegram tests to prove imports and existing constants still behave.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_telegram_app_photos.py
```

Expected: `tests/test_telegram_app_photos.py` passes.

- [ ] Run the full current suite.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Expected: full suite passes.

**Planned commit boundary:** `stabilization: add minimal runtime config guard`

## Task 2: Minimal Healthcheck

**Purpose:** Add a fast, local-only healthcheck that can verify package data and config safety without calling Telegram, Postgres, payment providers, or OpenAI.

**Files:**

- Create: `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\healthcheck.py`
- Create: `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_healthcheck.py`
- Uses: `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\runtime_config.py`

**Behavior to implement:**

- `python -m diet_bot.healthcheck --package-data-only` checks only package/import readiness and required local assets.
- Default `python -m diet_bot.healthcheck` checks package data plus the runtime config guard.
- No external network calls.
- No Telegram `Bot` construction.
- No Postgres connection attempt.
- No payment provider validation.
- Required package data checks:
  - `src/diet_bot/data/curated_foods.json`
  - `src/diet_bot/data/curated_recipes.json`
  - `src/diet_bot/data/curated_recipe_ingredients.json`
  - `src/diet_bot/data/curated_recipe_nutrition.json`
  - `src/diet_bot/data/welcome_foodbalance.png`
- Success output should be short and stable: `healthcheck: ok`.
- Failure output should start with `healthcheck:` and include the config or missing-asset message.

**Tests to add:**

- `test_package_data_healthcheck_ok_without_external_services`
- `test_healthcheck_reports_missing_required_package_data`
- `test_healthcheck_cli_package_data_only_exits_zero`
- `test_healthcheck_cli_default_reuses_runtime_config_guard`
- `test_healthcheck_cli_failure_message_starts_with_healthcheck_prefix`

**Steps:**

- [ ] Write `tests/test_healthcheck.py` against public functions and CLI behavior.
- [ ] Run the targeted healthcheck tests and confirm they fail because `diet_bot.healthcheck` does not exist yet.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_healthcheck.py
```

Expected: fail during import of `diet_bot.healthcheck`.

- [ ] Create `src/diet_bot/healthcheck.py` with package-data checks and CLI argument handling.
- [ ] Run targeted tests.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_healthcheck.py
```

Expected: `tests/test_healthcheck.py` passes.

- [ ] Run the package-data-only CLI.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m diet_bot.healthcheck --package-data-only
```

Expected:

```text
healthcheck: ok
```

- [ ] Run default healthcheck in explicit local mode.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
$env:DIET_BOT_ENV = "local"
.\.venv\Scripts\python.exe -B -m diet_bot.healthcheck
Remove-Item Env:\DIET_BOT_ENV
```

Expected:

```text
healthcheck: ok
```

- [ ] Run runtime config and healthcheck tests together.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_runtime_config.py tests/test_healthcheck.py
```

Expected: both targeted files pass.

- [ ] Run the full current suite.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Expected: full suite passes.

**Planned commit boundary:** `stabilization: add minimal local healthcheck`

## Task 3: Safe Env Example

**Purpose:** Provide a safe, copyable local env template that documents the current clean runtime without leaking secrets or pretending production/Postgres is ready.

**Files:**

- Create: `C:\Users\adck8\Documents\New project 2 CLEAN\.env.example`
- Create: `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_env_example.py`

**Behavior/content to implement:**

- The file must be safe to commit.
- The file must not contain real-looking secrets.
- It must show local mode explicitly:
  - `DIET_BOT_ENV=local`
  - `DIET_BOT_TOKEN=replace-with-telegram-bot-token`
  - `TELEGRAM_PROVIDER_TOKEN=`
  - `DIET_BOT_SUPPORT_CHAT_ID=`
  - `DIET_BOT_ADMIN_USER_IDS=`
  - `DIET_BOT_TESTER_CHAT_IDS=`
  - `DIET_BOT_STATE_FILE=.diet_bot_state/history.json`
  - `DIET_BOT_SUBSCRIPTIONS_STATE_FILE=.diet_bot_state/subscriptions.json`
  - `DIET_BOT_PROMO_CODES_STATE_FILE=.diet_bot_state/promo_codes.json`
- It must state that production mode is intentionally blocked in this clean branch until the storage phase lands.
- It must not include Postgres URL examples, payment webhook secrets, Docker config, or PDF settings in this phase.

**Tests to add:**

- `test_env_example_exists_and_is_committable`
- `test_env_example_documents_local_mode`
- `test_env_example_does_not_include_real_telegram_token_shape`
- `test_env_example_does_not_document_postgres_or_payment_webhook_settings`
- `test_env_example_matches_runtime_config_required_token_names`

**Steps:**

- [ ] Write `tests/test_env_example.py` first.
- [ ] Run it and confirm it fails because `.env.example` does not exist.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_env_example.py
```

Expected: fail with `.env.example` missing.

- [ ] Create `.env.example` with only the safe local runtime keys listed above.
- [ ] Run targeted env example tests.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_env_example.py
```

Expected: `tests/test_env_example.py` passes.

- [ ] Run config, healthcheck, and env tests together.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_runtime_config.py tests/test_healthcheck.py tests/test_env_example.py
```

Expected: all targeted config files pass.

- [ ] Run the full current suite.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Expected: full suite passes.

**Planned commit boundary:** `stabilization: add safe local env example`

## Task 4: Telegram Startup And Polling Sanity Checks

**Purpose:** Verify the bot fails before network startup when config is bad, starts polling through the expected dispatcher when config is good, and closes its bot session on polling exit/error.

**Files:**

- Modify: `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\telegram_app.py`
- Create: `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_telegram_startup.py`
- Re-run existing: `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_telegram_app_photos.py`

**Behavior to implement:**

- `run_bot` should use the runtime config guard for token/startup validation.
- Missing token should fail before constructing `aiogram.Bot`.
- Production mode rejection should fail before constructing `aiogram.Bot`.
- The polling startup order should remain:
  - validate config;
  - construct bot;
  - set bot commands;
  - create dispatcher;
  - start polling.
- Tests should use fake bot and fake dispatcher objects; they must not contact Telegram.
- Add only the smallest dependency-injection seam needed to test startup order.
- Ensure the bot session is closed when polling exits or raises.
- Do not change handlers, payment behavior, subscription rules, PDF generation, or message texts.

**Tests to add:**

- `test_run_bot_requires_token_before_constructing_bot`
- `test_run_bot_rejects_production_mode_before_constructing_bot`
- `test_run_bot_sets_commands_before_starting_polling`
- `test_run_bot_starts_polling_with_created_dispatcher`
- `test_run_bot_closes_bot_session_when_polling_raises`

**Steps:**

- [ ] Write `tests/test_telegram_startup.py` using fake bot and dispatcher classes.
- [ ] Run the targeted startup tests and confirm they fail against current `run_bot`.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_telegram_startup.py
```

Expected: fail because `run_bot` has no test seam and still reads raw env directly.

- [ ] Modify only the import section and `run_bot` in `src/diet_bot/telegram_app.py`.
- [ ] Run targeted startup tests.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_telegram_startup.py
```

Expected: `tests/test_telegram_startup.py` passes.

- [ ] Run the existing command-registration test area.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_telegram_app_photos.py::test_set_bot_commands_registers_start_menu_commands
```

Expected: command registration still passes.

- [ ] Run the full Telegram behavior file.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_telegram_app_photos.py
```

Expected: existing Telegram tests pass.

- [ ] Run all phase-1 targeted tests together.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_runtime_config.py tests/test_healthcheck.py tests/test_env_example.py tests/test_telegram_startup.py tests/test_telegram_app_photos.py
```

Expected: all targeted phase-1 tests pass.

- [ ] Run the full current suite.

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Expected: full suite passes.

**Planned commit boundary:** `stabilization: add telegram startup polling sanity checks`

## Final Verification For Phase 1

After all four implementation tasks:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
git status --short --branch
git diff --stat
git diff --check
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_runtime_config.py tests/test_healthcheck.py tests/test_env_example.py tests/test_telegram_startup.py tests/test_telegram_app_photos.py
.\.venv\Scripts\python.exe -B -m diet_bot.healthcheck --package-data-only
$env:DIET_BOT_ENV = "local"
.\.venv\Scripts\python.exe -B -m diet_bot.healthcheck
Remove-Item Env:\DIET_BOT_ENV
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Expected:

- `git diff --check` exits cleanly.
- Targeted phase-1 tests pass.
- `python -m diet_bot.healthcheck --package-data-only` prints `healthcheck: ok`.
- Default healthcheck in local mode prints `healthcheck: ok`.
- Full test suite passes.
- `git status --short --branch` shows only phase-1 files plus pre-existing docs files, with no data/assets/payment/PDF/Postgres changes.

## Planned Commit Boundaries

Use these boundaries only after explicit user approval to commit:

1. `stabilization: add minimal runtime config guard`
   - `src/diet_bot/runtime_config.py`
   - `tests/test_runtime_config.py`

2. `stabilization: add minimal local healthcheck`
   - `src/diet_bot/healthcheck.py`
   - `tests/test_healthcheck.py`

3. `stabilization: add safe local env example`
   - `.env.example`
   - `tests/test_env_example.py`

4. `stabilization: add telegram startup polling sanity checks`
   - `src/diet_bot/telegram_app.py`
   - `tests/test_telegram_startup.py`

Do not combine these into one commit unless the user explicitly asks for a single squashed commit.

## First Small Implementation Task

Start with only Task 1:

- [ ] Confirm clean branch and status.
- [ ] Ensure clean-local `.venv` exists and current suite passes.
- [ ] Add `tests/test_runtime_config.py` with the runtime config guard tests.
- [ ] Run `tests/test_runtime_config.py` and confirm it fails because the module does not exist.
- [ ] Add only `src/diet_bot/runtime_config.py`.
- [ ] Run `tests/test_runtime_config.py`.
- [ ] Run `tests/test_telegram_app_photos.py`.
- [ ] Run the full suite.
- [ ] Stop for review before Task 2.

## Self-Review

- Spec coverage: covers minimal runtime config guard, minimal healthcheck, safe env example, Telegram startup/polling sanity checks, tests for each change, exact files, exact commands, and commit boundaries.
- Scope check: excludes old folder reads, Postgres, payments, PDF redesign, Docker/CI, wholesale `telegram_app.py`, data/assets, and cleanup.
- Placeholder scan: no unresolved placeholders are required for execution; all task names, files, commands, and expected outcomes are explicit.
