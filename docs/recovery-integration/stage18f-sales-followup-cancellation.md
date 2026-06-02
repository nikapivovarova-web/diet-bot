# Stage 18F Sales Follow-Up Cancellation and Eligibility Integration

## Scope

Stage 18F closes the sales follow-up cancellation and production eligibility
integration left after Stage 18E. The campaign and worker remain disabled by
default, `FOOD20` remains inactive, and no live Telegram, provider, production
database, deploy, git, secret/env, recipe/data, PDF, price, discount metadata,
or payment-provider action was performed.

## Changed Files

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/stage18f-sales-followup-cancellation.md`
- `docs/recovery-integration/recovery-status.md`

## Exact Hooks Wired

- `_apply_successful_payment(...)` now cancels active sales follow-up jobs only
  after a processed successful payment application grants access:
  `subscription` uses reason `subscription_granted`, and `extra_weekly_pdf`
  uses reason `weekly_pdf_access_granted`.
- `_activate_promo_code_for_chat(...)` cancels after the JSON promo path
  successfully applies the monthly-access entitlement, using reason
  `monthly_access_promo_granted`.
- `_activate_postgres_promo_code_for_chat(...)` cancels after the Postgres promo
  path successfully applies the monthly-access entitlement, using reason
  `monthly_access_promo_granted`.
- `_record_successful_generation_history(...)` cancels after successful direct
  weekly PDF generation/delivery history recording, using reason
  `weekly_pdf_delivered`.
- `_prepare_weekly_pdf_delivery(...).after_success` cancels after successful
  queued weekly PDF delivery, using reason `weekly_pdf_delivered`.
- `_start_sales_followup_worker_if_configured(...)` now passes the production
  eligibility checker into `SalesFollowupWorker`.

## Cancellation Behavior

All Stage 18F grant hooks reuse the existing durable store cancellation method:
`cancel_active_jobs_for_chat_campaign(chat_id, campaign_key="free_trial_v1",
reason=..., chain_status="cancelled")`. The store cancels only queued or
running-unsent jobs; jobs with `send_started_at` or `sent_at` already set are
not retroactively changed by this stage.

Cancellation is best-effort and access-preserving: if cancellation logging fails
after access has been granted, the user grant is not rolled back. The worker
still has send-time eligibility rechecks, so current access state can suppress a
future send even if an earlier cancellation attempt could not complete.

This stage does not cancel on payment order creation, failed/unprocessed payment
handling, pending invoice/order state, transient provider/payment errors,
refunds, reversals, or chargebacks. Existing reversal/revocation logic was not
changed.

## Eligibility Behavior

`SalesFollowupWorker` keeps the Stage 18D/18E guard order for campaign
enablement, opt-out preference, and cancelled/suppressed chain/job state. Stage
18F wires the production checker for the remaining send-time access checks:

- non-private chat is blocked when chat type is available in the job/payload;
- active paid subscription/access blocks the send via `_has_active_paid_access`;
- active weekly PDF access blocks the send via `_weekly_pdf_attempt_available`;
- a private no-access user remains eligible.

## Disabled-by-Default Proof

No Stage 18F code enables campaign admission or worker runtime flags. The
existing sales follow-up campaign remains disabled by default in storage, the
worker remains gated by the existing disabled-by-default runtime flag, and
`FOOD20` was not activated, seeded, or wired into payment metadata.

## Verification

- Focused RED before implementation:
  `pytest tests/test_telegram_app_runtime.py::<Stage 18F selectors> -q` ->
  `9 failed, 2 passed`.
- Focused GREEN after implementation:
  `pytest tests/test_telegram_app_runtime.py::<Stage 18F selectors> -q` ->
  `11 passed`.
- `pytest tests/test_sales_followup.py tests/test_sales_followup_runtime.py -q`
  -> `26 passed`.
- `pytest tests/test_subscriptions.py tests/test_payments.py tests/test_promo_codes.py -q`
  -> `62 passed`.
- `pytest tests/test_telegram_app_runtime.py::<Stage 18F selectors> -q` ->
  `11 passed`.
- `git diff --check` -> passed.

## Not Done

- No campaign/worker flag was enabled.
- No bot process was started.
- No Telegram API/getUpdates call was made.
- No production database was used.
- No real payment, refund, reversal, chargeback, or provider action was made.
- No `FOOD20` activation, seeding, redemption, or metadata work was done.
- No price, discount/payment metadata, recipe/data, or PDF change was made.
- No deploy, push, commit, tag, PR, secret/env, archive, `New project 2 CLEAN`,
  or recovered-bot work was done.

## Remaining Before Enabling Campaign

- Re-audit Stage 18F cancellation and eligibility behavior.
- Explicitly approve campaign enablement and worker runtime flags.
- Run the approved safe staging/manual smoke path with controlled credentials.
- Keep `FOOD20` as a separate promo/payment stage unless explicitly approved.
- Keep provider sandbox refund/cancel/reversal acceptance as a separate paid
  launch gate.

## Verdict

READY FOR SALES FOLLOW-UP RE-AUDIT.
