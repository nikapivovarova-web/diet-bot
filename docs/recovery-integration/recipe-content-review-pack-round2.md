# Recipe Content Review Pack Round 2

Audit-only review pack. Recipe JSON/data, PDF, Telegram/privacy/questionnaire, payments/runtime/storage/deploy, and bot runtime were not edited by this generator.

## Summary
- total recipes checked: 665
- total recipes with any warning: 592
- total recipes with high suspicion: 24 (score >= 100)
- audit finding rows used: 1586 warnings, 0 blockers
- full-coverage CSV rows: 665 recipes; no-warning recipes are kept at the bottom with decision A
- how ranking works: title/ingredient mismatch, steps mentioning missing ingredients, truncation/fragment warnings, tiny/zero quantities, non-CIS/unclear ingredients, and missing approximate measures add score; clusters of 4+ ingredient-missing-from-steps warnings add extra score; recipes r401-r610 receive an extra +35 only when they already have a warning or user-reported issue; user-reported peanut-butter tiny amounts receive extra score even if the audit script no longer marks them as blockers.

## Top 25 Suspicious Recipes

### Rank 1: `r115_govyazhi_frikadelki_v_souse_iz_krasnoy_fasoli_souse_s_` - Говяжьи фрикадельки в соусе из красной фасоли соусе с лапшой
- recipe no: r115; score: 222; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 4 (whole_grain_bread, egg_noodles, stir_fry_vegetables, mint); title keyword missing from ingredients/steps: title contains `beans`, but expected ingredient/clear preparation was not found; missing approximate/user-friendly measure: 1; e.g. соус из черных бобов — 30 г; 4 ingredients in list are not named in steps
- suggested decision: F. needs user decision (rename recipe vs add missing ingredient/step)
- ingredients:
  - 1. говяжий фарш — 75 г (`beef_ground`; grams=75)
  - 2. свежие хлебные крошки — 50 г (`whole_grain_bread`; grams=50)
  - 3. соус из черных бобов — 30 г (`black_bean_sauce`; grams=30)
  - 4. сладкий соус чили — 15 мл (`chili_pepper`; grams=15)
  - 5. кетчуп — 11,2 мл (`ketchup`; grams=11.2)
  - 6. китайская смесь пять специй — 0,5 ч. л. (`five_spice`; grams=1)
  - 7. подсолнечное масло — 3,75 мл + 1,25 мл для рук (`vegetable_oil`; grams=1.15)
  - 8. средняя яичная лапша — 45 г (`egg_noodles`; grams=45)
  - 9. овощная смесь для стир-фрая — 100 г (`stir_fry_vegetables`; grams=100)
  - 10. соевый соус — 11,2 мл (`soy_sauce`; grams=12.99)
  - 11. кунжут — 0,25 ст. л. (`sesame_seeds`; grams=2.25)
  - 12. мята — 0,12 пучка, листья отделить (`mint`; grams=4)
- instruction steps:
  1. Разогрейте духовку до 220 °C.
  2. Смажьте ладони 1,25 мл подсолнечного масла.
  3. В миске смешайте говяжий фарш, хлебные крошки, 0,75 ст. л. соуса из черных бобов, по 0,25 ст. л. сладкого чили и кетчупа, а также 0,25 ч. л. смеси пять специй.
  4. Скатайте фрикадельки размером с грецкий орех, выложите на противень в один слой и запекайте 25 минут, один раз перевернув.
  5. Отварите яичную лапшу до горячего центра и слейте воду.
  6. В воке или широкой сковороде разогрейте 3,75 мл подсолнечного масла, быстро обжарьте овощную смесь несколько минут.
  7. Добавьте лапшу, оставшийся соус из черных бобов, оставшийся сладкий чили, кетчуп, вторую чайную ложку пяти специй и соевый соус; перемешивайте, пока лапша не покроется соусом и не прогреется.
  8. Разложите лапшу по мискам, сверху положите запеченные фрикадельки, посыпьте кунжутом и листьями мяты.

### Rank 2: `r171_spagetti_boloneze_s_govyadinoy_i_svininoy` - Спагетти болоньезе с говядиной и свининой
- recipe no: r171; score: 181; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 2 (tomato_paste, oregano); title keyword missing from ingredients/steps: title contains `pork`, but expected ingredient/clear preparation was not found
- suggested decision: F. needs user decision (rename recipe vs add missing ingredient/step)
- ingredients:
  - 1. оливковое масло — 0,75 ст. л. (`olive_oil`; grams=10.12)
  - 2. говяжий фарш — 75 г (`beef_ground`; grams=75)
  - 3. сбульонй фарш — 50 г (`ground_meat`; grams=50)
  - 4. шалот — 0,5 крупных, мелко нарезать (`onion`; grams=50)
  - 5. чеснок — 0,5–0,75 зубчика, раздавить (`garlic`; grams=3.12)
  - 6. пассата — 125 г (`passata`; grams=125)
  - 7. томатная паста — 0,25 ст. л. (`tomato_paste`; grams=4)
  - 8. красное бульон — 25 мл (`beef_broth`; grams=25)
  - 9. сушеный орегано — 0,25 ч. л. (`oregano`; grams=0.25)
  - 10. спагетти — 100 г (`spaghetti`; grams=100)
  - 11. пармезан — 12,5 г, мелко натереть (`parmesan`; grams=12.5)
  - 12. базилик — несколько листьев (`basil`; grams=2)
  - 13. Соль — 0,5–1 г (`salt`; grams=0.75)
  - 14. Черный перец — 0,12–0,25 г (`black_pepper`; grams=0.18)
- instruction steps:
  1. В большой кастрюле разогрейте 0,25 ст. л. оливкового масла на средне-сильном огне.
  2. Обжарьте говяжий фарш до румяного цвета, разбивая комки, и переложите в миску.
  3. Влейте еще 0,25 ст. л. масла, так же обжарьте сбульонй фарш и добавьте к говядине.
  4. Убавьте огонь, влейте оставшееся масло, положите шалот и готовьте 8–10 минут до мягкости.
  5. Добавьте чеснок на 1 минуту, затем верните оба вида фарша.
  6. Вмешайте пассату, томатную пасту, красное бульон, орегано, соль и черный перец.
  7. Накройте и тушите на слабом огне около 45 минут, иногда перемешивая.
  8. Отварите спагетти в подсоленной воде до альденте, сохраните половник воды от варки и слейте пасту.
  9. Вмешайте половину пармезана в соус, при необходимости разбавьте водой от пасты, соедините со спагетти и прогрейте 1 минуту.
  10. Разложите по тарелкам, посыпьте оставшимся пармезаном и листьями базилика.

### Rank 3: `r034_pankeyki_na_protivne_s_chetyrmya_toppingami` - Панкейки на противне с четырьмя топпингами
- recipe no: r034; score: 172; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 4 (wheat_flour, peanut_butter, blueberries); 4 ingredients in list are not named in steps; user-reported peanut-butter tiny amount: 2.5 g at ingredient line 10
- suggested decision: F. needs user decision (verify tiny quantity/measure)
- ingredients:
  - 1. белая цельнозерновая мука — 13,3 г (`wheat_flour`; grams=13.3)
  - 2. пшеничная мука — 13,8 г (`wheat_flour`; grams=13.8)
  - 3. разрыхлитель — 0,75 г (`baking_powder`; grams=0.75)
  - 4. сода — 0,5 г (`baking_soda`; grams=0.5)
  - 5. соль — 0,42 г (`salt`; grams=0.42)
  - 6. нежирная пахта — 60 мл (`buttermilk`; grams=61.8)
  - 7. яйца крупные — 0,25 шт. (`egg`; grams=12.5)
  - 8. кленовый сироп — 11,2 мл, из них 1,25 мл для теста (`maple_syrup`; grams=1.66)
  - 9. сливочное масло растопленное — 4,58 г (`butter`; grams=4.58)
  - 10. арахисовая паста — 2,5 г (примерно 1/2 ч. л.) (`peanut_butter`; grams=2.5)
  - 11. сливочный сыр — 2,5 г (примерно 1/2 ч. л.) (`cream_cheese`; grams=2.5)
  - 12. сахар — 1 г (`sugar`; grams=1)
  - 13. банан, нарезанный кружками — 5 г (`banana`; grams=5)
  - 14. темный шоколад, мелко нарезать — 3,75 г (`dark_chocolate`; grams=3.75)
  - 15. свежая малина — 5 г (`raspberries`; grams=5)
  - 16. свежая черника — 4,17 г (`blueberries`; grams=4.17)
  - 17. растительное масло — 0,42 мл для противня (`vegetable_oil`; grams=0.39)
