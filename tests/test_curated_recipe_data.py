import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from diet_bot.builder import _add_missing_garnishes
from diet_bot.builder import build_one_day_plan
from diet_bot.curated_data import _cis_friendly_ingredient, _looks_incomplete_instruction, curated_foods, curated_recipes
from diet_bot.domain import ActivityLevel, Goal, Sex, UserProfile
from diet_bot.domain import Meal, NutrientVector
from diet_bot.recipe_catalog import built_in_recipes
from scripts.dev.recipe_content_audit import run_audit


DATA_DIR = Path(__file__).resolve().parents[1] / "src" / "diet_bot" / "data"
LEGACY_CURATED_RECIPE_COUNT = 400
PRODUCT_RECOVERY_RECIPE_COUNT = 210
DOCX_RECIPE_COUNT = 55
SELECTED53_RECIPE_COUNT = 45
TOTAL_CURATED_RECIPE_COUNT = (
    LEGACY_CURATED_RECIPE_COUNT
    + PRODUCT_RECOVERY_RECIPE_COUNT
    + DOCX_RECIPE_COUNT
    + SELECTED53_RECIPE_COUNT
)
PRODUCT_RECOVERY_RECIPE_NOS = frozenset(range(401, 611))
DOCX_RECIPE_KEY_PREFIX = "docx20260520_"
DOCX_RECIPE_NOS = frozenset(range(611, 666))
SELECTED53_RECIPE_KEY_PREFIX = "selected53_"
SELECTED53_RECIPE_NOS = frozenset(range(666, 711))


def test_curated_recipe_data_has_full_calculation_coverage() -> None:
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))

    curated = curated_recipes()
    assert len(curated) == TOTAL_CURATED_RECIPE_COUNT
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


def test_product_recovery_batch_r401_r610_has_required_rows_and_photos() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))

    recovery_rows = [row for row in recipes if int(row["recipe_no"]) in PRODUCT_RECOVERY_RECIPE_NOS]
    recovery_ids = {row["recipe_id"] for row in recovery_rows}
    nutrition_ids = {row["recipe_id"] for row in nutrition}
    ingredient_counts = Counter(row["recipe_id"] for row in ingredients if row["recipe_id"] in recovery_ids)

    assert len(recovery_rows) == PRODUCT_RECOVERY_RECIPE_COUNT
    assert {int(row["recipe_no"]) for row in recovery_rows} == PRODUCT_RECOVERY_RECIPE_NOS
    assert all(row["recipe_id"] in nutrition_ids for row in recovery_rows)
    assert all(ingredient_counts[row["recipe_id"]] >= 3 for row in recovery_rows)
    assert all(row.get("instructions_ru", "").strip().endswith(".") for row in recovery_rows)
    assert all(row.get("image_url") == f"recipe_photos/r{row['recipe_no']}.jpg" for row in recovery_rows)
    assert all((DATA_DIR / row["image_url"]).exists() for row in recovery_rows)


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


def test_selected53_recipe_batch_r666_r710_has_required_rows_and_photos() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))

    selected_rows = [row for row in recipes if int(row["recipe_no"]) in SELECTED53_RECIPE_NOS]
    selected_ids = {row["recipe_id"] for row in selected_rows}
    nutrition_ids = {row["recipe_id"] for row in nutrition}
    ingredient_counts = Counter(row["recipe_id"] for row in ingredients if row["recipe_id"] in selected_ids)

    assert len(selected_rows) == SELECTED53_RECIPE_COUNT
    assert {int(row["recipe_no"]) for row in selected_rows} == SELECTED53_RECIPE_NOS
    assert all(str(row["recipe_key"]).startswith(SELECTED53_RECIPE_KEY_PREFIX) for row in selected_rows)
    assert all(row.get("source_staging_pack") == "selected-53" for row in selected_rows)
    assert all(row["recipe_id"] in nutrition_ids for row in selected_rows)
    assert all(ingredient_counts[row["recipe_id"]] >= 2 for row in selected_rows)
    assert all(row.get("instructions_ru", "").strip().endswith(".") for row in selected_rows)
    assert all(row.get("image_url") == f"recipe_photos/r{row['recipe_no']}.jpg" for row in selected_rows)
    assert all((DATA_DIR / row["image_url"]).exists() for row in selected_rows)


