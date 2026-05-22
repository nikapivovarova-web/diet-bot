from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence

from .runtime_config import (
    load_runtime_config,
    validate_startup,
    validate_strict_production,
)


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check diet bot runtime configuration.")
    parser.add_argument(
        "--strict-production",
        action="store_true",
        help="include opt-in production readiness checks",
    )
    args = parser.parse_args(argv)

    source = os.environ if env is None else env
    strict = args.strict_production or _strict_from_env(source)
    mode = "strict-production" if strict else "startup"

    config = load_runtime_config(source)
    issues = list(validate_startup(config))
    if strict:
        issues.extend(validate_strict_production(config))

    print("runtime config healthcheck")
    print(f"mode={mode}")
    print(json.dumps(config.safe_summary(), ensure_ascii=False, indent=2, sort_keys=True))
    if issues:
        print("issues:")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("issues: none")

    return 1 if issues else 0


def _strict_from_env(env: Mapping[str, str]) -> bool:
    return env.get("DIET_BOT_HEALTHCHECK_STRICT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


if __name__ == "__main__":
    raise SystemExit(main())
