from __future__ import annotations

from collections import Counter
from dataclasses import replace

from diet_bot.builder import (
    _RecipePlanCache,
    _RankedRecipeCandidate,
    _cooking_effort_constraints,
    _meal_energy_slots,
    _rank_recipes,
    _recipe_matches_cooking_effort,
    _recipe_title_uses_excluded_food,
    _select_ranked_recipe_from_window,
    _resolve_recipe_ingredients,
    build_one_day_plan,
    filter_foods,
)
from diet_bot.calculator import calculate_targets
from diet_bot.catalog import built_in_foods
from diet_bot.chef import format_ingredient
from diet_bot.domain import (
    ActivityLevel,
    ConditionCode,
    CookingTimePreference,
    Food,
    Goal,
    Meal,
    NutrientVector,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
)
from diet_bot.recipe_catalog import RecipeTemplate, built_in_recipes
from diet_bot.safety import evaluate_safety
from diet_bot.shopping import build_shopping_list_for_meals
from diet_bot.validation import validate_plan


def _profile() -> UserProfile:
    return UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=5,
        cooking_time=CookingTimePreference.SIMPLE,
    )


def _hard_blender_profile() -> UserProfile:
    return UserProfile(
        age=32,
        sex=Sex.FEMALE,
        height_cm=168,
        weight_kg=68,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=5,
        cooking_time=CookingTimePreference.SIMPLE,
        conditions=(ConditionCode.LACTOSE_INTOLERANCE, ConditionCode.HYPERTENSION),
        restrictions=(
            Restriction(RestrictionType.ALLERGY, "\u044f\u0439\u0446\u0430"),
            Restriction(RestrictionType.ALLERGY, "\u043e\u0440\u0435\u0445\u0438"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "\u0433\u0440\u0438\u0431\u044b"),
            Restriction(RestrictionType.EXCLUDED_FOOD, "\u043a\u0438\u043d\u0437\u0430"),
        ),
    )


def test_simple_effort_allows_quick_blender_smoothie() -> None:
    smoothie = RecipeTemplate(
        id="quick_blender_smoothie",
        slot="snack",
        title="Berry smoothie",
        ingredients_g={"milk": 220, "banana": 120, "berries": 120},
        instructions="Add milk, banana, and berries to a blender. Blend until smooth and serve immediately.",
        tags=frozenset({"curated"}),
        time_text="5 minutes",
        active_time_min=5,
    )

    assert _recipe_matches_cooking_effort(smoothie, CookingTimePreference.SIMPLE)


def test_simple_effort_keeps_long_blender_cooking_complex() -> None:
    slow_soup = RecipeTemplate(
        id="slow_blender_soup",
        slot="main",
        title="Slow blender soup",
        ingredients_g={"lentils": 180, "tomato": 180, "carrot": 120, "onion": 80},
        instructions="Simmer the vegetables and lentils for 45 minutes. Blend the soup until smooth. Return it to the pot and cook again.",
        tags=frozenset({"curated"}),
        time_text="60 minutes",
        active_time_min=60,
    )

    assert not _recipe_matches_cooking_effort(slow_soup, CookingTimePreference.SIMPLE)


def test_simple_effort_allows_low_active_passive_fridge_recipe() -> None:
    overnight_oats = RecipeTemplate(
        id="overnight_oats",
        slot="breakfast",
        title="Overnight oats",
        ingredients_g={"oats": 45, "milk": 160, "banana": 100, "berries": 60},
        instructions=(
            "Mix oats and milk in a jar. "
            "Cover and refrigerate overnight for 8 hours. "
            "In the morning, top with banana and berries."
        ),
        tags=frozenset({"curated"}),
        time_text="8 hours",
    )

    assert _recipe_matches_cooking_effort(overnight_oats, CookingTimePreference.SIMPLE)


def test_simple_effort_keeps_long_active_cooking_complex() -> None:
    stew = RecipeTemplate(
        id="long_active_stew",
        slot="main",
        title="Long active stew",
        ingredients_g={"lentils": 160, "tomato": 150, "carrot": 90, "onion": 70},
        instructions=(
            "Chop the vegetables. "
            "Saute the onion and carrot. "
            "Add lentils and tomato. "
            "Simmer and stir for 55 minutes."
        ),
        tags=frozenset({"curated"}),
        time_text="55 minutes",
    )

    assert not _recipe_matches_cooking_effort(stew, CookingTimePreference.SIMPLE)


