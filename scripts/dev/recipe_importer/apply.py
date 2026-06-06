from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PRODUCTION_JSON_FILES = (
    "curated_recipes.json",
    "curated_recipe_ingredients.json",
    "curated_recipe_nutrition.json",
)


class ApplyError(ValueError):
    """Raised when an importer run is not safe to apply."""


@dataclass(frozen=True)
class ApplyPlan:
    run_dir: Path
    data_dir: Path
    approved_by: str
    candidate_ids: list[str]
    write: bool
    recipes: int
    ingredients: int
    nutrition: int
    photos: int
    target_files: list[Path]

    def summary(self) -> str:
        mode = "write" if self.write else "dry-run"
        targets = "\n".join(f"- {path}" for path in self.target_files)
        if not targets:
            targets = "- no target files"
        return "\n".join(
            [
                f"mode: {mode}",
                f"run_dir: {self.run_dir}",
                f"data_dir: {self.data_dir}",
                f"approved_by: {self.approved_by}",
                f"candidate_ids: {', '.join(self.candidate_ids)}",
                f"curated_recipes rows: {self.recipes}",
                f"curated_recipe_ingredients rows: {self.ingredients}",
                f"curated_recipe_nutrition rows: {self.nutrition}",
                f"photo copies: {self.photos}",
                "target_files:",
                targets,
            ]
        )


@dataclass(frozen=True)
class _PreparedApply:
    plan: ApplyPlan
    recipes: list[dict[str, Any]]
    ingredients: list[dict[str, Any]]
    nutrition: list[dict[str, Any]]
    photos: list[tuple[Path, Path]]


def build_apply_plan(run_dir: Path, data_dir: Path, *, write: bool = False) -> ApplyPlan:
    return _prepare_apply(run_dir, data_dir, write=write).plan


def apply_run(run_dir: Path, data_dir: Path, *, write: bool = False) -> ApplyPlan:
    prepared = _prepare_apply(run_dir, data_dir, write=write)
    if write:
        _write_prepared(prepared)
    return prepared.plan


def _prepare_apply(run_dir: Path, data_dir: Path, *, write: bool) -> _PreparedApply:
    run_dir = Path(run_dir)
    data_dir = Path(data_dir)
    approval = _load_approval(run_dir)
    manifest = _load_manifest(run_dir)
    _verify_manifest(run_dir, manifest)

    production_dir = run_dir / "production_rows"
    _require_production_rows(run_dir, manifest, production_dir)

    classifications = _load_classifications(run_dir / "classification.csv")
    candidate_ids = approval["candidate_ids"]
    _verify_candidate_classifications(candidate_ids, classifications, approval)

    recipes_all = _read_json_list(production_dir / "curated_recipes.json")
    ingredients_all = _read_json_list(production_dir / "curated_recipe_ingredients.json")
    nutrition_all = _read_json_list(production_dir / "curated_recipe_nutrition.json")
    photo_rows_all = _read_csv(production_dir / "photo_manifest.csv")

    recipes = _select_recipes(candidate_ids, recipes_all)
    recipe_ids = {str(row.get("recipe_id", "")) for row in recipes}
    recipe_keys = {str(row.get("recipe_key", "")) for row in recipes}
    ingredients = _select_related_rows(ingredients_all, recipe_ids, recipe_keys)
    nutrition = _select_related_rows(nutrition_all, recipe_ids, recipe_keys)
    photos = _select_photo_copies(
        candidate_ids,
        photo_rows_all,
        photos_dir=_manifest_photos_dir(manifest),
        data_dir=data_dir,
    )
    target_files = [
        data_dir / "curated_recipes.json",
        data_dir / "curated_recipe_ingredients.json",
        data_dir / "curated_recipe_nutrition.json",
        *[destination for _, destination in photos],
    ]
    for target in target_files:
        _ensure_inside(data_dir, target, "target path escapes data-dir")

    plan = ApplyPlan(
        run_dir=run_dir,
        data_dir=data_dir,
        approved_by=approval["approved_by"],
        candidate_ids=candidate_ids,
        write=write,
        recipes=len(recipes),
        ingredients=len(ingredients),
        nutrition=len(nutrition),
        photos=len(photos),
        target_files=target_files,
    )
    return _PreparedApply(plan, recipes, ingredients, nutrition, photos)


