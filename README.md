# Telegram Diet Bot MVP

MVP for a Telegram nutrition assistant for adults 18+.

The current build focuses on the deterministic nutrition core:

- BMI, BMR, TDEE, calories, macros, and micronutrient targets.
- Allergy, gluten, lactose, and disease caution filters.
- A small built-in food catalog.
- A one-day nutrition builder with portion and diversity guardrails.
- Deterministic meal templates and shopping-list aggregation.

The Telegram and OpenAI adapters will sit on top of this core after the engine is stable.

## Run Tests

```bash
.\.venv\Scripts\python.exe -m pytest
```

## Run Demo

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m diet_bot.demo
```
