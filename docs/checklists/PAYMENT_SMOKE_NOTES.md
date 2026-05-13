# Payment Smoke Notes

Date: 2026-05-13

Scope: manual payment smoke notes only. This document records observed results and safety reminders from the in-progress payments smoke. It does not approve paid launch and does not change payment or storage behavior.

## Preflight Reminder

- Run from `C:\Users\adck8\Documents\New project 2 CLEAN`.
- Confirm exactly one bot process is polling with the active Telegram bot token. Two processes with the same token can trigger `TelegramConflictError`.
- Keep `DIET_BOT_TESTER_CHAT_IDS` empty for payment smoke. If it contains the test chat id, test access is always true and payment access checks are not meaningful.
- Use the intended local PostgreSQL URL for the smoke environment and verify it is not printed in logs.
- Treat YooKassa and Telegram Stars paths as potentially real payments. Do not run a YooKassa real-payment checkout or spend Stars without separate explicit approval.

## Checked

- Bot startup/polling conflict behavior when duplicate bot instances use the same Telegram token.
- Payment-smoke access conditions with `DIET_BOT_TESTER_CHAT_IDS`.
- `/cancel` behavior during the Telegram UX flow.
- Free trial path through the first free ration.
- Weekly PDF delivery/design state as part of payment-adjacent smoke.
- YooKassa shop/provider safety before attempting checkout.

## Passed

- After stopping the extra bot process, the polling conflict was resolved.
- With payment smoke configured correctly, `DIET_BOT_TESTER_CHAT_IDS` should remain empty so test access does not mask payment gates.
- Free trial behaved as expected: after the first free ration, `free_trial_used=true`.

## Known Issues

- `/cancel` UX is misleading: it resets only the current action/flow, not the saved questionnaire/profile.
- Weekly PDF design is still the old/basic design. PDF redesign is a separate future phase, not part of this payment smoke slice.
- A YooKassa shop was identified as real-payment capable. Do not perform a real YooKassa payment without separate explicit consent.

## Smoke Limits

- This smoke was manual and focused on payment-adjacent behavior and safety observations, not full paid-launch approval.
- YooKassa and Telegram Stars can involve real charges depending on provider/shop/account configuration.
- Do not treat test-access success as evidence of paid entitlement success when `DIET_BOT_TESTER_CHAT_IDS` is set.
- Refunds, chargebacks, admin reconciliation, and full durable payment-ledger evidence remain separate launch-gate work.
