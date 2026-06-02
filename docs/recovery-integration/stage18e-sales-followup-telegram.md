# Stage 18E Sales Follow-Up Telegram Rendering And Opt-Out Callback

## Scope

Stage 18E adds Telegram rendering/buttons and opt-out callback handling for
the already persisted sales follow-up payload contract. It does not start the
bot, call Telegram APIs, enable the campaign, enable worker flags, activate
`FOOD20`, change payment metadata, change payment/refund/provider behavior,
change recipes/data/PDF, deploy, push, commit, tag, create a PR, change
secrets/env files, archive work, `New project 2 CLEAN`, or recovered-bot work.

Implemented:

- Pure sales follow-up renderer for job payloads.
- Two-row inline keyboard contract:
  - row 1: exact payload `button_label` with exact stored safe
    `target_callback_data`;
  - row 2: `Не напоминать` with `diet:sales_followup_opt_out`.
- Fail-closed rendering for unresolved, missing, unsupported, mismatched, or
  too-long callback targets.
- Telegram worker sender adapter using the renderer plus the existing
  `safe_telegram_send()` abstraction.
- Disabled-by-default bot startup wiring for the sales follow-up worker, gated
  by `DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED`.
- Opt-out callback handler that writes the preference, cancels queued/running
  unsent sales follow-up jobs for the chat/campaign when a store is available,
  answers the callback, and edits or sends:
  `Хорошо, больше не буду напоминать.`
- Postgres store API for cancelling active sales follow-up jobs by
  `chat_id + campaign_key`.

## Renderer Behavior

`render_sales_followup_payload()` preserves `message_text` exactly and never
rewrites the 8 product texts. The main CTA button label is the exact persisted
`button_label`. The main CTA callback data is accepted only when it is already
stored in payload and matches the known safe target mapping.

Accepted mapping:

- `existing_weekly_pdf_flow` -> `diet:week_pdf`
- `existing_subscription_flow` -> `diet:subscribe_month`

Rejected mapping:

- `unresolved`
- missing `target_callback_data`
- unsupported target kind
- target kind/callback mismatch
- callback data outside Telegram callback size limits

The renderer does not invent callback data.

## Opt-Out Behavior

The opt-out callback data is `diet:sales_followup_opt_out`. It affects only
sales follow-up reminders:

- `store.set_opt_out(chat_id, opt_out_source="telegram_callback")`
- `store.cancel_active_jobs_for_chat_campaign(..., reason="opted_out",
  chain_status="opted_out")`

The cancellation API updates only `sales_followup_*` tables. It cancels queued
and running-unsent jobs for active chains in the selected chat/campaign and
marks the chain `opted_out`. It does not touch transactional/payment/support
messages, entitlements, payments, refunds, subscriptions, recipes, data, or
PDF generation.

If no store is available, the callback still fails gracefully: it answers the
callback and confirms the preference in chat without crashing. Repeated opt-out
callbacks are safe and idempotent at the handler level.

## Callback Mapping Proof

Existing CTA callbacks used:

- weekly PDF flow: `CALLBACK_WEEK_PLAN_PDF == "diet:week_pdf"`
- subscription flow: `CALLBACK_SUBSCRIBE == "diet:subscribe_month"`

New opt-out callback:

- `CALLBACK_SALES_FOLLOWUP_OPT_OUT == "diet:sales_followup_opt_out"`

The opt-out callback does not collide with the weekly PDF or subscription
callbacks.

## Exact Text And Button Proof

`tests/test_sales_followup.py::test_sales_followup_renderer_preserves_exact_payloads_and_adds_opt_out_button`
asserts all 8 rendered `message_text` values equal the existing
`EXPECTED_MESSAGE_TEXTS`, all main button labels equal the existing
`EXPECTED_BUTTON_LABELS`, and every rendered keyboard contains:

- row 1: exact payload CTA label and exact payload safe callback;
- row 2: `Не напоминать` and `diet:sales_followup_opt_out`.

`tests/test_sales_followup.py::test_sales_followup_renderer_fails_closed_for_unresolved_or_missing_callback_target`
asserts unresolved or missing callbacks are not sendable and produce no
keyboard.

## Disabled And No-Live-Send Proof

- `DIET_BOT_SALES_FOLLOWUP_ENABLED` remains disabled by default.
- `DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED` remains disabled by default.
- The new sender is only used if the existing disabled-by-default worker flag is
  explicitly enabled.
- No bot process was started in this stage.
- No Telegram API, polling, `getUpdates`, production DB, deploy, push, commit,
  tag, PR, or secrets/env change was performed.
- Tests use fake bot/context/store only.

## Verification

