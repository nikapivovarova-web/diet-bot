# FoodBalance Recovery Roadmap

Дата: 2026-05-12.

Этот roadmap фиксирует безопасный порядок восстановления FoodBalance после старой смешанной ветки. Главная цель: не спасать старую папку как один большой diff, а переносить только маленькие, понятные, откатываемые изменения в clean-папку.

## 1. Роли папок

### Clean-папка: рабочее место

Путь:

```text
C:\Users\adck8\Documents\New project 2 CLEAN
```

Роль:

- единственное место, где можно менять файлы;
- ветка для маленьких переносов: `codex/emergency-stabilization`;
- после каждого маленького переноса проект должен оставаться запускаемым и тестируемым;
- каждый перенос должен быть настолько маленьким, чтобы его можно было откатить одним маленьким commit.

Разрешено:

- читать любые файлы;
- менять только файлы, явно перечисленные в текущей фазе;
- добавлять узкие тесты рядом с переносимым поведением;
- запускать targeted tests и full fast tests.

Нельзя:

- подтягивать целиком крупные файлы из старой папки;
- смешивать runtime, storage, payments, PDF, CI, nutrition data и cleanup в одном переносе;
- делать `git reset --hard`, `git checkout --` или автоформатирование всего проекта;
- делать commit, push или PR без явной команды пользователя.

### Старая папка: read-only склад запчастей

Путь:

```text
C:\Users\adck8\Documents\New project 2
```

Роль:

- источник идей, тестов, маленьких hunks и уже написанных фрагментов;
- не рабочая ветка для продолжения разработки;
- не источник файлов для wholesale-copy.

Разрешено:

- читать файлы;
- смотреть `git diff`, `git status`, rescue-файлы и отдельные hunks;
- копировать вручную только маленькие проверенные фрагменты после адаптации к clean-коду.

Нельзя:

- редактировать старую папку;
- сбрасывать, чистить или чинить ее рабочее дерево;
- удалять rescue-файлы;
- копировать целиком `src/diet_bot/telegram_app.py`, `src/diet_bot/payments.py`, `src/diet_bot/postgres_store.py` или всю папку `tests`.

## 2. Release-ready MVP

Release-ready MVP для восстановления не означает перенос всех старых незавершенных идей. MVP считается готовым к релизу, когда выполнены эти условия:

- Telegram bot стартует предсказуемо с документированной runtime-конфигурацией.
- Dev/local режим остается простым: проект можно прогнать локально без production Postgres и payment secrets.
- Production режим не стартует молча с небезопасным storage fallback.
- Основные пользовательские сценарии из текущей clean-базы не регрессируют:
  - анкета;
  - расчет целей;
  - генерация дневного рациона;
  - генерация недельного рациона;
  - PDF, если включен в текущий релизный scope;
  - блюда, ингредиенты и shopping list;
  - подписки, лимиты и promo codes на уровне текущего clean-функционала.
- Fast test suite отделен от тяжелых PDF/Postgres/integration проверок.
- Минимальный runtime healthcheck есть, быстро выполняется и не требует внешних сервисов в package-data/local smoke режиме.
- PDF-генерация имеет safety guards против слишком тяжелой генерации, больших файлов и silent failure.
- Telegram runtime не имеет очевидных бесконечных ожиданий без deadline/cap.
- Storage/Postgres и payments переносятся только после стабилизации runtime/test gates и остаются отдельными фазами.
- Документация объясняет, как запускать fast, slow PDF и Postgres integration проверки.
- Каждый merged slice имеет маленький, понятный diff и может быть откатан отдельно.

Non-goals для первого release-ready MVP:

- не переносить весь PDF redesign как первый шаг;
- не делать production Postgres обязательным до storage-фазы;
- не переписывать payments до ledger/storage readiness;
- не чистить корневые helper scripts до конца восстановления;
- не пытаться в одном PR догнать старую папку целиком.

## 3. Общий gate после каждого маленького переноса

Перед началом каждого slice:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
git status --short --branch
git branch --show-current
```

После каждого slice:

```powershell
git status --short --branch
git diff --stat
git diff --check
```

Обязательный gate:

- `git status` маленький: только файлы текущего slice, без случайных data/assets/formatting изменений.
- Targeted tests прошли: запускать тесты, прямо покрывающие измененные файлы.
- Full fast tests прошли:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider
```

- Если появятся markers для разделения suite, full fast gate станет:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

