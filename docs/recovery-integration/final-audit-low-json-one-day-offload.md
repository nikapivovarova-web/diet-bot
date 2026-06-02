# Final Audit Low JSON One-Day Offload

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Verdict

Closed locally.

Updated local final pre-release audit count: `0 high / 0 medium / 2 low`.

## Finding

The low finding was real in the legacy JSON one-day generation path. The
Postgres durable worker path already generated one-day plans through
`asyncio.to_thread()`, but the JSON fallback helper `_send_plan()` still called
`build_one_day_plan()` directly from the async Telegram handler path.

## Root Cause

Stage 19.3 offloaded the queued durable one-day worker path, but the preserved
JSON fallback continued to share the old inline `_send_plan()` implementation.
That kept CPU-bound planner work on the Telegram event loop whenever no
Postgres one-day job runtime was configured.

## Fix

`_send_plan()` now wraps the existing `build_one_day_plan()` call in
`asyncio.to_thread()`. The planner inputs, entitlement consumption/refund
behavior, recipe history behavior, message delivery behavior, and Postgres
queued worker path are otherwise unchanged.

## Tests

RED before the fix:

- `python -m pytest tests/test_telegram_app_photos.py::test_one_day_json_backend_offloads_legacy_plan_build_to_thread -q`
  - `1 failed`
  - Failure proved `build_one_day_plan()` was reached with no `asyncio.to_thread`
    offload depth.

GREEN after the fix:

- `python -m pytest tests/test_telegram_app_photos.py::test_one_day_json_backend_offloads_legacy_plan_build_to_thread -q`
  - `1 passed`
- `python -m pytest tests/test_telegram_app_photos.py::test_one_day_json_backend_preserves_legacy_consume_refund_behavior tests/test_telegram_app_photos.py::test_one_day_json_backend_offloads_legacy_plan_build_to_thread tests/test_telegram_app_photos.py::test_one_day_json_history_save_failure_after_meals_is_best_effort tests/test_telegram_app_photos.py::test_one_day_history_read_failure_returns_false_and_refunds_json_attempt -q`
  - `4 passed`
- `python -m pytest tests/test_telegram_app_runtime.py::test_one_day_generation_delivery_offloads_plan_build_to_thread tests/test_one_day_generation_job_runtime.py::test_worker_generates_from_persisted_snapshot -q`
  - `2 passed`
- `python -m pytest tests/test_telegram_app_photos.py -k one_day -q`
  - `36 passed, 118 deselected`
- `python -m pytest tests/test_telegram_app_runtime.py -k one_day -q`
  - `2 passed, 42 deselected`
- `python -m pytest tests/test_one_day_generation_job_runtime.py -q`
  - `21 passed`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

## Scope Boundaries

- No privacy consent durability change.
- No promo `per_user_limit` change.
- No payment/provider/refund behavior change.
- No sales follow-up behavior change.
- No recipe data, import, or photo change.
- No bot process, Telegram API, `getUpdates`, production database,
  provider/live payment smoke, deploy, push, commit, tag, PR, archive,
  `New project 2 CLEAN`, or recovered-bot path was used.

## Remaining Low Findings

- Durable privacy consent if legal/product requires persisted acceptance.
- Promo `per_user_limit` semantics before enabling multi-use discount
  campaigns such as `FOOD20`.

## Next Recommended Prompt

FoodBalance: fix only the privacy-consent durability low finding, or explicitly
document it as accepted, with no payment/provider smoke, no bot start, no
Telegram API/getUpdates, no production DB, and no unrelated promo, JSON
planner, recipe, PDF, sales-follow-up, deploy, push, commit, tag, PR, archive,
`New project 2 CLEAN`, or recovered-bot work.
