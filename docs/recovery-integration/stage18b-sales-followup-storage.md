# Stage 18B Sales Follow-Up Storage Foundation

## Scope

Stage 18B adds only durable storage foundation for the unpaid sales follow-up funnel after a free one-day ration.

Implemented:

- PostgreSQL schema for `sales_followup_chains`, `sales_followup_jobs`, `sales_followup_preferences`, and `sales_followup_campaigns`.
- Store API for idempotent creation of one 8-job chain per chat/campaign.
- Exact 8-step schedule and payload contract with `message_text`, `button_label`, `target_kind`, `target_callback_data`, and `target_resolution_note`.
- Opt-out preference storage.
- Campaign row storage with `enabled=false` by default.
- Disabled-by-default runtime flag `DIET_BOT_SALES_FOLLOWUP_ENABLED=0`.

Not implemented in this stage:

- Scheduler hook after free one-day delivery.
- Worker that sends messages.
- Telegram send, templates, buttons rendering, or callback handlers.
- Opt-out callback in Telegram.
- Cancellation after payment.
- FOOD20 seed, redemption, payment discount, or payment metadata changes.
- Admin/ops UI.
- Manual smoke.

## Button Mapping

| Step | Button label | Target kind | Target callback data | Resolution note |
| --- | --- | --- | --- | --- |
| `m01_two_hours` | `Получить рацион на неделю` | `existing_weekly_pdf_flow` | `diet:week_pdf` | Existing `CALLBACK_WEEK_PLAN_PDF`; no new callback handler. |
| `m02_one_day` | `Попробовать неделю` | `existing_weekly_pdf_flow` | `diet:week_pdf` | Existing `CALLBACK_WEEK_PLAN_PDF`; no new callback handler. |
| `m03_two_days` | `Хочу свой план на неделю` | `existing_weekly_pdf_flow` | `diet:week_pdf` | Existing `CALLBACK_WEEK_PLAN_PDF`; no new callback handler. |
| `m04_three_days_food20` | `Оформить подписку` | `existing_subscription_flow` | `diet:subscribe_month` | Existing `CALLBACK_SUBSCRIBE`; FOOD20 remains text only in Stage 18B. |
| `m05_one_week` | `Проверить свой рацион` | `existing_weekly_pdf_flow` | `diet:week_pdf` | Existing `CALLBACK_WEEK_PLAN_PDF`; no new callback handler. |
| `m06_two_weeks` | `Получить рацион` | `existing_weekly_pdf_flow` | `diet:week_pdf` | Existing `CALLBACK_WEEK_PLAN_PDF`; no new callback handler. |
| `m07_one_month` | `Собрать мой рацион` | `existing_weekly_pdf_flow` | `diet:week_pdf` | Existing `CALLBACK_WEEK_PLAN_PDF`; no new callback handler. |
| `m08_six_weeks` | `Попробовать неделю` | `existing_weekly_pdf_flow` | `diet:week_pdf` | Existing `CALLBACK_WEEK_PLAN_PDF`; no new callback handler. |

No unresolved target mapping remained after read-only inspection of existing Telegram callbacks.

## Tables And Store APIs

New tables:

- `sales_followup_chains`
- `sales_followup_jobs`
- `sales_followup_preferences`
- `sales_followup_campaigns`

New store/API surface:

- `PostgresSalesFollowupStore.initialize()`
- `PostgresSalesFollowupStore.validate_schema()`
- `PostgresSalesFollowupStore.ensure_campaign()`
- `PostgresSalesFollowupStore.get_campaign()`
- `PostgresSalesFollowupStore.create_chain()`
- `PostgresSalesFollowupStore.get_chain()`
- `PostgresSalesFollowupStore.list_jobs_for_chain()`
- `PostgresSalesFollowupStore.set_opt_out()`
- `PostgresSalesFollowupStore.get_preference()`

`create_chain()` is transactional. It creates one active chain and exactly 8 queued jobs, returns an existing chain for repeated `trigger_idempotency_key`, and returns the active duplicate for a second active chain attempt on the same `chat_id + campaign_key`.

## Exact Text Preservation

Proof:

- `tests/test_sales_followup.py::test_sales_followup_contract_preserves_exact_eight_step_schedule_and_payloads` asserts all 8 `step_key` values, offsets, exact `message_text` strings, exact `button_label` strings, and payload `step_key` values.
- `tests/test_sales_followup.py::test_sales_followup_button_targets_use_only_existing_safe_flows` asserts the safe target mapping and verifies the FOOD20 step does not target promo redemption.
- DSN-backed `tests/test_postgres_sales_followup_store.py::test_create_chain_is_idempotent_and_creates_exact_eight_jobs` verifies persisted jobs include the expected first message/button, FOOD20 text once, and subscription callback for step 4.

## Disabled And No Send Proof

- `DIET_BOT_SALES_FOLLOWUP_ENABLED` defaults to `False`.
- `.env.example` sets `DIET_BOT_SALES_FOLLOWUP_ENABLED=0`.
- Enabling the flag requires Postgres storage and `DIET_BOT_DATABASE_URL`.
- `sales_followup_campaigns.enabled` defaults to `false`.
- No `telegram_app.py` callback/send code was changed.
- No worker, scheduler hook, Telegram sender, payment order metadata, promo seed, or FOOD20 redemption code was added.

## Verification

RED before implementation:

- `PYTHONPATH=src pytest tests/test_sales_followup.py tests/test_postgres_sales_followup_store.py -q`
- Result: `2 errors` during collection because `diet_bot.sales_followup` and `diet_bot.postgres_sales_followup_migrations` did not exist.

GREEN after implementation:

- `PYTHONPATH=src pytest tests/test_sales_followup.py tests/test_postgres_sales_followup_store.py -q`
- Result without DSN: `5 passed, 4 skipped`.

Focused config regression:

- `PYTHONPATH=src pytest tests/test_sales_followup.py tests/test_runtime_config.py -q`
- Result: `41 passed`.

DSN-backed local Postgres verification:

- Disposable Docker Postgres: `postgres:16-alpine`, database `diet_bot_test`, local port `55432`.
- `PYTHONPATH=src DIET_BOT_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/diet_bot_test pytest tests/test_postgres_sales_followup_store.py -q`
- Result: `6 passed`.
- Container stopped after verification.

## Stage 18C Remaining Work

- Add scheduler hook after successful free one-day ration delivery.
- Add durable worker claim/lease/retry loop.
- Add eligibility rechecks before send.
- Add Telegram message rendering and buttons only when send stage is explicitly approved.
- Add Telegram opt-out callback only in the send/callback stage.
- Add cancellation after subscription or weekly PDF purchase.
- Keep FOOD20 redemption/payment discount blocked until the dedicated payment/promo stage approves it.

## Verdict

READY FOR NEXT SALES FOLLOW-UP STAGE