def test_selected53_recipe_batch_r666_r710_foods_are_resolved() -> None:
    foods = {food.id for food in curated_foods()}
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    missing_foods = sorted(
        {
            normalized_food_id
            for row in ingredients
            if 666 <= int(row.get("recipe_no") or 0) <= 710
            if (normalized_food_id := _cis_friendly_ingredient(row)[0]) not in foods
        }
    )

    assert missing_foods == []


def test_selected53_post_import_blocker_mappings_are_fixed() -> None:
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    foods = json.loads((DATA_DIR / "curated_foods.json").read_text(encoding="utf-8"))

    by_recipe_line = {
        (int(row["recipe_no"]), int(row["line_index"])): row
        for row in ingredients
        if int(row.get("recipe_no") or 0) in SELECTED53_RECIPE_NOS
    }

    expected_rows = {
        (684, 1): ("green_beans", 150.0),
        (685, 1): ("rice_paper", 45.0),
        (688, 1): ("pasta_generic", 50.0),
        (691, 2): ("chicken_hearts", 150.0),
        (692, 1): ("beef_liver", 80.0),
        (705, 2): ("almond_milk", 50.0),
    }
    for key, (food_id, grams) in expected_rows.items():
        row = by_recipe_line[key]
        assert row["food_id"] == food_id
        assert float(row["grams"]) == grams

    sour_cream = {row["food_id"]: row for row in foods}["sour_cream"]
    assert sour_cream["fdc_id"] == "171256"
    assert "potato chips" not in sour_cream["source_description"].lower()
    assert sour_cream["nutrients_per_100g"]["energy_kcal"] == 135.0

    recipe_id_by_no = {int(row["recipe_no"]): row["recipe_id"] for row in recipes}
    nutrition_by_id = {row["recipe_id"]: row for row in nutrition}
    expected_energy = {
        684: 144.29,
        685: 324.47,
        688: 633.45,
        691: 454.61,
        692: 356.95,
        705: 336.65,
        707: 653.56,
    }
    for recipe_no, energy_kcal in expected_energy.items():
        row = nutrition_by_id[recipe_id_by_no[recipe_no]]
        assert row["calculation_status"] == "ok"
        assert row["energy_kcal"] == energy_kcal


def test_sour_cream_recipe_nutrition_matches_current_food_profile() -> None:
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    nutrition = json.loads((DATA_DIR / "curated_recipe_nutrition.json").read_text(encoding="utf-8"))
    foods = json.loads((DATA_DIR / "curated_foods.json").read_text(encoding="utf-8"))

    foods_by_id = {row["food_id"]: row for row in foods}
    ingredients_by_recipe: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in ingredients:
        ingredients_by_recipe[row["recipe_id"]].append(row)

    sour_cream_recipe_ids = sorted(
        {
            row["recipe_id"]
            for row in ingredients
            if row.get("food_id") == "sour_cream"
        }
    )
    assert len(sour_cream_recipe_ids) == 26

    nutrition_by_id = {row["recipe_id"]: row for row in nutrition}
    nutrient_fields = [
        key
        for key, value in nutrition[0].items()
        if key not in {"ingredient_count", "unmatched_ingredient_count"}
        and isinstance(value, (int, float))
    ]

    mismatches = []
    for recipe_id in sour_cream_recipe_ids:
        expected = dict.fromkeys(nutrient_fields, 0.0)
        for ingredient in ingredients_by_recipe[recipe_id]:
            food = foods_by_id[ingredient["food_id"]]
            grams = float(ingredient["grams"])
            for field in nutrient_fields:
                expected[field] += float(food["nutrients_per_100g"].get(field, 0.0)) * grams / 100

        saved = nutrition_by_id[recipe_id]
        for field in nutrient_fields:
            saved_value = round(float(saved[field]), 2)
            expected_value = round(float(expected[field]), 2)
            if saved_value != expected_value:
                mismatches.append((recipe_id, field, saved_value, expected_value))

    assert mismatches == []


