from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .chef import clean_recipe_instruction_text
from .domain import Food, MealRole, NutrientVector


DATA_DIR = Path(__file__).with_name("data")
NUTRIENT_FIELDS = (
    "energy_kcal",
    "protein_g",
    "fat_g",
    "saturated_fat_g",
    "carbohydrate_g",
    "fiber_g",
    "sugar_g",
    "added_sugar_g",
    "sodium_mg",
    "potassium_mg",
    "calcium_mg",
    "magnesium_mg",
    "iron_mg",
    "zinc_mg",
    "iodine_mcg",
    "selenium_mcg",
    "phosphorus_mg",
    "vitamin_c_mg",
    "vitamin_d_mcg",
    "vitamin_b12_mcg",
    "folate_mcg_dfe",
    "vitamin_b1_mg",
    "vitamin_b2_mg",
    "vitamin_b3_mg",
    "vitamin_b6_mg",
    "vitamin_a_mcg_rae",
    "vitamin_e_mg",
    "vitamin_k_mcg",
    "omega_3_mg",
)
INCOMPLETE_INSTRUCTION_END_RE = re.compile(
    r"(?:\b(?:и|в|с|на|до)\.?|(?:ст|ч)\.?(?:\s*л\.?)?|\bполобульон\w*)\s*$",
    re.IGNORECASE,
)
INSTRUCTION_FIXES_BY_RECIPE_ID = {
    "r202_lanch_bouly_s_bulgurom_kinoa_avokado_i_svekloy": (
        "Положите в кастрюлю лук, смесь булгура и киноа, тимьян и овощной бульонный порошок. "
        "Влейте 600 мл воды, доведите до слабого кипения, накройте и готовьте 15 минут. "
        "Снимите с огня и оставьте крупу под крышкой на 10 минут. Удалите тимьян, посолите и поперчите. "
        "Смешайте авокадо, часть помидоров, базилик, оливки, немного оливкового масла и уксуса. "
        "Отдельно смешайте нут, свеклу, оставшиеся помидоры, мяту, кумин, корицу, оставшееся масло и уксус. "
        "Разложите крупу по мискам, добавьте рукколу, обе начинки, дольки апельсина и кедровые орехи."
    ),
    "r241_kurinye_fahitas_s_pertsem_i_salsoy": (
        "Разогрейте духовку до 200 °C, заверните тортильи в фольгу и прогрейте их 5 минут. "
        "В миске смешайте копченую паприку, кориандр, кумин, чеснок, оливковое масло, сок лайма, острый соус, соль и перец. "
        "Добавьте курицу, красный лук, сладкий перец и чили, перемешайте с маринадом. "
        "Обжарьте смесь на сильно разогретой сковороде 6-8 минут, пока курица не будет готова, а овощи слегка подрумянятся. "
        "Разложите курицу с овощами по теплым тортильям, добавьте листья салата и сальсу."
    ),
    "r269_myagkie_ovsyano_izyumnye_granola_batonchiki": (
        "Разогрейте духовку до 163 °C. Форму 20 см застелите пергаментом с выступающими краями. "
        "Смешайте овсяные хлопья, муку, корицу и соль. Добавьте растопленное кокосовое масло, ореховую пасту, мед, сахар и ваниль, "
        "перемешайте до липкой массы. Вмешайте изюм и рубленые орехи. Плотно утрамбуйте массу в форму и выпекайте 25-28 минут, "
        "пока края слегка не подрумянятся. Полностью остудите, уберите в холодильник примерно на 2 часа и нарежьте на батончики."
    ),
    "r215_zolotoy_karri_sup_iz_krasnoy_chechevitsy_s_kokosovym_m": (
        "Разогрейте кастрюлю на среднем огне, влейте воду и добавьте шалот или лук. "
        "Готовьте около 3 минут, часто помешивая, пока лук не размягчится. "
        "Добавьте чеснок, имбирь и серрано, готовьте еще 2-3 минуты. "
        "Вмешайте морковь и щепотку соли, прогрейте 1-2 минуты. "
        "Влейте овощной бульон и кокосовое молоко, добавьте чечевицу, тамари и порошок карри. "
        "Доведите до слабого кипения и варите 12-15 минут, пока морковь и чечевица не станут мягкими. "
        "При желании слегка пробейте часть супа погружным блендером, чтобы он стал гуще. "
        "Вмешайте лимонный сок, попробуйте соль и подавайте с кинзой и кокосовыми сливками."
    ),
    "r331_rzhanye_krekery_s_tykvennymi_semechkami": (
        "Разогрейте духовку до 140 °C, при конвекции до 120 °C, и застелите два противня пергаментом. "
        "Смешайте ржаную муку, цельнозерновую пшеничную муку, тыквенные семечки, разрыхлитель, соль и мелкий светлый сахар. "
        "В отдельной миске взбейте яйцо с водой, влейте к сухой смеси и замесите плотное тесто. "
        "Подпылите стол цельнозерновой мукой, вымесите тесто до гладкости и раскатайте очень тонким пластом. "
        "Переложите пласт на противень, нарежьте на крекеры, наколите вилкой и выпекайте 60-90 минут до сухого хруста. "
        "Остудите на решетке и храните в сухом контейнере."
    ),
    "r332_ovsyanye_lepeshki_krekery_s_makom_i_kunzhutom": (
        "Разогрейте духовку до 200 °C, при конвекции до 180 °C. Растопите сливочное масло и слегка остудите. "
        "Смешайте овсяную крупку, пшеничную муку, пищевую соду, мак, кунжут и соль. "
        "Влейте растопленное масло, затем постепенно добавьте кипяток и замесите мягкое тесто. "
        "Раскатайте тесто тонким пластом на присыпанной мукой поверхности, нарежьте на лепешки-крекеры и переложите на противень. "
        "Выпекайте 12-15 минут до золотистых краев, затем остудите на решетке."
    ),
}


