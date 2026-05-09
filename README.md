# Telegram Diet Bot MVP

MVP for a Telegram nutrition assistant for adults 18+.

The current build focuses on the deterministic nutrition core:

- BMI, BMR, TDEE, calories, macros, and micronutrient targets.
- Allergy, gluten, lactose, and disease caution filters.
- A small built-in food catalog.
- A one-day nutrition builder with portion and diversity guardrails.
- Deterministic meal templates and shopping-list aggregation.
- Telegram `/start`, `/plan`, and `/cancel` flow using `aiogram`.

The OpenAI chef/dietitian adapters will sit on top of this core after the deterministic engine is stable.

## Run Telegram Bot

Create a bot in BotFather and set the token:

```powershell
$env:DIET_BOT_TOKEN = "123456:telegram-token"
$env:TELEGRAM_PROVIDER_TOKEN = "123456:TEST:telegram-provider-token" # YooKassa payments via Telegram
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m diet_bot.telegram_app
```

MVP commands:

- `/start`
- `/plan`
- `/cancel`

The bot also shows reply-keyboard buttons for starting a plan, choosing sex, goal, activity, meal count, and generating another one-day plan from the same profile.

## Run Tests

```bash
.\.venv\Scripts\python.exe -m pytest
```

## Run Demo

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m diet_bot.demo
```
