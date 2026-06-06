from pathlib import Path

import pytest

from scripts.dev.recipe_importer.servings import resolve_servings


@pytest.fixture()
def defaults_path(tmp_path: Path) -> Path:
    path = tmp_path / "default_servings_by_category.json"
    path.write_text('{"main": 2, "snack": 1}', encoding="utf-8")
    return path


def test_explicit_positive_servings_are_exact(defaults_path: Path) -> None:
    result = resolve_servings("3", "main", defaults_path)

    assert result.status == "valid"
    assert result.servings == 3
    assert result.estimated is False
    assert result.blocker_reason == ""


def test_serving_range_uses_lower_bound_and_marks_estimated(defaults_path: Path) -> None:
    result = resolve_servings("2-4", "main", defaults_path)

    assert result.status == "valid"
    assert result.servings == 2
    assert result.estimated is True
    assert result.source == "range_lower_bound"


def test_missing_servings_uses_category_default(defaults_path: Path) -> None:
    result = resolve_servings("", "snack", defaults_path)

    assert result.status == "valid"
    assert result.servings == 1
    assert result.estimated is True
    assert result.source == "category_default"


@pytest.mark.parametrize("raw", ["0", "-1", "abc", "1-0"])
def test_invalid_zero_or_negative_servings_block(raw: str, defaults_path: Path) -> None:
    result = resolve_servings(raw, "main", defaults_path)

    assert result.status == "blocked"
    assert result.servings == 0
    assert result.blocker_reason == "invalid_servings"
