from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SERVINGS_PATH = Path(__file__).parent / "config" / "default_servings_by_category.json"
_RANGE_PATTERN = re.compile(r"^\s*(?P<low>\d+(?:[.,]\d+)?)\s*[-–]\s*(?P<high>\d+(?:[.,]\d+)?)\s*$")


@dataclass(frozen=True)
class ServingsResult:
    status: str
    servings: int
    estimated: bool
    source: str
    blocker_reason: str


def resolve_servings(
    raw_servings: str,
    category: str,
    defaults_path: Path = DEFAULT_SERVINGS_PATH,
) -> ServingsResult:
    value = (raw_servings or "").strip()
    if not value:
        return _from_category_default(category, defaults_path)

    range_match = _RANGE_PATTERN.match(value)
    if range_match:
        low = _parse_positive_number(range_match.group("low"))
        high = _parse_positive_number(range_match.group("high"))
        if low is None or high is None or low > high:
            return _blocked()
        return ServingsResult("valid", int(low), True, "range_lower_bound", "")

    parsed = _parse_positive_number(value)
    if parsed is None:
        return _blocked()
    return ServingsResult("valid", int(parsed), False, "explicit", "")


def _from_category_default(category: str, defaults_path: Path) -> ServingsResult:
    defaults = json.loads(Path(defaults_path).read_text(encoding="utf-8"))
    key = (category or "").strip().lower()
    default = defaults.get(key)
    if not isinstance(default, int) or default <= 0:
        return _blocked("missing_servings_default")
    return ServingsResult("valid", default, True, "category_default", "")


def _parse_positive_number(value: str) -> float | None:
    try:
        parsed = float(value.replace(",", "."))
    except ValueError:
        return None
    if parsed <= 0 or not parsed.is_integer():
        return None
    return parsed


def _blocked(reason: str = "invalid_servings") -> ServingsResult:
    return ServingsResult("blocked", 0, False, "", reason)
