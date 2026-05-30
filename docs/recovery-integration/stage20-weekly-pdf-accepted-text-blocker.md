# Stage 20E Weekly PDF Accepted-Text Blocker

## Root Cause

- Reproduced the focused blocker with
  `pytest tests/test_weekly_pdf_postgres_wiring.py::test_postgres_admission_returns_accepted_without_entering_local_queue_or_starting -q`.
- The failing test showed `message.texts == []` while the test expected `WEEK_PDF_ACCEPTED_TEXT`.
- Investigation found this was a stale expectation after Stage 16. Stage 16 intentionally removed the separate durable Postgres admission notice; the single polished user-facing notice remains the weekly PDF status message sent by the queue/worker status path.
- `WEEK_PDF_ACCEPTED_TEXT` already aliases `WEEK_PDF_STATUS_INITIAL_TEXT`, so the old duplicate text is not the current expected copy.

## Change

- Updated `tests/test_weekly_pdf_postgres_wiring.py` so the durable Postgres admission-only path does not require a separate accepted-text send.
- Added an explicit assertion that the retired duplicate text `Готовлю недельный PDF. Я пришлю его сюда, как только он будет готов.` is not sent.
- Left `src/diet_bot/telegram_app.py`, payment/store tests, runtime worker guard, PDF renderer/layout, recipes/data, and promo behavior untouched.

## Verification

- `pytest tests/test_weekly_pdf_postgres_wiring.py -q`
  - `24 passed`
- `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `36 passed`
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings only.
