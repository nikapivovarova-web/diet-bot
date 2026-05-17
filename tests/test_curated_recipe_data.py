import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from openpyxl import load_workbook

from diet_bot.builder import _add_missing_garnishes
from diet_bot.builder import build_one_day_plan
from diet_bot.curated_data import _looks_incomplete_instruction, _recipe_instruction, curated_foods, curated_recipes
from diet_bot.domain import ActivityLevel, Goal, Sex, UserProfile
from diet_bot.domain import Meal, NutrientVector
from diet_bot.recipe_catalog import built_in_recipes


DATA_DIR = Path(__file__).resolve().parents[1] / "src" / "diet_bot" / "data"
ROOT_DIR = Path(__file__).resolve().parents[1]
LEGACY_CURATED_RECIPE_COUNT = 400
BATCH1_INTAKE_RECIPE_COUNT = 105
BATCH2_INTAKE_RECIPE_COUNT = 105
INTAKE_RECIPE_COUNT = BATCH1_INTAKE_RECIPE_COUNT + BATCH2_INTAKE_RECIPE_COUNT
TOTAL_CURATED_RECIPE_COUNT = LEGACY_CURATED_RECIPE_COUNT + INTAKE_RECIPE_COUNT
INTAKE_RECIPE_KEY_PREFIXES = ("intake_", "batch2_")


def _source_recipes() -> list[dict]:
    return json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))


def _source_ingredients() -> list[dict]:
    return json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))


def _rows_by_key(sheet, *, many: bool = False):
    headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    key_index = headers.index("recipe_key")
    rows = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        item = dict(zip(headers, row))
        if many:
            rows.setdefault(row[key_index], []).append(item)
        else:
            rows[row[key_index]] = item
    return rows


def _imported_recipe_rows() -> list[dict]:
    return [
        row
        for row in _source_recipes()
        if str(row.get("recipe_key", "")).startswith(INTAKE_RECIPE_KEY_PREFIXES)
    ]


def _imported_recipe_ids() -> set[str]:
    return {row["recipe_id"] for row in _imported_recipe_rows()}


def _is_imported_intake_recipe_id(recipe_id: str | None) -> bool:
    return bool(
        recipe_id
        and recipe_id.startswith("r")
        and recipe_id[1:4].isdigit()
        and int(recipe_id[1:4]) > LEGACY_CURATED_RECIPE_COUNT
    )


def _runtime_recipe_by_no() -> dict[int, object]:
    return {
        int(recipe.id[1:4]): recipe
        for recipe in built_in_recipes()
        if recipe.id.startswith("r") and recipe.id[1:4].isdigit()
    }


def test_curated_recipe_data_has_full_calculation_coverage() -> None:
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))

    curated = curated_recipes()
    assert len(curated) == TOTAL_CURATED_RECIPE_COUNT
    assert len(curated_foods()) >= 340
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


def test_sprats_supported_as_drained_canned_fish_policy() -> None:
    foods = json.loads((DATA_DIR / "curated_foods.json").read_text(encoding="utf-8"))
    sprats = next((food for food in foods if food["food_id"] == "sprats"), None)

    assert sprats is not None
    assert sprats["name_ru"] == "шпроты"
    assert "canned" in sprats["name_en"]
    assert "drained solids" in sprats["name_en"]
    assert sprats["default_state"] == "drained"
    assert "protein" in sprats["roles"]
    assert sprats["nutrients_per_100g"]["protein_g"] > 0
    assert sprats["nutrients_per_100g"]["fat_g"] > 0


