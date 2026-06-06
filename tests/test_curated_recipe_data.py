import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from diet_bot.builder import _add_missing_garnishes
from diet_bot.builder import build_one_day_plan
from diet_bot.builder import _resolve_recipe_ingredients
from diet_bot.curated_data import _cis_friendly_ingredient, _looks_incomplete_instruction, curated_foods, curated_recipes
from diet_bot.domain import ActivityLevel, Goal, Sex, UserProfile
from diet_bot.domain import Meal, NutrientVector
from diet_bot.recipe_catalog import built_in_recipes


DATA_DIR = Path(__file__).resolve().parents[1] / "src" / "diet_bot" / "data"
LEGACY_CURATED_RECIPE_COUNT = 400
DOCX_RECIPE_COUNT = 55
RESTORED_R401_R610_RECIPE_COUNT = 210
RESTORED_R666_R710_RECIPE_COUNT = 45
SECOND_PASS_IMPORT_RECIPE_COUNT = 157
SECOND_PASS_EXCLUDED_RECIPE_NOS = frozenset({856})
LOW_RISK_MISSING_FOOD_RECIPE_NOS = frozenset(
    {418, 429, 435, 471, 480, 484, 493, 495, 527, 562, 572, 684, 685}
)
TOTAL_CURATED_RECIPE_COUNT = (
    LEGACY_CURATED_RECIPE_COUNT
    + DOCX_RECIPE_COUNT
    + RESTORED_R401_R610_RECIPE_COUNT
    + RESTORED_R666_R710_RECIPE_COUNT
    + SECOND_PASS_IMPORT_RECIPE_COUNT
)
SELECTABLE_CURATED_RECIPE_COUNT = 834
DOCX_RECIPE_KEY_PREFIX = "docx20260520_"
DOCX_RECIPE_NOS = frozenset(range(611, 666))
EXCLUDED_MISSING_FOOD_RECIPE_NOS = frozenset()
RESTORED_R401_R610_RECIPE_NOS = frozenset(range(401, 611)) - EXCLUDED_MISSING_FOOD_RECIPE_NOS
RESTORED_R666_R710_RECIPE_NOS = frozenset(range(666, 711)) - EXCLUDED_MISSING_FOOD_RECIPE_NOS
RESTORED_RECIPE_NOS = RESTORED_R401_R610_RECIPE_NOS | RESTORED_R666_R710_RECIPE_NOS
SECOND_PASS_RECIPE_NOS = frozenset(range(711, 869)) - SECOND_PASS_EXCLUDED_RECIPE_NOS
USER_FACING_RECIPE_FIELDS = (
    "category_ru",
    "title_ru",
    "short_description_ru",
    "time_text",
    "instructions_ru",
    "source_name",
    "source_url",
)


def test_curated_recipe_data_has_full_calculation_coverage() -> None:
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))

    curated = curated_recipes()
    curated_ids = {recipe.id for recipe in curated}
    ingredient_ids = {row["recipe_id"] for row in ingredients}
    nutrition_ids = {row["recipe_id"] for row in nutrition}
    assert len(curated) == TOTAL_CURATED_RECIPE_COUNT
    assert curated_ids == ingredient_ids == nutrition_ids
    assert len(curated_foods()) >= 334
    assert all(recipe.instructions.rstrip().endswith(".") for recipe in curated)
    assert {row["calculation_status"] for row in nutrition} == {"ok"}
    assert all(row["unmatched_ingredient_count"] == 0 for row in nutrition)
    assert all(row["food_id"] and row["grams"] is not None for row in ingredients)


def test_curated_recipe_data_counts_extended_nutrients() -> None:
    foods = json.loads((DATA_DIR / "curated_foods.json").read_text(encoding="utf-8"))
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    fields = (
        "iodine_mcg",
        "selenium_mcg",
        "phosphorus_mg",
        "saturated_fat_g",
        "vitamin_k_mcg",
        "vitamin_b1_mg",
        "vitamin_b2_mg",
        "vitamin_b3_mg",
    )

    for field in fields:
        assert any(row["nutrients_per_100g"].get(field, 0) > 0 for row in foods), field
        assert any(row.get(field, 0) > 0 for row in nutrition), field


