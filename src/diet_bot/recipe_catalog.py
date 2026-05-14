from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


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


COMMONS_IMAGES: dict[str, dict[str, str]] = {
    "oatmeal": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8c/Child_Care_Recipes_%28Team_Nutiriton%29_%2820230123-FNS-UNK-018%29.jpg/960px-Child_Care_Recipes_%28Team_Nutiriton%29_%2820230123-FNS-UNK-018%29.jpg",
        "image_attribution": "USDAgov, Public domain, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Child_Care_Recipes_(Team_Nutiriton)_(20230123-FNS-UNK-018).jpg",
    },
    "egg": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e3/Omlette-fold.jpg/960px-Omlette-fold.jpg",
        "image_attribution": "Masoud Shafaee, CC BY-SA 3.0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Omlette-fold.jpg",
    },
    "egg_roll": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/24/Avocado_%26_Egg_Breakfast_Bap_-_Finch_2026-04-29.jpg/960px-Avocado_%26_Egg_Breakfast_Bap_-_Finch_2026-04-29.jpg",
        "image_attribution": "Andy Li, CC0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Avocado_&_Egg_Breakfast_Bap_-_Finch_2026-04-29.jpg",
    },
    "quinoa": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ed/Vegan_Quinoa_Bowl_%2844040185371%29.jpg/960px-Vegan_Quinoa_Bowl_%2844040185371%29.jpg",
        "image_attribution": "Ella Olsson, CC BY 2.0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Vegan_Quinoa_Bowl_(44040185371).jpg",
    },
    "salmon": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/54/Salmon%2C_tomato%2C_mashed_potato%2C_broccoli%2C_mushrooms%2C_and_corn_-_Massachusetts.jpg/960px-Salmon%2C_tomato%2C_mashed_potato%2C_broccoli%2C_mushrooms%2C_and_corn_-_Massachusetts.jpg",
        "image_attribution": "Daderot, CC0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Salmon,_tomato,_mashed_potato,_broccoli,_mushrooms,_and_corn_-_Massachusetts.jpg",
    },
    "shakshuka": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/26/Shakshuka1.jpg/960px-Shakshuka1.jpg",
        "image_attribution": "Joe Mahoney, CC BY 2.0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Shakshuka1.jpg",
    },
    "tuna": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6d/Tuna_olive_and_avocado_sandwich.jpg/960px-Tuna_olive_and_avocado_sandwich.jpg",
        "image_attribution": "Richard Masoner, CC BY-SA 2.0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Tuna_olive_and_avocado_sandwich.jpg",
    },
    "yogurt": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/Berry_Frozen_Yogurt_%284723048814%29.jpg/960px-Berry_Frozen_Yogurt_%284723048814%29.jpg",
        "image_attribution": "Katie Munoz, CC BY-SA 2.0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Berry_Frozen_Yogurt_(4723048814).jpg",
    },
    "avocado_toast": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/18/Avocado_toast_at_the_girl_%26_the_fig_-_Sarah_Stierch.jpg/960px-Avocado_toast_at_the_girl_%26_the_fig_-_Sarah_Stierch.jpg",
        "image_attribution": "Sarah Stierch, CC BY 4.0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Avocado_toast_at_the_girl_&_the_fig_-_Sarah_Stierch.jpg",
    },
    "tofu_rice": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b3/Stir_fried_Vegetable_Tofu_broken_with_rice_for_dinner.jpg/960px-Stir_fried_Vegetable_Tofu_broken_with_rice_for_dinner.jpg",
        "image_attribution": "Pradeepraajkumar1981, CC BY-SA 4.0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Stir_fried_Vegetable_Tofu_broken_with_rice_for_dinner.jpg",
    },
    "pasta": {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/63/Baked_chicken_steak_pasta_with_tomato_sauce.jpg/960px-Baked_chicken_steak_pasta_with_tomato_sauce.jpg",
        "image_attribution": "Apeach316, CC BY-SA 2.0, via Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Baked_chicken_steak_pasta_with_tomato_sauce.jpg",
    },
}


def img(key: str) -> dict[str, str]:
    return COMMONS_IMAGES.get(key, {})


@lru_cache(maxsize=1)
def built_in_recipes() -> tuple[RecipeTemplate, ...]:
    from .curated_data import curated_recipes

    return _dedupe_recipes(curated_recipes() + _manual_recipes() + _generated_recipes())


def _dedupe_recipes(recipes: tuple[RecipeTemplate, ...]) -> tuple[RecipeTemplate, ...]:
    seen_ids: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    seen_signatures: set[tuple[str, tuple[tuple[str, float], ...]]] = set()
    unique: list[RecipeTemplate] = []
    for recipe in recipes:
        title_key = (recipe.slot, recipe.title)
        signature = (recipe.slot, tuple(sorted(recipe.ingredients_g.items())))
        if recipe.id in seen_ids or title_key in seen_titles or signature in seen_signatures:
            continue
        seen_ids.add(recipe.id)
        seen_titles.add(title_key)
        seen_signatures.add(signature)
        unique.append(recipe)
    return tuple(unique)


