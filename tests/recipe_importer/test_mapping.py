from pathlib import Path

import pytest

from scripts.dev.recipe_importer.ingredients import ParsedIngredient
from scripts.dev.recipe_importer.mapping import load_alias_config, map_ingredients


def test_load_alias_config_normalizes_and_maps_alias_to_food_id(tmp_path: Path) -> None:
    path = tmp_path / "ingredient_aliases.csv"
    path.write_text(
        "alias,food_id,notes\n Olive Oil ,olive_oil,\nwater,water,\n",
        encoding="utf-8",
    )

    aliases = load_alias_config(path)

    assert aliases["olive oil"] == "olive_oil"
    assert aliases["water"] == "water"


def test_load_alias_config_detects_duplicate_aliases(tmp_path: Path) -> None:
    path = tmp_path / "ingredient_aliases.csv"
    path.write_text(
        "alias,food_id,notes\nOlive oil,olive_oil,\n olive   oil ,oil_alt,\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate alias"):
        load_alias_config(path)


def test_map_ingredients_blocks_unknown_alias(tmp_path: Path) -> None:
    path = tmp_path / "ingredient_aliases.csv"
    path.write_text("alias,food_id,notes\nolive oil,olive_oil,\n", encoding="utf-8")
    aliases = load_alias_config(path)

    result = map_ingredients(
        "c001",
        [ParsedIngredient(name="Honey", amount=10, unit="g", raw="Honey - 10 g")],
        aliases,
    )

    assert result.status == "blocked"
    assert result.blocker_reason == "unknown_ingredient_alias"
    assert result.rows[0].mapping_status == "blocked"


def test_map_ingredients_blocks_empty_parsed_ingredient_list(tmp_path: Path) -> None:
    path = tmp_path / "ingredient_aliases.csv"
    path.write_text("alias,food_id,notes\nwater,water,\n", encoding="utf-8")
    aliases = load_alias_config(path)

    result = map_ingredients("c001", [], aliases)

    assert result.status == "blocked"
    assert result.blocker_reason == "no_ingredients_to_map"
    assert result.rows == []


def test_water_maps_only_when_represented_in_config(tmp_path: Path) -> None:
    path = tmp_path / "ingredient_aliases.csv"
    path.write_text("alias,food_id,notes\nwater,water,zero nutrition allowed\n", encoding="utf-8")
    aliases = load_alias_config(path)

    result = map_ingredients(
        "c001",
        [ParsedIngredient(name="Water", amount=100, unit="ml", raw="Water - 100 ml")],
        aliases,
    )

    assert result.status == "mapped"
    assert result.rows[0].food_id == "water"


def test_generic_oil_alias_maps_only_exact_generic_oil() -> None:
    aliases = {"масло": "olive_oil"}

    exact = map_ingredients(
        "c001",
        [ParsedIngredient(name="масло", amount=10, unit="g", raw="масло 10 г")],
        aliases,
    )
    specific = map_ingredients(
        "c002",
        [
            ParsedIngredient(
                name="масло сливочное",
                amount=10,
                unit="g",
                raw="масло сливочное 10 г",
            )
        ],
        aliases,
    )

    assert exact.status == "mapped"
    assert exact.rows[0].food_id == "olive_oil"
    assert specific.status == "blocked"
    assert specific.rows[0].food_id == ""
    assert specific.rows[0].blocker_reason == "unknown_ingredient_alias"


def test_reordered_specific_butter_alias_maps_to_butter_not_generic_oil() -> None:
    aliases = {"масло": "olive_oil", "сливочное масло": "butter"}

    result = map_ingredients(
        "c001",
        [
            ParsedIngredient(
                name="масло сливочное",
                amount=10,
                unit="g",
                raw="масло сливочное 10 г",
            )
        ],
        aliases,
    )

    assert result.status == "mapped"
    assert result.rows[0].food_id == "butter"


def test_combined_black_pepper_and_oil_line_does_not_prefix_map_black_pepper() -> None:
    aliases = {
        "\u0447\u0435\u0440\u043d\u044b\u0439 \u043f\u0435\u0440\u0435\u0446": "black_pepper",
        "\u0440\u0430\u0441\u0442\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0435 \u043c\u0430\u0441\u043b\u043e": "vegetable_oil",
    }

    result = map_ingredients(
        "c001",
        [
            ParsedIngredient(
                name="\u0447\u0451\u0440\u043d\u044b\u0439 \u043f\u0435\u0440\u0435\u0446 \u0420\u0430\u0441\u0442\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0435 \u043c\u0430\u0441\u043b\u043e",
                amount=10,
                unit="g",
                raw="\u0447\u0451\u0440\u043d\u044b\u0439 \u043f\u0435\u0440\u0435\u0446 \u0420\u0430\u0441\u0442\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0435 \u043c\u0430\u0441\u043b\u043e 10 \u0433",
            )
        ],
        aliases,
    )

    assert result.status == "blocked"
    assert result.rows[0].food_id == ""
    assert result.rows[0].blocker_reason == "unknown_ingredient_alias"


def test_exact_black_pepper_alias_still_maps() -> None:
    aliases = {"\u0447\u0435\u0440\u043d\u044b\u0439 \u043f\u0435\u0440\u0435\u0446": "black_pepper"}

    result = map_ingredients(
        "c001",
        [
            ParsedIngredient(
                name="\u0447\u0451\u0440\u043d\u044b\u0439 \u043f\u0435\u0440\u0435\u0446",
                amount=2,
                unit="g",
                raw="\u0447\u0451\u0440\u043d\u044b\u0439 \u043f\u0435\u0440\u0435\u0446 2 \u0433",
            )
        ],
        aliases,
    )

    assert result.status == "mapped"
    assert result.rows[0].food_id == "black_pepper"


def test_generic_pepper_alias_does_not_prefix_map_specific_pepper() -> None:
    aliases = {"перец": "bell_pepper"}

    result = map_ingredients(
        "c001",
        [
            ParsedIngredient(
                name="перец чили",
                amount=10,
                unit="g",
                raw="перец чили 10 г",
            )
        ],
        aliases,
    )

    assert result.status == "blocked"
    assert result.rows[0].food_id == ""
    assert result.rows[0].blocker_reason == "unknown_ingredient_alias"


def test_non_generic_prefix_alias_still_maps_inflected_name() -> None:
    aliases = {"кальмар": "calamari"}

    result = map_ingredients(
        "c001",
        [
            ParsedIngredient(
                name="кальмары",
                amount=100,
                unit="g",
                raw="кальмары 100 г",
            )
        ],
        aliases,
    )

    assert result.status == "mapped"
    assert result.rows[0].food_id == "calamari"


def test_generated_food_definition_aliases_map_second_pass_names() -> None:
    aliases = load_alias_config(include_generated_aliases=True)

    result = map_ingredients(
        "c001",
        [
            ParsedIngredient(
                name="куриные бёдра",
                amount=1200,
                unit="g",
                raw="куриные бёдра 1,2 кг",
            ),
            ParsedIngredient(
                name="моцарелла",
                amount=300,
                unit="g",
                raw="моцарелла 300 г",
            ),
        ],
        aliases,
    )

    assert result.status == "mapped"
    assert [row.food_id for row in result.rows] == ["chicken_thigh", "mozzarella"]
