import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.dev.recipe_importer.apply import ApplyError, apply_run, build_apply_plan
from scripts.dev.recipe_importer.cli import main


def test_apply_refuses_missing_approval(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path)

    with pytest.raises(ApplyError, match="missing required approval"):
        build_apply_plan(run_dir, tmp_path / "data")


def test_apply_refuses_tampered_manifest_file(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path)
    _write_approval(run_dir, ["c001"])
    recipes_path = run_dir / "production_rows" / "curated_recipes.json"
    recipes_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ApplyError, match="manifest hash mismatch"):
        build_apply_plan(run_dir, tmp_path / "data")


def test_apply_refuses_non_import_ready_candidate(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path)
    _write_approval(run_dir, ["c003"])

    with pytest.raises(ApplyError, match="not import_ready"):
        build_apply_plan(run_dir, tmp_path / "data")


def test_apply_dry_run_writes_no_data_files(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path)
    data_dir = tmp_path / "data"
    _write_approval(run_dir, ["c001"])

    plan = apply_run(run_dir, data_dir, write=False)

    assert plan.write is False
    assert plan.candidate_ids == ["c001"]
    assert plan.recipes == 1
    assert not data_dir.exists()


def test_cli_apply_write_to_tmp_data_dir_writes_selected_json_and_photo(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path)
    data_dir = tmp_path / "data"
    _write_approval(run_dir, ["c001"])

    exit_code = main(
        [
            "apply",
            "--run",
            str(run_dir),
            "--data-dir",
            str(data_dir),
            "--write",
        ]
    )

    assert exit_code == 0
    assert sorted(_relative_files(data_dir)) == [
        "curated_recipe_ingredients.json",
        "curated_recipe_nutrition.json",
        "curated_recipes.json",
        "recipe_photos/r711.jpg",
    ]
    recipes = json.loads((data_dir / "curated_recipes.json").read_text(encoding="utf-8"))
    ingredients = json.loads(
        (data_dir / "curated_recipe_ingredients.json").read_text(encoding="utf-8")
    )
    nutrition = json.loads(
        (data_dir / "curated_recipe_nutrition.json").read_text(encoding="utf-8")
    )
    assert [row["import_metadata"]["candidate_id"] for row in recipes] == ["c001"]
    assert {row["recipe_id"] for row in ingredients} == {"r711_alpha_bowl"}
    assert {row["recipe_id"] for row in nutrition} == {"r711_alpha_bowl"}
    assert (data_dir / "recipe_photos" / "r711.jpg").read_bytes() == b"alpha-photo"


def test_apply_refuses_photo_target_outside_data_dir(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, malicious_target=True)
    _write_approval(run_dir, ["c001"])

    with pytest.raises(ApplyError, match="target path escapes data-dir"):
        build_apply_plan(run_dir, tmp_path / "data")


def _write_run(tmp_path: Path, *, malicious_target: bool = False) -> Path:
    run_dir = tmp_path / "run"
    production_dir = run_dir / "production_rows"
    photos_dir = tmp_path / "photos" / "batch_01"
    production_dir.mkdir(parents=True)
    photos_dir.mkdir(parents=True)
    (photos_dir / "c001.jpg").write_bytes(b"alpha-photo")
    (photos_dir / "c002.jpg").write_bytes(b"beta-photo")

    _write_csv(
        run_dir / "classification.csv",
        [
            {
                "candidate_id": "c001",
                "title_ru": "Alpha Bowl",
                "classification": "import_ready",
            },
            {
                "candidate_id": "c002",
                "title_ru": "Beta Bowl",
                "classification": "import_ready",
            },
            {
                "candidate_id": "c003",
                "title_ru": "Blocked Bowl",
                "classification": "blocked",
            },
        ],
    )
    _write_json(
        production_dir / "curated_recipes.json",
        [
            _recipe_row("c001", "r711_alpha_bowl", "recipe_photos/r711.jpg"),
            _recipe_row("c002", "r712_beta_bowl", "recipe_photos/r712.jpg"),
        ],
    )
    _write_json(
        production_dir / "curated_recipe_ingredients.json",
        [
            {"recipe_id": "r711_alpha_bowl", "recipe_key": "import202606_001"},
            {"recipe_id": "r712_beta_bowl", "recipe_key": "import202606_002"},
        ],
    )
    _write_json(
        production_dir / "curated_recipe_nutrition.json",
        [
            {"recipe_id": "r711_alpha_bowl", "recipe_key": "import202606_001"},
            {"recipe_id": "r712_beta_bowl", "recipe_key": "import202606_002"},
        ],
    )
    _write_csv(
        production_dir / "photo_manifest.csv",
        [
            {
                "candidate_id": "c001",
                "recipe_id": "r711_alpha_bowl",
                "recipe_no": "711",
                "recipe_key": "import202606_001",
                "source_photo_path": "batch_01/c001.jpg",
                "target_photo_path": "../outside.jpg"
                if malicious_target
                else "src/diet_bot/data/recipe_photos/r711.jpg",
                "photo_ext": ".jpg",
                "photo_size_bytes": "11",
            },
            {
                "candidate_id": "c002",
                "recipe_id": "r712_beta_bowl",
                "recipe_no": "712",
                "recipe_key": "import202606_002",
                "source_photo_path": "batch_01/c002.jpg",
                "target_photo_path": "src/diet_bot/data/recipe_photos/r712.jpg",
                "photo_ext": ".jpg",
                "photo_size_bytes": "10",
            },
        ],
    )
    _write_manifest(run_dir, photos_dir.parent)
    return run_dir


def _write_approval(run_dir: Path, candidate_ids: list[str]) -> None:
    _write_json(
        run_dir / "approval.json",
        {
            "approved_by": "operator@example.test",
            "candidate_ids": candidate_ids,
        },
    )


def _recipe_row(candidate_id: str, recipe_id: str, image_url: str) -> dict[str, object]:
    return {
        "recipe_id": recipe_id,
        "recipe_key": recipe_id.replace("r711_alpha_bowl", "import202606_001").replace(
            "r712_beta_bowl", "import202606_002"
        ),
        "title_ru": recipe_id,
        "image_url": image_url,
        "import_metadata": {"candidate_id": candidate_id},
    }


def _write_manifest(run_dir: Path, photos_dir: Path) -> None:
    files = [
        "classification.csv",
        "production_rows/curated_recipes.json",
        "production_rows/curated_recipe_ingredients.json",
        "production_rows/curated_recipe_nutrition.json",
        "production_rows/photo_manifest.csv",
    ]
    manifest = {
        "schema_version": 1,
        "photos_dir": str(photos_dir),
        "files": [
            {"path": path, "sha256": _sha256(run_dir / path)}
            for path in files
        ],
    }
    _write_json(run_dir / "manifest.json", manifest)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_files(root: Path) -> list[str]:
    return [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    ]
