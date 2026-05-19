from __future__ import annotations

from collections import Counter

from diet_bot import builder as builder_module
from diet_bot.builder import (
    _build_recipe_plan_for_time,
    _cooking_effort_constraints,
    _cooking_effort_phases,
    _meal_energy_slots,
    _rank_recipes,
    _recipe_matches_cooking_effort,
    _recipe_slot_eligibility,
    _recipe_title_uses_excluded_food,
    _recipe_time_bucket,
    _resolve_recipe_ingredients,
    filter_foods,
)
from diet_bot.calculator import calculate_targets
from diet_bot.catalog import built_in_foods
from diet_bot.domain import (
    ActivityLevel,
    CookingTimePreference,
    Food,
    Goal,
    MealRole,
    NutrientVector,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
)
from diet_bot.recipe_catalog import RecipeTemplate, built_in_recipes
from diet_bot.safety import evaluate_safety, is_food_excluded, is_name_excluded


REVIEWED_BREAKFAST_FLEX_RECIPE_IDS = (
    "r595_lavash_s_gorbushey_i_ovoschami",
    "r596_tortilya_s_gorbushey_i_kukuruzoy",
    "r581_roll_s_tuntsom_i_kukuruzoy",
    "r511_sendvich_s_tuntsom",
    "r508_buterbrody_s_kuritsey_i_ovoschami",
    "r352_roll_s_krevetkami_avokado_laymom_i_tabasko",
    "r585_tost_s_sardinami_i_ogurtsom",
    "r592_tosty_s_seledkoy_i_svekloy",
    "r587_tosty_so_shprotami_ogurtsom_i_gorchitsey",
    "r351_ostrye_rolly_s_kuritsey_avokado_i_pechenym_pertsem",
    "r489_rulet_iz_lavasha_s_humusom",
    "r580_tost_s_humusom_i_zapechennym_pertsem",
    "r285_tost_iz_batata_s_tuntsom_avokado_i_nori",
    "r290_brusketta_s_tomatami_persikom_i_avokado",
    "r349_yablochnye_sendvichi_s_arahisovoy_pastoy_i_izyumom",
)

REVIEWED_MAIN_ELIGIBLE_RECIPE_IDS = frozenset(
    {
        "r595_lavash_s_gorbushey_i_ovoschami",
        "r596_tortilya_s_gorbushey_i_kukuruzoy",
        "r581_roll_s_tuntsom_i_kukuruzoy",
        "r511_sendvich_s_tuntsom",
        "r508_buterbrody_s_kuritsey_i_ovoschami",
        "r352_roll_s_krevetkami_avokado_laymom_i_tabasko",
        "r351_ostrye_rolly_s_kuritsey_avokado_i_pechenym_pertsem",
    }
)


def profile_with(**kwargs) -> UserProfile:
    data = {
        "age": 32,
        "sex": Sex.MALE,
        "height_cm": 178,
        "weight_kg": 86,
        "goal": Goal.MAINTAIN,
        "activity": ActivityLevel.MODERATE,
        "meal_count": 5,
        "cooking_time": CookingTimePreference.SIMPLE,
    }
    data.update(kwargs)
    return UserProfile(**data)


def _food(
    food_id: str,
    *,
    category: str,
    energy: float,
    protein: float = 0.0,
    fat: float = 0.0,
    carbohydrate: float = 0.0,
    roles: frozenset[MealRole] = frozenset(),
) -> Food:
    return Food(
        id=food_id,
        name=f"{food_id} food",
        category=category,
        nutrients_per_100g=NutrientVector(
            {
                "energy_kcal": energy,
                "protein_g": protein,
                "fat_g": fat,
                "carbohydrate_g": carbohydrate,
            }
        ),
        roles=roles,
        max_per_meal_g=1000,
        max_per_day_g=5000,
    )


def _simple_recipe(
    recipe_id: str,
    *,
    title: str,
    instructions: str,
    time_text: str = "25 minutes",
    ingredients_g: dict[str, float] | None = None,
) -> RecipeTemplate:
    return RecipeTemplate(
        id=recipe_id,
        slot="main",
        title=title,
        ingredients_g=ingredients_g or {"chicken_breast": 140, "rice": 90, "tomato": 120},
        instructions=instructions,
        tags=frozenset({"curated"}),
        time_text=time_text,
    )


