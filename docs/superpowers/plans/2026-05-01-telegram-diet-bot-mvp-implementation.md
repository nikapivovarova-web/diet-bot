# Telegram Diet Bot MVP Implementation Plan

Date: 2026-05-01

## Milestone 1: Project Skeleton

Create a Python project with a clear separation between the Telegram interface and deterministic nutrition logic.

Deliverables:

- `pyproject.toml`
- `README.md`
- `src/diet_bot/`
- `tests/`

## Milestone 2: Core Domain

Implement typed domain objects:

- User profile.
- Restrictions.
- Medical conditions.
- Nutrient vector.
- Food.
- Meal.
- Meal plan.
- Shopping list item.

The core domain must not depend on Telegram, OpenAI, or a database.

## Milestone 3: Nutrition Calculator

Implement deterministic calculations:

- BMI.
- BMI category.
- BMR using Mifflin-St Jeor.
- TDEE with activity multiplier.
- Calorie target by goal.
- Macro target ranges.
- Initial micronutrient targets for adults.
- Macro-energy consistency validation.

## Milestone 4: Safety Filter

Implement rules for:

- Age under 18 red flag.
- Allergy exclusions.
- Gluten/celiac exclusions.
- Lactose intolerance exclusions.
- Chronic kidney disease caution mode.
- Diabetes, hypertension, GERD/gastritis, gout caution tags.

The filter returns:

- `can_generate_plan`
- hard excluded food tags/names
- caution notes
- user-facing disclaimers

## Milestone 5: Food Data MVP

Add a small built-in food catalog for local testing.

The catalog should include enough variety to test:

- grains/starches,
- protein sources,
- vegetables,
- fruits,
- dairy and lactose-free alternatives,
- nuts/seeds/oils,
- gluten-containing foods,
- high-sodium foods.

Later this layer will be replaced or expanded with USDA FoodData Central import.

## Milestone 6: Nutrition Builder Engine

Implement a scoring-based constructor:

- Start with meal skeleton.
- Filter candidate foods.
- Add foods by role.
- Subtract the full nutrient vector after every addition.
- Enforce per-food and per-category caps.
- Penalize repetition.
- Penalize sodium/sugar/fat excess.
- Prefer diverse food groups.

The first engine can be simple but must expose clear extension points.

## Milestone 7: Chef and Shopping List

Implement deterministic MVP chef templates before using an LLM:

- Breakfast bowl.
- Protein + grain + vegetables.
- Salad/bowl.
- Snack plate.

Generate:

- meal names,
- ingredient grams,
- short recipe text,
- shopping list aggregated by ingredient.

The future LLM chef will consume the same structured plan and must pass validation.

## Milestone 8: Validation

Validate:

- no forbidden food,
- no absurd portions,
- calories and macros within tolerance,
- meal count correct,
- shopping list equals ingredient totals,
- disease caution disclaimers included.

## Milestone 9: Telegram Adapter

Add an `aiogram` adapter after the core engine is tested.

MVP bot commands:

- `/start`
- `/plan`
- questionnaire flow
- final one-day plan response

## Milestone 10: Tests

Add unit tests for:

- BMI and targets.
- impossible macro targets.
- allergy exclusion.
- gluten exclusion.
- lactose exclusion.
- CKD caution.
- full nutrient vector subtraction.
- portion caps.
- shopping list aggregation.

## Current First Build

For the first code pass, implement milestones 1-8 with a deterministic command-line demo. Telegram and OpenAI integration come after the nutrition engine is stable.