- Diff понятный: можно объяснить каждую строку в 2-3 предложениях.
- Можно откатить один маленький commit: slice не зависит от невидимых ручных правок и не смешивает подсистемы.

Если gate не проходит:

- сначала понять конкретную причину;
- сузить slice;
- откатить только свои изменения текущего slice, если нужно;
- не чинить соседнюю подсистему "по пути".

## 4. Очередь переносов

Порядок фиксированный:

1. Emergency stabilization.
2. Tests/CI separation.
3. Minimal runtime healthcheck.
4. PDF safety guards.
5. Telegram runtime hardening.
6. Storage/Postgres.
7. Payments.
8. Data/nutrition.
9. Cleanup/hygiene.

Каждая фаза ниже является контейнером для нескольких маленьких переносов. Один bullet внутри фазы не означает один большой commit: если diff перестает быть очевидным, его надо разделить.

## 5. Phase 1: Emergency stabilization

Цель: зафиксировать clean-базу как безопасную точку и убрать самые маленькие runtime/config риски, не трогая Postgres, payments и PDF redesign.

### Что переносим

- Только минимальные guard-правки, которые предотвращают аварийный startup или случайный небезопасный режим.
- Маленькие runtime/config constants, если они не тянут storage/payment logic.
- Документированные local/prod env defaults, если они нужны для понятного старта.
- Узкие тесты на существующее поведение clean-базы.

### Что читать в старой папке

- `C:\Users\adck8\Documents\New project 2\src\diet_bot\runtime_config.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\healthcheck.py`
- Маленькие hunks из `C:\Users\adck8\Documents\New project 2\src\diet_bot\telegram_app.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_storage_config.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_healthcheck.py`
- `C:\Users\adck8\Documents\New project 2\.env.example`

### Что можно менять в clean

- `C:\Users\adck8\Documents\New project 2 CLEAN\.env.example`, если файл существует или будет введен отдельным config slice.
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\telegram_app.py`, только маленькие startup/config guards.
- `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_telegram_app_photos.py`, только если текущий guard касается существующего Telegram behavior.
- Новый узкий тестовый файл, например `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_runtime_config.py`, только если появляется соответствующий маленький module.
- Документы в `C:\Users\adck8\Documents\New project 2 CLEAN\docs\`.

### Какие тесты добавить/запустить

Добавить:

- тест, что local/dev конфигурация явно разрешена только через понятный env flag;
- тест, что production startup не выбирает JSON fallback молча;
- тест, что отсутствующие optional secrets дают понятную ошибку или отключают feature, а не ломают import.

Запустить:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_telegram_app_photos.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider
```

Если добавлен новый targeted test:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_runtime_config.py
```

### Что категорически нельзя делать

- Не добавлять Postgres dependencies или `postgres_store.py`.
- Не менять payment/subscription business rules.
- Не переносить PDF layout или PDF assets.
- Не копировать весь `telegram_app.py`.
- Не добавлять Docker/CI в тот же slice.
- Не удалять существующие helper scripts как "cleanup".

## 6. Phase 2: Tests/CI separation

Цель: сделать fast suite быстрым и стабильным, а тяжелые проверки вынести в отдельные markers/workflows.

### Что переносим

- Pytest markers для тяжелых категорий:
  - `slow_pdf_builder`;
  - `postgres_integration`;
  - при необходимости `runtime_smoke` или `external_service`.
- Минимальную конфигурацию test commands.
- CI separation только после локального разделения tests.
- Маленькие изменения в тестах, которые маркируют уже тяжелые проверки, не меняя runtime behavior.

### Что читать в старой папке

- `C:\Users\adck8\Documents\New project 2\pyproject.toml`
- `C:\Users\adck8\Documents\New project 2\tests\conftest.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_pdf_renderer.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_pdf_limits_smoke.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_postgres_store.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_json_to_postgres_migration.py`
- `C:\Users\adck8\Documents\New project 2\.github\workflows\tests.yml`
- `C:\Users\adck8\Documents\New project 2\.github\workflows\slow-pdf-builder.yml`
- `C:\Users\adck8\Documents\New project 2\.github\workflows\postgres-integration.yml`

### Что можно менять в clean

- `C:\Users\adck8\Documents\New project 2 CLEAN\pyproject.toml`
- `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_pdf_renderer.py`
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\tests\conftest.py`, только если нужен общий marker/helper.
- `.github/workflows/*` в clean, но только отдельным CI slice после локального test slice.
- `C:\Users\adck8\Documents\New project 2 CLEAN\docs\`.

### Какие тесты добавить/запустить

Добавить:

- tests не обязаны добавляться, если slice только маркирует уже существующие тяжелые тесты;
- если добавляется marker behavior, достаточно проверить collect-only и selected/deselected counts.

Запустить:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest --collect-only -q -p no:cacheprovider
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

Для PDF slow lane, только когда marker уже есть:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m slow_pdf_builder
```

