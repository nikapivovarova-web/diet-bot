from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "src" / "diet_bot" / "data"
DEFAULT_REPORT_PATH = ROOT / "docs" / "recovery-integration" / "recipe-content-audit-round2.md"
DEFAULT_CSV_PATH = ROOT / "docs" / "recovery-integration" / "recipe-content-audit-round2-findings.csv"

FINDING_GROUPS = (
    "title_ingredient_mismatch",
    "ingredient_missing_from_steps",
    "steps_mention_missing_ingredient",
    "truncation_fragments",
    "non_cis_unclear_ingredients",
    "tiny_gram_anomalies",
    "missing_approximate_measures",
)

GROUP_LABELS = {
    "title_ingredient_mismatch": "title/ingredient mismatch",
    "ingredient_missing_from_steps": "ingredient missing from steps",
    "steps_mention_missing_ingredient": "steps mention missing ingredient",
    "truncation_fragments": "truncation/fragments",
    "non_cis_unclear_ingredients": "non-CIS/unclear ingredients",
    "tiny_gram_anomalies": "tiny gram anomalies",
    "missing_approximate_measures": "missing approximate measures",
}

BLOCKER_PRIORITY = {
    "title_hummus_missing": 0,
    "step_mentions_missing_hummus": 1,
    "title_harissa_missing": 2,
    "user_facing_harissa": 3,
    "broken_step_fragment": 4,
    "empty_instructions": 5,
    "short_broken_step": 6,
    "title_term_missing": 7,
    "tiny_peanut_paste": 8,
    "tiny_primary_quantity": 9,
    "zero_primary_quantity": 10,
}

USER_FACING_NON_CIS_PATTERNS = (
    ("harissa", re.compile(r"\bharissa\b|харисс?а", re.IGNORECASE)),
    ("edamame", re.compile(r"\bedamame\b|эдамаме", re.IGNORECASE)),
    ("american_cheese", re.compile(r"\bamerican cheese\b|американский сыр", re.IGNORECASE)),
)

KNOWN_SEARCH_PATTERNS = (
    ("hummus", re.compile(r"\bhummus\b|хумус", re.IGNORECASE)),
    ("harissa", re.compile(r"\bharissa\b|харисс?а", re.IGNORECASE)),
    ("american_cheese", re.compile(r"\bamerican_cheese\b|\bamerican cheese\b|американский сыр", re.IGNORECASE)),
    ("edamame", re.compile(r"\bedamame\b|эдамаме", re.IGNORECASE)),
    ("peanut_paste", re.compile(r"арахисовая паста", re.IGNORECASE)),
)

IGNORED_USAGE_FOOD_IDS = frozenset(
    {
        "water",
        "salt",
        "black_pepper",
        "white_pepper",
        "paprika",
        "smoked_paprika",
        "cumin",
        "coriander",
        "cinnamon",
        "cardamom",
        "cloves",
        "nutmeg",
        "turmeric",
        "curry_powder",
        "garam_masala",
        "chili_powder",
        "chili_flakes",
        "red_pepper_flakes",
        "cayenne",
        "bay_leaf",
        "mixed_spices",
        "five_spice",
        "cajun_seasoning",
        "garlic_powder",
        "onion_powder",
        "baking_powder",
        "baking_soda",
        "yeast",
        "vanilla_extract",
        "vegetable_oil",
        "olive_oil",
        "olive_oil_spray",
        "canola_oil",
        "avocado_oil",
        "coconut_oil",
        "peanut_oil",
        "sesame_oil",
        "butter",
    }
)

SERVING_OR_GARNISH_MARKERS = (
    "сверху",
    "для подачи",
    "перед подачей",
    "при подаче",
    "гарнир",
    "украс",
    "по вкусу",
    "опционально",
    "по желанию",
    "немного",
    "для смазывания",
    "для формы",
    "для сковороды",
    "для жарки",
)

INTENTIONAL_ZERO_MARKERS = (
    "по вкусу",
    "сверху",
    "для подачи",
    "немного",
    "для варки",
    "для смазывания",
    "для формы",
    "кулинарный спрей",
    "0g seasoning policy",
)

HOUSEHOLD_MEASURE_MARKERS = (
    "шт",
    "зуб",
    "доль",
    "ломт",
    "ст.",
    "ч.",
    "мл",
    "л.",
    "стак",
    "перо",
    "горст",
    "лист",
    "капл",
    "щеп",
    "по вкусу",
    "около",
    "примерно",
    "≈",
    "~",
    "1/2",
    "1/3",
    "1/4",
    "0,5",
    "0.5",
)

APPROX_FOOD_IDS = frozenset(
    {
        "garlic",
        "dates",
        "dried_dates",
        "peanut_butter",
        "tahini",
        "hummus",
        "mayonnaise",
        "vinegar",
        "soy_sauce",
        "teriyaki_sauce",
        "sriracha",
        "sriracha_extra",
        "hot_sauce",
        "chili_sauce",
        "salsa",
        "pesto",
        "sesame_oil",
        "gouda",
        "cheddar",
        "mozzarella",
        "parmesan",
        "feta",
        "cream_cheese",
        "ricotta",
        "cottage_cheese",
        "blue_cheese",
        "goat_cheese",
        "american_cheese",
        "walnuts",
        "pecans",
        "almonds",
        "cashews",
        "hazelnuts",
        "pistachios",
        "peanuts",
        "nuts_mix",
    }
)

NUT_OR_PASTE_FOOD_IDS = frozenset(
    {
        "peanut_butter",
        "tahini",
        "almonds",
        "walnuts",
        "pecans",
        "cashews",
        "hazelnuts",
        "pistachios",
        "peanuts",
        "nuts_mix",
        "hummus",
        "pesto",
        "cream_cheese",
    }
)

SAUCE_FOOD_IDS = frozenset(
    {
        "soy_sauce",
        "teriyaki_sauce",
        "hot_sauce",
        "sriracha",
        "sriracha_extra",
        "vinegar",
        "mayonnaise",
        "hummus",
        "tahini",
        "pesto",
        "salsa",
        "guacamole",
        "worcestershire",
        "mustard",
    }
)

