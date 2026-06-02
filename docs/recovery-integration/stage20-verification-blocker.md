# Stage 20A Verification Blocker

## Root Cause

The five one-day Telegram tests were not failing because of a production
one-day generation bug. Each focused test passed in isolation. The failure only
reproduced after `tests/test_telegram_app_runtime.py` ran first.

The leaking test was
`test_run_bot_production_postgres_acquires_guard_before_bot_and_releases`. It
enabled both durable workers with a placeholder DSN:
`postgresql://user:secret@example/db`. The test was meant to verify production
startup guard ordering, but it did not stub the worker start hooks. As a
result, `run_bot()` built and cached a real one-day Postgres job runtime in
`telegram_app._ONE_DAY_GENERATION_JOB_RUNTIME`. Later tests that expected the
inline JSON one-day path reused that cached runtime and attempted to connect to
host `example`.

The first node id from the blocker report was stale in this checkout:
`tests/test_telegram_app_runtime.py::test_one_day_plan_double_callback_same_chat_consumes_once`
does not exist here. The actual five failing tests are in
`tests/test_telegram_app_photos.py`.

## Why This Is A Test Fixture Fix

Production behavior is correct: when the one-day durable worker runtime is
configured, Telegram one-day requests should use the Postgres enqueue path. The
problem was that a unit test used a fake placeholder DSN while exercising a
startup-order assertion and accidentally left the real runtime cached for later
tests.

The fix keeps the B-1 production worker guard path intact in production code. In
the startup-order test, the weekly PDF and one-day worker start hooks are now
stubbed and asserted as events. This preserves the guard/order coverage without
creating real worker runtimes from the placeholder DSN.

## Files Changed

- `tests/test_telegram_app_runtime.py`
  - Stubs `_start_weekly_pdf_worker_if_configured`.
  - Stubs `_start_one_day_generation_worker_if_configured`.
  - Asserts both worker start hooks are reached after guard acquisition and bot
    setup.
- `docs/recovery-integration/stage20-verification-blocker.md`
- `docs/recovery-integration/recovery-status.md`

No production code was changed.

## Tests Run

- Initial focused node from the blocker report:
  `pytest tests/test_telegram_app_runtime.py::test_one_day_plan_double_callback_same_chat_consumes_once -q`
  - `no tests ran`; the test lives in `tests/test_telegram_app_photos.py` in
    this checkout.
- Focused five tests individually from `tests/test_telegram_app_photos.py`
  - each passed in isolation.
- Original Stage 20 blocker command before the fix:
  `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_photos.py -q`
  - `5 failed, 210 passed`
- Minimal red repro before the fix:
  `pytest tests/test_telegram_app_runtime.py::test_run_bot_production_postgres_acquires_guard_before_bot_and_releases tests/test_telegram_app_photos.py::test_one_day_plan_double_callback_same_chat_consumes_once -q`
  - `1 failed, 1 passed`
- Minimal green repro after the fix:
  same command
  - `2 passed`
- Focused five after the fix:
  `pytest tests/test_telegram_app_photos.py::test_one_day_plan_double_callback_same_chat_consumes_once tests/test_telegram_app_photos.py::test_concurrent_one_day_requests_same_chat_consume_once tests/test_telegram_app_photos.py::test_one_day_failure_releases_guard_and_allows_retry tests/test_telegram_app_photos.py::test_one_day_generation_different_chats_do_not_block_each_other tests/test_telegram_app_photos.py::test_trial_questionnaire_completion_sends_one_day_plan_and_subscription_cta -q`
  - `5 passed`
- Requested blocker suite after the fix:
  `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_photos.py -q`
  - `215 passed`
- Whitespace check after docs update:
  `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings
    only.

## Remaining Risks

- This was not a full Stage 20 verification rerun. Work stopped after the
  blocker fix as requested.
- The test suite still uses placeholder Postgres DSNs for mocked runtime and
  startup checks. Those tests must keep stubbing real connection paths when they
  are not explicitly using `DIET_BOT_TEST_DATABASE_URL`.
- Live Telegram, real Postgres, payment, PDF rendering, recipe data, deploy,
  commit, push, tag, PR, archive, `New project 2 CLEAN`, and recovered-bot work
  were not performed.