- instruction steps:
  1. Разогрейте духовку до 260 °C и смажьте растительным маслом противень с бортиком около 46×33 см.
  2. Смешайте оба вида муки, разрыхлитель, соду и соль.
  3. В другой миске взбейте пахту, яйца и 1,25 мл кленового сиропа, влейте в сухую смесь и вмешайте растопленное сливочное масло; оставьте тесто на 5 минут.
  4. Арахисовую пасту слегка прогрейте до текучести, а сливочный сыр разотрите с сахаром.
  5. Распределите тесто по противню: в один угол вмешайте арахисовую пасту и банан, во второй насыпьте мелко нарезанный темный шоколад, в третий — малину, в четвертый — чернику и ложечки сливочного сыра.
  6. Поставьте противень в духовку и сразу снизьте температуру до 220 °C; выпекайте 14–16 минут до сухой шпажки.
  7. Нарежьте на 12 квадратов и подайте с оставшимися 10 мл кленового сиропа.

### Rank 4: `r607_syrnye_lepeshki` - Сырные лепёшки
- recipe no: r607; score: 158; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 1 (wheat_flour); tiny/zero gram anomaly: `baking_powder` has 0 g without an obvious intentional marker; missing approximate/user-friendly measure: 1; e.g. сыр гауда — 50 г; extra ranking weight: transferred range r401-r610
- suggested decision: F. needs user decision (correct zero/tiny quantity)
- ingredients:
  - 1. кефир — 80 мл (`kefir`; grams=80)
  - 2. мука — 100 г (`wheat_flour`; grams=100)
  - 3. сыр гауда — 50 г (`gouda`; grams=50)
  - 4. разрыхлитель — 0 ч. л. (`baking_powder`; grams=0)
  - 5. соль — по вкусу (`salt`; grams=0)
- instruction steps:
  1. Смешайте кефир с мукой и солью до мягкого теста.
  2. Вмешайте сыр и разделите тесто на небольшие лепешки.
  3. Разогрейте сухую сковороду на среднем огне.
  4. Обжарьте лепешки по 2-3 минуты с каждой стороны до золотистой корочки.

### Rank 5: `r595_lavash_s_gorbushey_i_ovoschami` - Лаваш с горбушей и овощами
- recipe no: r595; score: 149; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 3 (cucumber, lettuce, carrot); steps mention ingredient missing from list: mayonnaise; missing approximate/user-friendly measure: 1; e.g. хумус — 80 г; extra ranking weight: transferred range r401-r610
- suggested decision: C. add missing ingredient/step
- ingredients:
  - 1. Лаваш — 1 лист (без молочных добавок) (`lavash`; grams=70)
  - 2. горбуша — 70 г (`salmon`; grams=70)
  - 3. огурец — 80 г (`cucumber`; grams=80)
  - 4. салат — 30 г (`lettuce`; grams=30)
  - 5. морковь — 60 г (`carrot`; grams=60)
  - 6. хумус — 80 г (`hummus`; grams=80)
- instruction steps:
  1. Лаваш смажьте хумусом или постным майонезом тонким слоем.
  2. Овощи нарежьте соломкой, горбушу разделите на небольшие кусочки.
  3. Выложите горбушу и овощи на лаваш.
  4. Сверните плотный рулет и нарежьте через 2-3 минуты.

### Rank 6: `r474_kurinye_kotlety_s_kabachkom` - Куриные котлеты с кабачком
- recipe no: r474; score: 148; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 6 (chicken_ground, zucchini, carrot, egg, garlic, mustard); truncation/fragment/weak finish: 1; e.g. Обжаривайте до золотистой корочки; 6 ingredients in list are not named in steps; extra ranking weight: transferred range r401-r610
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. нежирный куриный фарш — 130 г (`chicken_ground`; grams=130)
  - 2. кабачок (натереть и отжать) — 50 г (`zucchini`; grams=50)
  - 3. морковь (натереть) — 30 г (`carrot`; grams=30)
  - 4. яйцо — 1 шт (`egg`; grams=55)
  - 5. лук репчатый (мелко нарезать) — 25 г (`onion`; grams=25)
  - 6. сухой чеснок — 1/4 ч. л. (`garlic`; grams=1)
  - 7. дижонская горчица — 1/4 ч. л. (`mustard`; grams=1)
  - 8. растительное масло (для жарки) — 5 мл (`vegetable_oil`; grams=5)
  - 9. соль — по вкусу (`salt`; grams=0.5)
- instruction steps:
  1. Мелко нарежьте лук и обжарьте его на растительном масле около 5—7 минут до мягкости.
  2. Сформируйте котлетки с помощью круглой вырубки или слепите их руками.
  3. Обжаривайте до золотистой корочки.

### Rank 7: `r062_veganskie_myusli_maffiny_s_yablokom_i_pekanom` - Веганские мюсли-маффины с яблоком и пеканом
- recipe no: r062; score: 143; new r401-r610: no
- why suspicious: missing approximate/user-friendly measure: 2; e.g. ореховая паста — 3,75 г (2,5 г в тесто + 1,25 г сверху); ingredient in list not named in steps: 1 (wheat_flour); truncation/fragment/weak finish: 1; e.g. Выпекайте 25–30 минут до золотистой верхушки и сухой шпажки; user-reported peanut-butter tiny amount: 3.75 g at ingredient line 8
- suggested decision: F. needs user decision (verify tiny quantity/measure)
- ingredients:
  - 1. мюсли — 12,5 г (8,33 г в тесто + 4,17 г сверху) (`muesli`; grams=12.5)
  - 2. мягкий светло-коричневый сахар — 4,17 г (`brown_sugar`; grams=4.17)
  - 3. пшеничная мука — 13,3 г (`wheat_flour`; grams=13.3)
  - 4. разрыхлитель — 0,33 г (`baking_powder`; grams=0.33)
  - 5. сладкое соевое молоко — 20,8 мл (`milk`; grams=21.42)
  - 6. яблоко — 0,083 шт. / около 12,5 г, очищенное и натертое (`apple`; grams=12.5)
  - 7. масло бульонградной косточки — 2,5 мл (`vegetable_oil`; grams=2.3)
  - 8. ореховая паста — 3,75 г (2,5 г в тесто + 1,25 г сверху) (`peanut_butter`; grams=3.75)
  - 9. обычный сахар — 4,17 г (`sugar`; grams=4.17)
  - 10. пекан — 4,17 г (`pecans`; grams=4.17)
- instruction steps:
  1. Разогрейте духовку до 200 °C и поставьте капсулы в форму на 12 маффинов.
  2. Смешайте 8,33 г мюсли, коричневый сахар, муку и разрыхлитель.
  3. Отдельно соедините соевое молоко, тертое яблоко, масло бульонградной косточки и 2,5 г ореховой пасты.
  4. Влейте жидкую смесь в сухую и перемешайте только до увлажнения муки.
  5. Разложите тесто по формам.
  6. Оставшиеся 4,17 г мюсли разотрите с демерарой, 1,25 г ореховой пасты и рубленым пеканом, распределите эту крошку поверх маффинов.
  7. Выпекайте 25–30 минут до золотистой верхушки и сухой шпажки.

