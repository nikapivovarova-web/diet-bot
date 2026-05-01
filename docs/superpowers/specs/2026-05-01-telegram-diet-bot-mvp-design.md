# Telegram Diet Bot MVP Design

Date: 2026-05-01

## Goal

Build a Telegram bot for adults 18+ that collects a user's nutrition profile, calculates BMI and daily nutrition targets, applies allergies/intolerances/basic medical restrictions, constructs a one-day meal plan, turns it into 3-5 practical meals, and returns recipes plus a shopping list.

The bot is a nutrition planning assistant, not a medical device. For diagnosed diseases it may adapt obvious food restrictions, but every disease-related output must include a clear instruction to discuss the plan with a physician or clinical dietitian.

## MVP Scope

Included in MVP:

- Telegram chat flow for one-day meal planning.
- Adult users only: 18+.
- Intake questionnaire: age, sex, height, weight, goal, activity, allergies, intolerances, diagnosed diseases, excluded foods, preferred meal count, cooking complexity, budget, and food preferences.
- BMI calculation and category.
- Daily target calculation for calories, protein, fat, carbohydrates, fiber, and selected micronutrients.
- Food filtering for allergies, gluten, lactose, disliked foods, and selected disease cautions.
- One-day menu with 3-5 meals.
- Short recipes for each meal.
- Full-day nutrition totals.
- Shopping list generated from the final meals.
- Medical and limitation disclaimers.

Excluded from MVP:

- Pediatric nutrition.
- Pregnancy and lactation meal planning.
- Therapeutic diets as clinical prescriptions.
- Medication-specific diet management.
- Lab-result-based supplementation plans.
- Multi-week adaptive coaching.
- Payment, subscriptions, admin panel, and user-facing web app.

## Source Material

The user's DOCX files are used as internal knowledge material and product requirements context:

- `C:\Users\adck8\Downloads\Диетология и питание для безопасного похудения.docx`
- `C:\Users\adck8\Downloads\Диетология для набора массы тела.docx`
- `C:\Users\adck8\Downloads\Здоровое питание при нормальном ИМТ.docx`
- `C:\Users\adck8\Downloads\Диетология и правильное питание для здорового взрослого.docx`
- `C:\Users\adck8\Downloads\Диетология.docx`

Authoritative external references for rules and defaults:

- WHO healthy diet guidance.
- NIH Office of Dietary Supplements and National Academies DRI tables for micronutrient targets.
- USDA FoodData Central for food nutrient profiles.
- NIDDK/NHS guidance for celiac disease and gluten-free diet basics.

The DOCX material can inform explanations, prompts, and practical ranges. It must not override hard safety rules or authoritative references.

## Safety Position

The bot must separate "food restrictions" from "clinical treatment."

Hard exclusions:

- User allergy to a food excludes that food and obvious derivatives.
- Celiac disease or strict gluten intolerance excludes wheat, rye, barley, bulgur, couscous, semolina, spelt, ordinary pasta, bread, and baked goods. Oats are allowed only if explicitly marked gluten-free and the user allows them.
- Lactose intolerance excludes lactose-containing milk products unless the user allows lactose-free dairy.
- User-declared disliked or prohibited foods are excluded.

Disease caution mode:

- Chronic kidney disease / chronic renal failure: avoid very salty foods by default, avoid high-protein assumptions, warn that protein, sodium, potassium, and phosphorus require clinician supervision.
- Diabetes: avoid sugar-heavy plans and sweet drinks, prefer high-fiber carbohydrate sources, warn that medication and glucose targets require clinician supervision.
- Hypertension: reduce high-sodium and highly processed foods.
- GERD/gastritis: avoid aggressive spicy/acidic templates if reported.
- Gout: limit organ meats and excessive red meat by default.

Red flags:

- Age under 18.
- Pregnancy or lactation.
- Eating disorder history or current signs.
- Dialysis or severe kidney disease.
- Oncology treatment.
- Severe liver disease.
- Unexplained rapid weight loss.
- Very low BMI.