def test_gnocchi_recipe_uses_gnocchi_ingredient_name() -> None:
    foods = json.loads((DATA_DIR / "curated_foods.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    gnocchi_rows = [
        row
        for row in ingredients
        if row["recipe_id"] == "r176_nokki_kacho_e_pepe" and row["raw_text"].startswith("ньокки")
    ]

    assert gnocchi_rows
    assert gnocchi_rows[0]["ingredient_name_ru"] == "ньокки"
    assert gnocchi_rows[0]["food_id"] == "gnocchi"
    assert any(food["food_id"] == "gnocchi" and food["name_ru"] == "ньокки" for food in foods)


def test_curated_recipe_data_has_local_photos() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))

    assert len(recipes) == TOTAL_CURATED_RECIPE_COUNT
    assert all(recipe.get("image_url") for recipe in recipes)
    missing = [
        recipe["recipe_id"]
        for recipe in recipes
        if not (DATA_DIR / recipe["image_url"]).exists()
    ]
    assert missing == []


def test_restored_recipe_batches_have_expected_rows_and_photos() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    recipes_by_no = {int(recipe["recipe_no"]): recipe for recipe in recipes}

    assert len(RESTORED_R401_R610_RECIPE_NOS) == RESTORED_R401_R610_RECIPE_COUNT
    assert len(RESTORED_R666_R710_RECIPE_NOS) == RESTORED_R666_R710_RECIPE_COUNT
    assert set(recipes_by_no) & EXCLUDED_MISSING_FOOD_RECIPE_NOS == set()
    assert RESTORED_R401_R610_RECIPE_NOS <= set(recipes_by_no)
    assert RESTORED_R666_R710_RECIPE_NOS <= set(recipes_by_no)
    assert all(
        recipes_by_no[recipe_no].get("image_url") == f"recipe_photos/r{recipe_no}.jpg"
        for recipe_no in RESTORED_RECIPE_NOS
    )
    assert all((DATA_DIR / f"recipe_photos/r{recipe_no}.jpg").exists() for recipe_no in RESTORED_RECIPE_NOS)


def test_low_risk_missing_food_recipes_are_restored_with_resolved_foods_and_photos() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    foods = {food.id for food in curated_foods()}
    recipes_by_no = {int(recipe["recipe_no"]): recipe for recipe in recipes}
    recipe_ids = {
        recipes_by_no[recipe_no]["recipe_id"]
        for recipe_no in LOW_RISK_MISSING_FOOD_RECIPE_NOS
    }

    assert LOW_RISK_MISSING_FOOD_RECIPE_NOS <= set(recipes_by_no)
    assert all(
        recipes_by_no[recipe_no].get("image_url") == f"recipe_photos/r{recipe_no}.jpg"
        for recipe_no in LOW_RISK_MISSING_FOOD_RECIPE_NOS
    )
    assert all((DATA_DIR / f"recipe_photos/r{recipe_no}.jpg").exists() for recipe_no in LOW_RISK_MISSING_FOOD_RECIPE_NOS)
    assert {
        _cis_friendly_ingredient(row)[0]
        for row in ingredients
        if row["recipe_id"] in recipe_ids
    } <= foods


def test_second_pass_bulk_import_has_expected_rows_and_photos() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    recipes_by_no = {int(recipe["recipe_no"]): recipe for recipe in recipes}
    second_pass_ids = {recipes_by_no[recipe_no]["recipe_id"] for recipe_no in SECOND_PASS_RECIPE_NOS}

    assert len(SECOND_PASS_RECIPE_NOS) == SECOND_PASS_IMPORT_RECIPE_COUNT
    assert SECOND_PASS_RECIPE_NOS <= set(recipes_by_no)
    assert set(recipes_by_no) & SECOND_PASS_EXCLUDED_RECIPE_NOS == set()
    assert all(str(recipes_by_no[recipe_no]["recipe_key"]).startswith("second_pass") for recipe_no in SECOND_PASS_RECIPE_NOS)
    assert all(
        recipes_by_no[recipe_no].get("image_url") == f"recipe_photos/r{recipe_no}.png"
        for recipe_no in SECOND_PASS_RECIPE_NOS
    )
    assert all((DATA_DIR / f"recipe_photos/r{recipe_no}.png").exists() for recipe_no in SECOND_PASS_RECIPE_NOS)
    assert second_pass_ids <= {row["recipe_id"] for row in nutrition}
    assert second_pass_ids <= {row["recipe_id"] for row in ingredients}


