import json
from pathlib import Path

from scripts.dev.recipe_importer.cli import main


def test_cli_audit_writes_expected_files(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    photos_dir = input_dir / "photo-work" / "batch_01"
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "out"
    photos_dir.mkdir(parents=True)
    data_dir.mkdir()
    (data_dir / "curated_foods.json").write_text(
        json.dumps(
            [
                {
                    "food_id": "olive_oil",
                    "nutrients_per_100g": {
                        "energy_kcal": 884,
                        "protein_g": 0,
                        "fat_g": 100,
                        "carbohydrate_g": 0,
                        "fiber_g": 0,
                        "sodium_mg": 2,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (photos_dir / "c001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (input_dir / "photo_ready.csv").write_text(
        "\n".join(
            [
                "candidate_id,title_ru,meal_type_guess,why_photo_ready,duplicate_risk,structured_ingredients,servings",
                'c001,Photo only,main,clear visual,low,"[{""name"": ""olive oil"", ""amount"": 10, ""unit"": ""g""}]",2',
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "audit",
            "--input",
            str(input_dir),
            "--input-format",
            "photo_prep_317",
            "--photos",
            str(input_dir / "photo-work"),
            "--out",
            str(out_dir),
            "--data-dir",
            str(data_dir),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    expected_files = {
        "normalized_recipes.csv",
        "photo_manifest.csv",
        "structured_ingredients.csv",
        "mapping_report.csv",
        "nutrition_rows.csv",
        "classification.csv",
        "review_table.csv",
        "audit_report.md",
        "manifest.json",
    }
    assert expected_files == {path.name for path in out_dir.iterdir()}
    classification = (out_dir / "classification.csv").read_text(encoding="utf-8")
    assert "import_ready" in classification
    assert "ok" in classification
    mapping_report = (out_dir / "mapping_report.csv").read_text(encoding="utf-8")
    assert "olive oil" in mapping_report
    nutrition = (out_dir / "nutrition_rows.csv").read_text(encoding="utf-8")
    assert "88.4" in nutrition
    assert "ok" in nutrition
    assert "dry_run: true" in (out_dir / "audit_report.md").read_text(encoding="utf-8")


def test_cli_audit_writes_production_rows_only_under_out(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    photos_dir = input_dir / "photo-work" / "batch_01"
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "out"
    photos_dir.mkdir(parents=True)
    data_dir.mkdir()
    (data_dir / "curated_foods.json").write_text(
        json.dumps(
            [
                {
                    "food_id": "olive_oil",
                    "nutrients_per_100g": {
                        "energy_kcal": 884,
                        "protein_g": 0,
                        "fat_g": 100,
                        "carbohydrate_g": 0,
                        "fiber_g": 0,
                        "sodium_mg": 2,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (photos_dir / "c001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (input_dir / "photo_ready.csv").write_text(
        "\n".join(
            [
                "candidate_id,title_ru,meal_type_guess,why_photo_ready,duplicate_risk,structured_ingredients,servings,source_url",
                'c001,Photo only,main,clear visual,low,"[{""name"": ""olive oil"", ""amount"": 10, ""unit"": ""g""}]",2,https://example.test/photo-only',
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "audit",
            "--input",
            str(input_dir),
            "--input-format",
            "photo_prep_317",
            "--photos",
            str(input_dir / "photo-work"),
            "--out",
            str(out_dir),
            "--data-dir",
            str(data_dir),
            "--recipe-no-start",
            "711",
            "--recipe-key-prefix",
            "import202606_",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    production_dir = out_dir / "production_rows"
    assert {
        "curated_recipes.json",
        "curated_recipe_ingredients.json",
        "curated_recipe_nutrition.json",
        "photo_manifest.csv",
    } == {path.name for path in production_dir.iterdir()}
    assert (out_dir / "apply_preview.md").exists()
    assert not (tmp_path / "src" / "diet_bot" / "data").exists()

    recipes = json.loads((production_dir / "curated_recipes.json").read_text(encoding="utf-8"))
    assert recipes[0]["recipe_no"] == 711
    assert recipes[0]["recipe_key"] == "import202606_001"
