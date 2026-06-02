# Final Audit Sales Follow-Up Re-Audit

Date: 2026-05-31

Verdict: HIGH-7 is closed locally.

The timed unpaid sales follow-up funnel is no longer design-only in the current
working tree. The implementation now has durable Postgres storage/jobs,
scheduler admission after successful free one-day trial delivery, worker
runtime, Telegram rendering/buttons, opt-out handling, and cancellation after
paid/weekly/monthly-promo access grants. The feature remains disabled until
explicit approval, and FOOD20 remains a separate gated decision.

Updated final-audit count: `0` blocker / `1` high / `4` medium / `6` low.
The remaining high finding is HIGH-3 provider reversal ingress/sandbox
acceptance.

## Checked Version

- Working folder:
  `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- Initial `git status --short`: already dirty before this re-audit, including
  tracked runtime/data/test/recovery files and untracked Stage 18 sales
  follow-up files/docs. This re-audit did not normalize or revert that state.

## Original Finding

`docs/recovery-integration/final-pre-release-audit.md` listed HIGH-7 as
`Timed Unpaid Funnel Is Design-Only` because only the design document existed
and production code had no durable 2h/1d/2d follow-up queue, opt-out, dedupe,
or cancellation implementation.

## Evidence By Stage

Stage 18B storage:

- `src/diet_bot/sales_followup.py` defines the `free_trial_v1` campaign, exact
  8-step schedule, exact payload fields, safe callback target mapping, and
  FOOD20 text-only step.
- `src/diet_bot/postgres_sales_followup_store.py` defines the schema
  expectation for `sales_followup_chains`, `sales_followup_jobs`,
  `sales_followup_preferences`, and `sales_followup_campaigns`.
- `create_chain()` is transactional, creates one active chain and exactly
  8 queued jobs, returns existing idempotency hits, and suppresses second active
  chains for the same `chat_id + campaign_key`.
- Campaign rows are inserted with `enabled=false`.

Stage 18C scheduler admission:

- `_send_trial_plan()` schedules only after `_send_plan()` succeeds and the
  existing trial subscription CTA is sent.
- `_prepare_one_day_generation_delivery(...).after_success()` schedules only
  after durable one-day delivery succeeds, recipe history is recorded, and the
  trial CTA is sent.
- Admission requires feature enabled, Postgres store, private chat, successful
  `free_one_day_delivery`, source `free_trial`, trial CTA, no active paid
  access, no weekly PDF access, and no opt-out preference.
- `/start`, questionnaire-only events, failed/partial delivery, paid one-day,
  weekly PDF, non-private chat, and already-paid/access users do not admit a
  chain.

Stage 18D worker runtime:

- `SalesFollowupWorker` claims only due active-chain jobs, uses lease/heartbeat,
  rechecks eligibility before send, records `send_started_at` and sent state,
  retries known transient failures, suppresses permanent failures, and marks
  unknown send outcomes for manual review.
- Claiming respects first-unfinished-step ordering and does not reclaim
  already-send-started running jobs.
- The worker is injectable/mocked in unit tests and is still gated by the
  disabled-by-default runtime flag.

Stage 18E Telegram rendering and opt-out:

- `render_sales_followup_payload()` preserves `message_text` exactly and builds
  a two-row keyboard: stored safe CTA callback plus opt-out callback
  `diet:sales_followup_opt_out`.
- Unsafe, unresolved, missing, mismatched, or too-long callback targets fail
  closed.
- `_TelegramSalesFollowupSender` uses the renderer and `safe_telegram_send()`.
- `_handle_sales_followup_opt_out_callback()` writes the opt-out preference,
  cancels queued/running-unsent jobs for the chat/campaign when a store exists,
  and confirms without touching transactional/payment/support messages.

Stage 18F cancellation and eligibility:

- `_apply_successful_payment()` cancels only after a processed successful grant:
  subscription -> `subscription_granted`; extra weekly PDF ->
  `weekly_pdf_access_granted`.
- `_activate_promo_code_for_chat()` and `_activate_postgres_promo_code_for_chat()`
  cancel after monthly-access promo grants.
- `_record_successful_generation_history()` and queued weekly PDF
  `after_success` cancel after successful weekly PDF delivery.
- `_start_sales_followup_worker_if_configured()` wires production send-time
  eligibility checks for active paid access, weekly PDF access, and known
  non-private chat type.
- Store-level `cancel_active_jobs_for_chat_campaign()` cancels queued or
  running-unsent jobs only; already send-started/sent jobs are not rewritten.

## Exact 8-Step Contract

Verified steps and offsets:

| Step | Offset | Target |
| --- | --- | --- |
| `m01_two_hours` | 2 hours | `diet:week_pdf` |
| `m02_one_day` | 1 day | `diet:week_pdf` |
| `m03_two_days` | 2 days | `diet:week_pdf` |
| `m04_three_days_food20` | 3 days | `diet:subscribe_month` |
| `m05_one_week` | 7 days | `diet:week_pdf` |
| `m06_two_weeks` | 14 days | `diet:week_pdf` |
| `m07_one_month` | 30 days | `diet:week_pdf` |
| `m08_six_weeks` | 45 days | `diet:week_pdf` |

`tests/test_sales_followup.py` asserts exact step keys, offsets, message texts,
button labels, payload step keys, and callback mapping. FOOD20 appears only in
the fourth message text; the fourth button targets the existing subscription
flow and not promo redemption.

## Disabled / Approval Gates

- `RuntimeConfig.sales_followup_enabled` defaults to `False`.
- `RuntimeConfig.sales_followup_worker_enabled` defaults to `False`.
- `.env.example` sets `DIET_BOT_SALES_FOLLOWUP_ENABLED=0` and
  `DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED=0`.
- Startup validation requires Postgres storage and `DIET_BOT_DATABASE_URL` when
  sales follow-up is enabled.
- Worker startup requires the worker flag and a configured Postgres runtime.
- Campaign storage defaults `enabled=false`.
- No campaign flag, worker flag, campaign row enablement, FOOD20 promo seed,
  FOOD20 redemption, discount/payment metadata, or launch path was activated.

## Commands And Results

- `git status --short`
  - existing dirty working tree before re-audit; no forbidden cleanup done.
- `git branch --show-current`
  - `codex/recover-product-ui-on-hardened-master`
- `git rev-parse HEAD`
  - `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- `PYTHONPATH=src python -m pytest tests/test_sales_followup.py tests/test_sales_followup_runtime.py -q`
  - `26 passed in 0.17s`