def test_second_pass_bulk_import_has_reviewed_user_facing_copy_and_time_policy() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    second_pass_rows = _second_pass_recipe_rows(recipes)

    assert len(second_pass_rows) == SECOND_PASS_IMPORT_RECIPE_COUNT
    assert all(row.get("time_text", "").strip() for row in second_pass_rows)
    assert all("recipe importer preview row" not in row.get("short_description_ru", "").lower() for row in second_pass_rows)
    assert all(row.get("short_description_ru", "").strip() for row in second_pass_rows)
    assert all(row.get("active_time_min", 0) > 0 for row in second_pass_rows)
    assert all(row.get("passive_time_min", 0) >= 0 for row in second_pass_rows)
    assert {
        row["import_metadata"].get("time_policy")
        for row in second_pass_rows
    } <= {
        "second_pass_default:no_cook_or_quick_assembly",
        "second_pass_default:breakfast_or_snack",
        "second_pass_default:stovetop_main",
        "second_pass_default:baked_or_simmered_main",
    }


def test_second_pass_bulk_import_user_facing_text_has_no_control_chars_or_placeholders() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    second_pass_rows = _second_pass_recipe_rows(recipes)

    bad_values: list[tuple[int, str, str, str]] = []
    for row in second_pass_rows:
        for field in USER_FACING_RECIPE_FIELDS:
            value = str(row.get(field) or "")
            if _has_forbidden_user_facing_text(value):
                bad_values.append((int(row["recipe_no"]), row["recipe_id"], field, value))

    assert bad_values == []


def test_green_beans_unblocks_existing_r209_recipe() -> None:
    food_by_id = {food.id: food for food in curated_foods()}
    recipes = [recipe for recipe in built_in_recipes() if "curated" in recipe.tags]
    selectable_recipe_ids = {
        recipe.id
        for recipe in recipes
        if _resolve_recipe_ingredients(recipe, food_by_id) is not None
    }

    assert len(selectable_recipe_ids) == SELECTABLE_CURATED_RECIPE_COUNT
    assert "r209_kinoa_gado_gado_s_ovoschami_i_ostrym_arahisovym_sousom" in selectable_recipe_ids


def test_curated_recipe_instructions_use_regular_salt_wording() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))

    assert "кошерн" not in json.dumps(recipes, ensure_ascii=False).lower()


def test_curated_recipe_fixes_cover_truncated_soup_and_rye_crackers() -> None:
    recipes = {recipe.id: recipe for recipe in built_in_recipes()}
    foods = {food.id: food for food in curated_foods()}

    soup = recipes["r215_zolotoy_karri_sup_iz_krasnoy_chechevitsy_s_kokosovym_m"]
    crackers = recipes["r331_rzhanye_krekery_s_tykvennymi_semechkami"]

    assert "овощной бульон и кокосовое молоко" in soup.instructions
    assert soup.instructions.endswith("кокосовых сливок.")
    assert crackers.ingredients_g["rye_flour"] == 8.0
    assert crackers.ingredients_g["wheat_flour"] == 9.0
    assert foods["rye_flour"].name == "ржаная мука"
    assert "ржаную муку" in crackers.instructions
    assert "Раскатайте как можно тоньше" in crackers.instructions
    assert "Выпекайте 45 минут" in crackers.instructions
    assert "пеките еще 45 минут" in crackers.instructions


def test_curated_recipe_source_json_has_complete_soup_and_rye_crackers() -> None:
    recipes = {
        row["recipe_id"]: row
        for row in json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    }

    soup = recipes["r215_zolotoy_karri_sup_iz_krasnoy_chechevitsy_s_kokosovym_m"]["instructions_ru"]
    crackers = recipes["r331_rzhanye_krekery_s_tykvennymi_semechkami"]["instructions_ru"]

    assert "овощной бульон и кокосовое молоко" in soup
    assert soup.endswith("кокосовых сливок.")
    assert "Раскатайте как можно тоньше" in crackers
    assert "пеките еще 45 минут" in crackers


def test_curated_recipe_source_json_has_no_truncated_instructions() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))

    truncated = [
        (row["recipe_no"], row["title_ru"], row["instructions_ru"])
        for row in recipes
        if _looks_incomplete_instruction(row["instructions_ru"])
    ]

    assert truncated == []