def _manual_recipes() -> tuple[RecipeTemplate, ...]:
    return (
        RecipeTemplate(
            id="breakfast_oat_berry_bowl",
            slot="breakfast",
            title="Овсяная тарелка с йогуртом и ягодами",
            ingredients_g={"oats": 55, "greek_yogurt": 180, "berries": 120, "pumpkin_seeds": 10},
            instructions="Заварите овсянку горячей водой на 5 минут, затем добавьте йогурт, ягоды и немного семечек для хруста.",
            **img("oatmeal"),
        ),
        RecipeTemplate(
            id="breakfast_banana_oats",
            slot="breakfast",
            title="Банановая овсянка с йогуртом",
            ingredients_g={"oats": 60, "greek_yogurt": 170, "banana": 120, "pumpkin_seeds": 10},
            instructions="Сварите овсянку до мягкости, снимите с огня, добавьте йогурт и ломтики банана. Семечки посыпьте сверху.",
            **img("oatmeal"),
        ),
        RecipeTemplate(
            id="breakfast_omelet_tomato",
            slot="breakfast",
            title="Омлет с томатами и шпинатом",
            ingredients_g={"egg": 120, "tomato": 120, "spinach": 60, "whole_grain_bread": 50},
            instructions="Взбейте яйца, добавьте томаты и шпинат, готовьте на слабом огне под крышкой. Подавайте с тостом.",
            **img("egg"),
        ),
        RecipeTemplate(
            id="breakfast_scramble_avocado",
            slot="breakfast",
            title="Скрэмбл с авокадо",
            ingredients_g={"egg": 120, "avocado": 70, "tomato": 120, "whole_grain_bread": 50},
            instructions="Сделайте нежный скрэмбл на слабом огне, рядом положите ломтики авокадо и томата, добавьте тост.",
            **img("egg"),
        ),
        RecipeTemplate(
            id="breakfast_cottage_berries",
            slot="breakfast",
            title="Творожная тарелка с ягодами",
            ingredients_g={"cottage_cheese": 200, "berries": 150, "oats": 35, "pumpkin_seeds": 10},
            instructions="Смешайте творог с ягодами, сверху добавьте сухие овсяные хлопья или слегка подсушите их на сковороде.",
            **img("yogurt"),
        ),
        RecipeTemplate(
            id="breakfast_tortilla_egg_roll",
            slot="breakfast",
            title="Утренний ролл с яйцом",
            ingredients_g={"corn_tortilla": 70, "egg": 100, "tomato": 80, "spinach": 50, "avocado": 50},
            instructions="Приготовьте яйцо скрэмблом, выложите в тортилью с овощами и авокадо, сверните плотный ролл.",
            **img("egg_roll"),
        ),
        RecipeTemplate(
            id="breakfast_quinoa_yogurt",
            slot="breakfast",
            title="Киноа-тарелка с апельсином",
            ingredients_g={"quinoa": 50, "greek_yogurt": 170, "orange": 140, "pumpkin_seeds": 10},
            instructions="Отварите киноа заранее, утром смешайте с йогуртом и апельсином, посыпьте семечками.",
            **img("quinoa"),
        ),
        RecipeTemplate(
            id="lunch_chicken_buckwheat_salad",
            slot="main",
            title="Гречка с курицей и овощным салатом",
            ingredients_g={"chicken_breast": 150, "buckwheat": 70, "cucumber": 120, "tomato": 120, "olive_oil": 10},
            instructions="Курицу обжарьте или запеките, гречку сварите рассыпчатой. Огурец и томат нарежьте салатом, заправьте маслом.",
        ),
        RecipeTemplate(
            id="lunch_turkey_quinoa_bowl",
            slot="main",
            title="Тарелка с индейкой, киноа и перцем",
            ingredients_g={"turkey": 150, "quinoa": 65, "bell_pepper": 130, "cucumber": 100, "olive_oil": 10},
            instructions="Индейку приготовьте кусочками, киноа отварите. Соберите боул с перцем, огурцом и легкой масляной заправкой.",
            **img("quinoa"),
        ),
        RecipeTemplate(
            id="lunch_salmon_potato_broccoli",
            slot="main",
            title="Лосось с картофелем и брокколи",
            ingredients_g={"salmon": 150, "potato": 240, "broccoli": 160, "olive_oil": 10},
            instructions="Лосось запеките 12-15 минут, картофель отварите или запеките дольками, брокколи приготовьте до мягко-хрустящей текстуры.",
            **img("salmon"),
        ),
        RecipeTemplate(
            id="lunch_tuna_avocado_sandwich",
            slot="main",
            title="Сэндвич с тунцом и авокадо",
            ingredients_g={"tuna": 130, "whole_grain_bread": 90, "avocado": 70, "cucumber": 100, "tomato": 80},
            instructions="Разомните авокадо, выложите на хлеб с тунцом, огурцом и томатом. Получится плотный сэндвич без тяжелого соуса.",
            **img("tuna"),
        ),
        RecipeTemplate(
            id="lunch_lentil_tomato_stew",
            slot="main",
            title="Томатная чечевичная похлебка",
            ingredients_g={"lentils": 230, "tomato": 180, "bell_pepper": 100, "olive_oil": 10, "whole_grain_bread": 50},
            instructions="Прогрейте чечевицу с томатами и перцем 7-10 минут, добавьте масло в конце. Подавайте с кусочком хлеба.",
        ),
        RecipeTemplate(
            id="lunch_tofu_rice_bowl",
            slot="main",
            title="Рисовая тарелка с тофу и овощами",
            ingredients_g={"tofu": 180, "rice": 70, "broccoli": 140, "bell_pepper": 120, "olive_oil": 10},
            instructions="Рис отварите, тофу подрумяньте кубиками, овощи быстро прогрейте на сковороде и соберите все в боул.",
            **img("tofu_rice"),
        ),
        RecipeTemplate(
            id="lunch_chicken_pasta_tomato",
            slot="main",
            title="Паста с курицей и томатами",
            ingredients_g={"chicken_breast": 140, "whole_wheat_pasta": 75, "tomato": 180, "spinach": 60, "olive_oil": 10},
            instructions="Пасту отварите al dente, курицу приготовьте кусочками, затем быстро соедините с томатами, шпинатом и маслом.",
            **img("pasta"),
        ),
        RecipeTemplate(
            id="dinner_turkey_potato_salad",
            slot="main",
            title="Индейка с картофелем и свежим салатом",
            ingredients_g={"turkey": 150, "potato": 250, "cucumber": 140, "tomato": 120, "olive_oil": 10},
            instructions="Индейку запеките или обжарьте без панировки, картофель сделайте дольками, овощи нарежьте свежим салатом.",
        ),
        RecipeTemplate(
            id="dinner_salmon_quinoa",
            slot="main",
            title="Лосось с киноа и огуречным салатом",
            ingredients_g={"salmon": 150, "quinoa": 60, "cucumber": 150, "spinach": 50, "olive_oil": 10},
            instructions="Лосось запеките, киноа отварите. Огурец и шпинат смешайте с маслом и подайте рядом.",
            **img("salmon"),
        ),
        RecipeTemplate(
            id="dinner_egg_shakshuka",
            slot="main",
            title="Шакшука с цельнозерновым тостом",
            ingredients_g={"egg": 120, "tomato": 220, "bell_pepper": 120, "whole_grain_bread": 60, "olive_oil": 8},
            instructions="Потушите томаты и перец до соуса, сделайте углубления и вбейте яйца. Готовьте под крышкой, подавайте с тостом.",
            **img("shakshuka"),
        ),
        RecipeTemplate(
            id="dinner_tuna_potato_bowl",
            slot="main",
            title="Картофельная тарелка с тунцом",
            ingredients_g={"tuna": 130, "potato": 260, "cucumber": 120, "tomato": 120, "avocado": 60},
            instructions="Картофель отварите или запеките кубиками, добавьте тунец, овощи и авокадо. Это сытный, но простой ужин.",
            **img("tuna"),
        ),
        RecipeTemplate(
            id="snack_yogurt_berries",
            slot="snack",
            title="Йогурт с ягодами",
            ingredients_g={"greek_yogurt": 180, "berries": 120, "pumpkin_seeds": 10},
            instructions="Смешайте йогурт с ягодами и добавьте немного семечек сверху.",
            **img("yogurt"),
        ),
        RecipeTemplate(
            id="snack_cottage_orange",
            slot="snack",
            title="Творог с апельсином",
            ingredients_g={"cottage_cheese": 170, "orange": 140},
            instructions="Нарежьте апельсин, добавьте к творогу. Получается быстрый белковый перекус.",
        ),
        RecipeTemplate(
            id="snack_banana_yogurt",
            slot="snack",
            title="Банановый йогурт",
            ingredients_g={"greek_yogurt": 170, "banana": 120},
            instructions="Нарежьте банан в йогурт. Если хочется плотнее, можно оставить на 5 минут, чтобы банан дал сладость.",
            **img("yogurt"),
        ),
        RecipeTemplate(
            id="snack_avocado_toast",
            slot="snack",
            title="Тост с авокадо",
            ingredients_g={"whole_grain_bread": 60, "avocado": 60, "tomato": 80},
            instructions="Разомните авокадо на тосте, сверху положите томат. Это быстрый перекус с полезными жирами.",
            **img("avocado_toast"),
        ),
        RecipeTemplate(
            id="snack_egg_cucumber",
            slot="snack",
            title="Яйцо с огурцом и тостом",
            ingredients_g={"egg": 60, "cucumber": 120, "whole_grain_bread": 40},
            instructions="Отварите яйцо заранее, подайте с огурцом и небольшим тостом.",
        ),
    )


