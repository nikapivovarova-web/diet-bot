# Final Audit MEDIUM-1 Start State Fix

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Scope

Fixed only `MEDIUM-1`: repeated `/start` leaving active questionnaire/trial
state behind.

The checkout was already dirty before this fix. This scoped change touched only
the `/start` cleanup boundary, one nearby `/start`/questionnaire regression
test, and recovery documentation.

Forbidden areas remained untouched: payments/provider/refunds, sales follow-up
stages, recipes/data/PDF, bot process startup, Telegram API/getUpdates,
production DB, deploy, push, commit, tag, PR, secrets/env files, archive,
`New project 2 CLEAN`, recovered bot, and other final-audit medium/low
findings.

## Root Cause

`start()` cleared support and promo request state before rendering the welcome
or subscriber menu, but it did not clear:

- `SESSION_BY_CHAT_ID`
- `QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID`
- `TRIAL_CHAT_IDS`

That allowed a user to see a fresh `/start` menu while the old active trial
questionnaire still existed. A later free-text answer could continue the stale
questionnaire instead of behaving like a fresh menu state.

## Fix

`start()` now clears the active questionnaire session and session token with
`_clear_questionnaire_session(message.chat.id)`, then discards the same chat
from `TRIAL_CHAT_IDS`, before rendering the `/start` result.

No resume model was added because the existing `/start` behavior presents a
fresh entry screen or subscriber cabinet rather than an explicit questionnaire
resume prompt.

## Behavior Before / After

Before:

- Active trial questionnaire starts and stores a session token.
- User sends `/start`.
- Welcome/subscriber menu is sent, but the old questionnaire session and trial
  marker stay active.
- A later text answer can advance the stale questionnaire.

After:

- Active trial questionnaire starts and stores a session token.
- User sends `/start`.
- `/start` removes the questionnaire session, token, and trial marker before
  rendering the menu.
- A later text answer no longer advances the old questionnaire; it falls back to
  the normal "press a button to build a ration" menu path.

## Changed Files

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/final-audit-medium-start-state-fix.md`
- `docs/recovery-integration/recovery-status.md`

## Tests

RED reproduced before the production fix:

- `pytest tests/test_telegram_app_photos.py::test_repeated_start_clears_active_trial_questionnaire_state -q`
  - result: `1 failed in 5.35s`
  - failure: `SESSION_BY_CHAT_ID` still contained the active questionnaire after
    `/start`.

Focused GREEN after the fix:

- `pytest tests/test_telegram_app_photos.py::test_repeated_start_clears_active_trial_questionnaire_state -q`
  - result: `1 passed in 4.39s`

Focused `/start`, privacy, support, and subscriber menu coverage:

- `pytest tests/test_telegram_app_photos.py::test_private_start_still_sends_welcome tests/test_telegram_app_photos.py::test_repeated_start_clears_active_trial_questionnaire_state tests/test_telegram_app_photos.py::test_private_callback_start_shows_privacy_consent_before_questionnaire tests/test_telegram_app_photos.py::test_support_callback_starts_request_mode tests/test_telegram_app_photos.py::test_start_sends_subscriber_cabinet_instead_of_free_trial -q`
  - result: `5 passed in 4.22s`

Requested test files:

- `pytest tests/test_telegram_app_runtime.py -q`
  - result: `44 passed in 8.71s`
- `pytest tests/test_telegram_app_photos.py -q`
  - result: `153 passed in 18.42s`
- `git diff --check`
  - exit code `0`
  - Git printed only LF-to-CRLF working-copy warnings in the already dirty
    checkout.

## Not Done

- Did not fix any other final-audit medium/low finding.
- Did not change payments/provider/refunds or provider reversal behavior.
- Did not change sales follow-up stages or worker behavior.
- Did not change recipes, curated data, photos, or PDF output.
- Did not run the bot, call Telegram API/getUpdates, use production DB, deploy,
  push, commit, tag, PR, or edit secrets/env files.
- Did not touch archive, `New project 2 CLEAN`, or recovered bot.

## Verdict

READY FOR MEDIUM-1 RE-AUDIT.
