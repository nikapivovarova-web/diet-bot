# Final Audit MEDIUM-1 Start State Re-Audit

Date: 2026-05-31
Branch: `codex/recover-product-ui-on-hardened-master`
HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

## Scope

Re-audited only `MEDIUM-1`: repeated `/start` previously left stale
questionnaire/trial state active.

Read-only inputs:

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_photos.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/final-audit-medium-start-state-fix.md`

Documentation updates:

- `docs/recovery-integration/final-audit-medium-start-state-reaudit.md`
- `docs/recovery-integration/recovery-status.md`

The checkout was already dirty before this re-audit. No code or test file was
changed in this pass.

## Static Evidence

- `start()` rejects non-private chats first, then clears local request/session
  state before rendering the fresh `/start` result:
  - `SUPPORT_REQUEST_CHAT_IDS.discard(message.chat.id)`
  - `PROMO_CODE_REQUEST_CHAT_IDS.discard(message.chat.id)`
  - `_clear_questionnaire_session(message.chat.id)`
  - `TRIAL_CHAT_IDS.discard(message.chat.id)`
- `_clear_questionnaire_session()` removes both:
  - `SESSION_BY_CHAT_ID`
  - `QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID`
- The cleanup runs before the welcome photo, active-paid-access check,
  subscriber cabinet branch, saved-profile main-menu branch, and fresh welcome
  menu branch.
- The focused regression test starts an active trial questionnaire, confirms the
  session, token, and trial marker exist, sends `/start`, confirms all three are
  removed, then sends a stale text answer and verifies the old trial
  questionnaire does not continue.
- Nearby coverage still checks ordinary private `/start`, privacy consent,
  support request mode, and subscriber cabinet/menu behavior.

## Command Evidence

Initial provenance:

- `git status --short`
  - Existing dirty audit/recovery checkout before this re-audit.
- `git branch --show-current`
  - `codex/recover-product-ui-on-hardened-master`
- `git rev-parse HEAD`
  - `13d085c5a0459d1fd449a823cec19cb16b6f5e77`

Requested verification:

- `pytest tests/test_telegram_app_photos.py::test_repeated_start_clears_active_trial_questionnaire_state -q`
  - `1 passed in 3.75s`
- `pytest tests/test_telegram_app_runtime.py -q`
  - `44 passed in 7.96s`
- `pytest tests/test_telegram_app_photos.py -q`
  - `153 passed in 15.28s`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.

## Updated Count

`MEDIUM-1` is closed by this re-audit.

Remaining local final pre-release audit count:

- `0` high
- `3` medium
- `6` low

`HIGH-3` sandbox/provider acceptance remains a separate paid-launch acceptance
gate and was not exercised in this re-audit.

## Not Done

- Did not change application code.
- Did not change tests.
- Did not fix other medium or low findings.
- Did not run the bot.
- Did not call Telegram API or `getUpdates`.
- Did not use production DB.
- Did not touch payments/provider/refunds.
- Did not touch sales follow-up.
- Did not deploy, push, commit, tag, or open a PR.
- Did not touch archive, `New project 2 CLEAN`, or recovered bot.

## Verdict

`MEDIUM-1` is closed.

Official count after this re-audit: `0 high / 3 medium / 6 low`.
