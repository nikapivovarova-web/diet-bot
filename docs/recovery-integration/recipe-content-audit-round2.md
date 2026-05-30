# Recipe Content Audit Round 2

Audit-only stage. The script reads curated JSON data and writes findings only; it does not change recipe/data content.

## Summary

- total recipes checked: 665
- total ingredients checked: 6130
- total foods checked: 359
- total nutrition rows checked: 665
- blocking findings count: 0
- warning findings count: 1221
- full CSV findings: `docs/recovery-integration/recipe-content-audit-round2-findings.csv`

## Counts By Finding Type

| finding type | blockers | warnings | total |
|---|---:|---:|---:|
| title/ingredient mismatch | 0 | 0 | 0 |
| ingredient missing from steps | 0 | 917 | 917 |
| steps mention missing ingredient | 0 | 0 | 0 |
| truncation/fragments | 0 | 171 | 171 |
| non-CIS/unclear ingredients | 0 | 0 | 0 |
| tiny gram anomalies | 0 | 0 | 0 |
| missing approximate measures | 0 | 133 | 133 |

## Known Blocker Search Summary

- `hummus` hits across curated recipes/ingredients/foods: 74
- `harissa` hits across curated recipes/ingredients/foods: 0
- `american_cheese` hits across curated recipes/ingredients/foods: 0
- `edamame` hits across curated recipes/ingredients/foods: 0
- `peanut_paste` hits across curated recipes/ingredients/foods: 54

## Required Top-Blocker Triage

- hummus recipe: no blockers, 0 warnings in title/ingredient and step-missing hummus checks.
- harissa recipe: no blockers, 0 warnings in harissa known-search/non-CIS checks.
- broken step fragments: no blockers, 0 warnings in empty/short/standalone fragment checks.
- severe title/ingredient mismatch: 0 blockers, 0 warnings.

## Top Blockers Requiring Next-Stage Fix

- none

## Findings By Type


### Title/Ingredient Mismatch

- none

### Ingredient Missing From Steps

