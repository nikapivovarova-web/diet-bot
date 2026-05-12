# AI Handoff

Дата handoff: 2026-05-12.

Этот документ нужен новому Codex-диалогу, чтобы продолжить работу без потери контекста. Важно: текущая стратегия изменилась. Старую ветку с большим смешанным diff больше не чиним как единый PR. Она считается складом запчастей. Новая рабочая ветка создана отдельно и должна наполняться маленькими безопасными изменениями.

## 1. Главная цель проекта

Приложение: Telegram diet bot / FoodBalance.

Что делает бот:

- ведет пользователя через анкету;
- рассчитывает нутриционные цели;
- генерирует рацион на день;
- генерирует недельный рацион и PDF;
- показывает блюда, ингредиенты, shopping list;
- поддерживает подписки, лимиты, promo codes и платные extras;
- в новых незавершенных изменениях также добавлены PostgreSQL storage, migration from JSON, payment events, refund/chargeback/reconciliation, production healthcheck, Docker/CI, Telegram runtime hardening.

Основная проблема сейчас:

- в старой рабочей папке `C:\Users\adck8\Documents\New project 2` накопилась большая смешанная куча изменений;
- в одной ветке одновременно оказались PDF redesign, Postgres/storage, payments/refunds, production deploy/healthcheck, Telegram polling/runtime, analytics, nutrition data changes, tests и cleanup;
- из-за этого исправление одной ошибки проявляло новые ошибки в соседнем слое;
- ощущение "починили 10, появилось 20" возникло потому, что менялись сразу runtime, storage, payments, tests и production config.

Желаемый финальный результат:

- не спасать старую ветку как один огромный PR;
- сохранить ее как источник хороших фрагментов;
- продолжать в чистой ветке `codex/emergency-stabilization`;
- переносить изменения маленькими тематическими PR:
  1. emergency stabilization;
  2. tests/CI separation;
  3. PDF;
  4. Telegram runtime;
  5. storage/Postgres;
  6. payments;
  7. data/nutrition;
  8. cleanup/hygiene.

Главное правило: перед каждым переносом спрашивать: "Если после этого сломается приложение, будет ли сразу понятно, что виноват именно этот маленький кусок?" Если нет, кусок слишком большой.

## 2. Текущее состояние репозитория

Есть две важные папки.

### Старая папка, склад запчастей

Путь:

```powershell
C:\Users\adck8\Documents\New project 2
```

Ветка:

```text
pdf-redesign-weekly-ration
```

Состояние:

- очень грязное рабочее дерево;
- staged changes нет;
- есть tracked changes, deleted files и много untracked files;
- также созданы backup-файлы:
  - `rescue-status.txt`;
  - `rescue-tracked.patch`;
  - `rescue-untracked-files.txt`;
- пользователь также сделал физическую копию всей папки в другое место.

Основные группы старых изменений:

- PDF redesign:
  - `src/diet_bot/pdf_renderer.py`;
  - `tests/test_pdf_renderer.py`;
  - PDF assets.
- Production/runtime/deploy:
  - `.env.example`;
  - `.dockerignore`;
  - `Dockerfile`;
  - `docker-compose.yml`;
  - `.github/workflows/*`;
  - `src/diet_bot/healthcheck.py`;
  - `src/diet_bot/runtime_config.py`;
  - `src/diet_bot/analytics.py`;
  - docs/runbook.
- Storage/Postgres/migration:
  - `src/diet_bot/postgres_store.py`;
  - `src/diet_bot/postgres_migrations.py`;
  - `src/diet_bot/json_storage.py`;
  - `scripts/migrate_json_to_postgres.py`;
  - `tests/test_postgres_store.py`;
  - `tests/test_json_to_postgres_migration.py`.
- Payments/subscriptions:
  - `src/diet_bot/payments.py`;
  - `src/diet_bot/subscriptions.py`;
  - payment sections inside `src/diet_bot/telegram_app.py`;
  - `tests/test_payments_smoke.py`;
  - updated `tests/test_subscriptions.py`.
