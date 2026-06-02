# Stage 19.3 One-Day `to_thread`

## Scope

External audit M-1 is fixed for the one-day generation worker delivery path.

The CPU-bound daily `build_one_day_plan(...)` call inside `_prepare_one_day_generation_delivery` now runs through `await asyncio.to_thread(...)`, matching the weekly PDF offload pattern. The same profile, seed, recent-recipe avoidance, and `recipe_source="curated_only"` arguments are passed through unchanged.

## Changed Files

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/stage19-one-day-to-thread.md`
- `docs/recovery-integration/recovery-status.md`

## TDD

RED before implementation:

- `pytest tests/test_telegram_app_runtime.py::test_one_day_generation_delivery_offloads_plan_build_to_thread -q`
- Result: `1 failed`
- Failure reason: the test patched `asyncio.to_thread` and asserted `build_one_day_plan` was called from that offload wrapper; the current worker delivery path called it synchronously.

GREEN after implementation:

- `pytest tests/test_telegram_app_runtime.py::test_one_day_generation_delivery_offloads_plan_build_to_thread -q`
- Result: `1 passed`

## Verification

- `pytest tests/test_telegram_app_runtime.py -q`
  - `24 passed`
- `pytest tests/test_one_day_generation_job_runtime.py -q`
  - `20 passed`
- `pytest tests/test_postgres_one_day_generation_job_store.py -q`
  - `3 passed, 32 skipped`

- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

## Guardrails

- Bot was not launched.
- No deploy, push, commit, tag, or PR was done.
- No promo store, PDF renderer/data, recipe data, sales follow-up, payment, or subscription semantics were changed.
- No archive, `New project 2 CLEAN`, or recovered bot paths were touched.