PRIMARY_FOOD_ID_PARTS = (
    "chicken",
    "turkey",
    "beef",
    "pork",
    "lamb",
    "salmon",
    "tuna",
    "cod",
    "hake",
    "trout",
    "shrimp",
    "tofu",
    "egg",
    "rice",
    "buckwheat",
    "bulgur",
    "quinoa",
    "pasta",
    "noodles",
    "potato",
    "bread",
    "pita",
    "lavash",
    "beans",
    "chickpeas",
    "lentils",
    "peas",
    "cheese",
)

MANUAL_FOOD_ALIASES: dict[str, tuple[str, ...]] = {
    "hummus": ("хумус",),
    "soba_noodles": ("соба", "лапша соба", "гречневая лапша", "лапша"),
    "peanut_butter": ("арахисовая паста", "ореховая паста", "арахисовый"),
    "harissa": ("харисса", "хариса", "harissa"),
    "american_cheese": ("американский сыр", "сыр в ломтиках", "сыр"),
    "edamame": ("эдамаме", "edamame"),
    "green_peas": ("зеленый горошек", "горошек", "стручковый горошек"),
    "chickpeas": ("нут",),
    "tahini": ("тахини", "паста тахини"),
    "soy_sauce": ("соевый соус", "тамари"),
    "sesame_oil": ("кунжутное масло",),
    "vinegar": ("уксус",),
    "mayonnaise": ("майонез",),
    "teriyaki_sauce": ("терияки", "соус терияки"),
    "gouda": ("гауда", "сыр"),
    "cheddar": ("чеддер", "сыр"),
    "mozzarella": ("моцарелла", "сыр"),
    "parmesan": ("пармезан", "сыр"),
    "feta": ("фета", "сыр"),
    "cream_cheese": ("сливочный сыр", "крем-сыр", "сыр"),
    "cottage_cheese": ("творог", "творожный"),
    "greek_yogurt": ("йогурт", "греческий йогурт"),
    "yogurt": ("йогурт",),
    "kefir": ("кефир",),
    "egg": ("яйцо", "яйца", "яичный"),
    "chicken_breast": ("курица", "куриный", "куриная грудка"),
    "chicken_breast_cooked": ("курица", "куриная грудка", "готовая куриная грудка"),
    "turkey": ("индейка", "индейки"),
    "turkey_breast_cooked": ("индейка", "грудка индейки"),
    "beef": ("говядина", "говяжий"),
    "ground_beef": ("говяжий фарш", "говядина", "фарш"),
    "pork": ("свинина", "свиной"),
    "salmon": ("лосось", "семга"),
    "tuna": ("тунец",),
    "tuna_steak": ("тунец",),
    "cod": ("треска", "белая рыба"),
    "hake": ("хек", "белая рыба"),
    "shrimp": ("креветки", "креветка"),
    "tofu": ("тофу",),
    "rice": ("рис", "рисовый"),
    "buckwheat": ("гречка", "гречневый"),
    "bulgur": ("булгур",),
    "quinoa": ("киноа",),
    "whole_wheat_pasta": ("паста", "макароны", "пенне", "спагетти"),
    "pasta": ("паста", "макароны", "пенне", "спагетти"),
    "potato": ("картофель", "картошка"),
    "sweet_potato": ("батат",),
    "lavash": ("лаваш",),
    "pita": ("пита", "питта"),
    "pita_extra": ("пита", "питта"),
    "tortilla": ("тортилья",),
    "whole_wheat_bread": ("хлеб", "тост"),
    "beans": ("фасоль",),
    "black_beans": ("черная фасоль", "фасоль"),
    "lentils": ("чечевица",),
    "lettuce": ("салат", "листья салата", "ромэн", "айсберг"),
    "tomato": ("помидор", "томат"),
    "cherry_tomatoes": ("помидоры черри", "томаты черри", "черри"),
    "cucumber": ("огурец",),
    "bell_pepper": ("сладкий перец", "болгарский перец", "перец"),
    "zucchini": ("кабачок", "цукини"),
    "eggplant": ("баклажан",),
    "carrot": ("морковь", "морковный"),
    "cabbage": ("капуста",),
    "broccoli": ("брокколи",),
    "spinach": ("шпинат",),
    "mushrooms": ("грибы", "шампиньоны"),
    "shiitake": ("шиитаке",),
    "avocado": ("авокадо",),
    "apple": ("яблоко", "яблочный"),
    "banana": ("банан", "банановый"),
    "dates": ("финики", "финик"),
    "berries": ("ягоды", "ягодный"),
    "blueberries": ("голубика",),
    "strawberries": ("клубника",),
    "raspberries": ("малина",),
    "mango": ("манго",),
    "sesame_seeds": ("кунжут",),
    "walnuts": ("грецкий орех", "грецкие орехи", "орех"),
    "pecans": ("пекан",),
    "almonds": ("миндаль",),
    "cashews": ("кешью",),
    "nuts_mix": ("орехи", "смесь орехов"),
}