def test_interesting_effort_pool_includes_simple_curated_recipes() -> None:
    curated_recipes = [recipe for recipe in built_in_recipes() if "curated" in recipe.tags]

    simple_ids = {
        recipe.id
        for recipe in curated_recipes
        if _recipe_matches_cooking_effort(recipe, CookingTimePreference.SIMPLE)
    }
    interesting_ids = {
        recipe.id
        for recipe in curated_recipes
        if _recipe_matches_cooking_effort(recipe, CookingTimePreference.INTERESTING)
    }

    assert simple_ids
    assert simple_ids <= interesting_ids


def test_simple_strict_allows_ordinary_oven_pan_and_pot() -> None:
    ordinary_recipes = (
        _simple_recipe(
            "ordinary_oven",
            title="Simple baked chicken",
            instructions="Bake chicken and tomatoes in the oven. Serve with rice.",
        ),
        _simple_recipe(
            "ordinary_pan",
            title="Simple chicken skillet",
            instructions="Cook chicken in a pan. Warm rice and tomatoes.",
        ),
        _simple_recipe(
            "ordinary_pot",
            title="Simple chicken pot",
            instructions="Simmer chicken and rice in a pot. Stir in tomatoes.",
        ),
    )

    assert all(_recipe_matches_cooking_effort(recipe, CookingTimePreference.SIMPLE) for recipe in ordinary_recipes)


def test_simple_strict_excludes_rare_equipment() -> None:
    rare_equipment_recipes = (
        _simple_recipe("waffle", title="Savory waffle plate", instructions="Cook the batter in a waffle iron."),
        _simple_recipe("grill", title="Grilled chicken bowl", instructions="Cook the chicken on a grill."),
        _simple_recipe("processor", title="Chicken bowl", instructions="Chop the sauce in a food processor."),
    )

    assert all(not _recipe_matches_cooking_effort(recipe, CookingTimePreference.SIMPLE) for recipe in rare_equipment_recipes)
    assert all(
        _recipe_matches_cooking_effort(recipe, CookingTimePreference.INTERESTING)
        for recipe in rare_equipment_recipes
    )


def test_passive_overnight_time_can_be_simple_but_active_eight_hours_is_not() -> None:
    passive_overnight = _simple_recipe(
        "passive_overnight",
        title="Overnight chicken marinade bowl",
        instructions="Mix the marinade and chicken. Leave overnight in the fridge. Cook quickly in the morning.",
        time_text="10 minutes + 8 hours chilling",
    )
    active_eight_hours = _simple_recipe(
        "active_eight_hours",
        title="Slow active stew",
        instructions="Stir and tend the pot throughout cooking. Serve with rice.",
        time_text="8 hours active cooking",
    )

    assert _recipe_matches_cooking_effort(passive_overnight, CookingTimePreference.SIMPLE)
    assert not _recipe_matches_cooking_effort(active_eight_hours, CookingTimePreference.SIMPLE)


def test_active_time_metadata_overrides_passive_total_time_for_simple_effort() -> None:
    passive_roast = RecipeTemplate(
        id="passive_roast",
        slot="main",
        title="Passive roast chicken bowl",
        ingredients_g={"chicken_breast": 140, "potato": 180, "tomato": 120},
        instructions="Season the chicken and vegetables. Roast until done. Serve with tomato.",
        tags=frozenset({"curated"}),
        time_text="1 hour 15 minutes",
        active_time_min=15,
    )

    assert _recipe_matches_cooking_effort(passive_roast, CookingTimePreference.SIMPLE)
    assert _recipe_time_bucket(passive_roast) == "quick"


def test_kitchen_unit_abbreviations_do_not_inflate_instruction_sentence_count() -> None:
    concise_old_style_recipe = _simple_recipe(
        "old_style_abbreviations",
        title="Old style skillet pork",
        instructions=(
            "Season the pork. "
            "Warm 1/2 ч. л. olive oil in a skillet. "
            "Stir in 1 ст. л. sauce. "
            "Cook the pork until done. "
            "Warm the grains. "
            "Serve with greens."
        ),
        time_text="25 minutes",
    )

    assert _recipe_matches_cooking_effort(concise_old_style_recipe, CookingTimePreference.SIMPLE)