FOOD_TITLES = {
    "apple": "яблоком",
    "avocado": "авокадо",
    "banana": "бананом",
    "bell_pepper": "сладким перцем",
    "berries": "ягодами",
    "broccoli": "брокколи",
    "buckwheat": "гречкой",
    "chicken_breast": "курицей",
    "corn_tortilla": "кукурузной тортильей",
    "cottage_cheese": "творогом",
    "cucumber": "огурцом",
    "egg": "яйцом",
    "greek_yogurt": "греческим йогуртом",
    "lactose_free_cottage_cheese": "безлактозным творогом",
    "lactose_free_yogurt": "безлактозным йогуртом",
    "lentils": "чечевицей",
    "oats": "овсянкой",
    "olive_oil": "оливковым маслом",
    "orange": "апельсином",
    "potato": "картофелем",
    "pumpkin_seeds": "тыквенными семечками",
    "quinoa": "киноа",
    "rice": "рисом",
    "salmon": "лососем",
    "spinach": "шпинатом",
    "tofu": "тофу",
    "tomato": "томатами",
    "tuna": "тунцом",
    "turkey": "индейкой",
    "whole_grain_bread": "цельнозерновым тостом",
    "whole_wheat_pasta": "цельнозерновой пастой",
}

FOOD_ACCUSATIVE = {
    "apple": "яблоко",
    "avocado": "авокадо",
    "banana": "банан",
    "bell_pepper": "сладкий перец",
    "berries": "ягоды",
    "broccoli": "брокколи",
    "buckwheat": "гречку",
    "chicken_breast": "курицу",
    "corn_tortilla": "кукурузную тортилью",
    "cottage_cheese": "творог",
    "cucumber": "огурец",
    "egg": "яйцо",
    "greek_yogurt": "греческий йогурт",
    "lactose_free_cottage_cheese": "безлактозный творог",
    "lactose_free_yogurt": "безлактозный йогурт",
    "lentils": "чечевицу",
    "oats": "овсянку",
    "olive_oil": "оливковое масло",
    "orange": "апельсин",
    "potato": "картофель",
    "pumpkin_seeds": "тыквенные семечки",
    "quinoa": "киноа",
    "rice": "рис",
    "salmon": "лосось",
    "spinach": "шпинат",
    "tofu": "тофу",
    "tomato": "томаты",
    "tuna": "тунца",
    "turkey": "индейку",
    "whole_grain_bread": "цельнозерновой тост",
    "whole_wheat_pasta": "цельнозерновую пасту",
}