- Telegram runtime:
  - major changes in `src/diet_bot/telegram_app.py`;
  - `src/diet_bot/state_cache.py`;
  - `src/diet_bot/telegram_rate_limit.py`;
  - runtime tests.
- Nutrition/data:
  - `src/diet_bot/builder.py`;
  - `src/diet_bot/chef.py`;
  - `src/diet_bot/curated_data.py`;
  - `src/diet_bot/questionnaire.py`;
  - `src/diet_bot/safety.py`;
  - large JSON files under `src/diet_bot/data/`.
- Cleanup/hygiene:
  - many root helper scripts deleted;
  - `.gitignore` updated;
  - README/docs updated.

Do not continue coding directly in the old folder unless explicitly instructed. Treat it as read-only source material.

### Новая clean-папка, текущая рабочая ветка

Путь:

```powershell
C:\Users\adck8\Documents\New project 2 CLEAN
```

Ветка:

```text
codex/emergency-stabilization
```

Создана командой:

```powershell
git worktree add "..\New project 2 CLEAN" -b codex/emergency-stabilization c4fa144
```

База:

```text
c4fa144 Backup current diet bot project state
```

Текущее состояние clean worktree на момент создания handoff:

```text
## codex/emergency-stabilization
 M .gitignore
?? docs/AI_HANDOFF.md
```

Staged:

- ничего не staged.

Unstaged:

- `.gitignore` изменен;
- `docs/AI_HANDOFF.md` создан этим handoff-шагом.

Какие изменения уже внесены в clean worktree:

- в `.gitignore` добавлена строка:

```text
.claude/
```

Зачем:

- чтобы локальная папка `.claude/` не попадала в git status;
- это безопасный hygiene-микрошаг, не влияющий на runtime.

Какие изменения нельзя откатывать без явного решения пользователя:

- не трогать и не удалять старую папку `C:\Users\adck8\Documents\New project 2`;
- не удалять rescue-файлы в старой папке;
- не удалять физическую копию проекта, сделанную пользователем;
- не делать reset/checkout старой ветки;
- не переносить весь старый `telegram_app.py` целиком;
- не копировать старую папку `tests` целиком;
- не делать `git add`, `commit`, `push`, пока пользователь явно не попросит.

## 3. Что уже было исправлено

В clean worktree исправлено только одно:

1. `.gitignore`

Файл:

```text
C:\Users\adck8\Documents\New project 2 CLEAN\.gitignore
```

Изменение:

```diff
 .diet_bot_state/
 .playwright-cli/
 .superpowers/
+.claude/
 node_modules/
```

Почему нужно:

- в старой папке `.claude/` была локальной служебной директорией;
- она не должна попадать в git status и будущие PR;
- это маленькое безопасное изменение для новой чистой ветки.

Других кодовых исправлений в clean worktree не было.

Процедурные действия, которые уже выполнены:

- старая смешанная папка сохранена пользователем физически;
- в старой папке созданы:
  - `rescue-status.txt`;
  - `rescue-tracked.patch`;
  - `rescue-untracked-files.txt`;
- создан отдельный clean worktree;
- clean base протестирована;
- после `.gitignore`-изменения тесты снова прошли.

## 4. Какие проблемы остаются

### Фактические проблемы

1. Старая ветка слишком смешанная.

Симптом:

- невозможно безопасно понять, какая правка сломала запуск или тест;
- в одной ветке смешаны runtime, payments, storage, PDF, tests, CI, data и cleanup.

2. Старый fast suite стал тяжелым.

Факт из аудита старой папки:

```text
319 passed, 32 deselected in 242.36s (0:04:02)
```

Ранний запуск с timeout 3 минуты оборвался, но затем полный fast suite прошел за 4:02. Это не доказанный hang, а недостаточный timeout плюс тяжелые тесты.

3. В clean base тесты проходят, но долго.

Факт:

```text
133 passed in 330.37s (0:05:30)
```

После `.gitignore`:

```text
133 passed in 308.82s (0:05:08)
```

4. При последнем clean test run был post-test Windows warning:

```text
Exception ignored in atexit callback ... PermissionError: [WinError 5]
C:\Users\adck8\AppData\Local\Temp\pytest-of-adck8\pytest-current
```

Это произошло после успешного `133 passed`. Не считается падением тестов, но новый Codex должен помнить, что на Windows pytest cleanup может шуметь.

### Подозрения из аудита старой папки

1. Runtime hangs возможны не из-за явных infinite loops, а из-за ожиданий без deadline.

Подозрительные места в старой папке:

- `src/diet_bot/telegram_app.py`: `_run_storage_io()` uses `asyncio.to_thread()` without upper timeout;
- `src/diet_bot/postgres_store.py`: sync Postgres client has `connect_timeout`, but no `statement_timeout` / `lock_timeout`;
- `src/diet_bot/json_storage.py`: JSON file lock has no timeout;
- `src/diet_bot/telegram_rate_limit.py`: `TelegramRetryAfter.retry_after` can sleep without cap;
- `src/diet_bot/telegram_app.py`: polling heartbeat is written late in startup;
- `src/diet_bot/telegram_app.py`: one-day generation path still does CPU work inside async handler;
- `src/diet_bot/telegram_app.py`: analytics is awaited inline.

2. Storage/Postgres migration is not production-safe yet.

Known risks from old folder:

- `payment_events.json` is not migrated;
- processed charge aliases can be lost;
- dry-run migration does not verify existing rows when database URL is present;
- migration is not atomic across all imported state;
- JSON fallback has no durable generation lifecycle.

3. Payment/refund/chargeback logic needs separate review.

Known risks:

- refund/chargeback for subscription can cut off current access if it is not tied to the exact paid period;
- extra purchase is checked at pre-checkout and then again at successful_payment, possibly under different entitlement snapshots;
- orphan successful_payment and pending refund/reconciliation paths are fragile if payment ledger is incomplete.

4. PDF/generation:

- weekly PDF path was moved to threads in old code, but there is no global generation semaphore/deadline;
- real ReportLab rendering is sync;
- some heavy weekly/PDF workflow tests were in fast suite in the old folder.

## 5. Архитектурные решения, которые уже были приняты

Accepted decisions:

1. Do not continue fixing the old mixed branch as one PR.

Reason:

- too many unrelated risk areas are mixed;
- it creates a loop of cascading bugs.

2. Use old folder as source material only.

Reason:

- it contains useful fragments;
- but copying it wholesale would recreate the same problem.

3. Continue in clean worktree `New project 2 CLEAN`.

Reason:

- clean base is tested;
- branch is small and controllable.

4. Transfer changes in small thematic slices.

Recommended order:

1. hygiene guard / `.gitignore`;
2. emergency startup/runtime stabilization;
3. tests/CI separation;
4. PDF;
5. Telegram runtime;
6. storage/Postgres;
7. payments;
8. data/nutrition;
9. cleanup.

5. Do not copy entire large files unless absolutely necessary.

Especially do not copy whole:

- `src/diet_bot/telegram_app.py`;
- `src/diet_bot/payments.py`;
- `src/diet_bot/postgres_store.py`;
- entire `tests/` folder.

6. JSON fallback should remain dev-only when storage work is eventually reintroduced.

Reason:

- production state must be durable;
- fallback reads/writes can hide migration mistakes.

7. Payment ledger must be the source of truth before production storage migration.

Reason:

- duplicate payment, refund, chargeback and orphan successful_payment depend on complete event history.

Decisions not to do now:

- no big refactor as first step;
- no production PostgreSQL migration first;
- no payment business logic rewrite first;
- no PDF redesign first;
- no cleanup of deleted scripts first;
- no commit/push until explicitly requested.

## 6. Тесты и проверки

### Clean worktree commands already run

From:

```powershell
C:\Users\adck8\Documents\New project 2 CLEAN
```

Using old venv:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider
```

Result before `.gitignore` change:

```text
133 passed in 330.37s (0:05:30)
```

Result after `.gitignore` change:

```text
133 passed in 308.82s (0:05:08)
```

Status before handoff file:

```text
## codex/emergency-stabilization
 M .gitignore