def test_simple_ingredient_count_ignores_basic_pantry_items_but_not_substantive_items() -> None:
    pantry_heavy_recipe = _simple_recipe(
        "pantry_heavy",
        title="Pantry counted bowl",
        ingredients_g={
            **{f"food_{index}": 10 for index in range(11)},
            "salt": 1,
            "black_pepper": 1,
            "olive_oil": 5,
            "water": 50,
        },
        instructions="Cook the grains. Warm the protein. Serve with vegetables.",
        time_text="25 minutes",
    )
    substantive_heavy_recipe = _simple_recipe(
        "substantive_heavy",
        title="Too many substantive ingredients",
        ingredients_g={f"food_{index}": 10 for index in range(12)},
        instructions="Cook the grains. Warm the protein. Serve with vegetables.",
        time_text="25 minutes",
    )

    assert _recipe_matches_cooking_effort(pantry_heavy_recipe, CookingTimePreference.SIMPLE)
    assert not _recipe_matches_cooking_effort(substantive_heavy_recipe, CookingTimePreference.SIMPLE)


def test_garlic_night_substring_does_not_make_simple_recipe_complex() -> None:
    garlic_recipe = _simple_recipe(
        "garlic_salmon",
        title="\u041b\u043e\u0441\u043e\u0441\u044c \u0441 \u0447\u0435\u0441\u043d\u043e\u0447\u043d\u044b\u043c \u0441\u043e\u0443\u0441\u043e\u043c",
        instructions="\u0417\u0430\u043f\u0435\u043a\u0438\u0442\u0435 \u043b\u043e\u0441\u043e\u0441\u044c. \u0421\u043c\u0435\u0448\u0430\u0439\u0442\u0435 \u0447\u0435\u0441\u043d\u043e\u0447\u043d\u044b\u0439 \u0441\u043e\u0443\u0441.",
        time_text="20 minutes",
    )

    assert _recipe_matches_cooking_effort(garlic_recipe, CookingTimePreference.SIMPLE)
    assert not is_name_excluded(
        "\u0447\u0435\u0441\u043d\u043e\u0447\u043d\u044b\u0439 \u0441\u043e\u0443\u0441",
        frozenset({"\u043d\u043e\u0447"}),
    )


def test_food_exclusion_boundaries_keep_eggplant_and_broccolini_behavior() -> None:
    egg_safety = evaluate_safety(
        profile_with(restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "egg"),))
    )
    eggplant = Food("eggplant", "eggplant", "vegetable", NutrientVector())
    egg = Food("egg", "egg", "protein", NutrientVector())

    assert not is_food_excluded(eggplant, egg_safety.excluded_food_names)
    assert is_food_excluded(egg, egg_safety.excluded_food_names)

    broccoli_safety = evaluate_safety(
        profile_with(
            restrictions=(
                Restriction(
                    RestrictionType.EXCLUDED_FOOD,
                    "\u0431\u0435\u0437 \u0431\u0440\u043e\u043a\u043a\u043e\u043b\u0438",
                ),
            )
        )
    )
    assert is_name_excluded("broccolini salad", broccoli_safety.excluded_food_names)
    assert not is_name_excluded("broccolinium supplement", broccoli_safety.excluded_food_names)


def _fallback_foods() -> list[Food]:
    return [
        _food("egg", category="protein", energy=150, protein=13, fat=10, roles=frozenset({MealRole.PROTEIN})),
        _food(
            "chicken_breast",
            category="protein",
            energy=165,
            protein=31,
            fat=4,
            roles=frozenset({MealRole.PROTEIN}),
        ),
        _food("tuna", category="protein", energy=130, protein=28, fat=1, roles=frozenset({MealRole.PROTEIN})),
        _food("pita", category="grains", energy=260, protein=8, carbohydrate=52, roles=frozenset({MealRole.CARB})),
        _food("rice", category="grains", energy=360, protein=7, carbohydrate=78, roles=frozenset({MealRole.CARB})),
        _food("tomato", category="vegetable", energy=20, protein=1, carbohydrate=4, roles=frozenset({MealRole.VEGETABLE})),
        _food("cucumber", category="vegetable", energy=15, protein=1, carbohydrate=3, roles=frozenset({MealRole.VEGETABLE})),
        _food("greek_yogurt", category="dairy", energy=95, protein=10, carbohydrate=4),
        _food("berries", category="fruit", energy=50, carbohydrate=12),
    ]


def _fallback_breakfast() -> RecipeTemplate:
    return RecipeTemplate(
        id="fallback_breakfast",
        slot="breakfast",
        title="Egg breakfast",
        ingredients_g={"egg": 200, "pita": 60},
        instructions="Cook eggs. Serve with pita.",
        tags=frozenset({"curated"}),
        time_text="10 minutes",
    )