def test_recipe_content_audit_has_no_round2_blockers() -> None:
    result = run_audit(DATA_DIR)

    assert [issue.markdown_line() for issue in result.blockers] == []


def test_product_recovery_batch_r401_r610_foods_are_resolved() -> None:
    foods = {food.id for food in curated_foods()}
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    missing_foods = sorted(
        {
            normalized_food_id
            for row in ingredients
            if 401 <= int(row.get("recipe_no") or 0) <= 610
            if (normalized_food_id := _cis_friendly_ingredient(row)[0]) not in foods
        }
    )

    assert missing_foods == []


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
    assert by_no_and_raw[(306, "поджаренный грецкий орех или пекан — 5 г (примерно 1 ст. л.)")]["food_id"] == "pecans"


def test_curated_recipe_data_fixes_manual_smoke_ingredient_anomalies() -> None:
    foods = json.loads((DATA_DIR / "curated_foods.json").read_text(encoding="utf-8"))
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    by_recipe_line = {
        (row["recipe_id"], row["line_index"]): row
        for row in ingredients
    }
    recipe_text = {
        row["recipe_id"]: row["instructions_ru"]
        for row in recipes
    }
    recipe_titles = {
        row["recipe_id"]: row["title_ru"]
        for row in recipes
    }
    food_names = {
        row["food_id"]: row["name_ru"]
        for row in foods
    }

    assert by_recipe_line[("r062_veganskie_myusli_maffiny_s_yablokom_i_pekanom", 8)]["grams"] == 3.75
    assert by_recipe_line[("r062_veganskie_myusli_maffiny_s_yablokom_i_pekanom", 1)]["grams"] == 12.5
    assert by_recipe_line[("r064_zapechennaya_bananovaya_ovsyanka_s_arahisovoy_pastoy", 10)]["grams"] == 12.0
    assert by_recipe_line[("r139_belaya_ryba_pikkata_s_limonno_kapersovym_maslyanym_sou", 1)]["grams"] == 14.6
    assert by_recipe_line[("r139_belaya_ryba_pikkata_s_limonno_kapersovym_maslyanym_sou", 8)]["grams"] == 18.8
    assert by_recipe_line[("r184_tayskiy_zharenyy_ris_s_ananasom_i_keshyu", 2)]["grams"] == 8.5
    assert by_recipe_line[("r543_tushenaya_govyadina_s_kartofelem", 3)]["grams"] == 40.0
    assert by_recipe_line[("r543_tushenaya_govyadina_s_kartofelem", 4)]["grams"] == 50.0
    assert by_recipe_line[("r543_tushenaya_govyadina_s_kartofelem", 8)]["grams"] == 0.2
    assert by_recipe_line[("r600_sendvich_s_tuntsom", 1)]["grams"] == 60.0
    assert by_recipe_line[("r601_tost_s_arahisovoy_pastoy_i_yablokom", 1)]["grams"] == 60.0
    assert by_recipe_line[("r273_zelenyy_humus_s_bazilikom_petrushkoy_i_ovoschnymi_palo", 12)]["grams"] == 80.0
    assert "овощными палочками" in recipe_text["r273_zelenyy_humus_s_bazilikom_petrushkoy_i_ovoschnymi_palo"]
    assert "Готовим:" not in recipe_text["r441_omlet_iz_nutovoy_muki_s_brokkoli_i_struchkovoy_fasolyu"]
    assert by_recipe_line[("r197_batat_s_nutom_masala_i_zelenym_chatni", 3)]["food_id"] == "salt"
    assert "примерно 1/2 ч. л." in by_recipe_line[("r034_pankeyki_na_protivne_s_chetyrmya_toppingami", 10)]["raw_text"]
    assert "Жевательный батончик" in recipe_titles["r270_zhevatelnye_batonchiki_s_shokoladnoy_kroshkoy_i_risovy"]
    assert "23 x 33" not in recipe_text["r270_zhevatelnye_batonchiki_s_shokoladnoy_kroshkoy_i_risovy"]
    assert "18 батончиков" not in recipe_text["r270_zhevatelnye_batonchiki_s_shokoladnoy_kroshkoy_i_risovy"]
    assert "american_cheese" not in food_names
    assert "harissa" not in food_names