```

Status after this handoff file should be:

```text
## codex/emergency-stabilization
 M .gitignore
?? docs/AI_HANDOFF.md
```

### Old mixed folder audit commands and results

From:

```powershell
C:\Users\adck8\Documents\New project 2
```

System Python failed because it did not know project dependencies:

```powershell
python -m diet_bot.healthcheck --package-data-only
```

Result:

```text
ModuleNotFoundError: No module named 'diet_bot'
```

```powershell
python -m pytest --collect-only -q -p no:cacheprovider
```

Result:

```text
No module named pytest
```

Using `.venv` worked:

```powershell
.\.venv\Scripts\python.exe -m pytest --version
```

Result:

```text
pytest 9.0.3
```

Package-data healthcheck:

```powershell
.\.venv\Scripts\python.exe -m diet_bot.healthcheck --package-data-only
```

Result:

```text
healthcheck: ok
```

Regular healthcheck without env:

```powershell
.\.venv\Scripts\python.exe -m diet_bot.healthcheck
```

Result:

```text
healthcheck: Set DIET_BOT_DATABASE_URL or DIET_BOT_ALLOW_JSON_STORAGE=1 for local JSON storage.
```

Collect-only in old mixed folder:

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q -p no:cacheprovider
```

Result:

```text
351 tests collected in 3.80s
```

Fast suite in old mixed folder:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration" --durations=10
```

Result:

```text
319 passed, 32 deselected in 242.36s (0:04:02)
```

Slow PDF/builder in old mixed folder:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider -m slow_pdf_builder --durations=10
```

Result:

```text
14 passed, 338 deselected in 254.37s (0:04:14)
```

Postgres integration without test DB:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider -m postgres_integration tests/test_postgres_store.py tests/test_json_to_postgres_migration.py
```

Result:

```text
19 skipped, 5 deselected in 3.29s
```

Git whitespace check in old folder:

```powershell
git diff --check
```

Result:

- exit code 0;
- only CRLF warnings.

### Fast/slow/integration classification from old audit

Fast PR gate in old proposed CI:

```powershell
python -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

Slow PDF/builder:

```powershell
python -m pytest -q -p no:cacheprovider -m slow_pdf_builder
```

Postgres integration:

```powershell
python -m pytest -q -p no:cacheprovider -m postgres_integration --require-postgres tests/test_postgres_store.py tests/test_json_to_postgres_migration.py
```

Before new changes, always run at minimum:

```powershell
git status --short --branch
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider
```

After future runtime/test changes, also run targeted tests for affected files.

## 7. Риски

### Payments

Easy to break:

- duplicate successful_payment handling;
- refund/chargeback;
- orphan successful_payment;
- pending refund before success;
- user_id mismatch;
- Telegram Stars vs YooKassa product mapping;
- extra purchase entitlement checks;
- legacy payload handling.

Known old-folder risks:

- refund/chargeback for old subscription charge may revoke current newer subscription;
- migration does not carry full payment ledger;
- processed charge aliases may not be migrated into correct columns;
- product/kind metadata may be missing for migrated charges.

Do not touch payments in emergency stabilization unless explicitly requested.

### Storage/Postgres/JSON fallback

Easy to break:

- production startup if env is missing;
- dev startup if JSON fallback is too strict;
- migration idempotency;
- payment duplicate registry;
- generation consumption/refund;
- stale generation cleanup;
- JSON lock behavior on Windows.

Known old-folder risks:

- no `statement_timeout` / `lock_timeout` in Postgres store;
- JSON file lock blocks without timeout;
- migration is not atomic;
- `payment_events.json` not migrated;
- dry-run does not compare against live DB.

Do not ship storage/Postgres migration before payment event ledger issues are fixed.

### PDF/generation

Easy to break:

- PDF generation blocking event loop;
- temp file cleanup;
- fallback to text when PDF fails;
- Telegram document size guard;
- slow tests leaking into fast suite;
- weekly plan generation taking too long.