def _load_approval(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "approval.json"
    if not path.exists():
        raise ApplyError(f"missing required approval marker: {path}")
    data = _read_json_object(path)
    approved_by = str(data.get("approved_by", "")).strip()
    candidate_ids = data.get("candidate_ids")
    if not approved_by:
        raise ApplyError("approval.json requires approved_by")
    if not isinstance(candidate_ids, list) or not candidate_ids:
        raise ApplyError("approval.json requires non-empty candidate_ids")
    normalized = [str(candidate_id).strip() for candidate_id in candidate_ids]
    if any(not candidate_id for candidate_id in normalized):
        raise ApplyError("approval.json candidate_ids must be non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ApplyError("approval.json candidate_ids must be unique")
    return {
        **data,
        "approved_by": approved_by,
        "candidate_ids": normalized,
    }


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "manifest.json"
    if not path.exists():
        raise ApplyError(f"missing required manifest: {path}")
    return _read_json_object(path)


def _verify_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ApplyError("manifest.json requires non-empty files")
    for entry in files:
        if not isinstance(entry, dict):
            raise ApplyError("manifest file entries must be objects")
        relative = str(entry.get("path", "")).strip()
        expected_hash = str(entry.get("sha256", "")).strip().lower()
        if not relative or not expected_hash:
            raise ApplyError("manifest file entries require path and sha256")
        path = _safe_run_path(run_dir, relative)
        if not path.exists():
            raise ApplyError(f"manifest file is missing: {relative}")
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise ApplyError(f"manifest hash mismatch for {relative}")


def _require_production_rows(run_dir: Path, manifest: dict[str, Any], production_dir: Path) -> None:
    if not production_dir.is_dir():
        raise ApplyError("production_rows missing")
    manifest_paths = {
        str(entry.get("path", "")).replace("\\", "/")
        for entry in manifest.get("files", [])
        if isinstance(entry, dict)
    }
    required = {
        "production_rows/curated_recipes.json",
        "production_rows/curated_recipe_ingredients.json",
        "production_rows/curated_recipe_nutrition.json",
        "production_rows/photo_manifest.csv",
    }
    missing_from_manifest = required - manifest_paths
    if missing_from_manifest:
        missing = ", ".join(sorted(missing_from_manifest))
        raise ApplyError(f"production_rows stale or incomplete in manifest: {missing}")
    for relative in required:
        _safe_run_path(run_dir, relative)


def _load_classifications(path: Path) -> dict[str, str]:
    rows = _read_csv(path)
    classifications: dict[str, str] = {}
    for row in rows:
        candidate_id = row.get("candidate_id", "").strip()
        if candidate_id:
            classifications[candidate_id] = row.get("classification", "").strip()
    if not classifications:
        raise ApplyError("classification.csv has no candidate rows")
    return classifications


def _verify_candidate_classifications(
    candidate_ids: list[str],
    classifications: dict[str, str],
    approval: dict[str, Any],
) -> None:
    allow_all = bool(approval.get("allow_non_import_ready"))
    allow_list_value = approval.get("allow_non_import_ready_candidate_ids", [])
    allow_list = {
        str(candidate_id).strip()
        for candidate_id in allow_list_value
        if str(candidate_id).strip()
    } if isinstance(allow_list_value, list) else set()
    for candidate_id in candidate_ids:
        classification = classifications.get(candidate_id)
        if classification is None:
            raise ApplyError(f"approved candidate {candidate_id} missing from classification.csv")
        if classification != "import_ready" and not allow_all and candidate_id not in allow_list:
            raise ApplyError(
                f"approved candidate {candidate_id} is not import_ready: {classification}"
            )


def _select_recipes(
    candidate_ids: list[str],
    recipes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_candidate = {
        _recipe_candidate_id(row): row
        for row in recipes
        if _recipe_candidate_id(row)
    }
    selected = []
    for candidate_id in candidate_ids:
        row = by_candidate.get(candidate_id)
        if row is None:
            raise ApplyError(f"approved candidate {candidate_id} missing from curated_recipes.json")
        selected.append(row)
    return selected


def _select_related_rows(
    rows: list[dict[str, Any]],
    recipe_ids: set[str],
    recipe_keys: set[str],
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("recipe_id", "")) in recipe_ids
        or str(row.get("recipe_key", "")) in recipe_keys
    ]


def _select_photo_copies(
    candidate_ids: list[str],
    photo_rows: list[dict[str, str]],
    *,
    photos_dir: Path,
    data_dir: Path,
) -> list[tuple[Path, Path]]:
    rows_by_candidate = {row.get("candidate_id", "").strip(): row for row in photo_rows}
    copies: list[tuple[Path, Path]] = []
    for candidate_id in candidate_ids:
        row = rows_by_candidate.get(candidate_id)
        if row is None:
            raise ApplyError(f"approved candidate {candidate_id} missing from photo_manifest.csv")
        source = _source_photo_path(photos_dir, row.get("source_photo_path", ""))
        if not source.exists():
            raise ApplyError(f"source photo missing for {candidate_id}: {source}")
        destination = _target_photo_path(data_dir, row.get("target_photo_path", ""))
        copies.append((source, destination))
    return copies


def _source_photo_path(photos_dir: Path, source_photo_path: str) -> Path:
    relative = _relative_path(source_photo_path, "source photo path escapes photos_dir")
    source = photos_dir / relative
    _ensure_inside(photos_dir, source, "source photo path escapes photos_dir")
    return source


def _target_photo_path(data_dir: Path, target_photo_path: str) -> Path:
    normalized = target_photo_path.replace("\\", "/").strip()
    prefix = "src/diet_bot/data/"
    if normalized.startswith(prefix):
        normalized = normalized[len(prefix):]
    relative = _relative_path(normalized, "target path escapes data-dir")
    target = data_dir / relative
    _ensure_inside(data_dir, target, "target path escapes data-dir")
    return target


def _relative_path(value: str, error: str) -> Path:
    if not value.strip():
        raise ApplyError(error)
    path = Path(value)
    if path.is_absolute():
        raise ApplyError(error)
    if any(part == ".." for part in path.parts):
        raise ApplyError(error)
    return path


def _safe_run_path(run_dir: Path, relative: str) -> Path:
    path = _relative_path(relative, "manifest path escapes run directory")
    full_path = run_dir / path
    _ensure_inside(run_dir, full_path, "manifest path escapes run directory")
    return full_path


def _manifest_photos_dir(manifest: dict[str, Any]) -> Path:
    photos_dir = str(manifest.get("photos_dir", "")).strip()
    if not photos_dir:
        raise ApplyError("manifest.json requires photos_dir for photo copy")
    return Path(photos_dir)


def _recipe_candidate_id(row: dict[str, Any]) -> str:
    metadata = row.get("import_metadata")
    if isinstance(metadata, dict):
        candidate_id = metadata.get("candidate_id")
        if candidate_id:
            return str(candidate_id)
    candidate_id = row.get("candidate_id")
    return str(candidate_id) if candidate_id else ""


def _write_prepared(prepared: _PreparedApply) -> None:
    data_dir = prepared.plan.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_json(data_dir / "curated_recipes.json", prepared.recipes)
    _write_json(data_dir / "curated_recipe_ingredients.json", prepared.ingredients)
    _write_json(data_dir / "curated_recipe_nutrition.json", prepared.nutrition)
    for source, destination in prepared.photos:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ApplyError(f"expected JSON object: {path}")
    return data


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ApplyError(f"expected JSON list: {path}")
    rows: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            raise ApplyError(f"expected JSON object rows: {path}")
        rows.append(row)
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ApplyError(f"missing required file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_inside(root: Path, path: Path, error: str) -> None:
    root_resolved = root.resolve(strict=False)
    path_resolved = path.resolve(strict=False)
    try:
        common = os.path.commonpath([str(root_resolved), str(path_resolved)])
    except ValueError as exc:
        raise ApplyError(error) from exc
    if common != str(root_resolved):
        raise ApplyError(error)