def _main_like_snacks() -> tuple[RecipeTemplate, RecipeTemplate]:
    return (
        RecipeTemplate(
            id="snack_chicken_pita_roll",
            slot="snack",
            title="Chicken pita roll",
            ingredients_g={"chicken_breast": 180, "pita": 70, "cucumber": 100},
            instructions="Fill the pita with chicken and cucumber.",
            tags=frozenset({"curated"}),
            time_text="10 minutes",
        ),
        RecipeTemplate(
            id="snack_tuna_rice_bowl",
            slot="snack",
            title="Tuna rice bowl",
            ingredients_g={"tuna": 180, "rice": 80, "tomato": 120},
            instructions="Toss tuna, rice and tomato in a bowl.",
            tags=frozenset({"curated"}),
            time_text="10 minutes",
        ),
    )


def _snack_dessert(recipe_id: str = "snack_yogurt_berry_parfait") -> RecipeTemplate:
    return RecipeTemplate(
        id=recipe_id,
        slot="snack",
        title="Yogurt berry parfait",
        ingredients_g={"greek_yogurt": 350, "berries": 120},
        instructions="Layer yogurt and berries.",
        tags=frozenset({"curated"}),
        time_text="10 minutes",
    )


def _slot_recipe(
    recipe_id: str,
    *,
    slot: str,
    ingredients_g: dict[str, float] | None = None,
    allowed_meal_slots: tuple[str, ...] = (),
    slot_flex_type: str | None = None,
    cooking_effort: str | None = None,
    time_text: str = "10 minutes",
    title: str | None = None,
    instructions: str = "Assemble the test recipe.",
) -> RecipeTemplate:
    return RecipeTemplate(
        id=recipe_id,
        slot=slot,
        title=title or recipe_id.replace("_", " ").title(),
        ingredients_g=ingredients_g or {"chicken_breast": 180, "pita": 70, "cucumber": 100},
        instructions=instructions,
        tags=frozenset({"curated"}),
        time_text=time_text,
        allowed_meal_slots=allowed_meal_slots,
        slot_flex_type=slot_flex_type,
        cooking_effort=cooking_effort,
    )


def _slot_eligibility(recipe: RecipeTemplate, slot: str):
    helper = getattr(builder_module, "_recipe_slot_eligibility", None)
    assert helper is not None
    return helper(
        recipe,
        slot,
        {food.id: food for food in _fallback_foods()},
        600,
        NutrientVector({"energy_kcal": 1900, "protein_g": 80, "fat_g": 55, "carbohydrate_g": 220}),
    )


def _manual_like_profile_b() -> UserProfile:
    return profile_with(
        goal=Goal.LOSE,
        restrictions=(
            Restriction(RestrictionType.ALLERGY, "яйца"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "кисломолочные продукты"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "каша"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "молочка"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "молоко"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "грибы"),
        ),
    )


def _slot_target(profile: UserProfile, slot: str) -> tuple[dict[str, Food], NutrientVector, float]:
    safety = evaluate_safety(profile)
    targets = calculate_targets(profile)
    food_by_id = {food.id: food for food in filter_foods(built_in_foods(), safety)}
    total_energy = targets.targets.get("energy_kcal")
    energy_slot = next(energy_slot for energy_slot in _meal_energy_slots(profile.meal_count) if energy_slot.slot == slot)
    return food_by_id, targets.targets, total_energy * energy_slot.target_ratio


def _passes_hard_recipe_filters(recipe: RecipeTemplate, profile: UserProfile) -> bool:
    safety = evaluate_safety(profile)
    food_by_id = {food.id: food for food in filter_foods(built_in_foods(), safety)}
    if _resolve_recipe_ingredients(recipe, food_by_id) is None:
        return False
    if _recipe_title_uses_excluded_food(recipe, safety.excluded_food_names):
        return False
    return any(
        phase.constraints is None or _recipe_matches_cooking_effort(recipe, phase.constraints)
        for phase in _cooking_effort_phases(profile.cooking_time)
    )


def test_native_slot_recipe_is_eligible_without_flex_penalty() -> None:
    recipe = _slot_recipe("native_main", slot="main", allowed_meal_slots=("main",), slot_flex_type="main_only")

    result = _slot_eligibility(recipe, "main")

    assert result.eligible
    assert result.penalty == 0.0


