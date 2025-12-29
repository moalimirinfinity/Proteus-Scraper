from __future__ import annotations

from core.config import settings
from core.governance import extract_domain


def is_stealth_allowed(url: str | None) -> bool:
    if not settings.stealth_enabled:
        return False
    allowlist = _parse_allowlist(settings.stealth_allowed_domains)
    if not allowlist:
        return True
    domain = extract_domain(url or "")
    if not domain:
        return False
    return any(_domain_matches(domain, entry) for entry in allowlist)


def _parse_allowlist(value: str | None) -> list[str]:
    if not value:
        return []
    items = [item.strip().lower() for item in value.split(",")]
    return [item for item in items if item]


def _domain_matches(domain: str, entry: str) -> bool:
    if domain == entry:
        return True
    return domain.endswith(f".{entry}")
