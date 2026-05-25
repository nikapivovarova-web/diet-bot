from __future__ import annotations

from collections.abc import Mapping

from diet_bot import payment_recovery_replay as impl


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    return impl.main(argv, env)


if __name__ == "__main__":
    raise SystemExit(main())