def test_breakfast_snack_metadata_flexes_between_breakfast_and_snack_with_penalty() -> None:
    breakfast = _slot_recipe(
        "breakfast_snack_flex",
        slot="breakfast",
        ingredients_g={"egg": 120, "pita": 60},
        allowed_meal_slots=("breakfast", "snack"),
        slot_flex_type="breakfast_snack",
    )
    snack = _slot_recipe(
        "snack_breakfast_flex",
        slot="snack",
        ingredients_g={"egg": 120, "pita": 60},
        allowed_meal_slots=("breakfast", "snack"),
        slot_flex_type="breakfast_snack",
    )

    snack_result = _slot_eligibility(breakfast, "snack")
    breakfast_result = _slot_eligibility(snack, "breakfast")
    main_result = _slot_eligibility(breakfast, "main")

    assert snack_result.eligible
    assert snack_result.penalty > 0
    assert breakfast_result.eligible
    assert breakfast_result.penalty > 0
    assert not main_result.eligible


def test_explicit_breakfast_slot_extends_reviewed_snack_metadata() -> None:
    light_main_snack = _slot_recipe(
        "metadata_breakfast_light_main",
        slot="snack",
        allowed_meal_slots=("breakfast", "snack", "main"),
        slot_flex_type="snack_light_main",
    )
    snack_only = _slot_recipe(
        "metadata_breakfast_snack_only",
        slot="snack",
        allowed_meal_slots=("breakfast", "snack"),
        slot_flex_type="snack_only",
    )

    light_main_result = _slot_eligibility(light_main_snack, "breakfast")
    snack_only_result = _slot_eligibility(snack_only, "breakfast")

    assert light_main_result.eligible
    assert light_main_result.penalty > 0
    assert snack_only_result.eligible
    assert snack_only_result.penalty > 0


def test_reviewed_snack_recipes_are_breakfast_eligible_for_profile_b_when_hard_filters_pass() -> None:
    profile = _manual_like_profile_b()
    food_by_id, target, slot_energy_target = _slot_target(profile, "breakfast")
    recipe_by_id = {recipe.id: recipe for recipe in built_in_recipes()}
    hard_valid_ids = []

    for recipe_id in REVIEWED_BREAKFAST_FLEX_RECIPE_IDS:
        recipe = recipe_by_id[recipe_id]
        if not _passes_hard_recipe_filters(recipe, profile):
            continue
        hard_valid_ids.append(recipe_id)
        result = _recipe_slot_eligibility(recipe, "breakfast", food_by_id, slot_energy_target, target)
        assert result.eligible, recipe_id

    assert hard_valid_ids == list(REVIEWED_BREAKFAST_FLEX_RECIPE_IDS)


def test_reviewed_breakfast_unlock_preserves_existing_snack_and_main_eligibility() -> None:
    profile = _manual_like_profile_b()
    recipe_by_id = {recipe.id: recipe for recipe in built_in_recipes()}
    snack_food_by_id, snack_target, snack_energy_target = _slot_target(profile, "snack")
    main_food_by_id, main_target, main_energy_target = _slot_target(profile, "main")

    main_eligible_ids = set()
    for recipe_id in REVIEWED_BREAKFAST_FLEX_RECIPE_IDS:
        recipe = recipe_by_id[recipe_id]
        assert _recipe_slot_eligibility(recipe, "snack", snack_food_by_id, snack_energy_target, snack_target).eligible
        if _recipe_slot_eligibility(recipe, "main", main_food_by_id, main_energy_target, main_target).eligible:
            main_eligible_ids.add(recipe_id)

    assert main_eligible_ids == REVIEWED_MAIN_ELIGIBLE_RECIPE_IDS


def test_unrestricted_simple_curated_profile_still_builds_complete_day_after_breakfast_unlock() -> None:
    profile = profile_with(goal=Goal.LOSE)

    plan = builder_module.build_one_day_plan(profile, variety_seed=0, recipe_source="curated_only")

    assert len(plan.meals) == profile.meal_count
    assert all(meal.recipe_id for meal in plan.meals)


def test_main_only_metadata_does_not_flex_even_when_allowed_slots_claim_main() -> None:
    recipe = _slot_recipe(
        "metadata_main_only_snack",
        slot="snack",
        allowed_meal_slots=("snack", "main"),
        slot_flex_type="main_only",
    )

    result = _slot_eligibility(recipe, "main")

    assert not result.eligible