def _load_json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _recipe_instruction(row: dict[str, Any]) -> str | None:
    recipe_id = str(row.get("recipe_id") or "")
    raw_text = INSTRUCTION_FIXES_BY_RECIPE_ID.get(recipe_id, str(row.get("instructions_ru") or ""))
    text = clean_recipe_instruction_text(raw_text)
    if _looks_incomplete_instruction(text):
        return None
    return text


def _looks_incomplete_instruction(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return bool(INCOMPLETE_INSTRUCTION_END_RE.search(stripped))


def _role(value: str) -> MealRole | None:
    try:
        return MealRole(value)
    except ValueError:
        return None


@lru_cache(maxsize=1)
def curated_foods() -> tuple[Food, ...]:
    foods: list[Food] = []
    for row in _load_json("curated_foods.json"):
        roles = frozenset(role for value in row.get("roles", ()) if (role := _role(value)) is not None)
        nutrients = {
            key: float(row.get("nutrients_per_100g", {}).get(key, 0.0))
            for key in NUTRIENT_FIELDS
        }
        foods.append(
            Food(
                id=str(row["food_id"]),
                name=str(row["name_ru"]),
                category=str(row["category"]),
                tags=frozenset(row.get("tags", ())),
                roles=roles,
                max_per_meal_g=float(row.get("max_per_meal_g", 250)),
                max_per_day_g=float(row.get("max_per_day_g", 400)),
                nutrients_per_100g=NutrientVector(nutrients),
            )
        )
    return tuple(foods)


@lru_cache(maxsize=1)
def curated_recipes():
    from .recipe_catalog import RecipeTemplate

    recipes = _load_json("curated_recipes.json")
    ingredients = _load_json("curated_recipe_ingredients.json")
    nutrition = _load_json("curated_recipe_nutrition.json")

    ok_recipe_ids = {
        row["recipe_id"]
        for row in nutrition
        if row.get("calculation_status") == "ok"
    }
    ingredients_by_recipe: dict[str, dict[str, float]] = {}
    for row in ingredients:
        recipe_id = row.get("recipe_id")
        food_id = row.get("food_id")
        grams = row.get("grams")
        if recipe_id not in ok_recipe_ids or not food_id or grams is None:
            continue
        ingredients_by_recipe.setdefault(recipe_id, {})
        ingredients_by_recipe[recipe_id][food_id] = ingredients_by_recipe[recipe_id].get(food_id, 0.0) + float(grams)

    templates = []
    for row in recipes:
        recipe_id = row["recipe_id"]
        recipe_ingredients = ingredients_by_recipe.get(recipe_id)
        if not recipe_ingredients:
            continue
        instructions = _recipe_instruction(row)
        if instructions is None:
            continue
        source_name = str(row.get("source_name") or "").strip()
        tags = {"curated", f"source:{source_name}"} if source_name else {"curated"}
        templates.append(
            RecipeTemplate(
                id=recipe_id,
                slot=str(row["slot"]),
                title=str(row["title_ru"]),
                ingredients_g={key: round(value, 2) for key, value in recipe_ingredients.items() if value > 0},
                instructions=instructions,
                time_text=str(row.get("time_text") or ""),
                tags=frozenset(tags),
                image_url=str(row.get("image_url") or "") or None,
                image_attribution=str(row.get("image_attribution") or "") or None,
                source_url=str(row.get("source_url") or "") or None,
            )
        )
    return tuple(templates)
