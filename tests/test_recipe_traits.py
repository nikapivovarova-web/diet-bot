from __future__ import annotations

from collections import Counter

import pytest

from diet_bot.recipe_catalog import RecipeTemplate, built_in_recipes
from diet_bot.recipe_traits import infer_recipe_traits


def _recipe(
    recipe_id: str,
    *,
    title: str = "Plain recipe",
    slot: str = "main",
    ingredients_g: dict[str, float] | None = None,
    instructions: str = "Mix and serve.",
    tags: frozenset[str] = frozenset(),
    allowed_meal_slots: tuple[str, ...] = (),
    slot_flex_type: str | None = None,
    cooking_effort: str | None = None,
    active_time_min: int | None = None,
) -> RecipeTemplate:
    return RecipeTemplate(
        id=recipe_id,
        slot=slot,
        title=title,
        ingredients_g=ingredients_g or {},
        instructions=instructions,
        tags=tags,
        allowed_meal_slots=allowed_meal_slots,
        slot_flex_type=slot_flex_type,
        cooking_effort=cooking_effort,
        active_time_min=active_time_min,
    )


@pytest.mark.parametrize(
    ("recipe_id", "expected_no", "expected_batch"),
    [
        ("r001_overnight_oats", 1, "r001-r400"),
        ("r401_imported_breakfast", 401, "r401-r610"),
        ("r611_future_recipe", 611, "r611+"),
        ("manual_recipe", None, "unknown"),
    ],
)
def test_source_batch_inference_uses_recipe_number_cohorts(
    recipe_id: str,
    expected_no: int | None,
    expected_batch: str,
) -> None:
    traits = infer_recipe_traits(_recipe(recipe_id))

    assert traits.recipe_no == expected_no
    assert traits.source_batch == expected_batch


@pytest.mark.parametrize(
    ("ingredients_g", "expected"),
    [
        ({"chicken_breast_cooked": 90}, "poultry"),
        ({"turkey": 90}, "poultry"),
        ({"beef_ground": 90}, "meat"),
        ({"pork_loin": 90}, "meat"),
        ({"salmon": 90}, "fish"),
        ({"trout": 90}, "fish"),
        ({"cod": 90}, "fish"),
        ({"tuna": 90}, "fish"),
        ({"sprats": 90}, "fish"),
        ({"anchovies": 90}, "fish"),
        ({"shrimp": 90}, "seafood"),
        ({"crab": 90}, "seafood"),
        ({"squid": 90}, "seafood"),
        ({"mussels": 90}, "seafood"),
        ({"egg": 90}, "egg"),
        ({"tofu": 90}, "plant_protein"),
        ({"lentils": 90}, "plant_protein"),
        ({"chickpeas": 90}, "plant_protein"),
        ({"black_beans": 90}, "plant_protein"),
        ({"greek_yogurt": 180}, "dairy"),
        ({"cucumber": 90}, "unknown"),
    ],
)
def test_primary_protein_family_inference(ingredients_g: dict[str, float], expected: str) -> None:
    traits = infer_recipe_traits(_recipe("r050_test", ingredients_g=ingredients_g))

    assert traits.primary_protein == expected


@pytest.mark.parametrize(
    ("ingredients_g", "expected"),
    [
        ({"rice": 70}, "rice"),
        ({"buckwheat": 70}, "buckwheat"),
        ({"oats": 70}, "oats"),
        ({"whole_wheat_pasta": 70}, "pasta"),
        ({"potato": 120}, "potato"),
        ({"whole_grain_bread": 70}, "bread"),
        ({"lavash": 70}, "bread"),
        ({"tortilla": 70}, "bread"),
        ({"quinoa": 70}, "grain"),
        ({"barley": 70}, "grain"),
        ({"bulgur": 70}, "grain"),
        ({"apple": 150, "spinach": 30}, "fruit_veg"),
        ({"egg": 100, "cheddar": 30}, "low_carb"),
        ({}, "unknown"),
    ],
)
def test_primary_carb_family_inference(ingredients_g: dict[str, float], expected: str) -> None:
    traits = infer_recipe_traits(_recipe("r080_test", ingredients_g=ingredients_g))

    assert traits.primary_carb == expected


@pytest.mark.parametrize(
    ("title", "recipe_id", "expected"),
    [
        ("Tomato pasta", "r101_tomato_pasta", "pasta"),
        ("Lentil soup", "r102_lentil_soup", "soup"),
        ("Chicken salad", "r103_chicken_salad", "salad"),
        ("Rice bowl", "r104_rice_bowl", "bowl"),
        ("Turkey wrap", "r105_turkey_wrap", "wrap"),
        ("Avocado toast", "r106_avocado_toast", "toast"),
        ("Chicken sandwich", "r107_chicken_sandwich", "sandwich"),
        ("Baked fish casserole", "r108_baked_fish_casserole", "bake"),
        ("Skillet potato hash", "r109_skillet_hash", "skillet"),
        ("Oat porridge", "r110_oat_porridge", "porridge"),
        ("Berry smoothie", "r111_berry_smoothie", "smoothie"),
        ("Yogurt dessert", "r112_yogurt_dessert", "dessert"),
        ("Cheese snack plate", "r113_cheese_snack", "snack"),
        ("Plain recipe", "manual_recipe", "unknown"),
    ],
)
def test_recipe_format_inference(title: str, recipe_id: str, expected: str) -> None:
    traits = infer_recipe_traits(_recipe(recipe_id, title=title))

    assert traits.recipe_format == expected


