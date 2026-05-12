from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


PRODUCTION_ENV_NAMES = frozenset({"prod", "production"})


class RuntimeConfigError(RuntimeError):
    """Raised when startup configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    bot_token: str
    telegram_provider_token: str
    support_chat_id: int | None
    admin_user_ids: frozenset[int]
    tester_chat_ids: frozenset[int]
    state_file: Path
    subscriptions_state_file: Path
    promo_codes_state_file: Path
    local_json_storage_allowed: bool


def load_runtime_config(environ: Mapping[str, str] | None = None) -> RuntimeConfig:
    env = os.environ if environ is None else environ
    environment = _env_value(env, "DIET_BOT_ENV") or "development"
    bot_token = _first_non_blank(env, "DIET_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise RuntimeConfigError("Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN.")

    if is_production_environment(environment):
        raise RuntimeConfigError(
            "DIET_BOT_ENV=production requires durable production storage; "
            "durable production storage is not implemented in this clean runtime phase."
        )

    default_state_file = Path(__file__).resolve().parents[2] / ".diet_bot_state" / "history.json"
    state_file = _path_from_env(env, "DIET_BOT_STATE_FILE", default_state_file)
    subscriptions_state_file = _path_from_env(
        env,
        "DIET_BOT_SUBSCRIPTIONS_STATE_FILE",
        state_file.with_name("subscriptions.json"),
    )
    promo_codes_state_file = _path_from_env(
        env,
        "DIET_BOT_PROMO_CODES_STATE_FILE",
        state_file.with_name("promo_codes.json"),
    )

    return RuntimeConfig(
        environment=environment.strip(),
        bot_token=bot_token,
        telegram_provider_token=_env_value(env, "TELEGRAM_PROVIDER_TOKEN"),
        support_chat_id=_parse_optional_int(_env_value(env, "DIET_BOT_SUPPORT_CHAT_ID")),
        admin_user_ids=_parse_id_set(_env_value(env, "DIET_BOT_ADMIN_USER_IDS")),
        tester_chat_ids=_parse_id_set(_env_value(env, "DIET_BOT_TESTER_CHAT_IDS")),
        state_file=state_file,
        subscriptions_state_file=subscriptions_state_file,
        promo_codes_state_file=promo_codes_state_file,
        local_json_storage_allowed=True,
    )


def is_production_environment(environment: str | None) -> bool:
    return (environment or "").strip().lower() in PRODUCTION_ENV_NAMES


def _first_non_blank(env: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = _env_value(env, name)
        if value:
            return value
    return ""


def _env_value(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _path_from_env(env: Mapping[str, str], name: str, default: Path) -> Path:
    value = _env_value(env, name)
    if not value:
        return default
    return Path(value)


def _parse_id_set(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for item in re.split(r"[\s,;]+", raw):
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            continue
    return frozenset(ids)


def _parse_optional_int(raw: str) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