For red flags, the bot should not generate a personalized diet plan. It should provide a brief safety message and advise medical consultation.

Standard disclaimer:

"Этот рацион не является медицинским назначением или клинической рекомендацией. Если у вас есть диагностированное заболевание, особенно ХПН, диабет, целиакия или заболевания ЖКТ, согласуйте рацион с лечащим врачом или клиническим диетологом."

## System Architecture

Recommended MVP stack:

- Python.
- `aiogram` for Telegram bot.
- `FastAPI` service layer if the bot and engine need to be separated.
- PostgreSQL for users, profiles, plans, foods, nutrient tables, and generated outputs.
- USDA FoodData Central as the initial nutrient data source, with a curated local food table for Russian-language common products.
- OpenAI API for conversational agents, using structured outputs/function calls.

Core modules:

- `BotInterface`: Telegram messages, buttons, state machine, and user session routing.
- `IntakeAgent`: conversational questionnaire and missing-data repair.
- `SafetyFilter`: red flags, disease caution mode, allergy/intolerance exclusions.
- `NutritionCalculator`: BMI, calorie target, macro targets, fiber, water, and selected micronutrients.
- `FoodDatabase`: food search, nutrient profiles per 100 g, categories, tags, allergen flags, gluten/lactose flags.
- `NutritionBuilderEngine`: constructs the one-day food basket using nutrient deficits, portion rules, and diversity constraints.
- `ChefAgent`: converts the food basket into meals and recipes.
- `PlanValidator`: recalculates totals, checks restrictions, portion sanity, repeats, and nutrition target fit.
- `ShoppingListBuilder`: aggregates final ingredient quantities by category.

## Data Flow

1. User requests a meal plan.
2. `IntakeAgent` collects required inputs.
3. `SafetyFilter` classifies the profile:
   - allowed,
   - caution mode,
   - red flag stop.
4. `NutritionCalculator` calculates targets.
5. `FoodDatabase` returns eligible food candidates after restrictions.
6. `NutritionBuilderEngine` builds a one-day food basket and meal skeleton.
7. `ChefAgent` turns the basket into 3-5 meals.
8. `PlanValidator` recalculates the final plan.
9. If validation fails, the system adjusts portions or asks `ChefAgent` to revise within constraints.
10. Bot returns analysis, targets, meals, recipes, nutrition totals, shopping list, and disclaimers.

## Intake Questions

Required:

- Age.
- Sex.
- Height.
- Weight.
- Goal: lose weight, maintain weight, gain muscle/weight.
- Activity level.
- Allergies.
- Intolerances: lactose, gluten, other.
- Diagnosed diseases.
- Foods the user does not eat.
- Number of meals per day: 3, 4, or 5.
- Cooking complexity: very simple, normal, advanced.

Optional:

- Budget.
- Cuisine preferences.
- Vegetarian/vegan/halal/kosher/fasting restrictions.
- Training schedule.
- Preferred breakfast style.
- Permission for lactose-free dairy.
- Permission for gluten-free oats.

## Nutrition Targets

The calculator returns a structured target object:

```json
{
  "energy_kcal": 2000,
  "protein_g": 100,
  "fat_g": 65,
  "carbohydrate_g": 230,
  "fiber_g": 25,
  "sodium_mg_max": 2300,
  "potassium_mg": 3400,
  "calcium_mg": 1000,
  "magnesium_mg": 400,
  "iron_mg": 8,
  "vitamin_c_mg": 90,
  "vitamin_d_mcg": 15,
  "vitamin_b12_mcg": 2.4,
  "folate_mcg_dfe": 400,
  "vitamin_b6_mg": 1.3,
  "vitamin_a_mcg_rae": 900,
  "vitamin_e_mg": 15,
  "omega_3_mg": 1000
}
```

Target generation rules:

- Validate impossible macro combinations before planning. Example: 300 g fat cannot fit into a 2000 kcal target.
- Macro targets should be ranges where appropriate, not brittle exact values.
- Micronutrients should be treated as targets with practical tolerances, not all-or-nothing requirements.
- The bot may report partial coverage for nutrients that are hard to meet from food alone, especially vitamin D.