- `warning` `ingredient_not_named_in_steps` r001 `r001_ovsyanka_na_noch_s_yagodami` `oats` line 1: `oats` is in ingredients but not found in instructions by known aliases Evidence: Овсяные хлопья — 50 г
- `warning` `ingredient_not_named_in_steps` r001 `r001_ovsyanka_na_noch_s_yagodami` `peanut_butter` line 5: `peanut_butter` is in ingredients but not found in instructions by known aliases Evidence: Ореховая паста — 8 г (≈1/2 ст. л.)
- `warning` `ingredient_not_named_in_steps` r002 `r002_tost_s_avokado` `lemon_juice` line 2: `lemon_juice` is in ingredients but not found in instructions by known aliases Evidence: Лимонный сок — 10–15 г (из 1/2 лимона)
- `warning` `ingredient_not_named_in_steps` r002 `r002_tost_s_avokado` `whole_grain_bread` line 4: `whole_grain_bread` is in ingredients but not found in instructions by known aliases Evidence: Хлеб на закваске — 2 ломтика / ≈80–100 г
- `warning` `ingredient_not_named_in_steps` r003 `r003_shakshuka` `chili_pepper` line 3: `chili_pepper` is in ingredients but not found in instructions by known aliases Evidence: Красный перец чили — 0,5 шт. / ≈5 г
- `warning` `ingredient_not_named_in_steps` r004 `r004_bananovo_ovsyanye_pankeyki` `egg` line 2: `egg` is in ingredients but not found in instructions by known aliases Evidence: Яйца — 1 шт.
- `warning` `ingredient_not_named_in_steps` r004 `r004_bananovo_ovsyanye_pankeyki` `oats` line 4: `oats` is in ingredients but not found in instructions by known aliases Evidence: Овсяные хлопья — 50 г
- `warning` `ingredient_not_named_in_steps` r004 `r004_bananovo_ovsyanye_pankeyki` `berries` line 9: `berries` is in ingredients but not found in instructions by known aliases Evidence: Фрукты или ягоды — 40–60 г
- `warning` `ingredient_not_named_in_steps` r005 `r005_chia_puding` `chia_seeds` line 1: `chia_seeds` is in ingredients but not found in instructions by known aliases Evidence: Семена чиа — 24 г (≈2 ст. л.)
- `warning` `ingredient_not_named_in_steps` r005 `r005_chia_puding` `maple_syrup` line 3: `maple_syrup` is in ingredients but not found in instructions by known aliases Evidence: Кленовый сироп — 10–12 г (≈2 ч. л.)
- `warning` `ingredient_not_named_in_steps` r006 `r006_burrito_na_zavtrak` `hot_sauce` line 1: `hot_sauce` is in ingredients but not found in instructions by known aliases Evidence: Паста чипотле или острый соус с копченой паприкой — 5 г (1 ч. л.)
- `warning` `ingredient_not_named_in_steps` r007 `r007_yaichnye_maffiny_s_ovoschami` `green_onion` line 4: `green_onion` is in ingredients but not found in instructions by known aliases Evidence: Зелёный лук — 0,5 пера / ≈5 г
- `warning` `ingredient_not_named_in_steps` r007 `r007_yaichnye_maffiny_s_ovoschami` `milk` line 6: `milk` is in ingredients but not found in instructions by known aliases Evidence: Цельное молоко — 3,75 г (0,25 ст. л.)
- `warning` `ingredient_not_named_in_steps` r007 `r007_yaichnye_maffiny_s_ovoschami` `green_onion` line 9: `green_onion` is in ingredients but not found in instructions by known aliases Evidence: Зеленый лук — 1,25 г
- `warning` `ingredient_not_named_in_steps` r008 `r008_yagodnyy_smuzi_boul` `maple_syrup` line 4: `maple_syrup` is in ingredients but not found in instructions by known aliases Evidence: Кленовый сироп — 5–6 г (1 ч. л.)
- `warning` `ingredient_not_named_in_steps` r008 `r008_yagodnyy_smuzi_boul` `whey_protein` line 5: `whey_protein` is in ingredients but not found in instructions by known aliases Evidence: Ванильный протеин — 5 г (≈1/2 ст. л.)
- `warning` `ingredient_not_named_in_steps` r008 `r008_yagodnyy_smuzi_boul` `almond_butter` line 9: `almond_butter` is in ingredients but not found in instructions by known aliases Evidence: Миндальная паста — 15–16 г (1 ст. л.)
- `warning` `ingredient_not_named_in_steps` r009 `r009_klassicheskaya_ovsyanaya_kasha` `oats` line 1: `oats` is in ingredients but not found in instructions by known aliases Evidence: Овсяные хлопья — 25 г
- `warning` `ingredient_not_named_in_steps` r009 `r009_klassicheskaya_ovsyanaya_kasha` `honey` line 5: `honey` is in ingredients but not found in instructions by known aliases Evidence: Мёд — 2,5–5 г
- `warning` `ingredient_not_named_in_steps` r013 `r013_birher_s_kinoa_persikom_i_imbirem` `ginger` line 3: `ginger` is in ingredients but not found in instructions by known aliases Evidence: свежий имбирь — 3,33 г, мелко натереть
- `warning` `ingredient_not_named_in_steps` r013 `r013_birher_s_kinoa_persikom_i_imbirem` `milk` line 5: `milk` is in ingredients but not found in instructions by known aliases Evidence: молоко — 62,5 мл
- `warning` `ingredient_not_named_in_steps` r015 `r015_morkovnaya_ovsyanaya_kasha_v_stile_morkovnogo_piroga` `milk` line 6: `milk` is in ingredients but not found in instructions by known aliases Evidence: молоко — 300 мл
- `warning` `ingredient_not_named_in_steps` r015 `r015_morkovnaya_ovsyanaya_kasha_v_stile_morkovnogo_piroga` `honey` line 8: `honey` is in ingredients but not found in instructions by known aliases Evidence: мед — 6,67 г
- `warning` `ingredient_not_named_in_steps` r016 `r016_ovsyanaya_chia_boul_s_malinovym_yagodnyy_sousom` `almond_butter` line 6: `almond_butter` is in ingredients but not found in instructions by known aliases Evidence: миндальная паста — 16 г (примерно 1 ст. л.)
- `warning` `ingredient_not_named_in_steps` r017 `r017_tykvennaya_pryanaya_ovsyanka` `milk` line 2: `milk` is in ingredients but not found in instructions by known aliases Evidence: молоко — 100 мл
- `warning` `ingredient_not_named_in_steps` r017 `r017_tykvennaya_pryanaya_ovsyanka` `cranberries_dried` line 4: `cranberries_dried` is in ingredients but not found in instructions by known aliases Evidence: сушеная клюква — 10 г
- `warning` `ingredient_not_named_in_steps` r019 `r019_tostirovannyy_myusli_s_mindalem_kokosom_i_konoplyanymi` `coconut_flakes` line 3: `coconut_flakes` is in ingredients but not found in instructions by known aliases Evidence: несладкая кокосовая стружка или хлопья — 3,75 г
- `warning` `ingredient_not_named_in_steps` r019 `r019_tostirovannyy_myusli_s_mindalem_kokosom_i_konoplyanymi` `cranberries_dried` line 9: `cranberries_dried` is in ingredients but not found in instructions by known aliases Evidence: сушеная клюква — 3,75 г, порубить
- `warning` `ingredient_not_named_in_steps` r019 `r019_tostirovannyy_myusli_s_mindalem_kokosom_i_konoplyanymi` `milk` line 11: `milk` is in ingredients but not found in instructions by known aliases Evidence: молоко или йогурт — около 0,12 л/кг
- `warning` `ingredient_not_named_in_steps` r020 `r020_domashnyaya_granola_s_gretskimi_orehami_i_klyukvoy` `almond_butter` line 8: `almond_butter` is in ingredients but not found in instructions by known aliases Evidence: кремовая миндальная паста — 6,4 г (примерно 1,5 ч. л.)
- `warning` `ingredient_not_named_in_steps` r023 `r023_zapechennaya_frittata_so_shpinatom_pertsem_i_tomatami` `roasted_red_pepper` line 6: `roasted_red_pepper` is in ingredients but not found in instructions by known aliases Evidence: запеченный красный перец — 0,5 шт., нарезать полосками
- `warning` `ingredient_not_named_in_steps` r024 `r024_frittata_s_brokkoli_zelenym_lukom_i_fetoy` `almond_milk` line 2: `almond_milk` is in ingredients but not found in instructions by known aliases Evidence: несладкое миндальное молоко или обычное молоко — 17,1 мл
- `warning` `ingredient_not_named_in_steps` r024 `r024_frittata_s_brokkoli_zelenym_lukom_i_fetoy` `feta` line 10: `feta` is in ingredients but not found in instructions by known aliases Evidence: фета — 10 г, раскрошить
- `warning` `ingredient_not_named_in_steps` r025 `r025_ovoschnaya_frittata_s_kozim_syrom_i_zelenyy_lukom` `milk` line 2: `milk` is in ingredients but not found in instructions by known aliases Evidence: жирные сливки или цельное молоко — 5,62 мл
- `warning` `ingredient_not_named_in_steps` r025 `r025_ovoschnaya_frittata_s_kozim_syrom_i_zelenyy_lukom` `goat_cheese` line 9: `goat_cheese` is in ingredients but not found in instructions by known aliases Evidence: козий сыр — 14,4 г, раскрошить
- `warning` `ingredient_not_named_in_steps` r025 `r025_ovoschnaya_frittata_s_kozim_syrom_i_zelenyy_lukom` `green_onion` line 10: `green_onion` is in ingredients but not found in instructions by known aliases Evidence: зеленый лук — 1,25 г, нарезать
- `warning` `ingredient_not_named_in_steps` r028 `r028_zapechennye_yaytsa_so_shpinatom_kanadskim_bekonom_i_ch` `egg` line 7: `egg` is in ingredients but not found in instructions by known aliases Evidence: яйца — 1 шт.
- `warning` `ingredient_not_named_in_steps` r028 `r028_zapechennye_yaytsa_so_shpinatom_kanadskim_bekonom_i_ch` `cream` line 8: `cream` is in ingredients but not found in instructions by known aliases Evidence: жирные сливки — 15 мл
- `warning` `ingredient_not_named_in_steps` r031 `r031_amerikanskie_pankeyki` `wheat_flour` line 1: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: пшеничная мука — 50 г
- `warning` `ingredient_not_named_in_steps` r031 `r031_amerikanskie_pankeyki` `maple_syrup` line 9: `maple_syrup` is in ingredients but not found in instructions by known aliases Evidence: кленовый сироп — 15 мл
- `warning` `ingredient_not_named_in_steps` r032 `r032_ovsyanye_pankeyki_v_blendere` `berries` line 11: `berries` is in ingredients but not found in instructions by known aliases Evidence: свежие ягоды или нарезанные фрукты — 60 г
- `warning` `ingredient_not_named_in_steps` r033 `r033_mini_pankeyki_s_koritsey_v_stile_sopapilya` `wheat_flour` line 1: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: пшеничная мука — 12,5 г
- `warning` `ingredient_not_named_in_steps` r034 `r034_pankeyki_na_protivne_s_chetyrmya_toppingami` `wheat_flour` line 1: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: белая цельнозерновая мука — 13,3 г
- `warning` `ingredient_not_named_in_steps` r034 `r034_pankeyki_na_protivne_s_chetyrmya_toppingami` `wheat_flour` line 2: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: пшеничная мука — 13,8 г
- `warning` `ingredient_not_named_in_steps` r035 `r035_klassicheskie_vafli` `wheat_flour` line 1: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: пшеничная мука — 50 г
- `warning` `ingredient_not_named_in_steps` r036 `r036_prostye_tselnozernovye_pankeyki_s_chernikoy` `wheat_flour` line 1: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: цельнозерновая пшеничная мука — 50 г
- `warning` `ingredient_not_named_in_steps` r036 `r036_prostye_tselnozernovye_pankeyki_s_chernikoy` `honey` line 8: `honey` is in ingredients but not found in instructions by known aliases Evidence: мед — 5 г
- `warning` `ingredient_not_named_in_steps` r037 `r037_bazovye_krepy` `milk` line 2: `milk` is in ingredients but not found in instructions by known aliases Evidence: молоко — 30 мл
- `warning` `ingredient_not_named_in_steps` r037 `r037_bazovye_krepy` `wheat_flour` line 5: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: пшеничная мука — 31,2 г
- `warning` `ingredient_not_named_in_steps` r038 `r038_gollandskiy_blin_iz_duhovki` `wheat_flour` line 3: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: пшеничная мука просеянная — 32,5 г
- `warning` `ingredient_not_named_in_steps` r039 `r039_zapechennaya_ovsyanka_s_chernikoy_limonom_i_kardamonom` `blueberries` line 12: `blueberries` is in ingredients but not found in instructions by known aliases Evidence: черника свежая или замороженная — 30 г
- `warning` `ingredient_not_named_in_steps` r041 `r041_beygl_klab_s_lososem_yaytsom_i_krem_syrom` `cream_cheese` line 2: `cream_cheese` is in ingredients but not found in instructions by known aliases Evidence: крем-сыр — 25 г (примерно 1-1,5 ст. л.)
- `warning` `ingredient_not_named_in_steps` r041 `r041_beygl_klab_s_lososem_yaytsom_i_krem_syrom` `lemon_juice` line 5: `lemon_juice` is in ingredients but not found in instructions by known aliases Evidence: лимон — 0,25 шт. (примерно 10 мл сока)
- `warning` `ingredient_not_named_in_steps` r043 `r043_tost_s_yaytsom_indeykoy_i_ovoschami` `whole_grain_bread` line 1: `whole_grain_bread` is in ingredients but not found in instructions by known aliases Evidence: цельнозерновой хлеб — 2 ломтика / ≈80 г
- `warning` `ingredient_not_named_in_steps` r043 `r043_tost_s_yaytsom_indeykoy_i_ovoschami` `turkey_or_chicken_breast` line 3: `turkey_or_chicken_breast` is in ingredients but not found in instructions by known aliases Evidence: готовая индейка или куриная грудка — 80 г
- `warning` `ingredient_not_named_in_steps` r045 `r045_rolly_s_kopchenym_lososem_slivochnym_syrom_i_tsukini` `salmon` line 6: `salmon` is in ingredients but not found in instructions by known aliases Evidence: копченый лосось — 21,2 г, нарезать полосками
- `warning` `ingredient_not_named_in_steps` r047 `r047_angliyskiy_maffin_s_yaytsom_syrom_i_sosisochnoy_kotlet` `sausage` line 6: `sausage` is in ingredients but not found in instructions by known aliases Evidence: готовая отварная сосиска для завтрака — 1 шт. (примерно 50 г)
- `warning` `ingredient_not_named_in_steps` r048 `r048_burrito_s_chorizo_yaytsom_fasolyu_i_poblano` `sausage` line 6: `sausage` is in ingredients but not found in instructions by known aliases Evidence: Куриная колбаска или постный фарш — 112,5 г
- `warning` `ingredient_not_named_in_steps` r048 `r048_burrito_s_chorizo_yaytsom_fasolyu_i_poblano` `flour_tortilla` line 8: `flour_tortilla` is in ingredients but not found in instructions by known aliases Evidence: Большие пшеничные тортильи — 1 шт. / ≈70 г
- `warning` `ingredient_not_named_in_steps` r048 `r048_burrito_s_chorizo_yaytsom_fasolyu_i_poblano` `red_beans` line 9: `red_beans` is in ingredients but not found in instructions by known aliases Evidence: Пережаренная фасоль — 27,5 г
- `warning` `ingredient_not_named_in_steps` r050 `r050_britanskiy_tost_s_domashney_fasolyu_v_tomatnom_souse` `tomato_paste` line 8: `tomato_paste` is in ingredients but not found in instructions by known aliases Evidence: томатная паста — 15 г (примерно 1 ст. л.)
- `warning` `ingredient_not_named_in_steps` r050 `r050_britanskiy_tost_s_domashney_fasolyu_v_tomatnom_souse` `red_beans` line 12: `red_beans` is in ingredients but not found in instructions by known aliases Evidence: белая фасоль консервированная — 0,5 банки по 425 г, слить и промыть
- `warning` `ingredient_not_named_in_steps` r051 `r051_tropicheskiy_smuzi_boul_s_mango_i_ananasom` `mint` line 9: `mint` is in ingredients but not found in instructions by known aliases Evidence: Мята — 1,5–2 листика
- `warning` `ingredient_not_named_in_steps` r054 `r054_vanilno_mindalnaya_chia_ovsyanaya_chasha_s_chernikoy` `honey` line 8: `honey` is in ingredients but not found in instructions by known aliases Evidence: Мед — 0,5 ст. л. (10 г)
- `warning` `ingredient_not_named_in_steps` r055 `r055_malinovo_persikovyy_mango_boul_s_grecheskim_yogurtom` `coconut_flakes` line 8: `coconut_flakes` is in ingredients but not found in instructions by known aliases Evidence: Кокосовая стружка несладкая — 1 ст. л. (5 г)
- `warning` `ingredient_not_named_in_steps` r056 `r056_puding_s_chia_v_stile_masala_chay_bananom_i_fistashkam` `pistachios` line 9: `pistachios` is in ingredients but not found in instructions by known aliases Evidence: Фисташки жареные несоленые — 1 ст. л. (8 г), рубленые
- `warning` `ingredient_not_named_in_steps` r058 `r058_tropicheskaya_yogurtovaya_chasha_s_greypfrutom_i_manda` `orange` line 1: `orange` is in ingredients but not found in instructions by known aliases Evidence: Сок апельсиновый сок 100% без сахара — 60 мл
- `warning` `ingredient_not_named_in_steps` r060 `r060_chia_chasha_s_arahisovoy_pastoy_i_yagodnym_yagodnyy_so` `orange` line 2: `orange` is in ingredients but not found in instructions by known aliases Evidence: Апельсиновый сок — 0,33 ст. л. (5 мл)
- `warning` `ingredient_not_named_in_steps` r061 `r061_tselnozernovye_maffiny_s_bananom_yablokom_i_chernikoy` `apple_sauce` line 4: `apple_sauce` is in ingredients but not found in instructions by known aliases Evidence: яблочное пюре — 8,33 г
- `warning` `ingredient_not_named_in_steps` r061 `r061_tselnozernovye_maffiny_s_bananom_yablokom_i_chernikoy` `honey` line 6: `honey` is in ingredients but not found in instructions by known aliases Evidence: жидкий мед — 7,08 г
- `warning` `ingredient_not_named_in_steps` r061 `r061_tselnozernovye_maffiny_s_bananom_yablokom_i_chernikoy` `wheat_flour` line 8: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: цельнозерновая мука — 16,7 г
- `warning` `ingredient_not_named_in_steps` r062 `r062_veganskie_myusli_maffiny_s_yablokom_i_pekanom` `wheat_flour` line 3: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: пшеничная мука — 13,3 г
- `warning` `ingredient_not_named_in_steps` r063 `r063_speltovye_maffiny_s_ezhevikoy_bananom_i_finikami` `wheat_flour` line 1: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: цельнозерновая спельтовая мука — 29,2 г
- `warning` `ingredient_not_named_in_steps` r064 `r064_zapechennaya_bananovaya_ovsyanka_s_arahisovoy_pastoy` `wheat_flour` line 1: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: овсяная мука — 60 г
- `warning` `ingredient_not_named_in_steps` r064 `r064_zapechennaya_bananovaya_ovsyanka_s_arahisovoy_pastoy` `whey_protein` line 2: `whey_protein` is in ingredients but not found in instructions by known aliases Evidence: ванильный сывороточный протеин — 15 г
- `warning` `ingredient_not_named_in_steps` r065 `r065_vegetarianskaya_zapekanka_s_sosiskami_gribami_i_pertse` `bell_pepper` line 5: `bell_pepper` is in ingredients but not found in instructions by known aliases Evidence: красный сладкий перец — 0,25 шт. / около 37,5 г
- `warning` `ingredient_not_named_in_steps` r065 `r065_vegetarianskaya_zapekanka_s_sosiskami_gribami_i_pertse` `milk` line 7: `milk` is in ingredients but not found in instructions by known aliases Evidence: цельное молоко — 31,2 мл
- `warning` `ingredient_not_named_in_steps` r065 `r065_vegetarianskaya_zapekanka_s_sosiskami_gribami_i_pertse` `green_onion` line 9: `green_onion` is in ingredients but not found in instructions by known aliases Evidence: зеленый лук — 1,25 г
- `warning` `ingredient_not_named_in_steps` r066 `r066_zapechennaya_ovsyanka_s_malinoy_kokosom_i_gretskimi_or` `coconut_flakes` line 3: `coconut_flakes` is in ingredients but not found in instructions by known aliases Evidence: кокосовая стружка — 6 г
- `warning` `ingredient_not_named_in_steps` r068 `r068_ovoschnaya_zapekanka_s_batatom_sparzhey_i_fetoy` `almond_milk` line 6: `almond_milk` is in ingredients but not found in instructions by known aliases Evidence: миндальное молоко — 10,9 мл
- `warning` `ingredient_not_named_in_steps` r068 `r068_ovoschnaya_zapekanka_s_batatom_sparzhey_i_fetoy` `feta` line 10: `feta` is in ingredients but not found in instructions by known aliases Evidence: фета — 10,5 г (примерно 2 ст. л. крошки)
- `warning` `ingredient_not_named_in_steps` r069 `r069_tselnozernovoy_bananovyy_hleb_s_medom` `wheat_flour` line 11: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: цельнозерновая пшеничная мука — 22 г
- `warning` `ingredient_not_named_in_steps` r070 `r070_norvezhskie_bulochki_s_zavarnym_kremom_i_kokosom` `wheat_flour` line 3: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: пшеничная мука — 39,6 г
- `warning` `ingredient_not_named_in_steps` r070 `r070_norvezhskie_bulochki_s_zavarnym_kremom_i_kokosom` `egg` line 8: `egg` is in ingredients but not found in instructions by known aliases Evidence: яйцо — 0,083 шт. / около 4,17 г
- `warning` `ingredient_not_named_in_steps` r070 `r070_norvezhskie_bulochki_s_zavarnym_kremom_i_kokosom` `egg_yolk` line 13: `egg_yolk` is in ingredients but not found in instructions by known aliases Evidence: яичные желтки — 0,17 шт. / около 2,92 г
- `warning` `ingredient_not_named_in_steps` r070 `r070_norvezhskie_bulochki_s_zavarnym_kremom_i_kokosom` `cornstarch` line 14: `cornstarch` is in ingredients but not found in instructions by known aliases Evidence: кукурузный крахмал — 1,33 г
- `warning` `ingredient_not_named_in_steps` r071 `r071_kurinyy_kondzhi_s_imbirem_i_zelenym_lukom` `ginger` line 6: `ginger` is in ingredients but not found in instructions by known aliases Evidence: свежий имбирь — 0,33–0,5 ст. л., натереть
- `warning` `ingredient_not_named_in_steps` r072 `r072_klassicheskiy_kedzheri_s_kopchenoy_pikshey_i_yaytsami` `smoked_white_fish` line 10: `smoked_white_fish` is in ingredients but not found in instructions by known aliases Evidence: копченая пикша, треска или другая белая рыба горячего копчения без красителя — 50 г
- `warning` `ingredient_not_named_in_steps` r073 `r073_yaytsa_s_fasolyu_tomatami_i_tortiley` `lime_juice` line 4: `lime_juice` is in ingredients but not found in instructions by known aliases Evidence: сок лайма — 0,62 ст. л.
- `warning` `ingredient_not_named_in_steps` r073 `r073_yaytsa_s_fasolyu_tomatami_i_tortiley` `red_beans` line 8: `red_beans` is in ingredients but not found in instructions by known aliases Evidence: красная фасоль консервированная — 0,25 банка / около 106 г, промыть и обсушить
- `warning` `ingredient_not_named_in_steps` r076 `r076_bystryy_nasi_goreng_s_ovoschami_i_zharenym_yaytsom` `onion` line 2: `onion` is in ingredients but not found in instructions by known aliases Evidence: маленькая луковица — 1 шт., тонко нарезать
- `warning` `ingredient_not_named_in_steps` r076 `r076_bystryy_nasi_goreng_s_ovoschami_i_zharenym_yaytsom` `napa_cabbage` line 5: `napa_cabbage` is in ingredients but not found in instructions by known aliases Evidence: китайская или савойская капуста — 1/2 маленького кочана, нашинковать
- `warning` `ingredient_not_named_in_steps` r077 `r077_kokosovyy_ris_s_yaytsom_ogurtsom_i_arahisom` `milk` line 2: `milk` is in ingredients but not found in instructions by known aliases Evidence: кокосовое молоко — 60 мл
- `warning` `ingredient_not_named_in_steps` r079 `r079_egipetskiy_ful_medames_s_tahini_i_limonom` `onion` line 3: `onion` is in ingredients but not found in instructions by known aliases Evidence: маленькая луковица — 0,5 шт., мелко нарезать
- `warning` `ingredient_not_named_in_steps` r080 `r080_ovoschnaya_mannaya_kasha_s_yaytsom_i_keshyu` `semolina` line 1: `semolina` is in ingredients but not found in instructions by known aliases Evidence: манная крупа — 45 г
- `warning` `ingredient_not_named_in_steps` r081 `r081_yaytsa_s_krasnoy_fasolyu_i_avokado_na_odnoy_skovorode` `chili_pepper` line 2: `chili_pepper` is in ingredients but not found in instructions by known aliases Evidence: красный чили — 0,5 шт., без семян, тонко нарезать
- `warning` `ingredient_not_named_in_steps` r081 `r081_yaytsa_s_krasnoy_fasolyu_i_avokado_na_odnoy_skovorode` `red_beans` line 5: `red_beans` is in ingredients but not found in instructions by known aliases Evidence: красная фасоль консервированная — 0,5 банка 200 г, вместе с жидкостью
- `warning` `ingredient_not_named_in_steps` r082 `r082_tost_s_brokkoli_yaytsom_i_yogurtovym_sousom` `whole_grain_bread` line 1: `whole_grain_bread` is in ingredients but not found in instructions by known aliases Evidence: цельнозерновой хлеб — 1–2 ломтика / ≈70 г
- `warning` `ingredient_not_named_in_steps` r082 `r082_tost_s_brokkoli_yaytsom_i_yogurtovym_sousom` `lemon_juice` line 5: `lemon_juice` is in ingredients but not found in instructions by known aliases Evidence: лимонный сок — 5 мл
- `warning` `ingredient_not_named_in_steps` r084 `r084_kesadilya_na_zavtrak_s_yaytsami_fasolyu_i_chedderom` `red_beans` line 4: `red_beans` is in ingredients but not found in instructions by known aliases Evidence: вареная фасоль пинто или красная фасоль — 60 г, промыть и обсушить
- `warning` `ingredient_not_named_in_steps` r085 `r085_boul_s_batatom_shiitake_keylom_i_yaytsom` `red_cabbage` line 5: `red_cabbage` is in ingredients but not found in instructions by known aliases Evidence: краснокочанная капуста — 35 г, тонко нашинковать
- `warning` `ingredient_not_named_in_steps` r085 `r085_boul_s_batatom_shiitake_keylom_i_yaytsom` `microgreens` line 12: `microgreens` is in ingredients but not found in instructions by known aliases Evidence: проростки брокколи или любые проростки — 10 г
- `warning` `ingredient_not_named_in_steps` r086 `r086_menemen_s_tomatami_zelenym_pertsem_i_myagkimi_yaytsami` `oregano` line 3: `oregano` is in ingredients but not found in instructions by known aliases Evidence: сушеный орегано — 0,12 ч. л.
- `warning` `ingredient_not_named_in_steps` r087 `r087_burrito_s_yaichnymi_belkami_shpinatom_i_kartofelem` `flour_tortilla` line 1: `flour_tortilla` is in ingredients but not found in instructions by known aliases Evidence: Цельнозерновые тортильи среднего размера — 1 шт. / ≈60 г
- `warning` `ingredient_not_named_in_steps` r087 `r087_burrito_s_yaichnymi_belkami_shpinatom_i_kartofelem` `egg_white` line 2: `egg_white` is in ingredients but not found in instructions by known aliases Evidence: Жидкие яичные белки — 75 мл / ≈75 г
- `warning` `ingredient_not_named_in_steps` r088 `r088_batat_tost_so_shpinatom_yaytsom_i_ostrym_sousom` `green_onion` line 5: `green_onion` is in ingredients but not found in instructions by known aliases Evidence: зеленый лук — 1/2 ч. л., нарезать
- `warning` `ingredient_not_named_in_steps` r088 `r088_batat_tost_so_shpinatom_yaytsom_i_ostrym_sousom` `hot_sauce` line 6: `hot_sauce` is in ingredients but not found in instructions by known aliases Evidence: острый соус — 1/2 ч. л.
- `warning` `ingredient_not_named_in_steps` r091 `r091_belkovaya_ovsyanka_na_noch_s_yagodami_arahisovoy_pasto` `whey_protein` line 1: `whey_protein` is in ingredients but not found in instructions by known aliases Evidence: ванильный протеин — 7,5 г
- `warning` `ingredient_not_named_in_steps` r092 `r092_tofu_pankeyki_s_bananom_malinoy_i_brazilskimi_orehami` `maple_syrup` line 4: `maple_syrup` is in ingredients but not found in instructions by known aliases Evidence: кленовый сироп или мед — 12 мл
- `warning` `ingredient_not_named_in_steps` r092 `r092_tofu_pankeyki_s_bananom_malinoy_i_brazilskimi_orehami` `lemon_juice` line 7: `lemon_juice` is in ingredients but not found in instructions by known aliases Evidence: лимонный сок — 2 мл
- `warning` `ingredient_not_named_in_steps` r092 `r092_tofu_pankeyki_s_bananom_malinoy_i_brazilskimi_orehami` `wheat_flour` line 10: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: гречневая мука — 50 г
- `warning` `ingredient_not_named_in_steps` r092 `r092_tofu_pankeyki_s_bananom_malinoy_i_brazilskimi_orehami` `brown_sugar` line 11: `brown_sugar` is in ingredients but not found in instructions by known aliases Evidence: светлый мусковадо — 9,6 г
- `warning` `ingredient_not_named_in_steps` r093 `r093_nut_s_pertsem_tomatami_i_zharenym_tofu` `tomato_paste` line 6: `tomato_paste` is in ingredients but not found in instructions by known aliases Evidence: томатная паста — 7,5 г (примерно 1 ч. л.)
- `warning` `ingredient_not_named_in_steps` r094 `r094_skrembl_s_fetoy_shpinatom_i_tomatami` `feta` line 4: `feta` is in ingredients but not found in instructions by known aliases Evidence: фета — 60 г, кубиками
- `warning` `ingredient_not_named_in_steps` r096 `r096_ovoschnye_yaichnye_maffiny_s_fetoy` `wheat_flour` line 8: `wheat_flour` is in ingredients but not found in instructions by known aliases Evidence: пшеничная мука — 2 г
- `warning` `ingredient_not_named_in_steps` r096 `r096_ovoschnye_yaichnye_maffiny_s_fetoy` `feta` line 10: `feta` is in ingredients but not found in instructions by known aliases Evidence: фета — 3,75 г, раскрошить
- `warning` `ingredient_not_named_in_steps` r097 `r097_yaichnye_kesadili_so_shpinatom_chedderom_i_halapeno` `flour_tortilla` line 7: `flour_tortilla` is in ingredients but not found in instructions by known aliases Evidence: пшеничные или цельнозерновые тортильи 15–20 см — 1,33 шт.
- `warning` `ingredient_not_named_in_steps` r098 `r098_veganskie_burrito_s_tofu_skremblom_i_chernoy_fasolyu` `red_beans` line 10: `red_beans` is in ingredients but not found in instructions by known aliases Evidence: красная фасоль вареная или консервированная — 22,5 г, промыть и обсушить
- `warning` `ingredient_not_named_in_steps` r098 `r098_veganskie_burrito_s_tofu_skremblom_i_chernoy_fasolyu` `bell_pepper` line 11: `bell_pepper` is in ingredients but not found in instructions by known aliases Evidence: запеченный красный сладкий перец — 0,25 шт., тонко нарезать
- `warning` `ingredient_not_named_in_steps` r098 `r098_veganskie_burrito_s_tofu_skremblom_i_chernoy_fasolyu` `green_onion` line 13: `green_onion` is in ingredients but not found in instructions by known aliases Evidence: маринованный красный лук или зеленый лук — 12,5 г
- ... 797 additional findings are in the CSV.