def test_simple_effort_keeps_overnight_with_complex_active_steps_complex() -> None:
    layered_breakfast = RecipeTemplate(
        id="complex_overnight_breakfast",
        slot="breakfast",
        title="Complex overnight breakfast",
        ingredients_g={
            "oats": 40,
            "milk": 140,
            "berries": 80,
            "banana": 90,
            "honey": 8,
            "cinnamon": 1,
            "walnuts": 12,
            "flour": 30,
            "butter": 10,
            "egg": 50,
            "cream_cheese": 35,
            "lemon_juice": 5,
        },
        instructions=(
            "Mix the oat base and refrigerate overnight. "
            "Cook a berry sauce until thick. "
            "Whisk a cream layer. "
            "Bake a crumble topping. "
            "Cool the topping. "
            "Slice the banana. "
            "Layer everything carefully before serving."
        ),
        tags=frozenset({"curated"}),
        time_text="8 hours",
    )

    assert not _recipe_matches_cooking_effort(layered_breakfast, CookingTimePreference.SIMPLE)


def test_hard_profile_blender_simple_recipes_enter_ranked_pool() -> None:
    profile = _hard_blender_profile()
    safety = evaluate_safety(profile)
    foods = filter_foods(built_in_foods(), safety)
    food_by_id = {food.id: food for food in foods}
    target = calculate_targets(profile).targets
    snack_slot = next(slot for slot in _meal_energy_slots(profile.meal_count) if slot.slot == "snack")
    strict_simple = _cooking_effort_constraints(CookingTimePreference.SIMPLE)
    recipes_by_id = {recipe.id: recipe for recipe in built_in_recipes()}

    def hard_safe_simple(recipe: RecipeTemplate) -> bool:
        return (
            "curated" in recipe.tags
            and _resolve_recipe_ingredients(recipe, food_by_id) is not None
            and not _recipe_title_uses_excluded_food(recipe, safety.excluded_food_names)
            and _recipe_matches_cooking_effort(recipe, strict_simple)
        )

    hard_safe_simple_recipes = [recipe for recipe in built_in_recipes() if hard_safe_simple(recipe)]
    blender_simple_ids = {
        recipe.id
        for recipe in hard_safe_simple_recipes
        if "blender" in recipe.instructions.lower() or "\u0431\u043b\u0435\u043d\u0434\u0435\u0440" in recipe.instructions.lower()
    }
    ranked_snacks = _rank_recipes(
        hard_safe_simple_recipes,
        "snack",
        set(),
        Counter(),
        Counter(),
        food_by_id,
        NutrientVector(),
        target,
        target.get("energy_kcal") * snack_slot.target_ratio,
        target.get("energy_kcal") * snack_slot.min_ratio,
        target.get("energy_kcal") * snack_slot.max_ratio,
        0,
        2,
    )

    assert {
        "r646_fruktovyy_smuzi_s_yogurtom",
        "r658_svekolnyy_humus_s_ovoschami",
    } <= blender_simple_ids
    assert "r214_pryanyy_chechevichnyy_sup_s_tomatami_i_keylom" not in blender_simple_ids
    assert "r417_aromatnyy_sup_pyure_iz_tsukini_i_chechevitsy" not in blender_simple_ids
    assert recipes_by_id["r658_svekolnyy_humus_s_ovoschami"] in ranked_snacks


def _milk_recipe() -> RecipeTemplate:
    return RecipeTemplate(
        id="milk_based_breakfast",
        slot="breakfast",
        title="Milk oats",
        ingredients_g={"milk": 180, "oats": 45, "banana": 100},
        instructions="Mix oats, milk, and banana. Chill and serve.",
        tags=frozenset({"curated"}),
        time_text="10 minutes",
        active_time_min=10,
        cooking_effort="simple",
    )


def _filtered_food_by_id(profile: UserProfile) -> dict[str, Food]:
    safety = evaluate_safety(profile)
    return {food.id: food for food in filter_foods(built_in_foods(), safety)}


def _hard_safe_simple_recipe_ids(food_by_id: dict[str, Food]) -> set[str]:
    strict_simple = _cooking_effort_constraints(CookingTimePreference.SIMPLE)
    return {
        recipe.id
        for recipe in built_in_recipes()
        if "curated" in recipe.tags
        and _resolve_recipe_ingredients(recipe, food_by_id) is not None
        and _recipe_matches_cooking_effort(recipe, strict_simple)
    }