ID_PARTS = {
    "apple": "apple",
    "avocado": "avocado",
    "banana": "banana",
    "bell_pepper": "pepper",
    "berries": "berries",
    "broccoli": "broccoli",
    "buckwheat": "buckwheat",
    "chicken_breast": "chicken",
    "corn_tortilla": "tortilla",
    "cottage_cheese": "cottage",
    "cucumber": "cucumber",
    "egg": "egg",
    "greek_yogurt": "yogurt",
    "lactose_free_cottage_cheese": "lf_cottage",
    "lactose_free_yogurt": "lf_yogurt",
    "lentils": "lentils",
    "oats": "oats",
    "olive_oil": "olive_oil",
    "orange": "orange",
    "potato": "potato",
    "pumpkin_seeds": "seeds",
    "quinoa": "quinoa",
    "rice": "rice",
    "salmon": "salmon",
    "spinach": "spinach",
    "tofu": "tofu",
    "tomato": "tomato",
    "tuna": "tuna",
    "turkey": "turkey",
    "whole_grain_bread": "bread",
    "whole_wheat_pasta": "pasta",
}

MAIN_STYLES = (
    ("bowl", "зерновая тарелка", "Соберите теплую тарелку"),
    ("plate", "тарелка", "Подайте как сбалансированную тарелку"),
    ("warm_salad", "теплый салат", "Сделайте теплый салат"),
    ("skillet", "сковорода", "Быстро прогрейте все на сковороде"),
    ("oven", "запеченная тарелка", "Запеките основу и гарнир, затем добавьте овощи"),
    ("steam", "легкая паровая тарелка", "Приготовьте основу щадящим способом и добавьте гарнир"),
    ("stew", "густое рагу", "Потушите основу с овощами до мягкости"),
    ("lunchbox", "ланч-бокс", "Разложите компоненты секциями в контейнер"),
    ("rustic", "домашняя тарелка", "Приготовьте простое домашнее блюдо"),
    ("fresh", "свежая тарелка", "Оставьте овощи свежими, а основу подайте теплой"),
    ("spiced", "пряная тарелка", "Добавьте специи в конце приготовления"),
    ("green", "зеленая тарелка", "Сделайте акцент на зелени и свежих овощах"),
)

