from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_LEGACY_PY_SCRIPTS = (
    "apply_editorial_notes.py",
    "apply_generated_rebuild_photos.py",
    "apply_grid_generated_photos.py",
    "combine_fixed_400.py",
    "image_map.py",
    "list_rebuilt_titles.py",
    "make_photo_contact_sheet.py",
    "make_photo_final_contact_sheet.py",
    "make_rebuild_photo_contact_sheets.py",
    "make_rebuild_target_contact_sheet.py",
    "polish_final_text.py",
    "rebuild_400_from_original_photos.py",
    "repair_workbook_open_view.py",
    "replace_replaced_recipe_photos.py",
    "restore_final_hyperlinks.py",
    "scale_recipes_1_200.py",
    "verify_photo_workbook_integrity.py",
    "verify_rebuilt_workbook.py",
)
ROOT_LEGACY_MJS_SCRIPTS = (
    "analyze_recipes.mjs",
    "compare_recipe_workbooks.mjs",
    "extract_notes.mjs",
    "final_check.mjs",
    "inspect_recipes.mjs",
    "list_recipe_titles.mjs",
    "render_photo_workbook_checks.mjs",
    "verify_final_400.mjs",
    "verify_recipes.mjs",
)
ROOT_LEGACY_SCRIPTS = ROOT_LEGACY_PY_SCRIPTS + ROOT_LEGACY_MJS_SCRIPTS
LOCAL_PATH_PATTERNS = (
    "C:\\Users",
    "C:/Users",
    "Documents\\New project 2",
    "Documents/New project 2",
)


def test_root_legacy_scripts_do_not_hard_code_local_workbook_paths() -> None:
    for script_name in ROOT_LEGACY_SCRIPTS:
        source = (REPO_ROOT / script_name).read_text(encoding="utf-8")

        for pattern in LOCAL_PATH_PATTERNS:
            assert pattern not in source


@pytest.mark.parametrize("script_name", ROOT_LEGACY_PY_SCRIPTS)
def test_python_root_legacy_scripts_require_explicit_paths(script_name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / script_name)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "usage:" in combined_output.lower()
    for pattern in LOCAL_PATH_PATTERNS:
        assert pattern not in combined_output


@pytest.mark.parametrize("script_name", ROOT_LEGACY_MJS_SCRIPTS)
def test_node_root_legacy_scripts_require_explicit_paths(script_name: str) -> None:
    result = subprocess.run(
        ["node", str(REPO_ROOT / script_name)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "usage:" in combined_output.lower()
    for pattern in LOCAL_PATH_PATTERNS:
        assert pattern not in combined_output