### Steps Mention Missing Ingredient

- none

### Truncation/Fragments

- `warning` `weak_serving_finish` r001 `r001_ovsyanka_na_noch_s_yagodami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Утром добавить ягоды и ореховую пасту
- `warning` `weak_serving_finish` r002 `r002_tost_s_avokado`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Поджарить хлеб, сбрызнуть маслом и выложить сверху авокадо
- `warning` `weak_serving_finish` r016 `r016_ovsyanaya_chia_boul_s_malinovym_yagodnyy_sousom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте малиновый ягодный соус, оставшуюся малину, апельсиновые кружочки, банан, миндальную пасту, годжи и семена чиа
- `warning` `weak_serving_finish` r043 `r043_tost_s_yaytsom_indeykoy_i_ovoschami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Соберите тост с индейкой или курицей, яйцом, помидором, салатом и йогуртовым соусом
- `warning` `weak_serving_finish` r050 `r050_britanskiy_tost_s_domashney_fasolyu_v_tomatnom_souse`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите горячую фасоль на тосты и завершите рукколой
- `warning` `weak_serving_finish` r056 `r056_puding_s_chia_v_stile_masala_chay_bananom_i_fistashkam`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите половину пудинга в стакан или миску, добавьте половину банана и фисташек, затем повторите слой пудинга, банана и фисташек
- `warning` `weak_serving_finish` r073 `r073_yaytsa_s_fasolyu_tomatami_i_tortiley`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Положите по яйцу на каждую тортилью, добавьте теплую сальсу и пико-де-гайо
- `warning` `weak_serving_finish` r077 `r077_kokosovyy_ris_s_yaytsom_ogurtsom_i_arahisom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите рис в тарелку, добавьте яйцо, огурец, арахис, зеленый лук и немного соевого соуса
- `warning` `weak_serving_finish` r079 `r079_egipetskiy_ful_medames_s_tahini_i_limonom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Если пюре выглядит расслоившимся или слишком густым, добавьте ложку холодной воды и снова перемешайте
- `warning` `weak_serving_finish` r082 `r082_tost_s_brokkoli_yaytsom_i_yogurtovym_sousom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Поджарьте хлеб, выложите брокколи и яйца, добавьте йогуртовый соус
- `warning` `weak_serving_finish` r085 `r085_boul_s_batatom_shiitake_keylom_i_yaytsom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Положите по яйцу в каждую миску, добавьте хумус, проростки и петрушку
- `warning` `weak_serving_finish` r109 `r109_kurinyy_sup_s_beloy_fasolyu_i_keylom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Разлейте горячий суп по глубоким мискам
- `warning` `weak_serving_finish` r111 `r111_govyadina_tushennaya_s_ovoschami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Тушите под крышкой 60–75 минут до мягкости мяса
- `warning` `weak_serving_finish` r113 `r113_amerikanskoe_ragu_iz_govyadiny_s_kartofelem`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Вмешайте горошек, прогрейте 5 минут и выровняйте соль и перец
- `warning` `weak_serving_finish` r119 `r119_burgery_iz_baraniny_s_tsatsiki`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Соберите бургеры с котлетами, цацики, ломтиками помидора, красным луком и листьями мяты
- `warning` `weak_serving_finish` r158 `r158_domashniy_vegetarianskiy_chili_s_chernoy_i_pinto_fasol`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Разлейте чили по мискам, добавьте авокадо, тортилья-чипсы и дополнительную кинзу
- `warning` `weak_serving_finish` r178 `r178_kremovaya_tselnozernovaya_pasta_s_pesto_i_keylom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Перемешайте, при необходимости разбавьте водой от пасты, посолите и поперчите
- `warning` `weak_serving_finish` r179 `r179_myasnaya_lazanya_s_rikottoy_i_tomatami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Дайте лазанье постоять 15 минут перед нарезкой
- `warning` `weak_serving_finish` r187 `r187_risovyy_boul_so_skumbriey_i_ovoschami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите рис в тарелку, добавьте рыбу, овощи, зеленый лук, соевый соус и лимонный сок
- `warning` `weak_serving_finish` r204 `r204_boul_s_lososem_brokkoli_i_bulgurom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите булгур, брокколи, огурец и лосось в миску, добавьте соус
- `warning` `weak_serving_finish` r206 `r206_boul_iz_perlovki_s_yaytsom_bekonom_i_tomatnym_sousom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите перловку в миску, добавьте соус с беконом и яйцо
- `warning` `weak_serving_finish` r226 `r226_grecheskaya_musaka_s_baklazhanami_i_beshamelem`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Дайте мусаке постоять 20 минут перед нарезкой
- `warning` `weak_serving_finish` r229 `r229_pastushiy_pirog_s_govyadinoy_i_kartofelnym_pyure`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Запеките при 200 °C 10-12 минут
- `warning` `weak_serving_finish` r237 `r237_salat_s_tuntsom_fasolyu_yablokom_i_fetoy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Заправьте йогуртом, лимонным соком, маслом, солью и перцем
- `warning` `weak_serving_finish` r242 `r242_tako_s_beloy_ryboy_krasnoy_kapustoy_i_avokado`: last instruction sentence does not clearly finish with serving/ready wording Evidence: На каждую тортилью намажьте немного сметаны, добавьте капусту, помидоры, авокадо, кусочки рыбы, кинзу, зеленый чили и острый соус
- `warning` `weak_serving_finish` r251 `r251_sendvich_s_tuntsom_i_yaytsom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Соберите сэндвич из хлеба, салата, огурца, тунца и яйца
- `warning` `weak_serving_finish` r253 `r253_tvorog_s_yagodami_i_gretskim_orehom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте ягоды, орех, мед и корицу
- `warning` `weak_serving_finish` r255 `r255_tost_s_indeykoy_syrom_i_tomatom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите индейку, сыр, томат и салат
- `warning` `weak_serving_finish` r256 `r256_hlebtsy_s_lososem_i_tvorozhnym_syrom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите лосось и огурец, добавьте укроп и лимонный сок
- `warning` `weak_serving_finish` r257 `r257_grecheskiy_yogurt_s_ovsyankoy_i_arahisovoy_pastoy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте нарезанный банан и арахисовую пасту
- `warning` `weak_serving_finish` r258 `r258_salat_s_nutom_tuntsom_i_ogurtsom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смешайте тунец, нут, огурец, йогурт, лимонный сок, укроп, соль и перец
- `warning` `weak_serving_finish` r259 `r259_kefirnyy_smuzi_s_tvorogom_i_bananom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Взбейте кефир, творог, банан, какао и мед до однородности
- `warning` `weak_serving_finish` r262 `r262_pita_s_humusom_i_kuritsey`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смажьте хумусом, добавьте курицу, огурец, помидор, салат и лимонный сок
- `warning` `weak_serving_finish` r263 `r263_ovsyanyy_boul_s_arahisovoy_pastoy_i_golubikoy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте голубику и арахисовую пасту
- `warning` `weak_serving_finish` r266 `r266_boul_s_kuritsey_fasolyu_i_avokado`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите в миску курицу, фасоль, авокадо, помидор и огурец, добавьте соус
- `warning` `weak_serving_finish` r267 `r267_hlebtsy_s_tvorogom_golubikoy_i_arahisovoy_pastoy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте голубику, арахисовую пасту, мед и корицу
- `warning` `weak_serving_finish` r277 `r277_yogurtovyy_dip_s_kuritsey_i_ovoschami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Ешьте курицу и овощи с йогуртовым дипом
- `warning` `weak_serving_finish` r282 `r282_krostini_s_pyure_iz_goroshka_rukkoloy_i_bobami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Настрогайте пекорино овощечисткой и сбрызните кростини оливковым маслом
- `warning` `weak_serving_finish` r286 `r286_letnyaya_tomatnaya_brusketta_s_bazilikom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Ложкой выложите томаты вместе с соком на тосты и закончите оставшейся солью
- `warning` `weak_serving_finish` r288 `r288_tost_s_indeykoy_tvorozhnym_syrom_i_inzhirom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Сбрызните бальзамическим уксусом
- `warning` `weak_serving_finish` r292 `r292_omlet_s_tremya_syrami_i_zelenym_lukom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Сложите пополам и прогрейте 1 минуту
- `warning` `weak_serving_finish` r293 `r293_tost_s_yaytsom_syrom_i_kukuruzoy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите яйцо, сыр, кукурузу и петрушку
- `warning` `weak_serving_finish` r296 `r296_mini_maffiny_iz_yaits_morkovi_kabachka_i_fety`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Дайте маффинам постоять 1-2 минуты, затем проведите ножом по краям и выньте их из формы
- `warning` `weak_serving_finish` r297 `r297_yaichnyy_sendvich_s_vetchinoy_i_chedderom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Соберите сэндвич с яйцами, ветчиной, сыром, помидором и салатом
- `warning` `weak_serving_finish` r299 `r299_tost_s_yaytsom_bekonom_i_syrom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Подсушите хлеб, выложите салат, помидор, бекон, яйцо и сыр
- `warning` `weak_serving_finish` r300 `r300_omlet_s_bekonom_gaudoy_i_tvorozhnym_syrom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Когда омлет схватится, добавьте гауду и творожный сыр, сложите пополам
- `warning` `weak_serving_finish` r301 `r301_tvorog_s_bananom_i_orehom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте нарезанный банан, орех и корицу
- `warning` `weak_serving_finish` r302 `r302_yogurt_s_chernikoy_yablokom_i_semenami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смешайте йогурт, чернику, яблоко, семечки и овсяные хлопья
- `warning` `weak_serving_finish` r303 `r303_ovsyanka_s_tvorogom_bananom_i_chernikoy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте творог, нарезанный банан, чернику и корицу
- `warning` `weak_serving_finish` r304 `r304_tvorog_s_yablokom_izyumom_i_koritsey`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смешайте творог, йогурт, яблоко, изюм и корицу
- `warning` `weak_serving_finish` r313 `r313_yagodno_kefirnyy_smuzi_s_bananom_i_mindalnoy_pastoy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Перелейте в большой стакан и выпейте свежим
- `warning` `weak_serving_finish` r318 `r318_shokoladnyy_proteinovyy_sheyk_s_tvorogom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Взбейте молоко, творог, банан, какао и арахисовую пасту до однородности
- `warning` `weak_serving_finish` r319 `r319_mango_lassi_na_yogurte_i_kefire`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Взбейте манго, йогурт, кефир, лаймовый сок, мед и кардамон
- `warning` `weak_serving_finish` r327 `r327_klubnichnyy_chizkeyk_na_yogurte`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите крошку, крем и нарезанную клубнику в небольшую миску
- `warning` `weak_serving_finish` r333 `r333_hlebtsy_s_tvorogom_i_tuntsom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите на хлебцы, добавьте огурец
- `warning` `weak_serving_finish` r334 `r334_rzhanoy_tost_s_yaytsom_i_syrom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Подсушите хлеб, добавьте сыр, яйца и помидор
- `warning` `weak_serving_finish` r341 `r341_pechenoe_yabloko_s_tvorogom_i_izyumom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Наполните яблоко и запеките при 200 °C 10-12 минут
- `warning` `weak_serving_finish` r344 `r344_tost_s_yablokom_indeykoy_i_syrom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите на хлеб соус, индейку, тонкие ломтики яблока и сыр
- `warning` `weak_serving_finish` r345 `r345_grecheskiy_yogurt_s_klubnikoy_i_temnym_shokoladom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите йогурт в миску, добавьте клубнику, шоколад, миндаль и мед
- `warning` `weak_serving_finish` r346 `r346_mango_yogurtovyy_boul_s_tvorogom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте нарезанное манго и кокосовую стружку
- `warning` `weak_serving_finish` r348 `r348_banan_s_arahisovoy_pastoy_yogurtom_i_temnym_shokoladom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте нарезанный банан, арахисовую пасту, тертый темный шоколад и какао
- `warning` `weak_serving_finish` r350 `r350_sendvich_s_kuritsey_mango_i_yogurtovym_sousom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Соберите сэндвич из хлеба, курицы, манго, салата и соуса
- `warning` `weak_serving_finish` r352 `r352_roll_s_krevetkami_avokado_laymom_i_tabasko`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите авокадную смесь полосой по центру тортильи, сверху распределите салатные листья и креветки
- `warning` `weak_serving_finish` r353 `r353_rolly_spiralki_s_indeykoy_bazilikovym_krem_syrom_i_shp`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Намажьте индейку частью базиликового крем-сыра, у ближнего края выложите полоски печеного перца и немного моркови
- `warning` `weak_serving_finish` r361 `r361_edamame_s_tvorogom_i_ogurtsom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите творог, горошек и огурец в миску, добавьте соевый соус, лимонный сок и кунжут
- `warning` `weak_serving_finish` r362 `r362_tvorog_s_mindalem_izyumom_i_vozdushnoy_pshenitsey`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте миндаль, изюм и воздушную пшеницу
- `warning` `weak_serving_finish` r364 `r364_ogurechnye_tosty_s_tuntsom_i_yogurtom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Подсушите хлеб, выложите тунцовый салат и огурец
- `warning` `weak_serving_finish` r370 `r370_sladko_solenye_ostrye_orehi_s_kuminom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Влейте горячий сироп к орехам, быстро перемешайте и распределите на противне одним слоем
- `warning` `weak_serving_finish` r371 `r371_grecheskiy_yogurt_s_bananom_klubnikoy_i_shokoladom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите йогурт в миску, добавьте фрукты, шоколад и орех
- `warning` `weak_serving_finish` r372 `r372_fruktovyy_tvorog_s_mango_kivi_i_yagodami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте нарезанные манго, киви и ягоды
- `warning` `weak_serving_finish` r373 `r373_klubnichno_bananovyy_kefirnyy_smuzi_s_tvorogom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Взбейте кефир, творог, клубнику, банан и мед
- `warning` `weak_serving_finish` r374 `r374_tropicheskiy_yogurt_s_mango_bananom_i_granoloy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте нарезанные манго и банан, гранолу и темный шоколад
- `warning` `weak_serving_finish` r375 `r375_yogurt_s_yagodnym_sousom_i_gretskim_orehom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите йогурт в миску, добавьте ягодный соус и орех
- `warning` `weak_serving_finish` r376 `r376_malinovo_fistashkovyy_grecheskiy_yogurt`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте малину, фисташки, мед и лимонную цедру
- `warning` `weak_serving_finish` r377 `r377_yagodnyy_tvorozhnyy_krem_s_limonom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте ягоды
- `warning` `weak_serving_finish` r378 `r378_shokoladno_bananovyy_tvorog`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте нарезанный банан и тертый темный шоколад
- `warning` `weak_serving_finish` r379 `r379_yogurtovyy_boul_s_mango_ananasom_i_granoloy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте манго, ананас, гранолу и миндаль
- `warning` `weak_serving_finish` r380 `r380_persikovyy_tvorog_s_vanilyu`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте нарезанный персик
- `warning` `weak_serving_finish` r382 `r382_farshirovannye_yaytsa_s_avokado_zelenym_lukom_i_bekono`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Наполните белки и добавьте бекон
- `warning` `weak_serving_finish` r385 `r385_salatnye_listya_s_kurinoy_grudkoy_avokado_i_bekonom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите начинку в листья салата и добавьте бекон
- `warning` `weak_serving_finish` r386 `r386_italyanskie_salatnye_listya_s_kurinoy_grudkoy_i_parmez`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите начинку в листья салата, добавьте черри, миндаль и пармезан
- `warning` `weak_serving_finish` r387 `r387_tvorozhnaya_banochka_s_pertsem_hrustyaschim_nutom_i_ku`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Сверху выложите нарезанный красный сладкий перец
- `warning` `weak_serving_finish` r391 `r391_grecheskiy_salat_s_kuritsey_ogurtsom_tomatami_olivkami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смешайте с оливками, оливковым маслом, лимонным соком, орегано, солью и перцем
- `warning` `weak_serving_finish` r392 `r392_balzamicheskiy_salat_s_ogurtsom_cherri_fetoy_i_olivkam`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смешайте с оливками, оливковым маслом, бальзамическим уксусом, солью и перцем
- `warning` `weak_serving_finish` r394 `r394_mini_salat_s_tomatami_ogurtsom_bazilikom_i_fetoy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смешайте с йогуртом, базиликом, маслом, лимонным соком, солью и перцем
- `warning` `weak_serving_finish` r395 `r395_sredizemnomorskiy_fasolevyy_salat_s_nutom_krasnoy_faso`: last instruction sentence does not clearly finish with serving/ready wording Evidence: В отдельной небольшой миске взбейте оливковое масло, лимонный сок, пропущенный через пресс чеснок, мелкую соль и хлопья красного перца
- `warning` `weak_serving_finish` r396 `r396_chashechki_iz_salata_s_chernoy_fasolyu_avokado_halapen`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите начинку в листья салата
- `warning` `weak_serving_finish` r397 `r397_salatnye_listya_s_nutom_avokado_i_yogurtovym_sousom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите начинку в листья салата
- `warning` `weak_serving_finish` r398 `r398_salatnye_listya_s_indeykoy_yogurtom_i_izyumom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите начинку в листья салата
- `warning` `weak_serving_finish` r399 `r399_ryba_v_salatnyh_listyah_s_morkovyu_i_yogurtovym_sousom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите рыбу, морковь, огурец и соус в листья салата
- `warning` `weak_serving_finish` r400 `r400_salatnye_chashechki_s_krevetkami_i_krabovymi_palochkam`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смешайте с йогуртом, лимонным соком, солью и перцем, выложите в листья салата
- `warning` `weak_serving_finish` r405 `r405_belkovyy_salat_s_tuntsom_yaytsom_i_svezhimi_ovoschami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите сверху яйца, чтобы сохранить их текстуру
- `warning` `weak_serving_finish` r411 `r411_pp_oladi_iz_kabachkov`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выкладывайте тесто столовой ложкой на разогретую сковороду, обжаривайте оладьи на небольшом огне по 5—6 минут с каждой стороны, до румяной корочки
- `warning` `weak_serving_finish` r414 `r414_ovsyanoblin_s_tvorozhnym_syrom_konservirovannym_tuntso`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте тунец, авокадо и огурец, сложите пополам
- `warning` `weak_serving_finish` r416 `r416_tselnozernovoy_hleb_s_pechenyu_treski`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите печень на хлеб, добавьте огурец и зелень
- `warning` `weak_serving_finish` r417 `r417_aromatnyy_sup_pyure_iz_tsukini_i_chechevitsy`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Пробейте суп блендером до гладкости, посолите и поперчите по вкусу
- `warning` `weak_serving_finish` r424 `r424_salat_iz_pecheni_treski_s_yaytsom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смешайте печень, яйцо, огурец и лук, приправьте зерновой горчицей и солью
- `warning` `weak_serving_finish` r425 `r425_salat_iz_pecheni_treski_s_ogurtsom_i_kartofelem`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Смешайте все компоненты в салатнике, сбрызните лимонным соком и добавьте немного масла из консервов
- `warning` `weak_serving_finish` r428 `r428_domashniy_salat_iz_pecheni_treski_s_zelenym_goroshkom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте зеленый лук и майонез, аккуратно перемешайте
- `warning` `weak_serving_finish` r429 `r429_belkovyy_salat_s_kuritsey`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Заправьте салат соусом и аккуратно перемешайте
- `warning` `weak_serving_finish` r432 `r432_salat_s_pomidorami_krasnoe_more`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Заправьте греческим йогуртом, посолите, поперчите и перемешайте
- `warning` `weak_serving_finish` r436 `r436_lenivaya_ovsyanka_s_yagodami_i_orehami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Оставьте на 10-15 минут для набухания или уберите на ночь в холодильник
- `warning` `weak_serving_finish` r459 `r459_pisto`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте кусочки кабачка/цуккини и баклажана
- `warning` `weak_serving_finish` r461 `r461_bigus_iz_svezhey_kapusty`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Если помидора нет, можно добавить томатный сок или 1-2 ложки томатной пасты
- `warning` `weak_serving_finish` r465 `r465_kalmary_s_kartofelem_i_shpinatom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Посолите, добавьте в сотейник немного кипятка и закройте крышкой
- `warning` `weak_serving_finish` r481 `r481_dorado_s_risom_i_yaytsom_pashot`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Варите 3—4 минуты, пока белок не схватится
- `warning` `weak_serving_finish` r488 `r488_bystryy_sup_s_nutom_i_kuritsey`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Посолите, добавьте паприку и зелень
- `warning` `weak_serving_finish` r495 `r495_salat_s_shampinonami_i_sparzhey`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Заправьте маслом, апельсиновым соком и солью
- `warning` `weak_serving_finish` r496 `r496_karbonara_s_bekonom_i_slivkami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: К концу жарки кусочки уменьшатся
- `warning` `weak_serving_finish` r497 `r497_kacho_e_pepe`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Пока варятся макароны, масло и перец добавьте в другую сковороду и нагрейте на среднем огне до яркого аромата
- `warning` `weak_serving_finish` r500 `r500_pasta_boloneze`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Отварите пасту и смешайте ее с соусом болоньезе
- `warning` `weak_serving_finish` r505 `r505_pyure_iz_zelenogo_goroshka_s_krevetkami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Выложите пюре в тарелку, сверху положите креветки и кедровые орехи
- `warning` `weak_serving_finish` r507 `r507_onigiri`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Заверните нори конвертом
- `warning` `weak_serving_finish` r508 `r508_buterbrody_s_kuritsey_i_ovoschami`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Накройте вторым ломтиком хлеба
- `warning` `weak_serving_finish` r509 `r509_hlebtsy_s_avokado_i_lososem`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Добавьте кусочки лосося
- `warning` `weak_serving_finish` r511 `r511_sendvich_s_tuntsom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Накройте вторым ломтиком хлеба
- `warning` `weak_serving_finish` r516 `r516_sendvich_s_kuritsey_i_syrom`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Накройте сэндвич оставшимся хлебом
- `warning` `weak_serving_finish` r518 `r518_kuritsa_s_risom_i_ovoschami_na_skovorode`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Тушите под крышкой 20 минут
- `warning` `weak_serving_finish` r520 `r520_pasta_s_kuritsey_v_tomatnom_souse`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Потушите 10 минут и смешайте с пастой
- `warning` `weak_serving_finish` r522 `r522_tefteli_v_tomatnom_souse`: last instruction sentence does not clearly finish with serving/ready wording Evidence: Разогрейте растительное масло в сковороде, добавьте соус из томатной пасты и воды и потушите тефтели 25-30 минут
- ... 51 additional findings are in the CSV.

