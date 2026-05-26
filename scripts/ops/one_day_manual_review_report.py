from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from diet_bot.ops import one_day_manual_review_report as impl


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    return impl.main(argv, env)


if __name__ == "__main__":
    raise SystemExit(main())