BREAKFAST_STYLES = (
    ("bowl", "утренняя тарелка"),
    ("porridge", "каша"),
    ("plate", "завтрак-тарелка"),
    ("jar", "ленивый завтрак в банке"),
    ("warm", "теплый завтрак"),
    ("creamy", "кремовая тарелка"),
    ("crunch", "хрустящий завтрак"),
    ("fresh", "свежая утренняя тарелка"),
)

SNACK_STYLES = (
    ("quick", "быстрый перекус"),
    ("protein", "белковый перекус"),
    ("fresh", "свежий перекус"),
    ("mini_bowl", "мини-порция"),
    ("crunch", "хрустящий перекус"),
    ("light", "легкий перекус"),
    ("lunchbox", "перекус в контейнер"),
    ("creamy", "кремовый перекус"),
    ("savory", "дневной перекус"),
    ("post_workout", "сытный перекус"),
    ("tea_pair", "мягкий перекус"),
    ("portable", "перекус с собой"),
)

ACCENTS = (
    ("lemon", "лимонной ноткой", "добавьте немного лимонного сока"),
    ("dill", "укропом", "добавьте рубленый укроп"),
    ("paprika", "паприкой", "приправьте сладкой паприкой"),
    ("basil", "базиликом", "добавьте сушеный или свежий базилик"),
    ("garlic", "чесночным акцентом", "добавьте щепотку сушеного чеснока"),
    ("cumin", "кумином", "добавьте немного кумина"),
    ("pepper", "черным перцем", "поперчите перед подачей"),
    ("herbs", "сухими травами", "добавьте сухие травы"),
    ("lime", "лаймовой ноткой", "сбрызните соком лайма"),
    ("parsley", "петрушкой", "добавьте петрушку перед подачей"),
)


def _generated_recipes() -> tuple[RecipeTemplate, ...]:
    recipes: list[RecipeTemplate] = []
    recipes.extend(_generated_breakfasts())
    recipes.extend(_generated_mains())
    recipes.extend(_generated_snacks())
    return _dedupe_recipes(recipes)


def _generated_breakfasts() -> tuple[RecipeTemplate, ...]:
    recipes: list[RecipeTemplate] = []
    grains = ("oats", "buckwheat", "quinoa")
    dairies = ("greek_yogurt", "cottage_cheese", "lactose_free_yogurt", "lactose_free_cottage_cheese")
    fruits = ("berries", "banana", "apple", "orange")
    boosters = ("pumpkin_seeds", "avocado", "spinach")
    vegetables = ("tomato", "spinach", "bell_pepper", "cucumber", "broccoli")
    carbs = ("whole_grain_bread", "corn_tortilla", "potato", "rice")
    index = 0

    for grain in grains:
        for dairy in dairies:
            for fruit in fruits:
                for booster in boosters:
                    if booster == "avocado" and fruit in {"banana", "orange"}:
                        continue
                    for style_id, style_title in BREAKFAST_STYLES:
                        accent_id, accent_title, accent_action = ACCENTS[index % len(ACCENTS)]
                        ingredients = {
                            grain: _grams(46, index, 4, 7),
                            dairy: _grams(115, index + 1, 8, 7),
                            fruit: _grams(115, index + 2, 8, 7),
                            booster: _grams(12 if booster == "pumpkin_seeds" else 45, index + 3, 3, 5),
                        }
                        recipes.append(
                            RecipeTemplate(
                                id=_recipe_id("breakfast", style_id, grain, dairy, fruit, booster, accent_id),
                                slot="breakfast",
                                title=(
                                    f"{style_title.capitalize()} с {FOOD_TITLES[grain]}, {FOOD_TITLES[dairy]}, "
                                    f"{FOOD_TITLES[fruit]} и {FOOD_TITLES[booster]}"
                                ),
                                ingredients_g=ingredients,
                                instructions=_breakfast_bowl_instructions(grain, dairy, fruit, booster, accent_action),
                                **img(_image_key(grain, dairy, fruit)),
                            )
                        )
                        index += 1

    for vegetable in vegetables:
        for carb in carbs:
            for booster in ("avocado", "pumpkin_seeds", "spinach"):
                if booster == vegetable:
                    continue
                for style_id, style_title in BREAKFAST_STYLES[:6]:
                    accent_id, accent_title, accent_action = ACCENTS[index % len(ACCENTS)]
                    ingredients = {
                        "egg": _grams(70, index, 5, 5),
                        vegetable: _grams(95, index + 1, 10, 6),
                        carb: _grams(55, index + 2, 6, 6),
                        booster: _grams(45 if booster != "pumpkin_seeds" else 10, index + 3, 3, 5),
                    }
                    recipes.append(
                        RecipeTemplate(
                            id=_recipe_id("breakfast", "egg", style_id, vegetable, carb, booster, accent_id),
                            slot="breakfast",
                            title=(
                                f"{style_title.capitalize()} с яйцом, {FOOD_TITLES[vegetable]}, "
                                f"{FOOD_TITLES[carb]} и {FOOD_TITLES[booster]}"
                            ),
                            ingredients_g=ingredients,
                            instructions=_egg_breakfast_instructions(vegetable, carb, booster, accent_action),
                            **img("egg"),
                        )
                    )
                    index += 1
    return tuple(recipes)


