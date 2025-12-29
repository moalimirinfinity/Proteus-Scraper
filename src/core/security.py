from __future__ import annotations

import ipaddress
import asyncio
import socket
from typing import Iterable
from urllib.parse import urlparse

from core.config import settings


class SecurityError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _parse_domain_list(value: str | None) -> list[str]:
    if not value:
        return []
    items = [item.strip().lower() for item in value.split(",")]
    return [item for item in items if item]


def _domain_matches(host: str, pattern: str) -> bool:
    host = host.lower().rstrip(".")
    pattern = pattern.lower().rstrip(".")
    if pattern == "*":
        return True
    if pattern.startswith("*."):
        base = pattern[2:]
        return host == base or host.endswith(f".{base}")
    return host == pattern


def _host_is_denied(host: str) -> bool:
    denylist = _parse_domain_list(settings.ssrf_denylist_domains)
    return any(_domain_matches(host, entry) for entry in denylist)


def _host_is_allowed(host: str) -> bool:
    allowlist = _parse_domain_list(settings.ssrf_allowlist_domains)
    if not allowlist:
        return True
    return any(_domain_matches(host, entry) for entry in allowlist)


def _strip_ipv6_zone(host: str) -> str:
    if "%" not in host:
        return host
    return host.split("%", 1)[0]


def _is_local_hostname(host: str) -> bool:
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"}:
        return True
    return lowered.endswith((".local", ".localhost", ".internal"))


def _ip_is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_reserved or ip.is_unspecified:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return True
    return False


async def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    addresses: list[ipaddress._BaseAddress] = []
    for entry in infos:
        sockaddr = entry[4]
        if not sockaddr:
            continue
        ip = sockaddr[0]
        if not ip:
            continue
        try:
            addresses.append(ipaddress.ip_address(ip))
        except ValueError:
            continue
    return addresses


def _deny_reason_for_host(host: str) -> str | None:
    if _host_is_denied(host):
        return "domain_denied"
    if not _host_is_allowed(host):
        return "domain_not_allowed"
    if settings.ssrf_allow_private_ips:
        return None
    if _is_local_hostname(host):
        return "ssrf_blocked"
    return None


async def ensure_url_allowed(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SecurityError("invalid_scheme")
    if parsed.username or parsed.password:
        raise SecurityError("invalid_url")
    host = parsed.hostname
    if not host:
        raise SecurityError("invalid_url")
    host = _strip_ipv6_zone(host)

    host_reason = _deny_reason_for_host(host)
    if host_reason:
        raise SecurityError(host_reason)

    try:
        ip = ipaddress.ip_address(host)
        ips: Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address] = [ip]
    except ValueError:
        try:
            ips = await _resolve_host_ips(host)
        except socket.gaierror as exc:
            raise SecurityError("dns_failed") from exc

    if settings.ssrf_allow_private_ips:
        return
    if not ips:
        raise SecurityError("dns_failed")
    if any(_ip_is_private(entry) for entry in ips):
        raise SecurityError("ssrf_blocked")
