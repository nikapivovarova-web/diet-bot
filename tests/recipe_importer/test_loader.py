from pathlib import Path

from scripts.dev.recipe_importer.loader import load_photo_prep_317


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
