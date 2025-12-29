from __future__ import annotations

import re
from typing import Mapping

from selectolax.parser import HTMLParser

from scraper.parsing import SelectorSpec

_TITLE_PATTERNS = [
    r"access denied",
    r"attention required",
    r"just a moment",
    r"verify you are human",
    r"are you human",
    r"robot check",
    r"unusual traffic",
    r"request blocked",
    r"temporarily unavailable",
    r"service unavailable",
    r"forbidden",
]

_URL_PATTERNS = [
    r"captcha",
    r"challenge",
    r"verify",
    r"blocked",
    r"denied",
    r"unusual-traffic",
    r"access-denied",
]

_CAPTCHA_PATTERNS = [
    r"g-recaptcha",
    r"hcaptcha",
    r"recaptcha",
    r"turnstile",
    r"captcha",
]

_SCRIPT_PATTERNS = [
    r"cf-chl",
    r"challenge-platform",
    r"datadome",
    r"perimeterx",
    r"distil",
    r"incapsula",
]

_HEADER_KEYS = {
    "cf-mitigated",
    "cf-chl-bypass",
    "cf-chl-out",
    "x-sucuri-block",
    "x-distil-cs",
    "x-datadome",
}

_HEADER_VALUE_PATTERNS = [
    r"captcha",
    r"challenge",
    r"blocked",
    r"bot",
    r"verify",
]


def detect_blocked_response(
    status: int | None,
    headers: Mapping[str, str] | None,
    url: str | None,
    html: str | None,
) -> str | None:
    if status in {403, 429}:
        return f"http_{status}"

    if url and _matches_any(url, _URL_PATTERNS):
        return "blocked_url"

    title = _extract_title(html or "")
    if title and _matches_any(title, _TITLE_PATTERNS):
        return "blocked_title"

    if html:
        if _matches_any(html, _CAPTCHA_PATTERNS):
            return "captcha_detected"
        if _matches_any(html, _SCRIPT_PATTERNS):
            return "challenge_script"

    if headers and _headers_suspicious(headers):
        return "blocked_header"

    return None


def detect_empty_parse(
    status: int | None,
    data: dict | None,
    selectors: list[SelectorSpec],
    errors: list[str] | None = None,
) -> str | None:
    if status not in {None, 200}:
        return None
    if not _has_required_fields(selectors):
        return None
    if errors and "parsel_unavailable" in errors:
        return None
    if not data or not _data_has_value(data):
        return "empty_parse"
    return None


def _matches_any(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


def _extract_title(html: str) -> str | None:
    if not html:
        return None
    tree = HTMLParser(html)
    node = tree.css_first("title")
    if node is None:
        return None
    value = node.text(strip=True)
    return value or None


def _headers_suspicious(headers: Mapping[str, str]) -> bool:
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    for key, value in lowered.items():
        if key in _HEADER_KEYS:
            return True
        if _matches_any(value, _HEADER_VALUE_PATTERNS):
            return True
    return False


def _has_required_fields(selectors: list[SelectorSpec]) -> bool:
    return any(spec.required for spec in selectors)


def _data_has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_data_has_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_data_has_value(item) for item in value)
    return True
