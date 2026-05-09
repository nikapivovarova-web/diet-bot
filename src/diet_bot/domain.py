from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class Goal(StrEnum):
    LOSE = "lose"
    MAINTAIN = "maintain"
    GAIN = "gain"


class ActivityLevel(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    ACTIVE = "active"
    VERY_ACTIVE = "very_active"


class CookingTimePreference(StrEnum):
    QUICK = "quick"
    MEDIUM = "medium"
    LONG = "long"


class RestrictionType(StrEnum):
    ALLERGY = "allergy"
    INTOLERANCE = "intolerance"
    EXCLUDED_FOOD = "excluded_food"
    DIETARY_PATTERN = "dietary_pattern"


class ConditionCode(StrEnum):
    CELIAC = "celiac"
    GLUTEN_INTOLERANCE = "gluten_intolerance"
    LACTOSE_INTOLERANCE = "lactose_intolerance"
    CKD = "chronic_kidney_disease"
    DIABETES = "diabetes"
    HYPERTENSION = "hypertension"
    GERD = "gerd"
    GASTRITIS = "gastritis"
    GOUT = "gout"
    PREGNANCY = "pregnancy"
    LACTATION = "lactation"
    EATING_DISORDER = "eating_disorder"
    DIALYSIS = "dialysis"
    ONCOLOGY = "oncology"
    SEVERE_LIVER_DISEASE = "severe_liver_disease"


class MealRole(StrEnum):
    PROTEIN = "protein"
    CARB = "carb"
    VEGETABLE = "vegetable"
    FRUIT = "fruit"
    FAT = "fat"
    CALCIUM = "calcium"
    BOOSTER = "booster"


@dataclass(frozen=True)
class UserProfile:
    age: int
    sex: Sex
    height_cm: float
    weight_kg: float
    goal: Goal
    activity: ActivityLevel
    meal_count: int = 4
    cooking_time: CookingTimePreference = CookingTimePreference.LONG
    restrictions: tuple["Restriction", ...] = ()
    conditions: tuple[ConditionCode, ...] = ()
    allow_lactose_free_dairy: bool = True
    allow_gluten_free_oats: bool = False


@dataclass(frozen=True)
class Restriction:
    type: RestrictionType
    value: str
    severity: str = "hard"

    @property
    def normalized_value(self) -> str:
        return normalize_text(self.value)


@dataclass(frozen=True)
class NutrientVector:
    amounts: dict[str, float] = field(default_factory=dict)

    def get(self, key: str) -> float:
        return float(self.amounts.get(key, 0.0))

    def scaled(self, factor: float) -> "NutrientVector":
        return NutrientVector({key: value * factor for key, value in self.amounts.items()})

    def plus(self, other: "NutrientVector") -> "NutrientVector":
        keys = set(self.amounts) | set(other.amounts)
        return NutrientVector({key: self.get(key) + other.get(key) for key in keys})

    def minus(self, other: "NutrientVector") -> "NutrientVector":
        keys = set(self.amounts) | set(other.amounts)
        return NutrientVector({key: self.get(key) - other.get(key) for key in keys})

    def clipped_positive(self) -> "NutrientVector":
        return NutrientVector({key: max(0.0, value) for key, value in self.amounts.items()})

    @classmethod
    def sum(cls, vectors: Iterable["NutrientVector"]) -> "NutrientVector":
        total = cls()
        for vector in vectors:
            total = total.plus(vector)
        return total


@dataclass(frozen=True)
class Food:
    id: str
    name: str
    category: str
    nutrients_per_100g: NutrientVector
    tags: frozenset[str] = frozenset()
    roles: frozenset[MealRole] = frozenset()
    max_per_meal_g: float = 250
    max_per_day_g: float = 400

    def portion(self, grams: float) -> "FoodPortion":
        return FoodPortion(food=self, grams=grams)

    def has_any_tag(self, tags: set[str]) -> bool:
        return bool(self.tags & tags)


@dataclass(frozen=True)
class FoodPortion:
    food: Food
    grams: float

    @property
    def nutrients(self) -> NutrientVector:
        return self.food.nutrients_per_100g.scaled(self.grams / 100)


@dataclass(frozen=True)
class BatchPrep:
    total_units: int
    serving_units: int
    unit_forms: tuple[str, str, str]
    batch_portions: tuple[FoodPortion, ...]
    is_carryover: bool = False

    @property
    def serving_count(self) -> int:
        if self.serving_units <= 0:
            return 1
        return max(1, self.total_units // self.serving_units)


@dataclass(frozen=True)
class NutritionTargets:
    bmi: float
    bmi_category: str
    bmr_kcal: float
    tdee_kcal: float
    water_l: float
    targets: NutrientVector
    calorie_bounds: tuple[float, float]
    macro_bounds: dict[str, tuple[float, float]]


@dataclass(frozen=True)
class SafetyResult:
    can_generate_plan: bool
    excluded_tags: frozenset[str] = frozenset()
    excluded_food_names: frozenset[str] = frozenset()
    caution_notes: tuple[str, ...] = ()
    disclaimers: tuple[str, ...] = ()
    red_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Meal:
    name: str
    portions: tuple[FoodPortion, ...]
    recipe: str
    image_url: str | None = None
    image_attribution: str | None = None
    source_url: str | None = None
    recipe_id: str | None = None
    recipe_key: str | None = None
    batch: BatchPrep | None = None

    @property
    def nutrients(self) -> NutrientVector:
        return NutrientVector.sum(portion.nutrients for portion in self.portions)


@dataclass(frozen=True)
class MealPlan:
    meals: tuple[Meal, ...]
    targets: NutritionTargets
    safety: SafetyResult

    @property
    def totals(self) -> NutrientVector:
        return NutrientVector.sum(meal.nutrients for meal in self.meals)


@dataclass(frozen=True)
class ShoppingItem:
    food_name: str
    category: str
    grams: float


def normalize_text(value: str) -> str:
    return value.strip().lower().replace("ё", "е")