def test_docx_recipe_batch_r611_r665_has_required_rows_and_photos() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))

    docx_rows = [row for row in recipes if int(row["recipe_no"]) in DOCX_RECIPE_NOS]
    docx_ids = {row["recipe_id"] for row in docx_rows}
    nutrition_ids = {row["recipe_id"] for row in nutrition}
    ingredient_counts = Counter(row["recipe_id"] for row in ingredients if row["recipe_id"] in docx_ids)

    assert len(docx_rows) == DOCX_RECIPE_COUNT
    assert {int(row["recipe_no"]) for row in docx_rows} == DOCX_RECIPE_NOS
    assert {int(row["recipe_no"]) for row in recipes if 401 <= int(row["recipe_no"]) <= 610} == (
        RESTORED_R401_R610_RECIPE_NOS
    )
    assert all(str(row["recipe_key"]).startswith(DOCX_RECIPE_KEY_PREFIX) for row in docx_rows)
    assert all(row["recipe_id"] in nutrition_ids for row in docx_rows)
    assert all(ingredient_counts[row["recipe_id"]] >= 4 for row in docx_rows)
    assert all(row.get("instructions_ru", "").strip().endswith(".") for row in docx_rows)
    assert all(row.get("image_url") == f"recipe_photos/r{row['recipe_no']}.jpg" for row in docx_rows)
    assert all((DATA_DIR / row["image_url"]).exists() for row in docx_rows)


def test_docx_recipe_batch_r611_r665_foods_are_resolved() -> None:
    foods = {food.id for food in curated_foods()}
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    missing_foods = sorted(
        {
            normalized_food_id
            for row in ingredients
            if 611 <= int(row.get("recipe_no") or 0) <= 665
            if (normalized_food_id := _cis_friendly_ingredient(row)[0]) not in foods
        }
    )

    assert missing_foods == []


def _second_pass_recipe_rows(recipes: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        row
        for row in recipes
        if int(row["recipe_no"]) in SECOND_PASS_RECIPE_NOS
    ]


def _has_forbidden_user_facing_text(value: str) -> bool:
    if "???" in value or "\ufffd" in value:
        return True
    return any(
        unicodedata.category(character)[0] == "C"
        and character not in {"\n", "\r", "\t"}
        for character in value
    )


def test_curated_recipe_titles_match_corrected_main_ingredients() -> None:
    recipes = {
        row["recipe_no"]: row
        for row in json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    }

    assert recipes[43]["title_ru"] == "Тост с яйцом, индейкой или курицей и овощами"
    assert recipes[44]["title_ru"] == "Пшеничный тортилья-ролл с курицей, перцем и яйцом"
    assert "Обжарьте курицу" in recipes[44]["instructions_ru"]
    assert recipes[321]["title_ru"] == "Творожный десерт в банке с персиком и пеканом"
    assert recipes[392]["title_ru"] == "Бальзамический салат с курицей, огурцом, черри, фетой и оливками"


def test_curated_recipe_ingredient_mapping_avoids_known_false_matches() -> None:
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))

    by_no_and_raw = {
        (row["recipe_no"], row["raw_text"]): row
        for row in ingredients
    }

    assert by_no_and_raw[(43, "готовая индейка или куриная грудка — 80 г")]["food_id"] == "turkey_or_chicken_breast"
    assert by_no_and_raw[(57, "Замороженное пюре асаи без сахара — около 225 г")]["food_id"] == "acai_puree"
    assert by_no_and_raw[(62, "масло бульонградной косточки — 2,5 мл")]["food_id"] == "vegetable_oil"
    assert by_no_and_raw[(63, "очень спелые бананы — 0,17 шт. / 13,3 г мякоти")]["food_id"] == "banana"
    assert by_no_and_raw[(209, "Вода для арахисового соуса — 30 мл")]["food_id"] == "water"
    assert by_no_and_raw[(238, "мангольд или кейл — 8 г")]["food_id"] == "kale"
    assert by_no_and_raw[(247, "арахисовое масло — 11 мл")]["food_id"] == "peanut_oil"
    assert by_no_and_raw[(247, "азиатское чили-масло — 0,5 мл")]["food_id"] == "chili_oil"
    assert by_no_and_raw[(287, "спелые томаты — 130 г")]["food_id"] == "tomato"
    assert by_no_and_raw[(306, "поджаренный грецкий орех или пекан — 5 г")]["food_id"] == "pecans"


