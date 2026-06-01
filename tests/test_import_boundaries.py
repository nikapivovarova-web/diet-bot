from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "diet_bot"


def _local_import_edges(module_name: str) -> set[str]:
    path = PACKAGE_ROOT / f"{module_name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    edges: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported = _module_from_import_from(node)
            if imported:
                edges.add(imported)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported = _module_from_import_name(alias.name)
                if imported:
                    edges.add(imported)
    return edges


def _module_from_import_from(node: ast.ImportFrom) -> str | None:
    if node.level == 1 and node.module:
        return _known_local_module(node.module.split(".", 1)[0])
    if node.level == 0 and node.module and node.module.startswith("diet_bot."):
        return _known_local_module(node.module.removeprefix("diet_bot.").split(".", 1)[0])
    return None


def _module_from_import_name(name: str) -> str | None:
    if not name.startswith("diet_bot."):
        return None
    return _known_local_module(name.removeprefix("diet_bot.").split(".", 1)[0])


def _known_local_module(module_name: str) -> str | None:
    if (PACKAGE_ROOT / f"{module_name}.py").exists():
        return module_name
    return None


def test_core_modules_do_not_keep_medium_3_two_way_import_cycles() -> None:
    checked_pairs = (
        ("recipe_catalog", "curated_data"),
        ("entitlement_storage", "subscriptions"),
    )
    modules = {module for pair in checked_pairs for module in pair}
    edges = {module: _local_import_edges(module) for module in modules}

    cycles = [
        f"{left} <-> {right}"
        for left, right in checked_pairs
        if right in edges[left] and left in edges[right]
    ]

    assert cycles == []
