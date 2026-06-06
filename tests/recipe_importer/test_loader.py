from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.dev.recipe_importer.loader import (
    load_excel_400_workbook,
    load_photo_prep_317,
    load_second_pass_suitable_csv,
)


def test_load_photo_prep_317_reads_photo_ready_and_duplicate_risk(tmp_path: Path) -> None:
    input_dir = tmp_path / "photo-prep"
    input_dir.mkdir()
    (input_dir / "photo_ready.csv").write_text(
        "\n".join(
            [
                "candidate_id,title_ru,meal_type_guess,duplicate_risk",
                "c001,Test soup,main,low",
                "c002,Test salad,salad,medium",
            ]
        ),
        encoding="utf-8",
    )
    (input_dir / "duplicate_risk.csv").write_text(
        "\n".join(
            [
                "candidate_id,status,duplicate_risk,duplicate_reason,possible_duplicate_candidate_ids",
                "c002,PHOTO_READY,medium,salad family,c099",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_photo_prep_317(input_dir)

    assert [recipe.candidate_id for recipe in loaded.recipes] == ["c001", "c002"]
    assert loaded.recipes[1].title_ru == "Test salad"
    assert loaded.duplicate_risks["c002"].duplicate_reason == "salad family"
    assert loaded.source_counts["photo_ready"] == 2
    assert loaded.source_counts["duplicate_risk"] == 1


def test_loader_preserves_raw_recipe_context_fields(tmp_path: Path) -> None:
    input_dir = tmp_path / "photo-prep"
    input_dir.mkdir()
    (input_dir / "photo_ready.csv").write_text(
        "\n".join(
            [
                "candidate_id,title_ru,structured_ingredients,ingredient_text,instructions,total_time,source_url",
                'c001,Test,"[{""name"": ""water"", ""amount"": 100, ""unit"": ""ml""}]",Water - 100 ml,Boil,15 min,https://example.test/recipe',
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_photo_prep_317(input_dir)
    recipe = loaded.recipes[0]

    assert recipe.structured_ingredients.startswith('[{"name": "water"')
    assert recipe.raw_ingredient_text == "Water - 100 ml"
    assert recipe.instructions == "Boil"
    assert recipe.time == "15 min"
    assert recipe.source == "https://example.test/recipe"


def test_load_second_pass_suitable_csv_uses_csv_as_primary_source(tmp_path: Path) -> None:
    csv_path = tmp_path / "suitable_after_second_pass.csv"
    csv_path.write_text(
        "\n".join(
            [
                "candidate_id,source_page,source_row,title,likely_meal_slot,duplicate_risk,existing_catalog_match,existing_catalog_match_id,ingredients,instructions,cleaned_ingredients,cleaned_instructions",
                'c001,3,7,Empanadas,main,none,,,"* dough 100 g","Bake.","dough - 100 g","Bake 20 min."',
                'c002,5,8,Caesar salad,salad,medium,yes,r690,"lettuce 80 g","Mix.",,',
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_second_pass_suitable_csv(csv_path)

    assert loaded.source_counts["second_pass_suitable_csv"] == 2
    assert loaded.source_counts["second_pass_existing_catalog_matches"] == 1
    assert [recipe.candidate_id for recipe in loaded.recipes] == ["c001", "c002"]
    assert loaded.recipes[0].title_ru == "Empanadas"
    assert loaded.recipes[0].meal_type == "main"
    assert loaded.recipes[0].raw_ingredient_text == "dough - 100 g"
    assert loaded.recipes[0].instructions == "Bake 20 min."
    assert loaded.recipes[0].source == "source_page=3;source_row=7"
    assert loaded.duplicate_risks["c002"].duplicate_reason == "existing_catalog_match:r690"
    assert loaded.duplicate_risks["c002"].possible_duplicate_candidate_ids == "r690"


def test_load_excel_400_workbook_reads_recipes_sheet_from_row_5(tmp_path: Path) -> None:
    workbook_path = tmp_path / "recipes.xlsx"
    _write_minimal_xlsx(
        workbook_path,
        sheet_name="Рецепты",
        rows={
            4: ["№", "Категория", "Название", "Порции", "Время", "Ингредиенты"],
            5: [
                "1",
                "Завтрак",
                "Овсянка на ночь с ягодами",
                "1 порция",
                "10 мин + ночь",
                "Овсяные хлопья — 50 г\nЯгоды — 80 г",
                "Смешать и охладить.",
                "BBC Good Food",
            ],
            6: [
                "2",
                "Обед",
                "Тост с авокадо",
                "2 порции",
                "5 мин",
                "Авокадо — 1 шт. / ≈150 г мякоти",
                "Размять авокадо.",
                "Example",
            ],
        },
    )

    loaded = load_excel_400_workbook(workbook_path)

    assert loaded.source_counts["excel_400_workbook"] == 2
    assert loaded.source_counts["workbook_non_empty_rows"] == 2
    assert [recipe.candidate_id for recipe in loaded.recipes] == ["recipe_1", "recipe_2"]
    assert loaded.recipes[0].meal_type == "Завтрак"
    assert loaded.recipes[0].title_ru == "Овсянка на ночь с ягодами"
    assert loaded.recipes[0].servings == "1"
    assert loaded.recipes[0].raw_ingredient_text == "Овсяные хлопья — 50 г\nЯгоды — 80 г"
    assert loaded.recipes[0].instructions == "Смешать и охладить."
    assert loaded.recipes[0].time == "10 мин + ночь"
    assert loaded.recipes[0].source == "BBC Good Food"
    assert loaded.recipes[1].servings == "2"


def _write_minimal_xlsx(
    path: Path,
    *,
    sheet_name: str,
    rows: dict[int, list[str]],
) -> None:
    sheet_rows = []
    for row_index, values in sorted(rows.items()):
        cells = []
        for column_index, value in enumerate(values, start=1):
            if value == "":
                continue
            cells.append(
                f'<c r="{_column_name(column_index)}{row_index}" t="inlineStr">'
                f"<is><t>{_xml_escape(value)}</t></is></c>"
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
""",
        )
        archive.writestr(
            "xl/workbook.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="{_xml_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>
""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>{''.join(sheet_rows)}</sheetData>
</worksheet>
""",
        )


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
