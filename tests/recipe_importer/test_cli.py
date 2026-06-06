from pathlib import Path

from scripts.dev.recipe_importer.cli import main


def test_cli_audit_writes_expected_files(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    photos_dir = input_dir / "photo-work" / "batch_01"
    out_dir = tmp_path / "out"
    photos_dir.mkdir(parents=True)
    (photos_dir / "c001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (input_dir / "photo_ready.csv").write_text(
        "\n".join(
            [
                "candidate_id,title_ru,meal_type_guess,why_photo_ready,duplicate_risk,structured_ingredients,servings",
                'c001,Photo only,main,clear visual,low,"[{""name"": ""water"", ""amount"": 100, ""unit"": ""ml""}]",2',
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
            "--dry-run",
        ]
    )

    assert exit_code == 0
    expected_files = {
        "normalized_recipes.csv",
        "photo_manifest.csv",
        "structured_ingredients.csv",
        "mapping_report.csv",
        "classification.csv",
        "review_table.csv",
        "audit_report.md",
    }
    assert expected_files == {path.name for path in out_dir.iterdir()}
    classification = (out_dir / "classification.csv").read_text(encoding="utf-8")
    assert "import_ready" in classification
    assert "nutrition_pending" in classification
    mapping_report = (out_dir / "mapping_report.csv").read_text(encoding="utf-8")
    assert "water" in mapping_report
    assert "dry_run: true" in (out_dir / "audit_report.md").read_text(encoding="utf-8")