Текущий clean-slice без Postgres integration:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -m pytest --collect-only -q -p no:cacheprovider
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider
```

Для Postgres lane, только после storage-фазы или при skip-safe tests:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration
```

### Что категорически нельзя делать

- Не менять production code ради ускорения тестов в этой фазе.
- Не удалять тяжелые тесты, если их можно маркировать.
- Не вводить Postgres runtime dependency только ради CI.
- Не переносить все workflows сразу.
- Не чинить PDF layout или storage migration в том же PR.

## 7. Phase 3: Minimal runtime healthcheck

Цель: добавить быстрый healthcheck, который подтверждает package data/import readiness и дает понятную ошибку для production storage config.

### Что переносим

- Минимальный `diet_bot.healthcheck` без внешних network calls.
- Проверку package data: JSON data и required image/assets, которые уже нужны clean runtime.
- CLI entrypoint `python -m diet_bot.healthcheck`.
- Опционально: healthcheck command в docs или CI smoke, отдельным маленьким slice.

### Что читать в старой папке

- `C:\Users\adck8\Documents\New project 2\src\diet_bot\healthcheck.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\runtime_config.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_healthcheck.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_production_deploy_files.py`
- `C:\Users\adck8\Documents\New project 2\docs\production-runbook.md`

### Что можно менять в clean

- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\healthcheck.py`
- Возможно новый `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\runtime_config.py`, если healthcheck требует общей config parsing функции.
- `C:\Users\adck8\Documents\New project 2 CLEAN\pyproject.toml`, только если нужен script entry.
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_healthcheck.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\docs\`.

### Какие тесты добавить/запустить

Добавить:

- `test_package_data_healthcheck_ok_without_external_services`;
- `test_production_healthcheck_requires_durable_storage_or_explicit_local_override`;
- `test_healthcheck_cli_exits_zero_for_package_data_only`;
- `test_healthcheck_cli_exits_nonzero_with_clear_message_for_missing_prod_storage`.

Запустить:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_healthcheck.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m diet_bot.healthcheck --package-data-only
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider
```

### Что категорически нельзя делать

- Не проверять реальный Telegram API.
- Не требовать настоящий Postgres URL для package-data-only режима.
- Не добавлять Docker/deploy hardening в тот же slice.
- Не переносить storage implementation вместе с healthcheck.
- Не превращать healthcheck в долгий integration test.

## 8. Phase 4: PDF safety guards

Цель: сделать PDF path безопасным до любого визуального redesign: deadlines, fallback, size guards, heavy tests outside fast suite.

### Что переносим

- Маленькие guards вокруг существующей PDF-генерации:
  - максимальный размер output;
  - понятная fallback path при ошибке генерации;
  - cleanup temp files;
  - optional timeout/deadline вокруг тяжелой weekly generation, если это можно сделать без большого runtime refactor.
- Тесты на failure/fallback и size guard.
- Markers для тяжелых PDF tests, если еще не сделано.

### Что читать в старой папке

- `C:\Users\adck8\Documents\New project 2\src\diet_bot\pdf_renderer.py`
- PDF-related hunks в `C:\Users\adck8\Documents\New project 2\src\diet_bot\telegram_app.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_pdf_renderer.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_pdf_limits_smoke.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\data\foodbalance_pdf_logo.png`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\data\foodbalance_pdf_qr.png`

### Что можно менять в clean

- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\pdf_renderer.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\telegram_app.py`, только PDF call/fallback wrapper hunks.
- `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_pdf_renderer.py`
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_pdf_limits_smoke.py`, если он остается small/marked.
- PDF assets only if required by current minimal renderer, not as redesign batch.

### Какие тесты добавить/запустить

Добавить:

- PDF generation failure returns/send fallback text without crashing handler;
- output size guard blocks sending oversized PDF;
- temp file cleanup happens on success and failure;
- slow ReportLab rendering test is marked `slow_pdf_builder`.

Запустить:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_pdf_renderer.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

Если slow marker есть и slice касается slow path:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m slow_pdf_builder
```