def test_lactose_intolerance_resolves_milk_recipe_to_lactose_free_milk_without_mutating_source() -> None:
    profile = replace(_profile(), conditions=(ConditionCode.LACTOSE_INTOLERANCE,))
    recipe = _milk_recipe()
    original_ingredients = dict(recipe.ingredients_g)

    resolved = _resolve_recipe_ingredients(recipe, _filtered_food_by_id(profile))

    assert resolved is not None
    resolved_ids = [food.id for food, _grams in resolved]
    assert resolved_ids == ["lactose_free_milk", "oats", "banana"]
    assert recipe.ingredients_g == original_ingredients
    assert "lactose_free_milk" not in recipe.ingredients_g


def test_lactose_free_milk_substitution_is_visible_in_portions_shopping_and_pdf_ingredients() -> None:
    profile = replace(_profile(), conditions=(ConditionCode.LACTOSE_INTOLERANCE,))
    resolved = _resolve_recipe_ingredients(_milk_recipe(), _filtered_food_by_id(profile))

    assert resolved is not None
    milk_food, milk_grams = resolved[0]
    milk_portion = milk_food.portion(milk_grams)
    meal = Meal(
        name="Breakfast",
        portions=(milk_portion,),
        recipe="Serve.",
        recipe_id="milk_based_breakfast",
        recipe_key="breakfast:curated:milk_based_breakfast",
    )
    shopping = build_shopping_list_for_meals((meal,))

    assert milk_food.id == "lactose_free_milk"
    assert "\u0431\u0435\u0437\u043b\u0430\u043a\u0442\u043e\u0437" in milk_food.name.casefold()
    assert "\u0431\u0435\u0437\u043b\u0430\u043a\u0442\u043e\u0437" in format_ingredient(milk_portion).casefold()
    assert [item.food_name for item in shopping] == [milk_food.name]


def test_milk_allergy_and_explicit_milk_exclusion_block_lactose_free_milk_substitution() -> None:
    lactose_profile = replace(_profile(), conditions=(ConditionCode.LACTOSE_INTOLERANCE,))
    guarded_profiles = (
        replace(
            lactose_profile,
            restrictions=(Restriction(RestrictionType.ALLERGY, "milk"),),
        ),
        replace(
            lactose_profile,
            restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "milk"),),
        ),
        replace(
            lactose_profile,
            restrictions=(Restriction(RestrictionType.ALLERGY, "dairy"),),
        ),
    )

    for guarded_profile in guarded_profiles:
        food_by_id = _filtered_food_by_id(guarded_profile)

        assert "milk" not in food_by_id
        assert "lactose_free_milk" not in food_by_id
        assert _resolve_recipe_ingredients(_milk_recipe(), food_by_id) is None


def test_existing_lactose_free_yogurt_and_cottage_substitutions_do_not_bypass_exclusions() -> None:
    lactose_profile = replace(_profile(), conditions=(ConditionCode.LACTOSE_INTOLERANCE,))
    yogurt_recipe = RecipeTemplate(
        id="yogurt_recipe",
        slot="snack",
        title="Yogurt snack",
        ingredients_g={"greek_yogurt": 150, "berries": 100},
        instructions="Serve.",
        tags=frozenset({"curated"}),
    )
    cottage_recipe = RecipeTemplate(
        id="cottage_recipe",
        slot="snack",
        title="Cottage snack",
        ingredients_g={"cottage_cheese": 150, "berries": 100},
        instructions="Serve.",
        tags=frozenset({"curated"}),
    )

    dairy_allergy_foods = _filtered_food_by_id(
        replace(lactose_profile, restrictions=(Restriction(RestrictionType.ALLERGY, "dairy"),))
    )
    yogurt_exclusion_foods = _filtered_food_by_id(
        replace(lactose_profile, restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "yogurt"),))
    )
    cottage_exclusion_foods = _filtered_food_by_id(
        replace(lactose_profile, restrictions=(Restriction(RestrictionType.EXCLUDED_FOOD, "cottage cheese"),))
    )

    assert _resolve_recipe_ingredients(yogurt_recipe, dairy_allergy_foods) is None
    assert _resolve_recipe_ingredients(cottage_recipe, dairy_allergy_foods) is None
    assert _resolve_recipe_ingredients(yogurt_recipe, yogurt_exclusion_foods) is None
    assert _resolve_recipe_ingredients(cottage_recipe, cottage_exclusion_foods) is None