@pytest.mark.parametrize(
    ("recipe_id", "expected"),
    [
        ("r021_gribnoy_omlet_s_chedderom_i_petrushkoy", "egg_dish"),
        ("r004_bananovo_ovsyanye_pankeyki", "dessert"),
        ("r141_spagetti_s_korolevskimi_krevetkami_harissoy_i_brokkoli", "pasta"),
        ("r156_farshirovannye_pertsy_s_risom_chernoy_fasolyu_i_syrom", "stuffed"),
        ("r625_sytnye_ovsyanye_oladi_s_lukom", "cutlet"),
        ("r611_lavash_s_kuritsey_i_nutovoy_pastoy", "wrap"),
        ("r102_kurinaya_dzhambalayya_s_chorizo", "rice_dish"),
        ("r622_fasol_s_indeykoy_i_ovoschami", "protein_side"),
        ("r621_ragu_iz_chechevitsy_s_ovoschami", "stew"),
        ("r632_postnyy_sendvich_s_nutom_i_avokado", "sandwich"),
    ],
)
def test_curated_recipe_format_regressions_from_unknown_clusters(recipe_id: str, expected: str) -> None:
    recipe_by_id = {recipe.id: recipe for recipe in built_in_recipes()}

    traits = infer_recipe_traits(recipe_by_id[recipe_id])

    assert traits.recipe_format == expected


@pytest.mark.parametrize(
    ("ingredients_g", "expected"),
    [
        ({"whole_wheat_pasta": 70, "chicken_breast": 90}, "pasta"),
        ({"rice_noodles": 70, "shrimp": 90}, "pasta"),
        ({"lavash": 70, "falafel_prepared": 90}, "wrap"),
        ({"whole_grain_bread": 70, "ham": 50}, "sandwich"),
    ],
)
def test_recipe_format_uses_safe_ingredient_carriers(
    ingredients_g: dict[str, float],
    expected: str,
) -> None:
    traits = infer_recipe_traits(_recipe("r590_plain_carrier", ingredients_g=ingredients_g))

    assert traits.recipe_format == expected


def test_explicit_trait_tags_override_fallback_inference() -> None:
    recipe = _recipe(
        "r120_chicken_pasta_soup",
        title="Chicken pasta soup",
        ingredients_g={"chicken_breast_cooked": 90, "whole_wheat_pasta": 70},
        tags=frozenset(
            {
                "primary_protein:fish",
                "primary_carb:rice",
                "recipe_format:bowl",
                "source:batch2",
            }
        ),
    )

    traits = infer_recipe_traits(recipe)

    assert traits.primary_protein == "fish"
    assert traits.primary_carb == "rice"
    assert traits.recipe_format == "bowl"
    assert traits.source_tag == "batch2"


def test_slot_and_effort_metadata_are_preserved_as_traits() -> None:
    recipe = _recipe(
        "r450_light_main_snack",
        slot="snack",
        allowed_meal_slots=("snack", "main"),
        slot_flex_type="snack_light_main",
        cooking_effort="simple",
        active_time_min=12,
    )

    traits = infer_recipe_traits(recipe)

    assert traits.native_slot == "snack"
    assert traits.allowed_meal_slots == frozenset({"snack", "main"})
    assert traits.slot_flex_type == "snack_light_main"
    assert traits.cooking_effort == "simple"
    assert traits.active_time_bucket == "quick"
    assert traits.main_signal == "light_main"


def test_all_curated_recipes_produce_traits_with_broad_unknown_thresholds() -> None:
    curated_recipes = [recipe for recipe in built_in_recipes() if "curated" in recipe.tags]

    traits = [infer_recipe_traits(recipe) for recipe in curated_recipes]
    recipe_nos = {trait.recipe_no for trait in traits}
    excluded_missing_food_recipe_nos = set()
    expected_recipe_nos = (
        set(range(1, 401))
        | (set(range(401, 611)) - excluded_missing_food_recipe_nos)
        | set(range(611, 666))
        | (set(range(666, 711)) - excluded_missing_food_recipe_nos)
    )

    assert len(traits) == 710
    assert recipe_nos == expected_recipe_nos
    assert Counter(trait.source_batch for trait in traits) == {
        "r001-r400": 400,
        "r401-r610": 210,
        "r611+": 100,
    }

    unknown_counts = Counter(
        field
        for trait in traits
        for field, value in (
            ("protein", trait.primary_protein),
            ("carb", trait.primary_carb),
            ("format", trait.recipe_format),
        )
        if value == "unknown"
    )
    catalog_size = len(traits)
    assert unknown_counts["protein"] < catalog_size * 0.45
    assert unknown_counts["carb"] < catalog_size * 0.25
    assert unknown_counts["format"] <= 80
