# Release Smoke Checklist

Use this checklist from the clean worktree before publishing a Telegram bot release.

## 1. Worktree And Env

- Confirm the current branch is `codex/emergency-stabilization`.
- Confirm only release documentation/env files are changed for a docs-only release.
- Confirm `.env.example` contains only placeholders.
- Confirm local `.env` exists only on the machine or deployment host and is not staged.
- Confirm `DIET_BOT_ENV` is `development` or another non-production value for this clean runtime phase.
- Confirm `DIET_BOT_TOKEN` is set to a test or release Telegram bot token.
- Leave `TELEGRAM_PROVIDER_TOKEN` empty unless card-payment smoke is explicitly being tested with a Telegram/YooKassa test provider token.

## 2. Healthcheck

From `C:\Users\adck8\Documents\New project 2 CLEAN`:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
$env:DIET_BOT_ENV = "development"

& $py -m diet_bot.healthcheck --package-data-only
& $py -m diet_bot.healthcheck
```

Both commands should print `healthcheck: ok`.

## 3. Test Gates

Fast release gate:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
& $py -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder"
```

Full local suite:

```powershell
$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
& $py -m pytest -q -p no:cacheprovider
```

## 4. Start Bot

```powershell
Set-Location "C:\Users\adck8\Documents\New project 2 CLEAN"

$py = "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"
$env:DIET_BOT_ENV = "development"
$env:DIET_BOT_TOKEN = "replace-with-telegram-bot-token"
$env:TELEGRAM_PROVIDER_TOKEN = ""

& $py -m diet_bot.telegram_app
```

Expected: the process starts polling without a startup config error.

## 5. Manual Telegram Smoke

- Send `/start`; confirm the bot replies with the welcome flow and usable buttons.
- Start a one-day plan; complete sex, age, height, weight, goal, activity, meal count, allergies/restrictions, and excluded-food prompts.
- Confirm the generated one-day plan includes meals, portions, daily totals, and a shopping list.
- Tap the option to generate another one-day plan from the same profile; confirm a different/new plan is returned.
- Send `/plan`; confirm the plan flow can be started from the command.
- Send `/cancel` during an active flow; confirm state is cleared and the user can start again.
- If `DIET_BOT_SUPPORT_CHAT_ID` is configured, smoke the support request path and confirm the support chat receives the request.
- If `DIET_BOT_TESTER_CHAT_IDS` or an active subscription is configured, request the weekly PDF ration; confirm Telegram receives a document attachment with a PDF file.
- For weekly PDF failures, confirm the bot shows a PDF failure/status message and does not send a text weekly-menu fallback.
- Confirm weekly PDF success sends only the PDF document plus its caption; no text fallback menu should appear before or after the document.
- If `TELEGRAM_PROVIDER_TOKEN` is empty, confirm card payment attempts do not create a broken invoice and the user receives a configuration message.
- If `TELEGRAM_PROVIDER_TOKEN` is set to a test provider token, smoke one card invoice link with test credentials only.

## 6. Release Notes

- Record the exact healthcheck output.
- Record the fast-test command and result.
- Record the full-test command and result if it was run for the release.
- Record manual Telegram smoke results, including the weekly PDF-only check.
