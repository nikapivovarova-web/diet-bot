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


def built_in_recipes() -> tuple[RecipeTemplate, ...]:
    return (
        RecipeTemplate(
            id="breakfast_oat_berry_bowl",
            slot="breakfast",
            title="Овсяный боул с йогуртом и ягодами",
            ingredients_g={"oats": 55, "greek_yogurt": 180, "berries": 120, "pumpkin_seeds": 10},
            instructions="Заварите овсянку горячей водой на 5 минут, затем добавьте йогурт, ягоды и немного семечек для хруста.",
        ),
        RecipeTemplate(
            id="breakfast_banana_oats",
            slot="breakfast",
            title="Банановая овсянка с йогуртом",
            ingredients_g={"oats": 60, "greek_yogurt": 170, "banana": 120, "pumpkin_seeds": 10},
            instructions="Сварите овсянку до мягкости, снимите с огня, добавьте йогурт и ломтики банана. Семечки посыпьте сверху.",
        ),
        RecipeTemplate(
            id="breakfast_omelet_tomato",
            slot="breakfast",
            title="Омлет с томатами и шпинатом",
            ingredients_g={"egg": 120, "tomato": 120, "spinach": 60, "whole_grain_bread": 50},
            instructions="Взбейте яйца, добавьте томаты и шпинат, готовьте на слабом огне под крышкой. Подавайте с тостом.",
        ),
        RecipeTemplate(
            id="breakfast_scramble_avocado",
            slot="breakfast",
            title="Скрэмбл с авокадо",
            ingredients_g={"egg": 120, "avocado": 70, "tomato": 120, "whole_grain_bread": 50},
            instructions="Сделайте нежный скрэмбл на слабом огне, рядом положите ломтики авокадо и томата, добавьте тост.",
        ),
        RecipeTemplate(
            id="breakfast_cottage_berries",
            slot="breakfast",
            title="Творожная тарелка с ягодами",
            ingredients_g={"cottage_cheese": 200, "berries": 150, "oats": 35, "pumpkin_seeds": 10},
            instructions="Смешайте творог с ягодами, сверху добавьте сухие овсяные хлопья или слегка подсушите их на сковороде.",
        ),
        RecipeTemplate(
            id="breakfast_tortilla_egg_roll",
            slot="breakfast",
            title="Утренний ролл с яйцом",
            ingredients_g={"corn_tortilla": 70, "egg": 100, "tomato": 80, "spinach": 50, "avocado": 50},
            instructions="Приготовьте яйцо скрэмблом, выложите в тортилью с овощами и авокадо, сверните плотный ролл.",
        ),
        RecipeTemplate(
            id="breakfast_quinoa_yogurt",
            slot="breakfast",
            title="Киноа-боул с апельсином",
            ingredients_g={"quinoa": 50, "greek_yogurt": 170, "orange": 140, "pumpkin_seeds": 10},
            instructions="Отварите киноа заранее, утром смешайте с йогуртом и апельсином, посыпьте семечками.",
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
            title="Боул с индейкой, киноа и перцем",
            ingredients_g={"turkey": 150, "quinoa": 65, "bell_pepper": 130, "cucumber": 100, "olive_oil": 10},
            instructions="Индейку приготовьте кусочками, киноа отварите. Соберите боул с перцем, огурцом и легкой масляной заправкой.",
        ),
        RecipeTemplate(
            id="lunch_salmon_potato_broccoli",
            slot="main",
            title="Лосось с картофелем и брокколи",
            ingredients_g={"salmon": 150, "potato": 240, "broccoli": 160, "olive_oil": 10},
            instructions="Лосось запеките 12-15 минут, картофель отварите или запеките дольками, брокколи приготовьте до мягко-хрустящей текстуры.",
        ),
        RecipeTemplate(
            id="lunch_tuna_avocado_sandwich",
            slot="main",
            title="Сэндвич с тунцом и авокадо",
            ingredients_g={"tuna": 130, "whole_grain_bread": 90, "avocado": 70, "cucumber": 100, "tomato": 80},
            instructions="Разомните авокадо, выложите на хлеб с тунцом, огурцом и томатом. Получится плотный сэндвич без тяжелого соуса.",
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
            title="Рисовый боул с тофу и овощами",
            ingredients_g={"tofu": 180, "rice": 70, "broccoli": 140, "bell_pepper": 120, "olive_oil": 10},
            instructions="Рис отварите, тофу подрумяньте кубиками, овощи быстро прогрейте на сковороде и соберите все в боул.",
        ),
        RecipeTemplate(
            id="lunch_chicken_pasta_tomato",
            slot="main",
            title="Паста с курицей и томатами",
            ingredients_g={"chicken_breast": 140, "whole_wheat_pasta": 75, "tomato": 180, "spinach": 60, "olive_oil": 10},
            instructions="Пасту отварите al dente, курицу приготовьте кусочками, затем быстро соедините с томатами, шпинатом и маслом.",
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
        ),
        RecipeTemplate(
            id="dinner_egg_shakshuka",
            slot="main",
            title="Шакшука с цельнозерновым тостом",
            ingredients_g={"egg": 120, "tomato": 220, "bell_pepper": 120, "whole_grain_bread": 60, "olive_oil": 8},
            instructions="Потушите томаты и перец до соуса, сделайте углубления и вбейте яйца. Готовьте под крышкой, подавайте с тостом.",
        ),
        RecipeTemplate(
            id="dinner_tuna_potato_bowl",
            slot="main",
            title="Картофельный боул с тунцом",
            ingredients_g={"tuna": 130, "potato": 260, "cucumber": 120, "tomato": 120, "avocado": 60},
            instructions="Картофель отварите или запеките кубиками, добавьте тунец, овощи и авокадо. Это сытный, но простой ужин.",
        ),
        RecipeTemplate(
            id="snack_yogurt_berries",
            slot="snack",
            title="Йогурт с ягодами",
            ingredients_g={"greek_yogurt": 180, "berries": 120, "pumpkin_seeds": 10},
            instructions="Смешайте йогурт с ягодами и добавьте немного семечек сверху.",
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
        ),
        RecipeTemplate(
            id="snack_avocado_toast",
            slot="snack",
            title="Тост с авокадо",
            ingredients_g={"whole_grain_bread": 60, "avocado": 60, "tomato": 80},
            instructions="Разомните авокадо на тосте, сверху положите томат. Это быстрый перекус с полезными жирами.",
        ),
        RecipeTemplate(
            id="snack_egg_cucumber",
            slot="snack",
            title="Яйцо с огурцом и тостом",
            ingredients_g={"egg": 60, "cucumber": 120, "whole_grain_bread": 40},
            instructions="Отварите яйцо заранее, подайте с огурцом и небольшим тостом.",
        ),
    )