def test_batch2_sprats_rows_are_ready_with_drained_weight_mapping() -> None:
    workbook_path = ROOT_DIR / "tmp" / "recipe_intake_batch2" / "cleaned_recipes_batch2.xlsx"
    sprats_keys = {"batch2_083", "batch2_084", "batch2_085", "batch2_086"}
    wb = load_workbook(workbook_path, read_only=True, data_only=True)

    recipes = _rows_by_key(wb["recipes"])
    ingredients = _rows_by_key(wb["ingredients"], many=True)
    qa_issues = _rows_by_key(wb["qa_issues"], many=True)
    wb.close()

    assert {key: recipes[key]["status"] for key in sprats_keys} == {
        key: "ready"
        for key in sprats_keys
    }
    for key in sprats_keys:
        sprats_rows = [
            row
            for row in ingredients[key]
            if str(row["ingredient_name_ru"]).lower() == "шпроты"
        ]
        assert len(sprats_rows) == 1
        assert sprats_rows[0]["grams_estimate"] == 70
        assert sprats_rows[0]["preparation_note"] == "масло слить, вес без масла"
        assert "unsupported" not in str(sprats_rows[0].get("issue_note") or "").lower()
        assert "needs_review" not in str(sprats_rows[0].get("issue_note") or "").lower()
        assert not [
            row
            for row in qa_issues.get(key, [])
            if row["severity"] == "warning" and "Sprats remain needs_review" in row["issue"]
        ]


def test_curated_recipe_data_has_local_photos() -> None:
    recipes = _source_recipes()

    assert len(recipes) == TOTAL_CURATED_RECIPE_COUNT
    missing = [
        recipe["recipe_id"]
        for recipe in recipes
        if recipe["recipe_no"] <= LEGACY_CURATED_RECIPE_COUNT
        and not (DATA_DIR / recipe["image_url"]).exists()
    ]
    assert missing == []

    imported = _imported_recipe_rows()
    assert len(imported) == INTAKE_RECIPE_COUNT
    imported_missing = [
        recipe["recipe_id"]
        for recipe in imported
        if not recipe.get("image_url")
        or not str(recipe["image_url"]).startswith("recipe_photos/")
        or not (DATA_DIR / recipe["image_url"]).exists()
    ]
    assert imported_missing == []
    assert all(recipe.get("photo_prompt_ru") for recipe in imported)


def test_cleaned_intake_recipes_are_imported_with_required_metadata() -> None:
    recipes = _source_recipes()
    ingredients = _source_ingredients()
    imported = _imported_recipe_rows()
    imported_ids = {row["recipe_id"] for row in imported}
    ingredients_by_recipe = Counter(
        row["recipe_id"]
        for row in ingredients
        if row["recipe_id"] in imported_ids
    )

    assert len(imported) == INTAKE_RECIPE_COUNT
    assert len({row["recipe_key"] for row in imported}) == INTAKE_RECIPE_COUNT
    assert len({row["recipe_id"] for row in recipes}) == len(recipes)
    assert Counter(row["recipe_key"].split("_", 1)[0] for row in imported) == {
        "intake": BATCH1_INTAKE_RECIPE_COUNT,
        "batch2": BATCH2_INTAKE_RECIPE_COUNT,
    }
    assert not any(row["recipe_key"] == "batch2_008" for row in imported)
    assert all(row["meal_slot"] in {"breakfast", "main", "snack"} for row in imported)
    assert all(row["slot"] == row["meal_slot"] for row in imported)
    assert all(row["cooking_effort"] in {"simple", "interesting"} for row in imported)
    assert all(row["instructions_ru"].strip().endswith(".") for row in imported)
    assert all(ingredients_by_recipe[row["recipe_id"]] > 0 for row in imported)


def test_batch2_curated_recipe_runtime_loads_metadata_fields() -> None:
    source = next(row for row in _source_recipes() if row.get("recipe_key") == "batch2_001")
    recipe = {recipe.id: recipe for recipe in curated_recipes()}[source["recipe_id"]]

    assert recipe.allowed_meal_slots == ("breakfast", "snack")
    assert recipe.slot_flex_type == source["slot_flex_type"]
    assert recipe.cooking_effort == source["cooking_effort"]
    assert recipe.active_time_min == source["active_time_min"]
    assert recipe.coverage_priority == source["coverage_priority"]


def test_legacy_curated_recipe_runtime_uses_metadata_defaults() -> None:
    source = next(row for row in _source_recipes() if row["recipe_no"] == 1)
    recipe = {recipe.id: recipe for recipe in curated_recipes()}[source["recipe_id"]]

    assert "allowed_meal_slots" not in source
    assert "slot_flex_type" not in source
    assert "cooking_effort" not in source
    assert "active_time_min" not in source
    assert "coverage_priority" not in source
    assert recipe.allowed_meal_slots == (recipe.slot,)
    assert recipe.slot_flex_type is None
    assert recipe.cooking_effort is None
    assert recipe.active_time_min is None
    assert recipe.coverage_priority is None


