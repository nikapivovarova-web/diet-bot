from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecipeTemplate:
    id: str
    slot: str
    title: str
    ingredients_g: dict[str, float]
    instructions: str
    tags: frozenset[str] = frozenset()
    image_url: str | None = None
    image_attribution: str | None = None
    source_url: str | None = None
    time_text: str = ""
    allowed_meal_slots: tuple[str, ...] = ()
    slot_flex_type: str | None = None
    cooking_effort: str | None = None
    active_time_min: int | None = None
    coverage_priority: str | None = None