def test_round2_recipe_content_regressions_are_absent() -> None:
    foods = json.loads((DATA_DIR / "curated_foods.json").read_text(encoding="utf-8"))
    recipes = json.loads((DATA_DIR / "curated_recipes.json").read_text(encoding="utf-8"))
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    ingredients_by_recipe: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in ingredients:
        ingredients_by_recipe[str(row["recipe_id"])].append(row)

    standalone_gotovim = [
        row["recipe_id"]
        for row in recipes
        if re.search(r"(?:^|[.!?]\s*)Готовим:\s*(?:$|[.!?])", row["instructions_ru"])
    ]
    assert standalone_gotovim == []

    zero_baking_powder = [
        (row["recipe_id"], row["line_index"], row["raw_text"])
        for row in ingredients
        if row["food_id"] == "baking_powder"
        if float(row["grams"]) == 0
        if "разрыхлитель" in str(row["raw_text"]).lower()
    ]
    assert zero_baking_powder == []

    searchable_blob = "\n".join(
        json.dumps(row, ensure_ascii=False).lower()
        for dataset in (foods, recipes, ingredients)
        for row in dataset
    )
    forbidden_terms = ("хариса", "харисса", "harissa", "american_cheese", "американский сыр")
    assert [term for term in forbidden_terms if term in searchable_blob] == []

    mayo_without_ingredient = []
    optional_markers = ("по желанию", "опционально", "при желании", "можно заменить")
    for recipe in recipes:
        instructions = str(recipe["instructions_ru"]).lower()
        if "майонез" not in instructions:
            continue
        food_ids = {str(row["food_id"]) for row in ingredients_by_recipe[str(recipe["recipe_id"])]}
        if "mayonnaise" in food_ids or any(marker in instructions for marker in optional_markers):
            continue
        mayo_without_ingredient.append(recipe["recipe_id"])
    assert mayo_without_ingredient == []

    hummus_without_support = []
    blend_markers = ("измельч", "взбей", "блендер", "комбайн", "пюре", "паста")
    hummus_base_ids = {"hummus", "chickpeas", "black_beans", "beans", "white_beans"}
    hummus_flavor_ids = {"tahini", "garlic", "lemon_juice", "olive_oil", "greek_yogurt"}
    for recipe in recipes:
        if "хумус" not in str(recipe["title_ru"]).lower():
            continue
        rows = ingredients_by_recipe[str(recipe["recipe_id"])]
        food_ids = {str(row["food_id"]) for row in rows}
        instructions = str(recipe["instructions_ru"]).lower()
        has_ready_hummus = "hummus" in food_ids
        makes_hummus = bool(food_ids & hummus_base_ids) and bool(food_ids & hummus_flavor_ids) and any(
            marker in instructions for marker in blend_markers
        )
        if not (has_ready_hummus or makes_hummus):
            hummus_without_support.append((recipe["recipe_id"], recipe["title_ru"]))
    assert hummus_without_support == []