### Rank 8: `r061_tselnozernovye_maffiny_s_bananom_yablokom_i_chernikoy` - Цельнозерновые маффины с бананом, яблоком и черникой
- recipe no: r061; score: 139; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 3 (apple_sauce, honey, wheat_flour); tiny/zero gram anomaly: `nuts_mix` has suspiciously tiny quantity 1.5 g; missing approximate/user-friendly measure: 1; e.g. смесь семечек — 1,5 г
- suggested decision: F. needs user decision (verify tiny quantity/measure)
- ingredients:
  - 1. яйца — 0,17 шт. / около 8,33 г (`egg`; grams=8.33)
  - 2. натуральный нежирный йогурт — 12,5 мл (`greek_yogurt`; grams=12.88)
  - 3. рапсовое масло — 4,17 мл (`canola_oil`; grams=3.84)
  - 4. яблочное пюре — 8,33 г (`apple_sauce`; grams=8.33)
  - 5. спелый банан — 0,083 шт. / около 10 г (`banana`; grams=10)
  - 6. жидкий мед — 7,08 г (`honey`; grams=7.08)
  - 7. ванильный экстракт — 0,42 мл (`vanilla_extract`; grams=0.38)
  - 8. цельнозерновая мука — 16,7 г (`wheat_flour`; grams=16.7)
  - 9. овсяные хлопья — 5 г (4,17 г в тесто + 0,83 г сверху) (`oats`; grams=5)
  - 10. разрыхлитель — 0,5 г (`baking_powder`; grams=0.5)
  - 11. пищевая сода — 0,58 г (`baking_soda`; grams=0.58)
  - 12. молотая корица — 0,33 г (`cinnamon`; grams=0.33)
  - 13. черника — 8,33 г (`blueberries`; grams=8.33)
  - 14. смесь семечек — 1,5 г (`nuts_mix`; grams=1.5)
  - 15. соль — 0,083 г (`salt`; grams=0.08)
- instruction steps:
  1. Разогрейте духовку до 180 °C и поставьте бумажные капсулы в форму на 12 маффинов.
  2. В миске взбейте яйца с йогуртом, рапсовым маслом, яблочным пюре, размятым бананом, медом и ванильным экстрактом.
  3. В другой миске смешайте цельнозерновую муку, 4,17 г овсяных хлопьев, разрыхлитель, соду, корицу и соль.
  4. Влейте жидкую смесь к сухой, быстро перемешайте до густого теста и вмешайте чернику.
  5. Разложите тесто по капсулам, посыпьте оставшимися овсяными хлопьями и смесью семечек.
  6. Выпекайте 25–30 минут, пока маффины не поднимутся и шпажка из центра не выйдет сухой.
  7. Переложите на решетку и остудите.

### Rank 9: `r308_bezglyutenovye_bananovo_grechnevye_maffiny_s_gretskimi` - Безглютеновые бананово-гречневые маффины с грецкими орехами
- recipe no: r308; score: 136; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 2 (wheat_flour, almonds); missing approximate/user-friendly measure: 2; e.g. миндальная мука — 3 г; tiny/zero gram anomaly: `almonds` has suspiciously tiny quantity 3 g
- suggested decision: F. needs user decision (verify tiny quantity/measure)
- ingredients:
  - 1. молотое льняное семя — 1,5 мл (`flaxseed_ground`; grams=1.5)
  - 2. вода — 1 мл (`water`; grams=1)
  - 3. спелые бананы — 24 г (`banana`; grams=24)
  - 4. кокосовый сахар — 10 г (`sugar`; grams=10)
  - 5. растительное масло или растопленное кокосовое масло — 3 мл (`vegetable_oil`; grams=2.76)
  - 6. ванильный экстракт — 0,5 мл (`vanilla_extract`; grams=0.45)
  - 7. гречневая мука — 4 г (`wheat_flour`; grams=4)
  - 8. картофельный крахмал — 3 г (`potato`; grams=3)
  - 9. миндальная мука — 3 г (`almonds`; grams=3)
  - 10. сода — 0,5 мл (`baking_soda`; grams=0.5)
  - 11. морская соль — 0,5 мл (`salt`; grams=0.6)
  - 12. грецкие орехи — 6 г (`walnuts`; grams=6)
- instruction steps:
  1. Разогрейте духовку до 176 C и выстелите форму для маффинов бумажными капсулами.
  2. В миске смешайте молотое льняное семя с водой и оставьте на 5 минут, чтобы смесь стала гелеобразной.
  3. Добавьте бананы и разомните их вилкой почти до пюре.
  4. Вмешайте кокосовый сахар, масло авокадо или кокосовое масло и ванильный экстракт.
  5. Всыпьте гречневую муку, картофельный крахмал, миндальную муку, соду и морскую соль, затем перемешайте до теста без сухих следов.
  6. Добавьте грецкие орехи и распределите их по тесту.
  7. Разложите массу по 10 формочкам и выпекайте 35-40 минут, пока шпажка не будет выходить с несколькими влажными крошками.
  8. Остудите 10 минут в форме, затем перенесите на решетку до полного остывания.

### Rank 10: `r577_ovsyanye_shariki` - Овсяные шарики
- recipe no: r577; score: 135; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 5 (oats, peanut_butter, honey, cocoa_powder, sunflower_seeds); truncation/fragment/weak finish: 1; e.g. Уберите в холодильник на 30 минут, чтобы они стали плотнее; 5 ingredients in list are not named in steps; extra ranking weight: transferred range r401-r610
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. Овсянка — 0,5 ст. л. (`oats`; grams=8)
  - 2. арахисовая паста — 1 ст. л. (`peanut_butter`; grams=20)
  - 3. мёд — 0,5 ст. л. (`honey`; grams=10)
  - 4. какао — 50 г (`cocoa_powder`; grams=50)
  - 5. семечки — 15 г (`sunflower_seeds`; grams=15)
- instruction steps:
  1. Смешайте все ингредиенты до липкой массы.
  2. Если масса рассыпается, хорошо прижмите ее ложкой к стенкам миски.
  3. Скатайте небольшие шарики влажными руками.
  4. Уберите в холодильник на 30 минут, чтобы они стали плотнее.

### Rank 11: `r598_ovsyanka_s_bananom_i_arahisovoy_pastoy` - Овсянка с бананом и арахисовой пастой
- recipe no: r598; score: 133; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 1 (peanut_butter); user-reported peanut-butter tiny amount: 5 g at ingredient line 4; extra ranking weight: transferred range r401-r610
- suggested decision: F. needs user decision (verify tiny quantity/measure)
- ingredients:
  - 1. овсянка — 50 г (`oats`; grams=50)
  - 2. вода — 200 мл (`water`; grams=200)
  - 3. банан — 1 шт. (`banana`; grams=120)
  - 4. арахисовая паста — 1 ч. л. (`peanut_butter`; grams=5)
- instruction steps:
  1. Доведите воду до кипения и всыпьте овсянку.
  2. Варите на слабом огне 5 минут, помешивая, до мягкости.
  3. Банан нарежьте кружками.
  4. Снимите кашу с огня, добавьте банан и арахисовую пасту, перемешайте до кремовой текстуры.

### Rank 12: `r631_shpinatnye_bliny_s_tomatami` - Шпинатные блины с томатами
- recipe no: r631; score: 131; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 2 (milk, wheat_flour); tiny/zero gram anomaly: `vinegar` has suspiciously tiny quantity 1.25 g; missing approximate/user-friendly measure: 1; e.g. уксус — 1,25 г
- suggested decision: F. needs user decision (verify tiny quantity/measure)
- ingredients:
  - 1. молоко — 125 г (`milk`; grams=125)
  - 2. пшеничная мука — 65 г (`wheat_flour`; grams=65)
  - 3. шпинат — 75 г (`spinach`; grams=75)
  - 4. сахар — 2 г (`sugar`; grams=2)
  - 5. уксус — 1,25 г (`vinegar`; grams=1.25)
  - 6. сода — 0,63 г (`baking_soda`; grams=0.63)
  - 7. растительное масло — 5 мл (`vegetable_oil`; grams=5)
  - 8. помидор — 100 г (`tomato`; grams=100)