### Что категорически нельзя делать

- Не переносить PDF redesign/layout целиком.
- Не добавлять все PDF assets разом без тестовой необходимости.
- Не менять nutrition builder logic ради PDF.
- Не смешивать PDF safety с Telegram runtime hardening шире PDF wrapper.
- Не оставлять тяжелые PDF tests в fast suite.

## 9. Phase 5: Telegram runtime hardening

Цель: снизить риск зависаний и долгих ожиданий в Telegram runtime без изменения бизнес-логики payments/storage.

### Что переносим

- Capped retry-after sleep для Telegram rate limit.
- Deadlines вокруг потенциально блокирующих async paths.
- Offload CPU-heavy generation/PDF calls только в узких местах с targeted tests.
- Startup heartbeat/liveness behavior, если оно не требует production deploy.
- Inline analytics decoupling только после отдельного minimal analytics decision.
- Маленький state cache/rate limit module, если он полностью покрыт тестами и не тянет storage.

### Что читать в старой папке

- `C:\Users\adck8\Documents\New project 2\src\diet_bot\telegram_app.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\telegram_rate_limit.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\state_cache.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\analytics.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_telegram_app_runtime.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_telegram_user_journeys_smoke.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_telegram_callback_owner_smoke.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_chat_state_cache.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_analytics.py`

### Что можно менять в clean

- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\telegram_app.py`, only narrow runtime hunks.
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\telegram_rate_limit.py`, если переносится rate limit helper.
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\state_cache.py`, если переносится cache helper отдельным slice.
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\analytics.py`, только если analytics не блокирует runtime и имеет tests.
- Новые targeted tests в `C:\Users\adck8\Documents\New project 2 CLEAN\tests\`.

### Какие тесты добавить/запустить

Добавить:

- retry-after sleep is capped;
- storage/generation wrapper times out with clear user-facing fallback;
- callback ownership checks reject mismatched users;
- startup heartbeat is emitted before long polling if that behavior is introduced;
- analytics failure does not fail user handler, if analytics is introduced.

Запустить:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_telegram_app_photos.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_subscriptions.py tests/test_promo_codes.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider
```

Если добавлены новые runtime tests:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_telegram_app_runtime.py
```

### Что категорически нельзя делать

- Не переписывать весь `telegram_app.py`.
- Не переносить payment handlers как часть runtime hardening.
- Не вводить Postgres storage calls в handlers.
- Не менять пользовательские тексты массово.
- Не добавлять analytics, cache и rate limit одним большим commit.
- Не считать "unit tests passed" доказательством production liveness без healthcheck/smoke.

## 10. Phase 6: Storage/Postgres

Цель: ввести durable storage безопасно, после runtime/test gates, не ломая dev-mode и не теряя payment/event state.

### Что переносим

- Storage interface или минимальный adapter boundary, если clean-код его еще не имеет.
- JSON storage hardening как отдельный preliminary slice:
  - timeout для file lock;
  - explicit dev-only fallback;
  - durable write semantics where small.
- Postgres store только после interface/tests.
- Migrations только после того, как known payment ledger gaps решены или явно вынесены из MVP.
- JSON-to-Postgres migration dry-run with verification.
- Postgres integration tests marked and skipped safely without test DB.

### Что читать в старой папке

- `C:\Users\adck8\Documents\New project 2\src\diet_bot\json_storage.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\postgres_store.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\postgres_migrations.py`
- `C:\Users\adck8\Documents\New project 2\scripts\migrate_json_to_postgres.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_json_storage.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_postgres_store.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_json_to_postgres_migration.py`
- `C:\Users\adck8\Documents\New project 2\docs\superpowers\specs\2026-05-10-postgresql-state-storage-design.md`
- `C:\Users\adck8\Documents\New project 2\scripts\ops\backup_postgres.sh`
- `C:\Users\adck8\Documents\New project 2\scripts\ops\restore_postgres_drill.sh`

### Что можно менять в clean

- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\json_storage.py`
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\postgres_store.py`, only after interface slice.
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\postgres_migrations.py`
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\scripts\migrate_json_to_postgres.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\telegram_app.py`, only adapter injection/wiring, not handler rewrites.
- `C:\Users\adck8\Documents\New project 2 CLEAN\pyproject.toml`, only for required Postgres dependency and markers.
- Targeted storage tests in `C:\Users\adck8\Documents\New project 2 CLEAN\tests\`.

### Какие тесты добавить/запустить

Добавить:

- JSON lock timeout on Windows-safe path;
- dev fallback requires explicit env flag;
- Postgres connection applies `connect_timeout`, `statement_timeout`, and `lock_timeout`;
- migration is idempotent;
- dry-run reports what would change without writing;
- payment event/processed charge state is either migrated or explicitly blocked with clear error;
- integration tests skip without DB unless `--require-postgres` or equivalent is provided.

Запустить:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_json_storage.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

Postgres skip-safe lane:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration
```