- Disposable local Postgres:
  - container: `foodbalance-sales-followup-reaudit-pg-20260531183148`
  - database: `diet_bot_test`
  - DSN used only in process environment:
    `postgresql://postgres:postgres@127.0.0.1:57899/diet_bot_test`
  - container stopped after verification.
- `PYTHONPATH=src DIET_BOT_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:57899/diet_bot_test python -m pytest tests/test_postgres_sales_followup_store.py -q`
  - `10 passed in 3.40s`
- `PYTHONPATH=src python -m pytest tests/test_telegram_app_runtime.py -q`
  - `44 passed in 10.71s`
- `PYTHONPATH=src python -m pytest tests/test_subscriptions.py tests/test_payments.py tests/test_promo_codes.py -q`
  - `62 passed in 0.28s`
- DB-only cancellation probe against the same disposable test DB:
  - created one `free_trial_v1` chain, called
    `cancel_active_jobs_for_chat_campaign(...)`, and verified
    `cancelled_jobs=8`, `chain_status=cancelled`,
    `skip_reason=reaudit_access_granted`.
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings
    only.

## Changed Files

Created/updated by this re-audit:

- `docs/recovery-integration/final-audit-sales-followup-reaudit.md`
- `docs/recovery-integration/recovery-status.md`

No code, data, config, env, tests, secrets, payment, recipe, PDF, Telegram
runtime, or campaign state was changed by this re-audit.

## Not Done

- Did not enable `DIET_BOT_SALES_FOLLOWUP_ENABLED`.
- Did not enable `DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED`.
- Did not enable a `sales_followup_campaigns` row.
- Did not start the bot, polling, webhook, or `getUpdates`.
- Did not call Telegram API.
- Did not use production DB or real secrets.
- Did not perform real payments, refunds, reversals, chargebacks, or provider
  actions.
- Did not activate, seed, redeem, or wire FOOD20 into payment metadata.
- Did not deploy, push, commit, tag, create a PR, touch archive,
  `New project 2 CLEAN`, recovered bot, or HIGH-3.

## Decision

HIGH-7 is closed for the current local release candidate. The funnel is
implemented and test-covered as a disabled-by-default durable feature. It is
not launch-enabled; enabling it still requires explicit campaign/worker
approval and safe staging/manual smoke.

Updated count: `0 blocker / 1 high / 4 medium / 6 low`.

Remaining high: HIGH-3 provider reversal ingress/sandbox acceptance.

## Next Recommended Prompt

Re-audit or fix only HIGH-3 provider reversal ingress/sandbox acceptance in
FoodBalance.

Scope:
- Work only in `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`.
- Read the final pre-release audit HIGH-3 section and current payment reversal
  docs/code/tests.
- Do not touch sales follow-up campaign enablement, FOOD20, Telegram bot
  runtime/API/getUpdates, production DB, real payments/refunds/provider actions,
  deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or recovered
  bot.
- Return a verdict on whether HIGH-3 remains open, what evidence supports it,
  and the next safe implementation or acceptance step.
