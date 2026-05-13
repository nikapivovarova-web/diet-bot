from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from importlib import import_module
from importlib.resources import files
from pathlib import PurePosixPath

from .postgres_store import PostgresDietBotStore
from .runtime_config import RuntimeConfig, RuntimeConfigError, is_production_environment, load_runtime_config


REQUIRED_DATA_FILES = (
    "curated_foods.json",
    "curated_recipes.json",
    "curated_recipe_ingredients.json",
    "curated_recipe_nutrition.json",
    "foodbalance_pdf_logo.png",
    "foodbalance_pdf_qr.png",
    "welcome_foodbalance.png",
)
HEALTHCHECK_LOCAL_TOKEN = "healthcheck-local-token"


def check_package_import() -> list[str]:
    try:
        import_module("diet_bot")
    except Exception as exc:  # noqa: BLE001 - healthcheck must translate import failures.
        return [f"Package import failed ({exc.__class__.__name__})."]
    return []


def check_package_data(required_files: Sequence[str] = REQUIRED_DATA_FILES) -> list[str]:
    try:
        data_root = files("diet_bot").joinpath("data")
    except Exception as exc:  # noqa: BLE001 - healthcheck must translate resource failures.
        return [f"Package data check failed ({exc.__class__.__name__})."]

    if not data_root.is_dir():
        return []

    errors: list[str] = []
    for relative_path in required_files:
        path = PurePosixPath(relative_path)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            errors.append(f"Invalid package data path: data/{relative_path}.")
            continue

        resource = data_root
        for part in path.parts:
            resource = resource.joinpath(part)
        if not resource.is_file():
            errors.append(f"Package data file missing: data/{relative_path}.")
    return errors


def check_runtime_config(environ: Mapping[str, str] | None = None) -> list[str]:
    _config, errors = _load_checked_runtime_config(environ)
    return errors


def check_postgres(config: RuntimeConfig) -> list[str]:
    if not config.database_url:
        if is_production_environment(config.environment):
            return ["Set DIET_BOT_DATABASE_URL for production durable storage."]
        return []

    try:
        store = PostgresDietBotStore(
            config.database_url,
            statement_timeout_ms=config.postgres_statement_timeout_ms,
            lock_timeout_ms=config.postgres_lock_timeout_ms,
        )
        store.healthcheck()
    except Exception as exc:  # noqa: BLE001 - healthcheck must translate DB failures.
        return [f"PostgreSQL healthcheck failed ({exc.__class__.__name__})."]
    return []


def run_healthcheck(
    *,
    package_data_only: bool = False,
    strict: bool = False,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
    errors.extend(check_package_import())
    errors.extend(check_package_data())
    if not package_data_only:
        config, config_errors = _load_checked_runtime_config(environ)
        errors.extend(config_errors)
        if strict and config is not None:
            errors.extend(check_postgres(config))
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check FoodBalance local runtime readiness.")
    parser.add_argument(
        "--package-data-only",
        action="store_true",
        help="Only verify package import and bundled data files.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Verify strict runtime dependencies such as PostgreSQL when configured.",
    )
    args = parser.parse_args(argv)

    errors = run_healthcheck(package_data_only=args.package_data_only, strict=args.strict)
    if errors:
        for error in errors:
            print(f"healthcheck: {error}", file=sys.stderr)
        return 1

    print("healthcheck: ok")
    return 0


def _load_checked_runtime_config(
    environ: Mapping[str, str] | None,
) -> tuple[RuntimeConfig | None, list[str]]:
    try:
        return load_runtime_config(_runtime_config_environ(environ)), []
    except RuntimeConfigError as exc:
        return None, [str(exc)]
    except Exception as exc:  # noqa: BLE001 - healthcheck must translate config failures.
        return None, [f"Runtime config check failed ({exc.__class__.__name__})."]


def _runtime_config_environ(environ: Mapping[str, str] | None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    healthcheck_env = {key: value for key, value in source.items()}
    if not _env_value(healthcheck_env, "DIET_BOT_TOKEN") and not _env_value(
        healthcheck_env,
        "TELEGRAM_BOT_TOKEN",
    ):
        healthcheck_env["DIET_BOT_TOKEN"] = HEALTHCHECK_LOCAL_TOKEN
    if not _env_value(healthcheck_env, "DIET_BOT_ENV"):
        healthcheck_env["DIET_BOT_ENV"] = "development"
    return healthcheck_env


def _env_value(environ: Mapping[str, str], name: str) -> str:
    return (environ.get(name) or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