## Nutrient Vector Model

Every food stores a full nutrient vector per 100 g, not only calories and macros.

Example fields:

- Energy.
- Protein.
- Fat.
- Carbohydrates.
- Fiber.
- Sugars.
- Sodium.
- Potassium.
- Calcium.
- Magnesium.
- Iron.
- Zinc.
- Iodine if available.
- Selenium if available.
- Vitamin C.
- Vitamin D.
- Vitamin B12.
- Folate/B9.
- Vitamin B6.
- Vitamin A.
- Vitamin E.
- Omega-3 where available.

When adding a food portion, the engine subtracts all available nutrients from the remaining daily deficit. Missing nutrient data should be tracked as unknown rather than treated as zero when that distinction matters.

## Nutrition Builder Engine

The engine acts as a constructor with a running nutrient balance.

Inputs:

- User profile.
- Target nutrient vector.
- Food candidates.
- Meal count.
- Restriction rules.
- Portion rules.
- Diversity rules.

Outputs:

- Food basket with gram amounts.
- Meal skeleton: which foods should appear in breakfast, lunch, dinner, and snacks.
- Nutrition totals and remaining gaps.

Recommended algorithm for MVP: scoring-based greedy search with guardrails.

Process:

1. Create a meal skeleton:
   - Breakfast.
   - Lunch.
   - Dinner.
   - Optional 1-2 snacks.
2. Assign roles per meal:
   - Protein source.
   - Complex carbohydrate.
   - Vegetable/fruit.
   - Fat source.
   - Micronutrient booster.
3. Add foods iteratively.
4. After each food, subtract the full nutrient vector from remaining targets.
5. Score candidate foods by:
   - how much they close current deficits,
   - whether they fit the meal role,
   - whether they preserve calorie and macro balance,
   - whether they improve variety,
   - whether they avoid sodium/sugar/excess fat penalties,
   - whether portions remain normal.
6. Adjust portion sizes.
7. Stop when the plan is close enough or no useful candidate remains.

## Anti-Monotony and Portion Guardrails

The engine must prevent technically correct but absurd plans, such as 1 kg of pumpkin seeds or four meals of buckwheat with seeds.

Rules:

- Maximum portion per food per meal.
- Maximum total amount per food per day.
- Maximum calories from nuts/seeds/oils.
- Maximum number of meals containing the same staple.
- Minimum number of distinct food groups.
- Minimum number of distinct main ingredients.
- Protein should be distributed across meals.
- Vegetables/fruits should appear in more than one meal where possible.
- Micronutrient gaps should be solved by combining food groups, not by overloading one dense food.

Example default caps:

- Nuts/seeds: 20-40 g/day depending on calorie target.
- Oil: 10-25 g/day.
- Dry grains: 60-100 g per meal.
- Fruit: usually 1-3 portions/day.
- Eggs: practical cap unless user preference allows more.
- One staple grain: no more than 1-2 meals/day.

These values are configurable and should be stored as food-category rules rather than hard-coded in prompts.

## Chef Agent

The chef receives a constrained basket and meal skeleton. It does not invent extra major ingredients unless allowed.

Responsibilities:

- Turn selected foods into normal meals.
- Keep recipes short and practical.
- Respect meal roles and restrictions.
- Preserve ingredient quantities.
- Avoid mixing unrelated leftovers into strange dishes.
- Offer substitutions only from allowed foods.

Allowed meal templates:

- Porridge/breakfast bowl.
- Omelet/egg plate.
- Protein + grain + vegetables.
- Soup.
- Salad with protein.
- Bowl.
- Yogurt/cottage cheese style meal if lactose is allowed or lactose-free alternatives are selected.
- Sandwich/wrap only if gluten rules allow appropriate bread/wraps.
- Snack plate.

The chef output must be structured so the validator can parse ingredients and quantities.

## Validator

The validator is deterministic and runs after the chef.

