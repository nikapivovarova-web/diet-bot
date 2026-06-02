# Stage 18C Sales Follow-Up Scheduler Admission

## Scope

Stage 18C adds only scheduler admission after successful free one-day ration
delivery. It creates an idempotent sales follow-up chain with the existing
8-job Stage 18B schedule when eligibility passes.

Implemented:

- Admission service in `sales_followup.py` with explicit skip statuses.
- Trigger idempotency key format:
  `sales-followup:free_trial_v1:{chat_id}:{delivery_identifier}`.
- Durable one-day worker success hook after free trial delivery and existing
  trial CTA.
- Legacy/direct trial delivery hook after `_send_plan()` succeeds and the
  existing trial CTA is sent.
- Durable trial admission now persists `chat_type` in the one-day job request
  payload so the worker can reject non-private chats without guessing.
- Eligibility checks for feature flag, store availability, private chat, free
  trial source, successful delivery, trial CTA, active paid access, weekly PDF
  access, and opt-out preference.

Not implemented:

- No sales follow-up Telegram messages are sent.
- No sales follow-up worker send/claim loop was added.
- No Telegram callback handlers or opt-out callback were added.
- No sales follow-up message texts or button mappings were changed.
- No `FOOD20` seed, activation, redemption, payment discount, or payment order
  metadata was changed.
- No recipe/data/PDF behavior, bot launch, deploy, push, commit, tag, PR,
  production DB, Telegram API polling, payments, refunds, secrets, archive,
  `New project 2 CLEAN`, or recovered-bot work was done.

## Hook Points

Durable worker path:

- `_send_trial_plan_with_postgres_job()` writes `request_payload["chat_type"]`
  for trial one-day jobs.
- `_prepare_one_day_generation_delivery(...).after_success()` calls scheduler
  admission only after the worker has delivered all value messages,
  remembered recipe history, and sent the existing trial subscription CTA.
- The source is `job.consumption_source`; only `free_trial` passes.
- The trigger ID is `job.job_id`, and `trigger_job_id` is persisted on the
  sales follow-up chain.

Legacy/direct path:

- `_send_trial_plan()` calls scheduler admission only after `_send_plan()`
  returns `True` and `_send_trial_subscription_cta()` completes.
- The source is the consumed one-day entitlement source; only `free_trial`
  passes.
- The trigger ID is the trial one-day idempotency key.

## Eligibility

Admission schedules only when all of these are true:

- `DIET_BOT_SALES_FOLLOWUP_ENABLED=1`;
- a Postgres sales follow-up store is available;
- chat type is `private`;
- delivery succeeded;
- trigger kind is `free_one_day_delivery`;
- source is `free_trial`;
- trial subscription CTA is part of the successful delivery path;
- user has no active paid/test/subscription access;
- user has no available weekly PDF access;
- user has not opted out of sales follow-up.

Admission skips `/start`, privacy consent, questionnaire-only events, failed or
partial delivery, paid one-day, repeated non-free-trial one-day generation,
weekly PDF generation, admin/test access flows, and non-private chats because
those paths either do not call the scheduler hook or fail the explicit
admission guard.

Duplicate triggers are idempotent through `trigger_idempotency_key`; second
active chains for the same `chat_id + campaign_key` are also suppressed by the
existing Stage 18B store contract.

## No-Send Proof

- The new admission function only calls `store.get_preference()` and
  `store.create_chain()`.
- The Telegram hook calls happen after existing successful free-trial delivery
  and existing trial CTA behavior; no new follow-up `message.answer()` call was
  added.
- No callback constants, callback routing, opt-out callback, worker send loop,
  Telegram rendering, `FOOD20` redemption, payment order metadata, or button
  mapping was added or changed.

## Verification

RED before implementation:

- `PYTHONPATH=src pytest tests/test_sales_followup.py -q`
  - collection failed because `SalesFollowupScheduleAdmissionStatus` and the
    scheduler admission helpers did not exist.
- Focused Telegram tests for durable/legacy scheduler hooks:
  - `3 failed, 1 passed`;
  - failures proved missing durable `chat_type` persistence and missing
    scheduler admission calls after legacy/durable success.

GREEN after implementation:

- `PYTHONPATH=src DIET_BOT_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55433/diet_bot_test pytest tests/test_sales_followup.py tests/test_postgres_sales_followup_store.py -q`
  - `16 passed`
- `PYTHONPATH=src pytest tests/test_one_day_generation_job_runtime.py -q`
  - `21 passed`
- `PYTHONPATH=src pytest tests/test_telegram_app_photos.py::test_postgres_trial_request_durable_admits_without_calculation_generation_or_cta tests/test_telegram_app_photos.py::test_send_trial_plan_keeps_legacy_path_without_one_day_job_runtime tests/test_telegram_app_photos.py::test_telegram_one_day_worker_processor_sends_trial_delivery_and_cta_after_success tests/test_telegram_app_photos.py::test_telegram_one_day_worker_processor_does_not_schedule_non_private_trial -q`
  - `4 passed`
- `git diff --check`
  - exit code `0`;
  - output contained only existing LF-to-CRLF working-copy warnings.

Postgres proof used disposable local Docker Postgres only:

- image: `postgres:16-alpine`;
- database: `diet_bot_test`;
- local port: `55433`;
- no production DB was used.

## Changed Files

- `src/diet_bot/sales_followup.py`
- `src/diet_bot/telegram_app.py`
- `tests/test_sales_followup.py`
- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/stage18c-sales-followup-scheduler.md`
- `docs/recovery-integration/recovery-status.md`

## Stage 18D Remaining Work

- Add the actual sales follow-up worker claim/lease/retry loop.
- Recheck eligibility before every send.
- Add Telegram message rendering and buttons only when send stage is explicitly
  approved.
- Add opt-out callback only in the send/callback stage.
- Add cancellation/suppression after subscription, weekly PDF purchase, opt-out,
  or campaign disable.
- Keep `FOOD20` redemption/payment discount blocked until the dedicated
  payment/promo stage approves it.

## Verdict

READY FOR NEXT SALES FOLLOW-UP STAGE