def test_snack_light_main_metadata_uses_existing_main_like_gates() -> None:
    structured = _slot_recipe(
        "metadata_light_main",
        slot="snack",
        allowed_meal_slots=("snack", "main"),
        slot_flex_type="snack_light_main",
    )
    dessert = _slot_recipe(
        "metadata_light_main_dessert",
        slot="snack",
        ingredients_g={"greek_yogurt": 350, "berries": 120},
        allowed_meal_slots=("snack", "main"),
        slot_flex_type="snack_light_main",
    )

    structured_result = _slot_eligibility(structured, "main")
    dessert_result = _slot_eligibility(dessert, "main")

    assert structured_result.eligible
    assert structured_result.penalty > 0
    assert not dessert_result.eligible


def test_legacy_snack_as_main_fallback_still_applies_without_explicit_metadata() -> None:
    legacy_snack = _slot_recipe("legacy_light_main", slot="snack")

    result = _slot_eligibility(legacy_snack, "main")

    assert result.eligible
    assert result.penalty > 0


def test_main_builder_can_use_high_protein_main_like_snack_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "diet_bot.builder.built_in_recipes",
        lambda: (_fallback_breakfast(), *_main_like_snacks(), _snack_dessert()),
    )

    meals = _build_recipe_plan_for_time(
        _fallback_foods(),
        NutrientVector({"energy_kcal": 1900, "protein_g": 80, "fat_g": 55, "carbohydrate_g": 220}),
        3,
        CookingTimePreference.SIMPLE,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
    )

    recipe_ids = {meal.recipe_id for meal in meals}
    assert {"snack_chicken_pita_roll", "snack_tuna_rice_bowl"} <= recipe_ids
    assert "snack_yogurt_berry_parfait" not in recipe_ids
    assert all(meal.recipe_key and meal.recipe_key.split(":", 1)[0] == "main" for meal in meals[1:])


def test_snack_dessert_does_not_fill_main_slot(monkeypatch) -> None:
    monkeypatch.setattr(
        "diet_bot.builder.built_in_recipes",
        lambda: (_fallback_breakfast(), _snack_dessert("snack_dessert_one"), _snack_dessert("snack_dessert_two")),
    )

    meals = _build_recipe_plan_for_time(
        _fallback_foods(),
        NutrientVector({"energy_kcal": 1900, "protein_g": 80, "fat_g": 55, "carbohydrate_g": 220}),
        3,
        CookingTimePreference.SIMPLE,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
    )

    assert meals == []


def test_slot_flex_does_not_relax_forbidden_ingredients(monkeypatch) -> None:
    egg = _food("egg", category="protein", energy=150, protein=13, fat=10, roles=frozenset({MealRole.PROTEIN}))
    safe = _food(
        "safe_high_protein",
        category="protein",
        energy=120,
        protein=24,
        fat=2,
        roles=frozenset({MealRole.PROTEIN}),
    )
    recipes = (
        _slot_recipe("safe_breakfast", slot="breakfast", ingredients_g={"safe_high_protein": 420}),
        _slot_recipe("safe_lunch", slot="main", ingredients_g={"safe_high_protein": 500}),
        _slot_recipe("safe_dinner", slot="main", ingredients_g={"safe_high_protein": 460}),
        _slot_recipe("safe_snack", slot="snack", ingredients_g={"safe_high_protein": 200}),
        _slot_recipe(
            "egg_flex_snack",
            slot="breakfast",
            ingredients_g={"egg": 250},
            allowed_meal_slots=("breakfast", "snack"),
            slot_flex_type="breakfast_snack",
        ),
    )
    safety = evaluate_safety(
        profile_with(restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "egg"),))
    )
    monkeypatch.setattr("diet_bot.builder.built_in_recipes", lambda: recipes)

    meals = _build_recipe_plan_for_time(
        filter_foods([egg, safe], safety),
        NutrientVector({"energy_kcal": 1600, "protein_g": 300, "fat_g": 45, "carbohydrate_g": 180}),
        4,
        CookingTimePreference.SIMPLE,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
        excluded_food_names=safety.excluded_food_names,
    )

    assert len(meals) == 4
    assert "egg_flex_snack" not in {meal.recipe_id for meal in meals}
    assert "egg" not in {portion.food.id for meal in meals for portion in meal.portions}