Known facts:

- ReportLab rendering is sync;
- in old code weekly PDF was offloaded via `asyncio.to_thread`;
- one-day generation still had sync CPU inside async handler;
- some weekly workflow tests in old fast suite took about 15 seconds each.

### Runtime/hangs

Easy to break:

- polling startup;
- heartbeat liveness;
- graceful shutdown;
- Telegram retry sleeping too long;
- DB/storage `to_thread` saturation;
- inline analytics delay.

Do not assume a passing unit test proves production startup health.

## 8. Рекомендованный следующий шаг

Smallest safe next task:

Commit or continue from the current tiny hygiene change only if the user asks. Otherwise next actual implementation task should be emergency stabilization planning/read-only comparison before any code transfer.

What new Codex should verify first:

1. Confirm working directory:

```powershell
pwd
git status --short --branch
git branch --show-current
```

Expected:

```text
C:\Users\adck8\Documents\New project 2 CLEAN
codex/emergency-stabilization
```

2. Confirm only expected files are changed:

```powershell
git diff -- .gitignore
git status --short --branch
```

Expected:

- `.gitignore` modified;
- `docs/AI_HANDOFF.md` untracked or modified;
- no code files modified.

3. Read this file first:

```text
docs/AI_HANDOFF.md
```

4. Then inspect old source material only read-only:

```powershell
git diff -- "C:\Users\adck8\Documents\New project 2\.gitignore"
```

Better: use normal file reads and `git diff` in the old folder, but do not edit the old folder.

Files to read first for future emergency stabilization:

- clean:
  - `.gitignore`;
  - `pyproject.toml`;
  - `src/diet_bot/telegram_app.py`;
  - current tests.
- old folder, read-only:
  - `src/diet_bot/runtime_config.py`;
  - `src/diet_bot/healthcheck.py`;
  - relevant small hunks in `src/diet_bot/telegram_app.py`;
  - `tests/test_healthcheck.py`;
  - `tests/test_storage_config.py`.

Commands to execute first:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
git status --short --branch
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider
```

What categorically not to do:

- do not edit old folder unless user explicitly asks;
- do not reset old folder;
- do not run `git checkout --` / `git reset --hard`;
- do not copy entire `telegram_app.py` from old folder;
- do not copy entire `tests/` folder from old folder;
- do not start with Postgres/payments migration;
- do not commit/push without explicit user request;
- do not autoformat unrelated files.

## 9. Инструкция для нового Codex

Готовый промт для нового диалога:

```text
Ты продолжаешь работу в репозитории Telegram diet bot / FoodBalance.

Рабочая папка для продолжения:
C:\Users\adck8\Documents\New project 2 CLEAN

Старая папка:
C:\Users\adck8\Documents\New project 2

ВАЖНО:
- Старая папка является складом запчастей. Не редактируй ее.
- Не делай git reset --hard, git checkout --, commit, push, autoformat.
- Не копируй целиком telegram_app.py, payments.py, postgres_store.py или tests/.
- Работай только маленькими тематическими изменениями в New project 2 CLEAN.
- Перед любыми действиями прочитай docs/AI_HANDOFF.md.

Текущее состояние:
- Ветка: codex/emergency-stabilization.
- База: c4fa144 Backup current diet bot project state.
- Уже изменен только .gitignore: добавлена строка .claude/.
- Создан docs/AI_HANDOFF.md.
- Тесты на clean base проходили: 133 passed.

Главная стратегия:
- Не чинить старую смешанную ветку как единый PR.
- Использовать ее только как источник хороших фрагментов.
- Переносить изменения маленькими группами:
  1. emergency stabilization;
  2. tests/CI separation;
  3. PDF;
  4. Telegram runtime;
  5. storage/Postgres;
  6. payments;
  7. data/nutrition;
  8. cleanup.

Сначала выполни:
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
git status --short --branch
git branch --show-current
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider

Затем предложи самый маленький следующий шаг. Если пользователь разрешит кодовые изменения, начни с emergency stabilization или tests/CI separation, но не с Postgres/payments.
```