def test_lactose_free_milk_expands_hard_profile_strict_simple_eligible_pool() -> None:
    profile = _hard_blender_profile()
    food_by_id = _filtered_food_by_id(profile)
    without_lactose_free_milk = {
        food_id: food
        for food_id, food in food_by_id.items()
        if food_id != "lactose_free_milk"
    }

    recovered_ids = (
        _hard_safe_simple_recipe_ids(food_by_id)
        - _hard_safe_simple_recipe_ids(without_lactose_free_milk)
    )

    recipes_by_id = {recipe.id: recipe for recipe in built_in_recipes()}

    assert recovered_ids
    assert all("milk" in recipes_by_id[recipe_id].ingredients_g for recipe_id in recovered_ids)


def test_hard_profile_simple_blender_plans_have_no_validation_violations() -> None:
    profile = _hard_blender_profile()
    violations = []

    for seed in range(6):
        plan = build_one_day_plan(profile, variety_seed=seed, recipe_source="curated_only")
        validation = validate_plan(plan)

        assert len(plan.meals) == profile.meal_count
        violations.extend(validation.errors)

    assert violations == []


def test_hard_profile_controlled_topn_reaches_safe_docx_breakfast_candidate() -> None:
    profile = _hard_blender_profile()
    recipe_counts: Counter[str] = Counter()
    meal_slot_ids: dict[str, set[str]] = {"breakfast": set(), "snack": set()}
    violations: list[str] = []

    for seed in range(50):
        plan = build_one_day_plan(profile, variety_seed=seed, recipe_source="curated_only")
        violations.extend(validate_plan(plan).errors)
        assert len(plan.meals) == profile.meal_count
        for meal in plan.meals:
            assert meal.recipe_id is not None
            recipe_counts[meal.recipe_id] += 1
            if meal.recipe_key is not None:
                meal_slot = meal.recipe_key.split(":", 1)[0]
                if meal_slot in meal_slot_ids:
                    meal_slot_ids[meal_slot].add(meal.recipe_id)

    total_placements = sum(recipe_counts.values())
    repeat_rate = (total_placements - len(recipe_counts)) / total_placements

    assert violations == []
    assert len(recipe_counts) > 49
    assert len(meal_slot_ids["breakfast"]) > 8
    assert len(meal_slot_ids["snack"]) >= 20
    assert repeat_rate < 0.804
    assert recipe_counts["r657_veganskaya_shakshuka_s_tofu"] > 0


def test_ranked_recipe_window_falls_back_to_top_recipe_when_guard_rejects_alternative() -> None:
    top_recipe = RecipeTemplate(
        id="top_balanced_breakfast",
        slot="breakfast",
        title="Top balanced breakfast",
        ingredients_g={},
        instructions="Serve.",
        tags=frozenset({"curated"}),
    )
    high_sodium_recipe = RecipeTemplate(
        id="unsafe_sodium_breakfast",
        slot="breakfast",
        title="Unsafe sodium breakfast",
        ingredients_g={},
        instructions="Serve.",
        tags=frozenset({"curated"}),
    )
    target = NutrientVector({"energy_kcal": 2000, "protein_g": 100, "sodium_mg": 2300})
    ranked = (
        _RankedRecipeCandidate(
            recipe=top_recipe,
            score=10.0,
            projected=NutrientVector({"energy_kcal": 500, "protein_g": 25, "sodium_mg": 250}),
            rank=0,
        ),
        _RankedRecipeCandidate(
            recipe=high_sodium_recipe,
            score=9.8,
            projected=NutrientVector({"energy_kcal": 505, "protein_g": 25, "sodium_mg": 900}),
            rank=1,
        ),
    )

    selected = _select_ranked_recipe_from_window(
        ranked,
        used_recipe_counts=Counter(),
        used_food_ids=Counter(),
        used_formats=Counter(),
        current_total=NutrientVector(),
        target=target,
        slot_energy_target=500,
        variety_seed=8,
        index=0,
    )

    assert selected == top_recipe