def test_requested_simple_uses_simple_recipes_when_available(monkeypatch) -> None:
    recipes = (
        _slot_recipe(
            "simple_breakfast",
            slot="breakfast",
            ingredients_g={"egg": 200, "pita": 60},
            cooking_effort="simple",
        ),
        _slot_recipe("fallback_simple_main_one", slot="main", cooking_effort="simple"),
        _slot_recipe("fallback_simple_main_two", slot="main", cooking_effort="simple"),
        _slot_recipe(
            "fallback_interesting_breakfast",
            slot="breakfast",
            ingredients_g={"egg": 200, "pita": 60},
            cooking_effort="interesting",
            time_text="40 minutes",
            instructions="Cook the batter in a waffle iron. Serve warm.",
        ),
        _slot_recipe(
            "fallback_interesting_main",
            slot="main",
            cooking_effort="interesting",
            time_text="40 minutes",
            instructions="Cook the chicken on a grill. Serve with rice.",
        ),
    )
    monkeypatch.setattr("diet_bot.builder.built_in_recipes", lambda: recipes)

    meals = _build_recipe_plan_for_time(
        _fallback_foods(),
        NutrientVector({"energy_kcal": 1900, "protein_g": 80, "fat_g": 55, "carbohydrate_g": 220}),
        3,
        CookingTimePreference.SIMPLE,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
    )

    assert {meal.recipe_id for meal in meals} == {
        "simple_breakfast",
        "fallback_simple_main_one",
        "fallback_simple_main_two",
    }


def test_requested_simple_can_complete_with_interesting_fallback_when_simple_pool_is_short(monkeypatch) -> None:
    recipes = (
        _slot_recipe(
            "fallback_interesting_breakfast",
            slot="breakfast",
            ingredients_g={"egg": 200, "pita": 60},
            cooking_effort="interesting",
            time_text="40 minutes",
            instructions="Cook the batter in a waffle iron. Serve warm.",
        ),
        _slot_recipe("fallback_simple_main_one", slot="main", cooking_effort="simple"),
        _slot_recipe("fallback_simple_main_two", slot="main", cooking_effort="simple"),
    )
    monkeypatch.setattr("diet_bot.builder.built_in_recipes", lambda: recipes)

    meals = _build_recipe_plan_for_time(
        _fallback_foods(),
        NutrientVector({"energy_kcal": 1900, "protein_g": 80, "fat_g": 55, "carbohydrate_g": 220}),
        3,
        CookingTimePreference.SIMPLE,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
    )

    assert len(meals) == 3
    assert {meal.recipe_id for meal in meals} == {
        "fallback_interesting_breakfast",
        "fallback_simple_main_one",
        "fallback_simple_main_two",
    }


def test_simple_effort_fallback_penalty_keeps_good_simple_recipe_ahead(monkeypatch) -> None:
    recipes = (
        _slot_recipe(
            "fallback_interesting_breakfast",
            slot="breakfast",
            ingredients_g={"egg": 200, "pita": 60},
            cooking_effort="interesting",
            time_text="40 minutes",
            instructions="Cook the batter in a waffle iron. Serve warm.",
        ),
        _slot_recipe("fallback_simple_main_one", slot="main", cooking_effort="simple"),
        _slot_recipe("fallback_simple_main_two", slot="main", cooking_effort="simple"),
        _slot_recipe(
            "fallback_interesting_main",
            slot="main",
            cooking_effort="interesting",
            time_text="40 minutes",
            instructions="Cook the chicken on a grill. Serve with rice.",
        ),
    )
    monkeypatch.setattr("diet_bot.builder.built_in_recipes", lambda: recipes)

    meals = _build_recipe_plan_for_time(
        _fallback_foods(),
        NutrientVector({"energy_kcal": 1900, "protein_g": 80, "fat_g": 55, "carbohydrate_g": 220}),
        3,
        CookingTimePreference.SIMPLE,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
    )

    assert len(meals) == 3
    assert "fallback_interesting_breakfast" in {meal.recipe_id for meal in meals}
    assert "fallback_interesting_main" not in {meal.recipe_id for meal in meals}