- instruction steps:
  1. Пробейте шпинат с молоком до однородности.
  2. Добавьте сахар, соду с уксусом и муку, размешайте тесто без комков.
  3. Сковороду слегка смажьте маслом и испеките тонкие блины по 1-2 минуты с каждой стороны.
  4. Подавайте с нарезанными томатами.

### Rank 13: `r063_speltovye_maffiny_s_ezhevikoy_bananom_i_finikami` - Спельтовые маффины с ежевикой, бананом и финиками
- recipe no: r063; score: 128; new r401-r610: no
- why suspicious: missing approximate/user-friendly measure: 2; e.g. финики без косточек — 6,67 г; tiny/zero gram anomaly: `pecans` has suspiciously tiny quantity 2.5 g; ingredient in list not named in steps: 1 (wheat_flour)
- suggested decision: F. needs user decision (verify tiny quantity/measure)
- ingredients:
  - 1. цельнозерновая спельтовая мука — 29,2 г (`wheat_flour`; grams=29.2)
  - 2. молотая корица — 0,42 г (`cinnamon`; grams=0.42)
  - 3. разрыхлитель — 1 г (`baking_powder`; grams=1)
  - 4. пищевая сода — 0,42 г (`baking_soda`; grams=0.42)
  - 5. очень спелые бананы — 0,17 шт. / 13,3 г мякоти (`banana`; grams=13.3)
  - 6. финики без косточек — 6,67 г (`dates`; grams=6.67)
  - 7. яйца — 0,17 шт. / около 8,33 г (`egg`; grams=8.33)
  - 8. натуральный йогурт — 23,8 г (`greek_yogurt`; grams=23.8)
  - 9. рапсовое масло — 5 мл (`canola_oil`; grams=4.6)
  - 10. ванильный экстракт — 0,83 мл (`vanilla_extract`; grams=0.75)
  - 11. ежевика — 18,8 г (`blackberries`; grams=18.8)
  - 12. пекан — 2,5 г (`pecans`; grams=2.5)
- instruction steps:
  1. Разогрейте духовку до 180 °C и выстелите форму на 12 маффинов бумажными капсулами.
  2. В большой миске смешайте спельтовую муку, корицу, разрыхлитель и соду.
  3. В другой миске разомните бананы с нарезанными финиками, затем вмешайте яйца, йогурт, рапсовое масло и ванильный экстракт.
  4. Обваляйте ежевику в мучной смеси, добавьте бананово-йогуртовую массу и быстро перемешайте в густое тесто.
  5. Разложите тесто почти до краев капсул, посыпьте пеканом.
  6. Выпекайте около 20 минут, пока маффины не станут упругими и золотистыми, затем остудите на решетке.

### Rank 14: `r209_kinoa_gado_gado_s_ovoschami_i_ostrym_arahisovym_sousom` - Киноа гадо-гадо с овощами и острым арахисовым соусом
- recipe no: r209; score: 128; new r401-r610: no
- why suspicious: missing approximate/user-friendly measure: 2; e.g. Кремовая арахисовая паста — 40 г; tiny/zero gram anomaly: `sriracha` has suspiciously tiny quantity 2.5 g; ingredient in list not named in steps: 1 (red_beans)
- suggested decision: F. needs user decision (verify tiny quantity/measure)
- ingredients:
  - 1. Белая или красная киноа — 40 г (`quinoa`; grams=40)
  - 2. Вода для киноа — 120 мл (`water`; grams=120)
  - 3. Стручковая фасоль, очищенная — 60 г (`red_beans`; grams=60)
  - 4. Красный сладкий перец — 40 г (`bell_pepper`; grams=40)
  - 5. Ростки маша — 40 г (`mung_sprouts`; grams=40)
  - 6. Краснокочанная капуста — 30 г (`red_cabbage`; grams=30)
  - 7. Морковь — 80 г (`carrot`; grams=80)
  - 8. Кремовая арахисовая паста — 40 г (`peanut_butter`; grams=40)
  - 9. Тамари или соевый соус — 8 мл (`soy_sauce`; grams=9.28)
  - 10. Кленовый сироп — 20 г (`maple_syrup`; grams=20)
  - 11. Сок лайма — 22 мл (`lime_juice`; grams=22.66)
  - 12. Чили-чесночный соус — 2,5 г (`sriracha`; grams=2.5)
  - 13. Вода для арахисового соуса — 30 мл (`water`; grams=30)
  - 14. Кинза нарезанная — 8 г (`cilantro`; grams=8)
  - 15. Лайм — 35 г (`lime_juice`; grams=35)
  - 16. Хлопья красного перца — 0,5 г (`red_pepper_flakes`; grams=0.5)
- instruction steps:
  1. Поставьте маленькую кастрюлю на средний огонь, всыпьте промытую киноа и прогревайте 3-4 минуты, помешивая, чтобы зерна подсохли и стали ореховыми на запах.
  2. Влейте 1 стакан воды для киноа, доведите до слабого кипения, накройте и варите 18-20 минут, пока жидкость не впитается.
  3. Разрыхлите киноа вилкой.
  4. Приготовьте стручковую фасоль на пару около 4 минут, затем быстро охладите холодной водой, чтобы она сохранила цвет и упругость.
  5. В миске взбейте арахисовую пасту, тамари или соевый соус, кленовый сироп, сок лайма, чили-чесночный соус и 4 ст. л. воды для арахисового соуса до густой, но текучей заправки.
  6. Разложите киноа по двум мискам.
  7. Добавьте стручковую фасоль, красный перец, ростки маша, краснокочанную капусту, морковь и кинзу.
  8. Полейте боулы арахисовым соусом, посыпьте хлопьями красного перца и подайте с дольками лайма.

### Rank 15: `r452_makarony_s_kuritsey_i_ovoschami_na_skovorode` - Макароны с курицей и овощами на сковороде
- recipe no: r452; score: 122; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 4 (bell_pepper, tomato, greens, garlic); truncation/fragment/weak finish: 1; e.g. Добавьте нарезанный сельдерей и снова накройте крышкой; 4 ingredients in list are not named in steps; extra ranking weight: transferred range r401-r610
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. курица — 120 г (`chicken_breast`; grams=120)
  - 2. макароны — 80 г (`poppy_seed`; grams=80)
  - 3. лук репчатый — 1/2 шт (`onion`; grams=40)
  - 4. морковь — 1/2 шт (`carrot`; grams=40)
  - 5. болгарский перец — 1/4 шт (`bell_pepper`; grams=38)
  - 6. помидор — 1/2 шт (`tomato`; grams=50)
  - 7. сельдерей — 1/2 ч. л. (`celery`; grams=2)
  - 8. зелень — 5 г (`greens`; grams=5)
  - 9. чеснок — 1 зубчик (`garlic`; grams=4)
  - 10. соль, специи — по вкусу (`salt`; grams=0.5)
  - 11. растительное масло — 5 г для сковороды (`vegetable_oil`; grams=5)
- instruction steps:
  1. Разогрейте растительное масло на сковороде, спассеруйте лук, затем добавьте нарезанную кубиками морковь и обжарьте 2-3 минуты.
  2. Одновременно поставьте на огонь кастрюлю для макарон.
  3. Нарежьте куриное филе кусочками, отправьте в сковороду, перемешайте и обжарьте 10 минут под крышкой.
  4. Добавьте нарезанный сельдерей и снова накройте крышкой.

