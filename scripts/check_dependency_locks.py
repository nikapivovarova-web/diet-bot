from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PIN_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)==([^;\s]+)")


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = PIN_RE.match(line)
        if not match:
            continue
        name = normalize_name(match.group(1))
        version = match.group(2)
        existing = pins.get(name)
        if existing is not None and existing != version:
            raise ValueError(
                f"{path}:{line_number}: duplicate pin for {name}: {existing} and {version}"
            )
        pins[name] = version
    return pins


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare committed pip-tools locks with freshly compiled locks by "
            "package/version while allowing explicitly listed platform-only pins."
        )
    )
    parser.add_argument("committed_lock", type=Path)
    parser.add_argument("compiled_lock", type=Path)
    parser.add_argument(
        "--allow-extra",
        action="append",
        default=[],
        help="Package name allowed in the committed lock when absent from this platform.",
    )
    args = parser.parse_args()

    committed = read_pins(args.committed_lock)
    compiled = read_pins(args.compiled_lock)
    allowed_extra = {normalize_name(name) for name in args.allow_extra}

    errors: list[str] = []

    for name, version in sorted(compiled.items()):
        committed_version = committed.get(name)
        if committed_version is None:
            errors.append(f"{args.committed_lock}: missing {name}=={version}")
        elif committed_version != version:
            errors.append(
                f"{args.committed_lock}: {name} is {committed_version}, expected {version}"
            )

    for name, version in sorted(committed.items()):
        if name not in compiled and name not in allowed_extra:
            errors.append(
                f"{args.committed_lock}: extra {name}=={version} not present in compiled lock"
            )

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