### Non-Cis/Unclear Ingredients

- none

### Tiny Gram Anomalies

- none

### Missing Approximate Measures

- `warning` `gram_only_user_hostile_measure` r022 `r022_frittata_s_kabachkom_shpinatom_i_rikottoy` `ricotta` line 6: gram-only ingredient should get an approximate household measure in the fix stage Evidence: рикотта — 31,2 г
- `warning` `gram_only_user_hostile_measure` r023 `r023_zapechennaya_frittata_so_shpinatom_pertsem_i_tomatami` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: нежирный зерненый творог — 75 г
- `warning` `gram_only_user_hostile_measure` r023 `r023_zapechennaya_frittata_so_shpinatom_pertsem_i_tomatami` `nutmeg` line 7: gram-only ingredient should get an approximate household measure in the fix stage Evidence: молотый мускатный орех — 0,12 г
- `warning` `gram_only_user_hostile_measure` r038 `r038_gollandskiy_blin_iz_duhovki` `nutmeg` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: молотый мускатный орех — 0,25 г
- `warning` `gram_only_user_hostile_measure` r067 `r067_sloenaya_zapekanka_s_vetchinoy_shpinatom_i_gryuyerom` `roasted_red_pepper` line 10: gram-only ingredient should get an approximate household measure in the fix stage Evidence: запеченный красный перец из банки — 15 твердый сыр — 14,2 г
- `warning` `gram_only_user_hostile_measure` r087 `r087_burrito_s_yaichnymi_belkami_shpinatom_i_kartofelem` `mozzarella` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Моцарелла — 56,7 г
- `warning` `gram_only_user_hostile_measure` r095 `r095_pankeyki_iz_tvoroga_i_ovsyanki` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: зерненый творог — 50 г
- `warning` `gram_only_user_hostile_measure` r100 `r100_yaichnye_mini_zapekanki_s_tvorogom_shpinatom_vyalenymi` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: зерненый творог — 14,2 г
- `warning` `gram_only_user_hostile_measure` r143 `r143_venetsianskoe_rizotto_s_krevetochnym_bulonom` `shrimp` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сырые крупные креветки в панцире — 112,5 г
- `warning` `gram_only_user_hostile_measure` r149 `r149_pasta_s_shafranom_midiyami_grebeshkami_i_krevetkami` `whole_wheat_pasta` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: длинные фузилли или другая паста или другая длинная тонкая паста — 100 г
- `warning` `gram_only_user_hostile_measure` r173 `r173_ovoschnaya_lazanya_s_tsukini_shpinatom_i_tvorozhnoy_na` `cottage_cheese` line 12: gram-only ingredient should get an approximate household measure in the fix stage Evidence: зерненый творог — 56,2 г
- `warning` `gram_only_user_hostile_measure` r178 `r178_kremovaya_tselnozernovaya_pasta_s_pesto_i_keylom` `whole_wheat_pasta` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: цельнозерновая паста — 75 г
- `warning` `gram_only_user_hostile_measure` r179 `r179_myasnaya_lazanya_s_rikottoy_i_tomatami` `tomato` line 6: gram-only ingredient should get an approximate household measure in the fix stage Evidence: томатный соус — 0,17 банки по 185 г
- `warning` `gram_only_user_hostile_measure` r179 `r179_myasnaya_lazanya_s_rikottoy_i_tomatami` `tomato_paste` line 7: gram-only ingredient should get an approximate household measure in the fix stage Evidence: томатная паста — 0,17 банки по 170 г
- `warning` `gram_only_user_hostile_measure` r179 `r179_myasnaya_lazanya_s_rikottoy_i_tomatami` `ricotta` line 17: gram-only ingredient should get an approximate household measure in the fix stage Evidence: рикотта — 37,5 г
- `warning` `gram_only_user_hostile_measure` r183 `r183_kurinyy_biryani_s_izyumom_i_mindalem` `thai_curry_paste` line 9: gram-only ingredient should get an approximate household measure in the fix stage Evidence: паста балти карри или мягкая индийская карри-паста — 15 г
- `warning` `gram_only_user_hostile_measure` r210 `r210_boul_s_kinoa_zapechennymi_ovoschami_i_pesto_iz_keyla` `quinoa` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Сырая киноа — 40 г
- `warning` `gram_only_user_hostile_measure` r213 `r213_ovoschnoy_minestrone_s_beloy_fasolyu_i_pastoy` `whole_wheat_pasta` line 15: gram-only ingredient should get an approximate household measure in the fix stage Evidence: мелкая паста — 25 г
- `warning` `gram_only_user_hostile_measure` r217 `r217_tayskiy_zelenyy_karri_sup_s_udonom_i_krevetkami` `shrimp` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сырые очищенные креветки — 75 г
- `warning` `gram_only_user_hostile_measure` r222 `r222_kurinaya_zapekanka_s_brokkoli_pastoy_i_mindalnoy_syrno` `whole_wheat_pasta` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: паста ракушки или перья — 90 г
- `warning` `gram_only_user_hostile_measure` r222 `r222_kurinaya_zapekanka_s_brokkoli_pastoy_i_mindalnoy_syrno` `tomato` line 6: gram-only ingredient should get an approximate household measure in the fix stage Evidence: паста из вяленых томатов — 15 г
- `warning` `gram_only_user_hostile_measure` r222 `r222_kurinaya_zapekanka_s_brokkoli_pastoy_i_mindalnoy_syrno` `greens` line 7: gram-only ingredient should get an approximate household measure in the fix stage Evidence: мягкий сыр с чесноком и зеленью — 20 г
- `warning` `gram_only_user_hostile_measure` r223 `r223_kurinaya_zapekanka_kordon_blyu_s_brokkoli_i_fuzilli` `cottage_cheese` line 9: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сухие твороговочные сухари — 7 г
- `warning` `gram_only_user_hostile_measure` r224 `r224_zapekanka_s_govyazhim_farshem_tsvetnoy_kapustoy_i_ched` `tomato` line 7: gram-only ingredient should get an approximate household measure in the fix stage Evidence: томатный соус — 65 г
- `warning` `gram_only_user_hostile_measure` r230 `r230_tetratstsini_iz_indeyki_s_gribami_goroshkom_i_parmezan` `cottage_cheese` line 16: gram-only ingredient should get an approximate household measure in the fix stage Evidence: твороговочные сухари — 15 г
- `warning` `gram_only_user_hostile_measure` r237 `r237_salat_s_tuntsom_fasolyu_yablokom_i_fetoy` `feta` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Фета — 35 г
- `warning` `gram_only_user_hostile_measure` r240 `r240_tunets_so_shpinatom_olivkami_fetoy_i_yogurtovoy_zaprav` `feta` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Фета — 40 г
- `warning` `gram_only_user_hostile_measure` r245 `r245_goanskoe_karri_s_krevetkami_kartofelem_i_kokosom` `shrimp` line 15: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сырые очищенные креветки — 100 г
- `warning` `gram_only_user_hostile_measure` r246 `r246_bystro_obzharennaya_govyadina_s_brokkoli_i_morkovyu` `spaghetti` line 13: gram-only ingredient should get an approximate household measure in the fix stage Evidence: готовая паста тонкая паста капеллини или спагетти-сквош — 85 г
- `warning` `gram_only_user_hostile_measure` r252 `r252_lavash_roll_s_kuritsey_i_ovoschami` `cream_cheese` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творожный сыр — 45 г
- `warning` `gram_only_user_hostile_measure` r253 `r253_tvorog_s_yagodami_i_gretskim_orehom` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 200 г
- `warning` `gram_only_user_hostile_measure` r256 `r256_hlebtsy_s_lososem_i_tvorozhnym_syrom` `cream_cheese` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творожный сыр — 45 г
- `warning` `gram_only_user_hostile_measure` r259 `r259_kefirnyy_smuzi_s_tvorogom_i_bananom` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 120 г
- `warning` `gram_only_user_hostile_measure` r261 `r261_bystrye_syrniki_s_yogurtom` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 180 г
- `warning` `gram_only_user_hostile_measure` r264 `r264_tvorozhnyy_dip_s_semechkami_i_ovoschami` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 180 г
- `warning` `gram_only_user_hostile_measure` r267 `r267_hlebtsy_s_tvorogom_golubikoy_i_arahisovoy_pastoy` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 180 г
- `warning` `gram_only_user_hostile_measure` r268 `r268_roll_s_indeykoy_tvorozhnym_syrom_i_ogurtsom` `cream_cheese` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творожный сыр — 45 г
- `warning` `gram_only_user_hostile_measure` r278 `r278_tsatsiki_s_morkovyu_ogurtsom_pertsem_i_pitoy` `cucumber` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Огурец для соуса — 100 г
- `warning` `gram_only_user_hostile_measure` r284 `r284_ogurechnye_tosty_s_rikottoy_i_zelenyu` `ricotta` line 8: gram-only ingredient should get an approximate household measure in the fix stage Evidence: рикотта из цельного молока — 60 г
- `warning` `gram_only_user_hostile_measure` r288 `r288_tost_s_indeykoy_tvorozhnym_syrom_i_inzhirom` `cream_cheese` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творожный сыр — 45 г
- `warning` `gram_only_user_hostile_measure` r292 `r292_omlet_s_tremya_syrami_i_zelenym_lukom` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 60 г
- `warning` `gram_only_user_hostile_measure` r300 `r300_omlet_s_bekonom_gaudoy_i_tvorozhnym_syrom` `cream_cheese` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творожный сыр — 35 г
- `warning` `gram_only_user_hostile_measure` r301 `r301_tvorog_s_bananom_i_orehom` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 200 г
- `warning` `gram_only_user_hostile_measure` r303 `r303_ovsyanka_s_tvorogom_bananom_i_chernikoy` `cottage_cheese` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 120 г
- `warning` `gram_only_user_hostile_measure` r304 `r304_tvorog_s_yablokom_izyumom_i_koritsey` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 200 г
- `warning` `gram_only_user_hostile_measure` r310 `r310_ovsyanyy_pankeyk_s_yablokom_na_kefire` `cottage_cheese` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 80 г
- `warning` `gram_only_user_hostile_measure` r318 `r318_shokoladnyy_proteinovyy_sheyk_s_tvorogom` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 150 г
- `warning` `gram_only_user_hostile_measure` r321 `r321_tvorozhnyy_desert_v_banke_s_persikom_i_gretskim_orehom` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: низкожирный творог без соли — 120 г
- `warning` `gram_only_user_hostile_measure` r322 `r322_tvorozhnaya_chasha_s_yagodami_gretskim_orehom_i_hrusty` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: низкожирный творог без соли — 110 г
- `warning` `gram_only_user_hostile_measure` r323 `r323_tvorog_s_malinovym_medom_i_semechkami` `cottage_cheese` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: низкожирный творог — 110 г
- `warning` `gram_only_user_hostile_measure` r327 `r327_klubnichnyy_chizkeyk_na_yogurte` `cream_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творожный сыр — 50 г
- `warning` `gram_only_user_hostile_measure` r330 `r330_tvorozhnyy_tiramisu_s_kofe` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 180 г
- `warning` `gram_only_user_hostile_measure` r333 `r333_hlebtsy_s_tvorogom_i_tuntsom` `cottage_cheese` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 100 г
- `warning` `gram_only_user_hostile_measure` r341 `r341_pechenoe_yabloko_s_tvorogom_i_izyumom` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 150 г
- `warning` `gram_only_user_hostile_measure` r343 `r343_yablochnye_dolki_s_tvorozhno_arahisovym_dipom` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 160 г
- `warning` `gram_only_user_hostile_measure` r346 `r346_mango_yogurtovyy_boul_s_tvorogom` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 150 г
- `warning` `gram_only_user_hostile_measure` r356 `r356_pita_s_humusom_morkovyu_kartofelem_i_fetoy` `feta` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Фета — 40 г
- `warning` `gram_only_user_hostile_measure` r360 `r360_ruletiki_iz_tortili_so_slivochno_pryanym_kremom_i_ovos` `ranch_seasoning` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сухая смесь для заправки ранч-соус — 2 г
- `warning` `gram_only_user_hostile_measure` r361 `r361_edamame_s_tvorogom_i_ogurtsom` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 150 г
- `warning` `gram_only_user_hostile_measure` r362 `r362_tvorog_s_mindalem_izyumom_i_vozdushnoy_pshenitsey` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 200 г
- `warning` `gram_only_user_hostile_measure` r372 `r372_fruktovyy_tvorog_s_mango_kivi_i_yagodami` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 200 г
- `warning` `gram_only_user_hostile_measure` r373 `r373_klubnichno_bananovyy_kefirnyy_smuzi_s_tvorogom` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 140 г
- `warning` `gram_only_user_hostile_measure` r377 `r377_yagodnyy_tvorozhnyy_krem_s_limonom` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 200 г
- `warning` `gram_only_user_hostile_measure` r378 `r378_shokoladno_bananovyy_tvorog` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 200 г
- `warning` `gram_only_user_hostile_measure` r380 `r380_persikovyy_tvorog_s_vanilyu` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 200 г
- `warning` `gram_only_user_hostile_measure` r387 `r387_tvorozhnaya_banochka_s_pertsem_hrustyaschim_nutom_i_ku` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: низкосолевой творог 2% — 70 г
- `warning` `gram_only_user_hostile_measure` r388 `r388_mini_pertsy_s_tvorozhnoy_nachinkoy_parmezanom_i_limono` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Творог 5% — 150 г
- `warning` `gram_only_user_hostile_measure` r391 `r391_grecheskiy_salat_s_kuritsey_ogurtsom_tomatami_olivkami` `feta` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Фета — 45 г
- `warning` `gram_only_user_hostile_measure` r392 `r392_balzamicheskiy_salat_s_ogurtsom_cherri_fetoy_i_olivkam` `feta` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Фета — 45 г
- `warning` `gram_only_user_hostile_measure` r394 `r394_mini_salat_s_tomatami_ogurtsom_bazilikom_i_fetoy` `feta` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Фета — 50 г
- `warning` `gram_only_user_hostile_measure` r396 `r396_chashechki_iz_salata_s_chernoy_fasolyu_avokado_halapen` `feta` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: Фета — 45 г
- `warning` `gram_only_user_hostile_measure` r402 `r402_tvorog_s_yaytsom_na_skovorode` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог 2-5% (размять) — 60 г
- `warning` `gram_only_user_hostile_measure` r403 `r403_omlet_s_tvorogom_i_zelenyu` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог — 80 г
- `warning` `gram_only_user_hostile_measure` r408 `r408_sendvich_s_tvorozhnym_sousom` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог мягкий 2-5% — 100 г
- `warning` `gram_only_user_hostile_measure` r409 `r409_rikotta_s_fruktami` `ricotta` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: рикотта или мягкий творог — 120 г
- `warning` `gram_only_user_hostile_measure` r419 `r419_salat_s_tuntsom_yaytsom_fasolyu_i_ovoschami` `sour_cream` line 7: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сметана (для соуса) — 20 г
- `warning` `gram_only_user_hostile_measure` r420 `r420_lenivyy_hachapuri_po_adzharski` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог 2-5% (хорошо размять) — 150 г
- `warning` `gram_only_user_hostile_measure` r423 `r423_ovsyanaya_kasha_s_tomatami_zelenym_goroshkom_i_rikotto` `ricotta` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: рикотта или мягкий творог — 50 г
- `warning` `gram_only_user_hostile_measure` r429 `r429_belkovyy_salat_s_kuritsey` `parmesan` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр пармезан — 50 г
- `warning` `gram_only_user_hostile_measure` r432 `r432_salat_s_pomidorami_krasnoe_more` `gouda` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр гауда (натереть) — 35 г
- `warning` `gram_only_user_hostile_measure` r433 `r433_shokoladnyy_pp_desert_s_bananom_v_mikrovolnovke` `greek_yogurt` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: йогурт натуральный (для соуса) — 50 г
- `warning` `gram_only_user_hostile_measure` r433 `r433_shokoladnyy_pp_desert_s_bananom_v_mikrovolnovke` `honey` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: мед (для соуса) — 8 г
- `warning` `gram_only_user_hostile_measure` r437 `r437_tvorog_s_medom_i_fruktami` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог 2-5% — 180 г
- `warning` `gram_only_user_hostile_measure` r444 `r444_tvorog_s_ukropom_s_tselnozernovym_hlebom` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог 5% — 110 г
- `warning` `gram_only_user_hostile_measure` r445 `r445_tvorog_s_ukropom_i_hlebtsami` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог 5% — 110 г
- `warning` `gram_only_user_hostile_measure` r446 `r446_tvorog_s_ukropom_i_morkovnymi_palochkami` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог 5% — 110 г
- `warning` `gram_only_user_hostile_measure` r460 `r460_makarony_s_yaytsom_i_syrom` `whole_wheat_pasta` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: цельнозерновая паста — 60 г
- `warning` `gram_only_user_hostile_measure` r466 `r466_shaurma_iz_morkovi` `gouda` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр гауда (натереть) — 50 г
- `warning` `gram_only_user_hostile_measure` r467 `r467_pirozhki_s_yaytsom_i_tvorogom` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог обезжиренный высокобелковый — 50 г
- `warning` `gram_only_user_hostile_measure` r476 `r476_syrniki_na_kokosovoy_muke` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творог — 130 г
- `warning` `gram_only_user_hostile_measure` r490 `r490_buterbrod_s_vetchinoy_i_omletom` `cream_cheese` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сливочный сыр — 50 г
- `warning` `gram_only_user_hostile_measure` r493 `r493_shaurma_s_falafelem` `greek_yogurt` line 8: gram-only ingredient should get an approximate household measure in the fix stage Evidence: греческий йогурт (для контролируемого соуса) — 30 г
- `warning` `gram_only_user_hostile_measure` r493 `r493_shaurma_s_falafelem` `lemon_juice` line 10: gram-only ingredient should get an approximate household measure in the fix stage Evidence: лимонный сок (для контролируемого соуса) — 5 г
- `warning` `gram_only_user_hostile_measure` r496 `r496_karbonara_s_bekonom_i_slivkami` `bacon` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: бекон сырокопченый (кусочками) — 60 г
- `warning` `gram_only_user_hostile_measure` r499 `r499_pasta_s_krevetkami_i_sousom_pesto` `whole_wheat_pasta` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: длинная паста — 80 г
- `warning` `gram_only_user_hostile_measure` r500 `r500_pasta_boloneze` `whole_wheat_pasta` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: цельнозерновая паста — 100 г
- `warning` `gram_only_user_hostile_measure` r501 `r501_pasta_s_kurinym_file_v_ostrom_tomatnom_souse` `whole_wheat_pasta` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: цельнозерновая паста — 100 г
- `warning` `gram_only_user_hostile_measure` r502 `r502_pasta_s_lososem_i_shpinatom_v_slivochnom_souse` `whole_wheat_pasta` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: цельнозерновая паста — 100 г
- `warning` `gram_only_user_hostile_measure` r502 `r502_pasta_s_lososem_i_shpinatom_v_slivochnom_souse` `cream_cheese` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творожный сыр — 35 г
- `warning` `gram_only_user_hostile_measure` r504 `r504_makarony_po_flotski` `whole_wheat_pasta` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: цельнозерновая паста — 50 г
- `warning` `gram_only_user_hostile_measure` r509 `r509_hlebtsy_s_avokado_i_lososem` `cream_cheese` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творожный сыр — 80 г
- `warning` `gram_only_user_hostile_measure` r512 `r512_lavash_s_tvorogom_i_zelenyu` `cottage_cheese` line 2: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творога — 200 г
- `warning` `gram_only_user_hostile_measure` r513 `r513_syrniki_na_risovoy_muke` `cottage_cheese` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: творога — 180 г
- `warning` `gram_only_user_hostile_measure` r517 `r517_lavash_s_kuritsey_i_gribami` `parmesan` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: твердый сыр — 40 г
- `warning` `gram_only_user_hostile_measure` r520 `r520_pasta_s_kuritsey_v_tomatnom_souse` `whole_wheat_pasta` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: паста — 100 г
- `warning` `gram_only_user_hostile_measure` r526 `r526_pasta_s_tuntsom_i_tomatami` `whole_wheat_pasta` line 1: gram-only ingredient should get an approximate household measure in the fix stage Evidence: паста — 100 г
- `warning` `gram_only_user_hostile_measure` r552 `r552_meksikanskaya_zapekanka_s_risom_i_fasolyu` `gouda` line 6: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр гауда — 40 г
- `warning` `gram_only_user_hostile_measure` r556 `r556_kartofelnye_nokki` `tomato` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: томаты в собственном соку — 120 г (без добавленного соуса)
- `warning` `gram_only_user_hostile_measure` r556 `r556_kartofelnye_nokki` `gouda` line 6: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр гауда — 40 г
- `warning` `gram_only_user_hostile_measure` r557 `r557_pitstsa_na_osnove_iz_tsvetnoy_kapusty` `gouda` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр гауда — 40 г
- `warning` `gram_only_user_hostile_measure` r557 `r557_pitstsa_na_osnove_iz_tsvetnoy_kapusty` `tomato` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: томаты в собственном соку — 120 г (без добавленного соуса)
- `warning` `gram_only_user_hostile_measure` r557 `r557_pitstsa_na_osnove_iz_tsvetnoy_kapusty` `mozzarella` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: моцарелла — 40 г
- `warning` `gram_only_user_hostile_measure` r559 `r559_ruletiki_iz_baklazhanov_s_myasom_i_syrom` `tomato` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: томаты в собственном соку — 120 г (без добавленного соуса)
- `warning` `gram_only_user_hostile_measure` r559 `r559_ruletiki_iz_baklazhanov_s_myasom_i_syrom` `gouda` line 4: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр гауда — 40 г
- `warning` `gram_only_user_hostile_measure` r561 `r561_kurinyy_burger_bez_bulki` `gouda` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр гауда — 40 г
- `warning` `gram_only_user_hostile_measure` r561 `r561_kurinyy_burger_bez_bulki` `greek_yogurt` line 7: gram-only ingredient should get an approximate household measure in the fix stage Evidence: йогурт — 40 г (для соуса)
- `warning` `gram_only_user_hostile_measure` r562 `r562_rizotto_s_tykvoy_i_tverdym_syrom` `parmesan` line 6: gram-only ingredient should get an approximate household measure in the fix stage Evidence: твердый сыр — 40 г
- `warning` `gram_only_user_hostile_measure` r564 `r564_enchilada_v_kukuruznyh_tortilyah` `tomato` line 3: gram-only ingredient should get an approximate household measure in the fix stage Evidence: томаты в собственном соку — 120 г (без добавленного соуса)
- `warning` `gram_only_user_hostile_measure` r564 `r564_enchilada_v_kukuruznyh_tortilyah` `gouda` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр гауда — 40 г
- `warning` `gram_only_user_hostile_measure` r565 `r565_kuritsa_s_pesto_i_kartofelem` `gouda` line 5: gram-only ingredient should get an approximate household measure in the fix stage Evidence: сыр гауда — 40 г
- ... 13 additional findings are in the CSV.

## Notes For Fix Stage

- Hummus/title consistency is audited separately from recipes that make hummus from chickpeas/tahini.
- Harissa, edamame, and American-cheese checks distinguish user-facing recipe content from internal IDs/catalog rows.
- Missing approximate measures are warnings, not fixes; this report only identifies gram-only rows that are awkward for users.