def test_bare_animal_main_gets_deficit_based_garnish() -> None:
    foods = list(curated_foods())
    food_by_id = {food.id: food for food in foods}
    used_grams = defaultdict(float)
    used_counts = Counter()
    breakfast = Meal("🍳 Завтрак", (food_by_id["oats"].portion(45),), "")
    bare_tuna = Meal(
        "🍽️ Обед: Обжаренные стейки тунца с перцем",
        (
            food_by_id["tuna_steak"].portion(140),
            food_by_id["olive_oil"].portion(8),
            food_by_id["salt"].portion(1),
        ),
        "Обжарьте тунца и подавайте.",
    )
    snack = Meal("🥣 Перекус", (food_by_id["greek_yogurt"].portion(150),), "")
    target = NutrientVector(
        {
            "energy_kcal": 2100,
            "protein_g": 120,
            "fat_g": 70,
            "carbohydrate_g": 260,
            "fiber_g": 32,
        }
    )

    meals = _add_missing_garnishes([breakfast, bare_tuna, snack], foods, target, used_grams, used_counts, variety_seed=0)
    lunch_ids = {portion.food.id for portion in meals[1].portions}

    assert any(portion.food.category == "vegetable" and portion.grams >= 80 for portion in meals[1].portions)
    assert lunch_ids & {"potato", "sweet_potato", "rice", "bulgur", "quinoa", "whole_wheat_pasta", "orzo", "buckwheat"}
    assert "Гарнир:" in meals[1].recipe


def test_plan_can_use_curated_table_recipes() -> None:
    profile = UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=5,
    )

    plans = [build_one_day_plan(profile, variety_seed=seed) for seed in range(3)]

    assert any(
        meal.recipe_id and meal.recipe_id.startswith("r") and meal.recipe_key and ":curated:" in meal.recipe_key
        for plan in plans
        for meal in plan.meals
    )


def test_curated_only_plan_uses_only_table_recipes_and_local_photos() -> None:
    profile = UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=5,
    )
    legacy_ids = {
        "snack_savory_creamy_bread_tofu_spinach_parsley",
        "breakfast_crunch_buckwheat_cottage_orange_seeds_lemon",
    }

    for seed in range(5):
        plan = build_one_day_plan(profile, variety_seed=seed, recipe_source="curated_only")

        assert len(plan.meals) == 5
        assert not legacy_ids & {meal.recipe_id for meal in plan.meals}
        assert all(meal.recipe_id and meal.recipe_id.startswith("r") for meal in plan.meals)
        assert all(meal.recipe_key and ":curated:" in meal.recipe_key for meal in plan.meals)
        assert all(meal.image_url and meal.image_url.startswith("recipe_photos/") for meal in plan.meals)
        assert all((DATA_DIR / meal.image_url).exists() for meal in plan.meals if meal.image_url)


def test_curated_only_plan_matches_requested_meal_count() -> None:
    for meal_count in (3, 4, 5):
        profile = UserProfile(
            age=32,
            sex=Sex.MALE,
            height_cm=178,
            weight_kg=86,
            goal=Goal.LOSE,
            activity=ActivityLevel.MODERATE,
            meal_count=meal_count,
        )

        for seed in range(8):
            plan = build_one_day_plan(profile, variety_seed=seed, recipe_source="curated_only")

            assert len(plan.meals) == meal_count


def test_curated_only_plan_keeps_meal_count_when_recent_history_is_too_strict() -> None:
    profile = UserProfile(
        age=32,
        sex=Sex.MALE,
        height_cm=178,
        weight_kg=86,
        goal=Goal.LOSE,
        activity=ActivityLevel.MODERATE,
        meal_count=5,
    )
    avoided_snack_ids = {
        recipe.id
        for recipe in built_in_recipes()
        if recipe.slot == "snack" and "curated" in recipe.tags
    }

    plan = build_one_day_plan(
        profile,
        variety_seed=3,
        avoided_recipe_ids=avoided_snack_ids,
        recipe_source="curated_only",
    )

    assert len(plan.meals) == 5
    assert sum(1 for meal in plan.meals if meal.recipe_key and meal.recipe_key.startswith("snack:curated:")) == 2