Checks:

- User is 18+.
- No red flag plan was generated.
- No excluded foods or allergens are present.
- Gluten/lactose rules are respected.
- Disease caution rules are respected at the basic level.
- Calories are within tolerance.
- Protein, fat, carbohydrate are within tolerance.
- Fiber is reasonable.
- Sodium does not exceed the configured limit.
- No individual portion is absurd.
- No single food or category dominates the day.
- Meal count matches user preference.
- Shopping list matches meal ingredients.

If validation fails:

- Small nutrition miss: adjust portions and revalidate.
- Forbidden ingredient: remove and regenerate affected meal.
- Absurd repetition: rebuild meal skeleton with diversity penalty increased.
- Medical red flag: stop and return safety response.

## Telegram Output Format

The final response should be concise but complete:

1. Short profile summary.
2. BMI and interpretation.
3. Daily targets: calories, macros, fiber, and key micronutrients.
4. Important restrictions applied.
5. One-day meal plan with 3-5 meals.
6. Short recipes.
7. Full-day totals.
8. Remaining nutrient gaps if any.
9. Shopping list.
10. Disclaimer.

Example sections:

- "Ваш расчет"
- "Ограничения, которые я учел"
- "Рацион на день"
- "Итого за день"
- "Список покупок"
- "Важно"

## Data Model Draft

Tables:

- `users`: Telegram ID, created_at, locale.
- `profiles`: age, sex, height_cm, weight_kg, goal, activity_level, meal_count, budget, cooking_level.
- `restrictions`: profile_id, type, value, severity, notes.
- `conditions`: profile_id, condition_code, caution_level, notes.
- `foods`: id, canonical_name, ru_name, category, tags.
- `food_nutrients`: food_id, nutrient_code, amount_per_100g, unit, source.
- `food_flags`: food_id, contains_gluten, contains_lactose, high_sodium, common_allergen, notes.
- `portion_rules`: food_id or category, min_g, max_per_meal_g, max_per_day_g.
- `plans`: profile_id, target_json, final_totals_json, disclaimers, created_at.
- `plan_meals`: plan_id, meal_name, recipe_text, sort_order.
- `plan_ingredients`: meal_id, food_id, grams.
- `shopping_items`: plan_id, food_id, total_grams, category.

## Testing Strategy

Unit tests:

- BMI calculation.
- Calorie target calculation.
- Macro calorie consistency.
- Nutrient vector subtraction.
- Allergy exclusion.
- Gluten exclusion.
- Lactose exclusion.
- Portion caps.
- Shopping list aggregation.

Integration tests:

- Healthy adult weight loss plan.
- Healthy adult maintenance plan.
- Muscle gain plan.
- Gluten-free plan for celiac disease.
- Lactose-free plan.
- Apple allergy exclusion.
- Chronic kidney disease caution mode.
- Impossible target detection.

Golden-output tests:

- The final plan contains no forbidden ingredients.
- Full-day totals match ingredient totals.
- The chef does not introduce untracked ingredients.
- The shopping list equals the sum of meal ingredients.

## Acceptance Criteria

The MVP is successful when:

- A user can complete the questionnaire in Telegram.
- The bot generates a one-day plan for a healthy adult 18+.
- Allergies and intolerances reliably remove foods.
- Celiac/gluten and lactose cases are handled with strict filters.
- Basic disease caution messages are shown.
- The plan contains normal portions and varied meals.
- The shopping list is generated from actual meal ingredients.
- Nutrition totals are recalculated after meal generation.
- The bot refuses or redirects red-flag cases.

## Open Decisions for Implementation

- Whether to use only Mifflin-St Jeor for MVP or combine with DRI/EER formulas from the source material.
- Which USDA FoodData Central subset to import first.
- Exact Russian product dictionary and synonym list.
- Initial tolerance thresholds for calorie and macro matching.
- Whether omega-3 is represented as ALA only, EPA/DHA only, or a combined practical field.

These are implementation decisions, not blockers for the MVP design.
