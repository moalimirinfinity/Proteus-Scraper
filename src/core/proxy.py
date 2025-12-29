from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from core.config import settings
from core.db import async_session
from core.db_sync import get_sync_session
from core.governance import extract_domain
from core.models import ProxyPolicy


@dataclass(frozen=True)
class ProxyDecision:
    mode: str
    proxy_url: str | None
    source: str


async def resolve_proxy_async(url: str) -> ProxyDecision:
    domain = extract_domain(url)
    if not domain:
        return _default_proxy()

    async with async_session() as session:
        result = await session.execute(
            select(ProxyPolicy)
            .where(ProxyPolicy.domain == domain)
            .where(ProxyPolicy.enabled.is_(True))
        )
        policy = result.scalar_one_or_none()
        if policy is None:
            return _default_proxy()
        return _policy_to_decision(policy)


def resolve_proxy_sync(url: str) -> ProxyDecision:
    domain = extract_domain(url)
    if not domain:
        return _default_proxy()

    with get_sync_session() as session:
        result = session.execute(
            select(ProxyPolicy)
            .where(ProxyPolicy.domain == domain)
            .where(ProxyPolicy.enabled.is_(True))
        )
        policy = result.scalar_one_or_none()
        if policy is None:
            return _default_proxy()
        return _policy_to_decision(policy)


def _policy_to_decision(policy: ProxyPolicy) -> ProxyDecision:
    mode = (policy.mode or "gateway").lower()
    if mode == "direct":
        return ProxyDecision(mode="direct", proxy_url=None, source="policy")
    if mode == "custom":
        return ProxyDecision(mode="custom", proxy_url=policy.proxy_url, source="policy")
    if settings.proxy_gateway_url:
        return ProxyDecision(mode="gateway", proxy_url=settings.proxy_gateway_url, source="policy")
    return ProxyDecision(mode="direct", proxy_url=None, source="policy")


def _default_proxy() -> ProxyDecision:
    mode = (settings.proxy_default_mode or "direct").lower()
    if mode == "gateway" and settings.proxy_gateway_url:
        return ProxyDecision(mode="gateway", proxy_url=settings.proxy_gateway_url, source="default")
    return ProxyDecision(mode="direct", proxy_url=None, source="default")