def test_round2_confident_approximate_measure_targets_are_not_gram_only() -> None:
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    confident_food_ids = {
        "almond_butter",
        "almonds",
        "brazil_nuts",
        "cashews",
        "dates",
        "dried_dates",
        "garlic",
        "hot_sauce",
        "hummus",
        "mayonnaise",
        "mixed_nuts",
        "nuts_mix",
        "peanut_butter",
        "peanuts",
        "pecans",
        "pesto",
        "pine_nuts",
        "pistachios",
        "pumpkin_seeds",
        "salsa",
        "sesame_seeds",
        "soy_sauce",
        "sriracha_extra",
        "sunflower_seeds",
        "tahini",
        "teriyaki_sauce",
        "tomato_paste",
        "walnuts",
    }
    small_cheese_food_ids = {
        "cheddar",
        "cream_cheese",
        "feta",
        "goat_cheese",
        "gouda",
        "monterey_jack",
        "mozzarella",
        "parmesan",
        "ricotta",
        "swiss_cheese",
    }

    missing = [
        (row["recipe_no"], row["line_index"], row["food_id"], row["quantity_text"], row["raw_text"])
        for row in ingredients
        if (
            row["food_id"] in confident_food_ids
            or (row["food_id"] in small_cheese_food_ids and float(row["grams"]) <= 30)
            or _is_confident_salt_or_pepper_measure(row)
        )
        if _looks_like_gram_only_measure(row)
    ]

    assert missing == []


def test_round2_garlic_and_date_examples_have_household_measures_when_present() -> None:
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))

    garlic_5g_rows = [
        row
        for row in ingredients
        if row["food_id"] == "garlic" and 4.5 <= float(row["grams"]) <= 5.5
    ]
    date_example_rows = [
        row
        for row in ingredients
        if row["food_id"] in {"dates", "dried_dates"} and 14 <= float(row["grams"]) <= 45
    ]

    assert garlic_5g_rows
    assert all("зуб" in _measure_blob(row).lower() for row in garlic_5g_rows)
    assert all("финик" in _measure_blob(row).lower() for row in date_example_rows)


def test_round2_sauce_and_paste_measures_do_not_use_dry_grain_wording() -> None:
    ingredients = json.loads((DATA_DIR / "curated_recipe_ingredients.json").read_text(encoding="utf-8"))
    sauce_or_paste_food_ids = {
        "almond_butter",
        "chili_sauce",
        "hot_sauce",
        "hummus",
        "mayonnaise",
        "peanut_butter",
        "pesto",
        "salsa",
        "sriracha",
        "sriracha_extra",
        "tahini",
        "teriyaki_sauce",
        "tomato_paste",
    }

    offenders = [
        (row["recipe_no"], row["line_index"], row["food_id"], row["raw_text"])
        for row in ingredients
        if row["food_id"] in sauce_or_paste_food_ids or any(word in str(row["raw_text"]).lower() for word in ("соус", "паста"))
        if "сухая крупа" in _measure_blob(row).lower()
    ]

    assert offenders == []


def _looks_like_gram_only_measure(row: dict[str, object]) -> bool:
    text = _measure_blob(row).lower()
    if not re.search(r"(?:^|[\s/])\d+(?:[,.]\d+)?\s*г(?:\s|$)", text):
        return False
    household_markers = (
        "шт",
        "зуб",
        "доль",
        "ломт",
        "ст.",
        "ч.",
        "мл",
        "стак",
        "чашк",
        "банк",
        "горст",
        "щеп",
        "примерно",
        "около",
        "≈",
        "~",
        "1/2",
        "1/3",
        "1/4",
    )
    return not any(marker in text for marker in household_markers)


def _is_confident_salt_or_pepper_measure(row: dict[str, object]) -> bool:
    if row["food_id"] not in {"salt", "black_pepper", "white_pepper"}:
        return False
    grams = float(row["grams"])
    return 0.25 <= grams <= 1.0


def _measure_blob(row: dict[str, object]) -> str:
    return f"{row.get('quantity_text', '')} {row.get('raw_text', '')}"


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