def test_cleaned_intake_required_policy_mappings_resolve() -> None:
    imported_ids = _imported_recipe_ids()
    imported_ingredients = [
        row
        for row in _source_ingredients()
        if row["recipe_id"] in imported_ids
    ]
    food_ids = {row["food_id"] for row in imported_ingredients}
    required_food_ids = {
        "cod_liver_canned_drained",
        "buckwheat",
        "grapes",
        "cornmeal",
        "chicken_liver",
        "split_peas",
        "trout",
        "rice",
        "tomato",
        "passata",
        "pumpkin",
        "asparagus",
        "falafel_prepared",
        "korean_carrot",
        "soy_sauce",
        "mayonnaise",
        "crab_sticks",
        "pesto",
        "teriyaki_sauce",
        "mixed_spices",
    }

    assert required_food_ids <= food_ids
    assert "басмати" in "\n".join(
        row["raw_text"]
        for row in imported_ingredients
        if row["food_id"] == "rice"
    )
    assert any(
        row["food_id"] == "cod_liver_canned_drained" and "без лишнего масла" in row["raw_text"]
        for row in imported_ingredients
    )
    assert any(
        row["food_id"] == "mixed_spices" and row["grams"] == 0
        for row in imported_ingredients
    )


def test_cleaned_intake_policy_rejected_terms_are_absent() -> None:
    imported = _imported_recipe_rows()
    imported_ids = {row["recipe_id"] for row in imported}
    ingredients = [
        row
        for row in _source_ingredients()
        if row["recipe_id"] in imported_ids
    ]
    text = "\n".join(
        [
            json.dumps(imported, ensure_ascii=False),
            json.dumps(ingredients, ensure_ascii=False),
        ]
    ).lower()
    blocked_patterns = (
        r"(?<![а-яa-z])вино(?![а-яa-z])",
        r"(?<![а-яa-z])wine(?![а-яa-z])",
        r"коньяк",
        r"cognac",
        r"голубой сыр",
        r"blue cheese",
        r"дор блю",
        r"рокфор",
        r"горгонзола",
    )

    for pattern in blocked_patterns:
        assert re.search(pattern, text) is None, pattern


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


def test_curated_recipe_runtime_keeps_complete_source_instruction_over_fallback() -> None:
    source_text = "Сварите суп до мягкости. Добавьте лимонный сок и подайте с зеленью."
    row = {
        "recipe_id": "r215_zolotoy_karri_sup_iz_krasnoy_chechevitsy_s_kokosovym_m",
        "instructions_ru": source_text,
    }

    assert _recipe_instruction(row) == source_text


def test_curated_recipe_runtime_blocks_service_only_instruction_text() -> None:
    row = {
        "recipe_id": "test_service_text",
        "instructions_ru": "Как AI-модель, я не могу приготовить это блюдо. Подпишитесь на наш канал.",
    }

    assert _recipe_instruction(row) is None


def test_curated_recipe_runtime_uses_cis_friendly_substitutions() -> None:
    foods = {food.id: food for food in curated_foods()}
    recipes = _runtime_recipe_by_no()
    runtime_ingredient_ids = {
        food_id
        for recipe in recipes.values()
        for food_id in recipe.ingredients_g
    }
    blocked_food_ids = {
        "agave_syrup",
        "almond_milk",
        "garam_masala",
        "kale",
        "monterey_jack",
        "sambal_olek",
        "tamari",
        "turkey_or_chicken_breast",
        "tzatziki",
        "wensleydale_cheese",
    }

    assert blocked_food_ids.isdisjoint(foods)
    assert blocked_food_ids.isdisjoint(runtime_ingredient_ids)
    assert foods["chicken_breast_cooked"].name == "готовая куриная грудка"
    assert foods["turkey_breast_cooked"].name == "готовая грудка индейки"

    assert recipes[43].title == "Тост с яйцом, курицей и овощами"
    assert recipes[43].ingredients_g["chicken_breast_cooked"] == 80.0
    assert recipes[85].ingredients_g["spinach"] == 50.0
    assert recipes[117].ingredients_g["greek_yogurt"] == 35.0
    assert recipes[159].ingredients_g["gouda"] == 40.0


