from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from pathlib import PurePosixPath

from .analytics import DEFAULT_POSTHOG_HOST
from .runtime_config import (
    is_production_environment,
    parse_support_chat_id,
    validate_bot_token,
    validate_database_url,
    validate_posthog_host,
    validate_privacy_policy_url,
    validate_production_runtime_config,
    validate_support_chat_id,
)

Bot = None

REQUIRED_DATA_FILES = (
    "curated_foods.json",
    "curated_recipes.json",
    "curated_recipe_ingredients.json",
    "curated_recipe_nutrition.json",
    "welcome_foodbalance.png",
    "foodbalance_pdf_logo.png",
    "foodbalance_pdf_qr.png",
)
POLLING_HEARTBEAT_FILE_ENV = "DIET_BOT_POLLING_HEARTBEAT_FILE"
POLLING_HEARTBEAT_MAX_AGE_ENV = "DIET_BOT_POLLING_HEARTBEAT_MAX_AGE_SECONDS"
DEFAULT_POLLING_HEARTBEAT_FILE = "/tmp/diet_bot_polling_heartbeat.json"
DEFAULT_POLLING_HEARTBEAT_MAX_AGE_SECONDS = 90


def _bot_token() -> str:
    return (os.getenv("DIET_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def _database_url() -> str:
    return os.getenv("DIET_BOT_DATABASE_URL", "").strip()


def _environment() -> str:
    return os.getenv("DIET_BOT_ENV", os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development"))).strip().lower()


def _support_chat_id() -> str:
    return os.getenv("DIET_BOT_SUPPORT_CHAT_ID", "").strip()


def _privacy_policy_url() -> str:
    return os.getenv("DIET_BOT_PRIVACY_POLICY_URL", "").strip()


def _posthog_api_key() -> str:
    return os.getenv("POSTHOG_API_KEY", "").strip()


def _posthog_host() -> str:
    return os.getenv("POSTHOG_HOST", DEFAULT_POSTHOG_HOST).strip() or DEFAULT_POSTHOG_HOST


def _json_storage_allowed() -> bool:
    return os.getenv("DIET_BOT_ALLOW_JSON_STORAGE", "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_positive_int(raw: str | None, default: int) -> int:
    try:
        value = int((raw or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _polling_heartbeat_path() -> Path:
    return Path(os.getenv(POLLING_HEARTBEAT_FILE_ENV, DEFAULT_POLLING_HEARTBEAT_FILE))


def _polling_heartbeat_max_age_seconds() -> int:
    return _parse_positive_int(
        os.getenv(POLLING_HEARTBEAT_MAX_AGE_ENV),
        DEFAULT_POLLING_HEARTBEAT_MAX_AGE_SECONDS,
    )


def _check_token() -> list[str]:
    return validate_bot_token(_bot_token())


def _check_environment(strict: bool) -> list[str]:
    if strict and not is_production_environment(_environment()):
        return ["DIET_BOT_ENV must be production when running strict healthcheck."]
    return []


def _check_runtime_config(strict: bool) -> list[str]:
    if strict:
        errors: list[str] = []
        errors.extend(validate_support_chat_id(_support_chat_id(), required=True))
        errors.extend(validate_privacy_policy_url(_privacy_policy_url(), required=True))
        if _posthog_api_key():
            errors.extend(validate_posthog_host(_posthog_host(), required=True))
        return errors

    return validate_production_runtime_config(
        environment=_environment(),
        support_chat_id=_support_chat_id(),
        privacy_policy_url=_privacy_policy_url(),
        posthog_api_key=_posthog_api_key(),
        posthog_host=_posthog_host(),
    )


def _check_database(strict: bool, *, connect: bool = True) -> list[str]:
    database_url = _database_url()
    if not database_url:
        if strict:
            return ["DIET_BOT_DATABASE_URL is required in strict mode."]
        if _json_storage_allowed():
            return []
        return ["Set DIET_BOT_DATABASE_URL or DIET_BOT_ALLOW_JSON_STORAGE=1 for local JSON storage."]

    validation_errors = validate_database_url(database_url)
    if validation_errors:
        return validation_errors

    if not connect:
        return []

    try:
        import psycopg

        with psycopg.connect(database_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - healthcheck must translate all failures to exit code 1.
        return [f"Postgres connection check failed ({exc.__class__.__name__})."]

    return []


def _parse_heartbeat_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _check_polling_liveness(max_age_seconds: int) -> list[str]:
    path = _polling_heartbeat_path()
    if not path.is_file():
        return [f"Polling heartbeat file is missing: {path}."]

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - healthcheck must translate all failures to exit code 1.
        return [f"Polling heartbeat file is unreadable ({exc.__class__.__name__})."]

    if not isinstance(payload, dict):
        return ["Polling heartbeat file must contain a JSON object."]
    state = str(payload.get("state", "")).strip().lower()
    if state != "polling":
        return [f"Polling heartbeat state is {state or 'missing'}, expected polling."]

    updated_at = _parse_heartbeat_timestamp(payload.get("updated_at"))
    if updated_at is None:
        return ["Polling heartbeat updated_at is missing or invalid."]
    age_seconds = (datetime.now(UTC) - updated_at).total_seconds()
    if age_seconds > max_age_seconds:
        return [
            "Polling heartbeat is stale "
            f"({age_seconds:.0f}s old, max {max_age_seconds}s)."
        ]
    if age_seconds < -10:
        return ["Polling heartbeat timestamp is too far in the future."]

    pid = payload.get("pid")
    if sys.platform != "win32" and isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return [f"Polling heartbeat process is not running (pid {pid})."]
        except PermissionError:
            pass
        except OSError as exc:
            return [f"Polling heartbeat process check failed ({exc.__class__.__name__})."]

    return []


def _data_file_exists(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False

    resource = files("diet_bot").joinpath("data")
    for part in path.parts:
        resource = resource.joinpath(part)
    return resource.is_file()


def _check_package_data() -> list[str]:
    errors = [
        f"Package data file missing: data/{name}."
        for name in REQUIRED_DATA_FILES
        if not _data_file_exists(name)
    ]
    if errors:
        return errors

    try:
        from .curated_data import curated_foods, curated_recipes

        foods = curated_foods()
        recipes = curated_recipes()
    except Exception as exc:  # noqa: BLE001 - healthcheck must report package-data failures.
        return [f"Package data check failed ({exc.__class__.__name__})."]

    if not foods:
        errors.append("Package data check failed: curated foods are empty.")
    if not recipes:
        errors.append("Package data check failed: curated recipes are empty.")

    missing_images = sorted(
        {
            str(recipe.image_url)
            for recipe in recipes
            if recipe.image_url and not _data_file_exists(str(recipe.image_url))
        }
    )
    if missing_images:
        preview = ", ".join(f"data/{path}" for path in missing_images[:3])
        suffix = f" and {len(missing_images) - 3} more" if len(missing_images) > 3 else ""
        errors.append(f"Package recipe photos missing: {preview}{suffix}.")

    return errors


def _check_pre_payment_buttons() -> list[str]:
    try:
        from . import telegram_app
    except Exception as exc:  # noqa: BLE001 - healthcheck must report import failures.
        return [f"Pre-payment button smoke failed ({exc.__class__.__name__})."]

    previous_privacy_url = telegram_app.PRIVACY_POLICY_URL
    try:
        telegram_app.PRIVACY_POLICY_URL = _privacy_policy_url()
        keyboards = {
            "start": telegram_app._start_keyboard(),
            "subscription": telegram_app._subscription_payment_keyboard(),
        }
    finally:
        telegram_app.PRIVACY_POLICY_URL = previous_privacy_url

    errors: list[str] = []
    for name, keyboard in keyboards.items():
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        has_support = any(button.callback_data == telegram_app.CALLBACK_SUPPORT for button in buttons)
        has_privacy_url = any(button.url == _privacy_policy_url() for button in buttons)
        if not has_support:
            errors.append(f"{name} buttons must include support callback before payment.")
        if not has_privacy_url:
            errors.append(f"{name} buttons must include the public privacy policy URL before payment.")
    return errors


async def _check_telegram_api(*, check_support_chat: bool = False) -> list[str]:
    token = _bot_token()
    if not token:
        return []

    bot_class = Bot
    if bot_class is None:
        try:
            from aiogram import Bot as bot_class
        except Exception as exc:  # noqa: BLE001 - healthcheck must report missing Telegram runtime.
            return [f"Telegram API check unavailable ({exc.__class__.__name__})."]

    bot = None
    try:
        bot = bot_class(token)
        try:
            await bot.get_me()
        except Exception as exc:  # noqa: BLE001 - healthcheck must translate all failures to exit code 1.
            return [f"Telegram getMe check failed ({exc.__class__.__name__})."]
        if check_support_chat:
            support_chat_id = parse_support_chat_id(_support_chat_id())
            if support_chat_id is not None:
                try:
                    await bot.get_chat(support_chat_id)
                except Exception as exc:  # noqa: BLE001 - healthcheck must translate all failures to exit code 1.
                    return [f"Telegram support chat check failed ({exc.__class__.__name__})."]
    finally:
        if bot is not None:
            await bot.session.close()

    return []


def _run_async_check(coro):
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    return asyncio.run(coro)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check Telegram diet bot runtime prerequisites.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require production prerequisites, including DIET_BOT_DATABASE_URL.",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Call Telegram getMe to verify the bot token. Disabled by default.",
    )
    parser.add_argument(
        "--package-data-only",
        action="store_true",
        help="Only verify packaged data files. Useful during image builds.",
    )
    parser.add_argument(
        "--polling-liveness",
        action="store_true",
        help="Verify the local polling heartbeat file. Does not call Telegram.",
    )
    parser.add_argument(
        "--polling-max-age-seconds",
        type=int,
        default=None,
        help="Maximum allowed polling heartbeat age. Defaults to DIET_BOT_POLLING_HEARTBEAT_MAX_AGE_SECONDS or 90.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    errors = []
    errors.extend(_check_package_data())
    if not args.package_data_only:
        errors.extend(_check_environment(strict=args.strict))
        errors.extend(_check_token())
        errors.extend(_check_runtime_config(strict=args.strict))
        errors.extend(_check_database(strict=args.strict, connect=not errors))
    if args.strict and not args.package_data_only and not errors:
        errors.extend(_check_pre_payment_buttons())
    if args.polling_liveness and not args.package_data_only:
        max_age_seconds = (
            args.polling_max_age_seconds
            if args.polling_max_age_seconds and args.polling_max_age_seconds > 0
            else _polling_heartbeat_max_age_seconds()
        )
        errors.extend(_check_polling_liveness(max_age_seconds))
    if args.telegram and not args.package_data_only:
        errors.extend(_run_async_check(_check_telegram_api(check_support_chat=args.strict)))

    if errors:
        for error in errors:
            print(f"healthcheck: {error}", file=sys.stderr)
        return 1

    print("healthcheck: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