### Rank 16: `r480_myaso_po_tayski_s_lapshoy` - Мясо по-тайски с лапшой
- recipe no: r480; score: 122; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 4 (pork_tenderloin, udon_noodles, broccoli, ginger); truncation/fragment/weak finish: 1; e.g. Лапшу сварите по инструкции на упаковке; 4 ingredients in list are not named in steps; extra ranking weight: transferred range r401-r610
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. свиная вырезка (тонкими полосками) — 100 г (`pork_tenderloin`; grams=100)
  - 2. лапша удон (generic udon noodles) — 40 г (`udon_noodles`; grams=40)
  - 3. морковь (соломкой) — 40 г (`carrot`; grams=40)
  - 4. брокколи (соцветиями) — 40 г (`broccoli`; grams=40)
  - 5. лук репчатый (полукольцами) — 30 г (`onion`; grams=30)
  - 6. имбирь свежий (натереть) — 5 г (`ginger`; grams=5)
  - 7. растительное масло (для жарки) — 5 мл (`vegetable_oil`; grams=5)
  - 8. кунжутное масло — 5 мл (`sesame_oil`; grams=5)
  - 9. соевый соус — 15 мл (`soy_sauce`; grams=15)
  - 10. рисовый уксус — 5 мл (`vinegar`; grams=5)
  - 11. сахар — 1/2 ч. л. (`sugar`; grams=2)
  - 12. кинза (для подачи) — 3 г (`cilantro`; grams=3)
- instruction steps:
  1. Свинину нарежьте тонкими полосками.
  2. Разогрейте растительное масло и обжарьте свинину на сильном огне.
  3. Добавьте в сковороду имбирь, морковь, лук и продолжайте жарить все ингредиенты на сильном огне ещё около 5 минут.
  4. Добавьте соевый соус, кунжутное масло, уксус и сахар.
  5. Перемешайте, убавьте огонь до среднего и готовьте ещё 2-3 минуты.
  6. Лапшу сварите по инструкции на упаковке.

### Rank 17: `r015_morkovnaya_ovsyanaya_kasha_v_stile_morkovnogo_piroga` - Морковная овсяная каша в стиле морковного пирога
- recipe no: r015; score: 119; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 3 (milk, peanut_butter, honey); missing approximate/user-friendly measure: 1; e.g. миндальная или другая ореховая паста — 5 г; user-reported peanut-butter tiny amount: 5 g at ingredient line 7
- suggested decision: F. needs user decision (verify tiny quantity/measure)
- ingredients:
  - 1. морковь — 0,67 небольшие шт., натереть (`carrot`; grams=46.9)
  - 2. овсяные хлопья для каши — 60 г (`oats`; grams=60)
  - 3. молотая корица — 0,33 ч. л. (`cinnamon`; grams=0.86)
  - 4. мускатный орех — 0,17 г, свеженатертый (`nutmeg`; grams=0.17)
  - 5. изюм — 25 г (`raisins`; grams=25)
  - 6. молоко — 300 мл (`milk`; grams=309)
  - 7. миндальная или другая ореховая паста — 5 г (`peanut_butter`; grams=5)
  - 8. мед — 6,67 г (`honey`; grams=6.67)
- instruction steps:
  1. В кастрюле соедините морковь, овсяные хлопья, корицу, мускатный орех, изюм, 283,5 мл молока и ореховую пасту.
  2. Варите на среднем огне 10–15 минут, часто помешивая, пока морковь не станет мягкой, а каша кремовой.
  3. Если каша густеет слишком быстро, влейте часть оставшихся 16,7 мл молока.
  4. Разложите по тарелкам, полейте медом и подавайте теплой.

### Rank 18: `r093_nut_s_pertsem_tomatami_i_zharenym_tofu` - Нут с перцем, томатами и жареным тофу
- recipe no: r093; score: 114; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 3 (tomato_paste, vegetable_broth, oregano); steps mention ingredient missing from list: soy_sauce; missing approximate/user-friendly measure: 1; e.g. томатная паста — 7,5 г
- suggested decision: C. add missing ingredient/step
- ingredients:
  - 1. оливковое масло — 7,5 мл (`olive_oil`; grams=6.83)
  - 2. репчатый лук — 80 г, тонко нарезать (`onion`; grams=80)
  - 3. оранжевый сладкий перец — 0,25 шт., нарезать полосками (`bell_pepper`; grams=37.5)
  - 4. красный чили — 0,25 шт., нарезать (`chili_pepper`; grams=11.25)
  - 5. рубленые томаты в собственном соку — 100 г (`tomato`; grams=100)
  - 6. томатная паста — 7,5 г (`tomato_paste`; grams=7.5)
  - 7. овощной бульонный порошок — 0,5 ч. л. (`vegetable_broth`; grams=2.5)
  - 8. сушеный орегано — 0,25 ч. л. (`oregano`; grams=0.25)
  - 9. копченая паприка — 0,12 г (`paprika`; grams=0.12)
  - 10. консервированный нут — 0,5 банки по 400 г, вместе с жидкостью (`chickpeas`; grams=400)
  - 11. экстра-твердый тофу — 70 г, нарезать ломтиками (`tofu`; grams=70)
  - 12. соевый йогурт — 60 г (`greek_yogurt`; grams=60)
  - 13. чеснок — 0,5 зубчика, мелко натереть (`garlic`; grams=2.5)
  - 14. петрушка — 1 ст. л., нарубить (`parsley`; grams=4)
- instruction steps:
  1. В глубокой сковороде разогрейте 3,75 мл оливкового масла, добавьте лук, накройте и готовьте 5 минут.
  2. Снимите крышку, перемешайте лук, добавьте сладкий перец, чили, рубленые томаты, томатную пасту, бульонный порошок, орегано, 0,25 ч. л. копченой паприки и нут вместе с жидкостью.
  3. Накройте и тушите 15–20 минут, пока соус слегка не загустеет.
  4. На другой сковороде разогрейте оставшееся масло и обжарьте ломтики тофу с двух сторон до легкой золотистости.
  5. Смешайте соевый йогурт с натертым чесноком.
  6. Разложите горячий нутовый соус по тарелкам, сверху положите тофу, добавьте чесночный йогурт, петрушку и щепотку копченой паприки.

### Rank 19: `r225_zapekanka_s_tuntsom_yaichnoy_lapshoy_goroshkom_i_hrust` - Запеканка с тунцом, яичной лапшой, горошком и хрустящей крошкой
- recipe no: r225; score: 114; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 8 (egg_noodles, wheat_flour, chicken_broth, milk, tuna, green_peas, cottage_cheese, parmesan); missing approximate/user-friendly measure: 2; e.g. твороговочные сухари панко — 30 г; 8 ingredients in list are not named in steps
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. яичная лапша — 55 г (`egg_noodles`; grams=55)
  - 2. Соль — 1 г (`salt`; grams=1)
  - 3. Черный перец — 0,5 г (`black_pepper`; grams=0.5)
  - 4. сливочное масло — 11 мл (`butter`; grams=11)
  - 5. лук — 12 г (`onion`; grams=12)
  - 6. сельдерей — 20 г (`celery`; grams=20)
  - 7. шампиньоны — 55 г (`mushrooms`; grams=55)
  - 8. мука — 11 мл (`wheat_flour`; grams=11)
  - 9. куриный бульон — 120 мл (`chicken_broth`; grams=120)
  - 10. молоко — 60 мл (`milk`; grams=61.8)
  - 11. тунец в воде — 70 г (`tuna`; grams=70)
  - 12. замороженный зеленый горошек — 40 г (`green_peas`; grams=40)
  - 13. твороговочные сухари панко — 30 г (`cottage_cheese`; grams=30)
  - 14. пармезан — 14 г (`parmesan`; grams=14)
  - 15. оливковое масло — 8 мл (`olive_oil`; grams=7.28)
