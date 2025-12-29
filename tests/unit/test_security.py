import ipaddress
import pytest

from core import security
from core.config import settings


@pytest.mark.asyncio
async def test_ssrf_blocks_private_ip(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ssrf_allow_private_ips", False)
    monkeypatch.setattr(settings, "ssrf_allowlist_domains", None)
    monkeypatch.setattr(settings, "ssrf_denylist_domains", None)
    with pytest.raises(security.SecurityError) as excinfo:
        await security.ensure_url_allowed("http://127.0.0.1")
    assert excinfo.value.code == "ssrf_blocked"


@pytest.mark.asyncio
async def test_ssrf_allows_public_ip(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ssrf_allow_private_ips", False)
    monkeypatch.setattr(settings, "ssrf_allowlist_domains", None)
    monkeypatch.setattr(settings, "ssrf_denylist_domains", None)
    await security.ensure_url_allowed("https://93.184.216.34")


@pytest.mark.asyncio
async def test_allowlist_enforced(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ssrf_allow_private_ips", False)
    monkeypatch.setattr(settings, "ssrf_allowlist_domains", "example.com")
    monkeypatch.setattr(settings, "ssrf_denylist_domains", None)

    async def fake_resolve(host: str):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(security, "_resolve_host_ips", fake_resolve)
    await security.ensure_url_allowed("https://example.com")
    with pytest.raises(security.SecurityError) as excinfo:
        await security.ensure_url_allowed("https://other.com")
    assert excinfo.value.code == "domain_not_allowed"


@pytest.mark.asyncio
async def test_denylist_overrides_allowlist(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ssrf_allow_private_ips", False)
    monkeypatch.setattr(settings, "ssrf_allowlist_domains", "example.com")
    monkeypatch.setattr(settings, "ssrf_denylist_domains", "example.com")

    async def fake_resolve(host: str):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(security, "_resolve_host_ips", fake_resolve)
    with pytest.raises(security.SecurityError) as excinfo:
        await security.ensure_url_allowed("https://example.com")
    assert excinfo.value.code == "domain_denied"