TITLE_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], bool], ...] = (
    ("hummus", ("хумус",), ("hummus",), True),
    ("harissa", ("харисса", "хариса", "harissa"), ("harissa",), True),
    ("american_cheese", ("американский сыр", "american cheese"), ("american_cheese",), True),
    ("edamame", ("эдамаме", "edamame"), ("edamame",), True),
    ("soba", ("соба", "лапша соба"), ("soba_noodles",), True),
    ("peanut_paste", ("арахисовая паста", "ореховая паста"), ("peanut_butter",), True),
    ("chicken", ("куриц", "курин"), ("chicken_breast", "chicken_breast_cooked", "chicken_thigh"), False),
    ("turkey", ("индейк",), ("turkey", "turkey_breast_cooked"), False),
    ("beef", ("говяд", "говяж"), ("beef", "ground_beef"), False),
    ("pork", ("свинин", "свин"), ("pork", "pork_tenderloin"), False),
    ("salmon", ("лосос", "семг"), ("salmon",), False),
    ("tuna", ("тунц",), ("tuna", "tuna_steak"), False),
    ("shrimp", ("кревет",), ("shrimp",), False),
    ("tofu", ("тофу",), ("tofu",), False),
    ("egg", ("яйц", "яич"), ("egg",), False),
    ("cottage_cheese", ("творог", "творож"), ("cottage_cheese",), False),
    ("yogurt", ("йогурт",), ("greek_yogurt", "yogurt"), False),
    ("cheese", ("сыр", "сырн"), ("gouda", "cheddar", "mozzarella", "parmesan", "feta", "cream_cheese", "cottage_cheese", "ricotta", "goat_cheese", "american_cheese"), False),
    ("rice", ("рис", "рисов"), ("rice",), False),
    ("buckwheat", ("греч",), ("buckwheat", "soba_noodles"), False),
    ("bulgur", ("булгур",), ("bulgur",), False),
    ("quinoa", ("киноа",), ("quinoa",), False),
    ("pasta", ("макарон", "спагетти", "пенне", "фузилли"), ("pasta", "whole_wheat_pasta"), False),
    ("potato", ("картоф", "картош"), ("potato",), False),
    ("sweet_potato", ("батат",), ("sweet_potato",), False),
    ("chickpeas", ("нут", "нутов"), ("chickpeas",), False),
    ("beans", ("фасол",), ("beans", "black_beans", "white_beans", "red_beans", "green_beans"), False),
    ("lentils", ("чечевиц",), ("lentils",), False),
    ("green_peas", ("горош",), ("green_peas",), False),
    ("avocado", ("авокад",), ("avocado",), False),
    ("cucumber", ("огур",), ("cucumber",), False),
    ("tomato", ("томат", "помид"), ("tomato", "cherry_tomatoes"), False),
    ("pepper", ("перец", "перц"), ("bell_pepper", "chili_pepper", "shishito_pepper"), False),
    ("carrot", ("морков",), ("carrot",), False),
    ("cabbage", ("капуст",), ("cabbage", "red_cabbage"), False),
    ("broccoli", ("брокколи",), ("broccoli",), False),
    ("spinach", ("шпинат",), ("spinach",), False),
    ("zucchini", ("кабач", "цукини"), ("zucchini",), False),
    ("eggplant", ("баклаж",), ("eggplant",), False),
    ("mushrooms", ("гриб", "шампиньон", "шиитаке"), ("mushrooms", "shiitake"), False),
    ("dates", ("финик",), ("dates", "dried_dates"), False),
    ("nuts", ("орех", "кешью", "миндаль", "пекан"), ("walnuts", "pecans", "almonds", "cashews", "hazelnuts", "pistachios", "nuts_mix"), False),
)

STEP_TERMS: tuple[tuple[str, tuple[str, ...], tuple[str, ...], bool], ...] = (
    ("hummus", ("хумус",), ("hummus",), True),
    ("harissa", ("харисса", "хариса", "harissa"), ("harissa",), True),
    ("american_cheese", ("американский сыр", "american cheese"), ("american_cheese",), True),
    ("edamame", ("эдамаме", "edamame"), ("edamame",), True),
    ("soba", ("соба", "лапша соба"), ("soba_noodles",), True),
    ("peanut_paste", ("арахисовая паста", "ореховая паста"), ("peanut_butter",), True),
    ("tahini", ("тахини",), ("tahini",), False),
    ("chickpeas", ("нут",), ("chickpeas",), False),
    ("soy_sauce", ("соевый соус", "тамари"), ("soy_sauce", "tamari"), False),
    ("sesame_oil", ("кунжутное масло",), ("sesame_oil",), False),
    ("mayonnaise", ("майонез",), ("mayonnaise",), False),
    ("teriyaki", ("терияки",), ("teriyaki_sauce",), False),
    ("rice", ("рис",), ("rice",), False),
    ("green_peas", ("зеленый горошек", "горошек"), ("green_peas",), False),
    ("cheese", ("сыр",), ("gouda", "cheddar", "mozzarella", "parmesan", "feta", "cream_cheese", "ricotta", "goat_cheese", "american_cheese", "cottage_cheese"), False),
)

BROKEN_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("standalone_spoon_fragment", re.compile(r"(?:^|[.!?]\s*)\d+(?:[,.]\d+)?\s*ст\.(?!\s*л\.)", re.IGNORECASE), "standalone `ст.` measure fragment"),
    ("standalone_l_fragment", re.compile(r"(?:^|[.!?]\s*)(?<!ст\. )(?<!ч\. )(?<!ст\.)(?<!ч\.)л\.(?:\s|$)", re.IGNORECASE), "standalone `л.` fragment"),
    ("broken_half_word", re.compile(r"полобульон", re.IGNORECASE), "known broken half-word fragment"),
    ("broken_broth_word", re.compile(r"бульонм", re.IGNORECASE), "known broken broth fragment"),
    ("duplicate_ready_phrase", re.compile(r"до состояния до", re.IGNORECASE), "duplicated ready-state wording"),
    ("english_lettuce_wraps", re.compile(r"lettuce wraps", re.IGNORECASE), "English phrase left in recipe text"),
)


@dataclass(frozen=True)
class AuditIssue:
    severity: str
    group: str
    code: str
    recipe_no: int | None
    recipe_id: str
    title: str
    message: str
    evidence: str = ""
    recommendation: str = ""
    food_id: str = ""
    line_index: int | None = None

    def sort_key(self) -> tuple[int, int, int, int, str, str]:
        severity_order = 0 if self.severity == "blocker" else 1
        group_order = FINDING_GROUPS.index(self.group) if self.group in FINDING_GROUPS else 99
        blocker_order = BLOCKER_PRIORITY.get(self.code, 50)
        return (severity_order, blocker_order, group_order, self.recipe_no or 9999, self.recipe_id, self.code)

    def location(self) -> str:
        if self.recipe_no is not None:
            return f"r{self.recipe_no:03d}"
        return self.recipe_id or "data"

    def markdown_line(self) -> str:
        line = f"- `{self.severity}` `{self.code}` {self.location()} `{self.recipe_id}`"
        if self.food_id:
            line += f" `{self.food_id}`"
        if self.line_index is not None:
            line += f" line {self.line_index}"
        line += f": {self.message}"
        if self.evidence:
            line += f" Evidence: {self.evidence}"
        return line