def test_curated_recipe_runtime_text_uses_accessible_ingredient_names() -> None:
    recipes = _runtime_recipe_by_no()
    runtime_text = "\n".join(
        [
            "\n".join(f"{recipe.title}\n{recipe.instructions}" for recipe in recipes.values()),
            "\n".join(food.name for food in curated_foods()),
        ]
    ).lower()
    blocked_terms = (
        "кейл",
        "шалот",
        "монтерей",
        "грюйер",
        "венслидейл",
        "кокосовый йогурт",
        "миндальное молоко",
        "сироп агавы",
        "гарам масала",
        "тандури масала",
        "самбал",
        "тамари",
        "цацики",
        "соевый соус или соевый соус",
        "кинзой или тайским базиликом",
        "хумус из эдамаме",
        "черный или обычный кунжут",
        "плоский хлеб или тонкий",
    )

    for term in blocked_terms:
        assert term not in runtime_text


def test_curated_recipe_data_uses_specific_minced_meat_names() -> None:
    foods = {food.id: food for food in curated_foods()}
    ingredients = _source_ingredients()
    ambiguous_names = {
        "\u0444\u0430\u0440\u0448",
        "\u043c\u044f\u0441\u043e \u0438\u043b\u0438 \u0444\u0430\u0440\u0448",
        "\u0444\u0430\u0440\u0448 \u0438\u043b\u0438 \u043a\u0443\u0440\u0438\u0446\u0430",
    }

    assert foods["ground_meat"].name == "\u0433\u043e\u0432\u044f\u0436\u0438\u0439 \u0444\u0430\u0440\u0448"
    for row in ingredients:
        ingredient_name = str(row.get("ingredient_name_ru") or "").casefold()
        raw_name = str(row.get("raw_text") or "").split("\u2014", 1)[0].strip().casefold()

        assert ingredient_name not in ambiguous_names
        assert raw_name not in ambiguous_names


def test_curated_recipe_data_has_no_user_facing_american_cheese() -> None:
    blocked = "\u0430\u043c\u0435\u0440\u0438\u043a\u0430\u043d\u0441\u043a\u0438\u0439 \u0441\u044b\u0440"
    foods = curated_foods()
    ingredients = _source_ingredients()

    assert all(blocked not in food.name.casefold() for food in foods)
    assert all(
        blocked not in str(row.get(field) or "").casefold()
        for row in ingredients
        for field in ("raw_text", "ingredient_name_ru")
    )


def test_curated_recipe_runtime_preserves_normal_ingredient_mappings() -> None:
    recipes = _runtime_recipe_by_no()

    assert recipes[57].ingredients_g["acai_puree"] > 0
    assert recipes[63].ingredients_g["banana"] > 0
    assert recipes[209].ingredients_g["water"] >= 30.0
    assert recipes[247].ingredients_g["peanut_oil"] > 0
    assert recipes[247].ingredients_g["chili_oil"] > 0
    assert recipes[287].ingredients_g["tomato"] == 130.0
    assert recipes[306].ingredients_g["pecans"] == 5.0


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
    assert lunch_ids & {"buckwheat", "potato", "sweet_potato", "rice", "bulgur", "quinoa", "whole_wheat_pasta", "orzo"}
    assert "Гарнир:" in meals[1].recipe


@pytest.mark.slow_pdf_builder
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
        assert all(
            meal.image_url or _is_imported_intake_recipe_id(meal.recipe_id)
            for meal in plan.meals
        )
        assert all(
            not meal.image_url or meal.image_url.startswith("recipe_photos/")
            for meal in plan.meals
        )
        assert all((DATA_DIR / meal.image_url).exists() for meal in plan.meals if meal.image_url)


@pytest.mark.slow_pdf_builder
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