def _generated_mains() -> tuple[RecipeTemplate, ...]:
    recipes: list[RecipeTemplate] = []
    proteins = ("chicken_breast", "turkey", "salmon", "tuna", "tofu", "lentils", "egg")
    carbs = ("buckwheat", "rice", "whole_wheat_pasta", "potato", "quinoa", "corn_tortilla", "whole_grain_bread")
    vegetables = ("broccoli", "tomato", "cucumber", "bell_pepper", "spinach")
    fats = ("olive_oil", "avocado", "pumpkin_seeds")
    index = 0

    for protein in proteins:
        for carb in carbs:
            if protein == "lentils" and carb in {"whole_grain_bread", "corn_tortilla"}:
                continue
            for first_veg_pos, first_veg in enumerate(vegetables):
                for second_veg in vegetables[first_veg_pos + 1 :]:
                    for fat in fats:
                        if fat == "avocado" and "avocado" in {first_veg, second_veg}:
                            continue
                        for style_id, style_title, style_action in MAIN_STYLES:
                            accent_id, accent_title, accent_action = ACCENTS[index % len(ACCENTS)]
                            ingredients = {
                                protein: _protein_grams(protein, index),
                                carb: _carb_grams(carb, index + 1),
                                first_veg: _veg_grams(first_veg, index + 2),
                                second_veg: _veg_grams(second_veg, index + 3),
                                fat: _fat_grams(fat, index + 4),
                            }
                            recipes.append(
                                RecipeTemplate(
                                    id=_recipe_id("main", style_id, protein, carb, first_veg, second_veg, fat, accent_id),
                                    slot="main",
                                    title=(
                                        f"{style_title.capitalize()} с {FOOD_TITLES[protein]}, "
                                        f"{FOOD_TITLES[carb]}, {FOOD_TITLES[first_veg]} и {accent_title}"
                                    ),
                                    ingredients_g=ingredients,
                                    instructions=_main_instructions(
                                        style_action,
                                        protein,
                                        carb,
                                        first_veg,
                                        second_veg,
                                        fat,
                                        accent_action,
                                    ),
                                    **img(_image_key(protein, carb)),
                                )
                            )
                            index += 1
    return tuple(recipes)


def _generated_snacks() -> tuple[RecipeTemplate, ...]:
    recipes: list[RecipeTemplate] = []
    dairies = ("greek_yogurt", "cottage_cheese", "lactose_free_yogurt", "lactose_free_cottage_cheese")
    fruits = ("berries", "banana", "apple", "orange")
    boosters = ("pumpkin_seeds", "spinach", "avocado")
    bases = ("whole_grain_bread", "corn_tortilla", "potato")
    proteins = ("egg", "tuna", "tofu", "cottage_cheese", "lactose_free_cottage_cheese")
    vegetables = ("cucumber", "tomato", "bell_pepper", "spinach")
    index = 0

    for dairy in dairies:
        for fruit in fruits:
            for booster in boosters:
                if booster == "avocado" and fruit in {"banana", "orange"}:
                    continue
                for style_id, style_title in SNACK_STYLES:
                    accent_id, accent_title, accent_action = ACCENTS[index % len(ACCENTS)]
                    ingredients = {
                        dairy: _grams(105, index, 8, 6),
                        fruit: _grams(100, index + 1, 8, 6),
                        booster: _grams(10 if booster == "pumpkin_seeds" else 38, index + 2, 3, 5),
                    }
                    recipes.append(
                        RecipeTemplate(
                            id=_recipe_id("snack", style_id, dairy, fruit, booster, accent_id),
                            slot="snack",
                            title=(
                                f"{style_title.capitalize()} с {FOOD_TITLES[dairy]}, {FOOD_TITLES[fruit]} "
                                f"и {FOOD_TITLES[booster]}"
                            ),
                            ingredients_g=ingredients,
                            instructions=_sweet_snack_instructions(dairy, fruit, booster, accent_action),
                            **img(_image_key(dairy, fruit)),
                        )
                    )
                    index += 1

    for base in bases:
        for protein in proteins:
            for vegetable in vegetables:
                if protein in {"cottage_cheese", "lactose_free_cottage_cheese"} and base == "potato":
                    continue
                for style_id, style_title in SNACK_STYLES:
                    accent_id, accent_title, accent_action = ACCENTS[index % len(ACCENTS)]
                    ingredients = {
                        base: _grams(48, index, 5, 6),
                        protein: _protein_grams(protein, index + 1, snack=True),
                        vegetable: _grams(75, index + 2, 8, 5),
                    }
                    recipes.append(
                        RecipeTemplate(
                            id=_recipe_id("snack", "savory", style_id, base, protein, vegetable, accent_id),
                            slot="snack",
                            title=(
                                f"{style_title.capitalize()} с {FOOD_TITLES[base]}, {FOOD_TITLES[protein]} "
                                f"и {FOOD_TITLES[vegetable]}"
                            ),
                            ingredients_g=ingredients,
                            instructions=_savory_snack_instructions(base, protein, vegetable, accent_action),
                            **img(_image_key(protein, base)),
                        )
                    )
                    index += 1
    return tuple(recipes)