def test_requested_interesting_can_build_from_simple_recipes(monkeypatch) -> None:
    recipes = (
        _slot_recipe(
            "simple_breakfast",
            slot="breakfast",
            ingredients_g={"egg": 200, "pita": 60},
            cooking_effort="simple",
        ),
        _slot_recipe("fallback_simple_main_one", slot="main", cooking_effort="simple"),
        _slot_recipe("fallback_simple_main_two", slot="main", cooking_effort="simple"),
    )
    monkeypatch.setattr("diet_bot.builder.built_in_recipes", lambda: recipes)

    meals = _build_recipe_plan_for_time(
        _fallback_foods(),
        NutrientVector({"energy_kcal": 1900, "protein_g": 80, "fat_g": 55, "carbohydrate_g": 220}),
        3,
        CookingTimePreference.INTERESTING,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
    )

    assert len(meals) == 3
    assert {meal.recipe_id for meal in meals} == {
        "simple_breakfast",
        "fallback_simple_main_one",
        "fallback_simple_main_two",
    }


def test_effort_fallback_does_not_relax_allergy_filtered_foods(monkeypatch) -> None:
    egg = _food("egg", category="protein", energy=150, protein=13, fat=10, roles=frozenset({MealRole.PROTEIN}))
    safe = _food(
        "safe_high_protein",
        category="protein",
        energy=120,
        protein=24,
        fat=2,
        roles=frozenset({MealRole.PROTEIN}),
    )
    recipes = (
        _slot_recipe(
            "safe_interesting_breakfast",
            slot="breakfast",
            ingredients_g={"safe_high_protein": 420},
            cooking_effort="interesting",
            time_text="40 minutes",
            instructions="Cook the safe protein on a grill. Serve warm.",
        ),
        _slot_recipe(
            "safe_main_one",
            slot="main",
            ingredients_g={"safe_high_protein": 500},
            cooking_effort="simple",
        ),
        _slot_recipe(
            "safe_main_two",
            slot="main",
            ingredients_g={"safe_high_protein": 460},
            cooking_effort="simple",
        ),
        _slot_recipe(
            "egg_interesting_breakfast",
            slot="breakfast",
            ingredients_g={"egg": 300},
            cooking_effort="interesting",
            time_text="40 minutes",
            instructions="Cook the eggs in a waffle iron. Serve warm.",
        ),
    )
    safety = evaluate_safety(
        profile_with(restrictions=(Restriction(RestrictionType.ALLERGY, "egg"),))
    )
    monkeypatch.setattr("diet_bot.builder.built_in_recipes", lambda: recipes)

    meals = _build_recipe_plan_for_time(
        filter_foods([egg, safe], safety),
        NutrientVector({"energy_kcal": 1600, "protein_g": 300, "fat_g": 45, "carbohydrate_g": 180}),
        3,
        CookingTimePreference.SIMPLE,
        0,
        frozenset(),
        frozenset(),
        "curated_only",
        excluded_food_names=safety.excluded_food_names,
    )

    assert len(meals) == 3
    assert "egg_interesting_breakfast" not in {meal.recipe_id for meal in meals}
    assert "egg" not in {portion.food.id for meal in meals for portion in meal.portions}


def test_simple_main_eligible_coverage_exceeds_audit_baseline() -> None:
    profile = profile_with()
    target = calculate_targets(profile).targets
    food_by_id = {food.id: food for food in built_in_foods()}
    lunch_slot = _meal_energy_slots(5)[1]
    simple_curated = [
        recipe
        for recipe in built_in_recipes()
        if "curated" in recipe.tags and _recipe_matches_cooking_effort(recipe, _cooking_effort_constraints(CookingTimePreference.SIMPLE))
    ]

    def is_imported_intake(recipe) -> bool:
        return recipe.id.startswith("r") and recipe.id[1:4].isdigit() and int(recipe.id[1:4]) >= 401

    def ranked_main_count(recipes) -> int:
        return len(
            _rank_recipes(
                recipes,
                "main",
                set(),
                Counter(),
                Counter(),
                food_by_id,
                NutrientVector(),
                target,
                target.get("energy_kcal") * lunch_slot.target_ratio,
                target.get("energy_kcal") * lunch_slot.min_ratio,
                target.get("energy_kcal") * lunch_slot.max_ratio,
                0,
                1,
            )
        )

    legacy_eligible = ranked_main_count([recipe for recipe in simple_curated if not is_imported_intake(recipe)])
    eligible = ranked_main_count(simple_curated)

    assert legacy_eligible >= 70
    assert eligible >= 86
    assert eligible - legacy_eligible >= 26