RED before implementation:

- `PYTHONPATH=src pytest tests/test_sales_followup.py::test_sales_followup_renderer_preserves_exact_payloads_and_adds_opt_out_button tests/test_sales_followup.py::test_sales_followup_renderer_fails_closed_for_unresolved_or_missing_callback_target -q`
  - failed during collection because the renderer and opt-out constants did not
    exist.
- `PYTHONPATH=src pytest tests/test_telegram_app_runtime.py::test_sales_followup_sender_renders_exact_text_and_two_row_keyboard tests/test_telegram_app_runtime.py::test_sales_followup_opt_out_callback_writes_preference_cancels_jobs_and_confirms tests/test_telegram_app_runtime.py::test_sales_followup_opt_out_callback_handles_missing_store_gracefully tests/test_telegram_app_runtime.py::test_sales_followup_opt_out_does_not_affect_other_callbacks tests/test_telegram_app_runtime.py::test_sales_followup_callback_mapping_reuses_existing_weekly_pdf_and_subscription_callbacks -q`
  - `4 failed, 1 passed`; failures were missing
    `_TelegramSalesFollowupSender` and `CALLBACK_SALES_FOLLOWUP_OPT_OUT`.

GREEN after implementation:

- `PYTHONPATH=src pytest tests/test_sales_followup.py::test_sales_followup_renderer_preserves_exact_payloads_and_adds_opt_out_button tests/test_sales_followup.py::test_sales_followup_renderer_fails_closed_for_unresolved_or_missing_callback_target -q`
  - `2 passed`
- `PYTHONPATH=src pytest tests/test_telegram_app_runtime.py::test_sales_followup_sender_renders_exact_text_and_two_row_keyboard tests/test_telegram_app_runtime.py::test_sales_followup_opt_out_callback_writes_preference_cancels_jobs_and_confirms tests/test_telegram_app_runtime.py::test_sales_followup_opt_out_callback_handles_missing_store_gracefully tests/test_telegram_app_runtime.py::test_sales_followup_opt_out_does_not_affect_other_callbacks tests/test_telegram_app_runtime.py::test_sales_followup_callback_mapping_reuses_existing_weekly_pdf_and_subscription_callbacks -q`
  - `5 passed`
- `PYTHONPATH=src pytest tests/test_sales_followup.py tests/test_sales_followup_runtime.py -q`
  - `26 passed`
- `PYTHONPATH=src pytest tests/test_telegram_app_runtime.py::test_sales_followup_sender_renders_exact_text_and_two_row_keyboard tests/test_telegram_app_runtime.py::test_sales_followup_opt_out_callback_writes_preference_cancels_jobs_and_confirms tests/test_telegram_app_runtime.py::test_sales_followup_opt_out_callback_handles_missing_store_gracefully tests/test_telegram_app_runtime.py::test_sales_followup_opt_out_does_not_affect_other_callbacks tests/test_telegram_app_runtime.py::test_sales_followup_callback_mapping_reuses_existing_weekly_pdf_and_subscription_callbacks tests/test_telegram_app_runtime.py::test_payment_callback_double_click_reuses_pending_order_without_second_invoice tests/test_telegram_app_photos.py::test_support_callback_starts_request_mode tests/test_telegram_app_photos.py::test_non_private_callback_rejects_before_state_mutation tests/test_telegram_app_photos.py::test_plan_choice_keyboard_has_day_and_week_pdf_buttons -q`
  - `11 passed`
- `PYTHONPATH=src pytest tests/test_telegram_app_runtime.py::test_telegram_app_import_does_not_import_postgres_or_psycopg_on_json_path -q`
  - `1 passed`
- `PYTHONPATH=src pytest tests/test_telegram_app_runtime.py -q`
  - `33 passed`
- `git diff --check`
  - exit code `0`; output contained only existing LF-to-CRLF working-copy
    warnings.

## Changed Files

- `src/diet_bot/sales_followup.py`
- `src/diet_bot/postgres_sales_followup_store.py`
- `src/diet_bot/telegram_app.py`
- `tests/test_sales_followup.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/stage18e-sales-followup-telegram.md`
- `docs/recovery-integration/recovery-status.md`

## Stage 18F Remaining Work

- Live eligibility source wiring for paid access, weekly PDF access, and chat
  type in the production worker path, if not already fully covered by the
  approved runtime.
- Dedicated send-stage/manual-smoke approval before any real bot run.
- Campaign enablement remains a separate explicit decision.
- `FOOD20` activation/redemption/payment discount remains blocked until its
  dedicated promo/payment stage.

## Verdict

READY FOR NEXT SALES FOLLOW-UP STAGE
