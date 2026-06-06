import pytest

from scripts.dev.recipe_importer.ingredients import parse_ingredients
from scripts.dev.recipe_importer.loader import NormalizedRecipe


def _recipe(**overrides: str) -> NormalizedRecipe:
    values = {
        "candidate_id": "c001",
        "title_ru": "Test",
        "meal_type": "main",
        "duplicate_risk": "low",
        "structured_ingredients": "",
        "raw_ingredient_text": "",
        "servings": "",
        "nutrition": "",
        "instructions": "",
        "time": "",
        "source": "",
        "raw": {},
    }
    values.update(overrides)
    return NormalizedRecipe(**values)


def test_parse_structured_ingredient_rows_with_name_amount_unit() -> None:
    result = parse_ingredients(
        _recipe(
            structured_ingredients=(
                '[{"name": "Olive oil", "amount": "12.5", "unit": "g"}, '
                '{"ingredient": "Water", "quantity": 100, "measure": "ml"}]'
            )
        )
    )

    assert result.parse_status == "parsed"
    assert result.blocker_reason == ""
    assert [(item.name, item.amount, item.unit) for item in result.ingredients] == [
        ("Olive oil", 12.5, "g"),
        ("Water", 100.0, "ml"),
    ]


@pytest.mark.parametrize(
    ("structured_ingredients", "reason"),
    [
        ("", "missing_ingredients"),
        ("{}", "ingredients_not_list"),
        ('[{"amount": 10, "unit": "g"}]', "missing_ingredient_name"),
        ('[{"name": "rice", "unit": "g"}]', "missing_ingredient_amount"),
        ('[{"name": "rice", "amount": 0, "unit": "g"}]', "invalid_ingredient_amount"),
    ],
)
def test_rejects_invalid_structured_ingredients(
    structured_ingredients: str, reason: str
) -> None:
    result = parse_ingredients(_recipe(structured_ingredients=structured_ingredients))

    assert result.parse_status == "blocked"
    assert result.blocker_reason == reason
    assert result.ingredients == []


def test_parses_deterministic_text_ingredient_rows() -> None:
    result = parse_ingredients(
        _recipe(raw_ingredient_text="Olive oil - 12 g\nWater - 100 ml")
    )

    assert result.parse_status == "parsed"
    assert [(item.name, item.amount, item.unit) for item in result.ingredients] == [
        ("Olive oil", 12.0, "g"),
        ("Water", 100.0, "ml"),
    ]


def test_parses_second_pass_bullet_ingredients_with_household_units() -> None:
    result = parse_ingredients(
        _recipe(
            raw_ingredient_text=(
                "• куриные бёдра 1,2 кг • лимонный сок 2 ст. л. "
                "• чеснок 2 зубчика • орегано 1 ч. л. "
                "• соль до 1/4 ч. л., масло 2 ст. л."
            )
        )
    )

    assert result.parse_status == "parsed"
    assert [(item.name, item.amount, item.unit) for item in result.ingredients] == [
        ("куриные бёдра", 1200.0, "g"),
        ("лимонный сок", 30.0, "ml"),
        ("чеснок", 10.0, "g"),
        ("орегано", 5.0, "ml"),
        ("соль", 1.25, "ml"),
        ("масло", 30.0, "ml"),
    ]


def test_parses_excel_400_dash_lines_and_prefers_explicit_grams() -> None:
    result = parse_ingredients(
        _recipe(
            raw_ingredient_text="\n".join(
                [
                    "Овсяные хлопья — 50 г",
                    "Авокадо спелый — 1 шт. / ≈150 г мякоти",
                    "Мёд — 5–7 г",
                ]
            )
        )
    )

    assert result.parse_status == "parsed"
    assert [(item.name, item.amount, item.unit) for item in result.ingredients] == [
        ("Овсяные хлопья", 50.0, "g"),
        ("Авокадо спелый", 150.0, "g"),
        ("Мёд", 5.0, "g"),
    ]


def test_blocks_ambiguous_text_ingredient_rows() -> None:
    result = parse_ingredients(_recipe(raw_ingredient_text="Olive oil to taste"))

    assert result.parse_status == "blocked"
    assert result.blocker_reason == "ambiguous_ingredient_text"
