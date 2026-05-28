from __future__ import annotations

import re


_URL_CREDENTIALS_PATTERN = re.compile(
    r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)(?P<credentials>[^@\s/]+@)"
)
_QUOTED_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<key_quote>[\"'])(?P<key>[A-Za-z][A-Za-z0-9_-]*)(?P=key_quote)"
    r"(?P<sep>\s*:\s*)"
    r"(?P<value_quote>[\"'])(?P<value>(?:\\.|(?!(?P=value_quote)).)*?)(?P=value_quote)",
    re.IGNORECASE,
)
_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?P<key>[A-Za-z][A-Za-z0-9_-]*)(?P<sep>\s*(?:=|:(?!//))\s*)"
    r"(?:(?P<quote>[\"'])(?P<quoted>.*?)(?P=quote)|(?P<unquoted>[^\s,;]+))",
    re.IGNORECASE,
)
_TELEGRAM_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])\d{6,12}:[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"
)
_OPAQUE_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?=[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-]))"
    r"(?=[A-Za-z0-9_-]*[A-Za-z])"
    r"(?=[A-Za-z0-9_-]*\d)"
    r"[A-Za-z0-9_-]{32,}"
    r"(?![A-Za-z0-9_-])"
)
_RAW_IDENTIFIER_PATTERN = re.compile(r"(?<![A-Za-z0-9])-?\d{5,}(?![A-Za-z0-9])")
_SENSITIVE_ASSIGNMENT_PARTS = frozenset({"key", "password", "secret", "token"})
_SENSITIVE_QUOTED_ASSIGNMENT_KEYS = frozenset({"database_url", "dsn"})


def redact_manual_review_text(value: object | None) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    text = _QUOTED_ASSIGNMENT_PATTERN.sub(_redact_sensitive_quoted_assignment, text)
    text = _URL_CREDENTIALS_PATTERN.sub(r"\g<scheme><redacted:credentials>@", text)
    text = _ASSIGNMENT_PATTERN.sub(_redact_sensitive_assignment, text)
    text = _TELEGRAM_TOKEN_PATTERN.sub("<redacted:token>", text)
    text = _OPAQUE_TOKEN_PATTERN.sub("<redacted:token>", text)
    return _RAW_IDENTIFIER_PATTERN.sub("<redacted:number>", text)


def _redact_sensitive_quoted_assignment(match: re.Match[str]) -> str:
    key = match.group("key")
    if not _is_sensitive_quoted_assignment_key(key):
        return match.group(0)
    return (
        f"{match.group('key_quote')}{key}{match.group('key_quote')}"
        f"{match.group('sep')}{match.group('value_quote')}<redacted:secret>{match.group('value_quote')}"
    )


def _redact_sensitive_assignment(match: re.Match[str]) -> str:
    key = match.group("key")
    if not _is_sensitive_assignment_key(key):
        return match.group(0)
    return f"{key}{match.group('sep')}<redacted:secret>"


def _is_sensitive_quoted_assignment_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SENSITIVE_QUOTED_ASSIGNMENT_KEYS or _is_sensitive_assignment_key(key)


def _is_sensitive_assignment_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized == "api_key":
        return True
    return any(part in _SENSITIVE_ASSIGNMENT_PARTS for part in normalized.split("_"))