def _acc(food_id: str) -> str:
    return FOOD_ACCUSATIVE.get(food_id, FOOD_TITLES[food_id])


def _grain_step(food_id: str) -> str:
    if food_id == "oats":
        return "Заварите овсянку горячей водой на 5-7 минут, чтобы она стала мягкой и густой."
    if food_id in {"buckwheat", "rice", "quinoa", "whole_wheat_pasta"}:
        return f"Отварите {_acc(food_id)} до готовности и оставьте на минуту под крышкой."
    if food_id == "potato":
        return "Отварите картофель или запеките его дольками до мягкой середины и легкой корочки."
    if food_id == "whole_grain_bread":
        return "Подсушите цельнозерновой тост на сухой сковороде или в тостере до хруста."
    if food_id == "corn_tortilla":
        return "Слегка прогрейте кукурузную тортилью на сухой сковороде, чтобы она стала мягкой."
    return f"Подготовьте {_acc(food_id)} до готовности."


def _protein_step(food_id: str) -> str:
    if food_id in {"chicken_breast", "turkey"}:
        return f"Нарежьте {_acc(food_id)} небольшими кусочками, посолите и быстро обжарьте или запеките до сочности."
    if food_id == "salmon":
        return "Запеките лосось 12-15 минут или обжарьте на сковороде кожей вниз, чтобы он остался нежным внутри."
    if food_id == "tuna":
        return "Разомните тунца вилкой и смешайте с каплей заправки, чтобы он лег ровным сочным слоем."
    if food_id == "tofu":
        return "Нарежьте тофу кубиками и подрумяньте на сковороде до тонкой золотистой корочки."
    if food_id == "lentils":
        return "Прогрейте чечевицу с частью овощей 5-7 минут, чтобы она стала основой густого рагу."
    if food_id == "egg":
        return "Отварите яйцо и нарежьте кружочками или приготовьте мягкий скрэмбл на слабом огне."
    if food_id in {"cottage_cheese", "lactose_free_cottage_cheese"}:
        return f"Разомните {_acc(food_id)} вилкой, чтобы он стал мягкой кремовой основой."
    return f"Подготовьте {_acc(food_id)} до готовности."


def _vegetable_step(*food_ids: str) -> str:
    if "broccoli" in food_ids:
        other_ids = [food_id for food_id in food_ids if food_id != "broccoli"]
        if other_ids:
            other_named = " и ".join(_acc(food_id) for food_id in other_ids)
            return f"Брокколи доведите до мягко-хрустящей текстуры, а {other_named} нарежьте для свежей части блюда."
        return "Брокколи доведите до мягко-хрустящей текстуры."
    named = " и ".join(_acc(food_id) for food_id in food_ids)
    return f"Нарежьте {named} аккуратными ломтиками или кубиками, чтобы блюдо выглядело свежо."


def _fat_step(food_id: str) -> str:
    if food_id == "olive_oil":
        return "Заправьте оливковым маслом уже перед подачей."
    if food_id == "avocado":
        return "Добавьте ломтики авокадо или разомните его в мягкий крем."
    if food_id == "pumpkin_seeds":
        return "Посыпьте сверху тыквенными семечками для хруста."
    return f"Добавьте {_acc(food_id)} перед подачей."


def _booster_step(food_id: str) -> str:
    if food_id == "pumpkin_seeds":
        return "Посыпьте семечками сверху, чтобы добавить хруст."
    if food_id == "avocado":
        return "Авокадо разомните вилкой или нарежьте тонкими ломтиками."
    if food_id == "spinach":
        return "Шпинат вмешайте в теплую основу в самом конце, чтобы он только слегка осел."
    return f"Добавьте {_acc(food_id)}."


def _breakfast_bowl_instructions(grain: str, dairy: str, fruit: str, booster: str, accent_action: str) -> str:
    return (
        f"{_grain_step(grain)} Добавьте {_acc(dairy)} и аккуратно вмешайте до кремовой текстуры. "
        f"Нарежьте {_acc(fruit)} и выложите сверху. {_booster_step(booster)} В конце {accent_action}."
    )