- instruction steps:
  1. Разогрейте духовку до 220 °C.
  2. Отварите яичную лапшу в подсоленной воде на 1–2 минуты меньше, чем указано на упаковке, и слейте.
  3. В большой сковороде растопите сливочное масло, добавьте лук, сельдерей и шампиньоны, посолите и поперчите.
  4. Готовьте 6–8 минут, пока овощи не станут мягкими, а грибы не выпустят влагу.

### Rank 20: `r515_salat_s_grechkoy_ovoschami_i_fetoy` - Салат с гречкой, овощами и фетой
- recipe no: r515; score: 105; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 5 (cucumber, tomato, bell_pepper, feta, lemon_juice); missing approximate/user-friendly measure: 1; e.g. фета — 50 г; 5 ingredients in list are not named in steps; extra ranking weight: transferred range r401-r610
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. гречка — 60 г (`buckwheat`; grams=60)
  - 2. огурец — 1 шт. (`cucumber`; grams=100)
  - 3. помидор — 1 шт. (`tomato`; grams=100)
  - 4. болгарский перец — 0,5 шт. (`bell_pepper`; grams=60)
  - 5. фета — 50 г (`feta`; grams=50)
  - 6. зелень — по вкусу (`greens`; grams=5)
  - 7. оливковое масло — 5 г (`olive_oil`; grams=5)
  - 8. лимонный сок — 10 г (`lemon_juice`; grams=10)
- instruction steps:
  1. Гречку отварите по инструкции на упаковке до мягкости и остудите до теплой.
  2. Овощи нарежьте небольшими кусочками, зелень измельчите, фету раскрошите.
  3. Смешайте гречку с овощами, зеленью и фетой.
  4. Заправьте оливковым маслом и лимонным соком, затем подавайте.

### Rank 21: `r498_pasta_s_konservirovannym_tuntsom_i_tomatami` - Паста с консервированным тунцом и томатами
- recipe no: r498; score: 104; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 3 (tomato, passata, vinegar); missing approximate/user-friendly measure: 2; e.g. паста — 80 г; truncation/fragment/weak finish: 1; e.g. Добавьте еще 4—5 столовых ложек воды из-под пасты, тщательно перемешайте; extra ranking weight: transferred range r401-r610
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. паста — 80 г (`whole_wheat_pasta`; grams=80)
  - 2. помидоры черри (половинками; maps to tomato policy) — 75 г (`tomato`; grams=75)
  - 3. пассата — 75 г (`passata`; grams=75)
  - 4. тунец консервированный (без жидкости) — 50 г (`tuna`; grams=50)
  - 5. оливковое масло — 8 мл (`olive_oil`; grams=8)
  - 6. сливочный сыр — 10 г (`cream_cheese`; grams=10)
  - 7. рисовый уксус — 5 мл (`vinegar`; grams=5)
  - 8. соль, сахар, чили — по вкусу (`salt`; grams=0.5)
- instruction steps:
  1. Налейте воду в кастрюлю, добавьте соль из расчета 10 г на 1 литр, поставьте на огонь.
  2. Поставьте таймер: варить нужно на 2—3 минуты меньше, чем указано в инструкции на упаковке.
  3. Добавьте к томатному соусу сливочный сыр и 3—4 столовые ложки воды из-под пасты.
  4. Добавьте тунец, разделите лопаткой на кусочки, перемешайте и потомите соус еще пару минут.
  5. Добавьте еще 4—5 столовых ложек воды из-под пасты, тщательно перемешайте.

### Rank 22: `r357_listya_romena_s_mango_tsukini_edamame_i_imbirno_soevym` - Листья ромэна с манго, цукини, зеленым горошком и имбирно-соевым дипом
- recipe no: r357; score: 100; new r401-r610: no
- why suspicious: ingredient in list not named in steps: 5 (green_onion, shishito_pepper, mint, green_peas, ginger); truncation/fragment/weak finish: 1; e.g. Добавьте на каждый лист несколько капель шрирачи, выжмите лайм из долек прямо перед едой и ешьте как открытые салатные чашечки; 5 ingredients in list are not named in steps
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. листья ромэна — 4,5 шт. (`lettuce`; grams=1350)
  - 2. цукини — 100 г (`zucchini`; grams=100)
  - 3. манго — 0,2 шт. (`mango`; grams=40)
  - 4. редис — 1,5 шт. (`radish`; grams=27)
  - 5. зеленый лук — 18 г (`green_onion`; grams=18)
  - 6. тайский красный перец — 75 г (`shishito_pepper`; grams=75)
  - 7. свежая мята — 2,5 г (`mint`; grams=2.5)
  - 8. зеленый горошек — 70 г (`green_peas`; grams=70)
  - 9. лайм — 35 г (`lime_juice`; grams=35)
  - 10. шрирача — 5 мл (`sriracha_extra`; grams=6)
  - 11. соевый соус — 30 мл (`soy_sauce`; grams=34.8)
  - 12. рисовый уксус — 22 мл (`vinegar`; grams=22)
  - 13. свежий имбирь — 2,5 мл (`ginger`; grams=2.5)
  - 14. мед — 5 мл (`honey`; grams=7.1)
  - 15. кунжутное масло — 0,5 мл (`sesame_oil`; grams=0.46)
- instruction steps:
  1. В небольшой миске смешайте соевый соус, рисовый уксус, натертый имбирь, мед, кунжутное масло и половину нарезанного тайского перца.
  2. Разложите листья ромэна на большом блюде.
  3. Наполните каждый лист соломкой цукини, ломтиками манго, редисом, зеленым луком, оставшимся тайским перцем, листьями мяты и зеленым горошком.
  4. Полейте начинку частью имбирно-соевого дипа или подайте дип рядом.
  5. Добавьте на каждый лист несколько капель шрирачи, выжмите лайм из долек прямо перед едой и ешьте как открытые салатные чашечки.

### Rank 23: `r491_kartofelnye_zrazy_s_belymi_gribami` - Картофельные зразы с белыми грибами
- recipe no: r491; score: 100; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 5 (allspice, thyme, wheat_flour, breadcrumbs, onion); 5 ingredients in list are not named in steps; extra ranking weight: transferred range r401-r610
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. картофель — 1/2 шт (`potato`; grams=60)
  - 2. соль — 1 г (`salt`; grams=1)
  - 3. душистый перец — 1 г (`allspice`; grams=1)
  - 4. тимьян — 1 г (`thyme`; grams=1)
  - 5. мука рисовая — 5 г (`wheat_flour`; grams=5)
  - 6. панировочные сухари — 1/2 ст. л. (`breadcrumbs`; grams=8)
  - 7. шампиньоны (белые грибы для начинки) — 50 г (`mushrooms`; grams=50)
  - 8. лук репчатый — 1/4 шт (`onion`; grams=20)
  - 9. шампиньоны — 25 г (`mushrooms`; grams=25)
  - 10. чеснок свежий — 1/4 зубчик (`garlic`; grams=1)
  - 11. соль — по вкусу (`salt`; grams=0.5)
  - 12. перец чёрный молотый — по вкусу (`black_pepper`; grams=0.3)
  - 13. укроп свежий — 3 г (`dill`; grams=3)
  - 14. масло растительное для жарки — 1/4 ст. л. (`butter`; grams=3)
- instruction steps:
  1. Картофель почистите и запеките в духовке при 180 °C в течение 25 минут.
  2. Шампиньоны и размороженные белые грибы нарежьте мелким кубиком, добавьте к луку и жарьте ещё 10—12 минут.
  3. Добавьте к грибам и луку измельчённый чеснок и специи, снимите с огня и дайте остыть до комнатной температуры.
  4. Добавьте к остывшей начинке рубленый укроп.
  5. Из каждого шарика сформируйте что-то вроде лодочки, положите в центр столовую ложку начинки и защипните края, как у пирожка.
  6. Обваляйте зразы в панировочных сухарях и обжарьте на растительном масле до золотистой корочки.