With real test DB only when explicitly configured:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration --require-postgres tests/test_postgres_store.py tests/test_json_to_postgres_migration.py
```

### Что категорически нельзя делать

- Не начинать recovery с этой фазы.
- Не делать JSON fallback production default.
- Не переносить Postgres store без integration skip strategy.
- Не мигрировать subscriptions/payments без полного payment ledger решения.
- Не менять payment business logic в storage PR.
- Не добавлять Docker production deploy в тот же slice.

## 11. Phase 7: Payments

Цель: восстановить payment/subscription behavior только после того, как storage/event ledger strategy стала понятной.

### Что переносим

- Payment event ledger as source of truth, если он нужен до refund/chargeback.
- Duplicate successful_payment protection.
- Orphan successful_payment handling.
- Refund/chargeback logic tied to exact paid period/product.
- Extra purchase entitlement checks with stable snapshot.
- Legacy payload parsing only with tests.
- Reconciliation path only after events are durable.

### Что читать в старой папке

- `C:\Users\adck8\Documents\New project 2\src\diet_bot\payments.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\subscriptions.py`
- Payment-related hunks in `C:\Users\adck8\Documents\New project 2\src\diet_bot\telegram_app.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_payments_smoke.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_subscriptions.py`
- `C:\Users\adck8\Documents\New project 2\docs\superpowers\specs\2026-05-09-yookassa-telegram-payments-design.md`
- `C:\Users\adck8\Documents\New project 2\docs\superpowers\specs\2026-05-08-telegram-stars-subscription-limits-design.md`

### Что можно менять в clean

- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\payments.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\subscriptions.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\telegram_app.py`, only narrow payment handler wiring.
- Storage files only if payment ledger interface already exists from Phase 6.
- `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_subscriptions.py`
- Новый `C:\Users\adck8\Documents\New project 2 CLEAN\tests\test_payments_smoke.py`

### Какие тесты добавить/запустить

Добавить:

- duplicate charge id is idempotent;
- refund for old subscription period does not revoke newer active subscription;
- chargeback affects only matching product/period;
- extra purchase pre-checkout and successful_payment use consistent entitlement state;
- orphan successful_payment is recorded and recoverable;
- legacy payload routes are parsed or rejected explicitly.

Запустить:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_subscriptions.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_payments_smoke.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

### Что категорически нельзя делать

- Не переносить payments до storage/event ledger decision.
- Не смешивать refunds, chargebacks, reconciliation и Telegram UI changes в одном commit.
- Не менять цены, продукты или payload format без backward compatibility tests.
- Не делать external payment API calls в unit tests.
- Не использовать JSON-only duplicate registry для production-ready payments.

## 12. Phase 8: Data/nutrition

Цель: переносить nutrition/data improvements отдельно от runtime/payments/storage, с проверкой качества и размера данных.

### Что переносим

- Маленькие curated data fixes.
- Recipe nutrition corrections with deterministic tests.
- Builder/chef/questionnaire changes only when tied to data correctness.
- Profile normalization only as separate slice with direct tests.
- Large JSON/photos only in controlled batches with before/after validation.

### Что читать в старой папке