def _egg_breakfast_instructions(vegetable: str, carb: str, booster: str, accent_action: str) -> str:
    return (
        f"{_grain_step(carb)} {_protein_step('egg')} "
        f"{_single_vegetable_step(vegetable)} {_booster_step(booster)} В конце {accent_action}."
    )


def _single_vegetable_step(food_id: str) -> str:
    if food_id == "spinach":
        return "Шпинат оставьте свежим и выложите рядом с яйцом."
    if food_id == "broccoli":
        return "Брокколи приготовьте до мягко-хрустящей текстуры и выложите рядом с яйцом."
    return f"Нарежьте {_acc(food_id)} и выложите рядом с яйцом."


def _main_instructions(
    style_action: str,
    protein: str,
    carb: str,
    first_veg: str,
    second_veg: str,
    fat: str,
    accent_action: str,
) -> str:
    return (
        f"{style_action}: {_protein_step(protein)} {_grain_step(carb)} "
        f"{_vegetable_step(first_veg, second_veg)} {_fat_step(fat)} "
        f"В конце {accent_action}; подайте так, чтобы теплая основа была рядом со свежими овощами."
    )


def _sweet_snack_instructions(dairy: str, fruit: str, booster: str, accent_action: str) -> str:
    return (
        f"Сделайте небольшой кремовый перекус: выложите {_acc(dairy)} в миску, "
        f"нарежьте {_acc(fruit)} и вмешайте часть кусочков внутрь. {_booster_step(booster)} В конце {accent_action}."
    )


def _savory_snack_instructions(base: str, protein: str, vegetable: str, accent_action: str) -> str:
    return (
        f"{_grain_step(base)} {_protein_step(protein)} "
        f"Нарежьте {_acc(vegetable)} и соберите все в аккуратный открытый тост, ролл или мини-тарелку. "
        f"Перед подачей {accent_action}."
    )


def _dedupe_recipes(recipes: list[RecipeTemplate]) -> tuple[RecipeTemplate, ...]:
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[RecipeTemplate] = []
    for recipe in recipes:
        title_key = f"{recipe.slot}:{recipe.title}"
        if recipe.id in seen_ids or title_key in seen_titles:
            continue
        seen_ids.add(recipe.id)
        seen_titles.add(title_key)
        unique.append(recipe)
    return tuple(unique)


def _recipe_id(prefix: str, *parts: str) -> str:
    clean_parts = [ID_PARTS.get(part, part) for part in parts]
    return "_".join((prefix, *clean_parts))


def _grams(base: float, index: int, step: float, spread: int) -> float:
    offset = (index % spread) - (spread // 2)
    return round(max(5.0, base + offset * step), 1)


def _protein_grams(food_id: str, index: int, snack: bool = False) -> float:
    if food_id == "egg":
        return _grams(50 if snack else 75, index, 5, 5)
    if food_id in {"cottage_cheese", "lactose_free_cottage_cheese"}:
        return _grams(100 if snack else 120, index, 8, 5)
    if food_id == "lentils":
        return _grams(130, index, 12, 5)
    if food_id == "tofu":
        return _grams(60 if snack else 90, index, 10, 5)
    if food_id == "tuna":
        return _grams(45 if snack else 70, index, 8, 5)
    if food_id == "salmon":
        return _grams(80, index, 8, 5)
    return _grams(75, index, 10, 5)


def _carb_grams(food_id: str, index: int) -> float:
    if food_id == "potato":
        return _grams(210, index, 15, 7)
    if food_id in {"whole_grain_bread", "corn_tortilla"}:
        return _grams(65, index, 5, 7)
    return _grams(65, index, 5, 7)


def _veg_grams(food_id: str, index: int) -> float:
    if food_id == "spinach":
        return _grams(60, index, 5, 5)
    return _grams(115, index, 8, 5)


def _fat_grams(food_id: str, index: int) -> float:
    if food_id == "olive_oil":
        return _grams(10, index, 2, 5)
    if food_id == "pumpkin_seeds":
        return _grams(12, index, 2, 5)
    return _grams(55, index, 5, 5)


def _image_key(*food_ids: str) -> str:
    food_set = set(food_ids)
    if "salmon" in food_set:
        return "salmon"
    if "tuna" in food_set:
        return "tuna"
    if "tofu" in food_set:
        return "tofu_rice"
    if "whole_wheat_pasta" in food_set:
        return "pasta"
    if "egg" in food_set:
        return "egg"
    if "quinoa" in food_set:
        return "quinoa"
    if "avocado" in food_set and "whole_grain_bread" in food_set:
        return "avocado_toast"
    if food_set & {"greek_yogurt", "lactose_free_yogurt", "cottage_cheese", "lactose_free_cottage_cheese"}:
        return "yogurt"
    if "oats" in food_set:
        return "oatmeal"
    return "quinoa"
