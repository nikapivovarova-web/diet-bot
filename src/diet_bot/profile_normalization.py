from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .domain import ConditionCode, normalize_text


MAX_RAW_TEXT_LENGTH = 300
MAX_ITEMS = 12
MAX_ITEM_LENGTH = 40
MIN_ITEM_LENGTH = 2

NONE_WORDS = {"нет", "no", "-", "ничего", "нету", "не"}
LIST_SEPARATOR_RE = re.compile(r"[,;\n]+")
UNSUPPORTED_ITEM_CHARS_RE = re.compile(r"[^a-zа-я0-9\- ]+", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
CONDITION_DISPLAY_NAMES = {
    ConditionCode.CELIAC: "целиакия",
    ConditionCode.GLUTEN_INTOLERANCE: "непереносимость глютена",
    ConditionCode.LACTOSE_INTOLERANCE: "непереносимость лактозы",
    ConditionCode.CKD: "ХПН",
    ConditionCode.DIABETES: "диабет",
    ConditionCode.HYPERTENSION: "гипертония",
    ConditionCode.GERD: "ГЭРБ",
    ConditionCode.GASTRITIS: "гастрит",
    ConditionCode.GOUT: "подагра",
    ConditionCode.PREGNANCY: "беременность",
    ConditionCode.LACTATION: "лактация",
    ConditionCode.EATING_DISORDER: "РПП",
    ConditionCode.DIALYSIS: "диализ",
    ConditionCode.ONCOLOGY: "онкология",
    ConditionCode.SEVERE_LIVER_DISEASE: "тяжелое заболевание печени",
}


@dataclass(frozen=True)
class NormalizedList:
    items: list[str]
    was_trimmed: bool = False
    errors: list[str] = field(default_factory=list)


def normalize_free_text_list(raw: str | None, *, max_items: int = MAX_ITEMS) -> NormalizedList:
    if raw is None or not raw.strip():
        return NormalizedList(items=[])

    text = _normalize_raw_text(raw)
    if _is_none_answer(text):
        return NormalizedList(items=[])

    if len(text) > MAX_RAW_TEXT_LENGTH:
        return NormalizedList(
            items=[],
            errors=[f"Ответ слишком длинный. Напишите до {MAX_RAW_TEXT_LENGTH} символов."],
        )

    cleaned = _clean_items(_split_text(text))
    if len(cleaned) > max_items:
        return NormalizedList(
            items=cleaned[:max_items],
            was_trimmed=True,
            errors=[f"Список слишком длинный. Напишите до {max_items} пунктов, через запятую."],
        )

    if not cleaned:
        return NormalizedList(
            items=[],
            errors=["Не удалось распознать список. Напишите коротко через запятую, например: молоко, арахис, креветки."],
        )

    return NormalizedList(items=cleaned)


def normalize_conditions(raw: str | None) -> NormalizedList:
    base = normalize_free_text_list(raw)
    if base.errors:
        return base
    if not base.items:
        return base

    condition_codes: list[ConditionCode] = []
    unknown_items: list[str] = []
    seen: set[ConditionCode] = set()
    for item in base.items:
        condition = _condition_code_for_item(item)
        if condition is None:
            unknown_items.append(item)
            continue
        if condition not in seen:
            seen.add(condition)
            condition_codes.append(condition)

    if unknown_items:
        recognized = ""
        if condition_codes:
            recognized = f"Я распознал: {_format_condition_codes(condition_codes)}. "
        return NormalizedList(
            items=[condition.value for condition in condition_codes],
            errors=[
                f"{recognized}Остальное не удалось точно распознать. Напишите коротко через запятую, например: диабет, гипертония, гастрит."
            ],
        )

    if not condition_codes:
        return NormalizedList(
            items=[],
            errors=[
                "Не удалось точно распознать состояния. Напишите коротко через запятую, например: диабет, гипертония, гастрит."
            ],
        )
    return NormalizedList(
        items=[condition.value for condition in condition_codes],
        was_trimmed=base.was_trimmed,
        errors=base.errors,
    )


def normalize_stored_free_text_items(value: object, *, max_items: int = MAX_ITEMS) -> list[str]:
    raw_items = _stored_value_to_parts(value)
    return _clean_items(raw_items)[:max_items]


def normalize_stored_condition_codes(value: object, *, max_items: int = MAX_ITEMS) -> list[ConditionCode]:
    raw_items = normalize_stored_free_text_items(value, max_items=max_items)
    return condition_codes_from_items(raw_items)


def condition_codes_from_items(items: Iterable[str]) -> list[ConditionCode]:
    found: list[ConditionCode] = []
    seen: set[ConditionCode] = set()
    for item in items:
        condition = _condition_code_for_item(item)
        if condition is not None and condition not in seen:
            seen.add(condition)
            found.append(condition)
    return found


def _stored_value_to_parts(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_text(_normalize_raw_text(value))
    if isinstance(value, Iterable):
        parts: list[str] = []
        for item in value:
            if item is None:
                continue
            parts.extend(_split_text(_normalize_raw_text(str(item))))
        return parts
    return _split_text(_normalize_raw_text(str(value)))


def _split_text(text: str) -> list[str]:
    if _is_none_answer(text):
        return []
    return LIST_SEPARATOR_RE.split(text)


def _clean_items(parts: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = _clean_item(part)
        if item is None or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _clean_item(value: str) -> str | None:
    item = value.strip(" .:-—–•\t")
    item = item.replace("_", " ")
    item = UNSUPPORTED_ITEM_CHARS_RE.sub("", item)
    item = SPACE_RE.sub(" ", item).strip()
    if item in NONE_WORDS:
        return None
    if len(item) < MIN_ITEM_LENGTH or len(item) > MAX_ITEM_LENGTH:
        return None
    return item


def _normalize_raw_text(value: str) -> str:
    text = normalize_text(value)
    return text.replace("_", " ")


def _is_none_answer(value: str) -> bool:
    return value.strip() in NONE_WORDS


def _format_condition_codes(conditions: Iterable[ConditionCode]) -> str:
    return ", ".join(CONDITION_DISPLAY_NAMES.get(condition, condition.value) for condition in conditions)


def _condition_code_for_item(item: str) -> ConditionCode | None:
    normalized = SPACE_RE.sub(" ", _normalize_raw_text(item))
    try:
        return ConditionCode(normalized)
    except ValueError:
        pass

    condition_map: tuple[tuple[tuple[str, ...], ConditionCode], ...] = (
        (("целиак",), ConditionCode.CELIAC),
        (("глютен", "gluten"), ConditionCode.GLUTEN_INTOLERANCE),
        (("лактоз", "lactose"), ConditionCode.LACTOSE_INTOLERANCE),
        (("хпн", "почек", "почеч", "ckd", "chronic kidney", "kidney disease"), ConditionCode.CKD),
        (("диабет", "diabetes", "diabetes type 2"), ConditionCode.DIABETES),
        (("гипертони", "давлен", "hypertension", "high blood pressure"), ConditionCode.HYPERTENSION),
        (("гэрб", "рефлюкс", "gerd", "reflux"), ConditionCode.GERD),
        (("гастрит", "gastritis"), ConditionCode.GASTRITIS),
        (("подагр", "gout"), ConditionCode.GOUT),
        (("беремен", "pregnancy"), ConditionCode.PREGNANCY),
        (("лактац", "кормлю", "гв", "breastfeeding", "lactation"), ConditionCode.LACTATION),
        (
            ("рпп", "расстройств пищев", "пищевое расстройств", "пищевое поведение", "eating disorder"),
            ConditionCode.EATING_DISORDER,
        ),
        (("диализ", "dialysis"), ConditionCode.DIALYSIS),
        (("онко", "рак", "oncology", "cancer"), ConditionCode.ONCOLOGY),
        (("печен", "цирроз", "liver disease", "cirrhosis"), ConditionCode.SEVERE_LIVER_DISEASE),
    )
    for needles, condition in condition_map:
        if any(needle in normalized for needle in needles):
            return condition
    return None