def test_ranked_recipe_window_uses_seeded_variety_pressure_deterministically() -> None:
    top_recipe = RecipeTemplate(
        id="top_repeat_breakfast",
        slot="breakfast",
        title="Top repeat breakfast",
        ingredients_g={},
        instructions="Serve.",
        tags=frozenset({"curated"}),
    )
    alternative_recipe = RecipeTemplate(
        id="safe_alternative_breakfast",
        slot="breakfast",
        title="Safe alternative breakfast",
        ingredients_g={},
        instructions="Serve.",
        tags=frozenset({"curated"}),
    )
    target = NutrientVector({"energy_kcal": 2000, "protein_g": 100, "sodium_mg": 2300})
    ranked = (
        _RankedRecipeCandidate(
            recipe=top_recipe,
            score=10.0,
            projected=NutrientVector({"energy_kcal": 500, "protein_g": 25, "sodium_mg": 250}),
            rank=0,
        ),
        _RankedRecipeCandidate(
            recipe=alternative_recipe,
            score=9.7,
            projected=NutrientVector({"energy_kcal": 510, "protein_g": 27, "sodium_mg": 280}),
            rank=1,
        ),
    )
    kwargs = {
        "ranked": ranked,
        "used_recipe_counts": Counter({top_recipe.id: 2}),
        "used_food_ids": Counter(),
        "used_formats": Counter(),
        "current_total": NutrientVector(),
        "target": target,
        "slot_energy_target": 500,
        "variety_seed": 11,
        "index": 0,
    }

    first = _select_ranked_recipe_from_window(**kwargs)
    second = _select_ranked_recipe_from_window(**kwargs)

    assert first == alternative_recipe
    assert second == first


def test_rank_recipes_cache_reuses_projected_nutrients_without_changing_order() -> None:
    profile = _profile()
    safety = evaluate_safety(profile)
    foods = filter_foods(built_in_foods(), safety)
    food_by_id = {food.id: food for food in foods}
    target = calculate_targets(profile).targets
    total_energy = target.get("energy_kcal")
    kwargs = {
        "recipes": list(built_in_recipes()),
        "slot": "main",
        "used_recipe_ids": set(),
        "used_food_ids": Counter(),
        "used_formats": Counter(),
        "food_by_id": food_by_id,
        "current_total": NutrientVector(),
        "target": target,
        "slot_energy_target": total_energy * 0.30,
        "slot_min_energy": total_energy * 0.24,
        "slot_max_energy": total_energy * 0.38,
        "variety_seed": 101,
        "index": 1,
        "ranking_mode": "balanced",
    }

    uncached_ids = [recipe.id for recipe in _rank_recipes(**kwargs)]
    cache = _RecipePlanCache()
    first_cached_ids = [recipe.id for recipe in _rank_recipes(**kwargs, recipe_cache=cache)]
    projected_misses = cache.stats["projected_nutrients_misses"]
    second_cached_ids = [recipe.id for recipe in _rank_recipes(**kwargs, recipe_cache=cache)]

    assert first_cached_ids == uncached_ids
    assert second_cached_ids == uncached_ids
    assert projected_misses > 0
    assert cache.stats["projected_nutrients_misses"] == projected_misses
    assert cache.stats["projected_nutrients_hits"] > 0


def test_recipe_plan_cache_is_instance_scoped() -> None:
    profile = _profile()
    safety = evaluate_safety(profile)
    foods = filter_foods(built_in_foods(), safety)
    food_by_id = {food.id: food for food in foods}
    target = calculate_targets(profile).targets
    total_energy = target.get("energy_kcal")
    kwargs = {
        "recipes": list(built_in_recipes()),
        "slot": "snack",
        "used_recipe_ids": set(),
        "used_food_ids": Counter(),
        "used_formats": Counter(),
        "food_by_id": food_by_id,
        "current_total": NutrientVector(),
        "target": target,
        "slot_energy_target": total_energy * 0.10,
        "slot_min_energy": total_energy * 0.07,
        "slot_max_energy": total_energy * 0.16,
        "variety_seed": 101,
        "index": 2,
        "ranking_mode": "balanced",
    }

    first_cache = _RecipePlanCache()
    second_cache = _RecipePlanCache()

    _rank_recipes(**kwargs, recipe_cache=first_cache)

    assert first_cache.stats["projected_nutrients_misses"] > 0
    assert second_cache.stats["projected_nutrients_misses"] == 0
    assert second_cache.projected_nutrients == {}