@dataclass(frozen=True)
class AuditResult:
    recipes_checked: int
    ingredients_checked: int
    foods_checked: int
    nutrition_rows_checked: int
    issues: tuple[AuditIssue, ...]
    known_search_counts: dict[str, int]

    @property
    def blockers(self) -> tuple[AuditIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "blocker")

    @property
    def warnings(self) -> tuple[AuditIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity != "blocker")

    @property
    def review_items(self) -> tuple[AuditIssue, ...]:
        return self.warnings

    def counts_by_group(self) -> dict[str, Counter[str]]:
        counts: dict[str, Counter[str]] = {group: Counter() for group in FINDING_GROUPS}
        for issue in self.issues:
            counts.setdefault(issue.group, Counter())[issue.severity] += 1
        return counts


def run_audit(data_dir: Path = DATA_DIR) -> AuditResult:
    recipes = _load_json(data_dir / "curated_recipes.json")
    ingredients = _load_json(data_dir / "curated_recipe_ingredients.json")
    foods = _load_json(data_dir / "curated_foods.json")
    nutrition = _load_json(data_dir / "curated_recipe_nutrition.json")

    recipe_by_id = {str(row["recipe_id"]): row for row in recipes}
    food_by_id = {str(row["food_id"]): row for row in foods}
    rows_by_recipe: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ingredients:
        rows_by_recipe[str(row.get("recipe_id") or "")].append(row)

    issues: list[AuditIssue] = []
    for recipe in recipes:
        recipe_id = str(recipe["recipe_id"])
        rows = rows_by_recipe.get(recipe_id, [])
        issues.extend(_audit_recipe(recipe, rows, food_by_id))
        issues.extend(_audit_ingredient_usage(recipe, rows, food_by_id))
        issues.extend(_audit_steps_missing_ingredients(recipe, rows))
        issues.extend(_audit_title_terms(recipe, rows))

    issues.extend(_audit_ingredient_rows(ingredients, recipe_by_id, food_by_id))
    issues.extend(_audit_food_catalog(foods))

    return AuditResult(
        recipes_checked=len(recipes),
        ingredients_checked=len(ingredients),
        foods_checked=len(foods),
        nutrition_rows_checked=len(nutrition),
        issues=tuple(sorted(_dedupe_issues(issues), key=AuditIssue.sort_key)),
        known_search_counts=_known_search_counts(recipes, ingredients, foods),
    )


