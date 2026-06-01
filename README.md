# FoodBalance Telegram Diet Bot

Telegram nutrition assistant for adults 18+.

The current release candidate combines deterministic meal planning with the
operational surfaces needed for controlled QA:

- BMI, BMR, TDEE, calories, macros, and micronutrient targets.
- Allergy, gluten, lactose, and disease caution filters.
- A curated recipe and food catalog with local recipe photos.
- One-day ration generation with portion and diversity guardrails.
- Weekly ration PDF rendering with shopping-list aggregation.
- Postgres-backed production storage and durable one-day / weekly-PDF queues.
- Controlled payment, promo, admin, reconciliation, and recovery tooling that
  remains disabled until explicit approval.
- Telegram `/start`, `/plan`, and `/cancel` flows using `aiogram`.

## Run Telegram Bot

Create a bot in BotFather and set the token:

```powershell
$env:DIET_BOT_TOKEN = "123456:telegram-token"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m diet_bot.telegram_app
```

Payments are disabled by default. Do not set `DIET_BOT_PAYMENTS_ENABLED` or
`TELEGRAM_PROVIDER_TOKEN` for normal local runs; payment QA and live payment
enablement require an explicit enablement decision.

Production operators should follow
[`docs/production-runbook.md`](docs/production-runbook.md) before any cutover.
Controlled QA without a production cutover is documented in
[`docs/controlled-qa-runbook.md`](docs/controlled-qa-runbook.md).

User commands:

- `/start`
- `/plan`
- `/cancel`

The bot also shows reply-keyboard buttons for starting a plan, choosing sex,
goal, activity, meal count, and generating another one-day plan from the same
profile.

## Run Tests

Install developer dependencies from the committed lock first:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

```bash
.\.venv\Scripts\python.exe -m pytest
```

Dependency lock maintenance is documented in
[`requirements/README.md`](requirements/README.md).

## Run Demo

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m diet_bot.demo
```