### Rank 24: `r540_zapechennyy_hek_s_ovoschami` - Запеченный хек с овощами
- recipe no: r540; score: 100; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 5 (white_fish, carrot, onion, tomato, bell_pepper); 5 ingredients in list are not named in steps; extra ranking weight: transferred range r401-r610
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. филе минтая — 170 г (`white_fish`; grams=170)
  - 2. морковь — 60 г (`carrot`; grams=60)
  - 3. лук — 40 г (`onion`; grams=40)
  - 4. томаты — 120 г (`tomato`; grams=120)
  - 5. масло — 5 г (`vegetable_oil`; grams=5)
  - 6. лимонный сок — 10 г (`lemon_juice`; grams=10)
  - 7. соль — по вкусу (`salt`; grams=0)
  - 8. сладкий перец — 80 г (`bell_pepper`; grams=80)
- instruction steps:
  1. Выложите овощи в форму, сверху положите рыбу.
  2. Добавьте лимонный сок, специи и немного масла.
  3. Запекайте 25-30 минут.

### Rank 25: `r538_lenivye_golubtsy` - Ленивые голубцы с говяжьим фаршем
- recipe no: r538; score: 99; new r401-r610: yes
- why suspicious: ingredient in list not named in steps: 3 (onion, carrot, tomato_paste); truncation/fragment/weak finish: 1; e.g. Потушите 30 минут; missing approximate/user-friendly measure: 1; e.g. томатная паста — 65 г; extra ranking weight: transferred range r401-r610
- suggested decision: D. rewrite steps for completeness
- ingredients:
  - 1. говяжий фарш — 130 г (`ground_meat`; grams=130)
  - 2. капуста — 130 г (`cabbage`; grams=130)
  - 3. рис — 50 г (отварной) (`rice`; grams=50)
  - 4. лук — 40 г (`onion`; grams=40)
  - 5. морковь — 60 г (`carrot`; grams=60)
  - 6. томатная паста — 65 г (`tomato_paste`; grams=65)
  - 7. вода — 150 мл (`water`; grams=150)
  - 8. растительное масло — 5 г для сковороды (`vegetable_oil`; grams=5)
- instruction steps:
  1. Смешайте говяжий фарш, рис и мелко нарезанную капусту.
  2. Сформируйте крупные котлеты или выложите массу в сковороду с растительным маслом и томатным соусом.
  3. Потушите 30 минут.

## User-Reported Examples

### Hummus / хумус
- status: no current title-hummus recipe was found where ingredients/steps fail to support hummus after checking hummus, chickpea/tahini/bean, and preparation context.
- title-hummus recipes checked: 13; any hummus context hits across recipes: 18
- `r262` `r262_pita_s_humusom_i_kuritsey` - Пита с хумусом и курицей (support: yes)
  - ingredient/base context: Хумус — 50 г
  - step context: Смажьте хумусом, добавьте курицу, огурец, помидор, салат и лимонный сок.
- `r271` `r271_klassicheskiy_humus_s_hrustyaschimi_pitta_chipsami` - Классический хумус с хрустящими питта-чипсами (support: yes)
  - ingredient/base context: консервированный нут — 55 г
  - step context: Смажьте противень небольшим количеством оливкового масла, разложите питту в один слой и запекайте около 10 минут до хруста; остудите. В чашу комбайна положите нут, кумин, чеснок, лимонный сок и оставшееся оливковое масло. Если хумус густой, добавляйте воду по 1 ст. л., пока он не станет гладким и удобным для макания. Переложите хумус в миску и подавайте с питта-чипсами.
- `r272` `r272_humus_iz_ovoschey_gril_s_pittoy_i_krudite` - Хумус из овощей гриль с питтой и крудите (support: yes)
  - ingredient/base context: консервированный нут — 100 г
  - step context: Отложите 2 ст. л. нута для подачи. Положите овощи гриль, остальной нут, чеснок и лимонный сок в комбайн, посолите и поперчите. Измельчите до густого однородного хумуса; при необходимости соскребите массу со стенок чаши и пробейте еще раз. Переложите хумус в миску, сверху добавьте отложенный нут и полейте оливковым маслом.
- `r273` `r273_zelenyy_humus_s_bazilikom_petrushkoy_i_ovoschnymi_palo` - Зеленый хумус с базиликом, петрушкой и овощными палочками (support: yes)
  - ingredient/base context: консервированный нут вместе с жидкостью — 55 г
  - step context: Перелейте нут с жидкостью в небольшую кастрюлю, добавьте целые зубчики чеснока и прогрейте 4–5 минут на слабом кипении. В блендер положите зеленый лук, базилик, петрушку, лимонный сок, оливковое масло и воду, измельчите до ярко-зеленой смеси. Слейте нут и чеснок, добавьте их в блендер вместе с йогуртом и морской солью. Взбейте до кремовой текстуры, подливая еще немного воды, если блендеру трудно работать. Подавайте хумус с овощными палочками.
- `r274` `r274_humus_s_pechenym_pertsem_gretskim_orehom_i_ovoschnymi_` - Хумус с печеным перцем, грецким орехом и овощными палочками (support: yes)
  - ingredient/base context: консервированный нут — 200 г
  - step context: Положите нут, чеснок, печеный красный перец, греческий йогурт и лимонный сок в чашу блендера или комбайна. Разложите хумус по двум контейнерам или мискам и подавайте с палочками цукини, моркови и сельдерея.
- `r276` `r276_humus_iz_chernoy_fasoli_s_listyami_aysberga` - Хумус из черной фасоли с листьями айсберга (support: yes)
  - ingredient/base context: вареная черная фасоль — 45 г
  - step context: Положите черную фасоль, чеснок, оливковое масло, лимонный сок, белый винный уксус и кумин в комбайн. Оставьте дип на 15 минут, чтобы кислота и специи раскрылись. Разложите клинья айсберга на тарелке и подавайте их как свежие хрустящие дипперы к хумусу из черной фасоли.
- `r356` `r356_pita_s_humusom_morkovyu_kartofelem_i_fetoy` - Пита с хумусом, морковью, картофелем и фетой (support: yes)
  - ingredient/base context: Хумус — 60 г
  - step context: Морковь и картофель нарежьте кубиками, смешайте с маслом, паприкой и солью, запеките при 200 °C около 20 минут. Разрежьте питу, добавьте хумус, овощи, фету и салат.
- `r359` `r359_tsvetnye_salatnye_chashechki_s_humusom_lapshoy_soba_i_` - Цветные салатные чашечки с хумусом, лапшой соба и быстрыми маринованными овощами (support: yes)
  - ingredient/base context: хумус — 45 г
  - step context: Смешайте морковь с редисом, уксусом и щепоткой соли, оставьте мариноваться на 10 минут. В каждый лист положите хумус, лапшу соба, маринованные овощи, огурец и зеленый лук.
- `r489` `r489_rulet_iz_lavasha_s_humusom` - Рулет из лаваша с хумусом и томатами (support: yes)
  - ingredient/base context: хумус — 100 г
  - step context: Намажьте лаваш хумусом.
- `r580` `r580_tost_s_humusom_i_zapechennym_pertsem` - Тост с хумусом и запечённым перцем (support: yes)
  - ingredient/base context: хумус — 80 г
  - step context: Подсушите хлеб 1-2 минуты до легкого хруста. Намажьте хумус ровным слоем.
- `r604` `r604_lavash_s_humusom_zapechennym_pertsem_i_syrom` - Лаваш с хумусом, запечённым перцем и сыром (support: yes)
  - ingredient/base context: хумус — 2 ст. л.
  - step context: Лаваш смажьте хумусом ровным слоем. Запеченный перец нарежьте полосками, сыр распределите поверх хумуса, добавьте зелень. Прогрейте на сухой сковороде 2-3 минуты с каждой стороны до хрустящей корочки.
- `r640` `r640_rulet_iz_lavasha_s_humusom` - Рулет из лаваша с хумусом (support: yes)
  - ingredient/base context: хумус — 80 г
  - step context: Лаваш намажьте хумусом.