def write_report(
    result: AuditResult,
    path: Path = DEFAULT_REPORT_PATH,
    csv_path: Path = DEFAULT_CSV_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(result, csv_path)
    counts = result.counts_by_group()
    lines = [
        "# Recipe Content Audit Round 2",
        "",
        "Audit-only stage. The script reads curated JSON data and writes findings only; it does not change recipe/data content.",
        "",
        "## Summary",
        "",
        f"- total recipes checked: {result.recipes_checked}",
        f"- total ingredients checked: {result.ingredients_checked}",
        f"- total foods checked: {result.foods_checked}",
        f"- total nutrition rows checked: {result.nutrition_rows_checked}",
        f"- blocking findings count: {len(result.blockers)}",
        f"- warning findings count: {len(result.warnings)}",
        f"- full CSV findings: `{_relative(csv_path)}`",
        "",
        "## Counts By Finding Type",
        "",
        "| finding type | blockers | warnings | total |",
        "|---|---:|---:|---:|",
    ]
    for group in FINDING_GROUPS:
        blockers = counts.get(group, Counter()).get("blocker", 0)
        warnings = counts.get(group, Counter()).get("warning", 0)
        lines.append(f"| {GROUP_LABELS[group]} | {blockers} | {warnings} | {blockers + warnings} |")

    lines.extend(["", "## Known Blocker Search Summary", ""])
    for name, count in result.known_search_counts.items():
        lines.append(f"- `{name}` hits across curated recipes/ingredients/foods: {count}")

    lines.extend(["", "## Required Top-Blocker Triage", ""])
    lines.append(_triage_line("hummus recipe", result, "hummus", "title/ingredient and step-missing hummus checks"))
    lines.append(_triage_line("harissa recipe", result, "harissa", "harissa known-search/non-CIS checks"))
    lines.append(_triage_line("broken step fragments", result, "fragment", "empty/short/standalone fragment checks"))
    severe_title_blockers = [
        issue for issue in result.blockers if issue.group == "title_ingredient_mismatch"
    ]
    title_warnings = [
        issue for issue in result.warnings if issue.group == "title_ingredient_mismatch"
    ]
    lines.append(
        "- severe title/ingredient mismatch: "
        f"{len(severe_title_blockers)} blockers, {len(title_warnings)} warnings."
    )

    lines.extend(["", "## Top Blockers Requiring Next-Stage Fix", ""])
    if result.blockers:
        for issue in result.blockers[:10]:
            lines.append(issue.markdown_line())
    else:
        lines.append("- none")

    lines.extend(["", "## Findings By Type", ""])
    for group in FINDING_GROUPS:
        group_issues = [issue for issue in result.issues if issue.group == group]
        lines.extend(["", f"### {GROUP_LABELS[group].title()}", ""])
        if not group_issues:
            lines.append("- none")
            continue
        for issue in group_issues[:120]:
            lines.append(issue.markdown_line())
        if len(group_issues) > 120:
            lines.append(f"- ... {len(group_issues) - 120} additional findings are in the CSV.")

    lines.extend(
        [
            "",
            "## Notes For Fix Stage",
            "",
            "- Hummus/title consistency is audited separately from recipes that make hummus from chickpeas/tahini.",
            "- Harissa, edamame, and American-cheese checks distinguish user-facing recipe content from internal IDs/catalog rows.",
            "- Missing approximate measures are warnings, not fixes; this report only identifies gram-only rows that are awkward for users.",
        ]
    )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _triage_line(label: str, result: AuditResult, needle: str, scope: str) -> str:
    needle_norm = needle.lower()
    blocker_count = sum(1 for issue in result.blockers if needle_norm in issue.code.lower() or needle_norm in issue.message.lower())
    warning_count = sum(1 for issue in result.warnings if needle_norm in issue.code.lower() or needle_norm in issue.message.lower())
    if blocker_count:
        return f"- {label}: {_count_label(blocker_count, 'blocker')}, {_count_label(warning_count, 'warning')} in {scope}."
    return f"- {label}: no blockers, {_count_label(warning_count, 'warning')} in {scope}."


def _count_label(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def _write_csv(result: AuditResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "severity",
                "group",
                "code",
                "recipe_no",
                "recipe_id",
                "title",
                "line_index",
                "food_id",
                "message",
                "evidence",
                "recommendation",
            ],
        )
        writer.writeheader()
        for issue in result.issues:
            writer.writerow(
                {
                    "severity": issue.severity,
                    "group": issue.group,
                    "code": issue.code,
                    "recipe_no": issue.recipe_no or "",
                    "recipe_id": issue.recipe_id,
                    "title": issue.title,
                    "line_index": issue.line_index or "",
                    "food_id": issue.food_id,
                    "message": issue.message,
                    "evidence": issue.evidence,
                    "recommendation": issue.recommendation,
                }
            )


def _audit_recipe(
    recipe: dict[str, Any],
    rows: list[dict[str, Any]],
    food_by_id: dict[str, dict[str, Any]],
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    recipe_id = str(recipe.get("recipe_id") or "")
    title = str(recipe.get("title_ru") or "")
    instructions = str(recipe.get("instructions_ru") or "")
    recipe_blob = "\n".join([recipe_id, title, instructions])
    row_blob = "\n".join(
        str(row.get(key) or "")
        for row in rows
        for key in ("raw_text", "ingredient_name_ru", "quantity_text", "food_id")
    )

    if not instructions.strip():
        issues.append(
            _issue(
                "blocker",
                "truncation_fragments",
                "empty_instructions",
                recipe,
                "instructions are empty",
            )
        )
    elif len(_words(instructions)) < 5:
        issues.append(
            _issue(
                "blocker",
                "truncation_fragments",
                "short_broken_step",
                recipe,
                "instructions are too short to be a complete recipe",
                evidence=_shorten(instructions),
            )
        )

    for code, pattern, message in BROKEN_TEXT_PATTERNS:
        if pattern.search(recipe_blob):
            issues.append(
                _issue(
                    "blocker",
                    "truncation_fragments",
                    "broken_step_fragment",
                    recipe,
                    message,
                    evidence=_shorten(pattern.search(recipe_blob).group(0) if pattern.search(recipe_blob) else ""),
                )
            )

    for fragment in _broken_sentence_fragments(instructions):
        issues.append(
            _issue(
                "blocker",
                "truncation_fragments",
                "short_broken_step",
                recipe,
                "instruction contains an empty/short standalone fragment",
                evidence=fragment,
            )
        )

    if instructions.strip() and not instructions.strip().endswith((".", "!", "?")):
        issues.append(
            _issue(
                "warning",
                "truncation_fragments",
                "missing_final_punctuation",
                recipe,
                "recipe does not end with sentence punctuation",
                evidence=_shorten(instructions[-120:]),
            )
        )

    if not _ends_like_serving_result(instructions):
        issues.append(
            _issue(
                "warning",
                "truncation_fragments",
                "weak_serving_finish",
                recipe,
                "last instruction sentence does not clearly finish with serving/ready wording",
                evidence=_shorten(_last_sentence(instructions)),
            )
        )

    for name, pattern in USER_FACING_NON_CIS_PATTERNS:
        if pattern.search("\n".join([title, instructions, row_blob])):
            issues.append(
                _issue(
                    "blocker",
                    "non_cis_unclear_ingredients",
                    f"user_facing_{name}",
                    recipe,
                    f"user-facing recipe text still contains `{name}` term",
                    evidence=_shorten(_first_match_context(pattern, "\n".join([title, instructions, row_blob]))),
                )
            )

    food_ids = {str(row.get("food_id") or "") for row in rows}
    title_norm = _norm(title)
    if "хумус" in title_norm and "hummus" not in food_ids and not _recipe_makes_hummus(rows, instructions):
        issues.append(
            _issue(
                "blocker",
                "title_ingredient_mismatch",
                "title_hummus_missing",
                recipe,
                "title says hummus, but ingredient rows do not include hummus and steps do not clearly make hummus",
                evidence=title,
            )
        )

    if "соба" in title_norm and "soba_noodles" not in food_ids:
        issues.append(
            _issue(
                "blocker",
                "title_ingredient_mismatch",
                "title_soba_missing",
                recipe,
                "title says soba, but ingredient rows do not include soba noodles",
                evidence=title,
            )
        )

    for row in rows:
        grams = _float(row.get("grams"))
        food_id = str(row.get("food_id") or "")
        if grams is None:
            continue
        if grams == 0 and not _looks_intentional_zero(row):
            issues.append(
                _issue_for_row(
                    "blocker" if _is_primary_food(food_id, food_by_id) else "warning",
                    "tiny_gram_anomalies",
                    "zero_primary_quantity" if _is_primary_food(food_id, food_by_id) else "zero_quantity",
                    recipe,
                    row,
                    f"`{food_id}` has 0 g without an obvious intentional marker",
                    evidence=str(row.get("raw_text") or ""),
                )
            )
        if 0 < grams <= 3 and _is_tiny_suspicious(food_id, row, recipe, food_by_id):
            code = "tiny_peanut_paste" if food_id == "peanut_butter" else "tiny_primary_quantity"
            issues.append(
                _issue_for_row(
                    "blocker" if food_id == "peanut_butter" or _title_mentions_row(recipe, row) else "warning",
                    "tiny_gram_anomalies",
                    code,
                    recipe,
                    row,
                    f"`{food_id}` has suspiciously tiny quantity {grams:g} g",
                    evidence=str(row.get("raw_text") or ""),
                )
            )

    return issues


def _audit_title_terms(recipe: dict[str, Any], rows: list[dict[str, Any]]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    title = str(recipe.get("title_ru") or "")
    instructions = str(recipe.get("instructions_ru") or "")
    title_norm = _norm(title)
    food_ids = {str(row.get("food_id") or "") for row in rows}
    row_text_norm = _norm(
        "\n".join(
            str(row.get(key) or "")
            for row in rows
            for key in ("raw_text", "ingredient_name_ru", "food_id")
        )
    )

    for name, title_terms, expected_food_ids, severe in TITLE_RULES:
        if not _any_alias_in_text(title_norm, title_terms):
            continue
        if any(food_id in food_ids for food_id in expected_food_ids):
            continue
        if _any_alias_in_text(row_text_norm, title_terms):
            continue
        if name == "hummus" and _recipe_makes_hummus(rows, instructions):
            continue
        severity = "blocker" if severe else "warning"
        issues.append(
            _issue(
                severity,
                "title_ingredient_mismatch",
                "title_term_missing",
                recipe,
                f"title contains `{name}`, but expected ingredient/clear preparation was not found",
                evidence=title,
            )
        )
    return issues


def _audit_ingredient_usage(
    recipe: dict[str, Any],
    rows: list[dict[str, Any]],
    food_by_id: dict[str, dict[str, Any]],
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    instructions = str(recipe.get("instructions_ru") or "")
    instructions_norm = _norm(instructions)
    for row in rows:
        food_id = str(row.get("food_id") or "")
        grams = _float(row.get("grams")) or 0.0
        if food_id in IGNORED_USAGE_FOOD_IDS or grams <= 0:
            continue
        if _is_serving_or_garnish(row):
            continue
        aliases = _row_aliases(row, food_by_id)
        if not aliases:
            continue
        if _any_alias_in_text(instructions_norm, aliases):
            continue
        severity = "blocker" if food_id in {"hummus", "soba_noodles", "harissa", "edamame", "american_cheese"} else "warning"
        issues.append(
            _issue_for_row(
                severity,
                "ingredient_missing_from_steps",
                "ingredient_not_named_in_steps",
                recipe,
                row,
                f"`{food_id}` is in ingredients but not found in instructions by known aliases",
                evidence=str(row.get("raw_text") or ""),
            )
        )
    return issues


def _audit_steps_missing_ingredients(recipe: dict[str, Any], rows: list[dict[str, Any]]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    instructions = str(recipe.get("instructions_ru") or "")
    instructions_norm = _norm(instructions)
    food_ids = {str(row.get("food_id") or "") for row in rows}
    row_text_norm = _norm(
        "\n".join(
            str(row.get(key) or "")
            for row in rows
            for key in ("raw_text", "ingredient_name_ru", "food_id")
        )
    )

    for name, aliases, expected_food_ids, severe in STEP_TERMS:
        if not _any_alias_in_text(instructions_norm, aliases):
            continue
        if any(food_id in food_ids for food_id in expected_food_ids):
            continue
        if _any_alias_in_text(row_text_norm, aliases):
            continue
        if name == "hummus" and _recipe_makes_hummus(rows, instructions):
            continue
        issues.append(
            _issue(
                "blocker" if severe else "warning",
                "steps_mention_missing_ingredient",
                f"step_mentions_missing_{name}",
                recipe,
                f"instructions mention `{name}`, but ingredient rows do not contain the expected item",
                evidence=_shorten(_first_alias_context(instructions, aliases)),
            )
        )
    return issues


def _audit_ingredient_rows(
    ingredients: list[dict[str, Any]],
    recipe_by_id: dict[str, dict[str, Any]],
    food_by_id: dict[str, dict[str, Any]],
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for row in ingredients:
        recipe = recipe_by_id.get(str(row.get("recipe_id") or ""))
        if recipe is None:
            continue

        food_id = str(row.get("food_id") or "")
        raw_blob = "\n".join(str(row.get(key) or "") for key in ("raw_text", "ingredient_name_ru", "quantity_text", "food_id"))

        if food_id in {"harissa", "edamame"}:
            issues.append(
                _issue_for_row(
                    "blocker",
                    "non_cis_unclear_ingredients",
                    f"food_id_{food_id}",
                    recipe,
                    row,
                    f"ingredient row still maps to `{food_id}`",
                    evidence=str(row.get("raw_text") or ""),
                )
            )
        elif food_id == "american_cheese":
            issues.append(
                _issue_for_row(
                    "warning",
                    "non_cis_unclear_ingredients",
                    "internal_american_cheese_id",
                    recipe,
                    row,
                    "ingredient row uses internal `american_cheese` id; verify user-facing wording stays CIS-friendly",
                    evidence=str(row.get("raw_text") or ""),
                )
            )

        for name, pattern in USER_FACING_NON_CIS_PATTERNS:
            if pattern.search(raw_blob):
                issues.append(
                    _issue_for_row(
                        "blocker",
                        "non_cis_unclear_ingredients",
                        f"user_facing_{name}_ingredient",
                        recipe,
                        row,
                        f"ingredient row still contains user-facing `{name}` term",
                        evidence=_shorten(_first_match_context(pattern, raw_blob)),
                    )
                )

        if _requires_approximate_measure(row, food_by_id) and _missing_approximate_measure(row):
            issues.append(
                _issue_for_row(
                    "warning",
                    "missing_approximate_measures",
                    "gram_only_user_hostile_measure",
                    recipe,
                    row,
                    "gram-only ingredient should get an approximate household measure in the fix stage",
                    evidence=str(row.get("raw_text") or ""),
                    recommendation="Add an approximate measure only after product/content review.",
                )
            )
    return issues


def _audit_food_catalog(foods: list[dict[str, Any]]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for row in foods:
        food_id = str(row.get("food_id") or "")
        blob = "\n".join(str(row.get(key) or "") for key in ("food_id", "name_ru", "name_en", "source_description"))
        if food_id in {"harissa", "edamame"}:
            issues.append(
                AuditIssue(
                    severity="warning",
                    group="non_cis_unclear_ingredients",
                    code=f"food_catalog_{food_id}",
                    recipe_no=None,
                    recipe_id="food_catalog",
                    title="curated_foods.json",
                    food_id=food_id,
                    message=f"food catalog still contains `{food_id}`; verify it is not user-facing or selected",
                    evidence=_shorten(blob),
                )
            )
        elif food_id == "american_cheese":
            issues.append(
                AuditIssue(
                    severity="warning",
                    group="non_cis_unclear_ingredients",
                    code="food_catalog_american_cheese",
                    recipe_no=None,
                    recipe_id="food_catalog",
                    title="curated_foods.json",
                    food_id=food_id,
                    message="food catalog keeps internal `american_cheese` id with CIS-friendly Russian name",
                    evidence=_shorten(blob),
                )
            )
    return issues


def _known_search_counts(
    recipes: list[dict[str, Any]],
    ingredients: list[dict[str, Any]],
    foods: list[dict[str, Any]],
) -> dict[str, int]:
    blobs: list[str] = []
    for row in recipes:
        blobs.append("\n".join(str(row.get(key) or "") for key in ("recipe_id", "title_ru", "instructions_ru", "image_url")))
    for row in ingredients:
        blobs.append("\n".join(str(row.get(key) or "") for key in ("recipe_id", "raw_text", "ingredient_name_ru", "quantity_text", "food_id")))
    for row in foods:
        blobs.append("\n".join(str(row.get(key) or "") for key in ("food_id", "name_ru", "name_en", "source_description")))
    text = "\n".join(blobs)
    return {name: len(pattern.findall(text)) for name, pattern in KNOWN_SEARCH_PATTERNS}


def _recipe_makes_hummus(rows: list[dict[str, Any]], instructions: str) -> bool:
    food_ids = {str(row.get("food_id") or "") for row in rows}
    text = _norm(
        instructions
        + "\n"
        + "\n".join(str(row.get(key) or "") for row in rows for key in ("raw_text", "ingredient_name_ru"))
    )
    has_chickpea_base = "chickpeas" in food_ids or "нут" in text
    has_hummus_flavor_base = "tahini" in food_ids or "тахини" in text or ("лимон" in text and "чеснок" in text)
    has_blending = any(word in text for word in ("измельч", "взбей", "блендер", "комбайн", "пюре", "паста"))
    return has_chickpea_base and has_hummus_flavor_base and has_blending


def _broken_sentence_fragments(instructions: str) -> list[str]:
    normalized = instructions.strip()
    if not normalized:
        return []
    protected = (
        normalized.replace("ст. л.", "ст_л")
        .replace("ч. л.", "ч_л")
        .replace("°C", "C")
        .replace("°С", "C")
    )
    fragments: list[str] = []
    for part in re.split(r"[.!?]+", protected):
        part = part.replace("ст_л", "ст. л.").replace("ч_л", "ч. л.").strip()
        if not part:
            continue
        words = _words(part)
        if len(words) <= 1 and len(part) <= 12:
            fragments.append(part)
        if re.fullmatch(r"\d+(?:[,.]\d+)?\s*(?:ст|ч|л|г|мл)\.?", part, re.IGNORECASE):
            fragments.append(part)
    return fragments


def _row_aliases(row: dict[str, Any], food_by_id: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    food_id = str(row.get("food_id") or "")
    aliases: list[str] = list(MANUAL_FOOD_ALIASES.get(food_id, ()))
    ingredient_name = str(row.get("ingredient_name_ru") or "").strip()
    if ingredient_name:
        aliases.append(ingredient_name)
    raw_name = str(row.get("raw_text") or "").split("—", 1)[0].strip()
    if raw_name:
        aliases.append(raw_name)
    food = food_by_id.get(food_id)
    if food is not None and food.get("name_ru"):
        aliases.append(str(food["name_ru"]))
    return tuple(_clean_alias(alias) for alias in aliases if _clean_alias(alias))


def _clean_alias(alias: str) -> str:
    alias = re.sub(r"\([^)]*\)", " ", alias)
    alias = re.sub(r"\b(?:нарезать|измельчить|натереть|сверху|приготовить|порубить)\b", " ", alias, flags=re.IGNORECASE)
    alias = " ".join(_words(alias))
    if len(alias) < 3:
        return ""
    return alias


def _requires_approximate_measure(row: dict[str, Any], food_by_id: dict[str, dict[str, Any]]) -> bool:
    food_id = str(row.get("food_id") or "")
    if food_id in APPROX_FOOD_IDS:
        return True
    food = food_by_id.get(food_id, {})
    category = str(food.get("category") or "")
    name_blob = _norm(" ".join(str(row.get(key) or "") for key in ("raw_text", "ingredient_name_ru", "food_id")))
    if category == "cheese":
        return True
    return any(word in name_blob for word in ("чеснок", "финик", "орех", "сыр", "соус", "паста", "майонез", "уксус", "соевый соус", "кунжутное масло"))


def _missing_approximate_measure(row: dict[str, Any]) -> bool:
    quantity = str(row.get("quantity_text") or "")
    raw = str(row.get("raw_text") or "")
    text = _norm(f"{quantity} {raw}")
    if any(marker in text for marker in HOUSEHOLD_MEASURE_MARKERS):
        return False
    return bool(re.search(r"(?:^|[\s/])\d+(?:[,.]\d+)?\s*г(?:\s|$)", text))


def _is_tiny_suspicious(
    food_id: str,
    row: dict[str, Any],
    recipe: dict[str, Any],
    food_by_id: dict[str, dict[str, Any]],
) -> bool:
    if food_id in IGNORED_USAGE_FOOD_IDS:
        return False
    if food_id == "garlic":
        return False
    if food_id in NUT_OR_PASTE_FOOD_IDS | SAUCE_FOOD_IDS:
        return _missing_approximate_measure(row)
    if _title_mentions_row(recipe, row) and _is_primary_food(food_id, food_by_id):
        return True
    return False


def _is_primary_food(food_id: str, food_by_id: dict[str, dict[str, Any]]) -> bool:
    if any(part in food_id for part in PRIMARY_FOOD_ID_PARTS):
        return True
    food = food_by_id.get(food_id, {})
    category = str(food.get("category") or "")
    return category in {"protein", "grain", "starch", "cheese", "legume"}


def _title_mentions_row(recipe: dict[str, Any], row: dict[str, Any]) -> bool:
    title = _norm(str(recipe.get("title_ru") or ""))
    food_id = str(row.get("food_id") or "")
    aliases = MANUAL_FOOD_ALIASES.get(food_id, ())
    return _any_alias_in_text(title, aliases)


def _is_serving_or_garnish(row: dict[str, Any]) -> bool:
    text = _norm(" ".join(str(row.get(key) or "") for key in ("raw_text", "quantity_text", "conversion_note")))
    return any(marker in text for marker in SERVING_OR_GARNISH_MARKERS)


def _looks_intentional_zero(row: dict[str, Any]) -> bool:
    text = _norm(" ".join(str(row.get(key) or "") for key in ("raw_text", "quantity_text", "conversion_note")))
    return any(marker in text for marker in INTENTIONAL_ZERO_MARKERS)


def _ends_like_serving_result(instructions: str) -> bool:
    sentence = _norm(_last_sentence(instructions))
    if not sentence:
        return False
    finish_words = (
        "пода",
        "готов",
        "посып",
        "полей",
        "разлож",
        "сразу",
        "остуд",
        "нареж",
        "укрась",
        "сверн",
        "перелож",
        "разреж",
        "сним",
        "запекайте",
        "обжарьте",
    )
    return any(word in sentence for word in finish_words)


def _last_sentence(text: str) -> str:
    parts = [part.strip() for part in re.split(r"[.!?]+", text.strip()) if part.strip()]
    return parts[-1] if parts else ""


def _any_alias_in_text(text_norm: str, aliases: Iterable[str]) -> bool:
    text_words = _words(text_norm)
    text_word_set = set(text_words)
    text_stems = {_stem(word) for word in text_words}
    for alias in aliases:
        alias_norm = _norm(alias)
        if not alias_norm or len(alias_norm) < 3:
            continue
        alias_words = _words(alias_norm)
        if not alias_words:
            continue
        if len(alias_words) > 1:
            if alias_norm in text_norm:
                return True
            stems = [_stem(word) for word in alias_words if len(_stem(word)) >= 3]
            if len(stems) == len(alias_words) and all(stem in text_stems for stem in stems):
                return True
        if len(alias_words) == 1:
            word = alias_words[0]
            stem = _stem(word)
            if word in text_word_set or stem in text_stems:
                return True
    return False


def _first_alias_context(text: str, aliases: Iterable[str]) -> str:
    text_norm = _norm(text)
    for alias in aliases:
        alias_norm = _norm(alias)
        index = text_norm.find(alias_norm)
        if index >= 0:
            return _shorten(text[max(0, index - 60) : index + len(alias) + 80])
    return _shorten(text)


def _first_match_context(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    if match is None:
        return ""
    start, end = match.span()
    return text[max(0, start - 60) : min(len(text), end + 80)]


def _norm(text: str) -> str:
    text = str(text).lower().replace("ё", "е")
    text = text.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zа-яе]+", _norm(text))


def _stem(word: str) -> str:
    word = _norm(word)
    for suffix in (
        "иями",
        "ями",
        "ами",
        "ого",
        "ему",
        "ыми",
        "ими",
        "ая",
        "яя",
        "ое",
        "ее",
        "ые",
        "ие",
        "ый",
        "ий",
        "ой",
        "ей",
        "ом",
        "ем",
        "ам",
        "ям",
        "ах",
        "ях",
        "ов",
        "ев",
        "ам",
        "ям",
        "а",
        "я",
        "ы",
        "и",
        "у",
        "ю",
        "е",
    ):
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _issue(
    severity: str,
    group: str,
    code: str,
    recipe: dict[str, Any],
    message: str,
    evidence: str = "",
    recommendation: str = "",
) -> AuditIssue:
    return AuditIssue(
        severity=severity,
        group=group,
        code=code,
        recipe_no=_optional_int(recipe.get("recipe_no")),
        recipe_id=str(recipe.get("recipe_id") or ""),
        title=str(recipe.get("title_ru") or ""),
        message=message,
        evidence=_shorten(evidence),
        recommendation=recommendation,
    )


def _issue_for_row(
    severity: str,
    group: str,
    code: str,
    recipe: dict[str, Any],
    row: dict[str, Any],
    message: str,
    evidence: str = "",
    recommendation: str = "",
) -> AuditIssue:
    return AuditIssue(
        severity=severity,
        group=group,
        code=code,
        recipe_no=_optional_int(recipe.get("recipe_no")),
        recipe_id=str(recipe.get("recipe_id") or ""),
        title=str(recipe.get("title_ru") or ""),
        food_id=str(row.get("food_id") or ""),
        line_index=_optional_int(row.get("line_index")),
        message=message,
        evidence=_shorten(evidence),
        recommendation=recommendation,
    )


def _dedupe_issues(issues: list[AuditIssue]) -> list[AuditIssue]:
    seen = set()
    unique = []
    for issue in issues:
        key = (
            issue.severity,
            issue.group,
            issue.code,
            issue.recipe_id,
            issue.line_index,
            issue.food_id,
            issue.message,
            issue.evidence,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def _load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _shorten(text: str, max_len: int = 220) -> str:
    text = " ".join(str(text).split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit curated recipe content for Round 2 QA findings.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--csv-path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--fail-on-blocker", action="store_true", help="Exit nonzero when blocker findings exist.")
    args = parser.parse_args()

    result = run_audit(args.data_dir)
    if not args.no_write_report:
        write_report(result, args.report_path, args.csv_path)

    counts = result.counts_by_group()
    print(f"recipes_checked={result.recipes_checked}")
    print(f"ingredients_checked={result.ingredients_checked}")
    print(f"foods_checked={result.foods_checked}")
    print(f"nutrition_rows_checked={result.nutrition_rows_checked}")
    print(f"blocking_findings={len(result.blockers)}")
    print(f"warning_findings={len(result.warnings)}")
    for group in FINDING_GROUPS:
        group_counts = counts.get(group, Counter())
        print(
            f"{group}.blockers={group_counts.get('blocker', 0)} "
            f"{group}.warnings={group_counts.get('warning', 0)}"
        )
    if result.blockers:
        print("top_blockers:")
        for issue in result.blockers[:10]:
            print(issue.markdown_line())

    if args.fail_on_blocker and result.blockers:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