- `C:\Users\adck8\Documents\New project 2\src\diet_bot\builder.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\chef.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\curated_data.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\questionnaire.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\safety.py`
- `C:\Users\adck8\Documents\New project 2\src\diet_bot\profile_normalization.py`
- Data files under `C:\Users\adck8\Documents\New project 2\src\diet_bot\data\`
- `C:\Users\adck8\Documents\New project 2\tests\test_curated_recipe_data.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_safety_and_builder.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_questionnaire_and_presentation.py`
- `C:\Users\adck8\Documents\New project 2\tests\test_profile_normalization.py`
- `C:\Users\adck8\Documents\New project 2\scripts\build_curated_recipe_data.py`

### Что можно менять в clean

- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\builder.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\chef.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\curated_data.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\questionnaire.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\safety.py`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\data\curated_recipes.json`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\data\curated_foods.json`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\data\curated_recipe_ingredients.json`
- `C:\Users\adck8\Documents\New project 2 CLEAN\src\diet_bot\data\curated_recipe_nutrition.json`
- Recipe photos only in small named batches.
- Corresponding tests in `C:\Users\adck8\Documents\New project 2 CLEAN\tests\`.

### Какие тесты добавить/запустить

Добавить:

- data schema/required fields validation for changed recipes;
- no duplicate recipe ids;
- nutrition totals remain within expected tolerance;
- changed questionnaire normalization is deterministic;
- shopping list output remains stable for representative vectors.

Запустить:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_curated_recipe_data.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_safety_and_builder.py tests/test_vectors_and_shopping.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

### Что категорически нельзя делать

- Не копировать все JSON data целиком без diff review.
- Не переносить сотни photos в одном slice.
- Не менять runtime/payment/storage вместе с nutrition.
- Не менять алгоритм builder без golden/vector tests.
- Не принимать data changes без validation command.

## 13. Phase 9: Cleanup/hygiene

Цель: после функционального восстановления убрать мусор, устаревшие scripts/docs и локальные артефакты без изменения behavior.

### Что переносим

- `.gitignore` hygiene.
- Удаление obsolete helper scripts only after confirming they are not used by docs/tests/CI.
- Docs cleanup after actual implementation is settled.
- README updates matching final commands.
- CI/docs naming consistency.

### Что читать в старой папке

- `C:\Users\adck8\Documents\New project 2\.gitignore`
- `C:\Users\adck8\Documents\New project 2\README.md`
- `C:\Users\adck8\Documents\New project 2\docs\production-runbook.md`
- `C:\Users\adck8\Documents\New project 2\docs\regression-checklist.md`
- Root helper scripts in `C:\Users\adck8\Documents\New project 2\`
- `.github/workflows/*` only after CI design is settled.

### Что можно менять в clean

- `C:\Users\adck8\Documents\New project 2 CLEAN\.gitignore`
- `C:\Users\adck8\Documents\New project 2 CLEAN\README.md`
- `C:\Users\adck8\Documents\New project 2 CLEAN\docs\*`
- Root helper scripts, only one cleanup topic per slice.
- `.github/workflows/*`, only if CI already exists in clean and tests pass.

### Какие тесты добавить/запустить

Добавить:

- usually none for docs-only cleanup;
- if deleting scripts, add or run checks proving no docs/CI/test references remain.

Запустить:

```powershell
rg "deleted_script_name|old_command_name" "C:\Users\adck8\Documents\New project 2 CLEAN"
git diff --check
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

If markers are not introduced yet:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider
```

### Что категорически нельзя делать

- Не начинать recovery с cleanup.
- Не удалять файлы, чтобы "уменьшить шум", пока неизвестно, используются ли они.
- Не менять behavior в hygiene PR.
- Не редактировать старую папку и не удалять rescue files.
- Не смешивать docs cleanup с payments/storage/PDF logic.

## 14. Правило размера slice

Перед переносом спросить:

```text
Если после этого сломается приложение, будет ли сразу понятно, что виноват именно этот маленький кусок?
```

Если ответ "нет", slice слишком большой.

Хороший slice:

- меняет 1-3 связанных файла;
- имеет 1 targeted test command;
- имеет понятный before/after;
- не требует читать весь старый diff;
- может быть закоммичен и откатан отдельно.

Плохой slice:

- переносит целый большой файл;
- смешивает tests, runtime и business logic;
- меняет data/assets без validation;
- требует объяснения "это все связано";
- не имеет targeted tests.

## 15. Минимальный порядок первого рабочего дня

1. Подтвердить clean status:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
git status --short --branch
```

2. Запустить baseline fast/full current suite:

```powershell
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider
```

3. Сделать первый маленький emergency stabilization slice или tests/CI separation slice.

4. Пройти gate:

```powershell
git status --short --branch
git diff --stat
git diff --check
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider <targeted-tests>
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider
```

5. Только после явного разрешения пользователя: stage/commit маленького slice.
