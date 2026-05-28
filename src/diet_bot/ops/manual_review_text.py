from __future__ import annotations

import re


_RAW_IDENTIFIER_PATTERN = re.compile(r"(?<![A-Za-z0-9])-?\d{5,}(?![A-Za-z0-9])")


def redact_manual_review_text(value: object | None) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    return _RAW_IDENTIFIER_PATTERN.sub("<redacted:number>", text)