- `r658` `r658_svekolnyy_humus_s_ovoschami` - Свекольный хумус с овощами (support: yes)
  - ingredient/base context: нут вареный — 80 г; тахини — 20 г
  - step context: Запеченную свеклу очистите и пробейте в блендере с нутом, тахини, лимонным соком, чесноком и специями.
- related non-title warning `r595_lavash_s_gorbushey_i_ovoschami` - Лаваш с горбушей и овощами
  - ingredient context: хумус — 80 г
  - step context: Лаваш смажьте хумусом или постным майонезом тонким слоем.

### Harissa / харисса
- status: not present in current curated recipes, recipe ingredients, or food catalog after rerunning the audit.

### American cheese / american_cheese
- status: not present in current curated recipes, recipe ingredients, or food catalog after rerunning the audit.

### Peanut butter tiny amount cases
- status: 4 current recipes have `peanut_butter` at <=5 g. These are user-reported ranking boosts, not recipe edits.
- `r015` `r015_morkovnaya_ovsyanaya_kasha_v_stile_morkovnogo_piroga` - Морковная овсяная каша в стиле морковного пирога
  - ingredient context: line 7: миндальная или другая ореховая паста — 5 г (`peanut_butter`, grams=5)
  - step context: В кастрюле соедините морковь, овсяные хлопья, корицу, мускатный орех, изюм, 283,5 мл молока и ореховую пасту.
- `r034` `r034_pankeyki_na_protivne_s_chetyrmya_toppingami` - Панкейки на противне с четырьмя топпингами
  - ingredient context: line 10: арахисовая паста — 2,5 г (примерно 1/2 ч. л.) (`peanut_butter`, grams=2.5)
  - step context: Арахисовую пасту слегка прогрейте до текучести, а сливочный сыр разотрите с сахаром. Распределите тесто по противню: в один угол вмешайте арахисовую пасту и банан, во второй насыпьте мелко нарезанный темный шоколад, в третий — малину, в четвертый — чернику и ложечки сливочного сыра.
- `r062` `r062_veganskie_myusli_maffiny_s_yablokom_i_pekanom` - Веганские мюсли-маффины с яблоком и пеканом
  - ingredient context: line 8: ореховая паста — 3,75 г (2,5 г в тесто + 1,25 г сверху) (`peanut_butter`, grams=3.75)
  - step context: Отдельно соедините соевое молоко, тертое яблоко, масло бульонградной косточки и 2,5 г ореховой пасты. Оставшиеся 4,17 г мюсли разотрите с демерарой, 1,25 г ореховой пасты и рубленым пеканом, распределите эту крошку поверх маффинов.
- `r598` `r598_ovsyanka_s_bananom_i_arahisovoy_pastoy` - Овсянка с бананом и арахисовой пастой
  - ingredient context: line 4: арахисовая паста — 1 ч. л. (`peanut_butter`, grams=5)
  - step context: Снимите кашу с огня, добавьте банан и арахисовую пасту, перемешайте до кремовой текстуры.

### Weird measure / zero quantity examples
- status: 1 zero-quantity warning remains.
- `r607_syrnye_lepeshki` - Сырные лепёшки: `baking_powder` has 0 g without an obvious intentional marker Evidence: разрыхлитель — 0 ч. л.

## Recommended Fix Batch
1. `r115` `r115_govyazhi_frikadelki_v_souse_iz_krasnoy_fasoli_souse_s_` - Говяжьи фрикадельки в соусе из красной фасоли соусе с лапшой: ingredient in list not named in steps: 4 (whole_grain_bread, egg_noodles, stir_fry_vegetables, mint); title keyword missing from ingredients/steps: title contains `beans`, but expected ingredient/clear preparation was not found; missing approximate/user-friendly measure: 1; e.g. соус из черных бобов — 30 г; 4 ingredients in list are not named in steps Suggested decision: F. needs user decision (rename recipe vs add missing ingredient/step).
2. `r171` `r171_spagetti_boloneze_s_govyadinoy_i_svininoy` - Спагетти болоньезе с говядиной и свининой: ingredient in list not named in steps: 2 (tomato_paste, oregano); title keyword missing from ingredients/steps: title contains `pork`, but expected ingredient/clear preparation was not found Suggested decision: F. needs user decision (rename recipe vs add missing ingredient/step).
3. `r607` `r607_syrnye_lepeshki` - Сырные лепёшки: ingredient in list not named in steps: 1 (wheat_flour); tiny/zero gram anomaly: `baking_powder` has 0 g without an obvious intentional marker; missing approximate/user-friendly measure: 1; e.g. сыр гауда — 50 г; extra ranking weight: transferred range r401-r610 Suggested decision: F. needs user decision (correct zero/tiny quantity).
4. `r595` `r595_lavash_s_gorbushey_i_ovoschami` - Лаваш с горбушей и овощами: ingredient in list not named in steps: 3 (cucumber, lettuce, carrot); steps mention ingredient missing from list: mayonnaise; missing approximate/user-friendly measure: 1; e.g. хумус — 80 г; extra ranking weight: transferred range r401-r610 Suggested decision: C. add missing ingredient/step.
5. `r093` `r093_nut_s_pertsem_tomatami_i_zharenym_tofu` - Нут с перцем, томатами и жареным тофу: ingredient in list not named in steps: 3 (tomato_paste, vegetable_broth, oregano); steps mention ingredient missing from list: soy_sauce; missing approximate/user-friendly measure: 1; e.g. томатная паста — 7,5 г Suggested decision: C. add missing ingredient/step.
6. `r280` `r280_baba_ganush_s_teploy_pittoy_i_ovoschami` - Баба гануш с теплой питтой и овощами: ingredient in list not named in steps: 1 (greek_yogurt); steps mention ingredient missing from list: tahini; missing approximate/user-friendly measure: 1; e.g. чеснок — 3 г Suggested decision: C. add missing ingredient/step.
7. `r034` `r034_pankeyki_na_protivne_s_chetyrmya_toppingami` - Панкейки на противне с четырьмя топпингами: ingredient in list not named in steps: 4 (wheat_flour, peanut_butter, blueberries); 4 ingredients in list are not named in steps; user-reported peanut-butter tiny amount: 2.5 g at ingredient line 10 Suggested decision: F. needs user decision (verify tiny quantity/measure).
8. `r474` `r474_kurinye_kotlety_s_kabachkom` - Куриные котлеты с кабачком: ingredient in list not named in steps: 6 (chicken_ground, zucchini, carrot, egg, garlic, mustard); truncation/fragment/weak finish: 1; e.g. Обжаривайте до золотистой корочки; 6 ingredients in list are not named in steps; extra ranking weight: transferred range r401-r610 Suggested decision: D. rewrite steps for completeness.
9. `r577` `r577_ovsyanye_shariki` - Овсяные шарики: ingredient in list not named in steps: 5 (oats, peanut_butter, honey, cocoa_powder, sunflower_seeds); truncation/fragment/weak finish: 1; e.g. Уберите в холодильник на 30 минут, чтобы они стали плотнее; 5 ingredients in list are not named in steps; extra ranking weight: transferred range r401-r610 Suggested decision: D. rewrite steps for completeness.
10. `r225` `r225_zapekanka_s_tuntsom_yaichnoy_lapshoy_goroshkom_i_hrust` - Запеканка с тунцом, яичной лапшой, горошком и хрустящей крошкой: ingredient in list not named in steps: 8 (egg_noodles, wheat_flour, chicken_broth, milk, tuna, green_peas, cottage_cheese, parmesan); missing approximate/user-friendly measure: 2; e.g. твороговочные сухари панко — 30 г; 8 ingredients in list are not named in steps Suggested decision: D. rewrite steps for completeness.

No fixes were made in this pack; these are candidates for user triage before any recipe edits.
